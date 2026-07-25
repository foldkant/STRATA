from __future__ import annotations

from collections import Counter
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsTeacher
from api.responses import fail, ok
from api.services import write_audit
from courses.models import Course, CourseClass
from learning.models import (
    LearningContentRecommendation,
    LearningSupportRecommendation,
    StratificationDecision,
    StudentSubjectBand,
    StudentLearningTargetStateVersion,
    StudentMasterySnapshot,
    TestAssessment,
)
from learning.services.bands import (
    apply_student_subject_band,
    resolve_student_band,
    validate_content_band_evidence,
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
from learning.services.stratification_visibility import visible_teacher_decisions
from ops.xlsx import build_workbook, workbook_response
from school.models import StudentProfile, TeachingAssignment


REVIEW_REASON_LABELS = {
    "classroom_evidence": "课堂表现或作品提供了补充依据",
    "recent_change": "学生近期状态发生变化",
    "support_plan": "教师已有明确的教学支持安排",
    "task_mismatch": "当前任务难度或学习机会不匹配",
    "data_issue": "平台材料缺失或记录需要核查",
    "other": "其他经教师核实的原因",
}
REVIEW_STATUS_MAP = {
    "accept": StratificationDecision.Status.ACCEPTED,
    "keep": StratificationDecision.Status.KEPT,
    "adjust": StratificationDecision.Status.ADJUSTED,
    "defer": StratificationDecision.Status.DEFERRED,
}
# Keep the write limit aligned with the suggestion workspace read limit so
# “处理当前范围全部建议” never degrades into a page-only action.
STRATIFICATION_BULK_LIMIT = 1000


class DecisionReviewError(Exception):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _parse_review_payload(decision, data, *, allow_adjust: bool = True):
    if decision.decision_kind == StratificationDecision.DecisionKind.LEGACY:
        raise DecisionReviewError(
            "该记录仅用于历史兼容，不能继续处理。", status=409
        )
    if decision.status != StratificationDecision.Status.PENDING:
        raise DecisionReviewError(
            "所选建议中包含已经处理的记录，请刷新后重新选择。", status=409
        )

    action = str(data.get("action") or "").strip()
    if action not in REVIEW_STATUS_MAP:
        raise DecisionReviewError("处理方式不正确。")
    if action == "adjust" and not allow_adjust:
        raise DecisionReviewError("批量处理不能调整 A/B/C，请逐个学生调整。")

    is_content_band = (
        decision.decision_kind == StratificationDecision.DecisionKind.CONTENT_BAND
    )
    recommendation = (
        LearningContentRecommendation.objects.select_related("target_state")
        .filter(source_decision=decision)
        .first()
        if is_content_band
        else LearningSupportRecommendation.objects.select_related(
            "target_state", "source_summary"
        )
        .filter(source_decision=decision)
        .first()
    )
    target_state = recommendation.target_state if recommendation else None
    confirms_recommendation = action in (
        {"accept", "adjust"} if is_content_band else {"accept", "keep"}
    )
    if is_content_band and action in {"accept", "adjust"}:
        try:
            recommendation = validate_content_band_evidence(decision=decision)
        except ValidationError as exc:
            raise DecisionReviewError(str(exc.messages[0]), status=409) from exc
        target_state = recommendation.target_state
    if confirms_recommendation and target_state is not None:
        if target_state.valid_until is None:
            raise DecisionReviewError(
                "该建议的学习材料未设置有效期，请先重新汇总或补充材料。",
                status=409,
            )
        if target_state.valid_until <= timezone.now():
            raise DecisionReviewError(
                "该建议所依据的学习材料已超过有效期，请先重新汇总或补充材料。",
                status=409,
            )
        if is_content_band:
            target_states = list(
                recommendation.target_states.order_by("content_recommendation_links__sort_order")
            )
            if not target_states:
                raise DecisionReviewError(
                    "该学习内容层级建议没有目标级学习依据，不能采纳。",
                    status=409,
                )
            if any(
                state.valid_until is None or state.valid_until <= timezone.now()
                for state in target_states
            ):
                raise DecisionReviewError(
                    "该建议包含已过期或未设置有效期的目标级材料，请重新计算后再处理。",
                    status=409,
                )
    elif confirms_recommendation and recommendation is not None and not is_content_band:
        evidence = recommendation.evidence_snapshot or {}
        valid_until = evidence.get("valid_until")
        if isinstance(valid_until, str):
            valid_until = parse_datetime(valid_until)
        if valid_until is None:
            raise DecisionReviewError(
                "该学习支持建议未冻结材料有效期，请先重新汇总材料。",
                status=409,
            )
        if timezone.is_naive(valid_until):
            valid_until = timezone.make_aware(
                valid_until, timezone.get_current_timezone()
            )
        if valid_until <= timezone.now():
            raise DecisionReviewError(
                "该学习支持建议所依据的材料已超过有效期，请先重新汇总材料。",
                status=409,
            )
        if (
            recommendation.source_summary_id
            and recommendation.source_summary.source_hash
            != recommendation.source_summary_hash
        ):
            raise DecisionReviewError(
                "该学习支持建议的材料版本校验失败，请重新汇总材料。",
                status=409,
            )
    if action == "adjust" and not is_content_band:
        raise DecisionReviewError("学习支持建议不能直接调整层级，请使用手动调整。")

    note = str(data.get("note") or "").strip()[:1000]
    reason_code = str(data.get("reason_code") or "").strip()
    if action in {"keep", "adjust", "defer"}:
        if reason_code not in REVIEW_REASON_LABELS:
            raise DecisionReviewError("请选择本次处理原因。")
        if reason_code == "other" and not note:
            raise DecisionReviewError("选择其他原因时请填写处理说明。")
    else:
        reason_code = ""

    selected_layer = ""
    if action == "accept" and is_content_band:
        if not decision.suggested_layer:
            raise DecisionReviewError("所选建议中有记录不能采纳层级变化。")
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
        selected_layer = str(data.get("layer") or "").upper()
        if selected_layer not in {"A", "B", "C"}:
            raise DecisionReviewError("请选择 A、B 或 C。")

    return {
        "action": action,
        "status": REVIEW_STATUS_MAP[action],
        "selected_layer": selected_layer,
        "reason_code": reason_code,
        "note": note,
        "is_content_band": is_content_band,
    }


def _apply_review(decision, review, *, actor):
    if review["is_content_band"] and review["action"] in {"accept", "adjust"}:
        apply_student_subject_band(
            decision=decision,
            selected_band=review["selected_layer"],
            confirmed_by=actor,
        )
    decision.status = review["status"]
    decision.teacher_selected_layer = review["selected_layer"]
    decision.review_reason_code = review["reason_code"]
    decision.review_note = review["note"]
    decision.reviewed_by = actor
    decision.reviewed_at = timezone.now()
    decision.save(
        update_fields=[
            "status",
            "teacher_selected_layer",
            "review_reason_code",
            "review_note",
            "reviewed_by",
            "reviewed_at",
        ]
    )
    if review["is_content_band"]:
        recommendation = LearningContentRecommendation.objects.filter(
            source_decision=decision
        ).first()
        if recommendation:
            recommendation.status = {
                "accept": LearningContentRecommendation.Status.CONFIRMED,
                "keep": LearningContentRecommendation.Status.KEPT,
                "adjust": LearningContentRecommendation.Status.ADJUSTED,
                "defer": LearningContentRecommendation.Status.NOT_RECOMMENDED,
            }.get(review["action"], recommendation.status)
            recommendation.teacher_selected_band = review["selected_layer"]
            recommendation.reviewed_by = actor
            recommendation.reviewed_at = decision.reviewed_at
            recommendation.save(
                update_fields=[
                    "status",
                    "teacher_selected_band",
                    "reviewed_by",
                    "reviewed_at",
                ]
            )
        record_band_transition_review(
            decision=decision,
            action=review["action"],
            final_band=review["selected_layer"],
            actor=actor,
        )
    else:
        recommendation = LearningSupportRecommendation.objects.filter(
            source_decision=decision
        ).first()
        if recommendation:
            recommendation.status = {
                "accept": LearningSupportRecommendation.Status.CONFIRMED,
                "keep": LearningSupportRecommendation.Status.CONFIRMED,
                "defer": LearningSupportRecommendation.Status.DEFERRED,
            }.get(review["action"], recommendation.status)
            recommendation.reviewed_by = actor
            recommendation.reviewed_at = decision.reviewed_at
            recommendation.save(
                update_fields=["status", "reviewed_by", "reviewed_at"]
            )


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
        "legacy_unmapped": snapshot.legacy_unmapped,
        "target_results": [
            {
                "id": result.id,
                "learning_target_version_id": result.learning_target_version_id,
                "learning_target_code": result.learning_target_version.code,
                "learning_target_name": result.learning_target_version.title,
                "target_version_hash": result.learning_target_version.content_hash,
                "data_status": result.data_status,
                "data_status_label": result.get_data_status_display(),
                "mastery_score": result.mastery_score,
                "measurement_error": result.measurement_error,
                "item_count": result.item_count,
                "answered_item_count": result.answered_item_count,
                "evidence_coverage": result.evidence_coverage,
                "content_hash": result.content_hash,
            }
            for result in snapshot.target_results.all()
        ],
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


def _decision_row(decision, *, resolved_layer=None):
    profile = decision.student.student_profile
    current_layer = (
        resolved_layer
        if resolved_layer is not None
        else resolve_student_band(
            student=decision.student,
            subject=decision.subject,
            course=decision.course,
        )
        if decision.subject_id
        else None
    )
    content_recommendation = getattr(decision, "content_recommendation", None)
    support_recommendation = getattr(decision, "support_recommendation", None)
    recommendation = (
        content_recommendation
        if decision.decision_kind == StratificationDecision.DecisionKind.CONTENT_BAND
        else support_recommendation
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
            dict(StudentSubjectBand.Band.choices).get(current_layer, "")
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
        "recommendation_status": (
            recommendation.status
            if recommendation
            else "not_recommended"
            if decision.decision_kind == StratificationDecision.DecisionKind.CONTENT_BAND
            and not decision.suggested_layer
            else ""
        ),
        "recommendation_status_label": (
            recommendation.get_status_display()
            if recommendation
            else "暂不建议"
            if decision.decision_kind == StratificationDecision.DecisionKind.CONTENT_BAND
            and not decision.suggested_layer
            else ""
        ),
        "target_state": (
            {
                "id": recommendation.target_state_id,
                "learning_target_code": recommendation.target_state.learning_target_code,
                "learning_target_name": recommendation.target_state.learning_target_name,
                "evidence_status": recommendation.target_state.evidence_status,
                "evidence_status_label": recommendation.target_state.get_evidence_status_display(),
                "evidence_coverage": recommendation.target_state.evidence_coverage,
                "uncertainty": recommendation.target_state.uncertainty,
                "valid_until": recommendation.target_state.valid_until,
            }
            if recommendation and recommendation.target_state_id
            else None
        ),
        "target_states": (
            [
                {
                    "id": link.target_state_id,
                    "learning_target_version_id": link.target_state.learning_target_version_id,
                    "learning_target_code": link.target_state.learning_target_code,
                    "learning_target_name": link.target_state.learning_target_name,
                    "evidence_status": link.target_state.evidence_status,
                    "evidence_coverage": link.target_state.evidence_coverage,
                    "estimate": link.target_state.estimate,
                    "uncertainty": link.target_state.uncertainty,
                    "valid_until": link.target_state.valid_until,
                    "content_hash": link.target_state.content_hash,
                }
                for link in content_recommendation.target_state_links.all()
            ]
            if content_recommendation
            else []
        ),
        "support_evidence": (
            {
                "source_summary_id": support_recommendation.source_summary_id,
                "source_summary_hash": support_recommendation.source_summary_hash,
                "source_hash": support_recommendation.source_hash,
                "evidence_snapshot": support_recommendation.evidence_snapshot,
                "learning_target_estimate": None,
            }
            if support_recommendation
            else None
        ),
        "transition_checks": decision.transition_checks,
        "mastery_snapshot_id": decision.mastery_snapshot_id,
        "rule_version": decision.rule_version,
        "source_label": (
            "教师手动调整"
            if decision.rule_version.startswith("teacher-manual-")
            else "班级校准候选"
            if decision.rule_version.startswith("m03-")
            else "学习支持建议"
            if decision.decision_kind == StratificationDecision.DecisionKind.SUPPORT
            else "共同测试层级建议"
        ),
        "window_start": decision.window_start,
        "window_end": decision.window_end,
        "status": decision.status,
        "status_label": decision.get_status_display(),
        "teacher_selected_layer": decision.teacher_selected_layer,
        "review_reason_code": decision.review_reason_code,
        "review_reason_label": REVIEW_REASON_LABELS.get(
            decision.review_reason_code, ""
        ),
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
        visible_teacher_decisions(teacher=user, class_ids=class_ids)
        .select_related(
            "student__student_profile",
            "class_group",
            "subject",
            "course",
            "reviewed_by",
            "content_recommendation__target_state",
            "support_recommendation__target_state",
            "support_recommendation__source_summary",
        )
        .prefetch_related(
            "content_recommendation__target_state_links__target_state"
        )
    )


def _target_state_row(state):
    latest_content = state.content_recommendations.order_by("-created_at", "-id").first()
    latest_support = state.support_recommendations.order_by("-created_at", "-id").first()
    return {
        "id": state.id,
        "student": {
            "id": state.student_id,
            "username": state.student.username,
            "display_name": state.student.display_name or state.student.username,
            "student_no": state.student.student_profile.student_no,
        },
        "class_group": {
            "id": state.class_group_id,
            "name": state.class_group.name,
            "grade": state.class_group.grade,
        },
        "subject": {"id": state.subject_id, "name": state.subject.name},
        "course": (
            {"id": state.course_id, "title": state.course.title}
            if state.course_id
            else None
        ),
        "learning_target_code": state.learning_target_code,
        "learning_target_name": state.learning_target_name,
        "learning_target_version_id": state.learning_target_version_id,
        "legacy_unmapped": state.legacy_unmapped,
        "evidence_status": state.evidence_status,
        "evidence_status_label": state.get_evidence_status_display(),
        "evidence_coverage": state.evidence_coverage,
        "estimate": state.estimate,
        "uncertainty": state.uncertainty,
        "is_initial_diagnostic": state.is_initial_diagnostic,
        "observed_at": state.observed_at,
        "valid_until": state.valid_until,
        "content_recommendation": (
            {
                "status": latest_content.status,
                "status_label": latest_content.get_status_display(),
                "suggested_band": latest_content.suggested_band,
            }
            if latest_content
            else None
        ),
        "support_recommendation": (
            {
                "status": latest_support.status,
                "status_label": latest_support.get_status_display(),
                "priority": latest_support.priority,
                "suggestion": latest_support.suggestion,
            }
            if latest_support
            else None
        ),
    }


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
    now = timezone.now()
    active_bands = []
    if course and student_ids:
        active_bands = list(
            StudentSubjectBand.objects.filter(
                student_id__in=student_ids,
                subject=course.subject,
                valid_from__lte=now,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gt=now))
            .filter(Q(course=course) | Q(course__isnull=True))
            .annotate(
                course_priority=Case(
                    When(course=course, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by("student_id", "course_priority", "-valid_from", "-id")
        )
    active_band_by_student = {}
    for band in active_bands:
        active_band_by_student.setdefault(band.student_id, band.band)
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
            active_band_by_student.get(profile.user_id)
            if course and band_course and band_course.id == course.id
            else resolve_student_band(
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
                    dict(StudentSubjectBand.Band.choices).get(layer, "未分层")
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
                "latest_decision": (
                    _decision_row(decision, resolved_layer=layer or "")
                    if decision
                    else None
                ),
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
def learning_target_states(request):
    class_ids = set(_teacher_class_ids(request.user))
    teaching_scopes = list(
        CourseClass.objects.filter(
            course__teacher=request.user,
            course__subject__school=request.user.school,
            class_group_id__in=class_ids,
        ).values_list("class_group_id", "course_id", "course__subject_id")
    )
    visible_class_ids = {class_group_id for class_group_id, _course_id, _subject_id in teaching_scopes}
    visible_course_ids = {course_id for _class_group_id, course_id, _subject_id in teaching_scopes}
    state_scope = Q(pk__in=[])
    subject_scopes = set()
    for class_group_id, course_id, subject_id in teaching_scopes:
        state_scope |= Q(
            class_group_id=class_group_id,
            subject_id=subject_id,
            course_id=course_id,
        )
        subject_scopes.add((class_group_id, subject_id))
    for class_group_id, subject_id in subject_scopes:
        state_scope |= Q(
            class_group_id=class_group_id,
            subject_id=subject_id,
            course__isnull=True,
        )

    rows = StudentLearningTargetStateVersion.objects.filter(
        state_scope,
        school=request.user.school,
    ).select_related(
        "student__student_profile",
        "class_group",
        "subject",
        "course",
    ).prefetch_related("content_recommendations", "support_recommendations")
    if request.query_params.get("class_group"):
        try:
            class_group_id = int(request.query_params["class_group"])
        except (TypeError, ValueError):
            return fail("班级筛选条件不正确。", status=400)
        if class_group_id not in visible_class_ids:
            return fail("学习目标情况不存在或无权查看。", status=404)
        rows = rows.filter(class_group_id=class_group_id)
    if request.query_params.get("course"):
        try:
            course_id = int(request.query_params["course"])
        except (TypeError, ValueError):
            return fail("课程筛选条件不正确。", status=400)
        if course_id not in visible_course_ids:
            return fail("学习目标情况不存在或无权查看。", status=404)
        rows = rows.filter(course_id=course_id)
    if request.query_params.get("student"):
        rows = rows.filter(student_id=request.query_params["student"])
    if request.query_params.get("learning_target_code"):
        rows = rows.filter(
            learning_target_code=request.query_params["learning_target_code"]
        )
    return ok([_target_state_row(row) for row in rows[:1000]])


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
        .prefetch_related("target_results__learning_target_version")
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
    visible_id = (
        _visible_stratification_decisions(request.user, class_ids)
        .filter(pk=pk)
        .values_list("pk", flat=True)
        .first()
    )
    if visible_id is None:
        return fail("学习安排建议不存在或无权处理。", status=404)
    try:
        with transaction.atomic():
            decision = (
                StratificationDecision.objects.select_for_update()
                .select_related("student", "class_group", "subject", "course")
                .filter(pk=visible_id)
                .first()
            )
            if decision is None:
                raise DecisionReviewError(
                    "学习安排建议不存在或无权处理。", status=404
                )
            review = _parse_review_payload(decision, request.data)
            _apply_review(decision, review, actor=request.user)
            write_audit(
                request,
                "teacher.stratification.review",
                school=request.user.school,
                target_type="stratification_decision",
                target_id=decision.id,
                detail={
                    "action": review["action"],
                    "selected_layer": review["selected_layer"],
                    "reason_code": review["reason_code"],
                    "layer_applied": review["is_content_band"]
                    and review["action"] in {"accept", "adjust"},
                },
            )
    except DecisionReviewError as exc:
        return fail(exc.message, status=exc.status)

    decision = StratificationDecision.objects.select_related(
        "student__student_profile", "class_group", "subject", "course", "reviewed_by"
    ).get(pk=decision.pk)
    return ok(_decision_row(decision), "学习安排建议已处理。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def bulk_review_stratification_suggestions(request):
    raw_ids = request.data.get("ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return fail("请至少选择一条待处理建议。", status=400)
    if len(raw_ids) > STRATIFICATION_BULK_LIMIT:
        return fail(
            f"单次最多处理 {STRATIFICATION_BULK_LIMIT} 条建议。", status=400
        )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_ids):
        return fail("建议编号格式不正确。", status=400)
    ids = list(dict.fromkeys(raw_ids))
    if len(ids) != len(raw_ids):
        return fail("建议编号不能重复。", status=400)

    action = str(request.data.get("action") or "").strip()
    if action == "adjust":
        return fail("批量处理不能调整 A/B/C，请逐个学生调整。", status=400)

    class_ids = _teacher_class_ids(request.user)
    visible_ids = set(
        _visible_stratification_decisions(request.user, class_ids)
        .filter(pk__in=ids)
        .values_list("pk", flat=True)
    )
    if visible_ids != set(ids):
        return fail("所选建议中包含不存在、未发布或无权处理的记录。", status=404)

    try:
        with transaction.atomic():
            locked_rows = list(
                StratificationDecision.objects.select_for_update()
                .select_related("student", "class_group", "subject", "course")
                .filter(pk__in=ids)
            )
            if len(locked_rows) != len(ids):
                raise DecisionReviewError(
                    "所选建议中包含不存在或无权处理的记录。", status=404
                )
            rows_by_id = {row.id: row for row in locked_rows}
            ordered_rows = [rows_by_id[item_id] for item_id in ids]
            prepared = [
                (row, _parse_review_payload(row, request.data, allow_adjust=False))
                for row in ordered_rows
            ]
            for row, review in prepared:
                _apply_review(row, review, actor=request.user)
            write_audit(
                request,
                "teacher.stratification.bulk_review",
                school=request.user.school,
                target_type="stratification_decision_batch",
                detail={
                    "ids": ids,
                    "count": len(ids),
                    "action": action,
                    "reason_code": str(request.data.get("reason_code") or "").strip(),
                    "content_band_count": sum(
                        int(review["is_content_band"]) for _row, review in prepared
                    ),
                    "support_count": sum(
                        int(not review["is_content_band"]) for _row, review in prepared
                    ),
                },
            )
    except DecisionReviewError as exc:
        return fail(exc.message, status=exc.status)

    return ok(
        {"updated_count": len(ids), "ids": ids, "action": action},
        f"已批量处理 {len(ids)} 条建议。",
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def manually_adjust_stratification(request):
    try:
        student_id = int(request.data.get("student") or 0)
        course_id = int(request.data.get("course") or 0)
        source_decision_id = int(request.data.get("source_decision") or 0)
    except (TypeError, ValueError):
        return fail("学生、课程或依据建议参数不正确。", status=400)
    if source_decision_id <= 0:
        return fail("再次调整必须选择一条可追溯的学习内容层级依据。", status=400)
    selected_layer = str(request.data.get("layer") or "").strip().upper()
    if selected_layer not in {"A", "B", "C"}:
        return fail("请选择 A、B 或 C。", status=400)
    reason_code = str(request.data.get("reason_code") or "").strip()
    if reason_code not in REVIEW_REASON_LABELS:
        return fail("请选择本次调整原因。", status=400)
    note = str(request.data.get("note") or "").strip()[:1000]
    if reason_code == "other" and not note:
        return fail("选择其他原因时请填写说明。", status=400)

    class_ids = set(_teacher_class_ids(request.user))
    profile = (
        StudentProfile.objects.select_related("user", "class_group")
        .filter(
            user_id=student_id,
            user__school=request.user.school,
            user__is_active=True,
            class_group_id__in=class_ids,
        )
        .first()
    )
    course = (
        Course.objects.select_related("subject")
        .filter(
            pk=course_id,
            teacher=request.user,
            subject__school=request.user.school,
            course_classes__class_group_id=profile.class_group_id if profile else None,
        )
        .distinct()
        .first()
    )
    if profile is None or course is None:
        return fail("学生或课程不存在，或无权调整。", status=404)

    source_decision = (
        _visible_stratification_decisions(request.user, class_ids)
        .select_related("student", "class_group", "subject", "course")
        .filter(
            pk=source_decision_id,
            student_id=profile.user_id,
            course=course,
            decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
        )
        .first()
    )
    if source_decision is None:
        return fail("学习内容层级依据不存在，或不在当前任教范围内。", status=404)
    try:
        source_recommendation = validate_content_band_evidence(
            decision=source_decision,
            require_pending_recommendation=False,
        )
    except ValidationError as exc:
        return fail(str(exc.messages[0]), status=409)
    source_links = list(
        source_recommendation.target_state_links.select_related("target_state")
        .order_by("sort_order", "id")
    )

    current_layer = resolve_student_band(
        student=profile.user,
        subject=course.subject,
        course=course,
    ) or ""
    if current_layer == selected_layer:
        return fail(f"该学生当前已经是 {selected_layer} 层。", status=400)

    now = timezone.now()
    with transaction.atomic():
        decision = StratificationDecision.objects.create(
            student=profile.user,
            class_group=profile.class_group,
            subject=course.subject,
            course=course,
            previous_layer=current_layer,
            suggested_layer=selected_layer,
            confidence=0,
            reasons=[REVIEW_REASON_LABELS[reason_code]],
            missing_data=[],
            learning_summary={
                "source": "teacher_manual_adjustment",
                "source_decision_id": source_decision.id,
                "source_recommendation_id": source_recommendation.id,
                "target_state_ids": [link.target_state_id for link in source_links],
                "reason_code": reason_code,
                "confidence_status": "not_applicable",
            },
            support_suggestion="",
            decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            policy_version=source_decision.policy_version,
            policy=source_decision.policy,
            mastery_snapshot=source_decision.mastery_snapshot,
            transition_checks={
                "manual_override": True,
                "reason_code": reason_code,
                "source_decision_id": source_decision.id,
            },
            window_start=now,
            window_end=now,
            rule_version=f"teacher-manual-{now.strftime('%y%m%d%H%M%S%f')}"[:32],
            teacher_selected_layer=selected_layer,
            review_reason_code=reason_code,
            review_note=note,
            status=StratificationDecision.Status.ADJUSTED,
            reviewed_by=request.user,
            reviewed_at=now,
        )
        recommendation = LearningContentRecommendation.objects.create(
            source_decision=decision,
            target_state=source_links[0].target_state,
            suggested_band=selected_layer,
            status=LearningContentRecommendation.Status.PENDING,
            rationale=[
                REVIEW_REASON_LABELS[reason_code],
                f"沿用已复核建议 {source_decision.id} 的目标级材料。",
            ],
            evidence_coverage=source_recommendation.evidence_coverage,
            uncertainty=source_recommendation.uncertainty,
        )
        for link in source_links:
            recommendation.target_state_links.create(
                target_state=link.target_state,
                sort_order=link.sort_order,
            )
        apply_student_subject_band(
            decision=decision,
            selected_band=selected_layer,
            confirmed_by=request.user,
            effective_at=now,
        )
        recommendation.status = LearningContentRecommendation.Status.ADJUSTED
        recommendation.teacher_selected_band = selected_layer
        recommendation.reviewed_by = request.user
        recommendation.reviewed_at = now
        recommendation.save(
            update_fields=[
                "status",
                "teacher_selected_band",
                "reviewed_by",
                "reviewed_at",
            ]
        )
        record_band_transition_review(
            decision=decision,
            action="manual_adjust",
            final_band=selected_layer,
            actor=request.user,
        )
    write_audit(
        request,
        "teacher.stratification.manual_adjust",
        school=request.user.school,
        target_type="stratification_decision",
        target_id=decision.id,
        detail={
            "student_id": profile.user_id,
            "course_id": course.id,
            "source_decision_id": source_decision.id,
            "previous_layer": current_layer,
            "selected_layer": selected_layer,
            "reason_code": reason_code,
        },
    )
    return ok(_decision_row(decision), "学生层级已调整。")
