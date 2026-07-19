from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
MISSING_CODES = {
    "NO_OPPORTUNITY",
    "NOT_STARTED",
    "IN_PROGRESS",
    "OFFLINE",
    "DATA_ERROR",
    "INSUFFICIENT_N",
    "NOT_APPLICABLE",
}
FEATURE_WINDOWS = {"7d", "14d", "30d", "unit"}
SNAPSHOT_VIEWS = {"operational_available", "reconstructed_complete"}


def canonical_hash(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FeatureDefinition(models.Model):
    class EvidenceGroup(models.TextChoices):
        BASELINE = "F0", "基础情况"
        DIRECT = "E1", "直接行为"
        PROXY = "E2", "研究候选"
        EVALUATION = "E3", "评价派生"
        AUDIT = "F4", "数据与教学条件"

    class CausalRole(models.TextChoices):
        BASELINE_STATE = "baseline_state", "既往状态"
        INSTRUCTIONAL_OPPORTUNITY = "instructional_opportunity", "学习机会"
        BEHAVIOR_EVIDENCE = "behavior_evidence", "行为事实"
        TREATMENT = "treatment", "教师支持"
        POST_TREATMENT = "post_treatment", "支持后变化"
        OUTCOME = "outcome", "未来结果"
        DATA_QUALITY = "data_quality", "数据质量"
        PROTECTED_AUDIT = "protected_audit", "受限审查字段"

    class DataType(models.TextChoices):
        RATIO = "ratio", "比例"
        COUNT = "count", "数量"
        DURATION = "duration", "时长"
        CONTINUOUS = "continuous", "连续值"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        RETIRED = "retired", "停用"

    feature_key = models.CharField(max_length=96)
    version = models.CharField(max_length=16)
    label = models.CharField(max_length=128)
    description = models.CharField(max_length=500, blank=True)
    evidence_group = models.CharField(max_length=8, choices=EvidenceGroup.choices)
    causal_role = models.CharField(max_length=40, choices=CausalRole.choices)
    data_type = models.CharField(max_length=24, choices=DataType.choices)
    formula = models.TextField()
    windows = models.JSONField(default=list)
    min_n = models.PositiveIntegerField(default=0)
    allowed_events = models.JSONField(default=list, blank=True)
    allowed_uses = models.JSONField(default=list)
    missing_codes = models.JSONField(default=list)
    competing_explanations = models.JSONField(default=list, blank=True)
    fairness_note = models.CharField(max_length=500, blank=True)
    model_input_allowed = models.BooleanField(default=False)
    generator_key = models.CharField(max_length=96)
    code_hash = models.CharField(max_length=64)
    definition_hash = models.CharField(max_length=64, editable=False)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["feature_key", "version"],
                name="uniq_feature_definition_version",
            )
        ]
        indexes = [
            models.Index(fields=["status", "evidence_group"]),
            models.Index(fields=["causal_role", "status"]),
        ]
        ordering = ["evidence_group", "feature_key", "version"]

    def semantic_definition(self) -> dict:
        return {
            "feature_key": self.feature_key,
            "version": self.version,
            "label": self.label,
            "description": self.description,
            "evidence_group": self.evidence_group,
            "causal_role": self.causal_role,
            "data_type": self.data_type,
            "formula": self.formula,
            "windows": self.windows,
            "min_n": self.min_n,
            "allowed_events": self.allowed_events,
            "allowed_uses": self.allowed_uses,
            "missing_codes": self.missing_codes,
            "competing_explanations": self.competing_explanations,
            "fairness_note": self.fairness_note,
            "model_input_allowed": self.model_input_allowed,
            "generator_key": self.generator_key,
            "code_hash": self.code_hash,
        }

    def clean(self) -> None:
        errors = {}
        if not re.fullmatch(r"^[a-z][a-z0-9_]*$", self.feature_key or ""):
            errors["feature_key"] = "特征编号必须使用小写字母、数字和下划线。"
        if not VERSION_PATTERN.fullmatch(self.version or ""):
            errors["version"] = "版本必须使用 major.minor 格式。"
        if not isinstance(self.windows, list) or not self.windows:
            errors["windows"] = "至少登记一个计算窗口。"
        elif unknown := set(self.windows) - FEATURE_WINDOWS:
            errors["windows"] = f"包含未登记窗口：{', '.join(sorted(unknown))}。"
        if not isinstance(self.allowed_events, list):
            errors["allowed_events"] = "允许事件必须是列表。"
        if not isinstance(self.allowed_uses, list) or not self.allowed_uses:
            errors["allowed_uses"] = "至少登记一个允许用途。"
        if not isinstance(self.missing_codes, list) or not self.missing_codes:
            errors["missing_codes"] = "至少登记一个缺失原因。"
        elif unknown := set(self.missing_codes) - MISSING_CODES:
            errors["missing_codes"] = (
                f"包含未登记缺失原因：{', '.join(sorted(unknown))}。"
            )
        if self.model_input_allowed and (
            self.evidence_group == self.EvidenceGroup.AUDIT
            or self.causal_role
            in {
                self.CausalRole.TREATMENT,
                self.CausalRole.POST_TREATMENT,
                self.CausalRole.OUTCOME,
                self.CausalRole.DATA_QUALITY,
                self.CausalRole.PROTECTED_AUDIT,
            }
        ):
            errors["model_input_allowed"] = (
                "教学处理、结果和数据质量字段不能进入主模型输入。"
            )
        if not re.fullmatch(r"^[0-9a-f]{64}$", self.code_hash or ""):
            errors["code_hash"] = "计算代码摘要必须是 64 位小写 SHA-256。"
        if self.status == self.Status.ACTIVE and not self.activated_at:
            self.activated_at = timezone.now()
        if self.status == self.Status.RETIRED and not self.retired_at:
            self.retired_at = timezone.now()
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        self.definition_hash = canonical_hash(self.semantic_definition())
        if previous and previous.status in {self.Status.ACTIVE, self.Status.RETIRED}:
            if previous.definition_hash != self.definition_hash:
                raise ValidationError("已启用的特征定义不可修改，请登记新版本。")
        if previous and previous.status == self.Status.ACTIVE:
            if self.status not in {self.Status.ACTIVE, self.Status.RETIRED}:
                raise ValidationError("已启用的特征定义只能停用。")
        if previous and previous.status == self.Status.RETIRED:
            if self.status != self.Status.RETIRED:
                raise ValidationError("已停用的特征定义不能重新启用。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("已启用或停用的特征定义不可删除。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.feature_key}@{self.version}"


class FeatureSetVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        RETIRED = "retired", "停用"

    set_key = models.CharField(max_length=64)
    version = models.CharField(max_length=16)
    label = models.CharField(max_length=128)
    definition_manifest = models.JSONField(default=list)
    allowed_views = models.JSONField(default=list)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    manifest_hash = models.CharField(max_length=64, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_feature_sets",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["set_key", "version"], name="uniq_feature_set_version"
            )
        ]
        ordering = ["set_key", "version"]

    def clean(self) -> None:
        errors = {}
        if not VERSION_PATTERN.fullmatch(self.version or ""):
            errors["version"] = "版本必须使用 major.minor 格式。"
        if (
            not isinstance(self.definition_manifest, list)
            or not self.definition_manifest
        ):
            errors["definition_manifest"] = "特征集必须包含特征定义。"
        if not isinstance(self.allowed_views, list) or not self.allowed_views:
            errors["allowed_views"] = "特征集必须登记可用视图。"
        elif unknown := set(self.allowed_views) - SNAPSHOT_VIEWS:
            errors["allowed_views"] = f"包含未登记视图：{', '.join(sorted(unknown))}。"
        if self.status == self.Status.ACTIVE and not self.activated_at:
            self.activated_at = timezone.now()
        if self.status == self.Status.RETIRED and not self.retired_at:
            self.retired_at = timezone.now()
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        self.manifest_hash = canonical_hash(
            {
                "set_key": self.set_key,
                "version": self.version,
                "definition_manifest": self.definition_manifest,
                "allowed_views": self.allowed_views,
            }
        )
        if previous and previous.status in {self.Status.ACTIVE, self.Status.RETIRED}:
            if previous.manifest_hash != self.manifest_hash:
                raise ValidationError("已启用的特征集不可修改，请登记新版本。")
        if previous and previous.status == self.Status.ACTIVE:
            if self.status not in {self.Status.ACTIVE, self.Status.RETIRED}:
                raise ValidationError("已启用的特征集只能停用。")
        if previous and previous.status == self.Status.RETIRED:
            if self.status != self.Status.RETIRED:
                raise ValidationError("已停用的特征集不能重新启用。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("已启用或停用的特征集不可删除。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.set_key}@{self.version}"


class DecisionPoint(models.Model):
    class PointType(models.TextChoices):
        WEEKLY = "weekly", "周度"
        UNIT = "unit", "单元"
        MANUAL = "manual", "手动"

    class Purpose(models.TextChoices):
        OPERATIONAL = "operational", "日常教学"
        PILOT = "pilot", "试运行"
        RESEARCH = "research", "正式研究"

    class Status(models.TextChoices):
        PLANNED = "planned", "已计划"
        FROZEN = "frozen", "已冻结"
        CANCELLED = "cancelled", "已取消"

    decision_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    scope_key = models.CharField(max_length=64, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="analysis_decision_points",
    )
    synthetic_run = models.ForeignKey(
        "learning_analytics.SyntheticDatasetRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analysis_decision_points",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="analysis_decision_points",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="analysis_decision_points",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analysis_decision_points",
    )
    feature_set = models.ForeignKey(
        FeatureSetVersion,
        on_delete=models.PROTECT,
        related_name="decision_points",
    )
    title = models.CharField(max_length=160)
    point_type = models.CharField(max_length=16, choices=PointType.choices)
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PLANNED
    )
    scheduled_for = models.DateTimeField()
    prediction_horizon_days = models.PositiveSmallIntegerField(default=7)
    allowed_lateness_minutes = models.PositiveIntegerField(default=1440)
    source = models.CharField(max_length=32, default="manual")
    context_snapshot = models.JSONField(default=dict, blank=True)
    context_hash = models.CharField(max_length=64, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_analysis_decision_points",
    )
    frozen_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "status", "scheduled_for"]),
            models.Index(fields=["class_group", "subject", "scheduled_for"]),
        ]
        ordering = ["-scheduled_for", "-id"]

    @property
    def late_data_cutoff(self):
        return self.scheduled_for + timedelta(minutes=self.allowed_lateness_minutes)

    def clean(self) -> None:
        errors = {}
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "班级与学校不一致。"
        if self.synthetic_run_id and self.synthetic_run.school_id != self.school_id:
            errors["synthetic_run"] = "模拟数据批次与分析时间点学校不一致。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与学校不一致。"
        if self.course_id and self.course.subject_id != self.subject_id:
            errors["course"] = "课程与学科不一致。"
        if (
            self.feature_set_id
            and self.feature_set.status != FeatureSetVersion.Status.ACTIVE
        ):
            errors["feature_set"] = "只能使用已启用的特征集。"
        if self.prediction_horizon_days < 1 or self.prediction_horizon_days > 365:
            errors["prediction_horizon_days"] = "未来观察天数必须为 1 至 365。"
        if self.status == self.Status.FROZEN and not self.frozen_at:
            self.frozen_at = timezone.now()
        if self.status == self.Status.CANCELLED and not self.cancelled_at:
            self.cancelled_at = timezone.now()
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous and previous.status == self.Status.FROZEN:
            raise ValidationError("已冻结的分析时间点不可修改。")
        if previous and previous.status == self.Status.CANCELLED:
            raise ValidationError("已取消的分析时间点不可修改。")
        self.scope_key = canonical_hash(
            {
                "school_id": self.school_id,
                "synthetic_run_id": self.synthetic_run_id,
                "class_group_id": self.class_group_id,
                "subject_id": self.subject_id,
                "course_id": self.course_id,
                "scheduled_for": self.scheduled_for,
                "purpose": self.purpose,
            }
        )
        if self.status == self.Status.FROZEN:
            self.context_hash = canonical_hash(self.context_snapshot)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.PLANNED:
            raise ValidationError("已冻结或取消的分析时间点不可删除。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.class_group}:{self.subject}:{self.scheduled_for:%Y-%m-%d %H:%M}"


class DecisionPointStudent(models.Model):
    class EligibilityStatus(models.TextChoices):
        ELIGIBLE = "eligible", "可纳入"
        INACTIVE = "inactive", "账号停用"
        NO_CLASS = "no_class", "未分班"
        EXCLUDED = "excluded", "不纳入"

    decision_point = models.ForeignKey(
        DecisionPoint, on_delete=models.PROTECT, related_name="student_scope"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analysis_decision_point_memberships",
    )
    eligibility_status = models.CharField(
        max_length=24,
        choices=EligibilityStatus.choices,
        default=EligibilityStatus.ELIGIBLE,
    )
    reason_code = models.CharField(max_length=64, blank=True)
    included = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["decision_point", "student"],
                name="uniq_decision_point_student",
            )
        ]
        indexes = [
            models.Index(fields=["decision_point", "included"]),
            models.Index(fields=["student", "created_at"]),
        ]
        ordering = ["decision_point_id", "student_id"]

    def clean(self) -> None:
        errors = {}
        if self.student_id:
            if self.student.role != self.student.Role.STUDENT:
                errors["student"] = "分析时间点只能登记学生。"
            if self.student.school_id != self.decision_point.school_id:
                errors["student"] = "学生与分析时间点学校不一致。"
        if self.included and self.eligibility_status != self.EligibilityStatus.ELIGIBLE:
            errors["included"] = "只有符合条件的学生可以纳入。"
        if not self.included and not self.reason_code:
            errors["reason_code"] = "未纳入学生必须记录原因。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("分析时间点学生范围不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("分析时间点学生范围不可直接删除。")


class StudentFeatureSnapshot(models.Model):
    class ViewType(models.TextChoices):
        OPERATIONAL = "operational_available", "当时可用数据"
        RECONSTRUCTED = "reconstructed_complete", "事后完整数据"

    class QualityStatus(models.TextChoices):
        READY = "ready", "可用"
        DEGRADED = "degraded", "部分可用"
        BLOCKED = "blocked", "不可用于分析"

    snapshot_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    decision_point = models.ForeignKey(
        DecisionPoint, on_delete=models.PROTECT, related_name="feature_snapshots"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analysis_feature_snapshots",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="analysis_feature_snapshots",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="analysis_feature_snapshots",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="analysis_feature_snapshots",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analysis_feature_snapshots",
    )
    feature_set = models.ForeignKey(
        FeatureSetVersion, on_delete=models.PROTECT, related_name="snapshots"
    )
    view_type = models.CharField(max_length=32, choices=ViewType.choices)
    as_of = models.DateTimeField()
    values = models.JSONField(default=dict)
    numerators = models.JSONField(default=dict)
    denominators = models.JSONField(default=dict)
    missing_codes = models.JSONField(default=dict)
    details = models.JSONField(default=dict, blank=True)
    window_starts = models.JSONField(default=dict)
    source_watermark = models.JSONField(default=dict)
    quality_status = models.CharField(max_length=16, choices=QualityStatus.choices)
    source_hash = models.CharField(max_length=64)
    generator_version = models.CharField(max_length=32)
    generated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["decision_point", "student", "view_type"],
                name="uniq_student_feature_snapshot_view",
            )
        ]
        indexes = [
            models.Index(fields=["school", "subject", "as_of"]),
            models.Index(fields=["class_group", "quality_status", "as_of"]),
            models.Index(fields=["student", "subject", "as_of"]),
        ]
        ordering = ["-as_of", "student_id", "view_type"]

    def clean(self) -> None:
        errors = {}
        if self.decision_point_id:
            point = self.decision_point
            pairs = (
                ("school_id", self.school_id, point.school_id),
                ("class_group_id", self.class_group_id, point.class_group_id),
                ("subject_id", self.subject_id, point.subject_id),
                ("course_id", self.course_id, point.course_id),
                ("feature_set_id", self.feature_set_id, point.feature_set_id),
            )
            for field, actual, expected in pairs:
                if actual != expected:
                    errors[field] = "特征快照与分析时间点范围不一致。"
            if self.as_of != point.scheduled_for:
                errors["as_of"] = "特征快照时间必须等于分析时间点。"
        if self.student_id:
            if self.student.role != self.student.Role.STUDENT:
                errors["student"] = "特征快照只能属于学生。"
            if self.student.school_id != self.school_id:
                errors["student"] = "学生与特征快照学校不一致。"
        for field_name in (
            "values",
            "numerators",
            "denominators",
            "missing_codes",
            "details",
            "window_starts",
            "source_watermark",
        ):
            if not isinstance(getattr(self, field_name), dict):
                errors[field_name] = "特征快照字段必须是 JSON 对象。"
        unknown_missing = set(self.missing_codes.values()) - MISSING_CODES
        if unknown_missing:
            errors["missing_codes"] = (
                f"包含未登记缺失原因：{', '.join(sorted(unknown_missing))}。"
            )
        if not re.fullmatch(r"^[0-9a-f]{64}$", self.source_hash or ""):
            errors["source_hash"] = "来源摘要必须是 64 位小写 SHA-256。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("已生成的特征快照不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("特征快照不可直接删除。")

    def __str__(self) -> str:
        return f"{self.student_id}:{self.subject_id}:{self.as_of}:{self.view_type}"


class OutcomeDefinition(models.Model):
    class OutcomeType(models.TextChoices):
        RATIO = "ratio", "比例"
        COUNT = "count", "数量"
        CONTINUOUS = "continuous", "连续值"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        RETIRED = "retired", "停用"

    outcome_key = models.CharField(max_length=96)
    version = models.CharField(max_length=16)
    label = models.CharField(max_length=128)
    description = models.CharField(max_length=500, blank=True)
    outcome_type = models.CharField(max_length=24, choices=OutcomeType.choices)
    horizon_days = models.PositiveSmallIntegerField()
    min_denominator = models.PositiveIntegerField(default=0)
    formula = models.TextField()
    eligibility_rule = models.TextField()
    allowed_evidence = models.JSONField(default=list)
    missing_codes = models.JSONField(default=list)
    generator_key = models.CharField(max_length=96)
    code_hash = models.CharField(max_length=64)
    definition_hash = models.CharField(max_length=64, editable=False)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["outcome_key", "version"],
                name="uniq_outcome_definition_version",
            )
        ]
        ordering = ["outcome_key", "version"]

    def semantic_definition(self) -> dict:
        return {
            "outcome_key": self.outcome_key,
            "version": self.version,
            "label": self.label,
            "description": self.description,
            "outcome_type": self.outcome_type,
            "horizon_days": self.horizon_days,
            "min_denominator": self.min_denominator,
            "formula": self.formula,
            "eligibility_rule": self.eligibility_rule,
            "allowed_evidence": self.allowed_evidence,
            "missing_codes": self.missing_codes,
            "generator_key": self.generator_key,
            "code_hash": self.code_hash,
        }

    def clean(self) -> None:
        errors = {}
        if not re.fullmatch(r"^[a-z][a-z0-9_]*$", self.outcome_key or ""):
            errors["outcome_key"] = "结果编号必须使用小写字母、数字和下划线。"
        if not VERSION_PATTERN.fullmatch(self.version or ""):
            errors["version"] = "版本必须使用 major.minor 格式。"
        if self.horizon_days < 1 or self.horizon_days > 365:
            errors["horizon_days"] = "未来观察天数必须为 1 至 365。"
        if not isinstance(self.allowed_evidence, list) or not self.allowed_evidence:
            errors["allowed_evidence"] = "至少登记一种结果材料。"
        if not isinstance(self.missing_codes, list) or not self.missing_codes:
            errors["missing_codes"] = "至少登记一个缺失原因。"
        elif unknown := set(self.missing_codes) - MISSING_CODES:
            errors["missing_codes"] = (
                f"包含未登记缺失原因：{', '.join(sorted(unknown))}。"
            )
        if not re.fullmatch(r"^[0-9a-f]{64}$", self.code_hash or ""):
            errors["code_hash"] = "计算代码摘要必须是 64 位小写 SHA-256。"
        if self.status == self.Status.ACTIVE and not self.activated_at:
            self.activated_at = timezone.now()
        if self.status == self.Status.RETIRED and not self.retired_at:
            self.retired_at = timezone.now()
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        self.definition_hash = canonical_hash(self.semantic_definition())
        if previous and previous.status in {self.Status.ACTIVE, self.Status.RETIRED}:
            if previous.definition_hash != self.definition_hash:
                raise ValidationError("已启用的未来结果定义不可修改，请登记新版本。")
        if previous and previous.status == self.Status.ACTIVE:
            if self.status not in {self.Status.ACTIVE, self.Status.RETIRED}:
                raise ValidationError("已启用的未来结果定义只能停用。")
        if previous and previous.status == self.Status.RETIRED:
            if self.status != self.Status.RETIRED:
                raise ValidationError("已停用的未来结果定义不能重新启用。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("已启用或停用的未来结果定义不可删除。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.outcome_key}@{self.version}"


class OutcomeObservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待观察"
        OBSERVED = "observed", "已观察"
        UNOBSERVED = "unobserved", "无可用结果"
        EXCLUDED = "excluded", "已排除"

    class EligibilityStatus(models.TextChoices):
        ELIGIBLE = "eligible", "符合条件"
        NOT_MATURE = "not_mature", "尚未到期"
        NO_OPPORTUNITY = "no_opportunity", "没有对应任务"
        INSUFFICIENT_N = "insufficient_n", "材料数量不足"
        COMPETING_EVENT = "competing_event", "存在转班等情况"
        DATA_ERROR = "data_error", "学习记录需检查"

    observation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    decision_point = models.ForeignKey(
        DecisionPoint, on_delete=models.PROTECT, related_name="outcome_observations"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analysis_outcome_observations",
    )
    outcome_definition = models.ForeignKey(
        OutcomeDefinition, on_delete=models.PROTECT, related_name="observations"
    )
    observation_version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    eligibility_status = models.CharField(
        max_length=24, choices=EligibilityStatus.choices
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    value = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    numerator = models.DecimalField(
        max_digits=16, decimal_places=6, null=True, blank=True
    )
    denominator = models.DecimalField(
        max_digits=16, decimal_places=6, null=True, blank=True
    )
    missing_code = models.CharField(max_length=32, blank=True)
    exclusion_reason = models.CharField(max_length=255, blank=True)
    evidence_refs = models.JSONField(default=list, blank=True)
    source_hash = models.CharField(max_length=64)
    frozen_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "decision_point",
                    "student",
                    "outcome_definition",
                    "observation_version",
                ],
                name="uniq_outcome_observation_version",
            )
        ]
        indexes = [
            models.Index(fields=["decision_point", "status"]),
            models.Index(fields=["outcome_definition", "window_end", "status"]),
            models.Index(fields=["student", "window_end"]),
        ]
        ordering = [
            "decision_point_id",
            "student_id",
            "outcome_definition_id",
            "observation_version",
        ]

    @property
    def is_final(self) -> bool:
        return self.status != self.Status.PENDING

    def clean(self) -> None:
        errors = {}
        if self.window_end <= self.window_start:
            errors["window_end"] = "未来结果窗口结束时间必须晚于开始时间。"
        if self.student_id:
            if self.student.role != self.student.Role.STUDENT:
                errors["student"] = "未来结果只能属于学生。"
            if self.student.school_id != self.decision_point.school_id:
                errors["student"] = "学生与分析时间点学校不一致。"
        if self.status == self.Status.OBSERVED:
            if self.value is None:
                errors["value"] = "已观察结果必须包含数值。"
            if self.missing_code:
                errors["missing_code"] = "已观察结果不能填写缺失原因。"
        elif self.status in {self.Status.UNOBSERVED, self.Status.EXCLUDED}:
            if self.value is not None:
                errors["value"] = "无可用结果或排除记录不能填写结果值。"
            if not self.missing_code:
                errors["missing_code"] = "无可用结果或排除记录必须填写原因。"
        if self.missing_code and self.missing_code not in MISSING_CODES:
            errors["missing_code"] = "未来结果缺失原因未登记。"
        if self.is_final and not self.frozen_at:
            errors["frozen_at"] = "最终未来结果必须记录冻结时间。"
        if self.status == self.Status.PENDING and self.frozen_at:
            errors["frozen_at"] = "等待观察的结果不能提前冻结。"
        if self.supersedes_id:
            previous = self.supersedes
            if previous.decision_point_id != self.decision_point_id:
                errors["supersedes"] = "被替代结果不属于同一分析时间点。"
            if previous.student_id != self.student_id:
                errors["supersedes"] = "被替代结果不属于同一学生。"
            if previous.outcome_definition_id != self.outcome_definition_id:
                errors["supersedes"] = "被替代结果定义不一致。"
            if previous.observation_version >= self.observation_version:
                errors["observation_version"] = "新结果版本必须晚于被替代版本。"
        elif self.observation_version != 1:
            errors["supersedes"] = "第二版及之后的结果必须引用上一版。"
        if not isinstance(self.evidence_refs, list):
            errors["evidence_refs"] = "结果材料引用必须是列表。"
        if not re.fullmatch(r"^[0-9a-f]{64}$", self.source_hash or ""):
            errors["source_hash"] = "来源摘要必须是 64 位小写 SHA-256。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("未来结果记录不可原地修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("未来结果记录不可直接删除。")


class TrainingDatasetVersion(models.Model):
    class Status(models.TextChoices):
        BUILDING = "building", "生成中"
        FROZEN = "frozen", "已冻结"
        FAILED = "failed", "生成失败"

    dataset_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    dataset_key = models.CharField(max_length=96, unique=True)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="training_dataset_versions",
    )
    synthetic_run = models.ForeignKey(
        "learning_analytics.SyntheticDatasetRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="training_dataset_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="training_dataset_versions",
    )
    feature_set = models.ForeignKey(
        FeatureSetVersion, on_delete=models.PROTECT, related_name="training_datasets"
    )
    outcome_definition = models.ForeignKey(
        OutcomeDefinition, on_delete=models.PROTECT, related_name="training_datasets"
    )
    view_type = models.CharField(
        max_length=32,
        choices=StudentFeatureSnapshot.ViewType.choices,
        default=StudentFeatureSnapshot.ViewType.OPERATIONAL,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.BUILDING
    )
    decision_start = models.DateTimeField()
    decision_end = models.DateTimeField()
    split_strategy = models.CharField(max_length=64)
    generator_version = models.CharField(max_length=32)
    manifest = models.JSONField(default=dict)
    manifest_hash = models.CharField(max_length=64, blank=True)
    source_hash = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField(default=0)
    observed_count = models.PositiveIntegerField(default=0)
    unobserved_count = models.PositiveIntegerField(default=0)
    excluded_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_training_dataset_versions",
    )
    frozen_at = models.DateTimeField(null=True, blank=True)
    error_message = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "subject", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "训练数据学科与学校不一致。"
        if self.synthetic_run_id and self.synthetic_run.school_id != self.school_id:
            errors["synthetic_run"] = "模拟数据批次与训练数据学校不一致。"
        if self.view_type != StudentFeatureSnapshot.ViewType.OPERATIONAL:
            errors["view_type"] = "训练数据只能使用当时可用数据视图。"
        if self.decision_end < self.decision_start:
            errors["decision_end"] = "结束时间不能早于开始时间。"
        if self.status == self.Status.FROZEN:
            if not self.frozen_at:
                errors["frozen_at"] = "冻结数据版本必须记录冻结时间。"
            if not self.manifest_hash:
                errors["manifest_hash"] = "冻结数据版本必须包含清单摘要。"
        if not isinstance(self.manifest, dict):
            errors["manifest"] = "数据版本清单必须是 JSON 对象。"
        if not re.fullmatch(r"^[0-9a-f]{64}$", self.source_hash or ""):
            errors["source_hash"] = "来源摘要必须是 64 位小写 SHA-256。"
        if self.manifest_hash and not re.fullmatch(
            r"^[0-9a-f]{64}$", self.manifest_hash
        ):
            errors["manifest_hash"] = "清单摘要必须是 64 位小写 SHA-256。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous and previous.status in {self.Status.FROZEN, self.Status.FAILED}:
            raise ValidationError("已冻结或失败的数据版本不可修改。")
        if self.status == self.Status.FROZEN and not self.manifest_hash:
            self.manifest_hash = canonical_hash(self.manifest)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.BUILDING:
            raise ValidationError("已冻结或失败的数据版本不可删除。")
        return super().delete(*args, **kwargs)


class TrainingDatasetRow(models.Model):
    class Split(models.TextChoices):
        TRAIN = "train", "训练"
        VALIDATION = "validation", "验证"
        TEST = "test", "测试"
        UNASSIGNED = "unassigned", "未分配"

    dataset = models.ForeignKey(
        TrainingDatasetVersion, on_delete=models.PROTECT, related_name="rows"
    )
    decision_point = models.ForeignKey(
        DecisionPoint, on_delete=models.PROTECT, related_name="training_dataset_rows"
    )
    snapshot = models.ForeignKey(
        StudentFeatureSnapshot,
        on_delete=models.PROTECT,
        related_name="training_dataset_rows",
    )
    outcome_observation = models.ForeignKey(
        OutcomeObservation,
        on_delete=models.PROTECT,
        related_name="training_dataset_rows",
    )
    pseudonymous_key = models.CharField(max_length=64)
    split = models.CharField(max_length=16, choices=Split.choices)
    split_group_key = models.CharField(max_length=96)
    split_assignments = models.JSONField(default=dict)
    feature_values = models.JSONField(default=dict)
    feature_numerators = models.JSONField(default=dict)
    feature_denominators = models.JSONField(default=dict)
    feature_missing_codes = models.JSONField(default=dict)
    outcome_status = models.CharField(max_length=16)
    outcome_value = models.DecimalField(
        max_digits=16, decimal_places=6, null=True, blank=True
    )
    outcome_numerator = models.DecimalField(
        max_digits=16, decimal_places=6, null=True, blank=True
    )
    outcome_denominator = models.DecimalField(
        max_digits=16, decimal_places=6, null=True, blank=True
    )
    outcome_missing_code = models.CharField(max_length=32, blank=True)
    row_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "snapshot", "outcome_observation"],
                name="uniq_training_dataset_snapshot_outcome",
            ),
            models.UniqueConstraint(
                fields=["dataset", "pseudonymous_key", "decision_point"],
                name="uniq_training_dataset_pseudonym_point",
            ),
        ]
        indexes = [
            models.Index(fields=["dataset", "split"]),
            models.Index(fields=["decision_point", "split"]),
        ]
        ordering = ["dataset_id", "decision_point_id", "pseudonymous_key"]

    def clean(self) -> None:
        errors = {}
        if self.dataset_id:
            if self.dataset.status != TrainingDatasetVersion.Status.BUILDING:
                errors["dataset"] = "只能向生成中的数据版本写入记录。"
            if self.snapshot.feature_set_id != self.dataset.feature_set_id:
                errors["snapshot"] = "特征快照版本与数据版本不一致。"
            if (
                self.outcome_observation.outcome_definition_id
                != self.dataset.outcome_definition_id
            ):
                errors["outcome_observation"] = "未来结果定义与数据版本不一致。"
        if (
            self.snapshot_id
            and self.snapshot.decision_point_id != self.decision_point_id
        ):
            errors["snapshot"] = "特征快照与分析时间点不一致。"
        if (
            self.outcome_observation_id
            and self.outcome_observation.decision_point_id != self.decision_point_id
        ):
            errors["outcome_observation"] = "未来结果与分析时间点不一致。"
        if self.snapshot_id and self.outcome_observation_id:
            if self.snapshot.student_id != self.outcome_observation.student_id:
                errors["outcome_observation"] = "特征快照与未来结果不属于同一学生。"
        for field_name in (
            "feature_values",
            "feature_numerators",
            "feature_denominators",
            "feature_missing_codes",
            "split_assignments",
        ):
            if not isinstance(getattr(self, field_name), dict):
                errors[field_name] = "训练数据字段必须是 JSON 对象。"
        if not re.fullmatch(r"^[0-9a-f]{64}$", self.pseudonymous_key or ""):
            errors["pseudonymous_key"] = "内部匿名编号必须是 64 位小写 SHA-256。"
        if not re.fullmatch(r"^[0-9a-f]{64}$", self.row_hash or ""):
            errors["row_hash"] = "行摘要必须是 64 位小写 SHA-256。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("训练数据记录不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("训练数据记录不可直接删除。")
