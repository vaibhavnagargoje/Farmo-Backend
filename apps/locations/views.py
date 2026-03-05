from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import UserLocation
from .serializers import LocationUpdateSerializer


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
