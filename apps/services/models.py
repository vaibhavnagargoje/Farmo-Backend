from django.db import models
from django.conf import settings
# Import PartnerProfile to link specifically to the business entity
from partners.models import PartnerProfile 

class Category(models.Model):
    """
    Examples: 
    - Agriculture Machinery
    - Construction Labor
    - Goods Transport
    """
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    icon = models.ImageField(upload_to='categories/icons/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Service(models.Model):
    """
    The main listing created by a Partner.
    """
    class PriceUnit(models.TextChoices):
        PER_HOUR = 'HOUR', 'Per Hour'
        PER_DAY = 'DAY', 'Per Day'
        PER_KM = 'KM', 'Per Kilometer'
        PER_ACRE = 'ACRE', 'Per Acre'
        FIXED = 'FIXED', 'Fixed Price'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'            # Partner is still writing it
        PENDING = 'PENDING', 'Pending Approval' # Waiting for Admin
        ACTIVE = 'ACTIVE', 'Active'          # Live on app
        REJECTED = 'REJECTED', 'Rejected'    # Admin said no
        HIDDEN = 'HIDDEN', 'Hidden (Paused)' # Partner paused it

    # --- 1. CRITICAL FIX: Link to PartnerProfile, not User ---
    partner = models.ForeignKey(
        PartnerProfile, 
        on_delete=models.CASCADE, 
        related_name='services'
    )
    
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    
    title = models.CharField(max_length=255)
    description = models.TextField()
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_unit = models.CharField(max_length=10, choices=PriceUnit.choices, default=PriceUnit.PER_HOUR)
    
    # --- 2. ADDED: Business Logic Constraints ---
    min_order_qty = models.DecimalField(
        max_digits=5, decimal_places=1, default=1, 
        help_text="Minimum Booking (e.g., 1 hour, or 2 acres)"
    )

    # Status & Availability
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    is_available = models.BooleanField(default=True) # "Currently Busy" switch
    
    # Geolocation
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    service_radius_km = models.PositiveIntegerField(default=10)

    # Technical Specs
    specifications = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.partner.business_name}"

class ServiceImage(models.Model):
    """
    Multiple images for one service
    """
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='services/images/')
    is_thumbnail = models.BooleanField(default=False)