"""Service and service image forms."""

from django import forms

from services.models import Service, ServiceImage

from .widgets import _apply


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


class ServiceImageAdminForm(forms.ModelForm):
    class Meta:
        model = ServiceImage
        fields = ["image", "is_thumbnail"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
