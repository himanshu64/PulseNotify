"""
Celery application for PulseNotify.

Imported from ``config/__init__.py`` so the app object exists as soon as Django
loads — this is what makes ``@shared_task`` decorators resolve correctly for
both the worker and Beat.
"""

import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

# The worker and Beat don't go through manage.py, so load .env here too.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
# billiard 4.3 defaults to the "spawn" start method on macOS; without this the
# spawned prefork children skip worker init and every task fails with
# "not enough values to unpack (expected 3, got 0)".
os.environ.setdefault("FORKED_BY_MULTIPROCESSING", "1")

app = Celery("pulse")

# The CELERY_ namespace keeps Celery's config out of Django's.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks.py in every INSTALLED_APPS entry.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Smoke test: confirms a worker is connected to the broker."""
    print(f"Celery request: {self.request!r}")
