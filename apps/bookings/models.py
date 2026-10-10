from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from services.models import Service, Category
from partners.models import PartnerProfile # Link to the Business, not just the User

CENTS = Decimal("0.01")

class Booking(models.Model):
    """
    A Farmo Assured job. Every booking is broadcast to the nearest providers
    (see bookings.dispatch) and the first one to accept is assigned.
    Customers who call a provider themselves are recorded as ProviderContact.
    """
    class Status(models.TextChoices):
        SEARCHING = 'SEARCHING', 'Searching for Providers'  # broadcast sent
        CONFIRMED = 'CONFIRMED', 'Accepted by Provider'
        EXPIRED = 'EXPIRED', 'Expired (No Provider Found)'  # nobody accepted in time
        IN_PROGRESS = 'IN_PROGRESS', 'Work Started'
        COMPLETED = 'COMPLETED', 'Work Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Payment Pending'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Payment Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    # --- RELATIONS ---
    # 1. The Customer (User who needs the service)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')

    # 2. The provider's service doing the job (set when an agent assigns one)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='bookings', null=True, blank=True)

    # 3. The Category the customer booked
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='bookings', null=True, blank=True)

    # 4. The Provider (empty until a provider accepts or an agent assigns one)
    provider = models.ForeignKey(
        PartnerProfile, on_delete=models.CASCADE, related_name='received_bookings',
        null=True, blank=True
    )

    # 5. Agent who accepted on behalf of the provider (for tracking)
    accepted_by_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='agent_accepted_bookings',
        null=True, blank=True, help_text="The admin/agent who accepted this on behalf of the provider"
    )

    # 6. Agent who placed the booking for the customer (e.g. from a phone call)
    created_by_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='agent_created_bookings',
        null=True, blank=True, help_text="The admin/agent who placed this booking for the customer"
    )

    # --- JOB DETAILS ---
    booking_id = models.CharField(max_length=20, unique=True, editable=False)
    order_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True,
        help_text="Quick order number (QO-YYYYMMDD-NNN), auto-generated"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SEARCHING)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

    # Work date and time (default to now)
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)

    # Provider search expiry
    expires_at = models.DateTimeField(null=True, blank=True, help_text="When the provider search ends if nobody accepts")

    # Broadcast tracking
    broadcast_count = models.PositiveIntegerField(
        default=0, help_text="Number of broadcast rounds sent to providers"
    )
    current_broadcast_radius = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Radius (km) used in the latest broadcast round"
    )
    assigned_at = models.DateTimeField(
        null=True, blank=True, help_text="When a provider accepted this booking"
    )

    # Tracking
    work_started_at = models.DateTimeField(null=True, blank=True)
    work_completed_at = models.DateTimeField(null=True, blank=True)

    # --- SECURITY (OTPs) ---
    start_job_otp = models.CharField(max_length=6, null=True, blank=True)
    end_job_otp = models.CharField(max_length=6, null=True, blank=True)
    # Single-OTP mode: one code generated at order creation
    job_otp = models.CharField(max_length=6, null=True, blank=True)
    # Snapshot of the OTP mode at the time this booking was created.
    # This insulates in-flight bookings from admin mode-switches mid-flow.
    otp_mode_snapshot = models.CharField(
        max_length=10,
        null=True, blank=True,
        help_text="OTP mode that was active when this booking was created (SINGLE or DUAL)."
    )

    # Location
    address = models.TextField()
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True)

    # Financials (Snapshot Pattern)
    quantity = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("1"),
        validators=[MinValueValidator(CENTS)],
        help_text="Number of Hours/Acres/Km (decimals allowed, e.g. 3.5 acres)"
    )
    price_unit = models.CharField(
        max_length=20,
        default='HOUR',
        help_text="Unit type for pricing — snapshot of the ServicePriceUnit.key at booking time"
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    original_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="System price before an agent overrode unit_price; empty when not overridden"
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
        help_text="Flat ₹ discount taken off quantity × unit price"
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    price_updated_at = models.DateTimeField(
        null=True, blank=True, help_text="When an agent last changed quantity, rate or discount"
    )
    price_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='price_updated_bookings',
        null=True, blank=True, help_text="The admin/agent who last changed quantity, rate or discount"
    )

    # Meta
    note = models.TextField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True, null=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_bookings')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def subtotal(self):
        """Quantity × unit price, before any discount."""
        return (Decimal(self.unit_price or 0) * Decimal(self.quantity or 0)).quantize(CENTS)

    @property
    def quantity_display(self):
        """Quantity without trailing zeros: 5, 3.5, 2.25."""
        if self.quantity is None:
            return ""
        return format(Decimal(self.quantity).normalize(), "f")

    def recalculate_total(self):
        """total_amount = quantity × unit price − discount, never below zero."""
        self.total_amount = max(Decimal("0"), self.subtotal - Decimal(self.discount_amount or 0))
        return self.total_amount

    @property
    def is_expired(self):
        """True when the provider search ran past its expiry with nobody assigned."""
        if self.expires_at:
            return timezone.now() > self.expires_at and self.status == self.Status.SEARCHING
        return False

    def _generate_order_number(self):
        """Generate a daily-sequential quick order number: QO-YYYYMMDD-NNN"""
        today = timezone.now().date()
        today_str = today.strftime('%Y%m%d')
        prefix = f"QO-{today_str}-"

        # Find the highest existing order number for today (robust against deletions)
        last = Booking.objects.filter(
            order_number__startswith=prefix,
        ).order_by('-order_number').values_list('order_number', flat=True).first()

        if last:
            try:
                last_num = int(last.split('-')[-1])
                return f"{prefix}{last_num + 1:03d}"
            except (ValueError, IndexError):
                pass
        return f"{prefix}001"

    def save(self, *args, **kwargs):
        # Auto-generate Booking ID
        if not self.booking_id:
            import uuid
            self.booking_id = f"FB-{uuid.uuid4().hex[:8].upper()}"

        if not self.order_number:
            self.order_number = self._generate_order_number()

        if not self.scheduled_date:
            self.scheduled_date = timezone.localdate()
        if not self.scheduled_time:
            self.scheduled_time = timezone.localtime(timezone.now()).time().replace(second=0, microsecond=0)
        if not self.expires_at and self.status == self.Status.SEARCHING:
            timeout = 10  # default
            if self.category and hasattr(self.category, 'instant_timeout_minutes'):
                timeout = self.category.instant_timeout_minutes
            self.expires_at = timezone.now() + timezone.timedelta(minutes=timeout)

        # --- OTP generation logic (mode-aware) ---
        import random
        from adminpanel.models import AppSettings
        app_settings = AppSettings.get()
        current_mode = app_settings.otp_mode

        # On first save (creation): snapshot the mode and generate SINGLE otp if needed
        is_new = not self.pk
        if is_new:
            self.otp_mode_snapshot = current_mode
            if current_mode == AppSettings.OTP_MODE_SINGLE and not self.job_otp:
                self.job_otp = str(random.randint(1000, 9999))

        # On CONFIRMED transition: generate Dual OTPs if this booking was created under DUAL mode
        effective_mode = self.otp_mode_snapshot or current_mode
        if self.status == self.Status.CONFIRMED and not self.start_job_otp:
            if effective_mode == AppSettings.OTP_MODE_DUAL:
                self.start_job_otp = str(random.randint(1000, 9999))
                self.end_job_otp = str(random.randint(1000, 9999))

        # Auto-Calculate Total
        if not self.total_amount and self.unit_price and self.quantity:
            self.recalculate_total()

        super().save(*args, **kwargs)

        # ── Calendar Availability: auto-mark busy on CONFIRMED ──
        if self.status == self.Status.CONFIRMED and self.provider and self.scheduled_date:
            from availability.models import BusyDay
            BusyDay.objects.get_or_create(
                partner=self.provider,
                service=None,  # Partner-level busy day
                date=self.scheduled_date,
                defaults={
                    'entity_type': BusyDay.EntityType.PARTNER,
                    'marked_by': BusyDay.MarkedBy.SYSTEM,
                    'reason': f'Booked: {self.booking_id}',
                    'booking': self,
                },
            )

        # Cascade: when booking is cancelled, expired, or completed, expire all pending offers
        # AND remove auto-created busy days
        if self.status in (self.Status.CANCELLED, self.Status.EXPIRED, self.Status.COMPLETED):
            self.offers.filter(
                status=BookingOffer.Status.PENDING,
            ).update(
                status=BookingOffer.Status.EXPIRED,
                responded_at=timezone.now(),
            )
            # Remove system-created busy days for this booking
            from availability.models import BusyDay
            BusyDay.objects.filter(booking=self).delete()

    def __str__(self):
        name = self.service.title if self.service else (self.category.name if self.category else "Unknown")
        return f"{self.booking_id} - {name}"

    class Meta:
        ordering = ['-created_at']


class InstantBookingRequest(models.Model):
    """
    Broadcast table: fans out one booking to N nearby providers.
    First provider to accept wins (first-come-first-serve).

    Code refers to this model as ``BookingOffer`` (alias below). The model keeps
    its original name because migrations are generated on each server, and
    Django's makemigrations cannot detect a model rename on its own: it would
    drop this table and create an empty one.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Awaiting Response'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        DECLINED = 'DECLINED', 'Declined'
        EXPIRED = 'EXPIRED', 'Expired (Timed Out)'

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='offers')
    provider = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name='booking_offers')

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    broadcast_round = models.PositiveIntegerField(
        default=1, help_text="Broadcast round: 1 = initial, 2 = re-broadcast with expanded radius"
    )

    notified_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    response_deadline = models.DateTimeField(
        null=True, blank=True,
        help_text="Per-provider response deadline (distinct from overall booking expiry)"
    )

    # Provider's distance from customer at time of request
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = 'booking offer'
        verbose_name_plural = 'booking offers'
        ordering = ['distance_km', 'notified_at']
        unique_together = ('booking', 'provider', 'broadcast_round')  # Allow same provider in different rounds

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache original status to detect transitions in save()
        self._original_status = self.status

    def save(self, *args, **kwargs):
        transitioning_to_accepted = (
            self._original_status != self.Status.ACCEPTED
            and self.status == self.Status.ACCEPTED
        )

        if transitioning_to_accepted:
            self.responded_at = self.responded_at or timezone.now()

        super().save(*args, **kwargs)

        # Cascade: when an offer is accepted (e.g. via admin),
        # assign provider to booking, confirm booking, expire other offers.
        if transitioning_to_accepted:
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(pk=self.booking_id)
                if booking.status == Booking.Status.SEARCHING:
                    booking.provider = self.provider
                    booking.status = Booking.Status.CONFIRMED
                    booking.assigned_at = timezone.now()
                    booking.save()

                # Expire all other pending offers for this booking
                BookingOffer.objects.filter(
                    booking_id=self.booking_id,
                    status=self.Status.PENDING,
                ).exclude(pk=self.pk).update(
                    status=self.Status.EXPIRED,
                    responded_at=timezone.now(),
                )

        # Update cached status after save
        self._original_status = self.status

    def __str__(self):
        return f"{self.booking.booking_id} → {self.provider.user.phone_number} [R{self.broadcast_round}:{self.status}]"


# The name the code uses for the broadcast table (see InstantBookingRequest).
BookingOffer = InstantBookingRequest


class ProviderContact(models.Model):
    """
    A customer found a provider in the app ("Find yourself") and called them
    directly. Not a booking: Farmo did not arrange the job. One row per call;
    the outcome comes from the customer's answer after the call.
    """
    class Outcome(models.TextChoices):
        CALLED = 'CALLED', 'Called, no answer yet'
        AGREED = 'AGREED', 'Provider agreed'
        NOT_AGREED = 'NOT_AGREED', 'Provider did not agree'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='provider_contacts'
    )
    provider = models.ForeignKey(
        PartnerProfile, on_delete=models.CASCADE, related_name='customer_contacts'
    )
    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts',
        help_text="The listing the customer called from"
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='provider_contacts'
    )

    # How much work the customer asked about
    quantity = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    price_unit = models.CharField(max_length=20, blank=True, default='')
    listed_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="The service's listed price when the customer called (the agreed price is unknown)"
    )

    address = models.TextField(blank=True, default='')
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    note = models.TextField(blank=True, default='')

    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.CALLED)
    responded_at = models.DateTimeField(
        null=True, blank=True, help_text="When the customer answered after the call"
    )
    legacy_booking_id = models.CharField(
        max_length=20, blank=True, default='',
        help_text="Booking ID of the old scheduled booking this record was moved from"
    )

    # A plain default (not auto_now_add) so moved records keep their original date.
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['provider', '-created_at'], name='contact_provider_created_idx'),
            models.Index(fields=['customer', '-created_at'], name='contact_customer_created_idx'),
        ]

    def __str__(self):
        name = self.service.title if self.service else (self.category.name if self.category else "Unknown")
        return f"{self.customer.phone_number} → {self.provider.user.phone_number} ({name}) [{self.outcome}]"
