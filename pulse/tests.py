"""
Unit tests for PulseNotify.

Three required test groups:
  1. Threshold comparison logic
  2. NotificationLog is created correctly
  3. Alert scoping (users see only their own alerts)
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from pulse.models import NotificationLog, PriceAlert, UserProfile


class PriceThresholdTest(TestCase):
    """Test 1 — threshold comparison logic."""

    def setUp(self):
        self.user = User.objects.create_user(username="thresholduser", password="pass")
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin="DEL",
            destination="BOM",
            threshold_price=Decimal("4500.00"),
        )

    def test_price_below_threshold_triggers_alert(self):
        # 4200 <= 4500 -> fire
        self.assertTrue(self.alert.should_trigger(Decimal("4200.00")))

    def test_price_above_threshold_does_not_trigger(self):
        # 5000 > 4500 -> no fire
        self.assertFalse(self.alert.should_trigger(Decimal("5000.00")))

    def test_price_equal_to_threshold_triggers_alert(self):
        # Edge case: equality still triggers
        self.assertTrue(self.alert.should_trigger(Decimal("4500.00")))

    def test_threshold_comparison_with_int_and_float(self):
        # should_trigger must cope with the raw int/float the mock feed returns
        self.assertTrue(self.alert.should_trigger(4200))
        self.assertTrue(self.alert.should_trigger(4200.0))
        self.assertFalse(self.alert.should_trigger(5000))


class NotificationLogTest(TestCase):
    """Test 2 — NotificationLog is created correctly."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin="DEL",
            destination="BOM",
            threshold_price=Decimal("4500.00"),
            status=PriceAlert.Status.ACTIVE,
        )

    def test_notification_log_created_with_correct_message(self):
        log = NotificationLog.objects.create(
            alert=self.alert,
            triggered_price=Decimal("4200.00"),
            message="Price dropped to 4200 for DEL-BOM",
        )
        self.assertEqual(log.triggered_price, Decimal("4200.00"))
        self.assertEqual(log.alert, self.alert)
        self.assertIn("DEL-BOM", log.message)

    def test_notification_log_is_linked_to_alert(self):
        NotificationLog.objects.create(
            alert=self.alert,
            triggered_price=Decimal("4000.00"),
            message="Price dropped to 4000 for DEL-BOM",
        )
        self.assertEqual(self.alert.notifications.count(), 1)

    def test_notification_log_message_contains_route_and_price(self):
        message = (
            f"Price alert triggered! {self.alert.origin}-{self.alert.destination} "
            f"is now ₹4200 — below your threshold of ₹{self.alert.threshold_price}"
        )
        log = NotificationLog.objects.create(
            alert=self.alert,
            triggered_price=Decimal("4200.00"),
            message=message,
        )
        self.assertIn("DEL-BOM", log.message)
        self.assertIn("4200", log.message)


class AlertScopingTest(TestCase):
    """Test 3 — alert scoping: users see only their own alerts."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", password="pass")
        self.user2 = User.objects.create_user(username="user2", password="pass")
        PriceAlert.objects.create(
            user=self.user1,
            origin="DEL",
            destination="BOM",
            threshold_price=Decimal("4500.00"),
        )
        PriceAlert.objects.create(
            user=self.user2,
            origin="BLR",
            destination="HYD",
            threshold_price=Decimal("2000.00"),
        )

    def test_user_only_sees_own_alerts(self):
        user1_alerts = PriceAlert.objects.filter(user=self.user1)
        self.assertEqual(user1_alerts.count(), 1)
        self.assertEqual(user1_alerts.first().origin, "DEL")

    def test_user_cannot_see_other_users_alerts(self):
        user2_alerts = PriceAlert.objects.filter(user=self.user1)
        # user1 must not see user2's BLR-HYD alert
        self.assertNotEqual(user2_alerts.first().origin, "BLR")

    def test_queryset_scoped_to_request_user_returns_empty_for_no_alerts(self):
        user3 = User.objects.create_user(username="user3", password="pass")
        self.assertEqual(PriceAlert.objects.filter(user=user3).count(), 0)


class UserProfileSignalTest(TestCase):
    """The post_save signal must auto-create a UserProfile with role=USER."""

    def test_profile_auto_created_on_user_creation(self):
        user = User.objects.create_user(username="signaltest", password="pass")
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.role, UserProfile.Role.USER)

    def test_role_defaults_to_user_never_admin(self):
        user = User.objects.create_user(username="signaltest2", password="pass")
        self.assertNotEqual(user.profile.role, UserProfile.Role.ADMIN)


class AdminPermissionTest(TestCase):
    """Custom IsAdminUser checks UserProfile.role, not User.is_staff."""

    def setUp(self):
        from pulse.permissions import IsAdminUser

        self.permission = IsAdminUser

    def _request(self, user):
        class _Req:
            pass

        req = _Req()
        req.user = user
        return req

    def test_admin_role_has_permission(self):
        from pulse.permissions import IsAdminUser

        user = User.objects.create_user(username="adminuser", password="pass")
        user.profile.role = UserProfile.Role.ADMIN
        user.profile.save()
        self.assertTrue(IsAdminUser().has_permission(self._request(user), None))

    def test_regular_user_denied(self):
        from pulse.permissions import IsAdminUser

        user = User.objects.create_user(username="regularuser", password="pass")
        self.assertFalse(IsAdminUser().has_permission(self._request(user), None))

    def test_anonymous_user_denied(self):
        from django.contrib.auth.models import AnonymousUser

        from pulse.permissions import IsAdminUser

        self.assertFalse(
            IsAdminUser().has_permission(self._request(AnonymousUser()), None)
        )


class AlertApiTest(TestCase):
    """Endpoint-level behaviour for the alert endpoints."""

    def setUp(self):
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.user = User.objects.create_user(username="apiuser", password="pass")
        self.other = User.objects.create_user(username="otheruser", password="pass")
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin="DEL",
            destination="BOM",
            threshold_price=Decimal("4500.00"),
        )
        self.other_alert = PriceAlert.objects.create(
            user=self.other,
            origin="BLR",
            destination="HYD",
            threshold_price=Decimal("2000.00"),
        )

    def test_register_returns_token_and_default_role(self):
        response = self.client.post(
            "/api/auth/register/",
            {"username": "newuser", "password": "securepass123",
             "email": "new@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("access", response.json())
        self.assertEqual(response.json()["role"], UserProfile.Role.USER)

    def test_register_rejects_duplicate_username(self):
        response = self.client.post(
            "/api/auth/register/",
            {"username": "apiuser", "password": "securepass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_login_returns_token(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "apiuser", "password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())

    def test_login_rejects_bad_credentials(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "apiuser", "password": "wrongpass"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_alerts_requires_auth(self):
        response = self.client.get("/api/alerts/")
        self.assertEqual(response.status_code, 401)

    def test_alert_list_returns_only_own_alerts(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/alerts/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["origin"], "DEL")

    def test_alert_create_takes_user_from_token_not_body(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/alerts/",
            {"origin": "blr", "destination": "hyd", "threshold_price": 2500,
             "user": self.other.id, "status": "triggered"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        alert = PriceAlert.objects.get(id=response.json()["id"])
        self.assertEqual(alert.user, self.user)
        self.assertEqual(alert.status, PriceAlert.Status.ACTIVE)
        self.assertEqual((alert.origin, alert.destination), ("BLR", "HYD"))

    def test_alert_create_rejects_non_positive_threshold(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/alerts/",
            {"origin": "DEL", "destination": "BOM", "threshold_price": 0},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_alert_delete_other_users_alert_returns_404(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/alerts/{self.other_alert.id}/")
        self.assertEqual(response.status_code, 404)

    def test_alert_delete_own_alert_deactivates(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/alerts/{self.alert.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "inactive")
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.INACTIVE)

    def test_flight_price_known_route(self):
        response = self.client.get("/api/flights/price/?route=DEL-BOM")
        self.assertEqual(response.status_code, 200)
        price = response.json()["price"]
        self.assertTrue(3000 <= price <= 7000)

    def test_flight_price_unknown_route_returns_404(self):
        response = self.client.get("/api/flights/price/?route=XXX-YYY")
        self.assertEqual(response.status_code, 404)

    def test_admin_summary_denied_for_regular_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/admin/summary/")
        self.assertEqual(response.status_code, 403)

    def test_admin_summary_allowed_for_admin(self):
        self.user.profile.role = UserProfile.Role.ADMIN
        self.user.profile.save()
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/admin/summary/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_alerts"], 2)
        self.assertEqual(payload["active_alerts"], 2)


class CeleryTaskTest(TestCase):
    """The two Celery tasks behave correctly when run inline."""

    def setUp(self):
        self.user = User.objects.create_user(username="taskuser", password="pass")
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin="DEL",
            destination="BOM",
            threshold_price=Decimal("4500.00"),
            status=PriceAlert.Status.ACTIVE,
        )

    def test_send_notification_writes_log_and_marks_triggered(self):
        from pulse.tasks import send_notification

        log_id = send_notification(self.alert.id, 4200)
        self.assertIsNotNone(log_id)

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.TRIGGERED)
        self.assertEqual(NotificationLog.objects.filter(alert=self.alert).count(), 1)

    def test_send_notification_message_contains_route(self):
        from pulse.tasks import send_notification

        send_notification(self.alert.id, 4200)
        log = NotificationLog.objects.get(alert=self.alert)
        self.assertIn("DEL-BOM", log.message)

    def test_check_prices_dispatches_notifications_when_threshold_met(self):
        """Mock requests.get to return a cheap price, and assert the task fires."""
        from unittest.mock import MagicMock, patch

        from pulse.tasks import check_prices

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {"route": "DEL-BOM", "price": 3200}

        with patch("pulse.tasks.requests.get", return_value=fake_response):
            with patch("pulse.tasks.send_notification.delay") as mock_delay:
                result = check_prices()

        mock_delay.assert_called_once_with(self.alert.id, 3200)
        self.assertEqual(result["routes_checked"], 1)
        self.assertEqual(result["notifications_dispatched"], 1)

    def test_check_prices_skips_route_when_price_above_threshold(self):
        from unittest.mock import MagicMock, patch

        from pulse.tasks import check_prices

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {"route": "DEL-BOM", "price": 6800}

        with patch("pulse.tasks.requests.get", return_value=fake_response):
            with patch("pulse.tasks.send_notification.delay") as mock_delay:
                result = check_prices()

        mock_delay.assert_not_called()
        self.assertEqual(result["notifications_dispatched"], 0)

    def test_check_prices_ignores_feed_errors(self):
        import requests
        from unittest.mock import patch

        from pulse.tasks import check_prices

        with patch(
            "pulse.tasks.requests.get",
            side_effect=requests.ConnectionError("broker down"),
        ):
            result = check_prices()

        self.assertEqual(result["routes_checked"], 0)
        self.assertEqual(result["notifications_dispatched"], 0)
