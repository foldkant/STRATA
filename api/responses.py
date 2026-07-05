from __future__ import annotations

from rest_framework.response import Response


def ok(data=None, message: str = "ok", status: int = 200) -> Response:
    return Response({"data": data, "message": message}, status=status)


def fail(message: str, *, errors=None, status: int = 400) -> Response:
    return Response({"data": None, "message": message, "errors": errors or {}}, status=status)


def page_data(page) -> dict:
    return {
        "count": page.paginator.count,
        "page": page.number,
        "page_size": page.paginator.per_page,
        "results": list(page.object_list),
    }
