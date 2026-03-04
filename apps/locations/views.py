from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import State, District, Tahsil,Village
from .serializers import (
    StateSerializer,
    DistrictSerializer,
    TahsilSerializer,
    VillageSerializer,
    LocationUpdateSerializer,
)


class StateListView(APIView):
    """List all states. Public endpoint."""
    permission_classes = []

    def get(self, request):
        states = State.objects.all()
        serializer = StateSerializer(states, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DistrictListView(APIView):
    """List districts. Optional filter: ?state_id=<id>. Public endpoint."""
    permission_classes = []

    def get(self, request):
        queryset = District.objects.select_related('state').all()
        state_id = request.query_params.get('state_id')
        if state_id:
            queryset = queryset.filter(state_id=state_id)
        serializer = DistrictSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TahsilListView(APIView):
    """List tahsils. Optional filter: ?district_id=<id>. Public endpoint."""
    permission_classes = []

    def get(self, request):
        queryset = Tahsil.objects.select_related('district').all()
        district_id = request.query_params.get('district_id')
        if district_id:
            queryset = queryset.filter(district_id=district_id)
        serializer = TahsilSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class VillageListView(APIView):
    """List villages. Optional filter: ?tahsil_id=<id>. Public endpoint."""
    permission_classes = []

    def get(self, request):
        queryset = Village.objects.select_related('tahasil').all()
        tahsil_id = request.query_params.get('tahsil_id')
        if tahsil_id:
            queryset = queryset.filter(tahasil_id=tahsil_id)
        serializer = VillageSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class UserLocationView(APIView):
    """
    Manage the authenticated user's saved location on CustomerProfile.
    GET  – return saved lat/lng/address
    POST – update lat/lng/address
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the user's saved location."""
        profile = getattr(request.user, "customer_profile", None)

        if not profile or not profile.latitude or not profile.longitude:
            return Response({
                "has_location": False,
                "location": None
            }, status=status.HTTP_200_OK)

        return Response({
            "has_location": True,
            "location": {
                "latitude": str(profile.latitude),
                "longitude": str(profile.longitude),
                "address": profile.user_address or "",
            }
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Update the user's saved location."""
        serializer = LocationUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        profile = getattr(request.user, "customer_profile", None)

        # Auto-create CustomerProfile if it doesn't exist yet
        if not profile:
            from apps.users.models import CustomerProfile
            profile = CustomerProfile.objects.create(user=request.user)

        profile.latitude = data["latitude"]
        profile.longitude = data["longitude"]
        profile.user_address = data.get("address", "")
        profile.save()

        return Response({
            "message": "Location updated successfully",
            "location": {
                "latitude": str(profile.latitude),
                "longitude": str(profile.longitude),
                "address": profile.user_address or "",
            }
        }, status=status.HTTP_200_OK)
