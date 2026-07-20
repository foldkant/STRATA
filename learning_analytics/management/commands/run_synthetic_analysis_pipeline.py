from __future__ import annotations

import json
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from courses.models import Course, CourseClass
from learning_analytics.models import (
    AnalyticsPipelineRun,
    DataQualityReport,
    OutcomeDefinition,
    OutcomeObservation,
    SyntheticDatasetRun,
)
from learning_analytics.services.advanced_models import build_model_02_comparison
from learning_analytics.services.class_calibration import (
    build_class_calibration_candidate,
)
from learning_analytics.services.feature_registry import (
    sync_feature_and_outcome_definitions,
)
from learning_analytics.services.feature_snapshots import create_decision_point
from learning_analytics.services.longitudinal import build_longitudinal_analysis
from learning_analytics.services.model_comparison import build_model_comparison
from learning_analytics.services.outcomes import (
    build_training_dataset,
    mature_due_outcomes,
)
from learning_analytics.services.quality import (
    create_quality_pipeline_run,
    execute_quality_pipeline,
)


def _ensure_historical_quality_reports(
    run: SyntheticDatasetRun, window_ends
) -> int:
    created_count = 0
    for window_end in sorted(window_ends):
        if DataQualityReport.objects.filter(
            synthetic_run=run,
            window_end=window_end,
            checks_passed=True,
        ).exists():
            continue
        pipeline_run = create_quality_pipeline_run(
            school=run.school,
            window_start=run.window_start,
            window_end=window_end,
            trigger=AnalyticsPipelineRun.Trigger.MANUAL,
            synthetic_run=run,
        )
        report = execute_quality_pipeline(pipeline_run)
        if not report.checks_passed:
            raise CommandError(
                f"批次 {run.run_id} 截至 {window_end.isoformat()} 的数据检查未通过。"
            )
        created_count += 1
    return created_count


class Command(BaseCommand):
    help = "Run decision points, frozen datasets, MODEL-01/02 and MODEL-03 for test batches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            action="append",
            default=[],
            help="Synthetic run UUID; repeat to process several schools together.",
        )
        parser.add_argument(
            "--outcome-key",
            default="new_overdue_count_next_7d",
        )

    def handle(self, *args, **options):
        sync_feature_and_outcome_definitions()
        runs = SyntheticDatasetRun.objects.filter(
            status=SyntheticDatasetRun.Status.SUCCEEDED
        ).select_related("school")
        if options["run_id"]:
            runs = runs.filter(run_id__in=options["run_id"])
        runs = list(runs.order_by("created_at"))
        if not runs:
            raise CommandError("没有可运行的测试数据批次。")
        outcome = OutcomeDefinition.objects.filter(
            outcome_key=options["outcome_key"],
            status=OutcomeDefinition.Status.ACTIVE,
        ).first()
        if outcome is None:
            raise CommandError("未来结果定义不存在。")

        prepared = []
        for run in runs:
            course = (
                Course.objects.filter(
                    subject__school=run.school,
                    title__contains=run.dataset_key[:8].upper(),
                )
                .select_related("subject", "teacher")
                .first()
            )
            if course is None:
                raise CommandError(f"批次 {run.run_id} 找不到测试课程。")
            classes = list(
                CourseClass.objects.filter(course=course)
                .select_related("class_group")
                .order_by("class_group_id")
            )
            start_date = parse_date(str(run.configuration.get("start_date") or ""))
            weeks = int(run.configuration.get("weeks") or 0)
            if start_date is None or weeks < 6:
                raise CommandError(
                    f"批次 {run.run_id} 至少需要 6 周测试数据。"
                )
            point_count = 0
            quality_report_count = 0
            for week_index in range(1, weeks - 1):
                point_date = start_date + timedelta(days=week_index * 7 + 1)
                scheduled_for = timezone.make_aware(
                    datetime.combine(point_date, time(hour=18)),
                    timezone.get_current_timezone(),
                )
                quality_report_count += _ensure_historical_quality_reports(
                    run, [scheduled_for]
                )
                for relation in classes:
                    class_group = relation.class_group
                    existing = run.analysis_decision_points.filter(
                        class_group=class_group,
                        course=course,
                        scheduled_for=scheduled_for,
                    ).first()
                    if existing is None:
                        create_decision_point(
                            school=run.school,
                            class_group=class_group,
                            subject=course.subject,
                            course=course,
                            scheduled_for=scheduled_for,
                            created_by=course.teacher,
                            synthetic_run=run,
                            title=f"[测试] {class_group.name} 第 {week_index + 1} 周分析",
                        )
                    point_count += 1
            outcome_windows = list(
                OutcomeObservation.objects.filter(
                    decision_point__synthetic_run=run,
                    status=OutcomeObservation.Status.PENDING,
                )
                .order_by()
                .values_list("window_end", flat=True)
                .distinct()
            )
            quality_report_count += _ensure_historical_quality_reports(
                run, outcome_windows
            )
            outcome_counts = mature_due_outcomes(
                school=run.school,
                as_of=run.window_end + timedelta(days=8),
                synthetic_run=run,
            )
            dataset = build_training_dataset(
                school=run.school,
                subject=course.subject,
                outcome_definition=outcome,
                created_by=course.teacher,
                synthetic_run=run,
            )
            prepared.append(
                (
                    run,
                    course,
                    dataset,
                    point_count,
                    quality_report_count,
                    outcome_counts,
                )
            )

        results = []
        for (
            run,
            course,
            dataset,
            point_count,
            quality_report_count,
            outcome_counts,
        ) in prepared:
            longitudinal = build_longitudinal_analysis(
                dataset=dataset, created_by=course.teacher
            )
            model_01 = build_model_comparison(
                dataset=dataset, created_by=course.teacher
            )
            model_02 = build_model_02_comparison(
                dataset=dataset,
                created_by=course.teacher,
                include_test_data=True,
            )
            model_03 = build_class_calibration_candidate(
                dataset=dataset,
                comparison_run=model_02,
                created_by=course.teacher,
                include_test_data=True,
            )
            results.append(
                {
                    "run_id": str(run.run_id),
                    "school": run.school.name,
                    "school_code": run.school.code,
                    "decision_points": point_count,
                    "historical_quality_reports": quality_report_count,
                    "outcomes": outcome_counts,
                    "dataset_id": dataset.id,
                    "dataset_key": dataset.dataset_key,
                    "dataset_rows": dataset.row_count,
                    "comparison_ready": dataset.manifest.get("comparison_ready"),
                    "longitudinal": {
                        "id": longitudinal.id,
                        "status": longitudinal.status,
                    },
                    "model_01": {"id": model_01.id, "status": model_01.status},
                    "model_02": {"id": model_02.id, "status": model_02.status},
                    "model_03": {
                        "id": model_03.id,
                        "status": model_03.status,
                        "suggestions": model_03.suggestion_count,
                    },
                }
            )
        self.stdout.write(
            json.dumps(results, ensure_ascii=False, sort_keys=True, default=str)
        )
