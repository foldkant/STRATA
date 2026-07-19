from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.utils import timezone

from learning_analytics.schemas.registry import (
    EventPayloadValidationError,
    canonical_payload_size,
    get_event_schema_spec,
    validate_event_payload,
)

from .evaluation_models import (  # noqa: F401
    EvaluationPlan,
    EvaluationPlanVersion,
    EvaluationScope,
    EvaluationReviewStatus,
    EvaluationScoringExample,
    EvaluationCriterionVersion,
    EvaluationStandard,
    EvaluationStandardVersion,
    EvaluationDimension,
    EvaluationTrialConclusion,
    EvaluationTrialRecord,
    EvaluationTrialStatus,
    EvaluationTrialType,
    LessonStepEvaluationBinding,
    ClassroomEvaluationStandardUse,
    EvaluationSubmissionEvidence,
)
from .feature_models import (  # noqa: F401
    DecisionPoint,
    DecisionPointStudent,
    FeatureDefinition,
    FeatureSetVersion,
    OutcomeDefinition,
    OutcomeObservation,
    StudentFeatureSnapshot,
    TrainingDatasetRow,
    TrainingDatasetVersion,
)
from .model_models import (  # noqa: F401
    LongitudinalAnalysisRun,
    LongitudinalFeatureResult,
    ModelComparisonRun,
    ModelEvaluationResult,
    ModelPrediction,
    NegativeControlResult,
)

EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
SCHEMA_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
ALLOWED_EVENT_CONTEXT_FIELDS = {
    "class_group",
    "subject",
    "course",
    "lesson",
    "classroom_session",
    "lesson_step",
    "object_type",
    "object_id",
    "object_version",
    "opportunity_id",
    "attempt_id",
}


def new_event_idempotency_key() -> str:
    return uuid.uuid4().hex


class EventSchemaDefinition(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        RETIRED = "retired", "停用"

    class PrivacyClass(models.TextChoices):
        OPERATIONAL = "operational", "运行数据"
        BEHAVIORAL = "behavioral", "学习行为"
        ASSESSMENT = "assessment", "测评数据"
        INTERVENTION = "intervention", "教师干预"
        SYSTEM_QUALITY = "system_quality", "系统质量"

    class AnalysisUnit(models.TextChoices):
        STUDENT = "student", "学生"
        GROUP = "group", "小组"
        CLASS = "class", "班级"
        CONTENT = "content", "学习内容"
        SYSTEM = "system", "系统"

    event_name = models.CharField(max_length=128)
    schema_version = models.CharField(max_length=16)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    privacy_class = models.CharField(max_length=24, choices=PrivacyClass.choices)
    analysis_unit = models.CharField(max_length=16, choices=AnalysisUnit.choices)
    payload_schema = models.JSONField(default=dict)
    required_context_fields = models.JSONField(default=list, blank=True)
    allowed_sources = models.JSONField(default=list, blank=True)
    requires_target_student = models.BooleanField(default=True)
    requires_opportunity = models.BooleanField(default=False)
    schema_hash = models.CharField(max_length=64, editable=False)
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event_name", "schema_version"],
                name="uniq_analytics_event_schema_version",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "event_name"]),
            models.Index(fields=["privacy_class", "status"]),
        ]
        ordering = ["event_name", "schema_version"]

    def semantic_definition(self) -> dict:
        return {
            "event_name": self.event_name,
            "schema_version": self.schema_version,
            "privacy_class": self.privacy_class,
            "analysis_unit": self.analysis_unit,
            "payload_schema": self.payload_schema,
            "required_context_fields": self.required_context_fields,
            "allowed_sources": self.allowed_sources,
            "requires_target_student": self.requires_target_student,
            "requires_opportunity": self.requires_opportunity,
        }

    def calculate_schema_hash(self) -> str:
        encoded = json.dumps(
            self.semantic_definition(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def clean(self) -> None:
        errors = {}
        if not EVENT_NAME_PATTERN.fullmatch(self.event_name or ""):
            errors["event_name"] = "事件名必须使用小写点分格式，例如 item.submitted。"
        if not SCHEMA_VERSION_PATTERN.fullmatch(self.schema_version or ""):
            errors["schema_version"] = "模式版本必须使用 major.minor 格式，例如 1.0。"
        if not isinstance(self.payload_schema, dict):
            errors["payload_schema"] = "载荷模式必须是 JSON 对象。"
        if not isinstance(self.required_context_fields, list):
            errors["required_context_fields"] = "必需上下文字段必须是列表。"
        elif (
            unknown_fields := set(self.required_context_fields)
            - ALLOWED_EVENT_CONTEXT_FIELDS
        ):
            errors["required_context_fields"] = (
                f"包含未知上下文字段：{', '.join(sorted(unknown_fields))}。"
            )
        if not isinstance(self.allowed_sources, list) or not self.allowed_sources:
            errors["allowed_sources"] = "至少登记一个允许的事件来源。"
        if self.status == self.Status.ACTIVE and not self.activated_at:
            self.activated_at = timezone.now()
        if self.status == self.Status.RETIRED and not self.retired_at:
            self.retired_at = timezone.now()
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        self.schema_hash = self.calculate_schema_hash()
        if previous and previous.status in {self.Status.ACTIVE, self.Status.RETIRED}:
            if previous.schema_hash != self.schema_hash:
                raise ValidationError("已启用的事件模式不可修改；请登记新的模式版本。")
        if previous and previous.status == self.Status.ACTIVE:
            if self.status not in {self.Status.ACTIVE, self.Status.RETIRED}:
                raise ValidationError("已启用的事件模式只能停用，不能退回草稿。")
        if (
            previous
            and previous.status == self.Status.RETIRED
            and self.status != self.Status.RETIRED
        ):
            raise ValidationError("已停用的事件模式不能重新启用；请登记新的模式版本。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.Status.ACTIVE:
            raise ValidationError("已启用的事件模式不可删除，只能停用。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.event_name}@{self.schema_version}"


class LearningEventV2(models.Model):
    class QualityStatus(models.TextChoices):
        RECEIVED = "received", "已接收"
        SCHEMA_VALID = "schema_valid", "模式有效"
        CONTEXT_VALID = "context_valid", "上下文有效"
        DEDUPLICATED = "deduplicated", "已去重"
        ACCEPTED = "accepted", "已接受"
        QUARANTINED = "quarantined", "已隔离"
        LEGACY_UNMAPPED = "legacy_unmapped", "旧事件未映射"

    event_id = models.UUIDField(default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(
        max_length=64, default=new_event_idempotency_key, editable=False
    )
    event_fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    schema_definition = models.ForeignKey(
        EventSchemaDefinition,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_name = models.CharField(max_length=128)
    schema_version = models.CharField(max_length=16)
    source = models.CharField(max_length=64)
    client_version = models.CharField(max_length=32, blank=True)
    legacy_event = models.OneToOneField(
        "learning.LearningEvent",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analytics_event_v2",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analytics_events_performed",
    )
    target_student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analytics_events_received",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="learning_events_v2",
    )
    synthetic_run = models.ForeignKey(
        "SyntheticDatasetRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_events_v2",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_events_v2",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_events_v2",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_events_v2",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_events_v2",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_events_v2",
    )
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=128, blank=True)
    object_version = models.CharField(max_length=64, blank=True)
    opportunity_id = models.UUIDField(null=True, blank=True)
    opportunity_record = models.ForeignKey(
        "LearningOpportunity",
        to_field="opportunity_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
    )
    attempt_id = models.UUIDField(null=True, blank=True)
    client_session_id = models.UUIDField(null=True, blank=True)
    client_sequence = models.PositiveBigIntegerField(null=True, blank=True)
    client_occurred_at = models.DateTimeField(db_index=True)
    server_received_at = models.DateTimeField(default=timezone.now, db_index=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    score_raw = models.FloatField(null=True, blank=True)
    score_max = models.FloatField(null=True, blank=True)
    delivered_band = models.CharField(max_length=8, blank=True)
    evaluation_version = models.CharField(max_length=64, blank=True)
    model_version = models.CharField(max_length=128, blank=True)
    privacy_class = models.CharField(
        max_length=24, choices=EventSchemaDefinition.PrivacyClass.choices
    )
    analysis_unit = models.CharField(
        max_length=16, choices=EventSchemaDefinition.AnalysisUnit.choices
    )
    payload = models.JSONField(default=dict, blank=True)
    quality_status = models.CharField(
        max_length=24,
        choices=QualityStatus.choices,
        default=QualityStatus.RECEIVED,
    )
    quality_errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "event_id"],
                name="uniq_analytics_event_id_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "idempotency_key"],
                name="uniq_analytics_idempotency_per_school",
            ),
            models.CheckConstraint(
                condition=models.Q(score_max__isnull=True) | models.Q(score_max__gt=0),
                name="analytics_event_score_max_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "server_received_at"]),
            models.Index(fields=["target_student", "subject", "client_occurred_at"]),
            models.Index(fields=["event_name", "server_received_at"]),
            models.Index(fields=["class_group", "client_occurred_at"]),
            models.Index(fields=["quality_status", "server_received_at"]),
        ]
        ordering = ["-server_received_at", "-id"]

    def clean(self) -> None:
        errors = {}
        registered_spec = None
        try:
            registered_spec = get_event_schema_spec(
                self.event_name, self.schema_version
            )
        except EventPayloadValidationError as exc:
            errors["event_name"] = str(exc)
        if self.schema_definition_id:
            definition = self.schema_definition
            if (self.event_name, self.schema_version) != (
                definition.event_name,
                definition.schema_version,
            ):
                errors["schema_definition"] = "事件名或模式版本与注册定义不一致。"
            if (
                registered_spec
                and definition.schema_hash != registered_spec.schema_hash
            ):
                errors["schema_definition"] = "数据库事件模式与代码注册表哈希不一致。"
            if definition.status != EventSchemaDefinition.Status.ACTIVE:
                errors["schema_definition"] = "只能写入已启用的事件模式。"
            if self.source not in definition.allowed_sources:
                errors["source"] = "该事件来源未在模式中登记。"
            if self.privacy_class != definition.privacy_class:
                errors["privacy_class"] = "隐私类别与事件模式不一致。"
            if self.analysis_unit != definition.analysis_unit:
                errors["analysis_unit"] = "分析单位与事件模式不一致。"
            if definition.requires_target_student and not self.target_student_id:
                errors["target_student"] = "该事件必须指定证据归属学生。"
            if definition.requires_opportunity and not self.opportunity_id:
                errors["opportunity_id"] = "该事件必须关联学习机会。"
            for field_name in definition.required_context_fields:
                if not getattr(self, field_name, None):
                    errors.setdefault("required_context", []).append(field_name)

        if self.actor_id and self.actor.school_id not in {None, self.school_id}:
            errors["actor"] = "事件执行人与事件学校不一致。"
        if self.synthetic_run_id:
            if self.synthetic_run.school_id != self.school_id:
                errors["synthetic_run"] = "合成数据批次与事件学校不一致。"
        if self.target_student_id:
            if self.target_student.school_id != self.school_id:
                errors["target_student"] = "目标学生与事件学校不一致。"
            if self.target_student.role != self.target_student.Role.STUDENT:
                errors["target_student"] = "证据归属对象必须是学生。"
            if self.class_group_id:
                try:
                    target_profile = self.target_student.student_profile
                except ObjectDoesNotExist:
                    errors["target_student"] = "目标学生缺少学生档案。"
                else:
                    if target_profile.class_group_id != self.class_group_id:
                        errors["target_student"] = "目标学生不属于事件班级。"
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "班级与事件学校不一致。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与事件学校不一致。"
        if (
            self.course_id
            and self.subject_id
            and self.course.subject_id != self.subject_id
        ):
            errors["course"] = "课程与学科上下文不一致。"
        if (
            self.lesson_id
            and self.course_id
            and self.lesson.course_id != self.course_id
        ):
            errors["lesson"] = "课时与课程上下文不一致。"
        if (
            self.lesson_step_id
            and self.lesson_id
            and self.lesson_step.lesson_id != self.lesson_id
        ):
            errors["lesson_step"] = "环节与课时上下文不一致。"
        if self.classroom_session_id:
            session = self.classroom_session
            if session.school_id != self.school_id or (
                self.class_group_id and session.class_group_id != self.class_group_id
            ):
                errors["classroom_session"] = "课堂与学校或班级上下文不一致。"
            if self.course_id and session.course_id != self.course_id:
                errors["classroom_session"] = "课堂与课程上下文不一致。"
            if self.lesson_id and session.lesson_id != self.lesson_id:
                errors["classroom_session"] = "课堂与课时上下文不一致。"
        if self.opportunity_record_id:
            opportunity = self.opportunity_record
            if self.opportunity_id != opportunity.opportunity_id:
                errors["opportunity_record"] = "学习机会 UUID 与外键记录不一致。"
            if opportunity.school_id != self.school_id:
                errors["opportunity_record"] = "学习机会与事件学校不一致。"
            if (
                self.target_student_id
                and opportunity.student_id != self.target_student_id
            ):
                errors["opportunity_record"] = "学习机会不属于事件目标学生。"
            if (
                self.class_group_id
                and opportunity.class_group_id != self.class_group_id
            ):
                errors["opportunity_record"] = "学习机会与事件班级不一致。"
            if self.subject_id and opportunity.subject_id != self.subject_id:
                errors["opportunity_record"] = "学习机会与事件学科不一致。"
            if self.object_id and opportunity.object_id != self.object_id:
                errors["opportunity_record"] = "学习机会与事件对象不一致。"
            if (
                self.object_version
                and opportunity.object_version != self.object_version
            ):
                errors["opportunity_record"] = "学习机会与事件对象版本不一致。"
        elif (
            self.opportunity_id
            and self.quality_status != self.QualityStatus.LEGACY_UNMAPPED
        ):
            errors["opportunity_record"] = "V2 接受事件必须关联可验证的学习机会记录。"

        if not isinstance(self.payload, dict):
            errors["payload"] = "事件载荷必须是 JSON 对象。"
        else:
            try:
                self.payload = validate_event_payload(
                    self.event_name, self.schema_version, self.payload
                )
            except EventPayloadValidationError as exc:
                errors["payload"] = str(exc)
            else:
                if canonical_payload_size(self.payload) > 16 * 1024:
                    errors["payload"] = "事件载荷不能超过 16KB。"

        if not isinstance(self.quality_errors, list):
            errors["quality_errors"] = "质量错误必须是列表。"
        if self.event_fingerprint and not re.fullmatch(
            r"[0-9a-f]{64}", self.event_fingerprint
        ):
            errors["event_fingerprint"] = "事件指纹必须是 64 位小写 SHA-256。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("学习事件 V2 是不可变事实，不能原地修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "学习事件 V2 不允许直接删除；请按数据保留策略执行受审计清理。"
        )

    def __str__(self) -> str:
        return f"{self.event_name}@{self.schema_version}:{self.event_id}"


class LearningOpportunity(models.Model):
    class ContentType(models.TextChoices):
        RESOURCE = "resource", "资源"
        VIDEO = "video", "视频"
        DOCUMENT = "document", "文档"
        QUESTION = "question", "题目"
        TASK = "task", "任务"
        LEARNING_PAGE = "learning_page", "AI 学习网页"
        PROJECT = "project", "项目"
        ATTENDANCE = "attendance", "签到考勤"
        INTERACTION = "interaction", "课堂互动"

    class InstructionalPhase(models.TextChoices):
        ORIENTATION = "orientation", "导入定向"
        PLANNING = "planning", "计划"
        EXECUTION = "execution", "执行"
        MONITORING = "monitoring", "监控"
        REVISION = "revision", "修订"
        REFLECTION = "reflection", "反思"
        UNSPECIFIED = "unspecified", "未标注"

    opportunity_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    release_event = models.ForeignKey(
        LearningEventV2,
        on_delete=models.PROTECT,
        related_name="released_opportunities",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="learning_opportunities",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="learning_opportunities",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="learning_opportunities",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="learning_opportunities",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_opportunities",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_opportunities",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_opportunities",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_opportunities",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_learning_opportunities",
    )
    content_type = models.CharField(max_length=24, choices=ContentType.choices)
    object_id = models.CharField(max_length=128)
    object_version = models.CharField(max_length=64)
    required = models.BooleanField(default=True)
    delivered_band = models.CharField(max_length=8, default="all")
    support_version = models.CharField(max_length=64, blank=True)
    unit_key = models.CharField(max_length=128, blank=True)
    instructional_phase = models.CharField(
        max_length=24,
        choices=InstructionalPhase.choices,
        default=InstructionalPhase.UNSPECIFIED,
    )
    group_key = models.CharField(max_length=128, blank=True)
    artifact_key = models.CharField(max_length=128, blank=True)
    role_version = models.CharField(max_length=64, blank=True)
    assigned_at = models.DateTimeField()
    released_at = models.DateTimeField()
    available_from = models.DateTimeField()
    available_to = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "release_event"],
                name="uniq_opportunity_student_release_event",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "class_group", "released_at"]),
            models.Index(fields=["student", "subject", "released_at"]),
            models.Index(fields=["content_type", "object_id", "object_version"]),
            models.Index(fields=["available_to"]),
        ]
        ordering = ["-released_at", "student_id"]

    def clean(self) -> None:
        errors = {}
        if self.release_event_id:
            release_event = self.release_event
            if release_event.event_name != "content.released":
                errors["release_event"] = "学习机会必须来源于 content.released 事件。"
            if release_event.school_id != self.school_id:
                errors["release_event"] = "投放事件与学习机会学校不一致。"
            if release_event.class_group_id != self.class_group_id:
                errors["release_event"] = "投放事件与学习机会班级不一致。"
        if self.student_id:
            if self.student.role != self.student.Role.STUDENT:
                errors["student"] = "学习机会只能分配给学生。"
            if self.student.school_id != self.school_id:
                errors["student"] = "学生与学习机会学校不一致。"
            try:
                profile = self.student.student_profile
            except ObjectDoesNotExist:
                errors["student"] = "学生缺少学生档案。"
            else:
                if profile.class_group_id != self.class_group_id:
                    errors["student"] = "学生不属于学习机会班级。"
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "班级与学习机会学校不一致。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与学习机会学校不一致。"
        if self.course_id and self.course.subject_id != self.subject_id:
            errors["course"] = "课程与学习机会学科不一致。"
        if self.lesson_id and self.lesson.course_id != self.course_id:
            errors["lesson"] = "课时与学习机会课程不一致。"
        if self.lesson_step_id and self.lesson_step.lesson_id != self.lesson_id:
            errors["lesson_step"] = "环节与学习机会课时不一致。"
        if not self.object_version:
            errors["object_version"] = "学习机会必须绑定不可变内容版本。"
        if self.delivered_band not in {"all", "A", "B", "C", "A/B", "B/C", "A/B/C"}:
            errors["delivered_band"] = "内容投放带不合法。"
        if self.released_at < self.assigned_at:
            errors["released_at"] = "开放时间不能早于分配时间。"
        if self.available_from < self.assigned_at:
            errors["available_from"] = "可用开始时间不能早于分配时间。"
        if self.available_to and self.available_to <= self.available_from:
            errors["available_to"] = "可用结束时间必须晚于开始时间。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("学习机会是不可变分母事实，不能原地修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "学习机会不能直接删除；撤回、豁免或不可用必须追加状态事实。"
        )

    def __str__(self) -> str:
        return f"{self.student_id}:{self.content_type}:{self.object_id}@{self.object_version}"


class LearningOpportunityTransitionFact(models.Model):
    class State(models.TextChoices):
        ASSIGNED = "assigned", "已分配"
        RELEASED = "released", "已开放"
        EXPOSED = "exposed", "已呈现"
        STARTED = "started", "已开始"
        SUBMITTED = "submitted", "已提交"
        GRADED = "graded", "已评分"
        WITHDRAWN = "withdrawn", "已撤回"
        EXCUSED = "excused", "已豁免"
        UNAVAILABLE = "unavailable", "不可用"

    TERMINAL_STATES = {State.WITHDRAWN, State.EXCUSED, State.UNAVAILABLE}

    transition_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    opportunity = models.ForeignKey(
        LearningOpportunity,
        on_delete=models.PROTECT,
        related_name="transition_facts",
    )
    state = models.CharField(max_length=16, choices=State.choices)
    source_event = models.ForeignKey(
        LearningEventV2,
        on_delete=models.PROTECT,
        related_name="opportunity_transition_facts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_opportunity_transition_facts",
    )
    reason_code = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "state", "source_event"],
                name="uniq_opportunity_state_source_event",
            ),
            models.UniqueConstraint(
                fields=["opportunity"],
                condition=models.Q(state__in=["withdrawn", "excused", "unavailable"]),
                name="uniq_opportunity_terminal_fact",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "occurred_at"]),
            models.Index(fields=["state", "occurred_at"]),
            models.Index(fields=["source_event"]),
        ]
        ordering = ["occurred_at", "id"]

    def clean(self) -> None:
        errors = {}
        if not isinstance(self.metadata, dict):
            errors["metadata"] = "状态证据元数据必须是 JSON 对象。"
        if self.state in self.TERMINAL_STATES and not self.reason_code:
            errors["reason_code"] = "撤回、豁免或不可用状态必须填写结构化原因码。"
        if self.source_event_id:
            if self.source_event.school_id != self.opportunity.school_id:
                errors["source_event"] = "状态来源事件与学习机会学校不一致。"
            if self.source_event.target_student_id not in {
                None,
                self.opportunity.student_id,
            }:
                errors["source_event"] = "状态来源事件不属于学习机会学生。"
        if self.actor_id and self.actor.school_id != self.opportunity.school_id:
            errors["actor"] = "状态执行人与学习机会学校不一致。"
        if self.occurred_at < self.opportunity.assigned_at:
            errors["occurred_at"] = "状态时间不能早于机会分配时间。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("学习机会状态事实不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("学习机会状态事实不可直接删除。")

    def __str__(self) -> str:
        return f"{self.opportunity_id}:{self.state}"


class AssessmentResultFact(models.Model):
    class GradingState(models.TextChoices):
        PENDING = "pending", "待评分"
        FINAL = "final", "最终评分"
        REVISED = "revised", "修订评分"

    class GraderType(models.TextChoices):
        AUTOMATIC = "automatic", "自动评分"
        TEACHER = "teacher", "教师评分"
        EVALUATION = "evaluation", "评价标准评分"

    result_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    opportunity = models.ForeignKey(
        LearningOpportunity,
        on_delete=models.PROTECT,
        related_name="assessment_result_facts",
    )
    source_event = models.OneToOneField(
        LearningEventV2,
        on_delete=models.PROTECT,
        related_name="assessment_result_fact",
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="assessment_result_facts",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assessment_result_facts",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="assessment_result_facts",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="assessment_result_facts",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_result_facts",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_result_facts",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_result_facts",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_result_facts",
    )
    grader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_results_graded",
    )
    attempt_id = models.UUIDField()
    object_id = models.CharField(max_length=128)
    object_version = models.CharField(max_length=64)
    grade_version = models.PositiveIntegerField()
    grading_state = models.CharField(max_length=16, choices=GradingState.choices)
    score_raw = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )
    score_max = models.DecimalField(max_digits=12, decimal_places=4)
    is_correct = models.BooleanField(null=True, blank=True)
    grader_type = models.CharField(max_length=16, choices=GraderType.choices)
    graded_at = models.DateTimeField()
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "attempt_id", "grade_version"],
                name="uniq_assessment_result_grade_version",
            ),
            models.CheckConstraint(
                condition=models.Q(score_max__gt=0),
                name="assessment_result_score_max_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(score_raw__isnull=True) | models.Q(score_raw__gte=0),
                name="assessment_result_score_raw_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(score_raw__isnull=True)
                | models.Q(score_raw__lte=models.F("score_max")),
                name="assessment_result_score_within_max",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "graded_at"]),
            models.Index(fields=["student", "subject", "graded_at"]),
            models.Index(fields=["opportunity", "attempt_id", "grade_version"]),
            models.Index(fields=["grading_state", "recorded_at"]),
        ]
        ordering = ["opportunity_id", "attempt_id", "grade_version"]

    @property
    def is_mature(self) -> bool:
        return self.grading_state in {
            self.GradingState.FINAL,
            self.GradingState.REVISED,
        }

    @property
    def normalized_score(self) -> Decimal | None:
        if self.score_raw is None or not self.score_max:
            return None
        return self.score_raw / self.score_max

    def clean(self) -> None:
        errors = {}
        if self.opportunity_id:
            opportunity = self.opportunity
            expected = {
                "school_id": opportunity.school_id,
                "student_id": opportunity.student_id,
                "class_group_id": opportunity.class_group_id,
                "subject_id": opportunity.subject_id,
                "course_id": opportunity.course_id,
                "lesson_id": opportunity.lesson_id,
                "classroom_session_id": opportunity.classroom_session_id,
                "lesson_step_id": opportunity.lesson_step_id,
                "object_id": opportunity.object_id,
                "object_version": opportunity.object_version,
            }
            for field_name, expected_value in expected.items():
                if getattr(self, field_name) != expected_value:
                    errors[field_name] = "评分事实与学习机会不一致。"
        if self.source_event_id:
            event = self.source_event
            if event.event_name != "item.graded":
                errors["source_event"] = "评分事实必须来源于 item.graded 事件。"
            if event.opportunity_record_id != self.opportunity_id:
                errors["source_event"] = "评分事件与学习机会不一致。"
            if event.attempt_id != self.attempt_id:
                errors["attempt_id"] = "评分事实与事件尝试编号不一致。"
            if event.target_student_id != self.student_id:
                errors["student"] = "评分事件与目标学生不一致。"
            payload = event.payload if isinstance(event.payload, dict) else {}
            if payload.get("grading_state") != self.grading_state:
                errors["grading_state"] = "评分成熟状态与来源事件不一致。"
            if payload.get("grader_type") != self.grader_type:
                errors["grader_type"] = "评分方式与来源事件不一致。"
            try:
                payload_max = Decimal(str(payload.get("score_max")))
                payload_raw = (
                    None
                    if payload.get("score_raw") is None
                    else Decimal(str(payload.get("score_raw")))
                )
            except (InvalidOperation, TypeError, ValueError):
                errors["source_event"] = "来源事件评分数值不合法。"
            else:
                if payload_max != self.score_max or payload_raw != self.score_raw:
                    errors["source_event"] = "评分数值与来源事件不一致。"
        if self.is_mature and self.score_raw is None:
            errors["score_raw"] = "最终或修订评分必须包含实际得分。"
        if self.grading_state == self.GradingState.REVISED and not self.supersedes_id:
            errors["supersedes"] = "修订评分必须引用被修订的成熟评分。"
        if self.supersedes_id:
            previous = self.supersedes
            if previous.opportunity_id != self.opportunity_id:
                errors["supersedes"] = "被替代评分不属于同一学习机会。"
            if previous.attempt_id != self.attempt_id:
                errors["supersedes"] = "被替代评分不属于同一次作答。"
            if previous.grade_version >= self.grade_version:
                errors["grade_version"] = "评分版本必须晚于被替代版本。"
            if (
                self.grading_state == self.GradingState.REVISED
                and not previous.is_mature
            ):
                errors["supersedes"] = "修订评分只能替代最终或修订评分。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("评分结果事实不可原地修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("评分结果事实不可直接删除。")

    def __str__(self) -> str:
        return (
            f"{self.student_id}:{self.object_id}:{self.attempt_id}@{self.grade_version}"
        )


class ParticipationPointLedger(models.Model):
    class EntryType(models.TextChoices):
        AWARD = "award", "加分"
        DEDUCTION = "deduction", "扣分"
        REVERSAL = "reversal", "冲正"

    entry_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source_event = models.OneToOneField(
        LearningEventV2,
        on_delete=models.PROTECT,
        related_name="participation_point_entry",
    )
    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal_entries",
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="participation_point_entries",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="participation_point_entries",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="participation_point_entries",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participation_point_entries",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participation_point_entries",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participation_point_entries",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participation_point_entries",
    )
    awarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participation_points_awarded",
    )
    academic_period = models.CharField(max_length=32, blank=True)
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    reason_code = models.CharField(max_length=64)
    delta = models.DecimalField(max_digits=10, decimal_places=2)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(delta=0),
                name="participation_point_delta_nonzero",
            ),
            models.CheckConstraint(
                condition=models.Q(delta__gte=-100) & models.Q(delta__lte=100),
                name="participation_point_delta_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(balance_before__gte=0)
                & models.Q(balance_after__gte=0),
                name="participation_point_balance_nonnegative",
            ),
            models.UniqueConstraint(
                fields=["reversal_of"],
                condition=models.Q(reversal_of__isnull=False),
                name="uniq_participation_point_reversal",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "class_group", "recorded_at"]),
            models.Index(fields=["student", "recorded_at"]),
            models.Index(fields=["classroom_session", "recorded_at"]),
            models.Index(fields=["reason_code", "recorded_at"]),
        ]
        ordering = ["recorded_at", "id"]

    def clean(self) -> None:
        errors = {}
        if self.student_id:
            if self.student.role != self.student.Role.STUDENT:
                errors["student"] = "积分流水目标必须是学生。"
            if self.student.school_id != self.school_id:
                errors["student"] = "积分流水学生与学校不一致。"
            try:
                profile = self.student.student_profile
            except ObjectDoesNotExist:
                errors["student"] = "积分流水学生缺少学生档案。"
            else:
                if profile.class_group_id != self.class_group_id:
                    errors["class_group"] = "积分流水班级与学生当前班级不一致。"
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "积分流水班级与学校不一致。"
        if self.source_event_id:
            event = self.source_event
            if event.school_id != self.school_id:
                errors["source_event"] = "积分来源事件与学校不一致。"
            if event.target_student_id != self.student_id:
                errors["source_event"] = "积分来源事件与学生不一致。"
            if event.class_group_id != self.class_group_id:
                errors["source_event"] = "积分来源事件与班级不一致。"
            context_pairs = (
                ("subject_id", self.subject_id),
                ("course_id", self.course_id),
                ("lesson_id", self.lesson_id),
                ("classroom_session_id", self.classroom_session_id),
            )
            if any(
                getattr(event, field_name) != value
                for field_name, value in context_pairs
            ):
                errors["source_event"] = "积分来源事件与教学上下文不一致。"
            if self.awarded_by_id and event.actor_id != self.awarded_by_id:
                errors["source_event"] = "积分来源事件执行人与确认教师不一致。"
        if self.awarded_by_id:
            if self.awarded_by.role != self.awarded_by.Role.TEACHER:
                errors["awarded_by"] = "积分只能由教师确认。"
            if self.awarded_by.school_id != self.school_id:
                errors["awarded_by"] = "积分执行教师与学校不一致。"
        if self.entry_type == self.EntryType.AWARD and self.delta <= 0:
            errors["delta"] = "加分流水必须为正数。"
        if self.entry_type == self.EntryType.DEDUCTION and self.delta >= 0:
            errors["delta"] = "扣分流水必须为负数。"
        if self.entry_type == self.EntryType.REVERSAL:
            if not self.reversal_of_id:
                errors["reversal_of"] = "冲正流水必须引用原流水。"
            else:
                if self.reversal_of.student_id != self.student_id:
                    errors["reversal_of"] = "冲正流水与原流水学生不一致。"
                if self.reversal_of.school_id != self.school_id:
                    errors["reversal_of"] = "冲正流水与原流水学校不一致。"
                if self.delta != -self.reversal_of.delta:
                    errors["delta"] = "冲正分值必须与原流水方向相反且绝对值相同。"
        elif self.reversal_of_id:
            errors["reversal_of"] = "只有冲正流水可以引用原流水。"
        if self.balance_after != self.balance_before + self.delta:
            errors["balance_after"] = "流水前后余额与增量不一致。"
        if self.balance_before < 0 or self.balance_after < 0:
            errors["balance_after"] = "课堂激励积分余额不能为负数。"
        if not self.reason_code:
            errors["reason_code"] = "积分流水必须包含结构化原因码。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("课堂积分流水不可原地修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("课堂积分流水不可直接删除；请追加冲正流水。")

    def __str__(self) -> str:
        return f"{self.student_id}:{self.delta}:{self.reason_code}"


class StudentLearningSummary(models.Model):
    class WindowType(models.TextChoices):
        DAY = "day", "当日"
        DAYS_7 = "7d", "近 7 日"
        DAYS_30 = "30d", "近 30 日"
        UNIT = "unit", "单元"

    class DataStatus(models.TextChoices):
        AVAILABLE = "available", "材料可用"
        INSUFFICIENT = "insufficient", "材料不足"
        NO_OPPORTUNITY = "no_opportunity", "没有学习任务"
        QUALITY_BLOCKED = "quality_blocked", "学习记录需检查"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="student_learning_summaries"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learning_summaries"
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, related_name="student_learning_summaries"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="student_learning_summaries"
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.PROTECT, null=True, blank=True, related_name="student_learning_summaries"
    )
    window_type = models.CharField(max_length=16, choices=WindowType.choices)
    period_key = models.CharField(max_length=128)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    data_status = models.CharField(max_length=24, choices=DataStatus.choices)
    metrics = models.JSONField(default=dict)
    missing_data = models.JSONField(default=list, blank=True)
    source_hash = models.CharField(max_length=64)
    generator_version = models.CharField(max_length=32, default="summary-v1")
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "subject", "course", "window_type", "period_key"],
                name="uniq_student_learning_summary_scope",
            )
        ]
        indexes = [
            models.Index(fields=["school", "class_group", "window_type", "window_end"]),
            models.Index(fields=["student", "subject", "window_end"]),
            models.Index(fields=["data_status", "generated_at"]),
        ]
        ordering = ["-window_end", "student_id", "subject_id"]

    def clean(self) -> None:
        errors = {}
        if self.window_end <= self.window_start:
            errors["window_end"] = "汇总结束时间必须晚于开始时间。"
        if self.student_id and self.student.role != self.student.Role.STUDENT:
            errors["student"] = "学习情况汇总只能属于学生。"
        if self.student_id and self.student.school_id != self.school_id:
            errors["student"] = "学生与汇总学校不一致。"
        if self.class_group_id and self.class_group.school_id != self.school_id:
            errors["class_group"] = "班级与汇总学校不一致。"
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "学科与汇总学校不一致。"
        if self.course_id and self.course.subject_id != self.subject_id:
            errors["course"] = "课程与汇总学科不一致。"
        if not isinstance(self.metrics, dict):
            errors["metrics"] = "学习情况必须是对象。"
        if not isinstance(self.missing_data, list):
            errors["missing_data"] = "材料说明必须是列表。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.student_id}:{self.subject_id}:{self.window_type}:{self.period_key}"


class LearningEventRejection(models.Model):
    class ReplayStatus(models.TextChoices):
        PENDING = "pending", "待处理"
        REPLAYED = "replayed", "已重放"
        DISCARDED = "discarded", "已丢弃"

    rejection_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="learning_event_rejections",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_event_rejections",
    )
    event_id = models.UUIDField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=64, blank=True)
    event_name = models.CharField(max_length=128, blank=True)
    schema_version = models.CharField(max_length=16, blank=True)
    source = models.CharField(max_length=64, blank=True)
    client_occurred_at = models.DateTimeField(null=True, blank=True)
    server_received_at = models.DateTimeField(default=timezone.now)
    error_code = models.CharField(max_length=64)
    errors = models.JSONField(default=list, blank=True)
    encrypted_envelope = models.TextField()
    envelope_hash = models.CharField(max_length=64)
    envelope_size_bytes = models.PositiveIntegerField(default=0)
    encryption_key_id = models.CharField(max_length=16)
    is_replayable = models.BooleanField(default=True)
    replay_status = models.CharField(
        max_length=16, choices=ReplayStatus.choices, default=ReplayStatus.PENDING
    )
    retention_expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "server_received_at"]),
            models.Index(fields=["school", "error_code", "server_received_at"]),
            models.Index(fields=["replay_status", "retention_expires_at"]),
            models.Index(fields=["event_id"]),
        ]
        ordering = ["-server_received_at", "-id"]

    def clean(self) -> None:
        if not isinstance(self.errors, list):
            raise ValidationError({"errors": "拒绝原因必须是列表。"})
        if self.retention_expires_at <= self.server_received_at:
            raise ValidationError(
                {"retention_expires_at": "隔离数据保留期限必须晚于接收时间。"}
            )
        if (
            not self.encrypted_envelope
            or not self.envelope_hash
            or not self.encryption_key_id
        ):
            raise ValidationError("隔离事件必须保存加密信封、摘要和密钥标识。")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            previous = type(self).objects.get(pk=self.pk)
            immutable_fields = (
                "school_id",
                "actor_id",
                "event_id",
                "idempotency_key",
                "event_name",
                "schema_version",
                "source",
                "client_occurred_at",
                "server_received_at",
                "error_code",
                "errors",
                "encrypted_envelope",
                "envelope_hash",
                "envelope_size_bytes",
                "encryption_key_id",
                "is_replayable",
                "retention_expires_at",
            )
            if any(
                getattr(previous, field) != getattr(self, field)
                for field in immutable_fields
            ):
                raise ValidationError("拒绝事件的原始审计字段不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.error_code}:{self.event_name or self.rejection_id}"


class AnalyticsOperatingMode(models.Model):
    class Mode(models.TextChoices):
        COLLECT_ONLY = "collect_only", "仅采集"
        SHADOW = "shadow", "影子运行"
        TEACHER_REVIEW = "teacher_review", "教师审核"
        ACTIVE = "active", "正式投放"
        SUSPENDED = "suspended", "已暂停"

    school = models.OneToOneField(
        "school.School",
        on_delete=models.CASCADE,
        related_name="analytics_operating_mode",
    )
    mode = models.CharField(
        max_length=24, choices=Mode.choices, default=Mode.COLLECT_ONLY
    )
    reason = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_analytics_operating_modes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["school_id"]

    def __str__(self) -> str:
        return f"{self.school}:{self.mode}"


class SensitiveInferenceAccessLog(models.Model):
    request_id = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="sensitive_inference_access_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sensitive_inference_access_logs",
    )
    actor_role = models.CharField(max_length=20, blank=True)
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sensitive_inference_access_logs",
    )
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64, blank=True)
    purpose = models.CharField(max_length=128)
    field_categories = models.JSONField(default=list, blank=True)
    export_requested = models.BooleanField(default=False)
    access_granted = models.BooleanField(default=False)
    denial_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["class_group", "created_at"]),
            models.Index(fields=["access_granted", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        if not isinstance(self.field_categories, list):
            raise ValidationError({"field_categories": "字段类别必须是列表。"})
        if self.class_group_id and self.class_group.school_id != self.school_id:
            raise ValidationError({"class_group": "班级与学校不一致。"})

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("敏感推断访问日志不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        outcome = "允许" if self.access_granted else "拒绝"
        return f"{self.actor_role}:{self.purpose}:{outcome}"


class SyntheticDatasetRun(models.Model):
    class Mode(models.TextChoices):
        ISOLATED_SCHOOL = "isolated_school", "独立模拟学校"
        SCHOOL_OVERLAY = "school_overlay", "校内测试叠加"

    class Status(models.TextChoices):
        PENDING = "pending", "等待生成"
        RUNNING = "running", "生成中"
        SUCCEEDED = "succeeded", "生成成功"
        FAILED = "failed", "生成失败"
        PURGED = "purged", "已清理"

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    dataset_key = models.CharField(max_length=64, unique=True)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="synthetic_dataset_runs",
    )
    mode = models.CharField(
        max_length=24,
        choices=Mode.choices,
        default=Mode.ISOLATED_SCHOOL,
    )
    generator_version = models.CharField(max_length=32)
    seed = models.PositiveBigIntegerField()
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    configuration = models.JSONField(default=dict)
    manifest_hash = models.CharField(max_length=64, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_message = models.CharField(max_length=1000, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    purge_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "status", "created_at"]),
            models.Index(fields=["generator_version", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.school_id:
            if self.mode == self.Mode.ISOLATED_SCHOOL and not self.school.is_synthetic:
                errors["school"] = "独立模拟批次只能属于合成研究学校。"
            if self.mode == self.Mode.SCHOOL_OVERLAY and self.school.is_synthetic:
                errors["school"] = "校内测试叠加批次必须属于正式学校。"
        if self.window_end <= self.window_start:
            errors["window_end"] = "生成窗口结束时间必须晚于开始时间。"
        if not isinstance(self.configuration, dict):
            errors["configuration"] = "生成配置必须是 JSON 对象。"
        if not isinstance(self.counts, dict):
            errors["counts"] = "生成计数必须是 JSON 对象。"
        if not isinstance(self.purge_summary, dict):
            errors["purge_summary"] = "清理摘要必须是 JSON 对象。"
        if self.manifest_hash and not re.fullmatch(r"[0-9a-f]{64}", self.manifest_hash):
            errors["manifest_hash"] = "清单指纹必须是 64 位小写 SHA-256。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.school.code}:{self.generator_version}:{self.dataset_key[:12]}"


class SyntheticStudentTruth(models.Model):
    synthetic_run = models.ForeignKey(
        SyntheticDatasetRun,
        on_delete=models.PROTECT,
        related_name="student_truths",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="synthetic_truth_records",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="synthetic_truth_records",
    )
    prior_mastery = models.DecimalField(max_digits=5, decimal_places=4)
    engagement = models.DecimalField(max_digits=5, decimal_places=4)
    self_regulation = models.DecimalField(max_digits=5, decimal_places=4)
    response_speed = models.DecimalField(max_digits=5, decimal_places=4)
    growth_rate = models.DecimalField(max_digits=6, decimal_places=5)
    class_effect = models.DecimalField(max_digits=6, decimal_places=5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["synthetic_run", "student"],
                name="uniq_synthetic_truth_run_student",
            )
        ]
        indexes = [
            models.Index(fields=["synthetic_run", "class_group"]),
        ]
        ordering = ["synthetic_run_id", "class_group_id", "student_id"]

    def clean(self) -> None:
        errors = {}
        if self.synthetic_run_id:
            school_id = self.synthetic_run.school_id
            if self.student_id and self.student.school_id != school_id:
                errors["student"] = "隐藏真值学生与合成批次学校不一致。"
            if self.class_group_id and self.class_group.school_id != school_id:
                errors["class_group"] = "隐藏真值班级与合成批次学校不一致。"
        if self.student_id and self.class_group_id:
            try:
                profile = self.student.student_profile
            except ObjectDoesNotExist:
                errors["student"] = "隐藏真值学生缺少学生档案。"
            else:
                if profile.class_group_id != self.class_group_id:
                    errors["class_group"] = "隐藏真值班级与学生档案不一致。"
        for field_name in (
            "prior_mastery",
            "engagement",
            "self_regulation",
            "response_speed",
        ):
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                errors[field_name] = "潜变量必须位于 0 到 1 之间。"
        if self.growth_rate < Decimal("-0.05000") or self.growth_rate > Decimal(
            "0.10000"
        ):
            errors["growth_rate"] = "成长率超出合成模型允许范围。"
        if self.class_effect < Decimal("-0.25000") or self.class_effect > Decimal(
            "0.25000"
        ):
            errors["class_effect"] = "班级效应超出合成模型允许范围。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("合成学生隐藏真值不可原地修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.synthetic_run_id}:{self.student_id}"


class EventIngestionDailyCounter(models.Model):
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="event_ingestion_daily_counters",
    )
    counter_date = models.DateField()
    source = models.CharField(max_length=64)
    synthetic_run = models.ForeignKey(
        SyntheticDatasetRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_daily_counters",
    )
    accepted_count = models.PositiveBigIntegerField(default=0)
    duplicate_count = models.PositiveBigIntegerField(default=0)
    rejected_count = models.PositiveBigIntegerField(default=0)
    late_count = models.PositiveBigIntegerField(default=0)
    offline_count = models.PositiveBigIntegerField(default=0)
    schema_error_count = models.PositiveBigIntegerField(default=0)
    context_error_count = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "counter_date", "source"],
                condition=models.Q(synthetic_run__isnull=True),
                name="uniq_operational_ingest_counter_day_source",
            ),
            models.UniqueConstraint(
                fields=["school", "counter_date", "source", "synthetic_run"],
                condition=models.Q(synthetic_run__isnull=False),
                name="uniq_synthetic_ingest_counter_day_source",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "counter_date"]),
            models.Index(fields=["source", "counter_date"]),
        ]
        ordering = ["-counter_date", "school_id", "source"]

    @property
    def attempt_count(self) -> int:
        return self.accepted_count + self.duplicate_count + self.rejected_count

    def __str__(self) -> str:
        return f"{self.school_id}:{self.counter_date}:{self.source}"


class AnalyticsPipelineRun(models.Model):
    class PipelineType(models.TextChoices):
        DATA_QUALITY = "data_quality", "数据检查"

    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", "定时"
        MANUAL = "manual", "手动"
        RETRY = "retry", "重试"

    class Status(models.TextChoices):
        PENDING = "pending", "等待"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        BLOCKED = "blocked", "检查未通过"

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="analytics_pipeline_runs",
    )
    synthetic_run = models.ForeignKey(
        SyntheticDatasetRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analytics_pipeline_runs",
    )
    pipeline_type = models.CharField(
        max_length=32,
        choices=PipelineType.choices,
        default=PipelineType.DATA_QUALITY,
    )
    trigger = models.CharField(
        max_length=16, choices=Trigger.choices, default=Trigger.SCHEDULED
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    check_version = models.CharField(max_length=32)
    code_version = models.CharField(max_length=64, blank=True)
    config_hash = models.CharField(max_length=64)
    attempt_no = models.PositiveSmallIntegerField(default=1)
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retries",
    )
    summary = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=1000, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "pipeline_type", "window_start", "window_end"],
                condition=models.Q(trigger="scheduled"),
                name="uniq_scheduled_pipeline_school_window",
            )
        ]
        indexes = [
            models.Index(fields=["school", "pipeline_type", "created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["window_end", "pipeline_type"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        if self.synthetic_run_id and self.synthetic_run.school_id != self.school_id:
            raise ValidationError({"synthetic_run": "合成批次与分析自动流程学校不一致。"})
        if self.window_end <= self.window_start:
            raise ValidationError(
                {"window_end": "自动流程窗口结束时间必须晚于开始时间。"}
            )
        if self.retry_of_id:
            if self.retry_of.school_id != self.school_id:
                raise ValidationError({"retry_of": "重试任务必须属于同一学校。"})
            if self.retry_of.pipeline_type != self.pipeline_type:
                raise ValidationError({"retry_of": "重试任务类型不一致。"})

    def __str__(self) -> str:
        return f"{self.school_id}:{self.pipeline_type}:{self.run_id}"


class AnalyticsTaskRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        SKIPPED = "skipped", "跳过"

    task_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    pipeline_run = models.ForeignKey(
        AnalyticsPipelineRun,
        on_delete=models.PROTECT,
        related_name="task_runs",
    )
    task_name = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempt_no = models.PositiveSmallIntegerField(default=1)
    metrics = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=1000, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "task_name", "attempt_no"],
                name="uniq_analytics_task_run_attempt",
            )
        ]
        indexes = [
            models.Index(fields=["pipeline_run", "status"]),
            models.Index(fields=["task_name", "created_at"]),
        ]
        ordering = ["pipeline_run_id", "created_at", "id"]

    def __str__(self) -> str:
        return f"{self.pipeline_run_id}:{self.task_name}:{self.status}"


class DataQualityReport(models.Model):
    class Status(models.TextChoices):
        GREEN = "green", "正常"
        AMBER = "amber", "需关注"
        RED = "red", "未通过"

    report_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="data_quality_reports",
    )
    pipeline_run = models.OneToOneField(
        AnalyticsPipelineRun,
        on_delete=models.PROTECT,
        related_name="quality_report",
    )
    synthetic_run = models.ForeignKey(
        SyntheticDatasetRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="data_quality_reports",
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    check_version = models.CharField(max_length=32)
    source_checksum = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices)
    checks_passed = models.BooleanField(default=False)
    event_count = models.PositiveBigIntegerField(default=0)
    receive_attempt_count = models.PositiveBigIntegerField(default=0)
    rejected_event_count = models.PositiveBigIntegerField(default=0)
    unconverted_old_event_count = models.PositiveBigIntegerField(default=0)
    unlinked_old_event_count = models.PositiveBigIntegerField(default=0)
    duplicate_rate = models.DecimalField(max_digits=7, decimal_places=6, default=0)
    invalid_event_rate = models.DecimalField(max_digits=7, decimal_places=6, default=0)
    late_event_rate = models.DecimalField(max_digits=7, decimal_places=6, default=0)
    unconverted_old_event_rate = models.DecimalField(
        max_digits=7, decimal_places=6, default=0
    )
    learning_task_link_rate = models.DecimalField(
        max_digits=7, decimal_places=6, default=0
    )
    client_offline_rate = models.DecimalField(max_digits=7, decimal_places=6, default=0)
    old_new_event_difference_rate = models.DecimalField(
        max_digits=7, decimal_places=6, default=0
    )
    thresholds = models.JSONField(default=dict)
    counts = models.JSONField(default=dict)
    issues = models.JSONField(default=list, blank=True)
    generated_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "window_end", "status"]),
            models.Index(fields=["checks_passed", "window_end"]),
        ]
        ordering = ["-window_end", "-created_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.pipeline_run_id:
            if self.pipeline_run.school_id != self.school_id:
                errors["pipeline_run"] = "检查报告与自动检查学校不一致。"
            if (
                self.pipeline_run.window_start != self.window_start
                or self.pipeline_run.window_end != self.window_end
            ):
                errors["pipeline_run"] = "检查报告与自动检查时间范围不一致。"
            if self.pipeline_run.synthetic_run_id != self.synthetic_run_id:
                errors["synthetic_run"] = "检查报告与自动检查测试数据范围不一致。"
        if self.window_end <= self.window_start:
            errors["window_end"] = "检查结束时间必须晚于开始时间。"
        if not isinstance(self.thresholds, dict) or not isinstance(self.counts, dict):
            errors["counts"] = "判断标准和数量必须是 JSON 对象。"
        if not isinstance(self.issues, list):
            errors["issues"] = "待处理问题必须是列表。"
        rates = (
            "duplicate_rate",
            "invalid_event_rate",
            "late_event_rate",
            "unconverted_old_event_rate",
            "learning_task_link_rate",
            "client_offline_rate",
            "old_new_event_difference_rate",
        )
        for field_name in rates:
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                errors[field_name] = "检查比例必须位于 0 到 1 之间。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("检查报告不可直接修改；重新检查应生成新报告。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("检查报告不可直接删除。")

    def __str__(self) -> str:
        return f"{self.school_id}:{self.window_end:%Y-%m-%d}:{self.status}"
