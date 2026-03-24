# apps/partners/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import PartnerProfile, LaborDetails, MachineryDetails, TransportDetails

User = get_user_model()

# --- Nested Detail Serializers ---
class LaborDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LaborDetails
        fields = ['skill_card_photo', 'daily_wage_estimate', 'is_migrant_worker', 'skills']

class MachineryDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineryDetails
        fields = ['owner_dl_number', 'owner_dl_photo', 'fleet_size']

class TransportDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransportDetails
        fields = ['driving_license_number', 'driving_license_photo', 'vehicle_insurance_photo', 'is_intercity_available']


# --- Main Partner Serializers ---
class PartnerProfileSerializer(serializers.ModelSerializer):
    """
    Read-only serializer to display Partner info (e.g., on a Service listing).
    """
    user_phone = serializers.CharField(source='user.phone_number', read_only=True)
    full_name = serializers.CharField(source='user.customer_profile.full_name', read_only=True, default='')
    profile_picture = serializers.SerializerMethodField()
    
    class Meta:
        model = PartnerProfile
        fields = [
            'id', 'user', 'user_phone', 'full_name', 'profile_picture', 'partner_type', 'about',
            'is_verified', 'is_kyc_submitted', 'is_available',
            'rating', 'jobs_completed', 'created_at'
        ]
        read_only_fields = ['id', 'user', 'is_verified', 'rating', 'jobs_completed', 'created_at']

    def get_profile_picture(self, obj):
        profile = getattr(obj.user, 'customer_profile', None)
        if profile and profile.profile_picture:
            request = self.context.get('request')
            photo_url = profile.profile_picture.url
            if request:
                return request.build_absolute_uri(photo_url)
            from django.conf import settings
            domain = getattr(settings, 'BACKEND_URL', 'http://127.0.0.1:8000').rstrip('/')
            return f"{domain}{photo_url}"
        return None


class PartnerRegistrationSerializer(serializers.ModelSerializer):
    """
    Used when a User registers as a Partner for the first time.
    """
    # Nested details (optional, based on partner_type)
    labor_details = LaborDetailsSerializer(required=False, allow_null=True)
    machinery_details = MachineryDetailsSerializer(required=False, allow_null=True)
    transport_details = TransportDetailsSerializer(required=False, allow_null=True)

    class Meta:
        model = PartnerProfile
        fields = [
            'partner_type', 'about',
            'aadhar_card_front', 'aadhar_card_back', 'pan_card',
            'labor_details', 'machinery_details', 'transport_details'
        ]

    def validate(self, attrs):
        partner_type = attrs.get('partner_type')
        
        # Note: Nested details (labor_details, machinery_details, transport_details)
        # are optional during initial onboarding. Partners can add them later
        # via profile update. We only validate that a valid partner_type is provided.
        if not partner_type:
            raise serializers.ValidationError({"partner_type": "Partner type is required."})
        
        return attrs

    def create(self, validated_data):
        # Pop nested data
        labor_data = validated_data.pop('labor_details', None)
        machinery_data = validated_data.pop('machinery_details', None)
        transport_data = validated_data.pop('transport_details', None)
        
        # Get the user from the request context
        user = self.context['request'].user
        
        # Create the main profile
        partner_profile = PartnerProfile.objects.create(user=user, **validated_data)
        
        # Update user role
        user.role = User.Role.PARTNER
        user.save()
        
        # Create the appropriate nested details
        if labor_data:
            LaborDetails.objects.create(partner=partner_profile, **labor_data)
        if machinery_data:
            MachineryDetails.objects.create(partner=partner_profile, **machinery_data)
        if transport_data:
            TransportDetails.objects.create(partner=partner_profile, **transport_data)
        
        return partner_profile


class PartnerProfileUpdateSerializer(serializers.ModelSerializer):
    """
    For updating existing Partner Profile (e.g., changing business name, uploading KYC).
    """
    class Meta:
        model = PartnerProfile
        fields = [
            'about',
            'is_available', 'aadhar_card_front', 'aadhar_card_back', 'pan_card', 'is_kyc_submitted'
        ]


class LaborDetailsUpdateSerializer(serializers.ModelSerializer):
    """
    Writable serializer for updating an existing LaborDetails record.
    All fields optional to allow partial updates.
    """
    class Meta:
        model = LaborDetails
        fields = ['skills', 'daily_wage_estimate', 'is_migrant_worker', 'skill_card_photo']
        extra_kwargs = {
            'skills': {'required': False},
            'daily_wage_estimate': {'required': False},
            'is_migrant_worker': {'required': False},
            'skill_card_photo': {'required': False},
        }
