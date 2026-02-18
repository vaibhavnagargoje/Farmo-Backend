# apps/partners/models.py
from django.db import models
from django.conf import settings # To refer to the User model

class PartnerProfile(models.Model):
    """
    The Master Profile for any Service Provider.
    Contains Common KYC, Bank info, and Verification Status.
    """
    class PartnerType(models.TextChoices):
        LABOR = "LABOR", "Manual Worker"
        MACHINERY_OWNER = "MACHINERY", "Machinery Owner (Tractor/Harvester)"
        TRANSPORTER = "TRANSPORT", "Vehicle Owner (Tempo/Truck)"
        AGENCY = "AGENCY", "Agency (Multiple Services)"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='partner_profile')
    
    # Classification
    partner_type = models.CharField(max_length=20, choices=PartnerType.choices)
    
    # Business Info
    business_name = models.CharField(max_length=255, help_text="Name displayed to customers")
    about = models.TextField(blank=True, help_text="Bio or Description of services")
    
    # KYC & Verification
    is_verified = models.BooleanField(default=False)
    is_kyc_submitted = models.BooleanField(default=False)
    rejected_reason = models.TextField(blank=True, null=True)

    # Documents (Common)
    aadhar_card_front = models.ImageField(upload_to='partners/kyc/', blank=True, null=True)
    aadhar_card_back = models.ImageField(upload_to='partners/kyc/', blank=True, null=True)
    pan_card = models.ImageField(upload_to='partners/kyc/', blank=True, null=True)
    
    # Base Location (Where they are based)
    base_city = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Availability (Online/Offline toggle)
    is_available = models.BooleanField(default=True, help_text="Partner is online and accepting jobs")
    
    # Metrics
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0)
    jobs_completed = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.business_name} [{self.partner_type}]"


# --- Specific Details based on Type ---

class LaborDetails(models.Model):
    """
    Extra details if partner_type == LABOR
    """
    partner = models.OneToOneField(PartnerProfile, on_delete=models.CASCADE, related_name='labor_details')
    
    # Specifics
    skill_card_photo = models.ImageField(upload_to='partners/skills/', blank=True, null=True)
    daily_wage_estimate = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    is_migrant_worker = models.BooleanField(default=False)
    
    # Skills (List of strings or ManyToMany in a real scenario)
    skills = models.TextField(help_text="Comma separated: Mason, Helper, Harvester") 

    def __str__(self):
        return f"Labor Details: {self.partner.business_name}"


class MachineryDetails(models.Model):
    """
    Extra details if partner_type == MACHINERY
    """
    partner = models.OneToOneField(PartnerProfile, on_delete=models.CASCADE, related_name='machinery_details')
    
    owner_dl_number = models.CharField(max_length=50, blank=True)
    owner_dl_photo = models.ImageField(upload_to='partners/machinery/', blank=True, null=True)
    
    fleet_size = models.IntegerField(default=1, help_text="How many machines do they own?")
    
    def __str__(self):
        return f"Machinery Owner: {self.partner.business_name}"


class TransportDetails(models.Model):
    """
    Extra details if partner_type == TRANSPORT
    """
    partner = models.OneToOneField(PartnerProfile, on_delete=models.CASCADE, related_name='transport_details')
    
    driving_license_number = models.CharField(max_length=50)
    driving_license_photo = models.ImageField(upload_to='partners/transport/', blank=True, null=True)
    
    vehicle_insurance_photo = models.ImageField(upload_to='partners/transport/', blank=True, null=True)
    
    is_intercity_available = models.BooleanField(default=False, help_text="Can go to other cities?")

    def __str__(self):
        return f"Transporter: {self.partner.business_name}"