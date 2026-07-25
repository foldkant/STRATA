from __future__ import annotations

from collections.abc import Iterable


WEAK_SECRET_VALUES = {
    "",
    "change-me",
    "change-me-before-production",
    "dev-only-change-me",
    "insecure",
    "secret",
}


def production_configuration_errors(
    *,
    environment: str,
    debug: bool,
    secret_key: str,
    allowed_hosts: Iterable[str],
    ssl_redirect: bool,
    session_cookie_secure: bool,
    csrf_cookie_secure: bool,
    hsts_seconds: int,
    onlyoffice_jwt_secret: str,
    database_engine: str,
    channel_layer_backend: str,
    celery_broker_url: str,
) -> list[str]:
    if str(environment or "").strip().lower() not in {"prod", "production"}:
        return []

    errors: list[str] = []
    normalized_secret = str(secret_key or "").strip()
    normalized_hosts = {str(item or "").strip().lower() for item in allowed_hosts}
    if debug:
        errors.append("DJANGO_DEBUG 必须为 false")
    if (
        normalized_secret.lower() in WEAK_SECRET_VALUES
        or len(normalized_secret) < 50
    ):
        errors.append("DJANGO_SECRET_KEY 必须使用至少 50 位的随机值")
    if not normalized_hosts or normalized_hosts.intersection(
        {"*", "0.0.0.0", "localhost", "127.0.0.1"}
    ):
        errors.append("DJANGO_ALLOWED_HOSTS 必须只包含实际部署域名或服务器地址")
    if not ssl_redirect:
        errors.append("DJANGO_SECURE_SSL_REDIRECT 必须为 true")
    if not session_cookie_secure:
        errors.append("DJANGO_SESSION_COOKIE_SECURE 必须为 true")
    if not csrf_cookie_secure:
        errors.append("DJANGO_CSRF_COOKIE_SECURE 必须为 true")
    if int(hsts_seconds or 0) < 3600:
        errors.append("DJANGO_SECURE_HSTS_SECONDS 必须至少为 3600")
    if len(str(onlyoffice_jwt_secret or "").strip()) < 32:
        errors.append("ONLYOFFICE_JWT_SECRET 必须配置至少 32 位的随机值")
    if str(database_engine or "").strip().lower() != "postgresql":
        errors.append("生产环境必须使用 PostgreSQL")
    if str(channel_layer_backend or "").strip().lower() != "redis":
        errors.append("生产环境 CHANNEL_LAYER_BACKEND 必须为 redis")
    if not str(celery_broker_url or "").strip().lower().startswith(
        ("redis://", "rediss://")
    ):
        errors.append("生产环境 CELERY_BROKER_URL 必须使用 Redis")
    return errors
