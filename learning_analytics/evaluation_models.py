from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def canonical_content_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value or "") == 64 and all(char in "0123456789abcdef" for char in value)


class EvaluationScope(models.TextChoices):
    COURSE = "course", "课程使用"
    SCHOOL = "school", "校级通用"
    ANALYSIS = "analysis", "专项分析"


class EvaluationReviewStatus(models.TextChoices):
    DRAFT = "draft", "编辑中"
    REVIEWED = "reviewed", "教师已完成复核"
    LEGACY_UNVERIFIED = "legacy_unverified", "历史版本待复核"


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


class EvaluationMode(models.TextChoices):
    TEST = "test", "测试式评价"
    OPERATION = "operation", "操作式评价"
    PROJECT = "project", "项目式评价"
    ARTIFACT = "artifact", "作品评价"
    ORAL_DEFENSE = "oral_defense", "答辩评价"
    MIXED = "mixed", "混合评价"


class EvidenceOwnership(models.TextChoices):
    INDIVIDUAL = "individual", "个人评价材料"
    GROUP = "group", "小组评价材料"
    BOTH = "both", "个人与小组评价材料"


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
    learning_activities = models.JSONField(default=list, blank=True)
    learning_tasks = models.JSONField(default=list, blank=True)
    evaluation_tasks = models.JSONField(default=list, blank=True)
    assessment_modes = models.JSONField(default=list, blank=True)
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
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_evaluation_plans",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_content_hash = models.CharField(max_length=64, blank=True)
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
            "learning_activities",
            "learning_tasks",
            "evaluation_tasks",
            "assessment_modes",
            "content_scope",
            "thinking_requirements",
            "support_options",
        ):
            if not isinstance(getattr(self, field_name), list):
                errors[field_name] = "必须是 JSON 列表。"
        if not isinstance(self.scoring_rules, dict):
            errors["scoring_rules"] = "评分规则必须是 JSON 对象。"
        audit_values = (
            self.reviewed_by_id,
            self.reviewed_at,
            self.reviewed_content_hash,
        )
        if self.review_status == EvaluationReviewStatus.REVIEWED:
            if not all(audit_values):
                errors["review_status"] = "教师完成复核时必须保留复核人、时间和内容哈希。"
            elif not _is_sha256(self.reviewed_content_hash):
                errors["reviewed_content_hash"] = "复核内容哈希格式不正确。"
            if self.course_id and self.reviewed_by_id != self.course.teacher_id:
                errors["reviewed_by"] = "评价方案必须由该课程教师完成专业复核。"
        elif any(audit_values):
            errors["review_status"] = "编辑中方案不能保留教师复核审计。"
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
    learning_activities = models.JSONField(default=list)
    # Legacy compatibility snapshot. New versions use learning_activities and
    # evaluation_tasks; an intentionally empty legacy list must remain valid.
    learning_tasks = models.JSONField(default=list, blank=True)
    evaluation_tasks = models.JSONField(default=list)
    assessment_modes = models.JSONField(default=list)
    content_scope = models.JSONField(default=list)
    thinking_requirements = models.JSONField(default=list)
    support_options = models.JSONField(default=list, blank=True)
    scoring_rules = models.JSONField(default=dict)
    follow_up_suggestion = models.TextField()
    review_status = models.CharField(
        max_length=32,
        choices=EvaluationReviewStatus.choices,
        default=EvaluationReviewStatus.LEGACY_UNVERIFIED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_evaluation_plan_versions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_content_hash = models.CharField(max_length=64, blank=True)
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
        if self.review_status == EvaluationReviewStatus.REVIEWED:
            if not self.reviewed_by_id or not self.reviewed_at:
                errors["review_status"] = "已复核方案版本缺少教师复核审计。"
            if self.reviewed_content_hash != self.content_hash:
                errors["reviewed_content_hash"] = "方案版本内容与教师复核内容不一致。"
            if self.course_id and self.reviewed_by_id != self.course.teacher_id:
                errors["reviewed_by"] = "方案版本复核人必须是该课程教师。"
        elif any((self.reviewed_by_id, self.reviewed_at, self.reviewed_content_hash)):
            errors["review_status"] = "历史待复核版本不能保留教师复核审计。"
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
            "learning_activities": self.learning_activities,
            "learning_tasks": self.learning_tasks,
            "evaluation_tasks": self.evaluation_tasks,
            "assessment_modes": self.assessment_modes,
            "content_scope": self.content_scope,
            "thinking_requirements": self.thinking_requirements,
            "support_options": self.support_options,
            "scoring_rules": self.scoring_rules,
            "follow_up_suggestion": self.follow_up_suggestion,
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
    plan_version = models.ForeignKey(
        EvaluationPlanVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="draft_evaluation_standards",
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
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_evaluation_standards",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_content_hash = models.CharField(max_length=64, blank=True)
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
        if self.plan_version_id:
            if not self.plan_id or self.plan_version.source_id != self.plan_id:
                errors["plan_version"] = "评价标准必须绑定所属评价方案的明确版本。"
            elif self.plan_version.course_id != self.course_id:
                errors["plan_version"] = "评价方案版本与评价标准课程范围不一致。"
        if self.created_by_id and self.created_by.school_id != self.school_id:
            errors["created_by"] = "创建人与评价标准不属于同一学校。"
        if self.updated_by_id and self.updated_by.school_id != self.school_id:
            errors["updated_by"] = "更新人与评价标准不属于同一学校。"
        if not isinstance(self.criteria, list):
            errors["criteria"] = "评价指标必须是 JSON 列表。"
        audit_values = (
            self.reviewed_by_id,
            self.reviewed_at,
            self.reviewed_content_hash,
        )
        if self.review_status == EvaluationReviewStatus.REVIEWED:
            if not all(audit_values):
                errors["review_status"] = "教师完成复核时必须保留复核人、时间和内容哈希。"
            elif not _is_sha256(self.reviewed_content_hash):
                errors["reviewed_content_hash"] = "复核内容哈希格式不正确。"
            if self.course_id and self.reviewed_by_id != self.course.teacher_id:
                errors["reviewed_by"] = "评价标准必须由该课程教师完成专业复核。"
        elif any(audit_values):
            errors["review_status"] = "编辑中评价标准不能保留教师复核审计。"
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
        default=EvaluationReviewStatus.LEGACY_UNVERIFIED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_evaluation_standard_versions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_content_hash = models.CharField(max_length=64, blank=True)
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
        if self.review_status == EvaluationReviewStatus.REVIEWED:
            if not self.reviewed_by_id or not self.reviewed_at:
                errors["review_status"] = "已复核评价标准版本缺少教师复核审计。"
            if self.reviewed_content_hash != self.content_hash:
                errors["reviewed_content_hash"] = "评价标准版本内容与教师复核内容不一致。"
            if self.course_id and self.reviewed_by_id != self.course.teacher_id:
                errors["reviewed_by"] = "评价标准版本复核人必须是该课程教师。"
            plan_version = self.plan_version
            if (
                plan_version.review_status != EvaluationReviewStatus.REVIEWED
                or not plan_version.reviewed_by_id
                or not plan_version.reviewed_at
                or plan_version.reviewed_content_hash != plan_version.content_hash
            ):
                errors["plan_version"] = "评价标准版本所绑定方案版本尚未完成教师复核。"
        elif any((self.reviewed_by_id, self.reviewed_at, self.reviewed_content_hash)):
            errors["review_status"] = "历史待复核版本不能保留教师复核审计。"
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
    learning_goal_codes = models.JSONField(default=list, blank=True)
    evaluation_task_codes = models.JSONField(default=list, blank=True)
    evidence_ownership = models.CharField(
        max_length=16,
        choices=EvidenceOwnership.choices,
        default=EvidenceOwnership.INDIVIDUAL,
    )
    material_types = models.JSONField(default=list, blank=True)
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
        for field_name in (
            "evaluation_sources",
            "learning_goal_codes",
            "evaluation_task_codes",
            "material_types",
            "support_options",
            "common_problems",
        ):
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
    completion_hash = models.CharField(max_length=64, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="completed_evaluation_trial_records",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
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
        if self.completed_by_id and self.completed_by.school_id != self.school_id:
            errors["completed_by"] = "完成人与试用记录不属于同一学校。"
        if not isinstance(self.issues, list):
            errors["issues"] = "发现的问题必须是列表。"
        if not isinstance(self.action_items, list):
            errors["action_items"] = "后续处理必须是列表。"
        if self.record_type != EvaluationTrialType.SCORING_CHECK and self.agreement_rate is not None:
            errors["agreement_rate"] = "只有评分一致性检查可以填写一致率。"
        completion_values = (self.completion_hash, self.completed_by_id, self.completed_at)
        if self.status == EvaluationTrialStatus.COMPLETED:
            if not all(completion_values):
                errors["status"] = "完成试用记录时必须生成完成审计。"
            elif self.completion_hash != self.compute_completion_hash():
                errors["completion_hash"] = "试用记录完成哈希与记录内容不一致。"
            if self.participant_count < 1:
                errors["participant_count"] = "完成试用记录至少需要一名参与者。"
            if not str(self.summary or "").strip():
                errors["summary"] = "完成试用记录必须填写结果说明。"
            if self.conclusion == EvaluationTrialConclusion.PENDING:
                errors["conclusion"] = "完成试用记录必须填写处理结论。"
            if (
                self.record_type == EvaluationTrialType.SCORING_CHECK
                and self.agreement_rate is None
            ):
                errors["agreement_rate"] = "完成评分一致性检查必须填写一致率。"
        elif any(completion_values):
            errors["status"] = "未完成试用记录不能保留完成审计。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        persisted = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if persisted and persisted.status == EvaluationTrialStatus.COMPLETED:
            raise ValidationError("已完成试用记录不可修改；后续情况应新增补充记录。")
        if self.status == EvaluationTrialStatus.COMPLETED:
            if not self.completed_by_id:
                self.completed_by = self.updated_by
            if not self.completed_at:
                self.completed_at = timezone.now()
            self.completion_hash = self.compute_completion_hash()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        persisted_status = (
            type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if self.pk
            else self.status
        )
        if persisted_status == EvaluationTrialStatus.COMPLETED:
            raise ValidationError("已完成试用记录不可删除。")
        return super().delete(*args, **kwargs)

    def completion_content(self) -> dict:
        activity_date = self.activity_date
        if activity_date is not None and hasattr(activity_date, "isoformat"):
            activity_date = activity_date.isoformat()
        elif activity_date is not None:
            activity_date = str(activity_date)
        return {
            "school_id": self.school_id,
            "standard_version_id": self.standard_version_id,
            "record_type": self.record_type,
            "title": self.title,
            "status": self.status,
            "activity_date": activity_date,
            "participant_count": self.participant_count,
            "agreement_rate": (
                str(self.agreement_rate) if self.agreement_rate is not None else None
            ),
            "conclusion": self.conclusion,
            "summary": self.summary,
            "issues": self.issues,
            "action_items": self.action_items,
        }

    def compute_completion_hash(self) -> str:
        return canonical_content_hash(self.completion_content())

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
            if (
                self.standard_version.review_status != EvaluationReviewStatus.REVIEWED
                or not self.standard_version.reviewed_by_id
                or not self.standard_version.reviewed_at
                or self.standard_version.reviewed_content_hash
                != self.standard_version.content_hash
            ):
                errors["standard_version"] = "课时只能绑定教师已完成复核的评价标准版本。"
            plan_version = self.standard_version.plan_version
            if (
                plan_version.review_status != EvaluationReviewStatus.REVIEWED
                or not plan_version.reviewed_by_id
                or not plan_version.reviewed_at
                or plan_version.reviewed_content_hash != plan_version.content_hash
            ):
                errors["standard_version"] = "评价标准所绑定方案版本尚未完成教师复核。"
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
    evidence_ownership = models.CharField(
        max_length=16,
        choices=EvidenceOwnership.choices,
        default=EvidenceOwnership.INDIVIDUAL,
    )
    group = models.ForeignKey(
        "courses.ClassroomGroup",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluation_evidence",
    )
    material_manifest = models.JSONField(default=list, blank=True)
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
            session = self.standard_use.session
            if self.submission.course_id != session.course_id:
                errors["submission"] = "评价提交与课堂课程不一致。"
            if self.submission.class_group_id != session.class_group_id:
                errors["submission"] = "评价提交与课堂班级不一致。"
            if self.submission.target.school_id != session.school_id:
                errors["submission"] = "被评价学生与课堂不属于同一学校。"
            if self.submission.evaluator.school_id != session.school_id:
                errors["submission"] = "评价人与课堂不属于同一学校。"
        if self.lesson_step_attempt_id and self.standard_use_id:
            attempt = self.lesson_step_attempt
            if attempt.classroom_session_id != self.standard_use.session_id:
                errors["lesson_step_attempt"] = "学生作答不属于当前课堂。"
            if attempt.lesson_step_id != self.standard_use.lesson_step_id:
                errors["lesson_step_attempt"] = "学生作答不属于当前评价环节。"
            if self.submission_id and attempt.student_id != self.submission.target_id:
                errors["lesson_step_attempt"] = "学生作答与被评价学生不一致。"
            if self.submission_id and self.submission.session_id and (
                attempt.school_id != self.submission.session.school_id
                or attempt.class_group_id != self.submission.class_group_id
                or attempt.course_id != self.submission.course_id
            ):
                errors["lesson_step_attempt"] = "学生作答的学校、班级或课程范围不一致。"
        if self.student_work_attachment_id and self.standard_use_id:
            work = self.student_work_attachment
            if work.classroom_session_id != self.standard_use.session_id:
                errors["student_work_attachment"] = "学生作品不属于当前课堂。"
            if work.lesson_step_id != self.standard_use.lesson_step_id:
                errors["student_work_attachment"] = "学生作品不属于当前评价环节。"
            if self.submission_id and work.student_id != self.submission.target_id:
                errors["student_work_attachment"] = "学生作品与被评价学生不一致。"
            if self.submission_id and self.submission.session_id and (
                work.school_id != self.submission.session.school_id
                or work.class_group_id != self.submission.class_group_id
                or work.course_id != self.submission.course_id
            ):
                errors["student_work_attachment"] = "学生作品的学校、班级或课程范围不一致。"
        if self.evidence_ownership in {
            EvidenceOwnership.GROUP,
            EvidenceOwnership.BOTH,
        } and not self.group_id:
            errors["group"] = "小组评价材料必须关联实际小组。"
        if self.group_id and self.standard_use_id:
            collaboration = self.group.collaboration
            if collaboration.session_id != self.standard_use.session_id:
                errors["group"] = "小组评价材料与课堂不一致。"
            elif (
                not self.group.is_active
                or self.group.plan_version != collaboration.active_plan_version
            ):
                errors["group"] = "小组评价材料没有关联当前生效的实际小组。"
            elif self.submission_id and not self.group.members.filter(
                student_id=self.submission.target_id,
                plan_version=collaboration.active_plan_version,
            ).exists():
                errors["group"] = "被评价学生不是该实际小组的成员。"
        if not isinstance(self.material_manifest, list):
            errors["material_manifest"] = "评价材料清单必须是列表。"
        elif any(not isinstance(item, dict) for item in self.material_manifest):
            errors["material_manifest"] = "评价材料清单中的每一项都必须是对象。"
        else:
            allowed_statuses = {
                "available",
                "missing",
                "not_observed",
                "not_applicable",
                "technical_issue",
            }
            allowed_material_types = {
                "answer",
                "artifact",
                "operation",
                "oral_defense",
                "observation",
                "score",
            }
            criteria_by_id = {
                str(item.get("id")): item
                for item in (
                    self.standard_use.criteria_snapshot
                    if self.standard_use_id
                    and isinstance(self.standard_use.criteria_snapshot, list)
                    else []
                )
                if isinstance(item, dict) and item.get("id")
            }
            manifest_ownerships = set()
            for item in self.material_manifest:
                if item.get("ownership") not in {
                    EvidenceOwnership.INDIVIDUAL,
                    EvidenceOwnership.GROUP,
                }:
                    errors["material_manifest"] = "评价材料清单包含无效材料归属。"
                    break
                manifest_ownerships.add(item.get("ownership"))
                if item.get("material_type") not in allowed_material_types:
                    errors["material_manifest"] = "评价材料清单包含无效材料类型。"
                    break
                if item.get("status") not in allowed_statuses:
                    errors["material_manifest"] = "评价材料清单包含无效材料状态。"
                    break
                source = item.get("source")
                if item.get("status") == "available" and not isinstance(source, dict):
                    errors["material_manifest"] = "可用评价材料必须保留真实来源。"
                    break
                if isinstance(source, dict) and not all(
                    str(source.get(field) or "").strip()
                    for field in ("source_type", "source_id", "source_version")
                ):
                    errors["material_manifest"] = "评价材料来源必须保留类型、标识和版本。"
                    break
                if isinstance(source, dict):
                    material_type = item.get("material_type")
                    ownership = item.get("ownership")
                    compatible_source_types = {
                        "answer": {"lesson_step_attempt"},
                        "operation": {"lesson_step_attempt"},
                        "oral_defense": {"classroom_evaluation_submission"},
                        "observation": {"classroom_evaluation_submission"},
                        "score": {"classroom_evaluation_submission"},
                        "artifact": (
                            {
                                "classroom_group_document_version",
                                "classroom_group_file",
                            }
                            if ownership == EvidenceOwnership.GROUP
                            else {"student_work_attachment"}
                        ),
                    }.get(material_type, set())
                    if source.get("source_type") not in compatible_source_types:
                        errors["material_manifest"] = "评价材料来源与材料类型或归属不一致。"
                        break
                if item.get("status") != "available" and source is not None:
                    errors["material_manifest"] = "不可用评价材料不能伪造材料来源。"
                    break
                criterion = criteria_by_id.get(str(item.get("criterion_id") or ""))
                if criterion is None:
                    errors["material_manifest"] = "评价材料未关联课堂冻结的评价指标。"
                    break
                target_links = item.get("learning_target_links")
                expected_target_links = criterion.get("learning_target_links") or []
                if not isinstance(target_links, list) or any(
                    not isinstance(link, dict) for link in target_links
                ):
                    errors["material_manifest"] = "评价材料必须保留学习目标版本清单。"
                    break
                if target_links != expected_target_links:
                    errors["material_manifest"] = "评价材料的学习目标版本与课堂冻结指标不一致。"
                    break
                if any(
                    not str(link.get("target_version_id") or "").isdigit()
                    or not str(link.get("logical_key") or "").strip()
                    or len(str(link.get("content_hash") or "")) != 64
                    for link in target_links
                ):
                    errors["material_manifest"] = "评价材料中的学习目标版本信息不完整。"
                    break
                configured_ownership = criterion.get("evidence_ownership")
                allowed_ownerships = (
                    {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
                    if configured_ownership == EvidenceOwnership.BOTH
                    else {configured_ownership}
                )
                if item.get("ownership") not in allowed_ownerships:
                    errors["material_manifest"] = "评价材料归属与课堂冻结指标不一致。"
                    break
                if item.get("material_type") not in set(
                    criterion.get("material_types") or []
                ):
                    errors["material_manifest"] = "评价材料类型与课堂冻结指标不一致。"
                    break
                if item.get("ownership") == EvidenceOwnership.GROUP:
                    if not self.group_id or item.get("group_id") != self.group_id:
                        errors["material_manifest"] = "小组评价材料未关联同一实际小组。"
                        break
                    participant_ids = item.get("participant_student_ids")
                    if not isinstance(participant_ids, list):
                        errors["material_manifest"] = "小组评价材料必须保留实际参与学生。"
                        break
                    actual_member_ids = set(
                        self.group.members.filter(
                            plan_version=self.group.collaboration.active_plan_version
                        ).values_list("student_id", flat=True)
                    )
                    if (
                        set(participant_ids) != actual_member_ids
                        or self.submission.target_id not in actual_member_ids
                    ):
                        errors["material_manifest"] = "小组评价材料参与者与实际小组不一致。"
                        break
                elif item.get("participant_student_ids") != [
                    self.submission.target_id
                ]:
                    errors["material_manifest"] = "个人评价材料参与者必须是被评价学生。"
                    break
            if "material_manifest" not in errors and self.material_manifest:
                expected_ownership = (
                    EvidenceOwnership.BOTH
                    if manifest_ownerships
                    == {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
                    else next(iter(manifest_ownerships), EvidenceOwnership.INDIVIDUAL)
                )
                if self.evidence_ownership != expected_ownership:
                    errors["evidence_ownership"] = "评价证据归属与材料清单不一致。"
                ratings = self.submission.ratings if self.submission_id else {}
                for criterion_id in ratings if isinstance(ratings, dict) else []:
                    criterion = criteria_by_id.get(str(criterion_id))
                    if not criterion or not criterion.get("material_types"):
                        continue
                    ownership = criterion.get("evidence_ownership")
                    required_ownerships = (
                        {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
                        if ownership == EvidenceOwnership.BOTH
                        else {ownership}
                    )
                    for required_ownership in required_ownerships:
                        if not any(
                            item.get("criterion_id") == str(criterion_id)
                            and item.get("ownership") == required_ownership
                            and item.get("status") == "available"
                            for item in self.material_manifest
                        ):
                            errors["material_manifest"] = (
                                "已评分指标必须保留对应归属的可用评价材料。"
                            )
                            break
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
