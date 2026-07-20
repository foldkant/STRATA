from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .feature_models import TrainingDatasetRow, TrainingDatasetVersion, canonical_hash


HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class LongitudinalAnalysisRun(models.Model):
    """保存同一冻结数据版本上的重复测量统计结果。"""

    class Status(models.TextChoices):
        BUILDING = "building", "计算中"
        COMPLETED = "completed", "已完成"
        BLOCKED = "blocked", "数据不足"
        FAILED = "failed", "计算失败"

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    run_key = models.CharField(max_length=96, unique=True)
    dataset = models.ForeignKey(
        TrainingDatasetVersion,
        on_delete=models.PROTECT,
        related_name="longitudinal_runs",
    )
    school = models.ForeignKey(
        "school.School", on_delete=models.PROTECT, related_name="longitudinal_runs"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="longitudinal_runs"
    )
    analysis_version = models.CharField(max_length=32, default="longitudinal-v1")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.BUILDING
    )
    manifest = models.JSONField(default=dict, blank=True)
    manifest_hash = models.CharField(max_length=64, blank=True)
    feature_count = models.PositiveIntegerField(default=0)
    ready_feature_count = models.PositiveIntegerField(default=0)
    row_count = models.PositiveIntegerField(default=0)
    student_count = models.PositiveIntegerField(default=0)
    class_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_longitudinal_runs",
    )
    error_message = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "analysis_version"],
                name="uniq_longitudinal_dataset_version",
            )
        ]
        ordering = ["-created_at", "-id"]

    def clean(self):
        errors = {}
        if self.dataset_id and self.dataset.status != TrainingDatasetVersion.Status.FROZEN:
            errors["dataset"] = "重复测量统计只能读取已冻结的数据版本。"
        if self.dataset_id and self.dataset.school_id != self.school_id:
            errors["school"] = "统计学校与数据版本不一致。"
        if self.dataset_id and self.dataset.subject_id != self.subject_id:
            errors["subject"] = "统计学科与数据版本不一致。"
        if self.status in {self.Status.COMPLETED, self.Status.BLOCKED}:
            if not self.finished_at:
                errors["finished_at"] = "已结束的统计必须记录完成时间。"
            if not self.manifest_hash:
                errors["manifest_hash"] = "已结束的统计必须保存清单摘要。"
        if self.manifest_hash and not HASH_PATTERN.fullmatch(self.manifest_hash):
            errors["manifest_hash"] = "清单摘要格式不正确。"
        if not isinstance(self.manifest, dict):
            errors["manifest"] = "统计清单必须是 JSON 对象。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous and previous.status in {self.Status.COMPLETED, self.Status.BLOCKED}:
            raise ValidationError("已完成的重复测量统计不可修改。")
        if self.status in {self.Status.COMPLETED, self.Status.BLOCKED} and not self.finished_at:
            self.finished_at = timezone.now()
        if self.status in {self.Status.COMPLETED, self.Status.BLOCKED} and not self.manifest_hash:
            self.manifest_hash = canonical_hash(self.manifest)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.BUILDING:
            raise ValidationError("已完成的重复测量统计不可删除。")
        return super().delete(*args, **kwargs)


class LongitudinalFeatureResult(models.Model):
    class Status(models.TextChoices):
        READY = "ready", "材料足够"
        INSUFFICIENT_N = "insufficient_n", "数据不足"
        NOT_APPLICABLE = "not_applicable", "暂不适用"

    run = models.ForeignKey(
        LongitudinalAnalysisRun,
        on_delete=models.PROTECT,
        related_name="feature_results",
    )
    feature_key = models.CharField(max_length=96)
    status = models.CharField(max_length=24, choices=Status.choices)
    observation_count = models.PositiveIntegerField(default=0)
    student_count = models.PositiveIntegerField(default=0)
    class_count = models.PositiveIntegerField(default=0)
    total_variance = models.FloatField(null=True, blank=True)
    between_variance = models.FloatField(null=True, blank=True)
    within_variance = models.FloatField(null=True, blank=True)
    intraclass_correlation = models.FloatField(null=True, blank=True)
    overall_association = models.FloatField(null=True, blank=True)
    within_association = models.FloatField(null=True, blank=True)
    between_association = models.FloatField(null=True, blank=True)
    interval_low = models.FloatField(null=True, blank=True)
    interval_high = models.FloatField(null=True, blank=True)
    direction = models.CharField(max_length=24, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "feature_key"],
                name="uniq_longitudinal_run_feature",
            )
        ]
        ordering = ["run_id", "feature_key"]

    def clean(self):
        if not isinstance(self.details, dict):
            raise ValidationError({"details": "指标统计详情必须是 JSON 对象。"})


class ModelComparisonRun(models.Model):
    class Status(models.TextChoices):
        BUILDING = "building", "计算中"
        SHADOW_ONLY = "shadow_only", "影子比较"
        BLOCKED = "blocked", "暂不输出"
        FAILED = "failed", "计算失败"

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    run_key = models.CharField(max_length=96, unique=True)
    dataset = models.ForeignKey(
        TrainingDatasetVersion,
        on_delete=models.PROTECT,
        related_name="model_comparison_runs",
    )
    school = models.ForeignKey(
        "school.School", on_delete=models.PROTECT, related_name="model_comparison_runs"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="model_comparison_runs"
    )
    comparison_version = models.CharField(max_length=32, default="model-01-v2")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.BUILDING
    )
    target_type = models.CharField(max_length=24, default="continuous")
    model_keys = models.JSONField(default=list, blank=True)
    validation_keys = models.JSONField(default=list, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    model_card = models.JSONField(default=dict, blank=True)
    manifest_hash = models.CharField(max_length=64, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    observed_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_model_comparison_runs",
    )
    error_message = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "comparison_version"],
                name="uniq_model_comparison_dataset_version",
            )
        ]
        ordering = ["-created_at", "-id"]

    def clean(self):
        errors = {}
        if self.dataset_id and self.dataset.status != TrainingDatasetVersion.Status.FROZEN:
            errors["dataset"] = "模型比较只能读取已冻结的数据版本。"
        if self.dataset_id and self.dataset.school_id != self.school_id:
            errors["school"] = "模型比较学校与数据版本不一致。"
        if self.dataset_id and self.dataset.subject_id != self.subject_id:
            errors["subject"] = "模型比较学科与数据版本不一致。"
        if self.status in {self.Status.SHADOW_ONLY, self.Status.BLOCKED}:
            if not self.finished_at:
                errors["finished_at"] = "已结束的模型比较必须记录完成时间。"
            if not self.manifest_hash:
                errors["manifest_hash"] = "已结束的模型比较必须保存清单摘要。"
        if self.manifest_hash and not HASH_PATTERN.fullmatch(self.manifest_hash):
            errors["manifest_hash"] = "模型比较清单摘要格式不正确。"
        if not isinstance(self.model_keys, list):
            errors["model_keys"] = "模型编号必须是列表。"
        if not isinstance(self.validation_keys, list):
            errors["validation_keys"] = "验证方式必须是列表。"
        if not isinstance(self.manifest, dict) or not isinstance(self.model_card, dict):
            errors["manifest"] = "模型比较清单和模型卡必须是 JSON 对象。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous and previous.status in {self.Status.SHADOW_ONLY, self.Status.BLOCKED}:
            raise ValidationError("已完成的模型比较不可修改。")
        if self.status in {self.Status.SHADOW_ONLY, self.Status.BLOCKED} and not self.finished_at:
            self.finished_at = timezone.now()
        if self.status in {self.Status.SHADOW_ONLY, self.Status.BLOCKED} and not self.manifest_hash:
            self.manifest_hash = canonical_hash(self.manifest)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.BUILDING:
            raise ValidationError("已完成的模型比较不可删除。")
        return super().delete(*args, **kwargs)


class ModelEvaluationResult(models.Model):
    class Status(models.TextChoices):
        READY = "ready", "可报告"
        INSUFFICIENT_N = "insufficient_n", "数据不足"
        NOT_APPLICABLE = "not_applicable", "暂不适用"
        BLOCKED = "blocked", "已阻断"

    run = models.ForeignKey(
        ModelComparisonRun, on_delete=models.PROTECT, related_name="evaluations"
    )
    model_key = models.CharField(max_length=16)
    validation_key = models.CharField(max_length=16)
    status = models.CharField(max_length=24, choices=Status.choices)
    train_count = models.PositiveIntegerField(default=0)
    test_count = models.PositiveIntegerField(default=0)
    predicted_count = models.PositiveIntegerField(default=0)
    abstained_count = models.PositiveIntegerField(default=0)
    primary_metric = models.FloatField(null=True, blank=True)
    rmse = models.FloatField(null=True, blank=True)
    mae = models.FloatField(null=True, blank=True)
    brier_score = models.FloatField(null=True, blank=True)
    calibration_intercept = models.FloatField(null=True, blank=True)
    calibration_slope = models.FloatField(null=True, blank=True)
    coverage = models.FloatField(null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "model_key", "validation_key"],
                name="uniq_model_eval_run_model_validation",
            )
        ]
        ordering = ["run_id", "validation_key", "model_key"]

    def clean(self):
        if not isinstance(self.metrics, dict):
            raise ValidationError({"metrics": "模型指标必须是 JSON 对象。"})


class ModelPrediction(models.Model):
    class Status(models.TextChoices):
        PREDICTED = "predicted", "已预测"
        ABSTAINED = "abstained", "拒绝预测"
        NOT_APPLICABLE = "not_applicable", "暂不适用"

    run = models.ForeignKey(
        ModelComparisonRun, on_delete=models.PROTECT, related_name="predictions"
    )
    evaluation = models.ForeignKey(
        ModelEvaluationResult,
        on_delete=models.PROTECT,
        related_name="predictions",
    )
    dataset_row = models.ForeignKey(
        TrainingDatasetRow, on_delete=models.PROTECT, related_name="model_predictions"
    )
    pseudonymous_key = models.CharField(max_length=64)
    model_key = models.CharField(max_length=16)
    validation_key = models.CharField(max_length=16)
    status = models.CharField(max_length=24, choices=Status.choices)
    predicted_value = models.FloatField(null=True, blank=True)
    observed_value = models.FloatField(null=True, blank=True)
    abstain_reason = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "dataset_row", "model_key", "validation_key"],
                name="uniq_model_prediction_row_model_fold",
            )
        ]
        indexes = [
            models.Index(fields=["run", "model_key", "validation_key"]),
            models.Index(fields=["pseudonymous_key", "run"]),
        ]

    def clean(self):
        errors = {}
        if self.dataset_row_id and self.dataset_row.dataset_id != self.run.dataset_id:
            errors["dataset_row"] = "预测记录与模型比较数据版本不一致。"
        if self.pseudonymous_key and not re.fullmatch(r"^[0-9a-f]{64}$", self.pseudonymous_key):
            errors["pseudonymous_key"] = "预测记录只能保存匿名编号。"
        if self.status == self.Status.PREDICTED and self.predicted_value is None:
            errors["predicted_value"] = "已预测记录必须保存预测值。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("模型预测记录不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("模型预测记录不可直接删除。")


class NegativeControlResult(models.Model):
    class Status(models.TextChoices):
        PASSED = "passed", "通过"
        INSUFFICIENT_N = "insufficient_n", "数据不足"
        FAILED = "failed", "需解释"
        NOT_APPLICABLE = "not_applicable", "暂不适用"

    run = models.ForeignKey(
        ModelComparisonRun, on_delete=models.PROTECT, related_name="negative_controls"
    )
    control_key = models.CharField(max_length=48)
    status = models.CharField(max_length=24, choices=Status.choices)
    expected_behavior = models.CharField(max_length=255)
    observed_metric = models.FloatField(null=True, blank=True)
    baseline_metric = models.FloatField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "control_key"],
                name="uniq_negative_control_run_key",
            )
        ]
        ordering = ["run_id", "control_key"]

    def clean(self):
        if not isinstance(self.details, dict):
            raise ValidationError({"details": "负对照详情必须是 JSON 对象。"})


class ClassCalibrationRun(models.Model):
    """保存全局模型在班级层面的校准候选，不直接改变学生层级。"""

    class Status(models.TextChoices):
        BUILDING = "building", "生成中"
        CANDIDATE = "candidate", "待教师使用"
        BLOCKED = "blocked", "暂不生成建议"
        FAILED = "failed", "生成失败"
        ARCHIVED = "archived", "已归档"

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    run_key = models.CharField(max_length=96, unique=True)
    dataset = models.ForeignKey(
        TrainingDatasetVersion,
        on_delete=models.PROTECT,
        related_name="class_calibration_runs",
    )
    comparison_run = models.ForeignKey(
        ModelComparisonRun,
        on_delete=models.PROTECT,
        related_name="class_calibration_runs",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="class_calibration_runs",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="class_calibration_runs",
    )
    calibration_version = models.CharField(max_length=32, default="model-03-v1")
    model_key = models.CharField(max_length=16, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.BUILDING,
    )
    global_parameters = models.JSONField(default=dict, blank=True)
    class_parameters = models.JSONField(default=dict, blank=True)
    model_card = models.JSONField(default=dict, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    manifest_hash = models.CharField(max_length=64, blank=True)
    artifact_path = models.CharField(max_length=500, blank=True)
    artifact_hash = models.CharField(max_length=64, blank=True)
    suggestion_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_class_calibration_runs",
    )
    error_message = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "calibration_version"],
                name="uniq_class_calibration_dataset_version",
            )
        ]
        indexes = [
            models.Index(fields=["school", "subject", "status"]),
            models.Index(fields=["comparison_run", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self):
        errors = {}
        if self.dataset_id and self.dataset.status != TrainingDatasetVersion.Status.FROZEN:
            errors["dataset"] = "班级校准只能读取已冻结的数据版本。"
        if self.dataset_id and self.dataset.school_id != self.school_id:
            errors["school"] = "班级校准学校与数据版本不一致。"
        if self.dataset_id and self.dataset.subject_id != self.subject_id:
            errors["subject"] = "班级校准学科与数据版本不一致。"
        if self.comparison_run_id and self.comparison_run.dataset_id != self.dataset_id:
            errors["comparison_run"] = "班级校准与模型比较数据版本不一致。"
        if not isinstance(self.global_parameters, dict):
            errors["global_parameters"] = "全局校准参数必须是 JSON 对象。"
        if not isinstance(self.class_parameters, dict):
            errors["class_parameters"] = "班级校准参数必须是 JSON 对象。"
        if not isinstance(self.model_card, dict) or not isinstance(self.manifest, dict):
            errors["manifest"] = "模型卡和运行清单必须是 JSON 对象。"
        if self.status in {self.Status.CANDIDATE, self.Status.BLOCKED}:
            if not self.finished_at:
                errors["finished_at"] = "已结束的班级校准必须记录完成时间。"
            if not self.manifest_hash:
                errors["manifest_hash"] = "已结束的班级校准必须保存清单摘要。"
        for field_name in ("manifest_hash", "artifact_hash"):
            value = getattr(self, field_name)
            if value and not HASH_PATTERN.fullmatch(value):
                errors[field_name] = "摘要必须是 64 位小写 SHA-256。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous and previous.status in {
            self.Status.CANDIDATE,
            self.Status.BLOCKED,
            self.Status.ARCHIVED,
        }:
            raise ValidationError("已结束的班级校准不可修改。")
        if self.status in {self.Status.CANDIDATE, self.Status.BLOCKED}:
            if not self.finished_at:
                self.finished_at = timezone.now()
            if not self.manifest_hash:
                self.manifest_hash = canonical_hash(self.manifest)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.BUILDING:
            raise ValidationError("已结束的班级校准不可直接删除。")
        return super().delete(*args, **kwargs)


class ModelRelease(models.Model):
    """A signed, school-scoped release of one immutable calibration run."""

    class Status(models.TextChoices):
        ACTIVE = "active", "当前使用"
        SUPERSEDED = "superseded", "已被新版本替代"
        ROLLED_BACK = "rolled_back", "已回退"

    release_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    release_key = models.CharField(max_length=96, unique=True)
    school = models.ForeignKey(
        "school.School", on_delete=models.PROTECT, related_name="model_releases"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="model_releases"
    )
    calibration_run = models.ForeignKey(
        ClassCalibrationRun,
        on_delete=models.PROTECT,
        related_name="releases",
    )
    release_version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    is_test_data = models.BooleanField(default=False)
    previous_release = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replacement_releases",
    )
    package_path = models.CharField(max_length=500)
    package_hash = models.CharField(max_length=64)
    package_signature = models.TextField()
    signing_key_id = models.CharField(max_length=64)
    manifest = models.JSONField(default=dict)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_model_releases",
    )
    released_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "is_test_data", "release_version"],
                name="uniq_model_release_scope_version",
            ),
            models.UniqueConstraint(
                fields=["school", "subject", "is_test_data"],
                condition=models.Q(status="active"),
                name="uniq_active_model_release_scope",
            ),
            models.UniqueConstraint(
                fields=["calibration_run"],
                name="uniq_model_release_calibration_run",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "is_test_data", "status"]),
            models.Index(fields=["released_at"]),
        ]
        ordering = ["-released_at", "-id"]

    def clean(self):
        errors = {}
        if self.calibration_run_id:
            if self.calibration_run.school_id != self.school_id:
                errors["school"] = "发布学校与班级校准运行不一致。"
            if self.calibration_run.subject_id != self.subject_id:
                errors["subject"] = "发布学科与班级校准运行不一致。"
            if self.calibration_run.status != ClassCalibrationRun.Status.CANDIDATE:
                errors["calibration_run"] = "只能发布已通过基础检查的候选模型。"
            expected_test_data = bool(self.calibration_run.dataset.synthetic_run_id)
            if self.is_test_data != expected_test_data:
                errors["is_test_data"] = "发布记录的测试数据标记与数据版本不一致。"
        if self.previous_release_id:
            previous = self.previous_release
            if (
                previous.school_id != self.school_id
                or previous.subject_id != self.subject_id
                or previous.is_test_data != self.is_test_data
            ):
                errors["previous_release"] = "上一版本必须属于相同学校、学科和数据范围。"
        for field_name in ("package_hash", "signing_key_id"):
            value = getattr(self, field_name)
            if not HASH_PATTERN.fullmatch(value or ""):
                errors[field_name] = "摘要必须是 64 位小写 SHA-256。"
        if not isinstance(self.manifest, dict):
            errors["manifest"] = "发布清单必须是 JSON 对象。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("模型发布记录不可删除。")


class ModelReleaseAudit(models.Model):
    class Action(models.TextChoices):
        PUBLISH = "publish", "发布"
        ROLLBACK = "rollback", "回滚"
        VERIFY = "verify", "校验"

    class Result(models.TextChoices):
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    school = models.ForeignKey(
        "school.School", on_delete=models.PROTECT, related_name="model_release_audits"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="model_release_audits"
    )
    calibration_run = models.ForeignKey(
        ClassCalibrationRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="release_audits",
    )
    release = models.ForeignKey(
        ModelRelease,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_records",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="model_release_actions",
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    result = models.CharField(max_length=16, choices=Result.choices)
    message = models.CharField(max_length=500)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "subject", "created_at"]),
            models.Index(fields=["action", "result", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self):
        if not isinstance(self.details, dict):
            raise ValidationError({"details": "审计详情必须是 JSON 对象。"})
        if self.calibration_run_id and self.calibration_run.school_id != self.school_id:
            raise ValidationError({"calibration_run": "校准运行不属于当前学校。"})
        if self.release_id and self.release.school_id != self.school_id:
            raise ValidationError({"release": "发布记录不属于当前学校。"})

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("模型发布审计不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("模型发布审计不可删除。")
