# apps/users/models.py
import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.utils.translation import gettext_lazy as _
from .managers import CustomUserManager 

class User(AbstractUser):
    """
    Core User Model. Handles Login and Roles.
    """
    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        PARTNER = "PARTNER", "Service Provider"
        MANAGER = "MANAGER", "Verification Manager"
        ADMIN = "ADMIN", "Admin"
        SUPERADMIN = "SUPERADMIN", "Super Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None  # We use email/phone login
    email = models.EmailField(_('email address'), unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=15, unique=True, help_text="Primary Login Method")
    
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    
    # Standard Django fields (is_staff, is_active) are inherited from AbstractUser
    
    USERNAME_FIELD = 'phone_number' 
    REQUIRED_FIELDS = ['email']

    objects = CustomUserManager()

    # Fix for reverse accessor clashes
    groups = models.ManyToManyField(
        Group,
        verbose_name=_('groups'),
        blank=True,
        help_text=_('The groups this user belongs to.'),
        related_name="custom_user_set",
        related_query_name="user",
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name=_('user permissions'),
        blank=True,
        help_text=_('Specific permissions for this user.'),
        related_name="custom_user_permissions_set",
        related_query_name="user",
    )

    def __str__(self):
        return f"{self.phone_number} ({self.role})"
    
    @property
    def is_partner_user(self):
        return self.role == self.Role.PARTNER


class CustomerProfile(models.Model):
    """
    Specific details for the 'Seeker' (User who needs labor/machines).
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    
    # Basic Profile
    full_name = models.CharField(max_length=255, blank=True, default="") 
    profile_picture = models.ImageField(upload_to='customers/avatars/', blank=True, null=True)
    
    # Location – lat/lng/address stored directly on profile
    user_address = models.TextField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Optional location hierarchy (State > District > Tahsil)
    state = models.ForeignKey(
        'locations.State',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_profiles',
    )
    district = models.ForeignKey(
        'locations.District',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_profiles',
    )
    tahsil = models.ForeignKey(
        'locations.Tahsil',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_profiles',
    )
    village = models.ForeignKey(
        'locations.Village',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_profiles',
    )

    def __str__(self):
        return f"Customer: {self.full_name}"