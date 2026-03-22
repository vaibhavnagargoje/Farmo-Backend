from django.db import models
from django.conf import settings

class DeviceToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='fcm_tokens')
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} - {self.token[:15]}..."


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        CUSTOMER_BOOKING = 'CUSTOMER_BOOKING', 'Customer Booking'
        PROVIDER_JOB = 'PROVIDER_JOB', 'Provider Job'
        GENERAL = 'GENERAL', 'General'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    booking_id = models.CharField(max_length=50, null=True, blank=True)
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.user}: {self.title}"
