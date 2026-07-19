from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import time
from typing import Any

from django.conf import settings


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 编码不正确。") from exc


class OnlyOfficeJWTError(ValueError):
    pass


def encode_jwt(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _base64url(
        json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    payload_part = _base64url(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{_base64url(signature)}"


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    if not secret:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 密钥未配置。")
    if not token or len(token) > 65_536:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 缺失或过长。")
    parts = token.split(".")
    if len(parts) != 3:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 格式不正确。")
    header_part, payload_part, signature_part = parts
    try:
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
    except UnicodeEncodeError as exc:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 格式不正确。") from exc
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    supplied = _base64url_decode(signature_part)
    if not hmac.compare_digest(expected, supplied):
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 签名无效。")
    try:
        header = json.loads(_base64url_decode(header_part).decode("utf-8"))
        payload = json.loads(_base64url_decode(payload_part).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 内容不正确。") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 只允许 HS256。")
    if not isinstance(payload, dict):
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 载荷必须是对象。")
    now = int(time.time())
    try:
        expires_at = int(payload["exp"]) if payload.get("exp") is not None else None
        not_before = int(payload["nbf"]) if payload.get("nbf") is not None else None
    except (TypeError, ValueError) as exc:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 时间声明不正确。") from exc
    if expires_at is not None and expires_at < now:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 已过期。")
    if not_before is not None and not_before > now + 30:
        raise OnlyOfficeJWTError("ONLYOFFICE JWT 尚未生效。")
    return payload


def verify_callback_payload(token: str, raw_payload: dict[str, Any]) -> dict[str, Any]:
    secret = getattr(settings, "ONLYOFFICE_JWT_SECRET", "").strip()
    decoded = decode_jwt(token, secret)
    signed_payload = decoded.get("payload", decoded)
    if not isinstance(signed_payload, dict):
        raise OnlyOfficeJWTError("ONLYOFFICE 回调 JWT 载荷不正确。")

    status = raw_payload.get("status")
    required_fields = ["status", "key"]
    if status in {2, 6}:
        required_fields.append("url")
    for field in required_fields:
        if field not in raw_payload or signed_payload.get(field) != raw_payload.get(
            field
        ):
            raise OnlyOfficeJWTError(f"ONLYOFFICE 回调字段 {field} 未通过签名校验。")
    for field in ("users", "actions"):
        if field in raw_payload and signed_payload.get(field) != raw_payload.get(field):
            raise OnlyOfficeJWTError(f"ONLYOFFICE 回调字段 {field} 未通过签名校验。")
    return signed_payload


def sign_editor_config(config: dict[str, Any]) -> dict[str, Any]:
    secret = getattr(settings, "ONLYOFFICE_JWT_SECRET", "").strip()
    if not secret:
        return config
    signed_config = copy.deepcopy(config)
    signed_config["token"] = encode_jwt(signed_config, secret)
    return signed_config
