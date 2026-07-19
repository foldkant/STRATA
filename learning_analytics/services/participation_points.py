from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from learning_analytics.models import LearningEventV2, ParticipationPointLedger
from learning_analytics.services.access_audit import teacher_has_class_scope
from school.models import StudentProfile


class ParticipationPointError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _point_decimal(value) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ParticipationPointError(
            "point_delta_invalid",
            "积分增量必须是有效数值。",
        ) from exc
    if result == 0 or abs(result) > Decimal("100"):
        raise ParticipationPointError(
            "point_delta_out_of_range",
            "单次积分增减必须大于 0 且不超过 100。",
        )
    return result


@transaction.atomic
def record_participation_points(
    *,
    source_event: LearningEventV2,
    delta,
    reason_code: str,
    awarded_by,
    reversal_of: ParticipationPointLedger | None = None,
    academic_period: str = "",
) -> tuple[ParticipationPointLedger, bool]:
    existing = ParticipationPointLedger.objects.filter(
        source_event=source_event
    ).first()
    requested_delta = _point_decimal(delta)
    reason_code = str(reason_code or "").strip()[:64]
    academic_period = str(academic_period or "").strip()[:32]
    if existing:
        expected_reversal_id = reversal_of.pk if reversal_of else None
        if (
            existing.delta == requested_delta
            and existing.reason_code == reason_code
            and existing.awarded_by_id == awarded_by.id
            and existing.reversal_of_id == expected_reversal_id
        ):
            return existing, False
        raise ParticipationPointError(
            "point_source_conflict",
            "同一来源事件已经生成不同的积分流水。",
        )

    if not reason_code:
        raise ParticipationPointError(
            "point_reason_required",
            "积分增减必须选择结构化原因。",
        )
    if source_event.target_student_id is None or source_event.class_group_id is None:
        raise ParticipationPointError(
            "point_context_missing",
            "积分来源事件必须包含目标学生和班级。",
        )
    if source_event.actor_id != awarded_by.id:
        raise ParticipationPointError(
            "point_actor_mismatch",
            "积分执行教师与来源事件执行人不一致。",
        )
    if not teacher_has_class_scope(
        teacher=awarded_by,
        class_group=source_event.class_group,
    ):
        raise ParticipationPointError(
            "point_class_scope_forbidden",
            "教师无权调整该班学生积分。",
        )

    profile = (
        StudentProfile.objects.select_for_update()
        .select_related("user", "class_group")
        .filter(
            user_id=source_event.target_student_id,
            class_group_id=source_event.class_group_id,
        )
        .first()
    )
    if profile is None:
        raise ParticipationPointError(
            "point_student_not_found",
            "目标学生不属于积分来源班级。",
        )

    if reversal_of:
        reversal_of = ParticipationPointLedger.objects.select_for_update().get(
            pk=reversal_of.pk
        )
        if reversal_of.student_id != profile.user_id:
            raise ParticipationPointError(
                "point_reversal_student_mismatch",
                "只能冲正同一学生的积分流水。",
            )
        if reversal_of.reversal_entries.exists():
            raise ParticipationPointError(
                "point_already_reversed",
                "该积分流水已经冲正。",
            )
        if requested_delta != -reversal_of.delta:
            raise ParticipationPointError(
                "point_reversal_delta_mismatch",
                "冲正分值必须与原流水方向相反且绝对值相同。",
            )
        entry_type = ParticipationPointLedger.EntryType.REVERSAL
    else:
        entry_type = (
            ParticipationPointLedger.EntryType.AWARD
            if requested_delta > 0
            else ParticipationPointLedger.EntryType.DEDUCTION
        )

    latest = (
        ParticipationPointLedger.objects.select_for_update()
        .filter(student=profile.user)
        .order_by("-recorded_at", "-id")
        .first()
    )
    balance_before = (
        latest.balance_after
        if latest
        else Decimal(str(profile.score or 0)).quantize(Decimal("0.01"))
    )
    balance_after = balance_before + requested_delta
    if balance_after < 0:
        raise ParticipationPointError(
            "point_balance_insufficient",
            "扣分或冲正后积分不能低于 0。",
        )

    entry = ParticipationPointLedger(
        source_event=source_event,
        reversal_of=reversal_of,
        school=source_event.school,
        student=profile.user,
        class_group=source_event.class_group,
        subject=source_event.subject,
        course=source_event.course,
        lesson=source_event.lesson,
        classroom_session=source_event.classroom_session,
        awarded_by=awarded_by,
        academic_period=academic_period,
        entry_type=entry_type,
        reason_code=reason_code,
        delta=requested_delta,
        balance_before=balance_before,
        balance_after=balance_after,
        occurred_at=source_event.client_occurred_at,
        recorded_at=timezone.now(),
    )
    entry.save()
    profile.score = float(balance_after)
    profile.save(update_fields=["score", "updated_at"])
    return entry, True


@transaction.atomic
def reconcile_participation_point_cache(*, student, apply: bool = False) -> dict:
    profile = StudentProfile.objects.select_for_update().get(user=student)
    entries = ParticipationPointLedger.objects.filter(student=student).order_by(
        "recorded_at", "id"
    )
    first = entries.first()
    if first:
        delta_sum = entries.aggregate(value=Sum("delta"))["value"] or Decimal("0")
        expected = first.balance_before + delta_sum
    else:
        expected = Decimal(str(profile.score or 0)).quantize(Decimal("0.01"))
    actual = Decimal(str(profile.score or 0)).quantize(Decimal("0.01"))
    changed = expected != actual
    if apply and changed:
        profile.score = float(expected)
        profile.save(update_fields=["score", "updated_at"])
    return {
        "student_id": student.id,
        "expected": expected,
        "actual": actual,
        "matches": not changed,
        "updated": bool(apply and changed),
    }
