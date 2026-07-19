from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, Subject
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationPlanVersion,
    EvaluationScope,
    EvaluationCriterionVersion,
    EvaluationStandardVersion,
)
from school.models import School


class EvaluationManagementApiTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Evaluation School", code="EVALUATION")
        self.other_school = School.objects.create(name="Other School", code="EVALUATION-OTHER")
        self.subject = Subject.objects.create(
            school=self.school,
            name="Information Technology",
            code="IT",
        )
        self.other_subject = Subject.objects.create(
            school=self.other_school,
            name="Other Subject",
            code="OTHER",
        )
        self.teacher = User.objects.create_user(
            username="evaluation_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.other_teacher = User.objects.create_user(
            username="other_evaluation_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.other_school,
        )
        self.student = User.objects.create_user(
            username="evaluation_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.school_admin = User.objects.create_user(
            username="evaluation_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.other_school_admin = User.objects.create_user(
            username="other_evaluation_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.other_school,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="Data and Computing",
            teacher=self.teacher,
            is_active=True,
        )
        self.other_course = Course.objects.create(
            subject=self.other_subject,
            title="Other Course",
            teacher=self.other_teacher,
            is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.school_admin)

    def plan_payload(self) -> dict:
        return {
            "course": self.course.id,
            "title": "Data representation evaluation plan",
            "content_version": "2026.1",
            "target_students": "Grade 10 students studying data representation",
            "learning_goal": "Students can select representations and explain why they fit a data problem.",
            "learning_goals": [
                {
                    "code": "C1",
                    "title": "Representation selection",
                    "description": "The student selects a defensible representation for the stated data problem.",
                }
            ],
            "evaluation_basis": [
                {
                    "code": "E1",
                    "goal_codes": ["C1"],
                    "description": "The artifact and explanation jointly show a reasoned representation choice.",
                    "source_types": ["student artifact", "written explanation"],
                }
            ],
            "learning_tasks": [
                {
                    "code": "T1",
                    "title": "Campus data visualization",
                    "basis_codes": ["E1"],
                    "description": "Create a visualization and explain the mapping between variables and visual encodings.",
                }
            ],
            "content_scope": ["data representation", "visual encoding"],
            "thinking_requirements": ["apply", "analyze"],
            "support_options": ["teacher-provided data dictionary"],
            "scoring_rules": {
                "approach": "separate criteria",
                "decision_rule": "Interpret each criterion separately and do not replace missing evidence with a low score.",
            },
            "follow_up_suggestion": "Use the weakest evidenced criterion to select the next feedback prompt and practice task.",
        }

    def standard_payload(self, plan_id: int) -> dict:
        return {
            "plan": plan_id,
            "title": "Data representation evaluation standard",
            "evaluation_target": "Student visualization artifact and written design explanation",
            "criteria": [
                {
                    "code": "D1",
                    "dimension": "subject_practice",
                    "title": "Representation reasoning",
                    "evaluation_target": "The submitted visualization and explanation",
                    "evaluation_sources": ["visualization artifact", "written explanation"],
                    "expected_performance": "The student links data characteristics, visual encoding choices, and the intended reader.",
                    "skip_condition": "Do not evaluate this criterion when no visualization or explanation is available.",
                    "support_options": ["data dictionary", "chart-type reference sheet"],
                    "common_problems": ["A polished chart without an explanation does not demonstrate reasoning."],
                    "level_descriptions": {
                        "1": "The representation conflicts with the data type and no defensible reason is provided.",
                        "2": "The representation is partly usable, but the explanation relies on unsupported preferences.",
                        "3": "The representation fits the main data type and the explanation identifies one relevant design reason.",
                        "4": "The representation fits the data and audience, with connected reasons for the main visual encodings.",
                        "5": "The representation is precise and the explanation evaluates alternatives, trade-offs, and audience needs.",
                    },
                    "scoring_examples": [
                        {
                            "level": 2,
                            "title": "Preference-only explanation",
                            "example_description": "The chart is readable, but the student only states that it looks better.",
                            "file_reference": "pilot-anchor-D1-L2",
                        },
                        {
                            "level": 4,
                            "title": "Connected encoding explanation",
                            "example_description": "The student connects variable types, axis choices, color, and the intended audience.",
                            "file_reference": "pilot-anchor-D1-L4",
                        },
                    ],
                    "follow_up_suggestion": "Ask the student to compare the chosen representation with one plausible alternative.",
                }
            ],
        }

    def create_plan(self) -> dict:
        response = self.client.post(
            "/api/v1/school-admin/evaluations/plans/",
            self.plan_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]

    def test_options_and_drafts_are_school_scoped(self):
        response = self.client.get("/api/v1/school-admin/evaluations/options/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data["data"]["courses"]], [self.course.id])
        enabled = [row for row in response.data["data"]["scopes"] if row["enabled"]]
        self.assertEqual([row["value"] for row in enabled], [EvaluationScope.COURSE])

        payload = self.plan_payload()
        payload["course"] = self.other_course.id
        response = self.client.post(
            "/api/v1/school-admin/evaluations/plans/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EvaluationPlan.objects.exists())

        student_client = APIClient()
        student_client.force_authenticate(self.student)
        self.assertEqual(
            student_client.get("/api/v1/school-admin/evaluations/plans/").status_code,
            403,
        )
        teacher_client = APIClient()
        teacher_client.force_authenticate(self.teacher)
        self.assertEqual(
            teacher_client.get("/api/v1/school-admin/evaluations/plans/").status_code,
            403,
        )

    def test_incomplete_draft_can_save_but_cannot_publish(self):
        response = self.client.post(
            "/api/v1/school-admin/evaluations/plans/",
            {"course": self.course.id, "title": "Working draft"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        plan_id = response.data["data"]["id"]

        response = self.client.post(
            f"/api/v1/school-admin/evaluations/plans/{plan_id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EvaluationPlanVersion.objects.exists())

    def test_plan_publish_is_immutable_idempotent_and_versioned(self):
        plan = self.create_plan()
        publish_url = f"/api/v1/school-admin/evaluations/plans/{plan['id']}/publish/"

        response = self.client.post(publish_url, {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        version = EvaluationPlanVersion.objects.get()
        self.assertEqual(version.version_no, 1)
        self.assertEqual(len(version.content_hash), 64)

        response = self.client.post(publish_url, {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EvaluationPlanVersion.objects.count(), 1)

        version.title = "Changed"
        with self.assertRaises(ValidationError):
            version.save()

        payload = self.plan_payload()
        payload["follow_up_suggestion"] = "Provide a contrast case and ask the student to revise the explanation before the next task."
        response = self.client.patch(
            f"/api/v1/school-admin/evaluations/plans/{plan['id']}/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(publish_url, {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            list(EvaluationPlanVersion.objects.order_by("version_no").values_list("version_no", flat=True)),
            [1, 2],
        )

    def test_standard_publish_creates_normalized_immutable_level_descriptions(self):
        plan = self.create_plan()
        self.client.post(
            f"/api/v1/school-admin/evaluations/plans/{plan['id']}/publish/",
            {},
            format="json",
        )
        response = self.client.post(
            "/api/v1/school-admin/evaluations/standards/",
            self.standard_payload(plan["id"]),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        standard_id = response.data["data"]["id"]

        response = self.client.post(
            f"/api/v1/school-admin/evaluations/standards/{standard_id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        version = EvaluationStandardVersion.objects.get()
        criterion = EvaluationCriterionVersion.objects.get()
        self.assertEqual(version.plan_version.version_no, 1)
        self.assertEqual(criterion.dimension, "subject_practice")
        self.assertEqual(criterion.scoring_examples.count(), 2)
        self.assertIn("Do not evaluate", criterion.skip_condition)

        criterion.title = "Changed"
        with self.assertRaises(ValidationError):
            criterion.save()

    def test_forbidden_operational_indicator_cannot_enter_published_standard(self):
        plan = self.create_plan()
        self.client.post(
            f"/api/v1/school-admin/evaluations/plans/{plan['id']}/publish/",
            {},
            format="json",
        )
        payload = self.standard_payload(plan["id"])
        payload["criteria"][0]["title"] = "签到与出勤表现"
        response = self.client.post(
            "/api/v1/school-admin/evaluations/standards/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        standard_id = response.data["data"]["id"]
        response = self.client.post(
            f"/api/v1/school-admin/evaluations/standards/{standard_id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EvaluationStandardVersion.objects.exists())

    def test_other_school_admin_cannot_read_or_publish_plans(self):
        plan = self.create_plan()
        other_client = APIClient()
        other_client.force_authenticate(self.other_school_admin)
        detail_url = f"/api/v1/school-admin/evaluations/plans/{plan['id']}/"
        publish_url = f"{detail_url}publish/"
        self.assertEqual(other_client.get(detail_url).status_code, 404)
        self.assertEqual(other_client.post(publish_url, {}, format="json").status_code, 404)

    def test_scope_cannot_be_submitted_directly(self):
        payload = self.plan_payload()
        payload["scope"] = EvaluationScope.ANALYSIS
        response = self.client.post(
            "/api/v1/school-admin/evaluations/plans/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown_fields", response.data["errors"])
