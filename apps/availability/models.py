# apps/availability/models.py
from django.db import models
from django.conf import settings
from partners.models import PartnerProfile


class BusyDay(models.Model):
    """
    Calendar-based availability: a row here = partner is BUSY on that date.
    No row = partner is AVAILABLE (default state).

    Design:
    - If a partner has NO BusyDay rows, they are free every day.
    - Workers/agents mark specific dates as busy (red on calendar).
    - Search queries exclude partners who have a BusyDay for the target date.
    - The old is_available toggle on PartnerProfile is kept as a "master switch"
      (emergency offline). Calendar is the primary source of truth for day-level.
    """

    class MarkedBy(models.TextChoices):
        SELF = 'SELF', 'Marked by Worker (App)'
        AGENT = 'AGENT', 'Marked by Agent (Center)'
        SYSTEM = 'SYSTEM', 'Auto-marked by System (Booking)'

    class EntityType(models.TextChoices):
        """Future-proof: allows calendar for different partner types."""
        PARTNER = 'PARTNER', 'Partner (Person)'
        SERVICE = 'SERVICE', 'Service (Asset/Machine)'

    # ── Who is busy? ──
    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name='busy_days',
    )
    # Optionally, which specific service/machine is busy (for machinery partners).
    # If null → entire partner is busy (used for LABOR).
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='busy_days',
        help_text="If null, the entire partner is busy. If set, only this specific service/machine.",
    )
    entity_type = models.CharField(
        max_length=10,
        choices=EntityType.choices,
        default=EntityType.PARTNER,
    )

    # ── When? ──
    date = models.DateField(db_index=True)

    # ── Who marked it and why? ──
    marked_by = models.CharField(max_length=10, choices=MarkedBy.choices)
    marked_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='marked_busy_days',
        help_text="The user (agent or partner) who marked this busy day.",
    )
    reason = models.CharField(
        max_length=255, blank=True, default='',
        help_text="Optional: 'private job', 'sick', 'booked via Farmo'",
    )

    # ── Linked booking (auto-marked) ──
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='busy_day_entries',
        help_text="If this busy day was auto-created from a confirmed booking.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('partner', 'service', 'date')
        ordering = ['date']
        indexes = [
            models.Index(fields=['partner', 'date']),
            models.Index(fields=['date']),
        ]
        verbose_name = 'Busy Day'
        verbose_name_plural = 'Busy Days'

    def __str__(self):
        svc = f" [{self.service.title}]" if self.service else ""
        return f"{self.partner.user.phone_number}{svc} — BUSY on {self.date} ({self.get_marked_by_display()})"
