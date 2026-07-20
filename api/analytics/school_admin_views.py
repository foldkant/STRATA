from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsSchoolAdmin
from api.responses import fail, ok
from api.services import write_audit
from courses.models import Course, CourseClass, Subject
from learning.models import ContentBandPolicyVersion, TestAssessment
from learning.services.mastery import (
    build_assessment_mastery_candidates,
    publish_content_band_policy,
)
from learning_analytics.models import (
    AnalyticsPipelineRun,
    AnalyticsTaskRun,
    DataQualityReport,
    DecisionPoint,
    FeatureDefinition,
    FeatureSetVersion,
    OutcomeDefinition,
    OutcomeObservation,
    StudentFeatureSnapshot,
    TrainingDatasetVersion,
    ClassCalibrationRun,
    LongitudinalAnalysisRun,
    ModelComparisonRun,
    ModelPrediction,
    ModelRelease,
    ModelReleaseAudit,
)
from learning_analytics.services.feature_registry import (
    sync_feature_and_outcome_definitions,
)
from learning_analytics.services.feature_snapshots import create_decision_point
from learning_analytics.services.outcomes import (
    build_training_dataset,
    mature_due_outcomes,
)
from learning_analytics.services.longitudinal import build_longitudinal_analysis
from learning_analytics.services.model_comparison import build_model_comparison
from learning_analytics.services.advanced_models import build_model_02_comparison
from learning_analytics.services.class_calibration import (
    build_class_calibration_candidate,
)
from learning_analytics.services.model_packages import (
    publish_model_candidate,
    rollback_model_release,
    verify_model_release,
)
from learning_analytics.services.quality import (
    QUALITY_THRESHOLDS,
    latest_quality_report,
    trailing_window,
)
from learning_analytics.tasks import dispatch_school_data_quality_pipeline
from ops.xlsx import build_workbook, workbook_response
from school.models import ClassGroup

METRIC_LABELS = {
    "duplicate_rate": "重复事件率",
    "invalid_event_rate": "无效事件率",
    "late_event_rate": "迟到事件率",
    "unconverted_old_event_rate": "旧事件未转换比例",
    "learning_task_link_rate": "学习任务关联率",
    "client_offline_rate": "客户端离线率",
    "old_new_event_difference_rate": "新旧记录差异率",
}

TASK_LABELS = {
    "collect_learning_data": "汇总学习记录",
    "compare_old_new_records": "核对新旧记录",
    "save_data_check_report": "保存检查报告",
}


def _content_band_policy_row(policy: ContentBandPolicyVersion) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "school": policy.school_id,
        "subject": {
            "id": policy.subject_id,
            "name": policy.subject.name,
            "code": policy.subject.code,
        },
        "course": (
            {"id": policy.course_id, "title": policy.course.title}
            if policy.course_id
            else None
        ),
        "version_no": policy.version_no,
        "policy_version": policy.policy_version,
        "a_min": policy.a_min,
        "b_min": policy.b_min,
        "boundary_margin": policy.boundary_margin,
        "hysteresis_margin": policy.hysteresis_margin,
        "max_measurement_error": policy.max_measurement_error,
        "min_common_items": policy.min_common_items,
        "min_answered_ratio": policy.min_answered_ratio,
        "required_consecutive_windows": policy.required_consecutive_windows,
        "cooldown_days": policy.cooldown_days,
        "max_step_change": policy.max_step_change,
        "status": policy.status,
        "status_label": policy.get_status_display(),
        "content_hash": policy.content_hash,
        "published_at": policy.published_at,
        "created_at": policy.created_at,
    }


def _number(data, key: str, default, *, integer=False):
    value = data.get(key, default)
    try:
        return int(value) if integer else float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({key: "请输入有效数值。"}) from exc


def _include_test_data(request) -> bool:
    return bool(
        settings.DEBUG
        and str(request.query_params.get("include_test_data") or "").lower()
        in {"1", "true", "yes"}
    )


def _task_row(task: AnalyticsTaskRun) -> dict:
    return {
        "id": task.id,
        "task_id": str(task.task_id),
        "task_name": task.task_name,
        "task_label": TASK_LABELS.get(task.task_name, task.task_name),
        "status": task.status,
        "status_label": task.get_status_display(),
        "attempt_no": task.attempt_no,
        "metrics": task.metrics,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _run_row(run: AnalyticsPipelineRun) -> dict:
    tasks = getattr(run, "prefetched_tasks", [])
    return {
        "id": run.id,
        "run_id": str(run.run_id),
        "status": run.status,
        "status_label": run.get_status_display(),
        "trigger": run.trigger,
        "trigger_label": run.get_trigger_display(),
        "attempt_no": run.attempt_no,
        "window_start": run.window_start,
        "window_end": run.window_end,
        "check_version": run.check_version,
        "summary": run.summary,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "tasks": [_task_row(task) for task in tasks],
    }


def _report_row(report: DataQualityReport) -> dict:
    issue_by_metric = {
        issue.get("metric"): issue.get("level")
        for issue in report.issues
        if isinstance(issue, dict) and issue.get("metric")
    }
    metrics = []
    for key, label in METRIC_LABELS.items():
        metrics.append(
            {
                "key": key,
                "label": label,
                "value": float(getattr(report, key)),
                "level": issue_by_metric.get(key, "green"),
                "thresholds": report.thresholds.get(
                    key, QUALITY_THRESHOLDS.get(key, {})
                ),
            }
        )
    return {
        "id": report.id,
        "report_id": str(report.report_id),
        "status": report.status,
        "status_label": report.get_status_display(),
        "checks_passed": report.checks_passed,
        "window_start": report.window_start,
        "window_end": report.window_end,
        "check_version": report.check_version,
        "source_checksum": report.source_checksum,
        "event_count": report.event_count,
        "receive_attempt_count": report.receive_attempt_count,
        "rejected_event_count": report.rejected_event_count,
        "unconverted_old_event_count": report.unconverted_old_event_count,
        "unlinked_old_event_count": report.unlinked_old_event_count,
        "metrics": metrics,
        "counts": report.counts,
        "issues": report.issues,
        "generated_at": report.generated_at,
        "pipeline_run_id": report.pipeline_run_id,
    }


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_quality(request):
    school = request.user.school
    reports = list(
        DataQualityReport.objects.filter(
            school=school,
            synthetic_run__isnull=True,
        )
        .select_related("pipeline_run")
        .order_by("-window_end", "-created_at")[:30]
    )
    runs = list(
        AnalyticsPipelineRun.objects.filter(
            school=school,
            pipeline_type=AnalyticsPipelineRun.PipelineType.DATA_QUALITY,
            synthetic_run__isnull=True,
        )
        .prefetch_related(
            Prefetch(
                "task_runs",
                queryset=AnalyticsTaskRun.objects.order_by("created_at"),
                to_attr="prefetched_tasks",
            )
        )
        .order_by("-created_at")[:20]
    )
    return ok(
        {
            "school": {"id": school.id, "name": school.name, "code": school.code},
            "current": _report_row(reports[0]) if reports else None,
            "history": [_report_row(report) for report in reports],
            "runs": [_run_row(run) for run in runs],
        }
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def run_school_quality(request):
    school = request.user.school
    if AnalyticsPipelineRun.objects.filter(
        school=school,
        pipeline_type=AnalyticsPipelineRun.PipelineType.DATA_QUALITY,
        synthetic_run__isnull=True,
        status__in={
            AnalyticsPipelineRun.Status.PENDING,
            AnalyticsPipelineRun.Status.RUNNING,
        },
    ).exists():
        return fail("本校已有数据检查任务正在等待或运行。", status=409)
    try:
        days = int(request.data.get("days") or 7)
        window_start, window_end = trailing_window(days=days)
    except (TypeError, ValueError):
        return fail(
            "统计窗口不正确。",
            errors={"days": ["统计天数必须是 1 至 365 的整数。"]},
            status=400,
        )
    try:
        run, async_result = dispatch_school_data_quality_pipeline(
            school=school,
            window_start=window_start,
            window_end=window_end,
            trigger=AnalyticsPipelineRun.Trigger.MANUAL,
        )
    except Exception as exc:
        return fail(f"数据检查任务未能提交：{exc}", status=503)
    return ok(
        {"run": _run_row(run), "task_id": async_result.id},
        "数据检查任务已提交。",
        status=202,
    )


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def export_school_quality(request):
    school = request.user.school
    reports = list(
        DataQualityReport.objects.filter(
            school=school,
            synthetic_run__isnull=True,
        )
        .select_related("pipeline_run")
        .order_by("-window_end", "-created_at")[:100]
    )
    runs = list(
        AnalyticsPipelineRun.objects.filter(
            school=school,
            pipeline_type=AnalyticsPipelineRun.PipelineType.DATA_QUALITY,
            synthetic_run__isnull=True,
        )
        .prefetch_related("task_runs")
        .order_by("-created_at")[:100]
    )

    report_rows = [
        [
            report.report_id,
            report.get_status_display(),
            "通过" if report.checks_passed else "未通过",
            report.window_start,
            report.window_end,
            report.event_count,
            report.receive_attempt_count,
            report.rejected_event_count,
            report.unconverted_old_event_count,
            report.unlinked_old_event_count,
            report.check_version,
            report.source_checksum,
            report.generated_at,
        ]
        for report in reports
    ]
    metric_rows = []
    issue_rows = []
    for report in reports:
        for key, label in METRIC_LABELS.items():
            threshold = report.thresholds.get(key, {})
            metric_rows.append(
                [
                    report.report_id,
                    label,
                    float(getattr(report, key)),
                    ("低于" if threshold.get("direction") == "low" else "高于"),
                    threshold.get("amber", ""),
                    threshold.get("red", ""),
                ]
            )
        for issue in report.issues:
            if not isinstance(issue, dict):
                continue
            issue_rows.append(
                [
                    report.report_id,
                    "未通过" if issue.get("level") == "red" else "提醒",
                    issue.get("code", ""),
                    METRIC_LABELS.get(issue.get("metric"), issue.get("metric", "")),
                    issue.get("value", ""),
                    issue.get("threshold", ""),
                ]
            )
    run_rows = []
    task_rows = []
    for run in runs:
        run_rows.append(
            [
                run.run_id,
                run.get_trigger_display(),
                run.get_status_display(),
                run.attempt_no,
                run.window_start,
                run.window_end,
                run.check_version,
                run.error_code,
                run.error_message,
                run.started_at,
                run.finished_at,
            ]
        )
        for task in run.task_runs.all():
            task_rows.append(
                [
                    run.run_id,
                    task.task_id,
                    TASK_LABELS.get(task.task_name, task.task_name),
                    task.get_status_display(),
                    task.attempt_no,
                    task.error_code,
                    task.error_message,
                    task.started_at,
                    task.finished_at,
                ]
            )
    workbook = build_workbook(
        [
            {
                "title": "检查报告",
                "headers": [
                    "报告ID",
                    "检查状态",
                    "检查",
                    "窗口开始",
                    "窗口结束",
                    "事件数",
                    "接收尝试数",
                    "拒绝数",
                    "未转换旧事件数",
                    "未关联旧记录数",
                    "检查版本",
                    "来源校验码",
                    "生成时间",
                ],
                "rows": report_rows,
            },
            {
                "title": "检查指标",
                "headers": [
                    "报告ID",
                    "指标",
                    "比率",
                    "判断方向",
                    "提醒标准",
                    "不通过标准",
                ],
                "rows": metric_rows,
            },
            {
                "title": "待处理问题",
                "headers": ["报告ID", "级别", "问题代码", "指标", "实际值", "判断标准"],
                "rows": issue_rows,
            },
            {
                "title": "自动检查记录",
                "headers": [
                    "运行ID",
                    "触发方式",
                    "状态",
                    "尝试次数",
                    "窗口开始",
                    "窗口结束",
                    "检查版本",
                    "错误代码",
                    "错误信息",
                    "开始时间",
                    "结束时间",
                ],
                "rows": run_rows,
            },
            {
                "title": "执行阶段",
                "headers": [
                    "运行ID",
                    "任务ID",
                    "任务名称",
                    "状态",
                    "尝试次数",
                    "错误代码",
                    "错误信息",
                    "开始时间",
                    "结束时间",
                ],
                "rows": task_rows,
            },
        ]
    )
    return workbook_response(
        workbook,
        f"{school.code}-学习数据检查-{timezone.localdate():%Y%m%d}.xlsx",
    )


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        return "；".join(
            message for messages in exc.message_dict.values() for message in messages
        )
    return "；".join(exc.messages)


def _current_outcomes(queryset):
    if hasattr(queryset, "order_by"):
        rows = queryset.order_by(
            "decision_point_id",
            "student_id",
            "outcome_definition_id",
            "-observation_version",
            "-id",
        )
    else:
        rows = sorted(
            queryset,
            key=lambda item: (
                item.decision_point_id,
                item.student_id,
                item.outcome_definition_id,
                -item.observation_version,
                -item.id,
            ),
        )
    latest = {}
    for item in rows:
        key = (
            item.decision_point_id,
            item.student_id,
            item.outcome_definition_id,
        )
        latest.setdefault(key, item)
    return list(latest.values())


def _decision_point_row(point: DecisionPoint) -> dict:
    snapshots = list(getattr(point, "prefetched_snapshots", []))
    prefetched_outcomes = getattr(point, "prefetched_outcomes", None)
    outcomes = _current_outcomes(
        OutcomeObservation.objects.filter(decision_point=point)
        if prefetched_outcomes is None
        else prefetched_outcomes
    )
    return {
        "id": point.id,
        "decision_id": str(point.decision_id),
        "title": point.title,
        "class_group": {
            "id": point.class_group_id,
            "name": point.class_group.name,
        },
        "subject": {"id": point.subject_id, "name": point.subject.name},
        "course": (
            {"id": point.course_id, "title": point.course.title}
            if point.course_id
            else None
        ),
        "purpose": point.purpose,
        "purpose_label": point.get_purpose_display(),
        "status": point.status,
        "status_label": point.get_status_display(),
        "scheduled_for": point.scheduled_for,
        "frozen_at": point.frozen_at,
        "student_count": point.context_snapshot.get("eligible_student_count", 0),
        "quality_checks_passed": point.context_snapshot.get(
            "quality_checks_passed", False
        ),
        "snapshot_counts": {
            status: sum(item.quality_status == status for item in snapshots)
            for status, _label in StudentFeatureSnapshot.QualityStatus.choices
        },
        "outcome_counts": {
            status: sum(item.status == status for item in outcomes)
            for status, _label in OutcomeObservation.Status.choices
        },
    }


def _dataset_row(dataset: TrainingDatasetVersion) -> dict:
    return {
        "id": dataset.id,
        "dataset_id": str(dataset.dataset_id),
        "dataset_key": dataset.dataset_key,
        "subject": {"id": dataset.subject_id, "name": dataset.subject.name},
        "outcome": {
            "key": dataset.outcome_definition.outcome_key,
            "label": dataset.outcome_definition.label,
            "version": dataset.outcome_definition.version,
        },
        "feature_set": {
            "key": dataset.feature_set.set_key,
            "version": dataset.feature_set.version,
        },
        "status": dataset.status,
        "status_label": dataset.get_status_display(),
        "decision_start": dataset.decision_start,
        "decision_end": dataset.decision_end,
        "row_count": dataset.row_count,
        "observed_count": dataset.observed_count,
        "unobserved_count": dataset.unobserved_count,
        "excluded_count": dataset.excluded_count,
        "comparison_ready": bool(dataset.manifest.get("comparison_ready")),
        "blockers": dataset.manifest.get("blockers", []),
        "manifest_hash": dataset.manifest_hash,
        "created_at": dataset.created_at,
        "frozen_at": dataset.frozen_at,
        "is_test_data": bool(dataset.synthetic_run_id),
    }


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def analysis_preparation(request):
    sync_feature_and_outcome_definitions()
    school = request.user.school
    include_test_data = _include_test_data(request)
    feature_set = FeatureSetVersion.objects.filter(
        status=FeatureSetVersion.Status.ACTIVE
    ).first()
    features = FeatureDefinition.objects.filter(status=FeatureDefinition.Status.ACTIVE)
    outcome_definitions = list(
        OutcomeDefinition.objects.filter(
            status=OutcomeDefinition.Status.ACTIVE
        ).order_by("outcome_key")
    )
    point_query = DecisionPoint.objects.filter(school=school)
    if not include_test_data:
        point_query = point_query.filter(synthetic_run__isnull=True)
    points = list(
        point_query
        .select_related("class_group", "subject", "course", "feature_set")
        .prefetch_related(
            Prefetch(
                "feature_snapshots",
                queryset=StudentFeatureSnapshot.objects.filter(
                    view_type=StudentFeatureSnapshot.ViewType.OPERATIONAL
                ),
                to_attr="prefetched_snapshots",
            ),
            Prefetch(
                "outcome_observations",
                queryset=OutcomeObservation.objects.order_by(
                    "student_id",
                    "outcome_definition_id",
                    "-observation_version",
                ),
                to_attr="prefetched_outcomes",
            ),
        )
        .order_by("-scheduled_for")[:30]
    )
    dataset_query = TrainingDatasetVersion.objects.filter(school=school)
    if not include_test_data:
        dataset_query = dataset_query.filter(synthetic_run__isnull=True)
    datasets = list(
        dataset_query
        .select_related("subject", "feature_set", "outcome_definition")
        .order_by("-created_at")[:30]
    )
    outcome_query = OutcomeObservation.objects.filter(decision_point__school=school)
    if not include_test_data:
        outcome_query = outcome_query.filter(
            decision_point__synthetic_run__isnull=True
        )
    current_outcomes = _current_outcomes(outcome_query)
    snapshot_query = StudentFeatureSnapshot.objects.filter(
        school=school,
        view_type=StudentFeatureSnapshot.ViewType.OPERATIONAL,
    )
    if not include_test_data:
        snapshot_query = snapshot_query.filter(
            decision_point__synthetic_run__isnull=True
        )
    quality_report = latest_quality_report(school=school)
    blockers = []
    if quality_report is None:
        blockers.append("还没有学习数据检查报告。")
    elif not quality_report.checks_passed:
        blockers.append("最近一次学习数据检查未通过。")
    if not points:
        blockers.append("还没有建立分析时间点。")
    if not any(
        item.status == OutcomeObservation.Status.OBSERVED for item in current_outcomes
    ):
        blockers.append("还没有到期且可用的未来学习结果。")
    if not datasets:
        blockers.append("还没有生成冻结的数据版本。")

    classes = list(
        ClassGroup.objects.filter(
            school=school,
            status=ClassGroup.Status.ACTIVE,
        )
        .annotate(
            active_student_count=Count(
                "students",
                filter=Q(students__user__is_active=True),
            )
        )
        .order_by("grade", "name")
    )
    courses = list(
        Course.objects.filter(
            subject__school=school,
            is_active=True,
        )
        .select_related("subject", "teacher")
        .prefetch_related("course_classes")
        .order_by("subject__name", "title")
    )
    return ok(
        {
            "school": {"id": school.id, "name": school.name, "code": school.code},
            "test_data_visible": include_test_data,
            "summary": {
                "feature_definition_count": features.count(),
                "model_input_feature_count": features.filter(
                    model_input_allowed=True
                ).count(),
                "audit_feature_count": features.filter(
                    model_input_allowed=False
                ).count(),
                "decision_point_count": len(points),
                "snapshot_count": snapshot_query.count(),
                "ready_snapshot_count": snapshot_query.filter(
                    quality_status=StudentFeatureSnapshot.QualityStatus.READY
                ).count(),
                "observed_outcome_count": sum(
                    item.status == OutcomeObservation.Status.OBSERVED
                    for item in current_outcomes
                ),
                "pending_outcome_count": sum(
                    item.status == OutcomeObservation.Status.PENDING
                    for item in current_outcomes
                ),
                "dataset_count": len(datasets),
                "comparison_ready_dataset_count": sum(
                    bool(item.manifest.get("comparison_ready")) for item in datasets
                ),
            },
            "feature_set": (
                {
                    "key": feature_set.set_key,
                    "version": feature_set.version,
                    "label": feature_set.label,
                    "manifest_hash": feature_set.manifest_hash,
                }
                if feature_set
                else None
            ),
            "feature_groups": [
                {
                    "key": key,
                    "label": label,
                    "count": features.filter(evidence_group=key).count(),
                }
                for key, label in FeatureDefinition.EvidenceGroup.choices
            ],
            "outcome_definitions": [
                {
                    "id": item.id,
                    "key": item.outcome_key,
                    "label": item.label,
                    "version": item.version,
                    "horizon_days": item.horizon_days,
                    "min_denominator": item.min_denominator,
                }
                for item in outcome_definitions
            ],
            "decision_points": [_decision_point_row(point) for point in points],
            "datasets": [_dataset_row(dataset) for dataset in datasets],
            "blockers": blockers,
            "options": {
                "classes": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "grade": item.grade,
                        "student_count": item.active_student_count,
                    }
                    for item in classes
                ],
                "courses": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "subject": {
                            "id": item.subject_id,
                            "name": item.subject.name,
                        },
                        "teacher_name": item.teacher.display_name
                        or item.teacher.username,
                        "class_ids": [
                            relation.class_group_id
                            for relation in item.course_classes.all()
                        ],
                    }
                    for item in courses
                ],
            },
        }
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def create_analysis_decision_point(request):
    school = request.user.school
    try:
        class_id = int(request.data.get("class_id") or 0)
        course_id = int(request.data.get("course_id") or 0)
    except (TypeError, ValueError):
        return fail("班级或课程不正确。", status=400)
    class_group = ClassGroup.objects.filter(
        pk=class_id,
        school=school,
        status=ClassGroup.Status.ACTIVE,
    ).first()
    course = (
        Course.objects.filter(
            pk=course_id,
            subject__school=school,
            is_active=True,
        )
        .select_related("subject")
        .first()
    )
    if class_group is None or course is None:
        return fail("班级或课程不存在。", status=404)
    if not CourseClass.objects.filter(course=course, class_group=class_group).exists():
        return fail("该课程没有分配给所选班级。", status=400)

    scheduled_for = timezone.now()
    raw_time = str(request.data.get("scheduled_for") or "").strip()
    if raw_time:
        parsed = parse_datetime(raw_time)
        if parsed is None:
            return fail("计划时间格式不正确。", status=400)
        scheduled_for = (
            timezone.make_aware(parsed, timezone.get_current_timezone())
            if timezone.is_naive(parsed)
            else parsed
        )
    now = timezone.now()
    if scheduled_for < now - timedelta(minutes=5):
        return fail("页面不能补建过去的分析时间点。", status=400)
    if scheduled_for > now + timedelta(days=90):
        return fail("计划时间不能超过未来 90 天。", status=400)
    try:
        result = create_decision_point(
            school=school,
            class_group=class_group,
            subject=course.subject,
            course=course,
            scheduled_for=scheduled_for,
            created_by=request.user,
            purpose=DecisionPoint.Purpose.PILOT,
            title=str(request.data.get("title") or "").strip(),
        )
    except IntegrityError:
        return fail("相同班级、课程和时间已经建立过分析时间点。", status=409)
    except ValidationError as exc:
        return fail(_validation_message(exc), status=400)
    point = result["decision_point"]
    point = (
        DecisionPoint.objects.select_related("class_group", "subject", "course")
        .prefetch_related(
            Prefetch(
                "feature_snapshots",
                queryset=StudentFeatureSnapshot.objects.filter(
                    view_type=StudentFeatureSnapshot.ViewType.OPERATIONAL
                ),
                to_attr="prefetched_snapshots",
            )
        )
        .get(pk=point.pk)
    )
    return ok(
        {"decision_point": _decision_point_row(point)},
        "分析时间点已建立。",
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def refresh_analysis_outcomes(request):
    counts = mature_due_outcomes(school=request.user.school)
    return ok(counts, "未来学习结果已更新。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def create_training_dataset(request):
    school = request.user.school
    try:
        subject_id = int(request.data.get("subject_id") or 0)
    except (TypeError, ValueError):
        return fail("学科不正确。", status=400)
    subject = Subject.objects.filter(pk=subject_id, school=school).first()
    outcome = OutcomeDefinition.objects.filter(
        outcome_key=str(request.data.get("outcome_key") or ""),
        status=OutcomeDefinition.Status.ACTIVE,
    ).first()
    if subject is None or outcome is None:
        return fail("学科或未来结果定义不存在。", status=404)
    try:
        dataset = build_training_dataset(
            school=school,
            subject=subject,
            outcome_definition=outcome,
            created_by=request.user,
        )
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    dataset = TrainingDatasetVersion.objects.select_related(
        "subject", "feature_set", "outcome_definition"
    ).get(pk=dataset.pk)
    return ok(
        {"dataset": _dataset_row(dataset)},
        "数据版本已生成。",
        status=201,
    )


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def export_training_dataset(request, pk: int):
    dataset_query = TrainingDatasetVersion.objects.filter(
        pk=pk,
        school=request.user.school,
    )
    if not _include_test_data(request):
        dataset_query = dataset_query.filter(synthetic_run__isnull=True)
    dataset = (
        dataset_query
        .select_related("school", "subject", "feature_set", "outcome_definition")
        .first()
    )
    if dataset is None:
        return fail("数据版本不存在。", status=404)
    rows = list(
        dataset.rows.select_related("decision_point").order_by(
            "decision_point__scheduled_for", "pseudonymous_key"
        )
    )
    workbook = build_workbook(
        [
            {
                "title": "版本说明",
                "headers": ["项目", "内容"],
                "rows": [
                    ["数据版本", dataset.dataset_key],
                    ["学校", dataset.school.name],
                    ["学科", dataset.subject.name],
                    [
                        "特征集",
                        f"{dataset.feature_set.set_key}@{dataset.feature_set.version}",
                    ],
                    [
                        "未来结果",
                        f"{dataset.outcome_definition.label}@{dataset.outcome_definition.version}",
                    ],
                    ["记录数", dataset.row_count],
                    ["已观察", dataset.observed_count],
                    ["无可用结果", dataset.unobserved_count],
                    ["已排除", dataset.excluded_count],
                    [
                        "可进入模型比较",
                        dataset.manifest.get("comparison_ready", False),
                    ],
                    ["暂不能比较原因", dataset.manifest.get("blockers", [])],
                    ["清单摘要", dataset.manifest_hash],
                ],
            },
            {
                "title": "匿名数据",
                "headers": [
                    "内部匿名编号",
                    "分析时间",
                    "学生分组",
                    "时间分组",
                    "特征值",
                    "分子",
                    "分母",
                    "缺失原因",
                    "结果状态",
                    "结果值",
                    "结果分子",
                    "结果分母",
                    "结果缺失原因",
                    "行摘要",
                ],
                "rows": [
                    [
                        item.pseudonymous_key,
                        item.decision_point.scheduled_for,
                        item.split_assignments.get("group_holdout", item.split),
                        item.split_assignments.get("time_holdout", ""),
                        item.feature_values,
                        item.feature_numerators,
                        item.feature_denominators,
                        item.feature_missing_codes,
                        item.outcome_status,
                        item.outcome_value,
                        item.outcome_numerator,
                        item.outcome_denominator,
                        item.outcome_missing_code,
                        item.row_hash,
                    ]
                    for item in rows
                ],
            },
        ]
    )
    return workbook_response(
        workbook,
        (
            f"{dataset.school.code}-{dataset.subject.code}-学习分析数据-"
            f"{dataset.dataset_key[:8]}.xlsx"
        ),
    )


def _longitudinal_run_row(run: LongitudinalAnalysisRun, detail=False):
    results = list(
        run.feature_results.order_by("feature_key")
        if detail
        else run.feature_results.order_by("feature_key")[:8]
    )
    return {
        "id": run.id,
        "run_id": str(run.run_id),
        "dataset_id": run.dataset_id,
        "dataset_key": run.dataset.dataset_key,
        "subject": {"id": run.subject_id, "name": run.subject.name},
        "status": run.status,
        "status_label": run.get_status_display(),
        "analysis_version": run.analysis_version,
        "feature_count": run.feature_count,
        "ready_feature_count": run.ready_feature_count,
        "row_count": run.row_count,
        "student_count": run.student_count,
        "class_count": run.class_count,
        "manifest": run.manifest,
        "manifest_hash": run.manifest_hash,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "feature_results": [
            {
                "feature_key": item.feature_key,
                "status": item.status,
                "status_label": item.get_status_display(),
                "observation_count": item.observation_count,
                "student_count": item.student_count,
                "class_count": item.class_count,
                "total_variance": item.total_variance,
                "between_variance": item.between_variance,
                "within_variance": item.within_variance,
                "intraclass_correlation": item.intraclass_correlation,
                "overall_association": item.overall_association,
                "within_association": item.within_association,
                "between_association": item.between_association,
                "interval_low": item.interval_low,
                "interval_high": item.interval_high,
                "direction": item.direction,
                "details": item.details,
            }
            for item in results
        ],
    }


def _model_comparison_row(run: ModelComparisonRun, detail=False):
    evaluations = run.evaluations.order_by("validation_key", "model_key")
    if not detail:
        evaluations = evaluations[:40]
    controls = run.negative_controls.order_by("control_key")
    return {
        "id": run.id,
        "run_id": str(run.run_id),
        "dataset_id": run.dataset_id,
        "dataset_key": run.dataset.dataset_key,
        "subject": {"id": run.subject_id, "name": run.subject.name},
        "status": run.status,
        "status_label": run.get_status_display(),
        "comparison_version": run.comparison_version,
        "target_type": run.target_type,
        "model_keys": run.model_keys,
        "validation_keys": run.validation_keys,
        "row_count": run.row_count,
        "observed_count": run.observed_count,
        "manifest": run.manifest,
        "model_card": run.model_card,
        "manifest_hash": run.manifest_hash,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "evaluations": [
            {
                "id": item.id,
                "model_key": item.model_key,
                "validation_key": item.validation_key,
                "status": item.status,
                "status_label": item.get_status_display(),
                "train_count": item.train_count,
                "test_count": item.test_count,
                "predicted_count": item.predicted_count,
                "abstained_count": item.abstained_count,
                "primary_metric": item.primary_metric,
                "mean_residual": item.metrics.get("mean_residual"),
                "residual_sum": item.metrics.get("residual_sum"),
                "residual_sum_squares": item.metrics.get("residual_sum_squares"),
                "mse": item.metrics.get("mse"),
                "rmse": item.rmse,
                "mae": item.mae,
                "r_squared": item.metrics.get("r_squared"),
                "brier_score": item.brier_score,
                "calibration_intercept": item.calibration_intercept,
                "calibration_slope": item.calibration_slope,
                "coverage": item.coverage,
                "metrics": item.metrics,
                "note": item.note,
            }
            for item in evaluations
        ],
        "negative_controls": [
            {
                "control_key": item.control_key,
                "status": item.status,
                "status_label": item.get_status_display(),
                "expected_behavior": item.expected_behavior,
                "observed_metric": item.observed_metric,
                "baseline_metric": item.baseline_metric,
                "details": item.details,
            }
            for item in controls
        ],
    }


def _class_calibration_row(run: ClassCalibrationRun):
    releases = list(getattr(run, "prefetched_releases", []))
    return {
        "id": run.id,
        "run_id": str(run.run_id),
        "dataset_id": run.dataset_id,
        "dataset_key": run.dataset.dataset_key,
        "comparison_run_id": run.comparison_run_id,
        "subject": {"id": run.subject_id, "name": run.subject.name},
        "status": run.status,
        "status_label": run.get_status_display(),
        "calibration_version": run.calibration_version,
        "model_key": run.model_key,
        "global_parameters": run.global_parameters,
        "class_parameters": run.class_parameters,
        "model_card": run.model_card,
        "manifest": run.manifest,
        "manifest_hash": run.manifest_hash,
        "artifact_hash": run.artifact_hash,
        "suggestion_count": run.suggestion_count,
        "release": _model_release_row(releases[0]) if releases else None,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


def _model_release_row(release: ModelRelease):
    return {
        "id": release.id,
        "release_id": str(release.release_id),
        "release_version": release.release_version,
        "status": release.status,
        "status_label": release.get_status_display(),
        "school": {
            "id": release.school_id,
            "name": release.school.name,
            "code": release.school.code,
        },
        "subject": {"id": release.subject_id, "name": release.subject.name},
        "calibration_run_id": release.calibration_run_id,
        "calibration_run_key": str(release.calibration_run.run_id),
        "model_key": release.calibration_run.model_key,
        "is_test_data": release.is_test_data,
        "previous_release_id": release.previous_release_id,
        "package_hash": release.package_hash,
        "signing_key_id": release.signing_key_id,
        "manifest": release.manifest,
        "released_by": release.released_by.display_name
        or release.released_by.username,
        "released_at": release.released_at,
        "deactivated_at": release.deactivated_at,
    }


def _model_release_audit_row(record: ModelReleaseAudit):
    return {
        "id": record.id,
        "action": record.action,
        "action_label": record.get_action_display(),
        "result": record.result,
        "result_label": record.get_result_display(),
        "subject": {"id": record.subject_id, "name": record.subject.name},
        "calibration_run_id": record.calibration_run_id,
        "release_id": record.release_id,
        "actor": record.actor.display_name or record.actor.username,
        "message": record.message,
        "details": record.details,
        "created_at": record.created_at,
    }


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def model_validation(request):
    school = request.user.school
    include_test_data = _include_test_data(request)
    longitudinal_query = LongitudinalAnalysisRun.objects.filter(school=school)
    comparison_query = ModelComparisonRun.objects.filter(school=school)
    dataset_query = TrainingDatasetVersion.objects.filter(
        school=school,
        status=TrainingDatasetVersion.Status.FROZEN,
    )
    calibration_query = ClassCalibrationRun.objects.filter(school=school)
    release_query = ModelRelease.objects.filter(school=school)
    audit_query = ModelReleaseAudit.objects.filter(school=school)
    if not include_test_data:
        longitudinal_query = longitudinal_query.filter(
            dataset__synthetic_run__isnull=True
        )
        comparison_query = comparison_query.filter(
            dataset__synthetic_run__isnull=True
        )
        dataset_query = dataset_query.filter(synthetic_run__isnull=True)
        calibration_query = calibration_query.filter(
            dataset__synthetic_run__isnull=True
        )
        release_query = release_query.filter(is_test_data=False)
        audit_query = audit_query.filter(
            Q(calibration_run__isnull=True)
            | Q(calibration_run__dataset__synthetic_run__isnull=True)
        )
    longitudinal_runs = list(
        longitudinal_query
        .select_related("dataset", "subject")
        .prefetch_related("feature_results")
        .order_by("-created_at")[:20]
    )
    comparison_runs = list(
        comparison_query
        .select_related("dataset", "subject")
        .prefetch_related("evaluations", "negative_controls")
        .order_by("-created_at")[:20]
    )
    datasets = list(
        dataset_query
        .select_related("subject", "outcome_definition")
        .order_by("-created_at")[:50]
    )
    calibration_runs = list(
        calibration_query.select_related(
            "dataset", "comparison_run", "subject"
        ).prefetch_related(
            Prefetch(
                "releases",
                queryset=ModelRelease.objects.select_related(
                    "school", "subject", "calibration_run", "released_by"
                ),
                to_attr="prefetched_releases",
            )
        ).order_by("-created_at")[:20]
    )
    releases = list(
        release_query.select_related(
            "school", "subject", "calibration_run", "released_by"
        ).order_by("-released_at")[:50]
    )
    release_audits = list(
        audit_query.select_related("subject", "actor").order_by("-created_at")[:50]
    )
    return ok(
        {
            "datasets": [_dataset_row(item) for item in datasets],
            "longitudinal_runs": [
                _longitudinal_run_row(item) for item in longitudinal_runs
            ],
            "comparison_runs": [
                _model_comparison_row(item) for item in comparison_runs
            ],
            "calibration_runs": [
                _class_calibration_row(item) for item in calibration_runs
            ],
            "releases": [_model_release_row(item) for item in releases],
            "release_audits": [
                _model_release_audit_row(item) for item in release_audits
            ],
            "test_data_visible": include_test_data,
            "rules": {
                "model_comparison_is_shadow_only": True,
                "minimum_evaluation_n": 30,
                "model_order": ["M00", "M01", "M02", "M03"],
                "validation_order": ["V-A", "V-B", "V-C", "V-D", "V-E"],
            },
        }
    )


def _dataset_for_school(request, request_data):
    try:
        dataset_id = int(request_data.get("dataset_id") or 0)
    except (TypeError, ValueError):
        raise ValidationError("数据版本编号不正确。")
    dataset_query = TrainingDatasetVersion.objects.filter(
        pk=dataset_id,
        school=request.user.school,
        status=TrainingDatasetVersion.Status.FROZEN,
    )
    if not _include_test_data(request):
        dataset_query = dataset_query.filter(synthetic_run__isnull=True)
    dataset = (
        dataset_query
        .select_related("school", "subject", "feature_set", "outcome_definition")
        .first()
    )
    if dataset is None:
        raise ValidationError("数据版本不存在，或尚未冻结。")
    return dataset


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def create_longitudinal_analysis(request):
    try:
        dataset = _dataset_for_school(request, request.data)
        run = build_longitudinal_analysis(dataset=dataset, created_by=request.user)
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    run = LongitudinalAnalysisRun.objects.select_related("dataset", "subject").prefetch_related(
        "feature_results"
    ).get(pk=run.pk)
    return ok(
        {"run": _longitudinal_run_row(run, detail=True)},
        "重复测量统计已生成。" if run.status == LongitudinalAnalysisRun.Status.COMPLETED else "重复测量统计暂不能报告。",
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def create_model_comparison(request):
    try:
        dataset = _dataset_for_school(request, request.data)
        run = build_model_comparison(dataset=dataset, created_by=request.user)
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    run = ModelComparisonRun.objects.select_related("dataset", "subject").prefetch_related(
        "evaluations", "negative_controls"
    ).get(pk=run.pk)
    return ok(
        {"run": _model_comparison_row(run, detail=True)},
        "模型比较已生成，当前只保留影子比较结果。"
        if run.status == ModelComparisonRun.Status.SHADOW_ONLY
        else "模型比较已生成，但存在数据不足或需要解释的问题。",
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def create_model_02_comparison(request):
    try:
        dataset = _dataset_for_school(request, request.data)
        run = build_model_02_comparison(
            dataset=dataset,
            created_by=request.user,
            include_test_data=_include_test_data(request),
        )
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    run = ModelComparisonRun.objects.select_related(
        "dataset", "subject"
    ).prefetch_related("evaluations", "negative_controls").get(pk=run.pk)
    return ok(
        {"run": _model_comparison_row(run, detail=True)},
        "MODEL-02 结构化模型比较已生成。"
        if run.status == ModelComparisonRun.Status.SHADOW_ONLY
        else "MODEL-02 已运行，但当前结果暂不生成教学建议。",
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def create_class_calibration(request):
    try:
        dataset = _dataset_for_school(request, request.data)
        run = build_class_calibration_candidate(
            dataset=dataset,
            created_by=request.user,
            include_test_data=_include_test_data(request),
        )
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    run = ClassCalibrationRun.objects.select_related(
        "dataset", "comparison_run", "subject"
    ).get(pk=run.pk)
    return ok(
        {"run": _class_calibration_row(run)},
        "班级校准候选已生成，学生层级没有被自动修改。"
        if run.status == ClassCalibrationRun.Status.CANDIDATE
        else "班级校准暂未生成建议，请查看阻塞原因。",
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def train_stratification_model(request):
    """Run the complete, repeatable model pipeline for one frozen dataset."""
    try:
        dataset = _dataset_for_school(request, request.data)
        include_test_data = _include_test_data(request)
        longitudinal = build_longitudinal_analysis(
            dataset=dataset,
            created_by=request.user,
        )
        baseline = build_model_comparison(
            dataset=dataset,
            created_by=request.user,
        )
        advanced = build_model_02_comparison(
            dataset=dataset,
            created_by=request.user,
            include_test_data=include_test_data,
        )
        calibration = build_class_calibration_candidate(
            dataset=dataset,
            comparison_run=advanced,
            created_by=request.user,
            include_test_data=include_test_data,
        )
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)

    advanced = ModelComparisonRun.objects.select_related(
        "dataset", "subject"
    ).prefetch_related("evaluations", "negative_controls").get(pk=advanced.pk)
    calibration = ClassCalibrationRun.objects.select_related(
        "dataset", "comparison_run", "subject"
    ).get(pk=calibration.pk)
    return ok(
        {
            "dataset": _dataset_row(dataset),
            "longitudinal_run_id": longitudinal.id,
            "baseline_run_id": baseline.id,
            "comparison_run": _model_comparison_row(advanced, detail=True),
            "calibration_run": _class_calibration_row(calibration),
        },
        (
            "模型训练完成，已生成待发布的教师分层建议。"
            if calibration.status == ClassCalibrationRun.Status.CANDIDATE
            else "模型训练已完成检查，但当前数据暂不能生成教师分层建议。"
        ),
        status=201,
    )


def _calibration_for_release(request, pk: int):
    query = ClassCalibrationRun.objects.filter(pk=pk, school=request.user.school)
    if not _include_test_data(request):
        query = query.filter(dataset__synthetic_run__isnull=True)
    return query.select_related(
        "school", "subject", "dataset", "comparison_run"
    ).first()


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def publish_class_calibration(request, pk: int):
    run = _calibration_for_release(request, pk)
    if run is None:
        return fail("班级校准候选不存在。", status=404)
    try:
        release = publish_model_candidate(calibration_run=run, actor=request.user)
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    except Exception:
        return fail("模型包生成失败，当前使用版本没有改变。", status=500)
    release = ModelRelease.objects.select_related(
        "school", "subject", "calibration_run", "released_by"
    ).get(pk=release.pk)
    message = "测试候选已发布，仅用于本地工程验收。" if release.is_test_data else "候选模型已发布。"
    return ok({"release": _model_release_row(release)}, message, status=201)


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def rollback_model_release_view(request, pk: int):
    query = ModelRelease.objects.filter(pk=pk, school=request.user.school)
    if not _include_test_data(request):
        query = query.filter(is_test_data=False)
    release = query.select_related(
        "school", "subject", "calibration_run", "released_by"
    ).first()
    if release is None:
        return fail("模型发布版本不存在。", status=404)
    try:
        release = rollback_model_release(target=release, actor=request.user)
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    except Exception:
        return fail("模型回滚失败，当前使用版本没有改变。", status=500)
    return ok({"release": _model_release_row(release)}, "已回滚到所选模型版本。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def verify_model_release_view(request, pk: int):
    query = ModelRelease.objects.filter(pk=pk, school=request.user.school)
    if not _include_test_data(request):
        query = query.filter(is_test_data=False)
    release = query.select_related(
        "school", "subject", "calibration_run", "released_by"
    ).first()
    if release is None:
        return fail("模型发布版本不存在。", status=404)
    try:
        manifest = verify_model_release(release=release, actor=request.user)
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    return ok(
        {"release": _model_release_row(release), "manifest": manifest},
        "模型包签名和文件校验通过。",
    )


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def download_model_release_package(request, pk: int):
    query = ModelRelease.objects.filter(pk=pk, school=request.user.school)
    if not _include_test_data(request):
        query = query.filter(is_test_data=False)
    release = query.select_related("calibration_run").first()
    if release is None:
        return fail("模型发布版本不存在。", status=404)
    try:
        verify_model_release(release=release)
        package = open(release.package_path, "rb")
    except ValidationError as exc:
        return fail(_validation_message(exc), status=409)
    except OSError:
        return fail("模型包文件无法读取。", status=409)
    filename = (
        f"{request.user.school.code}-{release.subject.code}-model-v"
        f"{release.release_version}.zip"
    )
    return FileResponse(package, as_attachment=True, filename=filename)


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def export_model_validation(request, pk: int):
    run_query = ModelComparisonRun.objects.filter(
        pk=pk,
        school=request.user.school,
    )
    if not _include_test_data(request):
        run_query = run_query.filter(dataset__synthetic_run__isnull=True)
    run = (
        run_query
        .select_related("dataset", "subject")
        .prefetch_related("evaluations", "negative_controls")
        .first()
    )
    if run is None:
        return fail("模型比较记录不存在。", status=404)
    longitudinal = LongitudinalAnalysisRun.objects.filter(dataset=run.dataset).first()
    longitudinal_results = list(
        longitudinal.feature_results.order_by("feature_key") if longitudinal else []
    )
    stability_rows = []
    class_difference_rows = []
    for item in run.evaluations.all():
        stability = item.metrics.get("stability") or {}
        if stability:
            stability_rows.append(
                [
                    item.model_key,
                    item.validation_key,
                    stability.get("status"),
                    stability.get("shared_prediction_count"),
                    stability.get("max_absolute_delta"),
                    stability.get("rule"),
                ]
            )
        fairness = item.metrics.get("fairness") or {}
        for group in fairness.get("groups") or []:
            class_difference_rows.append(
                [
                    item.model_key,
                    item.validation_key,
                    group.get("class_key"),
                    group.get("status"),
                    group.get("n"),
                    group.get("coverage"),
                    group.get("mae"),
                    fairness.get("mae_gap"),
                ]
            )
    calibration = ClassCalibrationRun.objects.filter(
        dataset=run.dataset,
        comparison_run=run,
    ).first()
    calibration_rows = []
    if calibration:
        calibration_rows.extend(
            [
                ["状态", calibration.get_status_display()],
                ["模型", calibration.model_key],
                ["建议数量", calibration.suggestion_count],
                ["模型文件", calibration.artifact_path],
                ["文件校验码", calibration.artifact_hash],
            ]
        )
        calibration_rows.extend(
            [f"全局参数.{key}", value]
            for key, value in calibration.global_parameters.items()
        )
    class_calibration_rows = [
        [
            class_key,
            values.get("n"),
            values.get("raw_residual_mean"),
            values.get("shrinkage_weight"),
            values.get("calibration_correction"),
        ]
        for class_key, values in (
            calibration.class_parameters.items() if calibration else []
        )
    ]
    prediction_rows = [
        [
            item.pseudonymous_key,
            item.model_key,
            item.validation_key,
            item.get_status_display(),
            item.observed_value,
            item.predicted_value,
            (
                item.observed_value - item.predicted_value
                if item.observed_value is not None and item.predicted_value is not None
                else None
            ),
            item.abstain_reason,
        ]
        for item in ModelPrediction.objects.filter(run=run).order_by(
            "model_key", "validation_key", "pseudonymous_key"
        )
    ]
    workbook = build_workbook(
        [
            {
                "title": "模型卡",
                "headers": ["项目", "内容"],
                "rows": [[key, value] for key, value in run.model_card.items()],
            },
            {
                "title": "模型比较",
                "headers": [
                    "模型",
                    "验证方式",
                    "状态",
                    "训练记录",
                    "测试记录",
                    "预测数",
                    "拒绝数",
                    "主要指标",
                    "平均残差",
                    "残差平方和",
                    "MSE",
                    "RMSE",
                    "MAE",
                    "R2",
                    "覆盖率",
                    "说明",
                ],
                "rows": [
                    [
                        item.model_key,
                        item.validation_key,
                        item.get_status_display(),
                        item.train_count,
                        item.test_count,
                        item.predicted_count,
                        item.abstained_count,
                        item.primary_metric,
                        item.metrics.get("mean_residual"),
                        item.metrics.get("residual_sum_squares"),
                        item.metrics.get("mse"),
                        item.rmse,
                        item.mae,
                        item.metrics.get("r_squared"),
                        item.coverage,
                        item.note,
                    ]
                    for item in run.evaluations.all()
                ],
            },
            {
                "title": "重复测量",
                "headers": [
                    "指标",
                    "状态",
                    "观测数",
                    "学生数",
                    "班级数",
                    "个体间差异",
                    "个体内差异",
                    "相关系数",
                    "区间下限",
                    "区间上限",
                    "方向",
                ],
                "rows": [
                    [
                        item.feature_key,
                        item.get_status_display(),
                        item.observation_count,
                        item.student_count,
                        item.class_count,
                        item.between_variance,
                        item.within_variance,
                        item.overall_association,
                        item.interval_low,
                        item.interval_high,
                        item.direction,
                    ]
                    for item in longitudinal_results
                ],
            },
            {
                "title": "负对照",
                "headers": ["检查", "状态", "预期", "实际指标", "基线指标", "详情"],
                "rows": [
                    [
                        item.control_key,
                        item.get_status_display(),
                        item.expected_behavior,
                        item.observed_metric,
                        item.baseline_metric,
                        item.details,
                    ]
                    for item in run.negative_controls.all()
                ],
            },
            {
                "title": "稳定性",
                "headers": [
                    "模型",
                    "验证方式",
                    "状态",
                    "共同预测数",
                    "最大差异",
                    "检查规则",
                ],
                "rows": stability_rows,
            },
            {
                "title": "班级差异",
                "headers": [
                    "模型",
                    "验证方式",
                    "班级编号",
                    "状态",
                    "记录数",
                    "覆盖率",
                    "MAE",
                    "班级间 MAE 差",
                ],
                "rows": class_difference_rows,
            },
            {
                "title": "班级校准",
                "headers": ["项目", "内容"],
                "rows": calibration_rows,
            },
            {
                "title": "班级参数",
                "headers": [
                    "班级编号",
                    "记录数",
                    "原始残差均值",
                    "收缩权重",
                    "校准修正值",
                ],
                "rows": class_calibration_rows,
            },
            {
                "title": "匿名预测明细",
                "headers": [
                    "匿名编号",
                    "模型",
                    "验证方式",
                    "状态",
                    "实际值",
                    "预测值",
                    "残差",
                    "拒绝原因",
                ],
                "rows": prediction_rows,
            },
        ]
    )
    return workbook_response(
        workbook,
        f"{run.school.code}-{run.subject.code}-模型验证-{run.run_key[:8]}.xlsx",
    )


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def content_band_policies(request):
    school = request.user.school
    if request.method == "GET":
        rows = (
            ContentBandPolicyVersion.objects.filter(school=school)
            .select_related("subject", "course")
            .order_by("subject__name", "course__title", "-version_no")
        )
        return ok([_content_band_policy_row(row) for row in rows])

    subject = Subject.objects.filter(
        pk=request.data.get("subject"), school=school, is_active=True
    ).first()
    if subject is None:
        return fail("请选择本校启用的学科。", status=400)
    course = None
    if request.data.get("course") not in (None, ""):
        course = Course.objects.filter(
            pk=request.data.get("course"), subject=subject
        ).first()
        if course is None:
            return fail("课程与学科不一致。", status=400)
    scope = ContentBandPolicyVersion.objects.filter(
        school=school, subject=subject, course=course
    )
    version_no = (
        scope.order_by("-version_no").values_list("version_no", flat=True).first()
        or 0
    ) + 1
    try:
        policy = ContentBandPolicyVersion(
            school=school,
            subject=subject,
            course=course,
            name=str(request.data.get("name") or f"{subject.name}学习内容层级标准")[
                :128
            ],
            version_no=version_no,
            policy_version=str(
                request.data.get("policy_version") or f"criterion-v{version_no}"
            )[:32],
            a_min=_number(request.data, "a_min", 0.8),
            b_min=_number(request.data, "b_min", 0.6),
            boundary_margin=_number(request.data, "boundary_margin", 0.03),
            hysteresis_margin=_number(request.data, "hysteresis_margin", 0.03),
            max_measurement_error=_number(
                request.data, "max_measurement_error", 0.18
            ),
            min_common_items=_number(
                request.data, "min_common_items", 5, integer=True
            ),
            min_answered_ratio=_number(request.data, "min_answered_ratio", 0.8),
            required_consecutive_windows=_number(
                request.data, "required_consecutive_windows", 2, integer=True
            ),
            cooldown_days=_number(request.data, "cooldown_days", 14, integer=True),
            max_step_change=1,
            created_by=request.user,
        )
        policy.save()
    except ValidationError as exc:
        return fail("层级标准校验失败。", errors=exc.message_dict, status=400)
    write_audit(
        request,
        "school_admin.content_band_policy.create",
        school=school,
        target_type="content_band_policy",
        target_id=policy.id,
    )
    return ok(_content_band_policy_row(policy), "层级标准草稿已创建。", status=201)


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def publish_content_band_policy_view(request, pk: int):
    policy = (
        ContentBandPolicyVersion.objects.select_related("school", "subject", "course")
        .filter(pk=pk, school=request.user.school)
        .first()
    )
    if policy is None:
        return fail("层级标准不存在。", status=404)
    try:
        policy = publish_content_band_policy(policy=policy, actor=request.user)
    except ValidationError as exc:
        return fail(str(exc.messages[0]), status=400)
    write_audit(
        request,
        "school_admin.content_band_policy.publish",
        school=request.user.school,
        target_type="content_band_policy",
        target_id=policy.id,
    )
    return ok(_content_band_policy_row(policy), "层级标准已启用。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def refresh_assessment_mastery(request):
    assessment = (
        TestAssessment.objects.select_related(
            "school", "subject", "course", "common_question_set"
        )
        .filter(pk=request.data.get("assessment"), school=request.user.school)
        .first()
    )
    if assessment is None:
        return fail("测试不存在。", status=404)
    try:
        result = build_assessment_mastery_candidates(assessment=assessment)
    except ValidationError as exc:
        return fail(str(exc.messages[0]), status=400)
    return ok(result, "共同测试掌握结果已更新。")
