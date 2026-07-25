from __future__ import annotations

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated

from config.login_security import (
    clear_login_account_failures,
    login_block_status,
    record_login_failure,
)

from .responses import fail, ok
from .serializers import user_summary


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_token_view(request):
    return ok({"csrf_token": get_token(request)})


@api_view(["POST"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def login_view(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    if not username or not password:
        return fail("请输入账号和密码。", status=400)
    login_block = login_block_status(request, username)
    if login_block.blocked:
        response = fail(
            "登录尝试次数过多，请稍后再试；如忘记密码，请联系学校管理员。",
            status=429,
        )
        response["Retry-After"] = str(login_block.retry_after_seconds)
        return response
    user = authenticate(request, username=username, password=password)
    if user is None:
        record_login_failure(request, username)
        return fail("账号或密码不正确。", status=400)
    if not user.is_active:
        return fail("账号已停用，请联系管理员。", status=403)
    clear_login_account_failures(request, username)
    auth_login(request, user)
    return ok(user_summary(user), "登录成功")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    auth_logout(request)
    return ok({}, "已退出")


@api_view(["GET"])
@permission_classes([AllowAny])
def me_view(request):
    if not request.user.is_authenticated:
        return ok(None)
    return ok(user_summary(request.user))
