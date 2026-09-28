"""Настоящие Django auth/session/ORM, без production БД и без детектора."""

import atexit
import os
import secrets
import sys
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TransactionTestCase
from django.utils import timezone
from fastapi.testclient import TestClient

from core.models import UserProfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

_files = TemporaryDirectory(prefix="buildvision-auth-tests-")
atexit.register(_files.cleanup)
_static_root = Path(_files.name) / "public"
_static_root.mkdir()
(_static_root / "index.html").write_text("public-page", encoding="utf-8")
(Path(_files.name) / "marker.txt").write_text("outside-public-root", encoding="utf-8")
os.environ["SK_FRONTEND_DIST"] = str(_static_root)
os.environ["SK_SESSION_COOKIE_SECURE"] = "true"
os.environ.pop("SK_SESSION_COOKIE_DOMAIN", None)
os.environ["SK_CORS_ORIGINS"] = "https://testserver,https://localhost,https://example.com"

from app.main import app


class AuthenticationTests(TransactionTestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(24)
        self.admin = User.objects.create_superuser("admin", password=self.password)
        self.participant = User.objects.create_user("participant", password=self.password)
        UserProfile.objects.create(user=self.admin, role=UserProfile.Role.ADMIN)
        UserProfile.objects.create(
            user=self.participant,
            role=UserProfile.Role.PARTICIPANT,
            position="Инженер",
        )
        self.api = TestClient(
            app,
            base_url="https://testserver",
            headers={"X-BuildVision-Request": "1"},
        )
        self.addCleanup(self.api.close)

    def login(self, username="participant", **kwargs):
        return self.api.post(
            "/api/auth/login",
            data={"username": username, "password": self.password},
            **kwargs,
        )

    def test_both_roles_login_restore_and_logout(self):
        for username, role in (("admin", "admin"), ("participant", "participant")):
            with self.subTest(role=role):
                result = self.login(username)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["user"]["role"], role)
                self.assertEqual(self.api.get("/api/auth/me").json()["user"]["username"], username)
                self.assertEqual(result.headers["cache-control"], "no-store")
                self.assertEqual(self.api.post("/api/auth/logout").status_code, 200)
                self.assertEqual(self.api.get("/api/auth/me").status_code, 401)

    def test_invalid_password_and_unknown_user_are_401(self):
        for username in ("admin", "unknown-user"):
            result = self.api.post(
                "/api/auth/login",
                data={"username": username, "password": secrets.token_urlsafe(24)},
            )
            self.assertEqual(result.status_code, 401)

    def test_api_session_opens_django_admin(self):
        self.assertEqual(self.login("admin").status_code, 200)
        admin_client = Client()
        admin_client.cookies[settings.SESSION_COOKIE_NAME] = self.api.cookies.get("sessionid")
        self.assertEqual(admin_client.get("/admin/", secure=True).status_code, 200)

    def test_django_session_opens_api_and_is_revoked_after_password_change(self):
        admin_client = Client()
        self.assertTrue(admin_client.login(username="admin", password=self.password))
        key = admin_client.cookies[settings.SESSION_COOKIE_NAME].value
        self.api.cookies.set("sessionid", key)
        self.assertEqual(self.api.get("/api/auth/me").status_code, 200)
        self.admin.set_password(secrets.token_urlsafe(24))
        self.admin.save(update_fields=["password"])
        self.assertEqual(self.api.get("/api/auth/me").status_code, 401)

    def test_api_session_is_revoked_after_password_change(self):
        self.login()
        self.participant.set_password(secrets.token_urlsafe(24))
        self.participant.save(update_fields=["password"])
        self.assertEqual(self.api.get("/api/auth/me").status_code, 401)

    def test_expired_session_is_rejected(self):
        self.login()
        Session.objects.filter(session_key=self.api.cookies.get("sessionid")).update(
            expire_date=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(self.api.get("/api/auth/me").status_code, 401)

    def test_legacy_session_without_auth_hash_is_rejected(self):
        self.login()
        session = SessionStore(self.api.cookies.get("sessionid"))
        del session[HASH_SESSION_KEY]
        session.save()
        self.assertEqual(self.api.get("/api/auth/me").status_code, 401)

    def test_inactive_account_cannot_login_or_use_old_session(self):
        self.login()
        self.participant.is_active = False
        self.participant.save(update_fields=["is_active"])
        self.assertEqual(self.api.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.login().status_code, 401)

    def test_switching_accounts_invalidates_old_session(self):
        self.login("admin")
        old_key = self.api.cookies.get("sessionid")
        self.login("participant")
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertEqual(self.api.get("/api/auth/me").json()["user"]["role"], "participant")

    def test_participant_cannot_train_or_deploy(self):
        self.login()
        self.assertEqual(self.api.post("/api/model-versions/train").status_code, 403)
        self.assertEqual(self.api.post("/api/model-versions/123/deploy").status_code, 403)

    def test_admin_role_also_requires_staff(self):
        self.participant.profile.role = UserProfile.Role.ADMIN
        self.participant.profile.save(update_fields=["role"])
        self.login()
        self.assertEqual(self.api.get("/api/auth/me").json()["user"]["role"], "participant")
        self.assertEqual(self.api.post("/api/model-versions/train").status_code, 403)

    def test_mobile_origin_login_has_secure_cross_site_cookie(self):
        result = self.login(headers={"Origin": "https://localhost"})
        self.assertEqual(result.status_code, 200)
        cookie = result.headers["set-cookie"].lower()
        self.assertIn("secure", cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=none", cookie)
        self.assertEqual(result.headers["access-control-allow-origin"], "https://localhost")
        self.assertEqual(result.headers["access-control-allow-credentials"], "true")
        self.assertEqual(self.api.get("/api/auth/me").status_code, 200)

    def test_cors_preflight_only_accepts_trusted_origins(self):
        for origin, expected in (("https://localhost", 200), ("https://untrusted.invalid", 400)):
            result = self.api.options(
                "/api/auth/login",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "X-BuildVision-Request",
                },
            )
            self.assertEqual(result.status_code, expected)

    def test_simple_forms_and_untrusted_origins_cannot_mutate(self):
        self.login("admin")
        with patch("app.learning.deploy_version") as deploy:
            for headers in (
                {"X-BuildVision-Request": ""},
                {"Origin": "https://untrusted.invalid"},
                {"Origin": "null"},
            ):
                result = self.api.post("/api/model-versions/1/deploy", headers=headers)
                self.assertEqual(result.status_code, 403)
            deploy.assert_not_called()
        self.assertEqual(self.api.get("/api/auth/me").status_code, 200)

    def test_csrf_guard_also_protects_login(self):
        self.assertEqual(self.login(headers={"X-BuildVision-Request": ""}).status_code, 403)
        self.assertEqual(self.login(headers={"Origin": "https://untrusted.invalid"}).status_code, 403)
        self.assertEqual(self.api.get("/api/auth/me").status_code, 401)

    def test_public_static_paths_cannot_escape_root(self):
        self.assertEqual(self.api.get("/login").status_code, 200)
        result = self.api.get("/%2e%2e/marker.txt")
        self.assertEqual(result.status_code, 404)
        self.assertNotIn("outside-public-root", result.text)

    def test_users_only_seed_preserves_passwords_profiles_and_work_data(self):
        output = StringIO()
        before = User.objects.get(pk=self.participant.pk).password
        with (
            patch.dict(os.environ, {"SK_PARTICIPANT_PASSWORD": secrets.token_urlsafe(24)}),
            patch("core.management.commands.seed_demo_data.Command._seed_vocabulary") as seed,
        ):
            call_command("seed_demo_data", users_only=True, stdout=output)
            seed.assert_not_called()
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.password, before)
        self.assertEqual(self.participant.profile.position, "Инженер")
        self.assertNotIn(self.password, output.getvalue())

    def test_bootstrap_participant_without_password_is_disabled(self):
        self.participant.delete()
        with patch.dict(os.environ, {}, clear=True):
            call_command("seed_demo_data", users_only=True, stdout=StringIO())
        self.assertFalse(User.objects.get(username="participant").has_usable_password())

    def test_bootstrap_admin_without_password_fails_closed(self):
        with (
            patch.dict(
                os.environ,
                {"DJANGO_SUPERUSER_USERNAME": "new-admin", "DJANGO_SUPERUSER_PASSWORD": ""},
            ),
            self.assertRaises(CommandError),
        ):
            call_command("seed_demo_data", users_only=True, stdout=StringIO())
        self.assertFalse(User.objects.filter(username="new-admin").exists())

    def test_bootstrap_uses_explicit_passwords_once(self):
        self.participant.delete()
        with patch.dict(
            os.environ,
            {
                "DJANGO_SUPERUSER_USERNAME": "new-admin",
                "DJANGO_SUPERUSER_PASSWORD": self.password,
                "SK_PARTICIPANT_PASSWORD": self.password,
            },
        ):
            call_command("seed_demo_data", users_only=True, stdout=StringIO())
        self.assertTrue(User.objects.get(username="new-admin").check_password(self.password))
        self.assertTrue(User.objects.get(username="participant").check_password(self.password))
