from django.contrib import admin
from .models import PartnerProfile, MachineryDetails, TransportDetails
from labor_services.models import LaborDetails

class LaborDetailsInline(admin.StackedInline):
    model = LaborDetails
    can_delete = False
    filter_horizontal = ('service_types',)
    extra = 0

class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'partner_type', 'is_verified', 'rating')
    list_filter = ('partner_type', 'is_verified')
    search_fields = ('user__phone_number',)
    inlines = [LaborDetailsInline]

admin.site.register(PartnerProfile, PartnerProfileAdmin)
admin.site.register(MachineryDetails)
admin.site.register(TransportDetails)
