from django.contrib import admin
from .models import UserLocation


@admin.register(UserLocation)
class UserLocationAdmin(admin.ModelAdmin):
    list_display = ['user', 'address', 'latitude', 'longitude', 'updated_at']
    search_fields = ['user__phone_number', 'address']
    raw_id_fields = ['user']