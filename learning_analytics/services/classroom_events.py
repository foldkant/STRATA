from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from courses.models import LearningWebPage, Resource
from learning.models import (
    LearningEvent,
    LessonStepAttempt,
    StudentWorkAttachment,
)
from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    learning_event_write_mode,
    record_learning_event,
)


class ClassroomEventError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(value: dict) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classroom_question_object_id(step, question_id: str) -> str:
    return f"lesson-step-question:{step.id}:{question_id}"


def classroom_question_version(step, question: dict) -> str:
    return _digest(
        {
            "lesson_step_id": step.id,
            "question": question,
        }
    )


def classroom_step_task_object_id(step) -> str:
    return f"lesson-step-task:{step.id}"


def classroom_step_task_version(step) -> str:
    return _digest(
        {
            "lesson_step_id": step.id,
            "title": step.title,
            "step_type": step.step_type,
            "student_instruction": step.student_instruction,
            "is_required": step.is_required,
        }
    )


def learning_page_object_id(page) -> str:
    return f"learning-web-page:{page.id}"


def learning_page_version(page) -> str:
    return _digest(
        {
            "page_id": page.id,
            "revision_no": page.revision_no,
            "schema": page.schema,
        }
    )


VIDEO_EXTENSIONS = {"mp4", "webm", "ogg", "mov"}
DOCUMENT_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}
AUDIO_EXTENSIONS = {"mp3", "wav", "m4a"}
ARCHIVE_EXTENSIONS = {"zip", "rar", "7z"}


def _resource_extension(resource, item: dict | None = None) -> str:
    item = item if isinstance(item, dict) else {}
    raw = str(item.get("file_ext") or "").strip().lower().lstrip(".")
    if raw:
        return raw[:16]
    name = str(item.get("attachment_name") or "").strip()
    if not name and resource.attachment:
        name = str(resource.attachment.name or "")
    return name.rsplit(".", 1)[-1].lower()[:16] if "." in name else ""


def classroom_resource_format(resource, item: dict | None = None) -> str:
    extension = _resource_extension(resource, item)
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    if extension in ARCHIVE_EXTENSIONS:
        return "archive"
    if resource.resource_type == Resource.ResourceType.ARTICLE:
        return "article"
    if resource.resource_type == Resource.ResourceType.LINK:
        return "link"
    if resource.resource_type == Resource.ResourceType.STUDENT_PROJECT:
        return "project"
    return "other"


def classroom_resource_content_type(resource, item: dict | None = None) -> str:
    resource_format = classroom_resource_format(resource, item)
    if resource_format == "video":
        return LearningOpportunity.ContentType.VIDEO
    if resource_format == "document":
        return LearningOpportunity.ContentType.DOCUMENT
    return LearningOpportunity.ContentType.RESOURCE


def classroom_resource_object_id(resource) -> str:
    return f"resource:{resource.id}"


def classroom_resource_version(resource, item: dict | None = None) -> str:
    item = item if isinstance(item, dict) else {}
    return _digest(
        {
            "resource_id": resource.id,
            "public_id": str(resource.public_id),
            "updated_at": resource.updated_at.isoformat(),
            "resource_type": resource.resource_type,
            "title": str(item.get("title") or resource.title),
            "attachment_name": str(item.get("attachment_name") or ""),
            "attachment_url": str(item.get("attachment_url") or ""),
            "file_ext": _resource_extension(resource, item),
            "external_url": resource.external_url,
        }
    )


def classroom_resource(step, resource_id) -> tuple[Resource, dict]:
    try:
        resource_id = int(resource_id)
    except (TypeError, ValueError):
        resource_id = 0
    item = next(
        (
            row
            for row in (
                step.resource_items if isinstance(step.resource_items, list) else []
            )
            if isinstance(row, dict)
            and str(row.get("kind") or "resource") != "learning_page"
            and str(row.get("id") or row.get("resource_id") or "") == str(resource_id)
        ),
        None,
    )
    resource = Resource.objects.filter(pk=resource_id).first() if item else None
    if resource is None:
        raise ClassroomEventError(
            "classroom_resource_missing",
            "课堂资源不存在、已被替换或不属于当前环节。",
        )
    return resource, item


def _raw_questions(step) -> list[dict]:
    if not isinstance(step.question_items, list):
        return []
    return [
        item
        for item in step.question_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]


def classroom_question(step, question_id: str) -> dict:
    question_id = str(question_id)
    question = next(
        (
            item
            for item in _raw_questions(step)
            if str(item.get("id") or "") == question_id
        ),
        None,
    )
    if question is None:
        raise ClassroomEventError("classroom_question_missing", "课堂题目不存在。")
    return question


def _question_content_type(question: dict) -> str:
    if str(question.get("question_type") or "") == "file":
        return LearningOpportunity.ContentType.TASK
    return LearningOpportunity.ContentType.QUESTION


def _question_target_layers(question: dict) -> list[str]:
    target = str(question.get("target_layer") or "all")
    return [target] if target in {"A", "B", "C", "A/B", "B/C", "A/B/C"} else ["all"]


def _release_rows(step) -> list[dict]:
    questions = _raw_questions(step)
    rows = []
    if not questions and step.step_type in {
        "question",
        "task",
        "discussion",
        "evaluation",
        "reflection",
        "ai_worksheet",
    }:
        rows.append(
            {
                "content_type": LearningOpportunity.ContentType.TASK,
                "object_type": "lesson_step_task",
                "object_id": classroom_step_task_object_id(step),
                "object_version": classroom_step_task_version(step),
                "required": bool(step.is_required),
                "target_layers": ["all"],
                "question_id": "",
                "learning_page_id": "",
                "resource_id": "",
            }
        )
    else:
        rows.extend(
            {
                "content_type": _question_content_type(question),
                "object_type": (
                    "lesson_step_file_question"
                    if str(question.get("question_type") or "") == "file"
                    else "lesson_step_question"
                ),
                "object_id": classroom_question_object_id(step, str(question["id"])),
                "object_version": classroom_question_version(step, question),
                "required": bool(question.get("is_required", True)),
                "target_layers": _question_target_layers(question),
                "question_id": str(question["id"]),
                "learning_page_id": "",
                "resource_id": "",
            }
            for question in questions
        )

    resource_items = (
        step.resource_items if isinstance(step.resource_items, list) else []
    )
    page_ids = []
    for item in resource_items:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "learning_page":
            continue
        try:
            page_id = int(item.get("learning_page_id") or 0)
        except (TypeError, ValueError):
            continue
        if page_id and page_id not in page_ids:
            page_ids.append(page_id)
    pages = {
        page.id: page
        for page in LearningWebPage.objects.filter(
            id__in=page_ids,
            lesson=step.lesson,
            is_active=True,
            status=LearningWebPage.Status.READY,
        )
    }
    for page_id in page_ids:
        page = pages.get(page_id)
        if page is None:
            continue
        rows.append(
            {
                "content_type": LearningOpportunity.ContentType.LEARNING_PAGE,
                "object_type": "learning_web_page",
                "object_id": learning_page_object_id(page),
                "object_version": learning_page_version(page),
                "required": bool(step.is_required),
                "target_layers": ["all"],
                "question_id": "",
                "learning_page_id": str(page.id),
                "resource_id": "",
            }
        )

    resource_ids = []
    resource_items_by_id = {}
    for item in resource_items:
        if (
            not isinstance(item, dict)
            or str(item.get("kind") or "resource") == "learning_page"
        ):
            continue
        try:
            resource_id = int(item.get("id") or item.get("resource_id") or 0)
        except (TypeError, ValueError):
            continue
        if resource_id and resource_id not in resource_items_by_id:
            resource_ids.append(resource_id)
            resource_items_by_id[resource_id] = item
    resources = {
        resource.id: resource
        for resource in Resource.objects.filter(id__in=resource_ids)
    }
    for resource_id in resource_ids:
        resource = resources.get(resource_id)
        if resource is None:
            continue
        item = resource_items_by_id[resource_id]
        rows.append(
            {
                "content_type": classroom_resource_content_type(resource, item),
                "object_type": "resource",
                "object_id": classroom_resource_object_id(resource),
                "object_version": classroom_resource_version(resource, item),
                "required": bool(item.get("is_required", step.is_required)),
                "target_layers": ["all"],
                "question_id": "",
                "learning_page_id": "",
                "resource_id": str(resource.id),
            }
        )
    return rows


@transaction.atomic
def release_classroom_step_opportunities(
    *, session, actor, occurred_at=None, source_override: str | None = None
) -> dict:
    occurred_at = occurred_at or timezone.now()
    existing_ids = set()
    if learning_event_write_mode() != "v1_only":
        existing_ids = set(
            LearningEventV2.objects.filter(
                school=session.school,
                event_name="content.released",
                classroom_session=session,
                lesson_step=session.current_step,
                client_occurred_at__gte=session.current_step_started_at or occurred_at,
                legacy_event__metadata__action="classroom_step_content_released",
            ).values_list("object_id", flat=True)
        )

    release_events = 0
    opportunities_created = 0
    for row in _release_rows(session.current_step):
        if row["object_id"] in existing_ids:
            continue
        try:
            result = record_learning_event(
                actor=actor,
                event_name="content.released",
                payload={
                    "content_type": row["content_type"],
                    "required": row["required"],
                    "target_layers": row["target_layers"],
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=session.class_group,
                subject=session.course.subject,
                course=session.course,
                lesson=session.lesson,
                classroom_session=session,
                lesson_step=session.current_step,
                object_type=row["object_type"],
                object_id=row["object_id"],
                object_version=row["object_version"],
                legacy_metadata={
                    "action": "classroom_step_content_released",
                    "classroom_session": session.id,
                    "lesson_step": session.current_step_id,
                    "question_id": row["question_id"],
                    "learning_page_id": row["learning_page_id"],
                    "resource_id": row["resource_id"],
                    "content_type": row["content_type"],
                },
                occurred_at=occurred_at,
                source_override=source_override,
            )
        except EventWriteError as exc:
            raise ClassroomEventError(exc.code, exc.message) from exc
        release_events += 1
        if result.analytics_event:
            opportunities_created += (
                result.analytics_event.released_opportunities.count()
            )
    return {
        "release_events": release_events,
        "opportunities_created": opportunities_created,
    }


@transaction.atomic
def ensure_classroom_step_opportunities(*, session) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"release_events": 0, "opportunities_created": 0}
    return release_classroom_step_opportunities(
        session=session,
        actor=session.teacher,
        occurred_at=timezone.now(),
        source_override="server",
    )


@transaction.atomic
def withdraw_classroom_step_opportunities(
    *, session, step, actor, reason_code: str, occurred_at=None
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"withdrawal_events": 0}
    occurred_at = occurred_at or timezone.now()
    releases = LearningEventV2.objects.filter(
        school=session.school,
        event_name="content.released",
        classroom_session=session,
        lesson_step=step,
        legacy_event__metadata__action="classroom_step_content_released",
    ).select_related("class_group", "subject", "course", "lesson", "lesson_step")
    withdrawal_events = 0
    for release in releases:
        if LearningEventV2.objects.filter(
            school=session.school,
            event_name="content.withdrawn",
            payload__release_event_id=str(release.event_id),
        ).exists():
            continue
        try:
            record_learning_event(
                actor=actor,
                event_name="content.withdrawn",
                payload={
                    "release_event_id": release.event_id,
                    "reason_code": reason_code,
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=release.class_group,
                subject=release.subject,
                course=release.course,
                lesson=release.lesson,
                classroom_session=session,
                lesson_step=step,
                object_type=release.object_type,
                object_id=release.object_id,
                legacy_metadata={
                    "action": "classroom_step_content_withdrawn",
                    "classroom_session": session.id,
                    "lesson_step": step.id,
                    "release_event_id": str(release.event_id),
                    "reason_code": reason_code,
                },
                occurred_at=occurred_at,
            )
        except EventWriteError as exc:
            raise ClassroomEventError(exc.code, exc.message) from exc
        withdrawal_events += 1
    return {"withdrawal_events": withdrawal_events}


def _active_opportunity(
    *, session, student, object_id: str, object_version: str | None = None
) -> LearningOpportunity | None:
    if learning_event_write_mode() == "v1_only":
        return None
    opportunities = LearningOpportunity.objects.filter(
        school=session.school,
        student=student,
        class_group=session.class_group,
        subject=session.course.subject,
        course=session.course,
        lesson=session.lesson,
        classroom_session=session,
        lesson_step=session.current_step,
        object_id=object_id,
        release_event__legacy_event__metadata__action="classroom_step_content_released",
    ).order_by("-released_at", "-created_at")
    if object_version is not None:
        opportunities = opportunities.filter(object_version=object_version)
    for opportunity in opportunities:
        if not opportunity.transition_facts.filter(
            state__in=LearningOpportunityTransitionFact.TERMINAL_STATES
        ).exists():
            return opportunity
    raise ClassroomEventError(
        "classroom_opportunity_missing",
        "该课堂任务没有可用学习机会，请让教师重新投放当前环节。",
    )


def _question_opportunity(*, session, student, question: dict):
    question = classroom_question(session.current_step, str(question["id"]))
    return _active_opportunity(
        session=session,
        student=student,
        object_id=classroom_question_object_id(
            session.current_step, str(question["id"])
        ),
        object_version=classroom_question_version(session.current_step, question),
    )


def _task_opportunity(*, session, student):
    return _active_opportunity(
        session=session,
        student=student,
        object_id=classroom_step_task_object_id(session.current_step),
        object_version=classroom_step_task_version(session.current_step),
    )


def _learning_page_opportunity(*, session, student, page):
    return _active_opportunity(
        session=session,
        student=student,
        object_id=learning_page_object_id(page),
        object_version=learning_page_version(page),
    )


def _resource_opportunity(*, session, student, resource):
    return _active_opportunity(
        session=session,
        student=student,
        object_id=classroom_resource_object_id(resource),
    )


def _event_version(opportunity, fallback: str) -> str:
    return opportunity.object_version if opportunity is not None else fallback


@transaction.atomic
def record_classroom_resource_opened(
    *,
    session,
    step,
    resource_id,
    student,
    presentation: str = "unknown",
    occurred_at=None,
):
    resource, item = classroom_resource(step, resource_id)
    opportunity = _resource_opportunity(
        session=session, student=student, resource=resource
    )
    version = _event_version(opportunity, classroom_resource_version(resource, item))
    presentation = (
        presentation
        if presentation in {"embedded", "popout", "external", "download"}
        else "unknown"
    )
    try:
        return record_learning_event(
            actor=student,
            target_student=student,
            event_name="resource.opened",
            payload={
                "resource_format": classroom_resource_format(resource, item),
                "presentation": presentation,
            },
            legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
            legacy_actor=student,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            lesson_step=step,
            object_type="resource",
            object_id=classroom_resource_object_id(resource),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            legacy_metadata={
                "action": "classroom_resource_opened",
                "resource": resource.id,
                "resource_format": classroom_resource_format(resource, item),
                "presentation": presentation,
                "lesson_step": step.id,
                "classroom_session": session.id,
            },
            occurred_at=occurred_at or timezone.now(),
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_classroom_video_progress(
    *,
    session,
    step,
    resource_id,
    student,
    position_seconds: float,
    media_seconds: float,
    playback_rate: float,
    duration_ms: int = 0,
    occurred_at=None,
):
    resource, item = classroom_resource(step, resource_id)
    if classroom_resource_format(resource, item) != "video":
        raise ClassroomEventError("classroom_resource_not_video", "当前资源不是视频。")
    opportunity = _resource_opportunity(
        session=session, student=student, resource=resource
    )
    version = _event_version(opportunity, classroom_resource_version(resource, item))
    try:
        return record_learning_event(
            actor=student,
            target_student=student,
            event_name="video.progress",
            payload={
                "position_seconds": position_seconds,
                "media_seconds": media_seconds,
                "playback_rate": playback_rate,
            },
            legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
            legacy_actor=student,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            lesson_step=step,
            object_type="resource",
            object_id=classroom_resource_object_id(resource),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            duration_ms=duration_ms,
            legacy_metadata={
                "action": "classroom_video_progress",
                "resource": resource.id,
                "position_seconds": position_seconds,
                "media_seconds": media_seconds,
                "playback_rate": playback_rate,
                "lesson_step": step.id,
                "classroom_session": session.id,
            },
            occurred_at=occurred_at or timezone.now(),
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_classroom_document_progress(
    *,
    session,
    step,
    resource_id,
    student,
    page: int,
    page_count: int,
    visible_seconds: float,
    occurred_at=None,
):
    resource, item = classroom_resource(step, resource_id)
    if classroom_resource_format(resource, item) != "document":
        raise ClassroomEventError(
            "classroom_resource_not_document", "当前资源不是文档。"
        )
    opportunity = _resource_opportunity(
        session=session, student=student, resource=resource
    )
    version = _event_version(opportunity, classroom_resource_version(resource, item))
    try:
        return record_learning_event(
            actor=student,
            target_student=student,
            event_name="document.progress",
            payload={
                "page": page,
                "page_count": page_count,
                "visible_seconds": visible_seconds,
            },
            legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
            legacy_actor=student,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            lesson_step=step,
            object_type="resource",
            object_id=classroom_resource_object_id(resource),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            duration_ms=max(int(visible_seconds * 1000), 0),
            legacy_metadata={
                "action": "classroom_document_progress",
                "resource": resource.id,
                "page": page,
                "page_count": page_count,
                "visible_seconds": visible_seconds,
                "lesson_step": step.id,
                "classroom_session": session.id,
            },
            occurred_at=occurred_at or timezone.now(),
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_learning_page_opened(
    *, session, step, page, student, presentation: str = "unknown", occurred_at=None
):
    occurred_at = occurred_at or timezone.now()
    opportunity = _learning_page_opportunity(
        session=session,
        student=student,
        page=page,
    )
    version = _event_version(opportunity, learning_page_version(page))
    schema = page.schema if isinstance(page.schema, dict) else {}
    blocks = schema.get("blocks") if isinstance(schema.get("blocks"), list) else []
    form_count = sum(
        1
        for block in blocks
        if isinstance(block, dict) and str(block.get("type") or "") == "form"
    )
    try:
        return record_learning_event(
            actor=student,
            target_student=student,
            event_name="learning_page.opened",
            payload={
                "page_version": page.revision_no,
                "block_count": len(blocks),
                "form_count": form_count,
                "presentation": (
                    presentation
                    if presentation in {"embedded", "popout"}
                    else "unknown"
                ),
            },
            legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
            legacy_actor=student,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            lesson_step=step,
            object_type="learning_web_page",
            object_id=learning_page_object_id(page),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            legacy_metadata={
                "action": "learning_web_page_view",
                "learning_web_page": page.id,
                "page_version": page.revision_no,
                "lesson_step": step.id,
                "classroom_session": session.id,
                "presentation": presentation,
            },
            occurred_at=occurred_at,
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_learning_page_block_viewed(
    *,
    session,
    step,
    page,
    student,
    block_id: str,
    block_type: str,
    visible_ms: int,
    visibility_ratio: float,
    occurred_at=None,
):
    schema = page.schema if isinstance(page.schema, dict) else {}
    blocks = schema.get("blocks") if isinstance(schema.get("blocks"), list) else []
    block = next(
        (
            item
            for item in blocks
            if isinstance(item, dict) and str(item.get("id") or "") == block_id
        ),
        None,
    )
    if block is None or str(block.get("type") or "") != block_type:
        raise ClassroomEventError(
            "learning_page_block_invalid",
            "学习网页区块不存在或页面版本已更新，请刷新后重试。",
        )
    occurred_at = occurred_at or timezone.now()
    opportunity = _learning_page_opportunity(
        session=session,
        student=student,
        page=page,
    )
    version = _event_version(opportunity, learning_page_version(page))
    try:
        return record_learning_event(
            actor=student,
            target_student=student,
            event_name="learning_page.block_viewed",
            payload={
                "page_version": page.revision_no,
                "block_id": block_id,
                "block_type": block_type,
                "visible_ms": visible_ms,
                "visibility_ratio": visibility_ratio,
            },
            legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
            legacy_actor=student,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            lesson_step=step,
            object_type="learning_web_page",
            object_id=learning_page_object_id(page),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            duration_ms=visible_ms,
            legacy_metadata={
                "action": "learning_web_page_block_viewed",
                "learning_web_page": page.id,
                "page_version": page.revision_no,
                "block_id": block_id,
                "block_type": block_type,
                "lesson_step": step.id,
                "classroom_session": session.id,
                "visibility_ratio": visibility_ratio,
            },
            occurred_at=occurred_at,
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_learning_page_form_submission(*, response) -> None:
    session = response.classroom_session
    page = response.page
    opportunity = _learning_page_opportunity(
        session=session,
        student=response.student,
        page=page,
    )
    version = _event_version(opportunity, learning_page_version(page))
    answers = response.answers if isinstance(response.answers, dict) else {}
    try:
        record_learning_event(
            actor=response.student,
            target_student=response.student,
            event_name="learning_page.form_submitted",
            payload={
                "page_version": response.page_version,
                "form_id": response.form_id,
                "response_id": str(response.id),
                "attempt_no": response.attempt_no,
                "field_count": len(answers),
            },
            legacy_event_type=LearningEvent.EventType.ANSWER_SUBMIT,
            legacy_actor=response.student,
            class_group=response.class_group,
            subject=response.course.subject,
            course=response.course,
            lesson=response.lesson,
            classroom_session=session,
            lesson_step=response.lesson_step,
            object_type="learning_web_page",
            object_id=learning_page_object_id(page),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=response.analytics_attempt_id,
            legacy_metadata={
                "action": "learning_web_page_form_submit",
                "response_id": response.id,
                "learning_web_page": page.id,
                "page_version": response.page_version,
                "form_id": response.form_id,
                "lesson_step": response.lesson_step_id,
                "classroom_session": session.id,
                "attempt_no": response.attempt_no,
                "field_count": len(answers),
            },
            occurred_at=response.submitted_at,
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_classroom_attempt_events(*, attempt: LessonStepAttempt) -> None:
    session = attempt.classroom_session
    answer_rows = list(attempt.answer_rows.all())
    if not answer_rows:
        opportunity = _task_opportunity(session=session, student=attempt.student)
        version = _event_version(
            opportunity, classroom_step_task_version(attempt.lesson_step)
        )
        try:
            record_learning_event(
                actor=attempt.student,
                target_student=attempt.student,
                event_name="task.submitted",
                payload={
                    "submission_version": version,
                    "submitted_at": attempt.submitted_at,
                    "artifact_count": 0,
                },
                legacy_event_type=LearningEvent.EventType.TASK_SUBMIT,
                legacy_actor=attempt.student,
                class_group=attempt.class_group,
                subject=attempt.course.subject,
                course=attempt.course,
                lesson=attempt.lesson,
                classroom_session=session,
                lesson_step=attempt.lesson_step,
                object_type="lesson_step_task",
                object_id=classroom_step_task_object_id(attempt.lesson_step),
                object_version=version,
                opportunity_id=opportunity.opportunity_id if opportunity else None,
                attempt_id=attempt.attempt_id,
                legacy_metadata={
                    "action": "lesson_step_task_submitted",
                    "attempt_id": attempt.id,
                    "classroom_session": session.id,
                    "lesson_step": attempt.lesson_step_id,
                },
                occurred_at=attempt.submitted_at,
            )
        except EventWriteError as exc:
            raise ClassroomEventError(exc.code, exc.message) from exc
        return

    for answer_row in answer_rows:
        if not answer_row.is_answered or answer_row.question_type == "file":
            continue
        question = classroom_question(attempt.lesson_step, answer_row.question_id)
        opportunity = _question_opportunity(
            session=session,
            student=attempt.student,
            question=question,
        )
        version = _event_version(opportunity, answer_row.question_version)
        try:
            record_learning_event(
                actor=attempt.student,
                target_student=attempt.student,
                event_name="item.submitted",
                schema_version="1.1",
                payload={
                    "question_version": version,
                    "response_kind": answer_row.question_type,
                    "attempt_no": attempt.attempt_no,
                    "response_time_ms": None,
                },
                legacy_event_type=LearningEvent.EventType.ANSWER_SUBMIT,
                legacy_actor=attempt.student,
                class_group=attempt.class_group,
                subject=attempt.course.subject,
                course=attempt.course,
                lesson=attempt.lesson,
                classroom_session=session,
                lesson_step=attempt.lesson_step,
                object_type="lesson_step_question",
                object_id=classroom_question_object_id(
                    attempt.lesson_step, answer_row.question_id
                ),
                object_version=version,
                opportunity_id=opportunity.opportunity_id if opportunity else None,
                attempt_id=attempt.attempt_id,
                legacy_metadata={
                    "action": "lesson_step_item_submitted",
                    "attempt_id": attempt.id,
                    "answer_row_id": answer_row.id,
                    "classroom_session": session.id,
                    "lesson_step": attempt.lesson_step_id,
                    "question_id": answer_row.question_id,
                    "response_kind": answer_row.question_type,
                },
                occurred_at=attempt.submitted_at,
            )
        except EventWriteError as exc:
            raise ClassroomEventError(exc.code, exc.message) from exc

        if answer_row.score_max > 0:
            pending = answer_row.question_type == "text"
            record_classroom_item_grade(
                session=session,
                student=attempt.student,
                question=question,
                attempt_id=attempt.attempt_id,
                score_raw=None if pending else answer_row.auto_score,
                score_max=answer_row.score_max,
                is_correct=None if pending else answer_row.is_correct,
                grading_state="pending" if pending else "final",
                grader_type="teacher" if pending else "automatic",
                actor=session.teacher,
                occurred_at=attempt.submitted_at,
                source_override="server",
            )


@transaction.atomic
def record_classroom_attachment_submission(
    *, work: StudentWorkAttachment, occurred_at=None
) -> None:
    occurred_at = occurred_at or timezone.now()
    session = work.classroom_session
    question = classroom_question(work.lesson_step, work.question_id)
    opportunity = _question_opportunity(
        session=session,
        student=work.student,
        question=question,
    )
    version = _event_version(
        opportunity, classroom_question_version(work.lesson_step, question)
    )
    try:
        record_learning_event(
            actor=work.student,
            target_student=work.student,
            event_name="task.submitted",
            payload={
                "submission_version": f"{version}:upload:{work.upload_version}",
                "submitted_at": occurred_at,
                "artifact_count": 1,
            },
            legacy_event_type=LearningEvent.EventType.TASK_SUBMIT,
            legacy_actor=work.student,
            class_group=work.class_group,
            subject=work.course.subject,
            course=work.course,
            lesson=work.lesson,
            classroom_session=session,
            lesson_step=work.lesson_step,
            object_type="lesson_step_file_question",
            object_id=classroom_question_object_id(work.lesson_step, work.question_id),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=work.submission_id,
            legacy_metadata={
                "action": "student_work_attachment_upload",
                "attachment_id": work.id,
                "upload_version": work.upload_version,
                "classroom_session": session.id,
                "lesson_step": work.lesson_step_id,
                "question_id": work.question_id,
                "filename": work.original_name,
                "file_ext": work.file_ext,
                "file_size": work.file_size,
            },
            occurred_at=occurred_at,
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc
    score_max = float(question.get("score") or 0)
    if score_max > 0:
        record_classroom_item_grade(
            session=session,
            student=work.student,
            question=question,
            attempt_id=work.submission_id,
            score_raw=None,
            score_max=score_max,
            is_correct=None,
            grading_state="pending",
            grader_type="teacher",
            actor=session.teacher,
            occurred_at=occurred_at,
            source_override="server",
        )


def ensure_classroom_attachment_submission(*, work: StudentWorkAttachment) -> None:
    if learning_event_write_mode() == "v1_only":
        return
    if LearningEventV2.objects.filter(
        school=work.school,
        event_name="task.submitted",
        attempt_id=work.submission_id,
    ).exists():
        return
    record_classroom_attachment_submission(work=work, occurred_at=timezone.now())


@transaction.atomic
def record_classroom_item_grade(
    *,
    session,
    student,
    question: dict,
    attempt_id,
    score_raw,
    score_max,
    is_correct,
    grading_state: str,
    grader_type: str,
    actor,
    occurred_at=None,
    source_override: str | None = None,
):
    occurred_at = occurred_at or timezone.now()
    opportunity = _question_opportunity(
        session=session,
        student=student,
        question=question,
    )
    version = _event_version(
        opportunity, classroom_question_version(session.current_step, question)
    )
    object_type = (
        "lesson_step_file_question"
        if str(question.get("question_type") or "") == "file"
        else "lesson_step_question"
    )
    try:
        return record_learning_event(
            actor=actor,
            target_student=student,
            event_name="item.graded",
            schema_version="1.1",
            payload={
                "grading_state": grading_state,
                "score_raw": score_raw,
                "score_max": score_max,
                "is_correct": is_correct,
                "grader_type": grader_type,
            },
            legacy_event_type=(
                LearningEvent.EventType.TEACHER_INTERVENTION
                if grader_type == "teacher"
                else LearningEvent.EventType.ANSWER_SUBMIT
            ),
            legacy_actor=student,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            lesson_step=session.current_step,
            object_type=object_type,
            object_id=classroom_question_object_id(
                session.current_step, str(question["id"])
            ),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=attempt_id,
            legacy_score=score_raw,
            legacy_metadata={
                "action": "lesson_step_item_graded",
                "classroom_session": session.id,
                "lesson_step": session.current_step_id,
                "question_id": str(question["id"]),
                "grading_state": grading_state,
                "grader_type": grader_type,
            },
            occurred_at=occurred_at,
            source_override=source_override,
        )
    except EventWriteError as exc:
        raise ClassroomEventError(exc.code, exc.message) from exc


def next_classroom_grading_state(
    *, session, student, question: dict, attempt_id
) -> str:
    if learning_event_write_mode() == "v1_only":
        return AssessmentResultFact.GradingState.FINAL
    opportunity = _question_opportunity(
        session=session,
        student=student,
        question=question,
    )
    mature_exists = AssessmentResultFact.objects.filter(
        opportunity=opportunity,
        attempt_id=attempt_id,
        grading_state__in=[
            AssessmentResultFact.GradingState.FINAL,
            AssessmentResultFact.GradingState.REVISED,
        ],
    ).exists()
    return (
        AssessmentResultFact.GradingState.REVISED
        if mature_exists
        else AssessmentResultFact.GradingState.FINAL
    )
