from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, Subject
from learning_analytics.measurement_models import (
    AssessmentBlueprint,
    AssessmentBlueprintVersion,
    MeasurementUse,
    RubricCriterionVersion,
    RubricDefinitionVersion,
)
from school.models import School


class MeasurementDesignApiTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Measurement School", code="MEASURE")
        self.other_school = School.objects.create(name="Other School", code="MEASURE-OTHER")
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
            username="measure_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.other_teacher = User.objects.create_user(
            username="other_measure_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.other_school,
        )
        self.student = User.objects.create_user(
            username="measure_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
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
        self.client.force_authenticate(self.teacher)

    def blueprint_payload(self) -> dict:
        return {
            "course": self.course.id,
            "title": "Data representation task blueprint",
            "task_version": "2026.1",
            "target_population": "Grade 10 students studying data representation",
            "course_goal": "Students can select representations and explain why they fit a data problem.",
            "claims": [
                {
                    "code": "C1",
                    "title": "Representation selection",
                    "description": "The student selects a defensible representation for the stated data problem.",
                }
            ],
            "evidence_rules": [
                {
                    "code": "E1",
                    "claim_codes": ["C1"],
                    "description": "The artifact and explanation jointly show a reasoned representation choice.",
                    "source_types": ["student artifact", "written explanation"],
                }
            ],
            "task_specifications": [
                {
                    "code": "T1",
                    "title": "Campus data visualization",
                    "evidence_codes": ["E1"],
                    "description": "Create a visualization and explain the mapping between variables and visual encodings.",
                }
            ],
            "content_coverage": ["data representation", "visual encoding"],
            "cognitive_complexity": ["apply", "analyze"],
            "allowed_supports": ["teacher-provided data dictionary"],
            "scoring_model": {
                "approach": "analytic rubric",
                "decision_rule": "Interpret each criterion separately and do not replace missing evidence with a low score.",
            },
            "next_formative_action": "Use the weakest evidenced criterion to select the next feedback prompt and practice task.",
        }

    def rubric_payload(self, blueprint_id: int) -> dict:
        return {
            "blueprint": blueprint_id,
            "title": "Data representation formative rubric",
            "evaluation_object": "Student visualization artifact and written design explanation",
            "criteria": [
                {
                    "code": "D1",
                    "module": "D",
                    "title": "Representation reasoning",
                    "evaluation_object": "The submitted visualization and explanation",
                    "evidence_sources": ["visualization artifact", "written explanation"],
                    "observable_evidence": "The student links data characteristics, visual encoding choices, and the intended reader.",
                    "not_assessed_condition": "Record NOT_ASSESSED when no visualization or explanation is available for inspection.",
                    "allowed_supports": ["data dictionary", "chart-type reference sheet"],
                    "counter_examples": ["A polished chart without an explanation does not demonstrate reasoning."],
                    "anchors": {
                        "1": "The representation conflicts with the data type and no defensible reason is provided.",
                        "2": "The representation is partly usable, but the explanation relies on unsupported preferences.",
                        "3": "The representation fits the main data type and the explanation identifies one relevant design reason.",
                        "4": "The representation fits the data and audience, with connected reasons for the main visual encodings.",
                        "5": "The representation is precise and the explanation evaluates alternatives, trade-offs, and audience needs.",
                    },
                    "anchor_examples": [
                        {
                            "level": 2,
                            "title": "Preference-only explanation",
                            "evidence_summary": "The chart is readable, but the student only states that it looks better.",
                            "artifact_reference": "pilot-anchor-D1-L2",
                        },
                        {
                            "level": 4,
                            "title": "Connected encoding explanation",
                            "evidence_summary": "The student connects variable types, axis choices, color, and the intended audience.",
                            "artifact_reference": "pilot-anchor-D1-L4",
                        },
                    ],
                    "next_formative_action": "Ask the student to compare the chosen representation with one plausible alternative.",
                }
            ],
        }

    def create_blueprint(self) -> dict:
        response = self.client.post(
            "/api/v1/teacher/measurement/blueprints/",
            self.blueprint_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]

    def test_options_and_drafts_are_teacher_scoped(self):
        response = self.client.get("/api/v1/teacher/measurement/options/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data["data"]["courses"]], [self.course.id])
        enabled = [row for row in response.data["data"]["uses"] if row["teacher_enabled"]]
        self.assertEqual([row["value"] for row in enabled], [MeasurementUse.LOCAL_FORMATIVE])

        payload = self.blueprint_payload()
        payload["course"] = self.other_course.id
        response = self.client.post(
            "/api/v1/teacher/measurement/blueprints/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AssessmentBlueprint.objects.exists())

        student_client = APIClient()
        student_client.force_authenticate(self.student)
        self.assertEqual(
            student_client.get("/api/v1/teacher/measurement/blueprints/").status_code,
            403,
        )

    def test_incomplete_draft_can_save_but_cannot_publish(self):
        response = self.client.post(
            "/api/v1/teacher/measurement/blueprints/",
            {"course": self.course.id, "title": "Working draft"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        blueprint_id = response.data["data"]["id"]

        response = self.client.post(
            f"/api/v1/teacher/measurement/blueprints/{blueprint_id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AssessmentBlueprintVersion.objects.exists())

    def test_blueprint_publish_is_immutable_idempotent_and_versioned(self):
        blueprint = self.create_blueprint()
        publish_url = f"/api/v1/teacher/measurement/blueprints/{blueprint['id']}/publish/"

        response = self.client.post(publish_url, {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        version = AssessmentBlueprintVersion.objects.get()
        self.assertEqual(version.version_no, 1)
        self.assertEqual(len(version.content_hash), 64)

        response = self.client.post(publish_url, {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AssessmentBlueprintVersion.objects.count(), 1)

        version.title = "Changed"
        with self.assertRaises(ValidationError):
            version.save()

        payload = self.blueprint_payload()
        payload["next_formative_action"] = "Provide a contrast case and ask the student to revise the explanation before the next task."
        response = self.client.patch(
            f"/api/v1/teacher/measurement/blueprints/{blueprint['id']}/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(publish_url, {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            list(AssessmentBlueprintVersion.objects.order_by("version_no").values_list("version_no", flat=True)),
            [1, 2],
        )

    def test_rubric_publish_creates_normalized_immutable_anchors(self):
        blueprint = self.create_blueprint()
        self.client.post(
            f"/api/v1/teacher/measurement/blueprints/{blueprint['id']}/publish/",
            {},
            format="json",
        )
        response = self.client.post(
            "/api/v1/teacher/measurement/rubrics/",
            self.rubric_payload(blueprint["id"]),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        rubric_id = response.data["data"]["id"]

        response = self.client.post(
            f"/api/v1/teacher/measurement/rubrics/{rubric_id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        version = RubricDefinitionVersion.objects.get()
        criterion = RubricCriterionVersion.objects.get()
        self.assertEqual(version.blueprint_version.version_no, 1)
        self.assertEqual(criterion.module, "D")
        self.assertEqual(criterion.anchor_examples.count(), 2)
        self.assertIn("NOT_ASSESSED", criterion.not_assessed_condition)

        criterion.title = "Changed"
        with self.assertRaises(ValidationError):
            criterion.save()

    def test_forbidden_operational_indicator_cannot_enter_published_rubric(self):
        blueprint = self.create_blueprint()
        self.client.post(
            f"/api/v1/teacher/measurement/blueprints/{blueprint['id']}/publish/",
            {},
            format="json",
        )
        payload = self.rubric_payload(blueprint["id"])
        payload["criteria"][0]["title"] = "签到与出勤表现"
        response = self.client.post(
            "/api/v1/teacher/measurement/rubrics/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        rubric_id = response.data["data"]["id"]
        response = self.client.post(
            f"/api/v1/teacher/measurement/rubrics/{rubric_id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(RubricDefinitionVersion.objects.exists())

    def test_other_teacher_cannot_read_or_publish_drafts(self):
        blueprint = self.create_blueprint()
        other = User.objects.create_user(
            username="same_school_other_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        other_client = APIClient()
        other_client.force_authenticate(other)
        detail_url = f"/api/v1/teacher/measurement/blueprints/{blueprint['id']}/"
        publish_url = f"{detail_url}publish/"
        self.assertEqual(other_client.get(detail_url).status_code, 404)
        self.assertEqual(other_client.post(publish_url, {}, format="json").status_code, 404)

    def test_teacher_cannot_submit_research_use_field(self):
        payload = self.blueprint_payload()
        payload["intended_use"] = MeasurementUse.RESEARCH_LINKED
        response = self.client.post(
            "/api/v1/teacher/measurement/blueprints/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown_fields", response.data["errors"])
