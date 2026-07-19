from __future__ import annotations

import uuid
from dataclasses import dataclass

from courses.models import ClassroomActivity, ClassroomSession, Lesson, LessonStep, Resource
from learning.models import LearningEvent, PretestSubmission
from learning_analytics.services.dual_write import (
    EventWriteError,
    backfill_existing_learning_event,
    record_legacy_unmapped_event,
)
from learning_analytics.schemas.registry import validate_event_payload
from realtime.models import ClassroomChatMessage

MAPPING_VERSION = "data01c-v1"
BACKFILL_NAMESPACE = uuid.UUID("c681e99f-c5f1-4f05-93b2-7f78f72218d8")


@dataclass(frozen=True, slots=True)
class LegacyMappingPlan:
    event_name: str
    payload: dict
    kwargs: dict


@dataclass(frozen=True, slots=True)
class LegacyBackfillResult:
    status: str
    event_name: str
    reason_code: str = ""


def deterministic_backfill_event_id(legacy_event_id: int, event_name: str) -> uuid.UUID:
    return uuid.uuid5(
        BACKFILL_NAMESPACE,
        f"{MAPPING_VERSION}:{legacy_event_id}:{event_name}",
    )


def _metadata(event: LearningEvent) -> dict:
    return event.metadata if isinstance(event.metadata, dict) else {}


def _integer(value) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _number(value, fallback: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _version(prefix: str, instance) -> str:
    updated_at = getattr(instance, "updated_at", None)
    suffix = int(updated_at.timestamp()) if updated_at else instance.id
    return f"{prefix}:{suffix}"


def _resource_mapping(event: LearningEvent, metadata: dict):
    if event.event_type != LearningEvent.EventType.RESOURCE_VIEW:
        return None
    if event.object_type != "resource_center":
        return None
    resource = (
        Resource.objects.select_related("owner__school", "subject")
        .filter(pk=_integer(event.object_id))
        .first()
    )
    if resource is None:
        return "resource_missing"
    origin_scope = "unknown"
    if event.actor.school_id and resource.owner.school_id:
        origin_scope = (
            "same_school"
            if event.actor.school_id == resource.owner.school_id
            else "external_school"
        )
    subject = (
        resource.subject
        if resource.subject_id
        and resource.subject.school_id == event.actor.school_id
        else None
    )
    return LegacyMappingPlan(
        event_name="resource.center.opened",
        payload={
            "resource_type": resource.resource_type,
            "visibility": resource.visibility,
            "origin_scope": origin_scope,
        },
        kwargs={
            "target_student": event.actor,
            "class_group": event.class_group,
            "subject": subject,
            "object_type": "resource_center",
            "object_id": resource.id,
            "object_version": _version("resource", resource),
        },
    )


def _pretest_mapping(event: LearningEvent, metadata: dict):
    if (
        event.event_type != LearningEvent.EventType.ANSWER_SUBMIT
        or event.object_type != "pretest_paper"
    ):
        return None
    submission_id = _integer(metadata.get("submission"))
    submission = (
        PretestSubmission.objects.select_related("student", "subject", "paper")
        .filter(pk=submission_id, student=event.actor)
        .first()
    )
    if submission is None:
        return "pretest_submission_missing"
    answers = submission.answers if isinstance(submission.answers, dict) else {}
    return LegacyMappingPlan(
        event_name="pretest.submitted",
        payload={
            "paper_kind": submission.paper.kind,
            "paper_version": submission.paper.version,
            "submission_id": submission.id,
            "answer_count": len(answers),
            "score_raw": float(submission.score or 0),
        },
        kwargs={
            "target_student": event.actor,
            "class_group": event.class_group,
            "subject": submission.subject,
            "object_type": "pretest_paper",
            "object_id": submission.paper_id,
            "object_version": f"paper-v{submission.paper.version}",
        },
    )


def _lesson_mapping(event: LearningEvent, metadata: dict):
    if event.event_type == LearningEvent.EventType.LESSON_ENTER:
        lesson = (
            Lesson.objects.select_related("course__subject", "course__teacher")
            .filter(pk=_integer(event.object_id))
            .first()
        )
        if lesson is None:
            return "lesson_missing"
        return LegacyMappingPlan(
            event_name="lesson.entered",
            payload={"entrypoint": "migration"},
            kwargs={
                "target_student": event.actor,
                "class_group": event.class_group,
                "subject": lesson.course.subject,
                "course": lesson.course,
                "lesson": lesson,
                "object_type": "lesson",
                "object_id": lesson.id,
                "object_version": _version("lesson", lesson),
            },
        )
    action = str(metadata.get("action") or "")
    if event.object_type != "lesson_step" or action not in {
        "step_enter",
        "step_complete",
    }:
        return None
    step = (
        LessonStep.objects.select_related(
            "lesson__course__subject", "lesson__course__teacher"
        )
        .filter(pk=_integer(event.object_id))
        .first()
    )
    if step is None:
        return "lesson_step_missing"
    event_name = (
        "lesson.step.entered" if action == "step_enter" else "lesson.step.completed"
    )
    payload = {"step_type": step.step_type}
    if event_name == "lesson.step.completed":
        payload["completion_source"] = "migration"
    return LegacyMappingPlan(
        event_name=event_name,
        payload=payload,
        kwargs={
            "target_student": event.actor,
            "class_group": event.class_group,
            "subject": step.lesson.course.subject,
            "course": step.lesson.course,
            "lesson": step.lesson,
            "lesson_step": step,
            "object_type": "lesson_step",
            "object_id": step.id,
            "object_version": _version("lesson-step", step),
        },
    )


def _chat_message_mapping(event: LearningEvent, metadata: dict):
    if (
        event.event_type != LearningEvent.EventType.CHAT_MESSAGE
        or metadata.get("action") != "classroom_chat_message"
    ):
        return None
    message = (
        ClassroomChatMessage.objects.select_related(
            "sender", "thread__session__course__subject", "thread__session__lesson"
        )
        .filter(pk=_integer(event.object_id), sender=event.actor)
        .first()
    )
    if message is None:
        return "chat_message_missing"
    session = message.thread.session
    return LegacyMappingPlan(
        event_name="chat.message.sent",
        payload={
            "room_type": message.thread.room_type,
            "moderation_status": message.moderation_status,
            "severity": message.severity,
            "content_length": len(message.content),
        },
        kwargs={
            "target_student": (
                event.actor if event.actor.role == event.actor.Role.STUDENT else None
            ),
            "class_group": session.class_group,
            "subject": session.course.subject,
            "course": session.course,
            "lesson": session.lesson,
            "classroom_session": session,
            "object_type": "classroom_chat_message",
            "object_id": message.id,
            "object_version": f"chat-message:{message.id}",
        },
    )


def _acknowledgement_mapping(event: LearningEvent, metadata: dict):
    action = str(metadata.get("action") or "")
    if action == "classroom_chat_moderation_feedback_ack":
        message = (
            ClassroomChatMessage.objects.select_related(
                "thread__session__course__subject", "thread__session__lesson"
            )
            .filter(pk=_integer(event.object_id), sender=event.actor)
            .first()
        )
        if message is None:
            return "chat_feedback_missing"
        session = message.thread.session
        return LegacyMappingPlan(
            event_name="intervention.acknowledged",
            payload={
                "intervention_type": "chat_moderation",
                "action": str(metadata.get("moderation_action") or "acknowledged"),
                "points": abs(_number(metadata.get("deduction_points"))),
            },
            kwargs={
                "target_student": event.actor,
                "class_group": session.class_group,
                "subject": session.course.subject,
                "course": session.course,
                "lesson": session.lesson,
                "classroom_session": session,
                "object_type": "classroom_chat_message",
                "object_id": message.id,
                "object_version": f"ack:chat:{message.id}",
            },
        )
    if action not in {
        "classroom_score_feedback_ack",
        "quick_answer_score_feedback_ack",
    }:
        return None
    activity = (
        ClassroomActivity.objects.select_related(
            "session__course__subject", "session__lesson"
        )
        .filter(pk=_integer(event.object_id))
        .first()
    )
    if activity is None:
        return "score_feedback_activity_missing"
    session = activity.session
    return LegacyMappingPlan(
        event_name="intervention.acknowledged",
        payload={
            "intervention_type": "score_feedback",
            "action": str(metadata.get("command") or "score_feedback"),
            "points": abs(_number(metadata.get("score", event.score))),
        },
        kwargs={
            "target_student": event.actor,
            "class_group": session.class_group,
            "subject": session.course.subject,
            "course": session.course,
            "lesson": session.lesson,
            "classroom_session": session,
            "object_type": "classroom_activity",
            "object_id": activity.id,
            "object_version": f"ack:activity:{activity.id}",
        },
    )


def _generic_interaction_mapping(event: LearningEvent, metadata: dict):
    if metadata.get("action") != "classroom_activity_response":
        return None
    command = str(metadata.get("command") or "")
    if command in {"sign_in", "quick_answer"}:
        return "opportunity_required"
    activity = (
        ClassroomActivity.objects.select_related(
            "session__course__subject", "session__lesson"
        )
        .filter(pk=_integer(event.object_id))
        .first()
    )
    if activity is None:
        return "classroom_activity_missing"
    session = activity.session
    content = str(metadata.get("content") or "")[:1000]
    return LegacyMappingPlan(
        event_name="classroom.interaction.responded",
        payload={
            "response_type": str(metadata.get("response_type") or command or "activity"),
            "command": command or activity.activity_type,
            "content_length": len(content),
        },
        kwargs={
            "target_student": event.actor,
            "class_group": session.class_group,
            "subject": session.course.subject,
            "course": session.course,
            "lesson": session.lesson,
            "classroom_session": session,
            "object_type": "classroom_activity",
            "object_id": activity.id,
            "object_version": _version("classroom-activity", activity),
        },
    )


def _classroom_control_mapping(event: LearningEvent, metadata: dict):
    if event.event_type != LearningEvent.EventType.TEACHER_INTERVENTION:
        return None
    action = str(metadata.get("action") or "")
    if not (
        action in {
            "step_opened",
            "step_locked",
            "step_closed",
            "session_started",
            "session_restarted",
            "session_finished",
            "activity_opened",
            "activity_closed",
        }
        or action.startswith("command_")
    ):
        return None
    session = (
        ClassroomSession.objects.select_related("course__subject", "lesson", "class_group")
        .filter(pk=_integer(metadata.get("session")))
        .first()
    )
    if session is None:
        return "classroom_session_missing"
    activity = None
    step = None
    object_kind = "classroom_session"
    object_id = session.id
    if event.object_type == "classroom_activity":
        activity = ClassroomActivity.objects.filter(
            pk=_integer(event.object_id), session=session
        ).first()
        if activity is None:
            return "classroom_activity_missing"
        object_kind = "classroom_activity"
        object_id = activity.id
    elif event.object_type == "lesson_step":
        step = LessonStep.objects.filter(
            pk=_integer(event.object_id), lesson=session.lesson
        ).first()
        if step is None:
            return "lesson_step_missing"
        object_kind = "lesson_step"
        object_id = step.id
    return LegacyMappingPlan(
        event_name="classroom.control.executed",
        payload={
            "action": action,
            "object_kind": object_kind,
            "activity_type": str(metadata.get("activity_type") or ""),
            "step_status": str(metadata.get("step_status") or ""),
            "submission_locked": bool(metadata.get("submission_locked")),
            "has_layered_questions": bool(metadata.get("has_layered_questions")),
        },
        kwargs={
            "class_group": session.class_group,
            "subject": session.course.subject,
            "course": session.course,
            "lesson": session.lesson,
            "classroom_session": session,
            "lesson_step": step,
            "object_type": object_kind,
            "object_id": object_id,
            "object_version": "legacy-v1",
        },
    )


MAPPERS = (
    _resource_mapping,
    _pretest_mapping,
    _lesson_mapping,
    _chat_message_mapping,
    _acknowledgement_mapping,
    _generic_interaction_mapping,
    _classroom_control_mapping,
)


def build_legacy_mapping_plan(event: LearningEvent):
    metadata = _metadata(event)
    for mapper in MAPPERS:
        result = mapper(event, metadata)
        if result is not None:
            return result
    return "unsupported_legacy_semantics"


def backfill_legacy_event(
    event: LearningEvent, *, dry_run: bool = False
) -> LegacyBackfillResult:
    if hasattr(event, "analytics_event_v2"):
        return LegacyBackfillResult(
            status="duplicate", event_name=event.analytics_event_v2.event_name
        )
    plan = build_legacy_mapping_plan(event)
    if isinstance(plan, str):
        if not dry_run:
            record_legacy_unmapped_event(
                legacy_event=event,
                event_id=deterministic_backfill_event_id(event.id, "legacy.unmapped"),
                reason_code=plan,
                mapping_version=MAPPING_VERSION,
            )
        return LegacyBackfillResult(
            status="unmapped", event_name="legacy.unmapped", reason_code=plan
        )
    validate_event_payload(plan.event_name, "1.0", plan.payload)
    if dry_run:
        return LegacyBackfillResult(status="mapped", event_name=plan.event_name)
    try:
        result = backfill_existing_learning_event(
            legacy_event=event,
            event_id=deterministic_backfill_event_id(event.id, plan.event_name),
            event_name=plan.event_name,
            payload=plan.payload,
            **plan.kwargs,
        )
    except EventWriteError as exc:
        reason_code = f"mapping_failed_{exc.code}"[:64]
        record_legacy_unmapped_event(
            legacy_event=event,
            event_id=deterministic_backfill_event_id(event.id, "legacy.unmapped"),
            reason_code=reason_code,
            mapping_version=MAPPING_VERSION,
        )
        return LegacyBackfillResult(
            status="unmapped",
            event_name="legacy.unmapped",
            reason_code=reason_code,
        )
    return LegacyBackfillResult(
        status="duplicate" if result.duplicate else "mapped",
        event_name=plan.event_name,
    )
