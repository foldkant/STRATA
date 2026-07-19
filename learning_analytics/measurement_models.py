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


class MeasurementUse(models.TextChoices):
    LOCAL_FORMATIVE = "local_formative", "本地形成性"
    SCHOOL_COMMON = "school_common", "校级共同测量"
    RESEARCH_LINKED = "research_linked", "研究链接"


class MeasurementValidationStatus(models.TextChoices):
    UNVALIDATED = "unvalidated", "尚未验证"
    CONTENT_REVIEW_PENDING = "content_review_pending", "待内容审查"
    CONTENT_REVIEWED = "content_reviewed", "已完成内容审查"
    PILOT_SCHEDULED = "pilot_scheduled", "已安排试测"
    PILOT_COMPLETED = "pilot_completed", "已完成试测"
    VALIDATED = "validated", "已验证"


class RubricModule(models.TextChoices):
    PRODUCT = "P", "P 成果与任务质量"
    STRATEGY = "S", "S 策略质量"
    REGULATION = "R", "R 调节过程"
    COLLABORATION = "C", "C 协作与反馈"
    DISCIPLINARY = "D", "D 学科实践"
    ETHICS = "E", "E 伦理与责任实践"


class AssessmentBlueprint(models.Model):
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="assessment_blueprints",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="assessment_blueprints",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_blueprints",
    )
    title = models.CharField(max_length=160)
    intended_use = models.CharField(
        max_length=32,
        choices=MeasurementUse.choices,
        default=MeasurementUse.LOCAL_FORMATIVE,
    )
    task_version = models.CharField(max_length=64, blank=True)
    target_population = models.CharField(max_length=300, blank=True)
    course_goal = models.TextField(blank=True)
    claims = models.JSONField(default=list, blank=True)
    evidence_rules = models.JSONField(default=list, blank=True)
    task_specifications = models.JSONField(default=list, blank=True)
    content_coverage = models.JSONField(default=list, blank=True)
    cognitive_complexity = models.JSONField(default=list, blank=True)
    allowed_supports = models.JSONField(default=list, blank=True)
    scoring_model = models.JSONField(default=dict, blank=True)
    next_formative_action = models.TextField(blank=True)
    validation_status = models.CharField(
        max_length=32,
        choices=MeasurementValidationStatus.choices,
        default=MeasurementValidationStatus.UNVALIDATED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assessment_blueprints",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_assessment_blueprints",
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
            errors["subject"] = "学科与测量蓝图学校不一致。"
        if self.course_id:
            if self.course.teacher.school_id != self.school_id:
                errors["course"] = "课程与测量蓝图学校不一致。"
            if self.course.subject_id != self.subject_id:
                errors["course"] = "课程与测量蓝图学科不一致。"
        if self.created_by_id and self.created_by.school_id != self.school_id:
            errors["created_by"] = "创建人与测量蓝图学校不一致。"
        if self.updated_by_id and self.updated_by.school_id != self.school_id:
            errors["updated_by"] = "更新人与测量蓝图学校不一致。"
        if (
            self.created_by_id
            and self.created_by.role == self.created_by.Role.TEACHER
            and self.intended_use != MeasurementUse.LOCAL_FORMATIVE
        ):
            errors["intended_use"] = "教师创建的量规只能用于本地形成性评价。"
        for field_name in (
            "claims",
            "evidence_rules",
            "task_specifications",
            "content_coverage",
            "cognitive_complexity",
            "allowed_supports",
        ):
            if not isinstance(getattr(self, field_name), list):
                errors[field_name] = "必须是 JSON 列表。"
        if not isinstance(self.scoring_model, dict):
            errors["scoring_model"] = "评分模型必须是 JSON 对象。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class ImmutableMeasurementVersion(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("已发布的测量版本不可原地修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已发布的测量版本不可直接删除。")


class AssessmentBlueprintVersion(ImmutableMeasurementVersion):
    source = models.ForeignKey(
        AssessmentBlueprint,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="assessment_blueprint_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="assessment_blueprint_versions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_blueprint_versions",
    )
    version_no = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64, editable=False)
    title = models.CharField(max_length=160)
    intended_use = models.CharField(max_length=32, choices=MeasurementUse.choices)
    task_version = models.CharField(max_length=64)
    target_population = models.CharField(max_length=300)
    course_goal = models.TextField()
    claims = models.JSONField(default=list)
    evidence_rules = models.JSONField(default=list)
    task_specifications = models.JSONField(default=list)
    content_coverage = models.JSONField(default=list)
    cognitive_complexity = models.JSONField(default=list)
    allowed_supports = models.JSONField(default=list, blank=True)
    scoring_model = models.JSONField(default=dict)
    next_formative_action = models.TextField()
    validation_status = models.CharField(
        max_length=32,
        choices=MeasurementValidationStatus.choices,
        default=MeasurementValidationStatus.UNVALIDATED,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_assessment_blueprint_versions",
    )
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "version_no"],
                name="uniq_blueprint_version_no",
            ),
            models.UniqueConstraint(
                fields=["source", "content_hash"],
                name="uniq_blueprint_content_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "published_at"]),
            models.Index(fields=["intended_use", "validation_status"]),
        ]
        ordering = ["source_id", "-version_no"]

    def clean(self) -> None:
        errors = {}
        if self.source_id:
            for field_name in ("school_id", "subject_id", "course_id"):
                if getattr(self, field_name) != getattr(self.source, field_name):
                    errors[field_name.removesuffix("_id")] = "发布版本与蓝图草案范围不一致。"
        if self.published_by_id and self.published_by.school_id != self.school_id:
            errors["published_by"] = "发布人与蓝图版本学校不一致。"
        if errors:
            raise ValidationError(errors)

    def semantic_content(self) -> dict:
        return {
            "school_id": self.school_id,
            "subject_id": self.subject_id,
            "course_id": self.course_id,
            "title": self.title,
            "intended_use": self.intended_use,
            "task_version": self.task_version,
            "target_population": self.target_population,
            "course_goal": self.course_goal,
            "claims": self.claims,
            "evidence_rules": self.evidence_rules,
            "task_specifications": self.task_specifications,
            "content_coverage": self.content_coverage,
            "cognitive_complexity": self.cognitive_complexity,
            "allowed_supports": self.allowed_supports,
            "scoring_model": self.scoring_model,
            "next_formative_action": self.next_formative_action,
            "validation_status": self.validation_status,
        }

    def __str__(self) -> str:
        return f"{self.title}@{self.version_no}"


class RubricDefinition(models.Model):
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="rubric_definitions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="rubric_definitions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rubric_definitions",
    )
    blueprint = models.ForeignKey(
        AssessmentBlueprint,
        on_delete=models.PROTECT,
        related_name="rubric_drafts",
    )
    title = models.CharField(max_length=160)
    intended_use = models.CharField(
        max_length=32,
        choices=MeasurementUse.choices,
        default=MeasurementUse.LOCAL_FORMATIVE,
    )
    evaluation_object = models.CharField(max_length=300, blank=True)
    criteria = models.JSONField(default=list, blank=True)
    validation_status = models.CharField(
        max_length=32,
        choices=MeasurementValidationStatus.choices,
        default=MeasurementValidationStatus.UNVALIDATED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_rubric_definitions",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_rubric_definitions",
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
        if self.blueprint_id:
            expected = {
                "school": self.blueprint.school_id,
                "subject": self.blueprint.subject_id,
                "course": self.blueprint.course_id,
            }
            for field_name, value in expected.items():
                if getattr(self, f"{field_name}_id") != value:
                    errors[field_name] = "量规与任务蓝图范围不一致。"
        if self.created_by_id and self.created_by.school_id != self.school_id:
            errors["created_by"] = "创建人与量规学校不一致。"
        if self.updated_by_id and self.updated_by.school_id != self.school_id:
            errors["updated_by"] = "更新人与量规学校不一致。"
        if (
            self.created_by_id
            and self.created_by.role == self.created_by.Role.TEACHER
            and self.intended_use != MeasurementUse.LOCAL_FORMATIVE
        ):
            errors["intended_use"] = "教师创建的量规只能用于本地形成性评价。"
        if not isinstance(self.criteria, list):
            errors["criteria"] = "量规条目必须是 JSON 列表。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class RubricDefinitionVersion(ImmutableMeasurementVersion):
    source = models.ForeignKey(
        RubricDefinition,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    blueprint_version = models.ForeignKey(
        AssessmentBlueprintVersion,
        on_delete=models.PROTECT,
        related_name="rubric_versions",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="rubric_definition_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="rubric_definition_versions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rubric_definition_versions",
    )
    version_no = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64, editable=False)
    title = models.CharField(max_length=160)
    intended_use = models.CharField(max_length=32, choices=MeasurementUse.choices)
    evaluation_object = models.CharField(max_length=300)
    validation_status = models.CharField(
        max_length=32,
        choices=MeasurementValidationStatus.choices,
        default=MeasurementValidationStatus.UNVALIDATED,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_rubric_definition_versions",
    )
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "version_no"],
                name="uniq_rubric_version_no",
            ),
            models.UniqueConstraint(
                fields=["source", "content_hash"],
                name="uniq_rubric_content_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "published_at"]),
            models.Index(fields=["intended_use", "validation_status"]),
        ]
        ordering = ["source_id", "-version_no"]

    def clean(self) -> None:
        errors = {}
        if self.source_id:
            for field_name in ("school_id", "subject_id", "course_id"):
                if getattr(self, field_name) != getattr(self.source, field_name):
                    errors[field_name.removesuffix("_id")] = "发布版本与量规草案范围不一致。"
        if self.blueprint_version_id:
            if self.blueprint_version.source_id != self.source.blueprint_id:
                errors["blueprint_version"] = "量规版本未绑定其任务蓝图的发布版本。"
            if self.blueprint_version.school_id != self.school_id:
                errors["blueprint_version"] = "任务蓝图版本与量规学校不一致。"
        if self.published_by_id and self.published_by.school_id != self.school_id:
            errors["published_by"] = "发布人与量规版本学校不一致。"
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.title}@{self.version_no}"


class RubricCriterionVersion(ImmutableMeasurementVersion):
    rubric_version = models.ForeignKey(
        RubricDefinitionVersion,
        on_delete=models.PROTECT,
        related_name="criteria",
    )
    code = models.CharField(max_length=32)
    module = models.CharField(max_length=1, choices=RubricModule.choices)
    title = models.CharField(max_length=160)
    evaluation_object = models.CharField(max_length=300)
    evidence_sources = models.JSONField(default=list)
    observable_evidence = models.TextField()
    not_assessed_condition = models.TextField()
    allowed_supports = models.JSONField(default=list, blank=True)
    counter_examples = models.JSONField(default=list)
    anchor_level_1 = models.TextField()
    anchor_level_2 = models.TextField()
    anchor_level_3 = models.TextField()
    anchor_level_4 = models.TextField()
    anchor_level_5 = models.TextField()
    next_formative_action = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rubric_version", "code"],
                name="uniq_rubric_criterion_code",
            ),
            models.UniqueConstraint(
                fields=["rubric_version", "sort_order"],
                name="uniq_rubric_criterion_order",
            ),
        ]
        ordering = ["sort_order", "id"]

    def clean(self) -> None:
        errors = {}
        for field_name in ("evidence_sources", "allowed_supports", "counter_examples"):
            if not isinstance(getattr(self, field_name), list):
                errors[field_name] = "必须是 JSON 列表。"
        if errors:
            raise ValidationError(errors)

    @property
    def anchor_texts(self) -> list[str]:
        return [
            self.anchor_level_1,
            self.anchor_level_2,
            self.anchor_level_3,
            self.anchor_level_4,
            self.anchor_level_5,
        ]

    def __str__(self) -> str:
        return f"{self.rubric_version_id}:{self.code}"


class RubricAnchorExample(ImmutableMeasurementVersion):
    criterion = models.ForeignKey(
        RubricCriterionVersion,
        on_delete=models.PROTECT,
        related_name="anchor_examples",
    )
    level = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=160)
    evidence_summary = models.TextField()
    artifact_reference = models.CharField(max_length=500, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__gte=1) & models.Q(level__lte=5),
                name="rubric_anchor_example_level_1_5",
            ),
            models.UniqueConstraint(
                fields=["criterion", "sort_order"],
                name="uniq_rubric_anchor_example_order",
            ),
        ]
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.criterion_id}:L{self.level}:{self.title}"
