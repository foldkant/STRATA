from __future__ import annotations

import ast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.urls import reverse
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsTeacher
from api.responses import fail, ok
from courses.models import Course, LessonStep
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationPlanVersion,
    EvaluationScope,
    EvaluationReviewStatus,
    EvaluationStandard,
    EvaluationStandardVersion,
    EvaluationDimension,
    EvaluationMode,
    EvidenceOwnership,
    EvaluationTrialConclusion,
    EvaluationTrialRecord,
    EvaluationTrialStatus,
    EvaluationTrialType,
    LessonStepEvaluationBinding,
)
from learning_analytics.services.evaluation import (
    EvaluationPublishConflict,
    THINKING_REQUIREMENT_VALUES,
    confirm_plan_review,
    confirm_standard_review,
    publish_plan,
    publish_standard,
    standard_curriculum_alignment,
)

from .evaluation_serializers import (
    EvaluationPlanWriteSerializer,
    EvaluationStandardWriteSerializer,
    EvaluationTrialRecordWriteSerializer,
)
from ops.xlsx import build_workbook, workbook_response


def _course_school_stage(course: Course) -> str:
    """Infer the curriculum school stage from the classes using the course.

    Course historically had no school-stage field.  Evaluation authoring still needs
    a deterministic stage so teachers are not asked to choose a curriculum standard
    that the lesson context already makes clear.
    """

    grades = {
        str(link.class_group.grade or "").strip().lower()
        for link in course.course_classes.all()
        if link.class_group_id
    }
    joined = " ".join(grades)
    high_school_markers = (
        "高中",
        "高一",
        "高二",
        "高三",
        "高1",
        "高2",
        "高3",
        "grade 10",
        "grade 11",
        "grade 12",
        "10年级",
        "11年级",
        "12年级",
        "k10",
        "k11",
        "k12",
    )
    compulsory_markers = (
        "小学",
        "初中",
        "一年级",
        "二年级",
        "三年级",
        "四年级",
        "五年级",
        "六年级",
        "七年级",
        "八年级",
        "九年级",
        "初一",
        "初二",
        "初三",
        "grade 1",
        "grade 2",
        "grade 3",
        "grade 4",
        "grade 5",
        "grade 6",
        "grade 7",
        "grade 8",
        "grade 9",
    )
    if any(marker in joined for marker in high_school_markers):
        return "k10_k12"
    if any(marker in joined for marker in compulsory_markers):
        return "k1_k9"
    return ""


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
        "reviewed_by": (
            version.reviewed_by.display_name or version.reviewed_by.username
            if version.reviewed_by_id
            else None
        ),
        "reviewed_at": version.reviewed_at,
        "reviewed_content_hash": version.reviewed_content_hash,
        "published_by": version.published_by.display_name
        or version.published_by.username,
        "published_at": version.published_at,
    }


def _plan_version_option(version) -> dict | None:
    if version is None:
        return None
    return {
        "id": version.id,
        "source_plan_id": version.source_id,
        "title": version.title,
        "version_no": version.version_no,
        "content_hash": version.content_hash,
        "review_status": version.review_status,
        "subject": {
            "id": version.subject_id,
            "name": version.subject.name,
        },
        "course": (
            {"id": version.course_id, "title": version.course.title}
            if version.course_id
            else None
        ),
        "learning_goals": version.learning_goals,
        "evaluation_tasks": version.evaluation_tasks,
    }


def _review_audit(source) -> dict:
    reviewed = bool(
        source.review_status == EvaluationReviewStatus.REVIEWED
        and source.reviewed_by_id
        and source.reviewed_at
        and source.reviewed_content_hash
    )
    return {
        "reviewed_by": (
            source.reviewed_by.display_name or source.reviewed_by.username
            if source.reviewed_by_id
            else None
        ),
        "reviewed_at": source.reviewed_at,
        "reviewed_content_hash": source.reviewed_content_hash,
        "allowed_actions": {
            "edit": True,
            "review": source.review_status == EvaluationReviewStatus.DRAFT,
            "publish": reviewed,
        },
    }


def _curriculum_reference_row(reference) -> dict:
    node = reference.node
    version = node.version
    source = version.source
    return {
        "id": node.id,
        "reference_id": reference.id,
        "node_type": node.node_type,
        "node_type_label": node.get_node_type_display(),
        "code": node.code,
        "title": node.title,
        "content": node.content,
        "source_page_start": node.source_page_start,
        "source_page_end": node.source_page_end,
        "source_paragraph": node.source_paragraph,
        "version_id": version.id,
        "version_label": version.version_label,
        "standard_id": source.id,
        "standard_title": version.official_title,
        "subject_code": version.subject_code_snapshot,
        "subject_name": version.subject_name_snapshot,
        "school_stage": version.school_stage_snapshot,
        "source_url": version.source_url,
        "pdf_url": reverse("api_curriculum_standard_pdf", kwargs={"pk": version.id}),
        "content_hash": node.content_hash,
        "curriculum_version_hash": version.content_hash,
        "alignment_explanation": reference.alignment_explanation,
    }


def _plan_row(plan: EvaluationPlan, *, detail: bool = False) -> dict:
    latest = next(iter(getattr(plan, "prefetched_versions", [])), None)
    if latest is None and detail:
        latest = plan.versions.select_related("published_by", "reviewed_by").order_by("-version_no").first()
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
        "learning_goal": plan.learning_goal,
        "assessment_modes": plan.assessment_modes,
        "goal_count": len(plan.learning_goals),
        "basis_count": len(plan.evaluation_basis),
        # 新评价链以“评价任务”为可评价单元；learning_tasks 仅为历史兼容字段。
        "task_count": len(plan.evaluation_tasks),
        "activity_count": len(plan.learning_activities),
        "evaluation_task_count": len(plan.evaluation_tasks),
        "curriculum_reference_count": len(plan.curriculum_references.all()),
        "review_status": plan.review_status,
        "review_status_label": plan.get_review_status_display(),
        "latest_version": _version_summary(latest),
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        **_review_audit(plan),
    }
    if detail:
        row.update(
            {
                "target_students": plan.target_students,
                "learning_goal": plan.learning_goal,
                "learning_goals": plan.learning_goals,
                "evaluation_basis": plan.evaluation_basis,
                "learning_activities": plan.learning_activities,
                "learning_tasks": plan.learning_tasks,
                "evaluation_tasks": plan.evaluation_tasks,
                "assessment_modes": plan.assessment_modes,
                "content_scope": plan.content_scope,
                "thinking_requirements": plan.thinking_requirements,
                "support_options": plan.support_options,
                "scoring_rules": plan.scoring_rules,
                "follow_up_suggestion": plan.follow_up_suggestion,
                "curriculum_references": [
                    _curriculum_reference_row(reference)
                    for reference in plan.curriculum_references.all()
                ],
                "versions": [
                    _version_summary(version)
                    for version in plan.versions.select_related("published_by", "reviewed_by").order_by("-version_no")
                ],
            }
        )
    return row


def _standard_row(standard: EvaluationStandard, *, detail: bool = False) -> dict:
    latest = next(iter(getattr(standard, "prefetched_versions", [])), None)
    if latest is None and detail:
        latest = standard.versions.select_related("published_by", "reviewed_by").order_by("-version_no").first()
    row = {
        "id": standard.id,
        "title": standard.title,
        "plan": {
            "id": standard.plan_id,
            "title": standard.plan.title,
        },
        "plan_version": _plan_version_option(standard.plan_version),
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
        "ai_assisted": standard.ai_draft_sessions.exists(),
        "review_status": standard.review_status,
        "review_status_label": standard.get_review_status_display(),
        "latest_version": _version_summary(latest),
        "created_at": standard.created_at,
        "updated_at": standard.updated_at,
        **_review_audit(standard),
    }
    if detail:
        row.update(
            {
                "criteria": standard.criteria,
                "versions": [
                    _version_summary(version)
                    for version in standard.versions.select_related("published_by", "reviewed_by").order_by("-version_no")
                ],
            }
        )
    return row


def _trial_row(record: EvaluationTrialRecord) -> dict:
    version = record.standard_version
    return {
        "id": record.id,
        "standard_version": {
            "id": version.id,
            "title": version.title,
            "version_no": version.version_no,
            "subject": {
                "id": version.subject_id,
                "name": version.subject.name,
            },
            "course": (
                {"id": version.course_id, "title": version.course.title}
                if version.course_id
                else None
            ),
        },
        "record_type": record.record_type,
        "record_type_label": record.get_record_type_display(),
        "title": record.title,
        "status": record.status,
        "status_label": record.get_status_display(),
        "activity_date": record.activity_date,
        "participant_count": record.participant_count,
        "agreement_rate": record.agreement_rate,
        "conclusion": record.conclusion,
        "conclusion_label": record.get_conclusion_display(),
        "summary": record.summary,
        "issues": record.issues,
        "action_items": record.action_items,
        "completion_hash": record.completion_hash,
        "completed_by": (
            record.completed_by.display_name or record.completed_by.username
            if record.completed_by_id
            else None
        ),
        "completed_at": record.completed_at,
        "created_by": record.created_by.display_name or record.created_by.username,
        "updated_by": record.updated_by.display_name or record.updated_by.username,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _teacher_plans(request):
    return EvaluationPlan.objects.filter(
        school=request.user.school,
        course__teacher=request.user,
    ).select_related("subject", "course", "reviewed_by").prefetch_related(
        "curriculum_references__node__version__source"
    )


def _request_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _criterion_version_row(criterion, curriculum_alignment: dict | None = None) -> dict:
    level_descriptions = []
    for description in criterion.level_descriptions:
        cleaned = description
        if isinstance(description, str) and description.lstrip().startswith("{"):
            try:
                legacy_value = ast.literal_eval(description)
            except (SyntaxError, ValueError):
                legacy_value = None
            if isinstance(legacy_value, dict):
                cleaned = str(
                    legacy_value.get("description")
                    or legacy_value.get("text")
                    or description
                ).strip()
        level_descriptions.append(cleaned)
    row = {
        "id": criterion.id,
        "code": criterion.code,
        "title": criterion.title,
        "dimension": criterion.dimension,
        "dimension_label": criterion.get_dimension_display(),
        "evaluation_target": criterion.evaluation_target,
        "evaluation_sources": criterion.evaluation_sources,
        "learning_goal_codes": criterion.learning_goal_codes,
        "evaluation_task_codes": criterion.evaluation_task_codes,
        "evidence_ownership": criterion.evidence_ownership,
        "evidence_ownership_label": criterion.get_evidence_ownership_display(),
        "material_types": criterion.material_types,
        "expected_performance": criterion.expected_performance,
        "level_descriptions": level_descriptions,
        "skip_condition": criterion.skip_condition,
        "support_options": criterion.support_options,
        "common_problems": criterion.common_problems,
        "follow_up_suggestion": criterion.follow_up_suggestion,
    }
    if curriculum_alignment is not None:
        row["curriculum_alignment"] = curriculum_alignment
    return row


def _standard_version_option(version) -> dict:
    curriculum_alignment = standard_curriculum_alignment(version)
    return {
        "id": version.id,
        "title": version.title,
        "version_no": version.version_no,
        "review_status": version.review_status,
        "review_status_label": version.get_review_status_display(),
        "criterion_count": len(version.criteria.all()),
        "criteria": [
            _criterion_version_row(
                criterion,
                curriculum_alignment.get(criterion.code, {}),
            )
            for criterion in version.criteria.all()
        ],
    }


def _binding_row(binding):
    if binding is None:
        return None
    version = binding.standard_version
    curriculum_alignment = standard_curriculum_alignment(version)
    return {
        "id": binding.id,
        "lesson_step": binding.lesson_step_id,
        "standard_version": version.id,
        "standard_title": version.title,
        "version_no": version.version_no,
        "enable_self": binding.enable_self,
        "enable_peer": binding.enable_peer,
        "enable_teacher": binding.enable_teacher,
        "locked": binding.classroom_uses.exists(),
        "criteria": [
            _criterion_version_row(
                item,
                curriculum_alignment.get(item.code, {}),
            )
            for item in version.criteria.all()
        ],
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def _lesson_step_evaluation_use_boundaries():
    """Describe what a lesson-step evaluation binding is allowed to do today.

    These are product and evidence-governance boundaries, not a claim that a
    published standard has already passed measurement or research validation.
    Keeping the contract on the server prevents a future client from presenting
    an ordinary classroom rating as an automatic mastery or training signal.
    """
    return [
        {
            "code": "classroom_feedback",
            "label": "课堂反馈",
            "status": "available",
            "status_label": "绑定后可用",
            "description": "用于学生自评、小组互评、教师评价和后续教学反馈。",
        },
        {
            "code": "learning_state_update",
            "label": "学习情况更新",
            "status": "requires_review",
            "status_label": "需另行审查",
            "description": (
                "只有目标对应、个人归属、材料质量、评价标准与评分质量均符合要求的材料，"
                "才可作为目标级学习情况的候选依据。"
            ),
        },
        {
            "code": "research_and_model",
            "label": "后续教学安排",
            "status": "not_direct",
            "status_label": "需教师再确认",
            "description": (
                "课堂星级和小组结果不会直接决定学生后续学习内容、支持方式或分组；"
                "教师需查看具体材料，研究数据则须由冻结方案另行构建。"
            ),
        },
    ]


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def lesson_step_binding(request, step_id: int):
    step = (
        LessonStep.objects.select_related("lesson__course")
        .filter(pk=step_id, lesson__course__teacher=request.user)
        .first()
    )
    if step is None:
        return fail("课时环节不存在或无权访问。", status=404)
    binding = (
        LessonStepEvaluationBinding.objects.select_related(
            "standard_version__plan_version"
        )
        .prefetch_related(
            "standard_version__criteria",
            "standard_version__plan_version__curriculum_references__node",
        )
        .filter(lesson_step=step)
        .first()
    )
    versions = (
        EvaluationStandardVersion.objects.filter(
            course=step.lesson.course,
            review_status=EvaluationReviewStatus.REVIEWED,
            reviewed_by__isnull=False,
            reviewed_at__isnull=False,
            reviewed_content_hash=F("content_hash"),
            plan_version__review_status=EvaluationReviewStatus.REVIEWED,
            plan_version__reviewed_by__isnull=False,
            plan_version__reviewed_at__isnull=False,
            plan_version__reviewed_content_hash=F("plan_version__content_hash"),
        )
        .select_related("plan_version")
        .prefetch_related("criteria", "plan_version__curriculum_references__node")
        .order_by("title", "-version_no")
    )
    if request.method == "GET":
        return ok(
            {
                "binding": _binding_row(binding),
                "standards": [_standard_version_option(version) for version in versions],
                "use_boundaries": _lesson_step_evaluation_use_boundaries(),
            }
        )
    if request.method == "DELETE":
        if binding is None:
            return ok({}, "当前环节未绑定评价标准。")
        if binding.classroom_uses.exists():
            return fail("该标准已在课堂中使用，不能取消绑定。", status=409)
        binding.delete()
        return ok({}, "已取消当前环节评价标准。")
    version = versions.filter(pk=request.data.get("standard_version")).first()
    if version is None:
        return fail("请选择本课程已发布的评价标准。", status=400)
    values = {
        "enable_self": _request_bool(request.data.get("enable_self")),
        "enable_peer": _request_bool(request.data.get("enable_peer")),
        "enable_teacher": _request_bool(request.data.get("enable_teacher")),
        "updated_by": request.user,
    }
    if not any(values[key] for key in ("enable_self", "enable_peer", "enable_teacher")):
        return fail("至少启用一种评价方式。", status=400)
    with transaction.atomic():
        binding = (
            LessonStepEvaluationBinding.objects.select_for_update()
            .filter(lesson_step=step)
            .first()
        )
        if binding and binding.classroom_uses.exists():
            unchanged = (
                binding.standard_version_id == version.id
                and binding.enable_self == values["enable_self"]
                and binding.enable_peer == values["enable_peer"]
                and binding.enable_teacher == values["enable_teacher"]
            )
            if not unchanged:
                return fail(
                    "该环节的评价标准已用于课堂，不能修改历史绑定。请复制环节后使用新标准。",
                    status=409,
                )
        binding, _ = LessonStepEvaluationBinding.objects.update_or_create(
            lesson_step=step,
            defaults={
                **values,
                "standard_version": version,
                "created_by": binding.created_by if binding else request.user,
            },
        )
    binding = LessonStepEvaluationBinding.objects.select_related(
        "standard_version__plan_version"
    ).prefetch_related(
        "standard_version__criteria",
        "standard_version__plan_version__curriculum_references__node",
    ).get(pk=binding.pk)
    return ok(_binding_row(binding), "当前环节评价标准已保存。")


def _teacher_standards(request):
    return EvaluationStandard.objects.filter(
        school=request.user.school,
        course__teacher=request.user,
    ).select_related(
        "subject",
        "course",
        "plan",
        "plan_version__source",
        "plan_version__subject",
        "plan_version__course",
        "reviewed_by",
    ).prefetch_related("ai_draft_sessions")


def _teacher_trial_records(request):
    return EvaluationTrialRecord.objects.filter(
        school=request.user.school,
        standard_version__course__teacher=request.user,
    ).select_related(
        "standard_version__subject",
        "standard_version__course",
        "created_by",
        "updated_by",
        "completed_by",
    )


@api_view(["GET"])
@permission_classes([IsTeacher])
def evaluation_options(request):
    courses = list(
        Course.objects.filter(
            subject__school=request.user.school,
            teacher=request.user,
        )
        .select_related("subject")
        .prefetch_related("course_classes__class_group")
        .order_by("subject__name", "title")
    )
    standard_versions = list(
        EvaluationStandardVersion.objects.filter(
            school=request.user.school,
            course__teacher=request.user,
            review_status=EvaluationReviewStatus.REVIEWED,
            reviewed_by__isnull=False,
            reviewed_at__isnull=False,
            reviewed_content_hash=F("content_hash"),
            plan_version__review_status=EvaluationReviewStatus.REVIEWED,
            plan_version__reviewed_by__isnull=False,
            plan_version__reviewed_at__isnull=False,
            plan_version__reviewed_content_hash=F("plan_version__content_hash"),
        )
        .select_related("subject", "course", "source")
        .order_by("subject__name", "title", "-version_no")
    )
    plan_versions = list(
        EvaluationPlanVersion.objects.filter(
            school=request.user.school,
            course__teacher=request.user,
            review_status=EvaluationReviewStatus.REVIEWED,
            reviewed_by__isnull=False,
            reviewed_at__isnull=False,
            reviewed_content_hash=F("content_hash"),
        )
        .select_related("source", "subject", "course")
        .order_by("subject__name", "title", "-version_no")
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
                        "code": course.subject.code,
                    },
                    "school_stage": _course_school_stage(course),
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
            "assessment_modes": [
                {"value": value, "label": label}
                for value, label in EvaluationMode.choices
            ],
            "evidence_ownerships": [
                {"value": value, "label": label}
                for value, label in EvidenceOwnership.choices
            ],
            "material_types": [
                {"value": value, "label": label}
                for value, label in (
                    ("answer", "作答记录"),
                    ("artifact", "作品材料"),
                    ("operation", "操作记录"),
                    ("oral_defense", "答辩记录"),
                    ("observation", "观察记录"),
                    ("score", "评分记录"),
                )
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
            "standard_versions": [
                {
                    "id": version.id,
                    "title": version.title,
                    "version_no": version.version_no,
                    "subject": {
                        "id": version.subject_id,
                        "name": version.subject.name,
                    },
                    "course": (
                        {"id": version.course_id, "title": version.course.title}
                        if version.course_id
                        else None
                    ),
                }
                for version in standard_versions
            ],
            "plan_versions": [
                _plan_version_option(version)
                for version in plan_versions
            ],
            "trial_types": [
                {"value": value, "label": label}
                for value, label in EvaluationTrialType.choices
            ],
            "trial_statuses": [
                {"value": value, "label": label}
                for value, label in EvaluationTrialStatus.choices
            ],
            "trial_conclusions": [
                {"value": value, "label": label}
                for value, label in EvaluationTrialConclusion.choices
            ],
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def plans(request):
    if request.method == "GET":
        rows = _teacher_plans(request).prefetch_related(
            "versions__published_by",
            "versions__reviewed_by",
        )
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
@permission_classes([IsTeacher])
def plan_detail(request, pk: int):
    plan = _teacher_plans(request).filter(pk=pk).first()
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
@permission_classes([IsTeacher])
def review_confirm_plan_view(request, pk: int):
    plan = _teacher_plans(request).filter(pk=pk).first()
    if plan is None:
        return fail("评价方案不存在或无权访问。", status=404)
    try:
        plan = confirm_plan_review(plan=plan, reviewed_by=request.user)
    except DjangoValidationError as exc:
        return fail("评价方案复核未完成。", errors=_validation_errors(exc), status=400)
    plan = _teacher_plans(request).get(pk=plan.pk)
    return ok(_plan_row(plan, detail=True), "教师已完成评价方案复核。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def publish_plan_view(request, pk: int):
    plan = _teacher_plans(request).filter(pk=pk).first()
    if plan is None:
        return fail("评价方案不存在或无权访问。", status=404)
    try:
        result = publish_plan(plan, published_by=request.user)
    except DjangoValidationError as exc:
        return fail("评价方案发布前检查未通过。", errors=_validation_errors(exc), status=400)
    except EvaluationPublishConflict as exc:
        return fail(str(exc), status=409)
    message = "已发布新的评价方案版本。" if result.created else "当前内容与已发布版本一致。"
    plan.refresh_from_db()
    return ok(_plan_row(plan, detail=True), message)


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def standards(request):
    if request.method == "GET":
        rows = _teacher_standards(request).prefetch_related(
            "versions__published_by",
            "versions__reviewed_by",
        )
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
@permission_classes([IsTeacher])
def standard_detail(request, pk: int):
    standard = _teacher_standards(request).filter(pk=pk).first()
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
@permission_classes([IsTeacher])
def review_confirm_standard_view(request, pk: int):
    standard = _teacher_standards(request).filter(pk=pk).first()
    if standard is None:
        return fail("评价标准不存在或无权访问。", status=404)
    try:
        standard = confirm_standard_review(
            standard=standard,
            reviewed_by=request.user,
        )
    except DjangoValidationError as exc:
        return fail("评价标准复核未完成。", errors=_validation_errors(exc), status=400)
    standard = _teacher_standards(request).get(pk=standard.pk)
    return ok(_standard_row(standard, detail=True), "教师已完成评价标准复核。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def publish_standard_view(request, pk: int):
    standard = _teacher_standards(request).filter(pk=pk).first()
    if standard is None:
        return fail("评价标准不存在或无权访问。", status=404)
    try:
        result = publish_standard(standard, published_by=request.user)
    except DjangoValidationError as exc:
        return fail("评价标准发布前检查未通过。", errors=_validation_errors(exc), status=400)
    except EvaluationPublishConflict as exc:
        return fail(str(exc), status=409)
    message = "已发布新的评价标准版本。" if result.created else "当前内容与已发布版本一致。"
    standard.refresh_from_db()
    return ok(_standard_row(standard, detail=True), message)


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def trial_records(request):
    if request.method == "GET":
        rows = _teacher_trial_records(request)
        record_type = request.query_params.get("type", "").strip()
        status = request.query_params.get("status", "").strip()
        if record_type:
            rows = rows.filter(record_type=record_type)
        if status:
            rows = rows.filter(status=status)
        return ok([_trial_row(row) for row in rows])

    serializer = EvaluationTrialRecordWriteSerializer(
        data=request.data,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("评价试用记录未保存。", errors=serializer.errors, status=400)
    record = serializer.save()
    return ok(_trial_row(record), "评价试用记录已创建。", status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def trial_record_detail(request, pk: int):
    record = _teacher_trial_records(request).filter(pk=pk).first()
    if record is None:
        return fail("评价试用记录不存在或无权访问。", status=404)
    if request.method == "GET":
        return ok(_trial_row(record))
    if request.method == "DELETE":
        if record.status == EvaluationTrialStatus.COMPLETED:
            return fail("已完成记录不能删除。", status=409)
        record.delete()
        return ok(message="评价试用记录已删除。")

    serializer = EvaluationTrialRecordWriteSerializer(
        record,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("评价试用记录未保存。", errors=serializer.errors, status=400)
    record = serializer.save()
    return ok(_trial_row(record), "评价试用记录已保存。")


@api_view(["GET"])
@permission_classes([IsTeacher])
def export_trial_records(request):
    school = request.user.school
    rows = _teacher_trial_records(request)
    workbook = build_workbook(
        [
            {
                "title": "评价试用记录",
                "headers": [
                    "记录ID",
                    "学科",
                    "课程",
                    "评价标准",
                    "标准版本",
                    "记录类型",
                    "记录名称",
                    "状态",
                    "日期",
                    "参与人数",
                    "评分一致率",
                    "处理结论",
                    "结果说明",
                    "发现的问题",
                    "后续处理",
                    "创建人",
                    "更新时间",
                ],
                "rows": [
                    [
                        record.id,
                        record.standard_version.subject.name,
                        record.standard_version.course.title
                        if record.standard_version.course_id
                        else "",
                        record.standard_version.title,
                        record.standard_version.version_no,
                        record.get_record_type_display(),
                        record.title,
                        record.get_status_display(),
                        record.activity_date,
                        record.participant_count,
                        record.agreement_rate,
                        record.get_conclusion_display(),
                        record.summary,
                        "；".join(record.issues),
                        "；".join(record.action_items),
                        record.created_by.display_name or record.created_by.username,
                        record.updated_at,
                    ]
                    for record in rows
                ],
            }
        ]
    )
    return workbook_response(
        workbook,
        f"{school.code}-评价试用记录-{timezone.localdate():%Y%m%d}.xlsx",
    )
