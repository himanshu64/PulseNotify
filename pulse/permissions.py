"""Custom permissions for PulseNotify."""

from rest_framework.permissions import BasePermission

from pulse.models import UserProfile


class IsAdminUser(BasePermission):
    """
    Allow access only to users whose UserProfile.role is ADMIN.

    Deliberately NOT Django's built-in IsAdminUser: this checks our own role
    field, which a user gets by having ``role`` set on their profile rather
    than by having ``is_staff`` set on the User.
    """

    message = "Admin privileges are required to access this resource."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        profile = getattr(user, "profile", None)
        if profile is None:
            return False

        return profile.role == UserProfile.Role.ADMIN
