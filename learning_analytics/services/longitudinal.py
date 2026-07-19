from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from learning_analytics.feature_models import (
    TrainingDatasetRow,
    TrainingDatasetVersion,
    canonical_hash,
)
from learning_analytics.model_models import LongitudinalAnalysisRun, LongitudinalFeatureResult


ANALYSIS_VERSION = "longitudinal-v1"
MIN_OBSERVATIONS = 30
MIN_STUDENTS = 10
MIN_CLASSES = 2


@dataclass(frozen=True, slots=True)
class LongitudinalRow:
    pseudonymous_key: str
    class_key: str
    feature_value: float
    outcome_value: float


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _variance(values: list[float]) -> float | None:
    if len(values) < 2:
        return 0.0 if values else None
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator_x = sum((x - mean_x) ** 2 for x in xs)
    denominator_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = math.sqrt(denominator_x * denominator_y)
    if denominator == 0:
        return None
    return numerator / denominator


def _bootstrap_interval(groups: dict[str, list[tuple[float, float]]], seed: str):
    if len(groups) < MIN_STUDENTS:
        return None, None
    rng = random.Random(seed)
    keys = list(groups)
    estimates = []
    for _ in range(200):
        selected = [keys[rng.randrange(len(keys))] for _ in keys]
        pairs = [pair for key in selected for pair in groups[key]]
        estimate = _correlation(
            [pair[0] for pair in pairs], [pair[1] for pair in pairs]
        )
        if estimate is not None:
            estimates.append(estimate)
    if len(estimates) < 40:
        return None, None
    estimates.sort()
    return estimates[int(len(estimates) * 0.025)], estimates[int(len(estimates) * 0.975)]


def _direction(value: float | None) -> str:
    if value is None:
        return "数据不足"
    if value >= 0.1:
        return "正向关联"
    if value <= -0.1:
        return "负向关联"
    return "无明显关联"


def _dataset_rows(dataset: TrainingDatasetVersion, feature_key: str):
    rows = []
    query = (
        TrainingDatasetRow.objects.filter(
            dataset=dataset,
            outcome_status="observed",
            outcome_value__isnull=False,
        )
        .select_related("decision_point")
        .order_by("decision_point__scheduled_for", "pseudonymous_key")
    )
    for item in query:
        feature_value = _finite_number(item.feature_values.get(feature_key))
        outcome_value = _finite_number(item.outcome_value)
        if feature_value is None or outcome_value is None:
            continue
        rows.append(
            LongitudinalRow(
                pseudonymous_key=item.pseudonymous_key,
                class_key=str(item.decision_point.class_group_id),
                feature_value=feature_value,
                outcome_value=outcome_value,
            )
        )
    return rows


def _result_for_feature(rows: list[LongitudinalRow], feature_key: str, run_key: str):
    by_student: dict[str, list[LongitudinalRow]] = defaultdict(list)
    by_class: dict[str, list[LongitudinalRow]] = defaultdict(list)
    for row in rows:
        by_student[row.pseudonymous_key].append(row)
        by_class[row.class_key].append(row)

    observation_values = [row.feature_value for row in rows]
    student_means = {
        key: sum(item.feature_value for item in values) / len(values)
        for key, values in by_student.items()
    }
    outcome_means = {
        key: sum(item.outcome_value for item in values) / len(values)
        for key, values in by_student.items()
    }
    total_variance = _variance(observation_values)
    between_variance = _variance(list(student_means.values()))
    within_components = []
    within_pairs = []
    for key, values in by_student.items():
        mean_feature = student_means[key]
        mean_outcome = outcome_means[key]
        within_components.extend([item.feature_value - mean_feature for item in values])
        within_pairs.extend(
            (
                item.feature_value - mean_feature,
                item.outcome_value - mean_outcome,
            )
            for item in values
        )
    within_variance = _variance(within_components)
    denominator = (between_variance or 0.0) + (within_variance or 0.0)
    intraclass = (between_variance / denominator) if denominator else None

    overall_pairs = [(row.feature_value, row.outcome_value) for row in rows]
    overall = _correlation(
        [pair[0] for pair in overall_pairs], [pair[1] for pair in overall_pairs]
    )
    within = _correlation(
        [pair[0] for pair in within_pairs], [pair[1] for pair in within_pairs]
    )
    between = _correlation(
        list(student_means.values()), list(outcome_means.values())
    )
    interval_low, interval_high = _bootstrap_interval(
        {
            key: [(item.feature_value, item.outcome_value) for item in values]
            for key, values in by_student.items()
        },
        f"{run_key}:{feature_key}",
    )
    class_means = {
        key: (
            sum(item.feature_value for item in values) / len(values),
            sum(item.outcome_value for item in values) / len(values),
        )
        for key, values in by_class.items()
    }
    class_association = _correlation(
        [item[0] for item in class_means.values()],
        [item[1] for item in class_means.values()],
    )
    status = LongitudinalFeatureResult.Status.READY
    note = "描述重复测量中的关联，不代表因果关系。"
    if len(rows) < MIN_OBSERVATIONS or len(by_student) < MIN_STUDENTS:
        status = LongitudinalFeatureResult.Status.INSUFFICIENT_N
        note = "有效观测或学生数量不足，只保留描述性结果。"
    elif len(by_class) < MIN_CLASSES:
        status = LongitudinalFeatureResult.Status.INSUFFICIENT_N
        note = "班级数量不足，不能报告稳定的班级聚类范围。"
    return {
        "feature_key": feature_key,
        "status": status,
        "observation_count": len(rows),
        "student_count": len(by_student),
        "class_count": len(by_class),
        "total_variance": total_variance,
        "between_variance": between_variance,
        "within_variance": within_variance,
        "intraclass_correlation": intraclass,
        "overall_association": overall,
        "within_association": within,
        "between_association": between,
        "interval_low": interval_low,
        "interval_high": interval_high,
        "direction": _direction(overall),
        "details": {
            "note": note,
            "class_association": class_association,
            "class_interval": {
                "low": None,
                "high": None,
                "method": "班级均值描述；班级不足时不计算区间。",
            },
            "student_observation_distribution": {
                "min": min((len(values) for values in by_student.values()), default=0),
                "max": max((len(values) for values in by_student.values()), default=0),
            },
        },
    }


@transaction.atomic
def build_longitudinal_analysis(
    *, dataset: TrainingDatasetVersion, created_by=None
) -> LongitudinalAnalysisRun:
    if dataset.status != TrainingDatasetVersion.Status.FROZEN:
        raise ValidationError("只能对已冻结的数据版本计算重复测量统计。")
    run_key = canonical_hash(
        {"dataset_key": dataset.dataset_key, "version": ANALYSIS_VERSION}
    )[:48]
    existing = LongitudinalAnalysisRun.objects.filter(run_key=run_key).first()
    if existing:
        return existing
    feature_keys = list(dataset.manifest.get("model_input_feature_keys", []))
    run = LongitudinalAnalysisRun.objects.create(
        run_key=run_key,
        dataset=dataset,
        school=dataset.school,
        subject=dataset.subject,
        analysis_version=ANALYSIS_VERSION,
        status=LongitudinalAnalysisRun.Status.BUILDING,
        created_by=created_by,
        manifest={"status": "building", "feature_keys": feature_keys},
    )
    all_rows = list(
        TrainingDatasetRow.objects.filter(
            dataset=dataset,
            outcome_status="observed",
            outcome_value__isnull=False,
        ).select_related("decision_point")
    )
    student_keys = {item.pseudonymous_key for item in all_rows}
    class_keys = {str(item.decision_point.class_group_id) for item in all_rows}
    ready_count = 0
    for feature_key in feature_keys:
        result = _result_for_feature(
            _dataset_rows(dataset, feature_key), feature_key, run_key
        )
        LongitudinalFeatureResult.objects.create(run=run, **result)
        ready_count += result["status"] == LongitudinalFeatureResult.Status.READY
    manifest = {
        "analysis_version": ANALYSIS_VERSION,
        "data_scope": "synthetic" if dataset.synthetic_run_id else "formal",
        "dataset_key": dataset.dataset_key,
        "feature_keys": feature_keys,
        "row_count": len(all_rows),
        "student_count": len(student_keys),
        "class_count": len(class_keys),
        "ready_feature_count": ready_count,
        "minimums": {
            "observations": MIN_OBSERVATIONS,
            "students": MIN_STUDENTS,
            "classes": MIN_CLASSES,
        },
        "interpretation": "结果仅描述个体内、个体间和班级层面的统计关联，不用于自动改变学生层级。",
    }
    run.row_count = len(all_rows)
    run.student_count = len(student_keys)
    run.class_count = len(class_keys)
    run.feature_count = len(feature_keys)
    run.ready_feature_count = ready_count
    run.manifest = manifest
    run.status = (
        LongitudinalAnalysisRun.Status.COMPLETED
        if feature_keys
        else LongitudinalAnalysisRun.Status.BLOCKED
    )
    run.save()
    return run
