"""
Configuración de Cronso Dplay.

Toda la configuración sensible se lee de variables de entorno (ver .env.example).
Si POSTGRES_HOST no está definido se usa SQLite (útil solo para pruebas rápidas).
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Apps del proyecto
    "apps.core",
    "apps.venues",
    "apps.songs",
    "apps.events",
    "apps.accounts",
    "apps.control",
    "apps.dj",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.app_info",
                "apps.accounts.context_processors.guest",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Base de datos ---------------------------------------------------------
if env("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "cronso_dplay"),
            "USER": env("POSTGRES_USER", "cronso"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-co"
TIME_ZONE = env("DJANGO_TIME_ZONE", "America/Bogota")
USE_I18N = True
USE_TZ = True

# --- Estáticos (WhiteNoise, sin servidor extra) ----------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

LOGIN_URL = "staff_login"
LOGIN_REDIRECT_URL = "dj:panel"
LOGOUT_REDIRECT_URL = "staff_login"

# --- Seguridad en producción -----------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}

# --- Reglas de negocio de Cronso Dplay -------------------------------------
APP_NAME = "Cronso Dplay"
# Máximo de canciones que puede pedir un mismo correo.
SONG_MAX_PER_EMAIL = int(env("SONG_MAX_PER_EMAIL", "3"))
# Ventana en horas para contar el límite. 0 = para siempre (sin reinicio).
SONG_LIMIT_WINDOW_HOURS = int(env("SONG_LIMIT_WINDOW_HOURS", "0"))
# Máximo de canciones por dispositivo (cookie anónima), aunque cambie de correo. 0 = sin límite.
SONG_MAX_PER_DEVICE = int(env("SONG_MAX_PER_DEVICE", "3"))
# Tope por IP pública. Debe ser ALTO: el WiFi del bar y las redes móviles comparten IP. 0 = sin límite.
SONG_MAX_PER_IP = int(env("SONG_MAX_PER_IP", "15"))
SONG_IP_WINDOW_HOURS = int(env("SONG_IP_WINDOW_HOURS", "12"))
# IPs o redes CIDR exentas del tope por IP (ej. la IP pública del WiFi de la discoteca).
SONG_IP_ALLOWLIST = env_list("SONG_IP_ALLOWLIST", "")
# Proxies de confianza delante de la app (CloudFront + ALB = 2). 0 = usar REMOTE_ADDR.
TRUSTED_PROXY_COUNT = int(env("TRUSTED_PROXY_COUNT", "0"))
# --- Inicio de sesión del público con Google (Google Identity Services) ---
# ID de cliente OAuth "Aplicación web" (termina en .apps.googleusercontent.com). Es público: no hay secreto.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", "")
# Exigir Google para pedir canciones y puntuar. Por defecto: activo si hay GOOGLE_CLIENT_ID.
GOOGLE_LOGIN_REQUIRED = env_bool("GOOGLE_LOGIN_REQUIRED", bool(GOOGLE_CLIENT_ID))
if len(sys.argv) > 1 and sys.argv[1] == "test":
    # Las pruebas del flujo sin Google no deben depender del .env; las de Google lo activan explícitamente.
    GOOGLE_LOGIN_REQUIRED = False
# El botón de Google abre una ventana emergente: "same-origin" (valor por defecto de Django) la bloquea.
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"

# --- YouTube Data API v3 (gratis, cuota 10.000 unidades/día) ---
# Sin API key la app funciona igual, solo que sin vistas/likes/recomendación.
YOUTUBE_API_KEY = env("YOUTUBE_API_KEY", "")
# Si la canción no trae link de YouTube, buscar el video por "artista título" (cuesta 100 unidades).
YOUTUBE_SEARCH_FALLBACK = env_bool("YOUTUBE_SEARCH_FALLBACK", True)
YOUTUBE_COMMENTS_MAX = int(env("YOUTUBE_COMMENTS_MAX", "100"))
# Reutilizar datos del mismo video consultado hace menos de N horas (ahorra cuota).
YOUTUBE_CACHE_HOURS = int(env("YOUTUBE_CACHE_HOURS", "24"))
# Consultar YouTube en segundo plano para no demorar el registro de la canción.
ENRICH_ASYNC = env_bool("ENRICH_ASYNC", True)
# Segundos entre refrescos del panel del DJ.
DJ_PANEL_POLL_SECONDS = int(env("DJ_PANEL_POLL_SECONDS", "8"))
# URL pública base usada para generar los QR (ej: https://dplay.cronso.com).
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:8000")
