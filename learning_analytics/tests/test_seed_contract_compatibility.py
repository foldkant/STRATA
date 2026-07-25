from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from courses.models import CourseClass
from learning.models import (
    LearningContentRecommendation,
    QuestionBankItem,
    QuestionBankItemVersion,
    StudentLearningTargetStateVersion,
    StudentMasterySnapshot,
    StudentMasteryTargetResult,
    TestAssessment,
)
from learning.services.mastery import (
    build_guarded_content_band_candidate,
    build_student_mastery_snapshot,
)
from learning_analytics.evaluation_models import EvaluationPlan, EvaluationStandard
from learning_analytics.services.evaluation import publish_plan
from learning_analytics.tests import test_learning_target_versions as target_fixture
from school.models import ClassGroup, StudentProfile


class EvaluationPilotSeedContractTests(TestCase):
    def setUp(self):
        target_fixture.LearningTargetVersionTests.setUp(self)

    def run_seed(self):
        output = StringIO()
        call_command(
            "seed_evaluation_pilot",
            teacher=self.teacher.username,
            course_id=self.course.id,
            curriculum_version_id=self.curriculum_version.id,
            stdout=output,
        )
        return output.getvalue()

    def test_seed_publishes_new_plan_and_standard_contract_idempotently(self):
        output = self.run_seed()
        plan = EvaluationPlan.objects.get(
            course=self.course,
            title="数据表达与解释试点评价方案",
        )
        standard = EvaluationStandard.objects.get(
            plan=plan,
            title="数据表达与解释评价标准",
        )

        self.assertEqual(plan.versions.count(), 1)
        self.assertEqual(standard.versions.count(), 1)
        version = plan.versions.get()
        self.assertEqual(len(version.learning_activities), 3)
        self.assertEqual(len(version.evaluation_tasks), 3)
        self.assertEqual(version.assessment_modes, ["project", "artifact"])
        self.assertEqual(version.learning_target_versions.count(), 4)
        self.assertTrue(
            all(
                len(row["curriculum_node_ids"]) == 4
                for row in version.learning_goals
            )
        )
        frozen_criteria = standard.versions.get().criteria.all()
        self.assertEqual(
            {
                task
                for row in frozen_criteria
                for task in row.evaluation_task_codes
            },
            {"T1", "T2", "T3"},
        )
        self.assertIn(str(self.curriculum_version.id), output)

        self.run_seed()
        self.assertEqual(plan.versions.count(), 1)
        self.assertEqual(standard.versions.count(), 1)


class MasteryAcceptanceSeedContractTests(TestCase):
    def setUp(self):
        target_fixture.LearningTargetVersionTests.setUp(self)
        type(self.school).objects.filter(pk=self.school.pk).update(is_synthetic=True)
        self.school.refresh_from_db()
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="掌握度种子验收班",
            grade="高一",
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        for index in range(3):
            student = User.objects.create_user(
                username=f"mastery_seed_student_{index}",
                password="Student123!",
                role=User.Role.STUDENT,
                school=self.school,
            )
            StudentProfile.objects.create(
                user=student,
                class_group=self.class_group,
                student_no=f"MS{index:02d}",
                is_first_use=False,
            )
        plan = target_fixture.LearningTargetVersionTests.create_plan(
            self,
            title="掌握度种子目标方案",
            goal_code="IT_MASTERY_01",
        )
        self.target_version = (
            publish_plan(plan, published_by=self.teacher)
            .version.learning_target_versions.get(code="IT_MASTERY_01")
        )

    def run_seed(self, *, clear=False):
        output = StringIO()
        call_command(
            "seed_mastery_pipeline_acceptance",
            school_code=self.school.code,
            confirmation="TEST-DATA-ONLY",
            student_limit=3,
            learning_target_version_id=self.target_version.id,
            clear=clear,
            stdout=output,
        )
        return output.getvalue()

    def test_seed_builds_exact_target_chain_and_clear_removes_dependents(self):
        self.run_seed()
        assessment = TestAssessment.objects.get(
            school=self.school,
            title__startswith="[TEST] 共同掌握夜间任务验收",
        )
        self.assertEqual(assessment.questions.count(), 30)
        self.assertEqual(assessment.common_question_set.items.count(), 30)
        self.assertTrue(
            all(
                row.source_version_id
                and row.learning_target_version_id == self.target_version.id
                and not row.legacy_unmapped
                for row in assessment.questions.all()
            )
        )
        self.assertEqual(
            QuestionBankItem.objects.filter(
                stem__startswith="[TEST-MASTERY]",
                learning_target_version=self.target_version,
                legacy_unmapped=False,
            ).count(),
            30,
        )
        self.assertEqual(
            QuestionBankItemVersion.objects.filter(
                learning_target_version=self.target_version,
                legacy_unmapped=False,
            ).count(),
            30,
        )

        snapshot = build_student_mastery_snapshot(
            attempt=assessment.attempts.order_by("id").first()
        )
        self.assertEqual(snapshot.data_status, StudentMasterySnapshot.DataStatus.AVAILABLE)
        self.assertFalse(snapshot.legacy_unmapped)
        result = snapshot.target_results.get()
        self.assertEqual(result.learning_target_version, self.target_version)
        decision = build_guarded_content_band_candidate(snapshot=snapshot)
        self.assertTrue(
            LearningContentRecommendation.objects.filter(
                source_decision=decision
            ).exists()
        )

        self.run_seed(clear=True)
        self.assertFalse(
            TestAssessment.objects.filter(
                school=self.school,
                title__startswith="[TEST] 共同掌握夜间任务验收",
            ).exists()
        )
        self.assertFalse(
            QuestionBankItem.objects.filter(stem__startswith="[TEST-MASTERY]").exists()
        )
        self.assertFalse(StudentMasterySnapshot.objects.filter(pk=snapshot.pk).exists())
        self.assertFalse(StudentMasteryTargetResult.objects.filter(pk=result.pk).exists())
        self.assertFalse(
            StudentLearningTargetStateVersion.objects.filter(
                source_type="common_assessment",
                source_id=str(result.id),
            ).exists()
        )
