from __future__ import annotations

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsSchoolAdmin
from api.responses import fail, ok
from learning_analytics.models import (
    AnalyticsPipelineRun,
    AnalyticsTaskRun,
    DataQualityReport,
)
from learning_analytics.services.quality import QUALITY_THRESHOLDS, trailing_window
from learning_analytics.tasks import dispatch_school_data_quality_pipeline
from ops.xlsx import build_workbook, workbook_response

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
                    (
                        "低于"
                        if threshold.get("direction") == "low"
                        else "高于"
                    ),
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
