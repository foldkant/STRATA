from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, CourseClass, Subject
from learning.models import StratificationDecision
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class DashboardDecisionCountTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="首页统计测试学校", code="DASHBOARD")
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.teacher = User.objects.create_user(
            username="dashboard_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.other_teacher = User.objects.create_user(
            username="dashboard_other_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.other_teacher,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="教师本人课程",
            teacher=self.teacher,
            is_active=True,
        )
        self.other_course = Course.objects.create(
            subject=self.subject,
            title="同班其他教师课程",
            teacher=self.other_teacher,
            is_active=True,
        )
        CourseClass.objects.create(course=self.course, class_group=self.class_group)
        CourseClass.objects.create(course=self.other_course, class_group=self.class_group)
        self.student = User.objects.create_user(
            username="dashboard_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(user=self.student, class_group=self.class_group)
        self.client = APIClient()

    def decision(self, *, course, kind, rule_version="transparent-rules-v1"):
        return StratificationDecision.objects.create(
            student=self.student,
            class_group=self.class_group,
            subject=self.subject,
            course=course,
            previous_layer="B",
            suggested_layer="A" if kind == StratificationDecision.DecisionKind.CONTENT_BAND else "",
            decision_kind=kind,
            rule_version=rule_version,
            status=StratificationDecision.Status.PENDING,
        )

    def test_teacher_dashboard_only_counts_published_content_band_for_own_course(self):
        self.decision(
            course=self.course,
            kind=StratificationDecision.DecisionKind.CONTENT_BAND,
        )
        self.decision(
            course=self.course,
            kind=StratificationDecision.DecisionKind.SUPPORT,
        )
        self.decision(
            course=self.other_course,
            kind=StratificationDecision.DecisionKind.CONTENT_BAND,
        )
        self.decision(
            course=self.course,
            kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            rule_version="m03-unpublished-candidate",
        )

        self.client.force_authenticate(self.teacher)
        response = self.client.get("/api/v1/teacher/dashboard/")

        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data["data"]
        metrics = {item["label"]: item["value"] for item in payload["metrics"]}
        todos = {item["label"]: item["count"] for item in payload["todo_rows"]}
        self.assertEqual(metrics["待确认教学安排"], 1)
        self.assertEqual(todos["待确认学习内容安排"], 1)
        self.assertEqual(todos["待确认学习支持安排"], 1)
        self.assertNotIn("student_layers", payload["charts"])

    def test_teacher_global_student_list_does_not_filter_or_show_legacy_layer(self):
        self.student.student_profile.current_layer = "A"
        self.student.student_profile.save(update_fields=["current_layer"])
        other_student = User.objects.create_user(
            username="dashboard_student_other",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=other_student,
            class_group=self.class_group,
            current_layer="C",
        )

        self.client.force_authenticate(self.teacher)
        response = self.client.get("/api/v1/teacher/students/?layer=A")

        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["data"]["results"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all("current_layer" not in row for row in rows))
        self.assertTrue(all("current_layer_label" not in row for row in rows))

    def test_super_admin_dashboard_ignores_support_unpublished_and_test_school(self):
        self.decision(
            course=self.course,
            kind=StratificationDecision.DecisionKind.CONTENT_BAND,
        )
        self.decision(
            course=self.course,
            kind=StratificationDecision.DecisionKind.SUPPORT,
        )
        self.decision(
            course=self.course,
            kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            rule_version="m03-unpublished-candidate",
        )

        test_school = School.objects.create(
            name="首页统计模拟学校",
            code="DASHBOARD-SIM",
            is_synthetic=True,
        )
        test_class = ClassGroup.objects.create(school=test_school, name="模拟1班")
        test_teacher = User.objects.create_user(
            username="dashboard_sim_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=test_school,
        )
        test_student = User.objects.create_user(
            username="dashboard_sim_student",
            password="123456",
            role=User.Role.STUDENT,
            school=test_school,
        )
        StudentProfile.objects.create(user=test_student, class_group=test_class)
        test_subject = Subject.objects.create(school=test_school, name="信息科技", code="IT")
        test_course = Course.objects.create(
            subject=test_subject,
            title="模拟课程",
            teacher=test_teacher,
        )
        StratificationDecision.objects.create(
            student=test_student,
            class_group=test_class,
            subject=test_subject,
            course=test_course,
            previous_layer="B",
            suggested_layer="A",
            decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            status=StratificationDecision.Status.PENDING,
        )

        super_admin = User.objects.create_superuser(
            username="dashboard_super_admin",
            password="Admin123!",
            role=User.Role.SUPER_ADMIN,
        )
        self.client.force_authenticate(super_admin)
        response = self.client.get("/api/v1/super-admin/dashboard/")

        self.assertEqual(response.status_code, 200, response.data)
        rows = {item["label"]: item["count"] for item in response.data["data"]["status_rows"]}
        self.assertEqual(rows["教师待确认层级"], 1)
