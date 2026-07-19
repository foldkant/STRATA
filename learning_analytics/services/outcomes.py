from __future__ import annotations

import hashlib
import hmac
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from learning_analytics.feature_models import (
    DecisionPoint,
    DecisionPointStudent,
    FeatureDefinition,
    OutcomeDefinition,
    OutcomeObservation,
    StudentFeatureSnapshot,
    TrainingDatasetRow,
    TrainingDatasetVersion,
    canonical_hash,
)
from learning_analytics.models import (
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.feature_registry import (
    sync_feature_and_outcome_definitions,
)
from learning_analytics.services.quality import latest_quality_report


OUTCOME_GENERATOR_VERSION = "outcome-v1"
DATASET_GENERATOR_VERSION = "training-dataset-v1"
SPLIT_STRATEGY = "fixed_group_and_time_v1"
TERMINAL_STATES = {
    LearningOpportunityTransitionFact.State.WITHDRAWN,
    LearningOpportunityTransitionFact.State.EXCUSED,
    LearningOpportunityTransitionFact.State.UNAVAILABLE,
}


def _scope_synthetic(queryset, decision_point: DecisionPoint, *, prefix: str = ""):
    field_name = f"{prefix}synthetic_run"
    if decision_point.synthetic_run_id:
        return queryset.filter(**{f"{field_name}_id": decision_point.synthetic_run_id})
    return queryset.filter(**{f"{field_name}__isnull": True})


def _scope_course(queryset, decision_point: DecisionPoint):
    if decision_point.course_id:
        return queryset.filter(course_id=decision_point.course_id)
    return queryset


def _observation_window(decision_point: DecisionPoint, definition: OutcomeDefinition):
    return (
        decision_point.scheduled_for,
        decision_point.scheduled_for + timedelta(days=definition.horizon_days),
    )


@transaction.atomic
def ensure_pending_outcomes(*, decision_point: DecisionPoint) -> int:
    sync_feature_and_outcome_definitions()
    definitions = list(
        OutcomeDefinition.objects.filter(status=OutcomeDefinition.Status.ACTIVE)
    )
    memberships = list(
        DecisionPointStudent.objects.filter(
            decision_point=decision_point,
            included=True,
        ).select_related("student")
    )
    created = 0
    for membership in memberships:
        for definition in definitions:
            if OutcomeObservation.objects.filter(
                decision_point=decision_point,
                student=membership.student,
                outcome_definition=definition,
            ).exists():
                continue
            window_start, window_end = _observation_window(decision_point, definition)
            OutcomeObservation.objects.create(
                decision_point=decision_point,
                student=membership.student,
                outcome_definition=definition,
                observation_version=1,
                status=OutcomeObservation.Status.PENDING,
                eligibility_status=OutcomeObservation.EligibilityStatus.NOT_MATURE,
                window_start=window_start,
                window_end=window_end,
                evidence_refs=[],
                source_hash=canonical_hash(
                    {
                        "decision_id": str(decision_point.decision_id),
                        "student_id": membership.student_id,
                        "outcome_definition": definition.definition_hash,
                        "window_start": window_start,
                        "window_end": window_end,
                        "status": "pending",
                    }
                ),
            )
            created += 1
    return created


def _future_context(
    *,
    pending: OutcomeObservation,
    data_cutoff,
):
    point = pending.decision_point
    opportunities = LearningOpportunity.objects.filter(
        school=point.school,
        class_group=point.class_group,
        subject=point.subject,
        student=pending.student,
        required=True,
        available_to__gt=pending.window_start,
        available_to__lte=pending.window_end,
        release_event__client_occurred_at__lte=pending.window_end,
        release_event__server_received_at__lte=data_cutoff,
    ).select_related("release_event")
    opportunities = _scope_course(opportunities, point)
    opportunities = _scope_synthetic(opportunities, point, prefix="release_event__")
    opportunities = list(opportunities.order_by("available_to", "opportunity_id"))
    opportunity_ids = [item.opportunity_id for item in opportunities]
    transitions = list(
        LearningOpportunityTransitionFact.objects.filter(
            opportunity_id__in=opportunity_ids,
            occurred_at__lte=pending.window_end,
            recorded_at__lte=data_cutoff,
            source_event__client_occurred_at__lte=pending.window_end,
            source_event__server_received_at__lte=data_cutoff,
        ).order_by("occurred_at", "id")
    )
    by_opportunity = defaultdict(list)
    for transition in transitions:
        by_opportunity[transition.opportunity_id].append(transition)
    eligible = []
    for opportunity in opportunities:
        states = {}
        for transition in by_opportunity[opportunity.opportunity_id]:
            states[transition.state] = transition
        if set(states) & TERMINAL_STATES:
            continue
        eligible.append((opportunity, states))
    return {
        "opportunities": opportunities,
        "eligible": eligible,
        "transitions": transitions,
        "source_hash": canonical_hash(
            {
                "opportunities": [
                    [
                        str(item.opportunity_id),
                        item.object_version,
                        item.available_to,
                    ]
                    for item in opportunities
                ],
                "transitions": [str(item.transition_id) for item in transitions],
                "window_start": pending.window_start,
                "window_end": pending.window_end,
                "data_cutoff": data_cutoff,
            }
        ),
    }


def _final_result(
    *,
    pending: OutcomeObservation,
    context,
    status: str,
    eligibility_status: str,
    value=None,
    numerator=None,
    denominator=None,
    missing_code="",
    exclusion_reason="",
):
    evidence_refs = [
        {
            "opportunity_id": str(item.opportunity_id),
            "object_version": item.object_version,
            "available_to": item.available_to.isoformat()
            if item.available_to
            else None,
        }
        for item in context["opportunities"]
    ]
    source_hash = canonical_hash(
        {
            "pending_source_hash": pending.source_hash,
            "future_source_hash": context["source_hash"],
            "status": status,
            "eligibility_status": eligibility_status,
            "value": value,
            "numerator": numerator,
            "denominator": denominator,
            "missing_code": missing_code,
            "exclusion_reason": exclusion_reason,
        }
    )
    return OutcomeObservation.objects.create(
        decision_point=pending.decision_point,
        student=pending.student,
        outcome_definition=pending.outcome_definition,
        observation_version=pending.observation_version + 1,
        supersedes=pending,
        status=status,
        eligibility_status=eligibility_status,
        window_start=pending.window_start,
        window_end=pending.window_end,
        value=value,
        numerator=numerator,
        denominator=denominator,
        missing_code=missing_code,
        exclusion_reason=exclusion_reason,
        evidence_refs=evidence_refs,
        source_hash=source_hash,
        frozen_at=timezone.now(),
    )


def _completion_outcome(pending: OutcomeObservation, context):
    denominator = len(context["eligible"])
    if denominator == 0:
        return _final_result(
            pending=pending,
            context=context,
            status=OutcomeObservation.Status.UNOBSERVED,
            eligibility_status=OutcomeObservation.EligibilityStatus.NO_OPPORTUNITY,
            denominator=0,
            missing_code="NO_OPPORTUNITY",
            exclusion_reason="未来 7 日没有有效已到期必做任务。",
        )
    if denominator < pending.outcome_definition.min_denominator:
        return _final_result(
            pending=pending,
            context=context,
            status=OutcomeObservation.Status.UNOBSERVED,
            eligibility_status=OutcomeObservation.EligibilityStatus.INSUFFICIENT_N,
            denominator=denominator,
            missing_code="INSUFFICIENT_N",
            exclusion_reason=(
                f"未来 7 日有效已到期任务少于 "
                f"{pending.outcome_definition.min_denominator} 个。"
            ),
        )
    completed = sum(
        LearningOpportunityTransitionFact.State.SUBMITTED in states
        for _item, states in context["eligible"]
    )
    return _final_result(
        pending=pending,
        context=context,
        status=OutcomeObservation.Status.OBSERVED,
        eligibility_status=OutcomeObservation.EligibilityStatus.ELIGIBLE,
        value=(Decimal(completed) / Decimal(denominator)).quantize(Decimal("0.000001")),
        numerator=completed,
        denominator=denominator,
    )


def _overdue_outcome(pending: OutcomeObservation, context):
    denominator = len(context["eligible"])
    if denominator == 0:
        return _final_result(
            pending=pending,
            context=context,
            status=OutcomeObservation.Status.UNOBSERVED,
            eligibility_status=OutcomeObservation.EligibilityStatus.NO_OPPORTUNITY,
            denominator=0,
            missing_code="NO_OPPORTUNITY",
            exclusion_reason="未来 7 日没有带截止时间的有效必做任务。",
        )
    overdue = 0
    for opportunity, states in context["eligible"]:
        submitted = states.get(LearningOpportunityTransitionFact.State.SUBMITTED)
        if submitted is None or submitted.occurred_at > opportunity.available_to:
            overdue += 1
    return _final_result(
        pending=pending,
        context=context,
        status=OutcomeObservation.Status.OBSERVED,
        eligibility_status=OutcomeObservation.EligibilityStatus.ELIGIBLE,
        value=overdue,
        numerator=overdue,
        denominator=denominator,
    )


OUTCOME_GENERATORS = {
    "required_completion_next_7d": _completion_outcome,
    "new_overdue_count_next_7d": _overdue_outcome,
}


@transaction.atomic
def mature_outcome_observation(
    pending: OutcomeObservation,
    *,
    as_of=None,
) -> OutcomeObservation:
    as_of = as_of or timezone.now()
    if pending.status != OutcomeObservation.Status.PENDING:
        return pending
    existing_final = OutcomeObservation.objects.filter(
        supersedes=pending,
    ).first()
    if existing_final:
        return existing_final
    maturity_cutoff = pending.window_end + timedelta(
        minutes=pending.decision_point.allowed_lateness_minutes
    )
    if as_of < maturity_cutoff:
        return pending
    point = pending.decision_point
    try:
        profile = pending.student.student_profile
    except Exception:
        profile = None
    context = _future_context(pending=pending, data_cutoff=maturity_cutoff)
    if profile is None or profile.class_group_id != point.class_group_id:
        return _final_result(
            pending=pending,
            context=context,
            status=OutcomeObservation.Status.EXCLUDED,
            eligibility_status=OutcomeObservation.EligibilityStatus.COMPETING_EVENT,
            missing_code="NOT_APPLICABLE",
            exclusion_reason="学生在结果冻结时已不属于原班级，需按转班情况单独处理。",
        )
    quality_report = latest_quality_report(
        school=point.school,
        as_of=pending.window_end,
        synthetic_run=point.synthetic_run,
    )
    if quality_report is None or not quality_report.checks_passed:
        return _final_result(
            pending=pending,
            context=context,
            status=OutcomeObservation.Status.UNOBSERVED,
            eligibility_status=OutcomeObservation.EligibilityStatus.DATA_ERROR,
            missing_code="DATA_ERROR",
            exclusion_reason=(
                "结果窗口结束前没有通过的学习数据检查。"
                if quality_report is None
                else "结果窗口对应的学习数据检查未通过。"
            ),
        )
    generator = OUTCOME_GENERATORS.get(pending.outcome_definition.generator_key)
    if generator is None:
        return _final_result(
            pending=pending,
            context=context,
            status=OutcomeObservation.Status.UNOBSERVED,
            eligibility_status=OutcomeObservation.EligibilityStatus.DATA_ERROR,
            missing_code="NOT_APPLICABLE",
            exclusion_reason="当前版本没有登记对应结果计算器。",
        )
    return generator(pending, context)


def mature_due_outcomes(*, school=None, as_of=None, synthetic_run=None) -> dict:
    as_of = as_of or timezone.now()
    query = OutcomeObservation.objects.filter(
        status=OutcomeObservation.Status.PENDING,
        window_end__lte=as_of,
    ).select_related(
        "decision_point",
        "decision_point__school",
        "decision_point__synthetic_run",
        "student",
        "outcome_definition",
    )
    if school is not None:
        query = query.filter(decision_point__school=school)
    if synthetic_run is None:
        query = query.filter(decision_point__synthetic_run__isnull=True)
    else:
        query = query.filter(decision_point__synthetic_run=synthetic_run)
    counts = {"observed": 0, "unobserved": 0, "excluded": 0, "pending": 0}
    for pending in list(query.order_by("window_end", "id")):
        result = mature_outcome_observation(pending, as_of=as_of)
        counts[result.status] += 1
    return counts


def _latest_final_observations(queryset):
    latest = {}
    for item in queryset.order_by(
        "decision_point_id",
        "student_id",
        "-observation_version",
        "-id",
    ):
        key = (item.decision_point_id, item.student_id)
        if key not in latest and item.status != OutcomeObservation.Status.PENDING:
            latest[key] = item
    return list(latest.values())


def _group_split(pseudonymous_key: str) -> str:
    bucket = int(pseudonymous_key[:8], 16) % 100
    if bucket < 70:
        return TrainingDatasetRow.Split.TRAIN
    if bucket < 85:
        return TrainingDatasetRow.Split.VALIDATION
    return TrainingDatasetRow.Split.TEST


def _time_splits(decision_dates):
    dates = sorted(set(decision_dates))
    if len(dates) == 1:
        return {dates[0]: TrainingDatasetRow.Split.TRAIN}
    if len(dates) == 2:
        return {
            dates[0]: TrainingDatasetRow.Split.TRAIN,
            dates[1]: TrainingDatasetRow.Split.TEST,
        }
    train_count = max(1, int(len(dates) * 0.7))
    validation_count = max(1, int(len(dates) * 0.15))
    if train_count + validation_count >= len(dates):
        train_count = len(dates) - 2
        validation_count = 1
    mapping = {}
    for index, value in enumerate(dates):
        if index < train_count:
            mapping[value] = TrainingDatasetRow.Split.TRAIN
        elif index < train_count + validation_count:
            mapping[value] = TrainingDatasetRow.Split.VALIDATION
        else:
            mapping[value] = TrainingDatasetRow.Split.TEST
    return mapping


@transaction.atomic
def build_training_dataset(
    *,
    school,
    subject,
    outcome_definition: OutcomeDefinition,
    created_by,
    decision_start=None,
    decision_end=None,
    synthetic_run=None,
) -> TrainingDatasetVersion:
    sync_feature_and_outcome_definitions()
    decision_query = DecisionPoint.objects.filter(
        school=school,
        subject=subject,
        status=DecisionPoint.Status.FROZEN,
        synthetic_run=synthetic_run,
    )
    if decision_start is not None:
        decision_query = decision_query.filter(scheduled_for__gte=decision_start)
    if decision_end is not None:
        decision_query = decision_query.filter(scheduled_for__lte=decision_end)
    decision_points = list(decision_query.order_by("scheduled_for", "id"))
    if not decision_points:
        raise ValidationError("当前范围没有已冻结的分析时间点。")

    point_ids = [item.id for item in decision_points]
    observations = _latest_final_observations(
        OutcomeObservation.objects.filter(
            decision_point_id__in=point_ids,
            outcome_definition=outcome_definition,
        ).select_related("decision_point", "student")
    )
    if not observations:
        raise ValidationError("当前范围还没有到期并冻结的未来结果。")
    snapshots = {
        (item.decision_point_id, item.student_id): item
        for item in StudentFeatureSnapshot.objects.filter(
            decision_point_id__in=point_ids,
            view_type=StudentFeatureSnapshot.ViewType.OPERATIONAL,
        ).select_related("decision_point", "student", "feature_set")
    }
    paired = [
        (snapshots[(item.decision_point_id, item.student_id)], item)
        for item in observations
        if (item.decision_point_id, item.student_id) in snapshots
    ]
    if not paired:
        raise ValidationError("冻结结果没有对应的当时可用特征快照。")

    feature_set = paired[0][0].feature_set
    if any(snapshot.feature_set_id != feature_set.id for snapshot, _item in paired):
        raise ValidationError("当前范围包含不同特征集版本，请分别生成数据版本。")
    source_rows = [
        {
            "decision_id": str(snapshot.decision_point.decision_id),
            "student_id": snapshot.student_id,
            "snapshot_hash": snapshot.source_hash,
            "outcome_hash": observation.source_hash,
        }
        for snapshot, observation in paired
    ]
    source_hash = canonical_hash(source_rows)
    dataset_key = canonical_hash(
        {
            "school_id": school.id,
            "synthetic_run_id": synthetic_run.id if synthetic_run else None,
            "subject_id": subject.id,
            "feature_set": feature_set.manifest_hash,
            "outcome": outcome_definition.definition_hash,
            "decision_start": decision_points[0].scheduled_for,
            "decision_end": decision_points[-1].scheduled_for,
            "source_hash": source_hash,
        }
    )[:48]
    existing = TrainingDatasetVersion.objects.filter(dataset_key=dataset_key).first()
    if existing:
        return existing

    dataset = TrainingDatasetVersion.objects.create(
        dataset_key=dataset_key,
        school=school,
        synthetic_run=synthetic_run,
        subject=subject,
        feature_set=feature_set,
        outcome_definition=outcome_definition,
        view_type=StudentFeatureSnapshot.ViewType.OPERATIONAL,
        status=TrainingDatasetVersion.Status.BUILDING,
        decision_start=decision_points[0].scheduled_for,
        decision_end=decision_points[-1].scheduled_for,
        split_strategy=SPLIT_STRATEGY,
        generator_version=DATASET_GENERATOR_VERSION,
        manifest={"status": "building"},
        source_hash=source_hash,
        created_by=created_by,
    )
    decision_dates = [
        snapshot.decision_point.scheduled_for.date() for snapshot, _item in paired
    ]
    time_splits = _time_splits(decision_dates)
    feature_definitions = list(
        FeatureDefinition.objects.filter(
            feature_key__in=[
                item["feature_key"] for item in feature_set.definition_manifest
            ],
            status=FeatureDefinition.Status.ACTIVE,
        )
    )
    model_keys = {
        definition.feature_key
        for definition in feature_definitions
        if definition.model_input_allowed
    }
    audit_keys = {
        definition.feature_key
        for definition in feature_definitions
        if not definition.model_input_allowed
    }
    split_counts = defaultdict(int)
    time_split_counts = defaultdict(int)
    blocked_snapshot_count = 0
    for snapshot, observation in paired:
        pseudonymous_key = hmac.new(
            settings.SECRET_KEY.encode(),
            f"{dataset_key}:{snapshot.student_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        group_split = _group_split(pseudonymous_key)
        time_split = time_splits[snapshot.decision_point.scheduled_for.date()]
        split_counts[group_split] += 1
        time_split_counts[time_split] += 1
        blocked_snapshot_count += (
            snapshot.quality_status == StudentFeatureSnapshot.QualityStatus.BLOCKED
        )
        row_payload = {
            "decision_id": str(snapshot.decision_point.decision_id),
            "pseudonymous_key": pseudonymous_key,
            "group_split": group_split,
            "time_split": time_split,
            "feature_values": snapshot.values,
            "feature_numerators": snapshot.numerators,
            "feature_denominators": snapshot.denominators,
            "feature_missing_codes": snapshot.missing_codes,
            "outcome_status": observation.status,
            "outcome_value": observation.value,
            "outcome_numerator": observation.numerator,
            "outcome_denominator": observation.denominator,
            "outcome_missing_code": observation.missing_code,
        }
        TrainingDatasetRow.objects.create(
            dataset=dataset,
            decision_point=snapshot.decision_point,
            snapshot=snapshot,
            outcome_observation=observation,
            pseudonymous_key=pseudonymous_key,
            split=group_split,
            split_group_key=f"student:{pseudonymous_key}",
            split_assignments={
                "group_holdout": group_split,
                "time_holdout": time_split,
            },
            feature_values=snapshot.values,
            feature_numerators=snapshot.numerators,
            feature_denominators=snapshot.denominators,
            feature_missing_codes=snapshot.missing_codes,
            outcome_status=observation.status,
            outcome_value=observation.value,
            outcome_numerator=observation.numerator,
            outcome_denominator=observation.denominator,
            outcome_missing_code=observation.missing_code,
            row_hash=canonical_hash(row_payload),
        )

    observed_count = sum(
        observation.status == OutcomeObservation.Status.OBSERVED
        for _snapshot, observation in paired
    )
    unobserved_count = sum(
        observation.status == OutcomeObservation.Status.UNOBSERVED
        for _snapshot, observation in paired
    )
    excluded_count = sum(
        observation.status == OutcomeObservation.Status.EXCLUDED
        for _snapshot, observation in paired
    )
    blockers = []
    if blocked_snapshot_count:
        blockers.append(f"{blocked_snapshot_count} 条特征快照的数据检查未通过。")
    if observed_count < 30:
        blockers.append("已观察结果少于 30 条，只能验证工程流程，暂不比较模型。")
    if len(set(decision_dates)) < 3:
        blockers.append("分析日期少于 3 个，暂不能形成完整时间外验证。")
    if not split_counts[TrainingDatasetRow.Split.TEST]:
        blockers.append("当前学生分组没有形成独立测试组。")
    manifest = {
        "dataset_key": dataset_key,
        "data_scope": "synthetic" if synthetic_run else "formal",
        "school_id": school.id,
        "subject_id": subject.id,
        "feature_set": {
            "key": feature_set.set_key,
            "version": feature_set.version,
            "manifest_hash": feature_set.manifest_hash,
        },
        "outcome_definition": {
            "key": outcome_definition.outcome_key,
            "version": outcome_definition.version,
            "definition_hash": outcome_definition.definition_hash,
        },
        "view_type": StudentFeatureSnapshot.ViewType.OPERATIONAL,
        "decision_range": [
            decision_points[0].scheduled_for.isoformat(),
            decision_points[-1].scheduled_for.isoformat(),
        ],
        "row_count": len(paired),
        "observed_count": observed_count,
        "unobserved_count": unobserved_count,
        "excluded_count": excluded_count,
        "blocked_snapshot_count": blocked_snapshot_count,
        "model_input_feature_keys": sorted(model_keys),
        "audit_only_feature_keys": sorted(audit_keys),
        "split_strategy": SPLIT_STRATEGY,
        "group_split_counts": dict(split_counts),
        "time_split_counts": dict(time_split_counts),
        "decision_date_count": len(set(decision_dates)),
        "comparison_ready": not blockers,
        "blockers": blockers,
        "source_hash": source_hash,
    }
    dataset.manifest = manifest
    dataset.row_count = len(paired)
    dataset.observed_count = observed_count
    dataset.unobserved_count = unobserved_count
    dataset.excluded_count = excluded_count
    dataset.status = TrainingDatasetVersion.Status.FROZEN
    dataset.frozen_at = timezone.now()
    dataset.save()
    return dataset
