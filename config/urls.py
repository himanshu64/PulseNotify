"""Root URL configuration for PulseNotify."""

from django.contrib import admin
from django.urls import path

from pulse.views import (
    admin_summary,
    alert_collection,
    alert_detail,
    flight_price,
    login,
    register,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # --- Public: auth -------------------------------------------------
    path("api/auth/register/", register, name="register"),
    path("api/auth/login/", login, name="login"),

    # --- JWT protected: alerts ----------------------------------------
    # GET lists the caller's alerts, POST creates one for the caller.
    path("api/alerts/", alert_collection, name="alert-collection"),
    # DELETE deactivates the caller's own alert; 404 if it isn't theirs.
    path("api/alerts/<int:pk>/", alert_detail, name="alert-detail"),

    # --- Public: internal mock price feed -----------------------------
    path("api/flights/price/", flight_price, name="flight-price"),

    # --- Admin only ---------------------------------------------------
    path("api/admin/summary/", admin_summary, name="admin-summary"),
]
