from __future__ import annotations

from accounts.models import User
from aiops.models import TeacherAIProvider
from courses.models import ClassroomActivity, ClassroomSession, Course, Lesson, LessonStep, Resource, Subject
from learning.models import Feedback, Notice, PretestPaper, PretestQuestion
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment

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
    "zip",
    "rar",
    "7z",
}


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
        "cover_url": f"/{course.cover.url.lstrip('/')}" if course.cover else "",
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
        attachment_name = str(item.get("attachment_name") or item.get("filename") or "").strip()
        attachment_url = str(item.get("attachment_url") or item.get("url") or "").strip()
        title = str(item.get("title") or item.get("name") or attachment_name or attachment_url).strip()
        file_ext = clean_resource_ext(item.get("file_ext"), attachment_name, attachment_url, title)
        return {
            "id": item.get("id") or "",
            "title": title,
            "attachment_url": attachment_url,
            "attachment_name": attachment_name,
            "file_ext": file_ext,
            "kind": str(item.get("kind") or "resource").strip(),
        }
    text = str(item or "").strip()
    file_ext = clean_resource_ext(text)
    return {
        "id": "",
        "title": text,
        "attachment_url": "",
        "attachment_name": text,
        "file_ext": file_ext,
        "kind": "legacy",
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


LESSON_QUESTION_TYPE_LABELS = {
    "single": "单选",
    "multiple": "多选",
    "judge": "判断",
    "blank": "填空",
    "text": "简答",
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
        if apply_layering and not lesson_target_layer_matches(target_layer, student_layer):
            continue
        base_score = clean_layer_score_value(item.get("score", 0), 0)
        raw_layer_scores = item.get("layer_scores") if isinstance(item.get("layer_scores"), dict) else {}
        layer_scores = {
            layer: clean_layer_score_value(raw_layer_scores.get(layer), base_score)
            for layer in sorted(LESSON_LAYER_CODES)
        }
        score = base_score
        if apply_layering and item.get("use_layer_scores") and student_layer in LESSON_LAYER_CODES:
            score = layer_scores.get(student_layer, base_score)
        row = {
            "id": item.get("id") or f"q_{index + 1}",
            "question_type": question_type,
            "question_type_label": LESSON_QUESTION_TYPE_LABELS.get(question_type, question_type),
            "stem": item.get("stem") or "",
            "options": item.get("options") if isinstance(item.get("options"), list) else [],
            "score": score,
            "is_required": bool(item.get("is_required", True)),
            "sort_order": item.get("sort_order", (index + 1) * 10),
        }
        if include_answer:
            row["target_layer"] = target_layer
            row["target_layer_label"] = LESSON_TARGET_LAYER_LABELS.get(target_layer, "全体")
            row["use_layer_scores"] = bool(item.get("use_layer_scores", False))
            row["layer_scores"] = layer_scores
            row["answer"] = item.get("answer") if isinstance(item.get("answer"), list) else []
            row["analysis"] = item.get("analysis") or ""
        rows.append(row)
    return sorted(rows, key=lambda row: (row["sort_order"], row["id"]))


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
        "activity_items": step.activity_items if isinstance(step.activity_items, list) else [],
        "question_items": normalize_lesson_question_items(step.question_items, include_answer=True),
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
        "class_group": class_group_row(profile.class_group) if profile.class_group_id else None,
        "current_layer": profile.current_layer,
        "current_layer_label": profile.get_current_layer_display() if profile.current_layer else "",
        "current_group_no": profile.current_group_no,
        "score": profile.score,
        "is_first_use": profile.is_first_use,
        "onboarding_status": profile.onboarding_status,
        "onboarding_status_label": profile.get_onboarding_status_display(),
        "password_updated_at": profile.password_updated_at,
        "class_selected_at": profile.class_selected_at,
        "pretest_completed_at": profile.pretest_completed_at,
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
        "cover_url": f"/{course.cover.url.lstrip('/')}" if course.cover else "",
        "teacher": student_teacher_row(course.teacher),
        "teaching_model": course.teaching_model,
        "teaching_model_label": course.get_teaching_model_display(),
        "lesson_count": getattr(course, "lesson_count", 0),
        "step_count": getattr(course, "step_count", 0),
        "latest_lesson": lesson_row(course.latest_lesson) if hasattr(course, "latest_lesson") and course.latest_lesson else None,
        "pretest_status": pretest_status or {"required": False, "completed": True, "missing": []},
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
        "target_layer": step.target_layer,
        "target_layer_label": step.get_target_layer_display(),
        "status": step.status,
        "status_label": step.get_status_display(),
        "resource_items": normalize_resource_items(step.resource_items),
        "activity_items": step.activity_items if isinstance(step.activity_items, list) else [],
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


def student_classroom_row(session: ClassroomSession | None, *, student_layer: str | None = None) -> dict | None:
    if session is None:
        return None
    apply_layering = bool(getattr(session, "is_layered", False))
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "status_label": session.get_status_display(),
        "is_layered": apply_layering,
        "current_step": student_lesson_step_row(
            session.current_step,
            student_layer=student_layer,
            apply_layering=apply_layering,
        )
        if getattr(session, "current_step", None) and session.current_step_id
        else None,
        "current_step_status": session.current_step_status,
        "current_step_status_label": session.get_current_step_status_display(),
        "submission_locked": session.submission_locked,
        "current_step_started_at": session.current_step_started_at,
        "current_step_closed_at": session.current_step_closed_at,
        "teacher": student_teacher_row(session.teacher),
        "course": student_course_row(session.course) if getattr(session, "course", None) else None,
        "lesson": lesson_row(session.lesson) if getattr(session, "lesson", None) and session.lesson_id else None,
        "class_group": class_group_row(session.class_group),
        "started_at": session.started_at,
        "finished_at": session.finished_at,
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


def resource_row(resource: Resource) -> dict:
    attachment_url = ""
    attachment_name = ""
    attachment_size = 0
    if resource.attachment:
        attachment_url = f"/{resource.attachment.url.lstrip('/')}"
        attachment_name = resource.attachment.name.rsplit("/", 1)[-1]
        try:
            attachment_size = resource.attachment.size
        except (OSError, ValueError):
            attachment_size = 0
    return {
        "id": resource.id,
        "title": resource.title,
        "content": resource.content,
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
        "attachment_size": attachment_size,
        "file_ext": clean_resource_ext(attachment_name, attachment_url),
        "view_count": resource.view_count,
        "is_pinned": resource.is_pinned,
        "created_at": resource.created_at,
        "updated_at": resource.updated_at,
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
        row["questions"] = [pretest_question_row(question) for question in paper.questions.all()]
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


def student_pretest_paper_row(paper: PretestPaper, *, include_questions: bool = False) -> dict:
    row = pretest_paper_row(paper, include_questions=False)
    if include_questions:
        row["questions"] = [student_pretest_question_row(question) for question in paper.questions.all()]
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
        "current_layer_label": profile.get_current_layer_display() if profile.current_layer else "",
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
        "target_classes": [class_group_row(class_group) for class_group in notice.target_classes.all()],
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


def classroom_activity_row(activity: ClassroomActivity) -> dict:
    return {
        "id": activity.id,
        "session": activity.session_id,
        "activity_type": activity.activity_type,
        "activity_type_label": activity.get_activity_type_display(),
        "title": activity.title,
        "content": activity.content,
        "status": activity.status,
        "status_label": activity.get_status_display(),
        "opened_at": activity.opened_at,
        "closed_at": activity.closed_at,
        "created_at": activity.created_at,
        "updated_at": activity.updated_at,
    }


def classroom_session_row(session: ClassroomSession, *, include_activities: bool = False) -> dict:
    row = {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "status_label": session.get_status_display(),
        "school": school_summary(session.school),
        "course": course_row(session.course) if getattr(session, "course", None) else None,
        "lesson": lesson_row(session.lesson) if getattr(session, "lesson", None) and session.lesson_id else None,
        "class_group": class_group_row(session.class_group) if getattr(session, "class_group", None) else None,
        "current_step": student_lesson_step_row(session.current_step)
        if getattr(session, "current_step", None) and session.current_step_id
        else None,
        "current_step_status": session.current_step_status,
        "current_step_status_label": session.get_current_step_status_display(),
        "submission_locked": session.submission_locked,
        "is_layered": session.is_layered,
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
        row["activities"] = [classroom_activity_row(activity) for activity in activities]
    return row
