# apps/bookings/views.py
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Booking
from .serializers import (
    BookingListSerializer,
    BookingDetailSerializer,
    BookingCreateSerializer,
    BookingStatusUpdateSerializer,
    BookingCancelSerializer
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
