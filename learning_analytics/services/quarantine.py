from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection

MAX_REPLAYABLE_ENVELOPE_BYTES = 64 * 1024


def _configured_key() -> bytes:
    configured = str(
        getattr(settings, "LEARNING_EVENT_QUARANTINE_KEY", "") or ""
    ).strip()
    if configured:
        key = configured.encode("ascii")
    elif settings.DEBUG or connection.vendor == "sqlite":
        digest = hashlib.sha256(
            f"{settings.SECRET_KEY}:learning-event-quarantine:v1".encode()
        ).digest()
        key = base64.urlsafe_b64encode(digest)
    else:
        raise ImproperlyConfigured("正式环境必须配置 LEARNING_EVENT_QUARANTINE_KEY。")
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "LEARNING_EVENT_QUARANTINE_KEY 不是有效的 Fernet 密钥。"
        ) from exc
    return key


def quarantine_key_id() -> str:
    return hashlib.sha256(_configured_key()).hexdigest()[:16]


def _canonical_json_bytes(value: dict) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("事件信封不是可序列化的 JSON 对象。") from exc


def encrypt_quarantined_envelope(envelope: dict) -> dict:
    raw = _canonical_json_bytes(envelope)
    envelope_hash = hashlib.sha256(raw).hexdigest()
    is_replayable = len(raw) <= MAX_REPLAYABLE_ENVELOPE_BYTES
    content = raw
    if not is_replayable:
        summary = {
            "event_id": str(envelope.get("event_id") or "")[:64],
            "event_name": str(envelope.get("event_name") or "")[:128],
            "schema_version": str(envelope.get("schema_version") or "")[:16],
            "payload_omitted": True,
            "original_size_bytes": len(raw),
            "original_sha256": envelope_hash,
        }
        content = _canonical_json_bytes(summary)
    token = Fernet(_configured_key()).encrypt(content).decode("ascii")
    return {
        "encrypted_envelope": token,
        "envelope_hash": envelope_hash,
        "envelope_size_bytes": len(raw),
        "encryption_key_id": quarantine_key_id(),
        "is_replayable": is_replayable,
    }


def quarantine_retention_deadline(received_at):
    days = int(getattr(settings, "LEARNING_EVENT_QUARANTINE_RETENTION_DAYS", 7))
    return received_at + timedelta(days=max(1, min(days, 90)))


def decrypt_quarantined_envelope(token: str) -> dict:
    try:
        decoded = Fernet(_configured_key()).decrypt(token.encode("ascii"))
        value = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError("隔离事件无法使用当前密钥解密。") from exc
    if not isinstance(value, dict):
        raise ValidationError("隔离事件解密结果不是 JSON 对象。")
    return value
