from django.apps import AppConfig


class AppcontrolConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'appcontrol'
    verbose_name = 'App control'

    def ready(self):
        import appcontrol.signals  # noqa: F401
