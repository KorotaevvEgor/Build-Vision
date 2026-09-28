"""Изолированная БД для тестов Django; никогда не подключается к PostgreSQL."""

from .settings import *

SECRET_KEY = "buildvision-test-settings-only-not-for-deployment"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": "file:buildvision_auth_tests?mode=memory&cache=shared"},
    },
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SECURE = True
