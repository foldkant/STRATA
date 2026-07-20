from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from learning.models import (
    AssessmentComparabilityRecord,
    BandTransitionAudit,
    ContentBandPolicyVersion,
    QuestionBankItem,
    StratificationDecision,
    StudentMasterySnapshot,
    TestAssessment,
    TestAttempt,
)
from learning.services.bands import get_active_student_band


BAND_RANK = {"C": 0, "B": 1, "A": 2}
RANK_BAND = {value: key for key, value in BAND_RANK.items()}
MASTERY_GENERATOR_VERSION = "common-mastery-v1"


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def active_content_band_policy(*, school, subject, course=None):
    query = ContentBandPolicyVersion.objects.filter(
        school=school,
        subject=subject,
        status=ContentBandPolicyVersion.Status.ACTIVE,
    )
    if course is not None:
        course_policy = query.filter(course=course).first()
        if course_policy:
            return course_policy
    return query.filter(course__isnull=True).first()


@transaction.atomic
def create_default_content_band_policy(*, school, subject, course=None, actor=None):
    existing = active_content_band_policy(
        school=school,
        subject=subject,
        course=course,
    )
    if existing:
        return existing, False
    if actor is None:
        raise ValidationError("创建层级标准需要记录操作人。")
    scope = ContentBandPolicyVersion.objects.filter(
        school=school,
        subject=subject,
        course=course,
    )
    version_no = (
        scope.order_by("-version_no").values_list("version_no", flat=True).first() or 0
    ) + 1
    policy = ContentBandPolicyVersion(
        school=school,
        subject=subject,
        course=course,
        name=f"{subject.name}学习内容层级标准",
        version_no=version_no,
        policy_version=f"criterion-v{version_no}",
        status=ContentBandPolicyVersion.Status.ACTIVE,
        created_by=actor,
        published_by=actor,
        published_at=timezone.now(),
    )
    policy.save()
    return policy, True


@transaction.atomic
def publish_content_band_policy(*, policy: ContentBandPolicyVersion, actor):
    if policy.status != ContentBandPolicyVersion.Status.DRAFT:
        raise ValidationError("只能启用草稿层级标准。")
    scope = ContentBandPolicyVersion.objects.select_for_update().filter(
        school=policy.school,
        subject=policy.subject,
        course=policy.course,
        status=ContentBandPolicyVersion.Status.ACTIVE,
    )
    now = timezone.now()
    for current in scope:
        current.status = ContentBandPolicyVersion.Status.RETIRED
        current.retired_at = now
        current.save(update_fields=["status", "retired_at"])
    policy.status = ContentBandPolicyVersion.Status.ACTIVE
    policy.published_by = actor
    policy.published_at = now
    policy.save(update_fields=["status", "published_by", "published_at"])
    return policy


def _comparability_evidence(assessment: TestAssessment) -> tuple[str, dict]:
    question_set = assessment.common_question_set
    if question_set is None:
        return "not_comparable", {"reason": "missing_common_question_set"}
    evidence = {
        "measurement_series": question_set.measurement_series,
        "question_set_id": question_set.id,
        "question_set_version": question_set.version_no,
        "version_purpose": question_set.version_purpose,
        "readiness": question_set.readiness,
    }
    if question_set.version_purpose == question_set.VersionPurpose.BASELINE:
        return "verified", evidence
    records = AssessmentComparabilityRecord.objects.filter(
        Q(left_assessment=assessment) | Q(right_assessment=assessment),
        status=AssessmentComparabilityRecord.Status.COMPARABLE,
    ).order_by("-compared_at")
    record = records.first()
    if record is None:
        evidence["reason"] = "no_comparable_assessment_version"
        return "not_comparable", evidence
    evidence["comparison_record_id"] = record.id
    evidence["common_question_count"] = record.common_question_count
    evidence["exact_version_match_count"] = record.exact_version_match_count
    return "comparable", evidence


def _answer_present(answer_row) -> bool:
    if answer_row is None:
        return False
    value = answer_row.answer
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return value is not None


@transaction.atomic
def build_student_mastery_snapshot(*, attempt: TestAttempt) -> StudentMasterySnapshot:
    assessment = (
        TestAssessment.objects.select_related(
            "school", "subject", "course", "common_question_set"
        )
        .prefetch_related("questions")
        .get(pk=attempt.assessment_id)
    )
    if assessment.common_question_set_id is None:
        raise ValidationError("测试未绑定共同题集合，不能计算共同掌握结果。")
    common_questions = list(
        assessment.questions.filter(item_role=QuestionBankItem.ItemRole.COMMON)
        .select_related("source_version")
        .order_by("sort_order", "id")
    )
    answers = {
        row.question_id: row
        for row in attempt.answer_rows.select_related("question").all()
    }
    pending_manual = any(
        question.question_type == QuestionBankItem.QuestionType.TEXT
        and answers.get(question.id) is not None
        and answers[question.id].manual_score is None
        for question in common_questions
    )
    answered = [
        question
        for question in common_questions
        if _answer_present(answers.get(question.id))
    ]
    score_max = sum(max(float(question.score), 0) for question in common_questions)
    score_obtained = sum(
        max(0.0, min(float(answers[question.id].final_score), float(question.score)))
        for question in answered
    )
    mastery_score = score_obtained / score_max if score_max > 0 else None
    item_count = len(common_questions)
    answered_ratio = len(answered) / item_count if item_count else 0
    measurement_error = (
        math.sqrt(max(mastery_score * (1 - mastery_score), 0) / item_count)
        if mastery_score is not None and item_count
        else None
    )
    comparability_status, comparability = _comparability_evidence(assessment)
    if attempt.status == TestAttempt.Status.IN_PROGRESS or pending_manual:
        data_status = StudentMasterySnapshot.DataStatus.PENDING_GRADING
    elif comparability_status == "not_comparable":
        data_status = StudentMasterySnapshot.DataStatus.NOT_COMPARABLE
    elif not common_questions or mastery_score is None:
        data_status = StudentMasterySnapshot.DataStatus.INSUFFICIENT
    else:
        data_status = StudentMasterySnapshot.DataStatus.AVAILABLE

    knowledge = defaultdict(lambda: {"score": 0.0, "max_score": 0.0, "items": 0})
    for question in common_questions:
        key = question.knowledge_point.strip() or "未标注知识点"
        row = knowledge[key]
        row["items"] += 1
        row["max_score"] += float(question.score)
        answer = answers.get(question.id)
        if answer:
            row["score"] += max(
                0.0, min(float(answer.final_score), float(question.score))
            )
    knowledge_results = [
        {
            "knowledge_point": key,
            "item_count": value["items"],
            "score": round(value["score"], 4),
            "max_score": round(value["max_score"], 4),
            "mastery_score": (
                round(value["score"] / value["max_score"], 6)
                if value["max_score"]
                else None
            ),
        }
        for key, value in sorted(knowledge.items())
    ]
    source = {
        "generator_version": MASTERY_GENERATOR_VERSION,
        "attempt_id": attempt.id,
        "attempt_status": attempt.status,
        "assessment_id": assessment.id,
        "question_set_hash": assessment.common_set_hash,
        "questions": [
            {
                "id": question.id,
                "version_id": question.source_version_id,
                "comparison_code": question.comparison_code,
                "score": question.score,
                "answer_id": answers.get(question.id).id
                if answers.get(question.id)
                else None,
                "final_score": answers[question.id].final_score
                if answers.get(question.id)
                else None,
            }
            for question in common_questions
        ],
    }
    observed_at = attempt.graded_at or attempt.submitted_at or attempt.last_saved_at
    snapshot, _created = StudentMasterySnapshot.objects.update_or_create(
        attempt=attempt,
        defaults={
            "student": attempt.student,
            "school": assessment.school,
            "class_group": attempt.class_group,
            "subject": assessment.subject,
            "course": assessment.course,
            "assessment": assessment,
            "common_question_set": assessment.common_question_set,
            "measurement_series": assessment.common_question_set.measurement_series,
            "assessment_version": f"v{assessment.common_set_version or assessment.common_question_set.version_no}",
            "data_status": data_status,
            "score_obtained": round(score_obtained, 6),
            "score_max": round(score_max, 6),
            "mastery_score": round(mastery_score, 6)
            if mastery_score is not None
            else None,
            "measurement_error": (
                round(measurement_error, 6) if measurement_error is not None else None
            ),
            "common_item_count": item_count,
            "answered_item_count": len(answered),
            "answered_ratio": round(answered_ratio, 6),
            "knowledge_results": knowledge_results,
            "comparability_evidence": {
                **comparability,
                "comparability_status": comparability_status,
            },
            "source_hash": _canonical_hash(source),
            "is_test_data": bool(assessment.school.is_synthetic),
            "observed_at": observed_at,
        },
    )
    return snapshot


def _raw_band(score: float, policy: ContentBandPolicyVersion) -> str:
    if score >= policy.a_min:
        return "A"
    if score >= policy.b_min:
        return "B"
    return "C"


def _boundary_band(score: float, policy: ContentBandPolicyVersion) -> str:
    if abs(score - policy.a_min) <= policy.boundary_margin:
        return StratificationDecision.BoundaryBand.AB
    if abs(score - policy.b_min) <= policy.boundary_margin:
        return StratificationDecision.BoundaryBand.BC
    return ""


def _measurement_crosses_threshold(
    score: float,
    error: float | None,
    policy: ContentBandPolicyVersion,
) -> bool:
    if error is None:
        return True
    lower, upper = score - error, score + error
    return any(
        lower <= threshold <= upper for threshold in (policy.a_min, policy.b_min)
    )


def _consecutive_candidate_count(*, snapshot, raw_band: str, policy) -> int:
    previous = (
        StratificationDecision.objects.filter(
            student=snapshot.student,
            subject=snapshot.subject,
            course=snapshot.course,
            decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            mastery_snapshot__observed_at__lt=snapshot.observed_at,
            policy=policy,
        )
        .order_by("-mastery_snapshot__observed_at", "-id")
        .values_list("learning_summary__raw_candidate_band", flat=True)
    )
    count = 1
    for value in previous:
        if value != raw_band:
            break
        count += 1
    return count


@transaction.atomic
def build_guarded_content_band_candidate(
    *,
    snapshot: StudentMasterySnapshot,
    policy: ContentBandPolicyVersion | None = None,
) -> StratificationDecision:
    policy = policy or active_content_band_policy(
        school=snapshot.school,
        subject=snapshot.subject,
        course=snapshot.course,
    )
    if policy is None:
        raise ValidationError("当前学科尚未启用学习内容层级标准。")
    current = get_active_student_band(
        student=snapshot.student,
        subject=snapshot.subject,
        course=snapshot.course,
        at=snapshot.observed_at,
    )
    previous_band = current.band if current else ""
    checks = {
        "data_status": snapshot.data_status,
        "common_item_count": snapshot.common_item_count,
        "answered_ratio": snapshot.answered_ratio,
        "measurement_error": snapshot.measurement_error,
        "cooldown_days": policy.cooldown_days,
        "required_consecutive_windows": policy.required_consecutive_windows,
    }
    raw_candidate = ""
    guarded_candidate = ""
    abstain_reason = ""
    boundary_band = ""
    score = snapshot.mastery_score
    if snapshot.data_status != StudentMasterySnapshot.DataStatus.AVAILABLE:
        abstain_reason = snapshot.data_status
    elif snapshot.common_item_count < policy.min_common_items:
        abstain_reason = "insufficient_common_items"
    elif snapshot.answered_ratio < policy.min_answered_ratio:
        abstain_reason = "insufficient_answered_items"
    elif (
        snapshot.measurement_error is None
        or snapshot.measurement_error > policy.max_measurement_error
    ):
        abstain_reason = "measurement_error_too_large"
    else:
        raw_candidate = _raw_band(score, policy)
        boundary_band = _boundary_band(score, policy)
        if _measurement_crosses_threshold(score, snapshot.measurement_error, policy):
            abstain_reason = "measurement_uncertainty"
        else:
            guarded_candidate = raw_candidate

    if guarded_candidate and previous_band and guarded_candidate != previous_band:
        old_rank = BAND_RANK[previous_band]
        new_rank = BAND_RANK[guarded_candidate]
        direction = 1 if new_rank > old_rank else -1
        next_band = RANK_BAND[old_rank + direction]
        if abs(new_rank - old_rank) > policy.max_step_change:
            guarded_candidate = next_band
            checks["single_step_applied"] = True
        if direction > 0:
            threshold = policy.a_min if next_band == "A" else policy.b_min
            if score < threshold + policy.hysteresis_margin:
                abstain_reason = abstain_reason or "hysteresis_hold"
        else:
            threshold = policy.a_min if previous_band == "A" else policy.b_min
            if score >= threshold - policy.hysteresis_margin:
                abstain_reason = abstain_reason or "hysteresis_hold"
        if snapshot.observed_at < current.valid_from + timedelta(
            days=policy.cooldown_days
        ):
            abstain_reason = abstain_reason or "cooldown_active"
        consecutive = _consecutive_candidate_count(
            snapshot=snapshot,
            raw_band=raw_candidate,
            policy=policy,
        )
        checks["consecutive_candidate_count"] = consecutive
        if consecutive < policy.required_consecutive_windows:
            abstain_reason = abstain_reason or "consecutive_evidence_required"
    elif guarded_candidate:
        checks["consecutive_candidate_count"] = 1

    if abstain_reason:
        guarded_candidate = ""
    checks["raw_candidate_band"] = raw_candidate
    checks["guarded_candidate_band"] = guarded_candidate
    checks["abstain_reason"] = abstain_reason
    rule_version = f"content-{policy.id}-{snapshot.assessment_id}"[:32]
    decision, _created = StratificationDecision.objects.update_or_create(
        student=snapshot.student,
        course=snapshot.course,
        window_end=snapshot.observed_at,
        rule_version=rule_version,
        defaults={
            "class_group": snapshot.class_group,
            "subject": snapshot.subject,
            "previous_layer": previous_band,
            "suggested_layer": guarded_candidate,
            "confidence": 0,
            "reasons": [
                f"共同题掌握情况为 {score * 100:.1f}% 。"
                if score is not None
                else "共同测试材料暂不可用。"
            ],
            "missing_data": [abstain_reason] if abstain_reason else [],
            "learning_summary": {
                "source": "comparable_mastery",
                "mastery_snapshot_id": snapshot.id,
                "mastery_score": score,
                "measurement_error": snapshot.measurement_error,
                "raw_candidate_band": raw_candidate,
                "guarded_candidate_band": guarded_candidate,
            },
            "decision_kind": StratificationDecision.DecisionKind.CONTENT_BAND,
            "boundary_band": boundary_band,
            "policy_version": policy.policy_version,
            "policy": policy,
            "mastery_snapshot": snapshot,
            "abstain_reason": abstain_reason,
            "transition_checks": checks,
            "window_start": snapshot.observed_at,
            "status": (
                StratificationDecision.Status.PENDING
                if guarded_candidate
                else StratificationDecision.Status.DEFERRED
            ),
        },
    )
    return decision


def build_assessment_mastery_candidates(*, assessment: TestAssessment) -> dict:
    snapshots = 0
    candidates = 0
    deferred = 0
    policy = active_content_band_policy(
        school=assessment.school,
        subject=assessment.subject,
        course=assessment.course,
    )
    if policy is None:
        return {"snapshots": 0, "candidates": 0, "deferred": 0, "reason": "no_policy"}
    attempts = assessment.attempts.exclude(status=TestAttempt.Status.IN_PROGRESS)
    for attempt in attempts:
        snapshot = build_student_mastery_snapshot(attempt=attempt)
        snapshots += 1
        decision = build_guarded_content_band_candidate(
            snapshot=snapshot, policy=policy
        )
        if decision.status == StratificationDecision.Status.PENDING:
            candidates += 1
        else:
            deferred += 1
    return {
        "snapshots": snapshots,
        "candidates": candidates,
        "deferred": deferred,
        "reason": "",
    }


def record_band_transition_review(
    *,
    decision: StratificationDecision,
    action: str,
    final_band: str,
    actor,
) -> BandTransitionAudit:
    return BandTransitionAudit.objects.create(
        decision=decision,
        student=decision.student,
        subject=decision.subject,
        course=decision.course,
        previous_band=decision.previous_layer,
        raw_candidate_band=str(
            (decision.learning_summary or {}).get("raw_candidate_band") or ""
        ),
        guarded_candidate_band=decision.suggested_layer,
        checks=decision.transition_checks,
        action=action,
        final_band=final_band,
        actor=actor,
    )
