from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, CourseClass, Resource, Subject
from learning.models import LearningEvent
from learning_analytics.models import (
    AnalyticsPipelineRun,
    AnalyticsTaskRun,
    DataQualityReport,
    EventIngestionDailyCounter,
)
from learning_analytics.services.ingestion_counters import record_ingestion_outcome
from learning_analytics.services.legacy_backfill import backfill_legacy_event
from learning_analytics.services.operational_events import record_resource_center_opened
from learning_analytics.services.quality import (
    QualityGateError,
    create_quality_pipeline_run,
    execute_quality_pipeline,
    require_quality_gate,
    trailing_window,
)
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from learning_analytics.tasks import run_nightly_data_quality
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class DataQualityPipelineTests(TestCase):
    def setUp(self):
        sync_event_schema_definitions()
        self.school = School.objects.create(name="Quality School", code="QUALITY")
        self.other_school = School.objects.create(
            name="Other Quality School", code="OTHER-QUALITY"
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="Class 1", grade="Grade 1"
        )
        self.subject = Subject.objects.create(
            school=self.school, name="Computing", code="QUALITY-COMPUTING"
        )
        self.teacher = User.objects.create_user(
            username="quality_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.student = User.objects.create_user(
            username="quality_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        self.school_admin = User.objects.create_user(
            username="quality_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.other_admin = User.objects.create_user(
            username="other_quality_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.other_school,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="Quality course",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.resource = Resource.objects.create(
            title="Quality resource",
            owner=self.teacher,
            subject=self.subject,
            resource_type=Resource.ResourceType.ARTICLE,
            visibility=Resource.Visibility.SCHOOL,
            publish_status=Resource.PublishStatus.PUBLISHED,
        )
        self.quality_as_of = timezone.now() + timedelta(days=1)
        self.window_start, self.window_end = trailing_window(
            days=7, now=self.quality_as_of
        )

    def _run(self):
        window_start, window_end = trailing_window(days=7, now=self.quality_as_of)
        run = create_quality_pipeline_run(
            school=self.school,
            window_start=window_start,
            window_end=window_end,
            trigger=AnalyticsPipelineRun.Trigger.MANUAL,
        )
        return run, execute_quality_pipeline(run)

    def test_manual_quality_window_uses_complete_local_days(self):
        now = timezone.make_aware(
            datetime(2026, 7, 19, 15, 23, 45), timezone.get_current_timezone()
        )
        window_start, window_end = trailing_window(days=7, now=now)

        self.assertEqual(timezone.localtime(window_end).hour, 0)
        self.assertEqual(timezone.localtime(window_end).date().isoformat(), "2026-07-19")
        self.assertEqual((window_end - window_start).days, 7)

    def test_green_report_and_gate_are_reproducible(self):
        record_resource_center_opened(
            resource=self.resource,
            student=self.student,
            profile=self.profile,
        )
        run, report = self._run()

        run.refresh_from_db()
        self.assertEqual(run.status, AnalyticsPipelineRun.Status.SUCCEEDED)
        self.assertEqual(report.status, DataQualityReport.Status.GREEN)
        self.assertTrue(report.gate_passed)
        self.assertEqual(report.event_count, 1)
        self.assertEqual(float(report.opportunity_coverage_rate), 1)
        self.assertEqual(run.task_runs.count(), 3)
        self.assertFalse(
            run.task_runs.exclude(status=AnalyticsTaskRun.Status.SUCCEEDED).exists()
        )
        self.assertEqual(require_quality_gate(school=self.school), report)

        report.status = DataQualityReport.Status.RED
        with self.assertRaises(ValidationError):
            report.save()

    def test_legacy_unmapped_produces_red_blocking_report(self):
        legacy = LearningEvent.objects.create(
            actor=self.student,
            class_group=self.class_group,
            event_type=LearningEvent.EventType.LOGIN,
            occurred_at=timezone.now(),
        )
        backfill_legacy_event(legacy)
        run, report = self._run()

        run.refresh_from_db()
        self.assertEqual(report.status, DataQualityReport.Status.RED)
        self.assertFalse(report.gate_passed)
        self.assertEqual(run.status, AnalyticsPipelineRun.Status.BLOCKED)
        self.assertGreater(float(report.semantic_missing_rate), 0.15)
        with self.assertRaises(QualityGateError) as blocked:
            require_quality_gate(school=self.school)
        self.assertEqual(blocked.exception.code, "quality_gate_blocked")

    def test_ingestion_attempt_counters_drive_duplicate_and_invalid_rates(self):
        record_resource_center_opened(
            resource=self.resource,
            student=self.student,
            profile=self.profile,
        )
        record_ingestion_outcome(
            school=self.school,
            source="student-web",
            status="duplicate",
            event_name="resource.center.opened",
        )
        record_ingestion_outcome(
            school=self.school,
            source="student-web",
            status="rejected",
            error_code="context_mismatch",
            event_name="resource.center.opened",
        )
        counter = EventIngestionDailyCounter.objects.get(school=self.school)
        self.assertEqual(counter.accepted_count, 1)
        self.assertEqual(counter.duplicate_count, 1)
        self.assertEqual(counter.rejected_count, 1)

        _run, report = self._run()
        self.assertGreater(float(report.duplicate_rate), 0.10)
        self.assertGreater(float(report.invalid_event_rate), 0.05)
        self.assertEqual(report.status, DataQualityReport.Status.RED)

    def test_failed_stage_is_recorded_without_partial_report(self):
        run = create_quality_pipeline_run(
            school=self.school,
            window_start=self.window_start,
            window_end=self.window_end,
            trigger=AnalyticsPipelineRun.Trigger.MANUAL,
        )
        with (
            patch(
                "learning_analytics.services.quality.collect_event_quality_metrics",
                side_effect=RuntimeError("quality collection failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            execute_quality_pipeline(run)
        run.refresh_from_db()
        self.assertEqual(run.status, AnalyticsPipelineRun.Status.FAILED)
        self.assertFalse(DataQualityReport.objects.filter(pipeline_run=run).exists())
        task = run.task_runs.get(task_name="collect_event_quality")
        self.assertEqual(task.status, AnalyticsTaskRun.Status.FAILED)

        retry = create_quality_pipeline_run(
            school=self.school,
            window_start=self.window_start,
            window_end=self.window_end,
            trigger=AnalyticsPipelineRun.Trigger.RETRY,
            retry_of=run,
        )
        self.assertEqual(retry.attempt_no, 2)
        self.assertEqual(retry.retry_of, run)

    def test_school_quality_api_is_scoped_and_can_enqueue_manual_run(self):
        record_resource_center_opened(
            resource=self.resource,
            student=self.student,
            profile=self.profile,
        )
        self._run()
        client = APIClient()
        client.force_authenticate(self.school_admin)
        response = client.get("/api/v1/school-admin/analytics/quality/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["school"]["id"], self.school.id)
        self.assertEqual(response.data["data"]["current"]["status"], "green")
        self.assertEqual(len(response.data["data"]["current"]["metrics"]), 7)
        self.assertIn(
            "direction", response.data["data"]["current"]["metrics"][0]["thresholds"]
        )

        client.force_authenticate(self.other_admin)
        response = client.get("/api/v1/school-admin/analytics/quality/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["current"])

        client.force_authenticate(self.student)
        self.assertEqual(
            client.get("/api/v1/school-admin/analytics/quality/").status_code,
            403,
        )

        client.force_authenticate(self.other_admin)
        with patch(
            "learning_analytics.tasks.execute_data_quality_pipeline_task.delay",
            return_value=SimpleNamespace(id="quality-task-1"),
        ):
            response = client.post(
                "/api/v1/school-admin/analytics/quality/run/",
                {"days": 7},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        queued = AnalyticsPipelineRun.objects.get(
            pk=response.data["data"]["run"]["id"]
        )
        self.assertEqual(queued.school, self.other_school)
        self.assertEqual(queued.status, AnalyticsPipelineRun.Status.PENDING)

    def test_nightly_dispatch_is_idempotent_for_the_same_school_window(self):
        with patch(
            "learning_analytics.tasks.execute_data_quality_pipeline_task.delay",
            side_effect=[SimpleNamespace(id="night-1"), SimpleNamespace(id="night-2")],
        ) as delay:
            first = run_nightly_data_quality()
            second = run_nightly_data_quality()

        self.assertEqual(delay.call_count, 2)
        self.assertEqual({row["status"] for row in first}, {"dispatched"})
        self.assertEqual({row["status"] for row in second}, {"existing"})
        self.assertEqual(
            AnalyticsPipelineRun.objects.filter(
                trigger=AnalyticsPipelineRun.Trigger.SCHEDULED
            ).count(),
            2,
        )

    def test_nightly_dispatch_isolates_one_school_broker_failure(self):
        with patch(
            "learning_analytics.tasks.execute_data_quality_pipeline_task.delay",
            side_effect=[RuntimeError("broker unavailable"), SimpleNamespace(id="night-ok")],
        ):
            results = run_nightly_data_quality()

        self.assertEqual(len(results), 2)
        self.assertEqual({row["status"] for row in results}, {"failed", "dispatched"})
        self.assertEqual(
            AnalyticsPipelineRun.objects.filter(
                status=AnalyticsPipelineRun.Status.FAILED
            ).count(),
            1,
        )
        self.assertEqual(
            AnalyticsPipelineRun.objects.filter(
                status=AnalyticsPipelineRun.Status.PENDING
            ).count(),
            1,
        )
