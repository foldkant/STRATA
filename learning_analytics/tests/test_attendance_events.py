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


class AttendanceEventTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="签到测试学校", code="ATTENDANCE")
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT-ATTENDANCE",
        )
        self.teacher = User.objects.create_user(
            username="attendance_teacher",
            password="Teacher123!",
            display_name="签到教师",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.course = Course.objects.create(
            title="签到课程",
            teacher=self.teacher,
            subject=self.subject,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(title="签到课时", course=self.course)
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="签到课堂",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        self.students = []
        for index in range(1, 5):
            student = User.objects.create_user(
                username=f"attendance_student{index}",
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

    def open_attendance(self) -> ClassroomActivity:
        response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/command/",
            {"command": "sign_in"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return ClassroomActivity.objects.get(pk=response.data["data"]["id"])

    def student_sign(self, activity: ClassroomActivity, student: User):
        self.client.force_authenticate(student)
        return self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/activities/{activity.id}/response/",
            {"response_type": "sign_in"},
            format="json",
        )

    def teacher_mark(
        self, activity: ClassroomActivity, student: User, status: str, note: str = ""
    ):
        self.client.force_authenticate(self.teacher)
        return self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/attendance/{activity.id}/mark/",
            {"student_id": student.id, "status": status, "note": note},
            format="json",
        )

    def test_attendance_uses_opportunity_and_append_only_status_revisions(self):
        activity = self.open_attendance()
        release = LearningEventV2.objects.get(
            event_name="content.released",
            payload__content_type="attendance",
        )
        self.assertEqual(release.object_id, str(activity.id))
        self.assertEqual(
            LearningOpportunity.objects.filter(content_type="attendance").count(),
            4,
        )
        student_opportunity = LearningOpportunity.objects.get(
            student=self.students[0],
            content_type="attendance",
        )
        with self.assertRaises(EventWriteError) as malicious:
            record_learning_event(
                actor=self.students[0],
                target_student=self.students[0],
                event_name="attendance.recorded",
                payload={
                    "attendance_status": "absent",
                    "recorded_by": "teacher",
                    "revision_no": 1,
                },
                legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
                class_group=self.class_group,
                subject=self.subject,
                course=self.course,
                lesson=self.lesson,
                classroom_session=self.session,
                object_type="classroom_activity",
                object_id=activity.id,
                object_version=student_opportunity.object_version,
                opportunity_id=student_opportunity.opportunity_id,
            )
        self.assertEqual(
            malicious.exception.code, "attendance_student_payload_forbidden"
        )

        first = self.student_sign(activity, self.students[0])
        duplicate = self.student_sign(activity, self.students[0])
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        first_event = LearningEventV2.objects.get(event_name="attendance.recorded")
        self.assertEqual(first_event.actor, self.students[0])
        self.assertEqual(first_event.target_student, self.students[0])
        self.assertEqual(first_event.payload["attendance_status"], "signed")
        self.assertEqual(first_event.payload["recorded_by"], "student")
        self.assertEqual(first_event.payload["revision_no"], 1)

        revised = self.teacher_mark(
            activity,
            self.students[0],
            "late",
            "进入教室时间由教师核实",
        )
        leave = self.teacher_mark(activity, self.students[1], "leave", "已提交请假说明")
        self.assertEqual(revised.status_code, 200, revised.data)
        self.assertEqual(leave.status_code, 200, leave.data)
        events = list(
            LearningEventV2.objects.filter(
                event_name="attendance.recorded",
                target_student=self.students[0],
            ).order_by("client_occurred_at", "event_id")
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].actor, self.teacher)
        self.assertEqual(events[1].payload["attendance_status"], "late")
        self.assertEqual(events[1].payload["recorded_by"], "teacher")
        self.assertEqual(events[1].payload["revision_no"], 2)
        self.assertEqual(
            events[1].payload["supersedes_event_id"], str(events[0].event_id)
        )
        self.assertTrue(all("note" not in event.payload for event in events))
        latest_legacy = (
            LearningEvent.objects.filter(
                actor=self.students[0],
                metadata__action="classroom_activity_response",
                metadata__command="sign_in",
            )
            .order_by("-occurred_at", "-id")
            .first()
        )
        self.assertEqual(latest_legacy.metadata["note"], "进入教室时间由教师核实")

        opportunity = LearningOpportunity.objects.get(
            student=self.students[0],
            content_type="attendance",
        )
        self.assertEqual(
            opportunity.transition_facts.filter(state="submitted").count(),
            2,
        )
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_nonresponse_is_withdrawn_not_automatically_labeled_absent(self):
        activity = self.open_attendance()
        self.assertEqual(self.student_sign(activity, self.students[0]).status_code, 200)
        self.assertEqual(
            self.teacher_mark(activity, self.students[1], "late").status_code,
            200,
        )
        self.assertEqual(
            self.teacher_mark(activity, self.students[2], "absent").status_code,
            200,
        )

        self.client.force_authenticate(self.teacher)
        closed = self.client.post(
            f"/api/v1/teacher/classroom/activities/{activity.id}/close/",
            {},
            format="json",
        )
        self.assertEqual(closed.status_code, 200, closed.data)
        student_after_close = self.student_sign(activity, self.students[3])
        self.assertEqual(student_after_close.status_code, 404, student_after_close.data)

        # 教师可在课堂结束前核实已关闭签到，但这里保留第 4 位学生为未知未响应。
        self.client.force_authenticate(self.teacher)
        finished = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/finish/",
            {},
            format="json",
        )
        self.assertEqual(finished.status_code, 200, finished.data)
        unknown_student = self.students[3]
        self.assertFalse(
            LearningEventV2.objects.filter(
                event_name="attendance.recorded",
                target_student=unknown_student,
            ).exists()
        )
        unknown_opportunity = LearningOpportunity.objects.get(
            student=unknown_student,
            content_type="attendance",
        )
        self.assertTrue(
            unknown_opportunity.transition_facts.filter(state="withdrawn").exists()
        )
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                opportunity__content_type="attendance",
                state="withdrawn",
            ).count(),
            1,
        )
        after_finish = self.teacher_mark(activity, unknown_student, "absent")
        self.assertEqual(after_finish.status_code, 400, after_finish.data)

        self.client.force_authenticate(self.teacher)
        deletion = self.client.delete(
            f"/api/v1/teacher/classroom/activities/{activity.id}/"
        )
        self.assertEqual(deletion.status_code, 409, deletion.data)

    @override_settings(LEARNING_EVENT_WRITE_MODE="v1_only")
    def test_v1_only_mode_preserves_attendance_business_flow(self):
        activity = self.open_attendance()
        self.assertEqual(LearningOpportunity.objects.count(), 0)

        signed = self.student_sign(activity, self.students[0])
        revised = self.teacher_mark(activity, self.students[0], "late", "回滚模式")
        self.assertEqual(signed.status_code, 200, signed.data)
        self.assertEqual(revised.status_code, 200, revised.data)
        self.assertFalse(
            LearningEventV2.objects.filter(event_name="attendance.recorded").exists()
        )
        rows = LearningEvent.objects.filter(
            actor=self.students[0],
            metadata__action="classroom_activity_response",
            metadata__command="sign_in",
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            rows.order_by("-id").first().metadata["attendance_status"], "late"
        )
