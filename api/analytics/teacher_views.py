from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsTeacher
from api.responses import fail, ok
from api.services import write_audit
from courses.models import Course, CourseClass
from learning.models import StratificationDecision
from learning_analytics.models import StudentLearningSummary
from learning_analytics.services.learning_summaries import (
    build_student_learning_summary,
    build_transparent_suggestion,
)
from ops.xlsx import build_workbook, workbook_response
from school.models import StudentProfile, TeachingAssignment


def _teacher_class_ids(user):
    return TeachingAssignment.objects.filter(
        school=user.school, teacher=user
    ).values_list("class_group_id", flat=True)


def _student_row(summary):
    profile = summary.student.student_profile
    return {
        "id": summary.student_id,
        "username": summary.student.username,
        "display_name": summary.student.display_name or summary.student.username,
        "student_no": profile.student_no,
        "class_group": {
            "id": summary.class_group_id,
            "name": summary.class_group.name,
            "grade": summary.class_group.grade,
        },
    }


def _summary_row(summary):
    return {
        "id": summary.id,
        "student": _student_row(summary),
        "subject": {"id": summary.subject_id, "name": summary.subject.name},
        "course": {"id": summary.course_id, "title": summary.course.title},
        "window_type": summary.window_type,
        "window_type_label": summary.get_window_type_display(),
        "period_key": summary.period_key,
        "window_start": summary.window_start,
        "window_end": summary.window_end,
        "data_status": summary.data_status,
        "data_status_label": summary.get_data_status_display(),
        "metrics": summary.metrics,
        "missing_data": summary.missing_data,
        "generated_at": summary.generated_at,
    }


def _learning_summary_queryset(user, query_params):
    window_type = str(query_params.get("window") or "7d")
    if window_type not in dict(StudentLearningSummary.WindowType.choices):
        return None, window_type, None
    rows = (
        StudentLearningSummary.objects.filter(
            school=user.school,
            class_group_id__in=_teacher_class_ids(user),
            course__teacher=user,
            window_type=window_type,
        )
        .select_related(
            "student__student_profile",
            "class_group",
            "subject",
            "course",
        )
        .order_by("class_group__grade", "class_group__name", "student__username")
    )
    if query_params.get("class_group"):
        rows = rows.filter(class_group_id=query_params["class_group"])
    if query_params.get("course"):
        rows = rows.filter(course_id=query_params["course"])
    latest_window = rows.order_by("-window_end").values_list("window_end", flat=True).first()
    if latest_window:
        rows = rows.filter(window_end=latest_window)
    return rows, window_type, latest_window


def _rate_for_export(value, *, empty_text="数据不足"):
    if value is None:
        return empty_text
    return f"{round(value * 100, 1)}%"


def _decision_row(decision):
    profile = decision.student.student_profile
    return {
        "id": decision.id,
        "student": {
            "id": decision.student_id,
            "username": decision.student.username,
            "display_name": decision.student.display_name or decision.student.username,
            "student_no": profile.student_no,
        },
        "class_group": {
            "id": decision.class_group_id,
            "name": decision.class_group.name,
            "grade": decision.class_group.grade,
        },
        "subject": (
            {"id": decision.subject_id, "name": decision.subject.name}
            if decision.subject_id
            else None
        ),
        "course": (
            {"id": decision.course_id, "title": decision.course.title}
            if decision.course_id
            else None
        ),
        "previous_layer": decision.previous_layer,
        "suggested_layer": decision.suggested_layer,
        "confidence": decision.confidence,
        "reasons": decision.reasons,
        "missing_data": decision.missing_data,
        "learning_summary": decision.learning_summary,
        "support_suggestion": decision.support_suggestion,
        "window_start": decision.window_start,
        "window_end": decision.window_end,
        "status": decision.status,
        "status_label": decision.get_status_display(),
        "teacher_selected_layer": decision.teacher_selected_layer,
        "review_note": decision.review_note,
        "reviewed_by": (
            decision.reviewed_by.display_name or decision.reviewed_by.username
            if decision.reviewed_by_id
            else ""
        ),
        "reviewed_at": decision.reviewed_at,
        "created_at": decision.created_at,
    }


@api_view(["GET"])
@permission_classes([IsTeacher])
def learning_summaries(request):
    rows, window_type, latest_window = _learning_summary_queryset(
        request.user, request.query_params
    )
    if rows is None:
        return fail("学习情况范围不正确。", status=400)
    return ok(
        {
            "window": window_type,
            "window_end": latest_window,
            "rows": [_summary_row(row) for row in rows[:1000]],
        }
    )


@api_view(["GET"])
@permission_classes([IsTeacher])
def export_learning_summaries(request):
    rows, window_type, latest_window = _learning_summary_queryset(
        request.user, request.query_params
    )
    if rows is None:
        return fail("学习情况范围不正确。", status=400)
    export_rows = []
    for summary in rows[:5000]:
        metrics = summary.metrics
        opportunities = metrics.get("opportunities", {})
        score = metrics.get("score", {})
        resources = metrics.get("resources", {})
        participation = metrics.get("participation", {})
        evaluation = metrics.get("evaluation", {})
        quality = metrics.get("quality", {})
        profile = summary.student.student_profile
        export_rows.append(
            [
                summary.student.display_name or summary.student.username,
                summary.student.username,
                profile.student_no,
                f"{summary.class_group.grade} {summary.class_group.name}".strip(),
                summary.subject.name,
                summary.course.title,
                summary.get_window_type_display(),
                summary.window_start,
                summary.window_end,
                summary.get_data_status_display(),
                opportunities.get("assigned_count", 0),
                opportunities.get("eligible_count", 0),
                opportunities.get("submitted_count", 0),
                _rate_for_export(
                    metrics.get("completion_rate"),
                    empty_text="没有学习任务" if summary.data_status == StudentLearningSummary.DataStatus.NO_OPPORTUNITY else "数据不足",
                ),
                _rate_for_export(metrics.get("on_time_rate")),
                score.get("graded_item_count", 0),
                _rate_for_export(score.get("score_rate"), empty_text="尚无评分"),
                resources.get("opened_count", 0),
                resources.get("assigned_count", 0),
                participation.get("interaction_count", 0),
                participation.get("point_delta", 0),
                (evaluation.get("self") or {}).get("average_stars") or "未评价",
                (evaluation.get("peer") or {}).get("average_stars") or "未评价",
                (evaluation.get("teacher") or {}).get("average_stars") or "未评价",
                _rate_for_export(quality.get("flagged_event_rate", 0)),
                "；".join(summary.missing_data or []),
            ]
        )
    workbook = build_workbook(
        [
            {
                "title": "学习情况",
                "headers": [
                    "学生",
                    "账号",
                    "学号",
                    "班级",
                    "学科",
                    "课程",
                    "汇总范围",
                    "开始时间",
                    "结束时间",
                    "材料状态",
                    "安排任务",
                    "有效任务",
                    "已提交",
                    "完成率",
                    "按时提交率",
                    "已评分项目",
                    "得分率",
                    "已打开资源",
                    "安排资源",
                    "课堂互动",
                    "课堂积分变化",
                    "自评平均星级",
                    "互评平均星级",
                    "师评平均星级",
                    "异常记录比例",
                    "需补充材料",
                ],
                "rows": export_rows,
            }
        ]
    )
    period = latest_window.date().isoformat() if latest_window else timezone.localdate().isoformat()
    window_label = dict(StudentLearningSummary.WindowType.choices)[window_type]
    return workbook_response(
        workbook,
        f"{request.user.school.code}-学生学习情况-{window_label}-{period}.xlsx",
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def refresh_learning_summaries(request):
    as_of: date = parse_date(str(request.data.get("as_of") or "")) or timezone.localdate()
    course_ids = Course.objects.filter(
        teacher=request.user,
        subject__school=request.user.school,
        is_active=True,
    ).values_list("id", flat=True)
    requested_course = request.data.get("course")
    if requested_course:
        course_ids = course_ids.filter(id=requested_course)
    courses = Course.objects.filter(id__in=course_ids).select_related("subject")
    class_ids = set(_teacher_class_ids(request.user))
    summaries = 0
    suggestions = 0
    for course in courses:
        course_class_ids = CourseClass.objects.filter(course=course).values_list(
            "class_group_id", flat=True
        )
        profiles = StudentProfile.objects.filter(
            class_group_id__in=set(course_class_ids) & class_ids,
            user__is_active=True,
        ).select_related("user", "class_group")
        for profile in profiles:
            by_window = {}
            for window_type, _label in StudentLearningSummary.WindowType.choices:
                by_window[window_type] = build_student_learning_summary(
                    student_profile=profile,
                    course=course,
                    window_type=window_type,
                    as_of=as_of,
                )
                summaries += 1
            build_transparent_suggestion(
                summary=by_window[StudentLearningSummary.WindowType.DAYS_30]
            )
            suggestions += 1
    write_audit(
        request,
        "teacher.learning_summary.refresh",
        school=request.user.school,
        target_type="learning_summary",
        target_id=request.user.id,
        detail={"as_of": as_of.isoformat(), "summaries": summaries},
    )
    return ok(
        {"summaries": summaries, "suggestions": suggestions, "as_of": as_of},
        "学习情况已重新汇总。",
    )


@api_view(["GET"])
@permission_classes([IsTeacher])
def stratification_suggestions(request):
    class_ids = _teacher_class_ids(request.user)
    rows = (
        StratificationDecision.objects.filter(
            class_group_id__in=class_ids,
            course__teacher=request.user,
        )
        .select_related(
            "student__student_profile",
            "class_group",
            "subject",
            "course",
            "reviewed_by",
        )
        .order_by("status", "class_group__name", "student__username", "-created_at")
    )
    status_value = str(request.query_params.get("status") or "")
    if status_value:
        rows = rows.filter(status=status_value)
    if request.query_params.get("class_group"):
        rows = rows.filter(class_group_id=request.query_params["class_group"])
    if request.query_params.get("course"):
        rows = rows.filter(course_id=request.query_params["course"])
    return ok([_decision_row(row) for row in rows[:1000]])


@api_view(["POST"])
@permission_classes([IsTeacher])
def review_stratification_suggestion(request, pk: int):
    class_ids = _teacher_class_ids(request.user)
    decision = (
        StratificationDecision.objects.select_related("student", "class_group", "course")
        .filter(
            pk=pk,
            class_group_id__in=class_ids,
            course__teacher=request.user,
        )
        .first()
    )
    if decision is None:
        return fail("学习安排建议不存在或无权处理。", status=404)
    action = str(request.data.get("action") or "").strip()
    status_map = {
        "accept": StratificationDecision.Status.ACCEPTED,
        "keep": StratificationDecision.Status.KEPT,
        "adjust": StratificationDecision.Status.ADJUSTED,
        "defer": StratificationDecision.Status.DEFERRED,
    }
    if action not in status_map:
        return fail("处理方式不正确。", status=400)
    selected_layer = ""
    if action == "accept":
        if not decision.suggested_layer:
            return fail("当前材料不足，不能采纳层级变化。", status=400)
        selected_layer = decision.suggested_layer
    elif action == "keep":
        selected_layer = decision.previous_layer
    elif action == "adjust":
        selected_layer = str(request.data.get("layer") or "").upper()
        if selected_layer not in {"A", "B", "C"}:
            return fail("请选择 A、B 或 C。", status=400)
    note = str(request.data.get("note") or "").strip()[:1000]
    with transaction.atomic():
        decision = StratificationDecision.objects.select_for_update().get(pk=decision.pk)
        decision.status = status_map[action]
        decision.teacher_selected_layer = selected_layer
        decision.review_note = note
        decision.reviewed_by = request.user
        decision.reviewed_at = timezone.now()
        decision.save(
            update_fields=[
                "status",
                "teacher_selected_layer",
                "review_note",
                "reviewed_by",
                "reviewed_at",
            ]
        )
    write_audit(
        request,
        "teacher.stratification.review",
        school=request.user.school,
        target_type="stratification_decision",
        target_id=decision.id,
        detail={"action": action, "selected_layer": selected_layer},
    )
    decision = StratificationDecision.objects.select_related(
        "student__student_profile", "class_group", "subject", "course", "reviewed_by"
    ).get(pk=decision.pk)
    return ok(_decision_row(decision), "学习安排建议已处理。")
