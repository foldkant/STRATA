from __future__ import annotations

from learning.models import LearningEvent
from learning_analytics.services.dual_write import record_learning_event


def _subject(course):
    return course.subject if course and course.subject_id else None


def _object_version(prefix: str, instance) -> str:
    updated_at = getattr(instance, "updated_at", None)
    suffix = int(updated_at.timestamp()) if updated_at else instance.id
    return f"{prefix}:{suffix}"


def record_resource_center_opened(*, resource, student, profile, occurred_at=None):
    origin_scope = "unknown"
    if resource.owner.school_id and student.school_id:
        origin_scope = (
            "same_school"
            if resource.owner.school_id == student.school_id
            else "external_school"
        )
    return record_learning_event(
        actor=student,
        target_student=student,
        event_name="resource.center.opened",
        payload={
            "resource_type": resource.resource_type,
            "visibility": resource.visibility,
            "origin_scope": origin_scope,
        },
        legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
        class_group=profile.class_group,
        subject=(
            resource.subject
            if resource.subject_id and resource.subject.school_id == student.school_id
            else None
        ),
        object_type="resource_center",
        object_id=resource.id,
        object_version=_object_version("resource", resource),
        legacy_metadata={
            "action": "resource_center_opened",
            "title": resource.title,
            "resource_type": resource.resource_type,
            "visibility": resource.visibility,
            "source_school": (
                resource.owner.school.name if resource.owner.school_id else ""
            ),
        },
        occurred_at=occurred_at,
    )


def record_pretest_submitted(*, submission, profile, occurred_at=None):
    answers = submission.answers if isinstance(submission.answers, dict) else {}
    return record_learning_event(
        actor=submission.student,
        target_student=submission.student,
        event_name="pretest.submitted",
        payload={
            "paper_kind": submission.paper.kind,
            "paper_version": submission.paper.version,
            "submission_id": submission.id,
            "answer_count": len(answers),
            "score_raw": float(submission.score or 0),
        },
        legacy_event_type=LearningEvent.EventType.ANSWER_SUBMIT,
        class_group=profile.class_group,
        subject=submission.subject,
        object_type="pretest_paper",
        object_id=submission.paper_id,
        object_version=f"paper-v{submission.paper.version}",
        legacy_score=submission.score,
        legacy_metadata={
            "subject": submission.subject_id,
            "kind": submission.paper.kind,
            "submission": submission.id,
        },
        occurred_at=occurred_at or submission.submitted_at,
    )


def record_lesson_entered(*, student, profile, lesson, occurred_at=None):
    return record_learning_event(
        actor=student,
        target_student=student,
        event_name="lesson.entered",
        payload={"entrypoint": "student_workspace"},
        legacy_event_type=LearningEvent.EventType.LESSON_ENTER,
        class_group=profile.class_group,
        subject=_subject(lesson.course),
        course=lesson.course,
        lesson=lesson,
        object_type="lesson",
        object_id=lesson.id,
        object_version=_object_version("lesson", lesson),
        occurred_at=occurred_at,
    )


def record_lesson_step_entered(*, student, profile, step, occurred_at=None):
    return record_learning_event(
        actor=student,
        target_student=student,
        event_name="lesson.step.entered",
        payload={"step_type": step.step_type},
        legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
        class_group=profile.class_group,
        subject=_subject(step.lesson.course),
        course=step.lesson.course,
        lesson=step.lesson,
        lesson_step=step,
        object_type="lesson_step",
        object_id=step.id,
        object_version=_object_version("lesson-step", step),
        legacy_metadata={"action": "step_enter", "step_type": step.step_type},
        occurred_at=occurred_at,
    )


def record_lesson_step_completed(
    *, student, profile, step, duration_ms: int = 0, occurred_at=None
):
    return record_learning_event(
        actor=student,
        target_student=student,
        event_name="lesson.step.completed",
        payload={"step_type": step.step_type, "completion_source": "student"},
        legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
        class_group=profile.class_group,
        subject=_subject(step.lesson.course),
        course=step.lesson.course,
        lesson=step.lesson,
        lesson_step=step,
        object_type="lesson_step",
        object_id=step.id,
        object_version=_object_version("lesson-step", step),
        duration_ms=duration_ms,
        legacy_metadata={"action": "step_complete", "step_type": step.step_type},
        occurred_at=occurred_at,
    )


def record_classroom_interaction_response(
    *, student, profile, session, activity, response_type: str, command: str, content: str
):
    return record_learning_event(
        actor=student,
        target_student=student,
        event_name="classroom.interaction.responded",
        payload={
            "response_type": response_type,
            "command": command,
            "content_length": len(content),
        },
        legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
        class_group=profile.class_group,
        subject=_subject(session.course),
        course=session.course,
        lesson=session.lesson,
        classroom_session=session,
        object_type="classroom_activity",
        object_id=activity.id,
        object_version=_object_version("classroom-activity", activity),
        legacy_metadata={
            "action": "classroom_activity_response",
            "response_type": response_type,
            "command": command,
            "quick_answer": False,
            "activity_title": activity.title,
            "content": content,
        },
    )


def record_intervention_acknowledged(
    *, student, profile, session, object_type: str, object_id, intervention_type: str,
    action: str, points=0, legacy_score=None, legacy_metadata: dict | None = None,
    occurred_at=None
):
    return record_learning_event(
        actor=student,
        target_student=student,
        event_name="intervention.acknowledged",
        payload={
            "intervention_type": intervention_type,
            "action": action,
            "points": abs(float(points or 0)),
        },
        legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
        class_group=profile.class_group,
        subject=_subject(session.course),
        course=session.course,
        lesson=session.lesson,
        classroom_session=session,
        object_type=object_type,
        object_id=object_id,
        object_version=f"ack:{object_type}:{object_id}",
        legacy_score=legacy_score,
        legacy_metadata=legacy_metadata,
        occurred_at=occurred_at,
    )


def record_chat_message_sent(*, message, session):
    sender = message.sender
    return record_learning_event(
        actor=sender,
        target_student=sender if sender.role == sender.Role.STUDENT else None,
        event_name="chat.message.sent",
        payload={
            "room_type": message.thread.room_type,
            "moderation_status": message.moderation_status,
            "severity": message.severity,
            "content_length": len(message.content),
        },
        legacy_event_type=LearningEvent.EventType.CHAT_MESSAGE,
        class_group=session.class_group,
        subject=_subject(session.course),
        course=session.course,
        lesson=session.lesson,
        classroom_session=session,
        object_type="classroom_chat_message",
        object_id=message.id,
        object_version=f"chat-message:{message.id}",
        legacy_metadata={
            "action": "classroom_chat_message",
            "classroom_session": session.id,
            "thread": message.thread_id,
            "room_type": message.thread.room_type,
            "moderation_status": message.moderation_status,
            "severity": message.severity,
            "content_length": len(message.content),
        },
        occurred_at=message.created_at,
    )


def record_classroom_control_executed(
    *, teacher, session, action: str, activity=None, step=None, occurred_at=None
):
    object_kind = "classroom_session"
    target = session
    if activity is not None:
        object_kind = "classroom_activity"
        target = activity
    elif step is not None:
        object_kind = "lesson_step"
        target = step
    has_layered_questions = bool(
        step
        and isinstance(step.question_items, list)
        and any(
            isinstance(item, dict)
            and (
                str(item.get("target_layer") or "all") not in {"", "all"}
                or bool(item.get("use_layer_scores"))
            )
            for item in step.question_items
        )
    )
    return record_learning_event(
        actor=teacher,
        event_name="classroom.control.executed",
        payload={
            "action": action,
            "object_kind": object_kind,
            "activity_type": activity.activity_type if activity else "",
            "step_status": session.current_step_status,
            "submission_locked": session.submission_locked,
            "has_layered_questions": has_layered_questions,
        },
        legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
        class_group=session.class_group,
        subject=_subject(session.course),
        course=session.course,
        lesson=session.lesson,
        classroom_session=session,
        lesson_step=step,
        object_type=object_kind,
        object_id=target.id,
        object_version=_object_version(object_kind, target),
        legacy_metadata={
            "action": action,
            "session": session.id,
            "activity": activity.id if activity else None,
            "activity_type": activity.activity_type if activity else "",
            "step": step.id if step else None,
            "step_status": session.current_step_status,
            "submission_locked": session.submission_locked,
            "has_layered_questions": has_layered_questions,
        },
        occurred_at=occurred_at,
    )
