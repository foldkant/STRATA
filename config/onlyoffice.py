from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
from typing import Any

from django.conf import settings


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def encode_jwt(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _base64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    payload_part = _base64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{_base64url(signature)}"


def sign_editor_config(config: dict[str, Any]) -> dict[str, Any]:
    secret = getattr(settings, "ONLYOFFICE_JWT_SECRET", "").strip()
    if not secret:
        return config
    signed_config = copy.deepcopy(config)
    signed_config["token"] = encode_jwt(signed_config, secret)
    return signed_config
