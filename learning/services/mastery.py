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
    LearningContentRecommendation,
    LearningContentRecommendationTargetState,
    QuestionBankItem,
    StratificationDecision,
    StudentMasterySnapshot,
    StudentMasteryTargetResult,
    StudentLearningTargetStateVersion,
    TestAssessment,
    TestAttempt,
)
from learning.services.bands import get_active_student_band


BAND_RANK = {"C": 0, "B": 1, "A": 2}
RANK_BAND = {value: key for key, value in BAND_RANK.items()}
MASTERY_GENERATOR_VERSION = "common-mastery-v2-conservative-uncertainty"
MASTERY_UNCERTAINTY_METHOD = "conservative_task_coverage_se_v1"


def _conservative_task_uncertainty(*, observed_count: int, task_count: int):
    """Worst-case task-sampling error plus opportunity coverage loss.

    This is an auditable conservative proxy, not a claim of psychometric
    calibration.  A later calibrated model must use a separately versioned
    estimator and frozen validation evidence.
    """

    if observed_count <= 0 or task_count <= 0:
        return None
    coverage = observed_count / task_count
    return min(1.0, max(1 - coverage, 0.5 / math.sqrt(observed_count)))


def _target_evidence_status(result, estimate):
    if result.data_status == StudentMasterySnapshot.DataStatus.PENDING_GRADING:
        return StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW
    if result.data_status != StudentMasterySnapshot.DataStatus.AVAILABLE:
        return StudentLearningTargetStateVersion.EvidenceStatus.INSUFFICIENT
    if estimate is None:
        return StudentLearningTargetStateVersion.EvidenceStatus.INSUFFICIENT
    if result.evidence_coverage < 1:
        return StudentLearningTargetStateVersion.EvidenceStatus.PARTIAL
    return StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE


def record_mastery_target_states(*, snapshot: StudentMasterySnapshot):
    rows = []
    results = snapshot.target_results.select_related(
        "learning_target_version__target"
    ).order_by("learning_target_version__code", "id")
    for result in results:
        version = result.learning_target_version
        estimate = result.mastery_score
        evidence_status = _target_evidence_status(result, estimate)
        estimate_is_reportable = evidence_status in {
            StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE,
            StudentLearningTargetStateVersion.EvidenceStatus.PARTIAL,
        }
        state, _created = StudentLearningTargetStateVersion.objects.get_or_create(
            student=snapshot.student,
            subject=snapshot.subject,
            course=snapshot.course,
            learning_target_code=version.code,
            source_type="common_assessment",
            source_id=str(result.id),
            source_version=result.content_hash,
            defaults={
                "school": snapshot.school,
                "class_group": snapshot.class_group,
                "learning_target_version": version,
                "mastery_target_result": result,
                "legacy_unmapped": False,
                "learning_target_name": version.title,
                "evidence_status": evidence_status,
                "evidence_coverage": result.evidence_coverage,
                "estimate": estimate if estimate_is_reportable else None,
                "uncertainty": (
                    result.measurement_error if estimate_is_reportable else None
                ),
                "material_references": [
                    f"mastery_snapshot:{snapshot.id}",
                    *[
                        f"assessment_question:{question_id}"
                        for question_id in result.evidence_snapshot.get(
                            "assessment_question_ids", []
                        )
                    ],
                ],
                "observation_notes": [
                    result.get_data_status_display(),
                    f"目标版本：{version.code}@{version.version_no}",
                ],
                "is_initial_diagnostic": False,
                "observed_at": snapshot.observed_at,
                "valid_from": snapshot.observed_at,
                "valid_until": snapshot.observed_at + timedelta(days=30),
            },
        )
        rows.append(state)
    return rows


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
        .select_related(
            "source_version__learning_target_version__target",
            "learning_target_version__target",
        )
        .prefetch_related("learning_target_version__curriculum_alignments")
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
    answered_score_max = sum(max(float(question.score), 0) for question in answered)
    score_obtained = sum(
        max(0.0, min(float(answers[question.id].final_score), float(question.score)))
        for question in answered
    )
    descriptive_mastery = (
        score_obtained / answered_score_max if answered_score_max > 0 else None
    )
    item_count = len(common_questions)
    answered_ratio = len(answered) / item_count if item_count else 0
    measurement_error = _conservative_task_uncertainty(
        observed_count=len(answered),
        task_count=item_count,
    )
    comparability_status, comparability = _comparability_evidence(assessment)
    mapping_issues = []
    target_groups = defaultdict(list)
    for question in common_questions:
        version = question.learning_target_version
        issue = ""
        if version is None or question.legacy_unmapped:
            issue = "missing_learning_target_version"
        elif question.source_version_id is None:
            issue = "missing_question_version"
        elif (
            question.source_version.learning_target_version_id != version.id
            or question.source_version.legacy_unmapped
        ):
            issue = "question_target_version_not_frozen"
        elif version.alignment_status != "complete" or not version.curriculum_alignments.exists():
            issue = "learning_target_alignment_incomplete"
        elif (
            version.target.school_id != assessment.school_id
            or version.target.subject_id != assessment.subject_id
            or version.target.course_id != assessment.course_id
        ):
            issue = "learning_target_scope_mismatch"
        if issue:
            mapping_issues.append(
                {
                    "assessment_question_id": question.id,
                    "source_version_id": question.source_version_id,
                    "reason": issue,
                }
            )
            continue
        target_groups[version.id].append(question)
    if attempt.status == TestAttempt.Status.IN_PROGRESS or pending_manual:
        data_status = StudentMasterySnapshot.DataStatus.PENDING_GRADING
    elif mapping_issues:
        data_status = StudentMasterySnapshot.DataStatus.NOT_COMPARABLE
    elif comparability_status == "not_comparable":
        data_status = StudentMasterySnapshot.DataStatus.NOT_COMPARABLE
    elif not common_questions or descriptive_mastery is None:
        data_status = StudentMasterySnapshot.DataStatus.INSUFFICIENT
    else:
        data_status = StudentMasterySnapshot.DataStatus.AVAILABLE
    reportable_mastery = (
        descriptive_mastery
        if data_status == StudentMasterySnapshot.DataStatus.AVAILABLE
        else None
    )
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
                "answered_at": answers[question.id].answered_at
                if answers.get(question.id)
                else None,
                "learning_target_version_id": question.learning_target_version_id,
                "learning_target_version_hash": (
                    question.learning_target_version.content_hash
                    if question.learning_target_version_id
                    else ""
                ),
                "legacy_unmapped": question.legacy_unmapped,
            }
            for question in common_questions
        ],
    }
    observed_at = attempt.graded_at or attempt.submitted_at or attempt.last_saved_at
    source_hash = _canonical_hash(source)
    existing = StudentMasterySnapshot.objects.filter(
        attempt=attempt,
        source_hash=source_hash,
    ).first()
    if existing is not None:
        record_mastery_target_states(snapshot=existing)
        return existing
    snapshot = StudentMasterySnapshot.objects.create(
        attempt=attempt,
        student=attempt.student,
        school=assessment.school,
        class_group=attempt.class_group,
        subject=assessment.subject,
        course=assessment.course,
        assessment=assessment,
        common_question_set=assessment.common_question_set,
        measurement_series=assessment.common_question_set.measurement_series,
        assessment_version=f"v{assessment.common_set_version or assessment.common_question_set.version_no}",
        data_status=data_status,
        score_obtained=round(score_obtained, 6),
        score_max=round(score_max, 6),
        mastery_score=(
            round(reportable_mastery, 6)
            if reportable_mastery is not None
            else None
        ),
        measurement_error=(
            round(measurement_error, 6)
            if reportable_mastery is not None and measurement_error is not None
            else None
        ),
        common_item_count=item_count,
        answered_item_count=len(answered),
        answered_ratio=round(answered_ratio, 6),
        knowledge_results=[],
        comparability_evidence={
            **comparability,
            "comparability_status": comparability_status,
            "target_mapping_status": "complete" if not mapping_issues else "legacy_unmapped",
            "target_mapping_issues": mapping_issues,
            "target_version_ids": sorted(target_groups),
            "descriptive_observed_score": (
                round(descriptive_mastery, 6)
                if descriptive_mastery is not None
                else None
            ),
            "answered_score_max": round(answered_score_max, 6),
            "uncertainty_method": MASTERY_UNCERTAINTY_METHOD,
            "uncertainty_observed_task_count": len(answered),
            "uncertainty_task_count": item_count,
        },
        source_hash=source_hash,
        legacy_unmapped=bool(mapping_issues),
        is_test_data=bool(assessment.school.is_synthetic),
        observed_at=observed_at,
    )
    for target_version_id, target_questions in sorted(target_groups.items()):
        target_answers = [
            question
            for question in target_questions
            if _answer_present(answers.get(question.id))
        ]
        target_score = sum(
            max(
                0.0,
                min(
                    float(answers[question.id].final_score),
                    float(question.score),
                ),
            )
            for question in target_answers
        )
        target_answered_max = sum(float(question.score) for question in target_answers)
        target_coverage = len(target_answers) / len(target_questions)
        target_status = data_status
        if (
            data_status == StudentMasterySnapshot.DataStatus.AVAILABLE
            and not target_answers
        ):
            target_status = StudentMasterySnapshot.DataStatus.INSUFFICIENT
        target_estimate = (
            target_score / target_answered_max
            if target_status == StudentMasterySnapshot.DataStatus.AVAILABLE
            and target_answered_max > 0
            else None
        )
        target_error = (
            _conservative_task_uncertainty(
                observed_count=len(target_answers),
                task_count=len(target_questions),
            )
            if target_estimate is not None
            else None
        )
        StudentMasteryTargetResult.objects.create(
            snapshot=snapshot,
            learning_target_version_id=target_version_id,
            data_status=target_status,
            score_obtained=round(target_score, 6),
            score_max=round(target_answered_max, 6),
            mastery_score=(
                round(target_estimate, 6) if target_estimate is not None else None
            ),
            measurement_error=(
                round(target_error, 6) if target_error is not None else None
            ),
            item_count=len(target_questions),
            answered_item_count=len(target_answers),
            evidence_coverage=round(target_coverage, 6),
            evidence_snapshot={
                "assessment_question_ids": [row.id for row in target_questions],
                "source_question_version_ids": [
                    row.source_version_id for row in target_questions
                ],
                "answer_ids": [
                    answers[row.id].id for row in target_answers
                ],
                "snapshot_source_hash": source_hash,
                "uncertainty_method": MASTERY_UNCERTAINTY_METHOD,
                "uncertainty_observed_task_count": len(target_answers),
                "uncertainty_task_count": len(target_questions),
            },
        )
    record_mastery_target_states(snapshot=snapshot)
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
    target_results = list(
        snapshot.target_results.select_related(
            "learning_target_version__target"
        ).order_by("learning_target_version__code", "id")
    )
    mapping_complete = bool(target_results) and not snapshot.legacy_unmapped
    mapping_complete = mapping_complete and (
        (snapshot.comparability_evidence or {}).get("target_mapping_status")
        == "complete"
    )
    mapping_complete = mapping_complete and all(
        result.learning_target_version.alignment_status == "complete"
        and result.learning_target_version.curriculum_alignments.exists()
        and result.learning_target_version.target.school_id == snapshot.school_id
        and result.learning_target_version.target.subject_id == snapshot.subject_id
        and result.learning_target_version.target.course_id == snapshot.course_id
        for result in target_results
    )
    target_states = record_mastery_target_states(snapshot=snapshot)
    evidence_coverage = (
        min(result.evidence_coverage for result in target_results)
        if target_results
        else 0
    )
    target_uncertainties = [
        result.measurement_error
        for result in target_results
        if result.measurement_error is not None
    ]
    conservative_uncertainty = max(target_uncertainties) if target_uncertainties else None
    target_score_obtained = sum(result.score_obtained for result in target_results)
    target_score_max = sum(result.score_max for result in target_results)
    score = (
        target_score_obtained / target_score_max
        if mapping_complete and target_score_max > 0
        else None
    )
    checks = {
        "data_status": snapshot.data_status,
        "common_item_count": snapshot.common_item_count,
        "answered_ratio": snapshot.answered_ratio,
        "measurement_error": snapshot.measurement_error,
        "source_hash": snapshot.source_hash,
        "target_mapping_complete": mapping_complete,
        "target_version_ids": [
            result.learning_target_version_id for result in target_results
        ],
        "target_result_hashes": [result.content_hash for result in target_results],
        "target_state_hashes": [state.content_hash for state in target_states],
        "cooldown_days": policy.cooldown_days,
        "required_consecutive_windows": policy.required_consecutive_windows,
    }
    raw_candidate = ""
    guarded_candidate = ""
    abstain_reason = ""
    boundary_band = ""
    if snapshot.data_status != StudentMasterySnapshot.DataStatus.AVAILABLE:
        abstain_reason = snapshot.data_status
    elif not mapping_complete:
        abstain_reason = "learning_target_mapping_incomplete"
    elif any(
        result.data_status != StudentMasterySnapshot.DataStatus.AVAILABLE
        or result.mastery_score is None
        for result in target_results
    ):
        abstain_reason = "target_evidence_incomplete"
    elif snapshot.common_item_count < policy.min_common_items:
        abstain_reason = "insufficient_common_items"
    elif snapshot.answered_ratio < policy.min_answered_ratio:
        abstain_reason = "insufficient_answered_items"
    elif (
        conservative_uncertainty is None
        or conservative_uncertainty > policy.max_measurement_error
    ):
        abstain_reason = "measurement_error_too_large"
    else:
        raw_candidate = _raw_band(score, policy)
        boundary_band = _boundary_band(score, policy)
        if _measurement_crosses_threshold(score, conservative_uncertainty, policy):
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
    rule_version = f"content-{policy.id}-{snapshot.source_hash}"
    existing_decision = StratificationDecision.objects.filter(
        student=snapshot.student,
        course=snapshot.course,
        window_end=snapshot.observed_at,
        rule_version=rule_version,
    ).first()
    if existing_decision is not None:
        # 同一不可变材料与规则只形成一次建议；重算不得覆盖教师处理或历史审计。
        return existing_decision
    decision = StratificationDecision.objects.create(
        student=snapshot.student,
        course=snapshot.course,
        window_end=snapshot.observed_at,
        rule_version=rule_version,
        class_group=snapshot.class_group,
        subject=snapshot.subject,
        previous_layer=previous_band,
        suggested_layer=guarded_candidate,
        confidence=0,
        reasons=[
            f"共同题在 {len(target_results)} 个学习目标上的综合掌握情况为 {score * 100:.1f}% 。"
            if score is not None
            else "共同测试材料暂不可用于学习内容层级建议。"
        ],
        missing_data=[abstain_reason] if abstain_reason else [],
        learning_summary={
            "source": "curriculum_aligned_target_mastery",
            "mastery_snapshot_id": snapshot.id,
            "source_hash": snapshot.source_hash,
            "target_result_ids": [result.id for result in target_results],
            "target_version_ids": [
                result.learning_target_version_id for result in target_results
            ],
            "mastery_score": score,
            "measurement_error": conservative_uncertainty,
            "evidence_coverage": evidence_coverage,
            "raw_candidate_band": raw_candidate,
            "guarded_candidate_band": guarded_candidate,
        },
        decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
        boundary_band=boundary_band,
        policy_version=policy.policy_version,
        policy=policy,
        mastery_snapshot=snapshot,
        abstain_reason=abstain_reason,
        transition_checks=checks,
        window_start=snapshot.observed_at,
        status=(
            StratificationDecision.Status.PENDING
            if guarded_candidate
            else StratificationDecision.Status.DEFERRED
        ),
    )
    primary_target_state = target_states[0] if target_states else None
    recommendation = LearningContentRecommendation.objects.create(
        source_decision=decision,
        target_state=primary_target_state,
        suggested_band=guarded_candidate,
        status=(
            LearningContentRecommendation.Status.PENDING
            if guarded_candidate
            else LearningContentRecommendation.Status.NOT_RECOMMENDED
        ),
        rationale=list(decision.reasons or []) + (
            [abstain_reason] if abstain_reason else []
        ),
        evidence_coverage=evidence_coverage,
        uncertainty=conservative_uncertainty,
    )
    for sort_order, target_state in enumerate(target_states):
        LearningContentRecommendationTargetState.objects.create(
            recommendation=recommendation,
            target_state=target_state,
            sort_order=sort_order,
        )
    return decision


@transaction.atomic
def build_initial_diagnostic_content_band_candidate(
    *,
    administration,
    student,
    policy: ContentBandPolicyVersion | None = None,
) -> StratificationDecision:
    """Build a conservative initial content recommendation from one batch.

    The function never converts a total pretest score into a layer.  It uses
    only current, exact, curriculum-aligned target states produced by the same
    immutable diagnostic administration.  Any missing, pending, expired or
    legacy target makes the result an auditable ``DEFERRED / 暂不建议`` row.
    Completing one task does not imply zero measurement error: every target
    state must carry an explicit, method-labelled uncertainty estimate and
    satisfy the active versioned policy before a candidate can be formed.
    """

    from learning.models import DiagnosticAdministration

    if administration.purpose != DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC:
        raise ValidationError("只有学习起点诊断批次可以形成初始学习内容层级建议。")
    if administration.status not in {
        DiagnosticAdministration.Status.PUBLISHED,
        DiagnosticAdministration.Status.CLOSED,
    }:
        raise ValidationError("只能依据已发布且版本冻结的诊断实施批次形成建议。")
    if administration.course_id is None:
        raise ValidationError("初始学习内容建议必须绑定具体课程。")
    policy = policy or active_content_band_policy(
        school=administration.school,
        subject=administration.subject,
        course=administration.course,
    )
    if policy is None:
        raise ValidationError("当前课程尚未启用学习内容层级标准。")

    profile = getattr(student, "student_profile", None)
    if profile is None or profile.class_group_id is None:
        raise ValidationError("学生尚未形成有效班级归属。")
    binding_rows = list(
        administration.submission_bindings.filter(student=student)
        .select_related("submission")
        .order_by("attempt_no", "id")
    )
    submission_ids = [row.submission_id for row in binding_rows]
    frozen_questions = [
        item
        for item in (administration.paper_version.question_snapshot or [])
        if isinstance(item, dict)
    ]
    mapped_questions = []
    mapping_parse_invalid = False
    expected_target_hashes: dict[int, set[str]] = {}
    for item in frozen_questions:
        if (
            item.get("learning_target_version_id") in {None, ""}
            or not item.get("learning_target_version_hash")
            or item.get("legacy_unmapped", False)
        ):
            continue
        try:
            version_id = int(item["learning_target_version_id"])
        except (TypeError, ValueError):
            mapping_parse_invalid = True
            continue
        mapped_questions.append(item)
        expected_target_hashes.setdefault(version_id, set()).add(
            str(item["learning_target_version_hash"])
        )
    expected_target_ids = sorted(expected_target_hashes)
    latest_states = {}
    states = (
        StudentLearningTargetStateVersion.objects.filter(
            student=student,
            school=administration.school,
            subject=administration.subject,
            course=administration.course,
            source_id__in=[str(value) for value in submission_ids],
            # Every state formed for the same immutable administration keeps
            # its administration hash as the version prefix.  A reviewed
            # state appends its immutable score-material id to that prefix.
            source_version__startswith=administration.content_hash,
            source_type__in=[
                "learning_entry_diagnostic",
                "learning_entry_diagnostic_review",
            ],
            is_initial_diagnostic=True,
        )
        .select_related("learning_target_version__target")
        .prefetch_related("learning_target_version__curriculum_alignments")
        .order_by("learning_target_version_id", "-observed_at", "-id")
    )
    for state in states:
        if state.learning_target_version_id not in latest_states:
            latest_states[state.learning_target_version_id] = state

    now = timezone.now()
    blockers = []
    if not binding_rows:
        blockers.append("diagnostic_submission_missing")
    if not expected_target_ids:
        blockers.append("diagnostic_target_mapping_missing")
    if mapping_parse_invalid or len(mapped_questions) != len(frozen_questions):
        blockers.append("diagnostic_target_mapping_incomplete")
    if any(len(hashes) != 1 for hashes in expected_target_hashes.values()):
        blockers.append("diagnostic_target_version_hash_inconsistent")
    missing_target_ids = sorted(set(expected_target_ids) - set(latest_states))
    if missing_target_ids:
        blockers.append("diagnostic_target_states_missing")
    selected_states = [
        latest_states[target_id]
        for target_id in expected_target_ids
        if target_id in latest_states
    ]
    for state in selected_states:
        version = state.learning_target_version
        if (
            state.legacy_unmapped
            or version is None
            or version.alignment_status != "complete"
            or not version.curriculum_alignments.exists()
            or version.target.school_id != administration.school_id
            or version.target.subject_id != administration.subject_id
            or version.target.course_id != administration.course_id
        ):
            blockers.append("diagnostic_target_alignment_incomplete")
        if (
            version is not None
            and version.content_hash
            not in expected_target_hashes.get(version.id, set())
        ):
            blockers.append("diagnostic_target_version_hash_mismatch")
        if state.evidence_status == StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW:
            blockers.append("diagnostic_grading_pending")
        elif state.evidence_status not in {
            StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE,
            StudentLearningTargetStateVersion.EvidenceStatus.PARTIAL,
        }:
            blockers.append("diagnostic_evidence_insufficient")
        if state.estimate is None:
            blockers.append("diagnostic_target_estimate_missing")
        if state.uncertainty is None:
            blockers.append("diagnostic_uncertainty_missing")
        if state.valid_until is None or state.valid_until <= now:
            blockers.append("diagnostic_evidence_expired")
    blockers = list(dict.fromkeys(blockers))

    evidence_coverage = (
        min(state.evidence_coverage for state in selected_states)
        if selected_states
        else 0
    )
    uncertainty_values = [
        state.uncertainty for state in selected_states if state.uncertainty is not None
    ]
    conservative_uncertainty = (
        max(uncertainty_values)
        if selected_states and len(uncertainty_values) == len(selected_states)
        else None
    )
    if selected_states and evidence_coverage < policy.min_answered_ratio:
        blockers.append("diagnostic_evidence_coverage_insufficient")
    if (
        selected_states
        and conservative_uncertainty is not None
        and conservative_uncertainty > policy.max_measurement_error
    ):
        blockers.append("diagnostic_measurement_error_too_large")
    score = (
        sum(float(state.estimate) for state in selected_states) / len(selected_states)
        if selected_states and not blockers
        else None
    )
    suggested_band = ""
    raw_candidate = ""
    boundary_band = ""
    current = get_active_student_band(
        student=student,
        subject=administration.subject,
        course=administration.course,
        at=now,
    )
    if current is not None:
        blockers.append("confirmed_content_band_already_exists")
        score = None
    if score is not None:
        raw_candidate = _raw_band(score, policy)
        boundary_band = _boundary_band(score, policy)
        if conservative_uncertainty is None:
            blockers.append("diagnostic_uncertainty_missing")
        elif _measurement_crosses_threshold(score, conservative_uncertainty, policy):
            blockers.append("diagnostic_measurement_uncertainty")
        else:
            suggested_band = raw_candidate
    if blockers:
        suggested_band = ""

    observed_at = max(
        (state.observed_at for state in selected_states),
        default=(administration.published_at or administration.created_at),
    )
    source_hash = _canonical_hash(
        {
            "generator_version": "initial-target-band-v1",
            "administration_id": administration.id,
            "administration_hash": administration.content_hash,
            "paper_version_id": administration.paper_version_id,
            "paper_version_hash": administration.paper_version.content_hash,
            "student_id": student.id,
            "policy_id": policy.id,
            "policy_hash": policy.content_hash,
            "expected_target_version_ids": expected_target_ids,
            "target_state_hashes": [state.content_hash for state in selected_states],
            "blockers": blockers,
        }
    )
    rule_version = f"initial-{policy.id}-{source_hash}"
    existing = StratificationDecision.objects.filter(
        student=student,
        course=administration.course,
        window_end=observed_at,
        rule_version=rule_version,
    ).first()
    if existing is not None:
        return existing
    decision = StratificationDecision.objects.create(
        student=student,
        class_group=profile.class_group,
        subject=administration.subject,
        course=administration.course,
        previous_layer="",
        suggested_layer=suggested_band,
        confidence=0,
        reasons=[
            f"学习起点诊断在 {len(selected_states)} 个学习目标上的综合情况为 {score * 100:.1f}% 。"
            if score is not None
            else "学习起点诊断材料暂不足以形成学习内容层级建议。"
        ],
        missing_data=blockers,
        learning_summary={
            "source": "initial_diagnostic_target_states",
            "administration_id": administration.id,
            "administration_hash": administration.content_hash,
            "source_hash": source_hash,
            "target_state_ids": [state.id for state in selected_states],
            "target_version_ids": expected_target_ids,
            "mastery_score": score,
            "measurement_error": conservative_uncertainty,
            "evidence_coverage": evidence_coverage,
            "raw_candidate_band": raw_candidate,
            "guarded_candidate_band": suggested_band,
        },
        decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
        boundary_band=boundary_band,
        policy_version=policy.policy_version,
        policy=policy,
        mastery_snapshot=None,
        abstain_reason=blockers[0] if blockers else "",
        transition_checks={
            "source_hash": source_hash,
            "administration_id": administration.id,
            "target_state_hashes": [state.content_hash for state in selected_states],
            "target_mapping_complete": not blockers,
            "teacher_confirmation_required": True,
        },
        window_start=administration.open_at or administration.published_at,
        window_end=observed_at,
        rule_version=rule_version,
        status=(
            StratificationDecision.Status.PENDING
            if suggested_band
            else StratificationDecision.Status.DEFERRED
        ),
    )
    primary_state = selected_states[0] if selected_states else None
    recommendation = LearningContentRecommendation.objects.create(
        target_state=primary_state,
        source_decision=decision,
        suggested_band=suggested_band,
        status=(
            LearningContentRecommendation.Status.PENDING
            if suggested_band
            else LearningContentRecommendation.Status.NOT_RECOMMENDED
        ),
        rationale=list(decision.reasons) + blockers,
        evidence_coverage=evidence_coverage,
        uncertainty=conservative_uncertainty,
    )
    for sort_order, state in enumerate(selected_states):
        LearningContentRecommendationTargetState.objects.create(
            recommendation=recommendation,
            target_state=state,
            sort_order=sort_order,
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
