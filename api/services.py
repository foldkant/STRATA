from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Max
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from aiops.crypto import decrypt_secret, encrypt_secret
from aiops.models import TeacherAIProvider
from courses.models import (
    ClassroomActivity,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
    Subject,
)
from learning.models import Feedback, LearningEvent, Notice, PretestPaper, PretestQuestion
from ops.forms import PASSWORD_PATTERN, _matches
from ops.forms import PERSON_NAME_PATTERN, PHONE_PATTERN, SchoolAdminCreateForm, SchoolAdminUpdateForm, SchoolForm
from ops.models import AuditLog
from ops.xlsx import normalize_text, read_table_rows
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment
from school_admin.forms import TeacherCreateForm, TeacherUpdateForm
from ops.forms import TEACHING_PASSWORD_PATTERN
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
    ".mp4",
    ".webm",
    ".mov",
    ".mp3",
    ".wav",
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
    ".zip",
    ".rar",
    ".7z",
}
LESSON_QUESTION_TYPES = {"single", "multiple", "judge", "blank", "text"}
TEACHER_IMPORT_HEADERS = ["登录账号", "姓名", "联系电话", "初始密码", "状态"]
STUDENT_IMPORT_HEADERS = ["登录账号", "姓名", "学号", "班级", "联系电话", "初始密码", "层级", "小组号", "积分", "状态"]
DEFAULT_AI_BASE_URL = "https://api.deepseek.com"
DEFAULT_AI_MODEL = "deepseek-v4-flash"
AI_MODEL_PATTERN = r"^[A-Za-z0-9._:\-]{2,64}$"
AI_KEY_PATTERN = r"^\S{10,512}$"


def _fullmatch(pattern: str, value: str) -> bool:
    return bool(re.fullmatch(pattern, value))


class ServiceError(Exception):
    def __init__(self, message: str, *, errors: dict | None = None, status: int = 400) -> None:
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


def write_audit(request, action: str, *, school=None, target_type: str = "", target_id: str | int = "", detail=None) -> None:
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
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.query and not parsed.fragment


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
    provider_name = str(data.get("provider", TeacherAIProvider.Provider.DEEPSEEK)).strip() or TeacherAIProvider.Provider.DEEPSEEK
    base_url = str(data.get("base_url", provider.base_url or DEFAULT_AI_BASE_URL)).strip().rstrip("/") or DEFAULT_AI_BASE_URL
    model = str(data.get("model", provider.model or DEFAULT_AI_MODEL)).strip() or DEFAULT_AI_MODEL
    api_key = str(data.get("api_key", "")).strip()
    clear_api_key = _clean_bool(data.get("clear_api_key", False))
    is_enabled = _clean_bool(data.get("is_enabled", provider.is_enabled))

    if provider_name != TeacherAIProvider.Provider.DEEPSEEK:
        errors["provider"] = ["当前第一版只支持 DeepSeek。"]
    if not _valid_base_url(base_url):
        errors["base_url"] = ["接口地址必须是有效的 http 或 https 地址，不能包含查询参数。"]
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
        raise ServiceError(provider.last_error, errors={"api_key": [provider.last_error]}, status=400)
    if not _valid_base_url(provider.base_url):
        provider.last_error = "接口地址格式不正确。"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError(provider.last_error, errors={"base_url": [provider.last_error]}, status=400)

    endpoint = f"{provider.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": "你是 STRATA 数智教学系统的连接测试助手。"},
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
        provider.last_error = f"DeepSeek 返回 {exc.code}，请检查 Key、模型或接口地址。{detail[:160]}"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError("AI 接入测试失败。", errors={"connection": [provider.last_error]}, status=400)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        provider.last_error = f"连接失败：{exc}"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError("AI 接入测试失败。", errors={"connection": [provider.last_error]}, status=400)

    if not payload.get("choices"):
        provider.last_error = "接口已响应，但没有返回有效内容。"
        provider.save(update_fields=["last_error", "updated_at"])
        raise ServiceError("AI 接入测试失败。", errors={"connection": [provider.last_error]}, status=400)

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


def _clean_id_list(data) -> list[int]:
    raw_ids = data.get("ids") if hasattr(data, "get") else None
    if not isinstance(raw_ids, list):
        raise ServiceError("请选择要操作的数据。", errors={"ids": ["请选择要操作的数据。"]}, status=400)

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
        raise ServiceError("所选数据包含无效编号。", errors={"ids": ["所选数据包含无效编号。"]}, status=400)
    if not ids:
        raise ServiceError("请选择要操作的数据。", errors={"ids": ["请选择要操作的数据。"]}, status=400)
    if len(ids) > BULK_LIMIT:
        raise ServiceError(f"单次最多处理 {BULK_LIMIT} 条数据。", errors={"ids": [f"单次最多处理 {BULK_LIMIT} 条数据。"]}, status=400)
    return ids


def _ensure_all_selected(found_ids: set[int], requested_ids: list[int], label: str) -> None:
    missing = [str(item_id) for item_id in requested_ids if item_id not in found_ids]
    if missing:
        raise ServiceError(f"部分{label}不存在或无权操作。", errors={"ids": [f"无权限或不存在：{', '.join(missing)}"]}, status=404)


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
        raise ServiceError(f"该学校已有{', '.join(blockers)}关联，不能物理删除；请保持停用或归档状态。", status=400)

    detail = {"code": school.code, "name": school.name}
    target_id = school.id
    school.delete()
    write_audit(request, "school.delete", target_type="school", target_id=target_id, detail=detail)


@transaction.atomic
def bulk_disable_schools(request, data) -> dict:
    ids = _clean_id_list(data)
    schools = list(School.objects.filter(id__in=ids).order_by("name", "code"))
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
    schools = list(School.objects.filter(id__in=ids).order_by("name", "code"))
    _ensure_all_selected({school.id for school in schools}, ids, "学校")

    active = [school for school in schools if school.status == School.Status.ACTIVE]
    if active:
        raise ServiceError(
            "所选学校包含启用状态，请先批量停用或归档后再删除。",
            errors={"ids": [f"未停用或归档：{', '.join(school.name for school in active)}"]},
            status=400,
        )

    deleted = 0
    blocked = []
    for school in schools:
        try:
            delete_school(request, school)
            deleted += 1
        except ServiceError as exc:
            blocked.append({"id": school.id, "name": school.name, "reason": exc.message})

    if blocked:
        message = f"已删除 {deleted} 个学校，{len(blocked)} 个学校已有业务数据，已保留当前状态。"
    else:
        message = f"已删除 {deleted} 个学校。"
    return {"requested_count": len(ids), "deleted_count": deleted, "blocked": blocked, "message": message}


def create_school_admin(request, data):
    form = SchoolAdminCreateForm(data)
    if not form.is_valid():
        raise ServiceError("学校管理员信息校验失败。", errors=form_errors(form), status=400)

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
        raise ServiceError("学校管理员信息校验失败。", errors=form_errors(form), status=400)

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
        existing_user = User.objects.filter(username=username).first() if username else None

        if not _fullmatch(USERNAME_PATTERN, username):
            errors.append(_row_error(row, "登录账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 teacher1。"))
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
            errors.append(_row_error(row, f"登录账号 {username} 不属于本校，不能更新。"))
        if not existing_user and not password:
            errors.append(_row_error(row, "新增教师必须填写初始密码。"))
        if password and not _matches(TEACHING_PASSWORD_PATTERN, password):
            errors.append(_row_error(row, "教师初始密码需为 6-32 位，可使用字母、数字和常用符号。"))

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
    rows = read_table_rows(uploaded_file, required_headers=["登录账号", "姓名"], all_headers=TEACHER_IMPORT_HEADERS)
    if not rows:
        raise ServiceError("Excel 文件没有可导入的数据行。", status=400)

    records, errors = _validate_teacher_import(request, rows)
    if errors:
        raise ServiceError("教师批量导入校验失败。", errors={"rows": errors[:100]}, status=400)

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
    return {"created_count": created_count, "updated_count": updated_count, "total_count": len(records)}


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


def _layer_value(value: str) -> str | None:
    text = normalize_text(value).upper()
    if not text:
        return None
    if text in {"A", "A层", "A 拓展挑战层", "拓展挑战层"}:
        return StudentProfile.Layer.A
    if text in {"B", "B层", "B 核心发展层", "核心发展层"}:
        return StudentProfile.Layer.B
    if text in {"C", "C层", "C 基础提升层", "基础提升层"}:
        return StudentProfile.Layer.C
    return "__invalid__"


def _row_error(row: dict, message: str) -> str:
    return f"第 {row.get('__row_number', '?')} 行：{message}"


def _clean_optional_int(value, field: str, errors: dict, *, min_value: int | None = None, max_value: int | None = None):
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


def save_class_group(request, data, *, class_group: ClassGroup | None = None) -> ClassGroup:
    errors: dict[str, list[str]] = {}
    is_create = class_group is None
    name = str(data.get("name", "")).strip()
    grade = str(data.get("grade", "")).strip()
    status = str(data.get("status", ClassGroup.Status.ACTIVE)).strip() or ClassGroup.Status.ACTIVE
    entry_year = _clean_optional_int(data.get("entry_year"), "entry_year", errors, min_value=1900, max_value=2100)

    if not _fullmatch(CLASS_NAME_PATTERN, name):
        errors["name"] = ["班级名称需为 1-64 位，可包含中文、字母、数字、空格、括号和短横线。"]
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
        detail={"name": class_group.name, "grade": class_group.grade, "status": class_group.status},
    )
    return class_group


@transaction.atomic
def bulk_create_class_groups(request, data) -> list[ClassGroup]:
    errors: dict[str, list[str]] = {}
    grade = str(data.get("grade", "")).strip()
    status = str(data.get("status", ClassGroup.Status.ACTIVE)).strip() or ClassGroup.Status.ACTIVE
    entry_year = _clean_optional_int(data.get("entry_year"), "entry_year", errors, min_value=1900, max_value=2100)
    class_count = _clean_optional_int(data.get("class_count"), "class_count", errors, min_value=1, max_value=80)
    start_no = _clean_optional_int(data.get("start_no"), "start_no", errors, min_value=1, max_value=999) or 1

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
        generated_names = [f"{grade}{number}班" for number in range(start_no, start_no + class_count)]
        invalid_names = [name for name in generated_names if not _fullmatch(CLASS_NAME_PATTERN, name)]
        if invalid_names:
            errors["grade"] = ["生成的班级名称格式不正确，请调整年级或起始序号。"]
        existing_names = set(
            ClassGroup.objects.filter(school=request.user.school, name__in=generated_names).values_list("name", flat=True)
        )
        if existing_names:
            errors["class_count"] = [f"以下班级已存在：{', '.join(sorted(existing_names))}。"]

    if errors:
        raise ServiceError("批量新增班级校验失败。", errors=errors, status=400)

    created = [
        ClassGroup(school=request.user.school, name=name, grade=grade, entry_year=entry_year, status=status)
        for name in generated_names
    ]
    ClassGroup.objects.bulk_create(created)
    saved = list(ClassGroup.objects.filter(school=request.user.school, name__in=generated_names).order_by("name"))
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

    classes = list(ClassGroup.objects.filter(school=request.user.school, grade=from_grade).order_by("name"))
    if from_grade and not classes:
        errors["from_grade"] = ["没有找到该年级的班级。"]

    rename_pairs: list[tuple[ClassGroup, str]] = []
    for class_group in classes:
        if class_group.name.startswith(from_grade):
            new_name = f"{to_grade}{class_group.name[len(from_grade):]}"
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
        errors["to_grade"] = [f"以下目标班级已存在：{', '.join(sorted(existing_names))}。"]

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
        detail={"from_grade": from_grade, "to_grade": to_grade, "count": len(rename_pairs), "names": target_names},
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
        raise ServiceError(f"该班级已有{', '.join(blockers)}关联，不能物理删除；请保持停用或归档状态。", status=400)

    detail = {"name": class_group.name, "grade": class_group.grade, "school": request.user.school.name}
    target_id = class_group.id
    class_group.delete()
    write_audit(request, "class.delete", school=request.user.school, target_type="class_group", target_id=target_id, detail=detail)


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


def _student_brief(profile: StudentProfile, reason: str = "") -> dict:
    return {
        "id": profile.id,
        "username": profile.user.username,
        "display_name": profile.user.display_name,
        "student_no": profile.student_no,
        "reason": reason,
    }


@transaction.atomic
def bulk_disable_teacher_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    teachers = User.objects.filter(id__in=ids, school=request.user.school, role="teacher").order_by("username")
    return bulk_disable_accounts(request, teachers, ids, label="教师", action_prefix="teacher", school=request.user.school)


def bulk_delete_teacher_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    teachers = User.objects.filter(id__in=ids, school=request.user.school, role="teacher").order_by("username")
    return bulk_delete_accounts(request, teachers, ids, label="教师", action_prefix="teacher")


@transaction.atomic
def bulk_disable_students(request, data) -> dict:
    ids = _clean_id_list(data)
    profiles = list(
        StudentProfile.objects.filter(id__in=ids, user__school=request.user.school)
        .select_related("user", "class_group")
        .order_by("user__username")
    )
    _ensure_all_selected({profile.id for profile in profiles}, ids, "学生")

    updated = 0
    for profile in profiles:
        if profile.user.is_active:
            set_student_active(request, profile, False)
            updated += 1

    write_audit(
        request,
        "student.bulk_disable",
        school=request.user.school,
        target_type="student_profile",
        detail={"ids": ids, "updated": updated},
    )
    return {"requested_count": len(ids), "updated_count": updated}


def bulk_delete_students(request, data) -> dict:
    ids = _clean_id_list(data)
    profiles = list(
        StudentProfile.objects.filter(id__in=ids, user__school=request.user.school)
        .select_related("user", "class_group")
        .order_by("user__username")
    )
    _ensure_all_selected({profile.id for profile in profiles}, ids, "学生")

    active = [profile for profile in profiles if profile.user.is_active]
    if active:
        raise ServiceError(
            "所选学生包含启用账号，请先批量停用后再删除。",
            errors={"ids": [f"未停用：{', '.join(profile.user.username for profile in active)}"]},
            status=400,
        )

    deleted = 0
    blocked = []
    for profile in profiles:
        try:
            delete_student(request, profile)
            deleted += 1
        except ServiceError as exc:
            blocked.append(_student_brief(profile, exc.message))

    if blocked:
        message = f"已删除 {deleted} 个学生，{len(blocked)} 个学生已有业务数据，已保留停用状态。"
    else:
        message = f"已删除 {deleted} 个学生。"
    return {"requested_count": len(ids), "deleted_count": deleted, "blocked": blocked, "message": message}


@transaction.atomic
def bulk_disable_class_groups(request, data) -> dict:
    ids = _clean_id_list(data)
    classes = list(ClassGroup.objects.filter(id__in=ids, school=request.user.school).order_by("grade", "name"))
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
    classes = list(ClassGroup.objects.filter(id__in=ids, school=request.user.school).order_by("grade", "name"))
    _ensure_all_selected({class_group.id for class_group in classes}, ids, "班级")

    active = [class_group for class_group in classes if class_group.status == ClassGroup.Status.ACTIVE]
    if active:
        raise ServiceError(
            "所选班级包含启用状态，请先批量停用或归档后再删除。",
            errors={"ids": [f"未停用或归档：{', '.join(class_group.name for class_group in active)}"]},
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
    return {"requested_count": len(ids), "deleted_count": deleted, "blocked": blocked, "message": message}


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
    return {"graduated_count": len(classes), "disabled_students": disabled_students, "graduated_at": now}


def _school_teacher(request, teacher_id, errors):
    User = get_user_model()
    try:
        return User.objects.get(pk=teacher_id, school=request.user.school, role="teacher")
    except (User.DoesNotExist, TypeError, ValueError):
        errors["teacher"] = ["请选择本校教师。"]
        return None


def _school_class(request, class_group_id, errors):
    try:
        return ClassGroup.objects.get(pk=class_group_id, school=request.user.school)
    except (ClassGroup.DoesNotExist, TypeError, ValueError):
        errors["class_group"] = ["请选择本校班级。"]
        return None


def _teaching_assignment_payload(request, data, *, assignment: TeachingAssignment | None = None):
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

    classes = list(ClassGroup.objects.filter(school=request.user.school, id__in=cleaned_class_ids).order_by("grade", "name"))
    if len(classes) != len(cleaned_class_ids):
        errors["class_groups"] = ["部分班级不存在或不属于本校。"]

    if errors:
        raise ServiceError("批量任课关系校验失败。", errors=errors, status=400)

    old_class_groups = list(
        ClassGroup.objects.filter(teaching_assignments__school=request.user.school, teaching_assignments__teacher=teacher)
        .distinct()
        .order_by("grade", "name")
    )
    old_ids = {class_group.id for class_group in old_class_groups}
    new_ids = {class_group.id for class_group in classes}
    removed_class_groups = [class_group for class_group in old_class_groups if class_group.id not in new_ids]

    deleted_count, _ = TeachingAssignment.objects.filter(
        school=request.user.school,
        teacher=teacher,
    ).exclude(class_group_id__in=new_ids).delete()

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
def save_teaching_assignment(request, data, *, assignment: TeachingAssignment | None = None) -> TeachingAssignment:
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
        raise ServiceError("任课关系校验失败。", errors={"class_group": ["该教师已任教该班级。"]}, status=400)

    if old_class_group is not None and old_teacher is not None:
        _sync_teaching_teacher_link(request.user.school, old_class_group, old_teacher)
    _sync_teaching_teacher_link(request.user.school, assignment.class_group, assignment.teacher)

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


def _student_payload_errors(request, data, *, profile: StudentProfile | None = None, require_password: bool = False):
    errors: dict[str, list[str]] = {}
    username = str(data.get("username", "")).strip()
    display_name = str(data.get("display_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))
    student_no = str(data.get("student_no", "")).strip()
    current_layer = str(data.get("current_layer", "")).strip() or None
    class_group_id = data.get("class_group")
    current_group_no = _clean_optional_int(data.get("current_group_no"), "current_group_no", errors, min_value=1, max_value=999)
    score = _clean_float(data.get("score"), "score", errors, default=0)

    class_group = None
    if class_group_id not in {None, ""}:
        try:
            class_group = ClassGroup.objects.get(pk=class_group_id, school=request.user.school)
        except (ClassGroup.DoesNotExist, TypeError, ValueError):
            errors["class_group"] = ["请选择本校班级。"]

    if not _fullmatch(USERNAME_PATTERN, username):
        errors["username"] = ["账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 student1。"]
    if not _matches(PERSON_NAME_PATTERN, display_name):
        errors["display_name"] = ["姓名需为 2-24 位中文或字母。"]
    if phone and not _matches(PHONE_PATTERN, phone):
        errors["phone"] = ["联系电话格式不正确。"]
    if password and not _matches(TEACHING_PASSWORD_PATTERN, password):
        errors["password"] = ["学生密码需为 6-32 位，可使用字母、数字和常用符号。"]
    if require_password and not password:
        errors["password"] = ["新增学生必须填写初始密码。"]
    if student_no and not _fullmatch(STUDENT_NO_PATTERN, student_no):
        errors["student_no"] = ["学号只能包含字母、数字、下划线或短横线。"]
    if current_layer and current_layer not in {item.value for item in StudentProfile.Layer}:
        errors["current_layer"] = ["层级只能为 A、B 或 C。"]

    User = get_user_model()
    user_queryset = User.objects.filter(username=username)
    if profile is not None:
        user_queryset = user_queryset.exclude(pk=profile.user_id)
    if username and user_queryset.exists():
        errors["username"] = ["该登录账号已存在。"]

    if class_group and student_no:
        no_queryset = StudentProfile.objects.filter(class_group=class_group, student_no=student_no)
        if profile is not None:
            no_queryset = no_queryset.exclude(pk=profile.pk)
        if no_queryset.exists():
            errors["student_no"] = ["该班级已存在相同学号。"]

    return {
        "errors": errors,
        "class_group": class_group,
        "username": username,
        "display_name": display_name,
        "phone": phone,
        "password": password,
        "student_no": student_no,
        "current_layer": current_layer,
        "current_group_no": current_group_no,
        "score": score,
        "is_active": _clean_bool(data.get("is_active", True)),
    }


def _school_class_by_name(request, name: str, row: dict, errors: list[str]) -> ClassGroup | None:
    class_name = normalize_text(name)
    if not class_name:
        return None
    class_group = ClassGroup.objects.filter(school=request.user.school, name=class_name).first()
    if class_group is None:
        errors.append(_row_error(row, f"班级 {class_name} 不存在。"))
    return class_group


def _validate_student_import(request, rows: list[dict]) -> tuple[list[dict], list[str]]:
    User = get_user_model()
    errors = []
    records = []
    seen_usernames = set()
    seen_student_no = set()

    for row in rows:
        username = normalize_text(row.get("登录账号"))
        display_name = normalize_text(row.get("姓名"))
        student_no = normalize_text(row.get("学号"))
        class_group = _school_class_by_name(request, row.get("班级"), row, errors)
        phone = normalize_text(row.get("联系电话"))
        password = normalize_text(row.get("初始密码"))
        current_layer = _layer_value(row.get("层级"))
        active = _active_value(row.get("状态"), default=True)
        current_group_no = _clean_optional_int(row.get("小组号"), "current_group_no", {}, min_value=1, max_value=999)
        score_errors: dict[str, list[str]] = {}
        score = _clean_float(row.get("积分"), "score", score_errors, default=0)
        existing_user = User.objects.filter(username=username).first() if username else None
        existing_profile = None
        if existing_user and existing_user.role == "student":
            try:
                existing_profile = existing_user.student_profile
            except StudentProfile.DoesNotExist:
                existing_profile = None

        if not _fullmatch(USERNAME_PATTERN, username):
            errors.append(_row_error(row, "登录账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 student1。"))
        if username in seen_usernames:
            errors.append(_row_error(row, f"登录账号 {username} 在文件中重复。"))
        seen_usernames.add(username)
        if not _matches(PERSON_NAME_PATTERN, display_name):
            errors.append(_row_error(row, "姓名需为 2-24 位中文或字母。"))
        if student_no and not _fullmatch(STUDENT_NO_PATTERN, student_no):
            errors.append(_row_error(row, "学号只能包含字母、数字、下划线或短横线。"))
        if class_group and student_no:
            key = (class_group.id, student_no)
            if key in seen_student_no:
                errors.append(_row_error(row, f"文件中同一班级重复学号 {student_no}。"))
            seen_student_no.add(key)
            no_queryset = StudentProfile.objects.filter(class_group=class_group, student_no=student_no)
            if existing_profile is not None:
                no_queryset = no_queryset.exclude(pk=existing_profile.pk)
            if no_queryset.exists():
                errors.append(_row_error(row, f"班级 {class_group.name} 已存在学号 {student_no}。"))
        if phone and not _matches(PHONE_PATTERN, phone):
            errors.append(_row_error(row, "联系电话格式不正确。"))
        if current_layer == "__invalid__":
            errors.append(_row_error(row, "层级只能填写 A、B、C 或留空。"))
            current_layer = None
        if active is None:
            errors.append(_row_error(row, "状态只能填写启用或停用。"))
        if current_group_no is None and normalize_text(row.get("小组号")):
            errors.append(_row_error(row, "小组号需为 1-999 的整数。"))
        if score_errors:
            errors.append(_row_error(row, "积分需为数字。"))
        if existing_user and existing_user.role != "student":
            errors.append(_row_error(row, f"登录账号 {username} 已被其他角色占用。"))
        if existing_user and existing_user.school_id != request.user.school_id:
            errors.append(_row_error(row, f"登录账号 {username} 不属于本校，不能更新。"))
        if existing_user and existing_user.role == "student" and existing_profile is None:
            errors.append(_row_error(row, f"学生账号 {username} 缺少学生档案，请联系技术人员处理。"))
        if not existing_user and not password:
            errors.append(_row_error(row, "新增学生必须填写初始密码。"))
        if password and not _matches(TEACHING_PASSWORD_PATTERN, password):
            errors.append(_row_error(row, "学生初始密码需为 6-32 位，可使用字母、数字和常用符号。"))

        records.append(
            {
                "username": username,
                "display_name": display_name,
                "student_no": student_no,
                "class_group": class_group,
                "phone": phone,
                "password": password,
                "current_layer": current_layer,
                "current_group_no": current_group_no,
                "score": score,
                "is_active": active if active is not None else True,
                "existing_user": existing_user,
                "existing_profile": existing_profile,
            }
        )

    return records, errors


@transaction.atomic
def import_students_from_xlsx(request, uploaded_file) -> dict:
    rows = read_table_rows(uploaded_file, required_headers=["登录账号", "姓名"], all_headers=STUDENT_IMPORT_HEADERS)
    if not rows:
        raise ServiceError("Excel 文件没有可导入的数据行。", status=400)

    records, errors = _validate_student_import(request, rows)
    if errors:
        raise ServiceError("学生批量导入校验失败。", errors={"rows": errors[:100]}, status=400)

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
            profile = record["existing_profile"]
            profile.class_group = record["class_group"]
            profile.student_no = record["student_no"]
            profile.current_layer = record["current_layer"]
            profile.current_group_no = record["current_group_no"]
            profile.score = record["score"]
            profile.save()
            updated_count += 1
        else:
            user = User.objects.create_user(
                username=record["username"],
                password=record["password"],
                display_name=record["display_name"],
                phone=record["phone"],
                role="student",
                school=request.user.school,
                is_active=record["is_active"],
                is_staff=False,
                is_first_login=True,
            )
            StudentProfile.objects.create(
                user=user,
                class_group=record["class_group"],
                student_no=record["student_no"],
                current_layer=record["current_layer"],
                current_group_no=record["current_group_no"],
                score=record["score"],
                is_first_use=True,
                onboarding_status=StudentProfile.OnboardingStatus.NEW,
            )
            created_count += 1

    write_audit(
        request,
        "student.bulk_import",
        school=request.user.school,
        target_type="student_profile",
        detail={"created": created_count, "updated": updated_count},
    )
    return {"created_count": created_count, "updated_count": updated_count, "total_count": len(records)}


@transaction.atomic
def create_student(request, data) -> StudentProfile:
    cleaned = _student_payload_errors(request, data, require_password=True)
    if cleaned["errors"]:
        raise ServiceError("学生信息校验失败。", errors=cleaned["errors"], status=400)

    User = get_user_model()
    user = User.objects.create_user(
        username=cleaned["username"],
        password=cleaned["password"],
        display_name=cleaned["display_name"],
        phone=cleaned["phone"],
        role="student",
        school=request.user.school,
        is_active=cleaned["is_active"],
        is_staff=False,
        is_first_login=True,
    )
    profile = StudentProfile.objects.create(
        user=user,
        class_group=cleaned["class_group"],
        student_no=cleaned["student_no"],
        current_layer=cleaned["current_layer"],
        current_group_no=cleaned["current_group_no"],
        score=cleaned["score"],
        is_first_use=True,
        onboarding_status=StudentProfile.OnboardingStatus.NEW,
    )
    write_audit(
        request,
        "student.create",
        school=request.user.school,
        target_type="student_profile",
        target_id=profile.id,
        detail={"username": user.username, "student_no": profile.student_no},
    )
    return profile


@transaction.atomic
def update_student(request, profile: StudentProfile, data) -> StudentProfile:
    cleaned = _student_payload_errors(request, data, profile=profile)
    if cleaned["errors"]:
        raise ServiceError("学生信息校验失败。", errors=cleaned["errors"], status=400)

    user = profile.user
    user.username = cleaned["username"]
    user.display_name = cleaned["display_name"]
    user.phone = cleaned["phone"]
    user.is_active = cleaned["is_active"]
    user.save()

    profile.class_group = cleaned["class_group"]
    profile.student_no = cleaned["student_no"]
    profile.current_layer = cleaned["current_layer"]
    profile.current_group_no = cleaned["current_group_no"]
    profile.score = cleaned["score"]
    try:
        profile.save()
    except IntegrityError:
        raise ServiceError("学生信息校验失败。", errors={"student_no": ["该班级已存在相同学号。"]}, status=400)
    write_audit(
        request,
        "student.update",
        school=request.user.school,
        target_type="student_profile",
        target_id=profile.id,
        detail={"username": user.username, "student_no": profile.student_no},
    )
    return profile


def set_student_active(request, profile: StudentProfile, is_active: bool) -> None:
    set_account_active(request, profile.user, is_active, action_prefix="student")


def reset_student_password(request, profile: StudentProfile, password: str) -> None:
    if not _matches(TEACHING_PASSWORD_PATTERN, password):
        raise ServiceError(
            "学生密码需为 6-32 位，可使用字母、数字和常用符号。",
            errors={"password": ["学生密码需为 6-32 位，可使用字母、数字和常用符号。"]},
        )
    profile.user.set_password(password)
    profile.user.is_first_login = True
    profile.user.save(update_fields=["password", "is_first_login"])
    write_audit(
        request,
        "student.reset_password",
        school=request.user.school,
        target_type="student_profile",
        target_id=profile.id,
        detail={"username": profile.user.username},
    )


@transaction.atomic
def delete_student(request, profile: StudentProfile) -> None:
    user = profile.user
    if user.is_active:
        raise ServiceError("该账号仍处于启用状态。请先停用账号，再执行删除。", status=400)

    blockers = []
    if user.learning_events.exists():
        blockers.append("学习行为")
    if user.feature_snapshots.exists():
        blockers.append("特征快照")
    if user.layer_decisions.exists():
        blockers.append("分层记录")
    if user.reviewed_layer_decisions.exists():
        blockers.append("分层审核")
    if blockers:
        raise ServiceError(f"该学生已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。", status=400)

    detail = {
        "username": user.username,
        "display_name": user.display_name,
        "student_no": profile.student_no,
        "class_group": profile.class_group.name if profile.class_group_id else "",
    }
    target_id = profile.id
    profile.delete()
    user.delete()
    write_audit(request, "student.delete", school=request.user.school, target_type="student_profile", target_id=target_id, detail=detail)


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
def bulk_disable_accounts(request, users, ids: list[int], *, label: str, action_prefix: str, school=None) -> dict:
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


def bulk_delete_accounts(request, users, ids: list[int], *, label: str, action_prefix: str) -> dict:
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
    return {"requested_count": len(ids), "deleted_count": deleted, "blocked": blocked, "message": message}


def bulk_disable_school_admin_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    users = User.objects.filter(id__in=ids, role="school_admin").select_related("school").order_by("school__name", "username")
    return bulk_disable_accounts(request, users, ids, label="学校管理员", action_prefix="school_admin")


def bulk_delete_school_admin_accounts(request, data) -> dict:
    ids = _clean_id_list(data)
    User = get_user_model()
    users = User.objects.filter(id__in=ids, role="school_admin").select_related("school").order_by("school__name", "username")
    return bulk_delete_accounts(request, users, ids, label="学校管理员", action_prefix="school_admin")


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
        raise ServiceError("该账号仍处于启用状态。请先停用账号，再执行删除。", status=400)
    blockers = _account_delete_blockers(user)
    if blockers:
        raise ServiceError(f"该账号已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。", status=400)

    detail = {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "school": user.school.name if user.school else "",
    }
    school = user.school
    target_id = user.id
    user.delete()
    write_audit(request, f"{action_prefix}.delete", school=school, target_type="user", target_id=target_id, detail=detail)


def reset_school_admin_password(request, user, password: str) -> None:
    if not _matches(PASSWORD_PATTERN, password):
        raise ServiceError("密码需为 8-32 位，并至少包含字母和数字。", errors={"password": ["密码需为 8-32 位，并至少包含字母和数字。"]})
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
        errors["code"] = ["学科编号需为 2-32 位，以字母或数字开头，可包含大写字母、数字、下划线和短横线。"]

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
        detail={"name": subject.name, "code": subject.code, "is_active": subject.is_active},
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
        raise ServiceError(f"该学科已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。", status=400)
    detail = {"name": subject.name, "code": subject.code}
    target_id = subject.id
    subject.delete()
    write_audit(request, "subject.delete", school=request.user.school, target_type="subject", target_id=target_id, detail=detail)


def _school_subject(request, subject_id, errors: dict) -> Subject | None:
    try:
        return Subject.objects.get(pk=subject_id, school=request.user.school)
    except (Subject.DoesNotExist, TypeError, ValueError):
        errors["subject"] = ["请选择本校学科。"]
        return None


def save_pretest_paper(request, data, *, paper: PretestPaper | None = None) -> PretestPaper:
    errors: dict[str, list[str]] = {}
    subject = _school_subject(request, data.get("subject"), errors)
    title = str(data.get("title", "")).strip()
    kind = str(data.get("kind", "")).strip()
    status = str(data.get("status", PretestPaper.Status.DRAFT)).strip() or PretestPaper.Status.DRAFT
    introduction = str(data.get("introduction", "")).strip()
    version = _clean_optional_int(data.get("version"), "version", errors, min_value=1, max_value=999)

    if not _fullmatch(r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{2,128}$", title):
        errors["title"] = ["套卷名称需为 2-128 位，可包含中文、字母和数字。"]
    if kind not in {item.value for item in PretestPaper.Kind}:
        errors["kind"] = ["前测类型只能为素养测试或学习态度问卷。"]
    if status not in {item.value for item in PretestPaper.Status}:
        errors["status"] = ["状态只能为草稿、已发布或归档。"]

    if subject and kind and version is None:
        max_version = (
            PretestPaper.objects.filter(school=request.user.school, subject=subject, kind=kind)
            .aggregate(value=Max("version"))
            .get("value")
            or 0
        )
        version = max_version + 1

    if subject and kind and version:
        queryset = PretestPaper.objects.filter(school=request.user.school, subject=subject, kind=kind, version=version)
        if paper is not None:
            queryset = queryset.exclude(pk=paper.pk)
        if queryset.exists():
            errors["version"] = ["该学科和前测类型下已存在相同版本号。"]

    if errors:
        raise ServiceError("前测套卷信息校验失败。", errors=errors, status=400)

    is_create = paper is None
    if paper is None:
        paper = PretestPaper(school=request.user.school, created_by=request.user)
    paper.subject = subject
    paper.title = title
    paper.kind = kind
    paper.version = version or 1
    paper.introduction = introduction
    paper.status = status
    if status == PretestPaper.Status.PUBLISHED and paper.published_at is None:
        paper.published_at = timezone.now()
    paper.save()

    if paper.status == PretestPaper.Status.PUBLISHED:
        PretestPaper.objects.filter(
            school=request.user.school,
            subject=paper.subject,
            kind=paper.kind,
            status=PretestPaper.Status.PUBLISHED,
        ).exclude(pk=paper.pk).update(status=PretestPaper.Status.ARCHIVED)

    write_audit(
        request,
        "pretest_paper.create" if is_create else "pretest_paper.update",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=paper.id,
        detail={"title": paper.title, "subject": paper.subject.code, "kind": paper.kind, "status": paper.status},
    )
    return paper


def publish_pretest_paper(request, paper: PretestPaper) -> PretestPaper:
    if not paper.questions.exists():
        raise ServiceError("套卷至少需要 1 道题目后才能发布。", status=400)
    paper.status = PretestPaper.Status.PUBLISHED
    paper.published_at = timezone.now()
    paper.save(update_fields=["status", "published_at", "updated_at"])
    PretestPaper.objects.filter(
        school=paper.school,
        subject=paper.subject,
        kind=paper.kind,
        status=PretestPaper.Status.PUBLISHED,
    ).exclude(pk=paper.pk).update(status=PretestPaper.Status.ARCHIVED)
    write_audit(
        request,
        "pretest_paper.publish",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=paper.id,
        detail={"title": paper.title, "subject": paper.subject.code, "kind": paper.kind},
    )
    return paper


def archive_pretest_paper(request, paper: PretestPaper) -> PretestPaper:
    paper.status = PretestPaper.Status.ARCHIVED
    paper.save(update_fields=["status", "updated_at"])
    write_audit(
        request,
        "pretest_paper.archive",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=paper.id,
        detail={"title": paper.title, "subject": paper.subject.code, "kind": paper.kind},
    )
    return paper


def delete_pretest_paper(request, paper: PretestPaper) -> None:
    if paper.status == PretestPaper.Status.PUBLISHED:
        raise ServiceError("已发布前测不能直接删除，请先归档。", status=400)
    if paper.submissions.exists():
        raise ServiceError("该套卷已有学生作答，不能物理删除；请保持归档状态。", status=400)
    detail = {"title": paper.title, "subject": paper.subject.code, "kind": paper.kind}
    target_id = paper.id
    paper.delete()
    write_audit(
        request,
        "pretest_paper.delete",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=target_id,
        detail=detail,
    )


def _clean_options(raw_options) -> list[dict]:
    if isinstance(raw_options, list):
        options = []
        for index, option in enumerate(raw_options):
            if isinstance(option, dict):
                label = str(option.get("label") or chr(65 + index)).strip().upper()
                text = str(option.get("text") or "").strip()
            else:
                label = chr(65 + index)
                text = str(option).strip()
            if text:
                options.append({"label": label[:8], "text": text})
        return options
    if isinstance(raw_options, str):
        options = []
        for index, line in enumerate(raw_options.splitlines()):
            text = line.strip()
            if text:
                options.append({"label": chr(65 + index), "text": text})
        return options
    return []


def _clean_answer(raw_answer) -> list[str]:
    if isinstance(raw_answer, list):
        return [str(item).strip().upper() for item in raw_answer if str(item).strip()]
    text = str(raw_answer or "").strip().upper()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,，\s]+", text) if item.strip()]


def save_pretest_question(request, paper: PretestPaper, data, *, question: PretestQuestion | None = None) -> PretestQuestion:
    errors: dict[str, list[str]] = {}
    stem = str(data.get("stem", "")).strip()
    question_type = str(data.get("question_type", PretestQuestion.QuestionType.SINGLE)).strip()
    options = _clean_options(data.get("options", []))
    answer = _clean_answer(data.get("answer", []))
    score = _clean_float(data.get("score"), "score", errors, default=0)
    dimension = str(data.get("dimension", "")).strip()
    sort_order = _clean_optional_int(data.get("sort_order"), "sort_order", errors, min_value=0, max_value=9999)
    is_required = _clean_bool(data.get("is_required", True))

    if len(stem) < 2:
        errors["stem"] = ["题干不能为空，且至少 2 个字符。"]
    if question_type not in {item.value for item in PretestQuestion.QuestionType}:
        errors["question_type"] = ["题型不正确。"]
    if question_type in {PretestQuestion.QuestionType.SINGLE, PretestQuestion.QuestionType.MULTIPLE, PretestQuestion.QuestionType.SCALE}:
        if len(options) < 2:
            errors["options"] = ["选择题或量表题至少需要 2 个选项。"]
    if question_type == PretestQuestion.QuestionType.SINGLE and len(answer) > 1:
        errors["answer"] = ["单选题只能设置一个正确答案。"]
    if dimension and not _fullmatch(r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{1,64}$", dimension):
        errors["dimension"] = ["维度名称格式不正确。"]

    valid_labels = {option["label"].upper() for option in options}
    invalid_answers = [item for item in answer if valid_labels and item not in valid_labels]
    if invalid_answers:
        errors["answer"] = [f"答案不在选项中：{', '.join(invalid_answers)}。"]

    if errors:
        raise ServiceError("前测题目信息校验失败。", errors=errors, status=400)

    is_create = question is None
    if question is None:
        question = PretestQuestion(paper=paper)
    question.stem = stem
    question.question_type = question_type
    question.options = options
    question.answer = answer
    question.score = score
    question.dimension = dimension
    question.sort_order = sort_order or 0
    question.is_required = is_required
    question.save()
    write_audit(
        request,
        "pretest_question.create" if is_create else "pretest_question.update",
        school=request.user.school,
        target_type="pretest_question",
        target_id=question.id,
        detail={"paper": paper.id, "type": question.question_type, "score": question.score},
    )
    return question


def delete_pretest_question(request, question: PretestQuestion) -> None:
    paper = question.paper
    if paper.status == PretestPaper.Status.PUBLISHED and paper.submissions.exists():
        raise ServiceError("已发布且已有作答记录的题目不能物理删除，请复制新版本套卷后调整。", status=400)
    detail = {"paper": paper.id, "stem": question.stem[:80]}
    target_id = question.id
    question.delete()
    write_audit(
        request,
        "pretest_question.delete",
        school=request.user.school,
        target_type="pretest_question",
        target_id=target_id,
        detail=detail,
    )


def _teacher_class_ids_for_user(user) -> set[int]:
    return set(
        TeachingAssignment.objects.filter(school=user.school, teacher=user)
        .values_list("class_group_id", flat=True)
        .distinct()
    )


def _teacher_notice_class_groups(request, raw_class_ids, errors: dict) -> list[ClassGroup]:
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

    unauthorized = [str(class_id) for class_id in class_ids if class_id not in teacher_class_ids]
    if unauthorized:
        errors["target_classes"] = ["只能选择本人任教班级。"]
        return []

    classes = list(ClassGroup.objects.filter(school=request.user.school, id__in=class_ids).order_by("grade", "name"))
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
    target_classes = _teacher_notice_class_groups(request, data.get("target_classes"), errors)

    if not _fullmatch(r"^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]{2,128}$", title):
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
        detail={"title": notice.title, "status": notice.status, "class_count": len(target_classes)},
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
    write_audit(request, "notice.delete", school=request.user.school, target_type="notice", target_id=target_id, detail=detail)


def _teacher_course(request, course_id) -> Course:
    try:
        course = (
            Course.objects.select_related("subject", "teacher")
            .filter(pk=int(course_id), teacher=request.user, teacher__school=request.user.school)
            .first()
        )
    except (TypeError, ValueError):
        course = None
    if course is None:
        raise ServiceError("课程不存在或无权操作。", status=404)
    return course


def _teacher_lesson(request, lesson_id) -> Lesson:
    try:
        lesson = (
            Lesson.objects.select_related("course", "course__subject", "course__teacher")
            .filter(pk=int(lesson_id), course__teacher=request.user, course__teacher__school=request.user.school)
            .first()
        )
    except (TypeError, ValueError):
        lesson = None
    if lesson is None:
        raise ServiceError("课时不存在或无权操作。", status=404)
    return lesson


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
            )
            .filter(pk=int(session_id), school=request.user.school, teacher=request.user)
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
            .filter(pk=int(activity_id), session__school=request.user.school, session__teacher=request.user)
            .first()
        )
    except (TypeError, ValueError):
        activity = None
    if activity is None:
        raise ServiceError("课堂活动不存在或无权操作。", status=404)
    return activity


def _teacher_subject(request, raw_subject, errors: dict, *, required: bool = False) -> Subject | None:
    if raw_subject in {None, ""}:
        if required:
            errors["subject"] = ["请选择学科。"]
        return None
    try:
        subject = Subject.objects.get(pk=int(raw_subject), school=request.user.school, is_active=True)
    except (Subject.DoesNotExist, TypeError, ValueError):
        errors["subject"] = ["请选择本校启用学科。"]
        return None
    return subject


def _teacher_class_groups(request, raw_class_ids, errors: dict, *, field: str = "class_groups", allow_empty: bool = False) -> list[ClassGroup]:
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

    unauthorized = [str(class_id) for class_id in class_ids if class_id not in teacher_class_ids]
    if unauthorized:
        errors[field] = ["只能选择本人任教班级。"]
        return []

    classes = list(ClassGroup.objects.filter(school=request.user.school, id__in=class_ids).order_by("grade", "name"))
    if len(classes) != len(class_ids):
        errors[field] = ["部分班级不存在或不属于本校。"]
        return []
    inactive = [class_group.name for class_group in classes if class_group.status != ClassGroup.Status.ACTIVE]
    if inactive:
        errors[field] = [f"只能选择启用班级：{', '.join(inactive[:10])}。"]
        return []
    return classes


def _status_to_active(data, *, default=False) -> bool:
    status = str(data.get("status", "")).strip()
    if status:
        return status == "published"
    return _clean_bool(data.get("is_active", default))


@transaction.atomic
def save_teacher_course(request, data, *, course: Course | None = None) -> Course:
    errors: dict[str, list[str]] = {}
    title = str(data.get("title", "")).strip()
    introduction = str(data.get("introduction", "")).strip()
    teaching_model = str(data.get("teaching_model", Course.TeachingModel.PROJECT)).strip() or Course.TeachingModel.PROJECT
    subject = _teacher_subject(request, data.get("subject"), errors)
    status = str(data.get("status", "")).strip()

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["课程名称需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if len(introduction) > 5000:
        errors["introduction"] = ["课程简介不能超过 5000 个字符。"]
    if teaching_model not in {item.value for item in Course.TeachingModel}:
        errors["teaching_model"] = ["教学模式不正确。"]
    if status and status not in {"draft", "published"}:
        errors["status"] = ["课程状态只能为草稿或已发布。"]

    if errors:
        raise ServiceError("课程信息校验失败。", errors=errors, status=400)

    is_create = course is None
    if course is None:
        course = Course(teacher=request.user)
    course.subject = subject
    course.title = title
    course.introduction = introduction
    course.teaching_model = teaching_model
    course.is_active = _status_to_active(data, default=course.is_active)
    course.save()

    if "class_groups" in data or "target_classes" in data:
        set_teacher_course_classes(request, course, data)

    write_audit(
        request,
        "course.create" if is_create else "course.update",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title, "status": "published" if course.is_active else "draft"},
    )
    return course


def _validate_course_cover(uploaded_file) -> None:
    if uploaded_file is None:
        raise ServiceError("请选择课程封面图片。", errors={"cover": ["请选择课程封面图片。"]}, status=400)
    if uploaded_file.size > COURSE_COVER_MAX_SIZE:
        raise ServiceError("课程封面不能超过 5MB。", errors={"cover": ["课程封面不能超过 5MB。"]}, status=400)

    suffix = Path(uploaded_file.name or "").suffix.lower()
    content_type = getattr(uploaded_file, "content_type", "")
    if suffix not in COURSE_COVER_EXTENSIONS or content_type not in COURSE_COVER_CONTENT_TYPES:
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
        raise ServiceError("课程封面图片无法识别。", errors={"cover": ["课程封面图片无法识别。"]}, status=400)
    finally:
        uploaded_file.seek(0)

    if width < 320 or height < 160:
        raise ServiceError(
            "课程封面尺寸不能小于 320x160。",
            errors={"cover": ["课程封面尺寸不能小于 320x160。"]},
            status=400,
        )
    if width * height > 64_000_000:
        raise ServiceError("课程封面图片尺寸过大。", errors={"cover": ["课程封面图片尺寸过大。"]}, status=400)


@transaction.atomic
def save_teacher_course_cover(request, course: Course, uploaded_file) -> Course:
    _validate_course_cover(uploaded_file)
    if course.cover:
        course.cover.delete(save=False)
    course.cover = uploaded_file
    course.save(update_fields=["cover", "updated_at"])
    write_audit(
        request,
        "course.cover.update",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title, "filename": getattr(uploaded_file, "name", "")},
    )
    return course


@transaction.atomic
def delete_teacher_course_cover(request, course: Course) -> Course:
    if course.cover:
        course.cover.delete(save=False)
        course.cover = ""
        course.save(update_fields=["cover", "updated_at"])
    write_audit(
        request,
        "course.cover.delete",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title},
    )
    return course


def _validate_resource_file(uploaded_file) -> None:
    if uploaded_file is None:
        return
    if uploaded_file.size > RESOURCE_MAX_SIZE:
        raise ServiceError("资源文件不能超过 512MB。", errors={"attachment": ["资源文件不能超过 512MB。"]}, status=400)
    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix not in RESOURCE_ALLOWED_EXTENSIONS:
        raise ServiceError(
            "暂不支持该资源格式。",
            errors={"attachment": ["支持图片、音视频、PDF、Office 文档、文本、表格和压缩包。"]},
            status=400,
        )


def _teacher_resource(request, resource_id) -> Resource:
    try:
        resource = Resource.objects.filter(pk=int(resource_id), owner=request.user, owner__school=request.user.school).first()
    except (TypeError, ValueError):
        resource = None
    if resource is None:
        raise ServiceError("资源不存在或无权操作。", status=404)
    return resource


@transaction.atomic
def save_teacher_resource(request, data, *, resource: Resource | None = None, uploaded_file=None) -> Resource:
    errors: dict[str, list[str]] = {}
    fallback_title = Path(getattr(uploaded_file, "name", "") or "").stem
    title = str(data.get("title", "") or fallback_title).strip()
    content = str(data.get("content", "")).strip()
    is_pinned = _clean_bool(data.get("is_pinned", resource.is_pinned if resource else False))

    if not _fullmatch(RESOURCE_TITLE_PATTERN, title):
        errors["title"] = ["资源标题需为 2-128 位，可包含中文、字母、数字、下划线和常用标点。"]
    if len(content) > 5000:
        errors["content"] = ["资源说明不能超过 5000 个字符。"]
    try:
        _validate_resource_file(uploaded_file)
    except ServiceError as exc:
        errors.update(exc.errors)

    if resource is None and uploaded_file is None and not content:
        errors["attachment"] = ["请上传资源文件，或填写资源说明。"]

    if errors:
        raise ServiceError("资源信息校验失败。", errors=errors, status=400)

    is_create = resource is None
    if resource is None:
        resource = Resource(owner=request.user)
    resource.title = title
    resource.content = content
    resource.is_pinned = is_pinned
    if uploaded_file is not None:
        if resource.attachment:
            resource.attachment.delete(save=False)
        resource.attachment = uploaded_file
    resource.save()

    write_audit(
        request,
        "resource.create" if is_create else "resource.update",
        school=request.user.school,
        target_type="resource",
        target_id=resource.id,
        detail={
            "title": resource.title,
            "filename": getattr(uploaded_file, "name", "") if uploaded_file else "",
            "has_attachment": bool(resource.attachment),
        },
    )
    return resource


def delete_teacher_resource(request, resource: Resource) -> None:
    detail = {
        "title": resource.title,
        "filename": resource.attachment.name if resource.attachment else "",
    }
    target_id = resource.id
    if resource.attachment:
        resource.attachment.delete(save=False)
    resource.delete()
    write_audit(request, "resource.delete", school=request.user.school, target_type="resource", target_id=target_id, detail=detail)


@transaction.atomic
def set_teacher_course_classes(request, course: Course, data) -> Course:
    errors: dict[str, list[str]] = {}
    raw_class_ids = data.get("class_groups", data.get("target_classes"))
    classes = _teacher_class_groups(request, raw_class_ids, errors, field="class_groups", allow_empty=True)
    if errors:
        raise ServiceError("课程班级范围校验失败。", errors=errors, status=400)

    class_ids = {class_group.id for class_group in classes}
    CourseClass.objects.filter(course=course).exclude(class_group_id__in=class_ids).delete()
    for class_group in classes:
        CourseClass.objects.get_or_create(course=course, class_group=class_group, defaults={"created_by": request.user})

    write_audit(
        request,
        "course.classes.update",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title, "class_ids": sorted(class_ids)},
    )
    return course


def publish_teacher_course(request, course: Course) -> Course:
    if not course.subject_id:
        raise ServiceError("课程发布前需要选择学科。", errors={"subject": ["课程发布前需要选择学科。"]}, status=400)
    if not course.course_classes.exists():
        raise ServiceError("课程发布前至少需要绑定 1 个任教班级。", errors={"class_groups": ["请选择课程可见班级。"]}, status=400)
    if not course.lessons.exists():
        raise ServiceError("课程发布前至少需要创建 1 个课时。", status=400)
    course.is_active = True
    course.save(update_fields=["is_active", "updated_at"])
    write_audit(
        request,
        "course.publish",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title},
    )
    return course


def archive_teacher_course(request, course: Course) -> Course:
    course.is_active = False
    course.save(update_fields=["is_active", "updated_at"])
    write_audit(
        request,
        "course.archive",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title},
    )
    return course


def delete_teacher_course(request, course: Course) -> None:
    if course.is_active:
        raise ServiceError("已发布课程不能直接删除，请先停用。", status=400)
    blockers = []
    if LearningEvent.objects.filter(course=course).exists():
        blockers.append("学习行为")
    if course.classroom_sessions.exists():
        blockers.append("课堂记录")
    if course.lessons.filter(classroom_sessions__isnull=False).exists():
        blockers.append("课时课堂")
    if blockers:
        raise ServiceError(f"该课程已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。", status=400)
    detail = {"title": course.title}
    target_id = course.id
    course.delete()
    write_audit(request, "course.delete", school=request.user.school, target_type="course", target_id=target_id, detail=detail)


def save_teacher_lesson(request, course: Course, data, *, lesson: Lesson | None = None) -> Lesson:
    errors: dict[str, list[str]] = {}
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    sort_order = _clean_optional_int(data.get("sort_order"), "sort_order", errors, min_value=0, max_value=9999)
    status = str(data.get("status", "")).strip()

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["课时名称需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if len(content) > 5000:
        errors["content"] = ["课时内容不能超过 5000 个字符。"]
    if status and status not in {"draft", "published"}:
        errors["status"] = ["课时状态只能为草稿或已发布。"]

    if errors:
        raise ServiceError("课时信息校验失败。", errors=errors, status=400)

    is_create = lesson is None
    if lesson is None:
        max_order = course.lessons.aggregate(value=Max("sort_order")).get("value") or 0
        lesson = Lesson(course=course, sort_order=sort_order if sort_order is not None else max_order + 10)
    else:
        lesson.sort_order = sort_order if sort_order is not None else lesson.sort_order
    lesson.title = title
    lesson.content = content
    lesson.is_active = _status_to_active(data, default=lesson.is_active)
    lesson.save()
    write_audit(
        request,
        "lesson.create" if is_create else "lesson.update",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={"course": course.id, "title": lesson.title, "status": "published" if lesson.is_active else "draft"},
    )
    return lesson


def publish_teacher_lesson(request, lesson: Lesson) -> Lesson:
    lesson.is_active = True
    lesson.save(update_fields=["is_active", "updated_at"])
    write_audit(
        request,
        "lesson.publish",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={"course": lesson.course_id, "title": lesson.title},
    )
    return lesson


def archive_teacher_lesson(request, lesson: Lesson) -> Lesson:
    lesson.is_active = False
    lesson.save(update_fields=["is_active", "updated_at"])
    write_audit(
        request,
        "lesson.archive",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={"course": lesson.course_id, "title": lesson.title},
    )
    return lesson


def delete_teacher_lesson(request, lesson: Lesson) -> None:
    if lesson.is_active:
        raise ServiceError("已发布课时不能直接删除，请先停用。", status=400)
    blockers = []
    if LearningEvent.objects.filter(lesson=lesson).exists():
        blockers.append("学习行为")
    if lesson.classroom_sessions.exists():
        blockers.append("课堂记录")
    if blockers:
        raise ServiceError(f"该课时已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。", status=400)
    detail = {"course": lesson.course_id, "title": lesson.title}
    target_id = lesson.id
    lesson.delete()
    write_audit(request, "lesson.delete", school=request.user.school, target_type="lesson", target_id=target_id, detail=detail)


def _clean_string_items(data, field: str, errors: dict, *, max_items: int = 20, max_length: int = 128) -> list[str]:
    raw_items = data.get(field, [])
    if raw_items is None or raw_items == "":
        return []
    if not isinstance(raw_items, list):
        errors[field] = ["数据格式不正确。"]
        return []

    items: list[str] = []
    for raw_item in raw_items:
        text = str(raw_item).strip()
        if not text:
            continue
        if len(text) > max_length:
            errors[field] = [f"单项内容不能超过 {max_length} 个字符。"]
            continue
        if text not in items:
            items.append(text)

    if len(items) > max_items:
        errors[field] = [f"最多填写 {max_items} 项。"]
        return items[:max_items]
    return items


def _resource_binding(resource: Resource) -> dict:
    attachment_url = ""
    attachment_name = ""
    file_ext = ""
    if resource.attachment:
        attachment_url = f"/{resource.attachment.url.lstrip('/')}"
        attachment_name = resource.attachment.name.rsplit("/", 1)[-1]
        file_ext = clean_resource_ext(attachment_name, attachment_url)
    return {
        "id": resource.id,
        "title": resource.title,
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
        "file_ext": file_ext,
        "kind": "resource",
    }


def _clean_resource_items(request, data, field: str, errors: dict, *, max_items: int = 30) -> list[dict]:
    raw_items = data.get(field, [])
    if raw_items is None or raw_items == "":
        return []
    if not isinstance(raw_items, list):
        errors[field] = ["资源数据格式不正确。"]
        return []

    items: list[dict] = []
    seen = set()
    for raw_item in raw_items:
        if isinstance(raw_item, dict):
            raw_id = raw_item.get("id") or raw_item.get("resource_id")
            if raw_id:
                try:
                    resource_id = int(raw_id)
                except (TypeError, ValueError):
                    errors[field] = ["资源编号不正确。"]
                    continue
                resource = Resource.objects.filter(pk=resource_id, owner=request.user, owner__school=request.user.school).first()
                if resource is None:
                    errors[field] = ["资源不存在或无权绑定。"]
                    continue
                key = f"resource:{resource.id}"
                if key not in seen:
                    seen.add(key)
                    items.append(_resource_binding(resource))
                continue
            text = str(raw_item.get("title") or raw_item.get("name") or "").strip()
        else:
            text = str(raw_item).strip()

        if not text:
            continue
        if len(text) > 128:
            errors[field] = ["资源名称不能超过 128 个字符。"]
            continue
        key = f"legacy:{text}"
        if key not in seen:
            seen.add(key)
            file_ext = clean_resource_ext(text)
            items.append(
                {
                    "id": "",
                    "title": text,
                    "attachment_url": "",
                    "attachment_name": text,
                    "file_ext": file_ext,
                    "kind": "legacy",
                }
            )

    if len(items) > max_items:
        errors[field] = [f"最多绑定 {max_items} 个资源。"]
        return items[:max_items]
    return items


def _clean_lesson_question_items(data, field: str, errors: dict, *, max_items: int = 30) -> list[dict]:
    raw_items = data.get(field, [])
    if raw_items is None or raw_items == "":
        return []
    if not isinstance(raw_items, list):
        errors[field] = ["题目数据格式不正确。"]
        return []

    items: list[dict] = []
    seen_ids = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            errors[field] = ["题目数据格式不正确。"]
            continue

        question_type = str(raw_item.get("question_type") or raw_item.get("type") or "single").strip()
        stem = str(raw_item.get("stem") or raw_item.get("title") or "").strip()
        analysis = str(raw_item.get("analysis") or "").strip()
        raw_options = raw_item.get("options", [])
        raw_answer = raw_item.get("answer", [])
        raw_id = str(raw_item.get("id") or "").strip()
        target_layer = str(raw_item.get("target_layer") or LessonStep.TargetLayer.ALL).strip() or LessonStep.TargetLayer.ALL
        use_layer_scores = _clean_bool(raw_item.get("use_layer_scores", False))
        raw_layer_scores = raw_item.get("layer_scores") if isinstance(raw_item.get("layer_scores"), dict) else {}
        question_id = raw_id if re.fullmatch(r"[A-Za-z0-9_-]{3,40}", raw_id) else f"q_{uuid4().hex[:12]}"
        while question_id in seen_ids:
            question_id = f"q_{uuid4().hex[:12]}"
        seen_ids.add(question_id)

        if question_type not in LESSON_QUESTION_TYPES:
            errors[field] = ["题型不正确。"]
            continue
        if target_layer not in {item.value for item in LessonStep.TargetLayer}:
            errors[field] = ["题目适用层级不正确。"]
            continue
        if not 2 <= len(stem) <= 1000:
            errors[field] = ["题干需为 2-1000 个字符。"]
            continue
        if len(analysis) > 1000:
            errors[field] = ["解析不能超过 1000 个字符。"]
            continue

        options: list[str] = []
        if question_type == "judge":
            options = ["正确", "错误"]
        elif question_type in {"single", "multiple"}:
            if isinstance(raw_options, list):
                for option in raw_options:
                    text = normalize_text(str(option))
                    if text and text not in options:
                        options.append(text[:200])
            if len(options) < 2:
                errors[field] = ["单选题和多选题至少需要 2 个选项。"]
                continue
            options = options[:8]

        if isinstance(raw_answer, list):
            answer = [normalize_text(str(value)) for value in raw_answer if normalize_text(str(value))]
        elif raw_answer is None or raw_answer == "":
            answer = []
        else:
            answer = [normalize_text(str(raw_answer))]
        if question_type == "single" and len(answer) > 1:
            answer = answer[:1]
        if question_type == "judge" and answer and answer[0] not in {"正确", "错误"}:
            answer = []
        if question_type in {"single", "multiple"} and answer:
            answer = [value for value in answer if value in options]

        try:
            score = float(raw_item.get("score", 1) or 0)
        except (TypeError, ValueError):
            errors[field] = ["题目分值必须是数字。"]
            score = 0
        if score < 0 or score > 100:
            errors[field] = ["题目分值需在 0-100 之间。"]
            continue

        layer_scores: dict[str, float] = {}
        layer_score_error = False
        for layer_code in ("A", "B", "C"):
            raw_layer_score = raw_layer_scores.get(layer_code, score)
            if raw_layer_score is None or raw_layer_score == "":
                raw_layer_score = score
            try:
                layer_score = float(raw_layer_score)
            except (TypeError, ValueError):
                errors[field] = [f"{layer_code} 层分值必须是数字。"]
                layer_score_error = True
                layer_score = score
            if layer_score < 0 or layer_score > 100:
                errors[field] = [f"{layer_code} 层分值需在 0-100 之间。"]
                layer_score_error = True
                continue
            layer_scores[layer_code] = layer_score
        if layer_score_error:
            continue

        sort_order = _clean_optional_int(
            raw_item.get("sort_order", (index + 1) * 10),
            field,
            errors,
            min_value=0,
            max_value=9999,
        )
        items.append(
            {
                "id": question_id,
                "question_type": question_type,
                "stem": stem,
                "options": options,
                "answer": answer,
                "score": score,
                "target_layer": target_layer,
                "use_layer_scores": use_layer_scores,
                "layer_scores": layer_scores,
                "analysis": analysis,
                "is_required": _clean_bool(raw_item.get("is_required", True)),
                "sort_order": sort_order if sort_order is not None else (index + 1) * 10,
            }
        )

    if len(items) > max_items:
        errors[field] = [f"最多配置 {max_items} 道题。"]
        items = items[:max_items]
    return sorted(items, key=lambda item: (item["sort_order"], item["id"]))


def save_lesson_step(request, lesson: Lesson, data, *, step: LessonStep | None = None) -> LessonStep:
    errors: dict[str, list[str]] = {}
    title = str(data.get("title", "")).strip()
    step_type = str(data.get("step_type", LessonStep.StepType.RESOURCE)).strip() or LessonStep.StepType.RESOURCE
    student_instruction = str(data.get("student_instruction", "")).strip()
    teacher_note = str(data.get("teacher_note", "")).strip()
    ai_prompt = str(data.get("ai_prompt", "")).strip()
    sort_order = _clean_optional_int(data.get("sort_order"), "sort_order", errors, min_value=0, max_value=9999)
    estimated_minutes = _clean_optional_int(data.get("estimated_minutes"), "estimated_minutes", errors, min_value=1, max_value=240)
    target_layer = str(data.get("target_layer", LessonStep.TargetLayer.ALL)).strip() or LessonStep.TargetLayer.ALL
    status = str(data.get("status", LessonStep.Status.DRAFT)).strip() or LessonStep.Status.DRAFT
    resource_items = _clean_resource_items(request, data, "resource_items", errors, max_items=30)
    activity_items = _clean_string_items(data, "activity_items", errors, max_items=30, max_length=128)
    question_items = _clean_lesson_question_items(data, "question_items", errors, max_items=30)

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["环节标题需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if step_type not in {item.value for item in LessonStep.StepType}:
        errors["step_type"] = ["环节类型不正确。"]
    if len(student_instruction) > 5000:
        errors["student_instruction"] = ["学生可见说明不能超过 5000 个字符。"]
    if len(teacher_note) > 5000:
        errors["teacher_note"] = ["教师备课备注不能超过 5000 个字符。"]
    if len(ai_prompt) > 3000:
        errors["ai_prompt"] = ["AI 生成目标不能超过 3000 个字符。"]
    if target_layer not in {item.value for item in LessonStep.TargetLayer}:
        errors["target_layer"] = ["目标层级不正确。"]
    if status not in {item.value for item in LessonStep.Status}:
        errors["status"] = ["环节状态不正确。"]

    if errors:
        raise ServiceError("课时环节校验失败。", errors=errors, status=400)

    is_create = step is None
    if step is None:
        max_order = lesson.steps.aggregate(value=Max("sort_order")).get("value") or 0
        step = LessonStep(
            lesson=lesson,
            created_by=request.user,
            sort_order=sort_order if sort_order is not None else max_order + 10,
        )
    else:
        step.sort_order = sort_order if sort_order is not None else step.sort_order

    step.title = title
    step.step_type = step_type
    step.student_instruction = student_instruction
    step.teacher_note = teacher_note
    step.estimated_minutes = estimated_minutes if estimated_minutes is not None else step.estimated_minutes
    step.target_layer = target_layer
    step.status = status
    step.is_required = _clean_bool(data.get("is_required", step.is_required))
    step.collect_student_log = _clean_bool(data.get("collect_student_log", step.collect_student_log))
    step.collect_class_log = _clean_bool(data.get("collect_class_log", step.collect_class_log))
    step.resource_items = resource_items
    step.activity_items = activity_items
    step.question_items = question_items
    step.ai_prompt = ai_prompt
    step.save()

    write_audit(
        request,
        "lesson_step.create" if is_create else "lesson_step.update",
        school=request.user.school,
        target_type="lesson_step",
        target_id=step.id,
        detail={"lesson": lesson.id, "title": step.title, "type": step.step_type, "status": step.status},
    )
    return step


def delete_lesson_step(request, step: LessonStep) -> None:
    detail = {
        "lesson": step.lesson_id,
        "title": step.title,
        "type": step.step_type,
        "status": step.status,
    }
    target_id = step.id
    step.delete()
    write_audit(request, "lesson_step.delete", school=request.user.school, target_type="lesson_step", target_id=target_id, detail=detail)


@transaction.atomic
def reorder_lesson_steps(request, lesson: Lesson, data) -> list[LessonStep]:
    raw_ids = data.get("ids") if hasattr(data, "get") else None
    if not isinstance(raw_ids, list):
        raise ServiceError("请提交环节排序数据。", errors={"ids": ["请提交环节排序数据。"]}, status=400)

    ids: list[int] = []
    for raw_id in raw_ids:
        try:
            step_id = int(raw_id)
        except (TypeError, ValueError):
            raise ServiceError("环节排序编号不正确。", errors={"ids": ["环节排序编号不正确。"]}, status=400)
        if step_id not in ids:
            ids.append(step_id)

    steps = list(LessonStep.objects.filter(lesson=lesson, id__in=ids).order_by("sort_order", "id"))
    if len(steps) != len(ids):
        raise ServiceError("部分环节不存在或不属于当前课时。", errors={"ids": ["部分环节不存在或不属于当前课时。"]}, status=404)

    by_id = {step.id: step for step in steps}
    for index, step_id in enumerate(ids, start=1):
        step = by_id[step_id]
        step.sort_order = index * 10
        step.save(update_fields=["sort_order", "updated_at"])

    write_audit(
        request,
        "lesson_step.reorder",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={"step_ids": ids},
    )
    return list(LessonStep.objects.filter(lesson=lesson).order_by("sort_order", "id"))


def _write_classroom_event(
    request,
    session: ClassroomSession,
    *,
    action: str,
    activity: ClassroomActivity | None = None,
    step: LessonStep | None = None,
) -> None:
    object_type = "classroom_session"
    object_id = str(session.id)
    if activity:
        object_type = "classroom_activity"
        object_id = str(activity.id)
    elif step:
        object_type = "lesson_step"
        object_id = str(step.id)
    LearningEvent.objects.create(
        actor=request.user,
        class_group=session.class_group,
        course=session.course,
        lesson=session.lesson,
        event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
        object_type=object_type,
        object_id=object_id,
        metadata={
            "action": action,
            "session": session.id,
            "activity": activity.id if activity else None,
            "activity_type": activity.activity_type if activity else "",
            "step": step.id if step else None,
            "step_status": session.current_step_status,
            "submission_locked": session.submission_locked,
            "is_layered": session.is_layered,
        },
        occurred_at=timezone.now(),
    )


def _classroom_session_step(session: ClassroomSession, step_id) -> LessonStep:
    if not session.lesson_id:
        raise ServiceError("当前课堂未绑定课时，不能投放学习环节。", status=400)
    try:
        step = LessonStep.objects.filter(pk=int(step_id), lesson=session.lesson, status=LessonStep.Status.READY).first()
    except (TypeError, ValueError):
        step = None
    if step is None:
        raise ServiceError("环节不存在、未配置，或不属于当前课堂课时。", status=404)
    return step


def set_classroom_current_step(request, session: ClassroomSession, data) -> ClassroomSession:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("请先开始课堂，再投放课时环节。", status=400)
    step = _classroom_session_step(session, data.get("step_id"))
    now = timezone.now()
    session.current_step = step
    session.current_step_status = ClassroomSession.StepStatus.OPEN
    session.submission_locked = False
    session.current_step_started_at = now
    session.current_step_closed_at = None
    session.save(
        update_fields=[
            "current_step",
            "current_step_status",
            "submission_locked",
            "current_step_started_at",
            "current_step_closed_at",
            "updated_at",
        ]
    )
    _write_classroom_event(request, session, action="step_opened", step=step)
    write_audit(
        request,
        "classroom.step.open",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"session": session.id, "step": step.id, "step_title": step.title},
    )
    return session


def lock_classroom_current_step(request, session: ClassroomSession) -> ClassroomSession:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("只有进行中的课堂可以锁定提交。", status=400)
    if not session.current_step_id:
        raise ServiceError("请先投放一个环节。", status=400)
    session.current_step_status = ClassroomSession.StepStatus.LOCKED
    session.submission_locked = True
    session.save(update_fields=["current_step_status", "submission_locked", "updated_at"])
    _write_classroom_event(request, session, action="step_locked", step=session.current_step)
    write_audit(
        request,
        "classroom.step.lock",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"session": session.id, "step": session.current_step_id},
    )
    return session


def close_classroom_current_step(request, session: ClassroomSession) -> ClassroomSession:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("只有进行中的课堂可以关闭当前环节。", status=400)
    if not session.current_step_id:
        raise ServiceError("请先投放一个环节。", status=400)
    session.current_step_status = ClassroomSession.StepStatus.CLOSED
    session.submission_locked = True
    session.current_step_closed_at = timezone.now()
    session.save(update_fields=["current_step_status", "submission_locked", "current_step_closed_at", "updated_at"])
    _write_classroom_event(request, session, action="step_closed", step=session.current_step)
    write_audit(
        request,
        "classroom.step.close",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"session": session.id, "step": session.current_step_id},
    )
    return session


def save_classroom_session(request, data, *, session: ClassroomSession | None = None) -> ClassroomSession:
    errors: dict[str, list[str]] = {}
    course = _teacher_course(request, data.get("course"))
    raw_lesson = data.get("lesson")
    lesson = None
    if raw_lesson not in {None, ""}:
        lesson = _teacher_lesson(request, raw_lesson)
        if lesson.course_id != course.id:
            errors["lesson"] = ["课时必须属于所选课程。"]
    classes = _teacher_class_groups(request, [data.get("class_group")], errors, field="class_group", allow_empty=False)
    class_group = classes[0] if classes else None
    title = str(data.get("title", "")).strip()
    if not title and course and class_group:
        title = f"{course.title} - {class_group.name}"

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["课堂标题需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if course and class_group and not CourseClass.objects.filter(course=course, class_group=class_group).exists():
        errors["class_group"] = ["该课程尚未绑定所选班级，请先在课程管理中设置班级范围。"]
    if session and session.status == ClassroomSession.Status.FINISHED:
        errors["status"] = ["已结束课堂不能修改基础信息。"]

    if errors:
        raise ServiceError("课堂信息校验失败。", errors=errors, status=400)

    is_create = session is None
    if session is None:
        session = ClassroomSession(school=request.user.school, teacher=request.user)
    session.course = course
    session.lesson = lesson
    session.class_group = class_group
    session.title = title
    session.is_layered = _clean_bool(data.get("is_layered", session.is_layered))
    if session.current_step_id and (lesson is None or session.current_step.lesson_id != lesson.id):
        session.current_step = None
        session.current_step_status = ClassroomSession.StepStatus.IDLE
        session.submission_locked = False
        session.current_step_started_at = None
        session.current_step_closed_at = None
    session.save()
    write_audit(
        request,
        "classroom.session.create" if is_create else "classroom.session.update",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"title": session.title, "course": course.id, "class_group": class_group.id, "is_layered": session.is_layered},
    )
    return session


def start_classroom_session(request, session: ClassroomSession) -> ClassroomSession:
    if session.status == ClassroomSession.Status.FINISHED:
        raise ServiceError("已结束课堂不能重新开始。", status=400)
    session.status = ClassroomSession.Status.RUNNING
    if not session.current_step_id:
        session.current_step_status = ClassroomSession.StepStatus.IDLE
        session.submission_locked = False
    session.started_at = session.started_at or timezone.now()
    session.finished_at = None
    session.save(update_fields=["status", "current_step_status", "submission_locked", "started_at", "finished_at", "updated_at"])
    _write_classroom_event(request, session, action="session_started")
    write_audit(
        request,
        "classroom.session.start",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"title": session.title},
    )
    return session


def restart_classroom_session(request, session: ClassroomSession) -> ClassroomSession:
    if session.status != ClassroomSession.Status.FINISHED:
        return start_classroom_session(request, session)
    now = timezone.now()
    session.status = ClassroomSession.Status.RUNNING
    session.current_step = None
    session.current_step_status = ClassroomSession.StepStatus.IDLE
    session.submission_locked = False
    session.current_step_started_at = None
    session.current_step_closed_at = None
    session.started_at = now
    session.finished_at = None
    session.save(
        update_fields=[
            "status",
            "current_step",
            "current_step_status",
            "submission_locked",
            "current_step_started_at",
            "current_step_closed_at",
            "started_at",
            "finished_at",
            "updated_at",
        ]
    )
    _write_classroom_event(request, session, action="session_restarted")
    write_audit(
        request,
        "classroom.session.restart",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"title": session.title},
    )
    return session


def finish_classroom_session(request, session: ClassroomSession) -> ClassroomSession:
    session.status = ClassroomSession.Status.FINISHED
    session.finished_at = timezone.now()
    if session.current_step_id and session.current_step_status != ClassroomSession.StepStatus.CLOSED:
        session.current_step_status = ClassroomSession.StepStatus.CLOSED
        session.submission_locked = True
        session.current_step_closed_at = session.finished_at
    session.activities.filter(status=ClassroomActivity.Status.OPEN).update(
        status=ClassroomActivity.Status.CLOSED,
        closed_at=session.finished_at,
        updated_at=session.finished_at,
    )
    session.save(
        update_fields=[
            "status",
            "current_step_status",
            "submission_locked",
            "current_step_closed_at",
            "finished_at",
            "updated_at",
        ]
    )
    _write_classroom_event(request, session, action="session_finished")
    write_audit(
        request,
        "classroom.session.finish",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"title": session.title},
    )
    return session


def delete_classroom_session(request, session: ClassroomSession) -> None:
    if session.status != ClassroomSession.Status.DRAFT:
        raise ServiceError("只有未开始课堂可以删除；进行中或已结束课堂请保留记录。", status=400)
    detail = {"title": session.title}
    target_id = session.id
    session.delete()
    write_audit(
        request,
        "classroom.session.delete",
        school=request.user.school,
        target_type="classroom_session",
        target_id=target_id,
        detail=detail,
    )


def save_classroom_activity(
    request,
    session: ClassroomSession,
    data,
    *,
    activity: ClassroomActivity | None = None,
) -> ClassroomActivity:
    errors: dict[str, list[str]] = {}
    activity_type = str(data.get("activity_type", ClassroomActivity.ActivityType.QUESTION)).strip()
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()

    if activity_type not in {item.value for item in ClassroomActivity.ActivityType}:
        errors["activity_type"] = ["课堂活动类型不正确。"]
    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["活动标题需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if len(content) > 5000:
        errors["content"] = ["活动内容不能超过 5000 个字符。"]
    if session.status == ClassroomSession.Status.FINISHED:
        errors["session"] = ["已结束课堂不能新增或编辑活动。"]
    if activity and activity.status == ClassroomActivity.Status.OPEN:
        errors["status"] = ["进行中的活动请先关闭后再编辑。"]

    if errors:
        raise ServiceError("课堂活动校验失败。", errors=errors, status=400)

    is_create = activity is None
    if activity is None:
        activity = ClassroomActivity(session=session)
    activity.activity_type = activity_type
    activity.title = title
    activity.content = content
    activity.save()
    write_audit(
        request,
        "classroom.activity.create" if is_create else "classroom.activity.update",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=activity.id,
        detail={"session": session.id, "type": activity.activity_type, "title": activity.title},
    )
    return activity


def open_classroom_activity(request, activity: ClassroomActivity) -> ClassroomActivity:
    session = activity.session
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("请先开始课堂，再开启课堂活动。", status=400)
    activity.status = ClassroomActivity.Status.OPEN
    activity.opened_at = timezone.now()
    activity.closed_at = None
    activity.save(update_fields=["status", "opened_at", "closed_at", "updated_at"])
    _write_classroom_event(request, session, action="activity_opened", activity=activity)
    write_audit(
        request,
        "classroom.activity.open",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=activity.id,
        detail={"session": session.id, "type": activity.activity_type, "title": activity.title},
    )
    return activity


def close_classroom_activity(request, activity: ClassroomActivity) -> ClassroomActivity:
    activity.status = ClassroomActivity.Status.CLOSED
    activity.closed_at = timezone.now()
    activity.save(update_fields=["status", "closed_at", "updated_at"])
    _write_classroom_event(request, activity.session, action="activity_closed", activity=activity)
    write_audit(
        request,
        "classroom.activity.close",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=activity.id,
        detail={"session": activity.session_id, "type": activity.activity_type, "title": activity.title},
    )
    return activity


def delete_classroom_activity(request, activity: ClassroomActivity) -> None:
    if activity.status == ClassroomActivity.Status.OPEN:
        raise ServiceError("进行中的课堂活动不能删除，请先关闭。", status=400)
    detail = {"session": activity.session_id, "title": activity.title, "type": activity.activity_type}
    target_id = activity.id
    activity.delete()
    write_audit(
        request,
        "classroom.activity.delete",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=target_id,
        detail=detail,
    )


def reply_teacher_feedback(request, feedback: Feedback, data) -> Feedback:
    reply_content = str(data.get("reply_content", "")).strip()
    if len(reply_content) < 2 or len(reply_content) > 3000:
        raise ServiceError("回复内容需为 2-3000 个字符。", errors={"reply_content": ["回复内容需为 2-3000 个字符。"]}, status=400)
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
