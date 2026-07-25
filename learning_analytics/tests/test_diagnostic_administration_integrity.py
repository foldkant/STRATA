from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Subject
from learning.models import (
    DiagnosticAdministration,
    DiagnosticAdministrationAssignment,
    DiagnosticSubmissionBinding,
    PretestPaper,
    PretestPaperVersion,
    PretestQuestion,
    PretestSubmission,
    StudentLearningTargetStateVersion,
    UnifiedAssessmentMaterial,
)
from learning.services.diagnostic_administrations import (
    DiagnosticAdministrationError,
    availability_status,
    bind_diagnostic_submission,
    close_diagnostic_administration,
    create_diagnostic_administration,
    diagnostic_completion_status,
    prepare_student_diagnostic_submission,
    publish_diagnostic_administration,
    replace_diagnostic_assignments,
)
from learning.services.mastery import build_initial_diagnostic_content_band_candidate
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from school.models import ClassGroup, School, StudentProfile


class DiagnosticAdministrationIntegrityTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="诊断实施学校", code="DIAG-ADMIN")
        self.other_school = School.objects.create(name="外校", code="DIAG-OTHER")
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
        )
        self.admin = User.objects.create_user(
            username="diagnostic_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.other_admin = User.objects.create_user(
            username="diagnostic_other_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.other_school,
        )
        self.experiment_class = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.control_class = ClassGroup.objects.create(
            school=self.school, name="高一2班", grade="高一"
        )
        self.other_class = ClassGroup.objects.create(
            school=self.other_school, name="高一9班", grade="高一"
        )
        self.experiment_student = User.objects.create_user(
            username="diagnostic_exp_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.control_student = User.objects.create_user(
            username="diagnostic_control_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.experiment_student, class_group=self.experiment_class
        )
        StudentProfile.objects.create(
            user=self.control_student, class_group=self.control_class
        )
        self.paper = PretestPaper.objects.create(
            school=self.school,
            subject=self.subject,
            title="信息科技共同学习起点诊断",
            # Administration lifecycle tests intentionally use a questionnaire
            # instrument. Exact literacy-target enforcement is covered below
            # and in test_learning_target_versions.
            kind=PretestPaper.Kind.ATTITUDE,
            version=1,
            status=PretestPaper.Status.PUBLISHED,
            created_by=self.admin,
            published_at=timezone.now(),
        )
        self.question = PretestQuestion.objects.create(
            paper=self.paper,
            stem="根据任务需要选择数据类型。",
            question_type=PretestQuestion.QuestionType.SINGLE,
            options=[{"label": "A", "text": "数值"}, {"label": "B", "text": "文本"}],
            answer=["A"],
            score=2,
            learning_target_code="IT-DATA-01",
            learning_target_name="根据任务需要选择数据类型",
        )
        self.version = self._version(1)

    def _version(self, version_no: int) -> PretestPaperVersion:
        return PretestPaperVersion.objects.create(
            source=self.paper,
            version_no=version_no,
            title=f"信息科技共同学习起点诊断 v{version_no}",
            kind=self.paper.kind,
            introduction="用于目标级学习起点判断。",
            question_snapshot=[
                {
                    "id": self.question.id,
                    "stem": self.question.stem,
                    "question_type": self.question.question_type,
                    "options": self.question.options,
                    "answer": self.question.answer,
                    "score": self.question.score,
                    "learning_target_code": self.question.learning_target_code,
                    "learning_target_name": self.question.learning_target_name,
                    "material_requirements": [],
                    "sort_order": 1,
                    "is_required": True,
                }
            ],
            published_by=self.admin,
        )

    def _draft(self, *, purpose="entry_diagnostic", suffix="ENTRY"):
        return create_diagnostic_administration(
            school=self.school,
            actor=self.admin,
            payload={
                "subject_id": self.subject.id,
                "paper_version_id": self.version.id,
                "purpose": purpose,
                "batch_code": f"IT-2026-{suffix}",
                "title": f"信息科技{suffix}实施",
                "open_at": (timezone.now() - timedelta(hours=1)).isoformat(),
                "close_at": (timezone.now() + timedelta(days=7)).isoformat(),
            },
        )

    def _assign_and_publish(self, draft, assignments):
        replace_diagnostic_assignments(
            administration_id=draft.id,
            school=self.school,
            payload={"assignments": assignments},
        )
        return publish_diagnostic_administration(
            administration_id=draft.id,
            school=self.school,
            actor=self.admin,
        )

    def test_research_batch_proves_experiment_and_control_share_exact_version(self):
        draft = self._draft(purpose="research_pretest", suffix="RESEARCH-PRE")
        published = self._assign_and_publish(
            draft,
            [
                {
                    "class_group_id": self.experiment_class.id,
                    "cohort_role": "experiment",
                    "opportunity_status": "offered",
                },
                {
                    "class_group_id": self.control_class.id,
                    "cohort_role": "control",
                    "opportunity_status": "offered",
                },
            ],
        )

        rows = list(published.assignments.order_by("cohort_role"))
        self.assertEqual({row.cohort_role for row in rows}, {"experiment", "control"})
        self.assertTrue(all(row.administration.paper_version_id == self.version.id for row in rows))
        self.assertEqual(published.content_hash, published.expected_content_hash())
        self.assertEqual(len(published.content_hash), 64)

    def test_new_formal_literacy_batch_rejects_explicit_legacy_target_mapping(self):
        literacy_paper = PretestPaper.objects.create(
            school=self.school,
            subject=self.subject,
            title="信息科技历史素养诊断",
            kind=PretestPaper.Kind.LITERACY,
            version=99,
            status=PretestPaper.Status.PUBLISHED,
            created_by=self.admin,
            published_at=timezone.now(),
        )
        legacy_version = PretestPaperVersion.objects.create(
            source=literacy_paper,
            version_no=99,
            title="显式历史未映射诊断版本",
            kind=PretestPaper.Kind.LITERACY,
            introduction="仅可用于试测。",
            question_snapshot=[
                {
                    "id": self.question.id,
                    "stem": self.question.stem,
                    "question_type": self.question.question_type,
                    "options": self.question.options,
                    "answer": self.question.answer,
                    "score": self.question.score,
                    "learning_target_code": self.question.learning_target_code,
                    "learning_target_name": self.question.learning_target_name,
                    "learning_target_version_id": None,
                    "learning_target_version_hash": "",
                    "legacy_unmapped": True,
                    "material_requirements": [],
                    "sort_order": 1,
                    "is_required": True,
                }
            ],
            published_by=self.admin,
        )
        with self.assertRaises(DiagnosticAdministrationError) as captured:
            create_diagnostic_administration(
                school=self.school,
                actor=self.admin,
                payload={
                    "subject_id": self.subject.id,
                    "paper_version_id": legacy_version.id,
                    "purpose": DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
                    "batch_code": "IT-LEGACY-FORMAL-01",
                    "title": "不应建立的正式诊断批次",
                },
            )
        self.assertEqual(captured.exception.status, 409)
        self.assertIn("不可变的学习目标版本", captured.exception.message)

        pilot = create_diagnostic_administration(
            school=self.school,
            actor=self.admin,
            payload={
                "subject_id": self.subject.id,
                "paper_version_id": legacy_version.id,
                "purpose": DiagnosticAdministration.Purpose.PILOT,
                "batch_code": "IT-LEGACY-PILOT-01",
                "title": "历史未映射任务试测批次",
            },
        )
        self.assertEqual(pilot.purpose, DiagnosticAdministration.Purpose.PILOT)

        implicit_legacy = PretestPaperVersion.objects.create(
            source=literacy_paper,
            version_no=100,
            title="无显式映射标记的历史素养诊断",
            kind=PretestPaper.Kind.LITERACY,
            introduction="仅保留用于历史审计。",
            question_snapshot=[
                {
                    "id": self.question.id,
                    "stem": self.question.stem,
                    "question_type": self.question.question_type,
                    "options": self.question.options,
                    "answer": self.question.answer,
                    "score": self.question.score,
                    "learning_target_code": self.question.learning_target_code,
                    "learning_target_name": self.question.learning_target_name,
                    "material_requirements": [],
                    "sort_order": 1,
                    "is_required": True,
                }
            ],
            published_by=self.admin,
        )
        with self.assertRaises(DiagnosticAdministrationError) as implicit_create:
            create_diagnostic_administration(
                school=self.school,
                actor=self.admin,
                payload={
                    "subject_id": self.subject.id,
                    "paper_version_id": implicit_legacy.id,
                    "purpose": DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
                    "batch_code": "IT-IMPLICIT-LEGACY-CREATE",
                    "title": "不应建立的隐式历史诊断批次",
                },
            )
        self.assertEqual(implicit_create.exception.status, 409)

        bypassed_draft = DiagnosticAdministration.objects.create(
            school=self.school,
            subject=self.subject,
            paper_version=implicit_legacy,
            purpose=DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
            batch_code="IT-IMPLICIT-LEGACY-PUBLISH",
            title="发布层必须再次拒绝的历史诊断批次",
            created_by=self.admin,
        )
        replace_diagnostic_assignments(
            administration_id=bypassed_draft.id,
            school=self.school,
            payload={
                "assignments": [
                    {
                        "class_group_id": self.experiment_class.id,
                        "cohort_role": "unassigned",
                        "opportunity_status": "offered",
                    }
                ]
            },
        )
        with self.assertRaises(DiagnosticAdministrationError) as implicit_publish:
            publish_diagnostic_administration(
                administration_id=bypassed_draft.id,
                school=self.school,
                actor=self.admin,
            )
        self.assertEqual(implicit_publish.exception.status, 409)

    def test_research_publish_rejects_missing_control_cohort(self):
        draft = self._draft(purpose="research_posttest", suffix="RESEARCH-POST")
        replace_diagnostic_assignments(
            administration_id=draft.id,
            school=self.school,
            payload={
                "assignments": [
                    {
                        "class_group_id": self.experiment_class.id,
                        "cohort_role": "experiment",
                        "opportunity_status": "offered",
                    }
                ]
            },
        )
        with self.assertRaises(DiagnosticAdministrationError) as caught:
            publish_diagnostic_administration(
                administration_id=draft.id,
                school=self.school,
                actor=self.admin,
            )
        self.assertEqual(caught.exception.status, 400)
        draft.refresh_from_db()
        self.assertEqual(draft.status, DiagnosticAdministration.Status.DRAFT)

    def test_research_review_keeps_measurement_source_separate_from_teaching_candidate(self):
        sync_event_schema_definitions()
        self.question.question_type = PretestQuestion.QuestionType.TEXT
        self.question.answer = []
        self.question.score = 10
        self.question.save()
        research_version = self._version(3)
        self.version = research_version
        administration = self._assign_and_publish(
            self._draft(
                purpose=DiagnosticAdministration.Purpose.RESEARCH_PRETEST,
                suffix="REVIEW-SEPARATION",
            ),
            [
                {
                    "class_group_id": self.experiment_class.id,
                    "cohort_role": "experiment",
                    "opportunity_status": "offered",
                },
                {
                    "class_group_id": self.control_class.id,
                    "cohort_role": "control",
                    "opportunity_status": "offered",
                },
            ],
        )
        client = APIClient()
        client.force_authenticate(self.experiment_student)
        submitted = client.post(
            f"/api/v1/student/diagnostic-administrations/{administration.id}/paper/",
            {
                "paper_version_id": research_version.id,
                "content_hash": research_version.content_hash,
                "idempotency_key": "research-review-separation-1",
                "answers": {str(self.question.id): "研究前测主观作答"},
                "task_statuses": {str(self.question.id): "observed"},
            },
            format="json",
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        raw_material = UnifiedAssessmentMaterial.objects.get(
            source_type="research_pretest",
            student=self.experiment_student,
        )
        original_state = StudentLearningTargetStateVersion.objects.get(
            source_type="research_pretest",
            student=self.experiment_student,
        )
        self.assertFalse(original_state.is_initial_diagnostic)

        client.force_authenticate(self.admin)
        reviewed = client.post(
            f"/api/v1/school-admin/pretest-materials/{raw_material.material_id}/review/",
            {"score": 8, "score_max": 10, "feedback": "研究测量评分"},
            format="json",
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        self.assertEqual(
            reviewed.data["data"]["learning_content_recommendation"]["status"],
            "not_applicable",
        )
        score_material = UnifiedAssessmentMaterial.objects.get(
            source_type="research_pretest_review",
            source_id=str(raw_material.material_id),
        )
        reviewed_state = StudentLearningTargetStateVersion.objects.get(
            source_type="research_pretest_review",
            source_id=str(submitted.data["data"]["id"]),
        )
        self.assertFalse(reviewed_state.is_initial_diagnostic)
        self.assertTrue(
            reviewed_state.source_version.startswith(administration.content_hash)
        )
        self.assertEqual(
            score_material.content["administration_content_hash"],
            administration.content_hash,
        )
        self.assertFalse(
            UnifiedAssessmentMaterial.objects.filter(
                source_type="learning_entry_diagnostic_review",
                student=self.experiment_student,
            ).exists()
        )
        with self.assertRaisesMessage(ValidationError, "只有学习起点诊断批次"):
            build_initial_diagnostic_content_band_candidate(
                administration=administration,
                student=self.experiment_student,
            )

    def test_published_version_and_assignments_are_frozen_when_new_version_exists(self):
        draft = self._draft()
        published = self._assign_and_publish(
            draft,
            [
                {
                    "class_group_id": self.experiment_class.id,
                    "cohort_role": "unassigned",
                    "opportunity_status": "offered",
                }
            ],
        )
        frozen_hash = published.content_hash
        frozen_version_id = published.paper_version_id
        newer_version = self._version(2)

        published.refresh_from_db()
        self.assertNotEqual(newer_version.id, frozen_version_id)
        self.assertEqual(published.paper_version_id, frozen_version_id)
        self.assertEqual(published.content_hash, frozen_hash)
        assignment = published.assignments.get()
        assignment.cohort_role = "experiment"
        with self.assertRaises(ValidationError):
            assignment.save()
        with self.assertRaises(ValidationError):
            assignment.delete()
        with self.assertRaises(ValidationError):
            published.assignments.update(cohort_role="control")
        with self.assertRaises(ValidationError):
            published.assignments.all().delete()
        with self.assertRaises(ValidationError):
            DiagnosticAdministration.objects.filter(pk=published.pk).update(
                title="不应写入"
            )
        with self.assertRaises(ValidationError):
            DiagnosticAdministration.objects.filter(pk=published.pk).delete()
        published.paper_version = newer_version
        with self.assertRaises(ValidationError):
            published.save()

    def test_entry_pre_post_can_reuse_one_exact_version_without_drift(self):
        entry = self._assign_and_publish(
            self._draft(suffix="ENTRY-REUSE"),
            [
                {
                    "class_group_id": self.experiment_class.id,
                    "cohort_role": "unassigned",
                    "opportunity_status": "offered",
                }
            ],
        )
        pre = self._assign_and_publish(
            self._draft(purpose="research_pretest", suffix="PRE-REUSE"),
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "experiment", "opportunity_status": "offered"},
                {"class_group_id": self.control_class.id, "cohort_role": "control", "opportunity_status": "offered"},
            ],
        )
        post = self._assign_and_publish(
            self._draft(purpose="research_posttest", suffix="POST-REUSE"),
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "experiment", "opportunity_status": "offered"},
                {"class_group_id": self.control_class.id, "cohort_role": "control", "opportunity_status": "offered"},
            ],
        )
        self.assertEqual(
            {entry.paper_version_id, pre.paper_version_id, post.paper_version_id},
            {self.version.id},
        )
        self.assertEqual(len({entry.content_hash, pre.content_hash, post.content_hash}), 3)

    def test_other_school_class_cannot_be_assigned(self):
        draft = self._draft(suffix="SCOPE")
        with self.assertRaises(DiagnosticAdministrationError) as caught:
            replace_diagnostic_assignments(
                administration_id=draft.id,
                school=self.school,
                payload={
                    "assignments": [
                        {
                            "class_group_id": self.other_class.id,
                            "cohort_role": "unassigned",
                            "opportunity_status": "offered",
                        }
                    ]
                },
            )
        self.assertIn("assignments.0", caught.exception.errors)

    def test_not_offered_is_an_exemption_and_student_cannot_submit(self):
        draft = self._draft(suffix="NOT-OFFERED")
        replace_diagnostic_assignments(
            administration_id=draft.id,
            school=self.school,
            payload={
                "assignments": [
                    {"class_group_id": self.experiment_class.id, "cohort_role": "unassigned", "opportunity_status": "not_offered"},
                    {"class_group_id": self.control_class.id, "cohort_role": "unassigned", "opportunity_status": "offered"},
                ]
            },
        )
        published = publish_diagnostic_administration(
            administration_id=draft.id, school=self.school, actor=self.admin
        )
        assignment = published.assignments.get(class_group=self.experiment_class)
        self.assertEqual(
            diagnostic_completion_status(assignment, None),
            {
                "submission": "not_required",
                "scoring": "not_applicable",
                "course_access": "exempt",
                "exception": "not_offered",
            },
        )
        with self.assertRaises(DiagnosticAdministrationError) as caught:
            prepare_student_diagnostic_submission(
                administration_id=published.id,
                student=self.experiment_student,
                idempotency_key="not-offered-attempt",
            )
        self.assertEqual(caught.exception.status, 403)

    def test_school_admin_api_is_scoped_and_student_lists_only_assignments(self):
        published = self._assign_and_publish(
            self._draft(suffix="API-SCOPE"),
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "unassigned", "opportunity_status": "offered"}
            ],
        )
        client = APIClient()
        client.force_authenticate(self.other_admin)
        hidden = client.get(
            f"/api/v1/school-admin/diagnostic-administrations/{published.id}/"
        )
        self.assertEqual(hidden.status_code, 404)

        client.force_authenticate(self.experiment_student)
        visible = client.get("/api/v1/student/diagnostic-administrations/")
        self.assertEqual(visible.status_code, 200, visible.data)
        self.assertEqual(
            [row["administration_id"] for row in visible.data["data"]],
            [published.id],
        )
        client.force_authenticate(self.control_student)
        absent = client.get("/api/v1/student/diagnostic-administrations/")
        self.assertEqual(absent.status_code, 200, absent.data)
        self.assertEqual(absent.data["data"], [])

    def test_scheduled_and_closed_student_apis_expose_only_status_and_time(self):
        draft = create_diagnostic_administration(
            school=self.school,
            actor=self.admin,
            payload={
                "subject_id": self.subject.id,
                "paper_version_id": self.version.id,
                "purpose": DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
                "batch_code": "IT-PRIVATE-WINDOW",
                "title": "开放窗口内容保护",
                "open_at": (timezone.now() + timedelta(days=1)).isoformat(),
                "close_at": (timezone.now() + timedelta(days=2)).isoformat(),
            },
        )
        administration = self._assign_and_publish(
            draft,
            [
                {
                    "class_group_id": self.experiment_class.id,
                    "cohort_role": "unassigned",
                    "opportunity_status": "offered",
                }
            ],
        )
        client = APIClient()
        client.force_authenticate(self.experiment_student)
        urls = (
            "/api/v1/student/diagnostic-administrations/",
            f"/api/v1/student/diagnostic-administrations/{administration.id}/",
            f"/api/v1/student/diagnostic-administrations/{administration.id}/paper/",
            f"/api/v1/student/pretests/papers/{self.paper.id}/",
            f"/api/v1/student/pretests/{self.subject.id}/",
        )
        forbidden = {
            "questions",
            "paper",
            "paper_version",
            "published_version",
            "stem",
            "options",
            "material_requirements",
            "download_url",
        }

        def assert_private(payload, expected_state):
            serialized = str(payload)
            self.assertNotIn(self.question.stem, serialized)

            def walk(value):
                if isinstance(value, dict):
                    self.assertTrue(forbidden.isdisjoint(value))
                    for nested in value.values():
                        walk(nested)
                elif isinstance(value, list):
                    for nested in value:
                        walk(nested)

            walk(payload)
            self.assertIn(expected_state, serialized)

        for url in urls:
            response = client.get(url)
            self.assertEqual(response.status_code, 200, response.data)
            assert_private(response.data["data"], "scheduled")

        subject_page = client.get(f"/api/v1/student/pretests/{self.subject.id}/")
        scheduled_row = subject_page.data["data"]["papers"][0]
        self.assertEqual(scheduled_row["title"], administration.title)
        self.assertEqual(scheduled_row["batch_code"], administration.batch_code)
        self.assertFalse(scheduled_row["submission_allowed"])
        self.assertNotIn("published_version", scheduled_row)
        required_rows = client.get("/api/v1/student/pretests/required/")
        status = next(
            row["pretest_status"]
            for row in required_rows.data["data"]
            if row["subject"]["id"] == self.subject.id
        )
        self.assertEqual(status["status"], "scheduled")
        self.assertFalse(status["required"])
        self.assertFalse(status["completed"])
        self.assertEqual(status["course_access"], "eligible")

        close_diagnostic_administration(
            administration_id=administration.id,
            school=self.school,
            actor=self.admin,
        )
        for url in urls:
            response = client.get(url)
            self.assertEqual(response.status_code, 200, response.data)
            assert_private(response.data["data"], "closed")

    def test_availability_window_is_separate_from_lifecycle_status(self):
        draft = self._draft(suffix="WINDOW")
        published = self._assign_and_publish(
            draft,
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "unassigned", "opportunity_status": "offered"}
            ],
        )
        self.assertEqual(availability_status(published), "open")
        published.open_at = timezone.now() + timedelta(days=1)
        # Persisted published fields are frozen; evaluate a detached copy only.
        self.assertEqual(availability_status(published), "scheduled")

    def test_same_paper_version_can_be_submitted_in_entry_and_research_batches(self):
        sync_event_schema_definitions()
        entry = self._assign_and_publish(
            self._draft(suffix="ENTRY-SUBMIT"),
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "unassigned", "opportunity_status": "offered"}
            ],
        )
        research = self._assign_and_publish(
            self._draft(purpose="research_pretest", suffix="PRE-SUBMIT"),
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "experiment", "opportunity_status": "offered"},
                {"class_group_id": self.control_class.id, "cohort_role": "control", "opportunity_status": "offered"},
            ],
        )
        client = APIClient()
        client.force_authenticate(self.experiment_student)
        for administration, key in ((entry, "entry-submit-1"), (research, "research-submit-1")):
            response = client.post(
                f"/api/v1/student/diagnostic-administrations/{administration.id}/paper/",
                {
                    "paper_version_id": self.version.id,
                    "content_hash": self.version.content_hash,
                    "idempotency_key": key,
                    "answers": {str(self.question.id): "A"},
                    "task_statuses": {str(self.question.id): "observed"},
                },
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["data"]["administration_id"], administration.id)

        submissions = list(
            PretestSubmission.objects.filter(student=self.experiment_student).order_by(
                "administration_id"
            )
        )
        self.assertEqual(len(submissions), 2)
        self.assertEqual({item.paper_version_id for item in submissions}, {self.version.id})
        self.assertEqual({item.attempt_no for item in submissions}, {1})
        self.assertEqual(
            set(DiagnosticSubmissionBinding.objects.values_list("administration_id", flat=True)),
            {entry.id, research.id},
        )
        entry_submission = PretestSubmission.objects.get(administration=entry)
        inconsistent = DiagnosticSubmissionBinding(
            administration=research,
            assignment=research.assignments.get(class_group=self.experiment_class),
            submission=entry_submission,
            student=self.experiment_student,
            attempt_no=entry_submission.attempt_no,
            idempotency_key=entry_submission.idempotency_key,
            request_hash="0" * 64,
        )
        with self.assertRaises(ValidationError):
            inconsistent.full_clean()
        wrong_key = DiagnosticSubmissionBinding(
            administration=entry,
            assignment=entry.assignments.get(),
            submission=entry_submission,
            student=self.experiment_student,
            attempt_no=entry_submission.attempt_no,
            idempotency_key="different-binding-key",
            request_hash="0" * 64,
        )
        with self.assertRaises(ValidationError):
            wrong_key.full_clean()

    def test_student_submission_is_idempotent_and_changed_payload_conflicts(self):
        sync_event_schema_definitions()
        administration = self._assign_and_publish(
            self._draft(suffix="IDEMPOTENT"),
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "unassigned", "opportunity_status": "offered"}
            ],
        )
        url = f"/api/v1/student/diagnostic-administrations/{administration.id}/paper/"
        payload = {
            "paper_version_id": self.version.id,
            "content_hash": self.version.content_hash,
            "idempotency_key": "same-browser-submit",
            "answers": {str(self.question.id): "A"},
            "task_statuses": {str(self.question.id): "observed"},
        }
        client = APIClient()
        client.force_authenticate(self.experiment_student)
        first = client.post(url, payload, format="json")
        repeated = client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertTrue(repeated.data["data"]["idempotent_replay"])
        self.assertEqual(repeated.data["data"]["id"], first.data["data"]["id"])
        self.assertEqual(PretestSubmission.objects.count(), 1)
        self.assertEqual(DiagnosticSubmissionBinding.objects.count(), 1)

        changed = client.post(
            url,
            {**payload, "answers": {str(self.question.id): "B"}},
            format="json",
        )
        self.assertEqual(changed.status_code, 409, changed.data)
        changed_status = client.post(
            url,
            {
                **payload,
                "task_statuses": {str(self.question.id): "device_issue"},
            },
            format="json",
        )
        self.assertEqual(changed_status.status_code, 409, changed_status.data)
        different_key = client.post(
            url,
            {**payload, "idempotency_key": "different-browser-submit"},
            format="json",
        )
        self.assertEqual(different_key.status_code, 409, different_key.data)
        self.assertEqual(PretestSubmission.objects.count(), 1)
        self.assertEqual(DiagnosticSubmissionBinding.objects.count(), 1)

    def test_version_mismatch_and_completion_dimensions_are_independent(self):
        sync_event_schema_definitions()
        administration = self._assign_and_publish(
            self._draft(suffix="VERSION-CHECK"),
            [
                {"class_group_id": self.experiment_class.id, "cohort_role": "unassigned", "opportunity_status": "offered"}
            ],
        )
        newer_version = self._version(2)
        client = APIClient()
        client.force_authenticate(self.experiment_student)
        url = f"/api/v1/student/diagnostic-administrations/{administration.id}/paper/"
        mismatch = client.post(
            url,
            {
                "paper_version_id": newer_version.id,
                "content_hash": newer_version.content_hash,
                "idempotency_key": "wrong-frozen-version",
                "answers": {str(self.question.id): "A"},
            },
            format="json",
        )
        self.assertEqual(mismatch.status_code, 409, mismatch.data)
        self.assertFalse(PretestSubmission.objects.exists())

        reported = client.post(
            url,
            {
                "paper_version_id": self.version.id,
                "content_hash": self.version.content_hash,
                "idempotency_key": "device-report",
                "answers": {},
                "opportunity_status": "device_issue",
            },
            format="json",
        )
        self.assertEqual(reported.status_code, 200, reported.data)
        completion = reported.data["data"]["completion"]
        self.assertEqual(completion["submission"], "reported")
        self.assertEqual(completion["scoring"], "not_applicable")
        self.assertEqual(completion["course_access"], "deferred")
        self.assertEqual(completion["exception"], "device_issue")
        result = reported.data["data"]["target_results"][0]
        self.assertTrue(result["legacy_unmapped"])
        self.assertIsNone(result["estimate"])

        def stale_prepare(**kwargs):
            context = prepare_student_diagnostic_submission(**kwargs)
            return replace(context, existing_binding=None)

        with patch(
            "api.pretest_views.prepare_student_diagnostic_submission",
            side_effect=stale_prepare,
        ):
            raced_replay = client.post(
                url,
                {
                    "paper_version_id": self.version.id,
                    "content_hash": self.version.content_hash,
                    "idempotency_key": "device-report",
                    "answers": {},
                    "opportunity_status": "device_issue",
                },
                format="json",
            )
            raced_conflict = client.post(
                url,
                {
                    "paper_version_id": self.version.id,
                    "content_hash": self.version.content_hash,
                    "idempotency_key": "device-report",
                    "answers": {str(self.question.id): "A"},
                    "opportunity_status": "device_issue",
                },
                format="json",
            )
        self.assertEqual(raced_replay.status_code, 200, raced_replay.data)
        self.assertTrue(raced_replay.data["data"]["idempotent_replay"])
        self.assertEqual(raced_conflict.status_code, 409, raced_conflict.data)
        self.assertEqual(
            PretestSubmission.objects.filter(administration=administration).count(),
            1,
        )
        self.assertEqual(
            DiagnosticSubmissionBinding.objects.filter(
                administration=administration
            ).count(),
            1,
        )

        first_submission = PretestSubmission.objects.get(
            administration=administration,
            attempt_no=1,
        )
        first_hash = first_submission.content_hash
        recovered = client.post(
            url,
            {
                "paper_version_id": self.version.id,
                "content_hash": self.version.content_hash,
                "idempotency_key": "device-recovery-observed",
                "answers": {str(self.question.id): "A"},
                "task_statuses": {str(self.question.id): "observed"},
            },
            format="json",
        )
        self.assertEqual(recovered.status_code, 200, recovered.data)
        attempts = list(
            PretestSubmission.objects.filter(administration=administration)
            .order_by("attempt_no")
            .values_list("attempt_no", "opportunity_status")
        )
        self.assertEqual(attempts, [(1, "device_issue"), (2, "observed")])
        first_submission.refresh_from_db()
        self.assertEqual(first_submission.content_hash, first_hash)
        replay = client.post(
            url,
            {
                "paper_version_id": self.version.id,
                "content_hash": self.version.content_hash,
                "idempotency_key": "device-recovery-observed",
                "answers": {str(self.question.id): "A"},
                "task_statuses": {str(self.question.id): "observed"},
            },
            format="json",
        )
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertTrue(replay.data["data"]["idempotent_replay"])
        after_completed = client.post(
            url,
            {
                "paper_version_id": self.version.id,
                "content_hash": self.version.content_hash,
                "idempotency_key": "third-attempt-after-complete",
                "answers": {str(self.question.id): "A"},
                "task_statuses": {str(self.question.id): "observed"},
            },
            format="json",
        )
        self.assertEqual(after_completed.status_code, 409, after_completed.data)
        self.assertEqual(
            PretestSubmission.objects.filter(administration=administration).count(),
            2,
        )
