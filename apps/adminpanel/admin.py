from django.contrib import admin

from .models import AgentPartnerRegistration


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

