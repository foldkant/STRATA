from datetime import timedelta

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
    Course,
    CourseClass,
    Lesson,
    Subject,
)
from learning.models import (
    CommonQuestionSet,
    ContentBandPolicyVersion,
    StratificationDecision,
    StudentMasterySnapshot,
    StudentSubjectBand,
    TestAssessment,
    TestAttempt,
)
from learning.services.bands import build_content_band_candidate
from learning.services.mastery import build_guarded_content_band_candidate
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class DynamicStratificationAndGroupingTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="动态策略测试学校", code="DYNAMIC")
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
        )
        self.teacher = User.objects.create_user(
            username="dynamic_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.school_admin = User.objects.create_user(
            username="dynamic_school_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与计算",
            teacher=self.teacher,
            is_active=True,
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

    def _mastery_snapshot(self, *, score, error, observed_at, version):
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
            student=self.profiles[0].user,
            class_group=self.class_group,
            status=TestAttempt.Status.GRADED,
            submitted_at=observed_at,
            graded_at=observed_at,
        )
        return StudentMasterySnapshot.objects.create(
            student=self.profiles[0].user,
            school=self.school,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            assessment=assessment,
            attempt=attempt,
            common_question_set=question_set,
            measurement_series="IT-COMMON-01",
            assessment_version=version,
            data_status=StudentMasterySnapshot.DataStatus.AVAILABLE,
            score_obtained=score * 10,
            score_max=10,
            mastery_score=score,
            measurement_error=error,
            common_item_count=10,
            answered_item_count=10,
            answered_ratio=1,
            source_hash=f"snapshot-{version}",
            observed_at=observed_at,
        )

    def _comparable_candidate(self, profile, score, *, version, window_end):
        return build_content_band_candidate(
            student_profile=profile,
            subject=self.subject,
            course=self.course,
            mastery_score=score,
            evidence_snapshot={
                "comparability_status": "verified",
                "measurement_series": "IT-COMMON-01",
                "assessment_version": version,
                "reasons": ["共同测试掌握度记录完整。"],
            },
            policy={
                "version": "criterion-v1",
                "a_min": 0.8,
                "b_min": 0.6,
                "boundary_margin": 0.03,
            },
            window_start=window_end - timedelta(days=7),
            window_end=window_end,
        )

    def _accept(self, decision):
        response = self.client.post(
            f"/api/v1/teacher/analytics/stratification/{decision.id}/review/",
            {"action": "accept"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

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

    def test_comparable_mastery_creates_versioned_formal_band(self):
        profile = self.profiles[0]
        now = timezone.now()
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
        self.assertEqual(profile.current_layer, "B")

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
