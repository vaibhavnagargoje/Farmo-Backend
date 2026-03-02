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


# --- Instant Booking Views ---
class InstantBookingCreateView(APIView):
    """
    POST: Create an instant (quick) booking.
    Finds nearby providers, computes avg price, creates broadcast requests.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InstantBookingCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            booking = serializer.save()
            nearby_count = booking.instant_requests.count()
            return Response({
                "message": f"Instant booking created. Searching {nearby_count} nearby providers...",
                "booking": BookingDetailSerializer(booking, context={'request': request}).data,
                "providers_notified": nearby_count,
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InstantBookingStatusView(APIView):
    """
    GET: Poll the status of an instant booking.
    Auto-expires if past expiry time.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, booking_id):
        booking = get_object_or_404(
            Booking,
            booking_id=booking_id,
            customer=request.user,
            booking_type=Booking.BookingType.INSTANT,
        )

        # Auto-expire if past expiry and still searching
        if booking.is_expired:
            booking.status = Booking.Status.EXPIRED
            booking.save(update_fields=['status'])
            # Also expire all pending instant requests
            booking.instant_requests.filter(
                status=InstantBookingRequest.RequestStatus.PENDING
            ).update(status=InstantBookingRequest.RequestStatus.EXPIRED)

        data = {
            "booking_id": booking.booking_id,
            "order_number": booking.order_number,
            "status": booking.status,
            "booking_type": booking.booking_type,
            "category_name": booking.category.name if booking.category else None,
            "quantity": booking.quantity,
            "price_unit": booking.price_unit,
            "unit_price": str(booking.unit_price),
            "total_amount": str(booking.total_amount),
            "broadcast_count": booking.broadcast_count,
            "current_broadcast_radius": str(booking.current_broadcast_radius) if booking.current_broadcast_radius else None,
            "expires_at": booking.expires_at.isoformat() if booking.expires_at else None,
            "assigned_at": booking.assigned_at.isoformat() if booking.assigned_at else None,
            "created_at": booking.created_at.isoformat(),
            "providers_notified": booking.instant_requests.count(),
            "providers_declined": booking.instant_requests.filter(
                status=InstantBookingRequest.RequestStatus.DECLINED
            ).count(),
        }

        # Include provider info if confirmed
        if booking.status == Booking.Status.CONFIRMED and booking.provider:
            data["provider"] = {
                "id": booking.provider.id,
                "business_name": booking.provider.business_name,
                "rating": str(booking.provider.rating),
                "jobs_completed": booking.provider.jobs_completed,
                "phone": booking.provider.user.phone_number,
            }

        return Response(data)


# --- Provider Instant Request Views ---
class ProviderInstantRequestListView(generics.ListAPIView):
    """
    GET: List all pending instant booking requests for the logged-in provider.
    Only shows requests where booking is still SEARCHING (not expired/cancelled).
    """
    serializer_class = InstantBookingRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'partner_profile'):
            return InstantBookingRequest.objects.none()

        partner = self.request.user.partner_profile

        # Auto-expire requests whose booking has passed its expiry
        now = timezone.now()
        InstantBookingRequest.objects.filter(
            provider=partner,
            status=InstantBookingRequest.RequestStatus.PENDING,
            booking__expires_at__lt=now,
            booking__status=Booking.Status.SEARCHING,
        ).update(status=InstantBookingRequest.RequestStatus.EXPIRED, responded_at=now)

        return InstantBookingRequest.objects.filter(
            provider=partner,
            status=InstantBookingRequest.RequestStatus.PENDING,
            booking__status=Booking.Status.SEARCHING,
        ).select_related(
            'booking', 'booking__customer', 'booking__category', 'booking__service'
        ).order_by('distance_km', '-notified_at')


class ProviderInstantRequestAcceptView(APIView):
    """
    POST: Provider accepts an instant booking request.
    First-come-first-serve: uses select_for_update for atomicity.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        partner = request.user.partner_profile

        with transaction.atomic():
            # Lock the request row
            try:
                instant_req = InstantBookingRequest.objects.select_for_update().get(
                    pk=pk,
                    provider=partner,
                )
            except InstantBookingRequest.DoesNotExist:
                return Response(
                    {"error": "Request not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check request is still pending
            if instant_req.status != InstantBookingRequest.RequestStatus.PENDING:
                return Response(
                    {"error": "This request has already been responded to."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Lock and check the booking
            booking = Booking.objects.select_for_update().get(pk=instant_req.booking_id)

            if booking.status != Booking.Status.SEARCHING:
                # Another provider already accepted or booking expired
                instant_req.status = InstantBookingRequest.RequestStatus.EXPIRED
                instant_req.responded_at = timezone.now()
                instant_req.save(update_fields=['status', 'responded_at'])
                return Response(
                    {"error": "This booking is no longer available — another provider may have accepted it."},
                    status=status.HTTP_409_CONFLICT
                )

            # Accept: assign provider to booking
            booking.provider = partner
            booking.status = Booking.Status.CONFIRMED
            booking.assigned_at = timezone.now()
            booking.save()  # This triggers OTP generation in model save()

            # Mark this request as accepted
            instant_req.status = InstantBookingRequest.RequestStatus.ACCEPTED
            instant_req.responded_at = timezone.now()
            instant_req.save(update_fields=['status', 'responded_at'])

            # Expire all other pending requests for this booking
            InstantBookingRequest.objects.filter(
                booking=booking,
                status=InstantBookingRequest.RequestStatus.PENDING,
            ).exclude(pk=pk).update(
                status=InstantBookingRequest.RequestStatus.EXPIRED,
                responded_at=timezone.now(),
            )

        # Return full booking details
        return Response({
            "message": "Booking accepted successfully!",
            "booking": BookingDetailSerializer(booking, context={'request': request}).data,
        })


class ProviderInstantRequestDeclineView(APIView):
    """
    POST: Provider declines an instant booking request.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        partner = request.user.partner_profile

        instant_req = get_object_or_404(
            InstantBookingRequest,
            pk=pk,
            provider=partner,
        )

        if instant_req.status != InstantBookingRequest.RequestStatus.PENDING:
            return Response(
                {"error": "This request has already been responded to."},
                status=status.HTTP_400_BAD_REQUEST
            )

        instant_req.status = InstantBookingRequest.RequestStatus.DECLINED
        instant_req.responded_at = timezone.now()
        instant_req.save(update_fields=['status', 'responded_at'])

        return Response({"message": "Request declined."})
