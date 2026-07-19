from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class EventPayloadValidationError(ValueError):
    pass


class StrictPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentReleasedPayload(StrictPayloadModel):
    content_type: Literal[
        "resource",
        "video",
        "document",
        "question",
        "task",
        "learning_page",
        "project",
    ]
    required: bool
    available_from: datetime | None = None
    available_to: datetime | None = None
    target_layers: list[Literal["all", "A", "B", "C", "A/B", "B/C", "A/B/C"]] = Field(
        default_factory=lambda: ["all"],
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_availability_window(self):
        if (
            self.available_from
            and self.available_to
            and self.available_to <= self.available_from
        ):
            raise ValueError("available_to 必须晚于 available_from")
        return self


class ContentReleasedPayloadV11(ContentReleasedPayload):
    target_student_ids: list[Annotated[int, Field(gt=0)]] | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_explicit_targets(self):
        if self.target_student_ids and len(set(self.target_student_ids)) != len(
            self.target_student_ids
        ):
            raise ValueError("target_student_ids 不能包含重复学生")
        return self


class ContentReleasedPayloadV12(ContentReleasedPayloadV11):
    content_type: Literal[
        "resource",
        "video",
        "document",
        "question",
        "task",
        "learning_page",
        "project",
        "attendance",
    ]


class ContentReleasedPayloadV13(ContentReleasedPayloadV12):
    content_type: Literal[
        "resource",
        "video",
        "document",
        "question",
        "task",
        "learning_page",
        "project",
        "attendance",
        "interaction",
    ]


class ContentWithdrawnPayload(StrictPayloadModel):
    release_event_id: uuid.UUID
    reason_code: Annotated[str, Field(min_length=1, max_length=64)]


class SessionHeartbeatPayload(StrictPayloadModel):
    foreground: bool
    idle_seconds: Annotated[int, Field(ge=0, le=3600)]
    network_state: Literal["online", "offline", "degraded", "unknown"]


class ResourceOpenedPayload(StrictPayloadModel):
    resource_format: Literal[
        "video",
        "document",
        "image",
        "audio",
        "article",
        "link",
        "archive",
        "project",
        "other",
    ]
    presentation: Literal["embedded", "popout", "external", "download", "unknown"]


class ResourceCenterOpenedPayload(StrictPayloadModel):
    resource_type: Literal["file", "article", "link", "student_project"]
    visibility: Literal["private", "classes", "school", "external"]
    origin_scope: Literal["same_school", "external_school", "unknown"]


class PretestSubmittedPayload(StrictPayloadModel):
    paper_kind: Literal["literacy", "attitude"]
    paper_version: Annotated[int, Field(ge=1, le=100_000)]
    submission_id: Annotated[int, Field(gt=0)]
    answer_count: Annotated[int, Field(ge=0, le=1000)]
    score_raw: Annotated[float, Field(ge=0)]


class LessonEnteredPayload(StrictPayloadModel):
    entrypoint: Literal["student_workspace", "classroom", "migration"]


class LessonStepEnteredPayload(StrictPayloadModel):
    step_type: Annotated[str, Field(min_length=1, max_length=32)]


class LessonStepCompletedPayload(StrictPayloadModel):
    step_type: Annotated[str, Field(min_length=1, max_length=32)]
    completion_source: Literal["student", "teacher", "server", "migration"]


class ClassroomInteractionRespondedPayload(StrictPayloadModel):
    response_type: Annotated[str, Field(min_length=1, max_length=64)]
    command: Annotated[str, Field(min_length=1, max_length=64)]
    content_length: Annotated[int, Field(ge=0, le=1000)]


class ChatMessageSentPayload(StrictPayloadModel):
    room_type: Literal["whole_class", "teacher_private", "group"]
    moderation_status: Literal["visible", "pending", "removed"]
    severity: Literal["none", "mild", "moderate", "severe"]
    content_length: Annotated[int, Field(ge=1, le=500)]


class InterventionAcknowledgedPayload(StrictPayloadModel):
    intervention_type: Annotated[str, Field(min_length=1, max_length=64)]
    action: Annotated[str, Field(min_length=1, max_length=64)]
    points: Annotated[float, Field(ge=0, le=100)] = 0


class ClassroomControlExecutedPayload(StrictPayloadModel):
    action: Annotated[str, Field(min_length=1, max_length=64)]
    object_kind: Literal["classroom_session", "classroom_activity", "lesson_step"]
    activity_type: Annotated[str, Field(max_length=32)] = ""
    step_status: Annotated[str, Field(max_length=16)] = ""
    submission_locked: bool = False
    has_layered_questions: bool = False


class LegacyUnmappedPayload(StrictPayloadModel):
    mapping_version: Annotated[str, Field(min_length=1, max_length=32)]
    reason_code: Annotated[str, Field(min_length=1, max_length=64)]
    legacy_event_type: Annotated[str, Field(min_length=1, max_length=64)]
    legacy_object_type: Annotated[str, Field(max_length=64)] = ""


class VideoProgressPayload(StrictPayloadModel):
    position_seconds: Annotated[float, Field(ge=0)]
    media_seconds: Annotated[float, Field(gt=0)]
    playback_rate: Annotated[float, Field(ge=0.25, le=4)] = 1

    @model_validator(mode="after")
    def validate_media_position(self):
        if self.position_seconds > self.media_seconds:
            raise ValueError("position_seconds 不能超过 media_seconds")
        return self


class DocumentProgressPayload(StrictPayloadModel):
    page: Annotated[int, Field(ge=1)]
    page_count: Annotated[int, Field(ge=1)]
    visible_seconds: Annotated[float, Field(ge=0, le=3600)]

    @model_validator(mode="after")
    def validate_page_range(self):
        if self.page > self.page_count:
            raise ValueError("page 不能超过 page_count")
        return self


class GroupDocumentOpenedPayload(StrictPayloadModel):
    document_version: Annotated[int, Field(ge=1, le=1_000_000)]
    presentation: Literal["embedded", "popout", "download"]
    editor_mode: Literal["view", "edit"]


class GroupDocumentSavedPayload(StrictPayloadModel):
    document_version: Annotated[int, Field(ge=2, le=1_000_000)]
    file_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    file_size: Annotated[int, Field(gt=0, le=2_147_483_648)]
    callback_status: Literal[2, 6]
    verified_editor_count: Annotated[int, Field(ge=0, le=2000)]
    attribution: Literal["group_only"] = "group_only"


class GroupFileSharedPayload(StrictPayloadModel):
    artifact_version: uuid.UUID
    version_no: Annotated[int, Field(ge=1, le=100_000)]
    file_ext: Annotated[str, Field(min_length=1, max_length=16)]
    file_size: Annotated[int, Field(gt=0, le=2_147_483_648)]


class AttendanceRecordedPayload(StrictPayloadModel):
    attendance_status: Literal["signed", "late", "leave", "absent"]
    recorded_by: Literal["student", "teacher"]
    revision_no: Annotated[int, Field(ge=1, le=10_000)]
    supersedes_event_id: uuid.UUID | None = None


class QuickAnswerRespondedPayload(StrictPayloadModel):
    response_rank: Annotated[int, Field(ge=1, le=10_000)]
    response_latency_ms: Annotated[int, Field(ge=0, le=7_200_000)]


class RandomCallSelectedPayload(StrictPayloadModel):
    selection_method: Literal["server_random", "client_draw"]
    eligible_student_count: Annotated[int, Field(ge=1, le=10_000)]
    selection_sequence: Annotated[int, Field(ge=1, le=100_000)]
    prior_selection_count: Annotated[int, Field(ge=0, le=100_000)]


class ItemSubmittedPayload(StrictPayloadModel):
    question_version: Annotated[str, Field(min_length=1, max_length=128)]
    response_kind: Literal["single", "multiple", "judge", "blank", "text", "file"]
    attempt_no: Annotated[int, Field(ge=1, le=100)]
    response_time_ms: Annotated[int, Field(ge=0, le=86_400_000)]
    learner_confidence_rating: Annotated[int, Field(ge=1, le=5)] | None = None


class ItemSubmittedPayloadV11(StrictPayloadModel):
    question_version: Annotated[str, Field(min_length=1, max_length=128)]
    response_kind: Literal["single", "multiple", "judge", "blank", "text", "file"]
    attempt_no: Annotated[int, Field(ge=1, le=100)]
    response_time_ms: Annotated[int, Field(ge=0, le=86_400_000)] | None = None
    learner_confidence_rating: Annotated[int, Field(ge=1, le=5)] | None = None


class ItemGradedPayload(StrictPayloadModel):
    grading_state: Literal["pending", "final", "revised"]
    score_raw: float | None = None
    score_max: Annotated[float, Field(gt=0)]
    is_correct: bool | None = None
    grader_type: Literal["automatic", "teacher", "rubric"]

    @model_validator(mode="after")
    def validate_score(self):
        if self.grading_state in {"final", "revised"} and self.score_raw is None:
            raise ValueError("最终评分必须包含 score_raw")
        if self.score_raw is not None and not 0 <= self.score_raw <= self.score_max:
            raise ValueError("score_raw 必须位于 0 到 score_max 之间")
        return self


class ItemGradedPayloadV11(ItemGradedPayload):
    grader_type: Literal["automatic", "teacher", "evaluation"]


class TaskSubmittedPayload(StrictPayloadModel):
    submission_version: Annotated[str, Field(min_length=1, max_length=128)]
    submitted_at: datetime
    due_at: datetime | None = None
    artifact_count: Annotated[int, Field(ge=0, le=100)]


class LearningPageOpenedPayload(StrictPayloadModel):
    page_version: Annotated[int, Field(ge=1, le=100_000)]
    block_count: Annotated[int, Field(ge=0, le=500)]
    form_count: Annotated[int, Field(ge=0, le=100)]
    presentation: Literal["embedded", "popout", "unknown"] = "unknown"


class LearningPageBlockViewedPayload(StrictPayloadModel):
    page_version: Annotated[int, Field(ge=1, le=100_000)]
    block_id: Annotated[str, Field(min_length=1, max_length=64)]
    block_type: Literal[
        "content",
        "callout",
        "list",
        "steps",
        "cards",
        "table",
        "code",
        "visualization",
        "interactive",
        "form",
    ]
    visible_ms: Annotated[int, Field(ge=250, le=3_600_000)]
    visibility_ratio: Annotated[float, Field(ge=0, le=1)]


class LearningPageFormSubmittedPayload(StrictPayloadModel):
    page_version: Annotated[int, Field(ge=1, le=100_000)]
    form_id: Annotated[str, Field(min_length=1, max_length=64)]
    response_id: Annotated[str, Field(min_length=1, max_length=64)]
    attempt_no: Annotated[int, Field(ge=1, le=10_000)]
    field_count: Annotated[int, Field(ge=0, le=200)]


class CriterionRatingPayload(StrictPayloadModel):
    criterion_id: Annotated[str, Field(min_length=1, max_length=128)]
    rating: Annotated[int, Field(ge=1, le=5)]


class RubricRatingSubmittedPayload(StrictPayloadModel):
    rubric_version: Annotated[str, Field(min_length=1, max_length=128)]
    criterion_ratings: list[CriterionRatingPayload] = Field(
        min_length=1, max_length=100
    )
    rater_role: Literal["self", "peer", "teacher"]


class CriterionNotAssessedPayload(StrictPayloadModel):
    criterion_id: Annotated[str, Field(min_length=1, max_length=128)]
    reason_code: Literal[
        "no_evidence",
        "not_observed",
        "not_applicable",
        "technical_issue",
        "other",
    ]


class EvaluationRatingSubmittedPayloadV11(StrictPayloadModel):
    evaluation_version: Annotated[str, Field(min_length=1, max_length=128)]
    criterion_ratings: list[CriterionRatingPayload] = Field(
        default_factory=list, max_length=100
    )
    not_assessed_criteria: list[CriterionNotAssessedPayload] = Field(
        default_factory=list, max_length=100
    )
    rater_role: Literal["self", "peer", "teacher"]

    @model_validator(mode="after")
    def validate_criterion_states(self):
        rated_ids = [item.criterion_id for item in self.criterion_ratings]
        skipped_ids = [item.criterion_id for item in self.not_assessed_criteria]
        if not rated_ids and not skipped_ids:
            raise ValueError("至少需要一个已评分或暂不评价的指标")
        if len(rated_ids) != len(set(rated_ids)):
            raise ValueError("已评分指标不能重复")
        if len(skipped_ids) != len(set(skipped_ids)):
            raise ValueError("暂不评价指标不能重复")
        if set(rated_ids) & set(skipped_ids):
            raise ValueError("同一指标不能同时评分和暂不评价")
        return self


class InterventionCreatedPayload(StrictPayloadModel):
    intervention_type: Annotated[str, Field(min_length=1, max_length=64)]
    reason_code: Annotated[str, Field(min_length=1, max_length=64)]
    intensity: Literal["low", "medium", "high"]


class ClientOfflinePayload(StrictPayloadModel):
    started_at: datetime
    ended_at: datetime
    queued_event_count: Annotated[int, Field(ge=0, le=10_000)]

    @model_validator(mode="after")
    def validate_offline_window(self):
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at 必须晚于 started_at")
        if (self.ended_at - self.started_at).total_seconds() > 7 * 24 * 3600:
            raise ValueError("单个离线区间不能超过 7 天")
        return self


@dataclass(frozen=True, slots=True)
class EventSchemaSpec:
    event_name: str
    schema_version: str
    description: str
    payload_model: type[StrictPayloadModel]
    privacy_class: str
    analysis_unit: str
    required_context_fields: tuple[str, ...]
    allowed_sources: tuple[str, ...]
    requires_target_student: bool = True
    requires_opportunity: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return self.event_name, self.schema_version

    @property
    def payload_schema(self) -> dict:
        return self.payload_model.model_json_schema()

    @property
    def semantic_definition(self) -> dict:
        return {
            "event_name": self.event_name,
            "schema_version": self.schema_version,
            "privacy_class": self.privacy_class,
            "analysis_unit": self.analysis_unit,
            "payload_schema": self.payload_schema,
            "required_context_fields": list(self.required_context_fields),
            "allowed_sources": list(self.allowed_sources),
            "requires_target_student": self.requires_target_student,
            "requires_opportunity": self.requires_opportunity,
        }

    @property
    def schema_hash(self) -> str:
        encoded = json.dumps(
            self.semantic_definition,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


STUDENT_SOURCES = ("student-web", "server", "migration")
TEACHER_SOURCES = ("teacher-web", "server", "worker", "migration")


_EVENT_SPECS = (
    EventSchemaSpec(
        "content.released",
        "1.0",
        "学习内容向班级或学生正式投放。",
        ContentReleasedPayload,
        "operational",
        "class",
        ("class_group", "subject", "object_id"),
        TEACHER_SOURCES,
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "content.released",
        "1.1",
        "学习内容向班级或显式学生集合正式投放。",
        ContentReleasedPayloadV11,
        "operational",
        "class",
        ("class_group", "subject", "object_id"),
        TEACHER_SOURCES,
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "content.released",
        "1.2",
        "学习内容向班级或显式学生集合正式投放，并支持签到考勤机会。",
        ContentReleasedPayloadV12,
        "operational",
        "class",
        ("class_group", "subject", "object_id"),
        TEACHER_SOURCES,
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "content.released",
        "1.3",
        "学习内容向班级或显式学生集合正式投放，并支持课堂互动机会。",
        ContentReleasedPayloadV13,
        "operational",
        "class",
        ("class_group", "subject", "object_id"),
        TEACHER_SOURCES,
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "content.withdrawn",
        "1.0",
        "教师撤回一次已投放内容及其尚未完成的学习机会。",
        ContentWithdrawnPayload,
        "operational",
        "class",
        ("class_group", "subject"),
        TEACHER_SOURCES,
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "session.heartbeat",
        "1.0",
        "学生学习会话的前台、空闲和网络状态心跳。",
        SessionHeartbeatPayload,
        "behavioral",
        "student",
        ("class_group", "subject"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "resource.opened",
        "1.0",
        "学生打开课堂已投放的普通资源；不把自动加载等同于完成学习。",
        ResourceOpenedPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "resource.center.opened",
        "1.0",
        "学生主动打开资源中心内容；该自由浏览事实不生成课堂机会分母。",
        ResourceCenterOpenedPayload,
        "behavioral",
        "student",
        ("class_group", "object_id"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "pretest.submitted",
        "1.0",
        "学生提交学科前测；答案正文保留在前测业务表。",
        PretestSubmittedPayload,
        "assessment",
        "student",
        ("class_group", "subject", "object_id"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "lesson.entered",
        "1.0",
        "学生主动进入一个已授权课时。",
        LessonEnteredPayload,
        "behavioral",
        "student",
        ("class_group", "course", "lesson", "object_id"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "lesson.step.entered",
        "1.0",
        "学生主动进入当前已投放课时环节。",
        LessonStepEnteredPayload,
        "behavioral",
        "student",
        ("class_group", "course", "lesson", "lesson_step", "object_id"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "lesson.step.completed",
        "1.0",
        "学生声明完成当前课时环节；时长保留为独立事件字段。",
        LessonStepCompletedPayload,
        "behavioral",
        "student",
        ("class_group", "course", "lesson", "lesson_step", "object_id"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "classroom.interaction.responded",
        "1.0",
        "学生响应未建立专用机会模型的普通课堂互动；不复制回答正文。",
        ClassroomInteractionRespondedPayload,
        "behavioral",
        "student",
        ("class_group", "course", "classroom_session", "object_id"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "chat.message.sent",
        "1.0",
        "课堂参与者发送实名聊天消息；只记录房间、审核状态和长度，不复制正文。",
        ChatMessageSentPayload,
        "behavioral",
        "class",
        ("class_group", "course", "classroom_session", "object_id"),
        ("student-web", "teacher-web", "server", "migration"),
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "intervention.acknowledged",
        "1.0",
        "学生确认已收到课堂积分或聊天审核干预反馈。",
        InterventionAcknowledgedPayload,
        "intervention",
        "student",
        ("class_group", "course", "classroom_session", "object_id"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "classroom.control.executed",
        "1.0",
        "教师执行课堂、环节或活动控制动作的班级级审计事实。",
        ClassroomControlExecutedPayload,
        "intervention",
        "class",
        ("class_group", "course", "classroom_session", "object_id"),
        TEACHER_SOURCES,
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "video.progress",
        "1.0",
        "学生观看已投放视频的进度。",
        VideoProgressPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "document.progress",
        "1.0",
        "学生查看已投放文档的页码和有效可见时间。",
        DocumentProgressPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "group.document.opened",
        "1.0",
        "学生打开本组协作文档；只记录访问方式和文档版本。",
        GroupDocumentOpenedPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "group.document.saved",
        "1.0",
        "ONLYOFFICE 完成一次经过验证的组级文档保存，不推断个人贡献。",
        GroupDocumentSavedPayload,
        "behavioral",
        "group",
        ("class_group", "subject", "object_id"),
        TEACHER_SOURCES,
        requires_target_student=False,
    ),
    EventSchemaSpec(
        "group.file.shared",
        "1.0",
        "学生向本组共享区提交文件；文件名和内容保留在业务表。",
        GroupFileSharedPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id", "attempt_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "attendance.recorded",
        "1.0",
        "学生自助签到或教师追加考勤状态修订；未响应不自动解释为缺勤。",
        AttendanceRecordedPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        ("student-web", "teacher-web", "server", "migration"),
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "quick_answer.responded",
        "1.0",
        "学生响应一次已开启抢答；排名和时延由服务端计算。",
        QuickAnswerRespondedPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        ("server", "migration"),
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "random_call.selected",
        "1.0",
        "教师完成一次随机点名选择；该事实不等同于学生作答或掌握。",
        RandomCallSelectedPayload,
        "intervention",
        "student",
        ("class_group", "subject", "object_id"),
        ("server", "migration"),
    ),
    EventSchemaSpec(
        "item.submitted",
        "1.0",
        "学生提交题目作答；正文保留在业务答卷表。",
        ItemSubmittedPayload,
        "assessment",
        "student",
        ("class_group", "subject", "object_id", "attempt_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "item.submitted",
        "1.1",
        "学生提交题目作答；允许旧业务在无法重建单题时长时明确记为未知。",
        ItemSubmittedPayloadV11,
        "assessment",
        "student",
        ("class_group", "subject", "object_id", "attempt_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "item.graded",
        "1.0",
        "题目作答形成评分版本。",
        ItemGradedPayload,
        "assessment",
        "student",
        ("class_group", "subject", "object_id", "attempt_id"),
        TEACHER_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "item.graded",
        "1.1",
        "题目作答形成评分版本，并使用统一的评价评分来源名称。",
        ItemGradedPayloadV11,
        "assessment",
        "student",
        ("class_group", "subject", "object_id", "attempt_id"),
        TEACHER_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "task.submitted",
        "1.0",
        "学生提交任务版本；附件明细保留在业务表。",
        TaskSubmittedPayload,
        "assessment",
        "student",
        ("class_group", "subject", "object_id", "attempt_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "learning_page.opened",
        "1.0",
        "学生打开已投放的受控 AI 学习网页。",
        LearningPageOpenedPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "learning_page.form_submitted",
        "1.0",
        "学生提交 AI 学习网页表单；答案正文保留在业务响应表。",
        LearningPageFormSubmittedPayload,
        "assessment",
        "student",
        ("class_group", "subject", "object_id", "attempt_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "learning_page.block_viewed",
        "1.0",
        "学生有效查看 AI 学习网页区块；不采集区块正文或表单值。",
        LearningPageBlockViewedPayload,
        "behavioral",
        "student",
        ("class_group", "subject", "object_id"),
        STUDENT_SOURCES,
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "evaluation.rating.submitted",
        "1.0",
        "学生或教师按已发布评价标准提交逐项五星评价。",
        RubricRatingSubmittedPayload,
        "assessment",
        "student",
        ("class_group", "subject", "object_id"),
        ("student-web", "teacher-web", "server", "migration"),
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "evaluation.rating.submitted",
        "1.1",
        "学生或教师按已发布评价标准提交逐项五星评价或暂不评价原因。",
        EvaluationRatingSubmittedPayloadV11,
        "assessment",
        "student",
        ("class_group", "subject", "object_id"),
        ("student-web", "teacher-web", "server", "migration"),
        requires_opportunity=True,
    ),
    EventSchemaSpec(
        "intervention.created",
        "1.0",
        "教师创建结构化教学干预。",
        InterventionCreatedPayload,
        "intervention",
        "student",
        ("class_group", "subject"),
        TEACHER_SOURCES,
    ),
    EventSchemaSpec(
        "client.offline",
        "1.0",
        "客户端报告离线区间和待补传事件数量。",
        ClientOfflinePayload,
        "system_quality",
        "student",
        ("class_group", "subject"),
        STUDENT_SOURCES,
    ),
    EventSchemaSpec(
        "legacy.unmapped",
        "1.0",
        "无法在不伪造上下文或学习机会的前提下确定映射语义的 V1 历史事件。",
        LegacyUnmappedPayload,
        "system_quality",
        "system",
        (),
        ("migration",),
        requires_target_student=False,
    ),
)

EVENT_SCHEMA_REGISTRY = {spec.key: spec for spec in _EVENT_SPECS}


def get_event_schema_spec(event_name: str, schema_version: str) -> EventSchemaSpec:
    try:
        return EVENT_SCHEMA_REGISTRY[(event_name, schema_version)]
    except KeyError as exc:
        raise EventPayloadValidationError(
            f"未登记的事件模式：{event_name}@{schema_version}"
        ) from exc


def validate_event_payload(event_name: str, schema_version: str, payload: dict) -> dict:
    spec = get_event_schema_spec(event_name, schema_version)
    try:
        parsed = spec.payload_model.model_validate(payload)
    except ValidationError as exc:
        messages = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(item) for item in error["loc"]) or "payload"
            messages.append(f"{location}: {error['msg']}")
        raise EventPayloadValidationError("；".join(messages)) from exc
    return parsed.model_dump(mode="json", exclude_none=True)


def canonical_payload_size(payload: dict) -> int:
    return len(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
