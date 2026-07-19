from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import (
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    Subject,
)
from learning_analytics.models import (
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import reconcile_v1_v2_events
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class EvaluationFactTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="评价事实测试学校", code="EVAL-FACT")
        self.subject = Subject.objects.create(
            school=self.school, name="信息科技", code="IT"
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.teacher = User.objects.create_user(
            username="eval_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.students = []
        self.profiles = []
        for index in range(1, 4):
            student = User.objects.create_user(
                username=f"eval_student{index}",
                password="123456",
                role=User.Role.STUDENT,
                school=self.school,
                display_name=f"学生{index}",
            )
            profile = StudentProfile.objects.create(
                user=student,
                class_group=self.class_group,
                is_first_use=False,
            )
            self.students.append(student)
            self.profiles.append(profile)
        self.course = Course.objects.create(
            subject=self.subject,
            title="评价事实课程",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(
            course=self.course, title="评价事实课时", is_active=True
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="评价事实课堂",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        self.config = ClassroomEvaluationConfig.objects.create(
            course=self.course,
            enable_self=True,
            enable_peer=True,
            enable_teacher=True,
            self_criteria=[
                {
                    "id": "self-process",
                    "title": "学习过程",
                    "description": "反思学习过程",
                    "sort_order": 10,
                }
            ],
            peer_criteria=[
                {
                    "id": "peer-collaboration",
                    "title": "协作贡献",
                    "description": "评价同伴贡献",
                    "sort_order": 10,
                }
            ],
            teacher_criteria=[
                {
                    "id": "teacher-outcome",
                    "title": "任务达成",
                    "description": "评价任务成果",
                    "sort_order": 10,
                }
            ],
            created_by=self.teacher,
        )
        collaboration = ClassroomGroupCollaboration.objects.create(
            session=self.session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.OPEN,
            created_by=self.teacher,
            opened_at=timezone.now(),
        )
        group = ClassroomGroup.objects.create(
            collaboration=collaboration,
            group_no=1,
            name="第1组",
        )
        for student, profile in zip(self.students, self.profiles, strict=True):
            ClassroomGroupMember.objects.create(
                collaboration=collaboration,
                group=group,
                student=student,
                student_profile=profile,
            )
        self.group = group
        self.client = APIClient()

    def enable_evaluation(self):
        self.client.force_authenticate(self.teacher)
        return self.client.patch(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/",
            {"evaluation_enabled": True},
            format="json",
        )

    def submit_student(self, student, evaluation_type, target=None, rating=4):
        self.client.force_authenticate(student)
        criterion_id = (
            "self-process" if evaluation_type == "self" else "peer-collaboration"
        )
        payload = {
            "evaluation_type": evaluation_type,
            "ratings": {criterion_id: rating},
            "comment": "评价正文只保留在业务表",
        }
        if target:
            payload["target"] = target.id
        return self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/evaluation/submit/",
            payload,
            format="json",
        )

    def test_classroom_evaluation_is_frozen_and_submissions_are_versioned(self):
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.session.refresh_from_db()
        frozen_version = self.session.evaluation_config_version
        self.assertIsNotNone(frozen_version)
        self.assertEqual(frozen_version.version_no, 1)
        self.assertEqual(
            LearningEventV2.objects.filter(
                event_name="content.released",
                legacy_event__metadata__action="classroom_evaluation_released",
            ).count(),
            3,
        )
        self.assertEqual(LearningOpportunity.objects.count(), 9)
        self.assertTrue(
            all(not item.required for item in LearningOpportunity.objects.all())
        )

        self_response = self.submit_student(self.students[0], "self", rating=4)
        peer_response = self.submit_student(
            self.students[0], "peer", target=self.students[1], rating=5
        )
        self.client.force_authenticate(self.teacher)
        teacher_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/teacher-submit/",
            {
                "target": self.students[0].id,
                "ratings": {"teacher-outcome": 3},
                "comment": "教师评价正文",
            },
            format="json",
        )
        revised_self = self.submit_student(self.students[0], "self", rating=5)
        self.assertEqual(self_response.status_code, 200, self_response.data)
        self.assertEqual(peer_response.status_code, 200, peer_response.data)
        self.assertEqual(teacher_response.status_code, 200, teacher_response.data)
        self.assertEqual(revised_self.status_code, 200, revised_self.data)

        self_submissions = list(
            ClassroomEvaluationSubmission.objects.filter(
                evaluation_type="self", evaluator=self.students[0]
            ).order_by("submission_version")
        )
        self.assertEqual([item.submission_version for item in self_submissions], [1, 2])
        self.assertEqual(self_submissions[1].supersedes, self_submissions[0])
        self.assertEqual(self_submissions[0].evaluation_version, frozen_version)
        self.assertNotEqual(
            self_submissions[0].analytics_attempt_id,
            self_submissions[1].analytics_attempt_id,
        )

        events = LearningEventV2.objects.filter(event_name="evaluation.rating.submitted")
        self.assertEqual(events.count(), 4)
        self.assertFalse(events.filter(payload__has_key="comment").exists())
        peer_event = events.get(payload__rater_role="peer")
        self.assertEqual(peer_event.actor, self.students[0])
        self.assertEqual(peer_event.target_student, self.students[1])
        self.assertEqual(peer_event.source, "server")
        self.assertEqual(peer_event.opportunity_record.student, self.students[1])
        self.assertEqual(
            peer_event.payload["criterion_ratings"],
            [{"criterion_id": "peer-collaboration", "rating": 5}],
        )

        self.config.self_criteria = [
            {
                "id": "new-self-item",
                "title": "新评价项",
                "description": "只用于后续课堂",
                "sort_order": 10,
            }
        ]
        self.config.save(update_fields=["self_criteria", "updated_at"])
        self.client.force_authenticate(self.teacher)
        saved = self.client.post(
            f"/api/v1/teacher/courses/{self.course.id}/evaluation/",
            {
                "enable_self": True,
                "enable_peer": True,
                "enable_teacher": True,
                "self_criteria": self.config.self_criteria,
                "peer_criteria": self.config.peer_criteria,
                "teacher_criteria": self.config.teacher_criteria,
            },
            format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(
            ClassroomEvaluationConfigVersion.objects.filter(course=self.course).count(),
            2,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.evaluation_config_version, frozen_version)
        still_frozen = self.submit_student(self.students[1], "self", rating=4)
        self.assertEqual(still_frozen.status_code, 200, still_frozen.data)

        self.client.force_authenticate(self.teacher)
        closed = self.client.patch(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/",
            {"evaluation_enabled": False},
            format="json",
        )
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertTrue(
            LearningOpportunityTransitionFact.objects.filter(state="withdrawn").exists()
        )
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_student_batch_cannot_forge_peer_rating_for_another_student(self):
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.session.refresh_from_db()
        version = self.session.evaluation_config_version
        opportunity = LearningOpportunity.objects.get(
            student=self.students[1],
            object_id=f"classroom-evaluation:{self.session.id}:peer",
        )
        self.client.force_authenticate(self.students[0])
        response = self.client.post(
            "/api/v1/learning-events/batch/",
            {
                "events": [
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_name": "evaluation.rating.submitted",
                        "schema_version": "1.0",
                        "target_student_id": self.students[1].id,
                        "class_id": self.class_group.id,
                        "subject_id": self.subject.id,
                        "course_id": self.course.id,
                        "session_id": self.session.id,
                        "object_type": "evaluation_standard",
                        "object_id": f"classroom-evaluation:{self.session.id}:peer",
                        "object_version": version.config_hash,
                        "opportunity_id": str(opportunity.opportunity_id),
                        "client_occurred_at": timezone.now().isoformat(),
                        "payload": {
                            "evaluation_version": (
                                f"course:{self.course.id}:v{version.version_no}:"
                                f"{version.config_hash[:12]}"
                            ),
                            "criterion_ratings": [
                                {
                                    "criterion_id": "peer-collaboration",
                                    "rating": 5,
                                }
                            ],
                            "rater_role": "peer",
                        },
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data["data"]["results"][0]
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error_code"], "target_forbidden")
        self.assertFalse(
            LearningEventV2.objects.filter(
                event_name="evaluation.rating.submitted"
            ).exists()
        )
