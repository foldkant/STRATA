from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    Subject,
)
from learning.models import LearningEvent
from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
    ParticipationPointLedger,
)
from learning_analytics.services.participation_points import (
    ParticipationPointError,
    reconcile_participation_point_cache,
    record_participation_points,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    reconcile_v1_v2_events,
    record_classroom_point_adjustment,
    record_learning_event,
)
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class AnalyticsFactTestBase(TestCase):
    endpoint = "/api/v1/learning-events/batch/"

    def setUp(self):
        sync_event_schema_definitions()
        self.school = School.objects.create(name="结果事实学校", code="RESULT-FACT")
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
            username="result_teacher",
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
            username="result_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        self.client = APIClient()

    def post_events(self, actor, events):
        self.client.force_authenticate(actor)
        return self.client.post(
            self.endpoint,
            {"batch_id": str(uuid.uuid4()), "events": events},
            format="json",
        )

    def intervention_event(self, *, reason_code: str, occurred_at=None):
        raw = {
            "event_id": str(uuid.uuid4()),
            "event_name": "intervention.created",
            "schema_version": "1.0",
            "source": "teacher-web",
            "target_student_id": self.student.id,
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "client_occurred_at": (occurred_at or timezone.now()).isoformat(),
            "payload": {
                "intervention_type": "participation_points",
                "reason_code": reason_code,
                "intensity": "low",
            },
        }
        response = self.post_events(self.teacher, [raw])
        self.assertEqual(response.data["data"]["results"][0]["status"], "accepted")
        return LearningEventV2.objects.get(event_id=raw["event_id"])


class AssessmentResultFactTests(AnalyticsFactTestBase):
    def setUp(self):
        super().setUp()
        self.base_time = timezone.now() - timedelta(minutes=5)
        release = {
            "event_id": str(uuid.uuid4()),
            "event_name": "content.released",
            "schema_version": "1.0",
            "source": "teacher-web",
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "object_type": "question",
            "object_id": "question-1",
            "object_version": "question-1@1",
            "client_occurred_at": self.base_time.isoformat(),
            "payload": {
                "content_type": "question",
                "required": True,
                "target_layers": ["all"],
            },
        }
        self.post_events(self.teacher, [release])
        self.opportunity = LearningOpportunity.objects.get(student=self.student)
        self.attempt_id = uuid.uuid4()

    def submit_answer(self, *, occurred_at=None):
        raw = {
            "event_id": str(uuid.uuid4()),
            "event_name": "item.submitted",
            "schema_version": "1.0",
            "source": "student-web",
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "object_type": "question",
            "object_id": self.opportunity.object_id,
            "object_version": self.opportunity.object_version,
            "opportunity_id": str(self.opportunity.opportunity_id),
            "attempt_id": str(self.attempt_id),
            "client_occurred_at": (
                occurred_at or self.base_time + timedelta(minutes=1)
            ).isoformat(),
            "payload": {
                "question_version": self.opportunity.object_version,
                "response_kind": "text",
                "attempt_no": 1,
                "response_time_ms": 30_000,
            },
        }
        return self.post_events(self.student, [raw])

    def grade_event(self, state: str, *, score_raw, occurred_at):
        return {
            "event_id": str(uuid.uuid4()),
            "event_name": "item.graded",
            "schema_version": "1.0",
            "source": "teacher-web",
            "target_student_id": self.student.id,
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "object_type": "question",
            "object_id": self.opportunity.object_id,
            "object_version": self.opportunity.object_version,
            "opportunity_id": str(self.opportunity.opportunity_id),
            "attempt_id": str(self.attempt_id),
            "client_occurred_at": occurred_at.isoformat(),
            "payload": {
                "grading_state": state,
                "score_raw": score_raw,
                "score_max": 5,
                "is_correct": None,
                "grader_type": "teacher",
            },
        }

    def test_pending_then_final_preserves_subjective_grade_maturity(self):
        self.submit_answer()
        pending = self.post_events(
            self.teacher,
            [
                self.grade_event(
                    "pending",
                    score_raw=None,
                    occurred_at=self.base_time + timedelta(minutes=2),
                )
            ],
        )
        final = self.post_events(
            self.teacher,
            [
                self.grade_event(
                    "final",
                    score_raw=4,
                    occurred_at=self.base_time + timedelta(minutes=3),
                )
            ],
        )

        self.assertFalse(pending.data["data"]["results"][0]["assessment_result_mature"])
        self.assertTrue(final.data["data"]["results"][0]["assessment_result_mature"])
        facts = list(AssessmentResultFact.objects.order_by("grade_version"))
        self.assertEqual([fact.grade_version for fact in facts], [1, 2])
        self.assertEqual(facts[0].grading_state, "pending")
        self.assertIsNone(facts[0].score_raw)
        self.assertEqual(facts[1].grading_state, "final")
        self.assertEqual(facts[1].supersedes, facts[0])
        self.assertEqual(facts[1].normalized_score, Decimal("0.8"))
        self.assertEqual(
            self.opportunity.transition_facts.filter(state="graded").count(),
            1,
        )

    def test_revised_grade_appends_version_and_duplicate_final_is_rejected(self):
        self.submit_answer()
        final_raw = self.grade_event(
            "final",
            score_raw=3,
            occurred_at=self.base_time + timedelta(minutes=2),
        )
        self.post_events(self.teacher, [final_raw])
        duplicate_final = self.post_events(
            self.teacher,
            [
                self.grade_event(
                    "final",
                    score_raw=4,
                    occurred_at=self.base_time + timedelta(minutes=3),
                )
            ],
        )
        revised = self.post_events(
            self.teacher,
            [
                self.grade_event(
                    "revised",
                    score_raw=4,
                    occurred_at=self.base_time + timedelta(minutes=4),
                )
            ],
        )

        self.assertEqual(
            duplicate_final.data["data"]["results"][0]["error_code"],
            "final_grade_already_exists",
        )
        self.assertEqual(
            revised.data["data"]["results"][0]["assessment_result_version"],
            2,
        )
        facts = list(AssessmentResultFact.objects.order_by("grade_version"))
        self.assertEqual([fact.grading_state for fact in facts], ["final", "revised"])
        self.assertEqual(facts[1].supersedes, facts[0])
        facts[0].score_raw = Decimal("1")
        with self.assertRaises(ValidationError):
            facts[0].save()

    def test_grade_without_submission_rolls_back_event_and_result(self):
        response = self.post_events(
            self.teacher,
            [
                self.grade_event(
                    "final",
                    score_raw=4,
                    occurred_at=self.base_time + timedelta(minutes=1),
                )
            ],
        )

        self.assertEqual(
            response.data["data"]["results"][0]["error_code"],
            "grading_submission_required",
        )
        self.assertFalse(AssessmentResultFact.objects.exists())
        self.assertFalse(
            LearningEventV2.objects.filter(event_name="item.graded").exists()
        )
        self.assertFalse(
            LearningOpportunityTransitionFact.objects.filter(state="graded").exists()
        )

    def test_grade_requires_submission_from_the_same_attempt(self):
        self.submit_answer()
        self.attempt_id = uuid.uuid4()

        response = self.post_events(
            self.teacher,
            [
                self.grade_event(
                    "final",
                    score_raw=4,
                    occurred_at=self.base_time + timedelta(minutes=2),
                )
            ],
        )

        self.assertEqual(
            response.data["data"]["results"][0]["error_code"],
            "grading_submission_required",
        )
        self.assertFalse(AssessmentResultFact.objects.exists())


class ParticipationPointLedgerTests(AnalyticsFactTestBase):
    def test_award_deduction_reversal_and_cache_reconciliation(self):
        award_source = self.intervention_event(reason_code="quick_answer")
        award, created = record_participation_points(
            source_event=award_source,
            delta=5,
            reason_code="quick_answer_correct",
            awarded_by=self.teacher,
        )
        duplicate, duplicate_created = record_participation_points(
            source_event=award_source,
            delta=5,
            reason_code="quick_answer_correct",
            awarded_by=self.teacher,
        )
        deduction_source = self.intervention_event(reason_code="classroom_warning")
        deduction, _ = record_participation_points(
            source_event=deduction_source,
            delta=-3,
            reason_code="classroom_warning",
            awarded_by=self.teacher,
        )
        reversal_source = self.intervention_event(reason_code="teacher_correction")
        reversal, _ = record_participation_points(
            source_event=reversal_source,
            delta=3,
            reason_code="reverse_classroom_warning",
            awarded_by=self.teacher,
            reversal_of=deduction,
        )

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate, award)
        self.assertEqual(
            reversal.entry_type, ParticipationPointLedger.EntryType.REVERSAL
        )
        self.assertEqual(reversal.reversal_of, deduction)
        self.assertEqual(
            list(
                ParticipationPointLedger.objects.values_list("balance_after", flat=True)
            ),
            [Decimal("5.00"), Decimal("2.00"), Decimal("5.00")],
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 5)

        self.profile.score = 99
        self.profile.save(update_fields=["score", "updated_at"])
        audit = reconcile_participation_point_cache(student=self.student)
        self.assertFalse(audit["matches"])
        repaired = reconcile_participation_point_cache(
            student=self.student,
            apply=True,
        )
        self.assertTrue(repaired["updated"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 5)

        award.delta = Decimal("9")
        with self.assertRaises(ValidationError):
            award.save()

    def test_point_floor_source_conflict_and_double_reversal_are_rejected(self):
        source = self.intervention_event(reason_code="random_pick")
        entry, _ = record_participation_points(
            source_event=source,
            delta=2,
            reason_code="random_pick_response",
            awarded_by=self.teacher,
        )
        with self.assertRaises(ParticipationPointError) as conflict:
            record_participation_points(
                source_event=source,
                delta=3,
                reason_code="random_pick_response",
                awarded_by=self.teacher,
            )
        self.assertEqual(conflict.exception.code, "point_source_conflict")

        deduction_source = self.intervention_event(reason_code="classroom_warning")
        with self.assertRaises(ParticipationPointError) as insufficient:
            record_participation_points(
                source_event=deduction_source,
                delta=-3,
                reason_code="classroom_warning",
                awarded_by=self.teacher,
            )
        self.assertEqual(insufficient.exception.code, "point_balance_insufficient")

        reversal_source = self.intervention_event(reason_code="teacher_correction")
        reversal, _ = record_participation_points(
            source_event=reversal_source,
            delta=-2,
            reason_code="reverse_random_pick",
            awarded_by=self.teacher,
            reversal_of=entry,
        )
        self.assertEqual(reversal.balance_after, Decimal("0.00"))
        second_source = self.intervention_event(reason_code="teacher_correction")
        with self.assertRaises(ParticipationPointError) as repeated:
            record_participation_points(
                source_event=second_source,
                delta=-2,
                reason_code="reverse_random_pick_again",
                awarded_by=self.teacher,
                reversal_of=entry,
            )
        self.assertEqual(repeated.exception.code, "point_already_reversed")


class DualWriteServiceTests(AnalyticsFactTestBase):
    def setUp(self):
        super().setUp()
        self.course = Course.objects.create(
            subject=self.subject,
            title="双写测试课程",
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
            title="双写测试课时",
            is_active=True,
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="双写测试课堂",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )

    def write_intervention(self, *, event_id=None, class_group=None):
        return record_learning_event(
            actor=self.teacher,
            target_student=self.student,
            event_name="intervention.created",
            payload={
                "intervention_type": "individual_guidance",
                "reason_code": "task_blocked",
                "intensity": "low",
            },
            legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
            legacy_actor=self.student,
            class_group=class_group or self.class_group,
            subject=self.subject,
            course=self.course if class_group is None else None,
            lesson=self.lesson if class_group is None else None,
            classroom_session=self.session if class_group is None else None,
            object_type="student_support",
            object_id=self.student.id,
            legacy_metadata={"action": "individual_guidance"},
            event_id=event_id,
        )

    def test_dual_write_links_v1_v2_and_reconciles(self):
        result = self.write_intervention()

        self.assertEqual(result.write_mode, "dual_required")
        self.assertEqual(result.legacy_event.actor, self.student)
        self.assertEqual(result.analytics_event.actor, self.teacher)
        self.assertEqual(result.analytics_event.target_student, self.student)
        self.assertEqual(
            result.analytics_event.legacy_event,
            result.legacy_event,
        )
        self.assertTrue(result.legacy_event.metadata["analytics_dual_write"])
        self.assertEqual(
            result.legacy_event.metadata["analytics_event_id"],
            str(result.analytics_event.event_id),
        )
        audit = reconcile_v1_v2_events(school=self.school)
        self.assertTrue(audit["consistent"])
        self.assertEqual(audit["legacy_dual_write_count"], 1)
        self.assertEqual(audit["analytics_mapped_count"], 1)

    def test_v2_scope_failure_rolls_back_legacy_event(self):
        other_class = ClassGroup.objects.create(
            school=self.school,
            name="高一2班",
            grade="高一",
        )

        with self.assertRaises(EventWriteError) as raised:
            self.write_intervention(class_group=other_class)

        self.assertEqual(raised.exception.code, "class_scope_forbidden")
        self.assertFalse(LearningEvent.objects.exists())
        self.assertFalse(LearningEventV2.objects.exists())

    @override_settings(LEARNING_EVENT_WRITE_MODE="v1_only")
    def test_v1_only_emergency_mode_keeps_legacy_business_write(self):
        result = self.write_intervention()

        self.assertEqual(result.write_mode, "v1_only")
        self.assertIsNone(result.analytics_event)
        self.assertEqual(LearningEvent.objects.count(), 1)
        self.assertFalse(LearningEventV2.objects.exists())
        self.assertFalse(
            result.legacy_event.metadata.get("analytics_dual_write", False)
        )

    def test_point_score_replacement_uses_ledger_delta_and_is_retry_safe(self):
        first = record_classroom_point_adjustment(
            teacher=self.teacher,
            student_profile=self.profile,
            classroom_session=self.session,
            object_type="classroom_activity",
            object_id=9,
            reason_code="quick_answer_score_adjustment",
            requested_score=2,
            previous_event_action="quick_answer_score",
            legacy_metadata={"action": "quick_answer_score"},
        )
        second = record_classroom_point_adjustment(
            teacher=self.teacher,
            student_profile=self.profile,
            classroom_session=self.session,
            object_type="classroom_activity",
            object_id=9,
            reason_code="quick_answer_score_adjustment",
            requested_score=-1,
            previous_event_action="quick_answer_score",
            legacy_metadata={"action": "quick_answer_score"},
        )
        retry = record_classroom_point_adjustment(
            teacher=self.teacher,
            student_profile=self.profile,
            classroom_session=self.session,
            object_type="classroom_activity",
            object_id=9,
            reason_code="quick_answer_score_adjustment",
            requested_score=-1,
            previous_event_action="quick_answer_score",
            legacy_metadata={"action": "quick_answer_score"},
        )

        self.assertEqual(first.applied_delta, Decimal("2.00"))
        self.assertEqual(second.applied_delta, Decimal("-2.00"))
        self.assertEqual(second.balance_after, Decimal("0.00"))
        self.assertEqual(retry.applied_delta, Decimal("0.00"))
        self.assertIsNone(retry.event_write)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 0)
        self.assertEqual(LearningEvent.objects.count(), 2)
        self.assertEqual(LearningEventV2.objects.count(), 2)
        self.assertEqual(ParticipationPointLedger.objects.count(), 2)
        self.assertEqual(
            list(ParticipationPointLedger.objects.values_list("delta", flat=True)),
            [Decimal("2.00"), Decimal("-2.00")],
        )
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])
