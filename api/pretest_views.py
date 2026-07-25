from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.request
import zipfile
from io import BytesIO
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from xml.sax.saxutils import escape

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login as auth_login,
    logout as auth_logout,
    update_session_auth_hash,
)
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction
from django.http import JsonResponse
from django.db.models import Count, F, Max, Prefetch, Q, Sum, TextField
from django.db.models.functions import Cast, TruncDate
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from config.onlyoffice import (
    OnlyOfficeJWTError,
    sign_editor_config,
    verify_callback_payload,
)
from aiops.models import ModelVersion, TrainingJob
from courses.models import (
    ClassroomActivity,
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupDocumentVersion,
    ClassroomGroupFile,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    LearningWebPage,
    LearningWebPageResponse,
    LearningWebPageVersion,
    Lesson,
    LessonStep,
    Resource,
    ResourceFile,
    Subject,
)
from courses.grouping import build_grouping_plan
from learning.models import (
    DiagnosticAdministration,
    DiagnosticAdministrationAssignment,
    DiagnosticSubmissionBinding,
    Feedback,
    LearningEvent,
    LessonStepAttempt,
    LessonStepAttemptAnswer,
    Notice,
    PretestPaper,
    PretestMaterialAttachment,
    PretestPaperVersion,
    PretestQuestion,
    PretestSubmission,
    QuestionBankItem,
    StratificationDecision,
    StudentWorkAttachment,
    StudentLearningTargetStateVersion,
    UnifiedAssessmentMaterial,
    TestAssessment,
    TestAttempt,
)
from learning.services.diagnostic_administrations import (
    DiagnosticAdministrationError,
    availability_status,
    bind_diagnostic_submission,
    diagnostic_completion_status,
    prepare_student_diagnostic_submission,
)
from learning.services.bands import resolve_student_band
from learning.services.mastery import build_initial_diagnostic_content_band_candidate
from learning.services.stratification_visibility import (
    visible_published_decisions,
    visible_teacher_decisions,
)
from learning_analytics.services.classroom_events import (
    ClassroomEventError,
    classroom_question,
    classroom_question_version,
    ensure_classroom_attachment_submission,
    ensure_classroom_step_opportunities,
    next_classroom_grading_state,
    record_classroom_attachment_submission,
    record_classroom_attempt_events,
    record_classroom_document_progress,
    record_classroom_item_grade,
    record_classroom_resource_opened,
    record_classroom_video_progress,
    record_learning_page_block_viewed,
    record_learning_page_form_submission,
    record_learning_page_opened,
)
from learning_analytics.services.attendance_events import (
    AttendanceEventError,
    is_attendance_activity,
    record_attendance_status,
)
from learning_analytics.services.classroom_interaction_events import (
    ClassroomInteractionEventError,
    record_quick_answer_response,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    record_classroom_point_adjustment,
)
from learning_analytics.services.evaluation_events import (
    EvaluationEventError,
    append_evaluation_submission,
    freeze_classroom_evaluation_standard,
    release_classroom_evaluation_opportunities,
    standard_binding_criteria,
    withdraw_classroom_evaluation_opportunities,
)
from learning_analytics.models import (
    ClassroomEvaluationStandardUse,
    GroupingCandidateRun,
    LearningTargetVersion,
    LessonStepEvaluationBinding,
)
from learning_analytics.services.group_collaboration_events import (
    GroupCollaborationEventError,
    record_group_document_opened,
    record_group_document_saved,
    record_group_file_shared,
    release_group_collaboration_opportunities,
    withdraw_group_collaboration_opportunities,
)
from learning_analytics.services.grouping_plans import (
    capture_grouping_outcomes,
    confirm_grouping_candidate,
    generate_grouping_candidate_run,
    record_confirmed_plan_evidence,
)
from learning_analytics.services.operational_events import (
    record_classroom_interaction_response,
    record_intervention_acknowledged,
    record_lesson_entered,
    record_lesson_step_completed,
    record_lesson_step_entered,
    record_pretest_submitted,
    record_resource_center_opened,
)
from ops.models import AuditLog, ExportBatch, ImportBatch
from ops.xlsx import export_rows, template_response
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment
from realtime.events import publish_chat_event, session_group, teacher_group

from .permissions import IsSchoolAdmin, IsStudent, IsSuperAdmin, IsTeacher
from .protected_files import signed_protected_file_url
from .responses import fail, ok, page_data
from .view_utils import current_school as _school
from .view_utils import paginate as _paginate
from .view_utils import service_error_response as _service_fail
from .serializers import (
    account_row,
    classroom_activity_row,
    classroom_evaluation_config_row,
    classroom_evaluation_submission_row,
    classroom_group_collaboration_row,
    classroom_group_file_row,
    classroom_session_row,
    classroom_attendance_row,
    class_group_row,
    clean_resource_ext,
    course_row,
    feedback_row,
    lesson_row,
    learning_web_page_response_row,
    learning_web_page_row,
    learning_web_page_version_row,
    lesson_step_has_layered_questions,
    lesson_step_row,
    normalize_lesson_question_items,
    notice_row,
    pretest_paper_row,
    pretest_question_row,
    resource_row,
    school_row,
    student_row,
    student_classroom_row,
    student_classroom_group_collaboration_row,
    student_classroom_group_row,
    student_course_row,
    student_feedback_row,
    student_lesson_step_row,
    student_notice_row,
    student_profile_summary,
    student_teacher_row,
    student_work_attachment_row,
    subject_row,
    teacher_ai_provider_row,
    teacher_student_profile_summary,
    teaching_assignment_row,
    teaching_teacher_row,
    user_summary,
)
from .services import (
    ServiceError,
    bulk_create_class_groups,
    bulk_delete_class_groups,
    bulk_delete_school_admin_accounts,
    bulk_delete_schools,
    bulk_delete_students,
    bulk_delete_teacher_accounts,
    bulk_disable_class_groups,
    bulk_disable_school_admin_accounts,
    bulk_disable_schools,
    bulk_disable_students,
    bulk_disable_teacher_accounts,
    bulk_save_teaching_assignments,
    archive_pretest_paper,
    create_school_admin,
    create_student,
    create_teacher,
    delete_account,
    delete_class_group,
    delete_pretest_paper,
    delete_pretest_question,
    delete_school,
    delete_student,
    delete_teaching_assignment,
    delete_subject,
    graduate_class_groups,
    import_students_from_xlsx,
    import_teachers_from_xlsx,
    get_teacher_ai_provider,
    generate_lesson_step_questions_with_ai,
    generate_learning_web_page_schema,
    publish_pretest_paper,
    promote_class_groups,
    reset_school_admin_password,
    reset_student_password,
    reset_teacher_password,
    archive_teacher_notice,
    save_class_group,
    save_teacher_ai_provider,
    save_teacher_notice,
    save_pretest_paper,
    save_pretest_question,
    save_school,
    save_subject,
    save_teaching_assignment,
    set_account_active,
    set_student_active,
    publish_teacher_notice,
    restart_classroom_session,
    reply_teacher_feedback,
    close_teacher_feedback,
    archive_teacher_course,
    archive_teacher_lesson,
    close_classroom_activity,
    close_classroom_current_step,
    delete_classroom_activity,
    delete_classroom_session,
    delete_teacher_course,
    delete_teacher_lesson,
    finish_classroom_session,
    lock_classroom_current_step,
    open_classroom_activity,
    publish_teacher_course,
    publish_teacher_lesson,
    save_classroom_activity,
    save_classroom_session,
    set_classroom_current_step,
    save_teacher_course,
    save_teacher_course_cover,
    save_teacher_lesson,
    save_lesson_step,
    save_teacher_resource,
    set_teacher_course_classes,
    delete_teacher_course_cover,
    delete_teacher_resource,
    start_classroom_session,
    test_teacher_ai_provider,
    reorder_lesson_steps,
    run_classroom_command,
    _teacher_classroom_activity,
    _teacher_classroom_session,
    _teacher_course,
    _teacher_lesson,
    _teacher_resource,
    delete_lesson_step,
    delete_teacher_notice,
    update_student,
    update_school_admin,
    update_teacher,
    write_audit,
    STUDENT_IMPORT_HEADERS,
    TEACHER_IMPORT_HEADERS,
)

# Pretest domain endpoints extracted from api.views.
from .views import (
    _student_profile,
    _student_required_pretest_status,
)


PRETEST_ATTACHMENT_EXTENSIONS = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "txt",
    "csv",
    "docx",
    "xlsx",
    "pptx",
}
PRETEST_ATTACHMENT_MIME_TYPES = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
    "txt": {"text/plain"},
    "csv": {"text/csv", "application/csv", "text/plain"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
}
PRETEST_ATTACHMENT_QUESTION_TYPES = {
    PretestQuestion.QuestionType.PERFORMANCE,
    PretestQuestion.QuestionType.OPERATION,
    PretestQuestion.QuestionType.SHORT_PROJECT,
}

DIAGNOSTIC_SOURCE_BY_PURPOSE = {
    DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC: "learning_entry_diagnostic",
    DiagnosticAdministration.Purpose.RESEARCH_PRETEST: "research_pretest",
    DiagnosticAdministration.Purpose.RESEARCH_POSTTEST: "research_posttest",
    DiagnosticAdministration.Purpose.PILOT: "diagnostic_pilot",
}
DIAGNOSTIC_SOURCE_TYPES = set(DIAGNOSTIC_SOURCE_BY_PURPOSE.values())
DIAGNOSTIC_REVIEW_SOURCE_BY_SOURCE = {
    source_type: f"{source_type}_review"
    for source_type in DIAGNOSTIC_SOURCE_TYPES
}
DIAGNOSTIC_REVIEW_SOURCE_TYPES = set(DIAGNOSTIC_REVIEW_SOURCE_BY_SOURCE.values())
DIAGNOSTIC_UNCERTAINTY_METHOD = "conservative_task_coverage_se_v1"


def _pretest_validity_policy(observed_at):
    days = min(
        max(int(getattr(settings, "LEARNING_ENTRY_DIAGNOSTIC_VALIDITY_DAYS", 90)), 1),
        365,
    )
    return {
        "code": "learning_entry_diagnostic_validity_days",
        "days": days,
        "valid_until": observed_at + timedelta(days=days),
    }


def _diagnostic_target_uncertainty(
    *,
    evidence_status: str,
    observed_task_count: int,
    task_count: int,
) -> tuple[float | None, float]:
    coverage = observed_task_count / task_count if task_count else 0.0
    if (
        evidence_status
        not in {
            StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE,
            StudentLearningTargetStateVersion.EvidenceStatus.PARTIAL,
        }
        or observed_task_count <= 0
    ):
        return None, coverage
    # Auditable conservative proxy, not a claim of psychometric calibration:
    # combine missing-task coverage with the worst-case Bernoulli standard error.
    uncertainty = max(1 - coverage, 0.5 / math.sqrt(observed_task_count))
    return round(min(uncertainty, 1.0), 6), coverage


def _student_pretest_version_row(
    paper: PretestPaper,
    paper_version: PretestPaperVersion,
    *,
    assignment: DiagnosticAdministrationAssignment | None = None,
) -> dict:
    question_type_labels = dict(PretestQuestion.QuestionType.choices)
    questions = []
    for raw in paper_version.question_snapshot:
        if not isinstance(raw, dict):
            continue
        question_type = str(raw.get("question_type") or "")
        questions.append(
            {
                "id": raw.get("id"),
                "paper": paper.id,
                "stem": str(raw.get("stem") or ""),
                "question_type": question_type,
                "question_type_label": question_type_labels.get(question_type, question_type),
                "options": raw.get("options") if isinstance(raw.get("options"), list) else [],
                "score": raw.get("score") or 0,
                "dimension": str(raw.get("dimension") or ""),
                "learning_target_code": str(raw.get("learning_target_code") or ""),
                "learning_target_name": str(raw.get("learning_target_name") or ""),
                "material_requirements": (
                    raw.get("material_requirements")
                    if isinstance(raw.get("material_requirements"), list)
                    else []
                ),
                "attachment_policy": {
                    "enabled": question_type in PRETEST_ATTACHMENT_QUESTION_TYPES,
                    "allowed_extensions": sorted(PRETEST_ATTACHMENT_EXTENSIONS),
                    "max_files": min(
                        max(int(getattr(settings, "PRETEST_MATERIAL_MAX_FILES_PER_TASK", 3)), 1),
                        5,
                    ),
                    "max_file_mb": min(
                        max(int(getattr(settings, "PRETEST_MATERIAL_MAX_FILE_MB", 8)), 1),
                        25,
                    ),
                },
                "sort_order": int(raw.get("sort_order") or 0),
                "is_required": bool(raw.get("is_required", True)),
            }
        )
    row = {
        "id": paper.id,
        "subject": subject_row(paper.subject),
        "title": paper_version.title,
        "kind": paper_version.kind,
        "kind_label": dict(PretestPaper.Kind.choices).get(
            paper_version.kind, paper_version.kind
        ),
        "version": paper_version.version_no,
        "introduction": paper_version.introduction,
        "status": paper.status,
        "status_label": paper.get_status_display(),
        "question_count": len(questions),
        "submission_count": paper.submissions.count(),
        "published_at": paper_version.published_at,
        "published_version": {
            "id": paper_version.id,
            "version_no": paper_version.version_no,
            "content_hash": paper_version.content_hash,
        },
        "created_at": paper.created_at,
        "updated_at": paper.updated_at,
        "questions": questions,
    }
    if assignment is not None:
        # The caller adds the current student's completion row; this block only
        # freezes the administration identity alongside the paper snapshot.
        administration = assignment.administration
        row.update(
            {
                "administration_id": administration.id,
                "batch_code": administration.batch_code,
                "purpose": administration.purpose,
                "purpose_label": administration.get_purpose_display(),
                "opportunity_status": assignment.opportunity_status,
                "administration_content_hash": administration.content_hash,
                "open_at": administration.open_at,
                "close_at": administration.close_at,
            }
        )
    return row


def _student_diagnostic_availability_row(
    administration: DiagnosticAdministration,
    assignment: DiagnosticAdministrationAssignment,
    binding: DiagnosticSubmissionBinding | None,
) -> dict:
    """Return the only student-visible fields while a batch is not open.

    Scheduled and closed instruments may expose safe administration metadata
    needed for a status row, but never item text, options, material
    requirements, version hashes, or attachment/download locations.
    """

    return {
        "administration_id": administration.id,
        "batch_code": administration.batch_code,
        "title": administration.title,
        "purpose": administration.purpose,
        "purpose_label": administration.get_purpose_display(),
        "subject": subject_row(administration.subject),
        "opportunity_status": assignment.opportunity_status,
        "availability_status": availability_status(administration),
        "open_at": administration.open_at,
        "close_at": administration.close_at,
        "submission_allowed": False,
        "completion": diagnostic_completion_status(assignment, binding),
    }


def _student_diagnostic_assignment(student, administration_id, *, include_closed=True):
    profile = StudentProfile.objects.filter(user=student).first()
    if profile is None or not profile.class_group_id:
        return None
    statuses = [DiagnosticAdministration.Status.PUBLISHED]
    if include_closed:
        statuses.append(DiagnosticAdministration.Status.CLOSED)
    return (
        DiagnosticAdministrationAssignment.objects.select_related(
            "class_group",
            "administration",
            "administration__subject",
            "administration__course",
            "administration__paper_version",
            "administration__paper_version__source",
        )
        .filter(
            administration_id=administration_id,
            administration__school_id=student.school_id,
            administration__status__in=statuses,
            class_group_id=profile.class_group_id,
        )
        .first()
    )


def _diagnostic_request_hash(request, payload: dict) -> str:
    file_manifest = []
    for key in request.FILES:
        for item in request.FILES.getlist(key):
            digest = hashlib.sha256()
            for chunk in item.chunks():
                digest.update(chunk)
            item.seek(0)
            file_manifest.append(
                (
                    key,
                    str(item.name),
                    int(item.size),
                    str(getattr(item, "content_type", "") or ""),
                    digest.hexdigest(),
                )
            )
    file_manifest.sort()
    canonical = {
        "paper_version_id": payload.get("paper_version_id"),
        "content_hash": payload.get("content_hash"),
        "answers": payload.get("answers") or {},
        "opportunity_status": payload.get("opportunity_status") or "observed",
        "task_statuses": payload.get("task_statuses") or {},
        "files": file_manifest,
    }
    return hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _diagnostic_idempotency_key(request, payload: dict, request_hash: str) -> str:
    explicit = str(
        request.headers.get("Idempotency-Key")
        or payload.get("idempotency_key")
        or ""
    ).strip()
    return explicit or f"auto:{request_hash}"


def _frozen_diagnostic_targets(
    paper_version: PretestPaperVersion,
    administration: DiagnosticAdministration,
) -> tuple[dict[str, LearningTargetVersion | None], dict[str, list[str]]]:
    rows = [row for row in paper_version.question_snapshot if isinstance(row, dict)]
    target_ids = set()
    for row in rows:
        if bool(row.get("legacy_unmapped", True)):
            continue
        try:
            target_ids.add(int(row.get("learning_target_version_id")))
        except (TypeError, ValueError):
            pass
    versions = {
        item.id: item
        for item in LearningTargetVersion.objects.select_related("target")
        .prefetch_related("curriculum_alignments")
        .filter(pk__in=target_ids)
    }
    resolved: dict[str, LearningTargetVersion | None] = {}
    errors: dict[str, list[str]] = {}
    target_identity_by_code: dict[str, int] = {}
    for index, row in enumerate(rows):
        question_id = str(row.get("id"))
        code = str(row.get("learning_target_code") or "")
        if bool(row.get("legacy_unmapped", True)):
            resolved[question_id] = None
            continue
        try:
            target_id = int(row.get("learning_target_version_id"))
        except (TypeError, ValueError):
            target_id = 0
        version = versions.get(target_id)
        valid = (
            version is not None
            and version.content_hash
            == str(row.get("learning_target_version_hash") or "")
            and version.code == code
            and version.title == str(row.get("learning_target_name") or "")
            and version.alignment_status == "complete"
            and bool(version.curriculum_alignments.all())
            and version.target.school_id == administration.school_id
            and version.target.subject_id == administration.subject_id
            and version.target.course_id == administration.course_id
        )
        if not valid:
            errors.setdefault("paper_version_id", []).append(
                f"第 {index + 1} 项任务的冻结学习目标版本或课标依据校验失败。"
            )
            resolved[question_id] = None
            continue
        previous = target_identity_by_code.setdefault(code, version.id)
        if previous != version.id:
            errors.setdefault("paper_version_id", []).append(
                f"学习目标代码 {code} 在同一发布版本中对应多个目标版本。"
            )
        resolved[question_id] = version
    return resolved, errors


def _diagnostic_submission_result(
    submission: PretestSubmission,
    *,
    administration: DiagnosticAdministration,
    assignment: DiagnosticAdministrationAssignment,
    idempotent_replay: bool,
) -> dict:
    attachments = submission.material_attachments.all()
    binding = DiagnosticSubmissionBinding.objects.filter(submission=submission).first()
    return {
        "id": submission.id,
        "score": submission.score,
        "target_results": submission.target_results,
        "opportunity_status": submission.opportunity_status,
        "paper_version_id": submission.paper_version_id,
        "content_hash": submission.paper_version.content_hash,
        "administration_id": administration.id,
        "administration_content_hash": administration.content_hash,
        "binding_content_hash": binding.content_hash if binding else "",
        "idempotent_replay": idempotent_replay,
        "completion": diagnostic_completion_status(assignment, binding),
        "attachments": [
            {
                "attachment_id": str(item.attachment_id),
                "question_id": item.question_id,
                "original_name": item.original_name,
                "file_size": item.file_size,
                "file_sha256": item.file_sha256,
                "download_url": f"/api/v1/files/pretest-materials/{item.attachment_id}/",
            }
            for item in attachments
        ],
        "submitted_at": submission.submitted_at,
    }


def _diagnostic_idempotency_race_response(
    *,
    administration: DiagnosticAdministration,
    assignment: DiagnosticAdministrationAssignment,
    student,
    idempotency_key: str,
    request_hash: str,
):
    """Resolve a duplicate discovered after a staged submission was rolled back."""

    existing_binding = (
        DiagnosticSubmissionBinding.objects.select_related(
            "submission",
            "submission__paper_version",
        )
        .filter(
            administration=administration,
            student=student,
            idempotency_key=idempotency_key,
        )
        .first()
    )
    if existing_binding is None:
        return None
    if existing_binding.request_hash != request_hash:
        return fail(
            "同一提交标识不能用于不同的诊断材料。",
            errors={"idempotency_key": ["请刷新后使用新的提交标识。"]},
            status=409,
        )
    replay_data = _diagnostic_submission_result(
        existing_binding.submission,
        administration=administration,
        assignment=assignment,
        idempotent_replay=True,
    )
    replay_data["learning_content_recommendation"] = (
        _initial_content_candidate_result(administration, student)
    )
    return ok(
        replay_data,
        "该学习起点诊断材料已经提交，本次返回原记录。",
    )


def _initial_content_candidate_result(administration, student) -> dict:
    if administration.purpose != DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC:
        return {"status": "not_applicable", "message": "该实施用途不形成教学安排建议。"}
    try:
        decision = build_initial_diagnostic_content_band_candidate(
            administration=administration,
            student=student,
        )
    except ValidationError as exc:
        return {
            "status": "not_suggested",
            "message": "当前材料或课程策略不足，暂不形成学习内容层级建议。",
            "reason": "; ".join(exc.messages),
        }
    return {
        "status": "pending_teacher_review" if decision.suggested_layer else "not_suggested",
        "message": (
            "已形成待教师查看的学习内容建议。"
            if decision.suggested_layer
            else "当前材料不足，暂不形成学习内容层级建议。"
        ),
        "decision_id": decision.id,
    }


def _pretest_submission_payload(request) -> dict:
    if not request.FILES:
        return request.data
    raw = request.data.get("payload")
    if not isinstance(raw, str):
        raise ValueError("multipart 请求缺少 payload。")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("payload 必须是对象。")
    return parsed


def _attachment_signature_is_valid(file_ext: str, data: bytes) -> bool:
    if file_ext == "pdf":
        return data.startswith(b"%PDF-")
    if file_ext == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if file_ext in {"jpg", "jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if file_ext == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if file_ext in {"txt", "csv"}:
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        return True
    if file_ext in {"docx", "xlsx", "pptx"}:
        expected_prefix = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}[file_ext]
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = set(archive.namelist())
                return "[Content_Types].xml" in names and any(
                    name.startswith(expected_prefix) for name in names
                )
        except (OSError, zipfile.BadZipFile):
            return False
    return False


def _prepare_pretest_attachments(request, snapshot_by_id: dict[str, dict]):
    prepared: dict[str, list[dict]] = {}
    errors: dict[str, list[str]] = {}
    if not request.FILES:
        return prepared, errors
    max_files = min(
        max(int(getattr(settings, "PRETEST_MATERIAL_MAX_FILES_PER_TASK", 3)), 1),
        5,
    )
    max_file_bytes = min(
        max(int(getattr(settings, "PRETEST_MATERIAL_MAX_FILE_MB", 8)), 1),
        25,
    ) * 1024 * 1024
    max_total_bytes = min(
        max(int(getattr(settings, "PRETEST_MATERIAL_MAX_TOTAL_MB", 16)), 1),
        50,
    ) * 1024 * 1024
    max_total_files = min(
        max(int(getattr(settings, "PRETEST_MATERIAL_MAX_TOTAL_FILES", 12)), 1),
        20,
    )
    total_file_count = sum(len(request.FILES.getlist(key)) for key in request.FILES.keys())
    if total_file_count > max_total_files:
        return {}, {
            "attachments": [f"本次提交最多包含 {max_total_files} 个附件。"]
        }
    total_bytes = 0
    for key in request.FILES.keys():
        match = re.fullmatch(r"attachment_(\d+)", str(key))
        if not match:
            errors.setdefault("attachments", []).append("附件字段格式不正确。")
            continue
        question_id = match.group(1)
        question = snapshot_by_id.get(question_id)
        if question is None:
            errors.setdefault("attachments", []).append(
                f"附件关联了当前发布版本中不存在的任务：{question_id}。"
            )
            continue
        if str(question.get("question_type") or "") not in PRETEST_ATTACHMENT_QUESTION_TYPES:
            errors.setdefault(question_id, []).append("该类评价任务不接收作品附件。")
            continue
        uploads = request.FILES.getlist(key)
        if len(uploads) > max_files:
            errors.setdefault(question_id, []).append(f"每项任务最多上传 {max_files} 个附件。")
            continue
        seen_hashes: set[str] = set()
        for uploaded in uploads:
            original_name = Path(str(getattr(uploaded, "name", "") or "attachment")).name[:255]
            file_ext = Path(original_name).suffix.lower().lstrip(".")
            if file_ext not in PRETEST_ATTACHMENT_EXTENSIONS:
                errors.setdefault(question_id, []).append(
                    f"不支持附件 {original_name} 的格式。"
                )
                continue
            file_size = int(getattr(uploaded, "size", 0) or 0)
            if file_size <= 0:
                errors.setdefault(question_id, []).append(f"附件 {original_name} 为空。")
                continue
            if file_size > max_file_bytes:
                errors.setdefault(question_id, []).append(
                    f"附件 {original_name} 超过单个文件大小限制。"
                )
                continue
            total_bytes += file_size
            if total_bytes > max_total_bytes:
                errors.setdefault("attachments", []).append("本次提交的附件总大小超过限制。")
                continue
            content_type = str(getattr(uploaded, "content_type", "") or "").lower()
            allowed_mimes = PRETEST_ATTACHMENT_MIME_TYPES[file_ext]
            if content_type and content_type not in allowed_mimes and content_type != "application/octet-stream":
                errors.setdefault(question_id, []).append(
                    f"附件 {original_name} 的文件类型与扩展名不一致。"
                )
                continue
            data = uploaded.read()
            if len(data) != file_size or not _attachment_signature_is_valid(file_ext, data):
                errors.setdefault(question_id, []).append(
                    f"附件 {original_name} 的内容格式无法确认。"
                )
                continue
            file_sha256 = hashlib.sha256(data).hexdigest()
            if file_sha256 in seen_hashes:
                errors.setdefault(question_id, []).append(
                    f"附件 {original_name} 与本项已选文件重复。"
                )
                continue
            seen_hashes.add(file_sha256)
            attachment_id = uuid4()
            prepared.setdefault(question_id, []).append(
                {
                    "attachment_id": attachment_id,
                    "original_name": original_name,
                    "file_ext": file_ext,
                    "content_type": content_type or sorted(allowed_mimes)[0],
                    "file_size": file_size,
                    "file_sha256": file_sha256,
                    "data": data,
                    "download_url": f"/api/v1/files/pretest-materials/{attachment_id}/",
                }
            )
    return prepared, errors

def _school_pretest_papers(request):
    subject_id = request.GET.get("subject", "").strip()
    kind = request.GET.get("kind", "").strip()
    status = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()
    papers = (
        PretestPaper.objects.filter(school=_school(request))
        .select_related("subject")
        .annotate(
            question_count=Count("questions", distinct=True),
            submission_count=Count("submissions", distinct=True),
        )
    )
    if subject_id:
        papers = papers.filter(subject_id=subject_id)
    if kind:
        papers = papers.filter(kind=kind)
    if status:
        papers = papers.filter(status=status)
    if query:
        papers = papers.filter(
            Q(title__icontains=query)
            | Q(subject__name__icontains=query)
            | Q(subject__code__icontains=query)
        )
    return papers.order_by("subject__name", "kind", "-version", "-created_at")


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_learning_target_versions(request):
    """List exact, curriculum-aligned target versions available to diagnostics."""

    rows = (
        LearningTargetVersion.objects.filter(
            target__school=_school(request),
            alignment_status="complete",
            curriculum_alignments__isnull=False,
        )
        .select_related(
            "target",
            "target__subject",
            "target__course",
            "plan_version",
        )
        .distinct()
    )
    subject_id = str(request.query_params.get("subject") or "").strip()
    course_id = str(request.query_params.get("course") or "").strip()
    if subject_id:
        rows = rows.filter(target__subject_id=subject_id)
    if course_id:
        rows = rows.filter(target__course_id=course_id)
    rows = rows.order_by(
        "target__subject__name",
        "target__course__title",
        "code",
        "-version_no",
        "-id",
    )
    return ok(
        [
            {
                "id": item.id,
                "logical_key": str(item.target.logical_key),
                "version_no": item.version_no,
                "code": item.code,
                "title": item.title,
                "description": item.description,
                "content_hash": item.content_hash,
                "alignment_status": item.alignment_status,
                "subject": {
                    "id": item.target.subject_id,
                    "name": item.target.subject.name,
                    "code": item.target.subject.code,
                },
                "course": {
                    "id": item.target.course_id,
                    "title": item.target.course.title,
                },
                "plan_version_id": item.plan_version_id,
                "published_at": item.published_at,
            }
            for item in rows
        ]
    )


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_papers(request):
    if request.method == "POST":
        try:
            paper = save_pretest_paper(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        paper.question_count = 0
        paper.submission_count = 0
        return ok(pretest_paper_row(paper), "学习起点诊断版本已创建", status=201)

    page = _paginate(request, _school_pretest_papers(request))
    page.object_list = [pretest_paper_row(paper) for paper in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_paper_detail(request, pk):
    paper = (
        PretestPaper.objects.filter(pk=pk, school=_school(request))
        .select_related("subject")
        .prefetch_related("questions")
        .annotate(
            question_count=Count("questions", distinct=True),
            submission_count=Count("submissions", distinct=True),
        )
        .first()
    )
    if paper is None:
        return fail("学习起点诊断版本不存在。", status=404)

    if request.method == "GET":
        return ok(pretest_paper_row(paper, include_questions=True))
    if request.method == "PATCH":
        try:
            paper = save_pretest_paper(request, request.data, paper=paper)
        except ServiceError as exc:
            return _service_fail(exc)
        paper.question_count = paper.questions.count()
        paper.submission_count = paper.submissions.count()
        return ok(pretest_paper_row(paper), "学习起点诊断版本已更新")

    try:
        delete_pretest_paper(request, paper)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "学习起点诊断版本已删除")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_paper_publish(request, pk):
    paper = (
        PretestPaper.objects.filter(pk=pk, school=_school(request))
        .select_related("subject")
        .first()
    )
    if paper is None:
        return fail("学习起点诊断版本不存在。", status=404)
    try:
        paper = publish_pretest_paper(request, paper)
    except ServiceError as exc:
        return _service_fail(exc)
    paper.question_count = paper.questions.count()
    paper.submission_count = paper.submissions.count()
    return ok(pretest_paper_row(paper), "学习起点诊断版本已发布")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_paper_archive(request, pk):
    paper = (
        PretestPaper.objects.filter(pk=pk, school=_school(request))
        .select_related("subject")
        .first()
    )
    if paper is None:
        return fail("学习起点诊断版本不存在。", status=404)
    paper = archive_pretest_paper(request, paper)
    paper.question_count = paper.questions.count()
    paper.submission_count = paper.submissions.count()
    return ok(pretest_paper_row(paper), "学习起点诊断版本已归档")


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_questions(request, paper_id):
    paper = (
        PretestPaper.objects.filter(pk=paper_id, school=_school(request))
        .select_related("subject")
        .first()
    )
    if paper is None:
        return fail("学习起点诊断版本不存在。", status=404)
    if request.method == "POST":
        try:
            question = save_pretest_question(request, paper, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(pretest_question_row(question), "题目已创建", status=201)

    questions = paper.questions.select_related(
        "learning_target_version",
        "learning_target_version__target",
    ).order_by("sort_order", "id")
    return ok([pretest_question_row(question) for question in questions])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_question_detail(request, paper_id, pk):
    question = (
        PretestQuestion.objects.filter(
            pk=pk, paper_id=paper_id, paper__school=_school(request)
        )
        .select_related("paper", "paper__subject")
        .first()
    )
    if question is None:
        return fail("题目不存在。", status=404)

    if request.method == "PATCH":
        try:
            question = save_pretest_question(
                request, question.paper, request.data, question=question
            )
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(pretest_question_row(question), "题目已更新")

    try:
        delete_pretest_question(request, question)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "题目已删除")


def _reviewable_pretest_materials(request):
    rows = UnifiedAssessmentMaterial.objects.filter(
        school=request.user.school,
        source_type__in=DIAGNOSTIC_SOURCE_TYPES,
        material_status=UnifiedAssessmentMaterial.MaterialStatus.PENDING_REVIEW,
    ).select_related(
        "student",
        "class_group",
        "subject",
        "course",
        "learning_target_version",
        "learning_target_version__target",
    ).prefetch_related("attachments")
    if request.user.role == "teacher":
        # A same-subject class is not sufficient authority to inspect or score
        # a student's diagnostic material.  The material must belong to the
        # teacher's exact course, that course must currently include the class,
        # and the teacher must still hold an explicit class assignment.
        rows = rows.filter(
            course__isnull=False,
            class_group__isnull=False,
            course__teacher=request.user,
            course__course_classes__class_group_id=F("class_group_id"),
            class_group__teaching_assignments__school=request.user.school,
            class_group__teaching_assignments__teacher=request.user,
        ).distinct()
    return rows


def _pretest_material_review_row(material: UnifiedAssessmentMaterial) -> dict:
    content = material.content if isinstance(material.content, dict) else {}
    attachments = [
        {
            "attachment_id": str(item.attachment_id),
            "original_name": item.original_name,
            "file_ext": item.file_ext,
            "content_type": item.content_type,
            "file_size": item.file_size,
            "file_sha256": item.file_sha256,
            "download_url": f"/api/v1/files/pretest-materials/{item.attachment_id}/",
        }
        for item in material.attachments.all()
    ]
    return {
        "material_id": str(material.material_id),
        "student": {
            "id": material.student_id,
            "username": material.student.username if material.student_id else "",
            "display_name": (
                material.student.display_name or material.student.username
                if material.student_id
                else ""
            ),
        },
        "class_group": (
            {
                "id": material.class_group_id,
                "name": material.class_group.name,
                "grade": material.class_group.grade,
            }
            if material.class_group_id
            else None
        ),
        "subject": {"id": material.subject_id, "name": material.subject.name},
        "learning_target_code": material.learning_target_code,
        "learning_target_version": (
            {
                "id": material.learning_target_version_id,
                "content_hash": material.learning_target_version.content_hash,
                "logical_key": str(material.learning_target_version.target.logical_key),
            }
            if material.learning_target_version_id
            else None
        ),
        "legacy_unmapped": material.legacy_unmapped,
        "material_type": material.material_type,
        "material_type_label": material.get_material_type_display(),
        "material_status": material.material_status,
        "material_status_label": material.get_material_status_display(),
        "question_id": str(content.get("question_id") or ""),
        "question_type": str(content.get("question_type") or ""),
        "answer": content.get("answer"),
        "process_explanation": content.get("process_explanation"),
        "attachments": attachments,
        "material_requirements": content.get("material_requirements") or [],
        "score_max": material.score_max,
        "recorded_at": material.recorded_at,
    }


def _diagnostic_review_provenance(
    material: UnifiedAssessmentMaterial,
) -> tuple[DiagnosticAdministration, DiagnosticSubmissionBinding, dict]:
    """Resolve and verify the immutable administration behind a raw material.

    A review is an appended assessment record, not a new measurement context.
    Therefore it must inherit the exact administration, paper version, course and
    learning-target identity frozen by the student's original submission.
    """

    content = material.content if isinstance(material.content, dict) else {}
    errors: list[str] = []
    try:
        administration_id = int(content.get("administration_id"))
    except (TypeError, ValueError):
        administration_id = 0
        errors.append("原始材料缺少诊断实施批次标识。")
    administration_hash = str(content.get("administration_content_hash") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", administration_hash):
        errors.append("原始材料缺少有效的诊断实施批次摘要。")
    try:
        submission_id = int(material.source_id)
    except (TypeError, ValueError):
        submission_id = 0
        errors.append("原始材料未绑定有效的诊断提交记录。")

    administration = (
        DiagnosticAdministration.objects.select_for_update()
        .select_related("paper_version", "paper_version__source", "course")
        .filter(pk=administration_id, school=material.school)
        .first()
    )
    if administration is None:
        errors.append("原始材料对应的诊断实施批次不存在或超出当前学校范围。")
    elif administration.content_hash != administration_hash:
        errors.append("原始材料中的实施批次摘要与不可变批次记录不一致。")

    binding = None
    if administration is not None and submission_id:
        binding = (
            DiagnosticSubmissionBinding.objects.select_related(
                "submission",
                "submission__paper_version",
                "assignment",
            )
            .filter(
                administration=administration,
                submission_id=submission_id,
                student=material.student,
            )
            .first()
        )
    if binding is None:
        errors.append("原始材料缺少与实施批次一致的不可变提交绑定。")

    if administration is not None:
        expected_source_type = DIAGNOSTIC_SOURCE_BY_PURPOSE.get(administration.purpose)
        if material.source_type != expected_source_type:
            errors.append("原始材料用途与诊断实施批次用途不一致。")
        if material.subject_id != administration.subject_id:
            errors.append("原始材料学科与诊断实施批次不一致。")
        if material.course_id != administration.course_id:
            errors.append("原始材料课程与诊断实施批次冻结课程不一致。")
        if str(content.get("paper_content_hash") or "") != administration.paper_version.content_hash:
            errors.append("原始材料中的诊断工具摘要与实施批次冻结版本不一致。")
        try:
            content_paper_version_id = int(content.get("paper_version_id"))
        except (TypeError, ValueError):
            content_paper_version_id = 0
        if content_paper_version_id != administration.paper_version_id:
            errors.append("原始材料中的诊断工具版本与实施批次冻结版本不一致。")

    content_legacy = bool(content.get("legacy_unmapped", True))
    if content_legacy != material.legacy_unmapped:
        errors.append("原始材料的学习目标映射状态与冻结内容不一致。")
    if material.learning_target_version_id:
        try:
            content_target_id = int(content.get("learning_target_version_id"))
        except (TypeError, ValueError):
            content_target_id = 0
        if content_target_id != material.learning_target_version_id:
            errors.append("原始材料中的学习目标版本身份不一致。")
        if (
            str(content.get("learning_target_version_hash") or "")
            != material.learning_target_version.content_hash
        ):
            errors.append("原始材料中的学习目标版本摘要不一致。")
        if (
            str(content.get("learning_target_logical_key") or "")
            != str(material.learning_target_version.target.logical_key)
        ):
            errors.append("原始材料中的学习目标逻辑身份不一致。")
    elif not material.legacy_unmapped:
        errors.append("正式评价材料未绑定不可变学习目标版本。")

    if errors:
        raise ValidationError(errors)
    return administration, binding, content


@api_view(["GET"])
@permission_classes([IsTeacher | IsSchoolAdmin])
def pretest_materials_pending_review(request):
    rows = _reviewable_pretest_materials(request)
    if request.query_params.get("subject"):
        rows = rows.filter(subject_id=request.query_params["subject"])
    if request.query_params.get("class_group"):
        rows = rows.filter(class_group_id=request.query_params["class_group"])
    reviewed_source_ids = set(
        UnifiedAssessmentMaterial.objects.filter(
            school=request.user.school,
            source_type__in=DIAGNOSTIC_REVIEW_SOURCE_TYPES,
            source_id__in=[str(item) for item in rows.values_list("material_id", flat=True)],
        ).values_list("source_id", flat=True)
    )
    rows = [row for row in rows.order_by("recorded_at", "id") if str(row.material_id) not in reviewed_source_ids]
    return ok([_pretest_material_review_row(row) for row in rows])


@api_view(["POST"])
@permission_classes([IsTeacher | IsSchoolAdmin])
@transaction.atomic
def review_pretest_material(request, material_id):
    material = (
        _reviewable_pretest_materials(request)
        .select_for_update()
        .filter(material_id=material_id)
        .first()
    )
    if material is None:
        return fail("待评价材料不存在或无权处理。", status=404)
    try:
        administration, binding, _source_content = _diagnostic_review_provenance(material)
    except ValidationError as exc:
        return fail(
            "原始评价材料的实施批次追溯信息校验失败，未写入评分。",
            errors={"material": exc.messages},
            status=409,
        )
    review_source_type = DIAGNOSTIC_REVIEW_SOURCE_BY_SOURCE[material.source_type]
    if UnifiedAssessmentMaterial.objects.filter(
        school=request.user.school,
        source_type=review_source_type,
        source_id=str(material.material_id),
    ).exists():
        return fail("该材料已经完成评价，请刷新列表。", status=409)
    try:
        score_max = float(material.score_max or 0)
        score = float(request.data.get("score"))
    except (TypeError, ValueError):
        return fail(
            "评分信息不正确。",
            errors={"score": ["请输入有效得分。"]},
            status=400,
        )
    requested_score_max = request.data.get("score_max")
    if requested_score_max not in (None, ""):
        try:
            if abs(float(requested_score_max) - score_max) > 1e-9:
                return fail(
                    "评价任务满分已随发布版本固定，请刷新后重试。",
                    errors={"score_max": ["不能修改已发布评价任务的满分。"]},
                    status=409,
                )
        except (TypeError, ValueError):
            return fail(
                "评分信息不正确。",
                errors={"score_max": ["评价任务满分格式不正确。"]},
                status=400,
            )
    if score_max <= 0 or score < 0 or score > score_max:
        return fail(
            "评分信息不正确。",
            errors={"score": ["得分必须位于 0 与满分之间。"]},
            status=400,
        )
    feedback = str(request.data.get("feedback") or "").strip()[:2000]
    if not math.isfinite(score) or not math.isfinite(score_max):
        return fail(
            "评分信息不正确。",
            errors={"score": ["得分与满分必须是有限数字。"]},
            status=400,
        )
    source_materials = list(
        UnifiedAssessmentMaterial.objects.filter(
            school=material.school,
            student=material.student,
            subject=material.subject,
            course=material.course,
            source_type=material.source_type,
            source_id=material.source_id,
            learning_target_version=material.learning_target_version,
            legacy_unmapped=material.legacy_unmapped,
            learning_target_code=material.learning_target_code,
        ).order_by("id")
    )
    provenance_errors = []
    for source in source_materials:
        content = source.content if isinstance(source.content, dict) else {}
        if (
            str(content.get("administration_id") or "") != str(administration.id)
            or str(content.get("administration_content_hash") or "")
            != administration.content_hash
            or str(content.get("paper_version_id") or "")
            != str(administration.paper_version_id)
            or str(content.get("paper_content_hash") or "")
            != administration.paper_version.content_hash
        ):
            provenance_errors.append(str(source.material_id))
    if provenance_errors:
        return fail(
            "同一学习目标下存在实施批次追溯信息不一致的材料，未写入评分。",
            errors={"material": [f"材料 {item} 的冻结信息不一致。" for item in provenance_errors]},
            status=409,
        )

    review_source_version = f"{administration.content_hash}:review:{material.id}"
    review_content = {
        "source_material_id": str(material.material_id),
        "source_material_content_hash": material.content_hash,
        "source_submission_id": material.source_id,
        "feedback": feedback,
        "reviewed_by": request.user.id,
        "reviewed_by_name": request.user.display_name or request.user.username,
        "administration_id": administration.id,
        "administration_content_hash": administration.content_hash,
        "batch_code": administration.batch_code,
        "purpose": administration.purpose,
        "paper_version_id": administration.paper_version_id,
        "paper_content_hash": administration.paper_version.content_hash,
        "submission_binding_id": binding.id,
        "submission_binding_content_hash": binding.content_hash,
        "learning_target_version_id": material.learning_target_version_id,
        "learning_target_version_hash": (
            material.learning_target_version.content_hash
            if material.learning_target_version_id
            else ""
        ),
        "learning_target_logical_key": (
            str(material.learning_target_version.target.logical_key)
            if material.learning_target_version_id
            else ""
        ),
        "legacy_unmapped": material.legacy_unmapped,
        "uncertainty_method": DIAGNOSTIC_UNCERTAINTY_METHOD,
    }
    try:
        with transaction.atomic():
            score_material = UnifiedAssessmentMaterial.objects.create(
                school=material.school,
                subject=material.subject,
                course=material.course,
                class_group=material.class_group,
                student=material.student,
                recorded_by=request.user,
                learning_target_version=material.learning_target_version,
                legacy_unmapped=material.legacy_unmapped,
                ownership=material.ownership,
                group_reference=material.group_reference,
                material_type=UnifiedAssessmentMaterial.MaterialType.SCORE,
                material_status=UnifiedAssessmentMaterial.MaterialStatus.AVAILABLE,
                learning_target_code=material.learning_target_code,
                source_type=review_source_type,
                source_id=str(material.material_id),
                source_version=review_source_version,
                content=review_content,
                score=score,
                score_max=score_max,
                recorded_at=timezone.now(),
            )
    except IntegrityError:
        return fail("该材料已经完成评价，请刷新列表。", status=409)

    source_ids = [str(item.material_id) for item in source_materials]
    score_materials = {
        item.source_id: item
        for item in UnifiedAssessmentMaterial.objects.filter(
            school=material.school,
            source_type=review_source_type,
            source_id__in=source_ids,
        ).order_by("id")
    }
    available_count = 0
    pending_count = 0
    score_total = 0.0
    score_max_total = 0.0
    material_references: list[str] = []
    for source in source_materials:
        source_id = str(source.material_id)
        material_references.append(source_id)
        effective = score_materials.get(source_id)
        if effective:
            material_references.append(str(effective.material_id))
            available_count += 1
            score_total += float(effective.score or 0)
            score_max_total += float(effective.score_max or 0)
        elif source.material_status == UnifiedAssessmentMaterial.MaterialStatus.AVAILABLE:
            available_count += 1
            if source.score is not None and source.score_max:
                score_total += float(source.score)
                score_max_total += float(source.score_max)
        elif source.material_status == UnifiedAssessmentMaterial.MaterialStatus.PENDING_REVIEW:
            pending_count += 1
    task_count = len(source_materials)
    coverage = available_count / task_count if task_count else 0
    if pending_count:
        evidence_status = StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW
    elif available_count and available_count < task_count:
        evidence_status = StudentLearningTargetStateVersion.EvidenceStatus.PARTIAL
    elif available_count:
        evidence_status = StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE
    else:
        evidence_status = StudentLearningTargetStateVersion.EvidenceStatus.NOT_OBSERVED
    estimate = (
        round(score_total / score_max_total, 6)
        if score_max_total and not pending_count and not material.legacy_unmapped
        else None
    )
    if material.legacy_unmapped:
        evidence_status = StudentLearningTargetStateVersion.EvidenceStatus.INSUFFICIENT
    uncertainty, coverage = _diagnostic_target_uncertainty(
        evidence_status=evidence_status,
        observed_task_count=available_count,
        task_count=task_count,
    )
    previous_state_scope = StudentLearningTargetStateVersion.objects.filter(
            student=material.student,
            school=material.school,
            subject=material.subject,
            course=material.course,
            learning_target_code=material.learning_target_code,
        )
    if material.learning_target_version_id:
        previous_state_scope = previous_state_scope.filter(
            learning_target_version=material.learning_target_version,
            legacy_unmapped=False,
        )
    else:
        previous_state_scope = previous_state_scope.filter(
            learning_target_version__isnull=True,
            legacy_unmapped=True,
        )
    previous_state = previous_state_scope.order_by("-observed_at", "-id").first()
    validity_policy = _pretest_validity_policy(score_material.recorded_at)
    observation_notes = [feedback] if feedback else []
    observation_notes.append(
        f"有效期策略：{validity_policy['code']}={validity_policy['days']}天"
    )
    observation_notes.append(
        "不确定性估计："
        f"method={DIAGNOSTIC_UNCERTAINTY_METHOD};"
        f"observed_task_count={available_count};"
        f"task_count={task_count};coverage={coverage:.6f}"
    )
    state = StudentLearningTargetStateVersion.objects.create(
        student=material.student,
        school=material.school,
        class_group=material.class_group,
        subject=material.subject,
        course=material.course,
        learning_target_version=material.learning_target_version,
        legacy_unmapped=material.legacy_unmapped,
        learning_target_code=material.learning_target_code,
        learning_target_name=(
            material.learning_target_version.title
            if material.learning_target_version_id
            else previous_state.learning_target_name
            if previous_state
            else material.learning_target_code
        ),
        source_type=review_source_type,
        source_id=material.source_id,
        source_version=f"{administration.content_hash}:review:{score_material.id}",
        evidence_status=evidence_status,
        evidence_coverage=round(coverage, 6),
        estimate=estimate,
        uncertainty=uncertainty,
        material_references=material_references,
        observation_notes=observation_notes,
        is_initial_diagnostic=(material.source_type == "learning_entry_diagnostic"),
        observed_at=score_material.recorded_at,
        valid_from=score_material.recorded_at,
        valid_until=validity_policy["valid_until"],
    )
    content_candidate_result = _initial_content_candidate_result(
        administration,
        material.student,
    )
    write_audit(
        request,
        "pretest_material.review",
        school=request.user.school,
        target_type="unified_assessment_material",
        target_id=score_material.id,
        detail={
            "source_material_id": str(material.material_id),
            "student_id": material.student_id,
            "learning_target_code": material.learning_target_code,
            "score": score,
            "score_max": score_max,
            "administration_id": administration.id,
            "administration_content_hash": administration.content_hash,
        },
    )
    return ok(
        {
            "score_material_id": str(score_material.material_id),
            "target_state_id": state.id,
            "evidence_status": state.evidence_status,
            "evidence_coverage": state.evidence_coverage,
            "estimate": state.estimate,
            "administration_id": administration.id,
            "administration_content_hash": administration.content_hash,
            "learning_content_recommendation": content_candidate_result,
        },
        "评价材料已评分，并生成新的学习目标情况版本。",
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_pretests_required(request):
    subjects = Subject.objects.filter(
        school=request.user.school, is_active=True
    ).order_by("name")
    return ok(
        [
            {
                "subject": subject_row(subject),
                "pretest_status": _student_required_pretest_status(
                    request.user, subject
                ),
            }
            for subject in subjects
        ]
    )

@api_view(["GET"])
@permission_classes([IsStudent])
def student_pretests_for_subject(request, subject_id):
    subject = Subject.objects.filter(
        id=subject_id, school=request.user.school, is_active=True
    ).first()
    if subject is None:
        return fail("学科不存在或已停用。", status=404)
    profile = StudentProfile.objects.filter(user=request.user).first()
    assignments = []
    if profile and profile.class_group_id:
        assignments = list(
            DiagnosticAdministrationAssignment.objects.filter(
                class_group_id=profile.class_group_id,
                administration__school=request.user.school,
                administration__subject=subject,
                administration__status__in=[
                    DiagnosticAdministration.Status.PUBLISHED,
                    DiagnosticAdministration.Status.CLOSED,
                ],
            )
            .select_related(
                "administration",
                "administration__paper_version",
                "administration__paper_version__source",
                "administration__subject",
                "administration__course",
            )
            .order_by("-administration__published_at", "-administration_id")
        )
    binding_by_administration = {}
    for item in (
        DiagnosticSubmissionBinding.objects.filter(
            student=request.user,
            administration_id__in=[row.administration_id for row in assignments],
        )
        .select_related("submission")
        .order_by("administration_id", "-attempt_no")
    ):
        binding_by_administration.setdefault(item.administration_id, item)
    papers = []
    for assignment in assignments:
        administration = assignment.administration
        version = administration.paper_version
        paper = version.source
        binding = binding_by_administration.get(administration.id)
        state = availability_status(administration)
        if state != "open":
            papers.append(
                _student_diagnostic_availability_row(
                    administration,
                    assignment,
                    binding,
                )
            )
            continue
        row = pretest_paper_row(paper)
        row.update(
            {
                "administration_id": administration.id,
                "batch_code": administration.batch_code,
                "purpose": administration.purpose,
                "purpose_label": administration.get_purpose_display(),
                "opportunity_status": assignment.opportunity_status,
                "availability_status": state,
                "open_at": administration.open_at,
                "close_at": administration.close_at,
                "submission_allowed": (
                    assignment.opportunity_status
                    == DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED
                ),
                "version": version.version_no,
                "question_count": len(version.question_snapshot),
                "published_version": {
                    "id": version.id,
                    "version_no": version.version_no,
                    "content_hash": version.content_hash,
                },
                "completion": diagnostic_completion_status(
                    assignment,
                    binding,
                ),
            }
        )
        papers.append(row)
    return ok(
        {
            "subject": subject_row(subject),
            "pretest_status": _student_required_pretest_status(request.user, subject),
            "papers": papers,
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsStudent])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@transaction.atomic
def student_pretest_paper(request, paper_id=None, administration_id=None):
    payload = None
    idempotency_key = ""
    request_hash = ""
    if request.method == "POST":
        try:
            payload = _pretest_submission_payload(request)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fail(
                "学习起点诊断提交格式不正确。",
                errors={"payload": ["请提交有效的诊断材料数据。"]},
                status=400,
            )
        request_hash = _diagnostic_request_hash(request, payload)
        idempotency_key = _diagnostic_idempotency_key(
            request,
            payload,
            request_hash,
        )

    if administration_id is None:
        # Compatibility URLs still require an explicit class assignment. They no
        # longer select the globally latest school/subject paper version.
        profile = StudentProfile.objects.filter(user=request.user).first()
        candidates = []
        if profile and profile.class_group_id:
            candidates = list(
                DiagnosticAdministrationAssignment.objects.filter(
                    class_group_id=profile.class_group_id,
                    administration__school=request.user.school,
                    administration__paper_version__source_id=paper_id,
                    administration__status__in=[
                        DiagnosticAdministration.Status.PUBLISHED,
                        DiagnosticAdministration.Status.CLOSED,
                    ],
                ).values_list("administration_id", flat=True)[:2]
            )
        if not candidates:
            return fail(
                "该学习起点诊断尚未通过实施批次指派给当前班级。", status=404
            )
        if len(candidates) > 1:
            return fail(
                "该诊断工具存在多个实施批次，请从具体批次进入。", status=409
            )
        administration_id = candidates[0]

    assignment = _student_diagnostic_assignment(
        request.user,
        administration_id,
        include_closed=True,
    )
    if assignment is None:
        return fail("诊断实施批次不存在或未指派给当前班级。", status=404)
    administration = assignment.administration
    paper_version = administration.paper_version
    paper = paper_version.source
    if request.method == "GET":
        binding = (
            DiagnosticSubmissionBinding.objects.filter(
                administration=administration,
                student=request.user,
            )
            .select_related("submission")
            .order_by("-attempt_no")
            .first()
        )
        if availability_status(administration) != "open":
            return ok(
                _student_diagnostic_availability_row(
                    administration,
                    assignment,
                    binding,
                )
            )
        row = _student_pretest_version_row(
            paper,
            paper_version,
            assignment=assignment,
        )
        row["completion"] = diagnostic_completion_status(assignment, binding)
        row["submission_allowed"] = (
            administration.status == DiagnosticAdministration.Status.PUBLISHED
            and assignment.opportunity_status
            == DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED
            and (not administration.open_at or timezone.now() >= administration.open_at)
            and (not administration.close_at or timezone.now() < administration.close_at)
        )
        return ok(row)

    try:
        diagnostic_context = prepare_student_diagnostic_submission(
            administration_id=administration.id,
            student=request.user,
            idempotency_key=idempotency_key,
        )
    except DiagnosticAdministrationError as exc:
        return fail(exc.message, errors=exc.errors, status=exc.status)
    assignment = diagnostic_context.assignment
    administration = diagnostic_context.administration
    paper_version = administration.paper_version
    paper = paper_version.source
    if diagnostic_context.existing_binding is not None:
        existing_submission = diagnostic_context.existing_binding.submission
        if diagnostic_context.existing_binding.request_hash != request_hash:
            return fail(
                "同一提交标识不能用于不同的诊断材料。",
                errors={"idempotency_key": ["请刷新后使用新的提交标识。"]},
                status=409,
            )
        replay_result = _diagnostic_submission_result(
            existing_submission,
            administration=administration,
            assignment=assignment,
            idempotent_replay=True,
        )
        replay_result["learning_content_recommendation"] = (
            _initial_content_candidate_result(administration, request.user)
        )
        return ok(
            replay_result,
            "该学习起点诊断材料已经提交，本次返回原记录。",
        )
    try:
        requested_version_id = int(payload.get("paper_version_id"))
    except (TypeError, ValueError):
        requested_version_id = 0
    requested_content_hash = str(payload.get("content_hash") or "").strip().lower()
    version_errors: dict[str, list[str]] = {}
    if not requested_version_id:
        version_errors["paper_version_id"] = ["提交时必须携带所见诊断版本。"]
    if not requested_content_hash:
        version_errors["content_hash"] = ["提交时必须携带所见内容校验值。"]
    if version_errors:
        return fail("缺少学习起点诊断版本信息。", errors=version_errors, status=400)
    if (
        requested_version_id != paper_version.id
        or requested_content_hash != paper_version.content_hash
    ):
        return fail(
            "学习起点诊断内容已经更新，请刷新后重新确认作答。",
            errors={
                "paper_version_id": ["提交版本与当前发布版本不一致。"],
                "content_hash": ["提交内容校验值与当前发布版本不一致。"],
            },
            status=409,
        )
    frozen_targets, frozen_target_errors = _frozen_diagnostic_targets(
        paper_version,
        administration,
    )
    if frozen_target_errors:
        return fail(
            "该诊断实施批次的冻结学习目标链校验失败，请联系学校管理员。",
            errors=frozen_target_errors,
            status=409,
        )
    diagnostic_source_type = DIAGNOSTIC_SOURCE_BY_PURPOSE[administration.purpose]
    is_initial_diagnostic = (
        administration.purpose == DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC
    )

    opportunity_status = str(
        payload.get("opportunity_status")
        or PretestSubmission.OpportunityStatus.OBSERVED
    ).strip()
    if opportunity_status == PretestSubmission.OpportunityStatus.NOT_OFFERED:
        return fail(
            "“未获得评价机会”必须由教师或诊断实施记录确认，学生端不能自行设置。",
            errors={"opportunity_status": ["请选择实际遇到的材料缺失或设备问题。"]},
            status=400,
        )
    if opportunity_status not in PretestSubmission.OpportunityStatus.values:
        return fail("学习起点诊断材料状态不正确。", status=400)
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict):
        return fail(
            "请提交诊断作答或评价材料。",
            errors={"answers": ["诊断作答必须是对象。"]},
            status=400,
        )
    raw_task_statuses = payload.get("task_statuses") or {}
    if not isinstance(raw_task_statuses, dict):
        return fail(
            "评价任务材料状态格式不正确。",
            errors={"task_statuses": ["评价任务材料状态必须是对象。"]},
            status=400,
        )
    if any(
        str(value).strip() == PretestSubmission.OpportunityStatus.NOT_OFFERED
        for value in raw_task_statuses.values()
    ):
        return fail(
            "“未获得评价机会”必须由教师或诊断实施记录确认，学生端不能自行设置。",
            errors={"task_statuses": ["学生只能报告材料缺失或设备问题。"]},
            status=400,
        )
    if DiagnosticSubmissionBinding.objects.filter(
        administration=administration,
        student=request.user,
        submission__opportunity_status=PretestSubmission.OpportunityStatus.OBSERVED,
    ).exists():
        return fail("该学习起点诊断已完成，不能另建重复提交。", status=409)

    try:
        profile = _student_profile(request)
    except ServiceError:
        profile = None
    if profile is None:
        return fail("学生档案不存在，学习起点诊断未保存。", status=404)
    if not profile.class_group_id:
        return fail("请先选择班级，再完成学习起点诊断。", status=409)

    errors: dict[str, list[str]] = {}
    # Keep scoring at the task/learning-target level.  The legacy submission
    # total is deliberately left empty so it cannot become an accidental
    # whole-instrument ability score or a direct stratification input.
    target_buckets: dict[str, dict] = {}
    normalized_task_statuses: dict[str, str] = {}
    objective_scores: dict[str, tuple[float, float]] = {}
    objective_types = {
        PretestQuestion.QuestionType.SINGLE,
        PretestQuestion.QuestionType.MULTIPLE,
    }
    snapshot_by_id = {
        str(item.get("id")): item
        for item in paper_version.question_snapshot
        if isinstance(item, dict) and item.get("id") is not None
    }
    unknown_answer_keys = sorted(set(map(str, answers.keys())) - set(snapshot_by_id))
    unknown_status_keys = sorted(set(map(str, raw_task_statuses.keys())) - set(snapshot_by_id))
    if unknown_answer_keys:
        errors["answers"] = [
            f"作答包含当前发布版本中不存在的任务：{', '.join(unknown_answer_keys)}。"
        ]
    if unknown_status_keys:
        errors["task_statuses"] = [
            f"材料状态包含当前发布版本中不存在的任务：{', '.join(unknown_status_keys)}。"
        ]
    prepared_attachments, attachment_errors = _prepare_pretest_attachments(
        request, snapshot_by_id
    )
    for field, messages in attachment_errors.items():
        errors.setdefault(field, []).extend(messages)
    for question in paper_version.question_snapshot:
        if not isinstance(question, dict):
            continue
        key = str(question.get("id"))
        answer = answers.get(key)
        task_attachments = prepared_attachments.get(key, [])
        answer_is_empty = (
            not task_attachments
            and (
                answer is None
                or answer == []
                or (isinstance(answer, str) and not answer.strip())
            )
        )
        task_status = str(
            raw_task_statuses.get(key)
            or opportunity_status
            or PretestSubmission.OpportunityStatus.OBSERVED
        ).strip()
        if opportunity_status != PretestSubmission.OpportunityStatus.OBSERVED:
            task_status = opportunity_status
        if task_status not in PretestSubmission.OpportunityStatus.values:
            errors[key] = ["该评价任务的材料状态不正确。"]
            continue
        if task_status != PretestSubmission.OpportunityStatus.OBSERVED and task_attachments:
            errors.setdefault(key, []).append(
                "本项标记为未形成观察时不能同时提交作品附件。"
            )
            continue
        if task_status == PretestSubmission.OpportunityStatus.OBSERVED and answer_is_empty:
            if question.get("is_required"):
                errors[key] = ["该评价任务需要提交材料。"]
                continue
            # 非必交且没有形成材料时，不把空白作为错误作答计入分母。
            task_status = PretestSubmission.OpportunityStatus.MISSING
        question_type = str(question.get("question_type") or "")
        if task_status == PretestSubmission.OpportunityStatus.OBSERVED:
            if question_type == PretestQuestion.QuestionType.MULTIPLE:
                if not isinstance(answer, list) or not all(
                    isinstance(item, (str, int, float)) for item in answer
                ):
                    errors.setdefault(key, []).append("多选题作答必须是选项值列表。")
                    continue
            elif question_type in {
                PretestQuestion.QuestionType.SINGLE,
                PretestQuestion.QuestionType.SCALE,
            }:
                if isinstance(answer, (dict, list)) or answer is None:
                    errors.setdefault(key, []).append("该题作答必须是一个选项值。")
                    continue
            elif question_type in {
                PretestQuestion.QuestionType.TEXT,
                *PRETEST_ATTACHMENT_QUESTION_TYPES,
            }:
                if answer is not None and not isinstance(answer, str):
                    errors.setdefault(key, []).append("过程说明或简答必须是文本。")
                    continue
            valid_option_values = {
                str(
                    option.get("label")
                    if isinstance(option, dict)
                    else option
                )
                for option in (question.get("options") or [])
            }
            if question_type in {
                PretestQuestion.QuestionType.SINGLE,
                PretestQuestion.QuestionType.SCALE,
            } and valid_option_values and str(answer) not in valid_option_values:
                errors.setdefault(key, []).append("作答选项不属于当前发布版本。")
                continue
            if question_type == PretestQuestion.QuestionType.MULTIPLE and any(
                str(item) not in valid_option_values for item in answer
            ):
                errors.setdefault(key, []).append("多选题作答包含无效选项。")
                continue
        normalized_task_statuses[key] = task_status
        target_version = frozen_targets.get(key)
        legacy_unmapped = target_version is None
        target_code = (
            target_version.code
            if target_version is not None
            else str(question.get("learning_target_code") or f"ENTRY-{key}")
        )
        target_name = (
            target_version.title
            if target_version is not None
            else str(question.get("learning_target_name") or "学习目标")
        )
        target_bucket_key = (
            f"version:{target_version.id}"
            if target_version is not None
            else f"legacy:{target_code}"
        )
        bucket = target_buckets.setdefault(
            target_bucket_key,
            {
                "learning_target_code": target_code,
                "learning_target_name": target_name,
                "learning_target_version_id": (
                    target_version.id if target_version is not None else None
                ),
                "learning_target_version_hash": (
                    target_version.content_hash if target_version is not None else ""
                ),
                "learning_target_logical_key": (
                    str(target_version.target.logical_key)
                    if target_version is not None
                    else ""
                ),
                "legacy_unmapped": legacy_unmapped,
                "score": 0.0,
                "score_max": 0.0,
                "observed_count": 0,
                "pending_review_count": 0,
                "missing_count": 0,
                "task_count": 0,
                "material_statuses": [],
            },
        )
        bucket["task_count"] += 1
        bucket["material_statuses"].append(task_status)
        if task_status != PretestSubmission.OpportunityStatus.OBSERVED:
            bucket["missing_count"] += 1
            continue
        bucket["observed_count"] += 1
        if question_type in objective_types:
            expected = question.get("answer") or []
            actual = answer if isinstance(answer, list) else [answer]
            item_score_max = float(question.get("score") or 0)
            item_score = 0.0
            bucket["score_max"] += item_score_max
            if sorted(map(str, actual)) == sorted(map(str, expected)):
                item_score = item_score_max
                bucket["score"] += item_score
            objective_scores[key] = (item_score, item_score_max)
        elif question_type != PretestQuestion.QuestionType.SCALE:
            bucket["pending_review_count"] += 1
    if errors:
        return fail("学习起点诊断材料校验失败。", errors=errors, status=400)

    target_results = []
    for bucket in target_buckets.values():
        if bucket["pending_review_count"]:
            evidence_status = "pending_review"
            estimate = None
        elif bucket["observed_count"] and bucket["missing_count"]:
            evidence_status = "partial"
            estimate = (
                round(bucket["score"] / bucket["score_max"], 6)
                if bucket["score_max"] > 0
                else None
            )
        elif bucket["observed_count"]:
            evidence_status = "available"
            estimate = (
                round(bucket["score"] / bucket["score_max"], 6)
                if bucket["score_max"] > 0
                else None
            )
        elif bucket["score_max"] > 0:
            evidence_status = "available"
            estimate = round(bucket["score"] / bucket["score_max"], 6)
        else:
            evidence_status = "not_observed"
            estimate = None
        non_observed_reasons = sorted(
            {
                item
                for item in bucket["material_statuses"]
                if item != PretestSubmission.OpportunityStatus.OBSERVED
            }
        )
        if bucket["legacy_unmapped"] and evidence_status in {"available", "partial"}:
            evidence_status = "insufficient"
            estimate = None
            non_observed_reasons.append("legacy_unmapped")
        target_results.append(
            {
                **bucket,
                "evidence_status": evidence_status,
                "estimate": estimate,
                "reason": ",".join(non_observed_reasons),
            }
        )

    observed_task_count = sum(
        int(status == PretestSubmission.OpportunityStatus.OBSERVED)
        for status in normalized_task_statuses.values()
    )
    if observed_task_count:
        submission_opportunity_status = PretestSubmission.OpportunityStatus.OBSERVED
    else:
        non_observed_statuses = set(normalized_task_statuses.values())
        submission_opportunity_status = (
            next(iter(non_observed_statuses))
            if len(non_observed_statuses) == 1
            else PretestSubmission.OpportunityStatus.MISSING
        )
    attempt_no = (
        DiagnosticSubmissionBinding.objects.filter(
            student=request.user,
            administration=administration,
        )
        .aggregate(value=Max("attempt_no"))
        .get("value")
        or 0
    ) + 1

    try:
        with transaction.atomic():
            submission = PretestSubmission.objects.create(
                student=request.user,
                subject=paper.subject,
                paper=paper,
                paper_version=paper_version,
                administration=administration,
                attempt_no=attempt_no,
                idempotency_key=idempotency_key,
                answers=answers,
                score=None,
                opportunity_status=submission_opportunity_status,
                task_statuses=normalized_task_statuses,
                target_results=target_results,
            )
            submission_binding, _ = bind_diagnostic_submission(
                context=diagnostic_context,
                submission=submission,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
    except IntegrityError:
        race_response = _diagnostic_idempotency_race_response(
            administration=administration,
            assignment=assignment,
            student=request.user,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if race_response is not None:
            return race_response
        return fail(
            "同一诊断实施批次出现并发提交，请刷新确认后重试。",
            errors={"idempotency_key": ["未重复写入任何诊断材料。"]},
            status=409,
        )
    except DiagnosticAdministrationError as exc:
        transaction.set_rollback(True)
        return fail(exc.message, errors=exc.errors, status=exc.status)
    except ValidationError as exc:
        race_response = _diagnostic_idempotency_race_response(
            administration=administration,
            assignment=assignment,
            student=request.user,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if race_response is not None:
            return race_response
        transaction.set_rollback(True)
        return fail(
            "诊断提交与冻结实施批次校验失败。",
            errors={"submission": exc.messages},
            status=409,
        )
    # Completion belongs to the immutable administration/submission binding.
    # A single subject diagnostic must not mutate the student's global first-
    # use/onboarding fields or a global pretest-completed timestamp.
    material_refs_by_target: dict[str, list[str]] = {}
    materials_by_question: dict[str, UnifiedAssessmentMaterial] = {}
    validity_policy = _pretest_validity_policy(submission.submitted_at)
    for question in paper_version.question_snapshot:
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id"))
        target_version = frozen_targets.get(question_id)
        legacy_unmapped = target_version is None
        target_code = (
            target_version.code
            if target_version is not None
            else str(question.get("learning_target_code") or f"ENTRY-{question_id}")
        )
        target_bucket_key = (
            f"version:{target_version.id}"
            if target_version is not None
            else f"legacy:{target_code}"
        )
        question_type = str(question.get("question_type") or "")
        task_status = normalized_task_statuses.get(
            question_id,
            PretestSubmission.OpportunityStatus.MISSING,
        )
        item_status = {
            PretestSubmission.OpportunityStatus.OBSERVED: UnifiedAssessmentMaterial.MaterialStatus.AVAILABLE,
            PretestSubmission.OpportunityStatus.MISSING: UnifiedAssessmentMaterial.MaterialStatus.MISSING,
            PretestSubmission.OpportunityStatus.DEVICE_ISSUE: UnifiedAssessmentMaterial.MaterialStatus.DEVICE_ISSUE,
            PretestSubmission.OpportunityStatus.NOT_OFFERED: UnifiedAssessmentMaterial.MaterialStatus.NOT_OFFERED,
        }[task_status]
        if (
            task_status == PretestSubmission.OpportunityStatus.OBSERVED
            and question_type not in objective_types
            and question_type != PretestQuestion.QuestionType.SCALE
        ):
            item_status = UnifiedAssessmentMaterial.MaterialStatus.PENDING_REVIEW
        material_type = UnifiedAssessmentMaterial.MaterialType.ANSWER
        if question_type == PretestQuestion.QuestionType.OPERATION:
            material_type = UnifiedAssessmentMaterial.MaterialType.OPERATION
        elif question_type in {
            PretestQuestion.QuestionType.PERFORMANCE,
            PretestQuestion.QuestionType.SHORT_PROJECT,
        }:
            material_type = UnifiedAssessmentMaterial.MaterialType.ARTIFACT
        attachment_manifest = [
            {
                key: (str(value) if key == "attachment_id" else value)
                for key, value in item.items()
                if key != "data"
            }
            for item in prepared_attachments.get(question_id, [])
        ]
        material = UnifiedAssessmentMaterial.objects.create(
            school=paper.school,
            subject=paper.subject,
            course=administration.course,
            class_group=profile.class_group,
            student=request.user,
            recorded_by=request.user,
            learning_target_version=target_version,
            legacy_unmapped=legacy_unmapped,
            ownership=UnifiedAssessmentMaterial.Ownership.INDIVIDUAL,
            material_type=material_type,
            material_status=item_status,
            learning_target_code=target_code,
            source_type=diagnostic_source_type,
            source_id=str(submission.id),
            source_version=paper_version.content_hash,
            content={
                "question_id": question_id,
                "question_type": question_type,
                "answer": answers.get(question_id),
                "process_explanation": (
                    answers.get(question_id)
                    if question_type in PRETEST_ATTACHMENT_QUESTION_TYPES
                    else None
                ),
                "attachments": attachment_manifest,
                "material_requirements": question.get("material_requirements") or [],
                "paper_version_id": paper_version.id,
                "paper_content_hash": paper_version.content_hash,
                "administration_id": administration.id,
                "administration_content_hash": administration.content_hash,
                "batch_code": administration.batch_code,
                "purpose": administration.purpose,
                "learning_target_version_id": (
                    target_version.id if target_version is not None else None
                ),
                "learning_target_version_hash": (
                    target_version.content_hash if target_version is not None else ""
                ),
                "learning_target_logical_key": (
                    str(target_version.target.logical_key)
                    if target_version is not None
                    else ""
                ),
                "legacy_unmapped": legacy_unmapped,
                "opportunity_status": task_status,
                "reported_by": request.user.id,
                "validity_policy": {
                    "code": validity_policy["code"],
                    "days": validity_policy["days"],
                },
            },
            score=(objective_scores.get(question_id) or (None, None))[0],
            score_max=(
                (objective_scores.get(question_id) or (None, None))[1]
                or (float(question.get("score") or 0) or None)
            ),
            recorded_at=submission.submitted_at,
        )
        materials_by_question[question_id] = material
        material_refs_by_target.setdefault(target_bucket_key, []).append(
            str(material.material_id)
        )

    for result in target_results:
        target_version_id = result.get("learning_target_version_id")
        target_version = (
            next(
                (
                    item
                    for item in frozen_targets.values()
                    if item is not None and item.id == target_version_id
                ),
                None,
            )
            if target_version_id
            else None
        )
        legacy_unmapped = target_version is None
        target_bucket_key = (
            f"version:{target_version.id}"
            if target_version is not None
            else f"legacy:{result['learning_target_code']}"
        )
        coverage = (
            result["observed_count"] / result["task_count"]
            if result["task_count"]
            else 0
        )
        uncertainty, coverage = _diagnostic_target_uncertainty(
            evidence_status=result["evidence_status"],
            observed_task_count=result["observed_count"],
            task_count=result["task_count"],
        )
        observation_notes = [result["reason"]] if result["reason"] else []
        observation_notes.append(
            f"有效期策略：{validity_policy['code']}={validity_policy['days']}天"
        )
        observation_notes.append(
            f"诊断实施批次：{administration.batch_code}；用途：{administration.get_purpose_display()}"
        )
        observation_notes.append(
            "不确定性估计："
            f"method={DIAGNOSTIC_UNCERTAINTY_METHOD};"
            f"observed_task_count={result['observed_count']};"
            f"task_count={result['task_count']};coverage={coverage:.6f}"
        )
        StudentLearningTargetStateVersion.objects.create(
            student=request.user,
            school=paper.school,
            class_group=profile.class_group,
            subject=paper.subject,
            course=administration.course,
            learning_target_version=target_version,
            legacy_unmapped=legacy_unmapped,
            learning_target_code=result["learning_target_code"],
            learning_target_name=result["learning_target_name"],
            source_type=diagnostic_source_type,
            source_id=str(submission.id),
            source_version=administration.content_hash,
            evidence_status=result["evidence_status"],
            evidence_coverage=round(coverage, 6),
            estimate=result["estimate"],
            uncertainty=uncertainty,
            material_references=material_refs_by_target.get(target_bucket_key, []),
            observation_notes=observation_notes,
            is_initial_diagnostic=is_initial_diagnostic,
            observed_at=submission.submitted_at,
            valid_from=submission.submitted_at,
            valid_until=validity_policy["valid_until"],
        )
    content_candidate_result = _initial_content_candidate_result(
        administration,
        request.user,
    )
    try:
        record_pretest_submitted(submission=submission, profile=profile)
    except EventWriteError as exc:
        transaction.set_rollback(True)
        return fail(exc.message, status=500)
    stored_paths: list[tuple[object, str]] = []
    created_attachments: list[PretestMaterialAttachment] = []
    try:
        for question_id, items in prepared_attachments.items():
            material = materials_by_question[question_id]
            for item in items:
                attachment = PretestMaterialAttachment(
                    attachment_id=item["attachment_id"],
                    material=material,
                    submission=submission,
                    paper_version=paper_version,
                    student=request.user,
                    question_id=question_id,
                    attachment=ContentFile(
                        item["data"],
                        name=f"{item['attachment_id'].hex}.{item['file_ext']}",
                    ),
                    original_name=item["original_name"],
                    file_ext=item["file_ext"],
                    content_type=item["content_type"],
                    file_size=item["file_size"],
                    file_sha256=item["file_sha256"],
                )
                attachment.save()
                stored_paths.append(
                    (attachment.attachment.storage, attachment.attachment.name)
                )
                created_attachments.append(attachment)
    except (OSError, ValidationError, IntegrityError):
        for storage, name in stored_paths:
            try:
                storage.delete(name)
            except OSError:
                pass
        transaction.set_rollback(True)
        return fail("作品附件保存失败，请检查文件后重试。", status=500)
    response_data = _diagnostic_submission_result(
            submission,
            administration=administration,
            assignment=assignment,
            idempotent_replay=False,
        )
    response_data["learning_content_recommendation"] = content_candidate_result
    return ok(
        response_data,
        "学习起点诊断已提交。",
    )
