from __future__ import annotations

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import User
from courses.models import ClassroomEvaluationConfig, Course, Subject
from learning_analytics.evaluation_models import EvaluationPlan, EvaluationStandard
from school.models import School


class LegacyEvaluationMigrationCommandTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="迁移测试学校", code="EVAL-MIGRATION")
        self.subject = Subject.objects.create(school=self.school, name="信息科技", code="IT")
        self.teacher = User.objects.create_user(
            username="migration_teacher",
            password="Test-only-123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="迁移测试课程",
            teacher=self.teacher,
            is_active=True,
        )
        self.config = ClassroomEvaluationConfig.objects.create(
            course=self.course,
            enable_self=True,
            enable_peer=True,
            enable_teacher=True,
            self_criteria=[{"id": "self-1", "title": "个人投入", "description": "按任务材料反思投入情况"}],
            peer_criteria=[{"id": "peer-1", "title": "团队协作", "description": "根据协作过程评价贡献"}],
            teacher_criteria=[{"id": "teacher-1", "title": "任务达成", "description": "根据作品评价任务达成"}],
            created_by=self.teacher,
        )

    def test_dry_run_validates_without_persisting(self):
        output = StringIO()
        call_command(
            "migrate_legacy_evaluation_standards",
            teacher=self.teacher.username,
            course_id=self.course.id,
            dry_run=True,
            stdout=output,
        )
        self.assertIn("[DRY-RUN]", output.getvalue())
        self.assertTrue(ClassroomEvaluationConfig.objects.filter(pk=self.config.pk).exists())
        self.assertFalse(EvaluationPlan.objects.filter(course=self.course).exists())

    def test_delete_requires_explicit_confirmation(self):
        with self.assertRaises(CommandError):
            call_command(
                "migrate_legacy_evaluation_standards",
                course_id=self.course.id,
                delete_legacy=True,
            )

    def test_migrates_complete_drafts_and_deletes_legacy_config(self):
        call_command(
            "migrate_legacy_evaluation_standards",
            course_id=self.course.id,
            delete_legacy=True,
            confirm="DELETE_LEGACY_EVALUATION_DATA",
            stdout=StringIO(),
        )

        plan = EvaluationPlan.objects.get(course=self.course)
        standard = EvaluationStandard.objects.get(plan=plan)
        self.assertEqual(plan.review_status, "draft")
        self.assertEqual(standard.review_status, "draft")
        self.assertEqual(plan.content_version, f"legacy-evaluation-config-{self.config.pk}-v1")
        self.assertEqual(len(standard.criteria), 3)
        self.assertFalse(ClassroomEvaluationConfig.objects.filter(pk=self.config.pk).exists())
