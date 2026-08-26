# apps/availability/admin.py
from django.contrib import admin
from .models import BusyDay


@admin.register(BusyDay)
class BusyDayAdmin(admin.ModelAdmin):
    list_display = ('partner', 'date', 'entity_type', 'service', 'marked_by', 'reason', 'created_at')
    list_filter = ('marked_by', 'entity_type', 'date')
    search_fields = ('partner__user__phone_number', 'reason')
    date_hierarchy = 'date'
    raw_id_fields = ('partner', 'service', 'marked_by_user', 'booking')
    ordering = ('-date',)
