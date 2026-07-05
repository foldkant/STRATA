from __future__ import annotations

import base64
import hashlib
import hmac
import os

from django.conf import settings


def _root_key() -> bytes:
    raw = getattr(settings, "AI_SECRET_KEY", "") or settings.SECRET_KEY
    return hashlib.sha256(str(raw).encode("utf-8")).digest()


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < size:
        counter_bytes = counter.to_bytes(4, "big")
        chunks.append(hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:size]


def encrypt_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    key = _root_key()
    nonce = os.urandom(16)
    plain = text.encode("utf-8")
    mask = _stream(key, nonce, len(plain))
    cipher = bytes(left ^ right for left, right in zip(plain, mask))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    token = base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")
    return f"v1:{token}"


def decrypt_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if not text.startswith("v1:"):
        return ""
    try:
        raw = base64.urlsafe_b64decode(text[3:].encode("ascii"))
    except (ValueError, TypeError):
        return ""
    if len(raw) < 32:
        return ""
    nonce = raw[:16]
    tag = raw[16:32]
    cipher = raw[32:]
    key = _root_key()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        return ""
    mask = _stream(key, nonce, len(cipher))
    plain = bytes(left ^ right for left, right in zip(cipher, mask))
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return ""
