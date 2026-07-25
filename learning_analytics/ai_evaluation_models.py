from __future__ import annotations

import hashlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def ai_evaluation_content_hash(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AIEvaluationDraftStatus(models.TextChoices):
    CREATED = "created", "待检索课程标准"
    RETRIEVED = "retrieved", "已检索课程标准"
    MODE_SUGGESTION_QUEUED = "mode_suggestion_queued", "评价方式建议排队中"
    MODE_SUGGESTION_RUNNING = "mode_suggestion_running", "正在形成评价方式建议"
    MODES_SUGGESTED = "modes_suggested", "评价方式待教师确认"
    MODES_CONFIRMED = "modes_confirmed", "教师已确认评价方式"
    DRAFT_QUEUED = "draft_queued", "评价初稿排队中"
    DRAFT_RUNNING = "draft_running", "正在形成评价初稿"
    DRAFT_GENERATED = "draft_generated", "评价初稿待教师审阅"
    SAVED = "saved", "已保存为评价方案草稿"
    FAILED = "failed", "后台任务失败"
    CANCELLED = "cancelled", "已取消"


class AIEvaluationTaskKind(models.TextChoices):
    NONE = "", "无"
    SUGGEST_MODES = "suggest_modes", "建议评价方式"
    GENERATE_DRAFT = "generate_draft", "生成评价初稿"


class AIEvaluationDraftSession(models.Model):
    """Governed, teacher-owned state machine for AI-assisted evaluation drafting.

    The schema intentionally contains no student identity field and no provider
    credential field.  Student evidence belongs to later evaluation workflows;
    provider credentials remain exclusively in ``TeacherAIProvider``.
    """

    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_evaluation_draft_sessions",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="ai_evaluation_draft_sessions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="ai_evaluation_draft_sessions",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="ai_evaluation_draft_sessions",
    )
    curriculum_version = models.ForeignKey(
        "curriculum_standards.CurriculumStandardVersion",
        on_delete=models.PROTECT,
        related_name="ai_evaluation_draft_sessions",
    )
    curriculum_version_content_hash = models.CharField(max_length=64)
    curriculum_pdf_sha256 = models.CharField(max_length=64)
    school_stage = models.CharField(max_length=16)
    grade_or_stage = models.CharField(max_length=64)
    unit_title = models.CharField(max_length=160)
    course_content = models.TextField()
    evaluation_purpose = models.TextField()
    teacher_mode_note = models.CharField(max_length=500, blank=True)
    retrieval_query = models.TextField()
    retrieval_snapshot = models.JSONField(default=list, blank=True)
    retrieval_snapshot_hash = models.CharField(max_length=64, blank=True)
    suggested_modes = models.JSONField(default=list, blank=True)
    confirmed_modes = models.JSONField(default=list, blank=True)
    plan_draft = models.JSONField(default=dict, blank=True)
    standard_draft = models.JSONField(default=dict, blank=True)
    automatic_check_result = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=32,
        choices=AIEvaluationDraftStatus.choices,
        default=AIEvaluationDraftStatus.CREATED,
    )
    active_task_kind = models.CharField(
        max_length=24,
        choices=AIEvaluationTaskKind.choices,
        default=AIEvaluationTaskKind.NONE,
        blank=True,
    )
    celery_task_id = models.CharField(max_length=128, blank=True, db_index=True)
    dispatch_count = models.PositiveIntegerField(default=0)
    dispatch_attempted_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    last_error_message = models.CharField(max_length=1000, blank=True)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    save_request_hash = models.CharField(max_length=64, blank=True)
    linked_plan = models.ForeignKey(
        "learning_analytics.EvaluationPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ai_draft_sessions",
    )
    linked_standard = models.ForeignKey(
        "learning_analytics.EvaluationStandard",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ai_draft_sessions",
    )
    saved_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "idempotency_key"],
                name="uniq_ai_eval_teacher_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["teacher", "status", "updated_at"]),
            models.Index(fields=["school", "course", "updated_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.teacher_id and self.teacher.school_id != self.school_id:
            errors["teacher"] = "教师与 AI 评价初稿会话不属于同一学校。"
        if self.course_id:
            if self.course.teacher_id != self.teacher_id:
                errors["course"] = "只能为本人任教课程生成评价初稿。"
            if not self.course.subject_id or self.course.subject_id != self.subject_id:
                errors["subject"] = "课程学科与 AI 评价初稿会话学科不一致。"
            elif self.course.subject.school_id != self.school_id:
                errors["course"] = "课程与 AI 评价初稿会话不属于同一学校。"
        if self.curriculum_version_id:
            if self.school_stage != self.curriculum_version.school_stage_snapshot:
                errors["school_stage"] = "所选学段与课程标准版本学段不一致。"
            if self.curriculum_version_content_hash != self.curriculum_version.content_hash:
                errors["curriculum_version_content_hash"] = "课程标准版本内容哈希与版本快照不一致。"
            if self.curriculum_pdf_sha256 != self.curriculum_version.pdf_sha256:
                errors["curriculum_pdf_sha256"] = "课程标准 PDF 哈希与版本快照不一致。"
        for field_name in ("retrieval_snapshot", "suggested_modes", "confirmed_modes"):
            if not isinstance(getattr(self, field_name), list):
                errors[field_name] = "必须是 JSON 列表。"
        for field_name in ("plan_draft", "standard_draft", "automatic_check_result"):
            if not isinstance(getattr(self, field_name), dict):
                errors[field_name] = "必须是 JSON 对象。"
        for field_name in ("request_hash", "retrieval_snapshot_hash", "save_request_hash"):
            value = getattr(self, field_name)
            if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
                errors[field_name] = "哈希格式不正确。"
        if self.linked_plan_id:
            if self.linked_plan.school_id != self.school_id:
                errors["linked_plan"] = "评价方案草稿与 AI 会话不属于同一学校。"
            if self.linked_plan.created_by_id != self.teacher_id:
                errors["linked_plan"] = "评价方案草稿不属于当前教师。"
        if self.linked_standard_id:
            if not self.linked_plan_id or self.linked_standard.plan_id != self.linked_plan_id:
                errors["linked_standard"] = "评价标准草稿未绑定本次保存的评价方案草稿。"
            if self.linked_standard.created_by_id != self.teacher_id:
                errors["linked_standard"] = "评价标准草稿不属于当前教师。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.teacher_id}:{self.course_id}:{self.session_id}"


class AIEvaluationGenerationStage(models.TextChoices):
    MODE_SUGGESTION = "mode_suggestion", "评价方式建议"
    EVALUATION_DRAFT = "evaluation_draft", "评价内容初稿"


class AIEvaluationGenerationStatus(models.TextChoices):
    SUCCEEDED = "succeeded", "成功"
    FAILED = "failed", "失败"


class AIEvaluationGenerationRecord(models.Model):
    """Append-only evidence for every completed provider invocation attempt."""

    session = models.ForeignKey(
        AIEvaluationDraftSession,
        on_delete=models.PROTECT,
        related_name="generation_records",
    )
    stage = models.CharField(max_length=24, choices=AIEvaluationGenerationStage.choices)
    attempt_no = models.PositiveIntegerField()
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=128)
    system_prompt = models.TextField()
    user_prompt = models.TextField()
    prompt_hash = models.CharField(max_length=64)
    generation_config = models.JSONField(default=dict)
    retrieval_snapshot = models.JSONField(default=list)
    raw_response_text = models.TextField(blank=True)
    raw_result = models.JSONField(default=dict, blank=True)
    parsed_result = models.JSONField(default=dict, blank=True)
    validation_result = models.JSONField(default=dict, blank=True)
    result_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=AIEvaluationGenerationStatus.choices)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=1000, blank=True)
    celery_task_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "stage", "attempt_no"],
                name="uniq_ai_eval_generation_attempt",
            ),
        ]
        indexes = [models.Index(fields=["session", "stage", "created_at"])]
        ordering = ["session_id", "stage", "attempt_no", "id"]

    def clean(self) -> None:
        errors = {}
        if not isinstance(self.retrieval_snapshot, list):
            errors["retrieval_snapshot"] = "课程标准检索快照必须是 JSON 列表。"
        if not isinstance(self.generation_config, dict):
            errors["generation_config"] = "生成参数快照必须是 JSON 对象。"
        for field_name in ("raw_result", "parsed_result", "validation_result"):
            if not isinstance(getattr(self, field_name), dict):
                errors[field_name] = "必须是 JSON 对象。"
        for field_name in ("prompt_hash", "result_hash"):
            value = getattr(self, field_name)
            if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
                errors[field_name] = "哈希格式不正确。"
        if self.status == AIEvaluationGenerationStatus.SUCCEEDED and not self.result_hash:
            errors["result_hash"] = "成功的生成记录必须保存结果哈希。"
        if self.status == AIEvaluationGenerationStatus.FAILED and not self.error_code:
            errors["error_code"] = "失败的生成记录必须保存错误代码。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("AI 生成审计记录不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AI 生成审计记录不可删除。")


class AIEvaluationTeacherDecisionType(models.TextChoices):
    ACCEPTED = "accepted", "采纳"
    EDITED = "edited", "修改后采纳"
    REJECTED = "rejected", "不采纳"


class AIEvaluationTeacherDecision(models.Model):
    """Append-only, item-level record of teacher confirmation and revision."""

    session = models.ForeignKey(
        AIEvaluationDraftSession,
        on_delete=models.PROTECT,
        related_name="teacher_decisions",
    )
    generation = models.ForeignKey(
        AIEvaluationGenerationRecord,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="teacher_decisions",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_evaluation_teacher_decisions",
    )
    stage = models.CharField(max_length=32)
    item_type = models.CharField(max_length=48)
    item_key = models.CharField(max_length=128)
    sequence = models.PositiveIntegerField(default=1)
    decision = models.CharField(
        max_length=16,
        choices=AIEvaluationTeacherDecisionType.choices,
    )
    ai_value = models.JSONField(null=True, blank=True)
    teacher_value = models.JSONField(null=True, blank=True)
    diff = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    content_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "stage", "item_type", "item_key", "sequence"],
                name="uniq_ai_eval_teacher_decision",
            ),
        ]
        indexes = [models.Index(fields=["session", "stage", "created_at"])]
        ordering = ["session_id", "stage", "item_type", "item_key", "sequence", "id"]

    def clean(self) -> None:
        errors = {}
        if self.teacher_id and self.teacher_id != self.session.teacher_id:
            errors["teacher"] = "教师决定必须由会话所属教师作出。"
        if self.generation_id and self.generation.session_id != self.session_id:
            errors["generation"] = "教师决定与 AI 生成记录不属于同一会话。"
        if not isinstance(self.diff, dict):
            errors["diff"] = "差异必须是 JSON 对象。"
        expected_hash = ai_evaluation_content_hash(
            {
                "decision": self.decision,
                "ai_value": self.ai_value,
                "teacher_value": self.teacher_value,
                "diff": self.diff,
                "reason": self.reason,
            }
        )
        if self.content_hash != expected_hash:
            errors["content_hash"] = "教师决定内容哈希不一致。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("教师修订审计记录不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("教师修订审计记录不可删除。")
