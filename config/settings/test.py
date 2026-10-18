"""
Test settings — uses SQLite so `manage.py test` works without Docker.
"""
from .base import *

DEBUG = True
SECRET_KEY = "django-insecure-test-key"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Run tasks synchronously — no broker needed.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
