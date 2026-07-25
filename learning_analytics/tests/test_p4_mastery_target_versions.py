from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import CourseClass
from learning.models import (
    CommonQuestionSet,
    CommonQuestionSetItem,
    ContentBandPolicyVersion,
    DiagnosticAdministration,
    DiagnosticAdministrationAssignment,
    DiagnosticSubmissionBinding,
    LearningContentRecommendation,
    QuestionBankItem,
    PretestPaper,
    PretestPaperVersion,
    PretestSubmission,
    StratificationDecision,
    StudentLearningTargetStateVersion,
    StudentMasterySnapshot,
    StudentSubjectBand,
    TestAssessment,
    TestAssessmentQuestion,
    TestAttempt,
    TestAttemptAnswer,
    UnifiedAssessmentMaterial,
)
from learning.services.mastery import (
    build_guarded_content_band_candidate,
    build_initial_diagnostic_content_band_candidate,
    build_student_mastery_snapshot,
)
from learning.services.bands import apply_student_subject_band
from learning.services.diagnostic_administrations import (
    publish_diagnostic_administration,
)
from learning.services.question_bank import ensure_question_version
from learning_analytics.services.evaluation import publish_plan
from learning_analytics.tests import test_learning_target_versions as target_fixture
from school.models import ClassGroup, StudentProfile, TeachingAssignment


class P4MasteryTargetVersionTests(TestCase):
    def setUp(self):
        # Reuse the complete four-node curriculum-standard fixture, while this
        # class keeps its own focused tests instead of inheriting that suite.
        target_fixture.LearningTargetVersionTests.setUp(self)
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一目标证据班",
            grade="高一",
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        TeachingAssignment.objects.get_or_create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.student = User.objects.create_user(
            username="mastery_target_student",
            password="Student123!",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
        )
        first_plan = target_fixture.LearningTargetVersionTests.create_plan(
            self,
            title="共同题学习目标一",
            goal_code="IT_DATA_01",
        )
        second_plan = target_fixture.LearningTargetVersionTests.create_plan(
            self,
            title="共同题学习目标二",
            goal_code="IT_DATA_02",
        )
        self.target_versions = [
            publish_plan(first_plan, published_by=self.teacher)
            .version.learning_target_versions.get(code="IT_DATA_01"),
            publish_plan(second_plan, published_by=self.teacher)
            .version.learning_target_versions.get(code="IT_DATA_02"),
        ]
        self.question_set = CommonQuestionSet.objects.create(
            school=self.school,
            subject=self.subject,
            title="目标级共同题",
            grade_scope="高一",
            term="上学期",
            version_no=1,
            measurement_series="IT-TARGET-MASTERY-01",
            version_purpose=CommonQuestionSet.VersionPurpose.BASELINE,
            content_hash="c" * 64,
            status=CommonQuestionSet.Status.ACTIVE,
            created_by=self.teacher,
            published_by=self.teacher,
            published_at=timezone.now(),
        )
        self.assessment = TestAssessment.objects.create(
            school=self.school,
            teacher=self.teacher,
            subject=self.subject,
            course=self.course,
            common_question_set=self.question_set,
            common_set_version=1,
            common_set_hash=self.question_set.content_hash,
            title="目标级共同测试",
            status=TestAssessment.Status.DRAFT,
        )
        self.assessment.target_classes.add(self.class_group)
        self.assessment_questions = []
        tasks_per_target = 7
        for target_index, target_version in enumerate(self.target_versions, start=1):
            for task_index in range(1, tasks_per_target + 1):
                sort_order = ((target_index - 1) * tasks_per_target + task_index) * 10
                question = QuestionBankItem.objects.create(
                    school=self.school,
                    subject=self.subject,
                    creator=self.teacher,
                    stem=f"目标 {target_index} 共同题 {task_index}",
                    question_type=QuestionBankItem.QuestionType.SINGLE,
                    options=["A", "B"],
                    answer=["A"],
                    difficulty=QuestionBankItem.Difficulty.NORMAL,
                    knowledge_point=f"旧展示标签 {target_index}",
                    default_score=10,
                    status=QuestionBankItem.Status.ACTIVE,
                    library_scope=QuestionBankItem.LibraryScope.SCHOOL,
                    item_role=QuestionBankItem.ItemRole.COMMON,
                    comparison_code=f"IT-COMMON-{target_index}-{task_index}",
                    learning_target_version=target_version,
                    legacy_unmapped=False,
                )
                version = ensure_question_version(question, actor=self.teacher)
                CommonQuestionSetItem.objects.create(
                    question_set=self.question_set,
                    question_version=version,
                    comparison_code=question.comparison_code,
                    required=True,
                    sort_order=sort_order,
                )
                self.assessment_questions.append(
                    TestAssessmentQuestion.objects.create(
                        assessment=self.assessment,
                        source_question=question,
                        source_version=version,
                        source_status=question.status,
                        question_type=question.question_type,
                        stem=question.stem,
                        options=question.options,
                        answer=question.answer,
                        score=10,
                        sort_order=sort_order,
                        item_role=QuestionBankItem.ItemRole.COMMON,
                        comparison_code=question.comparison_code,
                        learning_target_version=target_version,
                        legacy_unmapped=False,
                    )
                )
        self.assessment.status = TestAssessment.Status.CLOSED
        self.assessment.closed_at = timezone.now()
        self.assessment.save(update_fields=["status", "closed_at", "updated_at"])
        now = timezone.now()
        self.attempt = TestAttempt.objects.create(
            assessment=self.assessment,
            student=self.student,
            class_group=self.class_group,
            status=TestAttempt.Status.GRADED,
            submitted_at=now,
            graded_at=now,
        )
        self.answers = [
            TestAttemptAnswer.objects.create(
                attempt=self.attempt,
                question=question,
                answer=["A"],
                auto_score=10,
                is_correct=True,
            )
            for question in self.assessment_questions
        ]
        self.policy = ContentBandPolicyVersion.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            name="目标级内容层级标准",
            version_no=1,
            policy_version="target-policy-v1",
            a_min=0.8,
            b_min=0.6,
            boundary_margin=0.01,
            hysteresis_margin=0.01,
            max_measurement_error=0.2,
            min_common_items=2,
            min_answered_ratio=1,
            required_consecutive_windows=1,
            cooldown_days=0,
            status=ContentBandPolicyVersion.Status.ACTIVE,
            created_by=self.teacher,
            published_by=self.teacher,
            published_at=now,
        )

    def test_exact_target_results_form_multi_target_candidate(self):
        snapshot = build_student_mastery_snapshot(attempt=self.attempt)
        self.assertFalse(snapshot.legacy_unmapped)
        self.assertEqual(snapshot.knowledge_results, [])
        self.assertEqual(snapshot.target_results.count(), 2)
        self.assertGreater(snapshot.measurement_error, 0)
        self.assertEqual(
            snapshot.comparability_evidence["uncertainty_method"],
            "conservative_task_coverage_se_v1",
        )
        self.assertTrue(
            all(
                result.measurement_error and result.measurement_error > 0
                and result.evidence_snapshot["uncertainty_method"]
                == "conservative_task_coverage_se_v1"
                and result.evidence_snapshot["uncertainty_observed_task_count"] == 7
                for result in snapshot.target_results.all()
            )
        )

        decision = build_guarded_content_band_candidate(
            snapshot=snapshot,
            policy=self.policy,
        )
        recommendation = LearningContentRecommendation.objects.get(
            source_decision=decision
        )
        states = list(recommendation.target_states.order_by("learning_target_code"))
        self.assertEqual(decision.suggested_layer, "A")
        self.assertEqual(len(states), 2)
        self.assertEqual(
            {state.learning_target_version_id for state in states},
            {version.id for version in self.target_versions},
        )
        self.assertTrue(all(state.valid_until for state in states))
        first_state = states[0]
        self.assertIsNotNone(first_state.mastery_target_result_id)
        self.assertEqual(
            first_state.semantic_content()["mastery_target_result_id"],
            first_state.mastery_target_result_id,
        )
        expected_state_hash = hashlib.sha256(
            json.dumps(
                first_state.semantic_content(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(first_state.content_hash, expected_state_hash)
        self.assertEqual(
            StudentLearningTargetStateVersion.formal_training_queryset()
            .filter(pk__in=[state.pk for state in states])
            .count(),
            2,
        )
        first_link = recommendation.target_state_links.first()
        first_link.sort_order = 99
        with self.assertRaises(ValidationError):
            first_link.save()
        first_state.mastery_target_result = states[1].mastery_target_result
        with self.assertRaises(ValidationError):
            first_state.save()

        band = apply_student_subject_band(
            decision=decision,
            selected_band="A",
            confirmed_by=self.teacher,
        )
        self.assertEqual(band.band, "A")
        band.band = "B"
        with self.assertRaises(ValidationError):
            band.save()
        with self.assertRaises(ValidationError):
            StudentSubjectBand.objects.filter(pk=band.pk).update(band="B")
        with self.assertRaises(ValidationError):
            band.delete()

    def test_manual_adjustment_requires_and_preserves_target_evidence(self):
        snapshot = build_student_mastery_snapshot(attempt=self.attempt)
        decision = build_guarded_content_band_candidate(
            snapshot=snapshot,
            policy=self.policy,
        )
        client = APIClient()
        client.force_authenticate(self.teacher)
        accepted = client.post(
            f"/api/v1/teacher/analytics/stratification/{decision.id}/review/",
            {"action": "accept"},
            format="json",
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)

        missing_source = client.post(
            "/api/v1/teacher/analytics/stratification/manual-adjust/",
            {
                "student": self.student.id,
                "course": self.course.id,
                "layer": "B",
                "reason_code": "classroom_evidence",
            },
            format="json",
        )
        self.assertEqual(missing_source.status_code, 400, missing_source.data)

        adjusted = client.post(
            "/api/v1/teacher/analytics/stratification/manual-adjust/",
            {
                "student": self.student.id,
                "course": self.course.id,
                "source_decision": decision.id,
                "layer": "B",
                "reason_code": "classroom_evidence",
                "note": "结合近期作品中的补充材料调整。",
            },
            format="json",
        )
        self.assertEqual(adjusted.status_code, 200, adjusted.data)
        bands = list(
            StudentSubjectBand.objects.filter(
                student=self.student,
                subject=self.subject,
                course=self.course,
            ).order_by("valid_from", "id")
        )
        self.assertEqual(len(bands), 2)
        self.assertIsNotNone(bands[0].valid_until)
        self.assertEqual(bands[1].band, "B")
        self.assertIsNone(bands[1].valid_until)
        manual_decision = StratificationDecision.objects.get(
            pk=adjusted.data["data"]["id"]
        )
        manual_recommendation = LearningContentRecommendation.objects.get(
            source_decision=manual_decision
        )
        self.assertEqual(manual_recommendation.target_states.count(), 2)
        self.assertEqual(
            manual_decision.learning_summary["source_decision_id"], decision.id
        )

    def test_regrade_appends_snapshot_and_preserves_old_evidence(self):
        first = build_student_mastery_snapshot(attempt=self.attempt)
        first_hash = first.source_hash
        self.answers[0].auto_score = 5
        self.answers[0].save(update_fields=["auto_score", "answered_at"])
        self.attempt.graded_at = timezone.now() + timedelta(seconds=1)
        self.attempt.save(update_fields=["graded_at", "last_saved_at"])

        second = build_student_mastery_snapshot(attempt=self.attempt)
        duplicate = build_student_mastery_snapshot(attempt=self.attempt)
        self.assertNotEqual(first.pk, second.pk)
        self.assertNotEqual(first_hash, second.source_hash)
        self.assertEqual(duplicate.pk, second.pk)
        self.assertEqual(self.attempt.mastery_snapshots.count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.source_hash, first_hash)
        first.score_obtained = 0
        with self.assertRaises(ValidationError):
            first.save()

    def test_single_task_per_target_is_deferred_despite_full_scores(self):
        question_set = CommonQuestionSet.objects.create(
            school=self.school,
            subject=self.subject,
            title="单任务目标误差边界",
            grade_scope="高一",
            term="单任务边界",
            version_no=1,
            measurement_series="IT-SINGLE-TASK-BOUNDARY",
            version_purpose=CommonQuestionSet.VersionPurpose.BASELINE,
            content_hash="d" * 64,
            status=CommonQuestionSet.Status.ACTIVE,
            created_by=self.teacher,
            published_by=self.teacher,
            published_at=timezone.now(),
        )
        assessment = TestAssessment.objects.create(
            school=self.school,
            teacher=self.teacher,
            subject=self.subject,
            course=self.course,
            common_question_set=question_set,
            common_set_version=1,
            common_set_hash=question_set.content_hash,
            title="单任务不形成内容层级建议",
            status=TestAssessment.Status.DRAFT,
        )
        assessment.target_classes.add(self.class_group)
        assessment_questions = []
        for index, target_version in enumerate(self.target_versions, start=1):
            source = QuestionBankItem.objects.create(
                school=self.school,
                subject=self.subject,
                creator=self.teacher,
                stem=f"目标 {index} 唯一共同题",
                question_type=QuestionBankItem.QuestionType.SINGLE,
                options=["A", "B"],
                answer=["A"],
                difficulty=QuestionBankItem.Difficulty.NORMAL,
                default_score=10,
                status=QuestionBankItem.Status.ACTIVE,
                library_scope=QuestionBankItem.LibraryScope.SCHOOL,
                item_role=QuestionBankItem.ItemRole.COMMON,
                comparison_code=f"IT-SINGLE-{index}",
                learning_target_version=target_version,
                legacy_unmapped=False,
            )
            source_version = ensure_question_version(source, actor=self.teacher)
            CommonQuestionSetItem.objects.create(
                question_set=question_set,
                question_version=source_version,
                comparison_code=source.comparison_code,
                required=True,
                sort_order=index * 10,
            )
            assessment_questions.append(
                TestAssessmentQuestion.objects.create(
                    assessment=assessment,
                    source_question=source,
                    source_version=source_version,
                    source_status=source.status,
                    question_type=source.question_type,
                    stem=source.stem,
                    options=source.options,
                    answer=source.answer,
                    score=10,
                    sort_order=index * 10,
                    item_role=QuestionBankItem.ItemRole.COMMON,
                    comparison_code=source.comparison_code,
                    learning_target_version=target_version,
                    legacy_unmapped=False,
                )
            )
        now = timezone.now()
        assessment.status = TestAssessment.Status.CLOSED
        assessment.closed_at = now
        assessment.save(update_fields=["status", "closed_at", "updated_at"])
        attempt = TestAttempt.objects.create(
            assessment=assessment,
            student=self.student,
            class_group=self.class_group,
            status=TestAttempt.Status.GRADED,
            submitted_at=now,
            graded_at=now,
        )
        for question in assessment_questions:
            TestAttemptAnswer.objects.create(
                attempt=attempt,
                question=question,
                answer=["A"],
                auto_score=10,
                is_correct=True,
            )
        policy = ContentBandPolicyVersion.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            name="单任务拒绝边界",
            version_no=2,
            policy_version="single-task-reject-v1",
            a_min=0.8,
            b_min=0.6,
            boundary_margin=0.01,
            hysteresis_margin=0.01,
            max_measurement_error=0.2,
            min_common_items=1,
            min_answered_ratio=1,
            required_consecutive_windows=1,
            cooldown_days=0,
            status=ContentBandPolicyVersion.Status.DRAFT,
            content_hash="e" * 64,
            created_by=self.teacher,
        )

        snapshot = build_student_mastery_snapshot(attempt=attempt)
        self.assertEqual(snapshot.measurement_error, 0.353553)
        self.assertTrue(
            all(
                result.measurement_error == 0.5
                for result in snapshot.target_results.all()
            )
        )
        decision = build_guarded_content_band_candidate(
            snapshot=snapshot,
            policy=policy,
        )
        self.assertEqual(decision.status, decision.Status.DEFERRED)
        self.assertEqual(decision.suggested_layer, "")
        self.assertEqual(decision.abstain_reason, "measurement_error_too_large")
        self.assertFalse(
            StudentLearningTargetStateVersion.formal_training_queryset()
            .filter(mastery_target_result__snapshot=snapshot)
            .exists()
        )

    def test_synthetic_tenant_target_states_never_enter_formal_training(self):
        snapshot = build_student_mastery_snapshot(attempt=self.attempt)
        state_ids = list(
            StudentLearningTargetStateVersion.objects.filter(
                source_id__in=[
                    str(item.id) for item in snapshot.target_results.all()
                ]
            ).values_list("id", flat=True)
        )
        self.assertEqual(
            StudentLearningTargetStateVersion.formal_training_queryset()
            .filter(id__in=state_ids)
            .count(),
            2,
        )
        StudentMasterySnapshot.objects.filter(pk=snapshot.pk).update(is_test_data=True)
        self.assertFalse(
            StudentLearningTargetStateVersion.formal_training_queryset()
            .filter(id__in=state_ids)
            .exists()
        )
        StudentMasterySnapshot.objects.filter(pk=snapshot.pk).update(is_test_data=False)
        self.school.is_synthetic = True
        self.school.save(update_fields=["is_synthetic", "updated_at"])
        self.assertFalse(
            StudentLearningTargetStateVersion.formal_training_queryset()
            .filter(id__in=state_ids)
            .exists()
        )

    def test_incomplete_target_mapping_abstains_and_never_enters_c(self):
        TestAssessmentQuestion.objects.filter(
            pk=self.assessment_questions[0].pk
        ).update(learning_target_version=None, legacy_unmapped=True)
        snapshot = build_student_mastery_snapshot(attempt=self.attempt)
        decision = build_guarded_content_band_candidate(
            snapshot=snapshot,
            policy=self.policy,
        )
        recommendation = LearningContentRecommendation.objects.get(
            source_decision=decision
        )
        self.assertTrue(snapshot.legacy_unmapped)
        self.assertIsNone(snapshot.mastery_score)
        self.assertEqual(decision.status, decision.Status.DEFERRED)
        self.assertEqual(decision.suggested_layer, "")
        self.assertNotEqual(decision.suggested_layer, "C")
        self.assertEqual(
            recommendation.status,
            LearningContentRecommendation.Status.NOT_RECOMMENDED,
        )

    def test_pending_manual_grade_has_no_target_estimate(self):
        question = self.assessment_questions[0]
        # Fixture-only bypass to represent a historical submitted subjective
        # response; normal ORM save is intentionally locked after publication.
        TestAssessmentQuestion.objects.filter(pk=question.pk).update(
            question_type=QuestionBankItem.QuestionType.TEXT
        )
        question.refresh_from_db()
        self.answers[0].manual_score = None
        self.answers[0].save(update_fields=["manual_score", "answered_at"])
        self.attempt.status = TestAttempt.Status.SUBMITTED
        self.attempt.save(update_fields=["status", "last_saved_at"])

        snapshot = build_student_mastery_snapshot(attempt=self.attempt)
        decision = build_guarded_content_band_candidate(
            snapshot=snapshot,
            policy=self.policy,
        )
        self.assertEqual(
            snapshot.data_status,
            StudentMasterySnapshot.DataStatus.PENDING_GRADING,
        )
        self.assertIsNone(snapshot.mastery_score)
        self.assertTrue(
            all(result.mastery_score is None for result in snapshot.target_results.all())
        )
        self.assertEqual(decision.status, decision.Status.DEFERRED)
        self.assertEqual(decision.suggested_layer, "")

    def _initial_diagnostic_fixture(
        self,
        *,
        pending=False,
        missing_uncertainty=False,
        purpose=DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
    ):
        paper = PretestPaper.objects.create(
            school=self.school,
            subject=self.subject,
            title="学习起点诊断",
            kind=PretestPaper.Kind.LITERACY,
            version=1,
            status=PretestPaper.Status.PUBLISHED,
            created_by=self.teacher,
            published_at=timezone.now(),
        )
        tasks_per_target = 8
        question_snapshot = [
            {
                "id": target_index * tasks_per_target + task_index + 1,
                "stem": f"目标 {target_index + 1} 诊断任务 {task_index + 1}",
                "question_type": "single",
                "score": 10,
                "learning_target_code": version.code,
                "learning_target_name": version.title,
                "learning_target_version_id": version.id,
                "learning_target_version_hash": version.content_hash,
                "legacy_unmapped": False,
            }
            for target_index, version in enumerate(self.target_versions)
            for task_index in range(tasks_per_target)
        ]
        paper_version = PretestPaperVersion.objects.create(
            source=paper,
            version_no=1,
            title=paper.title,
            kind=paper.kind,
            question_snapshot=question_snapshot,
            published_by=self.teacher,
        )
        administration = DiagnosticAdministration.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            paper_version=paper_version,
            purpose=purpose,
            batch_code="ENTRY-P4-01",
            title="信息科技学习起点诊断批次",
            close_at=timezone.now() + timedelta(days=2),
            created_by=self.teacher,
        )
        assignment = DiagnosticAdministrationAssignment.objects.create(
            administration=administration,
            class_group=self.class_group,
            cohort_role=DiagnosticAdministrationAssignment.CohortRole.UNASSIGNED,
            opportunity_status=DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED,
        )
        administration = publish_diagnostic_administration(
            administration_id=administration.id,
            school=self.school,
            actor=self.teacher,
        )
        submission = PretestSubmission.objects.create(
            student=self.student,
            subject=self.subject,
            paper=paper,
            paper_version=paper_version,
            administration=administration,
            attempt_no=1,
            idempotency_key="initial-p4-submit-1",
            answers={str(item["id"]): "A" for item in question_snapshot},
            score=160,
            opportunity_status=PretestSubmission.OpportunityStatus.OBSERVED,
            target_results=[],
        )
        DiagnosticSubmissionBinding.objects.create(
            administration=administration,
            assignment=assignment,
            submission=submission,
            student=self.student,
            attempt_no=1,
            idempotency_key="initial-p4-submit-1",
            request_hash="1" * 64,
        )
        for index, version in enumerate(self.target_versions):
            is_pending = pending and index == 0
            StudentLearningTargetStateVersion.objects.create(
                student=self.student,
                school=self.school,
                class_group=self.class_group,
                subject=self.subject,
                course=self.course,
                learning_target_version=version,
                legacy_unmapped=False,
                learning_target_code=version.code,
                learning_target_name=version.title,
                source_type="learning_entry_diagnostic",
                source_id=str(submission.id),
                source_version=administration.content_hash,
                evidence_status=(
                    StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW
                    if is_pending
                    else StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE
                ),
                evidence_coverage=1.0,
                estimate=None if is_pending else 1.0,
                uncertainty=(
                    None
                    if is_pending or (missing_uncertainty and index == 0)
                    else round(0.5 / (tasks_per_target ** 0.5), 6)
                ),
                material_references=[
                    f"submission:{submission.id}:target:{version.id}:task:{task_index + 1}"
                    for task_index in range(tasks_per_target)
                ],
                observation_notes=[
                    "不确定性方法：conservative_task_coverage_se_v1；"
                    f"observed_task_count={tasks_per_target}；task_count={tasks_per_target}；coverage=1。"
                ],
                is_initial_diagnostic=True,
                observed_at=submission.submitted_at,
                valid_from=submission.submitted_at,
                valid_until=submission.submitted_at + timedelta(days=30),
            )
        return administration

    def test_initial_diagnostic_sufficient_exact_states_require_teacher_confirmation(self):
        administration = self._initial_diagnostic_fixture()
        decision = build_initial_diagnostic_content_band_candidate(
            administration=administration,
            student=self.student,
            policy=self.policy,
        )
        recommendation = LearningContentRecommendation.objects.get(
            source_decision=decision
        )
        self.assertEqual(decision.status, decision.Status.PENDING)
        self.assertEqual(decision.suggested_layer, "A")
        self.assertEqual(recommendation.target_states.count(), 2)
        for state in recommendation.target_states.all():
            self.assertIsNone(state.mastery_target_result_id)
            self.assertNotIn("mastery_target_result_id", state.semantic_content())
            historical_hash = hashlib.sha256(
                json.dumps(
                    state.semantic_content(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(state.content_hash, historical_hash)
        self.assertFalse(
            StudentLearningTargetStateVersion.formal_training_queryset()
            .filter(id__in=recommendation.target_states.values_list("id", flat=True))
            .exists()
        )
        self.assertEqual(
            decision.learning_summary["source"],
            "initial_diagnostic_target_states",
        )

    def test_initial_diagnostic_pending_material_is_not_recommended_not_c(self):
        administration = self._initial_diagnostic_fixture(pending=True)
        decision = build_initial_diagnostic_content_band_candidate(
            administration=administration,
            student=self.student,
            policy=self.policy,
        )
        recommendation = LearningContentRecommendation.objects.get(
            source_decision=decision
        )
        self.assertEqual(decision.status, decision.Status.DEFERRED)
        self.assertEqual(decision.suggested_layer, "")
        self.assertIn("diagnostic_grading_pending", decision.missing_data)
        self.assertEqual(
            recommendation.status,
            LearningContentRecommendation.Status.NOT_RECOMMENDED,
        )

    def test_initial_diagnostic_missing_uncertainty_is_deferred(self):
        administration = self._initial_diagnostic_fixture(missing_uncertainty=True)
        decision = build_initial_diagnostic_content_band_candidate(
            administration=administration,
            student=self.student,
            policy=self.policy,
        )
        self.assertEqual(decision.status, decision.Status.DEFERRED)
        self.assertEqual(decision.suggested_layer, "")
        self.assertIn("diagnostic_uncertainty_missing", decision.missing_data)
        self.assertIsNone(decision.learning_summary["measurement_error"])

    def test_initial_content_candidate_rejects_non_entry_administration(self):
        administration = self._initial_diagnostic_fixture(
            purpose=DiagnosticAdministration.Purpose.PILOT
        )
        with self.assertRaisesMessage(
            ValidationError,
            "只有学习起点诊断批次可以形成初始学习内容层级建议",
        ):
            build_initial_diagnostic_content_band_candidate(
                administration=administration,
                student=self.student,
                policy=self.policy,
            )

    def test_question_and_assessment_evidence_snapshots_are_immutable(self):
        version = self.assessment_questions[0].source_version
        version.stem = "试图改写题目版本"
        with self.assertRaises(ValidationError):
            version.save(update_fields=["stem"])
        with self.assertRaises(ValidationError):
            version.delete()

        question = self.assessment_questions[0]
        question.stem = "试图改写已发布测试题快照"
        with self.assertRaises(ValidationError):
            question.save(update_fields=["stem"])
        with self.assertRaises(ValidationError):
            question.delete()
        with self.assertRaises(ValidationError):
            TestAssessmentQuestion.objects.create(
                assessment=self.assessment,
                question_type=QuestionBankItem.QuestionType.SINGLE,
                stem="试图向已结束测试追加题目",
                options=["A", "B"],
                answer=["A"],
                legacy_unmapped=True,
            )

    def test_formal_material_requires_exact_course_scope(self):
        target_version = self.target_versions[0]
        with self.assertRaises(ValidationError):
            UnifiedAssessmentMaterial.objects.create(
                school=self.school,
                subject=self.subject,
                course=None,
                student=self.student,
                class_group=self.class_group,
                recorded_by=self.teacher,
                learning_target_version=target_version,
                legacy_unmapped=False,
                ownership=UnifiedAssessmentMaterial.Ownership.INDIVIDUAL,
                material_type=UnifiedAssessmentMaterial.MaterialType.SCORE,
                material_status=UnifiedAssessmentMaterial.MaterialStatus.AVAILABLE,
                learning_target_code=target_version.code,
                source_type="test_formal_material",
                source_id="formal-without-course",
                source_version="v1",
                score=8,
                score_max=10,
                recorded_at=timezone.now(),
            )
