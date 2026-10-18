"""Admin registrations for PulseNotify."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from pulse.models import NotificationLog, PriceAlert, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fk_name = "user"


class UserAdmin(DjangoUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ("username", "email", "get_role", "is_active")
    list_filter = ("is_active", "is_staff", "profile__role")

    @admin.display(description="Role", ordering="profile__role")
    def get_role(self, obj):
        return getattr(getattr(obj, "profile", None), "role", "-")


# auth.User is registered by Django's own admin; swap in our version that
# shows the role column and the inline profile. The decorator cannot be used
# here because it fires at import time, before unregister() gets a chance.
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("user__username",)


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "origin",
        "destination",
        "threshold_price",
        "status",
        "created_at",
    )
    list_filter = ("status", "origin", "destination")
    search_fields = ("user__username", "origin", "destination")
    list_editable = ("status",)
    date_hierarchy = "created_at"


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("id", "alert", "triggered_price", "notified_at")
    search_fields = ("alert__user__username", "message")
    date_hierarchy = "notified_at"
    readonly_fields = ("notified_at",)
