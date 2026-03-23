from django.db import models
from django.conf import settings


class UserLocation(models.Model):
    """
    Shared location record for any user (customer or partner).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='location',
    )
    address = models.TextField(blank=True, default="")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Location'
        verbose_name_plural = 'User Locations'

    def __str__(self):
        return f"Location for {self.user} — {self.address[:50] or 'No address'}"


# Make PricingZone discoverable by Django for migrations
from .pricing_models import PricingZone  # noqa: E402, F401