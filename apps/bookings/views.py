# apps/bookings/views.py
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from django.db.models import F
import math

from .models import Booking, InstantBookingRequest
from services.models import Service, Category
from partners.models import PartnerProfile
from .serializers import (
    BookingListSerializer,
    BookingDetailSerializer,
    BookingCreateSerializer,
    BookingStatusUpdateSerializer,
    BookingCancelSerializer,
    InstantBookingCreateSerializer,
    InstantBookingAcceptSerializer,
    InstantBookingRequestSerializer,
)


# --- Customer Booking Views ---
class CustomerBookingListView(generics.ListCreateAPIView):
    """
    GET: List all bookings for the logged-in customer.
    POST: Create a new booking.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BookingCreateSerializer
        return BookingListSerializer

    def get_queryset(self):
        return Booking.objects.filter(customer=self.request.user).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            booking = serializer.save()
            return Response({
                "message": "Booking created successfully. Waiting for provider confirmation.",
                "booking": BookingDetailSerializer(booking, context={'request': request}).data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomerBookingDetailView(APIView):
    """
    GET: View details of a specific booking.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, booking_id):
        booking = get_object_or_404(Booking, booking_id=booking_id, customer=request.user)
        serializer = BookingDetailSerializer(booking, context={'request': request})
        return Response(serializer.data)


class CustomerBookingCancelView(APIView):
    """
    POST: Cancel a booking (by customer).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, booking_id):
        booking = get_object_or_404(Booking, booking_id=booking_id, customer=request.user)
        
        serializer = BookingCancelSerializer(data=request.data, context={'booking': booking})
        if serializer.is_valid():
            booking.status = Booking.Status.CANCELLED
            booking.cancellation_reason = serializer.validated_data['reason']
            booking.cancelled_by = request.user
            booking.save()
            
            return Response({
                "message": "Booking cancelled successfully.",
                "booking": BookingListSerializer(booking).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- Provider Booking Views ---
class ProviderBookingListView(generics.ListAPIView):
    """
    GET: List all bookings received by the logged-in partner.
    """
    serializer_class = BookingListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'partner_profile'):
            return Booking.objects.none()
        
        status_filter = self.request.query_params.get('status')
        queryset = Booking.objects.filter(
            provider=self.request.user.partner_profile
        ).order_by('-created_at')
        
        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())
        
        return queryset


class ProviderBookingDetailView(APIView):
    """
    GET: View details of a booking received.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, booking_id):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        booking = get_object_or_404(
            Booking,
            booking_id=booking_id,
            provider=request.user.partner_profile
        )
        serializer = BookingDetailSerializer(booking, context={'request': request})
        return Response(serializer.data)


class ProviderBookingActionView(APIView):
    """
    POST: Take action on a booking (accept/reject/start/complete).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, booking_id):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        booking = get_object_or_404(
            Booking,
            booking_id=booking_id,
            provider=request.user.partner_profile
        )
        
        serializer = BookingStatusUpdateSerializer(
            data=request.data,
            context={'booking': booking}
        )
        
        if serializer.is_valid():
            action = serializer.validated_data['action']
            
            if action == 'accept':
                booking.status = Booking.Status.CONFIRMED
                # OTPs are auto-generated in the model's save() method
                message = "Booking accepted."
            
            elif action == 'reject':
                booking.status = Booking.Status.REJECTED
                booking.cancellation_reason = serializer.validated_data.get('rejection_reason')
                booking.cancelled_by = request.user
                message = "Booking rejected."
            
            elif action == 'start':
                booking.status = Booking.Status.IN_PROGRESS
                booking.work_started_at = timezone.now()
                message = "Job started."
            
            elif action == 'complete':
                booking.status = Booking.Status.COMPLETED
                booking.work_completed_at = timezone.now()
                
                # Update partner stats
                partner = request.user.partner_profile
                partner.jobs_completed += 1
                partner.save()
                
                message = "Job completed successfully."
            
            booking.save()
            
            return Response({
                "message": message,
                "booking": BookingDetailSerializer(booking, context={'request': request}).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProviderBookingCancelView(APIView):
    """
    POST: Cancel a booking (by provider).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, booking_id):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        booking = get_object_or_404(
            Booking,
            booking_id=booking_id,
            provider=request.user.partner_profile
        )
        
        serializer = BookingCancelSerializer(data=request.data, context={'booking': booking})
        if serializer.is_valid():
            booking.status = Booking.Status.CANCELLED
            booking.cancellation_reason = serializer.validated_data['reason']
            booking.cancelled_by = request.user
            booking.save()
            
            return Response({
                "message": "Booking cancelled successfully.",
                "booking": BookingListSerializer(booking).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ==============================
# --- Instant Booking Views ---
# ==============================

def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in km."""
    R = 6371  # Earth radius in km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class InstantBookingCreateView(APIView):
    """
    POST: Customer creates an instant booking for a category.
    Broadcasts to nearby providers who serve that category.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InstantBookingCreateSerializer(
            data=request.data, context={'request': request}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        booking = serializer.save()
        customer_lat = float(request.data.get('latitude', 0))
        customer_lon = float(request.data.get('longitude', 0))
        radius = booking.category.instant_search_radius_km

        # Find nearby providers who serve this category
        provider_services = Service.objects.filter(
            category=booking.category,
            is_active=True,
            provider__is_verified=True,
            provider__is_available=True,
        ).select_related('provider', 'provider__user')

        requests_created = 0
        for svc in provider_services:
            partner = svc.provider
            if partner.latitude and partner.longitude:
                dist = haversine_km(
                    customer_lat, customer_lon,
                    float(partner.latitude), float(partner.longitude),
                )
                if dist <= radius:
                    InstantBookingRequest.objects.create(
                        booking=booking,
                        provider=partner,
                        distance_km=round(dist, 2),
                    )
                    requests_created += 1

        if requests_created == 0:
            booking.status = Booking.Status.EXPIRED
            booking.save()
            return Response(
                {"error": "No providers available nearby. Try again later."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "message": f"Booking created. Notifying {requests_created} nearby providers.",
                "booking": BookingDetailSerializer(booking, context={'request': request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class InstantBookingStatusView(APIView):
    """
    GET: Customer polls the status of their instant booking.
    Returns booking status + list of provider requests.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, booking_id):
        booking = get_object_or_404(
            Booking,
            booking_id=booking_id,
            customer=request.user,
            booking_type=Booking.BookingType.INSTANT,
        )

        # Auto-expire if timed out
        if booking.status == Booking.Status.SEARCHING and booking.is_expired:
            booking.status = Booking.Status.EXPIRED
            booking.save()
            InstantBookingRequest.objects.filter(
                booking=booking, status=InstantBookingRequest.Status.PENDING
            ).update(status=InstantBookingRequest.Status.EXPIRED)

        return Response(
            BookingDetailSerializer(booking, context={'request': request}).data
        )


class ProviderInstantBookingListView(generics.ListAPIView):
    """
    GET: Provider sees their pending instant booking requests.
    """
    serializer_class = InstantBookingRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'partner_profile'):
            return InstantBookingRequest.objects.none()

        return (
            InstantBookingRequest.objects.filter(
                provider=self.request.user.partner_profile,
                status=InstantBookingRequest.Status.PENDING,
                booking__status=Booking.Status.SEARCHING,
            )
            .select_related('booking', 'booking__customer', 'booking__category')
            .order_by('-notified_at')
        )


class ProviderInstantBookingAcceptView(APIView):
    """
    POST: Provider accepts an instant booking (first-come-first-serve).
    Uses select_for_update to prevent race conditions.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, booking_id):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        partner = request.user.partner_profile

        with transaction.atomic():
            booking = (
                Booking.objects.select_for_update()
                .filter(
                    booking_id=booking_id,
                    booking_type=Booking.BookingType.INSTANT,
                    status=Booking.Status.SEARCHING,
                )
                .first()
            )

            if not booking:
                return Response(
                    {"error": "Booking is no longer available."},
                    status=status.HTTP_409_CONFLICT,
                )

            if booking.is_expired:
                booking.status = Booking.Status.EXPIRED
                booking.save()
                return Response(
                    {"error": "Booking has expired."},
                    status=status.HTTP_410_GONE,
                )

            ibr = InstantBookingRequest.objects.filter(
                booking=booking,
                provider=partner,
                status=InstantBookingRequest.Status.PENDING,
            ).first()

            if not ibr:
                return Response(
                    {"error": "You do not have a pending request for this booking."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Assign the booking
            booking.provider = partner
            booking.status = Booking.Status.CONFIRMED
            booking.save()

            # Mark this request as accepted
            ibr.status = InstantBookingRequest.Status.ACCEPTED
            ibr.responded_at = timezone.now()
            ibr.save()

            # Expire all other pending requests
            InstantBookingRequest.objects.filter(
                booking=booking, status=InstantBookingRequest.Status.PENDING
            ).update(
                status=InstantBookingRequest.Status.EXPIRED,
                responded_at=timezone.now(),
            )

        return Response(
            {
                "message": "Booking accepted! Head to the customer location.",
                "booking": BookingDetailSerializer(booking, context={'request': request}).data,
            }
        )


class ProviderInstantBookingDeclineView(APIView):
    """
    POST: Provider declines an instant booking request.
    If all providers decline, the booking is expired.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, booking_id):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        partner = request.user.partner_profile

        ibr = get_object_or_404(
            InstantBookingRequest,
            booking__booking_id=booking_id,
            provider=partner,
            status=InstantBookingRequest.Status.PENDING,
        )

        ibr.status = InstantBookingRequest.Status.DECLINED
        ibr.responded_at = timezone.now()
        ibr.save()

        # Check if all providers have responded
        pending = InstantBookingRequest.objects.filter(
            booking=ibr.booking,
            status=InstantBookingRequest.Status.PENDING,
        ).count()

        if pending == 0:
            ibr.booking.status = Booking.Status.EXPIRED
            ibr.booking.save()
            msg = "Declined. No more providers available — booking expired."
        else:
            msg = f"Declined. {pending} provider(s) still pending."

        return Response({"message": msg})
