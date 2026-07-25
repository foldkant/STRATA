from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import User
from courses.models import ClassroomSession, Course, LessonStep, Resource
from learning.models import StratificationDecision
from school.models import ClassGroup, TeachingAssignment


class E2EQualityGateSeedTests(TestCase):
    def test_seed_creates_a_running_classroom_with_a_deployed_resource(self):
        with TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            call_command("seed_e2e_quality_gate", verbosity=0)

        session = ClassroomSession.objects.select_related("current_step").get(pk=1)
        resource = Resource.objects.get(pk=1)
        teacher = User.objects.get(username="e2e_teacher")
        self.assertEqual(session.status, ClassroomSession.Status.RUNNING)
        self.assertEqual(
            session.current_step_status,
            ClassroomSession.StepStatus.OPEN,
        )
        self.assertTrue(session.evaluation_enabled)
        self.assertEqual(
            session.current_step.resource_items[0]["id"],
            resource.id,
        )
        self.assertTrue(resource.attachment.name.endswith("e2e-demo.pptx"))
        self.assertTrue(teacher.check_password("E2eSmoke123!"))
        self.assertEqual(
            ClassGroup.objects.filter(teachers=teacher).distinct().count(),
            8,
        )
        self.assertEqual(
            TeachingAssignment.objects.filter(teacher=teacher).count(),
            8,
        )
        self.assertEqual(Course.objects.get(pk=1).course_classes.count(), 8)
        pending = StratificationDecision.objects.get(
            course_id=1,
            status=StratificationDecision.Status.PENDING,
        )
        self.assertEqual(
            pending.decision_kind,
            StratificationDecision.DecisionKind.SUPPORT,
        )
        self.assertEqual(
            pending.support_priority,
            StratificationDecision.SupportPriority.WATCH,
        )

    def test_seed_refuses_to_write_into_a_nonempty_database(self):
        User.objects.create_user(
            username="existing-user",
            password="Existing123!",
            role=User.Role.SUPER_ADMIN,
        )

        with self.assertRaisesMessage(CommandError, "全新的隔离数据库"):
            call_command("seed_e2e_quality_gate", verbosity=0)
