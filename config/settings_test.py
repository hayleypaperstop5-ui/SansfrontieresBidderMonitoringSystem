"""
Test-only settings overrides.

Run tests with:
    python manage.py test --settings=config.settings_test --parallel auto --keepdb
"""
from .settings import *  # noqa

# Use a fast password hasher (MD5) — production uses PBKDF2.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Silence email sending during tests.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Reduce log noise.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}
