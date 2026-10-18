"""
Local development settings.

DEBUG on, verbose errors, database/Redis/Celery credentials from .env.
Selected with DJANGO_SETTINGS_MODULE=config.settings.local
"""

from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_int, env_list

DEBUG = True

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")

# SECRET_KEY stays overridable from .env; the base default is only a fallback.
SECRET_KEY = env("SECRET_KEY", "django-insecure-local-dev-key")

# Local dev connects to PostgreSQL from docker-compose. If the server isn't
# reachable (docker not running), fall back to SQLite so `manage.py test` and
# the local scripts still work. Set DB_ENGINE=sqlite3 in .env to force this.
def _postgres_reachable(host, port):
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=1.0):
            return True
    except OSError:
        return False


_db_host = env("DB_HOST", "localhost")
_db_port = env("DB_PORT", "5432")
_db_engine = env("DB_ENGINE", "")

if _db_engine == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
elif not _db_engine and not _postgres_reachable(_db_host, _db_port):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": _db_engine or "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "pulsenotify"),
            "USER": env("DB_USER", "pulsenotify"),
            "PASSWORD": env("DB_PASSWORD", "pulsenotify"),
            "HOST": _db_host,
            "PORT": _db_port,
        }
    }

# Celery runs against the Redis in docker-compose.
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# The mock price feed lives on runserver; the Celery worker calls it over HTTP.
INTERNAL_API_BASE = env("INTERNAL_API_BASE", "http://localhost:8000").rstrip("/")

# Eager mode makes tests and local one-off scripts run tasks inline.
# Keep this False when you actually want to watch the three terminals work.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True

# Browsable API is convenient in dev.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
