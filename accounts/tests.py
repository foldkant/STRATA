from django.contrib.auth import get_user_model
from django.test import TestCase


class FormalLoginPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="formal_login_teacher",
            password="FormalLogin12345",
            role="teacher",
        )

    def test_formal_login_page_contains_migrated_interface_and_security_fields(self):
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "登录教学平台")
        self.assertContains(response, "促进教学评一致性")
        self.assertContains(response, "关注学生个体差异")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, "/static/js/login.js")

    def test_invalid_login_keeps_username_and_shows_recovery_message(self):
        response = self.client.post(
            "/login/",
            {
                "username": "formal_login_unknown",
                "password": "not-the-password",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "账号或密码不正确，请重新输入。")
        self.assertContains(response, 'value="formal_login_unknown"')

    def test_valid_login_uses_role_home(self):
        response = self.client.post(
            "/login/",
            {
                "username": self.user.username,
                "password": "FormalLogin12345",
            },
        )

        self.assertRedirects(
            response,
            "/app/teacher",
            fetch_redirect_response=False,
        )

    def test_authenticated_user_is_redirected_away_from_login(self):
        self.client.force_login(self.user)

        response = self.client.get("/login/")

        self.assertRedirects(
            response,
            "/app/teacher",
            fetch_redirect_response=False,
        )
