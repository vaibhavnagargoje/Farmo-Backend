from django import forms

from locations.models import UserLocation
from partners.models import MachineryDetails, PartnerProfile, TransportDetails
from labor_services.models import LaborDetails, LaborServiceType
from services.models import Category, Service, ServiceImage
from users.models import CustomerProfile, User

# ─────────────────────────────────────────────────────────────────────────────
# Shared widget helpers
# ─────────────────────────────────────────────────────────────────────────────

TEXT_ATTRS = {"class": "form-input"}
TEXTAREA_ATTRS = {"class": "form-input", "rows": 3}
FILE_ATTRS = {"class": "form-input"}
SELECT_ATTRS = {"class": "form-input"}


def _apply(fields, mapping=None):
    """Apply standard widget attrs to every field in a ModelForm."""
    if mapping is None:
        mapping = {}
    for name, field in fields.items():
        if name in mapping:
            field.widget.attrs.update(mapping[name])
        elif isinstance(field.widget, forms.Textarea):
            field.widget.attrs.update(TEXTAREA_ATTRS)
        elif isinstance(field.widget, (forms.ClearableFileInput, forms.FileInput)):
            field.widget.attrs.update(FILE_ATTRS)
        elif isinstance(field.widget, forms.Select):
            field.widget.attrs.update(SELECT_ATTRS)
        elif isinstance(field.widget, forms.CheckboxInput):
            pass  # handled by toggle UI in template
        else:
            field.widget.attrs.update(TEXT_ATTRS)



# ─────────────────────────────────────────────────────────────────────────────
# 2. User Info (role + active status)
# ─────────────────────────────────────────────────────────────────────────────

class UserInfoForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Customer Profile
# ─────────────────────────────────────────────────────────────────────────────

class CustomerProfileAdminForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ["full_name", "gender", "profile_picture"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["full_name"].widget.attrs["placeholder"] = "Full name"
        self.fields["full_name"].required = False


# ─────────────────────────────────────────────────────────────────────────────
# 4. User Location
# ─────────────────────────────────────────────────────────────────────────────

class UserLocationForm(forms.Form):
    address = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Address",
    )
    latitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False, label="Latitude")
    longitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False, label="Longitude")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["address"].widget.attrs["placeholder"] = "Village / Taluka / District"
        self.fields["latitude"].widget.attrs["placeholder"] = "18.520430"
        self.fields["longitude"].widget.attrs["placeholder"] = "73.856744"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Partner Profile
# ─────────────────────────────────────────────────────────────────────────────

class PartnerProfileAdminForm(forms.ModelForm):
    class Meta:
        model = PartnerProfile
        fields = [
            "partner_type", "business_name", "about",
            "is_verified", "is_kyc_submitted", "rejected_reason",
            "aadhar_card_front", "aadhar_card_back", "pan_card",
            "is_available",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["business_name"].widget.attrs["placeholder"] = "Business / display name"
        self.fields["about"].widget.attrs["placeholder"] = "Short bio or description of services"
        self.fields["rejected_reason"].widget.attrs["placeholder"] = "Reason for rejection (if any)"
        self.fields["rejected_reason"].required = False
        self.fields["business_name"].required = False
        self.fields["about"].required = False



# ─────────────────────────────────────────────────────────────────────────────
# 7. Machinery Details
# ─────────────────────────────────────────────────────────────────────────────

class MachineryDetailsAdminForm(forms.ModelForm):
    class Meta:
        model = MachineryDetails
        fields = ["fleet_size", "owner_dl_number", "owner_dl_photo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["owner_dl_number"].widget.attrs["placeholder"] = "Driving licence number"
        self.fields["fleet_size"].widget.attrs["placeholder"] = "1"
        self.fields["owner_dl_number"].required = False


class TransportDetailsAdminForm(forms.ModelForm):
    class Meta:
        model = TransportDetails
        fields = [
            "driving_license_number", "driving_license_photo",
            "vehicle_insurance_photo", "is_intercity_available",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["driving_license_number"].widget.attrs["placeholder"] = "DL number"
        self.fields["driving_license_number"].required = False


# ─────────────────────────────────────────────────────────────────────────────
# 9. Service
# ─────────────────────────────────────────────────────────────────────────────

class ServiceAdminForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            "category", "title", "description",
            "price", "price_unit", "min_order_qty",
            "status", "is_available", "service_radius_km",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["title"].widget.attrs["placeholder"] = "Service title"
        self.fields["description"].widget.attrs["placeholder"] = "Describe the service..."
        self.fields["price"].widget.attrs["placeholder"] = "e.g. 500"
        self.fields["service_radius_km"].widget.attrs["placeholder"] = "e.g. 10"
        self.fields["min_order_qty"].widget.attrs["placeholder"] = "e.g. 1"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Labor Details
# ─────────────────────────────────────────────────────────────────────────────

class LaborDetailsAdminForm(forms.ModelForm):
    service_types = forms.ModelMultipleChoiceField(
        queryset=LaborServiceType.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Service Types",
    )

    class Meta:
        model = LaborDetails
        fields = ["daily_wage_estimate", "service_types", "skill_card_photo", "is_migrant_worker"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["daily_wage_estimate"].widget.attrs["placeholder"] = "e.g. 800"
        self.fields["daily_wage_estimate"].required = False
        self.fields["service_types"].label_from_instance = lambda obj: obj.get_name('mr')


# ─────────────────────────────────────────────────────────────────────────────
# 10. Service Image
# ─────────────────────────────────────────────────────────────────────────────

class ServiceImageAdminForm(forms.ModelForm):
    class Meta:
        model = ServiceImage
        fields = ["image", "is_thumbnail"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Add User (combined: User + CustomerProfile + UserLocation)
# ─────────────────────────────────────────────────────────────────────────────

class AddUserForm(forms.Form):
    """
    Single combined form for admin to create a new user with:
    - User account fields (phone, email, language, active status)
    - CustomerProfile fields (full name, gender)
    - UserLocation fields (address + coordinates via JS GPS)

    NOTE: Role is intentionally excluded — all users created via this form
    are assigned the CUSTOMER role by default for security reasons.
    Admins/SuperAdmins can change the role later from the user detail page.
    """

    # ── Account ───────────────────────────────────────────────────────────────
    phone_number = forms.CharField(
        max_length=15,
        label="Phone Number",
        help_text="Primary login identifier, e.g. +919876543210",
    )
    email = forms.EmailField(
        required=False,
        label="Email Address",
        help_text="Optional",
    )
    preferred_language = forms.ChoiceField(
        choices=User.Language.choices,
        initial=User.Language.ENGLISH,
        label="Preferred Language",
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        label="Active",
        help_text="User can log in immediately after creation",
    )

    # ── Customer Profile ──────────────────────────────────────────────────────
    full_name = forms.CharField(
        max_length=255,
        required=False,
        label="Full Name",
    )
    gender = forms.ChoiceField(
        choices=[("", "— Select gender —")] + list(CustomerProfile.Gender.choices),
        required=False,
        label="Gender",
    )

    # ── Location ──────────────────────────────────────────────────────────────
    address = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Address",
        help_text="Village / Taluka / District",
    )
    latitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        label="Latitude",
        help_text="Auto-filled via GPS",
    )
    longitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        label="Longitude",
        help_text="Auto-filled via GPS",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["phone_number"].widget.attrs.update({"placeholder": "+91 98765 43210"})
        self.fields["email"].widget.attrs.update({"placeholder": "farmer@example.com (optional)"})
        self.fields["full_name"].widget.attrs.update({"placeholder": "Full name of the user"})
        self.fields["address"].widget.attrs.update({"placeholder": "e.g. At. Shirur, Tal. Shirur, Dist. Pune"})
        self.fields["latitude"].widget.attrs.update({
            "placeholder": "18.520430",
            "readonly": "readonly",
            "id": "id_latitude",
        })
        self.fields["longitude"].widget.attrs.update({
            "placeholder": "73.856744",
            "readonly": "readonly",
            "id": "id_longitude",
        })

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        if User.objects.filter(phone_number=phone).exists():
            raise forms.ValidationError("A user with this phone number already exists.")
        return phone

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if not email:
            return None  # Store as NULL, not empty string
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email
