from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from courses.models import ClassroomEvaluationSubmission, Course, CourseClass
from learning.models import (
    LearningSupportRecommendation,
    StratificationDecision,
)
from learning.services.bands import resolve_student_band
from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
    ParticipationPointLedger,
    StudentLearningSummary,
)
from school.models import StudentProfile


SUMMARY_GENERATOR_VERSION = "summary-v1"
RULE_VERSION = "transparent-rules-v3"
SUPPORT_POLICY_VERSION = "support-policy-v3"
MIN_REQUIRED_OPPORTUNITIES = 5
MIN_GRADED_ITEMS = 3


def _canonical_hash(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _local_midnight(value: date) -> datetime:
    return timezone.make_aware(
        datetime.combine(value, time.min), timezone.get_current_timezone()
    )


def summary_window(*, window_type: str, as_of: date, course: Course):
    end = _local_midnight(as_of + timedelta(days=1))
    if window_type == StudentLearningSummary.WindowType.DAY:
        return _local_midnight(as_of), end, as_of.isoformat()
    if window_type == StudentLearningSummary.WindowType.DAYS_7:
        return end - timedelta(days=7), end, as_of.isoformat()
    if window_type == StudentLearningSummary.WindowType.DAYS_30:
        return end - timedelta(days=30), end, as_of.isoformat()
    start = min(course.created_at, end - timedelta(days=3650))
    return start, end, f"course:{course.id}"


def _latest_states(opportunity) -> dict[str, LearningOpportunityTransitionFact]:
    states = {}
    for fact in opportunity.transition_facts.all():
        current = states.get(fact.state)
        if current is None or fact.occurred_at > current.occurred_at:
            states[fact.state] = fact
    return states


def _evaluation_metrics(*, student, course, window_start, window_end):
    submissions = list(
        ClassroomEvaluationSubmission.objects.filter(
            target=student,
            course=course,
            created_at__gte=window_start,
            created_at__lt=window_end,
        ).order_by(
            "session_id",
            "evaluation_type",
            "evaluator_id",
            "target_id",
            "-submission_version",
            "-id",
        )
    )
    latest = []
    seen = set()
    for submission in submissions:
        key = (
            submission.session_id,
            submission.evaluation_type,
            submission.evaluator_id,
            submission.target_id,
        )
        if key in seen:
            continue
        seen.add(key)
        latest.append(submission)
    result = {}
    source_rows = []
    for evaluation_type, _label in ClassroomEvaluationSubmission.EvaluationType.choices:
        rows = [item for item in latest if item.evaluation_type == evaluation_type]
        values = []
        not_assessed_count = 0
        for item in rows:
            for value in item.ratings.values() if isinstance(item.ratings, dict) else []:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= number <= 5:
                    values.append(number)
            if isinstance(item.not_assessed, dict):
                not_assessed_count += len(item.not_assessed)
            source_rows.append(
                [item.id, item.submission_version, item.standard_use_id, item.evaluation_version_id]
            )
        result[evaluation_type] = {
            "submission_count": len(rows),
            "rated_item_count": len(values),
            "not_assessed_item_count": not_assessed_count,
            "average_stars": round(sum(values) / len(values), 2) if values else None,
            # Classroom stars remain useful descriptive feedback. They have not
            # been calibrated as a comparable learning-target measure, so they
            # must never be promoted to a target estimate or weighted into an
            # automated support/content decision.
            "aggregation_role": "descriptive_only",
            "calibration_status": "not_calibrated",
            "eligible_for_learning_target_estimate": False,
        }
    return result, source_rows


@transaction.atomic
def build_student_learning_summary(
    *, student_profile, course: Course, window_type: str, as_of: date
) -> StudentLearningSummary:
    window_start, window_end, period_key = summary_window(
        window_type=window_type, as_of=as_of, course=course
    )
    opportunities = list(
        LearningOpportunity.objects.filter(
            student=student_profile.user,
            course=course,
            assigned_at__gte=window_start,
            assigned_at__lt=window_end,
        )
        .select_related("subject")
        .prefetch_related("transition_facts")
        .order_by("assigned_at", "opportunity_id")
    )
    state_rows = {item.opportunity_id: _latest_states(item) for item in opportunities}
    terminal_states = {
        LearningOpportunityTransitionFact.State.WITHDRAWN,
        LearningOpportunityTransitionFact.State.EXCUSED,
        LearningOpportunityTransitionFact.State.UNAVAILABLE,
    }
    required = [item for item in opportunities if item.required]
    terminal_counts = {
        state: sum(state in state_rows[item.opportunity_id] for item in required)
        for state in terminal_states
    }
    eligible = [
        item
        for item in required
        if not (set(state_rows[item.opportunity_id]) & terminal_states)
    ]
    submitted = [
        item
        for item in eligible
        if LearningOpportunityTransitionFact.State.SUBMITTED
        in state_rows[item.opportunity_id]
    ]
    started = [
        item
        for item in eligible
        if LearningOpportunityTransitionFact.State.STARTED
        in state_rows[item.opportunity_id]
    ]
    graded = [
        item
        for item in eligible
        if LearningOpportunityTransitionFact.State.GRADED
        in state_rows[item.opportunity_id]
    ]
    deadline_items = [item for item in submitted if item.available_to]
    on_time_count = sum(
        state_rows[item.opportunity_id][
            LearningOpportunityTransitionFact.State.SUBMITTED
        ].occurred_at
        <= item.available_to
        for item in deadline_items
    )
    resource_types = {
        LearningOpportunity.ContentType.RESOURCE,
        LearningOpportunity.ContentType.VIDEO,
        LearningOpportunity.ContentType.DOCUMENT,
        LearningOpportunity.ContentType.LEARNING_PAGE,
    }
    resource_items = [item for item in opportunities if item.content_type in resource_types]
    exposed_resources = sum(
        bool(
            set(state_rows[item.opportunity_id])
            & {
                LearningOpportunityTransitionFact.State.EXPOSED,
                LearningOpportunityTransitionFact.State.STARTED,
                LearningOpportunityTransitionFact.State.SUBMITTED,
            }
        )
        for item in resource_items
    )

    result_facts = list(
        AssessmentResultFact.objects.filter(
            student=student_profile.user,
            course=course,
            opportunity_id__in=[item.opportunity_id for item in opportunities],
            grading_state__in={
                AssessmentResultFact.GradingState.FINAL,
                AssessmentResultFact.GradingState.REVISED,
            },
        ).order_by("opportunity_id", "attempt_id", "-grade_version", "-id")
    )
    latest_results = []
    result_seen = set()
    for result in result_facts:
        key = (result.opportunity_id, result.attempt_id)
        if key in result_seen:
            continue
        result_seen.add(key)
        latest_results.append(result)
    score_raw = sum(float(item.score_raw or 0) for item in latest_results)
    score_max = sum(float(item.score_max or 0) for item in latest_results)

    evaluation, evaluation_sources = _evaluation_metrics(
        student=student_profile.user,
        course=course,
        window_start=window_start,
        window_end=window_end,
    )
    point_delta = float(
        ParticipationPointLedger.objects.filter(
            student=student_profile.user,
            course=course,
            occurred_at__gte=window_start,
            occurred_at__lt=window_end,
        ).aggregate(value=Sum("delta"))["value"]
        or 0
    )
    events = LearningEventV2.objects.filter(
        target_student=student_profile.user,
        course=course,
        client_occurred_at__gte=window_start,
        client_occurred_at__lt=window_end,
    )
    event_count = events.count()
    flagged_event_count = events.filter(
        quality_status__in={
            LearningEventV2.QualityStatus.QUARANTINED,
            LearningEventV2.QualityStatus.LEGACY_UNMAPPED,
        }
    ).count()
    interaction_count = events.filter(
        event_name__in={
            "interaction.responded",
            "attendance.status.recorded",
            "evaluation.rating.submitted",
        }
    ).count()

    eligible_count = len(eligible)
    completion_rate = (
        round(len(submitted) / eligible_count, 4) if eligible_count else None
    )
    score_rate = round(score_raw / score_max, 4) if score_max else None
    resource_rate = (
        round(exposed_resources / len(resource_items), 4) if resource_items else None
    )
    on_time_rate = (
        round(on_time_count / len(deadline_items), 4) if deadline_items else None
    )
    quality_flag_rate = (
        round(flagged_event_count / event_count, 4) if event_count else 0
    )

    missing_data = []
    if not opportunities:
        data_status = StudentLearningSummary.DataStatus.NO_OPPORTUNITY
        missing_data.append("当前范围没有学习任务。")
    elif quality_flag_rate > 0.2:
        data_status = StudentLearningSummary.DataStatus.QUALITY_BLOCKED
        missing_data.append("部分学习记录需要学校管理员检查。")
    elif eligible_count < MIN_REQUIRED_OPPORTUNITIES or len(latest_results) < MIN_GRADED_ITEMS:
        data_status = StudentLearningSummary.DataStatus.INSUFFICIENT
        if eligible_count < MIN_REQUIRED_OPPORTUNITIES:
            missing_data.append(
                f"有效学习任务不足 {MIN_REQUIRED_OPPORTUNITIES} 个。"
            )
        if len(latest_results) < MIN_GRADED_ITEMS:
            missing_data.append(f"已评分题目不足 {MIN_GRADED_ITEMS} 个。")
    else:
        data_status = StudentLearningSummary.DataStatus.AVAILABLE
    if not deadline_items:
        missing_data.append("当前范围没有可计算按时提交率的截止时间。")
    if evaluation[ClassroomEvaluationSubmission.EvaluationType.TEACHER][
        "rated_item_count"
    ] == 0:
        missing_data.append("当前范围没有教师评价。")

    metrics = {
        "opportunities": {
            "assigned_count": len(opportunities),
            "required_count": len(required),
            "eligible_count": eligible_count,
            "started_count": len(started),
            "submitted_count": len(submitted),
            "graded_count": len(graded),
            "withdrawn_count": terminal_counts[
                LearningOpportunityTransitionFact.State.WITHDRAWN
            ],
            "excused_count": terminal_counts[
                LearningOpportunityTransitionFact.State.EXCUSED
            ],
            "unavailable_count": terminal_counts[
                LearningOpportunityTransitionFact.State.UNAVAILABLE
            ],
        },
        "completion_rate": completion_rate,
        "on_time_rate": on_time_rate,
        "score": {
            "graded_item_count": len(latest_results),
            "score_raw": round(score_raw, 2),
            "score_max": round(score_max, 2),
            "score_rate": score_rate,
        },
        "resources": {
            "assigned_count": len(resource_items),
            "opened_count": exposed_resources,
            "opened_rate": resource_rate,
        },
        "participation": {
            "interaction_count": interaction_count,
            "point_delta": point_delta,
        },
        "evaluation": evaluation,
        "quality": {
            "event_count": event_count,
            "flagged_event_count": flagged_event_count,
            "flagged_event_rate": quality_flag_rate,
        },
    }
    source_hash = _canonical_hash(
        {
            "opportunities": [
                [
                    str(item.opportunity_id),
                    sorted(state_rows[item.opportunity_id]),
                    item.object_version,
                ]
                for item in opportunities
            ],
            "results": [str(item.result_id) for item in latest_results],
            "evaluations": evaluation_sources,
            "window": [window_start.isoformat(), window_end.isoformat()],
        }
    )
    summary, _ = StudentLearningSummary.objects.update_or_create(
        student=student_profile.user,
        subject=course.subject,
        course=course,
        window_type=window_type,
        period_key=period_key,
        defaults={
            "school": course.subject.school,
            "class_group": student_profile.class_group,
            "window_start": window_start,
            "window_end": window_end,
            "data_status": data_status,
            "metrics": metrics,
            "missing_data": missing_data,
            "source_hash": source_hash,
            "generator_version": SUMMARY_GENERATOR_VERSION,
        },
    )
    return summary


def _support_priority(metrics: dict):
    completion = metrics.get("completion_rate")
    score = metrics.get("score", {}).get("score_rate")
    resource = metrics.get("resources", {}).get("opened_rate")
    weighted = []
    if score is not None:
        weighted.append((float(score), 0.45))
    if completion is not None:
        weighted.append((float(completion), 0.30))
    if resource is not None:
        weighted.append((float(resource), 0.15))
    if not weighted:
        return "", None
    index = sum(value * weight for value, weight in weighted) / sum(
        weight for _value, weight in weighted
    )
    if index >= 0.8:
        return StratificationDecision.SupportPriority.ROUTINE, round(index, 4)
    if index >= 0.6:
        return StratificationDecision.SupportPriority.WATCH, round(index, 4)
    return StratificationDecision.SupportPriority.HIGH, round(index, 4)


@transaction.atomic
def build_transparent_suggestion(*, summary: StudentLearningSummary):
    decision_rule_version = f"{RULE_VERSION}:{summary.source_hash}"
    existing = StratificationDecision.objects.filter(
        student=summary.student,
        course=summary.course,
        window_end=summary.window_end,
        rule_version=decision_rule_version,
    ).first()
    # A rule revision creates a new auditable suggestion. Superseded pending
    # transparent-rule candidates must not remain actionable beside it.
    StratificationDecision.objects.filter(
        student=summary.student,
        course=summary.course,
        window_end=summary.window_end,
        decision_kind=StratificationDecision.DecisionKind.SUPPORT,
        status=StratificationDecision.Status.PENDING,
        rule_version__startswith="transparent-rules-",
    ).exclude(rule_version=decision_rule_version).update(
        status=StratificationDecision.Status.DEFERRED,
        review_note="支持建议规则已更新，本记录仅保留用于审计。",
        reviewed_at=timezone.now(),
    )
    model_candidate = (
        StratificationDecision.objects.filter(
            student=summary.student,
            course=summary.course,
            status=StratificationDecision.Status.PENDING,
            rule_version__startswith="m03-",
            decision_kind=StratificationDecision.DecisionKind.SUPPORT,
        )
        .order_by("-window_end", "-created_at")
        .first()
    )
    if model_candidate:
        if existing and existing.status == StratificationDecision.Status.PENDING:
            existing.status = StratificationDecision.Status.DEFERRED
            existing.review_note = "已有班级校准候选，透明规则仅保留为比较记录。"
            existing.reviewed_at = timezone.now()
            existing.save(update_fields=["status", "review_note", "reviewed_at"])
        return model_candidate
    if existing and existing.status != StratificationDecision.Status.PENDING:
        return existing
    support_priority, index = ("", None)
    reasons = []
    support_suggestion = ""
    if summary.data_status == StudentLearningSummary.DataStatus.AVAILABLE:
        support_priority, index = _support_priority(summary.metrics)
        completion = summary.metrics.get("completion_rate")
        score_rate = summary.metrics.get("score", {}).get("score_rate")
        if score_rate is not None:
            reasons.append(f"本范围已评分任务得分率为 {score_rate * 100:.0f}%。")
        if completion is not None:
            reasons.append(f"有效任务完成率为 {completion * 100:.0f}%。")
        teacher_stars = summary.metrics.get("evaluation", {}).get("teacher", {}).get(
            "average_stars"
        )
        if teacher_stars is not None:
            reasons.append(f"教师评价平均为 {teacher_stars:.1f} 星。")
        support_suggestion = {
            StratificationDecision.SupportPriority.ROUTINE: "可增加开放性任务、迁移应用和同伴支持机会。",
            StratificationDecision.SupportPriority.WATCH: "保持核心任务，并针对薄弱知识点安排一次订正。",
            StratificationDecision.SupportPriority.HIGH: "减少单次任务负担，补充示例、分步提示和及时反馈。",
        }.get(support_priority, "继续收集学习材料后再安排支持。")
    else:
        reasons.append("当前学习材料不足，暂不生成层级变化建议。")
        support_suggestion = "保持当前学习安排，并补充必要的作答和评价材料。"
    current_band = resolve_student_band(
        student=summary.student,
        subject=summary.subject,
        course=summary.course,
    )
    defaults = {
        "class_group": summary.class_group,
        "subject": summary.subject,
        "previous_layer": current_band or "",
        "suggested_layer": "",
        "confidence": 0,
        "reasons": reasons,
        "missing_data": summary.missing_data,
        "learning_summary": {
            "summary_id": summary.id,
            "data_status": summary.data_status,
            "metrics": summary.metrics,
            "source_hash": summary.source_hash,
            "index": index,
            "support_priority": support_priority,
            "confidence_status": "not_estimated",
        },
        "support_suggestion": support_suggestion,
        "decision_kind": StratificationDecision.DecisionKind.SUPPORT,
        "support_priority": support_priority,
        "policy_version": SUPPORT_POLICY_VERSION,
        "window_start": summary.window_start,
        "window_end": summary.window_end,
        "status": StratificationDecision.Status.PENDING,
    }
    if existing:
        for field, value in defaults.items():
            setattr(existing, field, value)
        existing.save()
        decision = existing
    else:
        decision = StratificationDecision.objects.create(
            student=summary.student,
            course=summary.course,
            rule_version=decision_rule_version,
            **defaults,
        )
    recommendation_priority = {
        StratificationDecision.SupportPriority.ROUTINE: LearningSupportRecommendation.Priority.ROUTINE,
        StratificationDecision.SupportPriority.WATCH: LearningSupportRecommendation.Priority.WATCH,
        StratificationDecision.SupportPriority.HIGH: LearningSupportRecommendation.Priority.PRIORITY,
    }.get(support_priority, LearningSupportRecommendation.Priority.ROUTINE)
    valid_until = summary.window_end + timedelta(days=30)
    recommendation_source_hash = _canonical_hash(
        {
            "summary_id": summary.id,
            "summary_source_hash": summary.source_hash,
            "policy_version": SUPPORT_POLICY_VERSION,
            "support_priority": recommendation_priority,
            "suggestion": support_suggestion,
            "rationale": reasons,
            "valid_until": valid_until,
        }
    )
    LearningSupportRecommendation.objects.get_or_create(
        source_decision=decision,
        defaults={
            "target_state": None,
            "source_summary": summary,
            "source_summary_hash": summary.source_hash,
            "source_hash": recommendation_source_hash,
            "evidence_snapshot": {
                "schema_version": 1,
                "summary_id": summary.id,
                "summary_source_hash": summary.source_hash,
                "data_status": summary.data_status,
                "metrics": summary.metrics,
                "missing_data": summary.missing_data,
                "aggregation_role": "descriptive_support_only",
                "learning_target_estimate": None,
                "valid_from": summary.window_end.isoformat(),
                "valid_until": valid_until.isoformat(),
            },
            "priority": recommendation_priority,
            "suggestion": support_suggestion,
            "rationale": reasons,
            "status": LearningSupportRecommendation.Status.PENDING,
        },
    )
    return decision


def rebuild_school_learning_summaries(*, school, as_of: date | None = None):
    as_of = as_of or timezone.localdate()
    counts = {"summaries": 0, "suggestions": 0}
    courses = Course.objects.filter(
        subject__school=school, is_active=True
    ).select_related("subject")
    for course in courses.iterator():
        class_ids = CourseClass.objects.filter(course=course).values_list(
            "class_group_id", flat=True
        )
        profiles = StudentProfile.objects.filter(
            class_group_id__in=class_ids,
            user__is_active=True,
        ).select_related("user", "class_group")
        for profile in profiles.iterator():
            summaries = {}
            for window_type, _label in StudentLearningSummary.WindowType.choices:
                summary = build_student_learning_summary(
                    student_profile=profile,
                    course=course,
                    window_type=window_type,
                    as_of=as_of,
                )
                summaries[window_type] = summary
                counts["summaries"] += 1
            build_transparent_suggestion(
                summary=summaries[StudentLearningSummary.WindowType.DAYS_30]
            )
            counts["suggestions"] += 1
    return counts
