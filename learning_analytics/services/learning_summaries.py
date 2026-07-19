from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from courses.models import ClassroomEvaluationSubmission, Course, CourseClass
from learning.models import StratificationDecision
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
RULE_VERSION = "transparent-rules-v1"
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


def _suggested_layer(metrics: dict):
    completion = metrics.get("completion_rate")
    score = metrics.get("score", {}).get("score_rate")
    resource = metrics.get("resources", {}).get("opened_rate")
    teacher_stars = metrics.get("evaluation", {}).get("teacher", {}).get(
        "average_stars"
    )
    weighted = []
    if score is not None:
        weighted.append((float(score), 0.45))
    if completion is not None:
        weighted.append((float(completion), 0.30))
    if resource is not None:
        weighted.append((float(resource), 0.15))
    if teacher_stars is not None:
        weighted.append((float(teacher_stars) / 5, 0.10))
    if not weighted:
        return "", None
    index = sum(value * weight for value, weight in weighted) / sum(
        weight for _value, weight in weighted
    )
    if index >= 0.8:
        return "A", round(index, 4)
    if index >= 0.6:
        return "B", round(index, 4)
    return "C", round(index, 4)


@transaction.atomic
def build_transparent_suggestion(*, summary: StudentLearningSummary):
    existing = StratificationDecision.objects.filter(
        student=summary.student,
        course=summary.course,
        window_end=summary.window_end,
        rule_version=RULE_VERSION,
    ).first()
    if existing and existing.status != StratificationDecision.Status.PENDING:
        return existing
    suggested_layer, index = ("", None)
    reasons = []
    support_suggestion = ""
    if summary.data_status == StudentLearningSummary.DataStatus.AVAILABLE:
        suggested_layer, index = _suggested_layer(summary.metrics)
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
            "A": "可增加开放性任务、迁移应用和同伴支持机会。",
            "B": "保持核心任务，并针对薄弱知识点安排一次订正。",
            "C": "减少单次任务负担，补充示例、分步提示和及时反馈。",
        }.get(suggested_layer, "继续收集学习材料后再安排支持。")
    else:
        reasons.append("当前学习材料不足，暂不生成层级变化建议。")
        support_suggestion = "保持当前学习安排，并补充必要的作答和评价材料。"
    eligible_count = summary.metrics.get("opportunities", {}).get("eligible_count", 0)
    graded_count = summary.metrics.get("score", {}).get("graded_item_count", 0)
    confidence = (
        min(0.9, 0.4 + min(eligible_count, 10) * 0.03 + min(graded_count, 10) * 0.02)
        if suggested_layer
        else 0
    )
    defaults = {
        "class_group": summary.class_group,
        "subject": summary.subject,
        "previous_layer": summary.student.student_profile.current_layer or "",
        "suggested_layer": suggested_layer,
        "confidence": round(confidence, 3),
        "reasons": reasons,
        "missing_data": summary.missing_data,
        "learning_summary": {
            "summary_id": summary.id,
            "data_status": summary.data_status,
            "metrics": summary.metrics,
            "source_hash": summary.source_hash,
            "index": index,
        },
        "support_suggestion": support_suggestion,
        "window_start": summary.window_start,
        "window_end": summary.window_end,
        "status": StratificationDecision.Status.PENDING,
    }
    if existing:
        for field, value in defaults.items():
            setattr(existing, field, value)
        existing.save()
        return existing
    return StratificationDecision.objects.create(
        student=summary.student,
        course=summary.course,
        rule_version=RULE_VERSION,
        **defaults,
    )


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
