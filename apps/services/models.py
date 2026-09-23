from django.db import models
from django.conf import settings
# Import PartnerProfile to link specifically to the business entity
from partners.models import PartnerProfile 


class ServicePriceUnit(models.Model):
    """
    Dynamic pricing units for machinery/equipment services (e.g. Per Hour, Per Acre).
    Replaces the old static PriceUnit TextChoices so admins can add/edit them.
    Mirrors LaborPriceUnit from labor_services app.
    """
    key = models.CharField(
        max_length=20, unique=True,
        help_text="Internal key e.g. 'HOUR', 'ACRE' — used for backward compat"
    )
    name = models.CharField(max_length=50, help_text="e.g., Per Hour")
    name_translations = models.JSONField(
        default=dict, blank=True,
        help_text='{"mr": "प्रति तास", "hi": "प्रति घंटा", "en": "Per Hour"}'
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Service Price Unit'
        verbose_name_plural = 'Service Price Units'

    def __str__(self):
        return self.name

    def get_name(self, language_code='en'):
        return self.name_translations.get(language_code, self.name)


class Category(models.Model):
    """
    Examples: 
    - Agriculture Machinery
    - Construction Labor
    - Goods Transport
    """
    name = models.CharField(max_length=100)
    name_translations = models.JSONField(
        default=dict, blank=True,
        help_text='Translations: {"mr": "मराठी नाव", "hi": "हिंदी नाम"}'
    )
    slug = models.SlugField(unique=True)
    icon = models.ImageField(upload_to='categories/icons/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    # ── Instant Booking Pricing (set by Admin) ──
    instant_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Base price for instant bookings in this category (set by admin)"
    )
    instant_price_unit = models.ForeignKey(
        ServicePriceUnit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='categories',
        help_text="Price unit for instant bookings"
    )
    instant_enabled = models.BooleanField(
        default=True,
        help_text="Allow instant (quick) bookings for this category"
    )
    instant_timeout_minutes = models.PositiveIntegerField(
        default=10,
        help_text="Minutes before an instant booking expires if no provider accepts"
    )
    instant_search_radius_km = models.PositiveIntegerField(
        default=15,
        help_text="Radius (km) to search for nearby providers for instant bookings"
    )

    def __str__(self):
        return self.name

class Service(models.Model):
    """
    The main listing created by a Partner.
    """
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
    description = models.TextField(blank=True)
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_unit = models.ForeignKey(
        ServicePriceUnit,
        on_delete=models.PROTECT,
        related_name='services',
        help_text="The unit of pricing (e.g. Per Hour, Per Acre)"
    )
    
    # --- 2. ADDED: Business Logic Constraints ---
    min_order_qty = models.DecimalField(
        max_digits=5, decimal_places=1, default=1, 
        help_text="Minimum Booking (e.g., 1 hour, or 2 acres)"
    )

    # Status & Availability
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    is_available = models.BooleanField(default=True) # "Currently Busy" switch
    
    # Geolocation — lat/lng comes from partner's UserLocation
    # (removed location_lat, location_lng — single source of truth is locations.UserLocation)
    service_radius_km = models.PositiveIntegerField(default=10)

    # Technical Specs
    specifications = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.partner.user.phone_number}"

class ServiceImage(models.Model):
    """
    Multiple images for one service
    """
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='services/images/')
    is_thumbnail = models.BooleanField(default=False)