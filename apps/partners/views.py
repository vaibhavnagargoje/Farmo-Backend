# apps/partners/views.py
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db import transaction

from rest_framework import permissions
from .models import PartnerProfile, MachineryDetails, TransportDetails
from labor_services.models import LaborDetails
from .serializers import (
    PartnerProfileSerializer,
    PartnerRegistrationSerializer,
    PartnerProfileUpdateSerializer,
    LaborDetailsSerializer,
    MachineryDetailsSerializer,
    TransportDetailsSerializer,
    LaborDetailsUpdateSerializer,
)

User = get_user_model()


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
        service_type_ids = []
        partner_type = request.data.get('partner_type', '')
        if partner_type == 'LABOR':
            for key in ('daily_wage_estimate', 'is_migrant_worker'):
                val = request.data.get(key)
                if val is not None:
                    if key == 'is_migrant_worker':
                        val = str(val).lower() in ('true', '1')
                    labor_fields[key] = val
            # File field
            skill_photo = request.data.get('skill_card_photo')
            if skill_photo and hasattr(skill_photo, 'read'):
                labor_fields['skill_card_photo'] = skill_photo
            # Service type IDs (M2M)
            raw_ids = request.data.getlist('service_type_ids', [])
            if not raw_ids:
                ids_str = request.data.get('service_type_ids', '')
                if ids_str:
                    raw_ids = [x.strip() for x in str(ids_str).split(',') if x.strip()]
            try:
                service_type_ids = [int(x) for x in raw_ids]
            except (ValueError, TypeError):
                service_type_ids = []

        serializer = PartnerRegistrationSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            partner = serializer.save()

            # Create LaborDetails after partner profile exists
            if partner_type == 'LABOR' and labor_fields:
                labor = LaborDetails.objects.create(partner=partner, **labor_fields)
                if service_type_ids:
                    labor.service_types.set(service_type_ids)

            return Response({
                "message": "Partner registration successful. Awaiting KYC verification.",
                "partner": PartnerProfileSerializer(partner).data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PartnerOnboardOrAddServiceView(APIView):
    """
    POST: Unified endpoint for partner onboarding and service creation.
    
    Handles two scenarios in a single request:
    1. User is NOT yet a partner → creates PartnerProfile + service/labor details
    2. User IS already a partner → adds new service or updates labor details
    
    Request fields:
      - partner_type: 'MACHINERY' or 'LABOR' (required)
      
    For MACHINERY:
      - category: category ID (required)
      - title: service title (required)
      - description: service description (optional)
      - price: numeric price (required)
      - price_unit: HOUR/DAY/KM/ACRE/FIXED (optional, defaults to ACRE)
      - service_radius_km: integer (optional, defaults to 10)
      - images: image files (optional)
      
    For LABOR:
      - skills: comma-separated skills string (required)
      - daily_wage_estimate: numeric (required)
      - is_migrant_worker: bool (optional)
      - skill_card_photo: image file (optional)
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @transaction.atomic
    def post(self, request):
        user = request.user
        partner_type = request.data.get('partner_type', '').strip().upper()

        # ── Validate partner_type ──
        valid_types = [choice[0] for choice in PartnerProfile.PartnerType.choices]
        if partner_type not in valid_types:
            return Response(
                {"error": f"Invalid partner_type. Must be one of: {', '.join(valid_types)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Step 1: Ensure PartnerProfile exists ──
        is_new_partner = False
        try:
            partner = user.partner_profile
        except PartnerProfile.DoesNotExist:
            partner = PartnerProfile.objects.create(
                user=user,
                partner_type=partner_type,
            )
            user.role = User.Role.PARTNER
            user.save(update_fields=['role'])
            is_new_partner = True

        # ── Step 2: Handle based on partner_type ──
        service_created = False

        if partner_type == 'MACHINERY':
            # Validate required machinery/service fields
            category_id = request.data.get('category')
            title = request.data.get('title', '').strip()
            price = request.data.get('price')

            if not category_id:
                return Response({"error": "category is required for MACHINERY."}, status=status.HTTP_400_BAD_REQUEST)
            if not title:
                return Response({"error": "title is required for MACHINERY."}, status=status.HTTP_400_BAD_REQUEST)
            if not price:
                return Response({"error": "price is required for MACHINERY."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                price_val = float(price)
                if price_val <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                return Response({"error": "price must be a positive number."}, status=status.HTTP_400_BAD_REQUEST)

            # Verify category exists
            from services.models import Category, Service, ServiceImage
            try:
                cat = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                return Response({"error": "Invalid category ID."}, status=status.HTTP_400_BAD_REQUEST)

            # Create the Service
            description = request.data.get('description', '').strip()
            price_unit = request.data.get('price_unit', 'ACRE').strip().upper()
            service_radius = request.data.get('service_radius_km', 10)
            try:
                service_radius = int(service_radius)
            except (ValueError, TypeError):
                service_radius = 10

            service = Service.objects.create(
                partner=partner,
                category=cat,
                title=title,
                description=description,
                price=price_val,
                price_unit=price_unit,
                service_radius_km=service_radius,
                status=Service.Status.ACTIVE,
            )

            # Handle images
            images = request.FILES.getlist('images')
            for i, img_file in enumerate(images):
                ServiceImage.objects.create(
                    service=service,
                    image=img_file,
                    is_thumbnail=(i == 0),
                )

            service_created = True

        elif partner_type == 'LABOR':
            # Parse labor fields
            service_type_ids_raw = request.data.getlist('service_type_ids', [])
            # Also support comma-separated string fallback
            if not service_type_ids_raw:
                ids_str = request.data.get('service_type_ids', '')
                if ids_str:
                    service_type_ids_raw = [x.strip() for x in str(ids_str).split(',') if x.strip()]

            daily_wage = request.data.get('daily_wage_estimate')
            is_migrant = str(request.data.get('is_migrant_worker', 'false')).lower() in ('true', '1')
            skill_card = request.FILES.get('skill_card_photo')

            if not service_type_ids_raw:
                return Response({"error": "service_type_ids is required for LABOR."}, status=status.HTTP_400_BAD_REQUEST)
            if not daily_wage:
                return Response({"error": "daily_wage_estimate is required for LABOR."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                wage_val = float(daily_wage)
                if wage_val <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                return Response({"error": "daily_wage_estimate must be a positive number."}, status=status.HTTP_400_BAD_REQUEST)

            # Validate service type IDs
            from labor_services.models import LaborServiceType
            try:
                valid_ids = [int(x) for x in service_type_ids_raw]
            except (ValueError, TypeError):
                return Response({"error": "service_type_ids must be a list of integers."}, status=status.HTTP_400_BAD_REQUEST)

            existing_types = LaborServiceType.objects.filter(id__in=valid_ids, is_active=True)
            if existing_types.count() != len(valid_ids):
                return Response({"error": "One or more service_type_ids are invalid."}, status=status.HTTP_400_BAD_REQUEST)

            # Ensure partner_type on profile is set to LABOR
            if partner.partner_type != PartnerProfile.PartnerType.LABOR:
                partner.partner_type = PartnerProfile.PartnerType.LABOR
                partner.save(update_fields=['partner_type'])

            # Create or update LaborDetails
            labor, created = LaborDetails.objects.get_or_create(
                partner=partner,
                defaults={
                    'daily_wage_estimate': wage_val,
                    'is_migrant_worker': is_migrant,
                }
            )
            if not created:
                labor.daily_wage_estimate = wage_val
                labor.is_migrant_worker = is_migrant
                labor.save(update_fields=['daily_wage_estimate', 'is_migrant_worker'])

            # Set M2M service types
            labor.service_types.set(valid_ids)

            if skill_card and hasattr(skill_card, 'read'):
                labor.skill_card_photo = skill_card
                labor.save(update_fields=['skill_card_photo'])

        # ── Step 3: Build response ──
        partner.refresh_from_db()
        response_data = {
            "message": "Partner onboarding successful." if is_new_partner else "Service added successfully.",
            "is_new_partner": is_new_partner,
            "service_created": service_created,
            "partner": PartnerProfileSerializer(partner, context={'request': request}).data,
        }

        return Response(response_data, status=status.HTTP_201_CREATED if is_new_partner else status.HTTP_200_OK)

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

        # Get all verified LABOR partners who have a location and are online
        labor_partners = PartnerProfile.objects.filter(
            partner_type=PartnerProfile.PartnerType.LABOR,
            is_verified=True,
            is_available=True,
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
                profile_pic_url = None
                try:
                    profile = partner.user.customer_profile
                    full_name = profile.full_name
                    if profile.profile_picture:
                        profile_pic_url = request.build_absolute_uri(profile.profile_picture.url)
                except Exception:
                    pass

                # Language for display
                lang = getattr(request.user, 'preferred_language', 'en') if request.user.is_authenticated else request.query_params.get('lang', 'en')
                from labor_services.serializers import LaborServiceTypeSerializer
                skills_list = LaborServiceTypeSerializer(labor.service_types.all(), many=True, context={'request': request}).data if labor else []

                results.append({
                    "id": partner.id,
                    "full_name": full_name or partner.user.phone_number,
                    "profile_picture": profile_pic_url,
                    "skills": skills_list,
                    "daily_wage_estimate": str(labor.daily_wage_estimate) if labor and labor.daily_wage_estimate else None,
                    "is_migrant_worker": labor.is_migrant_worker if labor else False,
                    "skill_card_photo": request.build_absolute_uri(labor.skill_card_photo.url) if labor and labor.skill_card_photo else None,
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




