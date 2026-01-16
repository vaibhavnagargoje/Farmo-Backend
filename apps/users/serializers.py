from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the Custom User model.
    """
    class Meta:
        model = User
        fields = ['id', 'phone_number', 'email', 'role', 'first_name', 'last_name', 'is_active']
        read_only_fields = ['id', 'role', 'is_active']

class SendOTPSerializer(serializers.Serializer):
    """
    Validates the phone number for sending OTP.
    """
    phone_number = serializers.CharField(max_length=15, required=True)

class VerifyOTPSerializer(serializers.Serializer):
    """
    Validates the phone number and OTP for login.
    """
    phone_number = serializers.CharField(max_length=15, required=True)
    otp = serializers.CharField(max_length=6, min_length=4, required=True)
