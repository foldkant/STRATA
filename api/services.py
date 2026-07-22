from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Max, Q
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from aiops.crypto import decrypt_secret, encrypt_secret
from aiops.models import TeacherAIProvider
from courses.models import (
    ClassroomActivity,
    ClassroomGroupCollaboration,
    ClassroomSession,
    Course,
    CourseClass,
    LearningWebPage,
    Lesson,
    LessonStep,
    Resource,
    ResourceFile,
    Subject,
)
from learning.models import (
    Feedback,
    LearningEvent,
    Notice,
    PretestPaper,
    PretestQuestion,
)
from learning_analytics.services.classroom_events import (
    ClassroomEventError,
    release_classroom_step_opportunities,
    withdraw_classroom_step_opportunities,
)
from learning_analytics.services.attendance_events import (
    AttendanceEventError,
    release_attendance_opportunities,
    withdraw_attendance_opportunities,
)
from learning_analytics.services.classroom_interaction_events import (
    ClassroomInteractionEventError,
    record_random_call_selected,
    release_quick_answer_opportunities,
    withdraw_quick_answer_opportunities,
)
from learning_analytics.services.evaluation_events import (
    EvaluationEventError,
    withdraw_classroom_evaluation_opportunities,
)
from learning_analytics.services.group_collaboration_events import (
    GroupCollaborationEventError,
    withdraw_group_collaboration_opportunities,
)
from learning_analytics.services.dual_write import EventWriteError
from learning_analytics.services.operational_events import (
    record_classroom_control_executed,
)
from ops.forms import PASSWORD_PATTERN, _matches
from ops.forms import (
    PERSON_NAME_PATTERN,
    PHONE_PATTERN,
    SchoolAdminCreateForm,
    SchoolAdminUpdateForm,
    SchoolForm,
)
from ops.models import AuditLog
from ops.xlsx import normalize_text, read_table_rows
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment
from school_admin.forms import TeacherCreateForm, TeacherUpdateForm
from ops.forms import TEACHING_PASSWORD_PATTERN
from .protected_files import protected_file_url
from .serializers import clean_resource_ext

USERNAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{4,31}$"
CLASS_NAME_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{1,64}$"
GRADE_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9届级年高初小\s\-]{0,32}$"
STUDENT_NO_PATTERN = r"^[A-Za-z0-9_-]{0,32}$"
SUBJECT_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9_-]{1,31}$"
COURSE_TITLE_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]{2,128}$"
RESOURCE_TITLE_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\._\-\s]{2,128}$"
BULK_LIMIT = 200
COURSE_COVER_MAX_SIZE = 5 * 1024 * 1024
COURSE_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
COURSE_COVER_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
RESOURCE_MAX_SIZE = 512 * 1024 * 1024
RESOURCE_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".svg",
    ".mp4",
    ".webm",
    ".mov",
    ".ogg",
    ".mp3",
    ".wav",
    ".m4a",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".md",
    ".rtf",
    ".html",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".py",
    ".java",
    ".c",
    ".cpp",
    ".zip",
    ".rar",
    ".7z",
}
CLASSROOM_COMMANDS = {
    "sign_in": {
        "activity_type": ClassroomActivity.ActivityType.SIGN_IN,
        "title": "课堂签到",
    },
    "random_pick": {
        "activity_type": ClassroomActivity.ActivityType.QUESTION,
        "title": "随机点名",
    },
    "quick_answer": {
        "activity_type": ClassroomActivity.ActivityType.QUICK_ANSWER,
        "title": "抢答",
    },
    "timer": {
        "activity_type": ClassroomActivity.ActivityType.TASK,
        "title": "课堂倒计时",
    },
    "broadcast": {
        "activity_type": ClassroomActivity.ActivityType.BROADCAST,
        "title": "课堂广播",
    },
}
LESSON_QUESTION_TYPES = {"single", "multiple", "judge", "blank", "text", "file"}
LESSON_QUESTION_TYPE_LABELS = {
    "single": "单选",
    "multiple": "多选",
    "judge": "判断",
    "blank": "填空",
    "text": "简答",
    "file": "附件提交",
}
LESSON_TARGET_LAYER_VALUES = {item.value for item in LessonStep.TargetLayer}
LESSON_FILE_DEFAULT_EXTENSIONS = [
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "pdf",
    "zip",
    "rar",
    "7z",
    "png",
    "jpg",
    "jpeg",
]
LESSON_FILE_ALLOWED_EXTENSIONS = set(
    LESSON_FILE_DEFAULT_EXTENSIONS
    + ["webp", "gif", "mp4", "webm", "mov", "mp3", "wav", "csv", "txt", "md"]
)
AI_LAYER_TARGETS = ("A", "B", "C", "A/B", "B/C")
CLASSROOM_EVALUATION_TYPES = ("self", "peer", "teacher")
LEARNING_PAGE_BLOCK_TYPES = {
    "content",
    "callout",
    "list",
    "steps",
    "cards",
    "table",
    "code",
    "visualization",
    "interactive",
    "form",
}
LEARNING_PAGE_FIELD_TYPES = {
    "single",
    "multiple",
    "select",
    "short_text",
    "long_text",
    "number",
    "scale",
}
LEARNING_PAGE_ACCENTS = {"blue", "green", "cyan", "amber", "red", "indigo"}
LEARNING_PAGE_VISUALIZATION_TYPES = {"process", "timeline", "bars", "binary"}
LEARNING_PAGE_VISUALIZATION_TONES = {"blue", "green", "cyan", "amber", "red", "indigo"}
LEARNING_PAGE_GENERATION_MODES = {"auto", "interactive", "structured"}
TEACHER_IMPORT_HEADERS = ["登录账号", "姓名", "联系电话", "初始密码", "状态"]
STUDENT_IMPORT_HEADERS = [
    "登录账号",
    "姓名",
    "学号",
    "班级",
    "联系电话",
    "初始密码",
    "层级",
    "小组号",
    "积分",
    "状态",
]
DEFAULT_AI_BASE_URL = "https://api.deepseek.com"
DEFAULT_AI_MODEL = "deepseek-v4-flash"
AI_MODEL_PATTERN = r"^[A-Za-z0-9._:\-]{2,64}$"
AI_KEY_PATTERN = r"^\S{10,512}$"


def _fullmatch(pattern: str, value: str) -> bool:
    return bool(re.fullmatch(pattern, value))


class ServiceError(Exception):
    def __init__(
        self, message: str, *, errors: dict | None = None, status: int = 400
    ) -> None:
        self.message = message
        self.errors = errors or {}
        self.status = status
        super().__init__(message)


def form_errors(form) -> dict[str, list[str]]:
    errors = {}
    for field, items in form.errors.get_json_data().items():
        errors[field] = [item["message"] for item in items]
    return errors


def client_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def write_audit(
    request,
    action: str,
    *,
    school=None,
    target_type: str = "",
    target_id: str | int = "",
    detail=None,
) -> None:
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        school=school,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else "",
        ip_address=client_ip(request),
        detail=detail or {},
    )


def _valid_base_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.query
        and not parsed.fragment
    )


def get_teacher_ai_provider(user) -> TeacherAIProvider:
    provider, _ = TeacherAIProvider.objects.get_or_create(
        teacher=user,
        provider=TeacherAIProvider.Provider.DEEPSEEK,
        defaults={
            "base_url": DEFAULT_AI_BASE_URL,
            "model": DEFAULT_AI_MODEL,
        },
    )
    return provider


def save_teacher_ai_provider(request, data) -> TeacherAIProvider:
    errors: dict[str, list[str]] = {}
    provider = get_teacher_ai_provider(request.user)
    provider_name = (
        str(data.get("provider", TeacherAIProvider.Provider.DEEPSEEK)).strip()
        or TeacherAIProvider.Provider.DEEPSEEK
    )
    base_url = (
        str(data.get("base_url", provider.base_url or DEFAULT_AI_BASE_URL))
        .strip()
        .rstrip("/")
        or DEFAULT_AI_BASE_URL
    )
    model = (
        str(data.get("model", provider.model or DEFAULT_AI_MODEL)).strip()
        or DEFAULT_AI_MODEL
    )
    api_key = str(data.get("api_key", "")).strip()
    clear_api_key = _clean_bool(data.get("clear_api_key", False))
    is_enabled = _clean_bool(data.get("is_enabled", provider.is_enabled))

    if provider_name != TeacherAIProvider.Provider.DEEPSEEK:
        errors["provider"] = ["当前第一版只支持 DeepSeek。"]
    if not _valid_base_url(base_url):
        errors["base_url"] = [
            "接口地址必须是有效的 http 或 https 地址，不能包含查询参数。"
        ]
    if not _fullmatch(AI_MODEL_PATTERN, model):
        errors["model"] = ["模型名称格式不正确。"]
    if api_key and not _fullmatch(AI_KEY_PATTERN, api_key):
        errors["api_key"] = ["API Key 格式不正确，不能包含空格，长度需为 10-512 位。"]
    if is_enabled and clear_api_key and not api_key:
        errors["api_key"] = ["启用 AI 前需要填写 API Key。"]
    if is_enabled and not api_key and not provider.api_key_encrypted:
        errors["api_key"] = ["启用 AI 前需要填写 API Key。"]

    if errors:
        raise ServiceError("AI 接入配置校验失败。", errors=errors, status=400)

    provider.provider = provider_name
    provider.base_url = base_url
    provider.model = model
    provider.is_enabled = is_enabled
    if clear_api_key:
        provider.api_key_encrypted = ""
        provider.api_key_hint = ""
        provider.is_enabled = False
    if api_key:
        provider.api_key_encrypted = encrypt_secret(api_key)
        provider.api_key_hint = api_key[-6:] if len(api_key) >= 6 else "***"
    provider.last_error = ""
    provider.save()
    write_audit(
        request,
        "teacher.ai_provider.save",
        school=request.user.school,
        target_type="teacher_ai_provider",
        target_id=provider.id,
        detail={
            "provider": provider.provider,
            "base_url": provider.base_url,
            "model": provider.model,
            "is_enabled": provider.is_enabled,
            "has_key": bool(provider.api_key_encrypted),
        },
    )
    return provider


def test_teacher_ai_provider(request) -> TeacherAIProvider:
    provider = get_teacher_ai_provider(request.user)
    api_key = decrypt_secret(provider.api_key_encrypted)
    if not api_key:
        provider.last_error = "尚未配置可用的 API Key。"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            provider.last_error, errors={"api_key": [provider.last_error]}, status=400
        )
    if not _valid_base_url(provider.base_url):
        provider.last_error = "接口地址格式不正确。"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            provider.last_error, errors={"base_url": [provider.last_error]}, status=400
        )

    endpoint = f"{provider.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": provider.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是 STRATA 数智教学系统的连接测试助手。",
                },
                {"role": "user", "content": "请只回复：连接正常"},
            ],
            "max_tokens": 16,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = response.read(4096)
            payload = json.loads(raw.decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="ignore")
        provider.last_error = (
            f"DeepSeek 返回 {exc.code}，请检查 Key、模型或接口地址。{detail[:160]}"
        )
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            "AI 接入测试失败。",
            errors={"connection": [provider.last_error]},
            status=400,
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        provider.last_error = f"连接失败：{exc}"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            "AI 接入测试失败。",
            errors={"connection": [provider.last_error]},
            status=400,
        )

    if not payload.get("choices"):
        provider.last_error = "接口已响应，但没有返回有效内容。"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            "AI 接入测试失败。",
            errors={"connection": [provider.last_error]},
            status=400,
        )

    provider.last_tested_at = timezone.now()
    provider.last_error = ""
    provider.save(update_fields=["last_tested_at", "last_error", "updated_at"])
    write_audit(
        request,
        "teacher.ai_provider.test",
        school=request.user.school,
        target_type="teacher_ai_provider",
        target_id=provider.id,
        detail={"provider": provider.provider, "model": provider.model, "ok": True},
    )
    return provider


def _call_teacher_chat_json(
    request, *, system_prompt: str, user_prompt: str, max_tokens: int = 1800
) -> dict:
    provider = get_teacher_ai_provider(request.user)
    api_key = decrypt_secret(provider.api_key_encrypted)
    if not provider.is_enabled:
        raise ServiceError(
            "教师 AI 辅助尚未启用，请先在 AI 接入中启用。",
            errors={"ai": ["教师 AI 辅助尚未启用。"]},
            status=400,
        )
    if not api_key:
        raise ServiceError(
            "尚未配置可用的 DeepSeek API Key。",
            errors={"api_key": ["请先在 AI 接入中填写 API Key。"]},
            status=400,
        )
    if not _valid_base_url(provider.base_url):
        raise ServiceError(
            "AI 接口地址格式不正确。",
            errors={"base_url": ["请检查 AI 接入中的接口地址。"]},
            status=400,
        )

    endpoint = f"{provider.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
            "max_tokens": max_tokens,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    request_timeout = 90 if max_tokens > 4000 else 45
    try:
        with urllib.request.urlopen(req, timeout=request_timeout) as response:
            raw = response.read(1024 * 256)
            payload = json.loads(raw.decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read(1024).decode("utf-8", errors="ignore")
        provider.last_error = f"DeepSeek 返回 {exc.code}：{detail[:240]}"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            "AI 生成失败，请检查 Key、模型或接口地址。",
            errors={"ai": [provider.last_error]},
            status=400,
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        provider.last_error = f"连接或解析失败：{exc}"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            "AI 生成失败，请检查网络和接口配置。",
            errors={"ai": [provider.last_error]},
            status=400,
        )

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        provider.last_error = "接口已响应，但没有返回有效内容。"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            "AI 生成失败。", errors={"ai": [provider.last_error]}, status=400
        )
    content = (
        choices[0].get("message", {}).get("content", "")
        if isinstance(choices[0], dict)
        else ""
    )
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        provider.last_error = f"AI 未返回合法 JSON：{exc}"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(
            "AI 生成结果格式不正确，请重试。",
            errors={"ai": [provider.last_error]},
            status=400,
        )
    if not isinstance(result, dict):
        raise ServiceError(
            "AI 生成结果格式不正确，请重试。",
            errors={"ai": ["返回值不是 JSON 对象。"]},
            status=400,
        )
    provider.last_error = ""
    provider.save(update_fields=["last_error", "updated_at"])
    return result














def _lesson_question_base_score(question_type: str) -> float:
    if question_type == "file":
        return 10.0
    if question_type == "text":
        return 5.0
    if question_type == "blank":
        return 3.0
    return 2.0












QUESTION_BANK_AI_TYPES = {"single", "multiple", "judge", "blank", "text"}
QUESTION_BANK_AI_DIFFICULTIES = {"easy", "normal", "hard"}






def _clean_id_list(data) -> list[int]:
    raw_ids = data.get("ids") if hasattr(data, "get") else None
    if not isinstance(raw_ids, list):
        raise ServiceError(
            "请选择要操作的数据。", errors={"ids": ["请选择要操作的数据。"]}, status=400
        )

    ids: list[int] = []
    errors: list[str] = []
    for raw_id in raw_ids:
        try:
            value = int(raw_id)
        except (TypeError, ValueError):
            errors.append(str(raw_id))
            continue
        if value <= 0:
            errors.append(str(raw_id))
            continue
        if value not in ids:
            ids.append(value)

    if errors:
        raise ServiceError(
            "所选数据包含无效编号。",
            errors={"ids": ["所选数据包含无效编号。"]},
            status=400,
        )
    if not ids:
        raise ServiceError(
            "请选择要操作的数据。", errors={"ids": ["请选择要操作的数据。"]}, status=400
        )
    if len(ids) > BULK_LIMIT:
        raise ServiceError(
            f"单次最多处理 {BULK_LIMIT} 条数据。",
            errors={"ids": [f"单次最多处理 {BULK_LIMIT} 条数据。"]},
            status=400,
        )
    return ids


def _ensure_all_selected(
    found_ids: set[int], requested_ids: list[int], label: str
) -> None:
    missing = [str(item_id) for item_id in requested_ids if item_id not in found_ids]
    if missing:
        raise ServiceError(
            f"部分{label}不存在或无权操作。",
            errors={"ids": [f"无权限或不存在：{', '.join(missing)}"]},
            status=404,
        )


def save_school(request, data, *, school: School | None = None) -> School:
    form = SchoolForm(data, instance=school)
    if not form.is_valid():
        raise ServiceError("学校信息校验失败。", errors=form_errors(form), status=400)
    saved_school = form.save()
    write_audit(
        request,
        "school.update" if school else "school.create",
        school=saved_school,
        target_type="school",
        target_id=saved_school.id,
        detail={"code": saved_school.code, "name": saved_school.name},
    )
    return saved_school


def delete_school(request, school: School) -> None:
    if school.status == School.Status.ACTIVE:
        raise ServiceError("请先将学校停用或归档，再执行删除。", status=400)

    blockers = []
    if school.classes.exists():
        blockers.append("班级")
    if school.users.exists():
        blockers.append("账号")
    if school.import_batches.exists():
        blockers.append("采集记录")
    if school.export_batches.exists():
        blockers.append("导出记录")
    if blockers:
        raise ServiceError(
            f"该学校已有{', '.join(blockers)}关联，不能物理删除；请保持停用或归档状态。",
            status=400,
        )

    detail = {"code": school.code, "name": school.name}
    target_id = school.id
    school.delete()
    write_audit(
        request,
        "school.delete",
        target_type="school",
        target_id=target_id,
        detail=detail,
    )


@transaction.atomic
def bulk_disable_schools(request, data) -> dict:
    ids = _clean_id_list(data)
    schools = list(
        School.objects.filter(id__in=ids, is_synthetic=False).order_by("name", "code")
    )
    _ensure_all_selected({school.id for school in schools}, ids, "学校")

    updated = 0
    for school in schools:
        if school.status == School.Status.ACTIVE:
            school.status = School.Status.DISABLED
            school.save(update_fields=["status", "updated_at"])
            updated += 1

    write_audit(
        request,
        "school.bulk_disable",
        target_type="school",
        detail={"ids": ids, "updated": updated},
    )
    return {"requested_count": len(ids), "updated_count": updated}


def bulk_delete_schools(request, data) -> dict:
    ids = _clean_id_list(data)
    schools = list(
        School.objects.filter(id__in=ids, is_synthetic=False).order_by("name", "code")
    )
    _ensure_all_selected({school.id for school in schools}, ids, "学校")

    active = [school for school in schools if school.status == School.Status.ACTIVE]
    if active:
        raise ServiceError(
            "所选学校包含启用状态，请先批量停用或归档后再删除。",
            errors={
                "ids": [f"未停用或归档：{', '.join(school.name for school in active)}"]
            },
            status=400,
        )

    deleted = 0
    blocked = []
    for school in schools:
        try:
            delete_school(request, school)
            deleted += 1
        except ServiceError as exc:
            blocked.append(
                {"id": school.id, "name": school.name, "reason": exc.message}
            )

    if blocked:
        message = f"已删除 {deleted} 个学校，{len(blocked)} 个学校已有业务数据，已保留当前状态。"
    else:
        message = f"已删除 {deleted} 个学校。"
    return {
        "requested_count": len(ids),
        "deleted_count": deleted,
        "blocked": blocked,
        "message": message,
    }


def create_school_admin(request, data):
    form = SchoolAdminCreateForm(data)
    if not form.is_valid():
        raise ServiceError(
            "学校管理员信息校验失败。", errors=form_errors(form), status=400
        )

    User = get_user_model()
    user = User.objects.create_user(
        username=form.cleaned_data["username"],
        password=form.cleaned_data["password"],
        display_name=form.cleaned_data["display_name"],
        phone=form.cleaned_data["phone"],
        role="school_admin",
        school=form.cleaned_data["school"],
        is_active=form.cleaned_data["is_active"],
        is_staff=False,
        is_first_login=True,
    )
    write_audit(
        request,
        "school_admin.create",
        school=user.school,
        target_type="user",
        target_id=user.id,
        detail={"username": user.username},
    )
    return user


def update_school_admin(request, user, data):
    form = SchoolAdminUpdateForm(data, user=user)
    if not form.is_valid():
        raise ServiceError(
            "学校管理员信息校验失败。", errors=form_errors(form), status=400
        )

    user.school = form.cleaned_data["school"]
    user.username = form.cleaned_data["username"]
    user.display_name = form.cleaned_data["display_name"]
    user.phone = form.cleaned_data["phone"]
    user.is_active = form.cleaned_data["is_active"]
    if form.cleaned_data["password"]:
        user.set_password(form.cleaned_data["password"])
        user.is_first_login = True
    user.save()
    write_audit(
        request,
        "school_admin.update",
        school=user.school,
        target_type="user",
        target_id=user.id,
        detail={"username": user.username},
    )
    return user


def create_teacher(request, data):
    form = TeacherCreateForm(data, school=request.user.school)
    if not form.is_valid():
        raise ServiceError("教师信息校验失败。", errors=form_errors(form), status=400)

    User = get_user_model()
    teacher = User.objects.create_user(
        username=form.cleaned_data["username"],
        password=form.cleaned_data["password"],
        display_name=form.cleaned_data["display_name"],
        phone=form.cleaned_data["phone"],
        role="teacher",
        school=request.user.school,
        is_active=form.cleaned_data["is_active"],
        is_staff=False,
        is_first_login=True,
    )
    write_audit(
        request,
        "teacher.create",
        school=request.user.school,
        target_type="user",
        target_id=teacher.id,
        detail={"username": teacher.username},
    )
    return teacher


def update_teacher(request, teacher, data):
    form = TeacherUpdateForm(data, teacher=teacher, school=request.user.school)
    if not form.is_valid():
        raise ServiceError("教师信息校验失败。", errors=form_errors(form), status=400)

    teacher.username = form.cleaned_data["username"]
    teacher.display_name = form.cleaned_data["display_name"]
    teacher.phone = form.cleaned_data["phone"]
    teacher.is_active = form.cleaned_data["is_active"]
    teacher.save()
    write_audit(
        request,
        "teacher.update",
        school=request.user.school,
        target_type="user",
        target_id=teacher.id,
        detail={"username": teacher.username},
    )
    return teacher


def _validate_teacher_import(request, rows: list[dict]) -> tuple[list[dict], list[str]]:
    User = get_user_model()
    errors = []
    records = []
    seen_usernames = set()

    for row in rows:
        username = normalize_text(row.get("登录账号"))
        display_name = normalize_text(row.get("姓名"))
        phone = normalize_text(row.get("联系电话"))
        password = normalize_text(row.get("初始密码"))
        active = _active_value(row.get("状态"), default=True)
        existing_user = (
            User.objects.filter(username=username).first() if username else None
        )

        if not _fullmatch(USERNAME_PATTERN, username):
            errors.append(
                _row_error(
                    row,
                    "登录账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 teacher1。",
                )
            )
        if username in seen_usernames:
            errors.append(_row_error(row, f"登录账号 {username} 在文件中重复。"))
        seen_usernames.add(username)
        if not _matches(PERSON_NAME_PATTERN, display_name):
            errors.append(_row_error(row, "姓名需为 2-24 位中文或字母。"))
        if phone and not _matches(PHONE_PATTERN, phone):
            errors.append(_row_error(row, "联系电话格式不正确。"))
        if active is None:
            errors.append(_row_error(row, "状态只能填写启用或停用。"))
        if existing_user and existing_user.role != "teacher":
            errors.append(_row_error(row, f"登录账号 {username} 已被其他角色占用。"))
        if existing_user and existing_user.school_id != request.user.school_id:
            errors.append(
                _row_error(row, f"登录账号 {username} 不属于本校，不能更新。")
            )
        if not existing_user and not password:
            errors.append(_row_error(row, "新增教师必须填写初始密码。"))
        if password and not _matches(TEACHING_PASSWORD_PATTERN, password):
            errors.append(
                _row_error(
                    row, "教师初始密码需为 6-32 位，可使用字母、数字和常用符号。"
                )
            )

        records.append(
            {
                "username": username,
                "display_name": display_name,
                "phone": phone,
                "password": password,
                "is_active": active if active is not None else True,
                "existing_user": existing_user,
            }
        )

    return records, errors


@transaction.atomic
def import_teachers_from_xlsx(request, uploaded_file) -> dict:
    rows = read_table_rows(
        uploaded_file,
        required_headers=["登录账号", "姓名"],
        all_headers=TEACHER_IMPORT_HEADERS,
    )
    if not rows:
        raise ServiceError("Excel 文件没有可导入的数据行。", status=400)

    records, errors = _validate_teacher_import(request, rows)
    if errors:
        raise ServiceError(
            "教师批量导入校验失败。", errors={"rows": errors[:100]}, status=400
        )

    User = get_user_model()
    created_count = 0
    updated_count = 0
    for record in records:
        existing_user = record["existing_user"]
        if existing_user:
            existing_user.display_name = record["display_name"]
            existing_user.phone = record["phone"]
            existing_user.is_active = record["is_active"]
            if record["password"]:
                existing_user.set_password(record["password"])
                existing_user.is_first_login = True
            existing_user.save()
            updated_count += 1
        else:
            User.objects.create_user(
                username=record["username"],
                password=record["password"],
                display_name=record["display_name"],
                phone=record["phone"],
                role="teacher",
                school=request.user.school,
                is_active=record["is_active"],
                is_staff=False,
                is_first_login=True,
            )
            created_count += 1

    write_audit(
        request,
        "teacher.bulk_import",
        school=request.user.school,
        target_type="user",
        detail={"created": created_count, "updated": updated_count},
    )
    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "total_count": len(records),
    }


def _clean_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "active", "enabled", "启用"}
    return bool(value)


def _active_value(value: str, *, default=True) -> bool | None:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"启用", "正常", "是", "1", "true", "active", "enabled"}:
        return True
    if text in {"停用", "禁用", "否", "0", "false", "disabled", "inactive"}:
        return False
    return None




def _row_error(row: dict, message: str) -> str:
    return f"第 {row.get('__row_number', '?')} 行：{message}"


def _clean_optional_int(
    value,
    field: str,
    errors: dict,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
):
    if value in {None, ""}:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors[field] = ["请输入整数。"]
        return None
    if min_value is not None and number < min_value:
        errors[field] = [f"不能小于 {min_value}。"]
    if max_value is not None and number > max_value:
        errors[field] = [f"不能大于 {max_value}。"]
    return number


def _clean_float(value, field: str, errors: dict, *, default=0.0):
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        errors[field] = ["请输入数字。"]
        return default


def save_class_group(
    request, data, *, class_group: ClassGroup | None = None
) -> ClassGroup:
    errors: dict[str, list[str]] = {}
    is_create = class_group is None
    name = str(data.get("name", "")).strip()
    grade = str(data.get("grade", "")).strip()
    status = (
        str(data.get("status", ClassGroup.Status.ACTIVE)).strip()
        or ClassGroup.Status.ACTIVE
    )
    entry_year = _clean_optional_int(
        data.get("entry_year"), "entry_year", errors, min_value=1900, max_value=2100
    )

    if not _fullmatch(CLASS_NAME_PATTERN, name):
        errors["name"] = [
            "班级名称需为 1-64 位，可包含中文、字母、数字、空格、括号和短横线。"
        ]
    if grade and not _fullmatch(GRADE_PATTERN, grade):
        errors["grade"] = ["年级格式不正确。"]
    if status not in {item.value for item in ClassGroup.Status}:
        errors["status"] = ["状态只能为启用、停用或归档。"]

    queryset = ClassGroup.objects.filter(school=request.user.school, name=name)
    if class_group is not None:
        queryset = queryset.exclude(pk=class_group.pk)
    if name and queryset.exists():
        errors["name"] = ["本校已存在同名班级。"]

    if errors:
        raise ServiceError("班级信息校验失败。", errors=errors, status=400)

    if class_group is None:
        class_group = ClassGroup(school=request.user.school)
    class_group.name = name
    class_group.grade = grade
    class_group.entry_year = entry_year
    class_group.status = status
    class_group.save()
    write_audit(
        request,
        "class.create" if is_create else "class.update",
        school=request.user.school,
        target_type="class_group",
        target_id=class_group.id,
        detail={
            "name": class_group.name,
            "grade": class_group.grade,
            "status": class_group.status,
        },
    )
    return class_group


@transaction.atomic
def bulk_create_class_groups(request, data) -> list[ClassGroup]:
    errors: dict[str, list[str]] = {}
    grade = str(data.get("grade", "")).strip()
    status = (
        str(data.get("status", ClassGroup.Status.ACTIVE)).strip()
        or ClassGroup.Status.ACTIVE
    )
    entry_year = _clean_optional_int(
        data.get("entry_year"), "entry_year", errors, min_value=1900, max_value=2100
    )
    class_count = _clean_optional_int(
        data.get("class_count"), "class_count", errors, min_value=1, max_value=80
    )
    start_no = (
        _clean_optional_int(
            data.get("start_no"), "start_no", errors, min_value=1, max_value=999
        )
        or 1
    )

    if not grade:
        errors["grade"] = ["年级不能为空。"]
    elif not _fullmatch(GRADE_PATTERN, grade):
        errors["grade"] = ["年级格式不正确。"]
    if entry_year is None:
        errors["entry_year"] = ["入学年份不能为空。"]
    if class_count is None:
        errors["class_count"] = ["班级数量不能为空。"]
    if status not in {item.value for item in ClassGroup.Status}:
        errors["status"] = ["状态只能为启用、停用或归档。"]

    generated_names: list[str] = []
    if grade and class_count:
        generated_names = [
            f"{grade}{number}班" for number in range(start_no, start_no + class_count)
        ]
        invalid_names = [
            name for name in generated_names if not _fullmatch(CLASS_NAME_PATTERN, name)
        ]
        if invalid_names:
            errors["grade"] = ["生成的班级名称格式不正确，请调整年级或起始序号。"]
        existing_names = set(
            ClassGroup.objects.filter(
                school=request.user.school, name__in=generated_names
            ).values_list("name", flat=True)
        )
        if existing_names:
            errors["class_count"] = [
                f"以下班级已存在：{', '.join(sorted(existing_names))}。"
            ]

    if errors:
        raise ServiceError("批量新增班级校验失败。", errors=errors, status=400)

    created = [
        ClassGroup(
            school=request.user.school,
            name=name,
            grade=grade,
            entry_year=entry_year,
            status=status,
        )
        for name in generated_names
    ]
    ClassGroup.objects.bulk_create(created)
    saved = list(
        ClassGroup.objects.filter(
            school=request.user.school, name__in=generated_names
        ).order_by("name")
    )
    write_audit(
        request,
        "class.bulk_create",
        school=request.user.school,
        target_type="class_group",
        detail={
            "grade": grade,
            "entry_year": entry_year,
            "class_count": class_count,
            "start_no": start_no,
            "names": generated_names,
        },
    )
    return saved


@transaction.atomic
def promote_class_groups(request, data) -> list[ClassGroup]:
    errors: dict[str, list[str]] = {}
    from_grade = str(data.get("from_grade", "")).strip()
    to_grade = str(data.get("to_grade", "")).strip()

    if not from_grade:
        errors["from_grade"] = ["原年级不能为空。"]
    elif not _fullmatch(GRADE_PATTERN, from_grade):
        errors["from_grade"] = ["原年级格式不正确。"]
    if not to_grade:
        errors["to_grade"] = ["目标年级不能为空。"]
    elif not _fullmatch(GRADE_PATTERN, to_grade):
        errors["to_grade"] = ["目标年级格式不正确。"]
    if from_grade and to_grade and from_grade == to_grade:
        errors["to_grade"] = ["目标年级不能与原年级相同。"]

    classes = list(
        ClassGroup.objects.filter(
            school=request.user.school, grade=from_grade
        ).order_by("name")
    )
    if from_grade and not classes:
        errors["from_grade"] = ["没有找到该年级的班级。"]

    rename_pairs: list[tuple[ClassGroup, str]] = []
    for class_group in classes:
        if class_group.name.startswith(from_grade):
            new_name = f"{to_grade}{class_group.name[len(from_grade) :]}"
        else:
            new_name = class_group.name.replace(from_grade, to_grade, 1)
        if not _fullmatch(CLASS_NAME_PATTERN, new_name):
            errors["to_grade"] = ["生成的目标班级名称格式不正确。"]
            break
        rename_pairs.append((class_group, new_name))

    target_names = [name for _, name in rename_pairs]
    existing_names = set(
        ClassGroup.objects.filter(school=request.user.school, name__in=target_names)
        .exclude(id__in=[class_group.id for class_group, _ in rename_pairs])
        .values_list("name", flat=True)
    )
    if existing_names:
        errors["to_grade"] = [
            f"以下目标班级已存在：{', '.join(sorted(existing_names))}。"
        ]

    if errors:
        raise ServiceError("升班校验失败。", errors=errors, status=400)

    for class_group, new_name in rename_pairs:
        class_group.grade = to_grade
        class_group.name = new_name
        class_group.save(update_fields=["grade", "name"])

    write_audit(
        request,
        "class.promote",
        school=request.user.school,
        target_type="class_group",
        detail={
            "from_grade": from_grade,
            "to_grade": to_grade,
            "count": len(rename_pairs),
            "names": target_names,
        },
    )
    return [class_group for class_group, _ in rename_pairs]


def delete_class_group(request, class_group: ClassGroup) -> None:
    if class_group.status == ClassGroup.Status.ACTIVE:
        raise ServiceError("请先将班级停用或归档，再执行删除。", status=400)

    blockers = []
    if class_group.students.exists():
        blockers.append("学生")
    if class_group.learningevent_set.exists():
        blockers.append("学习行为")
    if class_group.studentfeaturesnapshot_set.exists():
        blockers.append("特征快照")
    if class_group.stratificationdecision_set.exists():
        blockers.append("分层记录")
    if class_group.model_versions.exists():
        blockers.append("模型版本")
    if class_group.training_jobs.exists():
        blockers.append("训练任务")
    if blockers:
        raise ServiceError(
            f"该班级已有{', '.join(blockers)}关联，不能物理删除；请保持停用或归档状态。",
            status=400,
        )

    detail = {
        "name": class_group.name,
        "grade": class_group.grade,
        "school": request.user.school.name,
    }
    target_id = class_group.id
    class_group.delete()
    write_audit(
        request,
        "class.delete",
        school=request.user.school,
        target_type="class_group",
        target_id=target_id,
        detail=detail,
    )


def _class_group_brief(class_group: ClassGroup, reason: str = "") -> dict:
    return {
        "id": class_group.id,
        "name": class_group.name,
        "grade": class_group.grade,
        "reason": reason,
    }


def _account_brief(user, reason: str = "") -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "reason": reason,
    }




@transaction.atomic
def bulk_disable_teacher_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    teachers = User.objects.filter(
        id__in=ids, school=request.user.school, role="teacher"
    ).order_by("username")
    return bulk_disable_accounts(
        request,
        teachers,
        ids,
        label="教师",
        action_prefix="teacher",
        school=request.user.school,
    )


def bulk_delete_teacher_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    teachers = User.objects.filter(
        id__in=ids, school=request.user.school, role="teacher"
    ).order_by("username")
    return bulk_delete_accounts(
        request, teachers, ids, label="教师", action_prefix="teacher"
    )






@transaction.atomic
def bulk_disable_class_groups(request, data) -> dict:
    ids = _clean_id_list(data)
    classes = list(
        ClassGroup.objects.filter(id__in=ids, school=request.user.school).order_by(
            "grade", "name"
        )
    )
    _ensure_all_selected({class_group.id for class_group in classes}, ids, "班级")

    updated = 0
    for class_group in classes:
        if class_group.status == ClassGroup.Status.ACTIVE:
            class_group.status = ClassGroup.Status.DISABLED
            class_group.save(update_fields=["status"])
            updated += 1

    write_audit(
        request,
        "class.bulk_disable",
        school=request.user.school,
        target_type="class_group",
        detail={"ids": ids, "updated": updated},
    )
    return {"requested_count": len(ids), "updated_count": updated}


def bulk_delete_class_groups(request, data) -> dict:
    ids = _clean_id_list(data)
    classes = list(
        ClassGroup.objects.filter(id__in=ids, school=request.user.school).order_by(
            "grade", "name"
        )
    )
    _ensure_all_selected({class_group.id for class_group in classes}, ids, "班级")

    active = [
        class_group
        for class_group in classes
        if class_group.status == ClassGroup.Status.ACTIVE
    ]
    if active:
        raise ServiceError(
            "所选班级包含启用状态，请先批量停用或归档后再删除。",
            errors={
                "ids": [
                    f"未停用或归档：{', '.join(class_group.name for class_group in active)}"
                ]
            },
            status=400,
        )

    deleted = 0
    blocked = []
    for class_group in classes:
        try:
            delete_class_group(request, class_group)
            deleted += 1
        except ServiceError as exc:
            blocked.append(_class_group_brief(class_group, exc.message))

    if blocked:
        message = f"已删除 {deleted} 个班级，{len(blocked)} 个班级已有业务数据，已保留当前状态。"
    else:
        message = f"已删除 {deleted} 个班级。"
    return {
        "requested_count": len(ids),
        "deleted_count": deleted,
        "blocked": blocked,
        "message": message,
    }


@transaction.atomic
def graduate_class_groups(request, data) -> dict:
    ids = _clean_id_list(data)
    classes = list(
        ClassGroup.objects.filter(id__in=ids, school=request.user.school)
        .prefetch_related("students__user")
        .order_by("grade", "name")
    )
    _ensure_all_selected({class_group.id for class_group in classes}, ids, "班级")

    now = timezone.now()
    disabled_students = 0
    for class_group in classes:
        class_group.status = ClassGroup.Status.ARCHIVED
        class_group.graduated_at = now
        class_group.graduated_by = request.user
        class_group.save(update_fields=["status", "graduated_at", "graduated_by"])
        for profile in class_group.students.all():
            if profile.user.is_active:
                set_student_active(request, profile, False)
                disabled_students += 1

    write_audit(
        request,
        "class.graduate",
        school=request.user.school,
        target_type="class_group",
        detail={
            "ids": ids,
            "class_count": len(classes),
            "disabled_students": disabled_students,
            "graduated_at": now.isoformat(),
        },
    )
    return {
        "graduated_count": len(classes),
        "disabled_students": disabled_students,
        "graduated_at": now,
    }


def _school_teacher(request, teacher_id, errors):
    User = get_user_model()
    try:
        return User.objects.get(
            pk=teacher_id, school=request.user.school, role="teacher"
        )
    except (User.DoesNotExist, TypeError, ValueError):
        errors["teacher"] = ["请选择本校教师。"]
        return None


def _school_class(request, class_group_id, errors):
    try:
        return ClassGroup.objects.get(pk=class_group_id, school=request.user.school)
    except (ClassGroup.DoesNotExist, TypeError, ValueError):
        errors["class_group"] = ["请选择本校班级。"]
        return None


def _teaching_assignment_payload(
    request, data, *, assignment: TeachingAssignment | None = None
):
    errors: dict[str, list[str]] = {}
    class_group = _school_class(request, data.get("class_group"), errors)
    teacher = _school_teacher(request, data.get("teacher"), errors)

    if class_group and teacher:
        queryset = TeachingAssignment.objects.filter(
            school=request.user.school,
            class_group=class_group,
            teacher=teacher,
        )
        if assignment is not None:
            queryset = queryset.exclude(pk=assignment.pk)
        if queryset.exists():
            errors["class_group"] = ["该教师已任教该班级。"]

    return {
        "errors": errors,
        "class_group": class_group,
        "teacher": teacher,
    }


def _sync_teaching_teacher_link(school, class_group: ClassGroup, teacher) -> None:
    has_assignment = TeachingAssignment.objects.filter(
        school=school,
        class_group=class_group,
        teacher=teacher,
    ).exists()
    if has_assignment:
        class_group.teachers.add(teacher)
    else:
        class_group.teachers.remove(teacher)


@transaction.atomic
def bulk_save_teaching_assignments(request, data) -> dict:
    errors: dict[str, list[str]] = {}
    teacher = _school_teacher(request, data.get("teacher"), errors)

    class_ids = data.get("class_groups")
    if not isinstance(class_ids, list):
        errors["class_groups"] = ["班级数据格式不正确。"]
        class_ids = []

    cleaned_class_ids = []
    for raw_id in class_ids:
        try:
            class_id = int(raw_id)
        except (TypeError, ValueError):
            errors["class_groups"] = ["班级编号不正确。"]
            continue
        if class_id not in cleaned_class_ids:
            cleaned_class_ids.append(class_id)

    classes = list(
        ClassGroup.objects.filter(
            school=request.user.school, id__in=cleaned_class_ids
        ).order_by("grade", "name")
    )
    if len(classes) != len(cleaned_class_ids):
        errors["class_groups"] = ["部分班级不存在或不属于本校。"]

    if errors:
        raise ServiceError("批量任课关系校验失败。", errors=errors, status=400)

    old_class_groups = list(
        ClassGroup.objects.filter(
            teaching_assignments__school=request.user.school,
            teaching_assignments__teacher=teacher,
        )
        .distinct()
        .order_by("grade", "name")
    )
    old_ids = {class_group.id for class_group in old_class_groups}
    new_ids = {class_group.id for class_group in classes}
    removed_class_groups = [
        class_group for class_group in old_class_groups if class_group.id not in new_ids
    ]

    deleted_count, _ = (
        TeachingAssignment.objects.filter(
            school=request.user.school,
            teacher=teacher,
        )
        .exclude(class_group_id__in=new_ids)
        .delete()
    )

    created_count = 0
    updated_count = 0
    for class_group in classes:
        assignment = TeachingAssignment.objects.filter(
            school=request.user.school,
            class_group=class_group,
            teacher=teacher,
        ).first()
        if assignment is None:
            assignment = TeachingAssignment(
                school=request.user.school,
                class_group=class_group,
                teacher=teacher,
            )
            created_count += 1
        else:
            updated_count += 1
        assignment.save()
        _sync_teaching_teacher_link(request.user.school, class_group, teacher)
    for class_group in removed_class_groups:
        _sync_teaching_teacher_link(request.user.school, class_group, teacher)

    write_audit(
        request,
        "teaching_assignment.bulk_save",
        school=request.user.school,
        target_type="teaching_assignment",
        detail={
            "teacher": teacher.username,
            "class_count": len(classes),
            "created": created_count,
            "updated": updated_count,
            "removed": deleted_count,
            "previous_class_count": len(old_ids),
        },
    )
    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "deleted_count": deleted_count,
        "total_count": len(classes),
    }


@transaction.atomic
def save_teaching_assignment(
    request, data, *, assignment: TeachingAssignment | None = None
) -> TeachingAssignment:
    cleaned = _teaching_assignment_payload(request, data, assignment=assignment)
    if cleaned["errors"]:
        raise ServiceError("任课关系校验失败。", errors=cleaned["errors"], status=400)

    is_create = assignment is None
    old_class_group = assignment.class_group if assignment is not None else None
    old_teacher = assignment.teacher if assignment is not None else None
    if assignment is None:
        assignment = TeachingAssignment(school=request.user.school)
    assignment.class_group = cleaned["class_group"]
    assignment.teacher = cleaned["teacher"]
    try:
        assignment.save()
    except IntegrityError:
        raise ServiceError(
            "任课关系校验失败。",
            errors={"class_group": ["该教师已任教该班级。"]},
            status=400,
        )

    if old_class_group is not None and old_teacher is not None:
        _sync_teaching_teacher_link(request.user.school, old_class_group, old_teacher)
    _sync_teaching_teacher_link(
        request.user.school, assignment.class_group, assignment.teacher
    )

    write_audit(
        request,
        "teaching_assignment.create" if is_create else "teaching_assignment.update",
        school=request.user.school,
        target_type="teaching_assignment",
        target_id=assignment.id,
        detail={
            "class_group": assignment.class_group.name,
            "teacher": assignment.teacher.username,
        },
    )
    return assignment


@transaction.atomic
def delete_teaching_assignment(request, assignment: TeachingAssignment) -> None:
    detail = {
        "class_group": assignment.class_group.name,
        "teacher": assignment.teacher.username,
    }
    target_id = assignment.id
    class_group = assignment.class_group
    teacher = assignment.teacher
    assignment.delete()
    _sync_teaching_teacher_link(request.user.school, class_group, teacher)
    write_audit(
        request,
        "teaching_assignment.delete",
        school=request.user.school,
        target_type="teaching_assignment",
        target_id=target_id,
        detail=detail,
    )




















def set_account_active(request, user, is_active: bool, *, action_prefix: str) -> None:
    if user.is_active == is_active:
        return
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    write_audit(
        request,
        f"{action_prefix}.enable" if is_active else f"{action_prefix}.disable",
        school=user.school,
        target_type="user",
        target_id=user.id,
        detail={"username": user.username},
    )


@transaction.atomic
def bulk_disable_accounts(
    request, users, ids: list[int], *, label: str, action_prefix: str, school=None
) -> dict:
    users = list(users)
    _ensure_all_selected({user.id for user in users}, ids, label)

    updated = 0
    for user in users:
        if user.is_active:
            set_account_active(request, user, False, action_prefix=action_prefix)
            updated += 1

    write_audit(
        request,
        f"{action_prefix}.bulk_disable",
        school=school,
        target_type="user",
        detail={"ids": ids, "updated": updated},
    )
    return {"requested_count": len(ids), "updated_count": updated}


def bulk_delete_accounts(
    request, users, ids: list[int], *, label: str, action_prefix: str
) -> dict:
    users = list(users)
    _ensure_all_selected({user.id for user in users}, ids, label)

    active = [user for user in users if user.is_active]
    if active:
        raise ServiceError(
            f"所选{label}包含启用账号，请先批量停用后再删除。",
            errors={"ids": [f"未停用：{', '.join(user.username for user in active)}"]},
            status=400,
        )

    deleted = 0
    blocked = []
    for user in users:
        try:
            delete_account(request, user, action_prefix=action_prefix)
            deleted += 1
        except ServiceError as exc:
            blocked.append(_account_brief(user, exc.message))

    if blocked:
        message = f"已删除 {deleted} 个{label}，{len(blocked)} 个{label}已有业务数据，已保留停用状态。"
    else:
        message = f"已删除 {deleted} 个{label}。"
    return {
        "requested_count": len(ids),
        "deleted_count": deleted,
        "blocked": blocked,
        "message": message,
    }


def bulk_disable_school_admin_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    users = (
        User.objects.filter(id__in=ids, role="school_admin")
        .select_related("school")
        .order_by("school__name", "username")
    )
    return bulk_disable_accounts(
        request, users, ids, label="学校管理员", action_prefix="school_admin"
    )


def bulk_delete_school_admin_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    users = (
        User.objects.filter(id__in=ids, role="school_admin")
        .select_related("school")
        .order_by("school__name", "username")
    )
    return bulk_delete_accounts(
        request, users, ids, label="学校管理员", action_prefix="school_admin"
    )


def _account_delete_blockers(user) -> list[str]:
    checks = [
        ("课程", lambda: user.courses.exists()),
        ("资源", lambda: user.resources.exists()),
        ("学习行为", lambda: user.learning_events.exists()),
        ("任课班级", lambda: user.teaching_classes.exists()),
        ("任课关系", lambda: user.teaching_assignments.exists()),
        ("分层审核", lambda: user.reviewed_layer_decisions.exists()),
        ("导出批次", lambda: user.created_export_batches.exists()),
        ("采集批次", lambda: user.uploaded_import_batches.exists()),
    ]
    blockers = []
    for label, exists in checks:
        try:
            if exists():
                blockers.append(label)
        except Exception:
            continue
    try:
        if user.student_profile:
            blockers.append("学生档案")
    except Exception:
        pass
    return blockers


@transaction.atomic
def delete_account(request, user, *, action_prefix: str) -> None:
    if user.is_active:
        raise ServiceError(
            "该账号仍处于启用状态。请先停用账号，再执行删除。", status=400
        )
    blockers = _account_delete_blockers(user)
    if blockers:
        raise ServiceError(
            f"该账号已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。",
            status=400,
        )

    detail = {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "school": user.school.name if user.school else "",
    }
    school = user.school
    target_id = user.id
    user.delete()
    write_audit(
        request,
        f"{action_prefix}.delete",
        school=school,
        target_type="user",
        target_id=target_id,
        detail=detail,
    )


def reset_school_admin_password(request, user, password: str) -> None:
    if not _matches(PASSWORD_PATTERN, password):
        raise ServiceError(
            "密码需为 8-32 位，并至少包含字母和数字。",
            errors={"password": ["密码需为 8-32 位，并至少包含字母和数字。"]},
        )
    user.set_password(password)
    user.is_first_login = True
    user.save(update_fields=["password", "is_first_login"])
    write_audit(
        request,
        "school_admin.reset_password",
        school=user.school,
        target_type="user",
        target_id=user.id,
        detail={"username": user.username},
    )


def reset_teacher_password(request, teacher, password: str) -> None:
    if not _matches(TEACHING_PASSWORD_PATTERN, password):
        raise ServiceError(
            "教师密码需为 6-32 位，可使用字母、数字和常用符号。",
            errors={"password": ["教师密码需为 6-32 位，可使用字母、数字和常用符号。"]},
        )
    teacher.set_password(password)
    teacher.is_first_login = True
    teacher.save(update_fields=["password", "is_first_login"])
    write_audit(
        request,
        "teacher.reset_password",
        school=request.user.school,
        target_type="user",
        target_id=teacher.id,
        detail={"username": teacher.username},
    )


def save_subject(request, data, *, subject: Subject | None = None) -> Subject:
    errors: dict[str, list[str]] = {}
    name = str(data.get("name", "")).strip()
    code = str(data.get("code", "")).strip().upper()
    is_active = _clean_bool(data.get("is_active", True))

    if not _fullmatch(r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{2,64}$", name):
        errors["name"] = ["学科名称需为 2-64 位，可包含中文、字母和数字。"]
    if not _fullmatch(SUBJECT_CODE_PATTERN, code):
        errors["code"] = [
            "学科编号需为 2-32 位，以字母或数字开头，可包含大写字母、数字、下划线和短横线。"
        ]

    queryset = Subject.objects.filter(school=request.user.school)
    if subject is not None:
        queryset = queryset.exclude(pk=subject.pk)
    if name and queryset.filter(name=name).exists():
        errors["name"] = ["本校已存在同名学科。"]
    if code and queryset.filter(code=code).exists():
        errors["code"] = ["本校已存在相同学科编号。"]

    if errors:
        raise ServiceError("学科信息校验失败。", errors=errors, status=400)

    is_create = subject is None
    if subject is None:
        subject = Subject(school=request.user.school, created_by=request.user)
    subject.name = name
    subject.code = code
    subject.is_active = is_active
    subject.save()
    write_audit(
        request,
        "subject.create" if is_create else "subject.update",
        school=request.user.school,
        target_type="subject",
        target_id=subject.id,
        detail={
            "name": subject.name,
            "code": subject.code,
            "is_active": subject.is_active,
        },
    )
    return subject


def delete_subject(request, subject: Subject) -> None:
    if subject.is_active:
        raise ServiceError("请先停用学科，再执行删除。", status=400)
    blockers = []
    if subject.courses.exists():
        blockers.append("课程")
    if subject.pretest_papers.exists():
        blockers.append("前测套卷")
    if subject.pretest_submissions.exists():
        blockers.append("前测作答")
    if blockers:
        raise ServiceError(
            f"该学科已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。",
            status=400,
        )
    detail = {"name": subject.name, "code": subject.code}
    target_id = subject.id
    subject.delete()
    write_audit(
        request,
        "subject.delete",
        school=request.user.school,
        target_type="subject",
        target_id=target_id,
        detail=detail,
    )




















def _teacher_class_ids_for_user(user) -> set[int]:
    return set(
        TeachingAssignment.objects.filter(school=user.school, teacher=user)
        .values_list("class_group_id", flat=True)
        .distinct()
    )


def _teacher_notice_class_groups(
    request, raw_class_ids, errors: dict
) -> list[ClassGroup]:
    if not isinstance(raw_class_ids, list):
        errors["target_classes"] = ["请选择公告接收班级。"]
        return []

    teacher_class_ids = _teacher_class_ids_for_user(request.user)
    class_ids: list[int] = []
    for raw_id in raw_class_ids:
        try:
            class_id = int(raw_id)
        except (TypeError, ValueError):
            errors["target_classes"] = ["班级编号不正确。"]
            continue
        if class_id not in class_ids:
            class_ids.append(class_id)

    if not class_ids:
        errors["target_classes"] = ["请选择公告接收班级。"]
        return []

    unauthorized = [
        str(class_id) for class_id in class_ids if class_id not in teacher_class_ids
    ]
    if unauthorized:
        errors["target_classes"] = ["只能选择本人任教班级。"]
        return []

    classes = list(
        ClassGroup.objects.filter(
            school=request.user.school, id__in=class_ids
        ).order_by("grade", "name")
    )
    if len(classes) != len(class_ids):
        errors["target_classes"] = ["部分班级不存在或不属于本校。"]
    return classes


@transaction.atomic
def save_teacher_notice(request, data, *, notice: Notice | None = None) -> Notice:
    errors: dict[str, list[str]] = {}
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    status = str(data.get("status", Notice.Status.DRAFT)).strip() or Notice.Status.DRAFT
    is_pinned = _clean_bool(data.get("is_pinned", False))
    target_classes = _teacher_notice_class_groups(
        request, data.get("target_classes"), errors
    )

    if not _fullmatch(
        r"^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]{2,128}$", title
    ):
        errors["title"] = ["标题需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if len(content) < 2 or len(content) > 5000:
        errors["content"] = ["内容需为 2-5000 个字符。"]
    if status not in {item.value for item in Notice.Status}:
        errors["status"] = ["状态只能为草稿、已发布或归档。"]

    if errors:
        raise ServiceError("公告信息校验失败。", errors=errors, status=400)

    is_create = notice is None
    if notice is None:
        notice = Notice(school=request.user.school, teacher=request.user)
    notice.title = title
    notice.content = content
    notice.status = status
    notice.is_pinned = is_pinned
    if status == Notice.Status.PUBLISHED and notice.published_at is None:
        notice.published_at = timezone.now()
    if status == Notice.Status.ARCHIVED and notice.archived_at is None:
        notice.archived_at = timezone.now()
    notice.save()
    notice.target_classes.set(target_classes)
    write_audit(
        request,
        "notice.create" if is_create else "notice.update",
        school=request.user.school,
        target_type="notice",
        target_id=notice.id,
        detail={
            "title": notice.title,
            "status": notice.status,
            "class_count": len(target_classes),
        },
    )
    return notice


def publish_teacher_notice(request, notice: Notice) -> Notice:
    if not notice.target_classes.exists():
        raise ServiceError("公告至少需要选择 1 个接收班级后才能发布。", status=400)
    notice.status = Notice.Status.PUBLISHED
    notice.published_at = timezone.now()
    notice.archived_at = None
    notice.save(update_fields=["status", "published_at", "archived_at", "updated_at"])
    write_audit(
        request,
        "notice.publish",
        school=request.user.school,
        target_type="notice",
        target_id=notice.id,
        detail={"title": notice.title},
    )
    return notice


def archive_teacher_notice(request, notice: Notice) -> Notice:
    notice.status = Notice.Status.ARCHIVED
    notice.archived_at = timezone.now()
    notice.save(update_fields=["status", "archived_at", "updated_at"])
    write_audit(
        request,
        "notice.archive",
        school=request.user.school,
        target_type="notice",
        target_id=notice.id,
        detail={"title": notice.title},
    )
    return notice


def delete_teacher_notice(request, notice: Notice) -> None:
    if notice.status == Notice.Status.PUBLISHED:
        raise ServiceError("已发布公告不能直接删除，请先归档。", status=400)
    target_id = notice.id
    detail = {"title": notice.title, "status": notice.status}
    notice.delete()
    write_audit(
        request,
        "notice.delete",
        school=request.user.school,
        target_type="notice",
        target_id=target_id,
        detail=detail,
    )






def _teacher_classroom_session(request, session_id) -> ClassroomSession:
    try:
        session = (
            ClassroomSession.objects.select_related(
                "school",
                "teacher",
                "course",
                "course__subject",
                "lesson",
                "class_group",
                "current_step",
                "current_step__lesson",
                "evaluation_config_version",
                "evaluation_standard_use__standard_version",
            )
            .filter(
                pk=int(session_id), school=request.user.school, teacher=request.user
            )
            .first()
        )
    except (TypeError, ValueError):
        session = None
    if session is None:
        raise ServiceError("课堂不存在或无权操作。", status=404)
    return session


def _teacher_classroom_activity(request, activity_id) -> ClassroomActivity:
    try:
        activity = (
            ClassroomActivity.objects.select_related(
                "session",
                "session__school",
                "session__teacher",
                "session__course",
                "session__course__subject",
                "session__lesson",
                "session__class_group",
            )
            .filter(
                pk=int(activity_id),
                session__school=request.user.school,
                session__teacher=request.user,
            )
            .first()
        )
    except (TypeError, ValueError):
        activity = None
    if activity is None:
        raise ServiceError("课堂活动不存在或无权操作。", status=404)
    return activity




def _teacher_class_groups(
    request,
    raw_class_ids,
    errors: dict,
    *,
    field: str = "class_groups",
    allow_empty: bool = False,
) -> list[ClassGroup]:
    if not isinstance(raw_class_ids, list):
        if allow_empty and raw_class_ids in {None, ""}:
            return []
        errors[field] = ["请选择任教班级。"]
        return []

    teacher_class_ids = _teacher_class_ids_for_user(request.user)
    class_ids: list[int] = []
    for raw_id in raw_class_ids:
        try:
            class_id = int(raw_id)
        except (TypeError, ValueError):
            errors[field] = ["班级编号不正确。"]
            continue
        if class_id not in class_ids:
            class_ids.append(class_id)

    if not class_ids:
        if not allow_empty:
            errors[field] = ["请选择任教班级。"]
        return []

    unauthorized = [
        str(class_id) for class_id in class_ids if class_id not in teacher_class_ids
    ]
    if unauthorized:
        errors[field] = ["只能选择本人任教班级。"]
        return []

    classes = list(
        ClassGroup.objects.filter(
            school=request.user.school, id__in=class_ids
        ).order_by("grade", "name")
    )
    if len(classes) != len(class_ids):
        errors[field] = ["部分班级不存在或不属于本校。"]
        return []
    inactive = [
        class_group.name
        for class_group in classes
        if class_group.status != ClassGroup.Status.ACTIVE
    ]
    if inactive:
        errors[field] = [f"只能选择启用班级：{', '.join(inactive[:10])}。"]
        return []
    return classes






def _validate_course_cover(uploaded_file) -> None:
    if uploaded_file is None:
        raise ServiceError(
            "请选择课程封面图片。",
            errors={"cover": ["请选择课程封面图片。"]},
            status=400,
        )
    if uploaded_file.size > COURSE_COVER_MAX_SIZE:
        raise ServiceError(
            "课程封面不能超过 5MB。",
            errors={"cover": ["课程封面不能超过 5MB。"]},
            status=400,
        )

    suffix = Path(uploaded_file.name or "").suffix.lower()
    content_type = getattr(uploaded_file, "content_type", "")
    if (
        suffix not in COURSE_COVER_EXTENSIONS
        or content_type not in COURSE_COVER_CONTENT_TYPES
    ):
        raise ServiceError(
            "课程封面仅支持 JPG、PNG、WEBP 图片。",
            errors={"cover": ["课程封面仅支持 JPG、PNG、WEBP 图片。"]},
            status=400,
        )

    try:
        image = Image.open(uploaded_file)
        width, height = image.size
        image.verify()
    except (UnidentifiedImageError, OSError):
        raise ServiceError(
            "课程封面图片无法识别。",
            errors={"cover": ["课程封面图片无法识别。"]},
            status=400,
        )
    finally:
        uploaded_file.seek(0)

    if width < 320 or height < 160:
        raise ServiceError(
            "课程封面尺寸不能小于 320x160。",
            errors={"cover": ["课程封面尺寸不能小于 320x160。"]},
            status=400,
        )
    if width * height > 64_000_000:
        raise ServiceError(
            "课程封面图片尺寸过大。",
            errors={"cover": ["课程封面图片尺寸过大。"]},
            status=400,
        )














def _teacher_resource(request, resource_id) -> Resource:
    try:
        resource = Resource.objects.filter(
            pk=int(resource_id), owner=request.user, owner__school=request.user.school
        ).first()
    except (TypeError, ValueError):
        resource = None
    if resource is None:
        raise ServiceError("资源不存在或无权操作。", status=404)
    return resource








































































def reply_teacher_feedback(request, feedback: Feedback, data) -> Feedback:
    reply_content = str(data.get("reply_content", "")).strip()
    if len(reply_content) < 2 or len(reply_content) > 3000:
        raise ServiceError(
            "回复内容需为 2-3000 个字符。",
            errors={"reply_content": ["回复内容需为 2-3000 个字符。"]},
            status=400,
        )
    feedback.reply_content = reply_content
    feedback.status = Feedback.Status.REPLIED
    feedback.replied_at = timezone.now()
    feedback.save(update_fields=["reply_content", "status", "replied_at", "updated_at"])
    write_audit(
        request,
        "feedback.reply",
        school=request.user.school,
        target_type="feedback",
        target_id=feedback.id,
        detail={"title": feedback.title, "student": feedback.student.username},
    )
    return feedback


def close_teacher_feedback(request, feedback: Feedback) -> Feedback:
    feedback.status = Feedback.Status.CLOSED
    feedback.closed_at = timezone.now()
    feedback.save(update_fields=["status", "closed_at", "updated_at"])
    write_audit(
        request,
        "feedback.close",
        school=request.user.school,
        target_type="feedback",
        target_id=feedback.id,
        detail={"title": feedback.title, "student": feedback.student.username},
    )
    return feedback


# Compatibility re-exports. New code should import from the domain modules.
from .course_services import (
    _clean_lesson_file_config,
    _clean_lesson_question_items,
    _clean_resource_items,
    _clean_string_items,
    _has_executable_interactive_block,
    _learning_page_generation_mode,
    _learning_page_identifier,
    _learning_page_text,
    _resource_binding,
    _status_to_active,
    _teacher_subject,
    archive_teacher_course,
    archive_teacher_lesson,
    clean_learning_web_page_schema,
    delete_lesson_step,
    delete_teacher_course,
    delete_teacher_course_cover,
    delete_teacher_lesson,
    generate_learning_web_page_schema,
    publish_teacher_course,
    publish_teacher_lesson,
    reorder_lesson_steps,
    save_lesson_step,
    save_teacher_course,
    save_teacher_course_cover,
    save_teacher_lesson,
    set_teacher_course_classes,
)
from .classroom_services import (
    _classroom_session_step,
    _clean_ai_generated_evaluation_criteria,
    _command_random_pick_payload,
    _latest_open_activity,
    _teacher_course,
    _teacher_lesson,
    _write_classroom_event,
    close_classroom_activity,
    close_classroom_current_step,
    delete_classroom_activity,
    delete_classroom_session,
    finish_classroom_session,
    generate_classroom_evaluation_criteria_with_ai,
    lock_classroom_current_step,
    open_classroom_activity,
    restart_classroom_session,
    run_classroom_command,
    save_classroom_activity,
    save_classroom_session,
    set_classroom_current_step,
    start_classroom_session,
)
from .pretest_services import (
    _clean_ai_generated_questions,
    _clean_answer,
    _clean_options,
    _clean_question_bank_ai_drafts,
    _initial_layer_scores,
    _school_subject,
    archive_pretest_paper,
    delete_pretest_paper,
    delete_pretest_question,
    generate_lesson_step_questions_with_ai,
    generate_question_bank_drafts_with_ai,
    publish_pretest_paper,
    save_pretest_paper,
    save_pretest_question,
)
from .resource_services import (
    _clean_resource_class_ids,
    _clean_resource_text_list,
    _resource_list_value,
    _validate_resource_file,
    delete_teacher_resource,
    save_teacher_resource,
)
from .student_services import (
    _layer_value,
    _school_class_by_name,
    _student_brief,
    _student_payload_errors,
    _validate_student_import,
    bulk_delete_students,
    bulk_disable_students,
    create_student,
    delete_student,
    import_students_from_xlsx,
    reset_student_password,
    set_student_active,
    update_student,
)
