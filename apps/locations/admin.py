from django.contrib import admin
from .models import State, District, Tahsil, Village, UserLocation


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ['name', 'code']
    search_fields = ['name', 'code']


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ['name', 'state']
    list_filter = ['state']
    search_fields = ['name']


@admin.register(Tahsil)
class TahsilAdmin(admin.ModelAdmin):
    list_display = ['name', 'district']
    list_filter = ['district__state', 'district']
    search_fields = ['name']

@admin.register(Village)
class VillageAdmin(admin.ModelAdmin):
    list_display = ['name', 'tahasil']
    list_filter = ['tahasil__district__state', 'tahasil__district', 'tahasil']
    search_fields = ['name']


@admin.register(UserLocation)
class UserLocationAdmin(admin.ModelAdmin):
    list_display = ['user', 'address', 'latitude', 'longitude', 'updated_at']
    search_fields = ['user__phone_number', 'address']
    list_filter = ['state', 'district']
    raw_id_fields = ['user']