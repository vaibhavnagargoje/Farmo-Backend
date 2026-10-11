"""Django admin access for emergencies. Day-to-day use: admin panel → App control."""

from django.contrib import admin

from .models import Announcement, AppControl, AppRelease, Broadcast


@admin.register(AppControl)
class AppControlAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'maintenance_ends_at', 'updated_at', 'updated_by')
    readonly_fields = ('updated_at', 'updated_by')

    def has_add_permission(self, request):
        return not AppControl.objects.exists()


@admin.register(AppRelease)
class AppReleaseAdmin(admin.ModelAdmin):
    list_display = ('platform', 'latest_version', 'latest_build', 'min_supported_build', 'soft_update_enabled', 'updated_at')
    readonly_fields = ('updated_at', 'updated_by')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'placement', 'audience', 'show_on', 'style', 'is_active', 'starts_at', 'ends_at', 'priority')
    list_filter = ('is_active', 'placement', 'audience', 'show_on', 'style')
    search_fields = ('title', 'message')


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ('title', 'audience', 'status', 'recipients', 'push_success', 'push_failure', 'created_at', 'sent_at')
    list_filter = ('status', 'audience')
    readonly_fields = ('status', 'recipients', 'push_success', 'push_failure', 'error', 'created_by', 'created_at', 'sent_at')
