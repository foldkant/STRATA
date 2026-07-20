from __future__ import annotations

import hashlib
import tempfile
import zipfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, CourseClass, Subject
from learning.models import StratificationDecision
from learning_analytics.models import (
    ClassCalibrationRun,
    FeatureSetVersion,
    ModelComparisonRun,
    ModelRelease,
    ModelReleaseAudit,
    OutcomeDefinition,
    TrainingDatasetVersion,
)
from learning_analytics.services.model_packages import (
    publish_model_candidate,
    rollback_model_release,
    verify_model_package,
    verify_model_release,
)
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class ModelReleaseTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.settings_override = override_settings(
            MODEL_ARTIFACT_ROOT=root / "artifacts",
            MODEL_PACKAGE_ROOT=root / "packages",
            MODEL_SIGNING_PRIVATE_KEY_PATH=root / "keys" / "private.pem",
            MODEL_SIGNING_PUBLIC_KEY_PATH=root / "keys" / "public.pem",
            MODEL_SIGNING_AUTO_CREATE=True,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        (root / "artifacts").mkdir(parents=True)
        self.artifact_root = root / "artifacts"

        self.school = School.objects.create(name="模型发布测试学校", code="RELEASE")
        self.other_school = School.objects.create(name="其他学校", code="OTHER-RELEASE")
        self.subject = Subject.objects.create(
            school=self.school, name="信息科技", code="IT"
        )
        self.admin = User.objects.create_user(
            username="release_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.other_admin = User.objects.create_user(
            username="other_release_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.other_school,
        )
        self.teacher = User.objects.create_user(
            username="release_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.student = User.objects.create_user(
            username="release_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与计算",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.feature_set = FeatureSetVersion.objects.create(
            set_key="release-test-features",
            version="1.0",
            label="模型发布测试指标",
            definition_manifest=[{"feature_key": "completion_rate"}],
            allowed_views=["operational_available"],
            status=FeatureSetVersion.Status.ACTIVE,
            created_by=self.admin,
        )
        self.outcome = OutcomeDefinition.objects.create(
            outcome_key="release_test_outcome",
            version="1.0",
            label="后续任务完成率",
            outcome_type=OutcomeDefinition.OutcomeType.RATIO,
            horizon_days=7,
            min_denominator=1,
            formula="completed / assigned",
            eligibility_rule="assigned > 0",
            allowed_evidence=["assessment"],
            missing_codes=["NO_OPPORTUNITY"],
            generator_key="release_test",
            code_hash="a" * 64,
            status=OutcomeDefinition.Status.ACTIVE,
        )

    def _candidate(self, suffix: str, *, blocked: bool = False):
        now = timezone.now()
        dataset = TrainingDatasetVersion.objects.create(
            dataset_key=f"release-dataset-{suffix}",
            school=self.school,
            subject=self.subject,
            feature_set=self.feature_set,
            outcome_definition=self.outcome,
            status=TrainingDatasetVersion.Status.FROZEN,
            decision_start=now,
            decision_end=now,
            split_strategy="time-and-class",
            generator_version="test-v1",
            manifest={"suffix": suffix},
            manifest_hash=hashlib.sha256(suffix.encode()).hexdigest(),
            source_hash=hashlib.sha256(f"source-{suffix}".encode()).hexdigest(),
            row_count=60,
            observed_count=60,
            created_by=self.admin,
            frozen_at=now,
        )
        comparison = ModelComparisonRun.objects.create(
            run_key=f"release-comparison-{suffix}",
            dataset=dataset,
            school=self.school,
            subject=self.subject,
            comparison_version=f"model-02-{suffix}",
            status=(
                ModelComparisonRun.Status.BLOCKED
                if blocked
                else ModelComparisonRun.Status.SHADOW_ONLY
            ),
            target_type="continuous",
            model_keys=["M00", "catboost"],
            validation_keys=["V-A", "V-B", "V-C"],
            manifest={"blockers": ["测试阻塞"] if blocked else []},
            model_card={"title": "测试比较"},
            row_count=60,
            observed_count=60,
            created_by=self.admin,
        )
        artifact = self.artifact_root / f"candidate-{suffix}.json"
        artifact.write_bytes(f'{{"candidate":"{suffix}"}}'.encode())
        calibration = ClassCalibrationRun.objects.create(
            run_key=f"release-calibration-{suffix}",
            dataset=dataset,
            comparison_run=comparison,
            school=self.school,
            subject=self.subject,
            calibration_version=f"model-03-{suffix}",
            model_key="catboost",
            status=(
                ClassCalibrationRun.Status.BLOCKED
                if blocked
                else ClassCalibrationRun.Status.CANDIDATE
            ),
            global_parameters={"thresholds": [0.33, 0.67]},
            class_parameters={str(self.class_group.id): {"shift": 0.0}},
            model_card={"teacher_confirmation_required": True},
            manifest={"blockers": ["测试阻塞"] if blocked else []},
            artifact_path=str(artifact),
            artifact_hash=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            suggestion_count=1,
            created_by=self.admin,
        )
        return calibration, artifact

    def _decision(self, calibration, suffix: str):
        return StratificationDecision.objects.create(
            student=self.student,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            previous_layer="B",
            suggested_layer="A",
            confidence=0.8,
            reasons=["近 30 日学习记录稳定"],
            learning_summary={"calibration_run_id": calibration.id},
            rule_version=f"m03-{suffix}",
            calibration_run=calibration,
            status=StratificationDecision.Status.PENDING,
        )

    def test_publish_creates_verified_signed_package(self):
        calibration, _ = self._candidate("one")

        release = publish_model_candidate(
            calibration_run=calibration, actor=self.admin
        )

        self.assertEqual(release.status, ModelRelease.Status.ACTIVE)
        self.assertEqual(release.release_version, 1)
        self.assertTrue(Path(release.package_path).is_file())
        manifest = verify_model_release(release=release)
        self.assertEqual(manifest["calibration"]["run_id"], str(calibration.run_id))
        self.assertTrue(manifest["rules"]["teacher_confirmation_required"])

    def test_blocked_candidate_is_rejected(self):
        calibration, _ = self._candidate("blocked", blocked=True)

        with self.assertRaises(ValidationError):
            publish_model_candidate(calibration_run=calibration, actor=self.admin)

        self.assertFalse(ModelRelease.objects.exists())
        self.assertTrue(
            ModelReleaseAudit.objects.filter(
                action=ModelReleaseAudit.Action.PUBLISH,
                result=ModelReleaseAudit.Result.FAILED,
            ).exists()
        )

    def test_failed_second_publish_keeps_current_release_active(self):
        first, _ = self._candidate("first")
        active = publish_model_candidate(calibration_run=first, actor=self.admin)
        second, artifact = self._candidate("second")
        artifact.write_bytes(b"corrupted-after-hash")

        with self.assertRaises(ValidationError):
            publish_model_candidate(calibration_run=second, actor=self.admin)

        active.refresh_from_db()
        self.assertEqual(active.status, ModelRelease.Status.ACTIVE)
        self.assertEqual(ModelRelease.objects.count(), 1)

    def test_new_release_supersedes_old_and_rollback_restores_it(self):
        first, _ = self._candidate("v1")
        first_decision = self._decision(first, "release-v1")
        old_release = publish_model_candidate(calibration_run=first, actor=self.admin)
        second, _ = self._candidate("v2")
        second_decision = self._decision(second, "release-v2")

        first_decision.refresh_from_db()
        self.assertEqual(first_decision.status, StratificationDecision.Status.PENDING)
        new_release = publish_model_candidate(calibration_run=second, actor=self.admin)

        old_release.refresh_from_db()
        first_decision.refresh_from_db()
        second_decision.refresh_from_db()
        self.assertEqual(old_release.status, ModelRelease.Status.SUPERSEDED)
        self.assertEqual(new_release.release_version, 2)
        self.assertEqual(first_decision.status, StratificationDecision.Status.DEFERRED)
        self.assertEqual(second_decision.status, StratificationDecision.Status.PENDING)

        restored = rollback_model_release(target=old_release, actor=self.admin)

        new_release.refresh_from_db()
        first_decision.refresh_from_db()
        second_decision.refresh_from_db()
        self.assertEqual(restored.status, ModelRelease.Status.ACTIVE)
        self.assertEqual(new_release.status, ModelRelease.Status.ROLLED_BACK)
        self.assertEqual(first_decision.status, StratificationDecision.Status.PENDING)
        self.assertEqual(second_decision.status, StratificationDecision.Status.DEFERRED)

    def test_tampered_package_signature_is_rejected(self):
        calibration, _ = self._candidate("tamper")
        release = publish_model_candidate(calibration_run=calibration, actor=self.admin)
        package = Path(release.package_path)
        with zipfile.ZipFile(package, "a") as bundle:
            bundle.writestr("manifest.json", b'{"tampered":true}')
        public_key = Path(self.settings_override.options["MODEL_SIGNING_PUBLIC_KEY_PATH"])

        with self.assertRaises(ValidationError):
            verify_model_package(package, trusted_public_key=public_key.read_bytes())

    def test_release_api_is_school_scoped(self):
        calibration, _ = self._candidate("api")
        client = APIClient()
        client.force_authenticate(self.other_admin)
        denied = client.post(
            f"/api/v1/school-admin/analytics/models/class-calibration/{calibration.id}/publish/?include_test_data=1",
            {},
            format="json",
        )
        self.assertEqual(denied.status_code, 404)

        client.force_authenticate(self.admin)
        response = client.post(
            f"/api/v1/school-admin/analytics/models/class-calibration/{calibration.id}/publish/?include_test_data=1",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["release"]["status"], "active")

    def test_teacher_only_sees_candidate_after_release(self):
        calibration, _ = self._candidate("teacher")
        self._decision(calibration, "test-v1")
        client = APIClient()
        client.force_authenticate(self.teacher)

        hidden = client.get("/api/v1/teacher/analytics/stratification/")
        self.assertEqual(hidden.status_code, 200)
        self.assertEqual(hidden.data["data"], [])

        publish_model_candidate(calibration_run=calibration, actor=self.admin)
        visible = client.get("/api/v1/teacher/analytics/stratification/")
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(len(visible.data["data"]), 1)
