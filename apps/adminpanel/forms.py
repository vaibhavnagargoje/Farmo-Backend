from django import forms

from partners.models import LaborDetails, MachineryDetails, PartnerProfile, TransportDetails
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
# 1. Register new user (used by old VLE flow + "Add User" in new panel)
# ─────────────────────────────────────────────────────────────────────────────

MARATHI_SKILLS = [
    "गवंडी", "मदतनीस", "कापणी कामगार", "नांगरणी", "खुरपणी",
    "फवारणी", "हमाल", "चालक", "सुतार", "पेंटर",
    "इलेक्ट्रिशियन", "प्लंबर", "शेतीकाम", "पेरणी",
]


class AgentUserRegistrationForm(forms.Form):
    phone_number = forms.CharField(max_length=15, label="Mobile Number",
                                   error_messages={"required": "Mobile number is required."})
    email = forms.EmailField(required=False, label="Email (optional)")
    full_name = forms.CharField(max_length=255, label="Full Name",
                                error_messages={"required": "Full name is required."})
    profile_picture = forms.ImageField(required=False, label="Profile Photo (optional)")
    address = forms.CharField(label="Address", widget=forms.Textarea(attrs={"rows": 3}), required=False)
    latitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False, label="Latitude")
    longitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False, label="Longitude")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["phone_number"].widget.attrs["placeholder"] = "e.g. 9876543210"
        self.fields["email"].widget.attrs["placeholder"] = "example@email.com"
        self.fields["full_name"].widget.attrs["placeholder"] = "Full name"
        self.fields["address"].widget.attrs["placeholder"] = "Village / Taluka / District"
        self.fields["latitude"].widget.attrs["placeholder"] = "18.520430"
        self.fields["longitude"].widget.attrs["placeholder"] = "73.856744"

    def clean_phone_number(self):
        phone = self.cleaned_data["phone_number"].strip()
        if User.objects.filter(phone_number=phone).exists():
            raise forms.ValidationError(
                f"A user with phone {phone} is already registered. "
                "Search for them in the Users list instead."
            )
        return phone

    def clean_email(self):
        raw = self.cleaned_data.get("email") or ""
        email = raw.strip().lower()
        if not email:
            # Leave email as None — don't store empty strings
            return None
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                f"Email {email} is already linked to another account. "
                "Leave this blank or use a different email."
            )
        return email


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
        fields = ["full_name", "profile_picture"]

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
# 6. Labor Details
# ─────────────────────────────────────────────────────────────────────────────

class LaborDetailsAdminForm(forms.ModelForm):
    skills = forms.MultipleChoiceField(
        choices=[(s, s) for s in MARATHI_SKILLS],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Skills",
    )

    class Meta:
        model = LaborDetails
        fields = ["daily_wage_estimate", "skills", "skill_card_photo", "is_migrant_worker"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["daily_wage_estimate"].widget.attrs["placeholder"] = "e.g. 800"
        self.fields["daily_wage_estimate"].required = False

        instance = kwargs.get("instance")
        if instance and instance.pk and instance.skills:
            self.initial["skills"] = [s.strip() for s in instance.skills.split(",") if s.strip()]

    def clean_skills(self):
        selected = self.cleaned_data.get("skills") or []
        return ", ".join(selected)


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


# ─────────────────────────────────────────────────────────────────────────────
# 8. Transport Details
# ─────────────────────────────────────────────────────────────────────────────

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
# Legacy VLE forms (kept for the old registration flow)
# ─────────────────────────────────────────────────────────────────────────────

class WorkerPartnerProfileForm(forms.ModelForm):
    class Meta:
        model = PartnerProfile
        fields = ["aadhar_card_front", "aadhar_card_back", "pan_card"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        css = (
            "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 "
            "text-sm text-slate-900 file:mr-3 file:rounded-md file:border-0 "
            "file:bg-slate-100 file:px-3 file:py-2 file:text-slate-700"
        )
        for name in ("aadhar_card_front", "aadhar_card_back", "pan_card"):
            self.fields[name].required = False
            self.fields[name].widget.attrs.update({"class": css})

    def clean(self):
        cleaned_data = super().clean()
        has_front = bool(
            cleaned_data.get("aadhar_card_front")
            or (self.instance and getattr(self.instance, "aadhar_card_front", None))
        )
        has_back = bool(
            cleaned_data.get("aadhar_card_back")
            or (self.instance and getattr(self.instance, "aadhar_card_back", None))
        )
        has_pan = bool(
            cleaned_data.get("pan_card")
            or (self.instance and getattr(self.instance, "pan_card", None))
        )
        if not has_pan and not (has_front and has_back):
            raise forms.ValidationError(
                "Aadhaar (front & back) or PAN card — at least one document is required."
            )
        return cleaned_data


class LaborDetailsForm(forms.ModelForm):
    skills = forms.MultipleChoiceField(
        choices=[(s, s) for s in MARATHI_SKILLS],
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="कौशल्ये",
        error_messages={"required": "किमान एक कौशल्य निवडा."},
    )
    is_migrant_worker = forms.ChoiceField(
        choices=(("yes", "होय"), ("no", "नाही")),
        widget=forms.RadioSelect,
        label="स्थलांतरित कामगार आहे का?",
        required=True,
    )

    class Meta:
        model = LaborDetails
        fields = ["daily_wage_estimate", "skills", "skill_card_photo", "is_migrant_worker"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field_css = (
            "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 "
            "text-sm text-slate-900 focus:border-emerald-500 focus:outline-none "
            "focus:ring-2 focus:ring-emerald-200"
        )
        file_css = (
            "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 "
            "text-sm text-slate-900 file:mr-3 file:rounded-md file:border-0 "
            "file:bg-slate-100 file:px-3 file:py-2 file:text-slate-700"
        )
        self.fields["daily_wage_estimate"].required = True
        self.fields["daily_wage_estimate"].widget.attrs.update({"class": field_css, "placeholder": "उदा. ८००"})
        self.fields["daily_wage_estimate"].label = "दैनिक मजुरी"
        self.fields["skills"].widget.attrs.update({"class": "peer sr-only"})
        self.fields["skill_card_photo"].required = False
        self.fields["skill_card_photo"].widget.attrs.update({"class": file_css})
        self.fields["skill_card_photo"].label = "कौशल्य कार्ड फोटो (ऐच्छिक)"
        self.fields["is_migrant_worker"].widget.attrs.update({"class": "peer sr-only"})

        instance = kwargs.get("instance")
        if instance and instance.pk:
            self.initial["is_migrant_worker"] = "yes" if instance.is_migrant_worker else "no"
            self.initial["skills"] = [s.strip() for s in (instance.skills or "").split(",") if s.strip()]

    def clean_skills(self):
        selected = self.cleaned_data.get("skills") or []
        if not selected:
            raise forms.ValidationError("किमान एक कौशल्य निवडा.")
        return ", ".join(selected)

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["is_migrant_worker"] = cleaned_data.get("is_migrant_worker") == "yes"
        return cleaned_data
