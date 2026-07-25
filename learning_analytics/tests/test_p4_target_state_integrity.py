from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from api.analytics.teacher_views import _apply_review
from courses.models import Course, CourseClass, Subject
from learning.models import (
    LearningContentRecommendation,
    LearningSupportRecommendation,
    StratificationDecision,
    StudentSubjectBand,
    StudentLearningTargetStateVersion,
)
from learning_analytics.models import StudentLearningSummary
from learning_analytics.services.learning_summaries import build_transparent_suggestion
from learning.services.bands import apply_student_subject_band
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class P4TargetStateIntegrityTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="P4 学习情况测试学校", code="P4STATE")
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="七年级1班",
            grade="七年级",
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="P4-IT",
        )
        self.teacher = User.objects.create_user(
            username="p4_state_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.student = User.objects.create_user(
            username="p4_state_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与编码",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.client = APIClient()
        self.now = timezone.now()

    def target_state(self, **overrides):
        values = {
            "student": self.student,
            "school": self.school,
            "class_group": self.class_group,
            "subject": self.subject,
            "course": self.course,
            "learning_target_code": "IT-7-DATA-01",
            "learning_target_name": "能依据任务需要选择适当的数据表示方式",
            "source_type": "classroom_assessment",
            "source_id": "task-1",
            "source_version": "v1",
            "evidence_status": StudentLearningTargetStateVersion.EvidenceStatus.AVAILABLE,
            "evidence_coverage": 0.8,
            "estimate": 0.7,
            "uncertainty": 0.15,
            "material_references": ["material:1"],
            "observation_notes": ["已完成主要操作步骤。"],
            "is_initial_diagnostic": False,
            "observed_at": self.now,
            "valid_from": self.now,
            "valid_until": self.now + timedelta(days=30),
        }
        values.update(overrides)
        return StudentLearningTargetStateVersion.objects.create(**values)

    def test_not_observed_never_carries_a_level_estimate(self):
        with self.assertRaises(ValidationError):
            self.target_state(
                evidence_status=StudentLearningTargetStateVersion.EvidenceStatus.NOT_OBSERVED,
                evidence_coverage=0,
                estimate=0.2,
                uncertainty=None,
            )

        state = self.target_state(
            source_version="v2",
            evidence_status=StudentLearningTargetStateVersion.EvidenceStatus.NOT_OBSERVED,
            evidence_coverage=0,
            estimate=None,
            uncertainty=None,
            material_references=[],
        )
        self.assertIsNone(state.estimate)
        self.assertEqual(state.evidence_coverage, 0)

    def test_subject_and_course_scopes_have_separate_immutable_versions(self):
        course_state = self.target_state()
        subject_state = self.target_state(course=None)
        self.assertNotEqual(course_state.id, subject_state.id)

        with self.assertRaises(ValidationError):
            course_state.learning_target_name = "试图覆盖已形成的版本"
            course_state.save()

        with self.assertRaises(ValidationError):
            self.target_state(course=None)

    def test_teacher_review_is_preserved_when_the_same_summary_is_rebuilt(self):
        summary = StudentLearningSummary.objects.create(
            school=self.school,
            student=self.student,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            window_type=StudentLearningSummary.WindowType.DAYS_30,
            period_key="2026-07-30d",
            window_start=self.now - timedelta(days=30),
            window_end=self.now,
            data_status=StudentLearningSummary.DataStatus.INSUFFICIENT,
            metrics={"opportunities": {"eligible_count": 0}},
            missing_data=["材料覆盖不足"],
            source_hash="p4-summary-v1",
        )
        decision = build_transparent_suggestion(summary=summary)
        recommendation = LearningSupportRecommendation.objects.get(
            source_decision=decision
        )

        _apply_review(
            decision,
            {
                "action": "accept",
                "status": StratificationDecision.Status.ACCEPTED,
                "selected_layer": "",
                "reason_code": "",
                "note": "保持当前学习内容，补充观察机会。",
                "is_content_band": False,
            },
            actor=self.teacher,
        )
        recommendation.refresh_from_db()
        self.assertEqual(
            recommendation.status,
            LearningSupportRecommendation.Status.CONFIRMED,
        )
        self.assertEqual(recommendation.reviewed_by, self.teacher)

        rebuilt = build_transparent_suggestion(summary=summary)
        rebuilt.refresh_from_db()
        recommendation.refresh_from_db()
        self.assertEqual(rebuilt.id, decision.id)
        self.assertEqual(rebuilt.status, StratificationDecision.Status.ACCEPTED)
        self.assertEqual(
            recommendation.status,
            LearningSupportRecommendation.Status.CONFIRMED,
        )
        self.assertEqual(recommendation.reviewed_by, self.teacher)

    def test_teacher_target_state_api_is_limited_to_taught_subject_and_course(self):
        own_course_state = self.target_state(source_id="own-course")
        own_subject_state = self.target_state(
            course=None,
            source_id="own-subject",
            source_version="v2",
        )
        other_teacher = User.objects.create_user(
            username="p4_other_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        other_course_same_subject = Course.objects.create(
            subject=self.subject,
            title="同班同学科其他教师课程",
            teacher=other_teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=other_course_same_subject,
            class_group=self.class_group,
            created_by=other_teacher,
        )
        foreign_course_state = self.target_state(
            course=other_course_same_subject,
            source_id="foreign-course",
            source_version="v3",
        )
        other_subject = Subject.objects.create(
            school=self.school,
            name="数学",
            code="P4-MATH",
        )
        other_subject_course = Course.objects.create(
            subject=other_subject,
            title="同班其他学科课程",
            teacher=other_teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=other_subject_course,
            class_group=self.class_group,
            created_by=other_teacher,
        )
        foreign_subject_state = self.target_state(
            subject=other_subject,
            course=None,
            learning_target_code="MATH-01",
            source_id="foreign-subject",
            source_version="v4",
        )

        self.client.force_authenticate(self.teacher)
        response = self.client.get("/api/v1/teacher/analytics/learning-target-states/")

        self.assertEqual(response.status_code, 200, response.data)
        returned_ids = {row["id"] for row in response.data["data"]}
        self.assertSetEqual(returned_ids, {own_course_state.id, own_subject_state.id})
        self.assertNotIn(foreign_course_state.id, returned_ids)
        self.assertNotIn(foreign_subject_state.id, returned_ids)

        forbidden_course = self.client.get(
            "/api/v1/teacher/analytics/learning-target-states/",
            {"course": other_course_same_subject.id},
        )
        self.assertEqual(forbidden_course.status_code, 404, forbidden_course.data)

    def test_expired_target_state_cannot_be_accepted_as_current_band(self):
        expired_state = self.target_state(
            source_id="expired-evidence",
            observed_at=self.now - timedelta(days=60),
            valid_from=self.now - timedelta(days=60),
            valid_until=self.now - timedelta(days=1),
        )
        decision = StratificationDecision.objects.create(
            student=self.student,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            previous_layer="",
            suggested_layer="A",
            confidence=0,
            reasons=["历史材料形成的建议。"],
            missing_data=[],
            learning_summary={"source": "expired-test"},
            decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            policy_version="criterion-v1",
            window_start=self.now - timedelta(days=60),
            window_end=self.now - timedelta(days=31),
            rule_version="expired-target-v1",
            status=StratificationDecision.Status.PENDING,
        )
        # Simulate a recommendation written before the immutable target-version
        # contract.  New service writes correctly reject this legacy-unmapped
        # source, but the review API must still fail closed for historical rows.
        LearningContentRecommendation.objects.bulk_create(
            [
                LearningContentRecommendation(
                    target_state=expired_state,
                    source_decision=decision,
                    suggested_band="A",
                    status=LearningContentRecommendation.Status.PENDING,
                    rationale=["历史材料形成的建议。"],
                    evidence_coverage=1,
                    uncertainty=0.1,
                )
            ]
        )

        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            f"/api/v1/teacher/analytics/stratification/{decision.id}/review/",
            {"action": "accept"},
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        decision.refresh_from_db()
        self.assertEqual(decision.status, StratificationDecision.Status.PENDING)
        self.assertFalse(
            StudentSubjectBand.objects.filter(source_decision=decision).exists()
        )

    def test_content_band_cannot_be_applied_without_target_level_evidence(self):
        decision = StratificationDecision.objects.create(
            student=self.student,
            class_group=self.class_group,
            subject=self.subject,
            course=self.course,
            previous_layer="",
            suggested_layer="C",
            confidence=0,
            reasons=["没有目标级材料的旧建议。"],
            missing_data=[],
            learning_summary={"source": "legacy-total-score"},
            decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
            policy_version="legacy-v1",
            window_start=self.now,
            window_end=self.now,
            rule_version="legacy-no-target-evidence",
            status=StratificationDecision.Status.PENDING,
        )

        with self.assertRaisesMessage(ValidationError, "缺少可追溯的目标级材料"):
            apply_student_subject_band(
                decision=decision,
                selected_band="C",
                confirmed_by=self.teacher,
            )
        self.assertFalse(StudentSubjectBand.objects.exists())
