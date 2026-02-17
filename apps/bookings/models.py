from django.db import models
from django.conf import settings
from django.utils import timezone
from services.models import Service, Category
from partners.models import PartnerProfile # Link to the Business, not just the User

class Booking(models.Model):
    class BookingType(models.TextChoices):
        INSTANT = 'INSTANT', 'Instant (Quick Book)'
        SCHEDULED = 'SCHEDULED', 'Scheduled (Advanced)'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Approval'
        SEARCHING = 'SEARCHING', 'Searching for Providers'  # Instant: broadcast sent
        CONFIRMED = 'CONFIRMED', 'Accepted by Provider'
        REJECTED = 'REJECTED', 'Rejected by Provider'
        EXPIRED = 'EXPIRED', 'Expired (No Provider Found)'  # Instant: timeout
        IN_PROGRESS = 'IN_PROGRESS', 'Work Started'
        COMPLETED = 'COMPLETED', 'Work Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Payment Pending'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Payment Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    # --- BOOKING TYPE ---
    booking_type = models.CharField(
        max_length=20, choices=BookingType.choices, default=BookingType.SCHEDULED
    )

    # --- RELATIONS ---
    # 1. The Customer (User who needs the service)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    
    # 2. The Service being booked (optional for instant bookings)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='bookings', null=True, blank=True)
    
    # 3. The Category (required for instant bookings, auto-set for scheduled)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='bookings', null=True, blank=True)
    
    # 4. The Provider (nullable for instant — assigned when a provider accepts)
    provider = models.ForeignKey(
        PartnerProfile, on_delete=models.CASCADE, related_name='received_bookings',
        null=True, blank=True
    )
    
    # --- JOB DETAILS ---
    booking_id = models.CharField(max_length=20, unique=True, editable=False) 
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    
    # Timing (nullable for instant — defaults to now)
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    
    # Instant booking expiry
    expires_at = models.DateTimeField(null=True, blank=True, help_text="When this instant booking expires if no provider accepts")
    
    # Tracking
    work_started_at = models.DateTimeField(null=True, blank=True)
    work_completed_at = models.DateTimeField(null=True, blank=True)

    # --- SECURITY (OTPs) ---
    start_job_otp = models.CharField(max_length=6, null=True, blank=True)
    end_job_otp = models.CharField(max_length=6, null=True, blank=True)

    # Location
    address = models.TextField()
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True)

    # Financials (Snapshot Pattern)
    quantity = models.PositiveIntegerField(default=1, help_text="Number of Hours/Acres/Km")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2) 
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Meta
    note = models.TextField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True, null=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_bookings')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_expired(self):
        """Check if an instant booking has expired."""
        if self.booking_type == self.BookingType.INSTANT and self.expires_at:
            return timezone.now() > self.expires_at and self.status == self.Status.SEARCHING
        return False

    def save(self, *args, **kwargs):
        # Auto-generate Booking ID
        if not self.booking_id:
            import uuid
            prefix = "FB" if self.booking_type == self.BookingType.INSTANT else "BK"
            self.booking_id = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
        
        # For instant bookings, set defaults
        if self.booking_type == self.BookingType.INSTANT:
            if not self.scheduled_date:
                self.scheduled_date = timezone.now().date()
            if not self.scheduled_time:
                self.scheduled_time = timezone.now().time()
            if not self.expires_at and self.status == self.Status.SEARCHING:
                timeout = 10  # default
                if self.category and hasattr(self.category, 'instant_timeout_minutes'):
                    timeout = self.category.instant_timeout_minutes
                self.expires_at = timezone.now() + timezone.timedelta(minutes=timeout)
            
        # Generate OTPs if confirmed
        if self.status == self.Status.CONFIRMED and not self.start_job_otp:
            import random
            self.start_job_otp = str(random.randint(1000, 9999))
            self.end_job_otp = str(random.randint(1000, 9999))
        
        # Auto-Calculate Total
        if not self.total_amount and self.unit_price and self.quantity:
            self.total_amount = self.unit_price * self.quantity
            
        super().save(*args, **kwargs)

    def __str__(self):
        type_label = "⚡" if self.booking_type == self.BookingType.INSTANT else "📅"
        name = self.service.title if self.service else (self.category.name if self.category else "Unknown")
        return f"{type_label} {self.booking_id} - {name}"

    class Meta:
        ordering = ['-created_at']


class InstantBookingRequest(models.Model):
    """
    Broadcast table: fans out one instant booking request to N nearby providers.
    First provider to accept wins (first-come-first-serve).
    """
    class RequestStatus(models.TextChoices):
        PENDING = 'PENDING', 'Awaiting Response'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        DECLINED = 'DECLINED', 'Declined'
        EXPIRED = 'EXPIRED', 'Expired (Timed Out)'

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='instant_requests')
    provider = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name='instant_requests')
    
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    
    notified_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    
    # Provider's distance from customer at time of request
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['distance_km', 'notified_at']
        unique_together = ('booking', 'provider')  # One request per provider per booking

    def __str__(self):
        return f"{self.booking.booking_id} → {self.provider.business_name} [{self.status}]"