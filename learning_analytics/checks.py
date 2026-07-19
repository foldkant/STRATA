from __future__ import annotations

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register()
def check_learning_event_write_mode(app_configs, **kwargs):
    mode = str(getattr(settings, "LEARNING_EVENT_WRITE_MODE", "") or "").strip()
    if mode not in {"dual_required", "v1_only"}:
        return [
            Error(
                "学习事件写入模式不正确。",
                hint="LEARNING_EVENT_WRITE_MODE 只能是 dual_required 或 v1_only。",
                id="learning_analytics.E003",
            )
        ]
    return []


@register(Tags.security)
def check_learning_event_quarantine_key(app_configs, **kwargs):
    configured = str(
        getattr(settings, "LEARNING_EVENT_QUARANTINE_KEY", "") or ""
    ).strip()
    engine = settings.DATABASES["default"]["ENGINE"]
    if not configured:
        if engine.endswith("postgresql"):
            return [
                Error(
                    "正式 PostgreSQL 环境未配置学习事件隔离密钥。",
                    hint="生成 Fernet 密钥并设置 LEARNING_EVENT_QUARANTINE_KEY。",
                    id="learning_analytics.E001",
                )
            ]
        return [
            Warning(
                "本地环境使用由 DJANGO_SECRET_KEY 派生的临时事件隔离密钥。",
                hint="正式部署必须设置独立 LEARNING_EVENT_QUARANTINE_KEY。",
                id="learning_analytics.W001",
            )
        ]
    try:
        Fernet(configured.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError):
        return [
            Error(
                "LEARNING_EVENT_QUARANTINE_KEY 不是有效的 Fernet 密钥。",
                hint="使用 Fernet.generate_key() 生成密钥，不要手工编写。",
                id="learning_analytics.E002",
            )
        ]
    return []
