from django.db import models
from django.conf import settings
from services.models import Service
from partners.models import PartnerProfile # Link to the Business, not just the User

class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Approval'
        CONFIRMED = 'CONFIRMED', 'Accepted by Provider'
        REJECTED = 'REJECTED', 'Rejected by Provider'
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
    
    # 2. The Service being booked
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='bookings')
    
    # 3. The Provider (The Business Entity fulfilling the job)
    # Changed from User -> PartnerProfile for consistency
    provider = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name='received_bookings')
    
    # --- JOB DETAILS ---
    booking_id = models.CharField(max_length=20, unique=True, editable=False) 
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    
    # Timing
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    
    # Tracking
    work_started_at = models.DateTimeField(null=True, blank=True)
    work_completed_at = models.DateTimeField(null=True, blank=True)

    # --- SECURITY (OTPs) ---
    # Code provider enters to start the job (Customer sees this code)
    start_job_otp = models.CharField(max_length=6, null=True, blank=True)
    # Code customer enters to finish the job
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

    def save(self, *args, **kwargs):
        # Auto-generate Booking ID
        if not self.booking_id:
            import uuid
            self.booking_id = f"BK-{uuid.uuid4().hex[:8].upper()}"
            
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
        return f"{self.booking_id} - {self.service.title}"