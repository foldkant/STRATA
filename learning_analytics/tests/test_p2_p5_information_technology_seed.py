from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import User
from courses.models import Course, CourseClass, Subject
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumStandard,
    CurriculumStandardNode,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    SchoolStage,
)
from learning.models import DiagnosticAdministration, PretestPaper
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationStandard,
    EvaluationTrialRecord,
)
from learning_analytics.services.test_data_governance import (
    resolve_explicit_test_data_targets,
)
from school.models import ClassGroup, School


class InformationTechnologyAcceptanceSeedTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="信息科技验收学校",
            code="P2P5-SEED",
            is_synthetic=True,
        )
        self.admin = User.objects.create_user(
            username="p2p5_seed_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.teacher = User.objects.create_user(
            username="p2p5_seed_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="SEED-IT",
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与计算",
            teacher=self.teacher,
            is_active=True,
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一信息科技验收班",
            grade="高一",
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
        )
        standard = CurriculumStandard.objects.create(
            title="普通高中信息科技课程标准",
            document_type=CurriculumDocumentType.SUBJECT_STANDARD,
            school_stage=SchoolStage.SENIOR_HIGH,
            subject_code="information_technology",
            subject_name="信息科技",
            created_by=self.admin,
            updated_by=self.admin,
        )
        version = CurriculumStandardVersion.objects.create(
            source=standard,
            version_label="2025",
            publication_year=2025,
            effective_year=2025,
            title_snapshot=standard.title,
            official_title="普通高中信息科技课程标准（2025年修订）",
            document_type_snapshot=standard.document_type,
            school_stage_snapshot=standard.school_stage,
            subject_code_snapshot=standard.subject_code,
            subject_name_snapshot=standard.subject_name,
            pdf_file="curriculum_standards/tests/seed-it-2025.pdf",
            pdf_sha256="a" * 64,
            pdf_size_bytes=1024,
            pdf_page_count=80,
            content_hash="b" * 64,
            created_by=self.admin,
        )
        definitions = (
            (CurriculumNodeType.CORE_COMPETENCY, "IT.CORE", "核心素养"),
            (CurriculumNodeType.COURSE_OBJECTIVE, "IT.OBJECTIVE", "课程目标"),
            (CurriculumNodeType.COURSE_CONTENT, "IT.CONTENT", "课程内容"),
            (CurriculumNodeType.ACADEMIC_QUALITY, "IT.QUALITY", "学业质量"),
        )
        for index, (node_type, code, title) in enumerate(definitions, start=1):
            CurriculumStandardNode.objects.create(
                version=version,
                node_type=node_type,
                code=code,
                title=title,
                content=f"信息科技{title}原文内容，用于工程验收中的可追溯引用。",
                source_page_start=index,
                source_page_end=index,
                source_paragraph=title,
                sort_order=index,
            )
        CurriculumStandardVersion.objects.filter(pk=version.pk).update(
            status=CurriculumVersionStatus.PUBLISHED,
            reviewed_by=self.admin,
            published_by=self.admin,
        )
        CurriculumStandard.objects.filter(pk=standard.pk).update(current_version=version)

    def run_seed(self, *, publish_diagnostic=True):
        output = StringIO()
        options = {
            "school_code": self.school.code,
            "course_id": self.course.id,
            "class_group_ids": [self.class_group.id],
            "school_stage": SchoolStage.SENIOR_HIGH,
            "school_admin": self.admin.username,
            "confirmation": "SEED-P2-P5-INFORMATION-TECHNOLOGY",
            "stdout": output,
        }
        if publish_diagnostic:
            options["publish_diagnostic"] = True
        call_command("seed_p2_p5_information_technology", **options)
        return output.getvalue()

    def test_seed_builds_three_published_chains_and_is_idempotent(self):
        first_output = self.run_seed()
        plans = EvaluationPlan.objects.filter(
            school=self.school,
            course=self.course,
            title__startswith="【信息科技示例】",
        )
        standards = EvaluationStandard.objects.filter(
            school=self.school,
            course=self.course,
            title__startswith="【信息科技示例】",
        )
        self.assertEqual(plans.count(), 3)
        self.assertEqual(standards.count(), 3)
        self.assertTrue(all(plan.versions.count() == 1 for plan in plans))
        self.assertTrue(all(standard.versions.count() == 1 for standard in standards))
        project = plans.get(title__contains="项目式")
        self.assertEqual(len(project.evaluation_tasks), 2)
        self.assertEqual(
            {item["evidence_ownership"] for item in project.evaluation_tasks},
            {"individual", "group"},
        )
        paper = PretestPaper.objects.get(
            school=self.school,
            subject=self.subject,
            title__startswith="【信息科技示例】",
        )
        self.assertEqual(paper.status, PretestPaper.Status.PUBLISHED)
        self.assertEqual(paper.questions.count(), 4)
        self.assertEqual(paper.published_versions.count(), 1)
        self.assertTrue(
            all(
                question.learning_target_version_id
                and not question.legacy_unmapped
                for question in paper.questions.all()
            )
        )
        frozen_target_ids = {
            row["learning_target_version_id"]
            for row in paper.published_versions.get().question_snapshot
        }
        self.assertEqual(len(frozen_target_ids), 1)
        administration = DiagnosticAdministration.objects.get(
            school=self.school,
            course=self.course,
            purpose=DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
        )
        self.assertEqual(
            administration.paper_version,
            paper.published_versions.get(),
        )
        self.assertEqual(administration.status, DiagnosticAdministration.Status.PUBLISHED)
        self.assertEqual(administration.assignments.count(), 1)
        self.assertEqual(
            administration.assignments.get().class_group,
            self.class_group,
        )
        self.assertIn("学习起点诊断", first_output)

        registered_roots = resolve_explicit_test_data_targets(
            [
                *[
                    f"learning_analytics.EvaluationPlan:{plan.pk}"
                    for plan in plans.order_by("pk")
                ],
                *[
                    f"learning_analytics.EvaluationStandard:{standard.pk}"
                    for standard in standards.order_by("pk")
                ],
                f"learning.PretestPaper:{paper.pk}",
                f"learning.DiagnosticAdministration:{administration.pk}",
            ]
        )
        self.assertEqual(len(registered_roots), 8)

        self.run_seed()
        self.assertEqual(plans.count(), 3)
        self.assertEqual(standards.count(), 3)
        self.assertEqual(
            PretestPaper.objects.filter(
                school=self.school,
                subject=self.subject,
                title__startswith="【信息科技示例】",
            ).count(),
            1,
        )
        self.assertEqual(
            DiagnosticAdministration.objects.filter(
                school=self.school,
                course=self.course,
                purpose=DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
            ).count(),
            1,
        )

    def test_seed_rejects_a_class_outside_the_course_without_partial_data(self):
        unrelated_class = ClassGroup.objects.create(
            school=self.school,
            name="未关联验收班",
            grade="高一",
        )
        with self.assertRaises(CommandError):
            call_command(
                "seed_p2_p5_information_technology",
                school_code=self.school.code,
                course_id=self.course.id,
                class_group_ids=[unrelated_class.id],
                school_stage=SchoolStage.SENIOR_HIGH,
                school_admin=self.admin.username,
                publish_diagnostic=True,
                confirmation="SEED-P2-P5-INFORMATION-TECHNOLOGY",
            )
        self.assertFalse(EvaluationPlan.objects.filter(school=self.school).exists())
        self.assertFalse(PretestPaper.objects.filter(school=self.school).exists())

    def test_seed_defaults_the_diagnostic_administration_to_draft(self):
        self.run_seed(publish_diagnostic=False)
        administration = DiagnosticAdministration.objects.get(
            school=self.school,
            course=self.course,
        )
        self.assertEqual(
            administration.status,
            DiagnosticAdministration.Status.DRAFT,
        )

    def test_seed_refuses_a_non_synthetic_school_before_writing(self):
        School.objects.filter(pk=self.school.pk).update(is_synthetic=False)
        with self.assertRaises(CommandError):
            self.run_seed()
        self.assertFalse(EvaluationPlan.objects.filter(school=self.school).exists())
        self.assertFalse(PretestPaper.objects.filter(school=self.school).exists())

    def test_evaluation_only_can_add_clearly_labelled_examples_to_development_school(self):
        School.objects.filter(pk=self.school.pk).update(is_synthetic=False)
        call_command(
            "seed_p2_p5_information_technology",
            school_code=self.school.code,
            course_id=self.course.id,
            school_stage=SchoolStage.SENIOR_HIGH,
            school_admin=self.admin.username,
            evaluation_only=True,
            allow_non_synthetic=True,
            confirmation="SEED-P2-P5-INFORMATION-TECHNOLOGY",
        )
        self.assertEqual(
            EvaluationPlan.objects.filter(
                school=self.school,
                title__startswith="【信息科技示例】",
            ).count(),
            3,
        )
        self.assertEqual(
            EvaluationStandard.objects.filter(
                school=self.school,
                title__startswith="【信息科技示例】",
            ).count(),
            3,
        )
        self.assertEqual(
            EvaluationTrialRecord.objects.filter(
                school=self.school,
                title__startswith="【信息科技示例】",
            ).count(),
            1,
        )
        self.assertFalse(PretestPaper.objects.filter(school=self.school).exists())
