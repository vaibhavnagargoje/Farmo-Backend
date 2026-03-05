from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import SendOTPSerializer, VerifyOTPSerializer, UserSerializer, ProfileUpdateSerializer, CustomerProfileSerializer
from django.core.cache import cache
import random

User = get_user_model()

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
            
            # 2. Store OTP in database cache (shared across workers, 5 min expiry)
            cache.set(f'otp_{phone}', otp, timeout=300)
            
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
            stored_otp = cache.get(f'otp_{phone}')
            
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
                cache.delete(f'otp_{phone}')

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
    Body: { "full_name": "Rahul Kumar" }
    Location data is managed separately via /locations/user-location/ endpoint.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get customer profile and location data."""
        user = request.user
        profile = getattr(user, "customer_profile", None)
        loc = getattr(user, "location", None)
        
        response_data = {
            "user": UserSerializer(user).data,
            "profile": None
        }
        
        if profile:
            profile_data = {
                "full_name": profile.full_name,
            }
            # Include location from UserLocation model
            if loc:
                profile_data["user_address"] = loc.address or None
                profile_data["latitude"] = str(loc.latitude) if loc.latitude else None
                profile_data["longitude"] = str(loc.longitude) if loc.longitude else None
                profile_data["state"] = loc.state_id
                profile_data["district"] = loc.district_id
                profile_data["tahsil"] = loc.tahsil_id
                profile_data["village"] = loc.village_id
            else:
                profile_data["user_address"] = None
                profile_data["latitude"] = None
                profile_data["longitude"] = None
                profile_data["state"] = None
                profile_data["district"] = None
                profile_data["tahsil"] = None
                profile_data["village"] = None
            response_data["profile"] = profile_data
        
        return Response(response_data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        data = serializer.validated_data

        # Update CustomerProfile (only full_name now)
        profile = getattr(user, "customer_profile", None)
        if profile:
            if "full_name" in data:
                profile.full_name = data.get("full_name", profile.full_name)
            profile.save()

        # Build response with location from UserLocation
        loc = getattr(user, "location", None)
        profile_data = None
        if profile:
            profile_data = {
                "full_name": profile.full_name,
                "user_address": loc.address if loc else None,
                "latitude": str(loc.latitude) if loc and loc.latitude else None,
                "longitude": str(loc.longitude) if loc and loc.longitude else None,
                "state": loc.state_id if loc else None,
                "district": loc.district_id if loc else None,
                "tahsil": loc.tahsil_id if loc else None,
                "village": loc.village_id if loc else None,
            }

        return Response({
            "message": "Profile updated",
            "user": UserSerializer(user).data,
            "profile": profile_data
        }, status=status.HTTP_200_OK)
