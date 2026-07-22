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

# Resources domain services extracted from api.services.
from . import services as _shared_services
from .services import (
    ServiceError,
    _clean_bool,
    _fullmatch,
    _teacher_class_groups,
    _validate_course_cover,
    write_audit,
)

def _validate_resource_file(uploaded_file) -> None:
    if uploaded_file is None:
        return
    if uploaded_file.size > RESOURCE_MAX_SIZE:
        raise ServiceError(
            "资源文件不能超过 512MB。",
            errors={"attachment": ["资源文件不能超过 512MB。"]},
            status=400,
        )
    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix not in RESOURCE_ALLOWED_EXTENSIONS:
        raise ServiceError(
            "暂不支持该资源格式。",
            errors={
                "attachment": [
                    "支持图片、音视频、PDF、Office 文档、文本、表格和压缩包。"
                ]
            },
            status=400,
        )


def _resource_list_value(data, field: str) -> list:
    raw_value = data.get(field, []) if hasattr(data, "get") else []
    if raw_value in (None, ""):
        return []
    if isinstance(raw_value, list):
        return raw_value
    if isinstance(raw_value, tuple):
        return list(raw_value)
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = [item.strip() for item in raw_value.split(",") if item.strip()]
        return parsed if isinstance(parsed, list) else []
    return []


def _clean_resource_text_list(
    data, field: str, errors: dict, *, max_items: int, max_length: int
) -> list[str]:
    values: list[str] = []
    for raw_value in _resource_list_value(data, field):
        value = str(raw_value or "").strip()
        if not value or value in values:
            continue
        if len(value) > max_length:
            errors[field] = [f"每项不能超过 {max_length} 个字符。"]
            continue
        values.append(value)
    if len(values) > max_items:
        errors[field] = [f"最多填写 {max_items} 项。"]
        return values[:max_items]
    return values


def _clean_resource_class_ids(data, errors: dict) -> list[int]:
    values: list[int] = []
    for raw_value in _resource_list_value(data, "class_ids"):
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            errors["class_ids"] = ["班级范围包含无效编号。"]
            continue
        if value > 0 and value not in values:
            values.append(value)
    return values


@transaction.atomic
def save_teacher_resource(
    request,
    data,
    *,
    resource: Resource | None = None,
    uploaded_file=None,
    cover_file=None,
    extra_files=None,
) -> Resource:
    errors: dict[str, list[str]] = {}
    fallback_title = Path(getattr(uploaded_file, "name", "") or "").stem
    title = str(data.get("title", "") or fallback_title).strip()
    content = str(data.get("content", "")).strip()
    is_pinned = _clean_bool(
        data.get("is_pinned", resource.is_pinned if resource else False)
    )
    resource_type = str(
        data.get(
            "resource_type",
            resource.resource_type if resource else Resource.ResourceType.FILE,
        )
    ).strip()
    category = str(
        data.get(
            "category", resource.category if resource else Resource.Category.COURSEWARE
        )
    ).strip()
    visibility = str(
        data.get(
            "visibility",
            resource.visibility if resource else Resource.Visibility.PRIVATE,
        )
    ).strip()
    grade_scope = str(
        data.get("grade_scope", resource.grade_scope if resource else "")
    ).strip()
    external_url = str(
        data.get("external_url", resource.external_url if resource else "")
    ).strip()
    project_type = str(
        data.get("project_type", resource.project_type if resource else "")
    ).strip()
    project_course = str(
        data.get("project_course", resource.project_course if resource else "")
    ).strip()
    competition_name = str(
        data.get("competition_name", resource.competition_name if resource else "")
    ).strip()
    award_level = str(
        data.get("award_level", resource.award_level if resource else "")
    ).strip()
    tags = _clean_resource_text_list(data, "tags", errors, max_items=12, max_length=24)
    project_members = _clean_resource_text_list(
        data, "project_members", errors, max_items=30, max_length=64
    )
    class_ids = _clean_resource_class_ids(data, errors)
    subject = None
    subject_id = data.get("subject", resource.subject_id if resource else None)
    if subject_id not in (None, ""):
        try:
            subject = Subject.objects.filter(
                pk=int(subject_id), school=request.user.school, is_active=True
            ).first()
        except (TypeError, ValueError):
            subject = None
        if subject is None:
            errors["subject"] = ["请选择本校有效学科。"]

    competition_year = None
    raw_competition_year = data.get(
        "competition_year", resource.competition_year if resource else None
    )
    if raw_competition_year not in (None, ""):
        try:
            competition_year = int(raw_competition_year)
        except (TypeError, ValueError):
            errors["competition_year"] = ["比赛年份格式不正确。"]
        else:
            if (
                competition_year < 2000
                or competition_year > timezone.localdate().year + 1
            ):
                errors["competition_year"] = ["比赛年份超出有效范围。"]

    if not _fullmatch(RESOURCE_TITLE_PATTERN, title):
        errors["title"] = [
            "资源标题需为 2-128 位，可包含中文、字母、数字、下划线和常用标点。"
        ]
    if len(content) > 5000:
        errors["content"] = ["资源说明不能超过 5000 个字符。"]
    try:
        _validate_resource_file(uploaded_file)
    except ServiceError as exc:
        errors.update(exc.errors)

    normalized_extra_files = list(extra_files or [])
    for extra_file in normalized_extra_files:
        try:
            _validate_resource_file(extra_file)
        except ServiceError as exc:
            errors["extra_files"] = exc.errors.get(
                "attachment", ["补充附件格式不正确。"]
            )
            break
    if cover_file is not None:
        try:
            _validate_course_cover(cover_file)
        except ServiceError as exc:
            errors["cover"] = exc.errors.get("cover", ["封面文件不正确。"])

    if resource_type not in Resource.ResourceType.values:
        errors["resource_type"] = ["资源类型不正确。"]
    if category not in Resource.Category.values:
        errors["category"] = ["资源分类不正确。"]
    if visibility not in Resource.Visibility.values:
        errors["visibility"] = ["共享范围不正确。"]
    if len(grade_scope) > 128:
        errors["grade_scope"] = ["适用年级不能超过 128 个字符。"]
    if (
        len(project_course) > 128
        or len(competition_name) > 128
        or len(award_level) > 128
    ):
        errors["project"] = ["学生项目信息不能超过 128 个字符。"]
    if external_url:
        parsed_url = urlparse(external_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            errors["external_url"] = ["外部链接必须是有效的 HTTP 或 HTTPS 地址。"]

    has_existing_file = bool(resource and resource.attachment)
    if (
        resource_type == Resource.ResourceType.FILE
        and uploaded_file is None
        and not has_existing_file
    ):
        errors["attachment"] = ["文件资源需要上传主文件。"]
    if resource_type == Resource.ResourceType.ARTICLE and not content:
        errors["content"] = ["图文内容需要填写正文。"]
    if resource_type == Resource.ResourceType.LINK and not external_url:
        errors["external_url"] = ["链接资源需要填写外部链接。"]
    if resource_type == Resource.ResourceType.STUDENT_PROJECT:
        category = Resource.Category.PROJECT
        if project_type not in Resource.ProjectType.values:
            errors["project_type"] = ["请选择个人项目或小组项目。"]
        if not project_members:
            errors["project_members"] = ["请至少填写一名项目成员。"]
        if (
            uploaded_file is None
            and not has_existing_file
            and not content
            and not external_url
        ):
            errors["attachment"] = ["学生项目需要项目说明、成果文件或项目链接。"]

    class_groups: list[ClassGroup] = []
    if visibility == Resource.Visibility.CLASSES:
        if not class_ids:
            errors["class_ids"] = ["请至少选择一个任教班级。"]
        else:
            class_groups = _teacher_class_groups(
                request, class_ids, errors, field="class_ids", allow_empty=False
            )

    if resource is None and uploaded_file is None and not content and not external_url:
        errors["attachment"] = ["请上传资源文件，或填写正文、项目说明或外部链接。"]

    if errors:
        raise ServiceError("资源信息校验失败。", errors=errors, status=400)

    is_create = resource is None
    if resource is None:
        resource = Resource(owner=request.user)
    resource.title = title
    resource.content = content
    resource.is_pinned = is_pinned
    resource.resource_type = resource_type
    resource.category = category
    resource.visibility = visibility
    resource.subject = subject
    resource.grade_scope = grade_scope
    resource.tags = tags
    resource.external_url = external_url
    resource.project_type = (
        project_type if resource_type == Resource.ResourceType.STUDENT_PROJECT else ""
    )
    resource.project_members = (
        project_members
        if resource_type == Resource.ResourceType.STUDENT_PROJECT
        else []
    )
    resource.project_course = (
        project_course if resource_type == Resource.ResourceType.STUDENT_PROJECT else ""
    )
    resource.competition_name = (
        competition_name
        if resource_type == Resource.ResourceType.STUDENT_PROJECT
        else ""
    )
    resource.competition_year = (
        competition_year
        if resource_type == Resource.ResourceType.STUDENT_PROJECT
        else None
    )
    resource.award_level = (
        award_level if resource_type == Resource.ResourceType.STUDENT_PROJECT else ""
    )
    if visibility == Resource.Visibility.PRIVATE:
        resource.publish_status = Resource.PublishStatus.PUBLISHED
        resource.published_at = timezone.now()
    elif visibility == Resource.Visibility.EXTERNAL:
        resource.publish_status = Resource.PublishStatus.PENDING
        resource.review_note = ""
        resource.reviewed_by = None
        resource.reviewed_at = None
        resource.published_at = None
    else:
        resource.publish_status = Resource.PublishStatus.PUBLISHED
        resource.published_at = timezone.now()
    if uploaded_file is not None:
        if resource.attachment:
            resource.attachment.delete(save=False)
        resource.attachment = uploaded_file
    if cover_file is not None:
        if resource.cover:
            resource.cover.delete(save=False)
        resource.cover = cover_file
    resource.save()
    resource.target_classes.set(
        class_groups if visibility == Resource.Visibility.CLASSES else []
    )
    start_order = (
        resource.extra_files.aggregate(max_order=Max("sort_order"))["max_order"] or 0
    )
    for offset, extra_file in enumerate(normalized_extra_files, start=1):
        ResourceFile.objects.create(
            resource=resource,
            file=extra_file,
            original_name=str(getattr(extra_file, "name", "") or "附件")[:255],
            file_ext=Path(getattr(extra_file, "name", "") or "")
            .suffix.lower()
            .lstrip(".")[:16],
            file_size=max(int(getattr(extra_file, "size", 0) or 0), 0),
            role=(
                ResourceFile.Role.PROCESS
                if resource_type == Resource.ResourceType.STUDENT_PROJECT
                else ResourceFile.Role.SUPPLEMENT
            ),
            sort_order=start_order + offset,
        )

    _shared_services.write_audit(
        request,
        "resource.create" if is_create else "resource.update",
        school=request.user.school,
        target_type="resource",
        target_id=resource.id,
        detail={
            "title": resource.title,
            "filename": getattr(uploaded_file, "name", "") if uploaded_file else "",
            "has_attachment": bool(resource.attachment),
            "resource_type": resource.resource_type,
            "visibility": resource.visibility,
            "publish_status": resource.publish_status,
            "extra_file_count": len(normalized_extra_files),
        },
    )
    return resource


def delete_teacher_resource(request, resource: Resource) -> None:
    detail = {
        "title": resource.title,
        "filename": resource.attachment.name if resource.attachment else "",
    }
    target_id = resource.id
    for extra_file in resource.extra_files.all():
        if extra_file.file:
            extra_file.file.delete(save=False)
    if resource.cover:
        resource.cover.delete(save=False)
    if resource.attachment:
        resource.attachment.delete(save=False)
    resource.delete()
    _shared_services.write_audit(
        request,
        "resource.delete",
        school=request.user.school,
        target_type="resource",
        target_id=target_id,
        detail=detail,
    )
