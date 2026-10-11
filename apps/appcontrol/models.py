"""
App control: what the mobile app and the website should do right now.

Maintenance mode, minimum/latest app versions, announcements and broadcast
messages, all managed from the admin panel (App control pages).

Text fields are written in English; `<field>_translations` holds other
languages as {"hi": "...", "mr": "..."}. The API falls back to English.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=com.farmoapp'

# Languages the admin can write announcement text in (the app's languages).
TEXT_LANGUAGES = ('en', 'hi', 'mr')


class Audience(models.TextChoices):
    ALL = 'ALL', 'Everyone'
    FARMERS = 'FARMERS', 'Farmers'
    PROVIDERS = 'PROVIDERS', 'Providers'


class AppControl(models.Model):
    """Singleton (pk=1): maintenance mode. Always read it with AppControl.get()."""

    maintenance_on = models.BooleanField(default=False)
    maintenance_title = models.CharField(max_length=120, blank=True, default='')
    maintenance_title_translations = models.JSONField(default=dict, blank=True)
    maintenance_message = models.TextField(blank=True, default='')
    maintenance_message_translations = models.JSONField(default=dict, blank=True)
    maintenance_ends_at = models.DateTimeField(
        null=True, blank=True, help_text="Shown to users as the time the app should be back",
    )
    block_api_during_maintenance = models.BooleanField(
        default=True,
        help_text="Refuse app API requests while maintenance is on (the admin panel keeps working)",
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        verbose_name = 'App control'
        verbose_name_plural = 'App control'

    def save(self, *args, **kwargs):
        self.pk = 1  # Singleton
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"App control [maintenance {'ON' if self.maintenance_on else 'off'}]"


class AppRelease(models.Model):
    """Versions for one platform: which builds must update and which are offered an update."""

    class Platform(models.TextChoices):
        ANDROID = 'android', 'Android'
        IOS = 'ios', 'iOS'

    platform = models.CharField(max_length=10, choices=Platform.choices, unique=True)
    latest_version = models.CharField(
        max_length=20, blank=True, default='', help_text="Newest version in the store, e.g. 1.0.27",
    )
    latest_build = models.PositiveIntegerField(
        default=0, help_text="Build number (Android versionCode) of the newest version, e.g. 27",
    )
    min_supported_build = models.PositiveIntegerField(
        default=0, help_text="Builds below this must update before using the app. 0 = nobody is forced",
    )
    soft_update_enabled = models.BooleanField(
        default=True, help_text="Offer an optional update to builds below the latest build",
    )
    store_url = models.URLField(blank=True, default='')
    update_title = models.CharField(max_length=120, blank=True, default='')
    update_title_translations = models.JSONField(default=dict, blank=True)
    update_message = models.TextField(blank=True, default='', help_text="What's new in the latest version")
    update_message_translations = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['platform']

    @classmethod
    def for_platform(cls, platform):
        obj, _ = cls.objects.get_or_create(
            platform=platform,
            defaults={'store_url': PLAY_STORE_URL if platform == cls.Platform.ANDROID else ''},
        )
        return obj

    def __str__(self):
        return f"{self.get_platform_display()} latest {self.latest_version or '-'} (min build {self.min_supported_build})"


class Announcement(models.Model):
    """A banner or one-time popup in the app, and/or a strip on the website."""

    class Style(models.TextChoices):
        INFO = 'INFO', 'Info'
        SUCCESS = 'SUCCESS', 'Good news'
        WARNING = 'WARNING', 'Warning'
        URGENT = 'URGENT', 'Urgent'

    class Placement(models.TextChoices):
        BANNER = 'BANNER', 'Banner (stays on screen)'
        POPUP = 'POPUP', 'Popup (shown once)'

    class ShowOn(models.TextChoices):
        APP = 'APP', 'App'
        WEBSITE = 'WEBSITE', 'Website'
        BOTH = 'BOTH', 'App and website'

    title = models.CharField(max_length=120)
    title_translations = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True, default='')
    message_translations = models.JSONField(default=dict, blank=True)

    style = models.CharField(max_length=10, choices=Style.choices, default=Style.INFO)
    placement = models.CharField(max_length=10, choices=Placement.choices, default=Placement.BANNER)
    audience = models.CharField(max_length=10, choices=Audience.choices, default=Audience.ALL)
    show_on = models.CharField(max_length=10, choices=ShowOn.choices, default=ShowOn.APP)
    image = models.ImageField(upload_to='announcements/', null=True, blank=True)

    cta_label = models.CharField(max_length=40, blank=True, default='', help_text="Button text, e.g. Learn more")
    cta_label_translations = models.JSONField(default=dict, blank=True)
    cta_url = models.CharField(
        max_length=500, blank=True, default='',
        help_text="Where the button goes: a web link (https://...), tel:..., or a WhatsApp link",
    )

    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True, help_text="Leave empty to show until turned off")
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0, help_text="Higher shows first")
    dismissible = models.BooleanField(default=True, help_text="Users can close it")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-starts_at']

    def state(self, now=None):
        """'off', 'scheduled', 'ended' or 'live'."""
        now = now or timezone.now()
        if not self.is_active:
            return 'off'
        if self.starts_at > now:
            return 'scheduled'
        if self.ends_at and self.ends_at <= now:
            return 'ended'
        return 'live'

    def __str__(self):
        return self.title


class Broadcast(models.Model):
    """A push notification plus a notification-list entry for many users at once."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENDING = 'SENDING', 'Sending'
        SENT = 'SENT', 'Sent'
        FAILED = 'FAILED', 'Failed'

    title = models.CharField(max_length=120)
    title_translations = models.JSONField(default=dict, blank=True)
    message = models.TextField()
    message_translations = models.JSONField(default=dict, blank=True)
    audience = models.CharField(max_length=10, choices=Audience.choices, default=Audience.ALL)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    recipients = models.PositiveIntegerField(default=0, help_text="People who got a notification-list entry")
    push_success = models.PositiveIntegerField(default=0, help_text="Devices the push reached")
    push_failure = models.PositiveIntegerField(default=0, help_text="Devices the push could not reach")
    error = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} [{self.status}]"
