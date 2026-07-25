from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsTeacher
from api.responses import fail, ok
from learning_analytics.ai_evaluation_models import (
    AIEvaluationDraftSession,
    AIEvaluationDraftStatus,
    AIEvaluationTaskKind,
)
from learning_analytics.services.ai_evaluation_drafting import (
    ALLOWED_EVALUATION_PURPOSES,
    AIEvaluationDraftError,
    cancel_session,
    confirm_modes,
    create_session,
    curriculum_version_options,
    dispatch_generation_stage,
    retrieve_curriculum_references,
    save_plan_draft,
    serialize_session,
)

from .evaluation_views import _plan_row, _standard_row


CREATE_FIELDS = {
    "course_id",
    "school_stage",
    "grade_or_stage",
    "unit_title",
    "curriculum_standard_version_id",
    "course_content",
    "evaluation_purpose",
    "retrieval_query",
    "idempotency_key",
}


def _teacher_sessions(request):
    return (
        AIEvaluationDraftSession.objects.filter(
            teacher=request.user,
            school=request.user.school,
        )
        .select_related(
            "teacher",
            "school",
            "subject",
            "course__subject",
            "curriculum_version__source",
            "linked_plan",
            "linked_standard",
        )
        .prefetch_related("generation_records", "teacher_decisions")
    )


def _get_session(request, pk: int):
    return _teacher_sessions(request).filter(pk=pk).first()


def _error_response(exc: AIEvaluationDraftError):
    return fail(exc.message, errors=exc.errors or {"code": [exc.code]}, status=exc.status)


def _django_error_response(exc: DjangoValidationError):
    if hasattr(exc, "message_dict"):
        errors = exc.message_dict
    else:
        errors = {"non_field_errors": exc.messages}
    return fail("AI 评价起草数据校验未通过。", errors=errors, status=400)


def _unknown_fields(data, allowed: set[str]):
    return sorted(set(data.keys()) - allowed)


def _require_empty_body(request):
    unknown = list(request.data.keys()) if hasattr(request.data, "keys") else []
    if unknown:
        raise AIEvaluationDraftError(
            "该步骤不接受额外字段。",
            errors={"non_field_errors": [f"未知字段：{', '.join(sorted(unknown))}"]},
        )


@api_view(["GET"])
@permission_classes([IsTeacher])
def ai_draft_options(request):
    return ok(
        {
            "curriculum_standard_versions": curriculum_version_options(request.user),
            "evaluation_purposes": [
                {"value": value, "label": label}
                for value, label in ALLOWED_EVALUATION_PURPOSES.items()
            ],
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def ai_drafts(request):
    if request.method == "GET":
        sessions = _teacher_sessions(request).order_by("-updated_at", "-id")[:50]
        return ok(
            {
                "results": [serialize_session(session) for session in sessions],
                "curriculum_standard_versions": curriculum_version_options(request.user),
                "evaluation_purposes": [
                    {"value": value, "label": label}
                    for value, label in ALLOWED_EVALUATION_PURPOSES.items()
                ],
            }
        )
    unknown = _unknown_fields(request.data, CREATE_FIELDS)
    if unknown:
        return fail(
            "起草情境包含未知字段。",
            errors={"non_field_errors": [f"未知字段：{', '.join(unknown)}"]},
            status=400,
        )
    idempotency_key = str(
        request.headers.get("Idempotency-Key")
        or request.data.get("idempotency_key")
        or ""
    ).strip()
    try:
        session, created = create_session(
            teacher=request.user,
            data=dict(request.data),
            idempotency_key=idempotency_key,
        )
    except AIEvaluationDraftError as exc:
        return _error_response(exc)
    except DjangoValidationError as exc:
        return _django_error_response(exc)
    session = _get_session(request, session.pk)
    return ok(
        serialize_session(session, detail=True),
        "AI 评价起草会话已创建。" if created else "已返回同一幂等请求的会话。",
        status=201 if created else 200,
    )


@api_view(["GET"])
@permission_classes([IsTeacher])
def ai_draft_detail(request, pk: int):
    session = _get_session(request, pk)
    if session is None:
        return fail("AI 评价起草会话不存在或无权访问。", status=404)
    return ok(serialize_session(session, detail=True))


@api_view(["POST"])
@permission_classes([IsTeacher])
def ai_draft_retrieve(request, pk: int):
    session = _get_session(request, pk)
    if session is None:
        return fail("AI 评价起草会话不存在或无权访问。", status=404)
    try:
        _require_empty_body(request)
        retrieve_curriculum_references(session=session, teacher=request.user)
    except AIEvaluationDraftError as exc:
        return _error_response(exc)
    except DjangoValidationError as exc:
        return _django_error_response(exc)
    return ok(
        serialize_session(_get_session(request, pk), detail=True),
        "课程标准依据已检索并冻结引用快照。",
    )


def _dispatch_response(request, pk: int, task_kind: str, *, allow_regenerate: bool = False):
    session = _get_session(request, pk)
    if session is None:
        return fail("AI 评价起草会话不存在或无权访问。", status=404)
    try:
        allowed_fields = {"regenerate"} if allow_regenerate else set()
        unknown = _unknown_fields(request.data, allowed_fields)
        if unknown:
            raise AIEvaluationDraftError(
                "该步骤包含未知字段。",
                errors={"non_field_errors": [f"未知字段：{', '.join(unknown)}"]},
            )
        regenerate = request.data.get("regenerate") is True if allow_regenerate else False
        result, dispatched = dispatch_generation_stage(
            session=session,
            teacher=request.user,
            task_kind=task_kind,
            regenerate=regenerate,
        )
    except AIEvaluationDraftError as exc:
        return _error_response(exc)
    except DjangoValidationError as exc:
        return _django_error_response(exc)
    result = _get_session(request, result.pk)
    data = serialize_session(result, detail=True)
    if result.status == AIEvaluationDraftStatus.FAILED:
        return ok(data, "后台任务队列当前不可用，失败状态已保存，可稍后重试。", status=503)
    completed = (
        result.status == AIEvaluationDraftStatus.MODES_SUGGESTED
        if task_kind == AIEvaluationTaskKind.SUGGEST_MODES
        else result.status == AIEvaluationDraftStatus.DRAFT_GENERATED
    )
    if completed:
        return ok(data, "该步骤已完成，返回原有结果。")
    return ok(
        data,
        "后台任务已进入队列。" if dispatched else "同一后台任务已在队列中。",
        status=202,
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def ai_draft_suggest_modes(request, pk: int):
    return _dispatch_response(request, pk, AIEvaluationTaskKind.SUGGEST_MODES)


@api_view(["POST"])
@permission_classes([IsTeacher])
def ai_draft_confirm_modes(request, pk: int):
    session = _get_session(request, pk)
    if session is None:
        return fail("AI 评价起草会话不存在或无权访问。", status=404)
    unknown = _unknown_fields(request.data, {"modes", "teacher_note"})
    if unknown:
        return fail(
            "评价方式确认包含未知字段。",
            errors={"non_field_errors": [f"未知字段：{', '.join(unknown)}"]},
            status=400,
        )
    try:
        result = confirm_modes(
            session=session,
            teacher=request.user,
            modes=request.data.get("modes") if isinstance(request.data.get("modes"), list) else [],
            teacher_note=str(request.data.get("teacher_note") or ""),
        )
    except AIEvaluationDraftError as exc:
        return _error_response(exc)
    except DjangoValidationError as exc:
        return _django_error_response(exc)
    return ok(
        serialize_session(_get_session(request, result.pk), detail=True),
        "教师已确认本次评价方式。",
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def ai_draft_generate(request, pk: int):
    return _dispatch_response(
        request,
        pk,
        AIEvaluationTaskKind.GENERATE_DRAFT,
        allow_regenerate=True,
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def ai_draft_save_plan(request, pk: int):
    session = _get_session(request, pk)
    if session is None:
        return fail("AI 评价起草会话不存在或无权访问。", status=404)
    unknown = _unknown_fields(
        request.data,
        {"plan_draft", "standard_draft", "review_decisions"},
    )
    if unknown:
        return fail(
            "草稿保存请求包含未知字段。",
            errors={"non_field_errors": [f"未知字段：{', '.join(unknown)}"]},
            status=400,
        )
    try:
        saved_session, plan, standard, created = save_plan_draft(
            session=session,
            teacher=request.user,
            plan_draft=request.data.get("plan_draft"),
            standard_draft=request.data.get("standard_draft"),
            review_decisions=request.data.get("review_decisions"),
        )
    except AIEvaluationDraftError as exc:
        return _error_response(exc)
    except DjangoValidationError as exc:
        return _django_error_response(exc)
    saved_session = _get_session(request, saved_session.pk)
    return ok(
        {
            "ai_draft": serialize_session(saved_session, detail=True),
            "plan": _plan_row(plan, detail=True),
            "standard": _standard_row(standard, detail=True),
            "drafts_saved": {"plan": True, "standard": True},
        },
        "评价方案与评价标准均已保存为待教师复核的草稿。",
        status=201 if created else 200,
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def ai_draft_cancel(request, pk: int):
    session = _get_session(request, pk)
    if session is None:
        return fail("AI 评价起草会话不存在或无权访问。", status=404)
    try:
        _require_empty_body(request)
        result = cancel_session(session=session, teacher=request.user)
    except AIEvaluationDraftError as exc:
        return _error_response(exc)
    except DjangoValidationError as exc:
        return _django_error_response(exc)
    return ok(
        serialize_session(_get_session(request, result.pk), detail=True),
        "AI 评价起草会话已取消。",
    )
