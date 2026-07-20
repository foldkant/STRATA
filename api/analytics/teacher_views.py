from __future__ import annotations

from collections import Counter
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsTeacher
from api.responses import fail, ok
from api.services import write_audit
from courses.models import Course, CourseClass
from learning.models import StratificationDecision, StudentMasterySnapshot, TestAssessment
from learning.services.bands import (
    apply_student_subject_band,
    resolve_student_band,
)
from learning_analytics.models import StudentLearningSummary
from learning_analytics.services.learning_summaries import (
    build_student_learning_summary,
    build_transparent_suggestion,
)
from learning_analytics.services.class_calibration import friendly_decision_reason
from learning.services.mastery import (
    build_assessment_mastery_candidates,
    record_band_transition_review,
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


def _mastery_row(snapshot: StudentMasterySnapshot) -> dict:
    return {
        "id": snapshot.id,
        "student": {
            "id": snapshot.student_id,
            "username": snapshot.student.username,
            "display_name": snapshot.student.display_name or snapshot.student.username,
        },
        "class_group": {
            "id": snapshot.class_group_id,
            "name": snapshot.class_group.name,
            "grade": snapshot.class_group.grade,
        },
        "subject": {"id": snapshot.subject_id, "name": snapshot.subject.name},
        "course": (
            {"id": snapshot.course_id, "title": snapshot.course.title}
            if snapshot.course_id
            else None
        ),
        "assessment": {
            "id": snapshot.assessment_id,
            "title": snapshot.assessment.title,
        },
        "measurement_series": snapshot.measurement_series,
        "assessment_version": snapshot.assessment_version,
        "data_status": snapshot.data_status,
        "data_status_label": snapshot.get_data_status_display(),
        "mastery_score": snapshot.mastery_score,
        "measurement_error": snapshot.measurement_error,
        "common_item_count": snapshot.common_item_count,
        "answered_item_count": snapshot.answered_item_count,
        "answered_ratio": snapshot.answered_ratio,
        "knowledge_results": snapshot.knowledge_results,
        "comparability_evidence": snapshot.comparability_evidence,
        "observed_at": snapshot.observed_at,
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
    current_layer = (
        resolve_student_band(
            student=decision.student,
            subject=decision.subject,
            course=decision.course,
        )
        if decision.subject_id
        else None
    )
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
        "current_layer": current_layer or "",
        "current_layer_label": (
            dict(StudentProfile.Layer.choices).get(current_layer, "")
        ),
        "suggested_layer": decision.suggested_layer,
        "confidence": decision.confidence,
        "reasons": [friendly_decision_reason(item) for item in decision.reasons],
        "missing_data": decision.missing_data,
        "learning_summary": decision.learning_summary,
        "support_suggestion": decision.support_suggestion,
        "decision_kind": decision.decision_kind,
        "support_priority": decision.support_priority,
        "boundary_band": decision.boundary_band,
        "policy_version": decision.policy_version,
        "abstain_reason": decision.abstain_reason,
        "transition_checks": decision.transition_checks,
        "mastery_snapshot_id": decision.mastery_snapshot_id,
        "rule_version": decision.rule_version,
        "source_label": (
            "班级校准候选"
            if decision.rule_version.startswith("m03-")
            else "透明规则建议"
        ),
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


def _visible_stratification_decisions(user, class_ids):
    return (
        StratificationDecision.objects.filter(
            class_group_id__in=class_ids,
            course__teacher=user,
        )
        .select_related(
            "student__student_profile",
            "class_group",
            "subject",
            "course",
            "reviewed_by",
        )
        .filter(
            ~Q(rule_version__startswith="m03-")
            | Q(calibration_run__releases__status="active")
        )
        .exclude(decision_kind=StratificationDecision.DecisionKind.LEGACY)
        .distinct()
    )


def _stratification_scope(user, query_params):
    class_ids = set(_teacher_class_ids(user))
    selected_class = str(query_params.get("class_group") or "").strip()
    if selected_class:
        try:
            selected_class_id = int(selected_class)
        except ValueError as exc:
            raise ValidationError("班级筛选条件不正确。") from exc
        if selected_class_id not in class_ids:
            raise ValidationError("无权查看该班级的分层情况。")
        class_ids = {selected_class_id}

    selected_course = str(query_params.get("course") or "").strip()
    course = None
    if selected_course:
        try:
            selected_course_id = int(selected_course)
        except ValueError as exc:
            raise ValidationError("课程筛选条件不正确。") from exc
        course = Course.objects.filter(
            pk=selected_course_id,
            teacher=user,
            subject__school=user.school,
        ).first()
        if course is None:
            raise ValidationError("无权查看该课程的分层情况。")
    else:
        course = (
            Course.objects.filter(
                teacher=user,
                subject__school=user.school,
                is_active=True,
            )
            .order_by("title", "id")
            .first()
        )
    if course:
        course_class_ids = set(
            CourseClass.objects.filter(course=course).values_list(
                "class_group_id", flat=True
            )
        )
        class_ids &= course_class_ids
    return class_ids, course


def _stratification_overview_data(user, query_params):
    class_ids, course = _stratification_scope(user, query_params)
    profiles = list(
        StudentProfile.objects.filter(
            user__school=user.school,
            user__is_active=True,
            class_group_id__in=class_ids,
        )
        .select_related("user", "class_group")
        .order_by(
            "class_group__grade",
            "class_group__name",
            "student_no",
            "user__display_name",
            "user__username",
        )
    )
    student_ids = [profile.user_id for profile in profiles]
    decisions = _visible_stratification_decisions(user, class_ids).filter(
        student_id__in=student_ids
    )
    if course:
        decisions = decisions.filter(course=course)
    decision_rows = list(decisions.order_by("student_id", "-created_at", "-id"))
    latest_decision_by_student = {}
    for decision in decision_rows:
        existing = latest_decision_by_student.get(decision.student_id)
        if existing is None or (
            decision.status == StratificationDecision.Status.PENDING
            and existing.status != StratificationDecision.Status.PENDING
        ):
            latest_decision_by_student[decision.student_id] = decision

    summaries = StudentLearningSummary.objects.filter(
        school=user.school,
        student_id__in=student_ids,
        class_group_id__in=class_ids,
        course__teacher=user,
        window_type=StudentLearningSummary.WindowType.DAYS_30,
    ).select_related("course")
    if course:
        summaries = summaries.filter(course=course)
    latest_summary_by_student = {}
    for summary in summaries.order_by("student_id", "-window_end", "-id"):
        latest_summary_by_student.setdefault(summary.student_id, summary)

    rows = []
    layer_counts = Counter()
    class_counts = {}
    for profile in profiles:
        decision = latest_decision_by_student.get(profile.user_id)
        summary = latest_summary_by_student.get(profile.user_id)
        band_course = course or (decision.course if decision else None) or (
            summary.course if summary else None
        )
        layer = (
            resolve_student_band(
                student=profile.user,
                subject=band_course.subject,
                course=band_course,
            )
            if band_course and band_course.subject_id
            else None
        )
        layer_key = layer or "unassigned"
        layer_counts[layer_key] += 1
        per_class = class_counts.setdefault(
            profile.class_group_id,
            {
                "id": profile.class_group_id,
                "name": profile.class_group.name,
                "grade": profile.class_group.grade,
                "A": 0,
                "B": 0,
                "C": 0,
                "unassigned": 0,
            },
        )
        per_class[layer_key] += 1
        metrics = summary.metrics if summary else {}
        rows.append(
            {
                "id": profile.id,
                "student": {
                    "id": profile.user_id,
                    "username": profile.user.username,
                    "display_name": (
                        profile.user.display_name or profile.user.username
                    ),
                    "student_no": profile.student_no,
                },
                "class_group": {
                    "id": profile.class_group_id,
                    "name": profile.class_group.name,
                    "grade": profile.class_group.grade,
                },
                "current_layer": layer or "",
                "current_layer_label": (
                    dict(StudentProfile.Layer.choices).get(layer, "未分层")
                ),
                "learning": (
                    {
                        "data_status": summary.data_status,
                        "data_status_label": summary.get_data_status_display(),
                        "completion_rate": metrics.get("completion_rate"),
                        "score_rate": (metrics.get("score") or {}).get("score_rate"),
                        "window_end": summary.window_end,
                        "course": {
                            "id": summary.course_id,
                            "title": summary.course.title,
                        },
                    }
                    if summary
                    else None
                ),
                "latest_decision": _decision_row(decision) if decision else None,
            }
        )

    pending_count = decisions.filter(
        status=StratificationDecision.Status.PENDING
    ).count()
    return {
        "scope": {
            "class_group_ids": sorted(class_ids),
            "course": (
                {"id": course.id, "title": course.title} if course else None
            ),
        },
        "counts": {
            "total": len(profiles),
            "A": layer_counts["A"],
            "B": layer_counts["B"],
            "C": layer_counts["C"],
            "unassigned": layer_counts["unassigned"],
            "pending": pending_count,
        },
        "class_distribution": list(class_counts.values()),
        "rows": rows,
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
def stratification_overview(request):
    try:
        data = _stratification_overview_data(request.user, request.query_params)
    except ValidationError as exc:
        return fail("；".join(exc.messages), status=400)
    return ok(data)


@api_view(["GET"])
@permission_classes([IsTeacher])
def export_stratification_overview(request):
    try:
        data = _stratification_overview_data(request.user, request.query_params)
    except ValidationError as exc:
        return fail("；".join(exc.messages), status=400)
    rows = []
    for item in data["rows"]:
        learning = item["learning"] or {}
        decision = item["latest_decision"] or {}
        rows.append(
            [
                item["student"]["display_name"],
                item["student"]["username"],
                item["student"]["student_no"],
                f'{item["class_group"]["grade"]} {item["class_group"]["name"]}'.strip(),
                item["current_layer"] or "未分层",
                item["current_layer_label"],
                _rate_for_export(learning.get("completion_rate")),
                _rate_for_export(learning.get("score_rate")),
                (learning.get("course") or {}).get("title", ""),
                decision.get("suggested_layer", ""),
                (
                    f'{round(float(decision.get("confidence") or 0) * 100)}%'
                    if decision.get("suggested_layer")
                    else ""
                ),
                decision.get("status_label", ""),
                "；".join(decision.get("reasons") or []),
                decision.get("support_suggestion", ""),
                decision.get("reviewed_by", ""),
                decision.get("reviewed_at") or "",
            ]
        )
    workbook = build_workbook(
        [
            {
                "title": "当前分层",
                "headers": [
                    "学生",
                    "账号",
                    "学号",
                    "班级",
                    "当前层级",
                    "层级说明",
                    "近30日完成率",
                    "近30日得分率",
                    "学习情况课程",
                    "最新建议",
                    "参考强度",
                    "建议状态",
                    "主要依据",
                    "教学支持建议",
                    "处理教师",
                    "处理时间",
                ],
                "rows": rows,
            }
        ]
    )
    return workbook_response(
        workbook,
        f"{request.user.school.code}-当前学生分层-{timezone.localdate().isoformat()}.xlsx",
    )


@api_view(["GET"])
@permission_classes([IsTeacher])
def stratification_suggestions(request):
    class_ids = _teacher_class_ids(request.user)
    rows = _visible_stratification_decisions(request.user, class_ids).order_by(
        "status", "class_group__name", "student__username", "-created_at"
    )
    status_value = str(request.query_params.get("status") or "")
    if status_value:
        rows = rows.filter(status=status_value)
    if request.query_params.get("class_group"):
        rows = rows.filter(class_group_id=request.query_params["class_group"])
    if request.query_params.get("course"):
        rows = rows.filter(course_id=request.query_params["course"])
    decision_kind = str(request.query_params.get("decision_kind") or "").strip()
    if decision_kind in StratificationDecision.DecisionKind.values:
        rows = rows.filter(decision_kind=decision_kind)
    return ok([_decision_row(row) for row in rows[:1000]])


@api_view(["GET"])
@permission_classes([IsTeacher])
def mastery_snapshots(request):
    class_ids = _teacher_class_ids(request.user)
    rows = (
        StudentMasterySnapshot.objects.filter(
            school=request.user.school,
            class_group_id__in=class_ids,
            assessment__teacher=request.user,
        )
        .select_related(
            "student", "class_group", "subject", "course", "assessment"
        )
        .order_by("-observed_at", "class_group__name", "student__username")
    )
    if request.query_params.get("class_group"):
        rows = rows.filter(class_group_id=request.query_params["class_group"])
    if request.query_params.get("course"):
        rows = rows.filter(course_id=request.query_params["course"])
    return ok([_mastery_row(row) for row in rows[:1000]])


@api_view(["POST"])
@permission_classes([IsTeacher])
def refresh_mastery_snapshots(request):
    assessment = TestAssessment.objects.select_related(
        "school", "subject", "course", "common_question_set"
    ).filter(
        pk=request.data.get("assessment"),
        school=request.user.school,
        teacher=request.user,
    ).first()
    if assessment is None:
        return fail("测试不存在或无权处理。", status=404)
    try:
        result = build_assessment_mastery_candidates(assessment=assessment)
    except ValidationError as exc:
        return fail(str(exc.messages[0]), status=400)
    return ok(result, "共同测试掌握结果已更新。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def review_stratification_suggestion(request, pk: int):
    class_ids = _teacher_class_ids(request.user)
    decision = (
        StratificationDecision.objects.select_related(
            "student", "class_group", "subject", "course"
        )
        .filter(
            pk=pk,
            class_group_id__in=class_ids,
            course__teacher=request.user,
        )
        .first()
    )
    if decision is None:
        return fail("学习安排建议不存在或无权处理。", status=404)
    if decision.decision_kind == StratificationDecision.DecisionKind.LEGACY:
        return fail("该记录仅用于历史兼容，不能继续处理。", status=409)
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
    is_content_band = (
        decision.decision_kind == StratificationDecision.DecisionKind.CONTENT_BAND
    )
    if action == "accept" and is_content_band:
        if not decision.suggested_layer:
            return fail("当前材料不足，不能采纳层级变化。", status=400)
        selected_layer = decision.suggested_layer
    elif action == "keep" and is_content_band:
        selected_layer = (
            resolve_student_band(
                student=decision.student,
                subject=decision.subject,
                course=decision.course,
            )
            or ""
        )
    elif action == "adjust" and is_content_band:
        selected_layer = str(request.data.get("layer") or "").upper()
        if selected_layer not in {"A", "B", "C"}:
            return fail("请选择 A、B 或 C。", status=400)
    note = str(request.data.get("note") or "").strip()[:1000]
    with transaction.atomic():
        decision = StratificationDecision.objects.select_for_update().get(pk=decision.pk)
        if is_content_band and action in {"accept", "adjust"}:
            apply_student_subject_band(
                decision=decision,
                selected_band=selected_layer,
                confirmed_by=request.user,
            )
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
        if is_content_band:
            record_band_transition_review(
                decision=decision,
                action=action,
                final_band=selected_layer,
                actor=request.user,
            )
    write_audit(
        request,
        "teacher.stratification.review",
        school=request.user.school,
        target_type="stratification_decision",
        target_id=decision.id,
        detail={
            "action": action,
            "selected_layer": selected_layer,
            "layer_applied": is_content_band and action in {"accept", "adjust"},
        },
    )
    decision = StratificationDecision.objects.select_related(
        "student__student_profile", "class_group", "subject", "course", "reviewed_by"
    ).get(pk=decision.pk)
    return ok(_decision_row(decision), "学习安排建议已处理。")
