"""
The PulseNotify application package.

Importing the Celery app here makes it load whenever Django starts — that's
what lets ``@shared_task`` decorators in ``pulse.tasks`` bind to the real
broker instead of silently running nowhere.
"""

from config.celery import app as celery_app

__all__ = ("celery_app",)
