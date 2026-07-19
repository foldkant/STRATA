from __future__ import annotations

from django.db.models import Prefetch, Q, Sum

from accounts.models import User
from aiops.models import TeacherAIProvider
from courses.models import (
    ClassroomActivity,
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupFile,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    LearningWebPage,
    LearningWebPageResponse,
    LearningWebPageVersion,
    Lesson,
    LessonStep,
    Resource,
    Subject,
)
from learning.models import (
    Feedback,
    LearningEvent,
    Notice,
    PretestPaper,
    PretestQuestion,
    StudentWorkAttachment,
)
from learning_analytics.privacy import sanitize_student_payload
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment

from .protected_files import protected_file_url

KNOWN_RESOURCE_EXTS = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "bmp",
    "mp4",
    "webm",
    "ogg",
    "mov",
    "mp3",
    "wav",
    "m4a",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "csv",
    "txt",
    "md",
    "zip",
    "rar",
    "7z",
}

DEFAULT_LESSON_FILE_EXTENSIONS = [
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


def clean_resource_ext(*values) -> str:
    for value in values:
        text = str(value or "").strip().lower().split("?", 1)[0].split("#", 1)[0]
        if "." in text:
            text = text.rsplit(".", 1)[-1]
        text = text.lstrip(".")
        text = "".join(ch for ch in text if ch.isalnum())
        if text in KNOWN_RESOURCE_EXTS:
            return text
    return ""


def school_summary(school: School | None) -> dict | None:
    if school is None:
        return None
    return {"id": school.id, "name": school.name, "code": school.code}


def user_summary(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "role_label": user.get_role_display(),
        "school": school_summary(user.school),
        "is_active": user.is_active,
        "is_first_login": user.is_first_login,
    }


def school_row(school: School) -> dict:
    return {
        "id": school.id,
        "name": school.name,
        "code": school.code,
        "status": school.status,
        "status_label": school.get_status_display(),
        "contact_name": school.contact_name,
        "contact_phone": school.contact_phone,
        "address": school.address,
        "note": school.note,
        "class_count": getattr(school, "class_count", 0),
        "user_count": getattr(school, "user_count", 0),
        "created_at": school.created_at,
        "updated_at": school.updated_at,
    }


def account_row(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "phone": user.phone,
        "role": user.role,
        "role_label": user.get_role_display(),
        "school": school_summary(user.school),
        "is_active": user.is_active,
        "is_first_login": user.is_first_login,
        "last_login": user.last_login,
        "date_joined": user.date_joined,
    }


def class_group_row(class_group: ClassGroup) -> dict:
    return {
        "id": class_group.id,
        "name": class_group.name,
        "grade": class_group.grade,
        "entry_year": class_group.entry_year,
        "status": class_group.status,
        "status_label": class_group.get_status_display(),
        "student_count": getattr(class_group, "student_count", 0),
        "teacher_count": getattr(class_group, "teacher_count", 0),
        "graduated_at": class_group.graduated_at,
        "created_at": class_group.created_at,
    }


def teaching_assignment_row(assignment: TeachingAssignment) -> dict:
    return {
        "id": assignment.id,
        "class_group": class_group_row(assignment.class_group),
        "teacher": account_row(assignment.teacher),
        "created_at": assignment.created_at,
        "updated_at": assignment.updated_at,
    }


def teaching_teacher_row(teacher, class_groups: list[ClassGroup]) -> dict:
    return {
        "id": teacher.id,
        "teacher": account_row(teacher),
        "classes": [class_group_row(class_group) for class_group in class_groups],
        "class_count": len(class_groups),
    }


def subject_row(subject: Subject) -> dict:
    return {
        "id": subject.id,
        "name": subject.name,
        "code": subject.code,
        "is_active": subject.is_active,
        "course_count": getattr(subject, "course_count", 0),
        "pretest_count": getattr(subject, "pretest_count", 0),
        "created_at": subject.created_at,
        "updated_at": subject.updated_at,
    }


def course_row(course: Course, *, include_lessons: bool = False) -> dict:
    target_classes = []
    course_classes = getattr(course, "prefetched_course_classes", None)
    if course_classes is None:
        course_classes = course.course_classes.select_related("class_group").all()
    for item in course_classes:
        target_classes.append(class_group_row(item.class_group))

    row = {
        "id": course.id,
        "subject": subject_row(course.subject) if course.subject_id else None,
        "title": course.title,
        "introduction": course.introduction,
        "cover_url": (
            protected_file_url("course-cover", course.id) if course.cover else ""
        ),
        "cover_name": course.cover.name.rsplit("/", 1)[-1] if course.cover else "",
        "teaching_model": course.teaching_model,
        "teaching_model_label": course.get_teaching_model_display(),
        "is_active": course.is_active,
        "status": "published" if course.is_active else "draft",
        "status_label": "已发布" if course.is_active else "草稿",
        "target_classes": target_classes,
        "class_count": getattr(course, "class_count", len(target_classes)),
        "lesson_count": getattr(course, "lesson_count", 0),
        "session_count": getattr(course, "session_count", 0),
        "created_at": course.created_at,
        "updated_at": course.updated_at,
    }
    if include_lessons:
        lessons = getattr(course, "prefetched_lessons", None)
        if lessons is None:
            lessons = course.lessons.all()
        row["lessons"] = [lesson_row(lesson) for lesson in lessons]
    return row


def lesson_row(lesson: Lesson) -> dict:
    return {
        "id": lesson.id,
        "course": lesson.course_id,
        "course_title": lesson.course.title if getattr(lesson, "course", None) else "",
        "title": lesson.title,
        "content": lesson.content,
        "sort_order": lesson.sort_order,
        "is_active": lesson.is_active,
        "status": "published" if lesson.is_active else "draft",
        "status_label": "已发布" if lesson.is_active else "草稿",
        "activity_count": getattr(lesson, "activity_count", 0),
        "session_count": getattr(lesson, "session_count", 0),
        "created_at": lesson.created_at,
        "updated_at": lesson.updated_at,
    }


def normalize_resource_item(item) -> dict:
    if isinstance(item, dict):
        attachment_name = str(
            item.get("attachment_name") or item.get("filename") or ""
        ).strip()
        attachment_url = str(
            item.get("attachment_url") or item.get("url") or ""
        ).strip()
        title = str(
            item.get("title") or item.get("name") or attachment_name or attachment_url
        ).strip()
        file_ext = clean_resource_ext(
            item.get("file_ext"), attachment_name, attachment_url, title
        )
        row = {
            "id": item.get("id") or "",
            "title": title,
            "attachment_url": attachment_url,
            "attachment_name": attachment_name,
            "file_ext": file_ext,
            "kind": str(item.get("kind") or "resource").strip(),
            "external_url": str(item.get("external_url") or "").strip(),
            "resource_type": str(item.get("resource_type") or "").strip(),
        }
        if row["kind"] == "learning_page":
            row["learning_page_id"] = item.get("learning_page_id") or ""
            row["revision_no"] = item.get("revision_no") or 1
        return row
    text = str(item or "").strip()
    file_ext = clean_resource_ext(text)
    return {
        "id": "",
        "title": text,
        "attachment_url": "",
        "attachment_name": text,
        "file_ext": file_ext,
        "kind": "legacy",
        "external_url": "",
        "resource_type": "",
    }


def normalize_resource_items(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    rows: list[dict] = []
    seen = set()
    for item in items:
        row = normalize_resource_item(item)
        key = row["id"] or row["attachment_url"] or row["title"]
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def learning_web_page_row(
    page: LearningWebPage, *, include_schema: bool = True
) -> dict:
    schema = page.schema if isinstance(page.schema, dict) else {}
    blocks = schema.get("blocks") if isinstance(schema.get("blocks"), list) else []
    forms = [
        item for item in blocks if isinstance(item, dict) and item.get("type") == "form"
    ]
    row = {
        "id": page.id,
        "school": page.school_id,
        "teacher": user_summary(page.teacher),
        "course": page.course_id,
        "lesson": page.lesson_id,
        "title": page.title,
        "generation_prompt": page.generation_prompt,
        "revision_no": page.revision_no,
        "status": page.status,
        "status_label": page.get_status_display(),
        "is_active": page.is_active,
        "block_count": len(blocks),
        "form_count": len(forms),
        "response_count": getattr(page, "response_count", page.responses.count()),
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }
    if include_schema:
        row["schema"] = schema
    return row


def learning_web_page_version_row(version: LearningWebPageVersion) -> dict:
    return {
        "id": version.id,
        "page": version.page_id,
        "version_no": version.version_no,
        "prompt": version.prompt,
        "schema": version.schema if isinstance(version.schema, dict) else {},
        "created_by": (
            user_summary(version.created_by) if version.created_by_id else None
        ),
        "created_at": version.created_at,
    }


def learning_web_page_response_row(response: LearningWebPageResponse) -> dict:
    return {
        "id": response.id,
        "page": response.page_id,
        "page_version": response.page_version,
        "student": user_summary(response.student),
        "class_group": class_group_row(response.class_group),
        "course": response.course_id,
        "lesson": response.lesson_id,
        "lesson_step": response.lesson_step_id,
        "classroom_session": response.classroom_session_id,
        "form_id": response.form_id,
        "answers": response.answers if isinstance(response.answers, dict) else {},
        "attempt_no": response.attempt_no,
        "submitted_at": response.submitted_at,
    }


LESSON_QUESTION_TYPE_LABELS = {
    "single": "单选",
    "multiple": "多选",
    "judge": "判断",
    "blank": "填空",
    "text": "简答",
    "file": "附件提交",
}

LESSON_TARGET_LAYER_LABELS = {
    "all": "全体",
    "A": "A",
    "B": "B",
    "C": "C",
    "A/B": "A/B",
    "B/C": "B/C",
    "A/B/C": "A/B/C",
}

LESSON_LAYER_CODES = {"A", "B", "C"}


def lesson_target_layer_codes(value: str | None) -> set[str]:
    if not value or value == "all":
        return set(LESSON_LAYER_CODES)
    return {item for item in str(value).split("/") if item in LESSON_LAYER_CODES}


def lesson_target_layer_matches(value: str | None, student_layer: str | None) -> bool:
    if not value or value == "all":
        return True
    if not student_layer:
        return False
    return student_layer in lesson_target_layer_codes(value)


def clean_layer_score_value(value, fallback: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return number if 0 <= number <= 100 else fallback


def normalize_lesson_file_config(value) -> dict:
    config = value if isinstance(value, dict) else {}
    raw_exts = config.get("allowed_extensions")
    if not isinstance(raw_exts, list):
        raw_exts = DEFAULT_LESSON_FILE_EXTENSIONS
    extensions = []
    for item in raw_exts:
        ext = clean_resource_ext(str(item))
        if ext and ext not in extensions:
            extensions.append(ext)
    if not extensions:
        extensions = list(DEFAULT_LESSON_FILE_EXTENSIONS)
    try:
        max_size_mb = int(config.get("max_size_mb", 100) or 100)
    except (TypeError, ValueError):
        max_size_mb = 100
    max_size_mb = min(max(max_size_mb, 1), 512)
    return {
        "allowed_extensions": extensions[:24],
        "max_size_mb": max_size_mb,
    }


def normalize_lesson_question_items(
    items,
    *,
    include_answer: bool = False,
    student_layer: str | None = None,
    apply_layering: bool = False,
) -> list[dict]:
    if not isinstance(items, list):
        return []
    rows = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        question_type = str(item.get("question_type") or "single")
        target_layer = str(item.get("target_layer") or "all")
        if target_layer not in LESSON_TARGET_LAYER_LABELS:
            target_layer = "all"
        if apply_layering and not lesson_target_layer_matches(
            target_layer, student_layer
        ):
            continue
        base_score = clean_layer_score_value(item.get("score", 0), 0)
        raw_layer_scores = (
            item.get("layer_scores")
            if isinstance(item.get("layer_scores"), dict)
            else {}
        )
        layer_scores = {
            layer: clean_layer_score_value(raw_layer_scores.get(layer), base_score)
            for layer in sorted(LESSON_LAYER_CODES)
        }
        score = base_score
        if (
            apply_layering
            and item.get("use_layer_scores")
            and student_layer in LESSON_LAYER_CODES
        ):
            score = layer_scores.get(student_layer, base_score)
        row = {
            "id": item.get("id") or f"q_{index + 1}",
            "question_type": question_type,
            "question_type_label": LESSON_QUESTION_TYPE_LABELS.get(
                question_type, question_type
            ),
            "stem": item.get("stem") or "",
            "options": (
                item.get("options") if isinstance(item.get("options"), list) else []
            ),
            "score": score,
            "is_required": bool(item.get("is_required", True)),
            "sort_order": item.get("sort_order", (index + 1) * 10),
        }
        if question_type == "file":
            row["file_config"] = normalize_lesson_file_config(item.get("file_config"))
        if include_answer:
            row["target_layer"] = target_layer
            row["target_layer_label"] = LESSON_TARGET_LAYER_LABELS.get(
                target_layer, "全体"
            )
            row["use_layer_scores"] = bool(item.get("use_layer_scores", False))
            row["layer_scores"] = layer_scores
            row["answer"] = (
                item.get("answer") if isinstance(item.get("answer"), list) else []
            )
            row["analysis"] = item.get("analysis") or ""
        rows.append(row)
    return sorted(rows, key=lambda row: (row["sort_order"], row["id"]))


def lesson_step_has_layered_questions(step: LessonStep | None) -> bool:
    if step is None:
        return False
    items = step.question_items if isinstance(step.question_items, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        target_layer = str(item.get("target_layer") or "all")
        if target_layer not in {"", "all"}:
            return True
        if item.get("use_layer_scores"):
            return True
    return False


def lesson_step_row(step: LessonStep) -> dict:
    return {
        "id": step.id,
        "lesson": step.lesson_id,
        "title": step.title,
        "step_type": step.step_type,
        "step_type_label": step.get_step_type_display(),
        "student_instruction": step.student_instruction,
        "teacher_note": step.teacher_note,
        "sort_order": step.sort_order,
        "is_required": step.is_required,
        "estimated_minutes": step.estimated_minutes,
        "target_layer": step.target_layer,
        "target_layer_label": step.get_target_layer_display(),
        "status": step.status,
        "status_label": step.get_status_display(),
        "resource_items": normalize_resource_items(step.resource_items),
        "activity_items": (
            step.activity_items if isinstance(step.activity_items, list) else []
        ),
        "question_items": normalize_lesson_question_items(
            step.question_items, include_answer=True
        ),
        "ai_prompt": step.ai_prompt,
        "collect_student_log": step.collect_student_log,
        "collect_class_log": step.collect_class_log,
        "created_at": step.created_at,
        "updated_at": step.updated_at,
    }


def student_profile_summary(profile: StudentProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "id": profile.id,
        "student_no": profile.student_no,
        "class_group": (
            class_group_row(profile.class_group) if profile.class_group_id else None
        ),
        "score": profile.score,
        "is_first_use": profile.is_first_use,
        "onboarding_status": profile.onboarding_status,
        "onboarding_status_label": profile.get_onboarding_status_display(),
        "password_updated_at": profile.password_updated_at,
        "class_selected_at": profile.class_selected_at,
        "pretest_completed_at": profile.pretest_completed_at,
    }


def teacher_student_profile_summary(profile: StudentProfile | None) -> dict | None:
    row = student_profile_summary(profile)
    if row is None:
        return None
    return {
        **row,
        "current_layer": profile.current_layer,
        "current_layer_label": (
            profile.get_current_layer_display() if profile.current_layer else ""
        ),
        "current_group_no": profile.current_group_no,
    }


def student_teacher_row(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
    }


def student_course_row(course: Course, *, pretest_status: dict | None = None) -> dict:
    return {
        "id": course.id,
        "subject": subject_row(course.subject) if course.subject_id else None,
        "title": course.title,
        "introduction": course.introduction,
        "cover_url": (
            protected_file_url("course-cover", course.id) if course.cover else ""
        ),
        "teacher": student_teacher_row(course.teacher),
        "teaching_model": course.teaching_model,
        "teaching_model_label": course.get_teaching_model_display(),
        "lesson_count": getattr(course, "lesson_count", 0),
        "step_count": getattr(course, "step_count", 0),
        "latest_lesson": (
            lesson_row(course.latest_lesson)
            if hasattr(course, "latest_lesson") and course.latest_lesson
            else None
        ),
        "pretest_status": pretest_status
        or {"required": False, "completed": True, "missing": []},
        "created_at": course.created_at,
        "updated_at": course.updated_at,
    }


def student_lesson_step_row(
    step: LessonStep,
    *,
    student_layer: str | None = None,
    apply_layering: bool = False,
) -> dict:
    return {
        "id": step.id,
        "lesson": step.lesson_id,
        "title": step.title,
        "step_type": step.step_type,
        "step_type_label": step.get_step_type_display(),
        "student_instruction": step.student_instruction,
        "sort_order": step.sort_order,
        "is_required": step.is_required,
        "estimated_minutes": step.estimated_minutes,
        "status": step.status,
        "status_label": step.get_status_display(),
        "resource_items": normalize_resource_items(step.resource_items),
        "activity_items": (
            step.activity_items if isinstance(step.activity_items, list) else []
        ),
        "question_items": normalize_lesson_question_items(
            step.question_items,
            include_answer=False,
            student_layer=student_layer,
            apply_layering=apply_layering,
        ),
        "collect_student_log": step.collect_student_log,
        "created_at": step.created_at,
        "updated_at": step.updated_at,
    }


def student_classroom_row(
    session: ClassroomSession | None,
    *,
    student_layer: str | None = None,
    student_user: User | None = None,
) -> dict | None:
    if session is None:
        return None
    apply_layering = lesson_step_has_layered_questions(
        session.current_step if session.current_step_id else None
    )
    activities = getattr(session, "prefetched_activities", None)
    if activities is None:
        activity_filter = Q(status=ClassroomActivity.Status.OPEN)
        if student_user is not None:
            scored_activity_ids = []
            for object_id in (
                LearningEvent.objects.filter(
                    Q(metadata__action="quick_answer_score")
                    | Q(metadata__action="random_pick_score"),
                    actor=student_user,
                    object_type="classroom_activity",
                )
                .values_list("object_id", flat=True)
                .distinct()
            ):
                try:
                    scored_activity_ids.append(int(object_id))
                except (TypeError, ValueError):
                    continue
            if scored_activity_ids:
                activity_filter |= Q(pk__in=scored_activity_ids)
        activities = session.activities.filter(activity_filter).order_by(
            "-opened_at", "-created_at"
        )
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "status_label": session.get_status_display(),
        "current_step": (
            student_lesson_step_row(
                session.current_step,
                student_layer=student_layer,
                apply_layering=apply_layering,
            )
            if getattr(session, "current_step", None) and session.current_step_id
            else None
        ),
        "current_step_status": session.current_step_status,
        "current_step_status_label": session.get_current_step_status_display(),
        "submission_locked": session.submission_locked,
        "current_step_started_at": session.current_step_started_at,
        "current_step_closed_at": session.current_step_closed_at,
        "teacher": student_teacher_row(session.teacher),
        "course": (
            student_course_row(session.course)
            if getattr(session, "course", None)
            else None
        ),
        "lesson": (
            lesson_row(session.lesson)
            if getattr(session, "lesson", None) and session.lesson_id
            else None
        ),
        "class_group": class_group_row(session.class_group),
        "started_at": session.started_at,
        "finished_at": session.finished_at,
        "activities": [
            classroom_activity_row(activity, student_user=student_user)
            for activity in activities
        ],
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def student_notice_row(notice: Notice) -> dict:
    return {
        "id": notice.id,
        "title": notice.title,
        "content": notice.content,
        "is_pinned": notice.is_pinned,
        "teacher": student_teacher_row(notice.teacher),
        "published_at": notice.published_at,
        "created_at": notice.created_at,
        "updated_at": notice.updated_at,
    }


def student_feedback_row(feedback: Feedback) -> dict:
    return {
        "id": feedback.id,
        "teacher": student_teacher_row(feedback.teacher),
        "category": feedback.category,
        "category_label": feedback.get_category_display(),
        "title": feedback.title,
        "content": feedback.content,
        "status": feedback.status,
        "status_label": feedback.get_status_display(),
        "reply_content": feedback.reply_content,
        "replied_at": feedback.replied_at,
        "closed_at": feedback.closed_at,
        "created_at": feedback.created_at,
        "updated_at": feedback.updated_at,
    }


def teacher_ai_provider_row(provider: TeacherAIProvider) -> dict:
    return {
        "id": provider.id,
        "provider": provider.provider,
        "provider_label": provider.get_provider_display(),
        "base_url": provider.base_url,
        "model": provider.model,
        "is_enabled": provider.is_enabled,
        "has_api_key": bool(provider.api_key_encrypted),
        "api_key_hint": provider.api_key_hint,
        "last_tested_at": provider.last_tested_at,
        "last_error": provider.last_error,
        "updated_at": provider.updated_at,
    }


def resource_file_row(resource_file) -> dict:
    file_url = (
        protected_file_url("resource-extra", resource_file.id)
        if resource_file.file
        else ""
    )
    return {
        "id": resource_file.id,
        "name": resource_file.original_name,
        "file_url": file_url,
        "file_ext": resource_file.file_ext,
        "file_size": resource_file.file_size,
        "role": resource_file.role,
        "role_label": resource_file.get_role_display(),
        "sort_order": resource_file.sort_order,
    }


def resource_row(resource: Resource, *, viewer=None) -> dict:
    attachment_url = ""
    attachment_name = ""
    attachment_size = 0
    cover_url = (
        protected_file_url("resource-cover", resource.id) if resource.cover else ""
    )
    if resource.attachment:
        attachment_url = protected_file_url("resource-attachment", resource.id)
        attachment_name = resource.attachment.name.rsplit("/", 1)[-1]
        try:
            attachment_size = resource.attachment.size
        except (OSError, ValueError):
            attachment_size = 0
    return {
        "id": resource.id,
        "public_id": str(resource.public_id),
        "title": resource.title,
        "content": resource.content,
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
        "attachment_size": attachment_size,
        "file_ext": clean_resource_ext(attachment_name, attachment_url),
        "cover_url": cover_url,
        "resource_type": resource.resource_type,
        "resource_type_label": resource.get_resource_type_display(),
        "category": resource.category,
        "category_label": resource.get_category_display(),
        "visibility": resource.visibility,
        "visibility_label": resource.get_visibility_display(),
        "publish_status": resource.publish_status,
        "publish_status_label": resource.get_publish_status_display(),
        "subject": subject_row(resource.subject) if resource.subject_id else None,
        "target_classes": [
            class_group_row(item) for item in resource.target_classes.all()
        ],
        "grade_scope": resource.grade_scope,
        "tags": resource.tags if isinstance(resource.tags, list) else [],
        "external_url": resource.external_url,
        "project_type": resource.project_type,
        "project_type_label": (
            resource.get_project_type_display() if resource.project_type else ""
        ),
        "project_members": (
            resource.project_members
            if isinstance(resource.project_members, list)
            else []
        ),
        "project_course": resource.project_course,
        "competition_name": resource.competition_name,
        "competition_year": resource.competition_year,
        "award_level": resource.award_level,
        "extra_files": [resource_file_row(item) for item in resource.extra_files.all()],
        "owner": user_summary(resource.owner),
        "school": school_summary(resource.owner.school),
        "view_count": resource.view_count,
        "is_pinned": resource.is_pinned,
        "is_owner": bool(viewer and viewer.id == resource.owner_id),
        "review_note": resource.review_note,
        "reviewed_at": resource.reviewed_at,
        "published_at": resource.published_at,
        "created_at": resource.created_at,
        "updated_at": resource.updated_at,
    }


def student_work_attachment_row(attachment: StudentWorkAttachment) -> dict:
    attachment_url = (
        protected_file_url("student-work", attachment.id)
        if attachment.attachment
        else ""
    )
    attachment_name = attachment.original_name or (
        attachment.attachment.name.rsplit("/", 1)[-1] if attachment.attachment else ""
    )
    file_ext = attachment.file_ext or clean_resource_ext(
        attachment_name, attachment_url
    )
    return {
        "id": attachment.id,
        "student": attachment.student_id,
        "lesson_step": attachment.lesson_step_id,
        "classroom_session": attachment.classroom_session_id,
        "question_id": attachment.question_id,
        "question_stem": attachment.question_stem,
        "upload_version": attachment.upload_version,
        "title": attachment_name or "学生附件",
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
        "file_ext": file_ext,
        "attachment_size": attachment.file_size,
        "score": attachment.score,
        "feedback": attachment.feedback,
        "evaluated_by": attachment.evaluated_by_id,
        "evaluated_at": attachment.evaluated_at,
        "created_at": attachment.created_at,
        "updated_at": attachment.updated_at,
    }


def classroom_group_file_row(file: ClassroomGroupFile) -> dict:
    attachment_url = (
        protected_file_url("group-file", file.id) if file.attachment else ""
    )
    uploader = file.uploader
    return {
        "id": file.id,
        "public_id": str(file.public_id),
        "version_no": file.version_no,
        "group": file.group_id,
        "uploader": (
            {
                "id": uploader.id,
                "username": uploader.username,
                "display_name": uploader.display_name or uploader.username,
                "role": uploader.role,
            }
            if uploader
            else None
        ),
        "title": file.original_name,
        "description": file.description,
        "attachment_url": attachment_url,
        "attachment_name": file.original_name,
        "file_ext": file.file_ext
        or clean_resource_ext(file.original_name, attachment_url),
        "file_size": file.file_size,
        "created_at": file.created_at,
    }


def classroom_group_member_row(member: ClassroomGroupMember) -> dict:
    profile = member.student_profile
    student = member.student
    return {
        "id": member.id,
        "student_id": student.id,
        "profile_id": profile.id if profile else None,
        "username": student.username,
        "display_name": student.display_name or student.username,
        "student_no": profile.student_no if profile else "",
        "current_layer": profile.current_layer if profile else "",
        "current_layer_label": (
            profile.get_current_layer_display()
            if profile and profile.current_layer
            else ""
        ),
        "role": member.role,
        "role_label": member.get_role_display(),
        "joined_at": member.joined_at,
    }


def student_classroom_group_member_row(member: ClassroomGroupMember) -> dict:
    profile = member.student_profile
    student = member.student
    return {
        "id": member.id,
        "student_id": student.id,
        "username": student.username,
        "display_name": student.display_name or student.username,
        "student_no": profile.student_no if profile else "",
        "role": member.role,
        "role_label": member.get_role_display(),
        "joined_at": member.joined_at,
    }


def classroom_group_row(group: ClassroomGroup, *, include_files: bool = True) -> dict:
    document_url = (
        protected_file_url("group-document", group.id)
        if group.collaboration_document
        else ""
    )
    document_name = (
        group.document_original_name
        or f"{group.name}.{group.document_file_ext or group.collaboration.document_type}"
    )
    document_size = 0
    if group.collaboration_document:
        try:
            document_size = group.collaboration_document.size
        except (OSError, ValueError):
            document_size = 0
    used_storage_bytes = getattr(group, "used_storage_bytes", None)
    if used_storage_bytes is None:
        used_storage_bytes = (
            group.files.aggregate(total=Sum("file_size")).get("total") or 0
        )
    files = getattr(group, "prefetched_files", None)
    if files is None and include_files:
        files = list(group.files.select_related("uploader").all())
    members = getattr(group, "prefetched_members", None)
    if members is None:
        members = list(group.members.select_related("student", "student_profile").all())
    return {
        "id": group.id,
        "collaboration": group.collaboration_id,
        "group_no": group.group_no,
        "name": group.name,
        "layer_hint": group.layer_hint,
        "leader": group.leader_id,
        "document": {
            "attachment_url": document_url,
            "attachment_name": document_name,
            "file_ext": group.document_file_ext or group.collaboration.document_type,
            "file_size": document_size,
            "document_version": group.document_version,
        },
        "used_storage_bytes": used_storage_bytes,
        "used_storage_mb": round(used_storage_bytes / 1024 / 1024, 2),
        "members": [classroom_group_member_row(member) for member in members],
        "files": (
            [classroom_group_file_row(file) for file in files] if include_files else []
        ),
        "file_count": len(files) if include_files else getattr(group, "file_count", 0),
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def student_classroom_group_row(
    group: ClassroomGroup, *, include_files: bool = True
) -> dict:
    document_url = (
        protected_file_url("group-document", group.id)
        if group.collaboration_document
        else ""
    )
    document_ext = group.document_file_ext or group.collaboration.document_type
    document_size = 0
    if group.collaboration_document:
        try:
            document_size = group.collaboration_document.size
        except (OSError, ValueError):
            document_size = 0
    used_storage_bytes = getattr(group, "used_storage_bytes", None)
    if used_storage_bytes is None:
        used_storage_bytes = (
            group.files.aggregate(total=Sum("file_size")).get("total") or 0
        )
    files = getattr(group, "prefetched_files", None)
    if files is None and include_files:
        files = list(group.files.select_related("uploader").all())
    members = getattr(group, "prefetched_members", None)
    if members is None:
        members = list(group.members.select_related("student", "student_profile").all())
    return {
        "id": group.id,
        "collaboration": group.collaboration_id,
        "group_no": group.group_no,
        "name": f"第{group.group_no}组",
        "leader": group.leader_id,
        "document": {
            "attachment_url": document_url,
            "attachment_name": f"第{group.group_no}组.{document_ext}",
            "file_ext": document_ext,
            "file_size": document_size,
            "document_version": group.document_version,
        },
        "used_storage_bytes": used_storage_bytes,
        "used_storage_mb": round(used_storage_bytes / 1024 / 1024, 2),
        "members": [student_classroom_group_member_row(member) for member in members],
        "files": (
            [classroom_group_file_row(file) for file in files] if include_files else []
        ),
        "file_count": len(files) if include_files else getattr(group, "file_count", 0),
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def classroom_group_collaboration_row(
    collaboration: ClassroomGroupCollaboration,
    *,
    include_groups: bool = True,
    include_files: bool = True,
    my_group: ClassroomGroup | None = None,
) -> dict:
    groups = getattr(collaboration, "prefetched_groups", None)
    if groups is None and include_groups:
        groups = list(
            collaboration.groups.annotate(used_storage_bytes=Sum("files__file_size"))
            .prefetch_related(
                Prefetch(
                    "members",
                    queryset=ClassroomGroupMember.objects.select_related(
                        "student", "student_profile"
                    ),
                    to_attr="prefetched_members",
                ),
                Prefetch(
                    "files",
                    queryset=ClassroomGroupFile.objects.select_related("uploader"),
                    to_attr="prefetched_files",
                ),
            )
            .order_by("group_no", "id")
        )
    return {
        "id": collaboration.id,
        "session": collaboration.session_id,
        "is_enabled": collaboration.is_enabled,
        "status": collaboration.status,
        "status_label": collaboration.get_status_display(),
        "group_size": collaboration.group_size,
        "grouping_strategy": collaboration.grouping_strategy,
        "grouping_strategy_label": collaboration.get_grouping_strategy_display(),
        "document_type": collaboration.document_type,
        "document_type_label": collaboration.get_document_type_display(),
        "storage_quota_mb": collaboration.storage_quota_mb,
        "allow_student_upload": collaboration.allow_student_upload,
        "allow_onlyoffice_edit": collaboration.allow_onlyoffice_edit,
        "group_count": len(groups) if include_groups else collaboration.groups.count(),
        "my_group_id": my_group.id if my_group else None,
        "my_group": (
            classroom_group_row(my_group, include_files=include_files)
            if my_group
            else None
        ),
        "groups": (
            [
                classroom_group_row(group, include_files=include_files)
                for group in groups
            ]
            if include_groups
            else []
        ),
        "opened_at": collaboration.opened_at,
        "closed_at": collaboration.closed_at,
        "created_at": collaboration.created_at,
        "updated_at": collaboration.updated_at,
    }


def student_classroom_group_collaboration_row(
    collaboration: ClassroomGroupCollaboration,
    *,
    my_group: ClassroomGroup,
    include_files: bool = True,
) -> dict:
    return {
        "id": collaboration.id,
        "session": collaboration.session_id,
        "is_enabled": collaboration.is_enabled,
        "status": collaboration.status,
        "status_label": collaboration.get_status_display(),
        "group_size": collaboration.group_size,
        "document_type": collaboration.document_type,
        "document_type_label": collaboration.get_document_type_display(),
        "storage_quota_mb": collaboration.storage_quota_mb,
        "allow_student_upload": collaboration.allow_student_upload,
        "allow_onlyoffice_edit": collaboration.allow_onlyoffice_edit,
        "group_count": collaboration.groups.count(),
        "my_group_id": my_group.id,
        "my_group": student_classroom_group_row(my_group, include_files=include_files),
        "groups": [],
        "opened_at": collaboration.opened_at,
        "closed_at": collaboration.closed_at,
        "created_at": collaboration.created_at,
        "updated_at": collaboration.updated_at,
    }


def classroom_evaluation_criteria_rows(items) -> list[dict]:
    rows = []
    raw_items = items if isinstance(items, list) else []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        rows.append(
            {
                "id": str(item.get("id") or f"crit_{index}"),
                "title": title,
                "description": str(item.get("description") or "").strip(),
                "sort_order": int(item.get("sort_order") or index * 10),
            }
        )
    return sorted(rows, key=lambda row: (row["sort_order"], row["id"]))


def classroom_evaluation_config_row(
    config: ClassroomEvaluationConfig | ClassroomEvaluationConfigVersion | None,
) -> dict:
    if config is None:
        return {
            "id": None,
            "course": None,
            "session": None,
            "enable_self": False,
            "enable_peer": False,
            "enable_teacher": False,
            "self_criteria": [],
            "peer_criteria": [],
            "teacher_criteria": [],
            "opened_at": None,
            "created_at": None,
            "updated_at": None,
            "version_no": None,
            "config_hash": "",
        }
    self_criteria = classroom_evaluation_criteria_rows(config.self_criteria)
    peer_criteria = classroom_evaluation_criteria_rows(config.peer_criteria)
    teacher_criteria = classroom_evaluation_criteria_rows(config.teacher_criteria)
    return {
        "id": config.id,
        "course": config.course_id,
        "session": None,
        "enable_self": bool(config.enable_self or self_criteria),
        "enable_peer": bool(config.enable_peer or peer_criteria),
        "enable_teacher": bool(config.enable_teacher or teacher_criteria),
        "self_criteria": self_criteria,
        "peer_criteria": peer_criteria,
        "teacher_criteria": teacher_criteria,
        "opened_at": getattr(config, "opened_at", None),
        "created_at": config.created_at,
        "updated_at": getattr(config, "updated_at", config.created_at),
        "version_no": getattr(config, "version_no", None),
        "config_hash": getattr(config, "config_hash", ""),
    }


def classroom_evaluation_submission_row(
    submission: ClassroomEvaluationSubmission | None,
) -> dict | None:
    if submission is None:
        return None
    ratings = submission.ratings if isinstance(submission.ratings, dict) else {}
    return {
        "id": submission.id,
        "course": submission.course_id,
        "class_group": submission.class_group_id,
        "session": submission.session_id,
        "evaluation_type": submission.evaluation_type,
        "evaluation_type_label": submission.get_evaluation_type_display(),
        "evaluator": account_row(submission.evaluator),
        "target": account_row(submission.target),
        "group": submission.group_id,
        "evaluation_version": submission.evaluation_version_id,
        "evaluation_version_no": submission.evaluation_version.version_no,
        "submission_id": str(submission.submission_id),
        "submission_version": submission.submission_version,
        "supersedes": submission.supersedes_id,
        "ratings": {
            str(key): int(value)
            for key, value in ratings.items()
            if str(value).isdigit()
        },
        "comment": submission.comment,
        "created_at": submission.created_at,
        "updated_at": submission.updated_at,
    }


def pretest_paper_row(paper: PretestPaper, *, include_questions: bool = False) -> dict:
    row = {
        "id": paper.id,
        "subject": subject_row(paper.subject),
        "title": paper.title,
        "kind": paper.kind,
        "kind_label": paper.get_kind_display(),
        "version": paper.version,
        "introduction": paper.introduction,
        "status": paper.status,
        "status_label": paper.get_status_display(),
        "question_count": getattr(paper, "question_count", 0),
        "submission_count": getattr(paper, "submission_count", 0),
        "published_at": paper.published_at,
        "created_at": paper.created_at,
        "updated_at": paper.updated_at,
    }
    if include_questions:
        row["questions"] = [
            pretest_question_row(question) for question in paper.questions.all()
        ]
    return row


def pretest_question_row(question: PretestQuestion) -> dict:
    return {
        "id": question.id,
        "paper": question.paper_id,
        "stem": question.stem,
        "question_type": question.question_type,
        "question_type_label": question.get_question_type_display(),
        "options": question.options,
        "answer": question.answer,
        "score": question.score,
        "dimension": question.dimension,
        "sort_order": question.sort_order,
        "is_required": question.is_required,
        "created_at": question.created_at,
        "updated_at": question.updated_at,
    }


def student_pretest_question_row(question: PretestQuestion) -> dict:
    return {
        "id": question.id,
        "paper": question.paper_id,
        "stem": question.stem,
        "question_type": question.question_type,
        "question_type_label": question.get_question_type_display(),
        "options": question.options,
        "score": question.score,
        "dimension": question.dimension,
        "sort_order": question.sort_order,
        "is_required": question.is_required,
    }


def student_pretest_paper_row(
    paper: PretestPaper, *, include_questions: bool = False
) -> dict:
    row = pretest_paper_row(paper, include_questions=False)
    if include_questions:
        row["questions"] = [
            student_pretest_question_row(question) for question in paper.questions.all()
        ]
    return row


def student_row(profile: StudentProfile) -> dict:
    user = profile.user
    class_group = None
    if profile.class_group_id:
        class_group = {
            "id": profile.class_group_id,
            "name": profile.class_group.name,
            "grade": profile.class_group.grade,
            "status": profile.class_group.status,
        }
    return {
        "id": profile.id,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "phone": user.phone,
        "student_no": profile.student_no,
        "class_group": class_group,
        "current_layer": profile.current_layer,
        "current_layer_label": (
            profile.get_current_layer_display() if profile.current_layer else ""
        ),
        "current_group_no": profile.current_group_no,
        "score": profile.score,
        "is_first_use": profile.is_first_use,
        "onboarding_status": profile.onboarding_status,
        "onboarding_status_label": profile.get_onboarding_status_display(),
        "pretest_completed_at": profile.pretest_completed_at,
        "is_active": user.is_active,
        "is_first_login": user.is_first_login,
        "last_login": user.last_login,
        "updated_at": profile.updated_at,
    }


def notice_row(notice: Notice) -> dict:
    return {
        "id": notice.id,
        "title": notice.title,
        "content": notice.content,
        "status": notice.status,
        "status_label": notice.get_status_display(),
        "is_pinned": notice.is_pinned,
        "target_classes": [
            class_group_row(class_group) for class_group in notice.target_classes.all()
        ],
        "published_at": notice.published_at,
        "archived_at": notice.archived_at,
        "created_at": notice.created_at,
        "updated_at": notice.updated_at,
    }


def feedback_row(feedback: Feedback) -> dict:
    return {
        "id": feedback.id,
        "student": account_row(feedback.student),
        "class_group": class_group_row(feedback.class_group),
        "category": feedback.category,
        "category_label": feedback.get_category_display(),
        "title": feedback.title,
        "content": feedback.content,
        "status": feedback.status,
        "status_label": feedback.get_status_display(),
        "reply_content": feedback.reply_content,
        "replied_at": feedback.replied_at,
        "closed_at": feedback.closed_at,
        "created_at": feedback.created_at,
        "updated_at": feedback.updated_at,
    }


def classroom_activity_row(
    activity: ClassroomActivity, *, student_user: User | None = None
) -> dict:
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    response_events = LearningEvent.objects.filter(
        object_type="classroom_activity",
        object_id=str(activity.id),
        metadata__action="classroom_activity_response",
    ).select_related("actor")
    respondents = []
    for event in response_events.order_by("occurred_at"):
        respondents.append(
            {
                "event_id": event.id,
                "user_id": event.actor_id,
                "username": event.actor.username,
                "display_name": event.actor.display_name or event.actor.username,
                "response_type": event.metadata.get("response_type", ""),
                "attendance_status": event.metadata.get("attendance_status", ""),
                "source": event.metadata.get("source", ""),
                "score": event.score,
                "score_action": event.metadata.get("score_action", ""),
                "score_note": event.metadata.get("score_note", ""),
                "occurred_at": event.occurred_at,
            }
        )
    if respondents:
        seen = set()
        unique_respondents = []
        for row in respondents:
            key = (row["user_id"], row["response_type"])
            if key in seen:
                continue
            seen.add(key)
            unique_respondents.append(row)
        metadata = {
            **metadata,
            "stats": {
                "response_count": len({row["user_id"] for row in respondents}),
                "responses": unique_respondents,
            },
        }
    if student_user is not None:
        score_event = (
            LearningEvent.objects.filter(
                Q(metadata__action="quick_answer_score")
                | Q(metadata__action="random_pick_score"),
                actor=student_user,
                object_type="classroom_activity",
                object_id=str(activity.id),
            )
            .order_by("-occurred_at", "-id")
            .first()
        )
        if score_event is not None:
            has_acknowledged = LearningEvent.objects.filter(
                Q(metadata__action="classroom_score_feedback_ack")
                | Q(metadata__action="quick_answer_score_feedback_ack"),
                actor=student_user,
                object_type="classroom_activity",
                object_id=str(activity.id),
                metadata__score_event_id=score_event.id,
            ).exists()
            if not has_acknowledged:
                score_metadata = (
                    score_event.metadata
                    if isinstance(score_event.metadata, dict)
                    else {}
                )
                metadata = {
                    **metadata,
                    "my_score_feedback": {
                        "event_id": score_event.id,
                        "score": score_event.score,
                        "score_action": score_metadata.get("score_action", ""),
                        "score_note": score_metadata.get("score_note", ""),
                        "command": score_metadata.get("command", ""),
                        "activity_title": score_metadata.get(
                            "activity_title", activity.title
                        ),
                        "occurred_at": score_event.occurred_at,
                    },
                }
        metadata = sanitize_student_payload(metadata)
    return {
        "id": activity.id,
        "session": activity.session_id,
        "activity_type": activity.activity_type,
        "activity_type_label": activity.get_activity_type_display(),
        "title": activity.title,
        "content": activity.content,
        "metadata": metadata,
        "status": activity.status,
        "status_label": activity.get_status_display(),
        "opened_at": activity.opened_at,
        "closed_at": activity.closed_at,
        "created_at": activity.created_at,
        "updated_at": activity.updated_at,
    }


def classroom_attendance_row(
    activity: ClassroomActivity,
    profile: StudentProfile,
    latest_event: LearningEvent | None,
) -> dict:
    status = "not_signed"
    status_label = "未签到"
    source = ""
    note = ""
    occurred_at = None
    if latest_event is not None:
        metadata = (
            latest_event.metadata if isinstance(latest_event.metadata, dict) else {}
        )
        status = str(metadata.get("attendance_status") or "signed")
        labels = {
            "signed": "已签到",
            "late": "迟到",
            "leave": "请假",
            "absent": "缺勤",
            "not_signed": "未签到",
        }
        status_label = labels.get(status, status)
        source = str(metadata.get("source") or "")
        note = str(metadata.get("note") or "")
        occurred_at = latest_event.occurred_at
    return {
        "student_id": profile.user_id,
        "profile_id": profile.id,
        "username": profile.user.username,
        "display_name": profile.user.display_name or profile.user.username,
        "student_no": profile.student_no,
        "current_layer": profile.current_layer,
        "current_layer_label": profile.get_current_layer_display(),
        "status": status,
        "status_label": status_label,
        "source": source,
        "note": note,
        "occurred_at": occurred_at,
        "activity_id": activity.id,
    }


def classroom_session_row(
    session: ClassroomSession, *, include_activities: bool = False
) -> dict:
    current_step = (
        session.current_step
        if getattr(session, "current_step", None) and session.current_step_id
        else None
    )
    row = {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "status_label": session.get_status_display(),
        "school": school_summary(session.school),
        "course": (
            course_row(session.course) if getattr(session, "course", None) else None
        ),
        "lesson": (
            lesson_row(session.lesson)
            if getattr(session, "lesson", None) and session.lesson_id
            else None
        ),
        "class_group": (
            class_group_row(session.class_group)
            if getattr(session, "class_group", None)
            else None
        ),
        "current_step": lesson_step_row(current_step) if current_step else None,
        "current_step_status": session.current_step_status,
        "current_step_status_label": session.get_current_step_status_display(),
        "submission_locked": session.submission_locked,
        "is_layered": lesson_step_has_layered_questions(current_step),
        "evaluation_enabled": session.evaluation_enabled,
        "evaluation_opened_at": session.evaluation_opened_at,
        "current_step_started_at": session.current_step_started_at,
        "current_step_closed_at": session.current_step_closed_at,
        "activity_count": getattr(session, "activity_count", 0),
        "open_activity_count": getattr(session, "open_activity_count", 0),
        "started_at": session.started_at,
        "finished_at": session.finished_at,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }
    if include_activities:
        activities = getattr(session, "prefetched_activities", None)
        if activities is None:
            activities = session.activities.all()
        row["activities"] = [
            classroom_activity_row(activity) for activity in activities
        ]
    return row
