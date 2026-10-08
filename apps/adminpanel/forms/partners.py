"""Provider profile, labor, machinery, and transport forms."""

from django import forms

from labor_services.models import LaborDetails, LaborServiceType
from partners.models import MachineryDetails, PartnerProfile, TransportDetails

from .widgets import _apply


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

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance
