from __future__ import annotations

from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import User
from courses.models import Course, Subject
from learning_analytics.models import TestDataBatch, TestDataObjectMarker
from learning_analytics.services.test_data_governance import (
    assert_no_explicit_test_data_objects,
    exclude_explicit_test_data_objects,
    is_explicit_test_data_object,
)
from school.models import School


class TestDataGovernanceCommandTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="批次标记测试学校", code="TEST-BATCH-SCHOOL"
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT-TEST-BATCH",
        )
        self.super_admin = User.objects.create_user(
            username="test_batch_super_admin",
            password="Test-only-123!",
            role=User.Role.SUPER_ADMIN,
        )
        self.teacher = User.objects.create_user(
            username="test_batch_teacher",
            password="Test-only-123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="明确登记的测试课程",
            teacher=self.teacher,
            is_active=False,
        )
        self.other_course = Course.objects.create(
            subject=self.subject,
            title="另一个测试课程",
            teacher=self.teacher,
            is_active=False,
        )

    def command_options(self, **overrides):
        options = {
            "batch_code": "TEST-MANUAL-20260722-A",
            "purpose": TestDataBatch.Purpose.ACCEPTANCE_TESTING,
            "source_kind": TestDataBatch.SourceKind.HISTORICAL_MANUAL,
            "description": "只用于 P0 批次登记验收，不得进入正式统计、训练或科研结论。",
            "target": [f"courses.Course:{self.course.pk}"],
            "actor": self.super_admin.username,
            "confirm": "REGISTER_TEST_DATA",
            "stdout": StringIO(),
        }
        options.update(overrides)
        return options

    def test_dry_run_validates_targets_without_writing(self):
        output = StringIO()
        call_command(
            "register_test_data_batch",
            **self.command_options(dry_run=True, confirm="", stdout=output),
        )

        self.assertIn("[DRY-RUN]", output.getvalue())
        self.assertIn("courses.course", output.getvalue())
        self.assertFalse(TestDataBatch.objects.exists())
        self.assertFalse(TestDataObjectMarker.objects.exists())

    def test_registration_is_explicit_immutable_and_idempotent(self):
        call_command("register_test_data_batch", **self.command_options())

        batch = TestDataBatch.objects.get(batch_code="TEST-MANUAL-20260722-A")
        marker = TestDataObjectMarker.objects.get(batch=batch)
        self.assertEqual(batch.target_count, 1)
        self.assertEqual(len(batch.manifest_hash), 64)
        self.assertEqual(marker.app_label, "courses")
        self.assertEqual(marker.model_name, "course")
        self.assertEqual(marker.object_pk, str(self.course.pk))
        self.assertTrue(is_explicit_test_data_object(self.course))
        self.assertFalse(is_explicit_test_data_object(self.other_course))

        repeat_output = StringIO()
        call_command(
            "register_test_data_batch",
            **self.command_options(stdout=repeat_output),
        )
        self.assertIn("[UNCHANGED]", repeat_output.getvalue())
        self.assertEqual(TestDataBatch.objects.count(), 1)
        self.assertEqual(TestDataObjectMarker.objects.count(), 1)

        batch.description = "试图覆盖不可变清单"
        with self.assertRaises(ValidationError):
            batch.save()
        marker.object_label = "试图改写对象名称快照"
        with self.assertRaises(ValidationError):
            marker.save()

    def test_registration_requires_confirmation_and_super_admin(self):
        with self.assertRaises(CommandError):
            call_command(
                "register_test_data_batch",
                **self.command_options(confirm=""),
            )
        with self.assertRaises(CommandError):
            call_command(
                "register_test_data_batch",
                **self.command_options(actor=self.teacher.username),
            )
        self.assertFalse(TestDataBatch.objects.exists())

    def test_same_code_cannot_be_reused_for_a_different_manifest(self):
        call_command("register_test_data_batch", **self.command_options())

        with self.assertRaises(CommandError):
            call_command(
                "register_test_data_batch",
                **self.command_options(
                    target=[f"courses.Course:{self.other_course.pk}"],
                ),
            )
        self.assertEqual(TestDataBatch.objects.count(), 1)
        self.assertEqual(TestDataObjectMarker.objects.count(), 1)

    def test_personal_or_unapproved_model_cannot_be_registered(self):
        with self.assertRaises(CommandError):
            call_command(
                "register_test_data_batch",
                **self.command_options(target=[f"accounts.User:{self.teacher.pk}"]),
            )
        self.assertFalse(TestDataBatch.objects.exists())

    def test_formal_queryset_helpers_exclude_or_block_active_markers(self):
        call_command("register_test_data_batch", **self.command_options())

        filtered_ids = set(
            exclude_explicit_test_data_objects(Course.objects.all()).values_list(
                "id", flat=True
            )
        )
        self.assertNotIn(self.course.id, filtered_ids)
        self.assertIn(self.other_course.id, filtered_ids)
        with self.assertRaises(ValidationError):
            assert_no_explicit_test_data_objects(
                Course.objects.filter(id__in=[self.course.id, self.other_course.id]),
                usage="正式训练",
            )
        assert_no_explicit_test_data_objects(
            Course.objects.filter(pk=self.other_course.pk),
            usage="正式训练",
        )

    def test_mistaken_marker_can_be_revoked_without_deleting_audit_row(self):
        call_command("register_test_data_batch", **self.command_options())
        marker = TestDataObjectMarker.objects.get()

        dry_run_output = StringIO()
        call_command(
            "revoke_test_data_marker",
            target=f"courses.Course:{self.course.pk}",
            actor=self.super_admin.username,
            reason="经来源台账复核，该课程属于正式教学数据，原测试标记错误。",
            dry_run=True,
            stdout=dry_run_output,
        )
        self.assertIn("[DRY-RUN]", dry_run_output.getvalue())
        marker.refresh_from_db()
        self.assertTrue(marker.is_active)

        with self.assertRaises(CommandError):
            call_command(
                "revoke_test_data_marker",
                target=f"courses.Course:{self.course.pk}",
                actor=self.super_admin.username,
                reason="经来源台账复核，该课程属于正式教学数据，原测试标记错误。",
                stdout=StringIO(),
            )
        with self.assertRaises(CommandError):
            call_command(
                "revoke_test_data_marker",
                target=f"courses.Course:{self.course.pk}",
                actor=self.teacher.username,
                reason="经来源台账复核，该课程属于正式教学数据，原测试标记错误。",
                confirm="REVOKE_TEST_DATA_MARKER",
                stdout=StringIO(),
            )
        marker.refresh_from_db()
        self.assertTrue(marker.is_active)

        revoke_output = StringIO()
        call_command(
            "revoke_test_data_marker",
            target=f"courses.Course:{self.course.pk}",
            actor=self.super_admin.username,
            reason="经来源台账复核，该课程属于正式教学数据，原测试标记错误。",
            confirm="REVOKE_TEST_DATA_MARKER",
            stdout=revoke_output,
        )
        self.assertIn("[REVOKED]", revoke_output.getvalue())
        marker.refresh_from_db()
        self.assertFalse(marker.is_active)
        self.assertEqual(marker.revoked_by, self.super_admin)
        self.assertIsNotNone(marker.revoked_at)
        self.assertTrue(marker.revocation_reason)
        self.assertFalse(is_explicit_test_data_object(self.course))
        self.assertIn(
            self.course.id,
            set(
                exclude_explicit_test_data_objects(Course.objects.all()).values_list(
                    "id", flat=True
                )
            ),
        )
        self.assertEqual(TestDataObjectMarker.objects.count(), 1)

        repeated_output = StringIO()
        call_command(
            "revoke_test_data_marker",
            target=f"courses.Course:{self.course.pk}",
            actor=self.super_admin.username,
            reason="重复撤销检查仍保留最初撤销审计记录，不再产生第二条记录。",
            confirm="REVOKE_TEST_DATA_MARKER",
            stdout=repeated_output,
        )
        self.assertIn("[UNCHANGED]", repeated_output.getvalue())
        self.assertEqual(TestDataObjectMarker.objects.count(), 1)
