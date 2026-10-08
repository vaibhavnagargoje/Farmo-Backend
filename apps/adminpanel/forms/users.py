"""User registration, account, customer profile, and location forms."""

from django import forms
from django.utils import timezone

from users.models import CustomerProfile, User

from .widgets import _apply


class UserInfoForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["role", "is_active", "email", "preferred_language"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        if "email" in self.fields:
            self.fields["email"].required = False
            self.fields["email"].widget.attrs["placeholder"] = "farmer@example.com (optional)"


class CustomerProfileAdminForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ["full_name", "gender", "date_of_birth", "age", "profile_picture"]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields["full_name"].widget.attrs["placeholder"] = "Full name"
        self.fields["full_name"].required = False
        if "age" in self.fields:
            self.fields["age"].widget.attrs.update({"placeholder": "e.g. 35", "min": "1", "max": "120"})


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
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        label="Date of Birth",
    )
    age = forms.IntegerField(
        min_value=1,
        max_value=120,
        required=False,
        label="Age",
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
        self.fields["date_of_birth"].widget.attrs.update({"id": "id_date_of_birth"})
        self.fields["age"].widget.attrs.update({
            "id": "id_age",
            "placeholder": "e.g. 35",
            "min": "1",
            "max": "120",
        })
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

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob:
            today = timezone.now().date()
            if dob > today:
                raise forms.ValidationError("Date of birth cannot be in the future.")
        return dob

    def clean(self):
        cleaned_data = super().clean()
        dob = cleaned_data.get("date_of_birth")
        age = cleaned_data.get("age")
        if dob and not age:
            today = timezone.now().date()
            calculated_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            cleaned_data["age"] = max(0, calculated_age)
        return cleaned_data
