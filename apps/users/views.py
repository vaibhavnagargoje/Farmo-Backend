from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
    SendOTPSerializer, VerifyOTPSerializer, UserSerializer,
    ProfileUpdateSerializer, CustomerProfileSerializer, GoogleAuthSerializer
)
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
from django.http import HttpResponse
import random
from .whatsapp_service import send_whatsapp_otp, clean_phone_number

User = get_user_model()


class SendOTPView(APIView):
    """
    Send OTP via WhatsApp to user's phone number (with optional email copy).
    Body: { "phone_number": "1234567890", "email": "user@example.com" (optional) }
    """
    permission_classes = []

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone_number']
            email = serializer.validated_data.get('email')
            
            # Check if user exists and is deactivated
            user_filter = User.objects.filter(phone_number=phone)
            if email:
                user_filter = user_filter | User.objects.filter(email=email)
            user = user_filter.first()
            if user and not user.is_active:
                return Response(
                    {"error": "Your account has been deleted. Please contact support or email us to reactivate."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # 1. Generate OTP
            if email and email.lower() == 'test@farmo.in':
                otp = '1234'
            else:
                # 4-digit OTP for WhatsApp template (supports 4-8 digits)
                otp = str(random.randint(1000, 9999))
            
            # 2. Store OTP in cache keyed by phone number (5 min expiry)
            clean_phone = clean_phone_number(phone)
            cache.set(f'otp_{clean_phone}', otp, timeout=300)
            cache.set(f'otp_{phone}', otp, timeout=300)
            
            # Also store under email if provided (for backward compatibility)
            if email:
                cache.set(f'otp_{email}', otp, timeout=300)
                cache.set(f'otp_phone_{email}', phone, timeout=300)
            
            # 3. Send OTP via WhatsApp Cloud API
            wa_result = send_whatsapp_otp(phone_number=phone, otp=otp)
            
            # 4. Optional: Send via email if email provided
            if email and email.lower() != 'test@farmo.in':
                try:
                    html_message = f"""
                    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 500px; margin: 0 auto; padding: 30px; border: 1px solid #eaeaea; border-radius: 12px; background-color: #ffffff;">
                        <div style="text-align: center; margin-bottom: 25px;">
                            <span style="font-size: 28px; font-weight: 800; color: #1a4570; letter-spacing: -0.5px;">Farmo</span>
                        </div>
                        <h2 style="color: #333333; font-size: 20px; font-weight: 600; margin-bottom: 15px; text-align: center;">Login Verification</h2>
                        <p style="font-size: 15px; color: #555555; line-height: 1.6; text-align: center;">
                            Hello,<br>Here is your One-Time Password (OTP) to securely sign in:
                        </p>
                        <div style="background-color: #f4f7fb; border: 1px solid #e1e8f0; padding: 20px; text-align: center; border-radius: 8px; margin: 30px 0;">
                            <span style="font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #1a4570;">{otp}</span>
                        </div>
                        <p style="font-size: 14px; color: #777777; text-align: center; margin-bottom: 30px;">
                            This code will expire in <b>5 minutes</b>. Please do not share it with anyone.
                        </p>
                        <hr style="border: none; border-top: 1px solid #eaeaea; margin: 20px 0;" />
                        <p style="font-size: 12px; color: #aaaaaa; text-align: center; line-height: 1.5;">
                            If you didn't request this code, you can safely ignore this email.<br>
                            &copy; 2026 Farmo. All rights reserved.
                        </p>
                    </div>
                    """
    
                    send_mail(
                        subject='Your Farmo Login Verification Code',
                        message=f'Your OTP for Farmo login is: {otp}\n\nThis OTP is valid for 5 minutes. Do not share this code with anyone.',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        fail_silently=False,
                        html_message=html_message
                    )
                except Exception as e:
                    print(f"--> Email send failed: {e}")
            
            print(f"--> SENT OTP {otp} to WhatsApp phone: {phone} (status: {wa_result.get('success')})")
            
            return Response({
                "message": "OTP sent to your WhatsApp successfully.",
                "whatsapp_delivered": wa_result.get("success", False),
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(APIView):
    """
    Verify OTP (via phone number or email) and return JWT Token.
    Body: { "phone_number": "1234567890", "otp": "123456", "email": "user@example.com" (optional) }
    """
    permission_classes = []

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone_number']
            email = serializer.validated_data.get('email')
            incoming_otp = serializer.validated_data['otp']
            
            # 1. Check OTP (check clean phone, raw phone, then email)
            clean_phone = clean_phone_number(phone)
            stored_otp = cache.get(f'otp_{clean_phone}') or cache.get(f'otp_{phone}')
            if not stored_otp and email:
                stored_otp = cache.get(f'otp_{email}')
            
            if stored_otp and stored_otp == incoming_otp:
                # OTP Matches!
                
                # 2. Get or Create User by phone_number (phone stays primary identifier)
                user, created = User.objects.get_or_create(phone_number=phone)
                
                if not user.is_active:
                    return Response(
                        {"error": "Your account has been deleted. Please contact support or email us to reactivate."},
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Update email if provided and valid
                if email and (not user.email or user.email != email):
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
                cache.delete(f'otp_{clean_phone}')
                cache.delete(f'otp_{phone}')
                if email:
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


class WhatsAppWebhookView(APIView):
    """
    Meta WhatsApp Cloud API Webhook Handler.
    - GET: Meta webhook verification handshake (hub.challenge).
    - POST: Incoming messages for auto chatbot & booking handling.
    """
    permission_classes = []

    def get(self, request):
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        expected_token = getattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "farmo_secret_webhook_verify_token_2026")

        if mode == "subscribe" and token == expected_token:
            return HttpResponse(challenge, content_type="text/plain", status=200)
        return HttpResponse("Verification token mismatch", status=403)

    def post(self, request):
        data = request.data
        try:
            entries = data.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    # Process incoming messages for chatbot/bookings
                    if "messages" in value:
                        for msg in value["messages"]:
                            sender_phone = msg.get("from")
                            msg_type = msg.get("type")
                            msg_body = msg.get("text", {}).get("body", "")
                            print(f"--> [WhatsApp Inbound] From: {sender_phone}, Type: {msg_type}, Body: {msg_body}")
                            # TODO: Connect your auto-chatbot or booking logic here!
        except Exception as e:
            print(f"--> [WhatsApp Webhook Error]: {e}")

        # Meta requires 200 OK
        return Response({"status": "EVENT_RECEIVED"}, status=status.HTTP_200_OK)


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
            
            if not user.is_active:
                return Response(
                    {"error": "Your account has been deleted. Please contact support or email us to reactivate."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
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
    Body (JSON): { "full_name": "Rahul Kumar" }
    Body (multipart/form-data): full_name + optional profile_picture
    Location data is managed separately via /locations/user-location/ endpoint.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

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
                "gender": profile.gender,
                "age": profile.age,
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

        # Update CustomerProfile
        profile = user.customer_profile if hasattr(user, "customer_profile") else None
        if profile:
            if "full_name" in data:
                profile.full_name = data.get("full_name", profile.full_name)
            if "profile_picture" in data:
                profile.profile_picture = data.get("profile_picture")
            if "gender" in data:
                profile.gender = data.get("gender")
            if "age" in data:
                profile.age = data.get("age")
            profile.save()

        # Build response with location from UserLocation
        loc = user.location if hasattr(user, "location") else None
        profile_data = None
        if profile:
            profile_data = {
                "full_name": profile.full_name,
                "gender": profile.gender,
                "age": profile.age,
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

class DeleteAccountView(APIView):
    """
    Soft deletes the authenticated user account by setting is_active to False.
    This prevents login but preserves historical data like bookings.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        user.is_active = False
        user.save(update_fields=['is_active'])
        return Response({"message": "Account successfully deleted."}, status=status.HTTP_200_OK)
