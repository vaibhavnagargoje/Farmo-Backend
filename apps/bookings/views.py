# apps/bookings/views.py
from datetime import timedelta

from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction

from .models import Booking, BookingOffer, ProviderContact
from .serializers import (
    LEGACY_BOOKING_TYPE,
    BookingListSerializer,
    BookingDetailSerializer,
    BookingCreateSerializer,
    BookingStatusUpdateSerializer,
    BookingCancelSerializer,
    BookingOfferSerializer,
    ProviderContactCreateSerializer,
    ProviderContactOutcomeSerializer,
    ProviderContactSerializer,
    PartnerContactSerializer,
)


# --- Customer Booking Views ---
class CustomerBookingListView(generics.ListAPIView):
    """
    GET: List all bookings for the logged-in customer.
    POST: Legacy. Older app versions post the "Find yourself" call here after
    the customer says the provider agreed. It is recorded as an agreed
    ProviderContact, not a booking.
    """
    serializer_class = BookingListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(customer=self.request.user).order_by('-created_at')

    def post(self, request, *args, **kwargs):
        data = request.data.copy()
        data['outcome'] = ProviderContact.Outcome.AGREED
        serializer = ProviderContactCreateSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            contact = serializer.save()
            return Response({
                "message": "Thanks! We have noted that you found this provider.",
                "booking": None,
                "contact_id": contact.id,
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
    POST: Start or complete an assigned booking.
    (Providers accept a booking through its offer: provider/instant-requests/<id>/accept/.)
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

            if action == 'start':
                # Serializer already rejects 'start' in SINGLE mode — safe to proceed
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


# --- Booking through Farmo ---
class BookingCreateView(APIView):
    """
    POST: Create a booking through Farmo.
    Prices it for the location and broadcasts offers to nearby providers.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BookingCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            booking = serializer.save()
            nearby_count = booking.offers.count()
            return Response({
                "message": f"Booking created. Searching {nearby_count} nearby providers...",
                "booking": BookingDetailSerializer(booking, context={'request': request}).data,
                "providers_notified": nearby_count,
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BookingStatusView(APIView):
    """
    GET: Poll the status of a booking's provider search.
    Auto-expires if past expiry time.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, booking_id):
        booking = get_object_or_404(
            Booking,
            booking_id=booking_id,
            customer=request.user,
        )

        # Auto-expire if past expiry and still searching
        if booking.is_expired:
            booking.status = Booking.Status.EXPIRED
            booking.save(update_fields=['status'])
            # Also expire all pending offers
            booking.offers.filter(
                status=BookingOffer.Status.PENDING
            ).update(status=BookingOffer.Status.EXPIRED)

        data = {
            "booking_id": booking.booking_id,
            "order_number": booking.order_number,
            "status": booking.status,
            "booking_type": LEGACY_BOOKING_TYPE,  # Deprecated
            "category_name": booking.category.name if booking.category else None,
            "quantity": float(booking.quantity),
            "price_unit": booking.price_unit,
            "unit_price": str(booking.unit_price),
            "discount_amount": str(booking.discount_amount),
            "total_amount": str(booking.total_amount),
            "broadcast_count": booking.broadcast_count,
            "current_broadcast_radius": str(booking.current_broadcast_radius) if booking.current_broadcast_radius else None,
            "expires_at": booking.expires_at.isoformat() if booking.expires_at else None,
            "assigned_at": booking.assigned_at.isoformat() if booking.assigned_at else None,
            "created_at": booking.created_at.isoformat(),
            "providers_notified": booking.offers.count(),
            "providers_declined": booking.offers.filter(
                status=BookingOffer.Status.DECLINED
            ).count(),
        }

        # Include provider info if confirmed
        if booking.status == Booking.Status.CONFIRMED and booking.provider:
            data["provider"] = {
                "id": booking.provider.id,
                "full_name": getattr(booking.provider.user.customer_profile, 'full_name', '') if hasattr(booking.provider.user, 'customer_profile') else '',
                "rating": str(booking.provider.rating),
                "jobs_completed": booking.provider.jobs_completed,
                "phone": booking.provider.user.phone_number,
            }

        return Response(data)


# --- Provider Offer Views ---
class ProviderOfferListView(generics.ListAPIView):
    """
    GET: List all pending booking offers for the logged-in provider.
    Only shows offers whose booking is still SEARCHING (not expired/cancelled).
    """
    serializer_class = BookingOfferSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'partner_profile'):
            return BookingOffer.objects.none()

        partner = self.request.user.partner_profile

        # Auto-expire offers whose booking has passed its expiry
        now = timezone.now()
        BookingOffer.objects.filter(
            provider=partner,
            status=BookingOffer.Status.PENDING,
            booking__expires_at__lt=now,
            booking__status=Booking.Status.SEARCHING,
        ).update(status=BookingOffer.Status.EXPIRED, responded_at=now)

        return BookingOffer.objects.filter(
            provider=partner,
            status=BookingOffer.Status.PENDING,
            booking__status=Booking.Status.SEARCHING,
        ).select_related(
            'booking', 'booking__customer', 'booking__category', 'booking__service'
        ).order_by('distance_km', '-notified_at')


class ProviderOfferAcceptView(APIView):
    """
    POST: Provider accepts a booking offer.
    First-come-first-serve: uses select_for_update for atomicity.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        partner = request.user.partner_profile

        with transaction.atomic():
            # Lock the offer row
            try:
                offer = BookingOffer.objects.select_for_update().get(
                    pk=pk,
                    provider=partner,
                )
            except BookingOffer.DoesNotExist:
                return Response(
                    {"error": "Request not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check offer is still pending
            if offer.status != BookingOffer.Status.PENDING:
                return Response(
                    {"error": "This request has already been responded to."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Lock and check the booking
            booking = Booking.objects.select_for_update().get(pk=offer.booking_id)

            if booking.status != Booking.Status.SEARCHING:
                # Another provider already accepted or booking expired
                offer.status = BookingOffer.Status.EXPIRED
                offer.responded_at = timezone.now()
                offer.save(update_fields=['status', 'responded_at'])
                return Response(
                    {"error": "This booking is no longer available — another provider may have accepted it."},
                    status=status.HTTP_409_CONFLICT
                )

            # Accept: assign provider to booking
            booking.provider = partner
            booking.status = Booking.Status.CONFIRMED
            booking.assigned_at = timezone.now()
            booking.save()  # This triggers OTP generation in model save()

            # Mark this offer as accepted
            offer.status = BookingOffer.Status.ACCEPTED
            offer.responded_at = timezone.now()
            offer.save(update_fields=['status', 'responded_at'])

            # Expire all other pending offers for this booking
            BookingOffer.objects.filter(
                booking=booking,
                status=BookingOffer.Status.PENDING,
            ).exclude(pk=pk).update(
                status=BookingOffer.Status.EXPIRED,
                responded_at=timezone.now(),
            )

        # Return full booking details
        return Response({
            "message": "Booking accepted successfully!",
            "booking": BookingDetailSerializer(booking, context={'request': request}).data,
        })


class ProviderOfferDeclineView(APIView):
    """
    POST: Provider declines a booking offer.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        partner = request.user.partner_profile

        offer = get_object_or_404(
            BookingOffer,
            pk=pk,
            provider=partner,
        )

        if offer.status != BookingOffer.Status.PENDING:
            return Response(
                {"error": "This request has already been responded to."},
                status=status.HTTP_400_BAD_REQUEST
            )

        offer.status = BookingOffer.Status.DECLINED
        offer.responded_at = timezone.now()
        offer.save(update_fields=['status', 'responded_at'])

        return Response({"message": "Request declined."})


# --- Direct provider contacts ("Find yourself") ---
class ProviderContactCreateView(APIView):
    """
    POST: Record that the customer is calling a provider from a listing.
    The answer after the call is sent to the outcome endpoint.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ProviderContactCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            contact = serializer.save()
            return Response(ProviderContactSerializer(contact).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProviderContactOutcomeView(APIView):
    """
    POST: The customer's answer after the call: AGREED or NOT_AGREED.
    Can be given once; repeating the same answer is accepted.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = ProviderContactOutcomeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        outcome = serializer.validated_data['outcome']

        with transaction.atomic():
            contact = get_object_or_404(
                ProviderContact.objects.select_for_update(), pk=pk, customer=request.user,
            )
            if contact.outcome == outcome:
                return Response(ProviderContactSerializer(contact).data)
            if contact.outcome != ProviderContact.Outcome.CALLED:
                return Response(
                    {"error": "This call already has an answer."},
                    status=status.HTTP_409_CONFLICT,
                )
            contact.outcome = outcome
            contact.responded_at = timezone.now()
            contact.save(update_fields=['outcome', 'responded_at'])  # Signal notifies the provider on AGREED

        return Response(ProviderContactSerializer(contact).data)


class PartnerContactPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProviderContactListView(generics.ListAPIView):
    """
    GET: Farmers who found the logged-in partner on Farmo and agreed on work.
    ?days=N limits the list to the last N days.
    """
    serializer_class = PartnerContactSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PartnerContactPagination

    def get_queryset(self):
        if not hasattr(self.request.user, 'partner_profile'):
            return ProviderContact.objects.none()
        queryset = ProviderContact.objects.filter(
            provider=self.request.user.partner_profile,
            outcome=ProviderContact.Outcome.AGREED,
        ).select_related('customer__customer_profile', 'service', 'category').order_by('-created_at')

        days = self.request.query_params.get('days', '')
        if days.isdecimal() and int(days) > 0:
            queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=int(days)))
        return queryset


# --- App Settings (Public) ---
class AppSettingsView(APIView):
    """
    GET: Returns global app configuration including the current OTP mode.
    Public endpoint — no authentication required.
    Response: { "otp_mode": "SINGLE" | "DUAL" }
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from adminpanel.models import AppSettings
        settings_obj = AppSettings.get()
        return Response({
            "otp_mode": settings_obj.otp_mode,
        })
