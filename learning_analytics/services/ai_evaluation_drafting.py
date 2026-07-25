from __future__ import annotations

import ast
import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from aiops.models import TeacherAIProvider
from courses.models import Course
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumRetrievalChunk,
    CurriculumRetrievalIndex,
    CurriculumRetrievalSourceKind,
    CurriculumStandardNode,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    SchoolStage,
)
from curriculum_standards.retrieval import retrieval_index_is_current
from learning_analytics.ai_evaluation_models import (
    AIEvaluationDraftSession,
    AIEvaluationDraftStatus,
    AIEvaluationGenerationRecord,
    AIEvaluationGenerationStage,
    AIEvaluationGenerationStatus,
    AIEvaluationTaskKind,
    AIEvaluationTeacherDecision,
    AIEvaluationTeacherDecisionType,
    ai_evaluation_content_hash,
)
from learning_analytics.evaluation_models import (
    EvaluationDimension,
    EvaluationMode,
    EvaluationReviewStatus,
    EvaluationScope,
    EvaluationStandard,
    EvidenceOwnership,
)
from learning_analytics.services.evaluation import (
    MATERIAL_TYPE_VALUES,
    MODE_MATERIAL_TYPES,
    THINKING_REQUIREMENT_VALUES,
)


ALLOWED_CURRICULUM_STATUSES = {CurriculumVersionStatus.PUBLISHED}
ALLOWED_EVALUATION_PURPOSES = {
    "entry_diagnostic": "学习起点诊断",
    "formative": "过程性评价",
    "summative": "总结性评价",
    "project": "项目学习评价",
}
MODE_LABELS = {
    EvaluationMode.TEST: "测试式评价",
    EvaluationMode.OPERATION: "操作式评价",
    EvaluationMode.PROJECT: "项目式评价",
    EvaluationMode.ARTIFACT: "作品评价",
    EvaluationMode.ORAL_DEFENSE: "答辩评价",
    EvaluationMode.MIXED: "混合评价",
}
NODE_LABELS = {
    CurriculumNodeType.CORE_COMPETENCY: "核心素养",
    CurriculumNodeType.COURSE_OBJECTIVE: "课程目标",
    CurriculumNodeType.COURSE_CONTENT: "课程内容",
    CurriculumNodeType.ACADEMIC_QUALITY: "学业质量",
}
MATERIAL_TYPE_ALIASES = {
    "answer": "answer",
    "response": "answer",
    "reflection": "answer",
    "artifact": "artifact",
    "work": "artifact",
    "operation": "operation",
    "operation_record": "operation",
    "project_process": "observation",
    "observation": "observation",
    "teacher_observation": "observation",
    "peer_feedback": "observation",
    "oral_defense": "oral_defense",
    "oral_response": "oral_defense",
    "presentation": "oral_defense",
    "score": "score",
}
ATOMIC_MODES = {
    EvaluationMode.TEST,
    EvaluationMode.OPERATION,
    EvaluationMode.PROJECT,
    EvaluationMode.ARTIFACT,
    EvaluationMode.ORAL_DEFENSE,
}
PROCESSING_STATUSES = {
    AIEvaluationDraftStatus.MODE_SUGGESTION_QUEUED,
    AIEvaluationDraftStatus.MODE_SUGGESTION_RUNNING,
    AIEvaluationDraftStatus.DRAFT_QUEUED,
    AIEvaluationDraftStatus.DRAFT_RUNNING,
}
TERMINAL_STATUSES = {
    AIEvaluationDraftStatus.SAVED,
    AIEvaluationDraftStatus.CANCELLED,
}
PII_KEY_PATTERN = re.compile(
    r"^(?:student_(?:id|name|no|number)|studentId|studentName|"
    r"user_id|username|real_name|phone|mobile|email|id_card|identity_number)$",
    re.IGNORECASE,
)
SENSITIVE_TEXT_PATTERNS = (
    (re.compile(r"(?i)\b(?:api[_ -]?key|authorization)\b\s*[:=]"), "接口密钥"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}"), "访问令牌"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "手机号码"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "身份证号码"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "电子邮箱"),
    (re.compile(r"(?:学生姓名|姓名|学号|手机号|身份证号)\s*[:：]"), "学生身份信息"),
)


@dataclass
class AIEvaluationDraftError(Exception):
    message: str
    code: str = "invalid_request"
    status: int = 400
    errors: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


def _text(value: Any, *, max_length: int = 4000) -> str:
    return str(value or "").strip()[:max_length]


def _level_description(value: Any, *, max_length: int = 1200) -> str:
    """Accept the common model variants for one observable performance level."""

    if isinstance(value, dict):
        value = (
            value.get("description")
            or value.get("text")
            or value.get("observable_performance")
            or value.get("performance")
            or ""
        )
    return _text(value, max_length=max_length)


def _string_list(value: Any, *, max_items: int = 30, max_length: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:max_items]:
        cleaned = _text(item, max_length=max_length)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _int_list(value: Any, *, allowed: set[int] | None = None) -> list[int]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        try:
            normalized = int(item)
        except (TypeError, ValueError):
            continue
        if allowed is not None and normalized not in allowed:
            continue
        if normalized not in result:
            result.append(normalized)
    return result


def _material_list(value: Any, *, mode: str = "") -> list[str]:
    result = []
    for item in _string_list(value, max_items=20, max_length=64):
        canonical = MATERIAL_TYPE_ALIASES.get(item.lower(), item.lower())
        if canonical in MATERIAL_TYPE_VALUES and canonical not in result:
            result.append(canonical)
    if result:
        return result
    if mode == EvaluationMode.MIXED:
        return ["artifact", "operation", "observation", "oral_defense"]
    if mode in MODE_MATERIAL_TYPES:
        return sorted(MODE_MATERIAL_TYPES[mode])
    return ["observation"]


MATERIAL_SOURCE_LABELS = {
    "answer": "作答记录",
    "artifact": "作品材料",
    "operation": "操作记录",
    "oral_defense": "答辩记录",
    "observation": "观察记录",
    "score": "评分记录",
}


def _evaluation_source_list(value: Any) -> list[str]:
    result = []
    for item in _string_list(value, max_items=20, max_length=160):
        canonical = MATERIAL_TYPE_ALIASES.get(item.lower(), item.lower())
        readable = MATERIAL_SOURCE_LABELS.get(canonical, item)
        if readable not in result:
            result.append(readable)
    return result


def _assert_no_sensitive_data(value: Any, *, field: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if PII_KEY_PATTERN.fullmatch(str(key)):
                raise AIEvaluationDraftError(
                    "AI 评价起草不得包含学生身份信息。",
                    code="student_identity_not_allowed",
                    errors={field: [f"不允许字段：{key}"]},
                )
            _assert_no_sensitive_data(item, field=f"{field}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_sensitive_data(item, field=f"{field}[{index}]")
        return
    if not isinstance(value, str):
        return
    for pattern, label in SENSITIVE_TEXT_PATTERNS:
        if pattern.search(value):
            raise AIEvaluationDraftError(
                "AI 评价起草不得包含学生身份信息或接口密钥。",
                code="sensitive_data_not_allowed",
                errors={field: [f"检测到{label}，请删除后重试。"]},
            )


def _safe_error_message(exc: Exception) -> str:
    value = str(exc).strip() or exc.__class__.__name__
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", value)
    value = re.sub(
        r"(?i)((?:api[_ -]?key|authorization)\s*[:=]\s*)\S+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"\b1[3-9]\d{9}\b", "[REDACTED]", value)
    value = re.sub(r"\b\d{17}[\dXx]\b", "[REDACTED]", value)
    return value[:1000]


def _normalized_subject_name(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).lower()
    for suffix in ("学科课程", "课程标准", "学科", "课程"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    aliases = {
        "信息技术": "信息科技",
        "informationtechnology": "信息科技",
        "information_technology": "信息科技",
        "思想政治": "政治",
        "生物学": "生物",
        "体育与健康": "体育",
        "道德与法治": "思想品德",
    }
    return aliases.get(text, text)


def _subjects_match(course: Course, version: CurriculumStandardVersion) -> bool:
    local = _normalized_subject_name(course.subject.name if course.subject_id else "")
    standard = _normalized_subject_name(version.subject_name_snapshot)
    return bool(local and standard and local == standard)


def _infer_stage_from_grade(value: str) -> str | None:
    normalized = re.sub(r"\s+", "", str(value or "")).lower()
    if not normalized:
        return None
    if any(token in normalized for token in ("高中", "高一", "高二", "高三")):
        return SchoolStage.SENIOR_HIGH
    if any(token in normalized for token in ("小学", "初中", "七年级", "八年级", "九年级")):
        return SchoolStage.COMPULSORY
    numbers = [int(item) for item in re.findall(r"(?<!\d)(?:1[0-2]|[1-9])(?!\d)", normalized)]
    if numbers:
        return SchoolStage.SENIOR_HIGH if max(numbers) >= 10 else SchoolStage.COMPULSORY
    return None


def _course_stages(course: Course) -> set[str]:
    stages = set()
    rows = course.course_classes.select_related("class_group").all()
    for row in rows:
        stage = _infer_stage_from_grade(row.class_group.grade or row.class_group.name)
        if stage:
            stages.add(stage)
    return stages


def _validate_course_and_version(
    *,
    teacher,
    course: Course,
    version: CurriculumStandardVersion,
    requested_stage: str,
    grade_or_stage: str,
) -> None:
    errors = {}
    if course.teacher_id != teacher.id or not course.subject_id:
        errors["course_id"] = ["只能选择本人任教且已设置学科的课程。"]
    elif course.subject.school_id != teacher.school_id:
        errors["course_id"] = ["课程与当前教师不属于同一学校。"]
    if (
        version.status not in ALLOWED_CURRICULUM_STATUSES
        or not version.source.is_active
        or version.source.current_version_id != version.id
    ):
        errors["curriculum_standard_version_id"] = ["只能使用已完成人工复核并作为当前版本发布的课程标准。"]
    if version.document_type_snapshot != CurriculumDocumentType.SUBJECT_STANDARD:
        errors["curriculum_standard_version_id"] = ["评价起草必须选择学科课程标准，不能选择课程方案。"]
    if requested_stage not in SchoolStage.values:
        errors["school_stage"] = ["学段不正确。"]
    elif version.school_stage_snapshot != requested_stage:
        errors["school_stage"] = ["所选课程标准版本与学段不一致。"]
    grade_stage = _infer_stage_from_grade(grade_or_stage)
    if grade_stage and grade_stage != requested_stage:
        errors["grade_or_stage"] = ["年级或学段说明与所选学段不一致。"]
    known_course_stages = _course_stages(course)
    if known_course_stages and requested_stage not in known_course_stages:
        errors["course_id"] = ["课程关联班级的学段与所选课程标准版本不一致。"]
    if course.subject_id and not _subjects_match(course, version):
        errors["curriculum_standard_version_id"] = [
            f"课程学科“{course.subject.name}”与课标学科“{version.subject_name_snapshot}”不一致。"
        ]
    index = CurriculumRetrievalIndex.objects.filter(version=version).first()
    if not index or not retrieval_index_is_current(version, index=index):
        errors["curriculum_standard_version_id"] = ["当前课程标准版本的 AI 检索片段尚未生成或校验未通过。"]
    if errors:
        raise AIEvaluationDraftError(
            "课程与课程标准版本校验未通过。",
            code="curriculum_scope_mismatch",
            errors=errors,
        )


def curriculum_version_options(teacher) -> list[dict]:
    courses = list(
        Course.objects.filter(teacher=teacher, subject__school=teacher.school)
        .select_related("subject")
        .prefetch_related("course_classes__class_group")
        .order_by("title", "id")
    )
    versions = list(
        CurriculumStandardVersion.objects.filter(
            status__in=ALLOWED_CURRICULUM_STATUSES,
            document_type_snapshot=CurriculumDocumentType.SUBJECT_STANDARD,
            source__is_active=True,
        )
        .select_related("source")
        .order_by("school_stage_snapshot", "subject_name_snapshot", "-publication_year", "-id")
    )
    result = []
    for version in versions:
        if version.source.current_version_id != version.id:
            continue
        index = CurriculumRetrievalIndex.objects.filter(version=version).first()
        if not index or not retrieval_index_is_current(version, index=index):
            continue
        compatible_ids = []
        for course in courses:
            stages = _course_stages(course)
            if _subjects_match(course, version) and (
                not stages or version.school_stage_snapshot in stages
            ):
                compatible_ids.append(course.id)
        if not compatible_ids:
            continue
        result.append(
            {
                "id": version.id,
                "title": version.official_title or version.title_snapshot,
                "version_label": version.version_label,
                "status": version.status,
                "status_label": version.get_status_display(),
                "school_stage": version.school_stage_snapshot,
                "subject": {
                    "id": version.source_id,
                    "name": version.subject_name_snapshot,
                    "code": version.subject_code_snapshot,
                },
                "compatible_course_ids": compatible_ids,
                "content_hash": version.content_hash,
                "pdf_sha256": version.pdf_sha256,
                "reviewed_at": version.reviewed_at.isoformat() if version.reviewed_at else None,
                "published_at": version.published_at.isoformat() if version.published_at else None,
            }
        )
    return result


def create_session(*, teacher, data: dict, idempotency_key: str) -> tuple[AIEvaluationDraftSession, bool]:
    _assert_no_sensitive_data(data)
    try:
        course_id = int(data.get("course_id"))
        version_id = int(data.get("curriculum_standard_version_id"))
    except (TypeError, ValueError) as exc:
        raise AIEvaluationDraftError(
            "课程或课程标准版本不正确。",
            errors={"course_id": ["必须选择课程和课程标准版本。"]},
        ) from exc
    course = (
        Course.objects.select_related("subject", "teacher")
        .prefetch_related("course_classes__class_group")
        .filter(pk=course_id, teacher=teacher, subject__school=teacher.school)
        .first()
    )
    if course is None:
        raise AIEvaluationDraftError(
            "课程不存在或无权访问。", code="course_not_found", status=404
        )
    version = (
        CurriculumStandardVersion.objects.select_related("source")
        .filter(pk=version_id)
        .first()
    )
    if version is None:
        raise AIEvaluationDraftError(
            "课程标准版本不存在。", code="curriculum_version_not_found", status=404
        )
    school_stage = _text(data.get("school_stage"), max_length=16)
    grade_or_stage = _text(data.get("grade_or_stage"), max_length=64)
    unit_title = _text(data.get("unit_title"), max_length=160)
    course_content = _text(data.get("course_content"), max_length=12000)
    evaluation_purpose = _text(data.get("evaluation_purpose"), max_length=40)
    errors = {}
    if len(grade_or_stage) < 1:
        errors["grade_or_stage"] = ["请填写适用年级或学段。"]
    if len(unit_title) < 2:
        errors["unit_title"] = ["单元或主题名称至少需要 2 个字符。"]
    if len(course_content) < 10:
        errors["course_content"] = ["课程内容至少需要 10 个字符。"]
    if evaluation_purpose not in ALLOWED_EVALUATION_PURPOSES:
        errors["evaluation_purpose"] = ["评价目的不在允许范围内。"]
    if errors:
        raise AIEvaluationDraftError("起草情境不完整。", errors=errors)
    _validate_course_and_version(
        teacher=teacher,
        course=course,
        version=version,
        requested_stage=school_stage,
        grade_or_stage=grade_or_stage,
    )
    retrieval_query = _text(
        data.get("retrieval_query")
        or f"核心素养 课程目标 课程内容 学业质量 {unit_title} {course.title}",
        max_length=1000,
    )
    request_payload = {
        "course_id": course.id,
        "curriculum_standard_version_id": version.id,
        "school_stage": school_stage,
        "grade_or_stage": grade_or_stage,
        "unit_title": unit_title,
        "course_content": course_content,
        "evaluation_purpose": evaluation_purpose,
        "retrieval_query": retrieval_query,
    }
    request_hash = ai_evaluation_content_hash(request_payload)
    normalized_key = _text(idempotency_key, max_length=128) or request_hash
    existing = AIEvaluationDraftSession.objects.filter(
        teacher=teacher, idempotency_key=normalized_key
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise AIEvaluationDraftError(
                "同一幂等键对应的起草情境不同。",
                code="idempotency_conflict",
                status=409,
            )
        return existing, False
    try:
        session = AIEvaluationDraftSession.objects.create(
            teacher=teacher,
            school=teacher.school,
            subject=course.subject,
            course=course,
            curriculum_version=version,
            curriculum_version_content_hash=version.content_hash,
            curriculum_pdf_sha256=version.pdf_sha256,
            school_stage=school_stage,
            grade_or_stage=grade_or_stage,
            unit_title=unit_title,
            course_content=course_content,
            evaluation_purpose=evaluation_purpose,
            retrieval_query=retrieval_query,
            idempotency_key=normalized_key,
            request_hash=request_hash,
        )
    except IntegrityError:
        session = AIEvaluationDraftSession.objects.get(
            teacher=teacher, idempotency_key=normalized_key
        )
        if session.request_hash != request_hash:
            raise AIEvaluationDraftError(
                "同一幂等键对应的起草情境不同。",
                code="idempotency_conflict",
                status=409,
            )
        return session, False
    return session, True


def _snapshot_from_node(
    node: CurriculumStandardNode,
    *,
    chunk: CurriculumRetrievalChunk | None = None,
) -> dict:
    text = chunk.text if chunk else node.content
    return {
        "id": node.id,
        "node_type": node.node_type,
        "node_type_label": NODE_LABELS.get(node.node_type, node.get_node_type_display()),
        "code": node.code,
        "title": node.title,
        "content": text[:2200],
        "source_page_start": chunk.source_page_start if chunk else node.source_page_start,
        "source_page_end": chunk.source_page_end if chunk else node.source_page_end,
        "source_paragraph": node.source_paragraph,
        "content_hash": node.content_hash,
        "curriculum_version_id": node.version_id,
        "citation": {
            "chunk_id": chunk.chunk_id if chunk else "",
            "source_kind": (
                chunk.source_kind if chunk else CurriculumRetrievalSourceKind.CONTENT_ITEM
            ),
            "source_locator": chunk.source_locator if chunk else f"node:{node.id}",
            "source_object_id": node.id,
            "source_content_hash": (
                chunk.source_content_hash if chunk else node.content_hash
            ),
            "source_page_hashes": chunk.source_page_hashes if chunk else [],
            "version_content_hash": node.version.content_hash,
            "pdf_sha256": node.version.pdf_sha256,
            "version_label": node.version.version_label,
            "official_title": node.version.official_title,
            "source_url": node.version.source_url,
        },
    }


@transaction.atomic
def retrieve_curriculum_references(*, session: AIEvaluationDraftSession, teacher) -> AIEvaluationDraftSession:
    locked = (
        AIEvaluationDraftSession.objects.select_for_update()
        .select_related("course__subject", "curriculum_version__source", "teacher")
        .get(pk=session.pk, teacher=teacher)
    )
    if locked.status == AIEvaluationDraftStatus.CANCELLED:
        raise AIEvaluationDraftError("已取消的会话不能继续检索。", status=409)
    if locked.retrieval_snapshot and locked.status != AIEvaluationDraftStatus.CREATED:
        return locked
    _validate_course_and_version(
        teacher=teacher,
        course=locked.course,
        version=locked.curriculum_version,
        requested_stage=locked.school_stage,
        grade_or_stage=locked.grade_or_stage,
    )
    nodes = list(
        CurriculumStandardNode.objects.filter(version=locked.curriculum_version)
        .select_related("version__source")
        .order_by("node_type", "sort_order", "id")
    )
    by_type: dict[str, list[CurriculumStandardNode]] = {
        node_type: [] for node_type in CurriculumNodeType.values
    }
    for node in nodes:
        by_type.setdefault(node.node_type, []).append(node)
    missing = [node_type for node_type in CurriculumNodeType.values if not by_type.get(node_type)]
    if missing:
        raise AIEvaluationDraftError(
            "课程标准结构化内容不完整，暂不能用于 AI 评价起草。",
            code="curriculum_structure_incomplete",
            errors={"curriculum_standard_version_id": [f"缺少：{'、'.join(NODE_LABELS[item] for item in missing)}"]},
        )
    index = CurriculumRetrievalIndex.objects.filter(version=locked.curriculum_version).first()
    use_chunks = bool(index and retrieval_index_is_current(locked.curriculum_version, index=index))
    chunks_by_node: dict[int, CurriculumRetrievalChunk] = {}
    if use_chunks:
        chunks = CurriculumRetrievalChunk.objects.filter(
            version=locked.curriculum_version,
            index=index,
            source_kind=CurriculumRetrievalSourceKind.CONTENT_ITEM,
            source_node__isnull=False,
        ).select_related("source_node", "version__source")
        query_terms = [
            term.lower()
            for term in re.split(r"\s+", locked.retrieval_query)
            if len(term.strip()) >= 2
        ]
        ranked = []
        for chunk in chunks:
            haystack = f"{chunk.source_node.title} {chunk.text}".lower()
            score = sum(haystack.count(term) for term in query_terms)
            ranked.append((score, -chunk.char_count, chunk))
        for _, _, chunk in sorted(ranked, key=lambda item: (-item[0], item[1], item[2].id)):
            chunks_by_node.setdefault(chunk.source_node_id, chunk)
    selected = []
    for node_type in CurriculumNodeType.values:
        type_nodes = by_type[node_type]
        ranked_nodes = sorted(
            type_nodes,
            key=lambda node: (
                0 if node.id in chunks_by_node else 1,
                node.sort_order,
                node.id,
            ),
        )
        for node in ranked_nodes[:3]:
            selected.append(_snapshot_from_node(node, chunk=chunks_by_node.get(node.id)))
    locked.retrieval_snapshot = selected
    locked.retrieval_snapshot_hash = ai_evaluation_content_hash(selected)
    locked.status = AIEvaluationDraftStatus.RETRIEVED
    locked.active_task_kind = AIEvaluationTaskKind.NONE
    locked.last_error_code = ""
    locked.last_error_message = ""
    locked.save(
        update_fields=[
            "retrieval_snapshot",
            "retrieval_snapshot_hash",
            "status",
            "active_task_kind",
            "last_error_code",
            "last_error_message",
            "updated_at",
        ]
    )
    return locked


def _provider_snapshot(teacher) -> tuple[str, str]:
    provider = TeacherAIProvider.objects.filter(teacher=teacher).order_by("id").first()
    if provider is None:
        return TeacherAIProvider.Provider.DEEPSEEK, "deepseek-v4-flash"
    return provider.provider, provider.model


def _citation_prompt(session: AIEvaluationDraftSession) -> str:
    rows = []
    for item in session.retrieval_snapshot:
        rows.append(
            {
                "node_id": item.get("id"),
                "node_type": item.get("node_type"),
                "code": item.get("code"),
                "title": item.get("title"),
                "content": item.get("content"),
                "pages": [item.get("source_page_start"), item.get("source_page_end")],
                "content_hash": item.get("content_hash"),
            }
        )
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def _mode_prompts(session: AIEvaluationDraftSession) -> tuple[str, str]:
    system_prompt = (
        "你是基础教育课程与评价设计助手。必须使用规范教育术语，仅依据给定且已完成人工复核并发布的课程标准原文形成建议。"
        "你只能生成教师可审阅的评价方式建议，不能评价或推断任何具体学生，不能输出姓名、学号、联系方式等身份信息。"
        "评价方式可选值仅为 test、operation、project、artifact、oral_defense、mixed。"
        "请返回 JSON 对象，键 suggested_modes 为数组；每项包含 mode、rationale、suitable_materials、cautions、recommended。"
    )
    user_prompt = (
        f"课程：{session.course.title}\n学段与年级：{session.school_stage} / {session.grade_or_stage}\n"
        f"单元或主题：{session.unit_title}\n评价目的：{ALLOWED_EVALUATION_PURPOSES[session.evaluation_purpose]}\n"
        f"课程内容：{session.course_content}\n"
        "请综合核心素养、课程目标、课程内容和学业质量，提出适切的评价方式组合。"
        "项目学习不应被强制改写为纸笔测试；学习起点诊断也应允许表现任务、简答或短项目。\n"
        f"课程标准引用快照：{_citation_prompt(session)}"
    )
    return system_prompt, user_prompt


def _draft_prompts(session: AIEvaluationDraftSession) -> tuple[str, str]:
    system_prompt = (
        "你是基础教育课程与评价设计助手。输出是供教师逐项复核的初稿，不是自动发布的评价结论。"
        "必须沿着“课程标准依据—学习目标—学习活动—评价任务—评价标准”的关系设计，"
        "并区分个人与小组评价材料。不得出现任何具体学生身份信息，不得根据缺失材料判定低水平。"
        "只返回一个 JSON 对象，必须同时包含 plan_draft 与 standard_draft。"
        "plan_draft 包含 title、content_version、target_students、learning_goal、learning_goals、evaluation_basis、"
        "learning_activities、learning_tasks、evaluation_tasks、content_scope、thinking_requirements、support_options、"
        "scoring_rules、follow_up_suggestion。每个 learning_goal 必须用 curriculum_node_ids 引用给定 node_id。"
        "evaluation_basis 至少一项，每项必须包含 code、goal_codes、description、source_types，并覆盖全部学习目标；"
        "learning_activities 每项必须包含 code、title、goal_codes、description；"
        "learning_tasks 每项必须包含 code、title、basis_codes、description。"
        "evaluation_tasks 每项包含 code、title、goal_codes、activity_codes、mode、component_modes、"
        "evidence_ownership、material_types、weight、description。material_types 只能使用 answer、artifact、operation、"
        "oral_defense、observation、score；项目式评价优先综合 artifact、operation、observation 和 oral_defense，不能退化为测试。"
        "standard_draft 包含 title、evaluation_target、criteria；每个指标必须关联 learning_goal_codes 与"
        "evaluation_task_codes，并包含 dimension、evaluation_sources、evidence_ownership、material_types、"
        "expected_performance、skip_condition、support_options、common_problems、level_descriptions(1至5)、"
        "scoring_examples 和 follow_up_suggestion。每个评价指标必须提供至少两个 scoring_examples，"
        "两个示例须对应不同表现水平，且每项都包含 level、title、example_description。"
        "每项评价指标名称必须唯一，并用可观察的学科表现命名；不能用相同的‘关键表现’名称概括不同学习目标。"
        "除非确有共同评价材料，评价指标不得笼统关联全部学习目标和全部评价任务。"
        "表现水平必须描述可观察表现，不能给学生贴固定标签。"
        "输出前必须逐项自查：目标均有评价依据，活动均对应目标，学习任务均对应评价依据，"
        "评价任务均对应目标和活动，评价指标均对应目标和评价任务，任务权重合计为100。"
    )
    user_prompt = (
        f"课程：{session.course.title}\n学段与年级：{session.school_stage} / {session.grade_or_stage}\n"
        f"单元或主题：{session.unit_title}\n评价目的：{ALLOWED_EVALUATION_PURPOSES[session.evaluation_purpose]}\n"
        f"教师确认的评价方式：{json.dumps(session.confirmed_modes, ensure_ascii=False)}\n"
        f"教师说明：{session.teacher_mode_note or '无补充说明'}\n课程内容：{session.course_content}\n"
        "请形成可执行的学习目标、学习活动、评价任务、评价依据、评分规则、评价指标、五级表现描述和后续教学建议。"
        "总权重为100；混合评价需在 component_modes 中列出组成方式。任何必填数组都不能省略或返回 null。\n"
        f"课程标准引用快照：{_citation_prompt(session)}"
    )
    return system_prompt, user_prompt


def _normalize_mode_suggestions(value: dict) -> list[dict]:
    rows = value.get("suggested_modes") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise AIEvaluationDraftError(
            "AI 未返回评价方式建议列表。", code="invalid_ai_mode_response"
        )
    result = []
    seen = set()
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        mode = _text(row.get("mode"), max_length=32)
        if mode not in EvaluationMode.values or mode in seen:
            continue
        rationale = _text(row.get("rationale"), max_length=1200)
        if not rationale:
            continue
        seen.add(mode)
        result.append(
            {
                "mode": mode,
                "label": MODE_LABELS[mode],
                "rationale": rationale,
                "suitable_materials": _string_list(
                    row.get("suitable_materials") or row.get("material_types"), max_items=12
                ),
                "cautions": _string_list(row.get("cautions") or row.get("risks"), max_items=10),
                "recommended": bool(row.get("recommended", True)),
            }
        )
    if not result:
        raise AIEvaluationDraftError(
            "AI 返回的评价方式均不在允许范围内。", code="invalid_ai_mode_response"
        )
    return result


def _normalize_object_rows(
    value: Any,
    *,
    fields: tuple[str, ...],
    max_items: int = 30,
) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for index, row in enumerate(value[:max_items], start=1):
        if not isinstance(row, dict):
            continue
        cleaned = {field: row.get(field) for field in fields}
        cleaned["code"] = _text(cleaned.get("code") or f"ITEM-{index:02d}", max_length=32)
        result.append(cleaned)
    return result


def _normalize_plan_draft(
    raw: Any,
    *,
    session: AIEvaluationDraftSession,
) -> dict:
    if not isinstance(raw, dict):
        raise AIEvaluationDraftError("AI 未返回评价方案初稿。", code="invalid_ai_draft_response")
    valid_node_ids = {
        int(item["id"])
        for item in session.retrieval_snapshot
        if str(item.get("id", "")).isdigit()
    }
    default_node_ids = sorted(valid_node_ids)
    raw_goals = raw.get("learning_goals")
    if (
        not isinstance(raw_goals, list)
        or not raw_goals
        or not any(isinstance(item, dict) for item in raw_goals)
    ):
        embedded_goals = raw.get("learning_goal")
        if isinstance(embedded_goals, list):
            raw_goals = embedded_goals
        elif isinstance(embedded_goals, str) and embedded_goals.strip().startswith("["):
            try:
                parsed_goals = ast.literal_eval(embedded_goals[:12000])
            except (SyntaxError, ValueError):
                parsed_goals = None
            if isinstance(parsed_goals, list):
                raw_goals = parsed_goals
    goals = _normalize_object_rows(
        raw_goals,
        fields=("code", "title", "description", "curriculum_node_ids"),
    )
    for row in goals:
        row["title"] = _text(row.get("title"), max_length=160)
        row["description"] = _text(row.get("description"), max_length=2000)
        row["curriculum_node_ids"] = (
            _int_list(row.get("curriculum_node_ids"), allowed=valid_node_ids)
            or default_node_ids
        )
    bases = _normalize_object_rows(
        raw.get("evaluation_basis"),
        fields=("code", "goal_codes", "description", "source_types"),
    )
    for row in bases:
        row["goal_codes"] = _string_list(row.get("goal_codes"), max_items=30, max_length=32)
        row["description"] = _text(row.get("description"), max_length=2000)
        row["source_types"] = _string_list(row.get("source_types"), max_items=15)
    activities = _normalize_object_rows(
        raw.get("learning_activities"),
        fields=("code", "title", "goal_codes", "description"),
    )
    for row in activities:
        row["title"] = _text(row.get("title"), max_length=160)
        row["goal_codes"] = _string_list(row.get("goal_codes"), max_items=30, max_length=32)
        row["description"] = _text(row.get("description"), max_length=2000)
    learning_tasks = _normalize_object_rows(
        raw.get("learning_tasks"),
        fields=("code", "title", "basis_codes", "description"),
    )
    for row in learning_tasks:
        row["title"] = _text(row.get("title"), max_length=160)
        row["basis_codes"] = _string_list(row.get("basis_codes"), max_items=30, max_length=32)
        row["description"] = _text(row.get("description"), max_length=2000)
    evaluation_tasks = _normalize_object_rows(
        raw.get("evaluation_tasks"),
        fields=(
            "code",
            "title",
            "goal_codes",
            "activity_codes",
            "mode",
            "component_modes",
            "evidence_ownership",
            "material_types",
            "weight",
            "description",
        ),
    )
    confirmed = list(session.confirmed_modes)
    for row in evaluation_tasks:
        row["title"] = _text(row.get("title"), max_length=160)
        row["goal_codes"] = _string_list(row.get("goal_codes"), max_items=30, max_length=32)
        row["activity_codes"] = _string_list(
            row.get("activity_codes"), max_items=30, max_length=32
        )
        mode = _text(row.get("mode"), max_length=32)
        row["mode"] = mode if mode in confirmed else (confirmed[0] if confirmed else EvaluationMode.MIXED)
        components = [
            item for item in _string_list(row.get("component_modes"), max_items=5) if item in ATOMIC_MODES
        ]
        row["component_modes"] = components if row["mode"] == EvaluationMode.MIXED else []
        ownership = _text(row.get("evidence_ownership"), max_length=16)
        row["evidence_ownership"] = (
            ownership if ownership in EvidenceOwnership.values else EvidenceOwnership.INDIVIDUAL
        )
        row["material_types"] = _material_list(row.get("material_types"), mode=row["mode"])
        try:
            row["weight"] = float(Decimal(str(row.get("weight"))))
        except (InvalidOperation, TypeError, ValueError):
            row["weight"] = 0
        row["description"] = _text(row.get("description"), max_length=2400)
    scoring = raw.get("scoring_rules") if isinstance(raw.get("scoring_rules"), dict) else {}
    overall_goal = _text(raw.get("learning_goal"), max_length=3000)
    if isinstance(raw.get("learning_goal"), list) or overall_goal.startswith("["):
        overall_goal = "；".join(
            row["description"] for row in goals if row.get("description")
        )[:3000]
    return {
        "course": session.course_id,
        "title": _text(raw.get("title") or f"{session.unit_title}评价方案", max_length=160),
        "content_version": _text(
            raw.get("content_version") or session.curriculum_version.version_label,
            max_length=64,
        ),
        "target_students": _text(raw.get("target_students") or session.grade_or_stage, max_length=300),
        "learning_goal": overall_goal,
        "learning_goals": goals,
        "evaluation_basis": bases,
        "learning_activities": activities,
        "learning_tasks": learning_tasks,
        "evaluation_tasks": evaluation_tasks,
        "assessment_modes": list(dict.fromkeys(row["mode"] for row in evaluation_tasks)),
        "content_scope": _string_list(raw.get("content_scope"), max_items=30),
        "thinking_requirements": _string_list(raw.get("thinking_requirements"), max_items=12),
        "support_options": _string_list(raw.get("support_options"), max_items=30),
        "scoring_rules": {
            "approach": _text(scoring.get("approach"), max_length=1200),
            "decision_rule": _text(scoring.get("decision_rule"), max_length=1200),
        },
        "follow_up_suggestion": _text(raw.get("follow_up_suggestion"), max_length=3000),
        "curriculum_node_ids": default_node_ids,
    }


def _normalize_standard_draft(raw: Any, *, plan: dict) -> dict:
    if not isinstance(raw, dict):
        raise AIEvaluationDraftError("AI 未返回评价标准初稿。", code="invalid_ai_draft_response")
    criteria_rows = _normalize_object_rows(
        raw.get("criteria"),
        fields=(
            "code",
            "dimension",
            "title",
            "evaluation_target",
            "evaluation_sources",
            "learning_goal_codes",
            "evaluation_task_codes",
            "evidence_ownership",
            "material_types",
            "expected_performance",
            "skip_condition",
            "support_options",
            "common_problems",
            "level_descriptions",
            "scoring_examples",
            "follow_up_suggestion",
            "sort_order",
        ),
    )
    result = []
    for index, row in enumerate(criteria_rows):
        dimension = _text(row.get("dimension"), max_length=32)
        ownership = _text(row.get("evidence_ownership"), max_length=16)
        levels = row.get("level_descriptions")
        if isinstance(levels, list):
            levels = {
                str(level): _level_description(value)
                for level, value in enumerate(levels[:5], 1)
            }
        elif isinstance(levels, dict):
            levels = {
                str(level): _level_description(
                    levels.get(str(level), levels.get(level))
                )
                for level in range(1, 6)
            }
        else:
            levels = {str(level): "" for level in range(1, 6)}
        examples = []
        if isinstance(row.get("scoring_examples"), list):
            for example in row["scoring_examples"][:10]:
                if not isinstance(example, dict):
                    continue
                try:
                    level = int(example.get("level"))
                except (TypeError, ValueError):
                    continue
                if 1 <= level <= 5:
                    examples.append(
                        {
                            "level": level,
                            "title": _text(example.get("title"), max_length=160),
                            "example_description": _text(
                                example.get("example_description"), max_length=1600
                            ),
                            "file_reference": "",
                        }
                    )
        result.append(
            {
                "code": row["code"],
                "dimension": (
                    dimension if dimension in EvaluationDimension.values else EvaluationDimension.TASK_QUALITY
                ),
                "title": _text(row.get("title"), max_length=160),
                "evaluation_target": _text(row.get("evaluation_target"), max_length=300),
                "evaluation_sources": _evaluation_source_list(
                    row.get("evaluation_sources") or _material_list(row.get("material_types"))
                ),
                "learning_goal_codes": _string_list(
                    row.get("learning_goal_codes"), max_items=30, max_length=32
                ),
                "evaluation_task_codes": _string_list(
                    row.get("evaluation_task_codes"), max_items=30, max_length=32
                ),
                "evidence_ownership": (
                    ownership if ownership in EvidenceOwnership.values else EvidenceOwnership.INDIVIDUAL
                ),
                "material_types": _material_list(row.get("material_types")),
                "expected_performance": _text(row.get("expected_performance"), max_length=2000),
                "skip_condition": _text(row.get("skip_condition"), max_length=1200),
                "support_options": _string_list(row.get("support_options"), max_items=20),
                "common_problems": _string_list(row.get("common_problems"), max_items=20),
                "level_descriptions": levels,
                "scoring_examples": examples,
                "follow_up_suggestion": _text(row.get("follow_up_suggestion"), max_length=2000),
                "sort_order": index,
            }
        )
    return {
        "title": _text(raw.get("title") or f"{plan['title']}评价标准", max_length=160),
        "evaluation_target": _text(raw.get("evaluation_target"), max_length=300),
        "criteria": result,
    }


def _draft_row_title(description: Any, fallback: str) -> str:
    value = _text(description, max_length=160)
    value = re.split(r"[，。；;]", value, maxsplit=1)[0].strip()
    return (value or fallback)[:80]


def _repair_ai_draft_structure(
    *,
    session: AIEvaluationDraftSession,
    plan: dict,
    standard: dict,
) -> list[str]:
    """Complete required links while preserving the raw model response for audit."""

    repairs: list[str] = []
    node_ids = sorted(
        int(item["id"])
        for item in session.retrieval_snapshot
        if str(item.get("id", "")).isdigit()
    )

    goals = plan.get("learning_goals") if isinstance(plan.get("learning_goals"), list) else []
    if not goals:
        description = _text(plan.get("learning_goal"), max_length=2000)
        if len(description) < 8:
            description = f"学生能够结合{session.unit_title}的任务要求完成学习成果，并说明方法与依据。"
        goals = [{
            "code": "G1",
            "title": _draft_row_title(description, "完成本次学习任务"),
            "description": description,
            "curriculum_node_ids": node_ids,
        }]
        plan["learning_goals"] = goals
        repairs.append("learning_goals_created")
    for index, goal in enumerate(goals, start=1):
        if not _text(goal.get("title")):
            goal["title"] = _draft_row_title(goal.get("description"), f"学习目标 {index}")
            repairs.append("learning_goal_title_completed")
        if len(_text(goal.get("description"))) < 8:
            goal["description"] = f"学生能够围绕“{goal['title']}”完成可观察的学习表现，并说明相应依据。"
            repairs.append("learning_goal_description_completed")
        # The publishing contract requires every goal to retain the full four-part
        # curriculum chain.  The teacher can narrow the wording during review.
        if set(_int_list(goal.get("curriculum_node_ids"))) != set(node_ids):
            goal["curriculum_node_ids"] = node_ids
            repairs.append("learning_goal_curriculum_links_completed")

    goal_codes = [str(row["code"]) for row in goals]
    if len(_text(plan.get("learning_goal"))) < 8 or _text(plan.get("learning_goal")).startswith("["):
        plan["learning_goal"] = "；".join(row["description"] for row in goals)[:3000]
        repairs.append("overall_learning_goal_completed")

    bases = plan.get("evaluation_basis") if isinstance(plan.get("evaluation_basis"), list) else []
    if not bases:
        bases = [{
            "code": f"B{index}",
            "goal_codes": [goal["code"]],
            "description": f"依据学生在学习活动与评价任务中形成的作品、操作记录和说明，判断“{goal['title']}”的具体表现。",
            "source_types": ["学生作品", "操作记录", "学生说明"],
        } for index, goal in enumerate(goals, start=1)]
        plan["evaluation_basis"] = bases
        repairs.append("evaluation_basis_created")
    for basis in bases:
        links = [code for code in _string_list(basis.get("goal_codes"), max_length=32) if code in goal_codes]
        basis["goal_codes"] = links or list(goal_codes)
        if len(_text(basis.get("description"))) < 8:
            basis["description"] = "依据学生作品、操作记录与个人说明，判断与学习目标对应的可观察表现。"
            repairs.append("evaluation_basis_description_completed")
        if not _string_list(basis.get("source_types")):
            basis["source_types"] = ["学生作品", "操作记录", "学生说明"]
            repairs.append("evaluation_basis_sources_completed")
    covered_goals = {code for row in bases for code in row["goal_codes"]}
    if set(goal_codes) - covered_goals:
        bases[0]["goal_codes"] = list(dict.fromkeys([*bases[0]["goal_codes"], *goal_codes]))
        repairs.append("evaluation_basis_links_completed")

    activities = plan.get("learning_activities") if isinstance(plan.get("learning_activities"), list) else []
    if not activities:
        activities = [{
            "code": "A1",
            "title": f"{session.unit_title}学习活动",
            "goal_codes": list(goal_codes),
            "description": f"学生围绕{session.unit_title}完成任务、交流方法并修改学习成果。",
        }]
        plan["learning_activities"] = activities
        repairs.append("learning_activities_created")
    for index, activity in enumerate(activities, start=1):
        links = [code for code in _string_list(activity.get("goal_codes"), max_length=32) if code in goal_codes]
        activity["goal_codes"] = links or list(goal_codes)
        if not _text(activity.get("title")):
            activity["title"] = f"学习活动 {index}"
        if len(_text(activity.get("description"))) < 8:
            activity["description"] = f"学生通过“{activity['title']}”完成相应学习目标，并留下可检查的学习材料。"
            repairs.append("learning_activity_description_completed")
    covered_goals = {code for row in activities for code in row["goal_codes"]}
    if set(goal_codes) - covered_goals:
        activities[0]["goal_codes"] = list(dict.fromkeys([*activities[0]["goal_codes"], *goal_codes]))
        repairs.append("learning_activity_links_completed")

    basis_codes = [str(row["code"]) for row in bases]
    learning_tasks = plan.get("learning_tasks") if isinstance(plan.get("learning_tasks"), list) else []
    if not learning_tasks:
        learning_tasks = [{
            "code": "T1",
            "title": "完成学习任务并提交材料",
            "basis_codes": list(basis_codes),
            "description": "学生完成本次学习任务，提交作品、操作记录或个人说明作为评价材料。",
        }]
        plan["learning_tasks"] = learning_tasks
        repairs.append("learning_tasks_created")
    for index, task in enumerate(learning_tasks, start=1):
        links = [code for code in _string_list(task.get("basis_codes"), max_length=32) if code in basis_codes]
        task["basis_codes"] = links or list(basis_codes)
        if not _text(task.get("title")):
            task["title"] = f"学习任务 {index}"
        if len(_text(task.get("description"))) < 8:
            task["description"] = f"完成“{task['title']}”并提交可用于判断学习表现的材料。"
            repairs.append("learning_task_description_completed")
    covered_basis = {code for row in learning_tasks for code in row["basis_codes"]}
    if set(basis_codes) - covered_basis:
        learning_tasks[0]["basis_codes"] = list(dict.fromkeys([*learning_tasks[0]["basis_codes"], *basis_codes]))
        repairs.append("learning_task_links_completed")

    evaluation_tasks = plan.get("evaluation_tasks") if isinstance(plan.get("evaluation_tasks"), list) else []
    if not evaluation_tasks:
        mode = session.confirmed_modes[0] if session.confirmed_modes else EvaluationMode.PROJECT
        evaluation_tasks = [{
            "code": "E1",
            "title": "完成本次评价任务",
            "goal_codes": list(goal_codes),
            "activity_codes": [str(row["code"]) for row in activities],
            "mode": mode,
            "component_modes": [],
            "evidence_ownership": EvidenceOwnership.INDIVIDUAL,
            "material_types": _material_list([], mode=mode),
            "weight": 100.0,
            "description": "学生完成与本课学习目标对应的任务，提交作品、操作记录或说明。",
        }]
        plan["evaluation_tasks"] = evaluation_tasks
        repairs.append("evaluation_tasks_created")
    activity_codes = [str(row["code"]) for row in activities]
    activities_by_code = {str(row["code"]): row for row in activities}
    confirmed_atomic = [mode for mode in session.confirmed_modes if mode in ATOMIC_MODES]
    for index, task in enumerate(evaluation_tasks, start=1):
        task["goal_codes"] = [code for code in _string_list(task.get("goal_codes"), max_length=32) if code in goal_codes] or list(goal_codes)
        linked_goal_codes = set(task["goal_codes"])
        task["activity_codes"] = [
            code
            for code in _string_list(task.get("activity_codes"), max_length=32)
            if code in activity_codes
            and linked_goal_codes.intersection(activities_by_code[code]["goal_codes"])
        ]
        if not task["activity_codes"]:
            task["activity_codes"] = [
                code
                for code in activity_codes
                if linked_goal_codes.intersection(activities_by_code[code]["goal_codes"])
            ] or list(activity_codes)
        if not _text(task.get("title")):
            task["title"] = f"评价任务 {index}"
        if len(_text(task.get("description"))) < 8:
            task["description"] = f"完成“{task['title']}”，并提交可检查的个人或小组评价材料。"
            repairs.append("evaluation_task_description_completed")
        mode = task.get("mode")
        materials = _material_list(task.get("material_types"), mode=mode)
        if mode == EvaluationMode.MIXED:
            components = [item for item in _string_list(task.get("component_modes"), max_items=5) if item in ATOMIC_MODES]
            for candidate in [*confirmed_atomic, EvaluationMode.OPERATION, EvaluationMode.ARTIFACT]:
                if candidate not in components:
                    components.append(candidate)
                if len(components) >= 2:
                    break
            task["component_modes"] = components[:5]
            for component in task["component_modes"]:
                if not set(materials).intersection(MODE_MATERIAL_TYPES[component]):
                    materials.append(sorted(MODE_MATERIAL_TYPES[component])[0])
                    repairs.append("evaluation_task_materials_completed")
        else:
            task["component_modes"] = []
            if mode not in MODE_MATERIAL_TYPES or not set(materials).intersection(MODE_MATERIAL_TYPES[mode]):
                alternative = next(
                    (candidate for candidate in confirmed_atomic if set(materials).intersection(MODE_MATERIAL_TYPES[candidate])),
                    None,
                )
                if alternative:
                    task["mode"] = alternative
                    repairs.append("evaluation_task_mode_aligned")
                else:
                    active_mode = mode if mode in MODE_MATERIAL_TYPES else (confirmed_atomic[0] if confirmed_atomic else EvaluationMode.PROJECT)
                    task["mode"] = active_mode
                    materials.append(sorted(MODE_MATERIAL_TYPES[active_mode])[0])
                    repairs.append("evaluation_task_materials_completed")
        task["material_types"] = list(dict.fromkeys(materials))
        if task.get("evidence_ownership") not in EvidenceOwnership.values:
            task["evidence_ownership"] = EvidenceOwnership.INDIVIDUAL
            repairs.append("evaluation_task_ownership_completed")
    covered_goals = {code for row in evaluation_tasks for code in row["goal_codes"]}
    covered_activities = {code for row in evaluation_tasks for code in row["activity_codes"]}
    missing_goal_codes = [code for code in goal_codes if code not in covered_goals]
    missing_activity_codes = [code for code in activity_codes if code not in covered_activities]
    evaluation_tasks[0]["goal_codes"] = list(
        dict.fromkeys([*evaluation_tasks[0]["goal_codes"], *missing_goal_codes])
    )
    evaluation_tasks[0]["activity_codes"] = list(
        dict.fromkeys([*evaluation_tasks[0]["activity_codes"], *missing_activity_codes])
    )
    for activity_code in missing_activity_codes:
        evaluation_tasks[0]["goal_codes"] = list(
            dict.fromkeys(
                [
                    *evaluation_tasks[0]["goal_codes"],
                    *activities_by_code[activity_code]["goal_codes"],
                ]
            )
        )
    for goal_code in missing_goal_codes:
        matching_activity = next(
            (
                code
                for code in activity_codes
                if goal_code in activities_by_code[code]["goal_codes"]
            ),
            None,
        )
        if matching_activity:
            evaluation_tasks[0]["activity_codes"] = list(
                dict.fromkeys(
                    [*evaluation_tasks[0]["activity_codes"], matching_activity]
                )
            )
    positive_weights = [max(float(row.get("weight") or 0), 0) for row in evaluation_tasks]
    total_weight = sum(positive_weights)
    if total_weight <= 0 or abs(total_weight - 100.0) >= 0.01:
        unit = round(100 / len(evaluation_tasks), 4)
        for index, task in enumerate(evaluation_tasks):
            task["weight"] = unit if index < len(evaluation_tasks) - 1 else round(100 - unit * (len(evaluation_tasks) - 1), 4)
        repairs.append("evaluation_task_weights_rebalanced")
    plan["assessment_modes"] = list(dict.fromkeys(row["mode"] for row in evaluation_tasks))

    if not _string_list(plan.get("content_scope")):
        plan["content_scope"] = [session.unit_title, _text(session.course_content, max_length=500)]
        repairs.append("content_scope_completed")
    thinking = [item for item in _string_list(plan.get("thinking_requirements")) if item in THINKING_REQUIREMENT_VALUES]
    if not thinking:
        thinking = ["understand", "apply"]
        repairs.append("thinking_requirements_completed")
    plan["thinking_requirements"] = thinking
    scoring = plan.get("scoring_rules") if isinstance(plan.get("scoring_rules"), dict) else {}
    if len(_text(scoring.get("approach"))) < 4:
        scoring["approach"] = "按评价指标分别判断并形成综合反馈"
        repairs.append("scoring_approach_completed")
    if len(_text(scoring.get("decision_rule"))) < 8:
        scoring["decision_rule"] = "依据学生实际形成的作品、操作记录和说明对照表现水平判断；材料不足、设备故障或未获得表现机会时暂不评价。"
        repairs.append("scoring_decision_rule_completed")
    plan["scoring_rules"] = scoring
    if len(_text(plan.get("follow_up_suggestion"))) < 8:
        plan["follow_up_suggestion"] = "根据学生具体表现提供针对性反馈，并安排补充说明、修改作品或迁移实践的学习机会。"
        repairs.append("follow_up_suggestion_completed")

    tasks_by_code = {str(row["code"]): row for row in evaluation_tasks}
    criteria = standard.get("criteria") if isinstance(standard.get("criteria"), list) else []
    repaired_criteria = []
    used_codes = set()
    for index, criterion in enumerate(criteria, start=1):
        code = str(criterion.get("code") or f"C{index}")
        if code in used_codes:
            code = f"C{index}"
        used_codes.add(code)
        criterion["code"] = code
        linked_codes = [code for code in _string_list(criterion.get("evaluation_task_codes"), max_length=32) if code in tasks_by_code]
        if not linked_codes:
            linked_codes = [str(evaluation_tasks[(index - 1) % len(evaluation_tasks)]["code"])]
        ownership = criterion.get("evidence_ownership")
        if ownership not in EvidenceOwnership.values:
            ownership = tasks_by_code[linked_codes[0]]["evidence_ownership"]
        compatible_codes = [task_code for task_code in linked_codes if tasks_by_code[task_code]["evidence_ownership"] in {ownership, EvidenceOwnership.BOTH}]
        if not compatible_codes:
            compatible_codes = [linked_codes[0]]
            task_ownership = tasks_by_code[linked_codes[0]]["evidence_ownership"]
            ownership = EvidenceOwnership.INDIVIDUAL if task_ownership == EvidenceOwnership.BOTH else task_ownership
        criterion["evaluation_task_codes"] = compatible_codes
        criterion["evidence_ownership"] = ownership
        linked_goals = list(dict.fromkeys(code for task_code in compatible_codes for code in tasks_by_code[task_code]["goal_codes"]))
        criterion["learning_goal_codes"] = linked_goals
        materials = _material_list(criterion.get("material_types"))
        for task_code in compatible_codes:
            task_materials = tasks_by_code[task_code]["material_types"]
            if not set(materials).intersection(task_materials):
                materials.append(task_materials[0])
        criterion["material_types"] = list(dict.fromkeys(materials))
        criterion["evaluation_sources"] = _evaluation_source_list(
            criterion.get("evaluation_sources") or criterion["material_types"]
        )
        if not _text(criterion.get("title")):
            criterion["title"] = f"{tasks_by_code[compatible_codes[0]]['title']}的关键表现"
        if len(_text(criterion.get("evaluation_target"))) < 4:
            criterion["evaluation_target"] = tasks_by_code[compatible_codes[0]]["title"]
        if len(_text(criterion.get("expected_performance"))) < 8:
            criterion["expected_performance"] = next(
                (goal["description"] for goal in goals if goal["code"] in linked_goals),
                "学生能够完成任务并以作品、操作记录或说明展示具体学习表现。",
            )
        if len(_text(criterion.get("skip_condition"))) < 8:
            criterion["skip_condition"] = "未提交可辨认材料，或因设备故障、缺席等原因未获得完成任务机会时暂不评价。"
        criterion["common_problems"] = _string_list(criterion.get("common_problems")) or ["材料只呈现结果，尚不足以说明方法与依据。"]
        levels = criterion.get("level_descriptions") if isinstance(criterion.get("level_descriptions"), dict) else {}
        expected = criterion["expected_performance"]
        fallbacks = {
            "1": f"尚未形成与“{criterion['title']}”对应的可辨认表现，需要更多学习支持。",
            "2": f"在较多帮助下能完成部分有关“{criterion['title']}”的任务，但材料或说明尚不完整。",
            "3": f"能够独立完成与“{criterion['title']}”对应的基本任务，可观察到：{expected}",
            "4": f"能够较为准确、完整地展示“{criterion['title']}”，并能结合任务要求说明方法与依据。",
            "5": f"能够综合情境与证据优化“{criterion['title']}”的表现，并能解释权衡、迁移与改进。",
        }
        criterion["level_descriptions"] = {
            level: _level_description(levels.get(level)) or fallback
            for level, fallback in fallbacks.items()
        }
        examples = []
        for example in criterion.get("scoring_examples", []):
            if not isinstance(example, dict):
                continue
            try:
                example_level = int(example.get("level") or 0)
            except (TypeError, ValueError):
                continue
            if 1 <= example_level <= 5 and _text(example.get("title")) and _text(example.get("example_description")):
                examples.append(example)
        if len({int(item["level"]) for item in examples}) < 2:
            examples = [{
                "level": level,
                "title": f"{level} 星表现示例",
                "example_description": f"可观察到：{criterion['level_descriptions'][str(level)]}",
                "file_reference": "",
            } for level in (2, 4)]
            repairs.append("scoring_examples_completed")
        criterion["scoring_examples"] = examples
        if len(_text(criterion.get("follow_up_suggestion"))) < 8:
            criterion["follow_up_suggestion"] = "依据该指标的具体表现提供反馈，并安排补充说明、修改作品或迁移应用的学习机会。"
        repaired_criteria.append(criterion)

    def add_criterion_for_task(task: dict, ownership: str) -> None:
        number = len(repaired_criteria) + 1
        title = f"{task['title']}的关键表现"
        expected = next(
            (goal["description"] for goal in goals if goal["code"] in task["goal_codes"]),
            "学生能够完成任务并提交可检查的学习材料。",
        )
        repaired_criteria.append({
            "code": f"C{number}",
            "dimension": EvaluationDimension.TASK_QUALITY,
            "title": title,
            "evaluation_target": task["title"],
            "evaluation_sources": _evaluation_source_list(task["material_types"]),
            "learning_goal_codes": list(task["goal_codes"]),
            "evaluation_task_codes": [task["code"]],
            "evidence_ownership": ownership,
            "material_types": list(task["material_types"]),
            "expected_performance": expected,
            "skip_condition": "未提交可辨认材料，或因设备故障、缺席等原因未获得完成任务机会时暂不评价。",
            "support_options": [],
            "common_problems": ["材料只呈现结果，尚不足以说明方法与依据。"],
            "level_descriptions": {
                "1": f"尚未形成与“{title}”对应的可辨认表现，需要更多学习支持。",
                "2": f"在较多帮助下能完成部分有关“{title}”的任务，但材料或说明尚不完整。",
                "3": f"能够独立完成与“{title}”对应的基本任务，可观察到：{expected}",
                "4": f"能够较为准确、完整地展示“{title}”，并能结合任务要求说明方法与依据。",
                "5": f"能够综合情境与证据优化“{title}”的表现，并能解释权衡、迁移与改进。",
            },
            "scoring_examples": [
                {"level": 2, "title": "2 星表现示例", "example_description": "在较多帮助下完成部分任务，材料或说明仍不完整。", "file_reference": ""},
                {"level": 4, "title": "4 星表现示例", "example_description": "独立完成任务，材料准确完整，并能结合任务要求说明方法与依据。", "file_reference": ""},
            ],
            "follow_up_suggestion": "依据该指标的具体表现提供反馈，并安排补充说明、修改作品或迁移应用的学习机会。",
            "sort_order": number - 1,
        })

    coverage = {
        str(task["code"]): {
            criterion["evidence_ownership"]
            for criterion in repaired_criteria
            if str(task["code"]) in criterion["evaluation_task_codes"]
        }
        for task in evaluation_tasks
    }
    for task in evaluation_tasks:
        required_ownerships = (
            {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
            if task["evidence_ownership"] == EvidenceOwnership.BOTH
            else {task["evidence_ownership"]}
        )
        for ownership in required_ownerships - coverage[str(task["code"])]:
            add_criterion_for_task(task, ownership)
            repairs.append("evaluation_criterion_created")
    standard["criteria"] = repaired_criteria
    if not _text(standard.get("title")):
        standard["title"] = f"{plan['title']}评价标准"
    if len(_text(standard.get("evaluation_target"))) < 4:
        standard["evaluation_target"] = "学生在本次学习任务中形成的作品、操作记录、个人说明与可观察表现"
        repairs.append("standard_evaluation_target_completed")
    return list(dict.fromkeys(repairs))


def _check(code: str, label: str, passed: bool, message: str, *, warning: bool = False) -> dict:
    return {
        "code": code,
        "label": label,
        "status": "passed" if passed else ("warning" if warning else "blocked"),
        "message": message,
    }


def run_automatic_checks(
    *,
    session: AIEvaluationDraftSession,
    plan: dict,
    standard: dict,
) -> dict:
    reference_types = {item.get("node_type") for item in session.retrieval_snapshot}
    complete_reference = set(CurriculumNodeType.values).issubset(reference_types)
    goal_codes = {str(row.get("code")) for row in plan.get("learning_goals", []) if row.get("code")}
    bases = plan.get("evaluation_basis", []) if isinstance(plan.get("evaluation_basis"), list) else []
    basis_codes = {str(row.get("code")) for row in bases if isinstance(row, dict) and row.get("code")}
    activities = (
        plan.get("learning_activities", [])
        if isinstance(plan.get("learning_activities"), list)
        else []
    )
    activity_codes = {
        str(row.get("code")) for row in activities if isinstance(row, dict) and row.get("code")
    }
    learning_tasks = (
        plan.get("learning_tasks", []) if isinstance(plan.get("learning_tasks"), list) else []
    )
    task_codes = {str(row.get("code")) for row in plan.get("evaluation_tasks", []) if row.get("code")}
    valid_node_ids = {int(item["id"]) for item in session.retrieval_snapshot if str(item.get("id", "")).isdigit()}
    goal_alignment = bool(goal_codes) and all(
        set(_int_list(row.get("curriculum_node_ids"))).issubset(valid_node_ids)
        and bool(_int_list(row.get("curriculum_node_ids")))
        for row in plan.get("learning_goals", [])
    )
    basis_goal_links = bool(bases) and all(
        bool(_string_list(row.get("goal_codes"), max_length=32))
        and set(_string_list(row.get("goal_codes"), max_length=32)).issubset(goal_codes)
        for row in bases
    ) and goal_codes.issubset(
        {
            code
            for row in bases
            for code in _string_list(row.get("goal_codes"), max_length=32)
        }
    )
    activity_goal_links = bool(activities) and all(
        bool(_string_list(row.get("goal_codes"), max_length=32))
        and set(_string_list(row.get("goal_codes"), max_length=32)).issubset(goal_codes)
        for row in activities
    ) and goal_codes.issubset(
        {
            code
            for row in activities
            for code in _string_list(row.get("goal_codes"), max_length=32)
        }
    )
    learning_task_basis_links = bool(learning_tasks) and all(
        bool(_string_list(row.get("basis_codes"), max_length=32))
        and set(_string_list(row.get("basis_codes"), max_length=32)).issubset(basis_codes)
        for row in learning_tasks
    ) and basis_codes.issubset(
        {
            code
            for row in learning_tasks
            for code in _string_list(row.get("basis_codes"), max_length=32)
        }
    )
    tasks = plan.get("evaluation_tasks", [])
    activities_by_code = {
        str(row.get("code")): row for row in activities if isinstance(row, dict) and row.get("code")
    }
    task_links = bool(tasks)
    for row in tasks:
        linked_goals = set(_string_list(row.get("goal_codes"), max_length=32))
        linked_activities = set(_string_list(row.get("activity_codes"), max_length=32))
        if (
            not linked_goals
            or not linked_activities
            or not linked_goals.issubset(goal_codes)
            or not linked_activities.issubset(activity_codes)
        ):
            task_links = False
            break
        activity_goal_sets = [
            set(_string_list(activities_by_code[code].get("goal_codes"), max_length=32))
            for code in linked_activities
        ]
        if any(not (linked_goals & values) for values in activity_goal_sets):
            task_links = False
            break
        if not linked_goals.issubset(set().union(*activity_goal_sets)):
            task_links = False
            break
    covered_task_goals = {
        code for row in tasks for code in _string_list(row.get("goal_codes"), max_length=32)
    }
    covered_activities = {
        code for row in tasks for code in _string_list(row.get("activity_codes"), max_length=32)
    }
    task_links = task_links and goal_codes.issubset(covered_task_goals) and activity_codes.issubset(
        covered_activities
    )
    mode_alignment = bool(tasks) and all(row.get("mode") in session.confirmed_modes for row in tasks)
    evidence_complete = bool(tasks)
    for row in tasks:
        mode = row.get("mode")
        component_modes = _string_list(row.get("component_modes"), max_items=5, max_length=32)
        materials = set(_string_list(row.get("material_types"), max_length=64))
        required_modes = component_modes if mode == EvaluationMode.MIXED else [mode]
        if (
            row.get("evidence_ownership") not in EvidenceOwnership.values
            or not materials
            or not materials.issubset(MATERIAL_TYPE_VALUES)
            or (mode == EvaluationMode.MIXED and (len(component_modes) < 2 or len(set(component_modes)) != len(component_modes)))
            or (mode != EvaluationMode.MIXED and bool(component_modes))
            or any(required not in MODE_MATERIAL_TYPES for required in required_modes)
            or any(not (materials & MODE_MATERIAL_TYPES[required]) for required in required_modes if required in MODE_MATERIAL_TYPES)
        ):
            evidence_complete = False
            break
    weight_total = round(sum(float(row.get("weight") or 0) for row in tasks), 4)
    weight_ok = abs(weight_total - 100.0) < 0.01
    criteria = standard.get("criteria", [])
    covered_goals = {
        code for row in criteria for code in _string_list(row.get("learning_goal_codes"), max_length=32)
    }
    covered_tasks = {
        code for row in criteria for code in _string_list(row.get("evaluation_task_codes"), max_length=32)
    }
    plan_tasks_by_code = {
        str(row.get("code")): row for row in tasks if isinstance(row, dict) and row.get("code")
    }
    criterion_mapping_valid = bool(criteria)
    ownership_coverage = {code: set() for code in task_codes}
    for criterion in criteria:
        criterion_goals = set(_string_list(criterion.get("learning_goal_codes"), max_length=32))
        criterion_tasks = set(_string_list(criterion.get("evaluation_task_codes"), max_length=32))
        criterion_materials = set(_string_list(criterion.get("material_types"), max_length=64))
        ownership = criterion.get("evidence_ownership")
        if (
            not criterion_goals
            or not criterion_tasks
            or not criterion_goals.issubset(goal_codes)
            or not criterion_tasks.issubset(task_codes)
            or not criterion_materials
            or not criterion_materials.issubset(MATERIAL_TYPE_VALUES)
            or ownership not in EvidenceOwnership.values
        ):
            criterion_mapping_valid = False
            break
        for task_code in criterion_tasks:
            task = plan_tasks_by_code[task_code]
            task_goals = set(_string_list(task.get("goal_codes"), max_length=32))
            task_materials = set(_string_list(task.get("material_types"), max_length=64))
            task_ownership = task.get("evidence_ownership")
            if (
                not (criterion_goals & task_goals)
                or not criterion_goals.issubset(
                    {
                        code
                        for linked_code in criterion_tasks
                        for code in _string_list(
                            plan_tasks_by_code[linked_code].get("goal_codes"), max_length=32
                        )
                    }
                )
                or not (criterion_materials & task_materials)
                or (task_ownership != EvidenceOwnership.BOTH and ownership != task_ownership)
            ):
                criterion_mapping_valid = False
                break
            ownership_coverage[task_code].update(
                {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
                if ownership == EvidenceOwnership.BOTH
                else {ownership}
            )
        if not criterion_mapping_valid:
            break
    both_coverage_valid = all(
        plan_tasks_by_code[code].get("evidence_ownership") != EvidenceOwnership.BOTH
        or ownership_coverage[code] == {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
        for code in task_codes
    )
    standard_coverage = (
        bool(criteria)
        and goal_codes.issubset(covered_goals)
        and task_codes.issubset(covered_tasks)
        and criterion_mapping_valid
        and both_coverage_valid
    )
    levels_complete = bool(criteria) and all(
        isinstance(row.get("level_descriptions"), dict)
        and all(_text(row["level_descriptions"].get(str(level))) for level in range(1, 6))
        for row in criteria
    )
    examples_complete = bool(criteria) and all(
        isinstance(row.get("scoring_examples"), list)
        and len(row["scoring_examples"]) >= 2
        and len(
            {
                int(example.get("level"))
                for example in row["scoring_examples"]
                if isinstance(example, dict)
                and str(example.get("level", "")).isdigit()
                and 1 <= int(example.get("level")) <= 5
                and _text(example.get("title"))
                and _text(example.get("example_description"))
            }
        )
        >= 2
        for row in criteria
    )
    selected_version_can_bind = (
        session.curriculum_version.status == CurriculumVersionStatus.PUBLISHED
        and session.curriculum_version.source.current_version_id == session.curriculum_version_id
    )
    checks = [
        _check(
            "curriculum_chain",
            "课程标准依据完整性",
            complete_reference,
            "已覆盖核心素养、课程目标、课程内容和学业质量。"
            if complete_reference
            else "课程标准依据未覆盖四类结构。",
        ),
        _check(
            "goal_alignment",
            "学习目标与课标依据对应",
            goal_alignment,
            "学习目标均可追溯到本次课标引用。" if goal_alignment else "部分学习目标缺少有效课标引用。",
        ),
        _check(
            "basis_goal_alignment",
            "评价依据与学习目标对应",
            basis_goal_links,
            "评价依据均合法关联学习目标且覆盖完整。"
            if basis_goal_links
            else "评价依据存在未知、缺失或未覆盖的学习目标。",
        ),
        _check(
            "activity_goal_alignment",
            "学习活动与学习目标对应",
            activity_goal_links,
            "学习活动均合法关联学习目标且覆盖完整。"
            if activity_goal_links
            else "学习活动存在未知、缺失或未覆盖的学习目标。",
        ),
        _check(
            "learning_task_basis_alignment",
            "学习任务与评价依据对应",
            learning_task_basis_links,
            "学习任务均合法关联评价依据且覆盖完整。"
            if learning_task_basis_links
            else "学习任务存在未知、缺失或未覆盖的评价依据。",
        ),
        _check(
            "task_goal_alignment",
            "评价任务与学习目标对应",
            task_links,
            "评价任务均关联学习目标。" if task_links else "部分评价任务未关联学习目标。",
        ),
        _check(
            "confirmed_modes",
            "评价方式经教师确认",
            mode_alignment,
            "评价任务均使用教师确认的评价方式。" if mode_alignment else "评价任务包含未经教师确认的方式。",
        ),
        _check(
            "evidence_definition",
            "评价材料与归属明确",
            evidence_complete,
            "评价任务均明确材料类型及个人/小组归属。"
            if evidence_complete
            else "部分评价任务未明确材料类型或归属。",
        ),
        _check(
            "weight_total",
            "评价任务权重",
            weight_ok,
            f"当前权重合计为 {weight_total:g}。" + ("" if weight_ok else "教师保存前应调整为 100。"),
        ),
        _check(
            "standard_coverage",
            "评价指标覆盖学习目标与评价任务",
            standard_coverage,
            "评价指标已覆盖全部学习目标和评价任务。"
            if standard_coverage
            else "评价指标尚未覆盖全部学习目标或评价任务。",
        ),
        _check(
            "performance_levels",
            "表现水平描述完整",
            levels_complete,
            "每项评价指标均包含五级可观察表现描述。"
            if levels_complete
                else "部分评价指标缺少完整的五级表现描述。",
        ),
        _check(
            "scoring_examples",
            "评分示例完整性",
            examples_complete,
            "每项评价指标均至少包含两个评分示例，并覆盖至少两个表现水平。"
            if examples_complete
            else "部分评价指标缺少评分示例，或示例未覆盖至少两个表现水平。",
        ),
        _check(
            "curriculum_binding",
            "课程标准引用可写入方案",
            selected_version_can_bind,
            "当前已发布课标节点可随方案草稿保存。"
            if selected_version_can_bind
            else "该版本已复核但尚未作为当前版本发布；初稿可保存，正式发布方案前需改用当前已发布课标版本。",
            warning=True,
        ),
        _check("data_minimization", "数据最小化", True, "未使用学生身份信息或个体学习数据。"),
    ]
    return {
        "checks": checks,
        "blocked": any(item["status"] == "blocked" for item in checks),
        "checked_at": timezone.now().isoformat(),
    }


def _call_ai(*, session: AIEvaluationDraftSession, system_prompt: str, user_prompt: str, max_tokens: int):
    from api.services import _call_teacher_chat_json

    response = _call_teacher_chat_json(
        SimpleNamespace(user=session.teacher),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        include_raw_response=True,
    )
    if isinstance(response, tuple) and len(response) == 2:
        parsed, raw_text = response
    else:
        parsed = response
        raw_text = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    _assert_no_sensitive_data(raw_text, field="ai_response")
    _assert_no_sensitive_data(parsed, field="ai_response")
    return parsed, raw_text


def _next_attempt(session: AIEvaluationDraftSession, stage: str) -> int:
    value = session.generation_records.filter(stage=stage).aggregate(value=Max("attempt_no"))["value"]
    return int(value or 0) + 1


def _create_generation_record(
    *,
    session: AIEvaluationDraftSession,
    stage: str,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    raw_response_text: str = "",
    raw_result: dict | None = None,
    parsed_result: dict | None = None,
    validation_result: dict | None = None,
    generation_config: dict | None = None,
    status: str,
    error_code: str = "",
    error_message: str = "",
) -> AIEvaluationGenerationRecord:
    prompt_hash = ai_evaluation_content_hash(
        {"system_prompt": system_prompt, "user_prompt": user_prompt}
    )
    result = parsed_result or {}
    return AIEvaluationGenerationRecord.objects.create(
        session=session,
        stage=stage,
        attempt_no=_next_attempt(session, stage),
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        prompt_hash=prompt_hash,
        generation_config=generation_config or {},
        retrieval_snapshot=session.retrieval_snapshot,
        raw_response_text=raw_response_text,
        raw_result=raw_result or {},
        parsed_result=result,
        validation_result=validation_result or {},
        result_hash=(ai_evaluation_content_hash(result) if status == AIEvaluationGenerationStatus.SUCCEEDED else ""),
        status=status,
        error_code=error_code,
        error_message=error_message,
        celery_task_id=session.celery_task_id,
    )


def execute_generation_stage(*, session_id: int, task_kind: str, task_id: str = "") -> dict:
    if task_kind not in AIEvaluationTaskKind.values or task_kind == AIEvaluationTaskKind.NONE:
        return {"status": "ignored", "reason": "unknown_task_kind"}
    queued_status = (
        AIEvaluationDraftStatus.MODE_SUGGESTION_QUEUED
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else AIEvaluationDraftStatus.DRAFT_QUEUED
    )
    running_status = (
        AIEvaluationDraftStatus.MODE_SUGGESTION_RUNNING
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else AIEvaluationDraftStatus.DRAFT_RUNNING
    )
    with transaction.atomic():
        session = (
            AIEvaluationDraftSession.objects.select_for_update()
            .select_related("teacher", "course", "curriculum_version__source")
            .filter(pk=session_id)
            .first()
        )
        if not session:
            return {"status": "ignored", "reason": "missing_session"}
        if session.status == AIEvaluationDraftStatus.CANCELLED:
            return {"status": "ignored", "reason": "cancelled"}
        if session.status != queued_status or session.active_task_kind != task_kind:
            return {"status": "ignored", "reason": "not_claimable"}
        if task_id and session.celery_task_id and task_id != session.celery_task_id:
            return {"status": "ignored", "reason": "stale_task"}
        session.status = running_status
        session.save(update_fields=["status", "updated_at"])
    stage = (
        AIEvaluationGenerationStage.MODE_SUGGESTION
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else AIEvaluationGenerationStage.EVALUATION_DRAFT
    )
    provider, model = _provider_snapshot(session.teacher)
    system_prompt, user_prompt = (
        _mode_prompts(session)
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else _draft_prompts(session)
    )
    raw_text = ""
    parsed: dict = {}
    max_tokens = 2400 if task_kind == AIEvaluationTaskKind.SUGGEST_MODES else 7600
    generation_config = {
        "temperature": 0.4,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "timeout_seconds": 45 if max_tokens <= 4000 else 90,
        "prompt_version": "ai_evaluation_drafting_v2",
    }
    try:
        parsed, raw_text = _call_ai(
            session=session,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES:
            normalized = {"suggested_modes": _normalize_mode_suggestions(parsed)}
            checks = {"valid": True, "item_count": len(normalized["suggested_modes"])}
        else:
            plan = _normalize_plan_draft(parsed.get("plan_draft"), session=session)
            standard = _normalize_standard_draft(parsed.get("standard_draft"), plan=plan)
            repairs = _repair_ai_draft_structure(
                session=session,
                plan=plan,
                standard=standard,
            )
            checks = run_automatic_checks(session=session, plan=plan, standard=standard)
            checks["structural_repairs"] = repairs
            normalized = {"plan_draft": plan, "standard_draft": standard}
        _assert_no_sensitive_data(normalized, field="normalized_ai_response")
    except Exception as exc:
        safe_message = _safe_error_message(exc)
        error_code = getattr(exc, "code", "ai_generation_failed")[:64]
        with transaction.atomic():
            locked = (
                AIEvaluationDraftSession.objects.select_for_update()
                .select_related("teacher", "course", "curriculum_version__source")
                .get(pk=session_id)
            )
            _create_generation_record(
                session=locked,
                stage=stage,
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                generation_config=generation_config,
                status=AIEvaluationGenerationStatus.FAILED,
                error_code=error_code,
                error_message=safe_message,
            )
            if locked.status != AIEvaluationDraftStatus.CANCELLED:
                locked.status = AIEvaluationDraftStatus.FAILED
                locked.last_error_code = error_code
                locked.last_error_message = safe_message
                locked.save(
                    update_fields=["status", "last_error_code", "last_error_message", "updated_at"]
                )
        return {"status": "failed", "error_code": error_code}
    with transaction.atomic():
        locked = (
            AIEvaluationDraftSession.objects.select_for_update()
            .select_related("teacher", "course", "curriculum_version__source")
            .get(pk=session_id)
        )
        record = _create_generation_record(
            session=locked,
            stage=stage,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw_response_text=raw_text,
            raw_result=parsed,
            parsed_result=normalized,
            validation_result=checks,
            generation_config=generation_config,
            status=AIEvaluationGenerationStatus.SUCCEEDED,
        )
        if locked.status == AIEvaluationDraftStatus.CANCELLED:
            return {"status": "cancelled", "generation_record_id": record.id}
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES:
            locked.suggested_modes = normalized["suggested_modes"]
            locked.status = AIEvaluationDraftStatus.MODES_SUGGESTED
            update_fields = ["suggested_modes", "status"]
        else:
            locked.plan_draft = normalized["plan_draft"]
            locked.standard_draft = normalized["standard_draft"]
            locked.automatic_check_result = checks
            locked.status = AIEvaluationDraftStatus.DRAFT_GENERATED
            update_fields = ["plan_draft", "standard_draft", "automatic_check_result", "status"]
        locked.last_error_code = ""
        locked.last_error_message = ""
        update_fields.extend(["last_error_code", "last_error_message", "updated_at"])
        locked.save(update_fields=update_fields)
    return {"status": "succeeded", "generation_record_id": record.id}


def dispatch_generation_stage(
    *,
    session: AIEvaluationDraftSession,
    teacher,
    task_kind: str,
    regenerate: bool = False,
):
    from learning_analytics.tasks import run_ai_evaluation_drafting_task

    expected_status = (
        AIEvaluationDraftStatus.RETRIEVED
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else AIEvaluationDraftStatus.MODES_CONFIRMED
    )
    queued_status = (
        AIEvaluationDraftStatus.MODE_SUGGESTION_QUEUED
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else AIEvaluationDraftStatus.DRAFT_QUEUED
    )
    running_status = (
        AIEvaluationDraftStatus.MODE_SUGGESTION_RUNNING
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else AIEvaluationDraftStatus.DRAFT_RUNNING
    )
    completed_status = (
        AIEvaluationDraftStatus.MODES_SUGGESTED
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else AIEvaluationDraftStatus.DRAFT_GENERATED
    )
    with transaction.atomic():
        locked = (
            AIEvaluationDraftSession.objects.select_for_update()
            .select_related("teacher")
            .get(pk=session.pk, teacher=teacher)
        )
        if locked.status in {queued_status, running_status} and locked.active_task_kind == task_kind:
            return locked, False
        can_regenerate = (
            regenerate
            and task_kind == AIEvaluationTaskKind.GENERATE_DRAFT
            and locked.status == completed_status
            and not locked.linked_plan_id
            and not locked.linked_standard_id
        )
        if locked.status == completed_status and not can_regenerate:
            return locked, False
        retryable_failure = (
            locked.status == AIEvaluationDraftStatus.FAILED and locked.active_task_kind == task_kind
        )
        if locked.status != expected_status and not retryable_failure and not can_regenerate:
            raise AIEvaluationDraftError(
                "当前会话步骤不允许提交该后台任务。",
                code="invalid_stage_transition",
                status=409,
            )
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES and not locked.retrieval_snapshot:
            raise AIEvaluationDraftError("请先检索课程标准依据。", status=409)
        if task_kind == AIEvaluationTaskKind.GENERATE_DRAFT and not locked.confirmed_modes:
            raise AIEvaluationDraftError("请先由教师确认评价方式。", status=409)
        task_id = str(uuid.uuid4())
        locked.status = queued_status
        locked.active_task_kind = task_kind
        locked.celery_task_id = task_id
        locked.dispatch_count += 1
        locked.dispatch_attempted_at = timezone.now()
        locked.last_error_code = ""
        locked.last_error_message = ""
        if can_regenerate:
            # Previous provider calls remain in the append-only generation records.
            # Clear only the active session result so clients cannot mistake the old
            # incomplete draft for the newly queued attempt.
            locked.plan_draft = {}
            locked.standard_draft = {}
            locked.automatic_check_result = {}
        locked.save(
            update_fields=[
                "status",
                "active_task_kind",
                "celery_task_id",
                "dispatch_count",
                "dispatch_attempted_at",
                "last_error_code",
                "last_error_message",
                *(
                    ["plan_draft", "standard_draft", "automatic_check_result"]
                    if can_regenerate
                    else []
                ),
                "updated_at",
            ]
        )
    try:
        run_ai_evaluation_drafting_task.apply_async(
            args=[locked.id, task_kind],
            task_id=task_id,
            queue=getattr(settings, "AI_EVALUATION_DRAFT_QUEUE", "celery"),
            retry=False,
        )
    except Exception as exc:
        safe_message = _safe_error_message(exc)
        with transaction.atomic():
            failed = AIEvaluationDraftSession.objects.select_for_update().get(pk=locked.pk)
            if failed.status == queued_status and failed.celery_task_id == task_id:
                failed.status = AIEvaluationDraftStatus.FAILED
                failed.last_error_code = "broker_unavailable"
                failed.last_error_message = safe_message
                failed.save(
                    update_fields=["status", "last_error_code", "last_error_message", "updated_at"]
                )
        return failed, False
    locked.refresh_from_db()
    return locked, True


@transaction.atomic
def confirm_modes(
    *,
    session: AIEvaluationDraftSession,
    teacher,
    modes: list[str],
    teacher_note: str = "",
) -> AIEvaluationDraftSession:
    _assert_no_sensitive_data({"modes": modes, "teacher_note": teacher_note})
    normalized = list(dict.fromkeys(_text(item, max_length=32) for item in modes))
    if not normalized or any(item not in EvaluationMode.values for item in normalized):
        raise AIEvaluationDraftError(
            "请至少确认一种有效评价方式。", errors={"modes": ["包含不支持的评价方式。"]}
        )
    locked = (
        AIEvaluationDraftSession.objects.select_for_update()
        .select_related("teacher")
        .get(pk=session.pk, teacher=teacher)
    )
    if locked.status == AIEvaluationDraftStatus.MODES_CONFIRMED:
        if locked.confirmed_modes == normalized and locked.teacher_mode_note == _text(teacher_note, max_length=500):
            return locked
        raise AIEvaluationDraftError("评价方式已经确认，不能覆盖原确认记录。", status=409)
    if locked.status != AIEvaluationDraftStatus.MODES_SUGGESTED:
        raise AIEvaluationDraftError("请等待评价方式建议完成后再确认。", status=409)
    generation = locked.generation_records.filter(
        stage=AIEvaluationGenerationStage.MODE_SUGGESTION,
        status=AIEvaluationGenerationStatus.SUCCEEDED,
    ).order_by("-attempt_no").first()
    suggested = {row.get("mode"): row for row in locked.suggested_modes}
    sequence = 1
    for mode, ai_value in suggested.items():
        decision = (
            AIEvaluationTeacherDecisionType.ACCEPTED
            if mode in normalized
            else AIEvaluationTeacherDecisionType.REJECTED
        )
        teacher_value = ai_value if mode in normalized else None
        diff = _diff_values(ai_value, teacher_value)
        decision_payload = {
            "decision": decision,
            "ai_value": ai_value,
            "teacher_value": teacher_value,
            "diff": diff,
            "reason": _text(teacher_note, max_length=500),
        }
        AIEvaluationTeacherDecision.objects.create(
            session=locked,
            generation=generation,
            teacher=teacher,
            stage="mode_confirmation",
            item_type="evaluation_mode",
            item_key=str(mode),
            sequence=sequence,
            decision=decision,
            ai_value=ai_value,
            teacher_value=teacher_value,
            diff=diff,
            reason=decision_payload["reason"],
            content_hash=ai_evaluation_content_hash(decision_payload),
        )
        sequence += 1
    for mode in normalized:
        if mode in suggested:
            continue
        teacher_value = {"mode": mode, "label": MODE_LABELS[mode]}
        diff = _diff_values(None, teacher_value)
        decision_payload = {
            "decision": AIEvaluationTeacherDecisionType.EDITED,
            "ai_value": None,
            "teacher_value": teacher_value,
            "diff": diff,
            "reason": _text(teacher_note, max_length=500),
        }
        AIEvaluationTeacherDecision.objects.create(
            session=locked,
            generation=generation,
            teacher=teacher,
            stage="mode_confirmation",
            item_type="evaluation_mode",
            item_key=mode,
            sequence=sequence,
            decision=AIEvaluationTeacherDecisionType.EDITED,
            ai_value=None,
            teacher_value=teacher_value,
            diff=diff,
            reason=decision_payload["reason"],
            content_hash=ai_evaluation_content_hash(decision_payload),
        )
        sequence += 1
    locked.confirmed_modes = normalized
    locked.teacher_mode_note = _text(teacher_note, max_length=500)
    locked.status = AIEvaluationDraftStatus.MODES_CONFIRMED
    locked.active_task_kind = AIEvaluationTaskKind.NONE
    locked.save(
        update_fields=[
            "confirmed_modes",
            "teacher_mode_note",
            "status",
            "active_task_kind",
            "updated_at",
        ]
    )
    return locked


def _review_item_map(plan: dict, standard: dict) -> dict[str, dict]:
    plan_list_fields = {
        "learning_goal": "learning_goals",
        "evaluation_basis": "evaluation_basis",
        "learning_activity": "learning_activities",
        "learning_task": "learning_tasks",
        "evaluation_task": "evaluation_tasks",
    }
    plan_overall = {
        key: value
        for key, value in plan.items()
        if key not in set(plan_list_fields.values()) | {"follow_up_suggestion"}
    }
    result = {
        "overall:plan": {"item_type": "overall", "item_code": "plan", "value": plan_overall},
        "follow_up_suggestion:plan": {
            "item_type": "follow_up_suggestion",
            "item_code": "plan",
            "value": plan.get("follow_up_suggestion"),
        },
    }
    for item_type, field_name in plan_list_fields.items():
        for row in plan.get(field_name, []) if isinstance(plan.get(field_name), list) else []:
            code = _text(row.get("code"), max_length=64) if isinstance(row, dict) else ""
            if code:
                result[f"{item_type}:{code}"] = {
                    "item_type": item_type,
                    "item_code": code,
                    "value": row,
                }
    result["overall:standard"] = {
        "item_type": "overall",
        "item_code": "standard",
        "value": {
            "title": standard.get("title"),
            "evaluation_target": standard.get("evaluation_target"),
        },
    }
    criteria = standard.get("criteria") if isinstance(standard.get("criteria"), list) else []
    for criterion in criteria:
        if not isinstance(criterion, dict):
            continue
        code = _text(criterion.get("code"), max_length=64)
        if not code:
            continue
        result[f"evaluation_criterion:{code}"] = {
            "item_type": "evaluation_criterion",
            "item_code": code,
            "value": criterion,
        }
        levels = criterion.get("level_descriptions")
        levels = levels if isinstance(levels, dict) else {}
        for level in range(1, 6):
            result[f"performance_level:{code}:{level}"] = {
                "item_type": "performance_level",
                "item_code": f"{code}:{level}",
                "value": levels.get(str(level), levels.get(level)),
            }
        result[f"follow_up_suggestion:{code}"] = {
            "item_type": "follow_up_suggestion",
            "item_code": code,
            "value": criterion.get("follow_up_suggestion"),
        }
        examples = criterion.get("scoring_examples")
        examples = examples if isinstance(examples, list) else []
        for index, example in enumerate(examples, start=1):
            level = _text(example.get("level"), max_length=4) if isinstance(example, dict) else ""
            result[f"scoring_example:{code}:{level}:{index}"] = {
                "item_type": "scoring_example",
                "item_code": f"{code}:{level}:{index}",
                "value": example,
            }
    return result


def _diff_values(before: Any, after: Any) -> dict:
    if before == after:
        return {"changed": False, "changed_fields": []}
    changed_fields = []
    if isinstance(before, dict) and isinstance(after, dict):
        changed_fields = sorted(
            key for key in set(before) | set(after) if before.get(key) != after.get(key)
        )
    return {
        "changed": True,
        "changed_fields": changed_fields,
        "before_hash": ai_evaluation_content_hash(before),
        "after_hash": ai_evaluation_content_hash(after),
    }


def _scoring_example_by_original_key(standard: dict, item_key: str):
    parts = item_key.split(":")
    if len(parts) != 4 or parts[0] != "scoring_example":
        return None
    criterion_code, _, index_text = parts[1:]
    try:
        index = int(index_text) - 1
    except (TypeError, ValueError):
        return None
    for criterion in standard.get("criteria", []):
        if not isinstance(criterion, dict) or str(criterion.get("code")) != criterion_code:
            continue
        examples = criterion.get("scoring_examples")
        if isinstance(examples, list) and 0 <= index < len(examples):
            return examples[index]
    return None


def _record_teacher_review_decisions(
    *,
    session: AIEvaluationDraftSession,
    teacher,
    plan_draft: dict,
    standard_draft: dict,
    decisions: list[dict],
) -> None:
    generation = session.generation_records.filter(
        stage=AIEvaluationGenerationStage.EVALUATION_DRAFT,
        status=AIEvaluationGenerationStatus.SUCCEEDED,
    ).order_by("-attempt_no").first()
    ai_items = _review_item_map(session.plan_draft, session.standard_draft)
    teacher_items = _review_item_map(plan_draft, standard_draft)
    supplied_keys = []
    decision_by_key = {}
    for row in decisions:
        if not isinstance(row, dict):
            raise AIEvaluationDraftError("教师逐项审阅记录格式不正确。")
        item_key = _text(row.get("item_key"), max_length=128)
        if not item_key:
            raise AIEvaluationDraftError("教师逐项审阅记录缺少稳定项目键。")
        supplied_keys.append(item_key)
        decision_by_key[item_key] = row
    duplicate_keys = sorted({key for key in supplied_keys if supplied_keys.count(key) > 1})
    if duplicate_keys:
        raise AIEvaluationDraftError(
            "教师逐项审阅记录不能重复。",
            code="duplicate_review_decision",
            errors={"review_decisions": [f"重复项目：{', '.join(duplicate_keys)}"]},
        )
    required_keys = set(ai_items)
    supplied = set(supplied_keys)
    missing = sorted(required_keys - supplied)
    unknown = sorted(supplied - required_keys)
    if missing or unknown:
        errors = {}
        if missing:
            errors["missing"] = [f"尚未审阅：{', '.join(missing)}"]
        if unknown:
            errors["unknown"] = [f"未知项目：{', '.join(unknown)}"]
        raise AIEvaluationDraftError(
            "必须逐项审阅 AI 生成的全部内容后才能保存草稿。",
            code="incomplete_teacher_review",
            errors={"review_decisions": errors},
        )
    existing_count = session.teacher_decisions.filter(stage="draft_revision").count()
    for offset, item_key in enumerate(sorted(required_keys), start=1):
        row = decision_by_key[item_key]
        if not isinstance(row, dict):
            raise AIEvaluationDraftError("教师逐项审阅记录格式不正确。")
        expected = ai_items[item_key]
        item_type = expected["item_type"]
        supplied_type = _text(row.get("item_type"), max_length=48)
        if supplied_type and supplied_type != item_type:
            raise AIEvaluationDraftError(
                "教师逐项审阅记录的项目类型与项目键不一致。",
                errors={"review_decisions": [f"{item_key} 应为 {item_type}。"]},
            )
        client_decision = _text(row.get("decision"), max_length=16)
        decision_map = {
            "accepted": AIEvaluationTeacherDecisionType.ACCEPTED,
            "modified": AIEvaluationTeacherDecisionType.EDITED,
            "edited": AIEvaluationTeacherDecisionType.EDITED,
            "removed": AIEvaluationTeacherDecisionType.REJECTED,
            "rejected": AIEvaluationTeacherDecisionType.REJECTED,
        }
        if client_decision not in decision_map:
            raise AIEvaluationDraftError(
                "教师逐项审阅记录包含无效决定。",
                errors={"review_decisions": [f"{item_key} 的决定不正确。"]},
            )
        ai_value = expected["value"]
        teacher_value = teacher_items.get(item_key, {}).get("value")
        if (
            item_key.startswith("scoring_example:")
            and teacher_value is None
            and client_decision not in {"removed", "rejected"}
        ):
            teacher_value = _scoring_example_by_original_key(standard_draft, item_key)
        teacher_item_exists = item_key in teacher_items or teacher_value is not None
        actual_decision = (
            AIEvaluationTeacherDecisionType.REJECTED
            if not teacher_item_exists
            else (
                AIEvaluationTeacherDecisionType.ACCEPTED
                if ai_value == teacher_value
                else AIEvaluationTeacherDecisionType.EDITED
            )
        )
        if client_decision in {"removed", "rejected"} and teacher_item_exists:
            raise AIEvaluationDraftError(
                "标记为不采纳的项目仍存在于教师提交内容中。",
                code="review_decision_mismatch",
                errors={"review_decisions": [item_key]},
            )
        if client_decision not in {"removed", "rejected"} and not teacher_item_exists:
            raise AIEvaluationDraftError(
                "标记为采纳或修改的项目未出现在教师提交内容中。",
                code="review_decision_mismatch",
                errors={"review_decisions": [item_key]},
            )
        diff = _diff_values(ai_value, teacher_value)
        reason = _text(row.get("reason"), max_length=500)
        payload = {
            "decision": actual_decision,
            "ai_value": ai_value,
            "teacher_value": teacher_value,
            "diff": diff,
            "reason": reason,
        }
        AIEvaluationTeacherDecision.objects.create(
            session=session,
            generation=generation,
            teacher=teacher,
            stage="draft_revision",
            item_type=item_type,
            item_key=item_key,
            sequence=existing_count + offset,
            decision=actual_decision,
            ai_value=ai_value,
            teacher_value=teacher_value,
            diff=diff,
            reason=reason,
            content_hash=ai_evaluation_content_hash(payload),
        )


@transaction.atomic
def save_plan_draft(
    *,
    session: AIEvaluationDraftSession,
    teacher,
    plan_draft: dict,
    standard_draft: dict,
    review_decisions: list[dict],
):
    from api.analytics.evaluation_serializers import EvaluationPlanWriteSerializer

    _assert_no_sensitive_data(
        {
            "plan_draft": plan_draft,
            "standard_draft": standard_draft,
            "review_decisions": review_decisions,
        }
    )
    if not isinstance(plan_draft, dict) or not isinstance(standard_draft, dict):
        raise AIEvaluationDraftError("评价方案初稿和评价标准初稿必须是 JSON 对象。")
    if not isinstance(review_decisions, list) or not review_decisions:
        raise AIEvaluationDraftError(
            "保存前必须完成逐项教师审阅。",
            errors={"review_decisions": ["至少需要一条教师审阅决定。"]},
        )
    locked = (
        AIEvaluationDraftSession.objects.select_for_update()
        .select_related(
            "teacher",
            "course__subject",
            "curriculum_version__source",
            "linked_plan",
            "linked_standard",
        )
        .get(pk=session.pk, teacher=teacher)
    )
    save_payload = {
        "plan_draft": plan_draft,
        "standard_draft": standard_draft,
        "review_decisions": review_decisions,
    }
    save_hash = ai_evaluation_content_hash(save_payload)
    if locked.status == AIEvaluationDraftStatus.SAVED:
        if (
            locked.save_request_hash == save_hash
            and locked.linked_plan_id
            and locked.linked_standard_id
        ):
            return locked, locked.linked_plan, locked.linked_standard, False
        raise AIEvaluationDraftError(
            "该 AI 初稿已经保存；如需继续修改，请在评价方案草稿中编辑。",
            code="draft_already_saved",
            status=409,
        )
    if locked.status != AIEvaluationDraftStatus.DRAFT_GENERATED:
        raise AIEvaluationDraftError("请等待评价初稿生成并完成教师审阅后再保存。", status=409)
    submitted_plan = dict(plan_draft)
    submitted_plan["course"] = locked.course_id
    selected_version_can_bind = (
        locked.curriculum_version.status == CurriculumVersionStatus.PUBLISHED
        and locked.curriculum_version.source.current_version_id == locked.curriculum_version_id
    )
    valid_node_ids = {
        int(item["id"])
        for item in locked.retrieval_snapshot
        if str(item.get("id", "")).isdigit()
    }
    submitted_ids = _int_list(submitted_plan.get("curriculum_node_ids"), allowed=valid_node_ids)
    if selected_version_can_bind:
        submitted_plan["curriculum_node_ids"] = submitted_ids or sorted(valid_node_ids)
    else:
        raise AIEvaluationDraftError(
            "所选课程标准已不是当前发布版本，不能保存新的评价草稿。",
            code="curriculum_version_no_longer_current",
            status=409,
        )
    standard_payload = _normalize_standard_draft(standard_draft, plan=submitted_plan)
    teacher_checks = run_automatic_checks(
        session=locked,
        plan=submitted_plan,
        standard=standard_payload,
    )
    blocked_checks = [
        item for item in teacher_checks["checks"] if item.get("status") == "blocked"
    ]
    if blocked_checks:
        raise AIEvaluationDraftError(
            "教师修改后的评价草稿未通过自动检查，请修正后再保存。",
            code="automatic_checks_blocked",
            errors={"checks": blocked_checks},
        )
    _record_teacher_review_decisions(
        session=locked,
        teacher=teacher,
        plan_draft=submitted_plan,
        standard_draft=standard_payload,
        decisions=review_decisions,
    )
    serializer = EvaluationPlanWriteSerializer(
        locked.linked_plan,
        data=submitted_plan,
        context={"request": SimpleNamespace(user=teacher)},
    ) if locked.linked_plan_id else EvaluationPlanWriteSerializer(
        data=submitted_plan,
        context={"request": SimpleNamespace(user=teacher)},
    )
    if not serializer.is_valid():
        raise AIEvaluationDraftError(
            "评价方案草稿未通过字段校验。",
            code="plan_draft_invalid",
            errors=serializer.errors,
        )
    plan = serializer.save()
    if plan.review_status != EvaluationReviewStatus.DRAFT:
        raise AIEvaluationDraftError(
            "AI 起草只能保存为待教师复核的评价方案草稿。",
            code="draft_boundary_violation",
            status=409,
        )
    standard = locked.linked_standard
    if standard is None:
        standard = EvaluationStandard.objects.create(
            school=locked.school,
            subject=locked.subject,
            course=locked.course,
            plan=plan,
            plan_version=None,
            title=standard_payload["title"],
            scope=EvaluationScope.COURSE,
            evaluation_target=standard_payload["evaluation_target"],
            criteria=standard_payload["criteria"],
            review_status=EvaluationReviewStatus.DRAFT,
            created_by=teacher,
            updated_by=teacher,
        )
    else:
        if standard.review_status != EvaluationReviewStatus.DRAFT:
            raise AIEvaluationDraftError(
                "AI 起草不能覆盖已复核的评价标准。",
                code="draft_boundary_violation",
                status=409,
            )
        standard.plan = plan
        standard.plan_version = None
        standard.title = standard_payload["title"]
        standard.evaluation_target = standard_payload["evaluation_target"]
        standard.criteria = standard_payload["criteria"]
        standard.reviewed_by = None
        standard.reviewed_at = None
        standard.reviewed_content_hash = ""
        standard.updated_by = teacher
        standard.save()
    locked.plan_draft = submitted_plan
    locked.standard_draft = standard_payload
    locked.automatic_check_result = teacher_checks
    locked.linked_plan = plan
    locked.linked_standard = standard
    locked.save_request_hash = save_hash
    locked.saved_at = timezone.now()
    locked.status = AIEvaluationDraftStatus.SAVED
    locked.active_task_kind = AIEvaluationTaskKind.NONE
    locked.save(
        update_fields=[
            "plan_draft",
            "standard_draft",
            "automatic_check_result",
            "linked_plan",
            "linked_standard",
            "save_request_hash",
            "saved_at",
            "status",
            "active_task_kind",
            "updated_at",
        ]
    )
    return locked, plan, standard, True


@transaction.atomic
def cancel_session(*, session: AIEvaluationDraftSession, teacher) -> AIEvaluationDraftSession:
    locked = AIEvaluationDraftSession.objects.select_for_update().get(
        pk=session.pk, teacher=teacher
    )
    if locked.status == AIEvaluationDraftStatus.CANCELLED:
        return locked
    if locked.status == AIEvaluationDraftStatus.SAVED:
        raise AIEvaluationDraftError("已保存为评价方案草稿的会话不能取消。", status=409)
    locked.status = AIEvaluationDraftStatus.CANCELLED
    locked.cancelled_at = timezone.now()
    locked.save(update_fields=["status", "cancelled_at", "updated_at"])
    return locked


def _public_status(status: str) -> str:
    return {
        AIEvaluationDraftStatus.CREATED: "context_ready",
        AIEvaluationDraftStatus.RETRIEVED: "references_ready",
        AIEvaluationDraftStatus.MODE_SUGGESTION_QUEUED: "suggesting_modes",
        AIEvaluationDraftStatus.MODE_SUGGESTION_RUNNING: "suggesting_modes",
        AIEvaluationDraftStatus.DRAFT_QUEUED: "generating_draft",
        AIEvaluationDraftStatus.DRAFT_RUNNING: "generating_draft",
    }.get(status, status)


def _background_task(session: AIEvaluationDraftSession) -> dict | None:
    if not session.active_task_kind and not session.last_error_code:
        return None
    if session.status in {
        AIEvaluationDraftStatus.MODE_SUGGESTION_QUEUED,
        AIEvaluationDraftStatus.DRAFT_QUEUED,
    }:
        status, progress = "queued", 0
    elif session.status in {
        AIEvaluationDraftStatus.MODE_SUGGESTION_RUNNING,
        AIEvaluationDraftStatus.DRAFT_RUNNING,
    }:
        status, progress = "running", None
    elif session.status == AIEvaluationDraftStatus.FAILED:
        status, progress = "failed", None
    else:
        status, progress = "completed", 100
    messages = {
        AIEvaluationTaskKind.SUGGEST_MODES: "正在后台形成评价方式建议。",
        AIEvaluationTaskKind.GENERATE_DRAFT: "正在后台形成评价方案与评价标准初稿。",
    }
    message = session.last_error_message or messages.get(session.active_task_kind, "后台任务已完成。")
    return {
        "kind": session.active_task_kind,
        "task_id": session.celery_task_id,
        "status": status,
        "message": message,
        "progress": progress,
        "dispatch_count": session.dispatch_count,
        "dispatch_attempted_at": (
            session.dispatch_attempted_at.isoformat() if session.dispatch_attempted_at else None
        ),
        "error_code": session.last_error_code,
    }


def serialize_session(session: AIEvaluationDraftSession, *, detail: bool = False) -> dict:
    version = session.curriculum_version
    data = {
        "id": session.id,
        "session_id": str(session.session_id),
        "status": _public_status(session.status),
        "status_label": session.get_status_display(),
        "context": {
            "course_id": session.course_id,
            "school_stage": session.school_stage,
            "grade_or_stage": session.grade_or_stage,
            "unit_title": session.unit_title,
            "curriculum_standard_version_id": session.curriculum_version_id,
            "course_content": session.course_content,
            "evaluation_purpose": session.evaluation_purpose,
        },
        "curriculum_standard_version": {
            "id": version.id,
            "title": version.official_title or version.title_snapshot,
            "version_label": version.version_label,
            "status": version.status,
            "status_label": version.get_status_display(),
            "school_stage": version.school_stage_snapshot,
            "subject": {
                "id": version.source_id,
                "name": version.subject_name_snapshot,
                "code": version.subject_code_snapshot,
            },
            "compatible_course_ids": [session.course_id],
            "content_hash": session.curriculum_version_content_hash,
            "pdf_sha256": session.curriculum_pdf_sha256,
            "published_at": version.published_at.isoformat() if version.published_at else None,
        },
        "curriculum_references": session.retrieval_snapshot,
        "mode_suggestions": session.suggested_modes,
        "confirmed_modes": session.confirmed_modes,
        "teacher_mode_note": session.teacher_mode_note,
        "plan_draft": session.plan_draft or None,
        "standard_draft": session.standard_draft or None,
        "checks": session.automatic_check_result.get("checks", []),
        "background_task": _background_task(session),
        "linked_plan_id": session.linked_plan_id,
        "linked_standard_id": session.linked_standard_id,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }
    if detail:
        data["audit"] = {
            "request_hash": session.request_hash,
            "retrieval_snapshot_hash": session.retrieval_snapshot_hash,
            "generation_records": [
                {
                    "id": row.id,
                    "stage": row.stage,
                    "attempt_no": row.attempt_no,
                    "provider": row.provider,
                    "model": row.model,
                    "system_prompt": row.system_prompt,
                    "user_prompt": row.user_prompt,
                    "prompt_hash": row.prompt_hash,
                    "generation_config": row.generation_config,
                    "retrieval_snapshot": row.retrieval_snapshot,
                    "raw_response_text": row.raw_response_text,
                    "raw_result": row.raw_result,
                    "parsed_result": row.parsed_result,
                    "validation_result": row.validation_result,
                    "result_hash": row.result_hash,
                    "status": row.status,
                    "error_code": row.error_code,
                    "error_message": row.error_message,
                    "created_at": row.created_at.isoformat(),
                }
                for row in session.generation_records.all()
            ],
            "teacher_decisions": [
                {
                    "id": row.id,
                    "stage": row.stage,
                    "item_type": row.item_type,
                    "item_key": row.item_key,
                    "sequence": row.sequence,
                    "decision": row.decision,
                    "ai_value": row.ai_value,
                    "teacher_value": row.teacher_value,
                    "diff": row.diff,
                    "reason": row.reason,
                    "content_hash": row.content_hash,
                    "created_at": row.created_at.isoformat(),
                }
                for row in session.teacher_decisions.all()
            ],
        }
    return data
