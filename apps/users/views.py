from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import SendOTPSerializer, VerifyOTPSerializer, UserSerializer
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
