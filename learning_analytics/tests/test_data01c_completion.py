from __future__ import annotations

from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
    Subject,
)
from learning.models import LearningEvent
from learning_analytics.models import LearningEventV2
from learning_analytics.services.legacy_backfill import (
    deterministic_backfill_event_id,
)
from learning_analytics.services.operational_events import (
    record_classroom_control_executed,
    record_lesson_entered,
    record_lesson_step_completed,
    record_lesson_step_entered,
    record_resource_center_opened,
)
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class Data01CCompletionTests(TestCase):
    def setUp(self):
        sync_event_schema_definitions()
        self.school = School.objects.create(name="DATA-01C School", code="DATA01C")
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="Class 1", grade="Grade 1"
        )
        self.subject = Subject.objects.create(
            school=self.school, name="Computing", code="DATA01C-COMPUTING"
        )
        self.teacher = User.objects.create_user(
            username="data01c_teacher",
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
            username="data01c_student",
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
        self.course = Course.objects.create(
            subject=self.subject,
            title="Data course",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(
            course=self.course, title="Data lesson", is_active=True
        )
        self.step = LessonStep.objects.create(
            lesson=self.lesson,
            title="Data step",
            step_type=LessonStep.StepType.RESOURCE,
            status=LessonStep.Status.READY,
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="Data classroom",
            status=ClassroomSession.Status.RUNNING,
            current_step=self.step,
            current_step_status=ClassroomSession.StepStatus.OPEN,
        )
        self.resource = Resource.objects.create(
            title="Free browsing resource",
            owner=self.teacher,
            subject=self.subject,
            visibility=Resource.Visibility.SCHOOL,
            publish_status=Resource.PublishStatus.PUBLISHED,
            resource_type=Resource.ResourceType.ARTICLE,
        )

    def test_remaining_operational_writes_are_dual_written(self):
        record_resource_center_opened(
            resource=self.resource,
            student=self.student,
            profile=self.profile,
        )
        record_lesson_entered(
            student=self.student, profile=self.profile, lesson=self.lesson
        )
        record_lesson_step_entered(
            student=self.student, profile=self.profile, step=self.step
        )
        record_lesson_step_completed(
            student=self.student,
            profile=self.profile,
            step=self.step,
            duration_ms=1200,
        )
        record_classroom_control_executed(
            teacher=self.teacher,
            session=self.session,
            action="step_opened",
            step=self.step,
        )

        self.assertEqual(LearningEvent.objects.count(), 5)
        self.assertEqual(LearningEventV2.objects.count(), 5)
        self.assertEqual(
            set(LearningEventV2.objects.values_list("event_name", flat=True)),
            {
                "resource.center.opened",
                "lesson.entered",
                "lesson.step.entered",
                "lesson.step.completed",
                "classroom.control.executed",
            },
        )
        resource_event = LearningEventV2.objects.get(
            event_name="resource.center.opened"
        )
        self.assertIsNone(resource_event.opportunity_id)
        self.assertEqual(resource_event.target_student, self.student)
        self.assertNotIn("title", resource_event.payload)

    def test_api_production_modules_have_no_direct_v1_create(self):
        api_root = Path(settings.BASE_DIR) / "api"
        offenders = []
        for path in api_root.rglob("*.py"):
            if path.name == "tests.py":
                continue
            if "LearningEvent.objects.create(" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(settings.BASE_DIR)))
        self.assertEqual(offenders, [])

    def test_deterministic_backfill_maps_known_event_and_is_idempotent(self):
        legacy = LearningEvent.objects.create(
            actor=self.student,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            event_type=LearningEvent.EventType.LESSON_ENTER,
            object_type="lesson",
            object_id=str(self.lesson.id),
            occurred_at=timezone.now(),
        )
        output = StringIO()
        call_command(
            "backfill_learning_event_v2",
            school=self.school.code,
            batch_size=1,
            stdout=output,
        )
        mapped = LearningEventV2.objects.get(legacy_event=legacy)
        self.assertEqual(mapped.event_name, "lesson.entered")
        self.assertEqual(
            mapped.event_id,
            deterministic_backfill_event_id(legacy.id, "lesson.entered"),
        )
        self.assertIn('"mapped": 1', output.getvalue())

        call_command(
            "backfill_learning_event_v2",
            school=self.school.code,
            batch_size=1,
            stdout=StringIO(),
        )
        self.assertEqual(LearningEventV2.objects.filter(legacy_event=legacy).count(), 1)

    def test_unknown_history_is_quarantined_as_legacy_unmapped(self):
        legacy = LearningEvent.objects.create(
            actor=self.student,
            class_group=self.class_group,
            event_type=LearningEvent.EventType.LOGIN,
            object_type="login",
            occurred_at=timezone.now(),
        )
        dry_output = StringIO()
        call_command(
            "backfill_learning_event_v2",
            school=self.school.code,
            dry_run=True,
            stdout=dry_output,
        )
        self.assertFalse(LearningEventV2.objects.filter(legacy_event=legacy).exists())
        self.assertIn('"unmapped": 1', dry_output.getvalue())

        call_command(
            "backfill_learning_event_v2",
            school=self.school.code,
            stdout=StringIO(),
        )
        unmapped = LearningEventV2.objects.get(legacy_event=legacy)
        self.assertEqual(unmapped.event_name, "legacy.unmapped")
        self.assertEqual(
            unmapped.quality_status, LearningEventV2.QualityStatus.LEGACY_UNMAPPED
        )
        self.assertEqual(
            unmapped.payload["reason_code"], "unsupported_legacy_semantics"
        )
        self.assertFalse(
            LearningEventV2.objects.filter(legacy_event=legacy)
            .exclude(opportunity_id=None)
            .exists()
        )

    def test_resume_skips_earlier_legacy_ids(self):
        first = LearningEvent.objects.create(
            actor=self.student,
            class_group=self.class_group,
            event_type=LearningEvent.EventType.LOGIN,
            occurred_at=timezone.now(),
        )
        second = LearningEvent.objects.create(
            actor=self.student,
            class_group=self.class_group,
            event_type=LearningEvent.EventType.LOGIN,
            occurred_at=timezone.now(),
        )
        call_command(
            "backfill_learning_event_v2",
            school=self.school.code,
            resume=first.id,
            stdout=StringIO(),
        )
        self.assertFalse(LearningEventV2.objects.filter(legacy_event=first).exists())
        self.assertTrue(LearningEventV2.objects.filter(legacy_event=second).exists())
