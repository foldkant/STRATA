from __future__ import annotations

from datetime import datetime, time, timedelta

from celery import shared_task
from django.db import IntegrityError
from django.utils import timezone
from learning_analytics.models import AnalyticsPipelineRun
from learning_analytics.services.quality import (
    QualityCheckError,
    create_quality_pipeline_run,
    execute_quality_pipeline,
    previous_local_day_window,
    require_quality_checks,
)
from learning_analytics.services.learning_summaries import (
    rebuild_school_learning_summaries,
)
from learning_analytics.services.feature_registry import (
    sync_feature_and_outcome_definitions,
)
from learning_analytics.services.feature_snapshots import (
    freeze_due_decision_points,
)
from learning_analytics.services.outcomes import mature_due_outcomes
from learning_analytics.services.longitudinal import build_longitudinal_analysis
from learning_analytics.services.model_comparison import build_model_comparison
from learning_analytics.services.advanced_models import build_model_02_comparison
from learning_analytics.services.class_calibration import (
    build_class_calibration_candidate,
)
from learning_analytics.feature_models import TrainingDatasetVersion
from learning.models import TestAssessment
from learning.services.mastery import build_assessment_mastery_candidates
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
        "checks_passed": report.checks_passed,
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


@shared_task
def rebuild_school_learning_summaries_task(
    school_id: int, as_of_iso: str | None = None, require_quality: bool = True
):
    school = School.objects.get(pk=school_id)
    as_of = (
        datetime.fromisoformat(as_of_iso).date()
        if as_of_iso
        else timezone.localdate() - timedelta(days=1)
    )
    if require_quality:
        window_end = timezone.make_aware(
            datetime.combine(as_of + timedelta(days=1), time.min),
            timezone.get_current_timezone(),
        )
        require_quality_checks(school=school, as_of=window_end)
    return rebuild_school_learning_summaries(school=school, as_of=as_of)


@shared_task
def run_nightly_learning_summaries():
    as_of = timezone.localdate() - timedelta(days=1)
    rows = []
    for school in School.objects.filter(
        status=School.Status.ACTIVE,
        is_synthetic=False,
    ).iterator():
        try:
            result = rebuild_school_learning_summaries_task(
                school.id, as_of.isoformat(), True
            )
        except QualityCheckError as exc:
            rows.append(
                {
                    "school_id": school.id,
                    "status": "skipped",
                    "reason": exc.code,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "school_id": school.id,
                    "status": "failed",
                    "reason": type(exc).__name__,
                }
            )
        else:
            rows.append({"school_id": school.id, "status": "completed", **result})
    return rows


@shared_task
def run_nightly_mastery_candidates(include_test_data: bool = False):
    rows = []
    assessments = TestAssessment.objects.filter(
        status=TestAssessment.Status.CLOSED,
        common_question_set__isnull=False,
        is_active=True,
    ).select_related("school", "subject", "course", "common_question_set")
    if not include_test_data:
        assessments = assessments.filter(school__is_synthetic=False)
    for assessment in assessments.iterator():
        try:
            result = build_assessment_mastery_candidates(assessment=assessment)
        except Exception as exc:
            rows.append(
                {
                    "assessment_id": assessment.id,
                    "school_id": assessment.school_id,
                    "status": "failed",
                    "reason": type(exc).__name__,
                }
            )
        else:
            rows.append(
                {
                    "assessment_id": assessment.id,
                    "school_id": assessment.school_id,
                    "status": "completed",
                    **result,
                }
            )
    return rows


@shared_task
def run_nightly_feature_outcomes():
    sync_feature_and_outcome_definitions()
    frozen = freeze_due_decision_points()
    schools = []
    for school in School.objects.filter(
        status=School.Status.ACTIVE,
        is_synthetic=False,
    ).iterator():
        try:
            counts = mature_due_outcomes(school=school)
        except Exception as exc:
            schools.append(
                {
                    "school_id": school.id,
                    "status": "failed",
                    "reason": type(exc).__name__,
                }
            )
        else:
            schools.append({"school_id": school.id, "status": "completed", **counts})
    return {"decision_points": frozen, "schools": schools}


@shared_task
def run_nightly_model_validation(include_test_data: bool = False):
    """对已冻结正式数据做重复测量和基线比较；结果始终是影子结果。"""
    rows = []
    datasets = TrainingDatasetVersion.objects.filter(
        status=TrainingDatasetVersion.Status.FROZEN,
    ).select_related("school", "subject")
    if not include_test_data:
        datasets = datasets.filter(
            synthetic_run__isnull=True,
            school__is_synthetic=False,
        )
    latest_datasets = {}
    for dataset in datasets.order_by(
        "school_id",
        "subject_id",
        "feature_set_id",
        "outcome_definition_id",
        "-frozen_at",
        "-id",
    ).iterator():
        scope_key = (
            dataset.school_id,
            dataset.subject_id,
            dataset.feature_set_id,
            dataset.outcome_definition_id,
            dataset.synthetic_run_id if include_test_data else None,
        )
        latest_datasets.setdefault(scope_key, dataset)
    for dataset in latest_datasets.values():
        try:
            longitudinal = build_longitudinal_analysis(dataset=dataset)
            comparison = build_model_comparison(dataset=dataset)
            advanced = build_model_02_comparison(
                dataset=dataset,
                include_test_data=include_test_data,
            )
            calibration = build_class_calibration_candidate(
                dataset=dataset,
                comparison_run=advanced,
                include_test_data=include_test_data,
            )
        except Exception as exc:
            rows.append(
                {
                    "dataset_id": dataset.id,
                    "school_id": dataset.school_id,
                    "status": "failed",
                    "reason": type(exc).__name__,
                }
            )
        else:
            rows.append(
                {
                    "dataset_id": dataset.id,
                    "school_id": dataset.school_id,
                    "status": "completed",
                    "longitudinal_run_id": longitudinal.id,
                    "comparison_run_id": comparison.id,
                    "comparison_status": comparison.status,
                    "advanced_comparison_run_id": advanced.id,
                    "advanced_comparison_status": advanced.status,
                    "calibration_run_id": calibration.id,
                    "calibration_status": calibration.status,
                    "suggestion_count": calibration.suggestion_count,
                }
            )
    return rows
