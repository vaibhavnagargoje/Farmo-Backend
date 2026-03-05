from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import State, District, Tahsil, Village, UserLocation
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
    Manage the authenticated user's saved location via UserLocation model.
    GET  – return saved lat/lng/address
    POST – update lat/lng/address
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the user's saved location."""
        loc = getattr(request.user, "location", None)

        if not loc or not loc.latitude or not loc.longitude:
            return Response({
                "has_location": False,
                "location": None
            }, status=status.HTTP_200_OK)

        return Response({
            "has_location": True,
            "location": {
                "latitude": str(loc.latitude),
                "longitude": str(loc.longitude),
                "address": loc.address or "",
            }
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Update the user's saved location."""
        serializer = LocationUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Get or create UserLocation for this user
        loc, _created = UserLocation.objects.get_or_create(user=request.user)

        loc.latitude = data["latitude"]
        loc.longitude = data["longitude"]
        loc.address = data.get("address", "")
        loc.save()

        return Response({
            "message": "Location updated successfully",
            "location": {
                "latitude": str(loc.latitude),
                "longitude": str(loc.longitude),
                "address": loc.address or "",
            }
        }, status=status.HTTP_200_OK)
