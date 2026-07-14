from pathlib import Path
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


# Secrets that must never reach a live server. If DEBUG is off and one of these
# is still in use, refuse to boot rather than silently run production with a
# known key. Generate a real one with:
#   python -c "import secrets; print(secrets.token_urlsafe(64))"
INSECURE_SECRETS = {"unsafe-dev-secret-key", "change-this-before-use", ""}

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-dev-secret-key")
DEBUG = env_bool("DJANGO_DEBUG", default=True)

if not DEBUG and SECRET_KEY in INSECURE_SECRETS:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is unset or a placeholder while DJANGO_DEBUG is off. "
        "Set a real secret before running the server: "
        "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "auditlog",
    "apps.accounts",
    "apps.core",
    "apps.patients",
    "apps.opd",
    "apps.prescriptions",
    "apps.comms",
    "apps.lab",
    "apps.pharmacy",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.ForcePinChangeMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.core.context_processors.hospital",
                "apps.core.context_processors.user_roles",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# Tri-lingual scaffolding from day one (PLAN §7): English UI with Hindi/Marathi
# available. Wrap user-facing strings in {% trans %}/gettext; run
# `manage.py makemessages -l hi -l mr` then `compilemessages` to add catalogs.
LANGUAGES = [
    ("en", "English"),
    ("hi", "हिंदी"),
    ("mr", "मराठी"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

HOSPITAL_UHID_CODE = os.environ.get("HOSPITAL_UHID_CODE", "DMH").upper()
HOSPITAL_PRIVACY_NOTICE_VERSION = os.environ.get(
    "HOSPITAL_PRIVACY_NOTICE_VERSION", "2026-07-02-v1"
)

OPD_DEFAULT_SLOT_MINUTES = int(os.environ.get("OPD_DEFAULT_SLOT_MINUTES", "10"))
OPD_SLOT_CAPACITY = int(os.environ.get("OPD_SLOT_CAPACITY", "1"))

# Thermal token printer (ESC/POS over RAW/JetDirect port 9100). When a host is
# set the server streams the token straight to the printer; otherwise the
# endpoint returns the raw bytes for a local spooler.
OPD_THERMAL_PRINTER_HOST = os.environ.get("OPD_THERMAL_PRINTER_HOST", "")
OPD_THERMAL_PRINTER_PORT = int(os.environ.get("OPD_THERMAL_PRINTER_PORT", "9100"))

# Waiting-room audio announcements: pre-generated per-symbol MP3 clips composed
# on the board (PLAN §4, not browser TTS). Off until the clips are generated —
# the board falls back to a chime. Clips live at static/announce/<lang>/<X>.mp3.
OPD_ANNOUNCE_AUDIO = env_bool("OPD_ANNOUNCE_AUDIO", default=False)
OPD_ANNOUNCE_LANG = os.environ.get("OPD_ANNOUNCE_LANG", "mr")

# Default channel for auto-queued appointment/follow-up reminders.
OPD_REMINDER_CHANNEL = os.environ.get("OPD_REMINDER_CHANNEL", "whatsapp")

# Video teleconsult (Jitsi Meet). Public server needs no key; a self-hosted
# Jitsi domain can be set for privacy.
OPD_JITSI_DOMAIN = os.environ.get("OPD_JITSI_DOMAIN", "meet.jit.si")

PIN_LENGTH = 6
PIN_SESSION_TIMEOUT_SECONDS = int(os.environ.get("PIN_SESSION_TIMEOUT_SECONDS", "300"))
SESSION_COOKIE_AGE = PIN_SESSION_TIMEOUT_SECONDS
SESSION_SAVE_EVERY_REQUEST = True

# Security posture follows DEBUG: a production boot (DEBUG=0, as docker-compose
# sets) automatically gets secure cookies + TLS redirect without the operator
# remembering to flip each flag. Caddy terminates TLS and forwards
# X-Forwarded-Proto, so Django correctly sees requests as secure.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = bool(SECURE_HSTS_SECONDS)
SECURE_HSTS_PRELOAD = bool(SECURE_HSTS_SECONDS)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG)
