from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from accounts.models import User
from api.renderers import StudentPrivacyJSONRenderer
from courses.models import (
    ClassroomActivity,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Subject,
)
from learning_analytics.privacy import find_student_privacy_violations
from realtime.events import publish_chat_event
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class StudentPrivacyRendererTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="隐私渲染学校", code="PRIVACY-RENDER")
        self.student = User.objects.create_user(
            username="privacy_renderer_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.teacher = User.objects.create_user(
            username="privacy_renderer_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )

    def render_for(self, user, data):
        response = Response(data)
        rendered = StudentPrivacyJSONRenderer().render(
            data,
            renderer_context={
                "request": SimpleNamespace(user=user),
                "response": response,
            },
        )
        return response, json.loads(rendered)

    def test_student_response_is_blocked_at_final_renderer(self):
        response, rendered = self.render_for(
            self.student,
            {"data": {"nested": {"current_layer": "A"}}},
        )
        self.assertEqual(response.status_code, 500)
        self.assertIsNone(rendered["data"])
        self.assertFalse(find_student_privacy_violations(rendered))

    def test_teacher_response_keeps_private_inference_fields(self):
        response, rendered = self.render_for(
            self.teacher,
            {"data": {"nested": {"current_layer": "A"}}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(rendered["data"]["nested"]["current_layer"], "A")

    def test_capability_style_group_name_is_blocked_for_students(self):
        response, _rendered = self.render_for(
            self.student,
            {"data": {"group": {"name": "A层第1组"}}},
        )
        self.assertEqual(response.status_code, 500)


class StudentRealtimePrivacyTests(TestCase):
    def test_hidden_payload_only_reaches_teacher_private_group(self):
        sent = []
        layer = SimpleNamespace(group_send=object())

        def async_adapter(_callable):
            return lambda group, event: sent.append((group, event))

        with (
            patch("realtime.events.get_channel_layer", return_value=layer),
            patch("realtime.events.async_to_sync", side_effect=async_adapter),
        ):
            publish_chat_event(
                [
                    "classroom_session_1",
                    "classroom_teacher_1",
                    "classroom_user_1_3",
                ],
                {"type": "unsafe.test", "current_layer": "A"},
            )

        self.assertEqual([group for group, _event in sent], ["classroom_teacher_1"])

    def test_safe_payload_reaches_all_requested_groups(self):
        sent = []
        layer = SimpleNamespace(group_send=object())

        def async_adapter(_callable):
            return lambda group, event: sent.append((group, event))

        with (
            patch("realtime.events.get_channel_layer", return_value=layer),
            patch("realtime.events.async_to_sync", side_effect=async_adapter),
        ):
            publish_chat_event(
                ["classroom_session_1", "classroom_user_1_3"],
                {"type": "chat.settings.updated", "session_id": 1},
            )

        self.assertEqual(len(sent), 2)


class StudentRestSurfacePrivacyTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="隐私接口学校", code="PRIVACY-REST")
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="PRIVACY-IT",
        )
        self.teacher = User.objects.create_user(
            username="privacy_rest_teacher",
            password="Teacher123!",
            display_name="隐私教师",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.student = User.objects.create_user(
            username="privacy_rest_student",
            password="123456",
            display_name="隐私学生",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            current_layer=StudentProfile.Layer.A,
            current_group_no=1,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
            password_updated_at=timezone.now(),
            class_selected_at=timezone.now(),
            pretest_completed_at=timezone.now(),
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
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="数据编码",
            is_active=True,
        )
        self.step = LessonStep.objects.create(
            lesson=self.lesson,
            title="分层练习",
            status=LessonStep.Status.READY,
            target_layer=LessonStep.TargetLayer.A,
            question_items=[
                {
                    "id": "privacy-question-a",
                    "question_type": "single",
                    "stem": "二进制 10 对应十进制几？",
                    "options": ["1", "2"],
                    "answer": ["2"],
                    "score": 2,
                    "target_layer": "A",
                    "use_layer_scores": True,
                    "layer_scores": {"A": 4, "B": 3, "C": 2},
                }
            ],
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="数据编码课堂",
            status=ClassroomSession.Status.RUNNING,
            current_step=self.step,
            current_step_status=ClassroomSession.StepStatus.OPEN,
            started_at=timezone.now(),
        )
        ClassroomActivity.objects.create(
            session=self.session,
            activity_type=ClassroomActivity.ActivityType.QUESTION,
            title="历史随机点名",
            metadata={
                "command": "random_pick",
                "picked_student": {
                    "user_id": self.student.id,
                    "display_name": self.student.display_name,
                    "current_layer": StudentProfile.Layer.A,
                    "current_layer_label": "拓展挑战层",
                },
            },
            status=ClassroomActivity.Status.OPEN,
            opened_at=timezone.now(),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.student)

    def test_primary_student_get_surfaces_share_hidden_field_contract(self):
        cases = [
            ("/api/v1/student/me/", {200}),
            ("/api/v1/student/dashboard/", {200}),
            ("/api/v1/student/profile/", {200}),
            ("/api/v1/student/onboarding/", {200}),
            ("/api/v1/student/onboarding/classes/", {200}),
            ("/api/v1/student/pretests/required/", {200}),
            ("/api/v1/student/resources/", {200}),
            ("/api/v1/student/courses/", {200}),
            (f"/api/v1/student/courses/{self.course.id}/", {200}),
            (f"/api/v1/student/courses/{self.course.id}/lessons/", {200}),
            (f"/api/v1/student/lessons/{self.lesson.id}/workspace/", {403}),
            ("/api/v1/student/classroom/current/", {200}),
            (f"/api/v1/student/classroom/{self.session.id}/", {200}),
            (f"/api/v1/student/classroom/{self.session.id}/chat/", {200}),
            (
                f"/api/v1/student/classroom/{self.session.id}/chat/messages/"
                "?room_type=whole_class",
                {200},
            ),
            (
                f"/api/v1/student/classroom/{self.session.id}/group-collaboration/",
                {200},
            ),
            (f"/api/v1/student/classroom/{self.session.id}/evaluation/", {200}),
            ("/api/v1/student/notices/", {200}),
            ("/api/v1/student/feedback/", {200}),
            ("/api/v1/student/assessments/", {200}),
        ]
        for url, expected_statuses in cases:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(response.status_code, expected_statuses, response.data)
                self.assertFalse(
                    find_student_privacy_violations(response.data),
                    f"学生接口泄漏：{url}",
                )

    def test_student_cannot_open_teacher_private_surface(self):
        response = self.client.get(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/"
        )
        self.assertIn(response.status_code, {403, 405})
