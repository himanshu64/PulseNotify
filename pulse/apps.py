"""App configuration for PulseNotify."""

from django.apps import AppConfig


class PulseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pulse"
    label = "pulse"

    def ready(self):
        """
        Connect signals here, not at import time.

        Importing signal handlers in ``ready()`` guarantees they're registered
        exactly once, after the app registry is fully populated.
        """
        from pulse import signals  # noqa: F401
