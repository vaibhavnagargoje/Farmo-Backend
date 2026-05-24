from django.conf import settings
from django.db import models

from partners.models import PartnerProfile


class AgentPartnerRegistration(models.Model):
	"""
	Tracks which VLE admin registered which user, and later links partner profile.
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
		verbose_name = "VLE Partner Registration"
		verbose_name_plural = "VLE Partner Registrations"

	def __str__(self):
		agent_phone = self.agent.phone_number if self.agent else "Unknown VLE"
		return f"{agent_phone} -> {self.registered_user.phone_number}"


class AppSettings(models.Model):
    """
    Singleton model for global application configuration.
    Always use AppSettings.get() to read the current settings.
    Only one row (pk=1) ever exists in this table.
    """

    OTP_MODE_SINGLE = 'SINGLE'
    OTP_MODE_DUAL = 'DUAL'
    OTP_MODE_CHOICES = [
        ('DUAL', 'Dual OTP — Start OTP + End OTP (default)'),
        ('SINGLE', 'Single OTP — one code generated at order creation'),
    ]

    otp_mode = models.CharField(
        max_length=10,
        choices=OTP_MODE_CHOICES,
        default='DUAL',
        help_text=(
            "DUAL: Provider needs a Start OTP to begin and an End OTP to complete. "
            "SINGLE: One OTP is generated when the order is placed. "
            "The customer shares it; partner enters it once to complete the job."
        )
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App Settings"
        verbose_name_plural = "App Settings"

    def save(self, *args, **kwargs):
        # Singleton enforcement — always pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        """Return the singleton AppSettings row, creating it if absent."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"App Settings [OTP Mode: {self.get_otp_mode_display()}]"
