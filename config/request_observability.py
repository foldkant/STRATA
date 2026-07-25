from __future__ import annotations

import logging
import re
import time
import uuid

logger = logging.getLogger("xlzxedu.request")

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _request_id(request) -> str:
    supplied = str(request.headers.get("X-Request-ID", "")).strip()
    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


class RequestObservabilityMiddleware:
    """Attach a correlation id and log metadata without request or response bodies."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = _request_id(request)
        started_at = time.perf_counter()
        response = self.get_response(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response["X-Request-ID"] = request.request_id

        user = getattr(request, "user", None)
        user_id = getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
        user_role = getattr(user, "role", "") if user_id else ""
        try:
            response_bytes = int(response.get("Content-Length") or len(response.content))
        except (AttributeError, TypeError, ValueError):
            response_bytes = 0
        needs_attention = response.status_code >= 500 or duration_ms >= 2000 or response_bytes >= 500_000
        log_method = logger.warning if needs_attention else logger.info
        log_method(
            "request_completed",
            extra={
                "request_id": request.request_id,
                "http_method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "user_id": user_id,
                "user_role": user_role,
                "response_bytes": response_bytes,
            },
        )
        return response
