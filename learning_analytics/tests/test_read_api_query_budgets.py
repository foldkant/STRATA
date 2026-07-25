from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import ClassroomSession, Course, CourseClass, Lesson, Subject
from school.models import ClassGroup, School, TeachingAssignment


class ReadApiQueryBudgetTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="读取性能测试学校", code="READ-BUDGET")
        self.teacher = User.objects.create_user(
            username="read_budget_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="七年级一班",
            grade="七年级",
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT-READ-BUDGET",
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与编码",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lessons = [
            Lesson.objects.create(
                course=self.course,
                title=f"第 {index + 1} 课时",
                sort_order=index + 1,
                is_active=True,
            )
            for index in range(4)
        ]
        ClassroomSession.objects.bulk_create(
            [
                ClassroomSession(
                    school=self.school,
                    teacher=self.teacher,
                    course=self.course,
                    lesson=self.lessons[index % len(self.lessons)],
                    class_group=self.class_group,
                    title=f"课堂 {index + 1}",
                )
                for index in range(25)
            ]
        )
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    def test_classroom_directory_stays_within_query_budget(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/api/v1/teacher/classroom/sessions/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]["results"]), 20)
        self.assertLessEqual(
            len(captured),
            8,
            f"课堂目录查询数超出预算：{len(captured)}",
        )
