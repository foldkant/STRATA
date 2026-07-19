from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from learning.models import LearningEvent
from learning_analytics.models import LearningEventV2, ParticipationPointLedger
from learning_analytics.schemas.registry import (
    EventPayloadValidationError,
    validate_event_payload,
)
from learning_analytics.services.event_ingestion import (
    EventIngestionError,
    event_source_for_actor,
    ingest_learning_event,
)
from learning_analytics.services.participation_points import (
    ParticipationPointError,
    record_participation_points,
)
from school.models import StudentProfile


class EventWriteError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class EventWriteResult:
    legacy_event: LearningEvent
    analytics_event: LearningEventV2 | None
    write_mode: str
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class PointAdjustmentResult:
    event_write: EventWriteResult | None
    ledger_entry: ParticipationPointLedger | None
    requested_score: Decimal
    applied_delta: Decimal
    balance_after: Decimal


def learning_event_write_mode() -> str:
    return str(
        getattr(settings, "LEARNING_EVENT_WRITE_MODE", "dual_required")
        or "dual_required"
    ).strip()


def _decimal_score(value, *, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise EventWriteError(
            "score_invalid",
            f"{field_name} 必须是有效数值。",
        ) from exc
    if not result.is_finite() or abs(result) > Decimal("100"):
        raise EventWriteError(
            "score_out_of_range",
            f"{field_name} 的绝对值不能超过 100。",
        )
    return result


@transaction.atomic
def record_learning_event(
    *,
    actor,
    target_student=None,
    event_name: str,
    payload: dict,
    legacy_event_type: str,
    legacy_actor=None,
    class_group=None,
    subject=None,
    course=None,
    lesson=None,
    classroom_session=None,
    lesson_step=None,
    object_type: str = "",
    object_id: str | int = "",
    object_version: str = "",
    opportunity_id=None,
    attempt_id=None,
    duration_ms: int = 0,
    legacy_score=None,
    legacy_metadata: dict | None = None,
    occurred_at=None,
    event_id=None,
    schema_version: str = "1.0",
    source_override: str | None = None,
) -> EventWriteResult:
    mode = learning_event_write_mode()
    if mode not in {"dual_required", "v1_only"}:
        raise EventWriteError("write_mode_invalid", "学习事件写入模式不正确。")
    if not getattr(actor, "school_id", None):
        raise EventWriteError("actor_school_required", "事件执行人必须绑定学校。")

    occurred_at = occurred_at or timezone.now()
    received_at = timezone.now()
    event_id = uuid.UUID(str(event_id)) if event_id else uuid.uuid4()
    object_id_text = str(object_id or "")
    metadata = dict(legacy_metadata or {})
    metadata["analytics_write_mode"] = mode
    if mode == "dual_required":
        metadata.update(
            {
                "analytics_dual_write": True,
                "analytics_event_id": str(event_id),
                "analytics_event_name": event_name,
                "analytics_schema_version": schema_version,
            }
        )

    try:
        normalized_payload = validate_event_payload(
            event_name,
            schema_version,
            payload,
        )
    except EventPayloadValidationError as exc:
        raise EventWriteError("schema_invalid", str(exc)) from exc

    legacy_event = LearningEvent.objects.create(
        actor=legacy_actor or target_student or actor,
        class_group=class_group,
        course=course,
        lesson=lesson,
        event_type=legacy_event_type,
        object_type=str(object_type or "")[:64],
        object_id=object_id_text[:64],
        duration_ms=max(int(duration_ms or 0), 0),
        score=legacy_score,
        metadata=metadata,
        occurred_at=occurred_at,
    )
    if mode == "v1_only":
        return EventWriteResult(
            legacy_event=legacy_event,
            analytics_event=None,
            write_mode=mode,
        )

    event_data = {
        "event_id": event_id,
        "event_name": event_name,
        "schema_version": schema_version,
        "source": source_override or event_source_for_actor(actor),
        "target_student_id": target_student.id if target_student else None,
        "class_id": class_group.id if class_group else None,
        "subject_id": subject.id if subject else None,
        "course_id": course.id if course else None,
        "lesson_id": lesson.id if lesson else None,
        "session_id": classroom_session.id if classroom_session else None,
        "step_id": lesson_step.id if lesson_step else None,
        "object_type": str(object_type or ""),
        "object_id": object_id_text,
        "object_version": str(object_version or ""),
        "opportunity_id": opportunity_id,
        "attempt_id": attempt_id,
        "client_occurred_at": occurred_at,
        "duration_ms": max(int(duration_ms or 0), 0),
        "payload": normalized_payload,
    }
    try:
        result = ingest_learning_event(
            actor=actor,
            event_data=event_data,
            received_at=received_at,
            legacy_event=legacy_event,
            trusted_source=source_override,
        )
    except EventIngestionError as exc:
        raise EventWriteError(exc.code, exc.message) from exc

    analytics_event = LearningEventV2.objects.get(
        school=actor.school,
        event_id=result["event_id"],
    )
    if result["status"] == "duplicate":
        legacy_event.delete()
        if analytics_event.legacy_event_id is None:
            raise EventWriteError(
                "duplicate_mapping_missing",
                "重复 V2 事件缺少对应的 V1 追溯记录。",
            )
        return EventWriteResult(
            legacy_event=analytics_event.legacy_event,
            analytics_event=analytics_event,
            write_mode=mode,
            duplicate=True,
        )
    return EventWriteResult(
        legacy_event=legacy_event,
        analytics_event=analytics_event,
        write_mode=mode,
    )


@transaction.atomic
def record_classroom_point_adjustment(
    *,
    teacher,
    student_profile: StudentProfile,
    classroom_session,
    object_type: str,
    object_id: str | int,
    reason_code: str,
    requested_score,
    previous_score=0,
    previous_event_action: str = "",
    legacy_metadata: dict | None = None,
    insufficient_policy: str = "clamp",
    occurred_at=None,
) -> PointAdjustmentResult:
    if insufficient_policy not in {"clamp", "reject"}:
        raise EventWriteError("point_policy_invalid", "积分余额处理策略不正确。")
    profile = (
        StudentProfile.objects.select_for_update(of=("self",))
        .select_related("user", "class_group")
        .get(pk=student_profile.pk)
    )
    requested = _decimal_score(requested_score, field_name="本次评分")
    if previous_event_action:
        previous_event = (
            LearningEvent.objects.filter(
                actor=profile.user,
                object_type=object_type,
                object_id=str(object_id),
                metadata__action=previous_event_action,
            )
            .order_by("-occurred_at", "-id")
            .first()
        )
        previous_score = previous_event.score if previous_event else 0
    previous = _decimal_score(previous_score, field_name="上次评分")
    current = Decimal(str(profile.score or 0)).quantize(Decimal("0.01"))
    if not current.is_finite() or current < 0:
        raise EventWriteError(
            "point_cache_invalid",
            "学生积分缓存不合法，请先执行积分对账。",
        )
    target = current - previous + requested
    if target < 0:
        if insufficient_policy == "reject":
            raise EventWriteError(
                "point_balance_insufficient",
                "学生当前积分不足，无法完成本次扣分。",
            )
        target = Decimal("0.00")
    applied_delta = target - current
    if applied_delta == 0:
        return PointAdjustmentResult(
            event_write=None,
            ledger_entry=None,
            requested_score=requested,
            applied_delta=applied_delta,
            balance_after=target,
        )

    metadata = dict(legacy_metadata or {})
    metadata.update(
        {
            "previous_score": float(previous),
            "requested_score": float(requested),
            "applied_point_delta": float(applied_delta),
        }
    )
    absolute_delta = abs(applied_delta)
    intensity = (
        "high" if absolute_delta >= 5 else "medium" if absolute_delta >= 3 else "low"
    )
    event_write = record_learning_event(
        actor=teacher,
        target_student=profile.user,
        event_name="intervention.created",
        payload={
            "intervention_type": "participation_points",
            "reason_code": reason_code,
            "intensity": intensity,
        },
        legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
        legacy_actor=profile.user,
        class_group=profile.class_group,
        subject=classroom_session.course.subject,
        course=classroom_session.course,
        lesson=classroom_session.lesson,
        classroom_session=classroom_session,
        object_type=object_type,
        object_id=object_id,
        legacy_score=float(requested),
        legacy_metadata=metadata,
        occurred_at=occurred_at,
    )
    ledger_entry = None
    if event_write.analytics_event:
        try:
            ledger_entry, _ = record_participation_points(
                source_event=event_write.analytics_event,
                delta=applied_delta,
                reason_code=reason_code,
                awarded_by=teacher,
            )
        except ParticipationPointError as exc:
            raise EventWriteError(exc.code, exc.message) from exc
    else:
        profile.score = float(target)
        profile.save(update_fields=["score", "updated_at"])
    return PointAdjustmentResult(
        event_write=event_write,
        ledger_entry=ledger_entry,
        requested_score=requested,
        applied_delta=applied_delta,
        balance_after=target,
    )


def reconcile_v1_v2_events(*, school=None, max_examples: int = 50) -> dict:
    legacy = LearningEvent.objects.filter(metadata__analytics_dual_write=True)
    analytics = LearningEventV2.objects.filter(legacy_event__isnull=False)
    if school is not None:
        legacy = legacy.filter(actor__school=school)
        analytics = analytics.filter(school=school)

    mapped_legacy_ids = analytics.values_list("legacy_event_id", flat=True)
    missing = legacy.exclude(pk__in=mapped_legacy_ids)
    mismatch_count = 0
    mismatches = []
    for event in analytics.select_related("legacy_event").iterator():
        metadata = (
            event.legacy_event.metadata
            if isinstance(event.legacy_event.metadata, dict)
            else {}
        )
        if (
            str(metadata.get("analytics_event_id") or "") != str(event.event_id)
            or metadata.get("analytics_event_name") != event.event_name
        ):
            mismatch_count += 1
            if len(mismatches) < max_examples:
                mismatches.append(
                    {
                        "legacy_event_id": event.legacy_event_id,
                        "analytics_event_id": str(event.event_id),
                    }
                )
    missing_ids = list(missing.values_list("id", flat=True)[:max_examples])
    missing_count = missing.count()
    return {
        "legacy_dual_write_count": legacy.count(),
        "analytics_mapped_count": analytics.count(),
        "missing_v2_count": missing_count,
        "mapping_mismatch_count": mismatch_count,
        "missing_v2_examples": missing_ids,
        "mapping_mismatch_examples": mismatches,
        "consistent": missing_count == 0 and mismatch_count == 0,
    }
