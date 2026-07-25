from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from courses.models import (
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomGroup,
    ClassroomGroupDocumentVersion,
    ClassroomGroupFile,
    ClassroomGroupMember,
)
from learning.models import LearningEvent, LessonStepAttempt, StudentWorkAttachment
from learning_analytics.models import (
    ClassroomEvaluationStandardUse,
    EvaluationSubmissionEvidence,
    LessonStepEvaluationBinding,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    learning_event_write_mode,
    record_learning_event,
)
from learning_analytics.services.evaluation import standard_curriculum_alignment


class EvaluationEventError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


EVALUATION_TYPES = {
    ClassroomEvaluationSubmission.EvaluationType.SELF,
    ClassroomEvaluationSubmission.EvaluationType.PEER,
    ClassroomEvaluationSubmission.EvaluationType.TEACHER,
}

EVIDENCE_OWNERSHIPS = {"individual", "group", "both"}
EVIDENCE_MATERIAL_TYPES = {
    "answer",
    "artifact",
    "operation",
    "oral_defense",
    "observation",
    "score",
}
EVIDENCE_MANIFEST_SCHEMA_VERSION = "evaluation-material-manifest-v2"


def _criteria_rows(raw_items) -> list[dict]:
    rows = []
    seen = set()
    for index, item in enumerate(raw_items if isinstance(raw_items, list) else [], 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        criterion_id = str(item.get("id") or f"crit_{index}").strip()[:64]
        if not criterion_id or criterion_id in seen:
            continue
        seen.add(criterion_id)
        try:
            sort_order = int(item.get("sort_order") or index * 10)
        except (TypeError, ValueError):
            sort_order = index * 10
        row = {
            "id": criterion_id,
            "title": title[:80],
            "description": str(item.get("description") or "").strip()[:300],
            "sort_order": sort_order,
        }
        optional_fields = {
            "standard_criterion_id": item.get("standard_criterion_id"),
            "criterion_code": str(item.get("criterion_code") or "").strip()[:32],
            "dimension": str(item.get("dimension") or "").strip()[:32],
            "evaluation_target": str(item.get("evaluation_target") or "").strip()[:300],
            "evaluation_sources": item.get("evaluation_sources"),
            "learning_goal_codes": item.get("learning_goal_codes"),
            "learning_target_links": item.get("learning_target_links"),
            "evaluation_task_codes": item.get("evaluation_task_codes"),
            "evidence_ownership": str(
                item.get("evidence_ownership") or ""
            ).strip(),
            "material_types": item.get("material_types"),
            "level_descriptions": item.get("level_descriptions"),
            "skip_condition": str(item.get("skip_condition") or "").strip(),
            "support_options": item.get("support_options"),
            "common_problems": item.get("common_problems"),
            "follow_up_suggestion": str(item.get("follow_up_suggestion") or "").strip(),
            "curriculum_alignment": item.get("curriculum_alignment"),
        }
        for field, value in optional_fields.items():
            if field in item:
                row[field] = value
        rows.append(row)
    return sorted(rows, key=lambda item: (item["sort_order"], item["id"]))


def evaluation_config_snapshot(config) -> dict:
    self_criteria = _criteria_rows(config.self_criteria)
    peer_criteria = _criteria_rows(config.peer_criteria)
    teacher_criteria = _criteria_rows(config.teacher_criteria)
    return {
        "enable_self": bool(config.enable_self or self_criteria),
        "enable_peer": bool(config.enable_peer or peer_criteria),
        "enable_teacher": bool(config.enable_teacher or teacher_criteria),
        "self_criteria": self_criteria,
        "peer_criteria": peer_criteria,
        "teacher_criteria": teacher_criteria,
    }


def evaluation_config_hash(snapshot: dict) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def publish_evaluation_config_version(
    *, config: ClassroomEvaluationConfig, actor=None
) -> ClassroomEvaluationConfigVersion:
    config = ClassroomEvaluationConfig.objects.select_for_update().get(pk=config.pk)
    snapshot = evaluation_config_snapshot(config)
    config_hash = evaluation_config_hash(snapshot)
    existing = ClassroomEvaluationConfigVersion.objects.filter(
        course=config.course,
        config_hash=config_hash,
    ).first()
    if existing:
        return existing
    latest_no = (
        ClassroomEvaluationConfigVersion.objects.filter(course=config.course).aggregate(
            value=Max("version_no")
        )["value"]
        or 0
    )
    return ClassroomEvaluationConfigVersion.objects.create(
        course=config.course,
        version_no=latest_no + 1,
        config_hash=config_hash,
        created_by=actor or config.created_by,
        **snapshot,
    )


def standard_binding_criteria(binding: LessonStepEvaluationBinding) -> list[dict]:
    rows = []
    curriculum_alignment = standard_curriculum_alignment(binding.standard_version)
    for index, criterion in enumerate(
        binding.standard_version.criteria.all().order_by("sort_order", "id"), 1
    ):
        target_links = [
            {
                "target_version_id": link.target_version_id,
                "logical_key": str(link.target_version.target.logical_key),
                "content_hash": link.target_version.content_hash,
                "alignment_status": link.target_version.alignment_status,
            }
            for link in criterion.learning_target_links.select_related(
                "target_version__target"
            ).order_by("sort_order", "id")
        ]
        rows.append(
            {
                "id": f"std_{binding.standard_version_id}_{criterion.code}"[:64],
                "title": criterion.title[:80],
                "description": criterion.expected_performance[:300],
                "sort_order": index * 10,
                "standard_criterion_id": criterion.id,
                "criterion_code": criterion.code,
                "dimension": criterion.dimension,
                "evaluation_target": criterion.evaluation_target,
                "evaluation_sources": criterion.evaluation_sources,
                "learning_goal_codes": criterion.learning_goal_codes,
                "learning_target_links": target_links,
                "evaluation_task_codes": criterion.evaluation_task_codes,
                "evidence_ownership": criterion.evidence_ownership,
                "material_types": criterion.material_types,
                "level_descriptions": criterion.level_descriptions,
                "skip_condition": criterion.skip_condition,
                "support_options": criterion.support_options,
                "common_problems": criterion.common_problems,
                "follow_up_suggestion": criterion.follow_up_suggestion,
                "curriculum_alignment": curriculum_alignment.get(criterion.code, {}),
            }
        )
    return rows


@transaction.atomic
def freeze_classroom_evaluation_standard(
    *, session, binding: LessonStepEvaluationBinding, actor
) -> ClassroomEvaluationStandardUse:
    existing = ClassroomEvaluationStandardUse.objects.filter(session=session).first()
    if existing:
        return existing
    criteria = standard_binding_criteria(binding)
    if not criteria:
        raise EvaluationEventError("evaluation_standard_empty", "评价标准没有可用评价指标。")
    snapshot = {
        "standard_version_id": binding.standard_version_id,
        "standard_version_no": binding.standard_version.version_no,
        "standard_content_hash": binding.standard_version.content_hash,
        "enable_self": binding.enable_self,
        "enable_peer": binding.enable_peer,
        "enable_teacher": binding.enable_teacher,
        "self_criteria": criteria if binding.enable_self else [],
        "peer_criteria": criteria if binding.enable_peer else [],
        "teacher_criteria": criteria if binding.enable_teacher else [],
    }
    config_hash = evaluation_config_hash(snapshot)
    return ClassroomEvaluationStandardUse.objects.create(
        session=session,
        binding=binding,
        lesson_step=binding.lesson_step,
        standard_version=binding.standard_version,
        evaluation_config_version=None,
        criteria_snapshot=criteria,
        configuration_snapshot=snapshot,
        content_hash=config_hash,
        enable_self=binding.enable_self,
        enable_peer=binding.enable_peer,
        enable_teacher=binding.enable_teacher,
        legacy_compatible=False,
        opened_by=actor,
    )


def _submission_scope_error(message: str) -> EvaluationEventError:
    return EvaluationEventError("evaluation_evidence_scope_mismatch", message)


def _validate_submission_scope(
    *, submission, standard_use: ClassroomEvaluationStandardUse, group=None
) -> None:
    session = submission.session
    if session is None:
        raise _submission_scope_error("正式评价证据必须属于一次课堂。")
    if submission.course_id != session.course_id:
        raise _submission_scope_error("评价提交与课堂课程不一致。")
    if submission.class_group_id != session.class_group_id:
        raise _submission_scope_error("评价提交与课堂班级不一致。")
    if standard_use.session_id != session.id:
        raise _submission_scope_error("评价提交与课堂冻结版本不一致。")
    if standard_use.course_id != session.course_id:
        raise _submission_scope_error("课堂冻结版本与课堂课程不一致。")
    standard_version = standard_use.standard_version
    if standard_version.school_id != session.school_id:
        raise _submission_scope_error("课堂冻结版本与课堂学校不一致。")
    if submission.evaluator.school_id != session.school_id:
        raise _submission_scope_error("评价人与课堂不属于同一学校。")
    if submission.target.school_id != session.school_id:
        raise _submission_scope_error("被评价学生与课堂不属于同一学校。")
    target_profile = getattr(submission.target, "student_profile", None)
    if target_profile is None or target_profile.class_group_id != session.class_group_id:
        raise _submission_scope_error("被评价学生不属于当前课堂班级。")
    if submission.evaluation_type == ClassroomEvaluationSubmission.EvaluationType.SELF:
        if submission.evaluator_id != submission.target_id:
            raise _submission_scope_error("自评的评价人与被评价学生必须一致。")
    elif submission.evaluation_type == ClassroomEvaluationSubmission.EvaluationType.TEACHER:
        if submission.evaluator_id != session.teacher_id:
            raise _submission_scope_error("师评必须由当前课堂教师提交。")
    elif submission.evaluation_type == ClassroomEvaluationSubmission.EvaluationType.PEER:
        if submission.evaluator_id == submission.target_id:
            raise _submission_scope_error("互评的评价人与被评价学生不能相同。")
    if group is not None:
        collaboration = group.collaboration
        if collaboration.session_id != session.id:
            raise _submission_scope_error("评价小组不属于当前课堂。")
        if not group.is_active or group.plan_version != collaboration.active_plan_version:
            raise _submission_scope_error("评价小组不是当前生效的实际小组。")
        member_ids = set(
            ClassroomGroupMember.objects.filter(
                collaboration=collaboration,
                group=group,
                plan_version=collaboration.active_plan_version,
            ).values_list("student_id", flat=True)
        )
        if submission.target_id not in member_ids:
            raise _submission_scope_error("被评价学生不是该实际小组的成员。")
        if (
            submission.evaluation_type
            == ClassroomEvaluationSubmission.EvaluationType.PEER
            and submission.evaluator_id not in member_ids
        ):
            raise _submission_scope_error("互评人与被评价学生必须属于同一实际小组。")


def _active_target_group(*, session, target) -> ClassroomGroup | None:
    return (
        ClassroomGroup.objects.select_related("collaboration")
        .filter(
            collaboration__session=session,
            is_active=True,
            members__student=target,
            members__plan_version=F("collaboration__active_plan_version"),
            plan_version=F("collaboration__active_plan_version"),
        )
        .order_by("group_no", "id")
        .first()
    )


def _material_source(
    *, material_type, ownership, submission, attempt, work, group_document, group_file
):
    if material_type == "score":
        return {
            "source_type": "classroom_evaluation_submission",
            "source_id": str(submission.submission_id),
            "source_version": str(submission.submission_version),
            "record_kind": "scoring_record",
            "recorded_by_user_id": submission.evaluator_id,
        }
    if material_type in {"oral_defense", "observation"}:
        if (
            submission.evaluation_type
            == ClassroomEvaluationSubmission.EvaluationType.TEACHER
            and str(submission.comment or "").strip()
        ):
            return {
                "source_type": "classroom_evaluation_submission",
                "source_id": str(submission.submission_id),
                "source_version": str(submission.submission_version),
                "record_kind": "teacher_attested_live_observation",
                "recorded_by_user_id": submission.evaluator_id,
            }
        return None
    if ownership == "individual":
        attempt_has_response = bool(
            attempt is not None
            and (
                attempt.answered_count
                or str(attempt.free_text or "").strip()
                or attempt.answer
            )
        )
        operation_recorded = bool(
            attempt_has_response
            and attempt.lesson_step.step_type in {"task", "ai_worksheet", "document"}
        )
        if (
            (material_type == "answer" and attempt_has_response)
            or (material_type == "operation" and operation_recorded)
        ) and attempt is not None:
            return {
                "source_type": "lesson_step_attempt",
                "source_id": str(attempt.attempt_id),
                "source_version": str(attempt.attempt_no),
                "record_kind": (
                    "structured_answer" if material_type == "answer" else "operation_attempt"
                ),
                "contributor_student_ids": [submission.target_id],
            }
        if (
            material_type == "artifact"
            and work is not None
            and bool(work.attachment)
            and work.file_size > 0
        ):
            return {
                "source_type": "student_work_attachment",
                "source_id": str(work.submission_id),
                "source_version": str(work.upload_version),
                "record_kind": "individual_artifact",
                "contributor_student_ids": [submission.target_id],
            }
        return None
    if material_type == "artifact" and group_document is not None:
        return {
            "source_type": "classroom_group_document_version",
            "source_id": str(group_document.id),
            "source_version": str(group_document.version_no),
            "record_kind": "group_artifact",
            "sha256": group_document.file_sha256,
            "contributor_student_ids": [
                int(editor_id)
                for editor_id in (group_document.verified_editor_ids or [])
                if str(editor_id).isdigit()
            ],
        }
    if material_type == "artifact" and group_file is not None:
        return {
            "source_type": "classroom_group_file",
            "source_id": str(group_file.public_id),
            "source_version": str(group_file.version_no),
            "record_kind": "group_artifact",
            "contributor_student_ids": (
                [group_file.uploader_id] if group_file.uploader_id else []
            ),
        }
    return None


def _not_assessed_status(reason: str) -> str:
    return {
        ClassroomEvaluationSubmission.NotAssessedReason.NO_EVIDENCE: "missing",
        ClassroomEvaluationSubmission.NotAssessedReason.NOT_OBSERVED: "not_observed",
        ClassroomEvaluationSubmission.NotAssessedReason.NOT_APPLICABLE: "not_applicable",
        ClassroomEvaluationSubmission.NotAssessedReason.TECHNICAL_ISSUE: "technical_issue",
        ClassroomEvaluationSubmission.NotAssessedReason.OTHER: "not_observed",
    }.get(reason, "missing")


def _criterion_material_manifest(
    *, criterion, submission, group, attempt, work, group_document, group_file
) -> list[dict]:
    criterion_id = str(criterion.get("id") or "")
    ownership = str(criterion.get("evidence_ownership") or "").strip()
    material_types = [
        str(item).strip()
        for item in (criterion.get("material_types") or [])
        if str(item).strip()
    ]
    if ownership not in EVIDENCE_OWNERSHIPS or not material_types:
        return []
    if set(material_types) - EVIDENCE_MATERIAL_TYPES:
        raise EvaluationEventError(
            "evaluation_material_type_invalid",
            f"评价指标“{criterion.get('title') or criterion_id}”包含未知评价材料类型。",
        )
    required_ownerships = (
        ["individual", "group"] if ownership == "both" else [ownership]
    )
    group_member_ids = (
        list(
            ClassroomGroupMember.objects.filter(
                collaboration=group.collaboration,
                group=group,
                plan_version=group.collaboration.active_plan_version,
            )
            .order_by("student_id")
            .values_list("student_id", flat=True)
        )
        if group is not None
        else []
    )
    not_assessed_row = submission.not_assessed.get(criterion_id)
    reason = (
        str(not_assessed_row.get("reason") or "")
        if isinstance(not_assessed_row, dict)
        else ""
    )
    rows = []
    for item_ownership in required_ownerships:
        for material_type in material_types:
            source = None
            status = _not_assessed_status(reason) if reason else "missing"
            if not reason:
                source = _material_source(
                    material_type=material_type,
                    ownership=item_ownership,
                    submission=submission,
                    attempt=attempt,
                    work=work,
                    group_document=group_document,
                    group_file=group_file,
                )
                if source:
                    status = "available"
            row = {
                "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
                "criterion_id": criterion_id,
                "criterion_code": str(criterion.get("criterion_code") or ""),
                "learning_goal_codes": list(criterion.get("learning_goal_codes") or []),
                "learning_target_links": list(
                    criterion.get("learning_target_links") or []
                ),
                "evaluation_task_codes": list(
                    criterion.get("evaluation_task_codes") or []
                ),
                "ownership": item_ownership,
                "material_type": material_type,
                "status": status,
                "student_id": submission.target_id,
                "group_id": group.id if item_ownership == "group" and group else None,
                "participant_student_ids": (
                    group_member_ids if item_ownership == "group" else [submission.target_id]
                ),
                "source": source,
            }
            if reason:
                row["not_assessed_reason"] = reason
            elif source is None:
                row["missing_reason"] = "matching_source_not_found"
            rows.append(row)
    if criterion_id in submission.ratings:
        for item_ownership in required_ownerships:
            matching_rows = [
                row for row in rows if row["ownership"] == item_ownership
            ]
            if not any(row["status"] == "available" for row in matching_rows):
                ownership_label = "个人" if item_ownership == "individual" else "小组"
                raise EvaluationEventError(
                    "evaluation_evidence_missing",
                    f"评价指标“{criterion.get('title') or criterion_id}”缺少可追溯的{ownership_label}评价材料，请选择暂不评价并记录原因。",
                )
    return rows


def capture_evaluation_submission_evidence(submission):
    if not submission.session_id:
        return None
    standard_use = ClassroomEvaluationStandardUse.objects.filter(
        session_id=submission.session_id
    ).first()
    if standard_use is None:
        return None
    criteria = _criteria_for_type(standard_use, submission.evaluation_type)
    criterion_ids = set(submission.ratings) | set(submission.not_assessed)
    selected_criteria = [
        criterion for criterion in criteria if str(criterion.get("id")) in criterion_ids
    ]
    configured_ownerships = {
        str(criterion.get("evidence_ownership") or "")
        for criterion in selected_criteria
        if str(criterion.get("evidence_ownership") or "") in EVIDENCE_OWNERSHIPS
    }
    needs_group = bool(configured_ownerships & {"group", "both"})
    group = submission.group
    if group is None and (
        needs_group
        or submission.evaluation_type
        == ClassroomEvaluationSubmission.EvaluationType.PEER
    ):
        group = _active_target_group(session=submission.session, target=submission.target)
    _validate_submission_scope(
        submission=submission,
        standard_use=standard_use,
        group=group,
    )
    if needs_group and group is None:
        raise EvaluationEventError(
            "evaluation_group_evidence_missing",
            "该评价指标需要小组评价材料，但被评价学生没有当前课堂的生效实际小组。",
        )
    attempt = (
        LessonStepAttempt.objects.select_related("lesson_step").filter(
            classroom_session_id=submission.session_id,
            lesson_step_id=standard_use.lesson_step_id,
            student_id=submission.target_id,
            school_id=submission.session.school_id,
            class_group_id=submission.class_group_id,
            course_id=submission.course_id,
        )
        .order_by("-attempt_no", "-id")
        .first()
    )
    work = (
        StudentWorkAttachment.objects.filter(
            classroom_session_id=submission.session_id,
            lesson_step_id=standard_use.lesson_step_id,
            student_id=submission.target_id,
            school_id=submission.session.school_id,
            class_group_id=submission.class_group_id,
            course_id=submission.course_id,
        )
        .exclude(attachment="")
        .filter(file_size__gt=0)
        .order_by("-upload_version", "-id")
        .first()
    )
    group_member_ids = (
        set(
            ClassroomGroupMember.objects.filter(
                collaboration=group.collaboration,
                group=group,
                plan_version=group.collaboration.active_plan_version,
            ).values_list("student_id", flat=True)
        )
        if group is not None
        else set()
    )
    group_member_id_strings = {str(student_id) for student_id in group_member_ids}
    group_document = (
        next(
            (
                document
                for document in ClassroomGroupDocumentVersion.objects.filter(
                    group=group,
                    source=ClassroomGroupDocumentVersion.Source.ONLYOFFICE_CALLBACK,
                    file_size__gt=0,
                ).order_by("-version_no", "-id")
                if group_member_id_strings.intersection(
                    str(editor_id) for editor_id in (document.verified_editor_ids or [])
                )
            ),
            None,
        )
        if group is not None
        else None
    )
    group_file = (
        ClassroomGroupFile.objects.filter(
            group=group,
            uploader_id__in=group_member_ids,
            file_size__gt=0,
        )
        .exclude(attachment="")
        .order_by("-version_no", "-created_at", "-id")
        .first()
        if group is not None
        else None
    )
    material_manifest = []
    for criterion in selected_criteria:
        material_manifest.extend(
            _criterion_material_manifest(
                criterion=criterion,
                submission=submission,
                group=group,
                attempt=attempt,
                work=work,
                group_document=group_document,
                group_file=group_file,
            )
        )
    if configured_ownerships == {"individual"}:
        evidence_ownership = "individual"
    elif configured_ownerships == {"group"}:
        evidence_ownership = "group"
    elif configured_ownerships:
        evidence_ownership = "both"
    else:
        # Historical frozen versions had no explicit ownership. Preserve their
        # prior personal-evidence behavior without inventing a P2 mapping.
        evidence_ownership = "individual"
    evidence = EvaluationSubmissionEvidence.objects.create(
        submission=submission,
        standard_use=standard_use,
        lesson_step_attempt=(
            attempt
            if not configured_ownerships
            or any(
                row["status"] == "available"
                and row["ownership"] == "individual"
                and row["source"]
                and row["source"]["source_type"] == "lesson_step_attempt"
                for row in material_manifest
            )
            else None
        ),
        student_work_attachment=(
            work
            if not configured_ownerships
            or any(
                row["status"] == "available"
                and row["ownership"] == "individual"
                and row["source"]
                and row["source"]["source_type"] == "student_work_attachment"
                for row in material_manifest
            )
            else None
        ),
        evidence_ownership=evidence_ownership,
        group=(group if evidence_ownership in {"group", "both"} else None),
        material_manifest=material_manifest,
    )
    if material_manifest:
        from learning_analytics.services.evaluation_materials import (
            project_evaluation_submission_materials,
        )

        project_evaluation_submission_materials(evidence=evidence)
    return evidence


def evaluation_version_label(version: ClassroomEvaluationConfigVersion | None) -> str:
    if version is None:
        return "legacy:unknown"
    return (
        f"course:{version.course_id}:v{version.version_no}:{version.config_hash[:12]}"
    )


def standard_use_version_label(use: ClassroomEvaluationStandardUse) -> str:
    version = use.standard_version
    return f"standard:{version.id}:v{version.version_no}:{version.content_hash[:12]}"


def classroom_evaluation_object_version(*, session, version) -> str:
    standard_use = ClassroomEvaluationStandardUse.objects.filter(
        session_id=session.id
    ).select_related("standard_version").first()
    return (
        standard_use_version_label(standard_use)
        if standard_use
        else getattr(version, "config_hash", "legacy:unknown")
    )


def _criteria_for_type(version, evaluation_type: str) -> list[dict]:
    field = {
        "self": "self_criteria",
        "peer": "peer_criteria",
        "teacher": "teacher_criteria",
    }.get(evaluation_type)
    return _criteria_rows(getattr(version, field, [])) if field else []


def _type_enabled(version, evaluation_type: str) -> bool:
    field = {
        "self": "enable_self",
        "peer": "enable_peer",
        "teacher": "enable_teacher",
    }.get(evaluation_type)
    return bool(
        field
        and getattr(version, field, False)
        and _criteria_for_type(version, evaluation_type)
    )


def classroom_evaluation_object_id(session, evaluation_type: str) -> str:
    return f"classroom-evaluation:{session.id}:{evaluation_type}"


def course_evaluation_object_id(course, class_group, evaluation_type: str) -> str:
    return f"course-evaluation:{course.id}:{class_group.id}:{evaluation_type}"


@transaction.atomic
def release_classroom_evaluation_opportunities(
    *, session, actor, version: ClassroomEvaluationConfigVersion, occurred_at=None
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"release_events": 0, "opportunities_created": 0}
    occurred_at = occurred_at or timezone.now()
    object_version = classroom_evaluation_object_version(
        session=session, version=version
    )
    existing_ids = set(
        LearningEventV2.objects.filter(
            school=session.school,
            event_name="content.released",
            classroom_session=session,
            legacy_event__metadata__action="classroom_evaluation_released",
            client_occurred_at__gte=session.evaluation_opened_at or occurred_at,
        ).values_list("object_id", flat=True)
    )
    release_events = 0
    opportunities_created = 0
    for evaluation_type in sorted(EVALUATION_TYPES):
        if not _type_enabled(version, evaluation_type):
            continue
        object_id = classroom_evaluation_object_id(session, evaluation_type)
        if object_id in existing_ids:
            continue
        try:
            result = record_learning_event(
                actor=actor,
                event_name="content.released",
                payload={
                    "content_type": LearningOpportunity.ContentType.TASK,
                    "required": False,
                    "target_layers": ["all"],
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=session.class_group,
                subject=session.course.subject,
                course=session.course,
                lesson=session.lesson,
                classroom_session=session,
                object_type="evaluation_standard",
                object_id=object_id,
                object_version=object_version,
                legacy_metadata={
                    "action": "classroom_evaluation_released",
                    "classroom_session": session.id,
                    "evaluation_type": evaluation_type,
                    "evaluation_version": evaluation_version_label(version),
                },
                occurred_at=occurred_at,
            )
        except EventWriteError as exc:
            raise EvaluationEventError(exc.code, exc.message) from exc
        release_events += 1
        if result.analytics_event:
            opportunities_created += (
                result.analytics_event.released_opportunities.count()
            )
    return {
        "release_events": release_events,
        "opportunities_created": opportunities_created,
    }


@transaction.atomic
def withdraw_classroom_evaluation_opportunities(
    *, session, actor, reason_code: str, occurred_at=None
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"withdrawal_events": 0}
    occurred_at = occurred_at or timezone.now()
    releases = LearningEventV2.objects.filter(
        school=session.school,
        event_name="content.released",
        classroom_session=session,
        legacy_event__metadata__action="classroom_evaluation_released",
    ).select_related("class_group", "subject", "course", "lesson")
    withdrawal_events = 0
    for release in releases:
        if LearningEventV2.objects.filter(
            school=session.school,
            event_name="content.withdrawn",
            payload__release_event_id=str(release.event_id),
        ).exists():
            continue
        try:
            record_learning_event(
                actor=actor,
                event_name="content.withdrawn",
                payload={
                    "release_event_id": release.event_id,
                    "reason_code": reason_code,
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=release.class_group,
                subject=release.subject,
                course=release.course,
                lesson=release.lesson,
                classroom_session=session,
                object_type=release.object_type,
                object_id=release.object_id,
                legacy_metadata={
                    "action": "classroom_evaluation_withdrawn",
                    "classroom_session": session.id,
                    "release_event_id": str(release.event_id),
                    "reason_code": reason_code,
                },
                occurred_at=occurred_at,
            )
        except EventWriteError as exc:
            raise EvaluationEventError(exc.code, exc.message) from exc
        withdrawal_events += 1
    return {"withdrawal_events": withdrawal_events}


def _active_evaluation_opportunity(*, student, object_id: str, object_version: str):
    if learning_event_write_mode() == "v1_only":
        return None
    opportunities = LearningOpportunity.objects.filter(
        student=student,
        content_type=LearningOpportunity.ContentType.TASK,
        object_id=object_id,
        object_version=object_version,
    ).order_by("-released_at", "-created_at")
    for opportunity in opportunities:
        if not opportunity.transition_facts.filter(
            state__in=LearningOpportunityTransitionFact.TERMINAL_STATES
        ).exists():
            return opportunity
    raise EvaluationEventError(
        "evaluation_opportunity_missing",
        "评价机会不存在或已经关闭，请重新开启评价后再提交。",
    )


@transaction.atomic
def _ensure_course_evaluation_opportunities(
    *, course, class_group, version, evaluation_type: str, actor, occurred_at=None
):
    if learning_event_write_mode() == "v1_only":
        return
    object_id = course_evaluation_object_id(course, class_group, evaluation_type)
    old_releases = LearningEventV2.objects.filter(
        school=actor.school,
        event_name="content.released",
        class_group=class_group,
        course=course,
        object_id=object_id,
        legacy_event__metadata__action="course_evaluation_released",
    ).exclude(object_version=version.config_hash)
    for release in old_releases.select_related("class_group", "subject", "course"):
        if LearningEventV2.objects.filter(
            school=actor.school,
            event_name="content.withdrawn",
            payload__release_event_id=str(release.event_id),
        ).exists():
            continue
        try:
            record_learning_event(
                actor=actor,
                event_name="content.withdrawn",
                payload={
                    "release_event_id": release.event_id,
                    "reason_code": "evaluation_revised",
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=release.class_group,
                subject=release.subject,
                course=release.course,
                object_type=release.object_type,
                object_id=release.object_id,
                legacy_metadata={
                    "action": "course_evaluation_withdrawn",
                    "release_event_id": str(release.event_id),
                    "reason_code": "evaluation_revised",
                },
                occurred_at=occurred_at or timezone.now(),
            )
        except EventWriteError as exc:
            raise EvaluationEventError(exc.code, exc.message) from exc
    exists = LearningEventV2.objects.filter(
        school=actor.school,
        event_name="content.released",
        class_group=class_group,
        course=course,
        object_id=object_id,
        object_version=version.config_hash,
        legacy_event__metadata__action="course_evaluation_released",
    ).exists()
    if exists:
        return
    try:
        record_learning_event(
            actor=actor,
            event_name="content.released",
            payload={
                "content_type": LearningOpportunity.ContentType.TASK,
                "required": False,
                "target_layers": ["all"],
            },
            legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
            class_group=class_group,
            subject=course.subject,
            course=course,
            object_type="evaluation_standard",
            object_id=object_id,
            object_version=version.config_hash,
            legacy_metadata={
                "action": "course_evaluation_released",
                "evaluation_type": evaluation_type,
                "evaluation_version": evaluation_version_label(version),
            },
            occurred_at=occurred_at or timezone.now(),
        )
    except EventWriteError as exc:
        raise EvaluationEventError(exc.code, exc.message) from exc


@transaction.atomic
def append_evaluation_submission(
    *,
    course,
    class_group,
    evaluation_type: str,
    evaluator,
    target,
    evaluation_version: ClassroomEvaluationConfigVersion | None = None,
    standard_use: ClassroomEvaluationStandardUse | None = None,
    ratings: dict,
    not_assessed: dict,
    comment: str,
    session=None,
    group=None,
) -> ClassroomEvaluationSubmission:
    runtime_config = standard_use or evaluation_version
    if runtime_config is None:
        raise EvaluationEventError("evaluation_version_missing", "评价提交缺少课堂冻结版本。")
    if runtime_config.course_id != course.id:
        raise EvaluationEventError("evaluation_course_mismatch", "评价评价标准不属于当前课程。")
    if session and standard_use is None:
        standard_use = ClassroomEvaluationStandardUse.objects.filter(session=session).first()
        runtime_config = standard_use or evaluation_version
    if standard_use and session and standard_use.session_id != session.id:
        raise EvaluationEventError("evaluation_session_mismatch", "课堂冻结版本不属于当前课堂。")
    query = ClassroomEvaluationSubmission.objects.select_for_update().filter(
        course=course,
        session=session,
        evaluation_type=evaluation_type,
        evaluator=evaluator,
        target=target,
    )
    previous = query.order_by("-submission_version", "-id").first()
    submission = ClassroomEvaluationSubmission.objects.create(
        course=course,
        class_group=class_group,
        session=session,
        evaluation_type=evaluation_type,
        evaluator=evaluator,
        target=target,
        group=group,
        evaluation_version=evaluation_version,
        standard_use=standard_use,
        legacy_compatible=standard_use is None,
        submission_version=(previous.submission_version + 1 if previous else 1),
        supersedes=previous,
        ratings=ratings,
        not_assessed=not_assessed,
        comment=comment,
    )
    evidence = capture_evaluation_submission_evidence(submission)
    if session:
        release_classroom_evaluation_opportunities(
            session=session,
            actor=session.teacher,
            version=runtime_config,
        )
        object_id = classroom_evaluation_object_id(session, evaluation_type)
    else:
        _ensure_course_evaluation_opportunities(
            course=course,
            class_group=class_group,
            version=evaluation_version,
            evaluation_type=evaluation_type,
            actor=course.teacher,
        )
        object_id = course_evaluation_object_id(course, class_group, evaluation_type)
    object_version = (
        standard_use_version_label(evidence.standard_use)
        if evidence
        else getattr(runtime_config, "config_hash", "legacy:unknown")
    )
    opportunity = _active_evaluation_opportunity(
        student=target,
        object_id=object_id,
        object_version=object_version,
    )
    criterion_order = {
        item["id"]: index
        for index, item in enumerate(
            _criteria_for_type(runtime_config, evaluation_type)
        )
    }
    criterion_ratings = [
        {"criterion_id": criterion_id, "rating": int(value)}
        for criterion_id, value in sorted(
            ratings.items(), key=lambda item: criterion_order.get(str(item[0]), 1000)
        )
    ]
    not_assessed_criteria = [
        {
            "criterion_id": criterion_id,
            "reason_code": str(value.get("reason") or ""),
        }
        for criterion_id, value in sorted(
            not_assessed.items(),
            key=lambda item: criterion_order.get(str(item[0]), 1000),
        )
        if isinstance(value, dict)
    ]
    try:
        record_learning_event(
            actor=evaluator,
            target_student=target,
            event_name="evaluation.rating.submitted",
            payload={
                "evaluation_version": (
                    standard_use_version_label(evidence.standard_use)
                    if evidence
                    else evaluation_version_label(evaluation_version)
                ),
                "criterion_ratings": criterion_ratings,
                "not_assessed_criteria": not_assessed_criteria,
                "rater_role": evaluation_type,
            },
            legacy_event_type=(
                LearningEvent.EventType.TEACHER_INTERVENTION
                if evaluation_type
                == ClassroomEvaluationSubmission.EvaluationType.TEACHER
                else LearningEvent.EventType.ANSWER_SUBMIT
            ),
            legacy_actor=evaluator,
            class_group=class_group,
            subject=course.subject,
            course=course,
            lesson=session.lesson if session else None,
            classroom_session=session,
            object_type="evaluation_standard",
            object_id=object_id,
            object_version=object_version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=submission.analytics_attempt_id,
            legacy_metadata={
                "action": f"{evaluation_type}_evaluation_submit",
                "evaluation_submission": submission.id,
                "submission_version": submission.submission_version,
                "target_id": target.id,
                "group_id": group.id if group else None,
                "evaluation_version": evaluation_version_label(evaluation_version),
                "standard_use": standard_use.id if standard_use else None,
                "ratings": ratings,
                "not_assessed": not_assessed,
            },
            occurred_at=timezone.now(),
            schema_version="1.1",
            source_override=(
                "server"
                if evaluation_type == ClassroomEvaluationSubmission.EvaluationType.PEER
                else None
            ),
        )
    except EventWriteError as exc:
        raise EvaluationEventError(exc.code, exc.message) from exc
    return submission
