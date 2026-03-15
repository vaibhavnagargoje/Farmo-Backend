from django.contrib import admin

# Register your models here.
from .models import Notification, DeviceToken

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'message', 'is_read', 'booking_id', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__username', 'title', 'message')

@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'token', 'created_at', 'updated_at')
    search_fields = ('user__username', 'token')