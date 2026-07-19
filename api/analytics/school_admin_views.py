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
    "semantic_missing_rate": "语义缺失率",
    "opportunity_coverage_rate": "机会关联覆盖率",
    "client_offline_rate": "客户端离线率",
    "v1_v2_difference_rate": "V1/V2 差异率",
}


def _task_row(task: AnalyticsTaskRun) -> dict:
    return {
        "id": task.id,
        "task_id": str(task.task_id),
        "task_name": task.task_name,
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
        "methodology_version": run.methodology_version,
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
        "gate_passed": report.gate_passed,
        "window_start": report.window_start,
        "window_end": report.window_end,
        "methodology_version": report.methodology_version,
        "source_fingerprint": report.source_fingerprint,
        "event_count": report.event_count,
        "ingestion_attempt_count": report.ingestion_attempt_count,
        "rejection_count": report.rejection_count,
        "legacy_unmapped_count": report.legacy_unmapped_count,
        "unlinked_legacy_count": report.unlinked_legacy_count,
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
        DataQualityReport.objects.filter(school=school)
        .select_related("pipeline_run")
        .order_by("-window_end", "-created_at")[:30]
    )
    runs = list(
        AnalyticsPipelineRun.objects.filter(
            school=school,
            pipeline_type=AnalyticsPipelineRun.PipelineType.DATA_QUALITY,
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
        status__in={
            AnalyticsPipelineRun.Status.PENDING,
            AnalyticsPipelineRun.Status.RUNNING,
        },
    ).exists():
        return fail("本校已有数据质量任务正在等待或运行。", status=409)
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
        return fail(f"质量任务未能入队：{exc}", status=503)
    return ok(
        {"run": _run_row(run), "task_id": async_result.id},
        "数据质量任务已提交。",
        status=202,
    )


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def export_school_quality(request):
    school = request.user.school
    reports = list(
        DataQualityReport.objects.filter(school=school)
        .select_related("pipeline_run")
        .order_by("-window_end", "-created_at")[:100]
    )
    runs = list(
        AnalyticsPipelineRun.objects.filter(
            school=school,
            pipeline_type=AnalyticsPipelineRun.PipelineType.DATA_QUALITY,
        )
        .prefetch_related("task_runs")
        .order_by("-created_at")[:100]
    )

    report_rows = [
        [
            report.report_id,
            report.get_status_display(),
            "通过" if report.gate_passed else "阻断",
            report.window_start,
            report.window_end,
            report.event_count,
            report.ingestion_attempt_count,
            report.rejection_count,
            report.legacy_unmapped_count,
            report.unlinked_legacy_count,
            report.methodology_version,
            report.source_fingerprint,
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
                    threshold.get("direction", ""),
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
                    issue.get("level", ""),
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
                run.methodology_version,
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
                    task.task_name,
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
                "title": "质量报告",
                "headers": [
                    "报告ID",
                    "质量状态",
                    "闸门",
                    "窗口开始",
                    "窗口结束",
                    "事件数",
                    "摄取尝试数",
                    "拒绝数",
                    "语义未映射数",
                    "未关联V1数",
                    "方法版本",
                    "来源指纹",
                    "生成时间",
                ],
                "rows": report_rows,
            },
            {
                "title": "质量指标",
                "headers": [
                    "报告ID",
                    "指标",
                    "比率",
                    "阈值方向",
                    "关注阈值",
                    "阻断阈值",
                ],
                "rows": metric_rows,
            },
            {
                "title": "质量问题",
                "headers": ["报告ID", "级别", "问题代码", "指标", "实际值", "阈值"],
                "rows": issue_rows,
            },
            {
                "title": "流水线运行",
                "headers": [
                    "运行ID",
                    "触发方式",
                    "状态",
                    "尝试次数",
                    "窗口开始",
                    "窗口结束",
                    "方法版本",
                    "错误代码",
                    "错误信息",
                    "开始时间",
                    "结束时间",
                ],
                "rows": run_rows,
            },
            {
                "title": "任务阶段",
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
        f"{school.code}-数据质量-{timezone.localdate():%Y%m%d}.xlsx",
    )
