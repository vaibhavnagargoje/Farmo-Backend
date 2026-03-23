from django.contrib import admin
from .models import UserLocation
from .pricing_models import PricingZone


@admin.register(UserLocation)
class UserLocationAdmin(admin.ModelAdmin):
    list_display = ['user', 'address', 'latitude', 'longitude', 'updated_at']
    search_fields = ['user__phone_number', 'address']
    raw_id_fields = ['user']


@admin.register(PricingZone)
class PricingZoneAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'category', 'price', 'price_unit',
        'radius_km', 'is_default', 'is_active',
    )
    list_filter = ('category', 'is_active', 'is_default', 'price_unit')
    search_fields = ('name', 'category__name')
    list_editable = ('price', 'is_active')

    fieldsets = (
        ('Zone Identity', {
            'fields': ('category', 'name', 'is_active'),
        }),
        ('Geographic Center', {
            'description': (
                'Set the center point and radius for this pricing zone. '
                'Leave lat/lng blank for the default (fallback) zone.'
            ),
            'fields': ('center_lat', 'center_lng', 'radius_km'),
        }),
        ('Pricing', {
            'fields': ('price', 'price_unit', 'is_default'),
        }),
    )