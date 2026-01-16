from django.contrib import admin
from .models import PartnerProfile, LaborDetails, MachineryDetails, TransportDetails

class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'partner_type', 'base_city', 'is_verified', 'rating')
    list_filter = ('partner_type', 'is_verified', 'base_city')
    search_fields = ('business_name', 'user__phone_number', 'base_city')

admin.site.register(PartnerProfile, PartnerProfileAdmin)
admin.site.register(LaborDetails)
admin.site.register(MachineryDetails)
admin.site.register(TransportDetails)
