from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


TARGET_CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
target_code_validator = RegexValidator(
    regex=TARGET_CODE_PATTERN,
    message="学习目标代码必须以字母开头，只能包含字母、数字、下划线或连字符。",
)
relation_code_validator = RegexValidator(
    regex=TARGET_CODE_PATTERN,
    message="代码必须以字母开头，只能包含字母、数字、下划线或连字符。",
)


class LearningTargetAlignmentStatus(models.TextChoices):
    COMPLETE = "complete", "课标依据完整"
    LEGACY_INCOMPLETE = "legacy_incomplete", "历史课标依据不完整"


class _ImmutableLearningTargetRecord(models.Model):
    """Shared protection for records that form a published evidence chain."""

    class Meta:
        abstract = True

    immutable_message = "已发布的学习目标记录不可修改。"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(self.immutable_message)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(self.immutable_message.replace("修改", "删除"))


class LearningTarget(_ImmutableLearningTargetRecord):
    """Stable identity shared by diagnostic, test, operation and project evidence.

    A target code has one logical identity inside an exact school-subject-course
    scope.  Its wording and curriculum alignment live in immutable versions.
    """

    logical_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="learning_targets",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="learning_targets",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="learning_targets",
    )
    code = models.CharField(max_length=32, validators=[target_code_validator])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_learning_targets",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "学习目标的逻辑身份及适用范围不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "course", "code"],
                name="uniq_learning_target_scope_code",
            )
        ]
        indexes = [
            models.Index(
                fields=["school", "subject", "course", "code"],
                name="la_target_scope_idx",
            )
        ]
        ordering = ["school_id", "subject_id", "course_id", "code"]

    def clean(self) -> None:
        errors = {}
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学习目标的学科与学校范围不一致。"
        if self.course_id:
            if self.course.subject_id != self.subject_id:
                errors["course"] = "学习目标的课程与学科范围不一致。"
            if self.course.teacher.school_id != self.school_id:
                errors["course"] = "学习目标的课程与学校范围不一致。"
        if self.created_by_id and self.created_by.school_id != self.school_id:
            errors["created_by"] = "学习目标创建人与适用学校不一致。"
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.course_id}:{self.code}"


class LearningTargetVersion(_ImmutableLearningTargetRecord):
    target = models.ForeignKey(
        LearningTarget,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    plan_version = models.ForeignKey(
        "learning_analytics.EvaluationPlanVersion",
        on_delete=models.PROTECT,
        related_name="learning_target_versions",
    )
    version_no = models.PositiveIntegerField()
    code = models.CharField(max_length=32, validators=[target_code_validator])
    title = models.CharField(max_length=160)
    description = models.TextField()
    content_hash = models.CharField(max_length=64, editable=False)
    alignment_status = models.CharField(
        max_length=24,
        choices=LearningTargetAlignmentStatus.choices,
        default=LearningTargetAlignmentStatus.COMPLETE,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_learning_target_versions",
    )
    published_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "已发布的学习目标版本不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target", "version_no"],
                name="uniq_learning_target_version_no",
            ),
            models.UniqueConstraint(
                fields=["target", "plan_version"],
                name="uniq_target_plan_version",
            ),
            models.UniqueConstraint(
                fields=["plan_version", "code"],
                name="uniq_plan_version_target_code",
            ),
        ]
        indexes = [
            models.Index(
                fields=["plan_version", "alignment_status"],
                name="la_target_plan_status_idx",
            ),
            models.Index(
                fields=["target", "published_at"],
                name="la_target_version_time_idx",
            ),
        ]
        ordering = ["target_id", "version_no", "id"]

    def clean(self) -> None:
        errors = {}
        if self.target_id and self.plan_version_id:
            plan_version = self.plan_version
            target = self.target
            if target.school_id != plan_version.school_id:
                errors["plan_version"] = "学习目标版本与评价方案版本的学校范围不一致。"
            elif target.subject_id != plan_version.subject_id:
                errors["plan_version"] = "学习目标版本与评价方案版本的学科范围不一致。"
            elif target.course_id != plan_version.course_id:
                errors["plan_version"] = "学习目标版本与评价方案版本的课程范围不一致。"
        if self.target_id and self.code != self.target.code:
            errors["code"] = "学习目标版本代码必须与逻辑目标代码一致。"
        if self.published_by_id and self.target_id:
            if self.published_by.school_id != self.target.school_id:
                errors["published_by"] = "发布人与学习目标适用学校不一致。"
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_hash or ""):
            errors["content_hash"] = "学习目标版本内容哈希格式不正确。"
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.target.logical_key}@{self.version_no}"


class LearningTargetCurriculumAlignment(_ImmutableLearningTargetRecord):
    target_version = models.ForeignKey(
        LearningTargetVersion,
        on_delete=models.PROTECT,
        related_name="curriculum_alignments",
    )
    plan_reference = models.ForeignKey(
        "curriculum_standards.EvaluationPlanVersionCurriculumReference",
        on_delete=models.PROTECT,
        related_name="learning_target_alignments",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "学习目标版本的课程标准依据不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target_version", "plan_reference"],
                name="uniq_target_curriculum_alignment",
            ),
            models.UniqueConstraint(
                fields=["target_version", "sort_order"],
                name="uniq_target_curriculum_order",
            ),
        ]
        ordering = ["sort_order", "id"]

    def clean(self) -> None:
        if (
            self.target_version_id
            and self.plan_reference_id
            and self.target_version.plan_version_id
            != self.plan_reference.plan_version_id
        ):
            raise ValidationError(
                {"plan_reference": "课程标准依据必须属于同一评价方案版本。"}
            )


class EvaluationBasisLearningTarget(_ImmutableLearningTargetRecord):
    plan_version = models.ForeignKey(
        "learning_analytics.EvaluationPlanVersion",
        on_delete=models.PROTECT,
        related_name="basis_learning_target_links",
    )
    basis_code = models.CharField(max_length=32, validators=[relation_code_validator])
    target_version = models.ForeignKey(
        LearningTargetVersion,
        on_delete=models.PROTECT,
        related_name="evaluation_basis_links",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "评价依据与学习目标版本的关系不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "basis_code", "target_version"],
                name="uniq_basis_learning_target",
            )
        ]
        indexes = [
            models.Index(
                fields=["plan_version", "basis_code"],
                name="la_basis_target_idx",
            )
        ]
        ordering = ["plan_version_id", "basis_code", "sort_order", "id"]

    def clean(self) -> None:
        errors = {}
        if (
            self.plan_version_id
            and self.target_version_id
            and self.target_version.plan_version_id != self.plan_version_id
        ):
            errors["target_version"] = "评价依据与学习目标版本不属于同一方案版本。"
        if self.plan_version_id and self.target_version_id:
            basis = next(
                (
                    row
                    for row in (self.plan_version.evaluation_basis or [])
                    if isinstance(row, dict)
                    and str(row.get("code") or "") == self.basis_code
                ),
                None,
            )
            if basis is None:
                errors["basis_code"] = "评价依据代码不存在于对应方案版本。"
            elif self.target_version.code not in {
                str(code) for code in (basis.get("goal_codes") or [])
            }:
                errors["target_version"] = "该评价依据未关联此学习目标。"
        if errors:
            raise ValidationError(errors)


class LearningActivityLearningTarget(_ImmutableLearningTargetRecord):
    plan_version = models.ForeignKey(
        "learning_analytics.EvaluationPlanVersion",
        on_delete=models.PROTECT,
        related_name="activity_learning_target_links",
    )
    activity_code = models.CharField(
        max_length=32,
        validators=[relation_code_validator],
    )
    target_version = models.ForeignKey(
        LearningTargetVersion,
        on_delete=models.PROTECT,
        related_name="learning_activity_links",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "学习活动与学习目标版本的关系不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "activity_code", "target_version"],
                name="uniq_activity_learning_target",
            )
        ]
        indexes = [
            models.Index(
                fields=["plan_version", "activity_code"],
                name="la_activity_target_idx",
            )
        ]
        ordering = ["plan_version_id", "activity_code", "sort_order", "id"]

    def clean(self) -> None:
        errors = {}
        if (
            self.plan_version_id
            and self.target_version_id
            and self.target_version.plan_version_id != self.plan_version_id
        ):
            errors["target_version"] = "学习活动与学习目标版本不属于同一方案版本。"
        if self.plan_version_id and self.target_version_id:
            activity = next(
                (
                    row
                    for row in (self.plan_version.learning_activities or [])
                    if isinstance(row, dict)
                    and str(row.get("code") or "") == self.activity_code
                ),
                None,
            )
            if activity is None:
                errors["activity_code"] = "学习活动代码不存在于对应方案版本。"
            elif self.target_version.code not in {
                str(code) for code in (activity.get("goal_codes") or [])
            }:
                errors["target_version"] = "该学习活动未关联此学习目标。"
        if errors:
            raise ValidationError(errors)


class EvaluationTaskLearningActivity(_ImmutableLearningTargetRecord):
    plan_version = models.ForeignKey(
        "learning_analytics.EvaluationPlanVersion",
        on_delete=models.PROTECT,
        related_name="task_learning_activity_links",
    )
    task_code = models.CharField(max_length=32, validators=[relation_code_validator])
    activity_code = models.CharField(
        max_length=32,
        validators=[relation_code_validator],
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "评价任务与学习活动的关系不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "task_code", "activity_code"],
                name="uniq_task_learning_activity",
            ),
            models.UniqueConstraint(
                fields=["plan_version", "task_code", "sort_order"],
                name="uniq_task_learning_activity_order",
            ),
        ]
        indexes = [
            models.Index(
                fields=["plan_version", "task_code"],
                name="la_task_activity_idx",
            )
        ]
        ordering = ["plan_version_id", "task_code", "sort_order", "id"]

    def clean(self) -> None:
        if not self.plan_version_id:
            return
        tasks = {
            str(row.get("code") or ""): row
            for row in (self.plan_version.evaluation_tasks or [])
            if isinstance(row, dict)
        }
        activities = {
            str(row.get("code") or ""): row
            for row in (self.plan_version.learning_activities or [])
            if isinstance(row, dict)
        }
        task = tasks.get(self.task_code)
        activity = activities.get(self.activity_code)
        errors = {}
        if task is None:
            errors["task_code"] = "评价任务代码不存在于对应方案版本。"
        if activity is None:
            errors["activity_code"] = "学习活动代码不存在于对应方案版本。"
        if task is not None and self.activity_code not in {
            str(code) for code in (task.get("activity_codes") or [])
        }:
            errors["activity_code"] = "该评价任务未关联此学习活动。"
        if task is not None and activity is not None and not (
            {str(code) for code in (task.get("goal_codes") or [])}
            & {str(code) for code in (activity.get("goal_codes") or [])}
        ):
            errors["activity_code"] = "评价任务与学习活动没有共同学习目标。"
        if errors:
            raise ValidationError(errors)


class EvaluationTaskLearningTarget(_ImmutableLearningTargetRecord):
    plan_version = models.ForeignKey(
        "learning_analytics.EvaluationPlanVersion",
        on_delete=models.PROTECT,
        related_name="task_learning_target_links",
    )
    task_code = models.CharField(max_length=32, validators=[relation_code_validator])
    target_version = models.ForeignKey(
        LearningTargetVersion,
        on_delete=models.PROTECT,
        related_name="evaluation_task_links",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "评价任务与学习目标版本的关系不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "task_code", "target_version"],
                name="uniq_task_learning_target",
            )
        ]
        indexes = [
            models.Index(
                fields=["plan_version", "task_code"],
                name="la_task_target_idx",
            )
        ]
        ordering = ["plan_version_id", "task_code", "sort_order", "id"]

    def clean(self) -> None:
        errors = {}
        if (
            self.plan_version_id
            and self.target_version_id
            and self.target_version.plan_version_id != self.plan_version_id
        ):
            errors["target_version"] = "评价任务与学习目标版本不属于同一方案版本。"
        if self.plan_version_id and self.target_version_id:
            task = next(
                (
                    row
                    for row in (self.plan_version.evaluation_tasks or [])
                    if isinstance(row, dict)
                    and str(row.get("code") or "") == self.task_code
                ),
                None,
            )
            if task is None:
                errors["task_code"] = "评价任务代码不存在于对应方案版本。"
            elif self.target_version.code not in {
                str(code) for code in (task.get("goal_codes") or [])
            }:
                errors["target_version"] = "该评价任务未关联此学习目标。"
        if errors:
            raise ValidationError(errors)


class EvaluationCriterionLearningTarget(_ImmutableLearningTargetRecord):
    criterion = models.ForeignKey(
        "learning_analytics.EvaluationCriterionVersion",
        on_delete=models.PROTECT,
        related_name="learning_target_links",
    )
    target_version = models.ForeignKey(
        LearningTargetVersion,
        on_delete=models.PROTECT,
        related_name="evaluation_criterion_links",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "评价指标与学习目标版本的关系不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["criterion", "target_version"],
                name="uniq_criterion_learning_target",
            ),
            models.UniqueConstraint(
                fields=["criterion", "sort_order"],
                name="uniq_criterion_target_order",
            ),
        ]
        ordering = ["criterion_id", "sort_order", "id"]

    def clean(self) -> None:
        errors = {}
        if self.criterion_id and self.target_version_id:
            plan_version_id = self.criterion.standard_version.plan_version_id
            if self.target_version.plan_version_id != plan_version_id:
                errors["target_version"] = "评价指标与学习目标版本不属于同一方案版本。"
            elif self.target_version.code not in {
                str(code) for code in (self.criterion.learning_goal_codes or [])
            }:
                errors["target_version"] = "该评价指标未关联此学习目标。"
        if errors:
            raise ValidationError(errors)


class EvaluationCriterionEvaluationTask(_ImmutableLearningTargetRecord):
    criterion = models.ForeignKey(
        "learning_analytics.EvaluationCriterionVersion",
        on_delete=models.PROTECT,
        related_name="evaluation_task_links",
    )
    task_code = models.CharField(max_length=32, validators=[relation_code_validator])
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "评价指标与评价任务的关系不可修改。"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["criterion", "task_code"],
                name="uniq_criterion_evaluation_task",
            ),
            models.UniqueConstraint(
                fields=["criterion", "sort_order"],
                name="uniq_criterion_evaluation_task_order",
            ),
        ]
        indexes = [
            models.Index(
                fields=["criterion", "task_code"],
                name="la_criterion_task_idx",
            )
        ]
        ordering = ["criterion_id", "sort_order", "id"]

    def clean(self) -> None:
        if not self.criterion_id:
            return
        plan_version = self.criterion.standard_version.plan_version
        task = next(
            (
                row
                for row in (plan_version.evaluation_tasks or [])
                if isinstance(row, dict)
                and str(row.get("code") or "") == self.task_code
            ),
            None,
        )
        errors = {}
        if task is None:
            errors["task_code"] = "评价任务代码不存在于对应方案版本。"
        elif self.task_code not in {
            str(code) for code in (self.criterion.evaluation_task_codes or [])
        }:
            errors["task_code"] = "该评价指标未关联此评价任务。"
        elif not (
            {str(code) for code in (task.get("goal_codes") or [])}
            & {str(code) for code in (self.criterion.learning_goal_codes or [])}
        ):
            errors["task_code"] = "评价指标与评价任务没有共同学习目标。"
        if errors:
            raise ValidationError(errors)


class LearningTargetBackfillIssue(_ImmutableLearningTargetRecord):
    """Auditable record for historical rows that could not be linked honestly."""

    plan_version = models.ForeignKey(
        "learning_analytics.EvaluationPlanVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="learning_target_backfill_issues",
    )
    standard_version = models.ForeignKey(
        "learning_analytics.EvaluationStandardVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="learning_target_backfill_issues",
    )
    item_kind = models.CharField(max_length=40)
    source_code = models.CharField(max_length=80, blank=True)
    reason = models.CharField(max_length=80)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_message = "学习目标历史回填审计记录不可修改。"

    class Meta:
        indexes = [
            models.Index(
                fields=["item_kind", "reason", "created_at"],
                name="la_target_issue_idx",
            )
        ]
        ordering = ["created_at", "id"]

    def clean(self) -> None:
        if not self.plan_version_id and not self.standard_version_id:
            raise ValidationError("历史回填审计记录必须关联方案版本或评价标准版本。")
