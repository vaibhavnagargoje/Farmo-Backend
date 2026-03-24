from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the Custom User model.
    Exposes full_name and profile_picture from CustomerProfile.
    """
    full_name = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'phone_number', 'email', 'role', 'full_name', 'profile_picture', 'is_active', 'preferred_language']
        read_only_fields = ['id', 'role', 'is_active']

    def get_full_name(self, obj):
        profile = getattr(obj, 'customer_profile', None)
        if profile and profile.full_name:
            return profile.full_name
        return ""

    def get_profile_picture(self, obj):
        profile = getattr(obj, 'customer_profile', None)
        if profile and profile.profile_picture:
            request = self.context.get('request')
            photo_url = profile.profile_picture.url
            if request:
                return request.build_absolute_uri(photo_url)
            # Fallback if request context is somehow missing
            from django.conf import settings
            domain = getattr(settings, 'BACKEND_URL', 'http://127.0.0.1:8000').rstrip('/')
            return f"{domain}{photo_url}"
        return None


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
    Location data is handled separately via the locations app (UserLocation).
    """
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)


class CustomerProfileSerializer(serializers.Serializer):
    """
    Serializer for customer profile data (without location — that's in UserLocation).
    """
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
