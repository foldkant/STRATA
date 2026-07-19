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


class EvaluationTrialType(models.TextChoices):
    CONTENT_REVIEW = "content_review", "内容审核"
    CLASSROOM_TRIAL = "classroom_trial", "课堂试用"
    SCORER_TRAINING = "scorer_training", "评分培训"
    SCORING_CHECK = "scoring_check", "评分一致性检查"


class EvaluationTrialStatus(models.TextChoices):
    PLANNED = "planned", "待进行"
    IN_PROGRESS = "in_progress", "进行中"
    COMPLETED = "completed", "已完成"


class EvaluationTrialConclusion(models.TextChoices):
    PENDING = "pending", "待确认"
    READY = "ready", "可使用"
    REVISE = "revise", "需要修改"
    HOLD = "hold", "暂不使用"


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


class EvaluationTrialRecord(models.Model):
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="evaluation_trial_records",
    )
    standard_version = models.ForeignKey(
        EvaluationStandardVersion,
        on_delete=models.PROTECT,
        related_name="trial_records",
    )
    record_type = models.CharField(max_length=32, choices=EvaluationTrialType.choices)
    title = models.CharField(max_length=160)
    status = models.CharField(
        max_length=24,
        choices=EvaluationTrialStatus.choices,
        default=EvaluationTrialStatus.PLANNED,
    )
    activity_date = models.DateField()
    participant_count = models.PositiveIntegerField(default=0)
    agreement_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    conclusion = models.CharField(
        max_length=24,
        choices=EvaluationTrialConclusion.choices,
        default=EvaluationTrialConclusion.PENDING,
    )
    summary = models.TextField(blank=True)
    issues = models.JSONField(default=list, blank=True)
    action_items = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_evaluation_trial_records",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_evaluation_trial_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "activity_date"]),
            models.Index(fields=["school", "record_type", "status"]),
            models.Index(fields=["standard_version", "activity_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(agreement_rate__isnull=True)
                    | (
                        models.Q(agreement_rate__gte=0)
                        & models.Q(agreement_rate__lte=100)
                    )
                ),
                name="evaluation_trial_agreement_rate_0_100",
            )
        ]
        ordering = ["-activity_date", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.standard_version_id and self.standard_version.school_id != self.school_id:
            errors["standard_version"] = "评价标准版本与试用记录不属于同一学校。"
        if self.created_by_id and self.created_by.school_id != self.school_id:
            errors["created_by"] = "创建人与试用记录不属于同一学校。"
        if self.updated_by_id and self.updated_by.school_id != self.school_id:
            errors["updated_by"] = "更新人与试用记录不属于同一学校。"
        if not isinstance(self.issues, list):
            errors["issues"] = "发现的问题必须是列表。"
        if not isinstance(self.action_items, list):
            errors["action_items"] = "后续处理必须是列表。"
        if self.record_type != EvaluationTrialType.SCORING_CHECK and self.agreement_rate is not None:
            errors["agreement_rate"] = "只有评分一致性检查可以填写一致率。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_record_type_display()}:{self.title}"


class LessonStepEvaluationBinding(models.Model):
    lesson_step = models.OneToOneField(
        "courses.LessonStep",
        on_delete=models.CASCADE,
        related_name="evaluation_standard_binding",
    )
    standard_version = models.ForeignKey(
        EvaluationStandardVersion,
        on_delete=models.PROTECT,
        related_name="lesson_step_bindings",
    )
    enable_self = models.BooleanField(default=False)
    enable_peer = models.BooleanField(default=False)
    enable_teacher = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_lesson_step_evaluation_bindings",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_lesson_step_evaluation_bindings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["standard_version", "updated_at"]),
        ]
        ordering = ["lesson_step_id"]

    def clean(self) -> None:
        errors = {}
        if not (self.enable_self or self.enable_peer or self.enable_teacher):
            errors["enable_teacher"] = "至少启用一种评价方式。"
        if self.lesson_step_id and self.standard_version_id:
            course_id = self.lesson_step.lesson.course_id
            if self.standard_version.course_id != course_id:
                errors["standard_version"] = "评价标准版本与课时环节不属于同一课程。"
            teacher_id = self.lesson_step.lesson.course.teacher_id
            if self.created_by_id and self.created_by_id != teacher_id:
                errors["created_by"] = "只有课程教师可以创建课时评价绑定。"
            if self.updated_by_id and self.updated_by_id != teacher_id:
                errors["updated_by"] = "只有课程教师可以修改课时评价绑定。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self).objects.filter(pk=self.pk).first()
            if persisted and persisted.classroom_uses.exists():
                protected_fields = (
                    "lesson_step_id",
                    "standard_version_id",
                    "enable_self",
                    "enable_peer",
                    "enable_teacher",
                )
                if any(
                    getattr(persisted, field) != getattr(self, field)
                    for field in protected_fields
                ):
                    raise ValidationError("已用于课堂的课时评价绑定不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.classroom_uses.exists():
            raise ValidationError("已用于课堂的课时评价绑定不可删除。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"step:{self.lesson_step_id}:standard:{self.standard_version_id}"


class ClassroomEvaluationStandardUse(models.Model):
    session = models.OneToOneField(
        "courses.ClassroomSession",
        on_delete=models.PROTECT,
        related_name="evaluation_standard_use",
    )
    binding = models.ForeignKey(
        LessonStepEvaluationBinding,
        on_delete=models.PROTECT,
        related_name="classroom_uses",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.PROTECT,
        related_name="classroom_evaluation_uses",
    )
    standard_version = models.ForeignKey(
        EvaluationStandardVersion,
        on_delete=models.PROTECT,
        related_name="classroom_uses",
    )
    evaluation_config_version = models.ForeignKey(
        "courses.ClassroomEvaluationConfigVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="standard_uses",
    )
    criteria_snapshot = models.JSONField(default=list)
    configuration_snapshot = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, db_index=True, default="")
    enable_self = models.BooleanField(default=False)
    enable_peer = models.BooleanField(default=False)
    enable_teacher = models.BooleanField(default=True)
    legacy_compatible = models.BooleanField(default=False, editable=False)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="opened_classroom_evaluation_standard_uses",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["standard_version", "created_at"]),
            models.Index(fields=["lesson_step", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.session_id and self.lesson_step_id:
            if self.session.current_step_id != self.lesson_step_id:
                errors["lesson_step"] = "课堂当前环节与评价标准使用记录不一致。"
            if self.session.lesson_id != self.lesson_step.lesson_id:
                errors["lesson_step"] = "评价环节不属于当前课堂课时。"
        if self.binding_id:
            if self.binding.lesson_step_id != self.lesson_step_id:
                errors["binding"] = "课时评价绑定与课堂环节不一致。"
            if self.binding.standard_version_id != self.standard_version_id:
                errors["standard_version"] = "课堂使用版本与课时绑定版本不一致。"
        if self.evaluation_config_version_id and self.standard_version_id:
            if self.evaluation_config_version.course_id != self.standard_version.course_id:
                errors["evaluation_config_version"] = "课堂评价快照与评价标准不属于同一课程。"
        if self.opened_by_id and self.session_id and self.opened_by_id != self.session.teacher_id:
            errors["opened_by"] = "只有课堂教师可以开启评价标准。"
        if not isinstance(self.criteria_snapshot, list):
            errors["criteria_snapshot"] = "评价指标快照必须是列表。"
        if not isinstance(self.configuration_snapshot, dict):
            errors["configuration_snapshot"] = "课堂评价配置快照必须是对象。"
        if not (self.enable_self or self.enable_peer or self.enable_teacher):
            errors["enable_teacher"] = "课堂评价至少需要一种评价方式。"
        if self.content_hash and len(self.content_hash) != 64:
            errors["content_hash"] = "课堂评价快照校验码格式不正确。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("课堂评价标准使用记录不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("课堂评价标准使用记录不可删除。")

    def __str__(self) -> str:
        return f"session:{self.session_id}:standard:{self.standard_version_id}"

    @property
    def course_id(self):
        return self.standard_version.course_id

    @property
    def version_no(self):
        return self.standard_version.version_no

    @property
    def config_hash(self):
        return self.content_hash

    @property
    def self_criteria(self):
        return self.configuration_snapshot.get("self_criteria", [])

    @property
    def peer_criteria(self):
        return self.configuration_snapshot.get("peer_criteria", [])

    @property
    def teacher_criteria(self):
        return self.configuration_snapshot.get("teacher_criteria", [])

    @property
    def standard_title(self):
        return self.standard_version.title

    @property
    def frozen(self):
        return True

    @property
    def opened_at(self):
        return self.created_at


class EvaluationSubmissionEvidence(models.Model):
    submission = models.OneToOneField(
        "courses.ClassroomEvaluationSubmission",
        on_delete=models.PROTECT,
        related_name="standard_evidence",
    )
    standard_use = models.ForeignKey(
        ClassroomEvaluationStandardUse,
        on_delete=models.PROTECT,
        related_name="submission_evidence",
    )
    lesson_step_attempt = models.ForeignKey(
        "learning.LessonStepAttempt",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluation_evidence",
    )
    student_work_attachment = models.ForeignKey(
        "learning.StudentWorkAttachment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluation_evidence",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["standard_use", "created_at"]),
            models.Index(fields=["lesson_step_attempt", "created_at"]),
            models.Index(fields=["student_work_attachment", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.submission_id and not self.submission.session_id:
            errors["submission"] = "正式评价证据必须属于一次课堂。"
        if self.submission_id and self.standard_use_id:
            if self.submission.session_id != self.standard_use.session_id:
                errors["standard_use"] = "评价提交与课堂评价标准使用记录不一致。"
        if self.lesson_step_attempt_id and self.standard_use_id:
            attempt = self.lesson_step_attempt
            if attempt.classroom_session_id != self.standard_use.session_id:
                errors["lesson_step_attempt"] = "学生作答不属于当前课堂。"
            if attempt.lesson_step_id != self.standard_use.lesson_step_id:
                errors["lesson_step_attempt"] = "学生作答不属于当前评价环节。"
            if self.submission_id and attempt.student_id != self.submission.target_id:
                errors["lesson_step_attempt"] = "学生作答与被评价学生不一致。"
        if self.student_work_attachment_id and self.standard_use_id:
            work = self.student_work_attachment
            if work.classroom_session_id != self.standard_use.session_id:
                errors["student_work_attachment"] = "学生作品不属于当前课堂。"
            if work.lesson_step_id != self.standard_use.lesson_step_id:
                errors["student_work_attachment"] = "学生作品不属于当前评价环节。"
            if self.submission_id and work.student_id != self.submission.target_id:
                errors["student_work_attachment"] = "学生作品与被评价学生不一致。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("评价证据关系不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("评价证据关系不可删除。")

    def __str__(self) -> str:
        return f"submission:{self.submission_id}:use:{self.standard_use_id}"
