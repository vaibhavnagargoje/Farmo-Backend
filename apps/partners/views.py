# apps/partners/views.py
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .models import PartnerProfile, LaborDetails, MachineryDetails, TransportDetails
from .serializers import (
    PartnerProfileSerializer,
    PartnerRegistrationSerializer,
    PartnerProfileUpdateSerializer,
    LaborDetailsSerializer,
    MachineryDetailsSerializer,
    TransportDetailsSerializer
)


class PartnerRegistrationView(APIView):
    """
    POST: Register as a new Partner.
    A logged-in Customer can become a Partner by submitting this form.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check if user already has a partner profile
        if hasattr(request.user, 'partner_profile'):
            return Response(
                {"error": "You are already registered as a Partner."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = PartnerRegistrationSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            partner = serializer.save()
            return Response({
                "message": "Partner registration successful. Awaiting KYC verification.",
                "partner": PartnerProfileSerializer(partner).data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PartnerProfileView(APIView):
    """
    GET: View own Partner Profile.
    PUT/PATCH: Update own Partner Profile.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        partner = get_object_or_404(PartnerProfile, user=request.user)
        serializer = PartnerProfileSerializer(partner)
        
        # Include nested details based on type
        data = serializer.data
        if partner.partner_type == PartnerProfile.PartnerType.LABOR:
            if hasattr(partner, 'labor_details'):
                data['labor_details'] = LaborDetailsSerializer(partner.labor_details).data
        elif partner.partner_type == PartnerProfile.PartnerType.MACHINERY_OWNER:
            if hasattr(partner, 'machinery_details'):
                data['machinery_details'] = MachineryDetailsSerializer(partner.machinery_details).data
        elif partner.partner_type == PartnerProfile.PartnerType.TRANSPORTER:
            if hasattr(partner, 'transport_details'):
                data['transport_details'] = TransportDetailsSerializer(partner.transport_details).data
        
        return Response(data)

    def patch(self, request):
        partner = get_object_or_404(PartnerProfile, user=request.user)
        serializer = PartnerProfileUpdateSerializer(partner, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Profile updated successfully.",
                "partner": PartnerProfileSerializer(partner).data
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PartnerPublicView(generics.RetrieveAPIView):
    """
    GET: Public view of a Partner's profile (for customers viewing a service provider).
    """
    queryset = PartnerProfile.objects.filter(is_verified=True)
    serializer_class = PartnerProfileSerializer
    permission_classes = []  # Public access
    lookup_field = 'id'


class PartnerDashboardView(APIView):
    """
    GET: Partner's dashboard stats (jobs, earnings overview).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        partner = get_object_or_404(PartnerProfile, user=request.user)
        
        # Get stats from related bookings
        from bookings.models import Booking
        
        total_bookings = partner.received_bookings.count()
        completed_jobs = partner.received_bookings.filter(status=Booking.Status.COMPLETED).count()
        pending_jobs = partner.received_bookings.filter(status=Booking.Status.PENDING).count()
        in_progress_jobs = partner.received_bookings.filter(status=Booking.Status.IN_PROGRESS).count()
        
        # Calculate total earnings from completed jobs
        from django.db.models import Sum
        total_earnings = partner.received_bookings.filter(
            status=Booking.Status.COMPLETED,
            payment_status=Booking.PaymentStatus.PAID
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        return Response({
            "business_name": partner.business_name,
            "is_verified": partner.is_verified,
            "rating": str(partner.rating),
            "stats": {
                "total_bookings": total_bookings,
                "completed_jobs": completed_jobs,
                "pending_jobs": pending_jobs,
                "in_progress_jobs": in_progress_jobs,
                "total_earnings": str(total_earnings)
            }
        })
