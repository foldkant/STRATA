from __future__ import annotations

from celery import shared_task
from django.db import IntegrityError
from django.utils import timezone
from learning_analytics.models import AnalyticsPipelineRun
from learning_analytics.services.quality import (
    create_quality_pipeline_run,
    execute_quality_pipeline,
    previous_local_day_window,
)
from school.models import School


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def execute_data_quality_pipeline_task(self, pipeline_run_id: int):
    run = AnalyticsPipelineRun.objects.select_related("school", "synthetic_run").get(
        pk=pipeline_run_id
    )
    try:
        report = execute_quality_pipeline(run)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            raise
        retry_run = create_quality_pipeline_run(
            school=run.school,
            window_start=run.window_start,
            window_end=run.window_end,
            trigger=AnalyticsPipelineRun.Trigger.RETRY,
            retry_of=run,
            synthetic_run=run.synthetic_run,
        )
        raise self.retry(
            args=(retry_run.id,),
            exc=exc,
            countdown=60 * (self.request.retries + 1),
        )
    return {
        "pipeline_run_id": run.id,
        "run_id": str(run.run_id),
        "report_id": str(report.report_id),
        "status": report.status,
        "gate_passed": report.gate_passed,
    }


def dispatch_school_data_quality_pipeline(
    *, school, window_start, window_end, trigger: str
):
    run = create_quality_pipeline_run(
        school=school,
        window_start=window_start,
        window_end=window_end,
        trigger=trigger,
    )
    try:
        async_result = execute_data_quality_pipeline_task.delay(run.id)
    except Exception as exc:
        run.status = AnalyticsPipelineRun.Status.FAILED
        run.error_code = "dispatch_failed"
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
    return run, async_result


@shared_task
def run_nightly_data_quality():
    dispatched = []
    window_start, window_end = previous_local_day_window()
    for school in School.objects.filter(
        status=School.Status.ACTIVE,
        is_synthetic=False,
    ).iterator():
        run_query = AnalyticsPipelineRun.objects.filter(
            school=school,
            pipeline_type=AnalyticsPipelineRun.PipelineType.DATA_QUALITY,
            trigger=AnalyticsPipelineRun.Trigger.SCHEDULED,
            window_start=window_start,
            window_end=window_end,
        )
        existing = run_query.first()
        if existing:
            dispatched.append(
                {
                    "school_id": school.id,
                    "pipeline_run_id": existing.id,
                    "status": "existing",
                }
            )
            continue
        try:
            run, result = dispatch_school_data_quality_pipeline(
                school=school,
                window_start=window_start,
                window_end=window_end,
                trigger=AnalyticsPipelineRun.Trigger.SCHEDULED,
            )
        except IntegrityError:
            existing = run_query.get()
            dispatched.append(
                {
                    "school_id": school.id,
                    "pipeline_run_id": existing.id,
                    "status": "existing",
                }
            )
        except Exception as exc:
            failed = run_query.first()
            dispatched.append(
                {
                    "school_id": school.id,
                    "pipeline_run_id": failed.id if failed else None,
                    "status": "failed",
                    "error_code": type(exc).__name__[:64],
                }
            )
        else:
            dispatched.append(
                {
                    "school_id": school.id,
                    "pipeline_run_id": run.id,
                    "task_id": result.id,
                    "status": "dispatched",
                }
            )
    return dispatched
