from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from courses.models import Course, Subject
from learning.models import (
    DiagnosticAdministration,
    DiagnosticAdministrationAssignment,
    DiagnosticSubmissionBinding,
    PretestPaper,
    PretestPaperVersion,
    PretestSubmission,
)
from learning_analytics.models import LearningTargetVersion
from school.models import ClassGroup, StudentProfile


BATCH_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,63}$")


class DiagnosticAdministrationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        errors: dict | None = None,
        status: int = 400,
    ) -> None:
        self.message = message
        self.errors = errors or {}
        self.status = status
        super().__init__(message)


def _validation_error(exc: ValidationError, message: str) -> DiagnosticAdministrationError:
    if hasattr(exc, "message_dict"):
        errors = exc.message_dict
    else:
        errors = {"non_field_errors": exc.messages}
    return DiagnosticAdministrationError(message, errors=errors)


def _parse_datetime(value, field: str):
    if value in {None, ""}:
        return None
    if hasattr(value, "tzinfo"):
        result = value
    else:
        result = parse_datetime(str(value).strip())
    if result is None:
        raise DiagnosticAdministrationError(
            "诊断实施时间格式不正确。",
            errors={field: ["请使用带日期和时间的 ISO 8601 格式。"]},
        )
    if timezone.is_naive(result):
        result = timezone.make_aware(result, timezone.get_current_timezone())
    return result


def _school_subject(school, value) -> Subject:
    try:
        subject_id = int(value)
    except (TypeError, ValueError):
        subject_id = 0
    subject = Subject.objects.filter(pk=subject_id, school=school, is_active=True).first()
    if subject is None:
        raise DiagnosticAdministrationError(
            "学科不存在或不属于当前学校。",
            errors={"subject_id": ["请选择当前学校的有效学科。"]},
            status=404,
        )
    return subject


def _school_course(school, subject: Subject, value) -> Course | None:
    if value in {None, ""}:
        return None
    try:
        course_id = int(value)
    except (TypeError, ValueError):
        course_id = 0
    course = Course.objects.select_related("subject", "teacher").filter(
        pk=course_id,
        subject=subject,
        subject__school=school,
    ).first()
    if course is None:
        raise DiagnosticAdministrationError(
            "课程不存在或与所选学科不一致。",
            errors={"course_id": ["请选择当前学校、当前学科下的课程。"]},
            status=404,
        )
    return course


def _paper_version(school, subject: Subject, value) -> PretestPaperVersion:
    try:
        version_id = int(value)
    except (TypeError, ValueError):
        version_id = 0
    version = PretestPaperVersion.objects.select_related("source", "source__subject").filter(
        pk=version_id,
        source__school=school,
        source__subject=subject,
    ).first()
    if version is None:
        raise DiagnosticAdministrationError(
            "已发布的诊断版本不存在或与所选学科不一致。",
            errors={"paper_version_id": ["请选择当前学校、当前学科的已发布版本。"]},
            status=404,
        )
    return version


def _snapshot_target_course(
    *, school, subject: Subject, version: PretestPaperVersion
) -> Course | None:
    formal_rows = [
        row
        for row in (version.question_snapshot or [])
        if isinstance(row, dict) and not bool(row.get("legacy_unmapped", True))
    ]
    if not formal_rows:
        return None
    target_ids = set()
    for index, row in enumerate(formal_rows):
        try:
            target_ids.add(int(row.get("learning_target_version_id")))
        except (TypeError, ValueError):
            raise DiagnosticAdministrationError(
                "诊断版本中的正式学习目标身份不完整。",
                errors={
                    "paper_version_id": [
                        f"第 {index + 1} 项任务缺少冻结学习目标版本，请重新发布诊断版本。"
                    ]
                },
                status=409,
            )
    targets = {
        item.id: item
        for item in LearningTargetVersion.objects.select_related("target")
        .prefetch_related("curriculum_alignments")
        .filter(pk__in=target_ids)
    }
    course_ids = set()
    errors = []
    for index, row in enumerate(formal_rows):
        target = targets.get(int(row["learning_target_version_id"]))
        valid = (
            target is not None
            and target.content_hash == str(row.get("learning_target_version_hash") or "")
            and target.code == str(row.get("learning_target_code") or "")
            and target.title == str(row.get("learning_target_name") or "")
            and target.alignment_status == "complete"
            and bool(target.curriculum_alignments.all())
            and target.target.school_id == school.id
            and target.target.subject_id == subject.id
        )
        if not valid:
            errors.append(f"第 {index + 1} 项任务的学习目标版本或课标依据校验失败。")
            continue
        course_ids.add(target.target.course_id)
    if errors:
        raise DiagnosticAdministrationError(
            "诊断版本的学习目标冻结链不完整。",
            errors={"paper_version_id": errors},
            status=409,
        )
    if len(course_ids) != 1:
        raise DiagnosticAdministrationError(
            "同一诊断实施批次只能对应一门具体课程的学习目标。",
            errors={"paper_version_id": ["发布版本包含多个课程范围的学习目标。"]},
            status=409,
        )
    return Course.objects.select_related("subject", "teacher").get(pk=course_ids.pop())


def _validate_formal_literacy_target_coverage(
    *,
    version: PretestPaperVersion,
    purpose: str,
    inferred_course: Course | None,
) -> None:
    """Prevent a new formal subject-literacy administration from going legacy.

    Attitude questionnaires may use questionnaire dimensions, and pilot batches
    may intentionally test draft constructs.  Entry diagnostics and research
    pre/post measurements based on a literacy tool, however, must freeze every
    task to a curriculum-aligned learning-target version.
    """

    if (
        version.kind != PretestPaper.Kind.LITERACY
        or purpose == DiagnosticAdministration.Purpose.PILOT
    ):
        return
    rows = [row for row in (version.question_snapshot or []) if isinstance(row, dict)]
    # Versions published before the target-version migration did not contain a
    # mapping marker at all.  They remain readable for historical traceability,
    # but the absence of an explicit marker is itself legacy/unmapped evidence:
    # a newly created or newly published formal administration must never turn
    # such a historical snapshot back into a current diagnostic instrument.
    unmapped_positions = [
        index + 1
        for index, row in enumerate(rows)
        if bool(row.get("legacy_unmapped", True))
        or not row.get("learning_target_version_id")
        or not row.get("learning_target_version_hash")
    ]
    if not rows or unmapped_positions or inferred_course is None:
        details = (
            f"第 {', '.join(map(str, unmapped_positions))} 项评价任务未绑定正式学习目标版本。"
            if unmapped_positions
            else "发布版本未形成可追溯的正式学习目标。"
        )
        raise DiagnosticAdministrationError(
            "正式素养诊断必须逐项对应课标依据完整、不可变的学习目标版本。",
            errors={
                "paper_version_id": [
                    f"{details} 历史未映射任务仅可用于试测；学习支持问卷不进入正式目标情况估计。"
                ]
            },
            status=409,
        )


def _normalized_draft_values(school, actor, payload: dict, instance=None) -> dict:
    def value(name, current=None):
        return payload[name] if name in payload else current

    subject = _school_subject(
        school,
        value("subject_id", getattr(instance, "subject_id", None)),
    )
    version = _paper_version(
        school,
        subject,
        value("paper_version_id", getattr(instance, "paper_version_id", None)),
    )
    inferred_course = _snapshot_target_course(
        school=school,
        subject=subject,
        version=version,
    )
    raw_course_id = value("course_id", getattr(instance, "course_id", None))
    course = _school_course(school, subject, raw_course_id)
    if inferred_course is not None:
        if course is not None and course.id != inferred_course.id:
            raise DiagnosticAdministrationError(
                "诊断实施课程与冻结学习目标版本不一致。",
                errors={"course_id": ["课程必须与学习目标版本的适用课程一致。"]},
                status=409,
            )
        course = inferred_course
    purpose = str(value("purpose", getattr(instance, "purpose", "")) or "").strip()
    if purpose not in DiagnosticAdministration.Purpose.values:
        raise DiagnosticAdministrationError(
            "诊断实施用途不正确。",
            errors={"purpose": ["请选择学习起点诊断、教育实验前测、教育实验后测或试测。"]},
        )
    _validate_formal_literacy_target_coverage(
        version=version,
        purpose=purpose,
        inferred_course=inferred_course,
    )
    batch_code = str(value("batch_code", getattr(instance, "batch_code", "")) or "").strip()
    if not BATCH_CODE_PATTERN.fullmatch(batch_code):
        raise DiagnosticAdministrationError(
            "批次编码格式不正确。",
            errors={"batch_code": ["请使用 3–64 位字母、数字、点号、冒号、短横线或下划线。"]},
        )
    title = str(value("title", getattr(instance, "title", "")) or "").strip()
    if not 2 <= len(title) <= 160:
        raise DiagnosticAdministrationError(
            "诊断实施名称格式不正确。",
            errors={"title": ["请输入 2–160 个字符的实施名称。"]},
        )
    open_at = _parse_datetime(
        value("open_at", getattr(instance, "open_at", None)), "open_at"
    )
    close_at = _parse_datetime(
        value("close_at", getattr(instance, "close_at", None)), "close_at"
    )
    return {
        "school": school,
        "subject": subject,
        "course": course,
        "paper_version": version,
        "purpose": purpose,
        "batch_code": batch_code,
        "title": title,
        "open_at": open_at,
        "close_at": close_at,
        "created_by": actor if instance is None else instance.created_by,
    }


@transaction.atomic
def create_diagnostic_administration(*, school, actor, payload: dict) -> DiagnosticAdministration:
    values = _normalized_draft_values(school, actor, payload)
    administration = DiagnosticAdministration(**values)
    try:
        administration.save()
    except ValidationError as exc:
        raise _validation_error(exc, "诊断实施草稿校验失败。") from exc
    except IntegrityError as exc:
        raise DiagnosticAdministrationError(
            "该批次编码已存在。",
            errors={"batch_code": ["同一学校内的批次编码不能重复。"]},
            status=409,
        ) from exc
    return administration


def _check_expected_updated_at(administration, expected) -> None:
    if not expected:
        return
    parsed = _parse_datetime(expected, "expected_updated_at")
    if abs((administration.updated_at - parsed).total_seconds()) > 0.001:
        raise DiagnosticAdministrationError(
            "该诊断实施草稿已被其他操作更新，请刷新后重试。",
            errors={"expected_updated_at": ["草稿版本已变化。"]},
            status=409,
        )


@transaction.atomic
def update_diagnostic_administration(
    *, administration_id: int, school, actor, payload: dict
) -> DiagnosticAdministration:
    administration = (
        DiagnosticAdministration.objects.select_for_update()
        .filter(pk=administration_id, school=school)
        .first()
    )
    if administration is None:
        raise DiagnosticAdministrationError("诊断实施批次不存在。", status=404)
    if administration.status != DiagnosticAdministration.Status.DRAFT:
        raise DiagnosticAdministrationError(
            "已发布的诊断实施批次不可修改。", status=409
        )
    _check_expected_updated_at(administration, payload.get("expected_updated_at"))
    values = _normalized_draft_values(school, actor, payload, administration)
    for field, item in values.items():
        setattr(administration, field, item)
    try:
        administration.save()
    except ValidationError as exc:
        raise _validation_error(exc, "诊断实施草稿校验失败。") from exc
    except IntegrityError as exc:
        raise DiagnosticAdministrationError(
            "该批次编码已存在。",
            errors={"batch_code": ["同一学校内的批次编码不能重复。"]},
            status=409,
        ) from exc
    return administration


@transaction.atomic
def replace_diagnostic_assignments(
    *, administration_id: int, school, payload: dict
) -> DiagnosticAdministration:
    administration = (
        DiagnosticAdministration.objects.select_for_update()
        .filter(pk=administration_id, school=school)
        .first()
    )
    if administration is None:
        raise DiagnosticAdministrationError("诊断实施批次不存在。", status=404)
    if administration.status != DiagnosticAdministration.Status.DRAFT:
        raise DiagnosticAdministrationError(
            "已发布的班级、实验角色与评价机会安排不可修改。", status=409
        )
    _check_expected_updated_at(administration, payload.get("expected_updated_at"))
    rows = payload.get("assignments")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise DiagnosticAdministrationError(
            "请设置 1–200 个班级指派。",
            errors={"assignments": ["班级指派必须是非空列表。"]},
        )
    normalized: list[tuple[ClassGroup, str, str]] = []
    seen: set[int] = set()
    errors: dict[str, list[str]] = {}
    for index, row in enumerate(rows):
        key = f"assignments.{index}"
        if not isinstance(row, dict):
            errors[key] = ["班级指派必须是对象。"]
            continue
        try:
            class_id = int(row.get("class_group_id"))
        except (TypeError, ValueError):
            class_id = 0
        class_group = ClassGroup.objects.filter(pk=class_id, school=school).first()
        if class_group is None:
            errors[key] = ["班级不存在或不属于当前学校。"]
            continue
        if class_id in seen:
            errors[key] = ["同一班级不能重复指派。"]
            continue
        seen.add(class_id)
        cohort_role = str(
            row.get("cohort_role")
            or DiagnosticAdministrationAssignment.CohortRole.UNASSIGNED
        ).strip()
        opportunity_status = str(
            row.get("opportunity_status")
            or DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED
        ).strip()
        if cohort_role not in DiagnosticAdministrationAssignment.CohortRole.values:
            errors[key] = ["实验角色不正确。"]
            continue
        if opportunity_status not in DiagnosticAdministrationAssignment.OpportunityStatus.values:
            errors[key] = ["评价机会状态不正确。"]
            continue
        normalized.append((class_group, cohort_role, opportunity_status))
    if errors:
        raise DiagnosticAdministrationError(
            "班级指派校验失败。", errors=errors
        )
    administration.assignments.all().delete()
    for class_group, cohort_role, opportunity_status in normalized:
        assignment = DiagnosticAdministrationAssignment(
            administration=administration,
            class_group=class_group,
            cohort_role=cohort_role,
            opportunity_status=opportunity_status,
        )
        try:
            assignment.save()
        except ValidationError as exc:
            raise _validation_error(exc, "班级指派校验失败。") from exc
    # Make updated_at an optimistic concurrency token for both aggregate parts.
    administration.save(update_fields=["updated_at"])
    return administration


@transaction.atomic
def publish_diagnostic_administration(
    *, administration_id: int, school, actor
) -> DiagnosticAdministration:
    administration = (
        DiagnosticAdministration.objects.select_for_update()
        .select_related("paper_version", "paper_version__source")
        .filter(pk=administration_id, school=school)
        .first()
    )
    if administration is None:
        raise DiagnosticAdministrationError("诊断实施批次不存在。", status=404)
    if administration.status != DiagnosticAdministration.Status.DRAFT:
        raise DiagnosticAdministrationError(
            "诊断实施批次已经发布或关闭。", status=409
        )
    inferred_course = _snapshot_target_course(
        school=administration.school,
        subject=administration.subject,
        version=administration.paper_version,
    )
    _validate_formal_literacy_target_coverage(
        version=administration.paper_version,
        purpose=administration.purpose,
        inferred_course=inferred_course,
    )
    if inferred_course is not None and administration.course_id != inferred_course.id:
        raise DiagnosticAdministrationError(
            "诊断实施课程与冻结学习目标版本不一致。",
            errors={"course_id": ["请重新建立实施批次并使用学习目标所属课程。"]},
            status=409,
        )
    assignments = list(
        administration.assignments.select_for_update()
        .select_related("class_group")
        .order_by("class_group_id")
    )
    if not assignments:
        raise DiagnosticAdministrationError(
            "发布前必须设置班级指派。",
            errors={"assignments": ["至少设置一个班级。"]},
        )
    if not any(
        item.opportunity_status
        == DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED
        for item in assignments
    ):
        raise DiagnosticAdministrationError(
            "发布前至少应为一个班级提供评价机会。",
            errors={"assignments": ["不能全部设置为未提供评价机会。"]},
        )
    if administration.purpose in {
        DiagnosticAdministration.Purpose.RESEARCH_PRETEST,
        DiagnosticAdministration.Purpose.RESEARCH_POSTTEST,
    }:
        offered_roles = {
            item.cohort_role
            for item in assignments
            if item.opportunity_status
            == DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED
        }
        required = {
            DiagnosticAdministrationAssignment.CohortRole.EXPERIMENT,
            DiagnosticAdministrationAssignment.CohortRole.CONTROL,
        }
        if not required.issubset(offered_roles):
            raise DiagnosticAdministrationError(
                "教育实验批次必须同时包含已提供评价机会的实验班和对照班。",
                errors={"assignments": ["实验班与对照班必须绑定同一诊断版本。"]},
            )
    now = timezone.now()
    if administration.close_at and administration.close_at <= now:
        raise DiagnosticAdministrationError(
            "关闭时间已经过去，不能发布该批次。",
            errors={"close_at": ["请调整草稿中的实施时间。"]},
            status=409,
        )
    snapshot = [
        {
            "class_group_id": item.class_group_id,
            "cohort_role": item.cohort_role,
            "opportunity_status": item.opportunity_status,
        }
        for item in assignments
    ]
    administration.status = DiagnosticAdministration.Status.PUBLISHED
    administration.published_by = actor
    administration.published_at = now
    administration.content_hash = administration.expected_content_hash(snapshot)
    try:
        administration.save()
    except ValidationError as exc:
        raise _validation_error(exc, "诊断实施批次发布校验失败。") from exc
    return administration


@transaction.atomic
def close_diagnostic_administration(
    *, administration_id: int, school, actor
) -> DiagnosticAdministration:
    administration = (
        DiagnosticAdministration.objects.select_for_update()
        .filter(pk=administration_id, school=school)
        .first()
    )
    if administration is None:
        raise DiagnosticAdministrationError("诊断实施批次不存在。", status=404)
    if administration.status != DiagnosticAdministration.Status.PUBLISHED:
        raise DiagnosticAdministrationError(
            "只有正在实施的已发布批次可以关闭。", status=409
        )
    administration.status = DiagnosticAdministration.Status.CLOSED
    administration.closed_by = actor
    administration.closed_at = timezone.now()
    try:
        administration.save()
    except ValidationError as exc:
        raise _validation_error(exc, "诊断实施批次关闭失败。") from exc
    return administration


def availability_status(administration: DiagnosticAdministration, *, at=None) -> str:
    at = at or timezone.now()
    if administration.status == DiagnosticAdministration.Status.CLOSED:
        return "closed"
    if administration.status != DiagnosticAdministration.Status.PUBLISHED:
        return "draft"
    if administration.open_at and at < administration.open_at:
        return "scheduled"
    if administration.close_at and at >= administration.close_at:
        return "closed"
    return "open"


@dataclass(frozen=True)
class StudentDiagnosticContext:
    administration: DiagnosticAdministration
    assignment: DiagnosticAdministrationAssignment
    profile: StudentProfile
    existing_binding: DiagnosticSubmissionBinding | None = None


@transaction.atomic
def prepare_student_diagnostic_submission(
    *, administration_id: int, student, idempotency_key: str
) -> StudentDiagnosticContext:
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 128:
        raise DiagnosticAdministrationError(
            "提交缺少有效的幂等标识。",
            errors={"idempotency_key": ["请携带 1–128 个字符的本次提交标识。"]},
        )
    administration = (
        DiagnosticAdministration.objects.select_for_update()
        .select_related(
            "school",
            "subject",
            "course",
            "paper_version",
            "paper_version__source",
        )
        .filter(pk=administration_id, school_id=student.school_id)
        .first()
    )
    if administration is None:
        raise DiagnosticAdministrationError("诊断实施批次不存在。", status=404)
    state = availability_status(administration)
    if state != "open":
        label = {"scheduled": "尚未开放", "closed": "已经关闭", "draft": "尚未发布"}.get(
            state, "当前不可提交"
        )
        raise DiagnosticAdministrationError(f"该诊断实施批次{label}。", status=409)
    profile = StudentProfile.objects.select_for_update().filter(user=student).first()
    if profile is None or not profile.class_group_id:
        raise DiagnosticAdministrationError(
            "请先完成班级信息确认。", status=409
        )
    assignment = (
        DiagnosticAdministrationAssignment.objects.select_for_update()
        .filter(administration=administration, class_group_id=profile.class_group_id)
        .first()
    )
    if assignment is None:
        raise DiagnosticAdministrationError(
            "当前班级未被指派参加该诊断实施批次。", status=403
        )
    if assignment.opportunity_status != DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED:
        raise DiagnosticAdministrationError(
            "本班级未获得本次评价机会，学生无需提交。", status=403
        )
    existing = DiagnosticSubmissionBinding.objects.select_related("submission").filter(
        administration=administration,
        student=student,
        idempotency_key=key,
    ).first()
    return StudentDiagnosticContext(administration, assignment, profile, existing)


@transaction.atomic
def bind_diagnostic_submission(
    *,
    context: StudentDiagnosticContext,
    submission: PretestSubmission,
    idempotency_key: str,
    request_hash: str,
) -> tuple[DiagnosticSubmissionBinding, bool]:
    administration = DiagnosticAdministration.objects.select_for_update().get(
        pk=context.administration.pk
    )
    existing = DiagnosticSubmissionBinding.objects.select_related("submission").filter(
        administration=administration,
        student=context.profile.user,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        # The caller has already staged a new immutable submission in a nested
        # transaction.  Returning the old binding would commit that new row as
        # an unbound orphan.  Surface a database-style conflict instead so the
        # caller's savepoint rolls the staged submission back, then let the
        # caller compare request_hash and replay the existing binding safely.
        raise IntegrityError("diagnostic idempotency key is already bound")
    binding = DiagnosticSubmissionBinding(
        administration=administration,
        assignment=context.assignment,
        submission=submission,
        student=context.profile.user,
        attempt_no=submission.attempt_no,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    try:
        binding.save()
    except ValidationError as exc:
        raise _validation_error(exc, "诊断提交与实施批次绑定失败。") from exc
    return binding, True


def diagnostic_completion_status(
    assignment: DiagnosticAdministrationAssignment,
    binding: DiagnosticSubmissionBinding | None,
) -> dict:
    if assignment.opportunity_status == DiagnosticAdministrationAssignment.OpportunityStatus.NOT_OFFERED:
        return {
            "submission": "not_required",
            "scoring": "not_applicable",
            "course_access": "exempt",
            "exception": "not_offered",
        }
    if binding is None:
        return {
            "submission": "pending",
            "scoring": "not_started",
            "course_access": "deferred",
            "exception": "",
        }
    submission = binding.submission
    if submission.opportunity_status in {
        PretestSubmission.OpportunityStatus.MISSING,
        PretestSubmission.OpportunityStatus.DEVICE_ISSUE,
    }:
        return {
            "submission": "reported",
            "scoring": "not_applicable",
            "course_access": "deferred",
            "exception": submission.opportunity_status,
        }
    pending_review = any(
        isinstance(item, dict) and item.get("evidence_status") == "pending_review"
        for item in (submission.target_results or [])
    )
    return {
        "submission": "completed",
        "scoring": "pending_review" if pending_review else "completed",
        "course_access": "eligible",
        "exception": "",
    }
