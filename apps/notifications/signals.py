from decimal import Decimal

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from bookings.models import BookingOffer, Booking, ProviderContact
from .models import Notification
from .utils import send_push_notification


# 0. Notify Provider when a farmer who found them on Farmo says they agreed on work
@receiver(pre_save, sender=ProviderContact)
def cache_previous_contact_outcome(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_outcome = None
        return
    previous = ProviderContact.objects.filter(pk=instance.pk).values('outcome').first()
    instance._previous_outcome = previous['outcome'] if previous else None


@receiver(post_save, sender=ProviderContact)
def notify_provider_on_agreed_contact(sender, instance, **kwargs):
    if instance.outcome != ProviderContact.Outcome.AGREED:
        return
    if getattr(instance, '_previous_outcome', None) == ProviderContact.Outcome.AGREED:
        return

    provider_user = instance.provider.user
    service_name = instance.service.title if instance.service else (
        instance.category.name if instance.category else "your service"
    )
    work = ""
    if instance.quantity:
        quantity = format(Decimal(instance.quantity).normalize(), "f")
        work = f" for {quantity} {instance.price_unit.lower()}".rstrip()
    message = f"A farmer found you on Farmo and agreed on {service_name} work{work}."

    Notification.objects.create(
        user=provider_user,
        title="A farmer found you on Farmo!",
        message=message,
        notification_type=Notification.NotificationType.PROVIDER_JOB,
    )
    send_push_notification(
        user=provider_user,
        title="A farmer found you on Farmo!",
        body=f"{message} Tap to see their details.",
        data={"type": "direct_contact", "contact_id": str(instance.pk)},
    )

# 1. Notify Provider when a new job is available (SEARCHING -> created BookingOffer)
@receiver(post_save, sender=BookingOffer)
def notify_provider_of_new_job(sender, instance, created, **kwargs):
    if created and instance.status == BookingOffer.Status.PENDING:
        provider_user = instance.provider.user
        
        # Save to DB for the Bell Icon
        Notification.objects.create(
            user=provider_user,
            title="New Job Nearby!",
            message=f"A farmer needs a {instance.booking.category.name} service nearby.",
            booking_id=instance.booking.booking_id,
            notification_type=Notification.NotificationType.PROVIDER_JOB,
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
                booking_id=instance.booking_id,
                notification_type=Notification.NotificationType.CUSTOMER_BOOKING,
            )

            send_push_notification(
                user=farmer_user,
                title="Provider Confirmed!",
                body=f"{provider_name} has accepted your booking. Tap to view details.",
                data={'booking_id': str(instance.booking_id), 'type': 'booking_confirmed'}
            )


@receiver(pre_save, sender=Booking)
def cache_previous_booking_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return

    previous = Booking.objects.filter(pk=instance.pk).values('status').first()
    instance._previous_status = previous['status'] if previous else None


# 3. Notify relevant users when booking is cancelled or expired
@receiver(post_save, sender=Booking)
def notify_booking_cancelled_or_expired(sender, instance, created, **kwargs):
    if created:
        return

    previous_status = getattr(instance, '_previous_status', None)
    if previous_status == instance.status:
        return

    if instance.status == Booking.Status.CANCELLED:
        customer_user = instance.customer
        provider_user = instance.provider.user if instance.provider else None
        cancelled_by_id = instance.cancelled_by_id

        if cancelled_by_id == customer_user.id:
            if provider_user:
                Notification.objects.create(
                    user=provider_user,
                    title="Booking Cancelled",
                    message=f"Customer cancelled booking {instance.booking_id}.",
                    booking_id=instance.booking_id,
                    notification_type=Notification.NotificationType.PROVIDER_JOB,
                )
                send_push_notification(
                    user=provider_user,
                    title="Booking Cancelled",
                    body=f"Customer cancelled booking {instance.booking_id}.",
                    data={'booking_id': str(instance.booking_id), 'type': 'booking_cancelled'},
                )
        elif provider_user and cancelled_by_id == provider_user.id:
            Notification.objects.create(
                user=customer_user,
                title="Booking Cancelled",
                message=f"Provider cancelled your booking {instance.booking_id}.",
                booking_id=instance.booking_id,
                notification_type=Notification.NotificationType.CUSTOMER_BOOKING,
            )
            send_push_notification(
                user=customer_user,
                title="Booking Cancelled",
                body=f"Provider cancelled your booking {instance.booking_id}.",
                data={'booking_id': str(instance.booking_id), 'type': 'booking_cancelled'},
            )
        else:
            # System/admin cancellation path: notify both sides when available.
            Notification.objects.create(
                user=customer_user,
                title="Booking Cancelled",
                message=f"Booking {instance.booking_id} was cancelled.",
                booking_id=instance.booking_id,
                notification_type=Notification.NotificationType.CUSTOMER_BOOKING,
            )
            send_push_notification(
                user=customer_user,
                title="Booking Cancelled",
                body=f"Booking {instance.booking_id} was cancelled.",
                data={'booking_id': str(instance.booking_id), 'type': 'booking_cancelled'},
            )

            if provider_user:
                Notification.objects.create(
                    user=provider_user,
                    title="Booking Cancelled",
                    message=f"Booking {instance.booking_id} was cancelled.",
                    booking_id=instance.booking_id,
                    notification_type=Notification.NotificationType.PROVIDER_JOB,
                )
                send_push_notification(
                    user=provider_user,
                    title="Booking Cancelled",
                    body=f"Booking {instance.booking_id} was cancelled.",
                    data={'booking_id': str(instance.booking_id), 'type': 'booking_cancelled'},
                )

    if instance.status == Booking.Status.EXPIRED:
        customer_user = instance.customer

        already_notified = Notification.objects.filter(
            user=customer_user,
            booking_id=instance.booking_id,
            title="Booking Expired",
        ).exists()

        if not already_notified:
            Notification.objects.create(
                user=customer_user,
                title="Booking Expired",
                message=f"No provider accepted booking {instance.booking_id} in time.",
                booking_id=instance.booking_id,
                notification_type=Notification.NotificationType.CUSTOMER_BOOKING,
            )
            send_push_notification(
                user=customer_user,
                title="Booking Expired",
                body=f"No provider accepted booking {instance.booking_id} in time.",
                data={'booking_id': str(instance.booking_id), 'type': 'booking_expired'},
            )
