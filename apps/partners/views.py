# apps/partners/views.py
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404

from .models import PartnerProfile, LaborDetails, MachineryDetails, TransportDetails
from .serializers import (
    PartnerProfileSerializer,
    PartnerRegistrationSerializer,
    PartnerProfileUpdateSerializer,
    LaborDetailsSerializer,
    MachineryDetailsSerializer,
    TransportDetailsSerializer,
    LaborDetailsUpdateSerializer
)


class PartnerStatusView(APIView):
    """
    GET: Check if the current user is already a Partner.
    Returns partner info if exists, or user info if not.
    Used by frontend onboarding page to decide flow.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = getattr(user, 'customer_profile', None)

        # Fetch existing locations for this user
        locations = []
        loc = getattr(user, 'location', None)
        if loc and loc.address:
            locations.append({"address": loc.address})

        user_info = {
            "full_name": profile.full_name if profile else "",
            "phone_number": user.phone_number,
            "locations": locations,
        }
        try:
            partner = user.partner_profile
            return Response({
                "is_partner": True,
                "partner": PartnerProfileSerializer(partner).data,
                "user": user_info
            })
        except PartnerProfile.DoesNotExist:
            return Response({
                "is_partner": False,
                "partner": None,
                "user": user_info
            })


class PartnerRegistrationView(APIView):
    """
    POST: Register as a new Partner.
    A logged-in Customer can become a Partner by submitting this form.
    Accepts multipart/form-data for KYC file uploads.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        # Check if user already has a partner profile
        if hasattr(request.user, 'partner_profile'):
            return Response(
                {"error": "You are already registered as a Partner."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Extract labor-specific fields BEFORE passing to serializer.
        # QueryDict cannot hold nested dicts, so we handle LaborDetails
        # manually instead of going through the nested serializer.
        labor_fields = {}
        partner_type = request.data.get('partner_type', '')
        if partner_type == 'LABOR':
            for key in ('skills', 'daily_wage_estimate', 'is_migrant_worker'):
                val = request.data.get(key)
                if val is not None:
                    if key == 'is_migrant_worker':
                        val = str(val).lower() in ('true', '1')
                    labor_fields[key] = val
            # File field
            skill_photo = request.data.get('skill_card_photo')
            if skill_photo and hasattr(skill_photo, 'read'):
                labor_fields['skill_card_photo'] = skill_photo

        serializer = PartnerRegistrationSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            partner = serializer.save()

            # Create LaborDetails after partner profile exists
            if partner_type == 'LABOR' and labor_fields:
                LaborDetails.objects.create(partner=partner, **labor_fields)

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


class LaborDetailsView(APIView):
    """
    GET: Retrieve the authenticated partner's labor details.
    PATCH: Update labor details (multipart for skill_card_photo).
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        partner = get_object_or_404(PartnerProfile, user=request.user)
        if partner.partner_type != PartnerProfile.PartnerType.LABOR:
            return Response({"error": "Not a labor partner."}, status=status.HTTP_400_BAD_REQUEST)
        labor = getattr(partner, 'labor_details', None)
        if not labor:
            return Response({"labor_details": None})
        return Response({"labor_details": LaborDetailsSerializer(labor).data})

    def patch(self, request):
        partner = get_object_or_404(PartnerProfile, user=request.user)
        if partner.partner_type != PartnerProfile.PartnerType.LABOR:
            return Response({"error": "Not a labor partner."}, status=status.HTTP_400_BAD_REQUEST)

        labor, created = LaborDetails.objects.get_or_create(partner=partner)
        serializer = LaborDetailsUpdateSerializer(labor, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Labor details updated.",
                "labor_details": LaborDetailsSerializer(labor).data
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PartnerPublicView(generics.RetrieveAPIView):
    """
    GET: Public view of a Partner's profile (for customers viewing a service provider).
    Includes nested details (labor/machinery/transport) based on partner_type.
    """
    queryset = PartnerProfile.objects.filter(is_verified=True)
    serializer_class = PartnerProfileSerializer
    permission_classes = []  # Public access
    lookup_field = 'id'

    def retrieve(self, request, *args, **kwargs):
        partner = self.get_object()
        data = self.get_serializer(partner).data

        # Attach nested details based on type
        if partner.partner_type == PartnerProfile.PartnerType.LABOR:
            labor = getattr(partner, 'labor_details', None)
            if labor:
                data['labor_details'] = LaborDetailsSerializer(labor).data
        elif partner.partner_type == PartnerProfile.PartnerType.MACHINERY_OWNER:
            md = getattr(partner, 'machinery_details', None)
            if md:
                data['machinery_details'] = MachineryDetailsSerializer(md).data
        elif partner.partner_type == PartnerProfile.PartnerType.TRANSPORTER:
            td = getattr(partner, 'transport_details', None)
            if td:
                data['transport_details'] = TransportDetailsSerializer(td).data

        return Response(data)


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


class NearbyLaborsView(APIView):
    """
    GET: Public endpoint to list nearby LABOR partners.
    Query params: lat, lng, distance (km, default 5).
    Uses Haversine formula for distance calculation.
    """
    permission_classes = []  # Public access

    def get(self, request):
        import math
        from locations.models import UserLocation

        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        distance_km = float(request.query_params.get('distance', 5))

        if not lat or not lng:
            return Response(
                {"error": "lat and lng query params are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_lat = float(lat)
            user_lng = float(lng)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid lat/lng values."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get all verified LABOR partners who have a location
        labor_partners = PartnerProfile.objects.filter(
            partner_type=PartnerProfile.PartnerType.LABOR,
            is_verified=True,
        ).select_related('user')

        results = []
        for partner in labor_partners:
            # Get partner's location
            try:
                loc = UserLocation.objects.get(user=partner.user)
            except UserLocation.DoesNotExist:
                continue

            if not loc.latitude or not loc.longitude:
                continue

            p_lat = float(loc.latitude)
            p_lng = float(loc.longitude)

            # Haversine distance
            R = 6371  # Earth radius in km
            d_lat = math.radians(p_lat - user_lat)
            d_lng = math.radians(p_lng - user_lng)
            a = (math.sin(d_lat / 2) ** 2 +
                 math.cos(math.radians(user_lat)) *
                 math.cos(math.radians(p_lat)) *
                 math.sin(d_lng / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            dist = R * c

            if dist <= distance_km:
                # Get labor details
                labor = getattr(partner, 'labor_details', None)
                full_name = ''
                try:
                    full_name = partner.user.customer_profile.full_name
                except Exception:
                    pass

                results.append({
                    "id": partner.id,
                    "full_name": full_name or partner.user.phone_number,
                    "skills": labor.skills if labor else "",
                    "daily_wage_estimate": str(labor.daily_wage_estimate) if labor and labor.daily_wage_estimate else None,
                    "is_migrant_worker": labor.is_migrant_worker if labor else False,
                    "skill_card_photo": labor.skill_card_photo.url if labor and labor.skill_card_photo else None,
                    "is_available": partner.is_available,
                    "rating": str(partner.rating),
                    "jobs_completed": partner.jobs_completed,
                    "distance_km": round(dist, 1),
                })

        # Sort by distance
        results.sort(key=lambda x: x["distance_km"])

        return Response({
            "count": len(results),
            "distance_filter_km": distance_km,
            "results": results,
        })
