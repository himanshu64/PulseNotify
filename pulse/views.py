"""
API views for PulseNotify.

Seven endpoints:

  POST /api/auth/register/        public  — create user, return JWT + role
  POST /api/auth/login/           public  — validate credentials, return JWT
  GET  /api/alerts/               JWT     — list caller's own alerts
  POST /api/alerts/               JWT     — create alert (user from request)
  DELETE /api/alerts/<id>/        JWT     — deactivate own alert, 404 if not
  GET  /api/flights/price/        public  — mock price feed (called by Celery)
  GET  /api/admin/summary/        admin   — platform-wide statistics
"""

import logging
import random

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from pulse.models import NotificationLog, PriceAlert, UserProfile
from pulse.permissions import IsAdminUser

logger = logging.getLogger(__name__)

# Mock price ranges per route — the "flight market" our feed simulates.
MOCK_PRICES = {
    "DEL-BOM": (3000, 7000),
    "BLR-HYD": (1500, 4000),
    "DEL-BLR": (4000, 9000),
    "BOM-GOA": (2000, 5000),
}


def _tokens_for_user(user):
    """Mint a fresh access/refresh pair for a user."""
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


# ---------------------------------------------------------------------------
# 5.1  POST /api/auth/register/
# ---------------------------------------------------------------------------

@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def register(request):
    """
    Create a Django User, auto-create the UserProfile via post_save signal,
    and return a JWT access token plus the profile role.

    ``role`` is never read from the request body — it always defaults to USER.
    """
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    email = (request.data.get("email") or "").strip()

    if not username or not password:
        return Response(
            {"error": "username and password are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if User.objects.filter(username__iexact=username).exists():
        return Response(
            {"error": "username already exists"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.create_user(
        username=username, password=password, email=email
    )

    # The post_save signal has already created the profile with role=USER.
    profile = user.profile

    tokens = _tokens_for_user(user)
    return Response(
        {
            "username": user.username,
            "email": user.email,
            "role": profile.role,
            **tokens,
        },
        status=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# 5.2  POST /api/auth/login/
# ---------------------------------------------------------------------------

@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def login(request):
    """Validate credentials with Django's authenticate() and return a JWT."""
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    user = authenticate(username=username, password=password)
    if user is None:
        return Response(
            {"error": "invalid credentials"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return Response(
            {"error": "account is disabled"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    tokens = _tokens_for_user(user)
    return Response(
        {
            "username": user.username,
            "role": user.profile.role,
            **tokens,
        },
        status=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# 5.3 / 5.4  Alerts
# ---------------------------------------------------------------------------

class PriceAlertSerializer(serializers.ModelSerializer):
    """``user`` and ``status`` are never read from the body."""

    class Meta:
        model = PriceAlert
        fields = ("id", "origin", "destination", "threshold_price", "status", "created_at")
        read_only_fields = ("id", "status", "created_at")

    def validate_origin(self, value):
        return value.strip().upper()

    def validate_destination(self, value):
        return value.strip().upper()

    def validate_threshold_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("threshold_price must be greater than zero")
        return value


class AlertListCreateView(generics.ListCreateAPIView):
    """
    GET  — list the logged-in user's own alerts. get_queryset() is scoped to
           request.user, so a user can never see another user's alerts. An
           empty list (not a 404) is returned when they have none.

    POST — create an alert for the logged-in user. The user comes from
           request.user (the JWT), never from the request body.
    """

    serializer_class = PriceAlertSerializer

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@api_view(["DELETE"])
def alert_detail(request, pk):
    """
    Deactivate the caller's alert. The row is kept — it's set to INACTIVE so
    the Beat job stops checking it.

    Returns 404 whether the alert doesn't exist or belongs to someone else,
    so we never leak that another user's alert id is real.
    """
    alert = get_object_or_404(PriceAlert, id=pk)

    if alert.user != request.user:
        return Response(
            {"error": "alert not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    alert.status = PriceAlert.Status.INACTIVE
    alert.save(update_fields=["status"])

    return Response({"status": "inactive"}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 5.6  GET /api/flights/price/   (mock price feed, no auth)
# ---------------------------------------------------------------------------

@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def flight_price(request):
    """
    Internal mock price feed.

    Called by the Celery worker with requests.get(). Returns a random price
    inside the route's configured range, or 404 for an unknown route.
    """
    route = request.GET.get("route", "")

    price_range = MOCK_PRICES.get(route)
    if not price_range:
        return Response({"error": "Route not found"}, status=status.HTTP_404_NOT_FOUND)

    price = random.randint(*price_range)
    return Response({"route": route, "price": price}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 5.7  GET /api/admin/summary/
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAdminUser])
def admin_summary(request):
    """
    Platform-wide statistics. Admin-only; regular users get 403.

    All counting happens in the database via aggregate/annotate.
    """
    alert_stats = PriceAlert.objects.aggregate(
        total_alerts=Count("id"),
        active_alerts=Count("id", filter=Q(status=PriceAlert.Status.ACTIVE)),
        triggered_alerts=Count("id", filter=Q(status=PriceAlert.Status.TRIGGERED)),
    )

    notification_stats = NotificationLog.objects.aggregate(
        total_notifications=Count("id")
    )

    top_routes = list(
        PriceAlert.objects.values("origin", "destination")
        .annotate(alert_count=Count("id"))
        .order_by("-alert_count")[:5]
    )

    return Response(
        {
            "total_alerts": alert_stats["total_alerts"],
            "active_alerts": alert_stats["active_alerts"],
            "triggered_alerts": alert_stats["triggered_alerts"],
            "total_notifications": notification_stats["total_notifications"],
            "top_routes": [
                {
                    "route": f"{r['origin']}-{r['destination']}",
                    "alert_count": r["alert_count"],
                }
                for r in top_routes
            ],
        },
        status=status.HTTP_200_OK,
    )
