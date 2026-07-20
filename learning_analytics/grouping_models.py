from __future__ import annotations

import hashlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


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
    class Trigger(models.TextChoices):
        LESSON_STEP = "lesson_step", "课堂环节"
        PROJECT_STAGE = "project_stage", "项目阶段"
        TEACHER_REQUEST = "teacher_request", "教师发起"

    class Status(models.TextChoices):
        OPEN = "open", "准备中"
        CANDIDATE_READY = "candidate_ready", "候选已生成"
        CONFIRMED = "confirmed", "已确认"
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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["decision_point", "input_hash", "algorithm_version"],
                name="uniq_grouping_candidate_input",
            )
        ]
        ordering = ["-created_at", "-id"]


class GroupingPlanVersion(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "已确认"
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
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
        ]
        ordering = ["-plan_version", "-id"]


class GroupingTeacherDecision(models.Model):
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


class GroupingFairnessAudit(models.Model):
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


class GroupingOpportunityAudit(models.Model):
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


class GroupingOutcomeSnapshot(models.Model):
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
