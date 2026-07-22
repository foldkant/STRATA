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

# Classroom domain services extracted from api.services.
from . import services as _shared_services
from .services import (
    ServiceError,
    _call_teacher_chat_json,
    _fullmatch,
    _teacher_class_groups,
    write_audit,
)

def _clean_ai_generated_evaluation_criteria(
    raw_items, *, fallback_prefix: str
) -> list[dict]:
    if not isinstance(raw_items, list):
        return []
    cleaned: list[dict] = []
    seen_titles = set()
    for index, raw_item in enumerate(raw_items[:8], start=1):
        if not isinstance(raw_item, dict):
            continue
        title = normalize_text(str(raw_item.get("title") or raw_item.get("name") or ""))
        description = normalize_text(
            str(raw_item.get("description") or raw_item.get("detail") or "")
        )
        if not title:
            title = f"{fallback_prefix}{index}"
        title = title[:80]
        if title in seen_titles:
            continue
        seen_titles.add(title)
        cleaned.append(
            {
                "id": f"crit_{uuid4().hex[:10]}",
                "title": title,
                "description": description[:300],
                "sort_order": index * 10,
            }
        )
    return cleaned


def generate_classroom_evaluation_criteria_with_ai(
    request, session: ClassroomSession | None, data, *, course: Course | None = None
) -> dict:
    raw_types = data.get("types") if isinstance(data, dict) else None
    if not isinstance(raw_types, list) or not raw_types:
        raw_types = list(CLASSROOM_EVALUATION_TYPES)
    types = [
        str(item).strip()
        for item in raw_types
        if str(item).strip() in CLASSROOM_EVALUATION_TYPES
    ]
    if not types:
        raise ServiceError(
            "请选择要生成的评价类型。",
            errors={"types": ["请选择自评、互评或师评。"]},
            status=400,
        )

    direction = (
        str(data.get("direction") or "").strip() if isinstance(data, dict) else ""
    )
    if len(direction) > 1000:
        raise ServiceError(
            "评价生成方向不能超过 1000 个字符。",
            errors={"direction": ["评价生成方向不能超过 1000 个字符。"]},
            status=400,
        )

    course = course or (session.course if session is not None else None)
    if course is None:
        raise ServiceError("课程不存在，无法生成评价项。", status=404)

    step = (
        session.current_step
        if session is not None and session.current_step_id
        else None
    )
    questions = []
    if step and isinstance(step.question_items, list):
        for item in step.question_items[:8]:
            if isinstance(item, dict):
                questions.append(
                    {
                        "type": item.get("question_type"),
                        "stem": str(item.get("stem") or "")[:160],
                        "target_layer": item.get("target_layer", "all"),
                    }
                )
    resources = []
    if step and isinstance(step.resource_items, list):
        for item in step.resource_items[:8]:
            if isinstance(item, dict):
                resources.append(
                    str(item.get("title") or item.get("attachment_name") or "")[:120]
                )
            else:
                resources.append(str(item)[:120])

    type_labels = {"self": "学生自评", "peer": "小组互评", "teacher": "教师评价"}
    system_prompt = (
        "你是 STRATA 数智教学系统的课堂评价设计助手。"
        "请根据课堂内容设计 5 星评价项，不能使用分数、权重或百分制。"
        "只返回 JSON 对象，不要 Markdown。"
    )
    user_prompt = json.dumps(
        {
            "任务": "生成课堂评价项",
            "要求": [
                "每种评价类型生成 3-5 个评价项。",
                "每个评价项包含 title 和 description。",
                "评价方式固定为 1-5 星，不要出现分数、满分、扣分、权重等表达。",
                "自评关注个人投入、理解、完成情况和反思。",
                "互评关注小组协作、贡献、沟通和支持，只有小组活动时使用。",
                "师评关注任务达成、学习过程、作品质量和课堂表现。",
                "语言简洁，适合高中课堂即时评价。",
            ],
            "需要生成": [{"type": item, "label": type_labels[item]} for item in types],
            "教师补充方向": direction,
            "课堂": {
                "title": session.title if session is not None else course.title,
                "course": course.title,
                "lesson": (
                    session.lesson.title
                    if session is not None and session.lesson_id
                    else ""
                ),
                "class": (
                    session.class_group.name
                    if session is not None and session.class_group_id
                    else ""
                ),
                "current_step": step.title if step else "",
                "student_instruction": step.student_instruction[:800] if step else "",
                "step_type": step.get_step_type_display() if step else "",
                "resources": resources,
                "questions": questions,
                "activities": (
                    step.activity_items[:8]
                    if step and isinstance(step.activity_items, list)
                    else []
                ),
            },
            "返回格式": {
                "self": [{"title": "自评项", "description": "5星观察说明"}],
                "peer": [{"title": "互评项", "description": "5星观察说明"}],
                "teacher": [{"title": "师评项", "description": "5星观察说明"}],
            },
        },
        ensure_ascii=False,
    )
    result = _shared_services._call_teacher_chat_json(
        request, system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=2200
    )
    payload = {}
    fallback_prefix = {"self": "自评维度", "peer": "互评维度", "teacher": "师评维度"}
    for item in types:
        payload[item] = _clean_ai_generated_evaluation_criteria(
            result.get(item), fallback_prefix=fallback_prefix[item]
        )
    if not any(payload.values()):
        raise ServiceError(
            "AI 没有返回有效评价项，请调整方向后重试。",
            errors={"ai": ["未生成有效评价项。"]},
            status=400,
        )

    _shared_services.write_audit(
        request,
        (
            "teacher.ai_generate_classroom_evaluation"
            if session is not None
            else "teacher.ai_generate_course_evaluation"
        ),
        school=request.user.school,
        target_type="classroom_session" if session is not None else "course",
        target_id=session.id if session is not None else course.id,
        detail={"types": types, "has_direction": bool(direction)},
    )
    return payload


def _teacher_course(request, course_id) -> Course:
    try:
        course = (
            Course.objects.select_related("subject", "teacher")
            .filter(
                pk=int(course_id),
                teacher=request.user,
                teacher__school=request.user.school,
            )
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
            Lesson.objects.select_related(
                "course", "course__subject", "course__teacher"
            )
            .filter(
                pk=int(lesson_id),
                course__teacher=request.user,
                course__teacher__school=request.user.school,
            )
            .first()
        )
    except (TypeError, ValueError):
        lesson = None
    if lesson is None:
        raise ServiceError("课时不存在或无权操作。", status=404)
    return lesson


def _write_classroom_event(
    request,
    session: ClassroomSession,
    *,
    action: str,
    activity: ClassroomActivity | None = None,
    step: LessonStep | None = None,
) -> None:
    try:
        record_classroom_control_executed(
            teacher=request.user,
            session=session,
            action=action,
            activity=activity,
            step=step,
        )
    except EventWriteError as exc:
        raise ServiceError(exc.message, status=500) from exc


def _classroom_session_step(session: ClassroomSession, step_id) -> LessonStep:
    if not session.lesson_id:
        raise ServiceError("当前课堂未绑定课时，不能投放学习环节。", status=400)
    try:
        step = LessonStep.objects.filter(
            pk=int(step_id), lesson=session.lesson, status=LessonStep.Status.READY
        ).first()
    except (TypeError, ValueError):
        step = None
    if step is None:
        raise ServiceError("环节不存在、未配置，或不属于当前课堂课时。", status=404)
    return step


@transaction.atomic
def set_classroom_current_step(
    request, session: ClassroomSession, data
) -> ClassroomSession:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("请先开始课堂，再投放课时环节。", status=400)
    step = _classroom_session_step(session, data.get("step_id"))
    now = timezone.now()
    previous_step = session.current_step if session.current_step_id else None
    if (
        previous_step
        and session.current_step_status != ClassroomSession.StepStatus.CLOSED
    ):
        try:
            withdraw_classroom_step_opportunities(
                session=session,
                step=previous_step,
                actor=request.user,
                reason_code="classroom_step_replaced",
                occurred_at=now,
            )
        except ClassroomEventError as exc:
            raise ServiceError(exc.message, status=400) from exc
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
    try:
        release_classroom_step_opportunities(
            session=session,
            actor=request.user,
            occurred_at=now,
        )
    except ClassroomEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    _write_classroom_event(request, session, action="step_opened", step=step)
    _shared_services.write_audit(
        request,
        "classroom.step.open",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"session": session.id, "step": step.id, "step_title": step.title},
    )
    return session


@transaction.atomic
def lock_classroom_current_step(request, session: ClassroomSession) -> ClassroomSession:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("只有进行中的课堂可以锁定提交。", status=400)
    if not session.current_step_id:
        raise ServiceError("请先投放一个环节。", status=400)
    session.current_step_status = ClassroomSession.StepStatus.LOCKED
    session.submission_locked = True
    session.save(
        update_fields=["current_step_status", "submission_locked", "updated_at"]
    )
    _write_classroom_event(
        request, session, action="step_locked", step=session.current_step
    )
    _shared_services.write_audit(
        request,
        "classroom.step.lock",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"session": session.id, "step": session.current_step_id},
    )
    return session


@transaction.atomic
def close_classroom_current_step(
    request, session: ClassroomSession
) -> ClassroomSession:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("只有进行中的课堂可以关闭当前环节。", status=400)
    if not session.current_step_id:
        raise ServiceError("请先投放一个环节。", status=400)
    session.current_step_status = ClassroomSession.StepStatus.CLOSED
    session.submission_locked = True
    session.current_step_closed_at = timezone.now()
    session.save(
        update_fields=[
            "current_step_status",
            "submission_locked",
            "current_step_closed_at",
            "updated_at",
        ]
    )
    try:
        withdraw_classroom_step_opportunities(
            session=session,
            step=session.current_step,
            actor=request.user,
            reason_code="classroom_step_closed",
            occurred_at=session.current_step_closed_at,
        )
    except ClassroomEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    _write_classroom_event(
        request, session, action="step_closed", step=session.current_step
    )
    _shared_services.write_audit(
        request,
        "classroom.step.close",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"session": session.id, "step": session.current_step_id},
    )
    return session


def _latest_open_activity(
    session: ClassroomSession, command: str
) -> ClassroomActivity | None:
    return (
        session.activities.filter(
            status=ClassroomActivity.Status.OPEN, metadata__command=command
        )
        .order_by("-opened_at", "-created_at")
        .first()
    )

def _command_random_pick_payload(
    session: ClassroomSession, picked_user_id=None
) -> dict:
    profiles = (
        StudentProfile.objects.select_related("user")
        .filter(class_group=session.class_group, user__is_active=True)
        .order_by("user__display_name", "user__username")
    )
    rows = list(profiles)
    if not rows:
        raise ServiceError("当前班级没有可点名学生。", status=400)
    profile = None
    try:
        picked_user_id = int(picked_user_id)
    except (TypeError, ValueError):
        picked_user_id = 0
    if picked_user_id:
        profile = next((item for item in rows if item.user_id == picked_user_id), None)
        if profile is None:
            raise ServiceError("被点名学生不属于当前班级。", status=400)
    if profile is None:
        seed = timezone.now().timestamp()
        index = int(seed * 1000) % len(rows)
        profile = rows[index]
    return {
        "picked_student": {
            "id": profile.id,
            "user_id": profile.user_id,
            "username": profile.user.username,
            "display_name": profile.user.display_name or profile.user.username,
            "student_no": profile.student_no,
        }
    }


@transaction.atomic
def run_classroom_command(
    request, session: ClassroomSession, data
) -> ClassroomActivity:
    command = str(data.get("command") or "").strip()
    config = CLASSROOM_COMMANDS.get(command)
    if not config:
        raise ServiceError(
            "课堂指令不正确。",
            errors={"command": ["请选择有效的课堂指令。"]},
            status=400,
        )
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("请先开始课堂，再使用课堂控制。", status=400)

    metadata = {"command": command}
    content = str(data.get("content") or "").strip()
    title = str(data.get("title") or config["title"]).strip() or config["title"]

    if command == "timer":
        try:
            duration_seconds = int(data.get("duration_seconds") or 300)
        except (TypeError, ValueError):
            duration_seconds = 300
        duration_seconds = min(max(duration_seconds, 1), 7200)
        metadata["duration_seconds"] = duration_seconds
        metadata["deadline_at"] = (
            timezone.now() + timedelta(seconds=duration_seconds)
        ).isoformat()
        content = (
            content
            or f"倒计时 {duration_seconds // 60} 分 {duration_seconds % 60} 秒。"
        )
    elif command == "broadcast":
        if len(content) < 1 or len(content) > 1000:
            raise ServiceError(
                "广播内容需为 1-1000 个字符。",
                errors={"content": ["请填写广播内容。"]},
                status=400,
            )
    elif command == "random_pick":
        metadata["selection_method"] = (
            "client_draw"
            if data.get("picked_user_id") not in {None, ""}
            else "server_random"
        )
        metadata.update(
            _command_random_pick_payload(session, data.get("picked_user_id"))
        )
        metadata["score_defaults"] = {"plus": 2, "minus": -1}
        metadata["ai_feature"] = "random_pick_score"
        picked = metadata["picked_student"]["display_name"]
        content = content or f"随机点名：{picked}"
    elif command == "sign_in":
        content = content or "请完成课堂签到。"
    elif command == "quick_answer":
        metadata["score_defaults"] = {"plus": 2, "minus": -1}
        metadata["ai_feature"] = "quick_answer_score"
        content = content or "抢答已开启。"

    reusable = command in {"sign_in", "quick_answer", "timer"}
    activity = _latest_open_activity(session, command) if reusable else None
    if activity is None:
        activity = ClassroomActivity(
            session=session, activity_type=config["activity_type"]
        )
    if command in {"random_pick", "broadcast"}:
        now = timezone.now()
        session.activities.filter(
            status=ClassroomActivity.Status.OPEN, metadata__command=command
        ).update(
            status=ClassroomActivity.Status.CLOSED,
            closed_at=now,
            updated_at=now,
        )
    activity.activity_type = config["activity_type"]
    activity.title = title[:128]
    activity.content = content[:5000]
    activity.metadata = metadata
    activity.status = ClassroomActivity.Status.OPEN
    activity.opened_at = timezone.now()
    activity.closed_at = None
    activity.save()
    try:
        release_attendance_opportunities(
            activity=activity,
            actor=request.user,
            occurred_at=activity.opened_at,
        )
    except AttendanceEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    try:
        release_quick_answer_opportunities(
            activity=activity,
            actor=request.user,
            occurred_at=activity.opened_at,
        )
        record_random_call_selected(
            activity=activity,
            actor=request.user,
            selection_method=str(metadata.get("selection_method") or "server_random"),
        )
    except ClassroomInteractionEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    _write_classroom_event(
        request, session, action=f"command_{command}", activity=activity
    )
    _shared_services.write_audit(
        request,
        "classroom.command",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=activity.id,
        detail={"session": session.id, "command": command, "title": activity.title},
    )
    return activity


def save_classroom_session(
    request, data, *, session: ClassroomSession | None = None
) -> ClassroomSession:
    errors: dict[str, list[str]] = {}
    course = _teacher_course(request, data.get("course"))
    raw_lesson = data.get("lesson")
    lesson = None
    if raw_lesson not in {None, ""}:
        lesson = _teacher_lesson(request, raw_lesson)
        if lesson.course_id != course.id:
            errors["lesson"] = ["课时必须属于所选课程。"]
    classes = _teacher_class_groups(
        request,
        [data.get("class_group")],
        errors,
        field="class_group",
        allow_empty=False,
    )
    class_group = classes[0] if classes else None
    title = str(data.get("title", "")).strip()
    if not title and course and class_group:
        title = f"{lesson.title if lesson else course.title} - {class_group.name}"

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["课堂标题需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if (
        course
        and class_group
        and not CourseClass.objects.filter(
            course=course, class_group=class_group
        ).exists()
    ):
        errors["class_group"] = [
            "该课程尚未绑定所选班级，请先在课程管理中设置班级范围。"
        ]
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
    if session.current_step_id and (
        lesson is None or session.current_step.lesson_id != lesson.id
    ):
        session.current_step = None
        session.current_step_status = ClassroomSession.StepStatus.IDLE
        session.submission_locked = False
        session.current_step_started_at = None
        session.current_step_closed_at = None
    session.save()
    _shared_services.write_audit(
        request,
        "classroom.session.create" if is_create else "classroom.session.update",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={
            "title": session.title,
            "course": course.id,
            "class_group": class_group.id,
        },
    )
    return session


@transaction.atomic
def start_classroom_session(request, session: ClassroomSession) -> ClassroomSession:
    if session.status == ClassroomSession.Status.FINISHED:
        raise ServiceError("已结束课堂不能重新开始。", status=400)
    was_running = session.status == ClassroomSession.Status.RUNNING
    session.status = ClassroomSession.Status.RUNNING
    if not session.current_step_id:
        session.current_step_status = ClassroomSession.StepStatus.IDLE
        session.submission_locked = False
    if not was_running:
        session.evaluation_enabled = False
        session.evaluation_opened_at = None
    session.started_at = session.started_at or timezone.now()
    session.finished_at = None
    session.save(
        update_fields=[
            "status",
            "current_step_status",
            "submission_locked",
            "evaluation_enabled",
            "evaluation_opened_at",
            "started_at",
            "finished_at",
            "updated_at",
        ]
    )
    _write_classroom_event(request, session, action="session_started")
    _shared_services.write_audit(
        request,
        "classroom.session.start",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"title": session.title},
    )
    return session


@transaction.atomic
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
    session.evaluation_enabled = False
    session.evaluation_opened_at = None
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
            "evaluation_enabled",
            "evaluation_opened_at",
            "started_at",
            "finished_at",
            "updated_at",
        ]
    )
    _write_classroom_event(request, session, action="session_restarted")
    _shared_services.write_audit(
        request,
        "classroom.session.restart",
        school=request.user.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={"title": session.title},
    )
    return session


@transaction.atomic
def finish_classroom_session(request, session: ClassroomSession) -> ClassroomSession:
    evaluation_was_enabled = session.evaluation_enabled
    session.status = ClassroomSession.Status.FINISHED
    session.evaluation_enabled = False
    session.finished_at = timezone.now()
    if (
        session.current_step_id
        and session.current_step_status != ClassroomSession.StepStatus.CLOSED
    ):
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
            "evaluation_enabled",
            "current_step_closed_at",
            "finished_at",
            "updated_at",
        ]
    )
    if session.current_step_id:
        try:
            withdraw_classroom_step_opportunities(
                session=session,
                step=session.current_step,
                actor=request.user,
                reason_code="classroom_finished",
                occurred_at=session.finished_at,
            )
        except ClassroomEventError as exc:
            raise ServiceError(exc.message, status=400) from exc
    try:
        withdraw_attendance_opportunities(
            session=session,
            actor=request.user,
            reason_code="classroom_finished",
            occurred_at=session.finished_at,
        )
    except AttendanceEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    try:
        withdraw_quick_answer_opportunities(
            session=session,
            actor=request.user,
            reason_code="classroom_finished",
            occurred_at=session.finished_at,
        )
    except ClassroomInteractionEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    if (
        evaluation_was_enabled
        or session.evaluation_config_version_id
        or hasattr(session, "evaluation_standard_use")
    ):
        try:
            withdraw_classroom_evaluation_opportunities(
                session=session,
                actor=request.user,
                reason_code="classroom_finished",
                occurred_at=session.finished_at,
            )
        except EvaluationEventError as exc:
            raise ServiceError(exc.message, status=400) from exc
    collaboration = (
        ClassroomGroupCollaboration.objects.select_for_update()
        .filter(session=session)
        .first()
    )
    if collaboration:
        try:
            withdraw_group_collaboration_opportunities(
                collaboration=collaboration,
                actor=request.user,
                reason_code="classroom_finished",
                occurred_at=session.finished_at,
            )
        except GroupCollaborationEventError as exc:
            raise ServiceError(exc.message, status=400) from exc
        collaboration.is_enabled = False
        collaboration.status = ClassroomGroupCollaboration.Status.CLOSED
        collaboration.closed_at = session.finished_at
        collaboration.save(
            update_fields=["is_enabled", "status", "closed_at", "updated_at"]
        )
    _write_classroom_event(request, session, action="session_finished")
    _shared_services.write_audit(
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
        raise ServiceError(
            "只有未开始课堂可以删除；进行中或已结束课堂请保留记录。", status=400
        )
    detail = {"title": session.title}
    target_id = session.id
    session.delete()
    _shared_services.write_audit(
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
    activity_type = str(
        data.get("activity_type", ClassroomActivity.ActivityType.QUESTION)
    ).strip()
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
    if not isinstance(activity.metadata, dict):
        activity.metadata = {}
    activity.save()
    _shared_services.write_audit(
        request,
        "classroom.activity.create" if is_create else "classroom.activity.update",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=activity.id,
        detail={
            "session": session.id,
            "type": activity.activity_type,
            "title": activity.title,
        },
    )
    return activity


@transaction.atomic
def open_classroom_activity(request, activity: ClassroomActivity) -> ClassroomActivity:
    session = activity.session
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("请先开始课堂，再开启课堂活动。", status=400)
    activity.status = ClassroomActivity.Status.OPEN
    activity.opened_at = timezone.now()
    activity.closed_at = None
    activity.save(update_fields=["status", "opened_at", "closed_at", "updated_at"])
    try:
        release_attendance_opportunities(
            activity=activity,
            actor=request.user,
            occurred_at=activity.opened_at,
        )
    except AttendanceEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    try:
        release_quick_answer_opportunities(
            activity=activity,
            actor=request.user,
            occurred_at=activity.opened_at,
        )
    except ClassroomInteractionEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    _write_classroom_event(
        request, session, action="activity_opened", activity=activity
    )
    _shared_services.write_audit(
        request,
        "classroom.activity.open",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=activity.id,
        detail={
            "session": session.id,
            "type": activity.activity_type,
            "title": activity.title,
        },
    )
    return activity


@transaction.atomic
def close_classroom_activity(request, activity: ClassroomActivity) -> ClassroomActivity:
    activity.status = ClassroomActivity.Status.CLOSED
    activity.closed_at = timezone.now()
    activity.save(update_fields=["status", "closed_at", "updated_at"])
    try:
        withdraw_quick_answer_opportunities(
            session=activity.session,
            activity=activity,
            actor=request.user,
            reason_code="classroom_activity_closed",
            occurred_at=activity.closed_at,
        )
    except ClassroomInteractionEventError as exc:
        raise ServiceError(exc.message, status=400) from exc
    _write_classroom_event(
        request, activity.session, action="activity_closed", activity=activity
    )
    _shared_services.write_audit(
        request,
        "classroom.activity.close",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=activity.id,
        detail={
            "session": activity.session_id,
            "type": activity.activity_type,
            "title": activity.title,
        },
    )
    return activity


def delete_classroom_activity(request, activity: ClassroomActivity) -> None:
    if activity.status == ClassroomActivity.Status.OPEN:
        raise ServiceError("进行中的课堂活动不能删除，请先关闭。", status=400)
    if (
        activity.opened_at
        or LearningEvent.objects.filter(
            object_type="classroom_activity", object_id=str(activity.id)
        ).exists()
    ):
        raise ServiceError(
            "已开启或已有课堂记录的活动必须保留，不能物理删除。", status=409
        )
    detail = {
        "session": activity.session_id,
        "title": activity.title,
        "type": activity.activity_type,
    }
    target_id = activity.id
    activity.delete()
    _shared_services.write_audit(
        request,
        "classroom.activity.delete",
        school=request.user.school,
        target_type="classroom_activity",
        target_id=target_id,
        detail=detail,
    )
