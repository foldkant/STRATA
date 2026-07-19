from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass, replace
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction

from learning_analytics.feature_models import (
    TrainingDatasetRow,
    TrainingDatasetVersion,
    canonical_hash,
)
from learning_analytics.model_models import (
    ModelComparisonRun,
    ModelEvaluationResult,
    ModelPrediction,
    NegativeControlResult,
)


COMPARISON_VERSION = "model-01-v2"
MODEL_KEYS = ("M00", "M01", "M02", "M03")
VALIDATION_KEYS = ("V-A", "V-B", "V-C", "V-D", "V-E")
MIN_EVALUATION_N = 30
MODEL_LABELS = {
    "M00": "总体平均基线",
    "M01": "透明规则基线",
    "M02": "正则化统计基线",
    "M03": "班级收缩基线",
}


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    row_id: int
    pseudonymous_key: str
    class_key: str
    decision_date: date
    features: dict
    outcome: float


@dataclass(frozen=True, slots=True)
class PredictionValue:
    row: ComparisonRow
    value: float | None
    status: str
    reason: str = ""


def _number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _covariance(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (len(xs) - 1)


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def _dataset_rows(dataset: TrainingDatasetVersion) -> list[ComparisonRow]:
    rows = []
    query = (
        TrainingDatasetRow.objects.filter(
            dataset=dataset,
            outcome_status="observed",
            outcome_value__isnull=False,
        )
        .select_related("decision_point")
        .order_by("decision_point__scheduled_for", "pseudonymous_key", "id")
    )
    for item in query:
        outcome = _number(item.outcome_value)
        if outcome is None:
            continue
        rows.append(
            ComparisonRow(
                row_id=item.id,
                pseudonymous_key=item.pseudonymous_key,
                class_key=str(item.decision_point.class_group_id),
                decision_date=item.decision_point.scheduled_for.date(),
                features=dict(item.feature_values),
                outcome=outcome,
            )
        )
    return rows


def _target_type(rows: list[ComparisonRow]) -> str:
    if rows and all(abs(row.outcome - round(row.outcome)) < 1e-9 for row in rows):
        values = {int(round(row.outcome)) for row in rows}
        if values <= {0, 1}:
            return "binary"
    return "continuous"


def _folds(rows: list[ComparisonRow]) -> dict[str, tuple[list[ComparisonRow], list[ComparisonRow], str]]:
    result = {}
    dates = sorted({row.decision_date for row in rows})
    if len(dates) >= 3:
        split = max(1, min(len(dates) - 1, int(len(dates) * 0.7)))
        train_dates = set(dates[:split])
        result["V-A"] = (
            [row for row in rows if row.decision_date in train_dates],
            [row for row in rows if row.decision_date not in train_dates],
            "按时间先后分开训练期和测试期。",
        )
    else:
        result["V-A"] = ([], [], "分析日期少于 3 个，不能形成时间外推。")

    train = [row for row in rows if int(row.pseudonymous_key[:8], 16) % 5 != 0]
    test = [row for row in rows if int(row.pseudonymous_key[:8], 16) % 5 == 0]
    result["V-B"] = (train, test, "按学生匿名编号整组留出，避免同一学生同时出现在训练和测试中。")

    class_keys = sorted({row.class_key for row in rows})
    if len(class_keys) >= 2:
        test_classes = {
            class_key
            for class_key in class_keys
            if int(hashlib.sha256(class_key.encode()).hexdigest()[:8], 16) % 5 == 0
        }
        if not test_classes or len(test_classes) == len(class_keys):
            test_classes = {class_keys[-1]}
        result["V-C"] = (
            [row for row in rows if row.class_key not in test_classes],
            [row for row in rows if row.class_key in test_classes],
            "按班级整组留出，检查教学情境变化。",
        )
    else:
        result["V-C"] = ([], [], "当前数据只有一个班级，不能形成新班级验证。")

    result["V-D"] = ([], [], "单校冻结数据版本不能模拟留出另一所学校；需要独立学校数据版本。")
    result["V-E"] = ([], [], "当前数据版本只有一套测量定义，暂不能验证课程或测量版本变化。")
    return result


def _feature_stats(rows: list[ComparisonRow], feature_keys: list[str]):
    means = {}
    scales = {}
    for key in feature_keys:
        values = [_number(row.features.get(key)) for row in rows]
        values = [value for value in values if value is not None]
        means[key] = _mean(values) or 0.0
        scales[key] = math.sqrt(_variance(values)) or 1.0
    return means, scales


def _vector(row: ComparisonRow, feature_keys: list[str], means: dict, scales: dict):
    values = []
    available = 0
    for key in feature_keys:
        value = _number(row.features.get(key))
        if value is not None:
            available += 1
            values.append((value - means[key]) / scales[key])
        else:
            values.append(0.0)
    return values, available


def _fit_ridge(
    train: list[ComparisonRow],
    feature_keys: list[str],
    target_type: str,
    *,
    custom_outcomes: list[float] | None = None,
):
    if not feature_keys or not train:
        return None
    means, scales = _feature_stats(train, feature_keys)
    outcomes = custom_outcomes or [row.outcome for row in train]
    bias = _mean(outcomes) or 0.0
    weights = [0.0] * len(feature_keys)
    learning_rate = 0.08 if target_type == "continuous" else 0.12
    l2 = 0.04
    l1 = 0.002
    for _ in range(500):
        gradient_bias = 0.0
        gradients = [0.0] * len(feature_keys)
        for index, row in enumerate(train):
            vector, _available = _vector(row, feature_keys, means, scales)
            linear = bias + sum(weight * value for weight, value in zip(weights, vector))
            prediction = linear if target_type == "continuous" else _sigmoid(linear)
            error = prediction - outcomes[index]
            gradient_bias += error
            for position, value in enumerate(vector):
                gradients[position] += error * value
        count = max(1, len(train))
        bias -= learning_rate * gradient_bias / count
        for position, gradient in enumerate(gradients):
            weight = weights[position] - learning_rate * (
                gradient / count + l2 * weights[position]
            )
            weights[position] = math.copysign(
                max(abs(weight) - learning_rate * l1, 0), weight
            )
    return {
        "means": means,
        "scales": scales,
        "weights": weights,
        "bias": bias,
        "target_type": target_type,
        "feature_keys": feature_keys,
    }


def _predict_ridge(model, row: ComparisonRow) -> PredictionValue:
    vector, available = _vector(
        row, model["feature_keys"], model["means"], model["scales"]
    )
    if available == 0:
        return PredictionValue(row, None, "abstained", "没有可用的模型输入指标。")
    linear = model["bias"] + sum(
        weight * value for weight, value in zip(model["weights"], vector)
    )
    value = linear if model["target_type"] == "continuous" else _sigmoid(linear)
    if model["target_type"] == "binary":
        value = _clamp(value, 0.0, 1.0)
    else:
        value = max(0.0, value)
    return PredictionValue(row, value, "predicted")


def _rule_features(feature_keys: list[str]) -> list[str]:
    preferred = (
        "opp_completion_rate",
        "first_attempt_correct_rate",
        "active_days",
        "engagement_days",
        "resource_exposure",
        "attendance_present_rate",
        "task_submission_rate",
        "assessment_score",
    )
    selected = [
        key for prefix in preferred for key in feature_keys if key.startswith(prefix)
    ]
    return list(dict.fromkeys(selected or feature_keys[:8]))[:8]


def _fit_rule(train: list[ComparisonRow], feature_keys: list[str], target_type: str):
    selected = _rule_features(feature_keys)
    if not selected:
        return None
    scores = []
    outcomes = []
    for row in train:
        values = [_number(row.features.get(key)) for key in selected]
        values = [value for value in values if value is not None]
        if not values:
            continue
        scores.append(sum(_clamp(value, 0.0, 1.0) for value in values) / len(values))
        outcomes.append(row.outcome)
    if len(scores) < 3:
        return None
    mean_score = _mean(scores) or 0.0
    mean_outcome = _mean(outcomes) or 0.0
    slope = _covariance(scores, outcomes) / (_variance(scores) or 1.0)
    return {
        "selected": selected,
        "mean_score": mean_score,
        "mean_outcome": mean_outcome,
        "slope": slope,
        "target_type": target_type,
    }


def _predict_rule(model, row: ComparisonRow) -> PredictionValue:
    values = [_number(row.features.get(key)) for key in model["selected"]]
    values = [value for value in values if value is not None]
    if len(values) < 2:
        return PredictionValue(row, None, "abstained", "透明规则可用指标少于 2 项。")
    score = sum(_clamp(value, 0.0, 1.0) for value in values) / len(values)
    value = model["mean_outcome"] + model["slope"] * (score - model["mean_score"])
    if model["target_type"] == "binary":
        value = _clamp(value, 0.0, 1.0)
    else:
        value = max(0.0, value)
    return PredictionValue(row, value, "predicted")


def _fit_class_shrink(train: list[ComparisonRow]):
    global_mean = _mean([row.outcome for row in train])
    if global_mean is None:
        return None
    grouped = {}
    for row in train:
        grouped.setdefault(row.class_key, []).append(row.outcome)
    return {
        "global_mean": global_mean,
        "class_means": {key: _mean(values) for key, values in grouped.items()},
        "class_counts": {key: len(values) for key, values in grouped.items()},
        "prior_strength": 10.0,
    }


def _predict_class_shrink(model, row: ComparisonRow) -> PredictionValue:
    class_mean = model["class_means"].get(row.class_key)
    if class_mean is None:
        return PredictionValue(row, model["global_mean"], "predicted")
    count = model["class_counts"][row.class_key]
    weight = count / (count + model["prior_strength"])
    value = model["global_mean"] + weight * (class_mean - model["global_mean"])
    return PredictionValue(row, max(0.0, value), "predicted")


def _predict(model_key: str, train: list[ComparisonRow], test: list[ComparisonRow], feature_keys, target_type):
    if not train or not test:
        return []
    if model_key == "M00":
        mean = _mean([row.outcome for row in train]) or 0.0
        return [
            PredictionValue(
                row,
                _clamp(mean, 0.0, 1.0) if target_type == "binary" else max(0.0, mean),
                "predicted",
            )
            for row in test
        ]
    if model_key == "M01":
        model = _fit_rule(train, feature_keys, target_type)
        return [
            _predict_rule(model, row) if model else PredictionValue(row, None, "abstained", "没有足够指标建立透明规则。")
            for row in test
        ]
    if model_key == "M02":
        model = _fit_ridge(train, feature_keys, target_type)
        return [
            _predict_ridge(model, row) if model else PredictionValue(row, None, "abstained", "没有可用模型输入指标。")
            for row in test
        ]
    model = _fit_class_shrink(train)
    return [
        _predict_class_shrink(model, row) if model else PredictionValue(row, None, "abstained", "训练结果不足。")
        for row in test
    ]


def _metrics(predictions: list[PredictionValue], target_type: str):
    valid = [item for item in predictions if item.status == "predicted" and item.value is not None]
    if not valid:
        return {"predicted_count": 0, "abstained_count": len(predictions), "coverage": 0.0}
    actual = [item.row.outcome for item in valid]
    predicted = [item.value for item in valid]
    errors = [prediction - truth for prediction, truth in zip(predicted, actual)]
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mae = sum(abs(error) for error in errors) / len(errors)
    mean_prediction = _mean(predicted)
    mean_actual = _mean(actual)
    calibration_slope = _covariance(predicted, actual) / (_variance(predicted) or 1.0)
    calibration_intercept = (mean_actual or 0.0) - calibration_slope * (mean_prediction or 0.0)
    brier = (
        sum((prediction - truth) ** 2 for prediction, truth in zip(predicted, actual))
        / len(predicted)
        if target_type == "binary"
        else None
    )
    primary = brier if brier is not None else rmse
    return {
        "predicted_count": len(valid),
        "abstained_count": len(predictions) - len(valid),
        "coverage": len(valid) / len(predictions) if predictions else 0.0,
        "rmse": rmse,
        "mae": mae,
        "brier_score": brier,
        "primary_metric": primary,
        "mean_prediction": mean_prediction,
        "mean_actual": mean_actual,
        "calibration_intercept": calibration_intercept,
        "calibration_slope": calibration_slope,
    }


def _fold_status(train: list[ComparisonRow], test: list[ComparisonRow]):
    if not train or not test:
        return ModelEvaluationResult.Status.NOT_APPLICABLE
    if len(test) < MIN_EVALUATION_N:
        return ModelEvaluationResult.Status.INSUFFICIENT_N
    return ModelEvaluationResult.Status.READY


def _negative_controls(run: ModelComparisonRun, rows, feature_keys, target_type, folds, evaluations):
    controls = []
    selected_fold = next(
        (
            key
            for key in ("V-A", "V-B", "V-C")
            if evaluations.get(("M00", key))
            and evaluations[("M00", key)].primary_metric is not None
            and folds[key][0]
            and folds[key][1]
        ),
        None,
    )
    reference = evaluations.get(("M00", selected_fold)) if selected_fold else None
    baseline_metric = reference.primary_metric if reference else None
    if baseline_metric is None:
        controls.append(
            {
                "control_key": "label_permutation",
                "status": NegativeControlResult.Status.INSUFFICIENT_N,
                "expected_behavior": "标签打乱后不应稳定优于总体平均基线。",
                "details": {"reason": "没有可用的独立测试折。"},
            }
        )
        controls.append(
            {
                "control_key": "random_identifier",
                "status": NegativeControlResult.Status.INSUFFICIENT_N,
                "expected_behavior": "随机匿名编号不应稳定优于总体平均基线。",
                "details": {"reason": "没有可用的独立测试折。"},
            }
        )
    else:
        train, test, _note = folds[selected_fold]
        shuffled_outcomes = [item.outcome for item in train]
        permutation_seed = int(
            hashlib.sha256(
                f"{run.run_key}:label_permutation".encode()
            ).hexdigest()[:16],
            16,
        )
        random.Random(permutation_seed).shuffle(shuffled_outcomes)
        model = _fit_ridge(
            train,
            feature_keys,
            target_type,
            custom_outcomes=shuffled_outcomes,
        )
        predictions = [_predict_ridge(model, item) for item in test] if model else []
        observed = _metrics(predictions, target_type).get("primary_metric")
        status = (
            NegativeControlResult.Status.PASSED
            if observed is None or observed >= baseline_metric - 0.02
            else NegativeControlResult.Status.FAILED
        )
        controls.append(
            {
                "control_key": "label_permutation",
                "status": status,
                "expected_behavior": "标签打乱后不应稳定优于总体平均基线。",
                "observed_metric": observed,
                "baseline_metric": baseline_metric,
                "details": {"fold": selected_fold},
            }
        )
        random_train = [
            replace(
                item,
                features={
                    **item.features,
                    "__random_id__": int(
                        hashlib.sha256(
                            f"{item.pseudonymous_key}:{item.decision_date}".encode()
                        ).hexdigest()[:12],
                        16,
                    )
                    / float(16**12),
                },
            )
            for item in train
        ]
        random_test = [
            replace(
                item,
                features={
                    **item.features,
                    "__random_id__": int(
                        hashlib.sha256(
                            f"{item.pseudonymous_key}:{item.decision_date}".encode()
                        ).hexdigest()[:12],
                        16,
                    )
                    / float(16**12),
                },
            )
            for item in test
        ]
        random_model = _fit_ridge(
            random_train,
            ["__random_id__"],
            target_type,
        )
        random_predictions = (
            [_predict_ridge(random_model, item) for item in random_test]
            if random_model
            else []
        )
        random_metric = _metrics(random_predictions, target_type).get(
            "primary_metric"
        )
        controls.append(
            {
                "control_key": "random_identifier",
                "status": (
                    NegativeControlResult.Status.PASSED
                    if random_metric is None
                    or random_metric >= baseline_metric - 0.02
                    else NegativeControlResult.Status.FAILED
                ),
                "expected_behavior": "随机匿名编号不应稳定优于总体平均基线。",
                "observed_metric": random_metric,
                "baseline_metric": baseline_metric,
                "details": {"fold": selected_fold},
            }
        )
    future_keys = [key for key in feature_keys if re.search(r"future|next_|after_", key, re.I)]
    controls.append(
        {
            "control_key": "future_sentinel",
            "status": NegativeControlResult.Status.PASSED if not future_keys else NegativeControlResult.Status.FAILED,
            "expected_behavior": "输入指标不能包含分析时间点之后的字段。",
            "details": {"suspicious_feature_keys": future_keys},
        }
    )
    audit_keys = set(run.dataset.manifest.get("audit_only_feature_keys", []))
    leaked_audit = sorted(audit_keys.intersection(feature_keys))
    controls.append(
        {
            "control_key": "data_availability",
            "status": NegativeControlResult.Status.PASSED if not leaked_audit else NegativeControlResult.Status.FAILED,
            "expected_behavior": "离线、数据错误等技术条件不能进入首期主模型输入。",
            "details": {"leaked_audit_feature_keys": leaked_audit},
        }
    )
    class_keys = {row.class_key for row in rows}
    class_evaluation = (
        evaluations.get(("M03", selected_fold)) if selected_fold else None
    )
    class_metric = class_evaluation.primary_metric if class_evaluation else None
    controls.append(
        {
            "control_key": "class_only",
            "status": (
                NegativeControlResult.Status.NOT_APPLICABLE
                if len(class_keys) < 2 or baseline_metric is None
                else NegativeControlResult.Status.PASSED
                if class_metric is None or class_metric >= baseline_metric - 0.02
                else NegativeControlResult.Status.FAILED
            ),
            "expected_behavior": "不能把学校或班级身份当成学生能力的替代变量。",
            "observed_metric": class_metric,
            "baseline_metric": baseline_metric,
            "details": {
                "class_count": len(class_keys),
                "fold": selected_fold,
                "note": "首期保存班级基线作为核查，不作个人能力解释。",
            },
        }
    )
    return controls


@transaction.atomic
def build_model_comparison(
    *, dataset: TrainingDatasetVersion, created_by=None
) -> ModelComparisonRun:
    if dataset.status != TrainingDatasetVersion.Status.FROZEN:
        raise ValidationError("只能对已冻结的数据版本运行模型比较。")
    run_key = canonical_hash(
        {"dataset_key": dataset.dataset_key, "version": COMPARISON_VERSION}
    )[:48]
    existing = ModelComparisonRun.objects.filter(run_key=run_key).first()
    if existing:
        return existing
    rows = _dataset_rows(dataset)
    feature_keys = list(dataset.manifest.get("model_input_feature_keys", []))
    target_type = _target_type(rows)
    run = ModelComparisonRun.objects.create(
        run_key=run_key,
        dataset=dataset,
        school=dataset.school,
        subject=dataset.subject,
        comparison_version=COMPARISON_VERSION,
        status=ModelComparisonRun.Status.BUILDING,
        target_type=target_type,
        model_keys=list(MODEL_KEYS),
        validation_keys=list(VALIDATION_KEYS),
        created_by=created_by,
        manifest={"status": "building"},
        model_card={},
    )
    folds = _folds(rows)
    evaluations = {}
    for validation_key in VALIDATION_KEYS:
        train, test, note = folds[validation_key]
        for model_key in MODEL_KEYS:
            status = _fold_status(train, test)
            predictions = _predict(model_key, train, test, feature_keys, target_type)
            metric_values = _metrics(predictions, target_type)
            reportable_metrics = (
                metric_values
                if status == ModelEvaluationResult.Status.READY
                else {
                    "predicted_count": metric_values.get("predicted_count", 0),
                    "abstained_count": metric_values.get(
                        "abstained_count", len(test)
                    ),
                    "coverage": metric_values.get("coverage", 0.0),
                }
            )
            result = ModelEvaluationResult.objects.create(
                run=run,
                model_key=model_key,
                validation_key=validation_key,
                status=status,
                train_count=len(train),
                test_count=len(test),
                predicted_count=metric_values.get("predicted_count", 0),
                abstained_count=metric_values.get("abstained_count", len(test)),
                primary_metric=reportable_metrics.get("primary_metric"),
                rmse=reportable_metrics.get("rmse"),
                mae=reportable_metrics.get("mae"),
                brier_score=reportable_metrics.get("brier_score"),
                calibration_intercept=reportable_metrics.get(
                    "calibration_intercept"
                ),
                calibration_slope=reportable_metrics.get("calibration_slope"),
                coverage=metric_values.get("coverage"),
                metrics={
                    **reportable_metrics,
                    "model_label": MODEL_LABELS[model_key],
                    "target_type": target_type,
                    "reportable": status == ModelEvaluationResult.Status.READY,
                },
                note=(
                    note
                    if status != ModelEvaluationResult.Status.READY
                    else "仅用于冻结数据版本内的影子比较，不产生教学建议。"
                ),
            )
            evaluations[(model_key, validation_key)] = result
            for prediction in predictions:
                ModelPrediction.objects.create(
                    run=run,
                    evaluation=result,
                    dataset_row=TrainingDatasetRow.objects.get(pk=prediction.row.row_id),
                    pseudonymous_key=prediction.row.pseudonymous_key,
                    model_key=model_key,
                    validation_key=validation_key,
                    status=(
                        ModelPrediction.Status.PREDICTED
                        if prediction.status == "predicted"
                        else ModelPrediction.Status.ABSTAINED
                    ),
                    predicted_value=prediction.value,
                    observed_value=prediction.row.outcome,
                    abstain_reason=prediction.reason,
                )

    negative_controls = _negative_controls(
        run, rows, feature_keys, target_type, folds, evaluations
    )
    for control in negative_controls:
        NegativeControlResult.objects.create(run=run, **control)
    blockers = []
    if len(rows) < MIN_EVALUATION_N:
        blockers.append(f"已观察结果只有 {len(rows)} 条，少于 {MIN_EVALUATION_N} 条。")
    if not any(
        item.status == ModelEvaluationResult.Status.READY
        for item in evaluations.values()
    ):
        blockers.append("没有一个验证折达到最小测试样本量。")
    failed_controls = [
        item["control_key"]
        for item in negative_controls
        if item["status"] == NegativeControlResult.Status.FAILED
    ]
    if failed_controls:
        blockers.append(f"负对照需要解释：{', '.join(failed_controls)}。")
    model_card = {
        "title": "M00-M03 透明基线模型卡",
        "status": "shadow_only" if not blockers else "blocked",
        "intended_use": "学校管理员和研究人员检查数据准备、验证切分和模型比较流程。",
        "prohibited_use": "不得直接改变学生层级、公开个人预测、替代教师判断或宣称教学效果。",
        "data_scope": "synthetic" if dataset.synthetic_run_id else "formal",
        "dataset_key": dataset.dataset_key,
        "target": {
            "label": dataset.outcome_definition.label,
            "type": target_type,
            "version": dataset.outcome_definition.version,
        },
        "models": [
            {"key": key, "label": MODEL_LABELS[key], "method": _model_method(key)}
            for key in MODEL_KEYS
        ],
        "validation": {
            "folds": list(VALIDATION_KEYS),
            "minimum_test_n": MIN_EVALUATION_N,
            "student_grouping": "学生匿名编号整组留出",
            "time_grouping": "按分析日期从早到晚留出",
        },
        "missing_and_abstention": "M01/M02 没有足够输入指标时拒绝预测；样本不足只显示数据不足。",
        "negative_controls": [item["control_key"] for item in negative_controls],
        "limitations": [
            "当前结果是统计比较，不是正式上线模型。",
            "单校数据不能证明跨校迁移。",
            "模拟数据不能证明真实学生上的有效性。",
            "关联方向不等于行为改变会导致结果改变。",
        ],
    }
    manifest = {
        "comparison_version": COMPARISON_VERSION,
        "dataset_key": dataset.dataset_key,
        "data_scope": "synthetic" if dataset.synthetic_run_id else "formal",
        "model_input_feature_keys": feature_keys,
        "model_keys": list(MODEL_KEYS),
        "validation_keys": list(VALIDATION_KEYS),
        "row_count": len(rows),
        "observed_count": len(rows),
        "blockers": blockers,
        "negative_control_status": {
            item["control_key"]: item["status"] for item in negative_controls
        },
    }
    run.model_card = model_card
    run.manifest = manifest
    run.row_count = len(rows)
    run.observed_count = len(rows)
    run.status = (
        ModelComparisonRun.Status.BLOCKED
        if blockers
        else ModelComparisonRun.Status.SHADOW_ONLY
    )
    run.save()
    return run


def _model_method(model_key: str) -> str:
    return {
        "M00": "训练集总体平均值，不读取行为特征。",
        "M01": "最多 8 项透明过程指标的规则分数，保留指标方向。",
        "M02": "纯 Python 可重复的正则化线性/逻辑基线；正式 Elastic Net 依赖接入前只作工程比较。",
        "M03": "按班级均值与总体均值做收缩的统计基线，未把班级身份解释为学生能力。",
    }[model_key]
