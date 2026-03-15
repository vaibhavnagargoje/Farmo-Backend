from django.db.models.signals import post_save
from django.dispatch import receiver
from bookings.models import InstantBookingRequest, Booking
from .models import Notification
from .utils import send_push_notification

# 1. Notify Provider when a new job is available (SEARCHING -> created InstantBookingRequest)
@receiver(post_save, sender=InstantBookingRequest)
def notify_provider_of_new_job(sender, instance, created, **kwargs):
    if created and instance.status == InstantBookingRequest.RequestStatus.PENDING:
        provider_user = instance.provider.user
        
        # Save to DB for the Bell Icon
        Notification.objects.create(
            user=provider_user,
            title="New Job Nearby!",
            message=f"A farmer needs a {instance.booking.category.name} service nearby.",
            booking_id=instance.booking.booking_id
        )
        
        # Fire push notification via FCM
        send_push_notification(
            user=provider_user,
            title="New Job Nearby!",
            body=f"A farmer needs a {instance.booking.category.name} service nearby. Tap to view and accept.",
            data={'booking_id': str(instance.booking.booking_id), 'type': 'new_job'}
        )

# 2. Notify Farmer when a Provider accepts the job (Booking status becomes CONFIRMED)
@receiver(post_save, sender=Booking)
def notify_farmer_on_confirmation(sender, instance, **kwargs):
    if instance.status == Booking.Status.CONFIRMED and instance.provider:
        farmer_user = instance.customer

        # Prevent duplicate notifications: only notify if one doesn't already exist for this event
        already_notified = Notification.objects.filter(
            user=farmer_user,
            booking_id=instance.booking_id,
            title="Provider Confirmed!"
        ).exists()

        if not already_notified:
            provider_name = instance.provider.user.get_full_name() or instance.provider.user.phone_number

            Notification.objects.create(
                user=farmer_user,
                title="Provider Confirmed!",
                message=f"{provider_name} has accepted your booking and is on the way.",
                booking_id=instance.booking_id
            )

            send_push_notification(
                user=farmer_user,
                title="Provider Confirmed!",
                body=f"{provider_name} has accepted your booking. Tap to view details.",
                data={'booking_id': str(instance.booking_id), 'type': 'booking_confirmed'}
            )
