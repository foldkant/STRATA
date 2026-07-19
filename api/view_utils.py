from django.core.paginator import Paginator

from .responses import fail


def paginate(request, rows, per_page=20):
    try:
        page_size = min(max(int(request.GET.get("page_size", per_page)), 1), 100)
    except ValueError:
        page_size = per_page
    return Paginator(rows, page_size).get_page(request.GET.get("page") or 1)


def current_school(request):
    return request.user.school


def service_error_response(exc):
    return fail(exc.message, errors=exc.errors, status=exc.status)
