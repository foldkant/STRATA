from __future__ import annotations

import hashlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class FrozenGroupingRecordQuerySet(models.QuerySet):
    """Block ordinary bulk writes that would erase grouping audit history."""

    def update(self, **kwargs):
        raise ValidationError("已形成的分组审计记录不可批量修改。")

    def delete(self):
        raise ValidationError("已形成的分组审计记录不可批量删除。")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("已形成的分组审计记录不可批量修改。")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, **kwargs):
        raise ValidationError("分组审计记录必须逐项校验后保存。")


class ImmutableGroupingRecord(models.Model):
    objects = FrozenGroupingRecordQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("已形成的分组审计记录不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已形成的分组审计记录不可删除。")


class GroupingPolicyVersion(models.Model):
    class Strategy(models.TextChoices):
        RANDOM_BASELINE = "random_baseline", "随机分组"
        READINESS_ALIGNED = "readiness_aligned", "准备度接近"
        READINESS_BRIDGED = "readiness_bridged", "相邻互助"
        SKILL_COMPLEMENTARY = "skill_complementary", "技能互补"
        STABLE_PROJECT = "stable_project", "项目稳定"
        MANUAL = "manual", "教师设置"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        RETIRED = "retired", "停用"

    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="grouping_policy_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="grouping_policy_versions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="grouping_policy_versions",
    )
    name = models.CharField(max_length=128)
    version_no = models.PositiveIntegerField(default=1)
    policy_version = models.CharField(max_length=32)
    strategy = models.CharField(max_length=32, choices=Strategy.choices)
    group_size = models.PositiveSmallIntegerField(default=4)
    min_group_size = models.PositiveSmallIntegerField(default=3)
    max_group_size = models.PositiveSmallIntegerField(default=5)
    role_scheme = models.JSONField(default=list, blank=True)
    hard_constraints = models.JSONField(default=dict, blank=True)
    objective_weights = models.JSONField(default=dict, blank=True)
    stability_window_days = models.PositiveSmallIntegerField(default=14)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    content_hash = models.CharField(max_length=64, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_grouping_policies",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_grouping_policies",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "policy_version"],
                name="uniq_grouping_policy_version",
            ),
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(
                    subject__isnull=True,
                    course__isnull=True,
                    status="active",
                ),
                name="uniq_active_global_grouping_policy",
            ),
            models.UniqueConstraint(
                fields=["school", "subject"],
                condition=models.Q(
                    subject__isnull=False,
                    course__isnull=True,
                    status="active",
                ),
                name="uniq_active_subject_grouping_policy",
            ),
            models.UniqueConstraint(
                fields=["school", "course"],
                condition=models.Q(course__isnull=False, status="active"),
                name="uniq_active_course_grouping_policy",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "status", "strategy"]),
            models.Index(fields=["course", "status", "version_no"]),
        ]
        ordering = ["school_id", "name", "-version_no", "-id"]

    def semantic_definition(self) -> dict:
        return {
            "school_id": self.school_id,
            "subject_id": self.subject_id,
            "course_id": self.course_id,
            "version_no": self.version_no,
            "policy_version": self.policy_version,
            "strategy": self.strategy,
            "group_size": self.group_size,
            "min_group_size": self.min_group_size,
            "max_group_size": self.max_group_size,
            "role_scheme": self.role_scheme,
            "hard_constraints": self.hard_constraints,
            "objective_weights": self.objective_weights,
            "stability_window_days": self.stability_window_days,
        }

    def clean(self):
        errors = {}
        if (
            self.course_id
            and self.subject_id
            and self.course.subject_id != self.subject_id
        ):
            errors["course"] = "课程与学科不一致。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与学校不一致。"
        if self.course_id and self.course.subject.school_id != self.school_id:
            errors["course"] = "课程与学校不一致。"
        if not 2 <= self.min_group_size <= self.group_size <= self.max_group_size <= 12:
            errors["group_size"] = (
                "小组人数必须满足最少人数 <= 目标人数 <= 最多人数，且范围为 2 至 12。"
            )
        allowed_roles = {
            "coordinator",
            "recorder",
            "resource",
            "presenter",
            "verifier",
            "leader",
            "member",
        }
        if not isinstance(self.role_scheme, list) or any(
            role not in allowed_roles for role in self.role_scheme
        ):
            errors["role_scheme"] = "小组角色设置不正确。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        payload = json.dumps(
            self.semantic_definition(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.content_hash = hashlib.sha256(payload).hexdigest()
        if previous and previous.status in {self.Status.ACTIVE, self.Status.RETIRED}:
            if previous.content_hash != self.content_hash:
                raise ValidationError("已启用的分组标准不能原地修改，请创建新版本。")
        self.full_clean()
        return super().save(*args, **kwargs)


class GroupingDecisionPoint(models.Model):
    ALLOWED_ROLES = {
        "coordinator",
        "recorder",
        "resource",
        "presenter",
        "verifier",
        "leader",
        "member",
    }

    class TaskPurpose(models.TextChoices):
        TARGETED_SUPPORT = "targeted_support", "聚焦补缺与教师指导"
        PEER_EXPLANATION = "peer_explanation", "同伴解释与互助讨论"
        OPEN_PROBLEM = "open_problem", "开放问题解决"
        PROJECT_LEARNING = "project_learning", "项目式学习"
        LOW_RISK_BASELINE = "low_risk_baseline", "低风险课堂活动"

    class Trigger(models.TextChoices):
        LESSON_STEP = "lesson_step", "课堂环节"
        PROJECT_STAGE = "project_stage", "项目阶段"
        TEACHER_REQUEST = "teacher_request", "教师发起"

    class Status(models.TextChoices):
        OPEN = "open", "准备中"
        CANDIDATE_READY = "candidate_ready", "候选已生成"
        REVIEWED = "reviewed", "教师已复核"
        ACTIVE = "active", "已启用"
        NOTIFIED = "notified", "已通知学生"
        CONFIRMED = "confirmed", "已确认（兼容）"
        CLOSED = "closed", "已结束"

    point_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="grouping_decision_points",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="grouping_decision_points",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="grouping_decision_points",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.PROTECT,
        related_name="grouping_decision_points",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="grouping_decision_points",
    )
    policy = models.ForeignKey(
        GroupingPolicyVersion,
        on_delete=models.PROTECT,
        related_name="decision_points",
    )
    trigger = models.CharField(max_length=24, choices=Trigger.choices)
    task_purpose = models.CharField(
        max_length=32,
        choices=TaskPurpose.choices,
        default=TaskPurpose.LOW_RISK_BASELINE,
    )
    task_stage = models.CharField(max_length=128, default="课堂活动")
    role_requirements = models.JSONField(default=list)
    resource_requirements = models.JSONField(default=list)
    safety_constraints = models.JSONField(default=dict, blank=True)
    opportunity_requirements = models.JSONField(default=dict, blank=True)
    stability_until = models.DateTimeField(null=True, blank=True)
    task_context = models.JSONField(default=dict, blank=True)
    scheduled_for = models.DateTimeField()
    status = models.CharField(max_length=24, choices=Status.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_grouping_decision_points",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["classroom_session", "status", "scheduled_for"]),
            models.Index(fields=["school", "class_group", "created_at"]),
        ]
        ordering = ["-scheduled_for", "-id"]

    def clean(self):
        errors = {}
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "班级与学校不一致。"
        if self.course_id and self.course.subject.school_id != self.school_id:
            errors["course"] = "课程与学校不一致。"
        if self.classroom_session_id:
            session = self.classroom_session
            if session.school_id != self.school_id:
                errors["classroom_session"] = "课堂与学校不一致。"
            elif session.class_group_id != self.class_group_id:
                errors["classroom_session"] = "课堂与班级不一致。"
            elif session.course_id != self.course_id:
                errors["classroom_session"] = "课堂与课程不一致。"
        if (
            self.lesson_step_id
            and self.lesson_step.lesson_id != self.classroom_session.lesson_id
        ):
            errors["lesson_step"] = "课堂环节不属于当前课时。"
        if not str(self.task_stage or "").strip():
            errors["task_stage"] = "请填写本次分组所处的学习阶段。"
        if not isinstance(self.role_requirements, list) or not self.role_requirements:
            errors["role_requirements"] = "请至少确定一种小组角色。"
        elif len(set(self.role_requirements)) != len(self.role_requirements):
            errors["role_requirements"] = "小组角色不能重复。"
        elif any(role not in self.ALLOWED_ROLES for role in self.role_requirements):
            errors["role_requirements"] = "小组角色设置不正确。"
        if not isinstance(self.resource_requirements, list):
            errors["resource_requirements"] = "学习资源设置必须是列表。"
        if not isinstance(self.safety_constraints, dict):
            errors["safety_constraints"] = "安全约束设置必须是对象。"
        if not isinstance(self.opportunity_requirements, dict):
            errors["opportunity_requirements"] = "学习机会设置必须是对象。"
        if (
            self.stability_until
            and self.scheduled_for
            and self.stability_until < self.scheduled_for
        ):
            errors["stability_until"] = "稳定期结束时间不能早于分组计划时间。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        immutable_fields = (
            "task_purpose",
            "task_stage",
            "role_requirements",
            "resource_requirements",
            "safety_constraints",
            "opportunity_requirements",
            "stability_until",
            "task_context",
        )
        if previous and previous.candidate_runs.exists():
            if any(
                getattr(previous, field) != getattr(self, field)
                for field in immutable_fields
            ):
                raise ValidationError(
                    "已生成候选的分组任务定义不能原地修改，请新建一次分组决策。"
                )
        update_fields = set(kwargs.get("update_fields") or [])
        if (
            not previous
            or not update_fields
            or update_fields.intersection(immutable_fields)
        ):
            self.full_clean()
        return super().save(*args, **kwargs)


class GroupingCandidateRun(models.Model):
    class Status(models.TextChoices):
        BUILDING = "building", "生成中"
        READY = "ready", "可选择"
        BLOCKED = "blocked", "无法生成"
        FAILED = "failed", "生成失败"

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    decision_point = models.ForeignKey(
        GroupingDecisionPoint,
        on_delete=models.PROTECT,
        related_name="candidate_runs",
    )
    policy = models.ForeignKey(
        GroupingPolicyVersion,
        on_delete=models.PROTECT,
        related_name="candidate_runs",
    )
    algorithm_version = models.CharField(max_length=32)
    seed = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices)
    input_snapshot = models.JSONField(default=dict)
    input_hash = models.CharField(max_length=64, db_index=True)
    candidates = models.JSONField(default=list)
    conflict_explanations = models.JSONField(default=list, blank=True)
    candidate_count = models.PositiveSmallIntegerField(default=0)
    selected_candidate_key = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_grouping_candidate_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    objects = FrozenGroupingRecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["decision_point", "input_hash", "algorithm_version"],
                name="uniq_grouping_candidate_input",
            )
        ]
        ordering = ["-created_at", "-id"]

    IMMUTABLE_INPUT_FIELDS = (
        "decision_point_id",
        "policy_id",
        "algorithm_version",
        "seed",
        "input_snapshot",
        "input_hash",
        "created_by_id",
    )

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous:
            if any(
                getattr(previous, field) != getattr(self, field)
                for field in self.IMMUTABLE_INPUT_FIELDS
            ):
                raise ValidationError("分组候选运行的输入快照不可改写。")
            if previous.status == self.Status.BUILDING:
                if self.status not in {
                    self.Status.READY,
                    self.Status.BLOCKED,
                    self.Status.FAILED,
                }:
                    raise ValidationError("分组候选运行状态迁移不正确。")
                if self.finished_at is None:
                    raise ValidationError("分组候选运行结束时必须记录完成时间。")
            else:
                output_fields = (
                    "status",
                    "candidates",
                    "conflict_explanations",
                    "candidate_count",
                    "finished_at",
                )
                if any(
                    getattr(previous, field) != getattr(self, field)
                    for field in output_fields
                ):
                    raise ValidationError("已经完成的分组候选内容不可改写。")
                if previous.selected_candidate_key:
                    if self.selected_candidate_key != previous.selected_candidate_key:
                        raise ValidationError("分组候选只能由教师选择一次。")
                elif self.selected_candidate_key:
                    if self.selected_candidate_key not in {
                        str(item.get("key") or "") for item in self.candidates
                    }:
                        raise ValidationError("教师选择的分组候选不存在。")
        if previous or self.status != self.Status.BUILDING:
            self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("分组候选运行不可删除。")


class GroupingPlanVersion(models.Model):
    class Status(models.TextChoices):
        REVIEWED = "reviewed", "教师已复核"
        ACTIVE = "active", "已启用"
        CONFIRMED = "confirmed", "已确认（兼容）"
        ARCHIVED = "archived", "已归档"

    plan_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    decision_point = models.ForeignKey(
        GroupingDecisionPoint,
        on_delete=models.PROTECT,
        related_name="plans",
    )
    collaboration = models.ForeignKey(
        "courses.ClassroomGroupCollaboration",
        on_delete=models.PROTECT,
        related_name="plan_versions",
    )
    candidate_run = models.ForeignKey(
        GroupingCandidateRun,
        on_delete=models.PROTECT,
        related_name="plans",
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replacement_plans",
    )
    plan_version = models.PositiveIntegerField()
    candidate_key = models.CharField(max_length=64)
    assignments = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices)
    adjustment_note = models.CharField(max_length=500, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_grouping_plans",
    )
    confirmed_at = models.DateTimeField()
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activated_grouping_plans",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    notified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notified_grouping_plans",
    )
    notified_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = FrozenGroupingRecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["collaboration", "plan_version"],
                name="uniq_grouping_plan_version",
            ),
            models.UniqueConstraint(
                fields=["collaboration"],
                condition=models.Q(status="confirmed"),
                name="uniq_confirmed_grouping_plan",
            ),
            models.UniqueConstraint(
                fields=["collaboration"],
                condition=models.Q(status="active"),
                name="uniq_active_grouping_plan",
            ),
        ]
        ordering = ["-plan_version", "-id"]

    IMMUTABLE_PLAN_FIELDS = (
        "decision_point_id",
        "collaboration_id",
        "candidate_run_id",
        "supersedes_id",
        "plan_version",
        "candidate_key",
        "assignments",
        "adjustment_note",
        "confirmed_by_id",
        "confirmed_at",
    )

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous:
            if any(
                getattr(previous, field) != getattr(self, field)
                for field in self.IMMUTABLE_PLAN_FIELDS
            ):
                raise ValidationError("教师已复核的分组方案不可改写，请生成新版本。")
            allowed_status_transitions = {
                (self.Status.REVIEWED, self.Status.ACTIVE),
                (self.Status.ACTIVE, self.Status.ARCHIVED),
                (self.Status.CONFIRMED, self.Status.ARCHIVED),
            }
            if previous.status != self.status and (
                previous.status,
                self.status,
            ) not in allowed_status_transitions:
                raise ValidationError("分组方案状态迁移不正确。")
            if previous.activated_at and (
                self.activated_at != previous.activated_at
                or self.activated_by_id != previous.activated_by_id
            ):
                raise ValidationError("分组方案启用记录不可改写。")
            if previous.notified_at and (
                self.notified_at != previous.notified_at
                or self.notified_by_id != previous.notified_by_id
            ):
                raise ValidationError("学生通知记录不可改写。")
            if previous.archived_at and self.archived_at != previous.archived_at:
                raise ValidationError("分组方案归档记录不可改写。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("教师已复核的分组方案不可删除。")


class GroupingTeacherDecision(ImmutableGroupingRecord):
    class Action(models.TextChoices):
        ACCEPT = "accept", "采用"
        ADJUST = "adjust", "调整后采用"
        REGENERATE = "regenerate", "重新生成"
        MANUAL = "manual", "教师设置"

    candidate_run = models.ForeignKey(
        GroupingCandidateRun,
        on_delete=models.PROTECT,
        related_name="teacher_decisions",
    )
    plan = models.ForeignKey(
        GroupingPlanVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="teacher_decisions",
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    candidate_key = models.CharField(max_length=64, blank=True)
    adjustments = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=500, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="grouping_teacher_decisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class GroupingPairHistory(models.Model):
    school = models.ForeignKey(
        "school.School", on_delete=models.PROTECT, related_name="grouping_pair_history"
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="grouping_pair_history",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="grouping_pair_history",
    )
    left_student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="grouping_pairs_as_left",
    )
    right_student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="grouping_pairs_as_right",
    )
    collaboration_count = models.PositiveIntegerField(default=0)
    last_collaborated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["class_group", "subject", "left_student", "right_student"],
                name="uniq_grouping_pair_history",
            )
        ]
        indexes = [
            models.Index(fields=["class_group", "subject", "collaboration_count"])
        ]


class GroupingFairnessAudit(ImmutableGroupingRecord):
    class Status(models.TextChoices):
        PASSED = "passed", "通过"
        REVIEW = "review", "需要检查"
        BLOCKED = "blocked", "不能使用"

    candidate_run = models.ForeignKey(
        GroupingCandidateRun,
        on_delete=models.PROTECT,
        related_name="fairness_audits",
    )
    candidate_key = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices)
    metrics = models.JSONField(default=dict)
    blockers = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["candidate_run", "candidate_key"],
                name="uniq_grouping_candidate_fairness",
            )
        ]


class GroupingOpportunityAudit(ImmutableGroupingRecord):
    plan = models.ForeignKey(
        GroupingPlanVersion,
        on_delete=models.PROTECT,
        related_name="opportunity_audits",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="grouping_opportunity_audits",
    )
    group_no = models.PositiveSmallIntegerField()
    role = models.CharField(max_length=24, blank=True)
    opportunities = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "student"],
                name="uniq_grouping_plan_student_opportunity",
            )
        ]


class GroupingOutcomeSnapshot(ImmutableGroupingRecord):
    plan = models.ForeignKey(
        GroupingPlanVersion,
        on_delete=models.PROTECT,
        related_name="outcome_snapshots",
    )
    group_no = models.PositiveSmallIntegerField()
    group_result = models.JSONField(default=dict)
    individual_results = models.JSONField(default=list)
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "group_no", "observed_at"],
                name="uniq_grouping_outcome_snapshot",
            )
        ]
