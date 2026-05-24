from django.contrib import admin
from django.utils.html import format_html

from .models import AgentPartnerRegistration, AppSettings


admin.site.site_header = "Farmo Admin"
admin.site.site_title = "Farmo Admin"
admin.site.index_title = "Admin Dashboard"


@admin.register(AgentPartnerRegistration)
class AgentPartnerRegistrationAdmin(admin.ModelAdmin):
	list_display = (
		"agent",
		"registered_user",
		"full_name",
		"partner_type",
		"created_at",
	)
	search_fields = (
		"agent__phone_number",
		"registered_user__phone_number",
		"registered_user__customer_profile__full_name",
		"registered_user__location__address",
	)
	list_filter = ("partner_type", "created_at")
	readonly_fields = ("created_at",)

	def full_name(self, obj):
		profile = getattr(obj.registered_user, "customer_profile", None)
		if profile and profile.full_name:
			return profile.full_name
		return ""


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    """
    Singleton admin for global app configuration.
    Only ever one row — cannot add or delete.
    """
    list_display = ('otp_mode_badge', 'updated_at')
    fields = ('otp_mode',)
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        # Allow add only if the singleton doesn't exist yet (first-time setup)
        return not AppSettings.objects.filter(pk=1).exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='OTP Mode')
    def otp_mode_badge(self, obj):
        if obj.otp_mode == 'SINGLE':
            return format_html(
                '<span style="background:#7c3aed;color:#fff;padding:3px 10px;border-radius:10px;font-size:12px;font-weight:bold;">⚡ SINGLE OTP</span>'
            )
        return format_html(
            '<span style="background:#2563eb;color:#fff;padding:3px 10px;border-radius:10px;font-size:12px;font-weight:bold;">🔐 DUAL OTP</span>'
        )

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_save_and_add_another'] = False
        extra_context['show_save_and_continue'] = False
        # Auto-redirect to the singleton if no object_id provided
        if object_id is None:
            obj = AppSettings.get()
            return super().changeform_view(request, str(obj.pk), form_url, extra_context)
        return super().changeform_view(request, object_id, form_url, extra_context)
