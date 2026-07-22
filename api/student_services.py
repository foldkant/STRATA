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

# Students domain services extracted from api.services.
from . import services as _shared_services
from .services import (
    ServiceError,
    _active_value,
    _clean_bool,
    _clean_float,
    _clean_id_list,
    _clean_optional_int,
    _ensure_all_selected,
    _fullmatch,
    _row_error,
    set_account_active,
    write_audit,
)

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


def _student_brief(profile: StudentProfile, reason: str = "") -> dict:
    return {
        "id": profile.id,
        "username": profile.user.username,
        "display_name": profile.user.display_name,
        "student_no": profile.student_no,
        "reason": reason,
    }


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

    _shared_services.write_audit(
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
            errors={
                "ids": [
                    f"未停用：{', '.join(profile.user.username for profile in active)}"
                ]
            },
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
    return {
        "requested_count": len(ids),
        "deleted_count": deleted,
        "blocked": blocked,
        "message": message,
    }


def _student_payload_errors(
    request,
    data,
    *,
    profile: StudentProfile | None = None,
    require_password: bool = False,
):
    errors: dict[str, list[str]] = {}
    username = str(data.get("username", "")).strip()
    display_name = str(data.get("display_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))
    student_no = str(data.get("student_no", "")).strip()
    current_layer = str(data.get("current_layer", "")).strip() or None
    class_group_id = data.get("class_group")
    current_group_no = _clean_optional_int(
        data.get("current_group_no"),
        "current_group_no",
        errors,
        min_value=1,
        max_value=999,
    )
    score = _clean_float(data.get("score"), "score", errors, default=0)

    class_group = None
    if class_group_id not in {None, ""}:
        try:
            class_group = ClassGroup.objects.get(
                pk=class_group_id, school=request.user.school
            )
        except (ClassGroup.DoesNotExist, TypeError, ValueError):
            errors["class_group"] = ["请选择本校班级。"]

    if not _fullmatch(USERNAME_PATTERN, username):
        errors["username"] = [
            "账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 student1。"
        ]
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
    if current_layer and current_layer not in {
        item.value for item in StudentProfile.Layer
    }:
        errors["current_layer"] = ["层级只能为 A、B 或 C。"]

    User = get_user_model()
    user_queryset = User.objects.filter(username=username)
    if profile is not None:
        user_queryset = user_queryset.exclude(pk=profile.user_id)
    if username and user_queryset.exists():
        errors["username"] = ["该登录账号已存在。"]

    if class_group and student_no:
        no_queryset = StudentProfile.objects.filter(
            class_group=class_group, student_no=student_no
        )
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


def _school_class_by_name(
    request, name: str, row: dict, errors: list[str]
) -> ClassGroup | None:
    class_name = normalize_text(name)
    if not class_name:
        return None
    class_group = ClassGroup.objects.filter(
        school=request.user.school, name=class_name
    ).first()
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
        current_group_no = _clean_optional_int(
            row.get("小组号"), "current_group_no", {}, min_value=1, max_value=999
        )
        score_errors: dict[str, list[str]] = {}
        score = _clean_float(row.get("积分"), "score", score_errors, default=0)
        existing_user = (
            User.objects.filter(username=username).first() if username else None
        )
        existing_profile = None
        if existing_user and existing_user.role == "student":
            try:
                existing_profile = existing_user.student_profile
            except StudentProfile.DoesNotExist:
                existing_profile = None

        if not _fullmatch(USERNAME_PATTERN, username):
            errors.append(
                _row_error(
                    row,
                    "登录账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 student1。",
                )
            )
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
            no_queryset = StudentProfile.objects.filter(
                class_group=class_group, student_no=student_no
            )
            if existing_profile is not None:
                no_queryset = no_queryset.exclude(pk=existing_profile.pk)
            if no_queryset.exists():
                errors.append(
                    _row_error(
                        row, f"班级 {class_group.name} 已存在学号 {student_no}。"
                    )
                )
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
            errors.append(
                _row_error(row, f"登录账号 {username} 不属于本校，不能更新。")
            )
        if (
            existing_user
            and existing_user.role == "student"
            and existing_profile is None
        ):
            errors.append(
                _row_error(
                    row, f"学生账号 {username} 缺少学生档案，请联系技术人员处理。"
                )
            )
        if not existing_user and not password:
            errors.append(_row_error(row, "新增学生必须填写初始密码。"))
        if password and not _matches(TEACHING_PASSWORD_PATTERN, password):
            errors.append(
                _row_error(
                    row, "学生初始密码需为 6-32 位，可使用字母、数字和常用符号。"
                )
            )

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
    rows = read_table_rows(
        uploaded_file,
        required_headers=["登录账号", "姓名"],
        all_headers=STUDENT_IMPORT_HEADERS,
    )
    if not rows:
        raise ServiceError("Excel 文件没有可导入的数据行。", status=400)

    records, errors = _validate_student_import(request, rows)
    if errors:
        raise ServiceError(
            "学生批量导入校验失败。", errors={"rows": errors[:100]}, status=400
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

    _shared_services.write_audit(
        request,
        "student.bulk_import",
        school=request.user.school,
        target_type="student_profile",
        detail={"created": created_count, "updated": updated_count},
    )
    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "total_count": len(records),
    }


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
    _shared_services.write_audit(
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
        raise ServiceError(
            "学生信息校验失败。",
            errors={"student_no": ["该班级已存在相同学号。"]},
            status=400,
        )
    _shared_services.write_audit(
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
    _shared_services.write_audit(
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
        raise ServiceError(
            "该账号仍处于启用状态。请先停用账号，再执行删除。", status=400
        )

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
        raise ServiceError(
            f"该学生已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。",
            status=400,
        )

    detail = {
        "username": user.username,
        "display_name": user.display_name,
        "student_no": profile.student_no,
        "class_group": profile.class_group.name if profile.class_group_id else "",
    }
    target_id = profile.id
    profile.delete()
    user.delete()
    _shared_services.write_audit(
        request,
        "student.delete",
        school=request.user.school,
        target_type="student_profile",
        target_id=target_id,
        detail=detail,
    )
