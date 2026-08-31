from django.contrib import admin
from .models import PartnerProfile, MachineryDetails, TransportDetails
from labor_services.models import LaborDetails, LaborServiceOffering


class LaborServiceOfferingPartnerInline(admin.TabularInline):
    model = LaborServiceOffering
    extra = 1
    autocomplete_fields = ('service_type',)
    fields = ('service_type', 'price', 'price_unit', 'note')


class LaborDetailsInline(admin.StackedInline):
    model = LaborDetails
    can_delete = False
    extra = 0
    # Note: service_types M2M now uses through model, managed via LaborServiceOfferingPartnerInline
    # in the standalone LaborDetails admin or via labor_services admin


class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'partner_type', 'is_verified', 'rating')
    list_filter = ('partner_type', 'is_verified')
    search_fields = ('user__phone_number',)
    inlines = [LaborDetailsInline]

admin.site.register(PartnerProfile, PartnerProfileAdmin)
admin.site.register(MachineryDetails)
admin.site.register(TransportDetails)

