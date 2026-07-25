from __future__ import annotations

from django.db.models import Count, Prefetch, Q
from rest_framework.decorators import api_view, permission_classes

from learning.models import (
    DiagnosticAdministration,
    DiagnosticAdministrationAssignment,
    DiagnosticSubmissionBinding,
)
from learning.services.diagnostic_administrations import (
    DiagnosticAdministrationError,
    availability_status,
    close_diagnostic_administration,
    create_diagnostic_administration,
    diagnostic_completion_status,
    publish_diagnostic_administration,
    replace_diagnostic_assignments,
    update_diagnostic_administration,
)
from school.models import StudentProfile

from .permissions import IsSchoolAdmin, IsStudent
from .responses import fail, ok
from .services import write_audit


def _error(exc: DiagnosticAdministrationError):
    return fail(exc.message, errors=exc.errors, status=exc.status)


def _assignment_row(item: DiagnosticAdministrationAssignment, *, include_completion=False):
    row = {
        "id": item.id,
        "class_group": {
            "id": item.class_group_id,
            "name": item.class_group.name,
            "grade": item.class_group.grade,
        },
        "cohort_role": item.cohort_role,
        "cohort_role_label": item.get_cohort_role_display(),
        "opportunity_status": item.opportunity_status,
        "opportunity_status_label": item.get_opportunity_status_display(),
        "created_at": item.created_at,
    }
    if include_completion:
        bindings = list(getattr(item, "prefetched_bindings", []))
        row["submission_count"] = len(bindings)
        row["scoring_completed_count"] = sum(
            diagnostic_completion_status(item, binding)["scoring"] == "completed"
            for binding in bindings
        )
    return row


def diagnostic_administration_row(
    administration: DiagnosticAdministration,
    *,
    include_assignments: bool = False,
) -> dict:
    version = administration.paper_version
    paper = version.source
    assignments = list(administration.assignments.all()) if include_assignments else []
    return {
        "id": administration.id,
        "school_id": administration.school_id,
        "subject": {
            "id": administration.subject_id,
            "name": administration.subject.name,
            "code": administration.subject.code,
        },
        "course": (
            {"id": administration.course_id, "title": administration.course.title}
            if administration.course_id
            else None
        ),
        "paper_version": {
            "id": version.id,
            "source_id": version.source_id,
            "title": version.title,
            "kind": version.kind,
            "kind_label": paper.get_kind_display(),
            "version_no": version.version_no,
            "content_hash": version.content_hash,
            "published_at": version.published_at,
        },
        "purpose": administration.purpose,
        "purpose_label": administration.get_purpose_display(),
        "batch_code": administration.batch_code,
        "title": administration.title,
        "open_at": administration.open_at,
        "close_at": administration.close_at,
        "status": administration.status,
        "status_label": administration.get_status_display(),
        "availability_status": availability_status(administration),
        "content_hash": administration.content_hash,
        "assignment_count": getattr(
            administration, "assignment_count", len(assignments) if include_assignments else 0
        ),
        "submission_count": getattr(administration, "submission_count", 0),
        "created_by": {
            "id": administration.created_by_id,
            "name": str(administration.created_by),
        },
        "created_at": administration.created_at,
        "updated_at": administration.updated_at,
        "published_by": (
            {"id": administration.published_by_id, "name": str(administration.published_by)}
            if administration.published_by_id
            else None
        ),
        "published_at": administration.published_at,
        "closed_by": (
            {"id": administration.closed_by_id, "name": str(administration.closed_by)}
            if administration.closed_by_id
            else None
        ),
        "closed_at": administration.closed_at,
        "assignments": [
            _assignment_row(item, include_completion=True) for item in assignments
        ]
        if include_assignments
        else None,
    }


def _base_query(school):
    return DiagnosticAdministration.objects.filter(school=school).select_related(
        "school",
        "subject",
        "course",
        "paper_version",
        "paper_version__source",
        "created_by",
        "published_by",
        "closed_by",
    )


def _detail_query(school):
    binding_query = DiagnosticSubmissionBinding.objects.select_related("submission")
    assignment_query = DiagnosticAdministrationAssignment.objects.select_related(
        "class_group"
    ).prefetch_related(
        Prefetch("submission_bindings", queryset=binding_query, to_attr="prefetched_bindings")
    )
    return _base_query(school).prefetch_related(
        Prefetch("assignments", queryset=assignment_query)
    )


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_diagnostic_administrations(request):
    if request.method == "POST":
        try:
            administration = create_diagnostic_administration(
                school=request.user.school,
                actor=request.user,
                payload=request.data,
            )
        except DiagnosticAdministrationError as exc:
            return _error(exc)
        write_audit(
            request,
            "diagnostic_administration.create",
            school=request.user.school,
            target_type="diagnostic_administration",
            target_id=administration.id,
            detail={
                "batch_code": administration.batch_code,
                "paper_version_id": administration.paper_version_id,
            },
        )
        administration = _detail_query(request.user.school).get(pk=administration.pk)
        return ok(
            diagnostic_administration_row(administration, include_assignments=True),
            "诊断实施草稿已创建。",
            status=201,
        )

    rows = _base_query(request.user.school).annotate(
        assignment_count=Count("assignments", distinct=True),
        submission_count=Count("submission_bindings", distinct=True),
    )
    status_value = str(request.GET.get("status") or "").strip()
    purpose = str(request.GET.get("purpose") or "").strip()
    subject_id = str(request.GET.get("subject") or "").strip()
    query = str(request.GET.get("q") or "").strip()
    if status_value:
        rows = rows.filter(status=status_value)
    if purpose:
        rows = rows.filter(purpose=purpose)
    if subject_id.isdigit():
        rows = rows.filter(subject_id=int(subject_id))
    if query:
        rows = rows.filter(
            Q(title__icontains=query)
            | Q(batch_code__icontains=query)
            | Q(paper_version__title__icontains=query)
        )
    return ok([diagnostic_administration_row(item) for item in rows[:300]])


@api_view(["GET", "PATCH"])
@permission_classes([IsSchoolAdmin])
def school_admin_diagnostic_administration_detail(request, pk):
    administration = _detail_query(request.user.school).filter(pk=pk).first()
    if administration is None:
        return fail("诊断实施批次不存在。", status=404)
    if request.method == "GET":
        return ok(diagnostic_administration_row(administration, include_assignments=True))
    try:
        administration = update_diagnostic_administration(
            administration_id=pk,
            school=request.user.school,
            actor=request.user,
            payload=request.data,
        )
    except DiagnosticAdministrationError as exc:
        return _error(exc)
    write_audit(
        request,
        "diagnostic_administration.update",
        school=request.user.school,
        target_type="diagnostic_administration",
        target_id=administration.id,
    )
    administration = _detail_query(request.user.school).get(pk=pk)
    return ok(
        diagnostic_administration_row(administration, include_assignments=True),
        "诊断实施草稿已更新。",
    )


@api_view(["PUT"])
@permission_classes([IsSchoolAdmin])
def school_admin_diagnostic_administration_assignments(request, pk):
    try:
        administration = replace_diagnostic_assignments(
            administration_id=pk,
            school=request.user.school,
            payload=request.data,
        )
    except DiagnosticAdministrationError as exc:
        return _error(exc)
    write_audit(
        request,
        "diagnostic_administration.assignments.replace",
        school=request.user.school,
        target_type="diagnostic_administration",
        target_id=administration.id,
        detail={"assignment_count": administration.assignments.count()},
    )
    administration = _detail_query(request.user.school).get(pk=pk)
    return ok(
        diagnostic_administration_row(administration, include_assignments=True),
        "班级、实验角色与评价机会安排已保存。",
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_diagnostic_administration_publish(request, pk):
    try:
        administration = publish_diagnostic_administration(
            administration_id=pk,
            school=request.user.school,
            actor=request.user,
        )
    except DiagnosticAdministrationError as exc:
        return _error(exc)
    write_audit(
        request,
        "diagnostic_administration.publish",
        school=request.user.school,
        target_type="diagnostic_administration",
        target_id=administration.id,
        detail={
            "content_hash": administration.content_hash,
            "paper_version_id": administration.paper_version_id,
        },
    )
    administration = _detail_query(request.user.school).get(pk=pk)
    return ok(
        diagnostic_administration_row(administration, include_assignments=True),
        "诊断实施批次已发布，版本与班级指派已经冻结。",
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_diagnostic_administration_close(request, pk):
    try:
        administration = close_diagnostic_administration(
            administration_id=pk,
            school=request.user.school,
            actor=request.user,
        )
    except DiagnosticAdministrationError as exc:
        return _error(exc)
    write_audit(
        request,
        "diagnostic_administration.close",
        school=request.user.school,
        target_type="diagnostic_administration",
        target_id=administration.id,
    )
    administration = _detail_query(request.user.school).get(pk=pk)
    return ok(
        diagnostic_administration_row(administration, include_assignments=True),
        "诊断实施批次已关闭。",
    )


def student_assigned_administrations(student, *, subject_id=None, include_closed=True):
    profile = StudentProfile.objects.filter(user=student).first()
    if profile is None or not profile.class_group_id:
        return DiagnosticAdministrationAssignment.objects.none()
    rows = (
        DiagnosticAdministrationAssignment.objects.filter(
            class_group_id=profile.class_group_id,
            administration__school_id=student.school_id,
            administration__status__in=(
                [
                    DiagnosticAdministration.Status.PUBLISHED,
                    DiagnosticAdministration.Status.CLOSED,
                ]
                if include_closed
                else [DiagnosticAdministration.Status.PUBLISHED]
            ),
        )
        .select_related(
            "class_group",
            "administration",
            "administration__subject",
            "administration__course",
            "administration__paper_version",
            "administration__paper_version__source",
        )
        .prefetch_related(
            Prefetch(
                "submission_bindings",
                queryset=DiagnosticSubmissionBinding.objects.filter(student=student)
                .select_related("submission")
                .order_by("-attempt_no"),
                to_attr="student_bindings",
            )
        )
        .order_by("-administration__published_at", "-administration_id")
    )
    if subject_id:
        rows = rows.filter(administration__subject_id=subject_id)
    return rows


def student_diagnostic_assignment_row(assignment, *, include_paper=False):
    administration = assignment.administration
    bindings = list(getattr(assignment, "student_bindings", []))
    binding = bindings[0] if bindings else None
    state = availability_status(administration)
    if state != "open":
        return {
            "administration_id": administration.id,
            "availability_status": state,
            "open_at": administration.open_at,
            "close_at": administration.close_at,
            "submission_allowed": False,
            "completion": diagnostic_completion_status(assignment, binding),
        }
    row = {
        "administration_id": administration.id,
        "batch_code": administration.batch_code,
        "title": administration.title,
        "purpose": administration.purpose,
        "purpose_label": administration.get_purpose_display(),
        "subject": {
            "id": administration.subject_id,
            "name": administration.subject.name,
            "code": administration.subject.code,
        },
        "course": (
            {"id": administration.course_id, "title": administration.course.title}
            if administration.course_id
            else None
        ),
        "opportunity_status": assignment.opportunity_status,
        "availability_status": state,
        "open_at": administration.open_at,
        "close_at": administration.close_at,
        "submission_allowed": (
            assignment.opportunity_status
            == DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED
        ),
        "paper_version": {
            "id": administration.paper_version_id,
            "source_id": administration.paper_version.source_id,
            "version_no": administration.paper_version.version_no,
            "content_hash": administration.paper_version.content_hash,
        },
        "completion": diagnostic_completion_status(assignment, binding),
        "latest_submission_id": binding.submission_id if binding else None,
    }
    if include_paper:
        from .pretest_views import _student_pretest_version_row

        paper = _student_pretest_version_row(
            administration.paper_version.source,
            administration.paper_version,
        )
        paper["administration"] = row.copy()
        paper["administration_id"] = administration.id
        row["paper"] = paper
    return row


@api_view(["GET"])
@permission_classes([IsStudent])
def student_diagnostic_administrations(request):
    subject_id = request.GET.get("subject")
    try:
        subject_id = int(subject_id) if subject_id else None
    except (TypeError, ValueError):
        return fail("学科参数不正确。", status=400)
    rows = student_assigned_administrations(
        request.user, subject_id=subject_id, include_closed=True
    )
    return ok([student_diagnostic_assignment_row(item) for item in rows])


@api_view(["GET"])
@permission_classes([IsStudent])
def student_diagnostic_administration_detail(request, pk):
    assignment = student_assigned_administrations(
        request.user, include_closed=True
    ).filter(administration_id=pk).first()
    if assignment is None:
        return fail("诊断实施批次不存在或未指派给当前班级。", status=404)
    return ok(student_diagnostic_assignment_row(assignment, include_paper=True))
