from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def canonical_content_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EvaluationScope(models.TextChoices):
    COURSE = "course", "课程使用"
    SCHOOL = "school", "校级通用"
    ANALYSIS = "analysis", "专项分析"


class EvaluationReviewStatus(models.TextChoices):
    DRAFT = "draft", "编辑中"
    REVIEW_PENDING = "review_pending", "待审核"
    REVIEWED = "reviewed", "已审核"
    TRIAL_SCHEDULED = "trial_scheduled", "待试用"
    TRIAL_COMPLETED = "trial_completed", "试用完成"
    APPROVED = "approved", "已启用"


class EvaluationDimension(models.TextChoices):
    TASK_QUALITY = "task_quality", "任务完成质量"
    LEARNING_METHOD = "learning_method", "学习方法"
    SELF_MANAGEMENT = "self_management", "自我管理"
    COLLABORATION = "collaboration", "合作与反馈"
    SUBJECT_PRACTICE = "subject_practice", "学科实践"
    RESPONSIBILITY = "responsibility", "规范与责任"


class EvaluationPlan(models.Model):
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="evaluation_plans",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="evaluation_plans",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluation_plans",
    )
    title = models.CharField(max_length=160)
    scope = models.CharField(
        max_length=32,
        choices=EvaluationScope.choices,
        default=EvaluationScope.COURSE,
    )
    content_version = models.CharField(max_length=64, blank=True)
    target_students = models.CharField(max_length=300, blank=True)
    learning_goal = models.TextField(blank=True)
    learning_goals = models.JSONField(default=list, blank=True)
    evaluation_basis = models.JSONField(default=list, blank=True)
    learning_tasks = models.JSONField(default=list, blank=True)
    content_scope = models.JSONField(default=list, blank=True)
    thinking_requirements = models.JSONField(default=list, blank=True)
    support_options = models.JSONField(default=list, blank=True)
    scoring_rules = models.JSONField(default=dict, blank=True)
    follow_up_suggestion = models.TextField(blank=True)
    review_status = models.CharField(
        max_length=32,
        choices=EvaluationReviewStatus.choices,
        default=EvaluationReviewStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_evaluation_plans",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_evaluation_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "subject", "updated_at"]),
            models.Index(fields=["created_by", "updated_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与评价方案不属于同一学校。"
        if self.course_id:
            if self.course.teacher.school_id != self.school_id:
                errors["course"] = "课程与评价方案不属于同一学校。"
            if self.course.subject_id != self.subject_id:
                errors["course"] = "课程与评价方案的学科不一致。"
        if self.created_by_id and self.created_by.school_id != self.school_id:
            errors["created_by"] = "创建人与评价方案不属于同一学校。"
        if self.updated_by_id and self.updated_by.school_id != self.school_id:
            errors["updated_by"] = "更新人与评价方案不属于同一学校。"
        for field_name in (
            "learning_goals",
            "evaluation_basis",
            "learning_tasks",
            "content_scope",
            "thinking_requirements",
            "support_options",
        ):
            if not isinstance(getattr(self, field_name), list):
                errors[field_name] = "必须是 JSON 列表。"
        if not isinstance(self.scoring_rules, dict):
            errors["scoring_rules"] = "评分规则必须是 JSON 对象。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class ImmutableEvaluationVersion(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("已发布版本不能直接修改，请生成新版本。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已发布版本不能删除。")


class EvaluationPlanVersion(ImmutableEvaluationVersion):
    source = models.ForeignKey(
        EvaluationPlan,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="evaluation_plan_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="evaluation_plan_versions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluation_plan_versions",
    )
    version_no = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64, editable=False)
    title = models.CharField(max_length=160)
    scope = models.CharField(max_length=32, choices=EvaluationScope.choices)
    content_version = models.CharField(max_length=64)
    target_students = models.CharField(max_length=300)
    learning_goal = models.TextField()
    learning_goals = models.JSONField(default=list)
    evaluation_basis = models.JSONField(default=list)
    learning_tasks = models.JSONField(default=list)
    content_scope = models.JSONField(default=list)
    thinking_requirements = models.JSONField(default=list)
    support_options = models.JSONField(default=list, blank=True)
    scoring_rules = models.JSONField(default=dict)
    follow_up_suggestion = models.TextField()
    review_status = models.CharField(
        max_length=32,
        choices=EvaluationReviewStatus.choices,
        default=EvaluationReviewStatus.DRAFT,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_evaluation_plan_versions",
    )
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "version_no"],
                name="uniq_evaluation_plan_version_no",
            ),
            models.UniqueConstraint(
                fields=["source", "content_hash"],
                name="uniq_evaluation_plan_content_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "published_at"]),
            models.Index(fields=["scope", "review_status"]),
        ]
        ordering = ["source_id", "-version_no"]

    def clean(self) -> None:
        errors = {}
        if self.source_id:
            for field_name in ("school_id", "subject_id", "course_id"):
                if getattr(self, field_name) != getattr(self.source, field_name):
                    errors[field_name.removesuffix("_id")] = "发布版本与评价方案范围不一致。"
        if self.published_by_id and self.published_by.school_id != self.school_id:
            errors["published_by"] = "发布人与评价方案不属于同一学校。"
        if errors:
            raise ValidationError(errors)

    def semantic_content(self) -> dict:
        return {
            "school_id": self.school_id,
            "subject_id": self.subject_id,
            "course_id": self.course_id,
            "title": self.title,
            "scope": self.scope,
            "content_version": self.content_version,
            "target_students": self.target_students,
            "learning_goal": self.learning_goal,
            "learning_goals": self.learning_goals,
            "evaluation_basis": self.evaluation_basis,
            "learning_tasks": self.learning_tasks,
            "content_scope": self.content_scope,
            "thinking_requirements": self.thinking_requirements,
            "support_options": self.support_options,
            "scoring_rules": self.scoring_rules,
            "follow_up_suggestion": self.follow_up_suggestion,
            "review_status": self.review_status,
        }

    def __str__(self) -> str:
        return f"{self.title}@{self.version_no}"


class EvaluationStandard(models.Model):
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="evaluation_standards",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="evaluation_standards",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluation_standards",
    )
    plan = models.ForeignKey(
        EvaluationPlan,
        on_delete=models.PROTECT,
        related_name="evaluation_standards",
    )
    title = models.CharField(max_length=160)
    scope = models.CharField(
        max_length=32,
        choices=EvaluationScope.choices,
        default=EvaluationScope.COURSE,
    )
    evaluation_target = models.CharField(max_length=300, blank=True)
    criteria = models.JSONField(default=list, blank=True)
    review_status = models.CharField(
        max_length=32,
        choices=EvaluationReviewStatus.choices,
        default=EvaluationReviewStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_evaluation_standards",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_evaluation_standards",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "subject", "updated_at"]),
            models.Index(fields=["created_by", "updated_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.plan_id:
            expected = {
                "school": self.plan.school_id,
                "subject": self.plan.subject_id,
                "course": self.plan.course_id,
            }
            for field_name, value in expected.items():
                if getattr(self, f"{field_name}_id") != value:
                    errors[field_name] = "评价标准与评价方案范围不一致。"
        if self.created_by_id and self.created_by.school_id != self.school_id:
            errors["created_by"] = "创建人与评价标准不属于同一学校。"
        if self.updated_by_id and self.updated_by.school_id != self.school_id:
            errors["updated_by"] = "更新人与评价标准不属于同一学校。"
        if not isinstance(self.criteria, list):
            errors["criteria"] = "评价指标必须是 JSON 列表。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class EvaluationStandardVersion(ImmutableEvaluationVersion):
    source = models.ForeignKey(
        EvaluationStandard,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    plan_version = models.ForeignKey(
        EvaluationPlanVersion,
        on_delete=models.PROTECT,
        related_name="evaluation_standard_versions",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="evaluation_standard_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="evaluation_standard_versions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluation_standard_versions",
    )
    version_no = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64, editable=False)
    title = models.CharField(max_length=160)
    scope = models.CharField(max_length=32, choices=EvaluationScope.choices)
    evaluation_target = models.CharField(max_length=300)
    review_status = models.CharField(
        max_length=32,
        choices=EvaluationReviewStatus.choices,
        default=EvaluationReviewStatus.DRAFT,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_evaluation_standard_versions",
    )
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "version_no"],
                name="uniq_evaluation_standard_version_no",
            ),
            models.UniqueConstraint(
                fields=["source", "content_hash"],
                name="uniq_evaluation_standard_content_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "published_at"]),
            models.Index(fields=["scope", "review_status"]),
        ]
        ordering = ["source_id", "-version_no"]

    def clean(self) -> None:
        errors = {}
        if self.source_id:
            for field_name in ("school_id", "subject_id", "course_id"):
                if getattr(self, field_name) != getattr(self.source, field_name):
                    errors[field_name.removesuffix("_id")] = "发布版本与评价标准范围不一致。"
        if self.plan_version_id:
            if self.plan_version.source_id != self.source.plan_id:
                errors["plan_version"] = "评价标准未绑定对应的评价方案版本。"
            if self.plan_version.school_id != self.school_id:
                errors["plan_version"] = "评价方案与评价标准不属于同一学校。"
        if self.published_by_id and self.published_by.school_id != self.school_id:
            errors["published_by"] = "发布人与评价标准不属于同一学校。"
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.title}@{self.version_no}"


class EvaluationCriterionVersion(ImmutableEvaluationVersion):
    standard_version = models.ForeignKey(
        EvaluationStandardVersion,
        on_delete=models.PROTECT,
        related_name="criteria",
    )
    code = models.CharField(max_length=32)
    dimension = models.CharField(max_length=32, choices=EvaluationDimension.choices)
    title = models.CharField(max_length=160)
    evaluation_target = models.CharField(max_length=300)
    evaluation_sources = models.JSONField(default=list)
    expected_performance = models.TextField()
    skip_condition = models.TextField()
    support_options = models.JSONField(default=list, blank=True)
    common_problems = models.JSONField(default=list)
    level_1_description = models.TextField()
    level_2_description = models.TextField()
    level_3_description = models.TextField()
    level_4_description = models.TextField()
    level_5_description = models.TextField()
    follow_up_suggestion = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["standard_version", "code"],
                name="uniq_evaluation_criterion_code",
            ),
            models.UniqueConstraint(
                fields=["standard_version", "sort_order"],
                name="uniq_evaluation_criterion_order",
            ),
        ]
        ordering = ["sort_order", "id"]

    def clean(self) -> None:
        errors = {}
        for field_name in ("evaluation_sources", "support_options", "common_problems"):
            if not isinstance(getattr(self, field_name), list):
                errors[field_name] = "必须是 JSON 列表。"
        if errors:
            raise ValidationError(errors)

    @property
    def level_descriptions(self) -> list[str]:
        return [
            self.level_1_description,
            self.level_2_description,
            self.level_3_description,
            self.level_4_description,
            self.level_5_description,
        ]

    def __str__(self) -> str:
        return f"{self.standard_version_id}:{self.code}"


class EvaluationScoringExample(ImmutableEvaluationVersion):
    criterion = models.ForeignKey(
        EvaluationCriterionVersion,
        on_delete=models.PROTECT,
        related_name="scoring_examples",
    )
    level = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=160)
    example_description = models.TextField()
    file_reference = models.CharField(max_length=500, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__gte=1) & models.Q(level__lte=5),
                name="evaluation_scoring_example_level_1_5",
            ),
            models.UniqueConstraint(
                fields=["criterion", "sort_order"],
                name="uniq_evaluation_scoring_example_order",
            ),
        ]
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.criterion_id}:L{self.level}:{self.title}"
