from __future__ import annotations

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from learning.models import LearningEvent
from learning_analytics.models import (
    AnalyticsPipelineRun,
    DataQualityReport,
    LearningEventV2,
    SyntheticDatasetRun,
    SyntheticStudentTruth,
)
from learning_analytics.services.synthetic_data import (
    SyntheticDataConfig,
    generate_synthetic_dataset,
)
from learning_analytics.services.synthetic_cleanup import purge_synthetic_dataset
from learning_analytics.services.quality import (
    create_quality_pipeline_run,
    execute_quality_pipeline,
    latest_quality_report,
    require_quality_gate,
)
from learning_analytics.tasks import run_nightly_data_quality
from school.models import School, StudentProfile


class SyntheticDataGenerationTests(TestCase):
    def config(self) -> SyntheticDataConfig:
        return SyntheticDataConfig(
            school_code="SIM-TEST",
            school_name="合成数据测试学校",
            seed=20260719,
            class_count=1,
            students_per_class=3,
            weeks=2,
            end_date=date(2026, 7, 18),
        )

    def test_generation_is_traceable_deterministic_and_quality_green(self):
        result = generate_synthetic_dataset(self.config())

        school = School.objects.get(code="SIM-TEST")
        run = SyntheticDatasetRun.objects.get(dataset_key=result["dataset_key"])
        report = DataQualityReport.objects.get(report_id=result["quality"]["report_id"])
        events = LearningEventV2.objects.filter(school=school)

        self.assertTrue(school.is_synthetic)
        self.assertEqual(run.status, SyntheticDatasetRun.Status.SUCCEEDED)
        self.assertEqual(
            SyntheticStudentTruth.objects.filter(synthetic_run=run).count(), 3
        )
        self.assertEqual(
            StudentProfile.objects.filter(
                user__school=school, current_layer__isnull=True
            ).count(),
            3,
        )
        self.assertGreater(events.count(), 0)
        self.assertFalse(events.exclude(synthetic_run=run).exists())
        self.assertFalse(
            LearningEvent.objects.filter(actor__school=school)
            .exclude(metadata__synthetic=True)
            .exists()
        )
        self.assertEqual(report.status, DataQualityReport.Status.GREEN)
        self.assertTrue(report.gate_passed)
        self.assertEqual(float(report.semantic_missing_rate), 0)
        self.assertEqual(float(report.v1_v2_difference_rate), 0)
        self.assertEqual(report.event_count, events.count())

        before = {
            "events": events.count(),
            "truths": SyntheticStudentTruth.objects.filter(synthetic_run=run).count(),
            "runs": SyntheticDatasetRun.objects.count(),
        }
        repeated = generate_synthetic_dataset(self.config())
        after = {
            "events": LearningEventV2.objects.filter(school=school).count(),
            "truths": SyntheticStudentTruth.objects.filter(synthetic_run=run).count(),
            "runs": SyntheticDatasetRun.objects.count(),
        }
        self.assertTrue(repeated["reused"])
        self.assertEqual(before, after)
        self.assertEqual(repeated["manifest_hash"], result["manifest_hash"])

    def test_synthetic_school_is_excluded_from_operational_surfaces(self):
        generate_synthetic_dataset(self.config())
        self.assertEqual(run_nightly_data_quality(), [])

        super_admin = User.objects.create_superuser(
            username="synthetic_audit_admin",
            password="Admin123!",
            role=User.Role.SUPER_ADMIN,
        )
        client = APIClient()
        client.force_authenticate(super_admin)
        response = client.get("/api/v1/super-admin/dashboard/")

        self.assertEqual(response.status_code, 200)
        metrics = {
            item["label"]: item["value"] for item in response.data["data"]["metrics"]
        }
        self.assertEqual(metrics["学校"], 0)
        self.assertEqual(metrics["教师"], 0)
        self.assertEqual(metrics["学生档案"], 0)
        self.assertEqual(metrics["班级"], 0)
        self.assertEqual(metrics["行为事件"], 0)

    def test_school_overlay_is_visible_but_does_not_dilute_formal_quality(self):
        school = School.objects.create(name="正式试测学校", code="REAL-OVERLAY")
        teacher = User.objects.create_user(
            username="overlay_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=school,
        )
        config = SyntheticDataConfig(
            school_code=school.code,
            school_name=school.name,
            seed=20260720,
            class_count=1,
            students_per_class=3,
            weeks=2,
            end_date=date(2026, 7, 18),
            mode=SyntheticDatasetRun.Mode.SCHOOL_OVERLAY,
            teacher_username=teacher.username,
        )

        result = generate_synthetic_dataset(config)
        run = SyntheticDatasetRun.objects.get(run_id=result["run_id"])
        synthetic_report = DataQualityReport.objects.get(synthetic_run=run)
        formal_pipeline = create_quality_pipeline_run(
            school=school,
            window_start=run.window_start,
            window_end=run.window_end,
            trigger=AnalyticsPipelineRun.Trigger.MANUAL,
        )
        formal_report = execute_quality_pipeline(formal_pipeline)

        self.assertFalse(school.is_synthetic)
        self.assertEqual(run.mode, SyntheticDatasetRun.Mode.SCHOOL_OVERLAY)
        self.assertTrue(synthetic_report.gate_passed)
        self.assertEqual(synthetic_report.event_count, result["counts"]["events"])
        self.assertFalse(formal_report.gate_passed)
        self.assertEqual(formal_report.event_count, 0)
        self.assertEqual(latest_quality_report(school=school), formal_report)
        self.assertEqual(
            require_quality_gate(school=school, synthetic_run=run),
            synthetic_report,
        )
        students = User.objects.filter(synthetic_truth_records__synthetic_run=run)
        self.assertEqual(students.count(), 3)
        self.assertTrue(all(user.check_password("123456") for user in students))
        self.assertTrue(teacher.courses.filter(title__contains="SIM-").exists())

        summary = purge_synthetic_dataset(
            run=run,
            confirmation_key=run.dataset_key,
        )
        run.refresh_from_db()

        self.assertEqual(summary["events"], result["counts"]["events"])
        self.assertEqual(run.status, SyntheticDatasetRun.Status.PURGED)
        self.assertTrue(User.objects.filter(pk=teacher.pk).exists())
        self.assertTrue(School.objects.filter(pk=school.pk).exists())
        self.assertFalse(LearningEventV2.objects.filter(synthetic_run=run).exists())
        self.assertFalse(
            SyntheticStudentTruth.objects.filter(synthetic_run=run).exists()
        )
        self.assertFalse(school.classes.exists())
        self.assertFalse(teacher.courses.exists())
        self.assertTrue(DataQualityReport.objects.filter(pk=formal_report.pk).exists())
