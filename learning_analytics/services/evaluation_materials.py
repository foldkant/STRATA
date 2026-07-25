from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from learning.models import (
    StudentLearningTargetStateVersion,
    UnifiedAssessmentMaterial,
)
from learning_analytics.models import LearningTargetVersion


MATERIAL_STATUS_MAP = {
    "available": UnifiedAssessmentMaterial.MaterialStatus.AVAILABLE,
    "missing": UnifiedAssessmentMaterial.MaterialStatus.MISSING,
    "not_observed": UnifiedAssessmentMaterial.MaterialStatus.NOT_OBSERVED,
    "not_applicable": UnifiedAssessmentMaterial.MaterialStatus.NOT_APPLICABLE,
    "technical_issue": UnifiedAssessmentMaterial.MaterialStatus.TECHNICAL_ISSUE,
}
EVALUATION_SOURCE_TYPE = "classroom_evaluation"
EVALUATION_CALIBRATION_STATUS = "rubric_rating_not_calibrated"
EVALUATION_VALIDITY_DAYS = 30


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _target_versions(rows: list[dict]) -> dict[int, LearningTargetVersion]:
    frozen_links: dict[int, dict] = {}
    for row in rows:
        for link in row.get("learning_target_links") or []:
            try:
                target_version_id = int(link.get("target_version_id"))
            except (TypeError, ValueError):
                raise ValidationError("评价材料缺少有效的学习目标版本标识。")
            previous = frozen_links.setdefault(target_version_id, link)
            if previous != link:
                raise ValidationError("同一评价提交包含相互冲突的学习目标版本信息。")

    versions = {
        item.id: item
        for item in LearningTargetVersion.objects.select_related("target").filter(
            id__in=frozen_links
        )
    }
    if set(versions) != set(frozen_links):
        raise ValidationError("评价材料引用的学习目标版本不存在。")

    for target_version_id, link in frozen_links.items():
        version = versions[target_version_id]
        if (
            str(version.target.logical_key) != str(link.get("logical_key") or "")
            or version.content_hash != str(link.get("content_hash") or "")
            or version.alignment_status != str(link.get("alignment_status") or "")
            or version.alignment_status != "complete"
            or not version.curriculum_alignments.exists()
        ):
            raise ValidationError("评价材料中的学习目标版本与已发布冻结版本不一致。")
    return versions


def _material_source_id(*, evidence, row: dict, row_index: int, target_version) -> str:
    identity = _canonical_hash(
        {
            "evidence_id": evidence.id,
            "submission_id": str(evidence.submission.submission_id),
            "submission_version": evidence.submission.submission_version,
            "criterion_id": row.get("criterion_id"),
            "ownership": row.get("ownership"),
            "material_type": row.get("material_type"),
            "row_index": row_index,
            "target_version_id": target_version.id,
            "target_version_hash": target_version.content_hash,
        }
    )
    return f"{evidence.submission.submission_id}:{identity[:24]}"


def _material_source_version(*, evidence, target_version) -> str:
    return (
        f"submission-v{evidence.submission.submission_version}:"
        f"target-{target_version.content_hash[:24]}"
    )


def _state_status(individual_rows: list[dict]) -> str:
    if not individual_rows:
        return StudentLearningTargetStateVersion.EvidenceStatus.INSUFFICIENT
    statuses = {str(row.get("status") or "") for row in individual_rows}
    if "available" in statuses:
        # A rubric rating is a useful descriptive record, but until the rubric,
        # raters and task are calibrated it must not become a numeric mastery
        # estimate.  Keep the material visible for an explicit review instead.
        return StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW
    if statuses and statuses.issubset({"not_observed", "not_applicable"}):
        return StudentLearningTargetStateVersion.EvidenceStatus.NOT_OBSERVED
    return StudentLearningTargetStateVersion.EvidenceStatus.INSUFFICIENT


@transaction.atomic
def project_evaluation_submission_materials(*, evidence) -> dict:
    """Project one immutable classroom evaluation into target-level facts.

    Group materials are retained as group facts and are never counted as
    evidence of an individual student's target attainment.  Rubric stars are
    retained in material metadata but are deliberately not converted into a
    target estimate before calibration evidence exists.
    """

    manifest = evidence.material_manifest if isinstance(evidence.material_manifest, list) else []
    if not manifest:
        return {"materials": [], "target_states": []}

    versions = _target_versions(manifest)
    submission = evidence.submission
    session = submission.session
    if session is None or submission.class_group_id is None:
        raise ValidationError("正式评价材料必须属于明确的课堂和班级。")

    materials = []
    rows_by_target: dict[int, list[tuple[dict, UnifiedAssessmentMaterial]]] = defaultdict(list)
    for row_index, row in enumerate(manifest):
        status = MATERIAL_STATUS_MAP.get(str(row.get("status") or ""))
        if status is None:
            raise ValidationError("评价材料包含无法识别的材料状态。")
        criterion_id = str(row.get("criterion_id") or "")
        descriptive_rating = (submission.ratings or {}).get(criterion_id)
        for link in row.get("learning_target_links") or []:
            target_version = versions[int(link["target_version_id"])]
            source_id = _material_source_id(
                evidence=evidence,
                row=row,
                row_index=row_index,
                target_version=target_version,
            )
            source_version = _material_source_version(
                evidence=evidence,
                target_version=target_version,
            )
            existing = UnifiedAssessmentMaterial.objects.filter(
                source_type=EVALUATION_SOURCE_TYPE,
                source_id=source_id,
                source_version=source_version,
                learning_target_version=target_version,
            ).first()
            if existing is not None:
                material = existing
            else:
                is_group = row.get("ownership") == UnifiedAssessmentMaterial.Ownership.GROUP
                material = UnifiedAssessmentMaterial(
                    school=session.school,
                    subject=submission.course.subject,
                    course=submission.course,
                    class_group=submission.class_group,
                    student=None if is_group else submission.target,
                    recorded_by=submission.evaluator,
                    legacy_unmapped=False,
                    learning_target_version=target_version,
                    ownership=(
                        UnifiedAssessmentMaterial.Ownership.GROUP
                        if is_group
                        else UnifiedAssessmentMaterial.Ownership.INDIVIDUAL
                    ),
                    group_reference=(
                        f"classroom_group:{row.get('group_id')}" if is_group else ""
                    ),
                    material_type=str(row.get("material_type") or ""),
                    material_status=status,
                    learning_target_code=target_version.code,
                    source_type=EVALUATION_SOURCE_TYPE,
                    source_id=source_id,
                    source_version=source_version,
                    content={
                        "schema_version": row.get("schema_version"),
                        "evaluation_evidence_id": evidence.id,
                        "evaluation_submission_id": str(submission.submission_id),
                        "evaluation_submission_version": submission.submission_version,
                        "evaluation_type": submission.evaluation_type,
                        "criterion_id": criterion_id,
                        "criterion_code": row.get("criterion_code"),
                        "evaluation_task_codes": list(
                            row.get("evaluation_task_codes") or []
                        ),
                        "participant_student_ids": list(
                            row.get("participant_student_ids") or []
                        ),
                        "material_source": row.get("source"),
                        "not_assessed_reason": row.get("not_assessed_reason"),
                        "missing_reason": row.get("missing_reason"),
                        "descriptive_rubric_rating": descriptive_rating,
                        "rubric_scale": "1-5",
                        "calibration_status": EVALUATION_CALIBRATION_STATUS,
                        "eligible_for_learning_target_estimate": False,
                    },
                    score=None,
                    score_max=None,
                    recorded_at=submission.created_at,
                )
                material.save()
            materials.append(material)
            rows_by_target[target_version.id].append((row, material))

    target_states = []
    for target_version_id, target_rows in sorted(rows_by_target.items()):
        target_version = versions[target_version_id]
        individual_rows = [
            row
            for row, _material in target_rows
            if row.get("ownership") == UnifiedAssessmentMaterial.Ownership.INDIVIDUAL
        ]
        individual_materials = [
            material
            for row, material in target_rows
            if row.get("ownership") == UnifiedAssessmentMaterial.Ownership.INDIVIDUAL
        ]
        group_material_count = sum(
            1
            for row, _material in target_rows
            if row.get("ownership") == UnifiedAssessmentMaterial.Ownership.GROUP
        )
        available_count = sum(
            1 for row in individual_rows if row.get("status") == "available"
        )
        coverage = (
            available_count / len(individual_rows) if individual_rows else 0.0
        )
        state_status = _state_status(individual_rows)
        state_source_version = (
            f"submission-v{submission.submission_version}:"
            f"standard-{evidence.standard_use.content_hash[:12]}:"
            f"target-{target_version.content_hash[:12]}"
        )
        notes = [
            "评价量尺星级尚未完成任务与评分者校准，仅作为描述性评价记录。",
            "该记录不生成学习目标水平估计，需由教师结合后续目标级材料复核。",
        ]
        if group_material_count:
            notes.append(
                f"同一目标另有 {group_material_count} 条小组评价材料；"
                "小组材料未计入个人学习情况覆盖率。"
            )
        state, _created = StudentLearningTargetStateVersion.objects.get_or_create(
            student=submission.target,
            school=session.school,
            class_group=submission.class_group,
            subject=submission.course.subject,
            course=submission.course,
            learning_target_version=target_version,
            legacy_unmapped=False,
            learning_target_code=target_version.code,
            source_type=EVALUATION_SOURCE_TYPE,
            source_id=str(submission.submission_id),
            source_version=state_source_version,
            defaults={
                "learning_target_name": target_version.title,
                "evidence_status": state_status,
                "evidence_coverage": round(coverage, 6),
                "estimate": None,
                "uncertainty": None,
                "material_references": [
                    f"assessment_material:{material.material_id}"
                    for material in individual_materials
                ],
                "observation_notes": notes,
                "is_initial_diagnostic": False,
                "observed_at": submission.created_at,
                "valid_from": submission.created_at,
                "valid_until": submission.created_at
                + timedelta(days=EVALUATION_VALIDITY_DAYS),
            },
        )
        target_states.append(state)

    return {"materials": materials, "target_states": target_states}
