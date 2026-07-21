from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from learning.models import StratificationDecision, StudentSubjectBand
from school.models import StudentProfile


COMPARABLE_EVIDENCE_STATUSES = {"comparable", "verified"}


def active_student_band_queryset(*, student, subject, course=None, at=None):
    at = at or timezone.now()
    query = StudentSubjectBand.objects.filter(
        student=student,
        subject=subject,
        valid_from__lte=at,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gt=at))
    if course is None:
        return query.filter(course__isnull=True).order_by("-valid_from", "-id")
    return (
        query.filter(Q(course=course) | Q(course__isnull=True))
        .annotate(
            course_priority=Case(
                When(course=course, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("course_priority", "-valid_from", "-id")
    )


def get_active_student_band(*, student, subject, course=None, at=None):
    if student is None or subject is None:
        return None
    return active_student_band_queryset(
        student=student,
        subject=subject,
        course=course,
        at=at,
    ).first()


def resolve_student_band(*, student, subject, course=None, at=None) -> str | None:
    band = get_active_student_band(
        student=student,
        subject=subject,
        course=course,
        at=at,
    )
    return band.band if band else None


@transaction.atomic
def build_content_band_candidate(
    *,
    student_profile: StudentProfile,
    subject,
    course,
    mastery_score: float,
    evidence_snapshot: dict,
    policy: dict,
    window_start,
    window_end,
) -> StratificationDecision:
    if not isinstance(evidence_snapshot, dict):
        raise ValidationError("学习内容层级证据必须是结构化记录。")
    if (
        evidence_snapshot.get("comparability_status")
        not in COMPARABLE_EVIDENCE_STATUSES
    ):
        raise ValidationError("共同测试版本尚未确认可比，不能生成学习内容层级建议。")
    if not evidence_snapshot.get("measurement_series"):
        raise ValidationError("学习内容层级证据缺少共同测试系列编号。")
    if not evidence_snapshot.get("assessment_version"):
        raise ValidationError("学习内容层级证据缺少测试版本。")
    if course is not None and course.subject_id != subject.id:
        raise ValidationError("课程与学科不一致。")
    try:
        score = float(mastery_score)
        a_min = float(policy["a_min"])
        b_min = float(policy["b_min"])
        boundary_margin = float(policy.get("boundary_margin", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("学习内容层级标准不完整。") from exc
    if not 0 <= score <= 1 or not 0 <= b_min < a_min <= 1:
        raise ValidationError("掌握度和学习内容层级标准必须在 0 至 1 之间。")
    if not 0 <= boundary_margin <= 0.1:
        raise ValidationError("边界范围必须在 0 至 0.1 之间。")
    policy_version = str(policy.get("version") or "").strip()
    if not policy_version:
        raise ValidationError("学习内容层级标准缺少版本号。")

    suggested_band = "A" if score >= a_min else "B" if score >= b_min else "C"
    boundary_band = ""
    if abs(score - a_min) <= boundary_margin:
        boundary_band = StratificationDecision.BoundaryBand.AB
    elif abs(score - b_min) <= boundary_margin:
        boundary_band = StratificationDecision.BoundaryBand.BC
    previous_band = resolve_student_band(
        student=student_profile.user,
        subject=subject,
        course=course,
        at=window_end,
    )
    rule_version = (
        f"content-{policy_version}-"
        f"{evidence_snapshot['measurement_series']}-"
        f"{evidence_snapshot['assessment_version']}"
    )[:32]
    defaults = {
        "class_group": student_profile.class_group,
        "subject": subject,
        "previous_layer": previous_band or "",
        "suggested_layer": suggested_band,
        "confidence": 0,
        "reasons": list(evidence_snapshot.get("reasons") or []),
        "missing_data": [],
        "learning_summary": {
            "source": "comparable_mastery",
            "mastery_score": score,
            "evidence": evidence_snapshot,
            "policy": policy,
            "confidence_status": "not_estimated",
        },
        "decision_kind": StratificationDecision.DecisionKind.CONTENT_BAND,
        "boundary_band": boundary_band,
        "policy_version": policy_version,
        "window_start": window_start,
        "status": StratificationDecision.Status.PENDING,
    }
    decision, _created = StratificationDecision.objects.update_or_create(
        student=student_profile.user,
        course=course,
        window_end=window_end,
        rule_version=rule_version,
        defaults=defaults,
    )
    return decision


@transaction.atomic
def apply_student_subject_band(
    *,
    decision: StratificationDecision,
    selected_band: str,
    confirmed_by,
    effective_at=None,
) -> StudentSubjectBand:
    if decision.decision_kind != StratificationDecision.DecisionKind.CONTENT_BAND:
        raise ValidationError("当前记录不是正式学习内容层级建议。")
    if selected_band not in StudentSubjectBand.Band.values:
        raise ValidationError("学习内容层级必须为 A、B 或 C。")
    if not decision.subject_id:
        raise ValidationError("正式学习内容层级必须关联学科。")

    existing = StudentSubjectBand.objects.filter(
        source_decision=decision,
        valid_until__isnull=True,
    ).first()
    if existing and existing.band == selected_band:
        return existing

    effective_at = effective_at or timezone.now()
    scope = StudentSubjectBand.objects.select_for_update().filter(
        student_id=decision.student_id,
        subject_id=decision.subject_id,
        valid_until__isnull=True,
    )
    if decision.course_id:
        scope = scope.filter(course_id=decision.course_id)
    else:
        scope = scope.filter(course__isnull=True)
    scope.update(valid_until=effective_at)

    evidence_snapshot = {
        "decision_id": decision.id,
        "rule_version": decision.rule_version,
        "reasons": list(decision.reasons or []),
        "learning_summary": dict(decision.learning_summary or {}),
    }
    source_evidence = evidence_snapshot["learning_summary"].get("evidence")
    if isinstance(source_evidence, dict) and isinstance(
        source_evidence.get("task_readiness"), dict
    ):
        evidence_snapshot["task_readiness"] = source_evidence["task_readiness"]
    band = StudentSubjectBand.objects.create(
        student_id=decision.student_id,
        school_id=decision.class_group.school_id,
        class_group_id=decision.class_group_id,
        subject_id=decision.subject_id,
        course_id=decision.course_id,
        band=selected_band,
        boundary_band=decision.boundary_band,
        valid_from=effective_at,
        source_decision=decision,
        policy_version=decision.policy_version,
        evidence_snapshot=evidence_snapshot,
        mastery_snapshot=decision.mastery_snapshot,
        confirmed_by=confirmed_by,
    )

    profile = StudentProfile.objects.select_for_update().get(
        user_id=decision.student_id
    )
    if profile.current_layer != selected_band:
        profile.current_layer = selected_band
        profile.save(update_fields=["current_layer", "updated_at"])
    return band
