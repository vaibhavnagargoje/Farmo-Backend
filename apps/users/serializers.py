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


class ProfileUpdateSerializer(serializers.Serializer):
    """
    Updates basic user profile data after first login.
    """
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    village = serializers.CharField(max_length=255, required=False, allow_blank=True)
    default_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    default_lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    default_address = serializers.CharField(max_length=500, required=False, allow_blank=True)


class CustomerProfileSerializer(serializers.Serializer):
    """
    Serializer for customer profile location data.
    """
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    default_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    default_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    default_lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)


class LocationUpdateSerializer(serializers.Serializer):
    """
    Dedicated serializer for updating user location.
    Used by the LocationView endpoint.
    """
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)
    address = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
