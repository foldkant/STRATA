from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.grouping import build_grouping_candidates, build_grouping_plan
from courses.models import (
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupMember,
    ClassroomSession,
    CourseClass,
    Lesson,
)
from learning.models import (
    BandTransitionAudit,
    CommonQuestionSet,
    ContentBandPolicyVersion,
    StratificationDecision,
    StudentLearningTargetStateVersion,
    StudentMasterySnapshot,
    StudentMasteryTargetResult,
    StudentSubjectBand,
    TestAssessment,
    TestAttempt,
)
from learning.services.bands import resolve_student_band
from learning.services.mastery import (
    build_guarded_content_band_candidate,
    record_mastery_target_states,
)
from learning_analytics.services.evaluation import publish_plan
from learning_analytics.tests import test_learning_target_versions as target_fixture
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class DynamicStratificationAndGroupingTests(TestCase):
    def setUp(self):
        # Reuse a published curriculum-standard fixture so every formal
        # content-band suggestion is backed by an exact, aligned target
        # version instead of the pre-P4 score-only test shortcut.
        target_fixture.LearningTargetVersionTests.setUp(self)
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.school_admin = self.admin
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="数据处理",
            is_active=True,
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="动态策略测试课堂",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        target_plan = target_fixture.LearningTargetVersionTests.create_plan(
            self,
            title="动态分层共同学习目标",
            goal_code="IT_DYNAMIC_01",
        )
        self.target_version = (
            publish_plan(target_plan, published_by=self.teacher)
            .version.learning_target_versions.get(code="IT_DYNAMIC_01")
        )
        self.profiles = []
        for index, layer in enumerate(("A", "A", "B", "B", "C", "C"), start=1):
            student = User.objects.create_user(
                username=f"dynamic_student{index}",
                password="123456",
                role=User.Role.STUDENT,
                school=self.school,
            )
            self.profiles.append(
                StudentProfile.objects.create(
                    user=student,
                    class_group=self.class_group,
                    current_layer=layer,
                    is_first_use=False,
                )
            )
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    def _mastery_snapshot(
        self,
        *,
        score,
        error,
        observed_at,
        version,
        profile=None,
        data_status=StudentMasterySnapshot.DataStatus.AVAILABLE,
    ):
        profile = profile or self.profiles[0]
        question_set, _created = CommonQuestionSet.objects.get_or_create(
            school=self.school,
            subject=self.subject,
            grade_scope="高一",
            term="上学期",
            version_no=1,
            defaults={
                "title": "共同测试",
                "measurement_series": "IT-COMMON-01",
                "status": CommonQuestionSet.Status.ACTIVE,
                "created_by": self.teacher,
                "published_by": self.teacher,
                "published_at": timezone.now(),
            },
        )
        assessment = TestAssessment.objects.create(
            school=self.school,
            teacher=self.teacher,
            subject=self.subject,
            course=self.course,
            common_question_set=question_set,
            common_set_version=1,
            common_set_hash=f"common-{version}",
            title=f"共同测试 {version}",
            status=TestAssessment.Status.CLOSED,
        )
        assessment.target_classes.add(self.class_group)
        attempt = TestAttempt.objects.create(
            assessment=assessment,
            student=profile.user,
            class_group=self.class_group,
            status=TestAttempt.Status.GRADED,
            submitted_at=observed_at,
            graded_at=observed_at,
        )
        available = data_status == StudentMasterySnapshot.DataStatus.AVAILABLE
        snapshot = StudentMasterySnapshot.objects.create(
            student=profile.user,
            school=self.school,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            assessment=assessment,
            attempt=attempt,
            common_question_set=question_set,
            measurement_series="IT-COMMON-01",
            assessment_version=version,
            data_status=data_status,
            score_obtained=score * 10,
            score_max=10,
            mastery_score=score if available else None,
            measurement_error=error if available else None,
            common_item_count=10,
            answered_item_count=10,
            answered_ratio=1,
            knowledge_results=[],
            comparability_evidence={
                "comparability_status": "verified",
                "target_mapping_status": "complete",
            },
            source_hash=f"snapshot-{profile.user_id}-{version}",
            legacy_unmapped=False,
            observed_at=observed_at,
        )
        StudentMasteryTargetResult.objects.create(
            snapshot=snapshot,
            learning_target_version=self.target_version,
            data_status=data_status,
            score_obtained=score * 10,
            score_max=10,
            mastery_score=score if available else None,
            measurement_error=error if available else None,
            item_count=10,
            answered_item_count=10,
            evidence_coverage=1,
            evidence_snapshot={
                "assessment_question_ids": list(range(1, 11)),
                "uncertainty_method": "test-fixture-conservative-v1",
            },
        )
        return snapshot

    def _comparable_candidate(self, profile, score, *, version, window_end):
        policy, _created = ContentBandPolicyVersion.objects.get_or_create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            policy_version="criterion-v1",
            defaults={
                "name": "信息科技学习内容层级标准",
                "version_no": 1,
                "a_min": 0.8,
                "b_min": 0.6,
                "boundary_margin": 0.01,
                "hysteresis_margin": 0,
                "max_measurement_error": 0.1,
                "min_common_items": 5,
                "min_answered_ratio": 0.8,
                "required_consecutive_windows": 1,
                "cooldown_days": 0,
                "status": ContentBandPolicyVersion.Status.ACTIVE,
                "created_by": self.teacher,
                "published_by": self.teacher,
                "published_at": timezone.now(),
            },
        )
        snapshot = self._mastery_snapshot(
            profile=profile,
            score=score,
            error=0.01,
            observed_at=window_end,
            version=version,
        )
        return build_guarded_content_band_candidate(
            snapshot=snapshot,
            policy=policy,
        )

    def _accept(self, decision):
        response = self.client.post(
            f"/api/v1/teacher/analytics/stratification/{decision.id}/review/",
            {"action": "accept"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def _support_decision(self, profile, suffix, *, status=None):
        return StratificationDecision.objects.create(
            student=profile.user,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            suggested_layer="",
            decision_kind=StratificationDecision.DecisionKind.SUPPORT,
            support_priority=StratificationDecision.SupportPriority.WATCH,
            support_suggestion="安排针对性练习。",
            rule_version=f"support-bulk-{suffix}",
            status=status or StratificationDecision.Status.PENDING,
        )

    def test_support_decision_never_changes_formal_band(self):
        profile = self.profiles[0]
        decision = StratificationDecision.objects.create(
            student=profile.user,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            suggested_layer="",
            decision_kind=StratificationDecision.DecisionKind.SUPPORT,
            support_priority=StratificationDecision.SupportPriority.HIGH,
            support_suggestion="补充支架。",
            rule_version="support-test-v2",
        )

        self._accept(decision)

        profile.refresh_from_db()
        self.assertEqual(profile.current_layer, "A")
        self.assertFalse(StudentSubjectBand.objects.exists())

    def test_support_decision_rejects_layer_adjust_action(self):
        profile = self.profiles[0]
        decision = StratificationDecision.objects.create(
            student=profile.user,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            suggested_layer="",
            decision_kind=StratificationDecision.DecisionKind.SUPPORT,
            support_priority=StratificationDecision.SupportPriority.HIGH,
            support_suggestion="补充支架。",
            rule_version="support-adjust-test-v2",
        )

        response = self.client.post(
            f"/api/v1/teacher/analytics/stratification/{decision.id}/review/",
            {"action": "adjust", "layer": "B"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        decision.refresh_from_db()
        self.assertEqual(decision.status, StratificationDecision.Status.PENDING)

    def test_bulk_review_accepts_support_and_content_band_together(self):
        support = self._support_decision(self.profiles[0], "mixed-support")
        content_band = self._comparable_candidate(
            self.profiles[1],
            0.68,
            version="content-bulk-mixed",
            window_end=timezone.now(),
        )

        response = self.client.post(
            "/api/v1/teacher/analytics/stratification/batch-review/",
            {"ids": [support.id, content_band.id], "action": "accept"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["updated_count"], 2)
        support.refresh_from_db()
        content_band.refresh_from_db()
        self.profiles[0].refresh_from_db()
        self.profiles[1].refresh_from_db()
        self.assertEqual(support.status, StratificationDecision.Status.ACCEPTED)
        self.assertEqual(content_band.status, StratificationDecision.Status.ACCEPTED)
        self.assertEqual(self.profiles[0].current_layer, "A")
        self.assertEqual(self.profiles[1].current_layer, "A")
        self.assertEqual(
            StudentSubjectBand.objects.get(source_decision=content_band).band,
            "B",
        )

    def test_bulk_review_rolls_back_when_one_decision_is_already_processed(self):
        pending = self._support_decision(self.profiles[0], "atomic-pending")
        processed = self._support_decision(
            self.profiles[1],
            "atomic-processed",
            status=StratificationDecision.Status.ACCEPTED,
        )

        response = self.client.post(
            "/api/v1/teacher/analytics/stratification/batch-review/",
            {
                "ids": [pending.id, processed.id],
                "action": "defer",
                "reason_code": "support_plan",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        pending.refresh_from_db()
        processed.refresh_from_db()
        self.assertEqual(pending.status, StratificationDecision.Status.PENDING)
        self.assertEqual(processed.status, StratificationDecision.Status.ACCEPTED)

    def test_bulk_review_requires_reason_before_writing_any_decision(self):
        first = self._support_decision(self.profiles[0], "reason-first")
        second = self._support_decision(self.profiles[1], "reason-second")

        response = self.client.post(
            "/api/v1/teacher/analytics/stratification/batch-review/",
            {"ids": [first.id, second.id], "action": "keep"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, StratificationDecision.Status.PENDING)
        self.assertEqual(second.status, StratificationDecision.Status.PENDING)

    def test_teacher_manual_adjustment_versions_band_and_preserves_model_decision(self):
        profile = self.profiles[0]
        now = timezone.now()
        model_decision = self._comparable_candidate(
            profile,
            0.86,
            version="manual-v1",
            window_end=now,
        )
        self._accept(model_decision)
        original_band = StudentSubjectBand.objects.get(source_decision=model_decision)

        response = self.client.post(
            "/api/v1/teacher/analytics/stratification/manual-adjust/",
            {
                "student": profile.user_id,
                "course": self.course.id,
                "source_decision": model_decision.id,
                "layer": "B",
                "reason_code": "classroom_evidence",
                "note": "课堂作品显示核心任务更适合当前阶段。",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        model_decision.refresh_from_db()
        self.assertEqual(model_decision.suggested_layer, "A")
        self.assertEqual(model_decision.status, StratificationDecision.Status.ACCEPTED)
        original_band.refresh_from_db()
        self.assertIsNotNone(original_band.valid_until)
        current_band = StudentSubjectBand.objects.get(
            student=profile.user,
            subject=self.subject,
            course=self.course,
            valid_until__isnull=True,
        )
        self.assertEqual(current_band.band, "B")
        self.assertEqual(current_band.source_decision.suggested_layer, "B")
        self.assertEqual(current_band.source_decision.teacher_selected_layer, "B")
        self.assertTrue(current_band.source_decision.rule_version.startswith("teacher-manual-"))
        self.assertTrue(
            BandTransitionAudit.objects.filter(
                decision=current_band.source_decision,
                action="manual_adjust",
                final_band="B",
            ).exists()
        )
        profile.refresh_from_db()
        self.assertEqual(profile.current_layer, "A")
        self.assertEqual(
            resolve_student_band(
                student=profile.user,
                subject=self.subject,
                course=self.course,
            ),
            "B",
        )

    def test_comparable_mastery_creates_versioned_formal_band(self):
        profile = self.profiles[0]
        now = timezone.now() - timedelta(seconds=2)
        first = self._comparable_candidate(
            profile,
            0.86,
            version="v1",
            window_end=now,
        )
        self._accept(first)
        first_band = StudentSubjectBand.objects.get(source_decision=first)
        self.assertEqual(first_band.band, "A")

        second = self._comparable_candidate(
            profile,
            0.68,
            version="v2",
            window_end=now + timedelta(seconds=1),
        )
        self._accept(second)

        first_band.refresh_from_db()
        second_band = StudentSubjectBand.objects.get(source_decision=second)
        self.assertIsNotNone(first_band.valid_until)
        self.assertEqual(second_band.band, "B")
        self.assertIsNone(second_band.valid_until)
        profile.refresh_from_db()
        self.assertEqual(profile.current_layer, "A")
        self.assertEqual(
            resolve_student_band(
                student=profile.user,
                subject=self.subject,
                course=self.course,
            ),
            "B",
        )

    def test_cross_school_band_record_is_rejected_before_resolution(self):
        other_school = School.objects.create(
            name="跨校脏数据测试学校",
            code="DIRTY-BAND",
        )
        profile = self.profiles[-1]
        decision = StratificationDecision.objects.create(
            student=profile.user,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            suggested_layer="C",
            decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            policy_version="dirty-school-v1",
            rule_version="dirty-school-band",
            status=StratificationDecision.Status.ACCEPTED,
        )
        with self.assertRaises(ValidationError):
            StudentSubjectBand.objects.create(
                student=profile.user,
                school=other_school,
                class_group=self.class_group,
                subject=self.subject,
                course=self.course,
                band="C",
                valid_from=timezone.now() - timedelta(minutes=1),
                source_decision=decision,
                policy_version="dirty-school-v1",
                confirmed_by=self.teacher,
            )

        self.assertIsNone(
            resolve_student_band(
                student=profile.user,
                subject=self.subject,
                course=self.course,
            )
        )

    def test_ai_grouping_ignores_legacy_layers_without_task_readiness(self):
        first = build_grouping_plan(
            session=self.session,
            profiles=self.profiles,
            group_size=3,
            strategy=ClassroomGroupCollaboration.GroupingStrategy.AI_LAYER,
            seed=20260720,
            plan_version=1,
        )
        second = build_grouping_plan(
            session=self.session,
            profiles=self.profiles,
            group_size=3,
            strategy=ClassroomGroupCollaboration.GroupingStrategy.AI_LAYER,
            seed=20260720,
            plan_version=1,
        )

        self.assertEqual(first.metadata["effective_strategy"], "random_baseline")
        self.assertEqual(
            first.metadata["fallback_reason"],
            "insufficient_valid_readiness",
        )
        self.assertEqual(
            [[row.user_id for row in chunk] for chunk in first.chunks],
            [[row.user_id for row in chunk] for chunk in second.chunks],
        )

    def test_ai_grouping_uses_valid_task_readiness(self):
        now = timezone.now()
        for index, profile in enumerate(self.profiles, start=1):
            decision = StratificationDecision.objects.create(
                student=profile.user,
                class_group=self.class_group,
                subject=self.subject,
                course=self.course,
                suggested_layer="A" if index <= 2 else "B" if index <= 4 else "C",
                decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
                policy_version="task-test-v1",
                rule_version=f"task-band-{index}",
                status=StratificationDecision.Status.ACCEPTED,
            )
            StudentSubjectBand.objects.create(
                student=profile.user,
                school=self.school,
                class_group=self.class_group,
                subject=self.subject,
                course=self.course,
                band=decision.suggested_layer,
                valid_from=now - timedelta(minutes=1),
                source_decision=decision,
                policy_version="task-test-v1",
                evidence_snapshot={
                    "task_readiness": {
                        "lesson_id": self.lesson.id,
                        "score": index / len(self.profiles),
                    }
                },
                confirmed_by=self.teacher,
            )

        plan = build_grouping_plan(
            session=self.session,
            profiles=self.profiles,
            group_size=3,
            strategy=ClassroomGroupCollaboration.GroupingStrategy.AI_LAYER,
            seed=20260720,
            plan_version=1,
        )

        self.assertEqual(plan.metadata["effective_strategy"], "skill_complementary")
        self.assertEqual(plan.metadata["task_readiness_coverage"], 1.0)
        self.assertEqual(plan.metadata["fallback_reason"], "")
        self.assertEqual(sum(len(chunk) for chunk in plan.chunks), len(self.profiles))

        candidates = build_grouping_candidates(
            session=self.session,
            profiles=self.profiles,
            group_size=3,
            strategy=ClassroomGroupCollaboration.GroupingStrategy.AI_LAYER,
            seed=20260720,
            plan_version=1,
            locked_assignments={self.profiles[0].user_id: 1},
        )
        self.assertSetEqual(
            {candidate["key"] for candidate in candidates},
            {"random", "task_preferred", "stability_preferred"},
        )
        for candidate in candidates[1:]:
            self.assertIn(
                self.profiles[0].user_id,
                [profile.user_id for profile in candidate["chunks"][0]],
            )

        collaboration = ClassroomGroupCollaboration.objects.create(
            session=self.session,
            is_enabled=True,
            group_size=3,
            grouping_strategy=ClassroomGroupCollaboration.GroupingStrategy.STABLE_PROJECT,
            active_plan_version=1,
            status=ClassroomGroupCollaboration.Status.OPEN,
            created_by=self.teacher,
        )
        original_groups = []
        for group_no, profiles in enumerate(
            (self.profiles[:3], self.profiles[3:]),
            start=1,
        ):
            group = ClassroomGroup.objects.create(
                collaboration=collaboration,
                group_no=group_no,
                plan_version=1,
                name=f"第{group_no}组",
                leader=profiles[0].user,
            )
            original_groups.append(frozenset(profile.user_id for profile in profiles))
            ClassroomGroupMember.objects.bulk_create(
                [
                    ClassroomGroupMember(
                        collaboration=collaboration,
                        group=group,
                        student=profile.user,
                        student_profile=profile,
                        plan_version=1,
                    )
                    for profile in profiles
                ]
            )
        stable_candidates = build_grouping_candidates(
            session=self.session,
            profiles=self.profiles,
            group_size=3,
            strategy=ClassroomGroupCollaboration.GroupingStrategy.STABLE_PROJECT,
            seed=20260721,
            plan_version=2,
        )
        stable = next(
            candidate
            for candidate in stable_candidates
            if candidate["key"] == "stability_preferred"
        )
        self.assertSetEqual(
            {
                frozenset(profile.user_id for profile in chunk)
                for chunk in stable["chunks"]
            },
            set(original_groups),
        )

    def test_grouping_candidates_explain_local_optimizer_fallback(self):
        readiness = {
            profile.user_id: index / len(self.profiles)
            for index, profile in enumerate(self.profiles, start=1)
        }
        with (
            patch("courses.grouping._candidate_readiness", return_value=readiness),
            patch(
                "courses.grouping._cp_sat_chunks",
                return_value=([], "ortools_unavailable"),
            ),
        ):
            candidates = build_grouping_candidates(
                session=self.session,
                profiles=self.profiles,
                group_size=3,
                strategy=ClassroomGroupCollaboration.GroupingStrategy.AI_LAYER,
                seed=20260721,
                plan_version=1,
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["key"], "random")
        self.assertEqual(
            candidates[0]["metadata"]["fallback_reason"],
            "ortools_unavailable",
        )

    def test_content_band_change_requires_cooldown_and_consecutive_evidence(self):
        policy = ContentBandPolicyVersion.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            name="信息科技层级标准",
            version_no=1,
            policy_version="criterion-v1",
            a_min=0.8,
            b_min=0.6,
            boundary_margin=0.01,
            hysteresis_margin=0.03,
            max_measurement_error=0.1,
            min_common_items=5,
            min_answered_ratio=0.8,
            required_consecutive_windows=2,
            cooldown_days=14,
            status=ContentBandPolicyVersion.Status.ACTIVE,
            created_by=self.teacher,
            published_by=self.teacher,
            published_at=timezone.now(),
        )
        now = timezone.now()
        first = build_guarded_content_band_candidate(
            snapshot=self._mastery_snapshot(
                score=0.9,
                error=0.01,
                observed_at=now,
                version="v1",
            ),
            policy=policy,
        )
        self.assertEqual(first.suggested_layer, "A")
        self._accept(first)

        cooldown = build_guarded_content_band_candidate(
            snapshot=self._mastery_snapshot(
                score=0.68,
                error=0.01,
                observed_at=now + timedelta(days=1),
                version="v2",
            ),
            policy=policy,
        )
        self.assertEqual(cooldown.status, StratificationDecision.Status.DEFERRED)
        self.assertEqual(cooldown.abstain_reason, "cooldown_active")

        eligible = build_guarded_content_band_candidate(
            snapshot=self._mastery_snapshot(
                score=0.67,
                error=0.01,
                observed_at=now + timedelta(days=15),
                version="v3",
            ),
            policy=policy,
        )
        self.assertEqual(eligible.status, StratificationDecision.Status.PENDING)
        self.assertEqual(eligible.suggested_layer, "B")
        self.assertEqual(
            eligible.transition_checks["consecutive_candidate_count"],
            2,
        )

    def test_measurement_uncertainty_defers_content_band(self):
        policy = ContentBandPolicyVersion.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            name="信息科技层级标准",
            version_no=1,
            policy_version="criterion-v1",
            a_min=0.8,
            b_min=0.6,
            boundary_margin=0.03,
            max_measurement_error=0.2,
            required_consecutive_windows=1,
            cooldown_days=0,
            status=ContentBandPolicyVersion.Status.ACTIVE,
            created_by=self.teacher,
            published_by=self.teacher,
            published_at=timezone.now(),
        )
        decision = build_guarded_content_band_candidate(
            snapshot=self._mastery_snapshot(
                score=0.79,
                error=0.03,
                observed_at=timezone.now(),
                version="uncertain",
            ),
            policy=policy,
        )
        self.assertEqual(decision.status, StratificationDecision.Status.DEFERRED)
        self.assertEqual(decision.abstain_reason, "measurement_uncertainty")
        self.assertEqual(decision.suggested_layer, "")

    def test_not_comparable_mastery_abstains_without_target_estimate(self):
        policy = ContentBandPolicyVersion.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            name="信息科技层级标准",
            version_no=1,
            policy_version="criterion-v1",
            required_consecutive_windows=1,
            cooldown_days=0,
            status=ContentBandPolicyVersion.Status.ACTIVE,
            created_by=self.teacher,
            published_by=self.teacher,
            published_at=timezone.now(),
        )
        snapshot = self._mastery_snapshot(
            score=0.92,
            error=0.02,
            observed_at=timezone.now(),
            version="not-comparable",
            data_status=StudentMasterySnapshot.DataStatus.NOT_COMPARABLE,
        )

        states = record_mastery_target_states(snapshot=snapshot)
        decision = build_guarded_content_band_candidate(
            snapshot=snapshot,
            policy=policy,
        )

        self.assertTrue(states)
        self.assertTrue(
            all(
                state.evidence_status
                == StudentLearningTargetStateVersion.EvidenceStatus.INSUFFICIENT
                and state.estimate is None
                for state in states
            )
        )
        self.assertEqual(decision.status, StratificationDecision.Status.DEFERRED)
        self.assertEqual(
            decision.abstain_reason,
            StudentMasterySnapshot.DataStatus.NOT_COMPARABLE,
        )
        self.assertEqual(decision.suggested_layer, "")

    def test_school_admin_can_version_and_activate_content_band_policy(self):
        self.client.force_authenticate(self.school_admin)
        create_response = self.client.post(
            "/api/v1/school-admin/analytics/content-band-policies/",
            {
                "subject": self.subject.id,
                "name": "信息科技学习内容层级标准",
                "a_min": 0.8,
                "b_min": 0.6,
                "boundary_margin": 0.03,
                "hysteresis_margin": 0.03,
                "max_measurement_error": 0.18,
                "min_common_items": 5,
                "min_answered_ratio": 0.8,
                "required_consecutive_windows": 2,
                "cooldown_days": 14,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)
        policy = create_response.data["data"]
        self.assertEqual(policy["status"], ContentBandPolicyVersion.Status.DRAFT)

        publish_response = self.client.post(
            f"/api/v1/school-admin/analytics/content-band-policies/{policy['id']}/publish/",
            {},
            format="json",
        )
        self.assertEqual(publish_response.status_code, 200, publish_response.data)
        self.assertEqual(
            publish_response.data["data"]["status"],
            ContentBandPolicyVersion.Status.ACTIVE,
        )

        self.client.force_authenticate(self.teacher)
        forbidden = self.client.get(
            "/api/v1/school-admin/analytics/content-band-policies/"
        )
        self.assertEqual(forbidden.status_code, 403)
