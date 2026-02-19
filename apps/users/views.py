from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import SendOTPSerializer, VerifyOTPSerializer, UserSerializer, ProfileUpdateSerializer, CustomerProfileSerializer, LocationUpdateSerializer
import random

User = get_user_model()

# --- MOCK STORAGE ---
# In production, use Redis or a Database Model to store OTPs with expiration.
OTP_STORAGE = {} 

class SendOTPView(APIView):
    """
    Endpoint to trigger an OTP SMS.
    Body: { "phone_number": "1234567890" }
    """
    permission_classes = [] # Allow anyone to request OTP

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone_number']
            
            # 1. Generate OTP
            otp = str(random.randint(1000, 9999))
            
            # 2. Store OTP (In memory for now)
            OTP_STORAGE[phone] = otp
            
            # 3. Send SMS (Mocked for existing code)
            print(f"--> SENT OTP {otp} to {phone}") 
            
            return Response({
                "message": "OTP sent successfully.",
                "debug_otp": otp # REMOVE THIS IN PRODUCTION
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifyOTPView(APIView):
    """
    Endpoint to verify OTP and return JWT Token.
    Body: { "phone_number": "1234567890", "otp": "1234" }
    """
    permission_classes = [] # Allow anyone to verify

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone_number']
            incoming_otp = serializer.validated_data['otp']
            
            # 1. Check OTP
            stored_otp = OTP_STORAGE.get(phone)
            
            if stored_otp and stored_otp == incoming_otp:
                # OTP Matches!
                
                # 2. Get or Create User
                # Since User model has a signal to create CustomerProfile, that handles itself.
                user, created = User.objects.get_or_create(phone_number=phone)
                
                # If created, they are a CUSTOMER by default (from model default)
                if created:
                    user.role = User.Role.CUSTOMER
                    user.save()

                # 3. Clear the used OTP
                del OTP_STORAGE[phone]

                # 4. Generate JWT Tokens
                refresh = RefreshToken.for_user(user)

                return Response({
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': UserSerializer(user).data,
                    'message': 'Login Successful',
                    'is_new_user': created
                }, status=status.HTTP_200_OK)
            
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileUpdateView(APIView):
    """
    Update basic profile fields after first login.
    Body: { "first_name": "Rahul", "last_name": "Kumar", "full_name": "Rahul Kumar", "village": "Rampur" }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get customer profile including location data."""
        user = request.user
        profile = getattr(user, "customer_profile", None)
        
        response_data = {
            "user": UserSerializer(user).data,
            "profile": None
        }
        
        if profile:
            response_data["profile"] = {
                "full_name": profile.full_name,
                "default_address": profile.default_address,
                "default_lat": str(profile.default_lat) if profile.default_lat else None,
                "default_lng": str(profile.default_lng) if profile.default_lng else None,
            }
        
        return Response(response_data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        data = serializer.validated_data

        # Update User fields
        if "first_name" in data:
            user.first_name = data.get("first_name", user.first_name)
        if "last_name" in data:
            user.last_name = data.get("last_name", user.last_name)
        user.save()

        # Update CustomerProfile (if exists)
        profile = getattr(user, "customer_profile", None)
        if profile:
            if "full_name" in data:
                profile.full_name = data.get("full_name", profile.full_name)
            if "village" in data:
                profile.default_address = data.get("village", profile.default_address)
            if "default_address" in data:
                profile.default_address = data.get("default_address", profile.default_address)
            if "default_lat" in data:
                profile.default_lat = data.get("default_lat")
            if "default_lng" in data:
                profile.default_lng = data.get("default_lng")
            profile.save()

        profile_data = None
        if profile:
            profile_data = {
                "full_name": profile.full_name,
                "default_address": profile.default_address,
                "default_lat": str(profile.default_lat) if profile.default_lat else None,
                "default_lng": str(profile.default_lng) if profile.default_lng else None,
            }

        return Response({
            "message": "Profile updated",
            "user": UserSerializer(user).data,
            "profile": profile_data
        }, status=status.HTTP_200_OK)


class LocationView(APIView):
    """
    Dedicated endpoint for user location management.
    GET: Return saved location from CustomerProfile.
    POST: Update location (latitude, longitude, address) on CustomerProfile.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the user's saved location."""
        profile = getattr(request.user, "customer_profile", None)

        if not profile or not profile.default_lat or not profile.default_lng:
            return Response({
                "has_location": False,
                "location": None
            }, status=status.HTTP_200_OK)

        return Response({
            "has_location": True,
            "location": {
                "latitude": str(profile.default_lat),
                "longitude": str(profile.default_lng),
                "address": profile.default_address or "",
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
            from .models import CustomerProfile
            profile = CustomerProfile.objects.create(user=request.user)

        profile.default_lat = data["latitude"]
        profile.default_lng = data["longitude"]
        profile.default_address = data.get("address", "")
        profile.save()

        return Response({
            "message": "Location updated successfully",
            "location": {
                "latitude": str(profile.default_lat),
                "longitude": str(profile.default_lng),
                "address": profile.default_address or "",
            }
        }, status=status.HTTP_200_OK)
