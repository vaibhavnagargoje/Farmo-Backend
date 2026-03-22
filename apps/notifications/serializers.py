from rest_framework import serializers
from .models import DeviceToken, Notification

class DeviceTokenSerializer(serializers.ModelSerializer):
    # Override to remove DRF's auto-UniqueValidator — we handle uniqueness
    # ourselves via update_or_create in create().
    token = serializers.CharField(max_length=255)

    class Meta:
        model = DeviceToken
        fields = ['token']

    def create(self, validated_data):
        user = self.context['request'].user
        token = validated_data.get('token')
        
        # Use update_or_create to prevent duplicate tokens for the same user
        device_token, created = DeviceToken.objects.update_or_create(
            token=token,
            defaults={'user': user}
        )
        return device_token

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'is_read', 'booking_id', 'notification_type', 'created_at']
