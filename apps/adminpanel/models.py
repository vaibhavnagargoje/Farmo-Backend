from django.conf import settings
from django.db import models

from partners.models import PartnerProfile


class AgentPartnerRegistration(models.Model):
	"""
	Tracks which admin agent registered which user, and later links partner profile.
	"""

	agent = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		related_name="agent_partner_registrations",
		null=True,
		blank=True,
	)
	registered_user = models.OneToOneField(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="agent_registration_record",
	)
	partner_profile = models.OneToOneField(
		PartnerProfile,
		on_delete=models.CASCADE,
		related_name="agent_registration_record",
		null=True,
		blank=True,
	)
	partner_type = models.CharField(
		max_length=20,
		choices=PartnerProfile.PartnerType.choices,
		null=True,
		blank=True,
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]
		verbose_name = "Agent Partner Registration"
		verbose_name_plural = "Agent Partner Registrations"

	def __str__(self):
		agent_phone = self.agent.phone_number if self.agent else "Unknown Agent"
		return f"{agent_phone} -> {self.registered_user.phone_number}"
