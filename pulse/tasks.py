"""
Celery tasks for PulseNotify.

Two tasks, exactly as the flow requires:

check_prices     — runs on Celery Beat every 60 seconds. Fetches the current
                   price for every route that has active alerts, and for each
                   alert whose threshold is met, fires send_notification.

send_notification— runs asynchronously via .delay(). Writes the
                   NotificationLog row and marks the alert TRIGGERED so it
                   doesn't fire again.

The price comes from our own Django endpoint at /api/flights/price/, called
with requests.get() — the same backend-to-backend pattern an external flight
API would need.
"""

import logging

import requests
from celery import shared_task
from django.conf import settings

from pulse.models import NotificationLog, PriceAlert

logger = logging.getLogger(__name__)


def _price_url() -> str:
    return f"{settings.INTERNAL_API_BASE}/api/flights/price/"


@shared_task
def check_prices():
    """
    Beat-driven price check across every active alert.
    
    Distinct routes are fetched once each, then each active alert on that
    route is compared against the price. A hit is dispatched to
    send_notification with .delay() so this task never blocks on the
    notification being written.
    """
    active_alerts = PriceAlert.objects.filter(status=PriceAlert.Status.ACTIVE)

    # One price fetch per distinct route, not per alert.
    routes = active_alerts.values_list("origin", "destination").distinct()

    checked_routes = 0
    dispatched = 0

    for origin, destination in routes:
        route = f"{origin}-{destination}"

        try:
            response = requests.get(
                _price_url(),
                params={"route": route},
                timeout=settings.PRICE_FEED_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("check_prices: price feed unreachable for %s: %s", route, exc)
            continue

        if response.status_code != 200:
            logger.warning(
                "check_prices: price feed returned %s for %s",
                response.status_code,
                route,
            )
            continue

        try:
            current_price = response.json().get("price")
        except ValueError:
            logger.warning("check_prices: non-JSON response for %s", route)
            continue

        if current_price is None:
            logger.warning("check_prices: no price in response for %s", route)
            continue

        checked_routes += 1

        route_alerts = active_alerts.filter(origin=origin, destination=destination)
        for alert in route_alerts:
            if alert.should_trigger(current_price):
                # Async: fire and move on to the next route immediately.
                send_notification.delay(alert.id, current_price)
                dispatched += 1

    logger.info(
        "check_prices: %d route(s) checked, %d notification(s) dispatched",
        checked_routes,
        dispatched,
    )
    return {"routes_checked": checked_routes, "notifications_dispatched": dispatched}


@shared_task
def send_notification(alert_id, triggered_price):
    """
    Write the NotificationLog row and retire the alert.

    Called only via .delay() from check_prices.
    """
    try:
        alert = PriceAlert.objects.get(id=alert_id)
    except PriceAlert.DoesNotExist:
        logger.warning("send_notification: alert %s no longer exists", alert_id)
        return None

    message = (
        f"Price alert triggered! {alert.origin}-{alert.destination} "
        f"is now ₹{triggered_price} — below your threshold of "
        f"₹{alert.threshold_price}"
    )

    log = NotificationLog.objects.create(
        alert=alert,
        triggered_price=triggered_price,
        message=message,
    )

    # One-shot: stop this alert from being checked again.
    alert.status = PriceAlert.Status.TRIGGERED
    alert.save(update_fields=["status"])

    logger.info("send_notification: %s", message)
    return log.id


