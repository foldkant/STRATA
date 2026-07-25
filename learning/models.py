import hashlib
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def student_work_upload_path(instance, filename: str) -> str:
    school_id = instance.school_id or "unknown"
    class_id = instance.class_group_id or "unknown"
    step_id = instance.lesson_step_id or "unknown"
    student_id = instance.student_id or "unknown"
    return f"student_work/school_{school_id}/class_{class_id}/step_{step_id}/student_{student_id}/{filename}"


def pretest_material_upload_path(instance, filename: str) -> str:
    """Build a server-controlled path without retaining the client path/name."""
    school_id = instance.material.school_id or "unknown"
    paper_version_id = instance.paper_version_id or "unknown"
    student_id = instance.student_id or "unknown"
    suffix = Path(filename).suffix.lower()[:12]
    return (
        f"pretest_materials/school_{school_id}/paper_version_{paper_version_id}/"
        f"student_{student_id}/{instance.attachment_id.hex}{suffix}"
    )


class LearningEvent(models.Model):
    class EventType(models.TextChoices):
        LOGIN = "login", "登录"
        PAGE_VIEW = "page_view", "页面访问"
        RESOURCE_VIEW = "resource_view", "资源查看"
        LESSON_ENTER = "lesson_enter", "进入课时"
        ANSWER_SUBMIT = "answer_submit", "提交答案"
        TASK_SUBMIT = "task_submit", "提交任务"
        PROJECT_SUBMIT = "project_submit", "提交项目"
        CHAT_MESSAGE = "chat_message", "聊天消息"
        QUESTION_ASK = "question_ask", "提问"
        QUESTION_ANSWER = "question_answer", "回答"
        TEACHER_INTERVENTION = "teacher_intervention", "教师干预"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_events",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, null=True, blank=True
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.SET_NULL, null=True, blank=True
    )
    lesson = models.ForeignKey(
        "courses.Lesson", on_delete=models.SET_NULL, null=True, blank=True
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    score = models.FloatField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["class_group", "occurred_at"]),
            models.Index(fields=["actor", "occurred_at"]),
            models.Index(fields=["event_type", "occurred_at"]),
        ]
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.actor_id}:{self.event_type}@{self.occurred_at:%Y-%m-%d %H:%M:%S}"


class StudentFeatureSnapshot(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feature_snapshots",
    )
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    features = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "window_start", "window_end"],
                name="uniq_feature_snapshot_window",
            )
        ]
        indexes = [
            models.Index(fields=["class_group", "window_end"]),
        ]


class StratificationDecision(models.Model):
    class DecisionKind(models.TextChoices):
        SUPPORT = "support", "学习支持"
        CONTENT_BAND = "content_band", "学习内容层级"
        LEGACY = "legacy", "兼容记录"

    class SupportPriority(models.TextChoices):
        ROUTINE = "routine", "常规关注"
        WATCH = "watch", "持续关注"
        HIGH = "high", "优先支持"

    class BoundaryBand(models.TextChoices):
        AB = "A/B", "A/B 边界"
        BC = "B/C", "B/C 边界"

    class Status(models.TextChoices):
        PENDING = "pending", "待教师确认"
        ACCEPTED = "accepted", "已采纳"
        KEPT = "kept", "保持当前安排"
        ADJUSTED = "adjusted", "教师已调整"
        DEFERRED = "deferred", "暂缓处理"
        REJECTED = "rejected", "已拒绝"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="layer_decisions",
    )
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, null=True, blank=True
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.PROTECT, null=True, blank=True
    )
    previous_layer = models.CharField(max_length=1)
    suggested_layer = models.CharField(max_length=1)
    confidence = models.FloatField(default=0)
    reasons = models.JSONField(default=list, blank=True)
    missing_data = models.JSONField(default=list, blank=True)
    learning_summary = models.JSONField(default=dict, blank=True)
    support_suggestion = models.TextField(blank=True)
    decision_kind = models.CharField(
        max_length=16,
        choices=DecisionKind.choices,
        default=DecisionKind.SUPPORT,
    )
    support_priority = models.CharField(
        max_length=16,
        choices=SupportPriority.choices,
        blank=True,
    )
    boundary_band = models.CharField(
        max_length=3,
        choices=BoundaryBand.choices,
        blank=True,
    )
    policy_version = models.CharField(max_length=32, default="support-policy-v2")
    policy = models.ForeignKey(
        "ContentBandPolicyVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decisions",
    )
    mastery_snapshot = models.ForeignKey(
        "StudentMasterySnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decisions",
    )
    abstain_reason = models.CharField(max_length=64, blank=True)
    transition_checks = models.JSONField(default=dict, blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    rule_version = models.CharField(max_length=96, default="transparent-rules-v1")
    teacher_selected_layer = models.CharField(max_length=1, blank=True)
    review_reason_code = models.CharField(max_length=32, blank=True)
    review_note = models.TextField(blank=True)
    model_version = models.ForeignKey(
        "aiops.ModelVersion", on_delete=models.SET_NULL, null=True, blank=True
    )
    calibration_run = models.ForeignKey(
        "learning_analytics.ClassCalibrationRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stratification_decisions",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_layer_decisions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course", "window_end", "rule_version"],
                name="uniq_stratification_suggestion_window",
            )
        ]
        indexes = [
            models.Index(fields=["class_group", "status", "created_at"]),
            models.Index(fields=["subject", "status", "created_at"]),
            models.Index(fields=["decision_kind", "status", "created_at"]),
        ]


class StudentSubjectBandQuerySet(models.QuerySet):
    """Keep applied content-band history append-only in ordinary ORM paths."""

    def update(self, **kwargs):
        raise ValidationError("已生效的学习内容层级记录不可批量修改。")

    def delete(self):
        raise ValidationError("已生效的学习内容层级记录不可批量删除。")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("已生效的学习内容层级记录不可批量修改。")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, **kwargs):
        raise ValidationError("学习内容层级记录必须逐项校验后保存。")

    def close_at(self, effective_at):
        """The only permitted bulk transition: close currently active rows."""
        if effective_at is None:
            raise ValidationError("学习内容层级安排的结束时间不能为空。")
        return models.QuerySet.update(
            self.filter(valid_until__isnull=True),
            valid_until=effective_at
        )


class StudentSubjectBand(models.Model):
    class Band(models.TextChoices):
        A = "A", "拓展挑战层"
        B = "B", "核心发展层"
        C = "C", "基础提升层"

    class BoundaryBand(models.TextChoices):
        AB = "A/B", "A/B 边界"
        BC = "B/C", "B/C 边界"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subject_bands",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="student_subject_bands",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="student_subject_bands",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="student_bands",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="student_bands",
    )
    band = models.CharField(max_length=1, choices=Band.choices)
    boundary_band = models.CharField(
        max_length=3,
        choices=BoundaryBand.choices,
        blank=True,
    )
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    source_decision = models.ForeignKey(
        StratificationDecision,
        on_delete=models.PROTECT,
        related_name="applied_bands",
    )
    policy_version = models.CharField(max_length=32)
    evidence_snapshot = models.JSONField(default=dict, blank=True)
    mastery_snapshot = models.ForeignKey(
        "StudentMasterySnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="applied_bands",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_student_subject_bands",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = StudentSubjectBandQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "subject"],
                condition=models.Q(course__isnull=True, valid_until__isnull=True),
                name="uniq_active_student_subject_band",
            ),
            models.UniqueConstraint(
                fields=["student", "subject", "course"],
                condition=models.Q(course__isnull=False, valid_until__isnull=True),
                name="uniq_active_student_course_band",
            ),
        ]
        indexes = [
            models.Index(fields=["student", "subject", "valid_from"]),
            models.Index(fields=["class_group", "subject", "valid_until"]),
        ]
        ordering = ["-valid_from", "-id"]

    IMMUTABLE_FIELDS = (
        "student_id",
        "school_id",
        "class_group_id",
        "subject_id",
        "course_id",
        "band",
        "boundary_band",
        "valid_from",
        "source_decision_id",
        "policy_version",
        "evidence_snapshot",
        "mastery_snapshot_id",
        "confirmed_by_id",
    )

    def clean(self):
        errors = {}
        if self.student_id and self.student.school_id != self.school_id:
            errors["student"] = "学生与学习内容层级记录的学校不一致。"
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "班级与学习内容层级记录的学校不一致。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与学习内容层级记录的学校不一致。"
        if self.course_id:
            if self.course.subject_id != self.subject_id:
                errors["course"] = "课程与学习内容层级记录的学科不一致。"
            elif self.course.subject.school_id != self.school_id:
                errors["course"] = "课程与学习内容层级记录的学校不一致。"
        if self.source_decision_id:
            decision = self.source_decision
            if decision.decision_kind != StratificationDecision.DecisionKind.CONTENT_BAND:
                errors["source_decision"] = "只有学习内容层级建议可以形成有效安排。"
            elif (
                decision.student_id != self.student_id
                or decision.class_group_id != self.class_group_id
                or decision.subject_id != self.subject_id
                or decision.course_id != self.course_id
            ):
                errors["source_decision"] = "层级安排范围与来源建议不一致。"
        if self.confirmed_by_id and self.confirmed_by.school_id != self.school_id:
            errors["confirmed_by"] = "确认教师与学习内容层级记录的学校不一致。"
        if self.valid_until and self.valid_until <= self.valid_from:
            errors["valid_until"] = "结束时间必须晚于生效时间。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original:
                if any(
                    getattr(original, field) != getattr(self, field)
                    for field in self.IMMUTABLE_FIELDS
                ):
                    raise ValidationError(
                        "已生效的学习内容层级记录不可改写；请追加新的安排版本。"
                    )
                if original.valid_until is not None or self.valid_until is None:
                    raise ValidationError(
                        "已生效的学习内容层级记录只允许关闭一次。"
                    )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已生效的学习内容层级记录不可删除。")


class ContentBandPolicyVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        RETIRED = "retired", "停用"

    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="content_band_policies",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="content_band_policies",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="content_band_policies",
    )
    name = models.CharField(max_length=128)
    version_no = models.PositiveIntegerField(default=1)
    policy_version = models.CharField(max_length=32)
    a_min = models.FloatField(default=0.8)
    b_min = models.FloatField(default=0.6)
    boundary_margin = models.FloatField(default=0.03)
    hysteresis_margin = models.FloatField(default=0.03)
    max_measurement_error = models.FloatField(default=0.18)
    min_common_items = models.PositiveSmallIntegerField(default=5)
    min_answered_ratio = models.FloatField(default=0.8)
    required_consecutive_windows = models.PositiveSmallIntegerField(default=2)
    cooldown_days = models.PositiveSmallIntegerField(default=14)
    max_step_change = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    content_hash = models.CharField(max_length=64, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_content_band_policies",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_content_band_policies",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "version_no"],
                condition=models.Q(course__isnull=True),
                name="uniq_subject_band_policy_version",
            ),
            models.UniqueConstraint(
                fields=["school", "subject", "course", "version_no"],
                condition=models.Q(course__isnull=False),
                name="uniq_course_band_policy_version",
            ),
            models.UniqueConstraint(
                fields=["school", "subject"],
                condition=models.Q(course__isnull=True, status="active"),
                name="uniq_active_subject_band_policy",
            ),
            models.UniqueConstraint(
                fields=["school", "subject", "course"],
                condition=models.Q(course__isnull=False, status="active"),
                name="uniq_active_course_band_policy",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "status"]),
            models.Index(fields=["course", "status", "version_no"]),
        ]
        ordering = ["subject_id", "course_id", "-version_no", "-id"]

    def semantic_definition(self) -> dict:
        return {
            "school_id": self.school_id,
            "subject_id": self.subject_id,
            "course_id": self.course_id,
            "version_no": self.version_no,
            "policy_version": self.policy_version,
            "a_min": self.a_min,
            "b_min": self.b_min,
            "boundary_margin": self.boundary_margin,
            "hysteresis_margin": self.hysteresis_margin,
            "max_measurement_error": self.max_measurement_error,
            "min_common_items": self.min_common_items,
            "min_answered_ratio": self.min_answered_ratio,
            "required_consecutive_windows": self.required_consecutive_windows,
            "cooldown_days": self.cooldown_days,
            "max_step_change": self.max_step_change,
        }

    def clean(self):
        errors = {}
        if self.course_id and self.course.subject_id != self.subject_id:
            errors["course"] = "课程与学科不一致。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与学校不一致。"
        if not 0 <= self.b_min < self.a_min <= 1:
            errors["a_min"] = "层级标准必须满足 0 <= B < A <= 1。"
        for field in (
            "boundary_margin",
            "hysteresis_margin",
            "max_measurement_error",
            "min_answered_ratio",
        ):
            if not 0 <= getattr(self, field) <= 1:
                errors[field] = "该值必须在 0 至 1 之间。"
        if self.max_step_change != 1:
            errors["max_step_change"] = "当前正式策略只允许单次调整一个层级。"
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
                raise ValidationError("已启用的层级标准不能原地修改，请创建新版本。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} v{self.version_no}"


class StudentMasterySnapshot(models.Model):
    class DataStatus(models.TextChoices):
        AVAILABLE = "available", "可用"
        INSUFFICIENT = "insufficient", "数据不足"
        NOT_COMPARABLE = "not_comparable", "不可比较"
        PENDING_GRADING = "pending_grading", "等待评分"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mastery_snapshots",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="student_mastery_snapshots",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="student_mastery_snapshots",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="student_mastery_snapshots",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_mastery_snapshots",
    )
    assessment = models.ForeignKey(
        "TestAssessment",
        on_delete=models.PROTECT,
        related_name="mastery_snapshots",
    )
    attempt = models.ForeignKey(
        "TestAttempt",
        on_delete=models.PROTECT,
        related_name="mastery_snapshots",
    )
    common_question_set = models.ForeignKey(
        "CommonQuestionSet",
        on_delete=models.PROTECT,
        related_name="mastery_snapshots",
    )
    measurement_series = models.CharField(max_length=96, db_index=True)
    assessment_version = models.CharField(max_length=32)
    data_status = models.CharField(max_length=24, choices=DataStatus.choices)
    score_obtained = models.FloatField(default=0)
    score_max = models.FloatField(default=0)
    mastery_score = models.FloatField(null=True, blank=True)
    measurement_error = models.FloatField(null=True, blank=True)
    common_item_count = models.PositiveIntegerField(default=0)
    answered_item_count = models.PositiveIntegerField(default=0)
    answered_ratio = models.FloatField(default=0)
    knowledge_results = models.JSONField(default=list, blank=True)
    comparability_evidence = models.JSONField(default=dict, blank=True)
    source_hash = models.CharField(max_length=64, db_index=True)
    legacy_unmapped = models.BooleanField(default=True)
    is_test_data = models.BooleanField(default=False)
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "source_hash"],
                name="uniq_mastery_attempt_source_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["student", "subject", "observed_at"]),
            models.Index(fields=["school", "subject", "data_status"]),
            models.Index(fields=["measurement_series", "assessment_version"]),
        ]
        ordering = ["-observed_at", "-id"]

    def __str__(self) -> str:
        return f"{self.student_id}:{self.measurement_series}:{self.assessment_version}"

    def clean(self):
        errors = {}
        if self.attempt_id:
            if self.attempt.student_id != self.student_id:
                errors["student"] = "掌握情况快照学生与作答学生不一致。"
            if self.attempt.assessment_id != self.assessment_id:
                errors["assessment"] = "掌握情况快照测试与作答测试不一致。"
            if self.attempt.class_group_id != self.class_group_id:
                errors["class_group"] = "掌握情况快照班级与作答班级不一致。"
        if self.assessment_id:
            if self.assessment.school_id != self.school_id:
                errors["school"] = "掌握情况快照学校与测试不一致。"
            if self.assessment.subject_id != self.subject_id:
                errors["subject"] = "掌握情况快照学科与测试不一致。"
            if self.assessment.course_id != self.course_id:
                errors["course"] = "掌握情况快照课程与测试不一致。"
            if self.assessment.common_question_set_id != self.common_question_set_id:
                errors["common_question_set"] = "掌握情况快照共同题版本与测试不一致。"
        for field in ("mastery_score", "measurement_error", "answered_ratio"):
            value = getattr(self, field)
            if value is not None and not 0 <= float(value) <= 1:
                errors[field] = "该值必须位于 0 至 1 之间。"
        if self.score_obtained < 0 or self.score_max < 0:
            errors["score_obtained"] = "得分与满分不能为负数。"
        elif self.score_obtained > self.score_max:
            errors["score_obtained"] = "得分不能超过满分。"
        if self.answered_item_count > self.common_item_count:
            errors["answered_item_count"] = "已作答共同题数量不能超过共同题总数。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("学生共同测试掌握情况快照不可修改；重新评分应追加新版本。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("学生共同测试掌握情况快照不可删除。")


class StudentMasteryTargetResult(models.Model):
    """One immutable estimate for one exact curriculum-aligned target version."""

    snapshot = models.ForeignKey(
        StudentMasterySnapshot,
        on_delete=models.PROTECT,
        related_name="target_results",
    )
    learning_target_version = models.ForeignKey(
        "learning_analytics.LearningTargetVersion",
        on_delete=models.PROTECT,
        related_name="student_mastery_results",
    )
    data_status = models.CharField(
        max_length=24,
        choices=StudentMasterySnapshot.DataStatus.choices,
    )
    score_obtained = models.FloatField(default=0)
    score_max = models.FloatField(default=0)
    mastery_score = models.FloatField(null=True, blank=True)
    measurement_error = models.FloatField(null=True, blank=True)
    item_count = models.PositiveIntegerField(default=0)
    answered_item_count = models.PositiveIntegerField(default=0)
    evidence_coverage = models.FloatField(default=0)
    evidence_snapshot = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "learning_target_version"],
                name="uniq_mastery_snapshot_target_version",
            ),
        ]
        indexes = [
            models.Index(fields=["learning_target_version", "data_status"]),
            models.Index(fields=["snapshot", "data_status"]),
        ]
        ordering = ["snapshot_id", "learning_target_version_id"]

    def semantic_content(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_source_hash": self.snapshot.source_hash,
            "learning_target_version_id": self.learning_target_version_id,
            "learning_target_content_hash": self.learning_target_version.content_hash,
            "data_status": self.data_status,
            "score_obtained": self.score_obtained,
            "score_max": self.score_max,
            "mastery_score": self.mastery_score,
            "measurement_error": self.measurement_error,
            "item_count": self.item_count,
            "answered_item_count": self.answered_item_count,
            "evidence_coverage": self.evidence_coverage,
            "evidence_snapshot": self.evidence_snapshot,
        }

    def clean(self):
        errors = {}
        snapshot = self.snapshot
        version = self.learning_target_version
        target = version.target
        if version.alignment_status != "complete" or not version.curriculum_alignments.exists():
            errors["learning_target_version"] = "正式掌握结果必须对应课标依据完整的学习目标版本。"
        if target.school_id != snapshot.school_id:
            errors["learning_target_version"] = "学习目标版本与快照学校不一致。"
        elif target.subject_id != snapshot.subject_id:
            errors["learning_target_version"] = "学习目标版本与快照学科不一致。"
        elif target.course_id != snapshot.course_id:
            errors["learning_target_version"] = "学习目标版本与快照课程不一致。"
        for field in ("mastery_score", "measurement_error", "evidence_coverage"):
            value = getattr(self, field)
            if value is not None and not 0 <= float(value) <= 1:
                errors[field] = "该值必须位于 0 至 1 之间。"
        if self.item_count <= 0:
            errors["item_count"] = "目标级掌握结果必须包含至少一道共同题。"
        if self.answered_item_count > self.item_count:
            errors["answered_item_count"] = "已作答题数不能超过目标共同题数。"
        if self.score_obtained < 0 or self.score_max < 0 or self.score_obtained > self.score_max:
            errors["score_obtained"] = "目标级得分与满分不正确。"
        elif self.data_status == StudentMasterySnapshot.DataStatus.AVAILABLE and self.score_max <= 0:
            errors["score_max"] = "可用目标级掌握结果必须包含大于 0 的已作答题目满分。"
        if self.data_status != StudentMasterySnapshot.DataStatus.AVAILABLE:
            if self.mastery_score is not None or self.measurement_error is not None:
                errors["mastery_score"] = "材料不可比较、待评分或不足时不能形成目标水平估计。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("目标级掌握结果不可修改；重新评分应追加新快照。")
        self.content_hash = hashlib.sha256(
            json.dumps(
                self.semantic_content(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("目标级掌握结果不可删除。")


class BandTransitionAudit(models.Model):
    decision = models.ForeignKey(
        StratificationDecision,
        on_delete=models.PROTECT,
        related_name="transition_audits",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="band_transition_audits",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="band_transition_audits",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="band_transition_audits",
    )
    previous_band = models.CharField(max_length=1, blank=True)
    raw_candidate_band = models.CharField(max_length=1, blank=True)
    guarded_candidate_band = models.CharField(max_length=1, blank=True)
    checks = models.JSONField(default=dict)
    action = models.CharField(max_length=24)
    final_band = models.CharField(max_length=1, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_band_transition_audits",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "subject", "created_at"]),
            models.Index(fields=["decision", "action"]),
        ]
        ordering = ["-created_at", "-id"]


class StudentLearningTargetStateVersion(models.Model):
    # Versioned engineering exclusion gate for candidate dataset review.  It
    # is not a validated psychometric standard and must not authorize training.
    TRAINING_CANDIDATE_UNCERTAINTY_POLICY = "conservative-proxy-gate-v1"
    TRAINING_CANDIDATE_MAX_UNCERTAINTY = 0.2

    class EvidenceStatus(models.TextChoices):
        AVAILABLE = "available", "材料可用"
        PARTIAL = "partial", "材料部分可用"
        INSUFFICIENT = "insufficient", "材料不足"
        PENDING_REVIEW = "pending_review", "等待评价"
        NOT_OBSERVED = "not_observed", "未形成观察"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="learning_target_state_versions",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="learning_target_state_versions",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="learning_target_state_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="learning_target_state_versions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="learning_target_state_versions",
    )
    learning_target_version = models.ForeignKey(
        "learning_analytics.LearningTargetVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="student_learning_states",
    )
    mastery_target_result = models.ForeignKey(
        StudentMasteryTargetResult,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="learning_target_states",
    )
    legacy_unmapped = models.BooleanField(default=True)
    learning_target_code = models.CharField(max_length=96)
    learning_target_name = models.CharField(max_length=300)
    source_type = models.CharField(max_length=48)
    source_id = models.CharField(max_length=96)
    source_version = models.CharField(max_length=96)
    evidence_status = models.CharField(
        max_length=24,
        choices=EvidenceStatus.choices,
    )
    evidence_coverage = models.FloatField(default=0)
    estimate = models.FloatField(null=True, blank=True)
    uncertainty = models.FloatField(null=True, blank=True)
    material_references = models.JSONField(default=list, blank=True)
    observation_notes = models.JSONField(default=list, blank=True)
    is_initial_diagnostic = models.BooleanField(default=False)
    observed_at = models.DateTimeField()
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "student",
                    "subject",
                    "learning_target_code",
                    "source_type",
                    "source_id",
                    "source_version",
                ],
                condition=models.Q(course__isnull=True),
                name="uniq_subject_target_state_source_version",
            ),
            models.UniqueConstraint(
                fields=[
                    "student",
                    "subject",
                    "course",
                    "learning_target_code",
                    "source_type",
                    "source_id",
                    "source_version",
                ],
                condition=models.Q(course__isnull=False),
                name="uniq_course_target_state_source_version",
            ),
        ]
        indexes = [
            models.Index(fields=["student", "subject", "observed_at"]),
            models.Index(fields=["class_group", "subject", "evidence_status"]),
            models.Index(fields=["learning_target_code", "observed_at"]),
        ]
        ordering = ["-observed_at", "-id"]

    def semantic_content(self):
        payload = {
            "student_id": self.student_id,
            "school_id": self.school_id,
            "class_group_id": self.class_group_id,
            "subject_id": self.subject_id,
            "course_id": self.course_id,
            "learning_target_version_id": self.learning_target_version_id,
            "legacy_unmapped": self.legacy_unmapped,
            "learning_target_code": self.learning_target_code,
            "learning_target_name": self.learning_target_name,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "evidence_status": self.evidence_status,
            "evidence_coverage": self.evidence_coverage,
            "estimate": self.estimate,
            "uncertainty": self.uncertainty,
            "material_references": self.material_references,
            "observation_notes": self.observation_notes,
            "is_initial_diagnostic": self.is_initial_diagnostic,
            "observed_at": self.observed_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
        }
        # Preserve pre-0026 and non-common state hashes exactly.  The new key
        # is part of the semantic payload only when exact mastery provenance
        # actually exists.
        if self.mastery_target_result_id is not None:
            payload["mastery_target_result_id"] = self.mastery_target_result_id
        return payload

    @classmethod
    def formal_training_queryset(cls):
        """Return conservative candidates for a human-approved frozen dataset.

        This selector is not authorization to train a model and does not claim
        psychometric calibration.  It only admits current target states whose
        immutable common-assessment result and snapshot provenance are intact;
        a separate reviewed dataset version must still be approved and frozen.
        """

        return cls.objects.filter(
            school__is_synthetic=False,
            legacy_unmapped=False,
            is_initial_diagnostic=False,
            source_type="common_assessment",
            mastery_target_result__isnull=False,
            mastery_target_result__data_status=StudentMasterySnapshot.DataStatus.AVAILABLE,
            mastery_target_result__mastery_score__isnull=False,
            mastery_target_result__measurement_error__isnull=False,
            mastery_target_result__measurement_error__lte=cls.TRAINING_CANDIDATE_MAX_UNCERTAINTY,
            mastery_target_result__snapshot__is_test_data=False,
            mastery_target_result__snapshot__legacy_unmapped=False,
            mastery_target_result__snapshot__data_status=StudentMasterySnapshot.DataStatus.AVAILABLE,
            mastery_target_result__snapshot__mastery_score__isnull=False,
            mastery_target_result__snapshot__measurement_error__isnull=False,
            mastery_target_result__snapshot__measurement_error__lte=cls.TRAINING_CANDIDATE_MAX_UNCERTAINTY,
            mastery_target_result__snapshot__comparability_evidence__target_mapping_status="complete",
            mastery_target_result__snapshot__comparability_evidence__comparability_status__in=[
                "verified",
                "comparable",
            ],
            learning_target_version__isnull=False,
            learning_target_version__alignment_status="complete",
            learning_target_version__curriculum_alignments__isnull=False,
            evidence_status__in={
                cls.EvidenceStatus.AVAILABLE,
                cls.EvidenceStatus.PARTIAL,
            },
            estimate__isnull=False,
            uncertainty__isnull=False,
            uncertainty__lte=cls.TRAINING_CANDIDATE_MAX_UNCERTAINTY,
            valid_until__gt=timezone.now(),
        ).distinct()

    def clean(self):
        errors = {}
        for field_name in ("evidence_coverage", "estimate", "uncertainty"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                errors[field_name] = "该值必须在 0 至 1 之间。"
        if self.valid_until and self.valid_from and self.valid_until <= self.valid_from:
            errors["valid_until"] = "有效期结束时间必须晚于开始时间。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与学校不一致。"
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "班级与学校不一致。"
        if self.student_id and self.student.school_id != self.school_id:
            errors["student"] = "学生与学校不一致。"
        if self.course_id:
            if self.course.subject_id != self.subject_id:
                errors["course"] = "课程与学科不一致。"
            elif self.course.subject.school_id != self.school_id:
                errors["course"] = "课程与学校不一致。"
        if self.learning_target_version_id:
            version = self.learning_target_version
            target = version.target
            if self.legacy_unmapped:
                errors["legacy_unmapped"] = "已绑定学习目标版本的记录不能标记为历史未映射。"
            if version.alignment_status != "complete" or not version.curriculum_alignments.exists():
                errors["learning_target_version"] = "正式学习情况必须对应课标依据完整的学习目标版本。"
            if target.school_id != self.school_id:
                errors["learning_target_version"] = "学习目标版本与学校范围不一致。"
            elif target.subject_id != self.subject_id:
                errors["learning_target_version"] = "学习目标版本与学科范围不一致。"
            elif target.course_id != self.course_id:
                errors["learning_target_version"] = "学习目标版本与课程范围不一致。"
            if version.code != self.learning_target_code:
                errors["learning_target_code"] = "学习目标代码与冻结版本不一致。"
            if version.title != self.learning_target_name:
                errors["learning_target_name"] = "学习目标名称与冻结版本不一致。"
            if self.valid_until is None:
                errors["valid_until"] = "正式学习目标情况必须设置材料有效期。"
        elif not self.legacy_unmapped:
            errors["learning_target_version"] = "正式学习情况必须绑定不可变学习目标版本。"
        if self.mastery_target_result_id:
            result = self.mastery_target_result
            snapshot = result.snapshot
            if self.source_type != "common_assessment":
                errors["mastery_target_result"] = "共同测试目标结果只能用于共同测试学习情况。"
            if self.source_id != str(result.id) or self.source_version != result.content_hash:
                errors["mastery_target_result"] = "学习情况来源标识必须与不可变目标结果一致。"
            if self.learning_target_version_id != result.learning_target_version_id:
                errors["mastery_target_result"] = "学习情况与共同测试目标结果的学习目标版本不一致。"
            if self.student_id != snapshot.student_id:
                errors["mastery_target_result"] = "学习情况与共同测试目标结果的学生不一致。"
            if self.school_id != snapshot.school_id or self.class_group_id != snapshot.class_group_id:
                errors["mastery_target_result"] = "学习情况与共同测试目标结果的学校或班级不一致。"
            if self.subject_id != snapshot.subject_id or self.course_id != snapshot.course_id:
                errors["mastery_target_result"] = "学习情况与共同测试目标结果的学科或课程不一致。"
        elif self.source_type == "common_assessment" and not self.legacy_unmapped:
            errors["mastery_target_result"] = "新形成的共同测试学习情况必须绑定不可变目标结果。"
        if self.evidence_status in {self.EvidenceStatus.INSUFFICIENT, self.EvidenceStatus.NOT_OBSERVED}:
            if self.estimate is not None:
                errors["estimate"] = "材料不足或未形成观察时不能生成水平估计。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("学习目标情况版本不可修改，请生成新版本。")
        self.content_hash = hashlib.sha256(
            json.dumps(
                self.semantic_content(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("学习目标情况版本不可删除。")


class LearningSupportRecommendation(models.Model):
    class Priority(models.TextChoices):
        ROUTINE = "routine", "常规支持"
        WATCH = "watch", "持续关注"
        PRIORITY = "priority", "优先支持"

    class Status(models.TextChoices):
        PENDING = "pending", "待教师确认"
        CONFIRMED = "confirmed", "已确认"
        ADJUSTED = "adjusted", "教师已调整"
        DEFERRED = "deferred", "暂缓安排"

    target_state = models.ForeignKey(
        StudentLearningTargetStateVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="support_recommendations",
    )
    source_decision = models.OneToOneField(
        StratificationDecision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="support_recommendation",
    )
    priority = models.CharField(max_length=16, choices=Priority.choices)
    suggestion = models.TextField()
    rationale = models.JSONField(default=list, blank=True)
    source_summary = models.ForeignKey(
        "learning_analytics.StudentLearningSummary",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="support_recommendations",
    )
    source_summary_hash = models.CharField(max_length=64, blank=True)
    evidence_snapshot = models.JSONField(default=dict, blank=True)
    source_hash = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_learning_support_recommendations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target_state"],
                condition=models.Q(target_state__isnull=False),
                name="uniq_support_recommendation_target_state",
            ),
        ]

    IMMUTABLE_EVIDENCE_FIELDS = (
        "target_state_id",
        "source_decision_id",
        "source_summary_id",
        "source_summary_hash",
        "evidence_snapshot",
        "source_hash",
        "priority",
        "suggestion",
        "rationale",
    )

    def clean(self):
        errors = {}
        if self.target_state_id is None:
            if self.source_summary_id is None:
                errors["source_summary"] = "描述性学习支持建议必须冻结学习汇总版本。"
            if not self.source_summary_hash or not self.source_hash:
                errors["source_hash"] = "描述性学习支持建议必须冻结材料校验值。"
            if not isinstance(self.evidence_snapshot, dict) or not self.evidence_snapshot:
                errors["evidence_snapshot"] = "描述性学习支持建议必须冻结材料快照。"
            elif self.evidence_snapshot.get("learning_target_estimate") is not None:
                errors["evidence_snapshot"] = "未经标定的描述性材料不能形成学习目标水平估计。"
        if self.source_summary_id:
            if self.source_summary.source_hash != self.source_summary_hash:
                errors["source_summary_hash"] = "学习汇总校验值与冻结版本不一致。"
            if self.source_decision_id:
                if self.source_summary.student_id != self.source_decision.student_id:
                    errors["source_summary"] = "学习汇总学生与支持建议学生不一致。"
                if self.source_summary.course_id != self.source_decision.course_id:
                    errors["source_summary"] = "学习汇总课程与支持建议课程不一致。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and any(
                getattr(original, field) != getattr(self, field)
                for field in self.IMMUTABLE_EVIDENCE_FIELDS
            ):
                raise ValidationError("学习支持建议的来源材料不可改写；请生成新建议版本。")
        self.full_clean()
        return super().save(*args, **kwargs)


class LearningContentRecommendation(models.Model):
    class Status(models.TextChoices):
        NOT_RECOMMENDED = "not_recommended", "暂不建议"
        PENDING = "pending", "待教师确认"
        CONFIRMED = "confirmed", "已确认"
        KEPT = "kept", "保持当前安排"
        ADJUSTED = "adjusted", "教师已调整"

    target_state = models.ForeignKey(
        StudentLearningTargetStateVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="content_recommendations",
    )
    source_decision = models.OneToOneField(
        StratificationDecision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="content_recommendation",
    )
    suggested_band = models.CharField(max_length=1, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices)
    rationale = models.JSONField(default=list, blank=True)
    evidence_coverage = models.FloatField(default=0)
    uncertainty = models.FloatField(null=True, blank=True)
    teacher_selected_band = models.CharField(max_length=1, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_learning_content_recommendations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    target_states = models.ManyToManyField(
        StudentLearningTargetStateVersion,
        through="LearningContentRecommendationTargetState",
        related_name="content_recommendation_evidence",
    )

    IMMUTABLE_EVIDENCE_FIELDS = (
        "target_state_id",
        "source_decision_id",
        "suggested_band",
        "rationale",
        "evidence_coverage",
        "uncertainty",
    )

    def clean(self):
        errors = {}
        if self.suggested_band and self.target_state_id is None:
            errors["target_state"] = "学习内容层级候选必须对应目标级学习情况。"
        if self.target_state_id and self.target_state.legacy_unmapped:
            errors["target_state"] = "历史未映射学习情况不能用于正式内容层级建议。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and any(
                getattr(original, field) != getattr(self, field)
                for field in self.IMMUTABLE_EVIDENCE_FIELDS
            ):
                raise ValidationError("学习内容层级建议的目标依据不可改写；请生成新建议版本。")
        self.full_clean()
        return super().save(*args, **kwargs)


class LearningContentRecommendationTargetState(models.Model):
    recommendation = models.ForeignKey(
        LearningContentRecommendation,
        on_delete=models.PROTECT,
        related_name="target_state_links",
    )
    target_state = models.ForeignKey(
        StudentLearningTargetStateVersion,
        on_delete=models.PROTECT,
        related_name="content_recommendation_links",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recommendation", "target_state"],
                name="uniq_content_recommendation_target_state",
            ),
            models.UniqueConstraint(
                fields=["recommendation", "sort_order"],
                name="uniq_content_recommendation_target_order",
            ),
        ]
        ordering = ["recommendation_id", "sort_order", "id"]

    def clean(self):
        if (
            self.recommendation.target_state_id
            and self.sort_order == 0
            and self.recommendation.target_state_id != self.target_state_id
        ):
            raise ValidationError("首个目标依据必须与建议的兼容主目标一致。")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("内容层级建议与目标情况的关系不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("内容层级建议与目标情况的关系不可删除。")


class PretestPaper(models.Model):
    class Kind(models.TextChoices):
        LITERACY = "literacy", "学科学习诊断"
        ATTITUDE = "attitude", "学习支持问卷"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        ARCHIVED = "archived", "归档"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="pretest_papers"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="pretest_papers"
    )
    title = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    version = models.PositiveIntegerField(default=1)
    introduction = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pretest_papers",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "kind", "version"],
                name="uniq_pretest_paper_version_per_subject_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "kind", "status"]),
        ]
        ordering = ["subject__name", "kind", "-version", "-created_at"]

    def __str__(self) -> str:
        return f"{self.subject} - {self.get_kind_display()} v{self.version}"


class PretestQuestion(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE = "single", "单选"
        MULTIPLE = "multiple", "多选"
        SCALE = "scale", "量表"
        TEXT = "text", "简答"
        PERFORMANCE = "performance", "表现任务"
        OPERATION = "operation", "操作任务"
        SHORT_PROJECT = "short_project", "短项目"

    paper = models.ForeignKey(
        PretestPaper, on_delete=models.CASCADE, related_name="questions"
    )
    stem = models.TextField()
    question_type = models.CharField(
        max_length=16, choices=QuestionType.choices, default=QuestionType.SINGLE
    )
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    score = models.FloatField(default=0)
    dimension = models.CharField(max_length=64, blank=True)
    learning_target_code = models.CharField(max_length=96, blank=True)
    learning_target_name = models.CharField(max_length=300, blank=True)
    learning_target_version = models.ForeignKey(
        "learning_analytics.LearningTargetVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pretest_questions",
    )
    legacy_unmapped = models.BooleanField(default=True)
    material_requirements = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["paper_id", "sort_order", "id"]
        indexes = [
            models.Index(fields=["paper", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.stem[:48]


class ImmutableDiagnosticRecordQuerySet(models.QuerySet):
    """Prevent ordinary ORM bulk operations from bypassing model immutability."""

    def update(self, **kwargs):
        raise ValidationError("已冻结的诊断事实不可批量修改。")

    def delete(self):
        raise ValidationError("已冻结的诊断事实不可批量删除。")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("已冻结的诊断事实不可批量修改。")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, **kwargs):
        raise ValidationError("已冻结的诊断事实必须逐项校验后保存。")


class PretestPaperVersion(models.Model):
    source = models.ForeignKey(
        PretestPaper,
        on_delete=models.PROTECT,
        related_name="published_versions",
    )
    version_no = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    title = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=PretestPaper.Kind.choices)
    introduction = models.TextField(blank=True)
    question_snapshot = models.JSONField(default=list)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_pretest_versions",
    )
    published_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableDiagnosticRecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "version_no"],
                name="uniq_pretest_source_version",
            ),
            models.UniqueConstraint(
                fields=["source", "content_hash"],
                name="uniq_pretest_source_content_hash",
            ),
        ]
        ordering = ["source_id", "-version_no"]

    def semantic_content(self):
        return {
            "source_id": self.source_id,
            "version_no": self.version_no,
            "title": self.title,
            "kind": self.kind,
            "introduction": self.introduction,
            "question_snapshot": self.question_snapshot,
        }

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("已发布的学习起点诊断版本不可修改。")
        self.content_hash = hashlib.sha256(
            json.dumps(
                self.semantic_content(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已发布的学习起点诊断版本不可删除。")


class PretestSubmission(models.Model):
    class OpportunityStatus(models.TextChoices):
        OBSERVED = "observed", "已获得评价机会"
        MISSING = "missing", "材料缺失"
        DEVICE_ISSUE = "device_issue", "设备问题"
        NOT_OFFERED = "not_offered", "未获得评价机会"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pretest_submissions",
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="pretest_submissions"
    )
    paper = models.ForeignKey(
        PretestPaper, on_delete=models.PROTECT, related_name="submissions"
    )
    paper_version = models.ForeignKey(
        PretestPaperVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submissions",
    )
    administration = models.ForeignKey(
        "learning.DiagnosticAdministration",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submissions",
    )
    attempt_no = models.PositiveSmallIntegerField(default=1)
    idempotency_key = models.CharField(max_length=128, blank=True)
    answers = models.JSONField(default=dict, blank=True)
    score = models.FloatField(null=True, blank=True)
    opportunity_status = models.CharField(
        max_length=24,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.OBSERVED,
    )
    task_statuses = models.JSONField(default=dict, blank=True)
    target_results = models.JSONField(default=list, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableDiagnosticRecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "paper", "attempt_no"],
                condition=models.Q(administration__isnull=True),
                name="uniq_pretest_legacy_attempt",
            ),
            models.UniqueConstraint(
                fields=["administration", "student", "attempt_no"],
                condition=models.Q(administration__isnull=False),
                name="uniq_pretest_admin_attempt",
            ),
            models.UniqueConstraint(
                fields=["administration", "student", "idempotency_key"],
                condition=models.Q(
                    administration__isnull=False,
                    idempotency_key__gt="",
                ),
                name="uniq_pretest_admin_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["subject", "submitted_at"]),
            models.Index(fields=["student", "subject"]),
            models.Index(fields=["administration", "student"]),
        ]

    def clean(self):
        errors = {}
        if self.paper_id and self.subject_id and self.paper.subject_id != self.subject_id:
            errors["subject"] = "诊断提交学科必须与诊断工具学科一致。"
        if self.paper_version_id:
            if self.paper_version.source_id != self.paper_id:
                errors["paper_version"] = "诊断提交版本不属于所选诊断工具。"
            elif self.paper_version.kind != self.paper.kind:
                errors["paper_version"] = "诊断提交版本类型与诊断工具不一致。"
        if self.student_id and self.paper_id:
            if self.student.school_id != self.paper.school_id:
                errors["student"] = "学生与诊断工具学校范围不一致。"
        if self.administration_id:
            administration = self.administration
            if administration.school_id != self.paper.school_id:
                errors["administration"] = "诊断实施批次与诊断工具学校不一致。"
            elif administration.subject_id != self.subject_id:
                errors["administration"] = "诊断实施批次与提交学科不一致。"
            elif administration.paper_version_id != self.paper_version_id:
                errors["administration"] = "提交必须使用诊断实施批次冻结的版本。"
            if administration.paper_version.source_id != self.paper_id:
                errors["paper"] = "提交诊断工具与实施批次冻结版本不一致。"
            if not self.idempotency_key.strip():
                errors["idempotency_key"] = "诊断实施批次提交必须携带幂等标识。"
        if self.attempt_no <= 0:
            errors["attempt_no"] = "尝试序号必须大于 0。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("学习起点诊断提交不可修改。")
        if self.opportunity_status != self.OpportunityStatus.OBSERVED:
            self.score = None
            normalized_results = []
            for item in self.target_results:
                if not isinstance(item, dict):
                    continue
                normalized = {
                    **item,
                    "evidence_status": "not_observed",
                    "estimate": None,
                    "mastery_score": None,
                    "measurement_error": None,
                    "uncertainty": None,
                    "score": None,
                    "score_obtained": None,
                    "earned_score": None,
                    # A submission-level fallback must not erase a more
                    # specific per-target/per-task exception.  Mixed reports
                    # (for example one missing material and one device issue)
                    # remain distinguishable for later review.
                    "reason": item.get("reason") or self.opportunity_status,
                }
                normalized_results.append(normalized)
            self.target_results = normalized_results
        payload = {
            "student_id": self.student_id,
            "administration_id": self.administration_id,
            "idempotency_key": self.idempotency_key,
            "paper_version_id": self.paper_version_id,
            "attempt_no": self.attempt_no,
            "answers": self.answers,
            "opportunity_status": self.opportunity_status,
            "task_statuses": self.task_statuses,
            "target_results": self.target_results,
        }
        self.content_hash = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("学习起点诊断提交不可删除。")


class UnifiedAssessmentMaterial(models.Model):
    class Ownership(models.TextChoices):
        INDIVIDUAL = "individual", "个人评价材料"
        GROUP = "group", "小组评价材料"

    class MaterialType(models.TextChoices):
        ANSWER = "answer", "作答记录"
        ARTIFACT = "artifact", "作品材料"
        OPERATION = "operation", "操作记录"
        ORAL_DEFENSE = "oral_defense", "答辩记录"
        OBSERVATION = "observation", "观察记录"
        SCORE = "score", "评分记录"

    class MaterialStatus(models.TextChoices):
        AVAILABLE = "available", "材料可用"
        MISSING = "missing", "材料缺失"
        DEVICE_ISSUE = "device_issue", "设备问题"
        TECHNICAL_ISSUE = "technical_issue", "技术问题"
        NOT_OFFERED = "not_offered", "未获得机会"
        NOT_OBSERVED = "not_observed", "未观察到"
        NOT_APPLICABLE = "not_applicable", "不适用"
        PENDING_REVIEW = "pending_review", "等待评价"

    material_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School", on_delete=models.PROTECT, related_name="assessment_materials"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="assessment_materials"
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_materials",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recorded_assessment_materials",
    )
    legacy_unmapped = models.BooleanField(default=True)
    learning_target_version = models.ForeignKey(
        "learning_analytics.LearningTargetVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_materials",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_materials",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_materials",
    )
    ownership = models.CharField(max_length=16, choices=Ownership.choices)
    group_reference = models.CharField(max_length=96, blank=True)
    material_type = models.CharField(max_length=24, choices=MaterialType.choices)
    material_status = models.CharField(max_length=24, choices=MaterialStatus.choices)
    learning_target_code = models.CharField(max_length=96, blank=True)
    source_type = models.CharField(max_length=48)
    source_id = models.CharField(max_length=96)
    source_version = models.CharField(max_length=96)
    content = models.JSONField(default=dict, blank=True)
    score = models.FloatField(null=True, blank=True)
    score_max = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField()
    content_hash = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableDiagnosticRecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id"],
                condition=models.Q(source_type="learning_entry_diagnostic_review"),
                name="uniq_pretest_material_review_source",
            ),
        ]
        indexes = [
            models.Index(fields=["student", "subject", "recorded_at"]),
            models.Index(fields=["source_type", "source_id", "source_version"]),
            models.Index(fields=["learning_target_code", "material_status"]),
        ]
        ordering = ["-recorded_at", "-id"]

    def clean(self):
        errors = {}
        if self.ownership == self.Ownership.INDIVIDUAL and not self.student_id:
            errors["student"] = "个人评价材料必须明确归属学生。"
        if self.ownership == self.Ownership.GROUP and not self.group_reference:
            errors["group_reference"] = "小组评价材料必须明确实际小组。"
        if self.material_status != self.MaterialStatus.AVAILABLE:
            if self.score is not None:
                errors["score"] = "材料不可用时不能记录为低分或其他分数。"
        if self.score_max is not None:
            if not isinstance(self.score_max, (int, float)) or not float(self.score_max) > 0:
                errors["score_max"] = "满分必须是大于 0 的有限数字。"
            elif not float(self.score_max) < float("inf"):
                errors["score_max"] = "满分必须是有限数字。"
        if self.score is not None:
            if self.score_max is None:
                errors["score_max"] = "记录得分时必须同时记录满分。"
            elif not isinstance(self.score, (int, float)) or not 0 <= float(self.score) <= float(self.score_max):
                errors["score"] = "得分必须位于 0 与满分之间。"
            elif not float(self.score) < float("inf"):
                errors["score"] = "得分必须是有限数字。"
        if not self.recorded_by_id and not self.legacy_unmapped:
            errors["recorded_by"] = "新评价材料必须记录材料形成者。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "评价材料学科与学校不一致。"
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "评价材料班级与学校不一致。"
        if self.student_id and self.student.school_id != self.school_id:
            errors["student"] = "评价材料学生与学校不一致。"
        if self.recorded_by_id and self.recorded_by.school_id not in {None, self.school_id}:
            errors["recorded_by"] = "材料形成者与学校不一致。"
        if self.course_id:
            if self.course.subject_id != self.subject_id:
                errors["course"] = "评价材料课程与学科不一致。"
            elif self.course.subject.school_id != self.school_id:
                errors["course"] = "评价材料课程与学校不一致。"
        elif not self.legacy_unmapped:
            errors["course"] = "新形成的正式评价材料必须绑定具体课程。"
        if self.learning_target_version_id:
            version = self.learning_target_version
            target = version.target
            if self.legacy_unmapped:
                errors["legacy_unmapped"] = "已绑定学习目标版本的材料不能标记为历史未映射。"
            if version.alignment_status != "complete" or not version.curriculum_alignments.exists():
                errors["learning_target_version"] = "正式评价材料必须对应课标依据完整的学习目标版本。"
            if target.school_id != self.school_id:
                errors["learning_target_version"] = "学习目标版本与材料学校不一致。"
            elif target.subject_id != self.subject_id:
                errors["learning_target_version"] = "学习目标版本与材料学科不一致。"
            elif target.course_id != self.course_id:
                errors["learning_target_version"] = "学习目标版本与材料课程不一致。"
            if self.learning_target_code and version.code != self.learning_target_code:
                errors["learning_target_code"] = "学习目标代码与冻结版本不一致。"
        elif not self.legacy_unmapped:
            errors["learning_target_version"] = "新正式评价材料必须绑定不可变学习目标版本。"
        if errors:
            raise ValidationError(errors)

    def semantic_content(self):
        return {
            "material_id": str(self.material_id),
            "school_id": self.school_id,
            "subject_id": self.subject_id,
            "course_id": self.course_id,
            "class_group_id": self.class_group_id,
            "student_id": self.student_id,
            "recorded_by_id": self.recorded_by_id,
            "legacy_unmapped": self.legacy_unmapped,
            "learning_target_version_id": self.learning_target_version_id,
            "ownership": self.ownership,
            "group_reference": self.group_reference,
            "material_type": self.material_type,
            "material_status": self.material_status,
            "learning_target_code": self.learning_target_code,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "content": self.content,
            "score": self.score,
            "score_max": self.score_max,
            "recorded_at": self.recorded_at,
        }

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("统一评价材料不可修改，请追加新材料记录。")
        self.content_hash = hashlib.sha256(
            json.dumps(
                self.semantic_content(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("统一评价材料不可删除。")


class PretestMaterialAttachment(models.Model):
    """Immutable file evidence attached to one published diagnostic task material."""

    attachment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    material = models.ForeignKey(
        UnifiedAssessmentMaterial,
        on_delete=models.PROTECT,
        related_name="attachments",
    )
    submission = models.ForeignKey(
        PretestSubmission,
        on_delete=models.PROTECT,
        related_name="material_attachments",
    )
    paper_version = models.ForeignKey(
        PretestPaperVersion,
        on_delete=models.PROTECT,
        related_name="material_attachments",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pretest_material_attachments",
    )
    question_id = models.CharField(max_length=64)
    attachment = models.FileField(upload_to=pretest_material_upload_path, max_length=500)
    original_name = models.CharField(max_length=255)
    file_ext = models.CharField(max_length=16)
    content_type = models.CharField(max_length=128, blank=True)
    file_size = models.PositiveIntegerField()
    file_sha256 = models.CharField(max_length=64, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableDiagnosticRecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["material", "file_sha256"],
                name="uniq_pretest_material_attachment_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["submission", "question_id"]),
            models.Index(fields=["student", "created_at"]),
            models.Index(fields=["paper_version", "question_id"]),
        ]
        ordering = ["material_id", "id"]

    def clean(self):
        errors = {}
        if self.material_id:
            if self.material.student_id != self.student_id:
                errors["student"] = "附件学生与评价材料归属不一致。"
            if self.material.source_type not in {
                "learning_entry_diagnostic",
                "research_pretest",
                "research_posttest",
                "diagnostic_pilot",
            }:
                errors["material"] = "附件只能绑定已冻结实施批次的诊断原始材料。"
            if self.material.source_id != str(self.submission_id):
                errors["submission"] = "附件提交与评价材料来源不一致。"
            if self.material.source_version != self.paper_version.content_hash:
                errors["paper_version"] = "附件版本与评价材料版本不一致。"
            content = self.material.content if isinstance(self.material.content, dict) else {}
            if str(content.get("question_id") or "") != str(self.question_id):
                errors["question_id"] = "附件题目与评价材料题目不一致。"
            if self.material.material_status not in {
                UnifiedAssessmentMaterial.MaterialStatus.AVAILABLE,
                UnifiedAssessmentMaterial.MaterialStatus.PENDING_REVIEW,
            }:
                errors["material"] = "未形成观察的任务不能保存附件。"
        if self.submission_id:
            if self.submission.student_id != self.student_id:
                errors["student"] = "附件学生与诊断提交学生不一致。"
            if self.submission.paper_version_id != self.paper_version_id:
                errors["paper_version"] = "附件必须绑定提交时的已发布诊断版本。"
        if self.file_size <= 0:
            errors["file_size"] = "附件不能为空。"
        if len(self.file_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.file_sha256.lower()
        ):
            errors["file_sha256"] = "附件校验值格式不正确。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("学习起点诊断附件不可修改。")
        self.file_sha256 = self.file_sha256.lower()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("学习起点诊断附件不可删除。")


class QuestionBankItem(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE = "single", "单选"
        MULTIPLE = "multiple", "多选"
        JUDGE = "judge", "判断"
        BLANK = "blank", "填空"
        TEXT = "text", "简答"

    class Difficulty(models.TextChoices):
        EASY = "easy", "基础"
        NORMAL = "normal", "适中"
        HARD = "hard", "挑战"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PENDING_REVIEW = "pending_review", "待审核"
        TRIAL = "trial", "可试用"
        ACTIVE = "active", "启用"
        DISABLED = "disabled", "停用"

    class Source(models.TextChoices):
        MANUAL = "manual", "手工创建"
        XLSX = "xlsx", "XLSX 导入"
        AI = "ai", "AI 生成"
        COPY = "copy", "复制题目"
        EXISTING = "existing", "既有题目"

    class LibraryScope(models.TextChoices):
        PERSONAL = "personal", "个人题目"
        SCHOOL = "school", "校内共享"

    class ItemRole(models.TextChoices):
        REGULAR = "regular", "普通题"
        COMMON = "common", "共同题"
        LAYERED = "layered", "分层题"

    class LayerScope(models.TextChoices):
        ALL = "all", "全体"
        A = "a", "A"
        B = "b", "B"
        C = "c", "C"
        AB = "ab", "A/B"
        BC = "bc", "B/C"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="question_bank_items"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="question_bank_items"
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_question_bank_items",
        limit_choices_to={"role": "teacher"},
    )
    stem = models.TextField()
    question_type = models.CharField(max_length=16, choices=QuestionType.choices)
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    analysis = models.TextField(blank=True)
    difficulty = models.CharField(
        max_length=16, choices=Difficulty.choices, default=Difficulty.NORMAL
    )
    knowledge_point = models.CharField(max_length=128, blank=True)
    default_score = models.FloatField(default=2)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DRAFT
    )
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.MANUAL
    )
    library_scope = models.CharField(
        max_length=16,
        choices=LibraryScope.choices,
        default=LibraryScope.PERSONAL,
    )
    item_role = models.CharField(
        max_length=16,
        choices=ItemRole.choices,
        default=ItemRole.REGULAR,
    )
    layer_scope = models.CharField(
        max_length=8,
        choices=LayerScope.choices,
        default=LayerScope.ALL,
    )
    comparison_code = models.CharField(max_length=64, blank=True, db_index=True)
    learning_target_version = models.ForeignKey(
        "learning_analytics.LearningTargetVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_bank_items",
    )
    legacy_unmapped = models.BooleanField(default=True)
    version_no = models.PositiveIntegerField(default=1)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    submitted_for_review_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_question_bank_items",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    disabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="disabled_question_bank_items",
    )
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "subject", "status", "updated_at"]),
            models.Index(fields=["school", "creator", "status"]),
            models.Index(fields=["school", "library_scope", "status"]),
            models.Index(fields=["school", "status", "submitted_for_review_at"]),
            models.Index(fields=["question_type", "difficulty"]),
            models.Index(fields=["school", "subject", "item_role", "comparison_code"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.stem[:48]


class QuestionBankItemVersion(models.Model):
    question = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versions",
    )
    original_question_id = models.PositiveBigIntegerField()
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="question_bank_item_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="question_bank_item_versions",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_question_bank_item_versions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_question_bank_item_versions",
    )
    version_no = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64)
    source = models.CharField(max_length=16, choices=QuestionBankItem.Source.choices)
    status_snapshot = models.CharField(
        max_length=24, choices=QuestionBankItem.Status.choices
    )
    stem = models.TextField()
    question_type = models.CharField(
        max_length=16, choices=QuestionBankItem.QuestionType.choices
    )
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    analysis = models.TextField(blank=True)
    difficulty = models.CharField(
        max_length=16, choices=QuestionBankItem.Difficulty.choices
    )
    knowledge_point = models.CharField(max_length=128, blank=True)
    default_score = models.FloatField(default=2)
    item_role = models.CharField(
        max_length=16,
        choices=QuestionBankItem.ItemRole.choices,
        default=QuestionBankItem.ItemRole.REGULAR,
    )
    layer_scope = models.CharField(
        max_length=8,
        choices=QuestionBankItem.LayerScope.choices,
        default=QuestionBankItem.LayerScope.ALL,
    )
    comparison_code = models.CharField(max_length=64, blank=True, db_index=True)
    learning_target_version = models.ForeignKey(
        "learning_analytics.LearningTargetVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_bank_item_versions",
    )
    legacy_unmapped = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "original_question_id", "version_no"],
                name="uniq_question_bank_item_version",
            ),
            models.UniqueConstraint(
                fields=["school", "original_question_id", "content_hash"],
                name="uniq_question_bank_item_content_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "created_at"]),
            models.Index(fields=["question", "version_no"]),
            models.Index(fields=["content_hash"]),
        ]
        ordering = ["original_question_id", "version_no"]

    def __str__(self) -> str:
        return f"{self.original_question_id}@{self.version_no}"

    def clean(self):
        errors = {}
        if self.learning_target_version_id:
            version = self.learning_target_version
            target = version.target
            if self.legacy_unmapped:
                errors["legacy_unmapped"] = "已绑定学习目标版本的题目版本不能标记为历史未映射。"
            if version.alignment_status != "complete" or not version.curriculum_alignments.exists():
                errors["learning_target_version"] = "题目版本只能绑定课标依据完整的学习目标版本。"
            if target.school_id != self.school_id:
                errors["learning_target_version"] = "学习目标版本与题目版本学校不一致。"
            elif target.subject_id != self.subject_id:
                errors["learning_target_version"] = "学习目标版本与题目版本学科不一致。"
        elif not self.legacy_unmapped:
            errors["learning_target_version"] = "非历史题目版本必须绑定不可变学习目标版本。"
        if self.question_id:
            if self.question.school_id != self.school_id:
                errors["question"] = "来源题目与题目版本学校不一致。"
            elif self.question.subject_id != self.subject_id:
                errors["question"] = "来源题目与题目版本学科不一致。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("题目版本是不可变证据；如需调整，请形成新的题目版本。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("题目版本是不可变证据，不能删除。")


class KnowledgeComponent(models.Model):
    """A school-owned subject concept used to link item responses over time."""

    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="knowledge_components",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="knowledge_components",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "code"],
                name="uniq_knowledge_component_code",
            ),
            models.UniqueConstraint(
                fields=["school", "subject", "name"],
                name="uniq_knowledge_component_name",
            ),
        ]
        indexes = [models.Index(fields=["school", "subject", "is_active"])]
        ordering = ["subject_id", "code"]

    def __str__(self) -> str:
        return f"{self.subject_id}:{self.code}"


class QuestionVersionKnowledgeComponent(models.Model):
    question_version = models.ForeignKey(
        QuestionBankItemVersion,
        on_delete=models.PROTECT,
        related_name="knowledge_mappings",
    )
    component = models.ForeignKey(
        KnowledgeComponent,
        on_delete=models.PROTECT,
        related_name="question_mappings",
    )
    weight = models.FloatField(default=1.0)
    is_primary = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_question_knowledge_mappings",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question_version", "component"],
                name="uniq_question_version_knowledge_component",
            ),
        ]
        indexes = [
            models.Index(fields=["component", "question_version"]),
            models.Index(fields=["question_version", "is_primary"]),
        ]
        ordering = ["question_version_id", "-is_primary", "component_id"]

    def __str__(self) -> str:
        return f"{self.question_version_id}:{self.component.code}"


class QuestionBankItemLifecycleRecord(models.Model):
    question = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lifecycle_records",
    )
    original_question_id = models.PositiveBigIntegerField()
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="question_bank_lifecycle_records",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="question_bank_lifecycle_actions",
    )
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, choices=QuestionBankItem.Status.choices)
    action = models.CharField(max_length=32)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "to_status", "created_at"]),
            models.Index(fields=["question", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.original_question_id}:{self.from_status}->{self.to_status}"


class CommonQuestionSet(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        ARCHIVED = "archived", "归档"

    class VersionPurpose(models.TextChoices):
        BASELINE = "baseline", "首个版本"
        FOLLOW_UP = "follow_up", "后续版本"
        PARALLEL = "parallel", "平行版本"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="common_question_sets"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="common_question_sets"
    )
    title = models.CharField(max_length=128)
    grade_scope = models.CharField(max_length=32, blank=True)
    term = models.CharField(max_length=32, blank=True)
    version_no = models.PositiveIntegerField(default=1)
    measurement_series = models.CharField(max_length=96, blank=True, db_index=True)
    version_purpose = models.CharField(
        max_length=16,
        choices=VersionPurpose.choices,
        default=VersionPurpose.BASELINE,
    )
    previous_version = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="next_versions",
    )
    readiness = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_common_question_sets",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_common_question_sets",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "grade_scope", "term", "version_no"],
                name="uniq_common_question_set_version",
            )
        ]
        indexes = [
            models.Index(fields=["school", "subject", "status", "updated_at"]),
            models.Index(
                fields=["school", "subject", "measurement_series", "version_no"]
            ),
        ]
        ordering = ["subject_id", "grade_scope", "term", "-version_no"]

    def __str__(self) -> str:
        return f"{self.title} v{self.version_no}"


class CommonQuestionSetItem(models.Model):
    question_set = models.ForeignKey(
        CommonQuestionSet, on_delete=models.CASCADE, related_name="items"
    )
    question_version = models.ForeignKey(
        QuestionBankItemVersion,
        on_delete=models.PROTECT,
        related_name="common_set_items",
    )
    anchor_source = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="anchor_successors",
    )
    comparison_code = models.CharField(max_length=64)
    required = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question_set", "question_version"],
                name="uniq_common_set_question_version",
            ),
            models.UniqueConstraint(
                fields=["question_set", "comparison_code"],
                name="uniq_common_set_comparison_code",
            ),
        ]
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.question_set_id}:{self.comparison_code}"


class TestAssessment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "待开启"
        OPEN = "open", "进行中"
        CLOSED = "closed", "已结束"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="test_assessments"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="test_assessments",
        limit_choices_to={"role": "teacher"},
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="test_assessments"
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_assessments",
    )
    common_question_set = models.ForeignKey(
        "CommonQuestionSet",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessments",
    )
    common_set_version = models.PositiveIntegerField(null=True, blank=True)
    common_set_hash = models.CharField(max_length=64, blank=True)
    target_classes = models.ManyToManyField(
        "school.ClassGroup", related_name="test_assessments"
    )
    title = models.CharField(max_length=128)
    instruction = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=45)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    show_score_after_submit = models.BooleanField(default=False)
    randomize_question_order = models.BooleanField(default=False)
    randomize_option_order = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "teacher", "status", "updated_at"]),
            models.Index(fields=["school", "status", "start_at", "end_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.title


class TestAssessmentQuestion(models.Model):
    assessment = models.ForeignKey(
        TestAssessment, on_delete=models.CASCADE, related_name="questions"
    )
    source_question = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_questions",
    )
    source_version = models.ForeignKey(
        QuestionBankItemVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_questions",
    )
    source_status = models.CharField(
        max_length=24,
        choices=QuestionBankItem.Status.choices,
        default=QuestionBankItem.Status.ACTIVE,
    )
    question_type = models.CharField(
        max_length=16, choices=QuestionBankItem.QuestionType.choices
    )
    stem = models.TextField()
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    analysis = models.TextField(blank=True)
    knowledge_point = models.CharField(max_length=128, blank=True)
    score = models.FloatField(default=2)
    sort_order = models.PositiveIntegerField(default=0)
    item_role = models.CharField(
        max_length=16,
        choices=QuestionBankItem.ItemRole.choices,
        default=QuestionBankItem.ItemRole.REGULAR,
    )
    layer_scope = models.CharField(
        max_length=8,
        choices=QuestionBankItem.LayerScope.choices,
        default=QuestionBankItem.LayerScope.ALL,
    )
    comparison_code = models.CharField(max_length=64, blank=True)
    learning_target_version = models.ForeignKey(
        "learning_analytics.LearningTargetVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_question_snapshots",
    )
    legacy_unmapped = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["assessment", "sort_order", "id"])]
        ordering = ["assessment_id", "sort_order", "id"]

    def __str__(self) -> str:
        return self.stem[:48]

    def clean(self):
        errors = {}
        assessment = self.assessment
        if self.learning_target_version_id:
            version = self.learning_target_version
            target = version.target
            if self.legacy_unmapped:
                errors["legacy_unmapped"] = "已绑定学习目标版本的测试题快照不能标记为历史未映射。"
            if version.alignment_status != "complete" or not version.curriculum_alignments.exists():
                errors["learning_target_version"] = "测试题快照只能绑定课标依据完整的学习目标版本。"
            if target.school_id != assessment.school_id:
                errors["learning_target_version"] = "学习目标版本与测试学校不一致。"
            elif target.subject_id != assessment.subject_id:
                errors["learning_target_version"] = "学习目标版本与测试学科不一致。"
            elif not assessment.course_id:
                errors["learning_target_version"] = "绑定学习目标版本的测试必须明确具体课程。"
            elif target.course_id != assessment.course_id:
                errors["learning_target_version"] = "学习目标版本与测试课程不一致。"
        elif not self.legacy_unmapped:
            errors["learning_target_version"] = "非历史测试题快照必须绑定不可变学习目标版本。"
        if self.source_version_id:
            source_version = self.source_version
            if source_version.school_id != assessment.school_id:
                errors["source_version"] = "来源题目版本与测试学校不一致。"
            elif source_version.subject_id != assessment.subject_id:
                errors["source_version"] = "来源题目版本与测试学科不一致。"
            if (
                source_version.learning_target_version_id
                != self.learning_target_version_id
                or source_version.legacy_unmapped != self.legacy_unmapped
            ):
                errors["source_version"] = "测试题快照的学习目标映射必须与来源题目版本一致。"
        if errors:
            raise ValidationError(errors)

    def _assessment_is_frozen(self) -> bool:
        return (
            self.assessment.status != TestAssessment.Status.DRAFT
            or self.assessment.attempts.exists()
        )

    def save(self, *args, **kwargs):
        exists = bool(self.pk and type(self).objects.filter(pk=self.pk).exists())
        if exists and self._assessment_is_frozen():
            raise ValidationError("测试发布或形成作答后，题目证据快照不可修改。")
        if not exists and self.assessment_id and self._assessment_is_frozen():
            raise ValidationError("测试发布后不能追加题目；请在草稿阶段形成完整题目快照。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._assessment_is_frozen():
            raise ValidationError("测试发布或形成作答后，题目证据快照不可删除。")
        return super().delete(*args, **kwargs)


class TestAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "答题中"
        SUBMITTED = "submitted", "已提交"
        GRADED = "graded", "已评分"

    assessment = models.ForeignKey(
        TestAssessment, on_delete=models.PROTECT, related_name="attempts"
    )
    analytics_attempt_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="test_attempts"
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, related_name="test_attempts"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.IN_PROGRESS
    )
    objective_score = models.FloatField(default=0)
    subjective_score = models.FloatField(default=0)
    total_score = models.FloatField(default=0)
    question_order = models.JSONField(default=list, blank=True)
    option_orders = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_saved_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "student"], name="uniq_test_attempt_per_student"
            ),
        ]
        indexes = [
            models.Index(fields=["assessment", "class_group", "status"]),
            models.Index(fields=["student", "status", "started_at"]),
        ]
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.assessment} - {self.student}"


class TestAttemptAnswer(models.Model):
    attempt = models.ForeignKey(
        TestAttempt, on_delete=models.CASCADE, related_name="answer_rows"
    )
    question = models.ForeignKey(
        TestAssessmentQuestion, on_delete=models.PROTECT, related_name="attempt_answers"
    )
    answer = models.JSONField(default=list, blank=True)
    auto_score = models.FloatField(default=0)
    manual_score = models.FloatField(null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"],
                name="uniq_test_answer_per_attempt_question",
            ),
        ]
        indexes = [models.Index(fields=["attempt", "question"])]
        ordering = ["question__sort_order", "question_id"]

    @property
    def final_score(self) -> float:
        return self.manual_score if self.manual_score is not None else self.auto_score


class AssessmentComparabilityRecord(models.Model):
    class Status(models.TextChoices):
        COMPARABLE = "comparable", "可以比较"
        NOT_COMPARABLE = "not_comparable", "不可比较"
        INSUFFICIENT = "insufficient", "数据不足"

    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="assessment_comparability_records",
    )
    left_assessment = models.ForeignKey(
        TestAssessment,
        on_delete=models.CASCADE,
        related_name="comparisons_as_left",
    )
    right_assessment = models.ForeignKey(
        TestAssessment,
        on_delete=models.CASCADE,
        related_name="comparisons_as_right",
    )
    status = models.CharField(max_length=24, choices=Status.choices)
    common_question_count = models.PositiveIntegerField(default=0)
    exact_version_match_count = models.PositiveIntegerField(default=0)
    left_sample_size = models.PositiveIntegerField(default=0)
    right_sample_size = models.PositiveIntegerField(default=0)
    reasons = models.JSONField(default=list, blank=True)
    compared_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["left_assessment", "right_assessment"],
                name="uniq_assessment_comparison_pair",
            )
        ]
        indexes = [models.Index(fields=["school", "status", "compared_at"])]
        ordering = ["-compared_at", "-id"]

    def __str__(self) -> str:
        return f"{self.left_assessment_id}:{self.right_assessment_id}:{self.status}"


class Notice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        ARCHIVED = "archived", "归档"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="notices"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teacher_notices",
    )
    target_classes = models.ManyToManyField(
        "school.ClassGroup", related_name="notices", blank=True
    )
    title = models.CharField(max_length=128)
    content = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    is_pinned = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "teacher", "status", "created_at"]),
            models.Index(fields=["school", "status", "is_pinned"]),
        ]
        ordering = ["-is_pinned", "-published_at", "-created_at"]

    def __str__(self) -> str:
        return self.title


class Feedback(models.Model):
    class Category(models.TextChoices):
        STUDY = "study", "学习问题"
        ACCOUNT = "account", "账号问题"
        RESOURCE = "resource", "资源问题"
        SUGGESTION = "suggestion", "建议反馈"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        PENDING = "pending", "待回复"
        REPLIED = "replied", "已回复"
        CLOSED = "closed", "已关闭"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="feedback_items"
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, related_name="feedback_items"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_feedback_items",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_feedback_items",
    )
    category = models.CharField(
        max_length=16, choices=Category.choices, default=Category.STUDY
    )
    title = models.CharField(max_length=128)
    content = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    reply_content = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "teacher", "status", "created_at"]),
            models.Index(fields=["class_group", "status", "created_at"]),
            models.Index(fields=["student", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class StudentWorkAttachment(models.Model):
    submission_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="student_work_attachments",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_work_attachments",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    question_id = models.CharField(max_length=64)
    question_stem = models.TextField(blank=True)
    upload_version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revisions",
    )
    attachment = models.FileField(upload_to=student_work_upload_path)
    original_name = models.CharField(max_length=255)
    file_ext = models.CharField(max_length=16, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    score = models.FloatField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluated_student_work_attachments",
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lesson_step", "question_id", "upload_version"],
                name="uniq_student_work_version",
            ),
        ]
        indexes = [
            models.Index(fields=["class_group", "lesson_step", "question_id"]),
            models.Index(fields=["student", "created_at"]),
            models.Index(fields=["classroom_session", "created_at"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.student_id}:{self.lesson_step_id}:{self.question_id}@{self.upload_version}"


class LessonStepAttempt(models.Model):
    attempt_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    attempt_no = models.PositiveIntegerField()
    answer = models.JSONField(default=dict, blank=True)
    free_text = models.TextField(blank=True)
    answered_count = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    auto_score = models.FloatField(default=0)
    auto_score_max = models.FloatField(default=0)
    submitted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "classroom_session",
                    "lesson_step",
                    "student",
                    "attempt_no",
                ],
                name="uniq_lesson_step_attempt_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["classroom_session", "lesson_step", "student", "submitted_at"]
            ),
            models.Index(fields=["student", "submitted_at"]),
        ]
        ordering = ["-submitted_at", "-id"]

    def __str__(self) -> str:
        return f"{self.student_id}:{self.lesson_step_id}#{self.attempt_no}"


class LessonStepAttemptAnswer(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE = "single", "单选"
        MULTIPLE = "multiple", "多选"
        JUDGE = "judge", "判断"
        BLANK = "blank", "填空"
        TEXT = "text", "简答"
        FILE = "file", "附件提交"

    attempt = models.ForeignKey(
        LessonStepAttempt,
        on_delete=models.PROTECT,
        related_name="answer_rows",
    )
    question_id = models.CharField(max_length=64)
    question_version = models.CharField(max_length=64)
    question_type = models.CharField(max_length=16, choices=QuestionType.choices)
    response = models.JSONField(default=dict, blank=True)
    is_answered = models.BooleanField(default=False)
    auto_score = models.FloatField(null=True, blank=True)
    score_max = models.FloatField()
    is_correct = models.BooleanField(null=True, blank=True)
    attachment = models.ForeignKey(
        StudentWorkAttachment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attempt_answers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question_id"],
                name="uniq_lesson_step_attempt_question",
            ),
        ]
        indexes = [
            models.Index(fields=["attempt", "question_id"]),
            models.Index(fields=["question_version"]),
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.attempt_id}:{self.question_id}"


# Create your models here.


# Kept in a separate module so the diagnostic-administration aggregate can evolve
# without extending this already large compatibility model file.
from .diagnostic_models import (  # noqa: E402,F401
    DiagnosticAdministration,
    DiagnosticAdministrationAssignment,
    DiagnosticSubmissionBinding,
)
