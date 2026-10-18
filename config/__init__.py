"""PulseNotify project configuration package (settings, urls, celery, wsgi).

Importing the Celery app here makes it load whenever Django starts, which is
what lets ``@shared_task`` decorators in ``pulse.tasks`` bind to the real
broker instead of silently running nowhere.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
