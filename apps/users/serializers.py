from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the Custom User model.
    Exposes full_name from CustomerProfile instead of first_name/last_name.
    """
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'phone_number', 'email', 'role', 'full_name', 'is_active']
        read_only_fields = ['id', 'role', 'is_active']

    def get_full_name(self, obj):
        profile = getattr(obj, 'customer_profile', None)
        if profile and profile.full_name:
            return profile.full_name
        return ""


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
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    user_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    # Optional location hierarchy IDs
    state = serializers.IntegerField(required=False, allow_null=True)
    district = serializers.IntegerField(required=False, allow_null=True)
    tahsil = serializers.IntegerField(required=False, allow_null=True)
    village = serializers.IntegerField(required=False, allow_null=True)


class CustomerProfileSerializer(serializers.Serializer):
    """
    Serializer for customer profile data.
    """
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    user_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    state = serializers.IntegerField(required=False, allow_null=True)
    district = serializers.IntegerField(required=False, allow_null=True)
    tahsil = serializers.IntegerField(required=False, allow_null=True)
    village = serializers.IntegerField(required=False, allow_null=True)
