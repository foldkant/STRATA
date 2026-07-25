from __future__ import annotations

import importlib
from datetime import timedelta
from types import SimpleNamespace

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, CourseClass, Subject
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumStandard,
    CurriculumStandardNode,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    EvaluationPlanCurriculumReference,
    SchoolStage,
)
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationStandard,
)
from learning_analytics.services.evaluation import (
    confirm_plan_review,
    confirm_standard_review,
    publish_plan,
    publish_standard,
)
from learning.models import (
    ContentBandPolicyVersion,
    DiagnosticAdministration,
    PretestPaper,
    PretestPaperVersion,
    PretestQuestion,
    PretestSubmission,
    StratificationDecision,
    StudentLearningTargetStateVersion,
    UnifiedAssessmentMaterial,
)
from learning.services.diagnostic_administrations import (
    create_diagnostic_administration,
    publish_diagnostic_administration,
    replace_diagnostic_assignments,
)
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from learning_analytics.target_models import (
    EvaluationBasisLearningTarget,
    EvaluationCriterionLearningTarget,
    EvaluationTaskLearningTarget,
    LearningActivityLearningTarget,
    LearningTarget,
    LearningTargetAlignmentStatus,
    LearningTargetBackfillIssue,
    LearningTargetCurriculumAlignment,
    LearningTargetVersion,
)
from school.models import ClassGroup, School, StudentProfile


class LearningTargetVersionTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="目标版本测试学校", code="TARGET-VERSION")
        self.subject = Subject.objects.create(
            school=self.school,
            name="Information Technology",
            code="IT",
        )
        self.teacher = User.objects.create_user(
            username="target_version_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.admin = User.objects.create_user(
            username="target_version_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="Data and Computing",
            teacher=self.teacher,
            is_active=True,
        )
        standard = CurriculumStandard.objects.create(
            title="Information Technology Curriculum Standard",
            document_type=CurriculumDocumentType.SUBJECT_STANDARD,
            school_stage=SchoolStage.SENIOR_HIGH,
            subject_code="information_technology",
            subject_name="Information Technology",
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.curriculum_version = CurriculumStandardVersion.objects.create(
            source=standard,
            version_label="2025",
            publication_year=2025,
            effective_year=2025,
            title_snapshot=standard.title,
            official_title="Information Technology Curriculum Standard (2025)",
            document_type_snapshot=standard.document_type,
            school_stage_snapshot=standard.school_stage,
            subject_code_snapshot=standard.subject_code,
            subject_name_snapshot=standard.subject_name,
            pdf_file="curriculum_standards/tests/it-2025.pdf",
            pdf_sha256="1" * 64,
            pdf_size_bytes=1024,
            pdf_page_count=100,
            content_hash="2" * 64,
            created_by=self.admin,
        )
        node_specs = (
            (CurriculumNodeType.CORE_COMPETENCY, "IT.CORE", "Core competency"),
            (CurriculumNodeType.COURSE_OBJECTIVE, "IT.OBJECTIVE", "Course objective"),
            (CurriculumNodeType.COURSE_CONTENT, "IT.CONTENT", "Course content"),
            (CurriculumNodeType.ACADEMIC_QUALITY, "IT.QUALITY", "Academic quality"),
        )
        self.nodes = []
        for sort_order, (node_type, code, title) in enumerate(node_specs, start=1):
            self.nodes.append(
                CurriculumStandardNode.objects.create(
                    version=self.curriculum_version,
                    node_type=node_type,
                    code=code,
                    title=title,
                    content=f"Published source text for {title} and data representation.",
                    source_page_start=sort_order,
                    source_page_end=sort_order,
                    source_paragraph=title,
                    sort_order=sort_order,
                )
            )
        CurriculumStandardVersion.objects.filter(pk=self.curriculum_version.pk).update(
            status=CurriculumVersionStatus.PUBLISHED,
            reviewed_by=self.admin,
            published_by=self.admin,
        )
        CurriculumStandard.objects.filter(pk=standard.pk).update(
            current_version=self.curriculum_version
        )
        self.curriculum_version.refresh_from_db()

    def create_plan(
        self,
        *,
        title="Data representation evaluation plan",
        goal_code="IT_DATA_01",
        goal_node_ids=None,
    ) -> EvaluationPlan:
        if goal_node_ids is None:
            goal_node_ids = [node.id for node in self.nodes]
        plan = EvaluationPlan.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            title=title,
            content_version="2026.1",
            target_students="Grade 10 students studying data representation",
            learning_goal="Students select a representation and explain why it fits the problem.",
            learning_goals=[
                {
                    "code": goal_code,
                    "title": "Representation selection",
                    "description": "The student selects and justifies a defensible representation for the data problem.",
                    "curriculum_node_ids": goal_node_ids,
                }
            ],
            evaluation_basis=[
                {
                    "code": "B1",
                    "goal_codes": [goal_code],
                    "description": "The artifact and explanation jointly demonstrate the intended learning target.",
                    "source_types": ["student artifact", "written explanation"],
                }
            ],
            learning_activities=[
                {
                    "code": "A1",
                    "title": "Campus data inquiry",
                    "goal_codes": [goal_code],
                    "description": "Students create a visualization and explain their visual encoding choices.",
                }
            ],
            evaluation_tasks=[
                {
                    "code": "T1",
                    "title": "Data visualization artifact",
                    "goal_codes": [goal_code],
                    "activity_codes": ["A1"],
                    "mode": "project",
                    "evidence_ownership": "individual",
                    "material_types": ["artifact"],
                    "weight": 100,
                    "description": "Submit the visualization artifact and a reasoned design explanation.",
                }
            ],
            assessment_modes=["project"],
            content_scope=["data representation", "visual encoding"],
            thinking_requirements=["apply", "analyze"],
            support_options=["teacher-provided data dictionary"],
            scoring_rules={
                "approach": "separate criteria",
                "decision_rule": "Interpret each criterion separately and never turn missing evidence into a low score.",
            },
            follow_up_suggestion="Use the evidenced learning need to select the next feedback prompt.",
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        for node in self.nodes:
            EvaluationPlanCurriculumReference.objects.create(
                plan=plan,
                node=node,
                alignment_explanation="This source passage directly supports the stated learning target.",
                created_by=self.teacher,
            )
        confirm_plan_review(plan=plan, reviewed_by=self.teacher)
        return plan

    def create_standard(self, plan: EvaluationPlan) -> EvaluationStandard:
        plan_version = plan.versions.order_by("-version_no", "-id").first()
        standard = EvaluationStandard.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            plan=plan,
            plan_version=plan_version,
            title="Data representation evaluation standard",
            evaluation_target="The submitted visualization and design explanation",
            criteria=[
                {
                    "code": "D1",
                    "dimension": "subject_practice",
                    "title": "Representation reasoning",
                    "evaluation_target": "The submitted visualization and explanation",
                    "evaluation_sources": ["visualization artifact", "written explanation"],
                    "learning_goal_codes": ["IT_DATA_01"],
                    "evaluation_task_codes": ["T1"],
                    "evidence_ownership": "individual",
                    "material_types": ["artifact"],
                    "expected_performance": "The student links data characteristics, encoding choices, and the intended reader.",
                    "skip_condition": "Do not evaluate when no visualization or explanation is available.",
                    "support_options": ["data dictionary"],
                    "common_problems": ["A polished chart alone does not demonstrate reasoning."],
                    "level_descriptions": {
                        "1": "The representation conflicts with the data type and no defensible reason is provided.",
                        "2": "The representation is partly usable but the explanation relies on preference only.",
                        "3": "The representation fits the main data type and gives one relevant reason.",
                        "4": "The representation fits the data and audience with connected design reasons.",
                        "5": "The representation is precise and evaluates alternatives and trade-offs.",
                    },
                    "scoring_examples": [
                        {
                            "level": 2,
                            "title": "Preference-only explanation",
                            "example_description": "The chart is readable but the student only says it looks better.",
                            "file_reference": "anchor-D1-L2",
                        },
                        {
                            "level": 4,
                            "title": "Connected encoding explanation",
                            "example_description": "The student connects variables, encodings, and audience needs.",
                            "file_reference": "anchor-D1-L4",
                        },
                    ],
                    "follow_up_suggestion": "Ask the student to compare the choice with one plausible alternative.",
                }
            ],
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        confirm_standard_review(standard=standard, reviewed_by=self.teacher)
        return standard

    def test_publish_builds_complete_relation_chain_and_is_idempotent(self):
        plan = self.create_plan()

        first = publish_plan(plan, published_by=self.teacher)
        second = publish_plan(plan, published_by=self.teacher)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.version.id, second.version.id)
        target_version = LearningTargetVersion.objects.get(
            plan_version=first.version,
            code="IT_DATA_01",
        )
        self.assertEqual(
            target_version.alignment_status,
            LearningTargetAlignmentStatus.COMPLETE,
        )
        alignments = list(
            target_version.curriculum_alignments.select_related("plan_reference")
        )
        self.assertEqual(len(alignments), 4)
        self.assertEqual(
            {link.plan_reference.node_type for link in alignments},
            {
                CurriculumNodeType.CORE_COMPETENCY,
                CurriculumNodeType.COURSE_OBJECTIVE,
                CurriculumNodeType.COURSE_CONTENT,
                CurriculumNodeType.ACADEMIC_QUALITY,
            },
        )
        self.assertEqual(EvaluationBasisLearningTarget.objects.count(), 1)
        self.assertEqual(LearningActivityLearningTarget.objects.count(), 1)
        self.assertEqual(EvaluationTaskLearningTarget.objects.count(), 1)

        standard = self.create_standard(plan)
        standard_first = publish_standard(standard, published_by=self.teacher)
        standard_second = publish_standard(standard, published_by=self.teacher)
        self.assertTrue(standard_first.created)
        self.assertFalse(standard_second.created)
        criterion_link = EvaluationCriterionLearningTarget.objects.get()
        self.assertEqual(criterion_link.target_version_id, target_version.id)
        self.assertEqual(LearningTarget.objects.count(), 1)
        self.assertEqual(LearningTargetVersion.objects.count(), 1)

    def test_logical_key_is_shared_across_plans_and_versions_in_same_course(self):
        first_plan = self.create_plan(title="Project evaluation plan")
        first_version = publish_plan(first_plan, published_by=self.teacher).version
        first_target_version = first_version.learning_target_versions.get(
            code="IT_DATA_01"
        )

        second_plan = self.create_plan(title="Operation evaluation plan")
        second_version = publish_plan(second_plan, published_by=self.teacher).version
        second_target_version = second_version.learning_target_versions.get(
            code="IT_DATA_01"
        )

        self.assertEqual(first_target_version.target_id, second_target_version.target_id)
        self.assertEqual(first_target_version.target.logical_key, second_target_version.target.logical_key)
        self.assertEqual(second_target_version.version_no, 2)
        self.assertNotEqual(first_target_version.content_hash, second_target_version.content_hash)

        second_plan.content_version = "2026.2"
        second_plan.learning_goals = [
            {
                **second_plan.learning_goals[0],
                "description": "The student compares alternatives before selecting and justifying a representation.",
            }
        ]
        second_plan.save()
        confirm_plan_review(plan=second_plan, reviewed_by=self.teacher)
        third_version = publish_plan(second_plan, published_by=self.teacher).version
        third_target_version = third_version.learning_target_versions.get(
            code="IT_DATA_01"
        )
        self.assertEqual(third_target_version.target_id, first_target_version.target_id)
        self.assertEqual(third_target_version.version_no, 3)
        self.assertNotEqual(third_target_version.content_hash, second_target_version.content_hash)

    def test_each_target_must_cover_the_full_curriculum_standard_chain(self):
        with self.assertRaisesMessage(ValidationError, "尚缺"):
            self.create_plan(goal_node_ids=[self.nodes[0].id])

        self.assertFalse(EvaluationPlan.objects.get().versions.exists())
        self.assertFalse(LearningTarget.objects.exists())

    def test_published_target_records_reject_update_delete_and_cross_version_link(self):
        first_plan = self.create_plan(title="First plan")
        first_version = publish_plan(first_plan, published_by=self.teacher).version
        first_target_version = first_version.learning_target_versions.get()
        first_alignment = first_target_version.curriculum_alignments.first()

        first_target_version.title = "Changed title"
        with self.assertRaisesMessage(ValidationError, "不可修改"):
            first_target_version.save()
        with self.assertRaisesMessage(ValidationError, "不可删除"):
            first_target_version.delete()
        with self.assertRaisesMessage(ValidationError, "不可删除"):
            first_alignment.delete()

        second_plan = self.create_plan(title="Second plan")
        second_version = publish_plan(second_plan, published_by=self.teacher).version
        second_reference = second_version.curriculum_references.first()
        invalid_alignment = LearningTargetCurriculumAlignment(
            target_version=first_target_version,
            plan_reference=second_reference,
            sort_order=99,
        )
        with self.assertRaisesMessage(ValidationError, "同一评价方案版本"):
            invalid_alignment.save()

        invalid_task_link = EvaluationTaskLearningTarget(
            plan_version=second_version,
            task_code="T1",
            target_version=first_target_version,
            sort_order=0,
        )
        with self.assertRaisesMessage(ValidationError, "同一方案版本"):
            invalid_task_link.save()

    def test_data_migration_rebuilds_and_reverses_complete_historical_chain(self):
        plan = self.create_plan()
        plan_version = publish_plan(plan, published_by=self.teacher).version
        standard = self.create_standard(plan)
        standard_version = publish_standard(
            standard, published_by=self.teacher
        ).version

        EvaluationCriterionLearningTarget.objects.all().delete()
        EvaluationTaskLearningTarget.objects.all().delete()
        LearningActivityLearningTarget.objects.all().delete()
        EvaluationBasisLearningTarget.objects.all().delete()
        LearningTargetCurriculumAlignment.objects.all().delete()
        LearningTargetVersion.objects.all().delete()
        LearningTarget.objects.all().delete()

        migration = importlib.import_module(
            "learning_analytics.migrations.0034_learningtarget_learningtargetbackfillissue_and_more"
        )
        schema_editor = SimpleNamespace(connection=connection)
        migration.backfill_learning_target_versions(apps, schema_editor)

        target_version = LearningTargetVersion.objects.get(
            plan_version=plan_version,
            code="IT_DATA_01",
        )
        self.assertEqual(target_version.alignment_status, "complete")
        self.assertEqual(target_version.curriculum_alignments.count(), 4)
        self.assertTrue(
            EvaluationBasisLearningTarget.objects.filter(
                plan_version=plan_version,
                target_version=target_version,
                basis_code="B1",
            ).exists()
        )
        self.assertTrue(
            LearningActivityLearningTarget.objects.filter(
                plan_version=plan_version,
                target_version=target_version,
                activity_code="A1",
            ).exists()
        )
        self.assertTrue(
            EvaluationTaskLearningTarget.objects.filter(
                plan_version=plan_version,
                target_version=target_version,
                task_code="T1",
            ).exists()
        )
        self.assertTrue(
            EvaluationCriterionLearningTarget.objects.filter(
                criterion__standard_version=standard_version,
                target_version=target_version,
            ).exists()
        )
        self.assertFalse(LearningTargetBackfillIssue.objects.exists())

        migration.reverse_learning_target_backfill(apps, schema_editor)
        self.assertFalse(LearningTarget.objects.exists())
        self.assertTrue(plan.versions.filter(pk=plan_version.pk).exists())
        self.assertTrue(standard.versions.filter(pk=standard_version.pk).exists())

        incomplete_goals = [dict(plan_version.learning_goals[0])]
        incomplete_goals[0]["curriculum_node_ids"] = [self.nodes[0].id]
        type(plan_version).objects.filter(pk=plan_version.pk).update(
            learning_goals=incomplete_goals
        )
        migration.backfill_learning_target_versions(apps, schema_editor)
        incomplete_target_version = LearningTargetVersion.objects.get(
            plan_version=plan_version,
            code="IT_DATA_01",
        )
        self.assertEqual(
            incomplete_target_version.alignment_status,
            LearningTargetAlignmentStatus.LEGACY_INCOMPLETE,
        )
        self.assertEqual(
            list(
                incomplete_target_version.curriculum_alignments.values_list(
                    "plan_reference__node_id", flat=True
                )
            ),
            [self.nodes[0].id],
        )
        self.assertTrue(
            LearningTargetBackfillIssue.objects.filter(
                plan_version=plan_version,
                source_code="IT_DATA_01",
                reason="curriculum_chain_incomplete",
            ).exists()
        )
        migration.reverse_learning_target_backfill(apps, schema_editor)

    def test_real_diagnostic_submission_review_and_candidate_preserve_exact_target_chain(self):
        """Exercise the product APIs instead of manufacturing an available state."""

        plan_version = publish_plan(
            self.create_plan(title="Diagnostic target plan"),
            published_by=self.teacher,
        ).version
        target_version = plan_version.learning_target_versions.get(code="IT_DATA_01")
        class_group = ClassGroup.objects.create(
            school=self.school,
            name="Grade 10 diagnostic class",
            grade="Grade 10",
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=class_group,
            created_by=self.teacher,
        )
        student = User.objects.create_user(
            username="target_version_diagnostic_student",
            password="Student123!",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(user=student, class_group=class_group)
        paper = PretestPaper.objects.create(
            school=self.school,
            subject=self.subject,
            title="Exact target learning-entry diagnostic",
            kind=PretestPaper.Kind.LITERACY,
            version=1,
            status=PretestPaper.Status.PUBLISHED,
            created_by=self.admin,
            published_at=timezone.now(),
        )
        questions = [
            PretestQuestion.objects.create(
                paper=paper,
                stem=f"Explain a defensible data representation decision in context {index}.",
                question_type=PretestQuestion.QuestionType.TEXT,
                answer=[],
                score=10,
                dimension="data representation reasoning",
                learning_target_code=target_version.code,
                learning_target_name=target_version.title,
                learning_target_version=target_version,
                legacy_unmapped=False,
                material_requirements=["individual written explanation"],
                sort_order=index,
                is_required=True,
            )
            for index in range(1, 8)
        ]
        question_snapshot = [
            {
                "id": question.id,
                "stem": question.stem,
                "question_type": question.question_type,
                "options": [],
                "answer": [],
                "score": question.score,
                "dimension": question.dimension,
                "learning_target_code": target_version.code,
                "learning_target_name": target_version.title,
                "learning_target_version_id": target_version.id,
                "learning_target_version_hash": target_version.content_hash,
                "legacy_unmapped": False,
                "material_requirements": question.material_requirements,
                "sort_order": question.sort_order,
                "is_required": True,
            }
            for question in questions
        ]
        paper_version = PretestPaperVersion.objects.create(
            source=paper,
            version_no=1,
            title=paper.title,
            kind=paper.kind,
            introduction="Seven independent task contexts support a conservative initial estimate.",
            question_snapshot=question_snapshot,
            published_by=self.admin,
        )
        administration = create_diagnostic_administration(
            school=self.school,
            actor=self.admin,
            payload={
                "subject_id": self.subject.id,
                "paper_version_id": paper_version.id,
                "purpose": DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
                "batch_code": "IT-ENTRY-EXACT-01",
                "title": "Exact-target learning-entry diagnostic batch",
                "open_at": (timezone.now() - timedelta(hours=1)).isoformat(),
                "close_at": (timezone.now() + timedelta(days=7)).isoformat(),
            },
        )
        self.assertEqual(administration.course_id, self.course.id)
        replace_diagnostic_assignments(
            administration_id=administration.id,
            school=self.school,
            payload={
                "assignments": [
                    {
                        "class_group_id": class_group.id,
                        "cohort_role": "unassigned",
                        "opportunity_status": "offered",
                    }
                ]
            },
        )
        administration = publish_diagnostic_administration(
            administration_id=administration.id,
            school=self.school,
            actor=self.admin,
        )
        policy = ContentBandPolicyVersion.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            name="Diagnostic exact-target content-band policy",
            version_no=1,
            policy_version="diagnostic-exact-target-v1",
            a_min=0.8,
            b_min=0.6,
            boundary_margin=0.01,
            hysteresis_margin=0.01,
            max_measurement_error=0.2,
            min_common_items=7,
            min_answered_ratio=1,
            required_consecutive_windows=1,
            cooldown_days=0,
            max_step_change=1,
            status=ContentBandPolicyVersion.Status.ACTIVE,
            created_by=self.admin,
            published_by=self.admin,
            published_at=timezone.now(),
        )
        sync_event_schema_definitions()
        client = APIClient()
        client.force_authenticate(self.admin)
        target_options = client.get(
            "/api/v1/school-admin/pretests/learning-target-versions/",
            {"subject": self.subject.id},
        )
        self.assertEqual(target_options.status_code, 200, target_options.data)
        selected_option = next(
            item
            for item in target_options.data["data"]
            if item["id"] == target_version.id
        )
        self.assertEqual(selected_option["content_hash"], target_version.content_hash)
        self.assertEqual(
            selected_option["logical_key"], str(target_version.target.logical_key)
        )
        self.assertEqual(selected_option["course"]["id"], self.course.id)
        client.force_authenticate(student)
        answers = {
            str(question.id): f"Context {question.sort_order}: representation is justified by data type and audience."
            for question in questions
        }
        task_statuses = {str(question.id): "observed" for question in questions}
        submitted = client.post(
            f"/api/v1/student/diagnostic-administrations/{administration.id}/paper/",
            {
                "paper_version_id": paper_version.id,
                "content_hash": paper_version.content_hash,
                "answers": answers,
                "task_statuses": task_statuses,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="exact-target-real-api-submit-1",
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        submission = PretestSubmission.objects.get(
            pk=submitted.data["data"]["id"]
        )
        self.assertEqual(submission.administration_id, administration.id)
        target_result = submission.target_results[0]
        self.assertEqual(target_result["learning_target_version_id"], target_version.id)
        self.assertEqual(
            target_result["learning_target_version_hash"], target_version.content_hash
        )
        self.assertEqual(
            target_result["learning_target_logical_key"],
            str(target_version.target.logical_key),
        )
        self.assertFalse(target_result["legacy_unmapped"])

        initial_state = StudentLearningTargetStateVersion.objects.get(
            source_type="learning_entry_diagnostic",
            source_id=str(submission.id),
            learning_target_version=target_version,
        )
        initial_hash = initial_state.content_hash
        self.assertEqual(
            initial_state.evidence_status,
            StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW,
        )
        self.assertTrue(initial_state.source_version.startswith(administration.content_hash))
        self.assertFalse(initial_state.legacy_unmapped)
        materials = list(
            UnifiedAssessmentMaterial.objects.filter(
                source_type="learning_entry_diagnostic",
                source_id=str(submission.id),
                learning_target_version=target_version,
            ).order_by("id")
        )
        self.assertEqual(len(materials), 7)
        self.assertTrue(all(not item.legacy_unmapped for item in materials))
        self.assertTrue(
            all(
                item.content["administration_content_hash"] == administration.content_hash
                and item.content["learning_target_version_hash"]
                == target_version.content_hash
                for item in materials
            )
        )

        client.force_authenticate(self.admin)
        final_review = None
        first_review_decision_id = None
        for index, material in enumerate(materials):
            final_review = client.post(
                f"/api/v1/school-admin/pretest-materials/{material.material_id}/review/",
                {
                    "score": 10,
                    "score_max": 10,
                    "feedback": "The explanation links the representation to data and audience.",
                },
                format="json",
            )
            self.assertEqual(final_review.status_code, 200, final_review.data)
            if index == 0:
                first_recommendation = final_review.data["data"][
                    "learning_content_recommendation"
                ]
                self.assertEqual(first_recommendation["status"], "not_suggested")
                first_review_decision_id = first_recommendation["decision_id"]
        self.assertEqual(
            final_review.data["data"]["learning_content_recommendation"]["status"],
            "pending_teacher_review",
        )

        initial_state.refresh_from_db()
        self.assertEqual(initial_state.content_hash, initial_hash)
        self.assertEqual(
            initial_state.evidence_status,
            StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW,
        )
        appended_states = StudentLearningTargetStateVersion.objects.filter(
            source_type="learning_entry_diagnostic_review",
            source_id=str(submission.id),
            learning_target_version=target_version,
        ).order_by("observed_at", "id")
        self.assertEqual(appended_states.count(), 7)
        latest_state = appended_states.last()
        self.assertEqual(
            latest_state.evidence_status,
            StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE,
        )
        self.assertEqual(latest_state.estimate, 1)
        self.assertEqual(latest_state.uncertainty, 0.188982)
        self.assertFalse(latest_state.legacy_unmapped)
        self.assertTrue(latest_state.source_version.startswith(administration.content_hash))
        self.assertIn("method=conservative_task_coverage_se_v1", " ".join(latest_state.observation_notes))
        score_materials = UnifiedAssessmentMaterial.objects.filter(
            source_type="learning_entry_diagnostic_review",
            learning_target_version=target_version,
        )
        self.assertEqual(score_materials.count(), 7)
        self.assertTrue(
            all(
                item.source_version.startswith(administration.content_hash)
                and item.content["administration_id"] == administration.id
                and item.content["administration_content_hash"]
                == administration.content_hash
                and item.content["learning_target_version_hash"]
                == target_version.content_hash
                and item.content["legacy_unmapped"] is False
                for item in score_materials
            )
        )
        decision = StratificationDecision.objects.get(
            pk=final_review.data["data"]["learning_content_recommendation"]["decision_id"]
        )
        first_review_decision = StratificationDecision.objects.get(
            pk=first_review_decision_id
        )
        self.assertEqual(
            first_review_decision.status,
            StratificationDecision.Status.DEFERRED,
        )
        self.assertIn("diagnostic_grading_pending", first_review_decision.missing_data)
        self.assertEqual(decision.status, StratificationDecision.Status.PENDING)
        self.assertEqual(decision.suggested_layer, "A")
        self.assertEqual(decision.policy_id, policy.id)
        self.assertEqual(
            decision.learning_summary["administration_hash"], administration.content_hash
        )
        self.assertEqual(decision.learning_summary["target_version_ids"], [target_version.id])
