"""
Signal wiring for PulseNotify.

A ``UserProfile`` is created automatically for every new ``User`` via a
``post_save`` signal — so registration never has to remember to build one.
"""

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from pulse.models import UserProfile


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Auto-create a UserProfile (role=USER) when a User is first created."""
    if created:
        UserProfile.objects.create(user=instance, role=UserProfile.Role.USER)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Keep the profile in step when the User is saved."""
    if hasattr(instance, "profile"):
        instance.profile.save()
