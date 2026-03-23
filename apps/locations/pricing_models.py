from django.db import models
from services.models import Category


PRICE_UNIT_CHOICES = [
    ('HOUR', 'Hour'),
    ('DAY', 'Day'),
    ('KM', 'Kilometer'),
    ('ACRE', 'Acre'),
    ('FIXED', 'Fixed Price'),
]


class PricingZone(models.Model):
    """
    Admin-defined geographic pricing zone for a service category.

    Each zone has a center point (lat/lng) + radius, and a price override.
    When a customer makes an instant booking, the system finds the closest
    matching zone and uses that zone's price instead of the global
    category.instant_price.

    Resolution order:
      1. Active zones whose radius contains the customer → closest wins
      2. Default zone (is_default=True) for this category
      3. category.instant_price (global fallback, unchanged)
    """

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='pricing_zones',
        help_text="Which category this price zone applies to",
    )
    name = models.CharField(
        max_length=100,
        help_text="Human-readable label, e.g. 'Pune Urban', 'Solapur Region'",
    )

    # ── Geographic center of the zone ──
    center_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Latitude of zone center (leave blank for default zone)",
    )
    center_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Longitude of zone center (leave blank for default zone)",
    )
    radius_km = models.PositiveIntegerField(
        default=25,
        help_text="Coverage radius in kilometers from the center point",
    )

    # ── Pricing override ──
    price = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Price for instant bookings within this zone",
    )
    price_unit = models.CharField(
        max_length=10, choices=PRICE_UNIT_CHOICES, default='HOUR',
        help_text="Unit for this zone's price (Hour/Day/Km/Acre/Fixed)",
    )

    # ── Flags ──
    is_default = models.BooleanField(
        default=False,
        help_text="If True, this zone is the fallback when the customer is outside all geographic zones",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('category', 'name')
        ordering = ['category', 'name']
        verbose_name = 'Pricing Zone'
        verbose_name_plural = 'Pricing Zones'

    def __str__(self):
        tag = " [DEFAULT]" if self.is_default else ""
        return f"{self.category.name} — {self.name}{tag} (₹{self.price}/{self.price_unit})"
