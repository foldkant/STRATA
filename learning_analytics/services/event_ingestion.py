from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import User
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Subject,
)
from learning_analytics.models import LearningEventRejection, LearningEventV2
from learning_analytics.schemas.registry import EventSchemaSpec, get_event_schema_spec
from learning_analytics.services.access_audit import teacher_has_class_scope
from learning_analytics.services.assessment_results import (
    AssessmentResultError,
    record_assessment_result,
)
from learning_analytics.services.opportunities import (
    OpportunityError,
    apply_event_to_opportunity,
    release_learning_opportunities,
    resolve_event_opportunity,
    withdraw_released_opportunities,
)
from learning_analytics.services.quarantine import (
    encrypt_quarantined_envelope,
    quarantine_retention_deadline,
)
from learning_analytics.services.schema_registry import ensure_event_schema_definition
from school.models import ClassGroup


class EventIngestionError(Exception):
    def __init__(self, code: str, message: str, *, errors: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors = errors or []


def event_source_for_actor(actor) -> str:
    if actor.role == User.Role.STUDENT and not actor.is_superuser and actor.school_id:
        return "student-web"
    if actor.role == User.Role.TEACHER and not actor.is_superuser and actor.school_id:
        return "teacher-web"
    raise EventIngestionError(
        "role_not_allowed", "只有教师和学生客户端可以提交学习事件。"
    )


def _canonical_value(value):
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _sha256_json(value: dict) -> str:
    raw = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_event_idempotency_key(
    *, school_id: int, actor_id: int, source: str, event_data: dict
) -> str:
    client_session_id = event_data.get("client_session_id")
    client_sequence = event_data.get("client_sequence")
    if client_session_id is not None and client_sequence is not None:
        identity = f"session:{client_session_id}:{client_sequence}"
    else:
        identity = f"event:{event_data['event_id']}"
    return hashlib.sha256(
        f"v1:{school_id}:{actor_id}:{source}:{identity}".encode()
    ).hexdigest()


def _event_fingerprint(
    *, source: str, target_student, context: dict, event_data: dict
) -> str:
    return _sha256_json(
        {
            "event_name": event_data["event_name"],
            "schema_version": event_data["schema_version"],
            "source": source,
            "target_student_id": target_student.id if target_student else None,
            "class_id": getattr(context.get("class_group"), "id", None),
            "subject_id": getattr(context.get("subject"), "id", None),
            "course_id": getattr(context.get("course"), "id", None),
            "lesson_id": getattr(context.get("lesson"), "id", None),
            "session_id": getattr(context.get("classroom_session"), "id", None),
            "step_id": getattr(context.get("lesson_step"), "id", None),
            "object_type": event_data.get("object_type", ""),
            "object_id": event_data.get("object_id", ""),
            "object_version": event_data.get("object_version", ""),
            "opportunity_id": event_data.get("opportunity_id"),
            "attempt_id": event_data.get("attempt_id"),
            "client_occurred_at": event_data["client_occurred_at"],
            "duration_ms": event_data.get("duration_ms"),
            "payload": event_data["payload"],
        }
    )


def _not_found(label: str) -> EventIngestionError:
    return EventIngestionError("context_not_found", f"{label}不存在或不属于当前学校。")


def _resolve_context(
    *, actor, event_data: dict, spec: EventSchemaSpec, trusted_source: str | None = None
) -> tuple[object | None, dict]:
    school = actor.school
    source = trusted_source or event_source_for_actor(actor)
    if trusted_source and (
        trusted_source not in {"server", "worker", "migration"}
        or trusted_source not in spec.allowed_sources
    ):
        raise EventIngestionError(
            "trusted_source_forbidden",
            "内部事件来源未在事件模式中登记。",
        )
    if not trusted_source and source not in spec.allowed_sources:
        raise EventIngestionError(
            "source_forbidden",
            "事件来源未在事件模式中登记。",
        )

    if event_data.get("event_name") == "attendance.recorded":
        payload = event_data.get("payload") or {}
        if actor.role == actor.Role.STUDENT and (
            payload.get("recorded_by") != "student"
            or payload.get("attendance_status") != "signed"
        ):
            raise EventIngestionError(
                "attendance_student_payload_forbidden",
                "学生只能记录本人的自助签到，其他考勤状态必须由教师确认。",
            )
        if actor.role == actor.Role.TEACHER and payload.get("recorded_by") != "teacher":
            raise EventIngestionError(
                "attendance_teacher_payload_invalid",
                "教师考勤事件必须标记为教师记录。",
            )
        if actor.role not in {actor.Role.STUDENT, actor.Role.TEACHER}:
            raise EventIngestionError(
                "attendance_actor_forbidden",
                "只有学生本人或任课教师可以记录考勤状态。",
            )

    classroom_session = None
    if event_data.get("session_id"):
        classroom_session = (
            ClassroomSession.objects.select_related(
                "class_group", "course__subject", "lesson"
            )
            .filter(pk=event_data["session_id"], school=school)
            .first()
        )
        if classroom_session is None:
            raise _not_found("课堂")

    lesson_step = None
    if event_data.get("step_id"):
        lesson_step = (
            LessonStep.objects.select_related(
                "lesson__course__subject", "lesson__course__teacher"
            )
            .filter(pk=event_data["step_id"], lesson__course__teacher__school=school)
            .first()
        )
        if lesson_step is None:
            raise _not_found("课时环节")

    lesson = None
    if event_data.get("lesson_id"):
        lesson = (
            Lesson.objects.select_related("course__subject", "course__teacher")
            .filter(pk=event_data["lesson_id"], course__teacher__school=school)
            .first()
        )
        if lesson is None:
            raise _not_found("课时")

    course = None
    if event_data.get("course_id"):
        course = (
            Course.objects.select_related("subject", "teacher")
            .filter(pk=event_data["course_id"], teacher__school=school)
            .first()
        )
        if course is None:
            raise _not_found("课程")

    derived_lessons = [
        item
        for item in (
            lesson,
            lesson_step.lesson if lesson_step else None,
            classroom_session.lesson if classroom_session else None,
        )
        if item
    ]
    if derived_lessons and len({item.id for item in derived_lessons}) > 1:
        raise EventIngestionError("context_mismatch", "课时、环节或课堂上下文不一致。")
    lesson = derived_lessons[0] if derived_lessons else None

    derived_courses = [
        item
        for item in (
            course,
            lesson.course if lesson else None,
            classroom_session.course if classroom_session else None,
        )
        if item
    ]
    if derived_courses and len({item.id for item in derived_courses}) > 1:
        raise EventIngestionError("context_mismatch", "课程、课时或课堂上下文不一致。")
    course = derived_courses[0] if derived_courses else None

    class_group = None
    if event_data.get("class_id"):
        class_group = ClassGroup.objects.filter(
            pk=event_data["class_id"], school=school
        ).first()
        if class_group is None:
            raise _not_found("班级")
    if classroom_session:
        if class_group and class_group.id != classroom_session.class_group_id:
            raise EventIngestionError("context_mismatch", "班级与课堂上下文不一致。")
        class_group = classroom_session.class_group

    subject = None
    if event_data.get("subject_id"):
        subject = Subject.objects.filter(
            pk=event_data["subject_id"], school=school
        ).first()
        if subject is None:
            raise _not_found("学科")
    if course and course.subject_id:
        if subject and subject.id != course.subject_id:
            raise EventIngestionError("context_mismatch", "学科与课程上下文不一致。")
        subject = course.subject

    target_student = None
    requested_target_id = event_data.get("target_student_id")
    if actor.role == User.Role.STUDENT:
        peer_evaluation_target = bool(
            trusted_source == "server"
            and event_data.get("event_name") == "evaluation.rating.submitted"
            and event_data.get("payload", {}).get("rater_role") == "peer"
        )
        if (
            requested_target_id
            and requested_target_id != actor.id
            and not peer_evaluation_target
        ):
            raise EventIngestionError(
                "target_forbidden", "学生只能提交归属于自己的学习事件。"
            )
        try:
            profile = actor.student_profile
        except ObjectDoesNotExist as exc:
            raise EventIngestionError(
                "student_profile_missing", "学生档案不存在。"
            ) from exc
        if requested_target_id and requested_target_id != actor.id:
            target_student = User.objects.filter(
                pk=requested_target_id,
                school=school,
                role=User.Role.STUDENT,
                is_active=True,
                student_profile__class_group=profile.class_group,
            ).first()
            if target_student is None:
                raise EventIngestionError(
                    "target_forbidden", "互评目标必须是同班在籍学生。"
                )
        else:
            target_student = actor
        if not class_group:
            class_group = profile.class_group
        if class_group and profile.class_group_id != class_group.id:
            raise EventIngestionError("class_scope_forbidden", "学生不属于该事件班级。")
        if (
            course
            and class_group
            and not CourseClass.objects.filter(
                course=course, class_group=class_group
            ).exists()
        ):
            raise EventIngestionError(
                "course_scope_forbidden", "课程未向学生所在班级发布。"
            )
    else:
        if requested_target_id:
            target_student = User.objects.filter(
                pk=requested_target_id,
                school=school,
                role=User.Role.STUDENT,
                is_active=True,
            ).first()
            if target_student is None:
                raise _not_found("目标学生")
        if not class_group:
            raise EventIngestionError("class_required", "教师事件必须指定任教班级。")
        if not teacher_has_class_scope(teacher=actor, class_group=class_group):
            raise EventIngestionError(
                "class_scope_forbidden", "教师不在该班级有效任课范围内。"
            )
        if course and course.teacher_id != actor.id:
            raise EventIngestionError(
                "course_scope_forbidden", "教师只能为自己的课程提交事件。"
            )

    if spec.requires_target_student and target_student is None:
        raise EventIngestionError("target_required", "该事件必须指定证据归属学生。")

    return target_student, {
        "class_group": class_group,
        "subject": subject,
        "course": course,
        "lesson": lesson,
        "classroom_session": classroom_session,
        "lesson_step": lesson_step,
        "source": source,
    }


def _quality_flags(*, occurred_at, received_at) -> list[str]:
    flags = []
    if occurred_at > received_at + timedelta(minutes=10):
        flags.append("client_clock_ahead")
    delay = received_at - occurred_at
    if delay > timedelta(days=7):
        flags.append("very_late_arrival_7d")
    elif delay > timedelta(hours=24):
        flags.append("late_arrival_24h")
    return flags


def _model_validation_errors(exc: ValidationError) -> list[dict]:
    if hasattr(exc, "message_dict"):
        return [
            {"field": field, "message": str(message)}
            for field, messages in exc.message_dict.items()
            for message in messages
        ]
    return [{"field": "event", "message": str(message)} for message in exc.messages]


def ingest_learning_event(
    *,
    actor,
    event_data: dict,
    received_at=None,
    legacy_event=None,
    synthetic_run=None,
    trusted_source: str | None = None,
) -> dict:
    received_at = received_at or timezone.now()
    spec = get_event_schema_spec(event_data["event_name"], event_data["schema_version"])
    definition = ensure_event_schema_definition(
        event_data["event_name"], event_data["schema_version"]
    )
    target_student, context = _resolve_context(
        actor=actor,
        event_data=event_data,
        spec=spec,
        trusted_source=trusted_source,
    )
    source = context.pop("source")
    idempotency_key = build_event_idempotency_key(
        school_id=actor.school_id,
        actor_id=actor.id,
        source=source,
        event_data=event_data,
    )
    fingerprint = _event_fingerprint(
        source=source,
        target_student=target_student,
        context=context,
        event_data=event_data,
    )
    existing = (
        LearningEventV2.objects.filter(school=actor.school)
        .filter(Q(event_id=event_data["event_id"]) | Q(idempotency_key=idempotency_key))
        .first()
    )
    if existing:
        if existing.event_fingerprint != fingerprint:
            raise EventIngestionError(
                "idempotency_conflict",
                "相同事件标识或客户端序号对应了不同内容。",
            )
        return {
            "status": "duplicate",
            "event_id": str(existing.event_id),
            "server_received_at": existing.server_received_at,
            "quality_errors": existing.quality_errors,
        }

    payload = event_data["payload"]
    quality_errors = _quality_flags(
        occurred_at=event_data["client_occurred_at"],
        received_at=received_at,
    )
    opportunity = None
    if spec.requires_opportunity:
        try:
            opportunity, opportunity_flags = resolve_event_opportunity(
                actor=actor,
                target_student=target_student,
                context=context,
                event_data=event_data,
            )
        except OpportunityError as exc:
            raise EventIngestionError(exc.code, exc.message) from exc
        quality_errors.extend(
            flag for flag in opportunity_flags if flag not in quality_errors
        )
    event = LearningEventV2(
        event_id=event_data["event_id"],
        idempotency_key=idempotency_key,
        event_fingerprint=fingerprint,
        schema_definition=definition,
        event_name=event_data["event_name"],
        schema_version=event_data["schema_version"],
        source=source,
        client_version=event_data.get("client_version", ""),
        legacy_event=legacy_event,
        actor=actor,
        target_student=target_student,
        school=actor.school,
        synthetic_run=synthetic_run,
        object_type=event_data.get("object_type", ""),
        object_id=event_data.get("object_id", ""),
        object_version=event_data.get("object_version", ""),
        opportunity_id=opportunity.opportunity_id if opportunity else None,
        opportunity_record=opportunity,
        attempt_id=event_data.get("attempt_id"),
        client_session_id=event_data.get("client_session_id"),
        client_sequence=event_data.get("client_sequence"),
        client_occurred_at=event_data["client_occurred_at"],
        server_received_at=received_at,
        duration_ms=event_data.get("duration_ms"),
        score_raw=(
            payload.get("score_raw")
            if event_data["event_name"] == "item.graded"
            else None
        ),
        score_max=(
            payload.get("score_max")
            if event_data["event_name"] == "item.graded"
            else None
        ),
        delivered_band=opportunity.delivered_band if opportunity else "",
        evaluation_version=payload.get("evaluation_version", ""),
        privacy_class=spec.privacy_class,
        analysis_unit=spec.analysis_unit,
        payload=payload,
        quality_status=LearningEventV2.QualityStatus.ACCEPTED,
        quality_errors=quality_errors,
        **context,
    )
    derived_result = {}
    try:
        with transaction.atomic():
            event.save()
            if event.event_name == "content.released":
                derived_result = release_learning_opportunities(event)
            elif event.event_name == "content.withdrawn":
                derived_result = withdraw_released_opportunities(event)
            elif opportunity:
                derived_result = apply_event_to_opportunity(
                    event=event,
                    opportunity=opportunity,
                )
                if event.event_name == "item.graded":
                    result_fact, result_created = record_assessment_result(
                        event=event,
                        opportunity=opportunity,
                    )
                    derived_result.update(
                        {
                            "assessment_result_created": int(result_created),
                            "assessment_result_mature": result_fact.is_mature,
                            "assessment_result_version": result_fact.grade_version,
                        }
                    )
    except IntegrityError:
        existing = (
            LearningEventV2.objects.filter(school=actor.school)
            .filter(Q(event_id=event.event_id) | Q(idempotency_key=idempotency_key))
            .first()
        )
        if existing and existing.event_fingerprint == fingerprint:
            return {
                "status": "duplicate",
                "event_id": str(existing.event_id),
                "server_received_at": existing.server_received_at,
                "quality_errors": existing.quality_errors,
            }
        raise EventIngestionError("idempotency_conflict", "事件幂等约束发生冲突。")
    except ValidationError as exc:
        raise EventIngestionError(
            "context_invalid",
            "事件上下文校验失败。",
            errors=_model_validation_errors(exc),
        ) from exc
    except OpportunityError as exc:
        raise EventIngestionError(exc.code, exc.message) from exc
    except AssessmentResultError as exc:
        raise EventIngestionError(exc.code, exc.message) from exc

    return {
        "status": "accepted",
        "event_id": str(event.event_id),
        "server_received_at": event.server_received_at,
        "quality_errors": quality_errors,
        **derived_result,
    }


def _safe_uuid(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def _safe_datetime(value):
    if isinstance(value, datetime):
        return value
    parsed = parse_datetime(str(value)) if value else None
    return parsed if parsed and timezone.is_aware(parsed) else None


def record_rejected_learning_event(
    *,
    actor,
    raw_envelope: dict,
    source: str,
    error_code: str,
    errors: list[dict],
    received_at=None,
) -> LearningEventRejection:
    received_at = received_at or timezone.now()
    encrypted = encrypt_quarantined_envelope(raw_envelope)
    event_id = _safe_uuid(raw_envelope.get("event_id"))
    client_session_id = _safe_uuid(raw_envelope.get("client_session_id"))
    client_sequence = raw_envelope.get("client_sequence")
    idempotency_key = ""
    if event_id:
        safe_data = {"event_id": event_id}
        if (
            client_session_id
            and isinstance(client_sequence, int)
            and client_sequence >= 0
        ):
            safe_data.update(
                {
                    "client_session_id": client_session_id,
                    "client_sequence": client_sequence,
                }
            )
        idempotency_key = build_event_idempotency_key(
            school_id=actor.school_id,
            actor_id=actor.id,
            source=source,
            event_data=safe_data,
        )
    return LearningEventRejection.objects.create(
        school=actor.school,
        actor=actor,
        event_id=event_id,
        idempotency_key=idempotency_key,
        event_name=str(raw_envelope.get("event_name") or "")[:128],
        schema_version=str(raw_envelope.get("schema_version") or "")[:16],
        source=source,
        client_occurred_at=_safe_datetime(raw_envelope.get("client_occurred_at")),
        server_received_at=received_at,
        error_code=error_code[:64],
        errors=errors,
        retention_expires_at=quarantine_retention_deadline(received_at),
        **encrypted,
    )
