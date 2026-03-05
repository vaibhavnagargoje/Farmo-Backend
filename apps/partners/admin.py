from django.contrib import admin
from .models import PartnerProfile, LaborDetails, MachineryDetails, TransportDetails

class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'partner_type', 'is_verified', 'rating')
    list_filter = ('partner_type', 'is_verified')
    search_fields = ('user__phone_number',)

admin.site.register(PartnerProfile, PartnerProfileAdmin)
admin.site.register(LaborDetails)
admin.site.register(MachineryDetails)
admin.site.register(TransportDetails)
