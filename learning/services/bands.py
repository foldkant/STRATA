from __future__ import annotations

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from learning.models import (
    LearningContentRecommendation,
    StratificationDecision,
    StudentLearningTargetStateVersion,
    StudentSubjectBand,
)
from school.models import StudentProfile


COMPARABLE_EVIDENCE_STATUSES = {"comparable", "verified"}


def validate_content_band_evidence(
    *,
    decision: StratificationDecision,
    at=None,
    require_pending_recommendation: bool = True,
) -> LearningContentRecommendation:
    """Fail closed before a content-band candidate can become an arrangement."""
    at = at or timezone.now()
    if decision.decision_kind != StratificationDecision.DecisionKind.CONTENT_BAND:
        raise ValidationError("当前记录不是学习内容层级建议。")
    if decision.abstain_reason or decision.suggested_layer not in StudentSubjectBand.Band.values:
        raise ValidationError("当前材料只能形成“暂不建议”，不能生成学习内容层级安排。")
    recommendation = (
        LearningContentRecommendation.objects.select_related("target_state")
        .prefetch_related("target_state_links__target_state__learning_target_version__target")
        .filter(source_decision=decision)
        .first()
    )
    if recommendation is None:
        raise ValidationError("学习内容层级建议缺少可追溯的目标级材料。")
    if (
        require_pending_recommendation
        and recommendation.status != LearningContentRecommendation.Status.PENDING
    ):
        raise ValidationError("该学习内容层级建议已经处理，请刷新后重试。")
    if recommendation.suggested_band not in StudentSubjectBand.Band.values:
        raise ValidationError("学习内容层级建议没有可确认的候选层级。")

    links = list(recommendation.target_state_links.all())
    if not links:
        raise ValidationError("学习内容层级建议没有目标级学习情况依据。")
    states = [link.target_state for link in links]
    if recommendation.target_state_id != states[0].id:
        raise ValidationError("学习内容层级建议的主要依据与目标情况清单不一致。")
    if recommendation.evidence_coverage <= 0 or recommendation.uncertainty is None:
        raise ValidationError("学习内容层级建议缺少材料覆盖或不确定性记录。")

    allowed_status = StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE
    for state in states:
        version = state.learning_target_version
        target = version.target if version is not None else None
        if (
            state.legacy_unmapped
            or version is None
            or version.alignment_status != "complete"
            or not version.curriculum_alignments.exists()
        ):
            raise ValidationError("学习内容层级建议包含未完成课标映射的目标情况。")
        if (
            target.school_id != decision.class_group.school_id
            or target.subject_id != decision.subject_id
            or target.course_id != decision.course_id
        ):
            raise ValidationError("学习目标情况与建议的学校、学科或课程范围不一致。")
        if (
            state.student_id != decision.student_id
            or state.class_group_id != decision.class_group_id
            or state.subject_id != decision.subject_id
            or state.course_id != decision.course_id
        ):
            raise ValidationError("学习目标情况与建议的学生或教学范围不一致。")
        if state.evidence_status != allowed_status or state.estimate is None:
            raise ValidationError("学习目标材料不足或尚未完成处理，只能暂不建议。")
        if state.uncertainty is None:
            raise ValidationError("学习目标情况缺少不确定性记录，只能暂不建议。")
        if state.valid_from > at or state.valid_until is None or state.valid_until <= at:
            raise ValidationError("学习目标材料尚未生效或已超过有效期，请重新汇总。")
        expected_hash = state.content_hash
        calculated_hash = hashlib.sha256(
            json.dumps(
                state.semantic_content(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        if calculated_hash != expected_hash:
            raise ValidationError("学习目标情况的材料校验值不一致，不能确认层级安排。")
    return recommendation


def active_student_band_queryset(*, student, subject, course=None, at=None):
    at = at or timezone.now()
    school_id = getattr(student, "school_id", None)
    query = StudentSubjectBand.objects.filter(
        student=student,
        school_id=school_id,
        subject=subject,
        valid_from__lte=at,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gt=at))
    if getattr(subject, "school_id", None) != school_id:
        return query.none()
    if course is not None and course.subject_id != subject.id:
        return query.none()
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

    effective_at = effective_at or timezone.now()
    validate_content_band_evidence(decision=decision, at=effective_at)

    existing = StudentSubjectBand.objects.filter(
        source_decision=decision,
        valid_until__isnull=True,
    ).first()
    if existing and existing.band == selected_band:
        return existing

    scope = StudentSubjectBand.objects.select_for_update().filter(
        student_id=decision.student_id,
        subject_id=decision.subject_id,
        valid_until__isnull=True,
    )
    if decision.course_id:
        scope = scope.filter(course_id=decision.course_id)
    else:
        scope = scope.filter(course__isnull=True)
    if scope.filter(valid_from__gte=effective_at).exists():
        raise ValidationError("新的学习内容层级安排必须晚于当前安排的生效时间。")
    scope.close_at(effective_at)

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

    return band
