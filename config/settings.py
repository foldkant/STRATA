from __future__ import annotations

import os
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv
from kombu import Queue

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except (TypeError, ValueError):
        return default


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-change-me")
AI_SECRET_KEY = env("AI_SECRET_KEY", SECRET_KEY)
LEARNING_EVENT_QUARANTINE_KEY = env("LEARNING_EVENT_QUARANTINE_KEY", "")
LEARNING_EVENT_QUARANTINE_RETENTION_DAYS = min(
    max(env_int("LEARNING_EVENT_QUARANTINE_RETENTION_DAYS", 7), 1),
    90,
)
LEARNING_EVENT_WRITE_MODE = env("LEARNING_EVENT_WRITE_MODE", "dual_required").strip()
DEBUG = env_bool("DJANGO_DEBUG", True)
CURRICULUM_REQUIRE_SEPARATE_REVIEWERS = env_bool(
    "CURRICULUM_REQUIRE_SEPARATE_REVIEWERS",
    not DEBUG,
)
CURRICULUM_OCR_SCALE = min(max(env_float("CURRICULUM_OCR_SCALE", 1.5), 1.0), 3.0)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
SECURE_CROSS_ORIGIN_OPENER_POLICY = env("DJANGO_CROSS_ORIGIN_OPENER_POLICY", "same-origin") or None
CSRF_TRUSTED_ORIGINS = [
    origin for origin in env_list("DJANGO_CSRF_TRUSTED_ORIGINS") if origin.startswith(("http://", "https://"))
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "channels",
    "django_celery_beat",
    "accounts",
    "school",
    "courses",
    "learning",
    "learning_analytics",
    "curriculum_standards",
    "realtime",
    "aiops",
    "api",
    "ops",
    "school_admin",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

database_engine = env("DATABASE_ENGINE", "sqlite").lower()
if database_engine == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DATABASE_NAME", "xlzxedu"),
            "USER": env("DATABASE_USER", "xlzxedu"),
            "PASSWORD": env("DATABASE_PASSWORD", ""),
            "HOST": env("DATABASE_HOST", "127.0.0.1"),
            "PORT": env("DATABASE_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    sqlite_name = env("DATABASE_NAME", "storage/dev.sqlite3")
    sqlite_timeout_seconds = min(max(env_int("SQLITE_TIMEOUT_SECONDS", 30), 5), 120)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / sqlite_name,
            # OCR commits page staging in short transactions. A longer busy
            # timeout prevents transient Web/worker overlap from failing
            # immediately; production PostgreSQL is unaffected.
            "OPTIONS": {"timeout": sqlite_timeout_seconds},
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / env("STATIC_ROOT", "storage/static")
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / env("MEDIA_ROOT", "storage/media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list("DJANGO_CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "api.renderers.StudentPrivacyJSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379/0")
CHANNEL_LAYER_BACKEND = env("CHANNEL_LAYER_BACKEND", "memory" if DEBUG else "redis").lower()
if CHANNEL_LAYER_BACKEND == "memory":
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/2")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_DEFAULT_QUEUE = "celery"
CELERY_TASK_DEFAULT_ROUTING_KEY = "celery"
CURRICULUM_PROCESSING_QUEUE = env(
    "CURRICULUM_PROCESSING_QUEUE",
    "curriculum_ocr",
).strip() or "curriculum_ocr"
if CURRICULUM_PROCESSING_QUEUE != "curriculum_ocr":
    raise ValueError("CURRICULUM_PROCESSING_QUEUE must remain 'curriculum_ocr'.")
CURRICULUM_PROCESSING_STALE_SECONDS = max(
    env_int("CURRICULUM_PROCESSING_STALE_SECONDS", 30 * 60),
    5 * 60,
)
CELERY_TASK_QUEUES = (
    Queue("celery", routing_key="celery"),
    Queue(CURRICULUM_PROCESSING_QUEUE, routing_key=CURRICULUM_PROCESSING_QUEUE),
)
CELERY_TASK_ROUTES = {
    "curriculum_standards.process_version_pdf": {
        "queue": CURRICULUM_PROCESSING_QUEUE,
        "routing_key": CURRICULUM_PROCESSING_QUEUE,
    },
}

# One curriculum-standard job owns one PDF. The dedicated worker also fixes
# concurrency and prefetch on its command line; these values are consumed by
# the task so ordinary analytics jobs keep their existing one-hour limit.
CURRICULUM_OCR_TASK_SOFT_TIME_LIMIT = max(
    env_int("CURRICULUM_OCR_TASK_SOFT_TIME_LIMIT", 3 * 60 * 60),
    5 * 60,
)
CURRICULUM_OCR_TASK_TIME_LIMIT = max(
    env_int("CURRICULUM_OCR_TASK_TIME_LIMIT", CURRICULUM_OCR_TASK_SOFT_TIME_LIMIT + 5 * 60),
    CURRICULUM_OCR_TASK_SOFT_TIME_LIMIT + 60,
)

# Redis remains mandatory in production. A single-host Windows development
# machine may opt into Kombu's filesystem transport. Producer and worker use
# opposite inbox/outbox directions; processed messages are retained for local
# diagnosis. The worker launcher creates these directories before Celery
# imports this configuration.
if CELERY_BROKER_URL.lower().startswith("filesystem://"):
    CURRICULUM_CELERY_FILESYSTEM_ROLE = env(
        "CURRICULUM_CELERY_FILESYSTEM_ROLE",
        "producer",
    ).strip().lower()
    if CURRICULUM_CELERY_FILESYSTEM_ROLE not in {"producer", "worker"}:
        raise ValueError(
            "CURRICULUM_CELERY_FILESYSTEM_ROLE must be 'producer' or 'worker'."
        )

    _filesystem_root = Path(
        env(
            "CURRICULUM_CELERY_FILESYSTEM_ROOT",
            "storage/celery/curriculum_ocr",
        )
    ).expanduser()
    if not _filesystem_root.is_absolute():
        _filesystem_root = BASE_DIR / _filesystem_root
    _filesystem_root = _filesystem_root.resolve()
    _producer_out = _filesystem_root / "producer-out"
    _worker_out = _filesystem_root / "worker-out"
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "data_folder_in": str(
            _worker_out
            if CURRICULUM_CELERY_FILESYSTEM_ROLE == "producer"
            else _producer_out
        ),
        "data_folder_out": str(
            _producer_out
            if CURRICULUM_CELERY_FILESYSTEM_ROLE == "producer"
            else _worker_out
        ),
        "store_processed": True,
        "processed_folder": str(_filesystem_root / "processed"),
        "control_folder": str(_filesystem_root / "control"),
    }
    # Curriculum processing persists its state in Django models and its task
    # explicitly ignores Celery results. Do not accidentally fall back to a
    # Redis result backend when the local filesystem broker is selected.
    CELERY_RESULT_BACKEND = "disabled://"
elif CELERY_BROKER_URL.lower().startswith(("redis://", "rediss://")):
    # acks_late OCR jobs must not become visible again while still inside their
    # allowed execution window. Keep the Redis visibility window beyond the
    # curriculum hard limit; duplicate delivery is still guarded by DB state.
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "visibility_timeout": max(
            env_int("CELERY_VISIBILITY_TIMEOUT", 4 * 60 * 60),
            CURRICULUM_OCR_TASK_TIME_LIMIT + 5 * 60,
        ),
    }
ANALYTICS_CODE_VERSION = env("ANALYTICS_CODE_VERSION", "")
CELERY_BEAT_SCHEDULE = {
    "strata-nightly-data-quality": {
        "task": "learning_analytics.tasks.run_nightly_data_quality",
        "schedule": crontab(hour=1, minute=30),
    },
    "strata-nightly-learning-summaries": {
        "task": "learning_analytics.tasks.run_nightly_learning_summaries",
        "schedule": crontab(hour=2, minute=30),
    },
    "strata-nightly-mastery-candidates": {
        "task": "learning_analytics.tasks.run_nightly_mastery_candidates",
        "schedule": crontab(hour=2, minute=40),
    },
    "strata-nightly-feature-outcomes": {
        "task": "learning_analytics.tasks.run_nightly_feature_outcomes",
        "schedule": crontab(hour=2, minute=50),
    },
    "strata-nightly-model-validation": {
        "task": "learning_analytics.tasks.run_nightly_model_validation",
        "schedule": crontab(hour=3, minute=10),
    },
}

MLFLOW_TRACKING_URI = env("MLFLOW_TRACKING_URI", f"file:{BASE_DIR / 'storage/mlruns'}")
MODEL_ARTIFACT_ROOT = BASE_DIR / env("MODEL_ARTIFACT_ROOT", "storage/models")
MODEL_PACKAGE_ROOT = BASE_DIR / env("MODEL_PACKAGE_ROOT", "storage/model_packages")
MODEL_SIGNING_PRIVATE_KEY_PATH = BASE_DIR / env(
    "MODEL_SIGNING_PRIVATE_KEY_PATH", "storage/keys/model_signing_private.pem"
)
MODEL_SIGNING_PUBLIC_KEY_PATH = BASE_DIR / env(
    "MODEL_SIGNING_PUBLIC_KEY_PATH", "storage/keys/model_signing_public.pem"
)
MODEL_SIGNING_AUTO_CREATE = env_bool("MODEL_SIGNING_AUTO_CREATE", DEBUG)
ONLYOFFICE_DOCUMENT_SERVER_URL = env("ONLYOFFICE_DOCUMENT_SERVER_URL", "http://192.168.11.165").rstrip("/")
ONLYOFFICE_JWT_SECRET = env("ONLYOFFICE_JWT_SECRET", "")
