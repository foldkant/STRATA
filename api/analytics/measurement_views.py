from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsTeacher
from api.responses import fail, ok
from courses.models import Course
from learning_analytics.measurement_models import (
    AssessmentBlueprint,
    MeasurementUse,
    MeasurementValidationStatus,
    RubricDefinition,
    RubricModule,
)
from learning_analytics.services.measurement import (
    COGNITIVE_COMPLEXITY_VALUES,
    publish_blueprint,
    publish_rubric,
)

from .measurement_serializers import (
    AssessmentBlueprintWriteSerializer,
    RubricDefinitionWriteSerializer,
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
        "validation_status": version.validation_status,
        "validation_status_label": version.get_validation_status_display(),
        "published_by": version.published_by.display_name
        or version.published_by.username,
        "published_at": version.published_at,
    }


def _blueprint_row(blueprint: AssessmentBlueprint, *, detail: bool = False) -> dict:
    latest = next(iter(getattr(blueprint, "prefetched_versions", [])), None)
    if latest is None and detail:
        latest = blueprint.versions.select_related("published_by").order_by("-version_no").first()
    row = {
        "id": blueprint.id,
        "title": blueprint.title,
        "subject": {"id": blueprint.subject_id, "name": blueprint.subject.name},
        "course": (
            {"id": blueprint.course_id, "title": blueprint.course.title}
            if blueprint.course_id
            else None
        ),
        "intended_use": blueprint.intended_use,
        "intended_use_label": blueprint.get_intended_use_display(),
        "task_version": blueprint.task_version,
        "claim_count": len(blueprint.claims),
        "evidence_count": len(blueprint.evidence_rules),
        "task_count": len(blueprint.task_specifications),
        "validation_status": blueprint.validation_status,
        "validation_status_label": blueprint.get_validation_status_display(),
        "latest_version": _version_summary(latest),
        "created_at": blueprint.created_at,
        "updated_at": blueprint.updated_at,
    }
    if detail:
        row.update(
            {
                "target_population": blueprint.target_population,
                "course_goal": blueprint.course_goal,
                "claims": blueprint.claims,
                "evidence_rules": blueprint.evidence_rules,
                "task_specifications": blueprint.task_specifications,
                "content_coverage": blueprint.content_coverage,
                "cognitive_complexity": blueprint.cognitive_complexity,
                "allowed_supports": blueprint.allowed_supports,
                "scoring_model": blueprint.scoring_model,
                "next_formative_action": blueprint.next_formative_action,
                "versions": [
                    _version_summary(version)
                    for version in blueprint.versions.select_related("published_by").order_by("-version_no")
                ],
            }
        )
    return row


def _rubric_row(rubric: RubricDefinition, *, detail: bool = False) -> dict:
    latest = next(iter(getattr(rubric, "prefetched_versions", [])), None)
    if latest is None and detail:
        latest = rubric.versions.select_related("published_by").order_by("-version_no").first()
    row = {
        "id": rubric.id,
        "title": rubric.title,
        "blueprint": {
            "id": rubric.blueprint_id,
            "title": rubric.blueprint.title,
        },
        "subject": {"id": rubric.subject_id, "name": rubric.subject.name},
        "course": (
            {"id": rubric.course_id, "title": rubric.course.title}
            if rubric.course_id
            else None
        ),
        "intended_use": rubric.intended_use,
        "intended_use_label": rubric.get_intended_use_display(),
        "evaluation_object": rubric.evaluation_object,
        "criterion_count": len(rubric.criteria),
        "validation_status": rubric.validation_status,
        "validation_status_label": rubric.get_validation_status_display(),
        "latest_version": _version_summary(latest),
        "created_at": rubric.created_at,
        "updated_at": rubric.updated_at,
    }
    if detail:
        row.update(
            {
                "criteria": rubric.criteria,
                "versions": [
                    _version_summary(version)
                    for version in rubric.versions.select_related("published_by").order_by("-version_no")
                ],
            }
        )
    return row


def _teacher_blueprints(request):
    return AssessmentBlueprint.objects.filter(
        school=request.user.school,
        created_by=request.user,
    ).select_related("subject", "course")


def _teacher_rubrics(request):
    return RubricDefinition.objects.filter(
        school=request.user.school,
        created_by=request.user,
    ).select_related("subject", "course", "blueprint")


@api_view(["GET"])
@permission_classes([IsTeacher])
def measurement_options(request):
    courses = list(
        Course.objects.filter(
            teacher=request.user,
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
            "uses": [
                {
                    "value": value,
                    "label": label,
                    "teacher_enabled": value == MeasurementUse.LOCAL_FORMATIVE,
                }
                for value, label in MeasurementUse.choices
            ],
            "validation_statuses": [
                {"value": value, "label": label}
                for value, label in MeasurementValidationStatus.choices
            ],
            "rubric_modules": [
                {"value": value, "label": label}
                for value, label in RubricModule.choices
            ],
            "cognitive_complexities": [
                {"value": value, "label": label}
                for value, label in (
                    ("remember", "记忆"),
                    ("understand", "理解"),
                    ("apply", "应用"),
                    ("analyze", "分析"),
                    ("evaluate", "评价"),
                    ("create", "创造"),
                )
                if value in COGNITIVE_COMPLEXITY_VALUES
            ],
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def blueprints(request):
    if request.method == "GET":
        rows = _teacher_blueprints(request).prefetch_related("versions__published_by")
        for row in rows:
            row.prefetched_versions = sorted(
                row.versions.all(),
                key=lambda version: version.version_no,
                reverse=True,
            )
        return ok([_blueprint_row(row) for row in rows])

    serializer = AssessmentBlueprintWriteSerializer(
        data=request.data,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("蓝图草案未保存。", errors=serializer.errors, status=400)
    blueprint = serializer.save()
    return ok(_blueprint_row(blueprint, detail=True), "蓝图草案已创建。", status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsTeacher])
def blueprint_detail(request, pk: int):
    blueprint = _teacher_blueprints(request).filter(pk=pk).first()
    if blueprint is None:
        return fail("任务蓝图不存在或无权访问。", status=404)
    if request.method == "GET":
        return ok(_blueprint_row(blueprint, detail=True))
    serializer = AssessmentBlueprintWriteSerializer(
        blueprint,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("蓝图草案未保存。", errors=serializer.errors, status=400)
    blueprint = serializer.save()
    return ok(_blueprint_row(blueprint, detail=True), "蓝图草案已保存。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def publish_blueprint_view(request, pk: int):
    blueprint = _teacher_blueprints(request).filter(pk=pk).first()
    if blueprint is None:
        return fail("任务蓝图不存在或无权访问。", status=404)
    try:
        result = publish_blueprint(blueprint, published_by=request.user)
    except DjangoValidationError as exc:
        return fail("蓝图发布前检查未通过。", errors=_validation_errors(exc), status=400)
    message = "已发布新的任务蓝图版本。" if result.created else "当前内容与已发布版本一致。"
    blueprint.refresh_from_db()
    return ok(_blueprint_row(blueprint, detail=True), message)


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def rubrics(request):
    if request.method == "GET":
        rows = _teacher_rubrics(request).prefetch_related("versions__published_by")
        for row in rows:
            row.prefetched_versions = sorted(
                row.versions.all(),
                key=lambda version: version.version_no,
                reverse=True,
            )
        return ok([_rubric_row(row) for row in rows])

    serializer = RubricDefinitionWriteSerializer(
        data=request.data,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("量规草案未保存。", errors=serializer.errors, status=400)
    rubric = serializer.save()
    return ok(_rubric_row(rubric, detail=True), "量规草案已创建。", status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsTeacher])
def rubric_detail(request, pk: int):
    rubric = _teacher_rubrics(request).filter(pk=pk).first()
    if rubric is None:
        return fail("量规不存在或无权访问。", status=404)
    if request.method == "GET":
        return ok(_rubric_row(rubric, detail=True))
    serializer = RubricDefinitionWriteSerializer(
        rubric,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("量规草案未保存。", errors=serializer.errors, status=400)
    rubric = serializer.save()
    return ok(_rubric_row(rubric, detail=True), "量规草案已保存。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def publish_rubric_view(request, pk: int):
    rubric = _teacher_rubrics(request).filter(pk=pk).first()
    if rubric is None:
        return fail("量规不存在或无权访问。", status=404)
    try:
        result = publish_rubric(rubric, published_by=request.user)
    except DjangoValidationError as exc:
        return fail("量规发布前检查未通过。", errors=_validation_errors(exc), status=400)
    message = "已发布新的量规版本。" if result.created else "当前内容与已发布版本一致。"
    rubric.refresh_from_db()
    return ok(_rubric_row(rubric, detail=True), message)
