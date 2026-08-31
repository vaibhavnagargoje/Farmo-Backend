from django.db import models


class LaborPriceUnit(models.Model):
    """
    Standard pricing units for labor services (e.g. Per Day, Per Pump).
    Replaces the old static PriceUnit choices so admins can add/edit them.
    """
    name = models.CharField(max_length=50, help_text="e.g., Per Day")
    name_translations = models.JSONField(
        default=dict, blank=True,
        help_text='{"mr": "प्रति दिवस", "hi": "प्रति दिन", "en": "Per Day"}'
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Labor Price Unit'
        verbose_name_plural = 'Labor Price Units'

    def __str__(self):
        return self.name

    def get_name(self, language_code='en'):
        return self.name_translations.get(language_code, self.name)


class LaborCategory(models.Model):
    """
    Top-level sector grouping for labor work.
    Mirrors services.Category for equipment.
    Examples: शेतीकामे (Farming), बांधकाम (Construction), कुशल कामगार (Skilled Trade)
    """
    name = models.CharField(max_length=100, unique=True)
    name_translations = models.JSONField(
        default=dict, blank=True,
        help_text='{"mr": "शेतीकामे", "hi": "खेती के काम", "en": "Farming"}'
    )
    slug = models.SlugField(max_length=100, unique=True)
    icon = models.ImageField(upload_to='labor_categories/icons/', blank=True, null=True)
    cover_image = models.ImageField(upload_to='labor_categories/covers/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Labor Category'
        verbose_name_plural = 'Labor Categories'

    def __str__(self):
        return self.name

class LaborServiceType(models.Model):
    """
    Specific type of labor work within a category.
    Replaces the old flat LaborSkill.
    Examples: खुरपणी (Weeding), गवंडी (Mason), वेल्डर (Welder)
    """
    category = models.ForeignKey(
        LaborCategory, on_delete=models.CASCADE, related_name='service_types'
    )
    name = models.CharField(max_length=100, unique=True)
    name_translations = models.JSONField(
        default=dict, blank=True,
        help_text='{"mr": "खुरपणी", "hi": "निराई", "en": "Weeding"}'
    )
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    icon = models.ImageField(upload_to='labor_service_types/icons/', blank=True, null=True)
    cover_image = models.ImageField(
        upload_to='labor_service_types/covers/', blank=True, null=True,
        help_text="Photo representing this type of work"
    )
    default_price_unit = models.ForeignKey(
        LaborPriceUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Suggested default unit for this type of work (e.g. Per Pump for spraying)"
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Labor Service Type'
        verbose_name_plural = 'Labor Service Types'

    def __str__(self):
        return f"{self.category.name} -> {self.name}"

    def get_name(self, language_code='en'):
        return self.name_translations.get(language_code, self.name)

class LaborDetails(models.Model):
    """
    Extra details if partner_type == LABOR
    Moved from partners app to labor_services app.
    """
    partner = models.OneToOneField('partners.PartnerProfile', on_delete=models.CASCADE, related_name='labor_details')
    
    # Specifics
    skill_card_photo = models.ImageField(upload_to='partners/skills/', blank=True, null=True)
    daily_wage_estimate = models.DecimalField(
        max_digits=8, decimal_places=2, null=True,
        help_text="Headline / average wage — real per-skill prices live in LaborServiceOffering"
    )
    is_migrant_worker = models.BooleanField(default=False)
    
    # Service types linked via through model for per-skill pricing
    # service_types = models.ManyToManyField(
    #     LaborServiceType,
    #     through='LaborServiceOffering',
    #     related_name='labor_profiles',
    #     blank=True,
    # )
    
    def __str__(self):
        return f"Labor Details: {self.partner.user.phone_number}"


class LaborServiceOffering(models.Model):
    """
    Through model: stores per-skill price, unit, and optional note
    for each service type a labor partner offers.
    
    Example rows:
      labor_details=1, service_type="Tractor Driving", price=600, unit=1
      labor_details=1, service_type="Dose Spraying",   price=60,  unit=2, note="20L pump"
      labor_details=1, service_type="Mason",            price=1000, unit=1, note="Mistri"
    """
    labor_details = models.ForeignKey(
        LaborDetails, on_delete=models.CASCADE, related_name='offerings'
    )
    service_type = models.ForeignKey(
        LaborServiceType, on_delete=models.CASCADE, related_name='offerings'
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_unit = models.ForeignKey(
        LaborPriceUnit,
        on_delete=models.PROTECT,
        help_text="The unit of pricing (e.g. Per Day)"
    )
    note = models.TextField(
        blank=True,
        help_text="Optional note, e.g. '20L pump only', 'with own tractor'"
    )

    class Meta:
        unique_together = ('labor_details', 'service_type')
        verbose_name = 'Labor Service Offering'
        verbose_name_plural = 'Labor Service Offerings'

    def __str__(self):
        return f"{self.service_type.name} — ₹{self.price}/{self.price_unit.name}"
