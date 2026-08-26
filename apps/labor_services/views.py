from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Prefetch, Count
import math

from .models import LaborCategory, LaborServiceType
from .serializers import LaborCategorySerializer, LaborServiceTypeSerializer
from partners.models import PartnerProfile

class LaborCategoryListView(generics.ListAPIView):
    """
    GET /api/v1/labor/categories/
    Returns all active labor categories with nested service types.
    """
    permission_classes = [AllowAny]
    serializer_class = LaborCategorySerializer

    def get_queryset(self):
        # We can annotate worker count based on the related PartnerProfiles
        # For now we'll just return the categories and prefetch active service types
        return LaborCategory.objects.filter(is_active=True).prefetch_related(
            Prefetch('service_types', queryset=LaborServiceType.objects.filter(is_active=True))
        ).order_by('order', 'name')

class LaborServiceTypeListView(generics.ListAPIView):
    """
    GET /api/v1/labor/service-types/
    Returns all active service types.
    """
    permission_classes = [AllowAny]
    serializer_class = LaborServiceTypeSerializer
    queryset = LaborServiceType.objects.filter(is_active=True).order_by('order', 'name')

class NearbyLaborsByTypeView(APIView):
    """
    GET /api/v1/labor/nearby/?service_type_id=5&lat=18.5&lng=73.8&distance=10
    """
    permission_classes = [AllowAny]

    def get(self, request):
        service_type_id = request.query_params.get('service_type_id')
        category_id = request.query_params.get('category_id')
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')

        # Build base queryset for LABOR partners
        queryset = PartnerProfile.objects.filter(
            partner_type=PartnerProfile.PartnerType.LABOR,
            is_verified=True,
            is_available=True,
        ).select_related('user', 'labor_details')

        if service_type_id:
            queryset = queryset.filter(labor_details__service_types__id=service_type_id)
        elif category_id:
            queryset = queryset.filter(labor_details__service_types__category_id=category_id)

        # Remove duplicates if filtering by category matched multiple service types for same worker
        queryset = queryset.distinct()

        results = []
        user_lat = float(lat) if lat else None
        user_lng = float(lng) if lng else None

        for partner in queryset:
            dist = 9999.0
            
            # Distance Calculation
            if user_lat and user_lng:
                loc = getattr(partner.user, 'location', None)
                if loc and loc.latitude and loc.longitude:
                    p_lat = float(loc.latitude)
                    p_lng = float(loc.longitude)
                    
                    # Haversine
                    R = 6371
                    d_lat = math.radians(p_lat - user_lat)
                    d_lng = math.radians(p_lng - user_lng)
                    a = (math.sin(d_lat / 2) ** 2 +
                         math.cos(math.radians(user_lat)) *
                         math.cos(math.radians(p_lat)) *
                         math.sin(d_lng / 2) ** 2)
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    dist = R * c

            # Apply distance filter if provided
            distance_param = request.query_params.get('distance')
            if distance_param and user_lat and user_lng:
                try:
                    if dist > float(distance_param):
                        continue
                except ValueError:
                    pass

            labor = getattr(partner, 'labor_details', None)
            
            profile_pic_url = None
            full_name = partner.user.phone_number
            try:
                profile = partner.user.customer_profile
                full_name = profile.full_name
                if profile.profile_picture:
                    profile_pic_url = request.build_absolute_uri(profile.profile_picture.url)
            except Exception:
                pass

            lang = getattr(request.user, 'preferred_language', 'en') if request.user.is_authenticated else request.query_params.get('lang', 'en')
            skills_list = []
            if labor:
                # Use the new service_types mapping
                skills_list = LaborServiceTypeSerializer(labor.service_types.all(), many=True, context={'request': request}).data

            results.append({
                "id": partner.id,
                "full_name": full_name,
                "profile_picture": profile_pic_url,
                "skills": skills_list,
                "daily_wage_estimate": str(labor.daily_wage_estimate) if labor and labor.daily_wage_estimate else None,
                "is_migrant_worker": labor.is_migrant_worker if labor else False,
                "skill_card_photo": request.build_absolute_uri(labor.skill_card_photo.url) if labor and labor.skill_card_photo else None,
                "is_available": partner.is_available,
                "rating": str(partner.rating),
                "jobs_completed": partner.jobs_completed,
                "distance_km": round(dist, 1) if user_lat else None,
            })

        if user_lat:
            results.sort(key=lambda x: x["distance_km"])

        return Response({
            "results": results,
            "count": len(results)
        })
