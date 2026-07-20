from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from catboost import CatBoostClassifier, CatBoostRegressor
from django.core.exceptions import ValidationError
from django.db import transaction
from lightgbm import LGBMClassifier, LGBMRegressor

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
from learning_analytics.services.model_comparison import (
    MIN_EVALUATION_N,
    MODEL_KEYS,
    MODEL_LABELS,
    ComparisonRow,
    PredictionValue,
    _dataset_rows,
    _fold_status,
    _folds,
    _metrics,
    _negative_controls,
    _predict,
    _target_type,
)


MODEL_02_VERSION = "model-02-v3"
ADVANCED_MODEL_KEYS = ("CATBOOST", "LIGHTGBM")
ALL_MODEL_KEYS = (*MODEL_KEYS, *ADVANCED_MODEL_KEYS)
VALIDATION_KEYS = ("V-A", "V-B", "V-C", "V-D", "V-E")
RANDOM_SEED = 20260720
ADVANCED_LABELS = {
    "CATBOOST": "CatBoost 结构化模型",
    "LIGHTGBM": "LightGBM 结构化模型",
}


def feature_matrix(rows: list[ComparisonRow], feature_keys: list[str]) -> np.ndarray:
    values = []
    for row in rows:
        values.append(
            [
                float(row.features[key])
                if row.features.get(key) is not None
                and math.isfinite(float(row.features[key]))
                else np.nan
                for key in feature_keys
            ]
        )
    return np.asarray(values, dtype=float)


def fit_advanced_model(
    model_key: str,
    train: list[ComparisonRow],
    feature_keys: list[str],
    target_type: str,
):
    if model_key not in ADVANCED_MODEL_KEYS or not train or not feature_keys:
        return None
    x_train = feature_matrix(train, feature_keys)
    y_train = np.asarray([row.outcome for row in train], dtype=float)
    if target_type == "binary" and len(set(y_train.tolist())) < 2:
        return None
    if model_key == "CATBOOST":
        model_class = CatBoostClassifier if target_type == "binary" else CatBoostRegressor
        kwargs = {
            "iterations": 140,
            "depth": 5,
            "learning_rate": 0.045,
            "random_seed": RANDOM_SEED,
            "verbose": False,
            "allow_writing_files": False,
            "thread_count": 1,
        }
        if target_type == "binary":
            kwargs.update({"loss_function": "Logloss", "eval_metric": "Logloss"})
        else:
            kwargs.update({"loss_function": "RMSE", "eval_metric": "RMSE"})
        model = model_class(**kwargs)
    else:
        model_class = LGBMClassifier if target_type == "binary" else LGBMRegressor
        model = model_class(
            n_estimators=140,
            learning_rate=0.045,
            num_leaves=15,
            max_depth=5,
            min_child_samples=10,
            subsample=1.0,
            colsample_bytree=1.0,
            reg_alpha=0.02,
            reg_lambda=0.08,
            random_state=RANDOM_SEED,
            n_jobs=1,
            verbosity=-1,
        )
    model.fit(x_train, y_train)
    return model


def predict_advanced_model(
    model,
    model_key: str,
    rows: list[ComparisonRow],
    feature_keys: list[str],
    target_type: str,
) -> list[PredictionValue]:
    if model is None:
        return [
            PredictionValue(row, None, "abstained", "训练数据不足，未建立模型。")
            for row in rows
        ]
    usable = []
    usable_indexes = []
    results: list[PredictionValue | None] = [None] * len(rows)
    for index, row in enumerate(rows):
        if not any(row.features.get(key) is not None for key in feature_keys):
            results[index] = PredictionValue(
                row, None, "abstained", "没有可用的模型输入指标。"
            )
            continue
        usable.append(row)
        usable_indexes.append(index)
    if usable:
        matrix = feature_matrix(usable, feature_keys)
        if target_type == "binary":
            predicted = model.predict_proba(matrix)[:, 1]
        else:
            predicted = model.predict(matrix)
        for index, row, value in zip(usable_indexes, usable, predicted):
            value = float(value)
            results[index] = PredictionValue(
                row,
                max(0.0, min(1.0, value)) if target_type == "binary" else max(0.0, value),
                "predicted",
            )
    return [item for item in results if item is not None]


def _feature_importance(model, feature_keys: list[str]) -> list[dict]:
    values = getattr(model, "feature_importances_", None)
    if values is None and hasattr(model, "get_feature_importance"):
        values = model.get_feature_importance()
    if values is None:
        return []
    rows = [
        {"feature_key": key, "importance": round(float(value), 8)}
        for key, value in zip(feature_keys, values)
    ]
    return sorted(rows, key=lambda item: item["importance"], reverse=True)


def _stability(
    model_key: str,
    train: list[ComparisonRow],
    test: list[ComparisonRow],
    feature_keys: list[str],
    target_type: str,
    first_predictions: list[PredictionValue],
) -> dict:
    second_model = fit_advanced_model(model_key, train, feature_keys, target_type)
    second_predictions = predict_advanced_model(
        second_model, model_key, test, feature_keys, target_type
    )
    first = {
        item.row.row_id: item.value
        for item in first_predictions
        if item.status == "predicted" and item.value is not None
    }
    second = {
        item.row.row_id: item.value
        for item in second_predictions
        if item.status == "predicted" and item.value is not None
    }
    shared = sorted(set(first) & set(second))
    max_delta = max((abs(first[key] - second[key]) for key in shared), default=None)
    return {
        "status": "passed" if max_delta is not None and max_delta <= 1e-8 else "review",
        "shared_prediction_count": len(shared),
        "max_absolute_delta": max_delta,
        "rule": "相同数据、参数和随机种子重复训练，最大预测差应不超过 1e-8。",
    }


def _fairness_by_class(predictions: list[PredictionValue], target_type: str) -> dict:
    grouped: dict[str, list[PredictionValue]] = defaultdict(list)
    for prediction in predictions:
        if prediction.status == "predicted" and prediction.value is not None:
            grouped[prediction.row.class_key].append(prediction)
    group_rows = []
    reportable_mae = []
    for class_key, rows in sorted(grouped.items()):
        metrics = _metrics(rows, target_type)
        reportable = len(rows) >= 10
        if reportable and metrics.get("mae") is not None:
            reportable_mae.append(metrics["mae"])
        group_rows.append(
            {
                "class_key": class_key,
                "n": len(rows),
                "coverage": metrics.get("coverage"),
                "mae": metrics.get("mae") if reportable else None,
                "status": "ready" if reportable else "insufficient_n",
            }
        )
    gap = max(reportable_mae) - min(reportable_mae) if len(reportable_mae) >= 2 else None
    return {
        "status": (
            "passed"
            if gap is not None and gap <= 0.15
            else "review"
            if gap is not None
            else "insufficient_n"
        ),
        "mae_gap": gap,
        "groups": group_rows,
        "interpretation": "这里只检查班级间误差和覆盖差异，不能替代性别、家庭背景等公平性研究。",
    }


def _peer_datasets(dataset: TrainingDatasetVersion, *, include_test_data: bool):
    query = TrainingDatasetVersion.objects.filter(
        status=TrainingDatasetVersion.Status.FROZEN,
        feature_set=dataset.feature_set,
        outcome_definition=dataset.outcome_definition,
    ).exclude(school=dataset.school)
    if not include_test_data:
        query = query.filter(synthetic_run__isnull=True, school__is_synthetic=False)
    subject_key = dataset.manifest.get("subject_comparison_key")
    latest_by_school = {}
    for item in query.order_by("school_id", "-frozen_at", "-id"):
        if item.manifest.get("subject_comparison_key") != subject_key:
            continue
        latest_by_school.setdefault(item.school_id, item)
    return list(latest_by_school.values())


def _external_rows(datasets: list[TrainingDatasetVersion]) -> list[ComparisonRow]:
    rows = []
    for dataset in datasets:
        rows.extend(_dataset_rows(dataset))
    return rows


def select_best_advanced_model(run: ModelComparisonRun) -> str | None:
    scores: dict[str, list[float]] = defaultdict(list)
    for evaluation in run.evaluations.filter(
        model_key__in=ADVANCED_MODEL_KEYS,
        status=ModelEvaluationResult.Status.READY,
        primary_metric__isnull=False,
    ):
        scores[evaluation.model_key].append(float(evaluation.primary_metric))
    if not scores:
        return None
    return min(scores, key=lambda key: sum(scores[key]) / len(scores[key]))


@transaction.atomic
def build_model_02_comparison(
    *,
    dataset: TrainingDatasetVersion,
    created_by=None,
    include_test_data: bool = False,
) -> ModelComparisonRun:
    if dataset.status != TrainingDatasetVersion.Status.FROZEN:
        raise ValidationError("只能对已冻结的数据版本运行结构化模型比较。")
    run_key = canonical_hash(
        {"dataset_key": dataset.dataset_key, "version": MODEL_02_VERSION}
    )[:48]
    existing = ModelComparisonRun.objects.filter(run_key=run_key).first()
    if existing:
        return existing

    rows = _dataset_rows(dataset)
    feature_keys = list(dataset.manifest.get("model_input_feature_keys", []))
    target_type = _target_type(rows)
    peers = _peer_datasets(dataset, include_test_data=include_test_data)
    folds = _folds(rows)
    external_rows = _external_rows(peers)
    folds["V-D"] = (
        rows,
        external_rows,
        "使用其他学校的独立冻结数据检查跨校迁移。"
        if external_rows
        else "没有可用的独立学校数据版本。",
    )
    run = ModelComparisonRun.objects.create(
        run_key=run_key,
        dataset=dataset,
        school=dataset.school,
        subject=dataset.subject,
        comparison_version=MODEL_02_VERSION,
        status=ModelComparisonRun.Status.BUILDING,
        target_type=target_type,
        model_keys=list(ALL_MODEL_KEYS),
        validation_keys=list(VALIDATION_KEYS),
        created_by=created_by,
        manifest={"status": "building"},
        model_card={},
    )
    evaluations = {}
    dependency_versions = {}
    import catboost
    import lightgbm
    import sklearn

    dependency_versions["catboost"] = catboost.__version__
    dependency_versions["lightgbm"] = lightgbm.__version__
    dependency_versions["numpy"] = np.__version__
    dependency_versions["scikit_learn"] = sklearn.__version__
    current_row_ids = set(
        TrainingDatasetRow.objects.filter(dataset=dataset).values_list(
            "id", flat=True
        )
    )

    for validation_key in VALIDATION_KEYS:
        train, test, note = folds[validation_key]
        for model_key in ALL_MODEL_KEYS:
            status = _fold_status(train, test)
            model = None
            if status == ModelEvaluationResult.Status.READY:
                if model_key in ADVANCED_MODEL_KEYS:
                    model = fit_advanced_model(
                        model_key, train, feature_keys, target_type
                    )
                    predictions = predict_advanced_model(
                        model, model_key, test, feature_keys, target_type
                    )
                else:
                    predictions = _predict(
                        model_key, train, test, feature_keys, target_type
                    )
            else:
                predictions = []
            metric_values = _metrics(predictions, target_type)
            reportable = status == ModelEvaluationResult.Status.READY
            advanced_details = {}
            if reportable and model_key in ADVANCED_MODEL_KEYS and model is not None:
                advanced_details = {
                    "feature_importance": _feature_importance(model, feature_keys),
                    "stability": _stability(
                        model_key,
                        train,
                        test,
                        feature_keys,
                        target_type,
                        predictions,
                    ),
                    "fairness": _fairness_by_class(predictions, target_type),
                }
            result = ModelEvaluationResult.objects.create(
                run=run,
                model_key=model_key,
                validation_key=validation_key,
                status=status,
                train_count=len(train),
                test_count=len(test),
                predicted_count=metric_values.get("predicted_count", 0),
                abstained_count=metric_values.get("abstained_count", len(test)),
                primary_metric=metric_values.get("primary_metric") if reportable else None,
                rmse=metric_values.get("rmse") if reportable else None,
                mae=metric_values.get("mae") if reportable else None,
                brier_score=metric_values.get("brier_score") if reportable else None,
                calibration_intercept=(
                    metric_values.get("calibration_intercept") if reportable else None
                ),
                calibration_slope=(
                    metric_values.get("calibration_slope") if reportable else None
                ),
                coverage=metric_values.get("coverage"),
                metrics={
                    **(
                        metric_values
                        if reportable
                        else {
                            "predicted_count": 0,
                            "abstained_count": len(test),
                            "coverage": 0.0,
                        }
                    ),
                    **advanced_details,
                    "model_label": (
                        MODEL_LABELS.get(model_key)
                        or ADVANCED_LABELS.get(model_key, model_key)
                    ),
                    "target_type": target_type,
                    "reportable": reportable,
                },
                note=(
                    "仅用于同范围影子比较，不产生自动分层。"
                    if reportable
                    else note
                ),
            )
            evaluations[(model_key, validation_key)] = result
            if validation_key == "V-D":
                continue
            for prediction in predictions:
                if prediction.row.row_id not in current_row_ids:
                    continue
                ModelPrediction.objects.create(
                    run=run,
                    evaluation=result,
                    dataset_row_id=prediction.row.row_id,
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

    controls = _negative_controls(
        run, rows, feature_keys, target_type, folds, evaluations
    )
    for control in controls:
        NegativeControlResult.objects.create(run=run, **control)
    blockers = []
    ready_advanced = [
        item
        for (model_key, _validation), item in evaluations.items()
        if model_key in ADVANCED_MODEL_KEYS
        and item.status == ModelEvaluationResult.Status.READY
        and item.primary_metric is not None
        and item.predicted_count >= MIN_EVALUATION_N
    ]
    if not ready_advanced:
        blockers.append("CatBoost 和 LightGBM 没有达到可报告的测试样本量。")
    failed_controls = [
        item["control_key"]
        for item in controls
        if item["status"] == NegativeControlResult.Status.FAILED
    ]
    if failed_controls:
        blockers.append(f"防误判检查需要解释：{', '.join(failed_controls)}。")
    best_model = select_best_advanced_model(run)
    manifest = {
        "comparison_version": MODEL_02_VERSION,
        "dataset_key": dataset.dataset_key,
        "data_scope": "synthetic" if dataset.synthetic_run_id else "formal",
        "model_keys": list(ALL_MODEL_KEYS),
        "validation_keys": list(VALIDATION_KEYS),
        "feature_keys": feature_keys,
        "peer_dataset_ids": [item.id for item in peers],
        "dependency_versions": dependency_versions,
        "best_advanced_model": best_model,
        "blockers": blockers,
    }
    run.model_card = {
        "title": "MODEL-02 结构化模型比较",
        "status": "shadow_only" if not blockers else "blocked",
        "intended_use": "比较透明基线、CatBoost 和 LightGBM，并检查校准、稳定性和班级间误差差异。",
        "prohibited_use": "不得直接改变学生层级，不得向学生显示预测或用模拟数据宣称真实效果。",
        "best_advanced_model": best_model,
        "dependencies": dependency_versions,
        "minimum_test_n": MIN_EVALUATION_N,
        "limitations": [
            "班级间误差检查不等同于完整公平性研究。",
            "跨校检查只在存在独立学校冻结数据时报告。",
            "模拟数据只能证明程序和计算流程可运行。",
        ],
    }
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
