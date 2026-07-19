from __future__ import annotations

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import (
    ClassroomActivity,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    Subject,
)
from learning.models import LearningEvent
from learning_analytics.models import (
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    reconcile_v1_v2_events,
    record_learning_event,
)
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class ClassroomInteractionEventTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="互动测试学校", code="INTERACTION")
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT-INTERACTION",
        )
        self.teacher = User.objects.create_user(
            username="interaction_teacher",
            password="Teacher123!",
            display_name="互动教师",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.course = Course.objects.create(
            title="互动课程",
            teacher=self.teacher,
            subject=self.subject,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(title="互动课时", course=self.course)
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="互动课堂",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        self.students = []
        for index in range(1, 5):
            student = User.objects.create_user(
                username=f"interaction_student{index}",
                password="123456",
                display_name=f"学生{index}",
                role=User.Role.STUDENT,
                school=self.school,
            )
            StudentProfile.objects.create(
                user=student,
                class_group=self.class_group,
                is_first_use=False,
                onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
            )
            self.students.append(student)
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    def run_command(self, command: str, **values) -> ClassroomActivity:
        response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/command/",
            {"command": command, **values},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return ClassroomActivity.objects.get(pk=response.data["data"]["id"])

    def quick_answer(self, activity: ClassroomActivity, student: User):
        self.client.force_authenticate(student)
        return self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/activities/{activity.id}/response/",
            {"response_type": "quick_answer"},
            format="json",
        )

    def test_quick_answer_records_server_rank_and_withdraws_nonresponders(self):
        activity = self.run_command("quick_answer")
        release = LearningEventV2.objects.get(
            event_name="content.released",
            schema_version="1.3",
            payload__content_type="interaction",
        )
        self.assertFalse(release.payload["required"])
        self.assertEqual(
            LearningOpportunity.objects.filter(content_type="interaction").count(),
            4,
        )

        first = self.quick_answer(activity, self.students[0])
        duplicate = self.quick_answer(activity, self.students[0])
        second = self.quick_answer(activity, self.students[1])
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        self.assertEqual(second.status_code, 200, second.data)
        events = list(
            LearningEventV2.objects.filter(
                event_name="quick_answer.responded"
            ).order_by("payload__response_rank")
        )
        self.assertEqual(len(events), 2)
        self.assertEqual([event.payload["response_rank"] for event in events], [1, 2])
        self.assertTrue(all(event.source == "server" for event in events))
        self.assertTrue(
            all(event.payload["response_latency_ms"] >= 0 for event in events)
        )
        self.assertTrue(all("content" not in event.payload for event in events))

        self.client.force_authenticate(self.teacher)
        closed = self.client.post(
            f"/api/v1/teacher/classroom/activities/{activity.id}/close/",
            {},
            format="json",
        )
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                opportunity__content_type="interaction",
                state="submitted",
            ).count(),
            2,
        )
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                opportunity__content_type="interaction",
                state="withdrawn",
            ).count(),
            2,
        )
        for student in self.students[:2]:
            opportunity = LearningOpportunity.objects.get(
                student=student,
                content_type="interaction",
            )
            self.assertFalse(
                opportunity.transition_facts.filter(state="withdrawn").exists()
            )
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_random_call_is_teacher_selection_fact_not_student_completion(self):
        first_activity = self.run_command(
            "random_pick",
            picked_user_id=self.students[0].id,
        )
        first = LearningEventV2.objects.get(event_name="random_call.selected")
        self.assertEqual(first.actor, self.teacher)
        self.assertEqual(first.target_student, self.students[0])
        self.assertEqual(first.source, "server")
        self.assertEqual(first.payload["selection_method"], "client_draw")
        self.assertEqual(first.payload["eligible_student_count"], 4)
        self.assertEqual(first.payload["selection_sequence"], 1)
        self.assertEqual(first.payload["prior_selection_count"], 0)
        self.assertFalse(LearningOpportunity.objects.exists())
        self.assertNotIn("current_layer", first.payload)

        self.client.force_authenticate(self.teacher)
        second_activity = self.run_command(
            "random_pick",
            picked_user_id=self.students[0].id,
        )
        self.assertNotEqual(first_activity.id, second_activity.id)
        second = (
            LearningEventV2.objects.filter(
                event_name="random_call.selected",
                target_student=self.students[0],
            )
            .order_by("-client_occurred_at", "-event_id")
            .first()
        )
        self.assertEqual(second.payload["selection_sequence"], 2)
        self.assertEqual(second.payload["prior_selection_count"], 1)

        with self.assertRaises(EventWriteError) as forged:
            record_learning_event(
                actor=self.teacher,
                target_student=self.students[0],
                event_name="random_call.selected",
                payload={
                    "selection_method": "client_draw",
                    "eligible_student_count": 4,
                    "selection_sequence": 99,
                    "prior_selection_count": 98,
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=self.class_group,
                subject=self.subject,
                course=self.course,
                lesson=self.lesson,
                classroom_session=self.session,
                object_type="classroom_activity",
                object_id=second_activity.id,
                object_version="forged",
            )
        self.assertEqual(forged.exception.code, "source_forbidden")
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_finishing_classroom_withdraws_unanswered_quick_answer_opportunities(self):
        activity = self.run_command("quick_answer")
        self.assertEqual(self.quick_answer(activity, self.students[0]).status_code, 200)

        self.client.force_authenticate(self.teacher)
        finished = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/finish/",
            {},
            format="json",
        )
        self.assertEqual(finished.status_code, 200, finished.data)
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                opportunity__content_type="interaction",
                state="withdrawn",
            ).count(),
            3,
        )
        answered = LearningOpportunity.objects.get(
            student=self.students[0], content_type="interaction"
        )
        self.assertFalse(answered.transition_facts.filter(state="withdrawn").exists())

    @override_settings(LEARNING_EVENT_WRITE_MODE="v1_only")
    def test_v1_only_mode_preserves_quick_answer_and_random_call(self):
        quick = self.run_command("quick_answer")
        response = self.quick_answer(quick, self.students[0])
        self.assertEqual(response.status_code, 200, response.data)

        self.client.force_authenticate(self.teacher)
        random_activity = self.run_command(
            "random_pick",
            picked_user_id=self.students[1].id,
        )
        self.assertFalse(LearningOpportunity.objects.exists())
        self.assertFalse(
            LearningEventV2.objects.filter(
                event_name__in={"quick_answer.responded", "random_call.selected"}
            ).exists()
        )
        self.assertTrue(
            LearningEvent.objects.filter(
                actor=self.students[0],
                object_id=str(quick.id),
                metadata__command="quick_answer",
            ).exists()
        )
        self.assertTrue(
            LearningEvent.objects.filter(
                actor=self.students[1],
                object_id=str(random_activity.id),
                metadata__action="random_call_selected",
            ).exists()
        )
