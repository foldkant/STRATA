from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from courses.models import Course, CourseClass
from learning_analytics.feature_models import (
    DecisionPoint,
    DecisionPointStudent,
    FeatureDefinition,
    FeatureSetVersion,
    StudentFeatureSnapshot,
    canonical_hash,
)
from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.feature_registry import (
    FEATURE_SET_KEY,
    FEATURE_SET_VERSION,
    sync_feature_and_outcome_definitions,
)
from learning_analytics.services.quality import latest_quality_report
from school.models import StudentProfile


SNAPSHOT_GENERATOR_VERSION = "feature-snapshot-v1"
WINDOW_DAYS = {"7d": 7, "14d": 14, "30d": 30}
TERMINAL_STATES = {
    LearningOpportunityTransitionFact.State.WITHDRAWN,
    LearningOpportunityTransitionFact.State.EXCUSED,
    LearningOpportunityTransitionFact.State.UNAVAILABLE,
}
RESOURCE_TYPES = {
    LearningOpportunity.ContentType.RESOURCE,
    LearningOpportunity.ContentType.VIDEO,
    LearningOpportunity.ContentType.DOCUMENT,
}


def _result(
    *,
    value=None,
    numerator=None,
    denominator=None,
    missing_code="",
    detail="",
):
    return {
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "missing_code": missing_code,
        "detail": detail,
    }


def _missing(code: str, detail: str, *, denominator=None):
    return _result(
        value=None,
        numerator=None,
        denominator=denominator,
        missing_code=code,
        detail=detail,
    )


def _ratio(numerator: int | float, denominator: int | float, digits: int = 6):
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), digits)


def _scope_synthetic(queryset, decision_point: DecisionPoint, *, prefix: str = ""):
    field_name = f"{prefix}synthetic_run"
    if decision_point.synthetic_run_id:
        return queryset.filter(**{f"{field_name}_id": decision_point.synthetic_run_id})
    return queryset.filter(**{f"{field_name}__isnull": True})


def _data_cutoff(decision_point: DecisionPoint, view_type: str):
    if view_type == StudentFeatureSnapshot.ViewType.OPERATIONAL:
        return decision_point.scheduled_for
    cutoff = decision_point.late_data_cutoff
    if timezone.now() < cutoff:
        raise ValidationError("事后完整数据需要等待允许的补传时间结束后再生成。")
    return cutoff


def _scope_course(queryset, decision_point: DecisionPoint):
    if decision_point.course_id:
        return queryset.filter(course_id=decision_point.course_id)
    return queryset


def _load_feature_context(
    *,
    decision_point: DecisionPoint,
    student,
    view_type: str,
):
    as_of = decision_point.scheduled_for
    data_cutoff = _data_cutoff(decision_point, view_type)
    earliest = as_of - timedelta(days=30)

    opportunities = (
        LearningOpportunity.objects.filter(
            school=decision_point.school,
            class_group=decision_point.class_group,
            subject=decision_point.subject,
            student=student,
            assigned_at__lte=as_of,
            release_event__client_occurred_at__lte=as_of,
            release_event__server_received_at__lte=data_cutoff,
        )
        .filter(Q(assigned_at__gte=earliest) | Q(available_to__gte=earliest))
        .select_related("release_event")
    )
    opportunities = _scope_course(opportunities, decision_point)
    opportunities = _scope_synthetic(
        opportunities, decision_point, prefix="release_event__"
    )
    opportunities = list(opportunities.order_by("assigned_at", "opportunity_id"))
    opportunity_ids = [item.opportunity_id for item in opportunities]

    transitions = list(
        LearningOpportunityTransitionFact.objects.filter(
            opportunity_id__in=opportunity_ids,
            occurred_at__lte=as_of,
            recorded_at__lte=data_cutoff,
            source_event__client_occurred_at__lte=as_of,
            source_event__server_received_at__lte=data_cutoff,
        ).order_by("occurred_at", "id")
    )
    transitions_by_opportunity = defaultdict(list)
    for transition in transitions:
        transitions_by_opportunity[transition.opportunity_id].append(transition)

    results = AssessmentResultFact.objects.filter(
        opportunity_id__in=opportunity_ids,
        student=student,
        subject=decision_point.subject,
        graded_at__lte=as_of,
        recorded_at__lte=data_cutoff,
        source_event__client_occurred_at__lte=as_of,
        source_event__server_received_at__lte=data_cutoff,
        grading_state__in={
            AssessmentResultFact.GradingState.FINAL,
            AssessmentResultFact.GradingState.REVISED,
        },
    )
    results = _scope_course(results, decision_point)
    results = _scope_synthetic(results, decision_point, prefix="source_event__")
    results = list(
        results.order_by("opportunity_id", "attempt_id", "-grade_version", "-id")
    )

    events = LearningEventV2.objects.filter(
        school=decision_point.school,
        class_group=decision_point.class_group,
        subject=decision_point.subject,
        target_student=student,
        client_occurred_at__gte=earliest,
        client_occurred_at__lte=as_of,
        server_received_at__lte=data_cutoff,
    )
    events = _scope_course(events, decision_point)
    events = _scope_synthetic(events, decision_point)
    events = list(events.order_by("client_occurred_at", "id"))

    latest_results = []
    seen_attempts = set()
    for result in results:
        key = (result.opportunity_id, result.attempt_id)
        if key in seen_attempts:
            continue
        seen_attempts.add(key)
        latest_results.append(result)

    first_results = {}
    for result in sorted(latest_results, key=lambda item: (item.graded_at, item.id)):
        first_results.setdefault(result.opportunity_id, result)

    source_facts = {
        "opportunities": [
            [
                str(item.opportunity_id),
                item.object_version,
                item.assigned_at.isoformat(),
            ]
            for item in opportunities
        ],
        "transitions": [str(item.transition_id) for item in transitions],
        "results": [str(item.result_id) for item in results],
        "events": [str(item.event_id) for item in events],
        "as_of": as_of.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "view_type": view_type,
    }
    return {
        "as_of": as_of,
        "data_cutoff": data_cutoff,
        "earliest": earliest,
        "opportunities": opportunities,
        "transitions": transitions_by_opportunity,
        "events": events,
        "first_results": first_results,
        "source_facts": source_facts,
    }


def _window_items(context, window: str):
    if window == "unit":
        return [], []
    start = context["as_of"] - timedelta(days=WINDOW_DAYS[window])
    opportunities = [
        item for item in context["opportunities"] if item.assigned_at >= start
    ]
    events = [item for item in context["events"] if item.client_occurred_at >= start]
    return opportunities, events


def _latest_states(context, opportunity):
    states = {}
    for transition in context["transitions"].get(opportunity.opportunity_id, []):
        states[transition.state] = transition
    return states


def _eligible_due(context, opportunities, *, window_start):
    result = []
    for opportunity in opportunities:
        if not opportunity.required or not opportunity.available_to:
            continue
        if not (window_start < opportunity.available_to <= context["as_of"]):
            continue
        states = _latest_states(context, opportunity)
        if set(states) & TERMINAL_STATES:
            continue
        result.append((opportunity, states))
    return result


def _feature_due_count(context, window, definition):
    window_start = context["as_of"] - timedelta(days=WINDOW_DAYS[window])
    due = _eligible_due(context, context["opportunities"], window_start=window_start)
    if not due:
        return _missing(
            "NO_OPPORTUNITY", "当前窗口没有已到期的有效必做任务。", denominator=0
        )
    return _result(value=len(due), numerator=len(due), denominator=len(due))


def _feature_completion(context, window, definition):
    window_start = context["as_of"] - timedelta(days=WINDOW_DAYS[window])
    due = _eligible_due(context, context["opportunities"], window_start=window_start)
    denominator = len(due)
    if denominator == 0:
        return _missing(
            "NO_OPPORTUNITY", "当前窗口没有已到期的有效必做任务。", denominator=0
        )
    if denominator < definition.min_n:
        return _missing(
            "INSUFFICIENT_N",
            f"有效已到期任务少于 {definition.min_n} 个。",
            denominator=denominator,
        )
    completed = sum(
        LearningOpportunityTransitionFact.State.SUBMITTED in states
        for _item, states in due
    )
    return _result(
        value=_ratio(completed, denominator),
        numerator=completed,
        denominator=denominator,
    )


def _feature_on_time(context, window, definition):
    window_start = context["as_of"] - timedelta(days=WINDOW_DAYS[window])
    due = _eligible_due(context, context["opportunities"], window_start=window_start)
    denominator = len(due)
    if denominator == 0:
        return _missing(
            "NO_OPPORTUNITY", "当前窗口没有带截止时间的有效必做任务。", denominator=0
        )
    if denominator < definition.min_n:
        return _missing(
            "INSUFFICIENT_N",
            f"带截止时间的有效任务少于 {definition.min_n} 个。",
            denominator=denominator,
        )
    on_time = 0
    for opportunity, states in due:
        submitted = states.get(LearningOpportunityTransitionFact.State.SUBMITTED)
        if submitted and submitted.occurred_at <= opportunity.available_to:
            on_time += 1
    return _result(
        value=_ratio(on_time, denominator),
        numerator=on_time,
        denominator=denominator,
    )


def _heartbeat_seconds(events):
    heartbeats = [item for item in events if item.event_name == "session.heartbeat"]
    seconds = 0.0
    day_seconds = defaultdict(float)
    previous = None
    for event in heartbeats:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if previous is not None:
            previous_payload = (
                previous.payload if isinstance(previous.payload, dict) else {}
            )
            same_session = (
                event.client_session_id
                and previous.client_session_id == event.client_session_id
            )
            delta = (
                event.client_occurred_at - previous.client_occurred_at
            ).total_seconds()
            if (
                same_session
                and 0 < delta <= 120
                and payload.get("foreground") is True
                and previous_payload.get("foreground") is True
                and int(payload.get("idle_seconds") or 0) <= 120
                and int(previous_payload.get("idle_seconds") or 0) <= 120
            ):
                seconds += delta
                day_seconds[event.client_occurred_at.date()] += delta
        previous = event
    return seconds, day_seconds, len(heartbeats)


def _feature_active_minutes(context, window, definition):
    opportunities, events = _window_items(context, window)
    if not opportunities:
        return _missing("NO_OPPORTUNITY", "当前窗口没有学习任务。", denominator=0)
    seconds, _day_seconds, heartbeat_count = _heartbeat_seconds(events)
    if heartbeat_count == 0:
        started = any(
            LearningOpportunityTransitionFact.State.STARTED
            in _latest_states(context, item)
            for item in opportunities
        )
        return _missing(
            "DATA_ERROR" if started else "NOT_STARTED",
            "已有开始记录但缺少心跳。" if started else "当前窗口没有开始学习的记录。",
            denominator=len(opportunities),
        )
    return _result(
        value=round(seconds / 60, 3),
        numerator=round(seconds, 3),
        denominator=heartbeat_count,
        detail="分子为合并后的有效秒数，分母为心跳条数。",
    )


def _feature_active_days(context, window, definition):
    opportunities, events = _window_items(context, window)
    opportunity_days = {item.assigned_at.date() for item in opportunities}
    denominator = len(opportunity_days)
    if denominator == 0:
        return _missing("NO_OPPORTUNITY", "当前窗口没有学习机会日期。", denominator=0)
    if denominator < definition.min_n:
        return _missing(
            "INSUFFICIENT_N",
            f"学习机会日期少于 {definition.min_n} 天。",
            denominator=denominator,
        )
    _seconds, day_seconds, heartbeat_count = _heartbeat_seconds(events)
    if heartbeat_count == 0:
        return _missing(
            "NOT_STARTED", "当前窗口没有开始学习的心跳记录。", denominator=denominator
        )
    active_days = sum(day_seconds.get(day, 0) >= 300 for day in opportunity_days)
    return _result(
        value=_ratio(active_days, denominator),
        numerator=active_days,
        denominator=denominator,
    )


def _resource_progress(event):
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event.event_name == "video.progress":
        total = float(payload.get("media_seconds") or 0)
        return float(payload.get("position_seconds") or 0) / total if total else None
    if event.event_name == "document.progress":
        total = int(payload.get("page_count") or 0)
        return int(payload.get("page") or 0) / total if total else None
    return None


def _feature_resource_completion(context, window, definition):
    opportunities, events = _window_items(context, window)
    resources = [
        item
        for item in opportunities
        if item.required and item.content_type in RESOURCE_TYPES
    ]
    denominator = len(resources)
    if denominator == 0:
        return _missing("NO_OPPORTUNITY", "当前窗口没有必看资源。", denominator=0)
    if denominator < definition.min_n:
        return _missing(
            "INSUFFICIENT_N",
            f"可计算资源少于 {definition.min_n} 个。",
            denominator=denominator,
        )
    progress_by_opportunity = defaultdict(list)
    for event in events:
        if event.event_name not in {"video.progress", "document.progress"}:
            continue
        if event.opportunity_record_id:
            progress = _resource_progress(event)
            if progress is not None:
                progress_by_opportunity[event.opportunity_record_id].append(progress)
    unsupported = [
        item
        for item in resources
        if item.content_type == LearningOpportunity.ContentType.RESOURCE
        and item.opportunity_id not in progress_by_opportunity
    ]
    if unsupported:
        return _missing(
            "NOT_APPLICABLE",
            "部分资源没有可验证的完成规则，不能用打开记录代替完成。",
            denominator=denominator,
        )
    completed = sum(
        max(progress_by_opportunity.get(item.opportunity_id, [0])) >= 0.9
        for item in resources
    )
    return _result(
        value=_ratio(completed, denominator),
        numerator=completed,
        denominator=denominator,
    )


def _window_first_results(context, window):
    start = context["as_of"] - timedelta(days=WINDOW_DAYS[window])
    return [
        item for item in context["first_results"].values() if item.graded_at >= start
    ]


def _feature_graded_count(context, window, definition):
    results = _window_first_results(context, window)
    if not context["opportunities"]:
        return _missing("NO_OPPORTUNITY", "当前窗口没有学习任务。", denominator=0)
    if not results:
        return _missing(
            "IN_PROGRESS", "当前窗口没有已完成最终评分的题目。", denominator=0
        )
    return _result(value=len(results), numerator=len(results), denominator=len(results))


def _feature_score_ratio(context, window, definition):
    results = _window_first_results(context, window)
    denominator_count = len(results)
    if denominator_count == 0:
        code = "NO_OPPORTUNITY" if not context["opportunities"] else "IN_PROGRESS"
        return _missing(code, "当前窗口没有已完成最终评分的题目。", denominator=0)
    if denominator_count < definition.min_n:
        return _missing(
            "INSUFFICIENT_N",
            f"首次最终评分题目少于 {definition.min_n} 道。",
            denominator=denominator_count,
        )
    score_raw = sum(Decimal(item.score_raw or 0) for item in results)
    score_max = sum(Decimal(item.score_max or 0) for item in results)
    if not score_max:
        return _missing(
            "DATA_ERROR", "评分满分合计为 0。", denominator=denominator_count
        )
    return _result(
        value=round(float(score_raw / score_max), 6),
        numerator=float(score_raw),
        denominator=float(score_max),
    )


def _feature_accuracy(context, window, definition):
    results = [
        item
        for item in _window_first_results(context, window)
        if item.is_correct is not None
    ]
    denominator = len(results)
    if denominator == 0:
        return _missing(
            "NO_OPPORTUNITY", "当前窗口没有可判断正误的首次评分题目。", denominator=0
        )
    if denominator < definition.min_n:
        return _missing(
            "INSUFFICIENT_N",
            f"可判断正误的首次评分题目少于 {definition.min_n} 道。",
            denominator=denominator,
        )
    correct = sum(item.is_correct is True for item in results)
    return _result(
        value=_ratio(correct, denominator),
        numerator=correct,
        denominator=denominator,
    )


def _feature_interventions(context, window, definition):
    opportunities, events = _window_items(context, window)
    if not opportunities:
        return _missing("NO_OPPORTUNITY", "当前窗口没有学习任务。", denominator=0)
    count = sum(item.event_name == "intervention.created" for item in events)
    return _result(value=count, numerator=count, denominator=len(opportunities))


def _feature_event_quality(context, window, definition):
    opportunities, events = _window_items(context, window)
    denominator = len(events)
    if denominator == 0:
        code = "NO_OPPORTUNITY" if not opportunities else "NOT_STARTED"
        return _missing(code, "当前窗口没有可检查的学生学习事件。", denominator=0)
    flagged = sum(
        item.quality_status
        in {
            LearningEventV2.QualityStatus.QUARANTINED,
            LearningEventV2.QualityStatus.LEGACY_UNMAPPED,
        }
        or bool(item.quality_errors)
        for item in events
    )
    return _result(
        value=_ratio(flagged, denominator),
        numerator=flagged,
        denominator=denominator,
    )


GENERATORS = {
    "prior_due_required_count": _feature_due_count,
    "opp_completion_rate": _feature_completion,
    "on_time_submission_rate": _feature_on_time,
    "active_minutes": _feature_active_minutes,
    "active_days_ratio": _feature_active_days,
    "resource_completion_rate": _feature_resource_completion,
    "prior_graded_item_count": _feature_graded_count,
    "first_attempt_score_ratio": _feature_score_ratio,
    "first_attempt_accuracy": _feature_accuracy,
    "intervention_count": _feature_interventions,
    "event_quality_flag_rate": _feature_event_quality,
}


def _calculate_feature(context, definition: FeatureDefinition, window: str):
    if window == "unit":
        return _missing("NOT_APPLICABLE", "当前时间点没有登记统一单元边界。")
    generator = GENERATORS.get(definition.generator_key)
    if generator is None:
        return _missing("NOT_APPLICABLE", "当前数据或验证条件尚不支持计算该项。")
    return generator(context, window, definition)


def _quality_report_for_point(decision_point: DecisionPoint):
    return latest_quality_report(
        school=decision_point.school,
        as_of=decision_point.scheduled_for,
        synthetic_run=decision_point.synthetic_run,
    )


@transaction.atomic
def build_student_feature_snapshot(
    *,
    decision_point: DecisionPoint,
    student,
    view_type: str = StudentFeatureSnapshot.ViewType.OPERATIONAL,
) -> StudentFeatureSnapshot:
    if decision_point.status != DecisionPoint.Status.FROZEN:
        raise ValidationError("分析时间点冻结后才能生成特征快照。")
    membership = DecisionPointStudent.objects.filter(
        decision_point=decision_point,
        student=student,
        included=True,
    ).first()
    if membership is None:
        raise ValidationError("学生不在该分析时间点的冻结范围内。")
    existing = StudentFeatureSnapshot.objects.filter(
        decision_point=decision_point,
        student=student,
        view_type=view_type,
    ).first()
    if existing:
        return existing

    definitions = {
        item.feature_key: item
        for item in FeatureDefinition.objects.filter(
            status=FeatureDefinition.Status.ACTIVE,
            feature_key__in=[
                entry["feature_key"]
                for entry in decision_point.feature_set.definition_manifest
            ],
        )
    }
    context = _load_feature_context(
        decision_point=decision_point,
        student=student,
        view_type=view_type,
    )
    values = {}
    numerators = {}
    denominators = {}
    missing_codes = {}
    details = {}
    window_starts = {}
    model_missing = []
    for entry in decision_point.feature_set.definition_manifest:
        definition = definitions[entry["feature_key"]]
        for window in entry["windows"]:
            output_key = f"{definition.feature_key}__{window}"
            if window in WINDOW_DAYS:
                window_starts[window] = (
                    decision_point.scheduled_for - timedelta(days=WINDOW_DAYS[window])
                ).isoformat()
            result = _calculate_feature(context, definition, window)
            values[output_key] = result["value"]
            numerators[output_key] = result["numerator"]
            denominators[output_key] = result["denominator"]
            if result["missing_code"]:
                missing_codes[output_key] = result["missing_code"]
                if definition.model_input_allowed and result["missing_code"] in {
                    "OFFLINE",
                    "DATA_ERROR",
                }:
                    model_missing.append(output_key)
            if result["detail"]:
                details[output_key] = result["detail"]

    report = _quality_report_for_point(decision_point)
    if report is None or not report.checks_passed:
        quality_status = StudentFeatureSnapshot.QualityStatus.BLOCKED
        details["_quality"] = (
            "该时间点之前没有通过的学习数据检查。"
            if report is None
            else "该时间点之前最近一次学习数据检查未通过。"
        )
    elif model_missing:
        quality_status = StudentFeatureSnapshot.QualityStatus.DEGRADED
        details["_quality"] = "部分可用于模型的学习记录需要检查。"
    else:
        quality_status = StudentFeatureSnapshot.QualityStatus.READY

    source_hash = canonical_hash(
        {
            "feature_set": decision_point.feature_set.manifest_hash,
            "facts": context["source_facts"],
            "values": values,
            "numerators": numerators,
            "denominators": denominators,
            "missing_codes": missing_codes,
        }
    )
    return StudentFeatureSnapshot.objects.create(
        decision_point=decision_point,
        student=student,
        school=decision_point.school,
        class_group=decision_point.class_group,
        subject=decision_point.subject,
        course=decision_point.course,
        feature_set=decision_point.feature_set,
        view_type=view_type,
        as_of=decision_point.scheduled_for,
        values=values,
        numerators=numerators,
        denominators=denominators,
        missing_codes=missing_codes,
        details=details,
        window_starts=window_starts,
        source_watermark={
            "client_occurred_through": decision_point.scheduled_for.isoformat(),
            "server_received_through": context["data_cutoff"].isoformat(),
            "quality_report_id": report.id if report else None,
        },
        quality_status=quality_status,
        source_hash=source_hash,
        generator_version=SNAPSHOT_GENERATOR_VERSION,
    )


@transaction.atomic
def freeze_decision_point(decision_point: DecisionPoint) -> dict:
    decision_point = DecisionPoint.objects.select_for_update().get(pk=decision_point.pk)
    if decision_point.status == DecisionPoint.Status.FROZEN:
        return {
            "decision_point": decision_point,
            "student_count": decision_point.student_scope.filter(included=True).count(),
            "snapshot_count": decision_point.feature_snapshots.count(),
        }
    if decision_point.status != DecisionPoint.Status.PLANNED:
        raise ValidationError("只有已计划的分析时间点可以冻结。")
    if decision_point.scheduled_for > timezone.now():
        raise ValidationError("尚未到达计划时间，不能提前冻结。")

    profiles = list(
        StudentProfile.objects.filter(
            class_group=decision_point.class_group,
            user__role="student",
        ).select_related("user")
    )
    if not profiles:
        raise ValidationError("当前班级没有学生，不能建立分析时间点。")
    for profile in profiles:
        included = profile.user.is_active
        DecisionPointStudent.objects.create(
            decision_point=decision_point,
            student=profile.user,
            eligibility_status=(
                DecisionPointStudent.EligibilityStatus.ELIGIBLE
                if included
                else DecisionPointStudent.EligibilityStatus.INACTIVE
            ),
            reason_code="" if included else "ACCOUNT_INACTIVE_AT_T0",
            included=included,
        )
    report = _quality_report_for_point(decision_point)
    decision_point.context_snapshot = {
        "class_group": {
            "id": decision_point.class_group_id,
            "name": decision_point.class_group.name,
            "grade": decision_point.class_group.grade,
        },
        "subject": {
            "id": decision_point.subject_id,
            "name": decision_point.subject.name,
            "code": decision_point.subject.code,
        },
        "course": (
            {"id": decision_point.course_id, "title": decision_point.course.title}
            if decision_point.course_id
            else None
        ),
        "eligible_student_count": sum(profile.user.is_active for profile in profiles),
        "excluded_student_count": sum(
            not profile.user.is_active for profile in profiles
        ),
        "quality_report_id": report.id if report else None,
        "quality_checks_passed": bool(report and report.checks_passed),
        "data_scope": "synthetic" if decision_point.synthetic_run_id else "formal",
    }
    decision_point.status = DecisionPoint.Status.FROZEN
    decision_point.frozen_at = timezone.now()
    decision_point.save()

    snapshots = 0
    for membership in decision_point.student_scope.filter(included=True).select_related(
        "student"
    ):
        build_student_feature_snapshot(
            decision_point=decision_point,
            student=membership.student,
        )
        snapshots += 1

    from learning_analytics.services.outcomes import ensure_pending_outcomes

    ensure_pending_outcomes(decision_point=decision_point)
    return {
        "decision_point": decision_point,
        "student_count": decision_point.student_scope.filter(included=True).count(),
        "snapshot_count": snapshots,
    }


@transaction.atomic
def create_decision_point(
    *,
    school,
    class_group,
    subject,
    course: Course | None,
    scheduled_for: datetime,
    created_by,
    point_type: str = DecisionPoint.PointType.MANUAL,
    purpose: str = DecisionPoint.Purpose.PILOT,
    synthetic_run=None,
    title: str = "",
) -> dict:
    sync_feature_and_outcome_definitions()
    if class_group.school_id != school.id or subject.school_id != school.id:
        raise ValidationError("班级、学科与学校不一致。")
    if course:
        if course.subject_id != subject.id:
            raise ValidationError("课程与学科不一致。")
        if not CourseClass.objects.filter(
            course=course, class_group=class_group
        ).exists():
            raise ValidationError("该课程没有分配给所选班级。")
    feature_set = FeatureSetVersion.objects.get(
        set_key=FEATURE_SET_KEY,
        version=FEATURE_SET_VERSION,
        status=FeatureSetVersion.Status.ACTIVE,
    )
    point = DecisionPoint.objects.create(
        school=school,
        synthetic_run=synthetic_run,
        class_group=class_group,
        subject=subject,
        course=course,
        feature_set=feature_set,
        title=title or f"{class_group.name} {subject.name} 学习分析",
        point_type=point_type,
        purpose=purpose,
        status=DecisionPoint.Status.PLANNED,
        scheduled_for=scheduled_for,
        source="manual",
        created_by=created_by,
    )
    if scheduled_for <= timezone.now():
        return freeze_decision_point(point)
    return {"decision_point": point, "student_count": 0, "snapshot_count": 0}


def freeze_due_decision_points(*, as_of=None) -> dict:
    as_of = as_of or timezone.now()
    counts = {"frozen": 0, "snapshots": 0, "failed": 0}
    point_ids = list(
        DecisionPoint.objects.filter(
            status=DecisionPoint.Status.PLANNED,
            scheduled_for__lte=as_of,
        ).values_list("id", flat=True)
    )
    for point_id in point_ids:
        try:
            result = freeze_decision_point(DecisionPoint.objects.get(pk=point_id))
        except Exception:
            counts["failed"] += 1
        else:
            counts["frozen"] += 1
            counts["snapshots"] += result["snapshot_count"]
    return counts
