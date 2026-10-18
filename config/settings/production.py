"""
Production settings.

DEBUG off, ALLOWED_HOSTS from env, database credentials mandatory from .env.
Selected with DJANGO_SETTINGS_MODULE=config.settings.production
"""

from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_int, env_list

DEBUG = False

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "")

# Production requires an explicit SECRET_KEY — no accidental default.
SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY must be set in production environment")

DATABASES = {
    "default": {
        "ENGINE": env("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT", "5432"),
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
INTERNAL_API_BASE = env("INTERNAL_API_BASE").rstrip("/")

CELERY_TASK_ALWAYS_EAGER = False

DEFAULT_RENDERER_CLASSES = ("rest_framework.renderers.JSONRenderer",)

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
