from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from learning_analytics.models import (
    AnalyticsPipelineRun,
    AnalyticsTaskRun,
    DataQualityReport,
    EventIngestionDailyCounter,
    LearningEventRejection,
    LearningEventV2,
)
from learning_analytics.services.dual_write import reconcile_v1_v2_events

METHODOLOGY_VERSION = "data-quality-v1"
RATE_QUANTUM = Decimal("0.000001")
QUALITY_THRESHOLDS = {
    "duplicate_rate": {"amber": 0.05, "red": 0.10, "direction": "high"},
    "invalid_event_rate": {"amber": 0.02, "red": 0.05, "direction": "high"},
    "late_event_rate": {"amber": 0.10, "red": 0.25, "direction": "high"},
    "semantic_missing_rate": {"amber": 0.05, "red": 0.15, "direction": "high"},
    "opportunity_coverage_rate": {
        "amber": 0.98,
        "red": 0.90,
        "direction": "low",
    },
    "client_offline_rate": {"amber": 0.10, "red": 0.25, "direction": "high"},
    "v1_v2_difference_rate": {"amber": 0.0, "red": 0.0, "direction": "high"},
}


class QualityGateError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def previous_local_day_window(now=None) -> tuple[datetime, datetime]:
    local_now = timezone.localtime(now or timezone.now())
    end_date = local_now.date()
    start_date = end_date - timedelta(days=1)
    zone = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start_date, time.min), zone),
        timezone.make_aware(datetime.combine(end_date, time.min), zone),
    )


def trailing_window(*, days: int, now=None) -> tuple[datetime, datetime]:
    if not 1 <= days <= 365:
        raise ValueError("Quality window days must be between 1 and 365.")
    local_now = timezone.localtime(now or timezone.now())
    zone = timezone.get_current_timezone()
    end = timezone.make_aware(datetime.combine(local_now.date(), time.min), zone)
    return end - timedelta(days=days), end


def _ratio(numerator: int, denominator: int, *, empty: float = 0) -> Decimal:
    if denominator <= 0:
        return Decimal(str(empty)).quantize(RATE_QUANTUM)
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        RATE_QUANTUM, rounding=ROUND_HALF_UP
    )


def _config_hash() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "methodology_version": METHODOLOGY_VERSION,
                "thresholds": QUALITY_THRESHOLDS,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def create_quality_pipeline_run(
    *,
    school,
    window_start,
    window_end,
    trigger: str,
    retry_of: AnalyticsPipelineRun | None = None,
    synthetic_run=None,
) -> AnalyticsPipelineRun:
    attempt_no = retry_of.attempt_no + 1 if retry_of else 1
    run = AnalyticsPipelineRun(
        school=school,
        synthetic_run=synthetic_run,
        pipeline_type=AnalyticsPipelineRun.PipelineType.DATA_QUALITY,
        trigger=trigger,
        status=AnalyticsPipelineRun.Status.PENDING,
        window_start=window_start,
        window_end=window_end,
        methodology_version=METHODOLOGY_VERSION,
        code_version=str(getattr(settings, "ANALYTICS_CODE_VERSION", "") or "")[:64],
        config_hash=_config_hash(),
        attempt_no=attempt_no,
        retry_of=retry_of,
    )
    run.full_clean()
    run.save()
    return run


def _task(run: AnalyticsPipelineRun, task_name: str, operation):
    task = AnalyticsTaskRun.objects.create(
        pipeline_run=run,
        task_name=task_name,
        status=AnalyticsTaskRun.Status.RUNNING,
        attempt_no=run.attempt_no,
        started_at=timezone.now(),
    )
    try:
        result = operation()
    except Exception as exc:
        task.status = AnalyticsTaskRun.Status.FAILED
        task.error_code = type(exc).__name__[:64]
        task.error_message = str(exc)[:1000]
        task.finished_at = timezone.now()
        task.save(
            update_fields=[
                "status",
                "error_code",
                "error_message",
                "finished_at",
            ]
        )
        raise
    task.status = AnalyticsTaskRun.Status.SUCCEEDED
    task.metrics = result if isinstance(result, dict) else {}
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "metrics", "finished_at"])
    return result


def collect_event_quality_metrics(
    *, school, window_start, window_end, synthetic_run=None
) -> dict:
    events = LearningEventV2.objects.filter(
        school=school,
        server_received_at__gte=window_start,
        server_received_at__lt=window_end,
    )
    if synthetic_run is None:
        events = events.filter(synthetic_run__isnull=True)
    else:
        events = events.filter(synthetic_run=synthetic_run)
    operational_events = events.exclude(source="migration")
    event_count = events.count()
    operational_event_count = operational_events.count()
    rejection_fact_count = LearningEventRejection.objects.filter(
        school=school,
        server_received_at__gte=window_start,
        server_received_at__lt=window_end,
    ).count()

    local_start = timezone.localtime(window_start).date()
    local_end = timezone.localtime(window_end - timedelta(microseconds=1)).date()
    counters = EventIngestionDailyCounter.objects.filter(
        school=school,
        counter_date__gte=local_start,
        counter_date__lte=local_end,
    )
    if synthetic_run is None:
        counters = counters.filter(synthetic_run__isnull=True)
    else:
        counters = counters.filter(synthetic_run=synthetic_run)
    counter_totals = counters.aggregate(
        accepted=Sum("accepted_count"),
        duplicate=Sum("duplicate_count"),
        rejected=Sum("rejected_count"),
        late=Sum("late_count"),
        offline=Sum("offline_count"),
    )
    counter_accepted = int(counter_totals["accepted"] or 0)
    duplicate_count = int(counter_totals["duplicate"] or 0)
    counter_rejected = int(counter_totals["rejected"] or 0)
    rejection_count = max(rejection_fact_count, counter_rejected)
    attempt_count = operational_event_count + duplicate_count + rejection_count

    late_count = 0
    explicit_offline_count = 0
    opportunity_expected_count = 0
    opportunity_linked_count = 0
    student_web_count = 0
    for (
        quality_errors,
        event_name,
        opportunity_id,
        source,
        requires_opportunity,
    ) in events.values_list(
        "quality_errors",
        "event_name",
        "opportunity_id",
        "source",
        "schema_definition__requires_opportunity",
    ).iterator():
        flags = set(quality_errors or [])
        if flags.intersection({"late_arrival_24h", "very_late_arrival_7d"}):
            late_count += 1
        if event_name == "client.offline":
            explicit_offline_count += 1
        if source == "student-web":
            student_web_count += 1
        if requires_opportunity:
            opportunity_expected_count += 1
            if opportunity_id:
                opportunity_linked_count += 1

    legacy_unmapped_count = events.filter(
        quality_status=LearningEventV2.QualityStatus.LEGACY_UNMAPPED
    ).count()
    last_received = events.aggregate(value=Max("server_received_at"))["value"]
    telemetry_complete = counter_accepted >= operational_event_count
    return {
        "event_count": event_count,
        "operational_event_count": operational_event_count,
        "ingestion_attempt_count": attempt_count,
        "counter_accepted_count": counter_accepted,
        "duplicate_count": duplicate_count,
        "rejection_count": rejection_count,
        "rejection_fact_count": rejection_fact_count,
        "counter_rejected_count": counter_rejected,
        "late_count": late_count,
        "legacy_unmapped_count": legacy_unmapped_count,
        "opportunity_expected_count": opportunity_expected_count,
        "opportunity_linked_count": opportunity_linked_count,
        "student_web_count": student_web_count,
        "explicit_offline_count": explicit_offline_count,
        "telemetry_complete": telemetry_complete,
        "last_received_at": last_received.isoformat() if last_received else None,
    }


def collect_reconciliation_metrics(*, school, synthetic_run=None) -> dict:
    return reconcile_v1_v2_events(
        school=school,
        synthetic_run=synthetic_run,
        exclude_synthetic=synthetic_run is None,
    )


def _metric_issue(metric: str, value: Decimal) -> dict | None:
    config = QUALITY_THRESHOLDS[metric]
    numeric = float(value)
    if config["direction"] == "high":
        if numeric > config["red"]:
            level = "red"
            threshold = config["red"]
        elif numeric > config["amber"]:
            level = "amber"
            threshold = config["amber"]
        else:
            return None
    else:
        if numeric < config["red"]:
            level = "red"
            threshold = config["red"]
        elif numeric < config["amber"]:
            level = "amber"
            threshold = config["amber"]
        else:
            return None
    return {
        "code": f"{metric}_{level}",
        "level": level,
        "metric": metric,
        "value": numeric,
        "threshold": threshold,
    }


def publish_quality_report(
    *, pipeline_run: AnalyticsPipelineRun, event_metrics: dict, reconciliation: dict
) -> DataQualityReport:
    event_count = int(event_metrics["event_count"])
    attempt_count = int(event_metrics["ingestion_attempt_count"])
    required_count = int(event_metrics["opportunity_expected_count"])
    linked_count = int(event_metrics["opportunity_linked_count"])
    student_web_count = int(event_metrics["student_web_count"])
    v1_total = (
        int(reconciliation["legacy_dual_write_count"])
        + int(reconciliation["historical_mapped_count"])
        + int(reconciliation["historical_unmapped_count"])
        + int(reconciliation["unlinked_legacy_count"])
    )
    difference_count = (
        int(reconciliation["missing_v2_count"])
        + int(reconciliation["mapping_mismatch_count"])
        + int(reconciliation["unlinked_legacy_count"])
    )
    rates = {
        "duplicate_rate": _ratio(event_metrics["duplicate_count"], attempt_count),
        "invalid_event_rate": _ratio(event_metrics["rejection_count"], attempt_count),
        "late_event_rate": _ratio(event_metrics["late_count"], event_count),
        "semantic_missing_rate": _ratio(
            event_metrics["legacy_unmapped_count"], event_count
        ),
        "opportunity_coverage_rate": _ratio(linked_count, required_count, empty=1),
        "client_offline_rate": _ratio(
            event_metrics["explicit_offline_count"], student_web_count
        ),
        "v1_v2_difference_rate": _ratio(difference_count, v1_total),
    }
    issues = []
    if event_count == 0:
        issues.append(
            {
                "code": "no_events",
                "level": "red",
                "metric": "event_count",
                "value": 0,
                "threshold": 1,
            }
        )
    if (
        not event_metrics["telemetry_complete"]
        and event_metrics["operational_event_count"]
    ):
        issues.append(
            {
                "code": "ingestion_telemetry_incomplete",
                "level": "amber",
                "metric": "counter_accepted_count",
                "value": event_metrics["counter_accepted_count"],
                "threshold": event_metrics["operational_event_count"],
            }
        )
    for metric, value in rates.items():
        issue = _metric_issue(metric, value)
        if issue:
            issues.append(issue)
    status = DataQualityReport.Status.GREEN
    if any(issue["level"] == "red" for issue in issues):
        status = DataQualityReport.Status.RED
    elif issues:
        status = DataQualityReport.Status.AMBER
    source_values = {
        "window_start": pipeline_run.window_start.isoformat(),
        "window_end": pipeline_run.window_end.isoformat(),
        "event_metrics": event_metrics,
        "reconciliation": reconciliation,
        "methodology_version": METHODOLOGY_VERSION,
        "synthetic_run_id": (
            str(pipeline_run.synthetic_run.run_id)
            if pipeline_run.synthetic_run_id
            else None
        ),
    }
    source_fingerprint = hashlib.sha256(
        json.dumps(source_values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DataQualityReport.objects.create(
        school=pipeline_run.school,
        synthetic_run=pipeline_run.synthetic_run,
        pipeline_run=pipeline_run,
        window_start=pipeline_run.window_start,
        window_end=pipeline_run.window_end,
        methodology_version=METHODOLOGY_VERSION,
        source_fingerprint=source_fingerprint,
        status=status,
        gate_passed=status != DataQualityReport.Status.RED,
        event_count=event_count,
        ingestion_attempt_count=attempt_count,
        rejection_count=event_metrics["rejection_count"],
        legacy_unmapped_count=event_metrics["legacy_unmapped_count"],
        unlinked_legacy_count=reconciliation["unlinked_legacy_count"],
        thresholds=QUALITY_THRESHOLDS,
        counts={
            **event_metrics,
            "v1_total_count": v1_total,
            "v1_v2_difference_count": difference_count,
        },
        issues=issues,
        **rates,
    )


def execute_quality_pipeline(pipeline_run: AnalyticsPipelineRun) -> DataQualityReport:
    with transaction.atomic():
        run = AnalyticsPipelineRun.objects.select_for_update().get(pk=pipeline_run.pk)
        if run.status not in {
            AnalyticsPipelineRun.Status.PENDING,
            AnalyticsPipelineRun.Status.FAILED,
        }:
            if hasattr(run, "quality_report"):
                return run.quality_report
            raise QualityGateError(
                "pipeline_state_invalid", "数据质量流水线状态不可执行。"
            )
        run.status = AnalyticsPipelineRun.Status.RUNNING
        run.started_at = timezone.now()
        run.error_code = ""
        run.error_message = ""
        run.save(update_fields=["status", "started_at", "error_code", "error_message"])
    try:
        event_metrics = _task(
            run,
            "collect_event_quality",
            lambda: collect_event_quality_metrics(
                school=run.school,
                window_start=run.window_start,
                window_end=run.window_end,
                synthetic_run=run.synthetic_run,
            ),
        )
        reconciliation = _task(
            run,
            "reconcile_v1_v2",
            lambda: collect_reconciliation_metrics(
                school=run.school,
                synthetic_run=run.synthetic_run,
            ),
        )

        def publish_and_finalize():
            with transaction.atomic():
                report = publish_quality_report(
                    pipeline_run=run,
                    event_metrics=event_metrics,
                    reconciliation=reconciliation,
                )
                run.status = (
                    AnalyticsPipelineRun.Status.SUCCEEDED
                    if report.gate_passed
                    else AnalyticsPipelineRun.Status.BLOCKED
                )
                run.summary = {
                    "report_id": str(report.report_id),
                    "quality_status": report.status,
                    "gate_passed": report.gate_passed,
                    "issue_count": len(report.issues),
                }
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "summary", "finished_at"])
                return report

        report = _task(
            run,
            "publish_quality_report",
            publish_and_finalize,
        )
    except Exception as exc:
        run.status = AnalyticsPipelineRun.Status.FAILED
        run.error_code = type(exc).__name__[:64]
        run.error_message = str(exc)[:1000]
        run.finished_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "error_code",
                "error_message",
                "finished_at",
            ]
        )
        raise
    return report


def latest_quality_report(*, school, as_of=None, synthetic_run=None):
    query = DataQualityReport.objects.filter(school=school)
    if synthetic_run is None:
        query = query.filter(synthetic_run__isnull=True)
    else:
        query = query.filter(synthetic_run=synthetic_run)
    if as_of is not None:
        query = query.filter(window_end__lte=as_of)
    return query.select_related("pipeline_run").first()


def require_quality_gate(
    *, school, as_of=None, synthetic_run=None
) -> DataQualityReport:
    report = latest_quality_report(
        school=school,
        as_of=as_of,
        synthetic_run=synthetic_run,
    )
    if report is None:
        raise QualityGateError("quality_report_missing", "本校尚无数据质量报告。")
    if not report.gate_passed:
        raise QualityGateError("quality_gate_blocked", "本校数据质量闸门未通过。")
    return report
