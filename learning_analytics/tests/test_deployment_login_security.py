from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from config.deployment_security import production_configuration_errors


class ProductionConfigurationTests(SimpleTestCase):
    def test_local_environment_is_not_rejected(self):
        errors = production_configuration_errors(
            environment="local",
            debug=True,
            secret_key="dev-only-change-me",
            allowed_hosts=["127.0.0.1"],
            ssl_redirect=False,
            session_cookie_secure=False,
            csrf_cookie_secure=False,
            hsts_seconds=0,
            onlyoffice_jwt_secret="",
            database_engine="sqlite",
            channel_layer_backend="memory",
            celery_broker_url="filesystem://",
        )
        self.assertEqual(errors, [])

    def test_production_reports_every_unsafe_startup_setting(self):
        errors = production_configuration_errors(
            environment="production",
            debug=True,
            secret_key="dev-only-change-me",
            allowed_hosts=["0.0.0.0"],
            ssl_redirect=False,
            session_cookie_secure=False,
            csrf_cookie_secure=False,
            hsts_seconds=0,
            onlyoffice_jwt_secret="short",
            database_engine="sqlite",
            channel_layer_backend="memory",
            celery_broker_url="filesystem://",
        )
        self.assertGreaterEqual(len(errors), 10)
        self.assertTrue(any("拒绝" not in item for item in errors))
        self.assertTrue(any("ONLYOFFICE_JWT_SECRET" in item for item in errors))
        self.assertTrue(any("PostgreSQL" in item for item in errors))

    def test_complete_production_configuration_is_accepted(self):
        errors = production_configuration_errors(
            environment="production",
            debug=False,
            secret_key="x" * 64,
            allowed_hosts=["strata.school.example"],
            ssl_redirect=True,
            session_cookie_secure=True,
            csrf_cookie_secure=True,
            hsts_seconds=31536000,
            onlyoffice_jwt_secret="y" * 48,
            database_engine="postgresql",
            channel_layer_backend="redis",
            celery_broker_url="redis://127.0.0.1:6379/1",
        )
        self.assertEqual(errors, [])


class RequestObservabilityTests(TestCase):
    def test_response_returns_valid_caller_request_id(self):
        response = self.client.get(
            "/api/health/",
            HTTP_X_REQUEST_ID="school-support-20260724",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Request-ID"], "school-support-20260724")

    def test_invalid_request_id_is_replaced(self):
        response = self.client.get(
            "/api/health/",
            HTTP_X_REQUEST_ID="../../student-answer",
        )
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")


@override_settings(
    LOGIN_FAILURE_LIMIT_PER_ADDRESS=100,
    LOGIN_FAILURE_LIMIT_PER_ACCOUNT=2,
    LOGIN_FAILURE_WINDOW_SECONDS=600,
)
class LoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="limited_login_user",
            password="CorrectPassword123!",
            role=User.Role.SUPER_ADMIN,
        )

    def tearDown(self):
        cache.clear()

    def test_repeated_failures_are_blocked_with_recovery_message(self):
        for _ in range(2):
            failed = self.client.post(
                "/api/v1/auth/login/",
                {
                    "username": self.user.username,
                    "password": "wrong-password",
                },
                format="json",
                REMOTE_ADDR="192.0.2.10",
            )
            self.assertEqual(failed.status_code, 400)

        blocked = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": self.user.username,
                "password": "CorrectPassword123!",
            },
            format="json",
            REMOTE_ADDR="192.0.2.10",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "600")
        self.assertIn("联系学校管理员", blocked.data["message"])

    def test_success_clears_account_failure_counter(self):
        failed = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": self.user.username,
                "password": "wrong-password",
            },
            format="json",
            REMOTE_ADDR="192.0.2.11",
        )
        self.assertEqual(failed.status_code, 400)
        success = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": self.user.username,
                "password": "CorrectPassword123!",
            },
            format="json",
            REMOTE_ADDR="192.0.2.11",
        )
        self.assertEqual(success.status_code, 200)

        self.client.post("/api/v1/auth/logout/", {}, format="json")
        next_failure = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": self.user.username,
                "password": "wrong-password",
            },
            format="json",
            REMOTE_ADDR="192.0.2.11",
        )
        self.assertEqual(next_failure.status_code, 400)
