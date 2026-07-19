from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsSchoolAdmin
from api.responses import fail, ok
from courses.models import Course
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationScope,
    EvaluationReviewStatus,
    EvaluationStandard,
    EvaluationDimension,
)
from learning_analytics.services.evaluation import (
    THINKING_REQUIREMENT_VALUES,
    publish_plan,
    publish_standard,
)

from .evaluation_serializers import (
    EvaluationPlanWriteSerializer,
    EvaluationStandardWriteSerializer,
)


def _validation_errors(exc: DjangoValidationError) -> dict[str, list[str]]:
    if hasattr(exc, "message_dict"):
        return {
            key: [str(message) for message in messages]
            for key, messages in exc.message_dict.items()
        }
    return {"non_field_errors": [str(message) for message in exc.messages]}


def _version_summary(version) -> dict | None:
    if version is None:
        return None
    return {
        "id": version.id,
        "version_no": version.version_no,
        "content_hash": version.content_hash,
        "review_status": version.review_status,
        "review_status_label": version.get_review_status_display(),
        "published_by": version.published_by.display_name
        or version.published_by.username,
        "published_at": version.published_at,
    }


def _plan_row(plan: EvaluationPlan, *, detail: bool = False) -> dict:
    latest = next(iter(getattr(plan, "prefetched_versions", [])), None)
    if latest is None and detail:
        latest = plan.versions.select_related("published_by").order_by("-version_no").first()
    row = {
        "id": plan.id,
        "title": plan.title,
        "subject": {"id": plan.subject_id, "name": plan.subject.name},
        "course": (
            {"id": plan.course_id, "title": plan.course.title}
            if plan.course_id
            else None
        ),
        "scope": plan.scope,
        "scope_label": plan.get_scope_display(),
        "content_version": plan.content_version,
        "goal_count": len(plan.learning_goals),
        "basis_count": len(plan.evaluation_basis),
        "task_count": len(plan.learning_tasks),
        "review_status": plan.review_status,
        "review_status_label": plan.get_review_status_display(),
        "latest_version": _version_summary(latest),
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }
    if detail:
        row.update(
            {
                "target_students": plan.target_students,
                "learning_goal": plan.learning_goal,
                "learning_goals": plan.learning_goals,
                "evaluation_basis": plan.evaluation_basis,
                "learning_tasks": plan.learning_tasks,
                "content_scope": plan.content_scope,
                "thinking_requirements": plan.thinking_requirements,
                "support_options": plan.support_options,
                "scoring_rules": plan.scoring_rules,
                "follow_up_suggestion": plan.follow_up_suggestion,
                "versions": [
                    _version_summary(version)
                    for version in plan.versions.select_related("published_by").order_by("-version_no")
                ],
            }
        )
    return row


def _standard_row(standard: EvaluationStandard, *, detail: bool = False) -> dict:
    latest = next(iter(getattr(standard, "prefetched_versions", [])), None)
    if latest is None and detail:
        latest = standard.versions.select_related("published_by").order_by("-version_no").first()
    row = {
        "id": standard.id,
        "title": standard.title,
        "plan": {
            "id": standard.plan_id,
            "title": standard.plan.title,
        },
        "subject": {"id": standard.subject_id, "name": standard.subject.name},
        "course": (
            {"id": standard.course_id, "title": standard.course.title}
            if standard.course_id
            else None
        ),
        "scope": standard.scope,
        "scope_label": standard.get_scope_display(),
        "evaluation_target": standard.evaluation_target,
        "criterion_count": len(standard.criteria),
        "review_status": standard.review_status,
        "review_status_label": standard.get_review_status_display(),
        "latest_version": _version_summary(latest),
        "created_at": standard.created_at,
        "updated_at": standard.updated_at,
    }
    if detail:
        row.update(
            {
                "criteria": standard.criteria,
                "versions": [
                    _version_summary(version)
                    for version in standard.versions.select_related("published_by").order_by("-version_no")
                ],
            }
        )
    return row


def _school_plans(request):
    return EvaluationPlan.objects.filter(
        school=request.user.school,
    ).select_related("subject", "course")


def _school_standards(request):
    return EvaluationStandard.objects.filter(
        school=request.user.school,
    ).select_related("subject", "course", "plan")


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def evaluation_options(request):
    courses = list(
        Course.objects.filter(
            subject__school=request.user.school,
        )
        .select_related("subject")
        .order_by("subject__name", "title")
    )
    return ok(
        {
            "courses": [
                {
                    "id": course.id,
                    "title": course.title,
                    "subject": {
                        "id": course.subject_id,
                        "name": course.subject.name,
                    },
                    "is_active": course.is_active,
                }
                for course in courses
            ],
            "scopes": [
                {
                    "value": value,
                    "label": label,
                    "enabled": value == EvaluationScope.COURSE,
                }
                for value, label in EvaluationScope.choices
            ],
            "review_statuses": [
                {"value": value, "label": label}
                for value, label in EvaluationReviewStatus.choices
            ],
            "dimensions": [
                {"value": value, "label": label}
                for value, label in EvaluationDimension.choices
            ],
            "thinking_requirements": [
                {"value": value, "label": label}
                for value, label in (
                    ("remember", "记忆"),
                    ("understand", "理解"),
                    ("apply", "应用"),
                    ("analyze", "分析"),
                    ("evaluate", "评价"),
                    ("create", "创造"),
                )
                if value in THINKING_REQUIREMENT_VALUES
            ],
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def plans(request):
    if request.method == "GET":
        rows = _school_plans(request).prefetch_related("versions__published_by")
        for row in rows:
            row.prefetched_versions = sorted(
                row.versions.all(),
                key=lambda version: version.version_no,
                reverse=True,
            )
        return ok([_plan_row(row) for row in rows])

    serializer = EvaluationPlanWriteSerializer(
        data=request.data,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("评价方案未保存。", errors=serializer.errors, status=400)
    plan = serializer.save()
    return ok(_plan_row(plan, detail=True), "评价方案已创建。", status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsSchoolAdmin])
def plan_detail(request, pk: int):
    plan = _school_plans(request).filter(pk=pk).first()
    if plan is None:
        return fail("评价方案不存在或无权访问。", status=404)
    if request.method == "GET":
        return ok(_plan_row(plan, detail=True))
    serializer = EvaluationPlanWriteSerializer(
        plan,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("评价方案未保存。", errors=serializer.errors, status=400)
    plan = serializer.save()
    return ok(_plan_row(plan, detail=True), "评价方案已保存。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def publish_plan_view(request, pk: int):
    plan = _school_plans(request).filter(pk=pk).first()
    if plan is None:
        return fail("评价方案不存在或无权访问。", status=404)
    try:
        result = publish_plan(plan, published_by=request.user)
    except DjangoValidationError as exc:
        return fail("评价方案发布前检查未通过。", errors=_validation_errors(exc), status=400)
    message = "已发布新的评价方案版本。" if result.created else "当前内容与已发布版本一致。"
    plan.refresh_from_db()
    return ok(_plan_row(plan, detail=True), message)


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def standards(request):
    if request.method == "GET":
        rows = _school_standards(request).prefetch_related("versions__published_by")
        for row in rows:
            row.prefetched_versions = sorted(
                row.versions.all(),
                key=lambda version: version.version_no,
                reverse=True,
            )
        return ok([_standard_row(row) for row in rows])

    serializer = EvaluationStandardWriteSerializer(
        data=request.data,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("评价标准未保存。", errors=serializer.errors, status=400)
    standard = serializer.save()
    return ok(_standard_row(standard, detail=True), "评价标准已创建。", status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsSchoolAdmin])
def standard_detail(request, pk: int):
    standard = _school_standards(request).filter(pk=pk).first()
    if standard is None:
        return fail("评价标准不存在或无权访问。", status=404)
    if request.method == "GET":
        return ok(_standard_row(standard, detail=True))
    serializer = EvaluationStandardWriteSerializer(
        standard,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("评价标准未保存。", errors=serializer.errors, status=400)
    standard = serializer.save()
    return ok(_standard_row(standard, detail=True), "评价标准已保存。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def publish_standard_view(request, pk: int):
    standard = _school_standards(request).filter(pk=pk).first()
    if standard is None:
        return fail("评价标准不存在或无权访问。", status=404)
    try:
        result = publish_standard(standard, published_by=request.user)
    except DjangoValidationError as exc:
        return fail("评价标准发布前检查未通过。", errors=_validation_errors(exc), status=400)
    message = "已发布新的评价标准版本。" if result.created else "当前内容与已发布版本一致。"
    standard.refresh_from_db()
    return ok(_standard_row(standard, detail=True), message)
