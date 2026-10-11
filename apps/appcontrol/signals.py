from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Announcement, AppControl, AppRelease
from .services import clear_state


@receiver(post_save, sender=AppControl)
@receiver(post_save, sender=AppRelease)
@receiver(post_save, sender=Announcement)
@receiver(post_delete, sender=AppRelease)
@receiver(post_delete, sender=Announcement)
def refresh_app_control_state(sender, **kwargs):
    """The app and website see a change on their next request, not 30 seconds later."""
    clear_state()
