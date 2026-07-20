from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from learning.models import StratificationDecision
from learning_analytics.feature_models import (
    TrainingDatasetRow,
    TrainingDatasetVersion,
    canonical_hash,
)
from learning_analytics.model_models import ClassCalibrationRun, ModelComparisonRun
from learning_analytics.services.advanced_models import (
    MODEL_02_VERSION,
    build_model_02_comparison,
    fit_advanced_model,
    predict_advanced_model,
    select_best_advanced_model,
)
from learning_analytics.services.model_comparison import _dataset_rows, _target_type


CALIBRATION_VERSION = "model-03-v4"
CLASS_PRIOR_STRENGTH = 20.0
FEATURE_LABELS = {
    "prior_due_required_count__7d": "近 7 日到期必做任务数",
    "prior_due_required_count__30d": "近 30 日到期必做任务数",
    "prior_graded_item_count__14d": "近 14 日已评分题目数",
    "prior_graded_item_count__30d": "近 30 日已评分题目数",
    "prior_score_ratio__14d": "近 14 日题目得分率",
    "prior_score_ratio__30d": "近 30 日题目得分率",
    "opp_completion_rate__7d": "近 7 日任务完成情况",
    "opp_completion_rate__30d": "近 30 日任务完成情况",
    "on_time_submission_rate__30d": "近 30 日按时提交率",
    "active_minutes__7d": "近 7 日有效活动时间",
    "active_minutes__30d": "近 30 日有效活动时间",
    "active_days_ratio__7d": "近 7 日有效活动天数比例",
    "active_days_ratio__30d": "近 30 日有效活动天数比例",
    "resource_completion_rate__7d": "近 7 日资源完成率",
    "resource_completion_rate__30d": "近 30 日资源完成率",
    "first_attempt_score_ratio__14d": "近 14 日首次作答得分率",
    "first_attempt_score_ratio__30d": "近 30 日首次作答得分率",
    "first_attempt_accuracy__14d": "近 14 日首次作答正确率",
    "first_attempt_accuracy__30d": "近 30 日首次作答正确率",
}
RATIO_FEATURE_PREFIXES = {
    "prior_score_ratio",
    "opp_completion_rate",
    "on_time_submission_rate",
    "active_days_ratio",
    "resource_completion_rate",
    "first_attempt_score_ratio",
    "first_attempt_accuracy",
}
COUNT_FEATURE_PREFIXES = {
    "prior_due_required_count",
    "prior_graded_item_count",
}
LEGACY_REASON_PATTERN = re.compile(
    r"^(?P<feature>[a-z0-9_]+)（(?P<window>1d|7d|14d|30d|unit)）：(?P<value>-?\d+(?:\.\d+)?)$"
)


def _higher_is_better(outcome_key: str) -> bool:
    lowered = outcome_key.lower()
    return not any(token in lowered for token in ("overdue", "late", "error", "risk"))


def _save_artifact(model, model_key: str, run_key: str, school_id: int) -> tuple[str, str]:
    root = Path(settings.MODEL_ARTIFACT_ROOT)
    folder = root / f"school_{school_id}" / "model03" / run_key
    folder.mkdir(parents=True, exist_ok=True)
    filename = "global_model.cbm" if model_key == "CATBOOST" else "global_model.txt"
    path = folder / filename
    if model_key == "CATBOOST":
        model.save_model(str(path))
    else:
        model.booster_.save_model(str(path))
    content = path.read_bytes()
    try:
        relative = path.relative_to(Path(settings.BASE_DIR))
    except ValueError:
        relative = path
    return str(relative).replace("\\", "/"), hashlib.sha256(content).hexdigest()


def _quantile(values: list[float], q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), q))


def _layer_for_score(score: float, lower: float, upper: float, *, higher_is_better: bool):
    if higher_is_better:
        if score >= upper:
            return "A"
        if score >= lower:
            return "B"
        return "C"
    if score <= lower:
        return "A"
    if score <= upper:
        return "B"
    return "C"


def _confidence(score: float, lower: float, upper: float) -> float:
    span = max(abs(upper - lower), 0.05)
    distance = min(abs(score - lower), abs(score - upper))
    return round(min(0.95, 0.55 + 0.4 * distance / span), 4)


def _format_feature_value(key: str, value: float) -> str:
    feature_prefix = key.split("__", 1)[0]
    if feature_prefix in RATIO_FEATURE_PREFIXES:
        return f"{value * 100:.0f}%"
    if feature_prefix in COUNT_FEATURE_PREFIXES:
        return f"{value:.0f}"
    if feature_prefix == "active_minutes":
        return f"{value:.0f} 分钟"
    return f"{value:.2f}"


def friendly_decision_reason(reason: str) -> str:
    """Translate legacy feature-key explanations without changing stored evidence."""
    match = LEGACY_REASON_PATTERN.match(reason)
    if not match:
        return reason
    key = f"{match.group('feature')}__{match.group('window')}"
    label = FEATURE_LABELS.get(key)
    if not label:
        return reason
    value = float(match.group("value"))
    return f"{label}：{_format_feature_value(key, value)}"


def _reasons(row, importance: list[dict]) -> list[str]:
    reasons = []
    for item in importance[:3]:
        key = item.get("feature_key", "")
        value = row.features.get(key)
        if value is None:
            continue
        label = FEATURE_LABELS.get(key, "学习过程指标")
        reasons.append(f"{label}：{_format_feature_value(key, float(value))}")
    return reasons or ["依据当前冻结的学习过程记录形成候选建议。"]


def _support_suggestion(layer: str) -> str:
    return {
        "A": "可安排拓展任务，同时保留共同题用于持续比较。",
        "B": "保持核心任务，结合薄弱环节安排一次针对性练习。",
        "C": "先提供必要支架和基础任务，完成后再逐步增加难度。",
    }[layer]


@transaction.atomic
def build_class_calibration_candidate(
    *,
    dataset: TrainingDatasetVersion,
    comparison_run: ModelComparisonRun | None = None,
    created_by=None,
    include_test_data: bool = False,
) -> ClassCalibrationRun:
    if dataset.status != TrainingDatasetVersion.Status.FROZEN:
        raise ValidationError("只能为已冻结的数据版本生成班级校准候选。")
    comparison_run = comparison_run or ModelComparisonRun.objects.filter(
        dataset=dataset,
        comparison_version=MODEL_02_VERSION,
    ).first()
    if comparison_run is None:
        comparison_run = build_model_02_comparison(
            dataset=dataset,
            created_by=created_by,
            include_test_data=include_test_data,
        )
    run_key = canonical_hash(
        {
            "dataset_key": dataset.dataset_key,
            "comparison_run_key": comparison_run.run_key,
            "version": CALIBRATION_VERSION,
        }
    )[:48]
    existing = ClassCalibrationRun.objects.filter(run_key=run_key).first()
    if existing:
        return existing
    best_model_key = select_best_advanced_model(comparison_run)
    run = ClassCalibrationRun.objects.create(
        run_key=run_key,
        dataset=dataset,
        comparison_run=comparison_run,
        school=dataset.school,
        subject=dataset.subject,
        calibration_version=CALIBRATION_VERSION,
        model_key=best_model_key or "",
        status=ClassCalibrationRun.Status.BUILDING,
        created_by=created_by,
        manifest={"status": "building"},
    )
    rows = _dataset_rows(dataset)
    rows_by_id = {item.row_id: item for item in rows}
    feature_keys = list(dataset.manifest.get("model_input_feature_keys", []))
    target_type = _target_type(rows)
    blockers = []
    if comparison_run.status != ModelComparisonRun.Status.SHADOW_ONLY:
        blockers.append("MODEL-02 尚未通过基础检查。")
    if best_model_key is None:
        blockers.append("没有可用于班级校准的 CatBoost 或 LightGBM 结果。")
    if len(rows) < 60:
        blockers.append("已观察结果少于 60 条，暂不生成班级校准建议。")
    if blockers:
        run.manifest = {
            "calibration_version": CALIBRATION_VERSION,
            "dataset_key": dataset.dataset_key,
            "comparison_run_id": comparison_run.id,
            "blockers": blockers,
        }
        run.model_card = {
            "title": "MODEL-03 班级校准候选",
            "status": "blocked",
            "prohibited_use": "不得自动修改学生层级。",
        }
        run.status = ClassCalibrationRun.Status.BLOCKED
        run.save()
        return run

    model = fit_advanced_model(best_model_key, rows, feature_keys, target_type)
    if model is None:
        raise ValidationError("无法使用完整冻结数据建立全局模型。")
    predictions = predict_advanced_model(
        model, best_model_key, rows, feature_keys, target_type
    )
    predicted_by_row = {
        item.row.row_id: float(item.value)
        for item in predictions
        if item.status == "predicted" and item.value is not None
    }
    if len(predicted_by_row) < 60:
        raise ValidationError("可用预测少于 60 条，不能生成班级校准候选。")

    global_residuals = [
        row.outcome - predicted_by_row[row.row_id]
        for row in rows
        if row.row_id in predicted_by_row
    ]
    global_residual = float(np.mean(global_residuals))
    class_residuals: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.row_id in predicted_by_row:
            class_residuals[row.class_key].append(
                row.outcome - predicted_by_row[row.row_id]
            )
    class_parameters = {}
    calibrated_by_row = {}
    for class_key, residuals in class_residuals.items():
        count = len(residuals)
        class_residual = float(np.mean(residuals))
        weight = count / (count + CLASS_PRIOR_STRENGTH)
        correction = weight * class_residual + (1 - weight) * global_residual
        class_parameters[class_key] = {
            "n": count,
            "raw_residual_mean": class_residual,
            "shrinkage_weight": weight,
            "calibration_correction": correction,
        }
    for row in rows:
        if row.row_id not in predicted_by_row:
            continue
        correction = class_parameters[row.class_key]["calibration_correction"]
        calibrated_by_row[row.row_id] = predicted_by_row[row.row_id] + correction

    values = list(calibrated_by_row.values())
    lower = _quantile(values, 1 / 3)
    upper = _quantile(values, 2 / 3)
    higher_is_better = _higher_is_better(dataset.outcome_definition.outcome_key)
    artifact_path, artifact_hash = _save_artifact(
        model, best_model_key, run_key, dataset.school_id
    )
    importance = []
    raw_importance = getattr(model, "feature_importances_", None)
    if raw_importance is not None:
        importance = sorted(
            [
                {"feature_key": key, "importance": round(float(value), 8)}
                for key, value in zip(feature_keys, raw_importance)
            ],
            key=lambda item: item["importance"],
            reverse=True,
        )

    dataset_rows = {
        item.id: item
        for item in TrainingDatasetRow.objects.filter(
            dataset=dataset,
            outcome_status="observed",
            outcome_value__isnull=False,
        ).select_related(
            "snapshot__student__student_profile",
            "decision_point__class_group",
            "decision_point__course",
            "decision_point__subject",
        )
    }
    latest_by_student = {}
    for row in rows:
        source = dataset_rows[row.row_id]
        student_id = source.snapshot.student_id
        previous = latest_by_student.get(student_id)
        if previous is None or source.decision_point.scheduled_for > previous.decision_point.scheduled_for:
            latest_by_student[student_id] = source

    rule_version = f"m03-{run_key[:24]}"
    latest_sources = list(latest_by_student.values())
    suggestion_count = 0
    for source in latest_sources:
        score = calibrated_by_row.get(source.id)
        if score is None:
            continue
        student = source.snapshot.student
        profile = student.student_profile
        suggested_layer = _layer_for_score(
            score, lower, upper, higher_is_better=higher_is_better
        )
        comparison_row = rows_by_id[source.id]
        _, created = StratificationDecision.objects.get_or_create(
            student=student,
            course=source.decision_point.course,
            window_end=dataset.decision_end,
            rule_version=rule_version,
            defaults={
                "class_group": source.decision_point.class_group,
                "subject": source.decision_point.subject,
                "previous_layer": profile.current_layer or "",
                "suggested_layer": suggested_layer,
                "confidence": _confidence(score, lower, upper),
                "reasons": _reasons(comparison_row, importance),
                "missing_data": [],
                "learning_summary": {
                    "source": "model03",
                    "calibration_run_id": run.id,
                    "model_key": best_model_key,
                    "raw_prediction": predicted_by_row[source.id],
                    "calibrated_prediction": score,
                    "outcome_key": dataset.outcome_definition.outcome_key,
                },
                "support_suggestion": _support_suggestion(suggested_layer),
                "window_start": dataset.decision_start,
                "calibration_run": run,
                "status": StratificationDecision.Status.PENDING,
            },
        )
        suggestion_count += created

    run.global_parameters = {
        "outcome_key": dataset.outcome_definition.outcome_key,
        "higher_is_better": higher_is_better,
        "global_residual_correction": global_residual,
        "layer_thresholds": {"lower": lower, "upper": upper},
        "class_prior_strength": CLASS_PRIOR_STRENGTH,
        "feature_importance": importance,
    }
    run.class_parameters = class_parameters
    run.artifact_path = artifact_path
    run.artifact_hash = artifact_hash
    run.suggestion_count = suggestion_count
    run.manifest = {
        "calibration_version": CALIBRATION_VERSION,
        "dataset_key": dataset.dataset_key,
        "comparison_run_id": comparison_run.id,
        "model_key": best_model_key,
        "row_count": len(rows),
        "class_count": len(class_parameters),
        "suggestion_count": suggestion_count,
        "rule_version": rule_version,
        "blockers": [],
    }
    run.model_card = {
        "title": "MODEL-03 班级校准候选",
        "status": "candidate",
        "method": "全局结构化模型加班级残差收缩校准，不按单班从零训练模型。",
        "intended_use": "向任课教师提供学生不可见的学习支持候选建议。",
        "prohibited_use": "不得自动修改学生层级，不得向学生展示层级、概率或判断原因。",
        "teacher_confirmation_required": True,
    }
    run.status = ClassCalibrationRun.Status.CANDIDATE
    run.save()
    return run
