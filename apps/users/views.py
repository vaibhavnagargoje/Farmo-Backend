from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
    SendOTPSerializer, VerifyOTPSerializer, UserSerializer,
    ProfileUpdateSerializer, CustomerProfileSerializer, GoogleAuthSerializer
)
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
import random

User = get_user_model()


class SendOTPView(APIView):
    """
    Send OTP to user's email address.
    Body: { "phone_number": "1234567890", "email": "user@example.com" }
    """
    permission_classes = []

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone_number']
            email = serializer.validated_data['email']
            
            # 1. Generate OTP
            otp = str(random.randint(1000, 9999))
            
            # 2. Store OTP in cache keyed by email (5 min expiry)
            cache.set(f'otp_{email}', otp, timeout=300)
            # Also store the phone number associated with this email OTP
            cache.set(f'otp_phone_{email}', phone, timeout=300)
            
            # 3. Send OTP via email
            try:
                send_mail(
                    subject='Your Farmo Login OTP',
                    message=f'Your OTP for Farmo login is: {otp}\n\nThis OTP is valid for 5 minutes.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"--> Email send failed: {e}")
                # In development, OTP is still printed to console
            
            print(f"--> SENT OTP {otp} to {email} (phone: {phone})")
            
            return Response({
                "message": "OTP sent to your email.",
                "debug_otp": otp  # REMOVE THIS IN PRODUCTION
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(APIView):
    """
    Verify email OTP and return JWT Token.
    Body: { "phone_number": "1234567890", "email": "user@example.com", "otp": "1234" }
    """
    permission_classes = []

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone_number']
            email = serializer.validated_data['email']
            incoming_otp = serializer.validated_data['otp']
            
            # 1. Check OTP (keyed by email)
            stored_otp = cache.get(f'otp_{email}')
            
            if stored_otp and stored_otp == incoming_otp:
                # OTP Matches!
                
                # 2. Get or Create User by phone_number (phone stays primary identifier)
                user, created = User.objects.get_or_create(phone_number=phone)
                
                # Check if email is already used by another user
                if not user.email or user.email != email:
                    existing = User.objects.filter(email=email).exclude(pk=user.pk).first()
                    if existing:
                        return Response(
                            {"error": "This email is already registered with another account."},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    user.email = email
                
                if created:
                    user.role = User.Role.CUSTOMER
                
                user.save()

                # 3. Clear the used OTP
                cache.delete(f'otp_{email}')
                cache.delete(f'otp_phone_{email}')

                # 4. Generate JWT Tokens
                refresh = RefreshToken.for_user(user)

                return Response({
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': UserSerializer(user, context={'request': request}).data,
                    'message': 'Login Successful',
                    'is_new_user': created
                }, status=status.HTTP_200_OK)
            
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GoogleAuthView(APIView):
    """
    Authenticate with Google Sign-In.
    Body: { "id_token": "...", "phone_number": "1234567890" }
    
    Verifies the Google ID token using Firebase Admin SDK,
    then creates/finds user by phone_number and issues JWT.
    """
    permission_classes = []

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        if serializer.is_valid():
            id_token = serializer.validated_data['id_token']
            phone = serializer.validated_data['phone_number']
            
            # 1. Verify Google ID token using Firebase Admin SDK
            try:
                from firebase_admin import auth as firebase_auth
                decoded_token = firebase_auth.verify_id_token(id_token)
                google_email = decoded_token.get('email')
                google_name = decoded_token.get('name', '')
                
                if not google_email:
                    return Response(
                        {"error": "Google account does not have an email."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                print(f"--> Firebase token verification failed: {e}")
                return Response(
                    {"error": "Invalid Google token. Please try again."},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # 2. Get or Create User by phone_number
            user, created = User.objects.get_or_create(phone_number=phone)
            
            # Check if email is already used by another user
            if not user.email or user.email != google_email:
                existing = User.objects.filter(email=google_email).exclude(pk=user.pk).first()
                if existing:
                    return Response(
                        {"error": "This email is already registered with another phone number."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                user.email = google_email
            
            if created:
                user.role = User.Role.CUSTOMER
            
            user.save()
            
            # Set Google name on profile if new user and name exists
            if created and google_name:
                profile = getattr(user, 'customer_profile', None)
                if profile and not profile.full_name:
                    profile.full_name = google_name
                    profile.save()

            # 3. Generate JWT Tokens
            refresh = RefreshToken.for_user(user)

            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': UserSerializer(user, context={'request': request}).data,
                'message': 'Login Successful',
                'is_new_user': created
            }, status=status.HTTP_200_OK)
        
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
        profile = user.customer_profile if hasattr(user, "customer_profile") else None
        loc = user.location if hasattr(user, "location") else None
        
        response_data = {
            "user": UserSerializer(user, context={'request': request}).data,
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
            else:
                profile_data["user_address"] = None
                profile_data["latitude"] = None
                profile_data["longitude"] = None
            response_data["profile"] = profile_data
        
        return Response(response_data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        data = serializer.validated_data

        # Update CustomerProfile (only full_name now)
        profile = user.customer_profile if hasattr(user, "customer_profile") else None
        if profile:
            if "full_name" in data:
                profile.full_name = data.get("full_name", profile.full_name)
            profile.save()

        # Build response with location from UserLocation
        loc = user.location if hasattr(user, "location") else None
        profile_data = None
        if profile:
            profile_data = {
                "full_name": profile.full_name,
                "user_address": loc.address if loc else None,
                "latitude": str(loc.latitude) if loc and loc.latitude else None,
                "longitude": str(loc.longitude) if loc and loc.longitude else None,
            }

        return Response({
            "message": "Profile updated",
            "user": UserSerializer(user, context={'request': request}).data,
            "profile": profile_data
        }, status=status.HTTP_200_OK)


class LanguagePreferenceView(APIView):
    """
    GET:  Return user's preferred language.
    POST: Set user's preferred language. Body: { "language": "mr" }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "language": request.user.preferred_language,
        })

    def post(self, request):
        lang = request.data.get('language', '').strip()
        valid_codes = [c[0] for c in User.Language.choices]
        if lang not in valid_codes:
            return Response(
                {"error": f"Invalid language. Choices: {valid_codes}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.preferred_language = lang
        request.user.save(update_fields=['preferred_language'])
        return Response({
            "message": "Language updated",
            "language": lang,
        })
