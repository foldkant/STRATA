from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache


@dataclass(frozen=True)
class LoginBlock:
    blocked: bool
    retry_after_seconds: int


def _client_address(request) -> str:
    return str(request.META.get("REMOTE_ADDR") or "unknown").strip()[:128]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _keys(request, username: str) -> tuple[str, str]:
    address_key = _digest(_client_address(request))
    account_key = _digest(str(username or "").strip().casefold())
    return (
        f"strata:login-failure:address:{address_key}",
        f"strata:login-failure:account:{account_key}",
    )


def _counter(key: str) -> int:
    try:
        return int(cache.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def login_block_status(request, username: str) -> LoginBlock:
    address_key, account_key = _keys(request, username)
    address_limit = max(int(settings.LOGIN_FAILURE_LIMIT_PER_ADDRESS), 1)
    account_limit = max(int(settings.LOGIN_FAILURE_LIMIT_PER_ACCOUNT), 1)
    blocked = (
        _counter(address_key) >= address_limit
        or _counter(account_key) >= account_limit
    )
    return LoginBlock(
        blocked=blocked,
        retry_after_seconds=max(int(settings.LOGIN_FAILURE_WINDOW_SECONDS), 60),
    )


def record_login_failure(request, username: str) -> None:
    window = max(int(settings.LOGIN_FAILURE_WINDOW_SECONDS), 60)
    for key in _keys(request, username):
        if cache.add(key, 1, timeout=window):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window)


def clear_login_account_failures(request, username: str) -> None:
    _address_key, account_key = _keys(request, username)
    cache.delete(account_key)


def clear_login_failures_for_username(username: str) -> None:
    """Allow an authorised password reset to immediately restore account access."""

    account_key = _digest(str(username or "").strip().casefold())
    cache.delete(f"strata:login-failure:account:{account_key}")
