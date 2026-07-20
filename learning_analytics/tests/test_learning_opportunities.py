from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Subject
from learning.models import StratificationDecision, StudentSubjectBand
from learning_analytics.models import (
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.opportunities import (
    OpportunityError,
    mark_opportunity_terminal,
)
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class LearningOpportunityApiTests(TestCase):
    endpoint = "/api/v1/learning-events/batch/"

    def setUp(self):
        sync_event_schema_definitions()
        self.school = School.objects.create(name="机会测试学校", code="OPPORTUNITY")
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
            username="opportunity_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.student_a = self.create_student("opportunity_a", StudentProfile.Layer.A)
        self.student_b = self.create_student("opportunity_b", StudentProfile.Layer.B)
        self.student_unassigned = self.create_student("opportunity_new", None)
        self.client = APIClient()

    def create_student(self, username: str, layer: str | None):
        user = User.objects.create_user(
            username=username,
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=user,
            class_group=self.class_group,
            current_layer=layer,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        if layer:
            decision = StratificationDecision.objects.create(
                student=user,
                class_group=self.class_group,
                subject=self.subject,
                suggested_layer=layer,
                decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
                policy_version="opportunity-test-v1",
                rule_version=f"opportunity-{username}-v1",
                status=StratificationDecision.Status.ACCEPTED,
            )
            StudentSubjectBand.objects.create(
                student=user,
                school=self.school,
                class_group=self.class_group,
                subject=self.subject,
                band=layer,
                valid_from=timezone.now() - timedelta(seconds=1),
                source_decision=decision,
                policy_version="opportunity-test-v1",
                confirmed_by=self.teacher,
            )
        return user

    def post_events(self, actor, events):
        self.client.force_authenticate(actor)
        return self.client.post(
            self.endpoint,
            {"batch_id": str(uuid.uuid4()), "events": events},
            format="json",
        )

    def release_event(
        self, *, target_layers=None, occurred_at=None, object_id="document-1"
    ):
        return {
            "event_id": str(uuid.uuid4()),
            "event_name": "content.released",
            "schema_version": "1.0",
            "source": "teacher-web",
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "object_type": "document",
            "object_id": object_id,
            "object_version": f"{object_id}@1",
            "client_occurred_at": (occurred_at or timezone.now()).isoformat(),
            "payload": {
                "content_type": "document",
                "required": True,
                "target_layers": target_layers or ["all"],
            },
        }

    def progress_event(
        self,
        opportunity: LearningOpportunity,
        *,
        actor=None,
        client_session_id=None,
        client_sequence=1,
        occurred_at=None,
        visible_seconds=20,
    ):
        return {
            "event_id": str(uuid.uuid4()),
            "event_name": "document.progress",
            "schema_version": "1.0",
            "source": "student-web",
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "object_type": "document",
            "object_id": opportunity.object_id,
            "object_version": opportunity.object_version,
            "opportunity_id": str(opportunity.opportunity_id),
            "client_session_id": str(client_session_id or uuid.uuid4()),
            "client_sequence": client_sequence,
            "client_occurred_at": (occurred_at or timezone.now()).isoformat(),
            "payload": {
                "page": 1,
                "page_count": 10,
                "visible_seconds": visible_seconds,
            },
        }

    def test_layer_targeted_release_creates_student_level_denominators(self):
        response = self.post_events(
            self.teacher,
            [self.release_event(target_layers=["A/B"])],
        )

        self.assertEqual(response.status_code, 200)
        result = response.data["data"]["results"][0]
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["opportunities_created"], 2)
        self.assertSetEqual(
            set(LearningOpportunity.objects.values_list("student_id", flat=True)),
            {self.student_a.id, self.student_b.id},
        )
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                state=LearningOpportunityTransitionFact.State.ASSIGNED
            ).count(),
            2,
        )
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                state=LearningOpportunityTransitionFact.State.RELEASED
            ).count(),
            2,
        )
        self.assertTrue(
            all(
                value == "A/B"
                for value in LearningOpportunity.objects.values_list(
                    "delivered_band", flat=True
                )
            )
        )

    def test_common_release_includes_student_without_current_band(self):
        response = self.post_events(
            self.teacher, [self.release_event(target_layers=["all"])]
        )
        self.assertEqual(
            response.data["data"]["results"][0]["opportunities_created"], 3
        )
        self.assertTrue(
            LearningOpportunity.objects.filter(student=self.student_unassigned).exists()
        )

    def test_progress_requires_owned_opportunity_and_records_process_states(self):
        self.post_events(self.teacher, [self.release_event(target_layers=["all"])])
        opportunity = LearningOpportunity.objects.get(student=self.student_a)

        accepted = self.post_events(
            self.student_a,
            [self.progress_event(opportunity)],
        )
        stolen = self.post_events(
            self.student_b,
            [self.progress_event(opportunity)],
        )

        self.assertEqual(accepted.data["data"]["results"][0]["status"], "accepted")
        self.assertEqual(
            accepted.data["data"]["results"][0]["opportunity_states_recorded"],
            2,
        )
        self.assertEqual(
            stolen.data["data"]["results"][0]["error_code"], "opportunity_forbidden"
        )
        event = LearningEventV2.objects.get(event_name="document.progress")
        self.assertEqual(event.opportunity_id, opportunity.opportunity_id)
        self.assertEqual(event.opportunity_record, opportunity)
        self.assertSetEqual(
            set(opportunity.transition_facts.values_list("state", flat=True)),
            {"assigned", "released", "exposed", "started"},
        )

    def test_random_opportunity_uuid_is_rejected(self):
        self.post_events(self.teacher, [self.release_event(target_layers=["all"])])
        opportunity = LearningOpportunity.objects.get(student=self.student_a)
        raw = self.progress_event(opportunity)
        raw["opportunity_id"] = str(uuid.uuid4())

        response = self.post_events(self.student_a, [raw])

        self.assertEqual(
            response.data["data"]["results"][0]["error_code"], "opportunity_not_found"
        )
        self.assertFalse(
            LearningEventV2.objects.filter(event_name="document.progress").exists()
        )

    def test_withdrawal_preserves_fact_and_blocks_later_progress(self):
        release_raw = self.release_event(target_layers=["all"])
        self.post_events(self.teacher, [release_raw])
        opportunity = LearningOpportunity.objects.get(student=self.student_a)
        withdrawal = {
            "event_id": str(uuid.uuid4()),
            "event_name": "content.withdrawn",
            "schema_version": "1.0",
            "source": "teacher-web",
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "client_occurred_at": (timezone.now() + timedelta(seconds=1)).isoformat(),
            "payload": {
                "release_event_id": release_raw["event_id"],
                "reason_code": "teacher_replaced_content",
            },
        }
        withdrawn = self.post_events(self.teacher, [withdrawal])
        progress = self.post_events(
            self.student_a,
            [
                self.progress_event(
                    opportunity,
                    occurred_at=timezone.now() + timedelta(seconds=2),
                )
            ],
        )

        self.assertEqual(
            withdrawn.data["data"]["results"][0]["opportunities_withdrawn"], 3
        )
        terminal = opportunity.transition_facts.get(state="withdrawn")
        self.assertEqual(terminal.reason_code, "teacher_replaced_content")
        self.assertEqual(
            progress.data["data"]["results"][0]["error_code"], "opportunity_closed"
        )

    def test_late_earlier_progress_is_appended_without_overwrite(self):
        released_at = timezone.now() - timedelta(minutes=10)
        self.post_events(
            self.teacher,
            [self.release_event(target_layers=["all"], occurred_at=released_at)],
        )
        opportunity = LearningOpportunity.objects.get(student=self.student_a)
        client_session_id = uuid.uuid4()
        later = self.progress_event(
            opportunity,
            client_session_id=client_session_id,
            client_sequence=2,
            occurred_at=timezone.now(),
        )
        earlier = self.progress_event(
            opportunity,
            client_session_id=client_session_id,
            client_sequence=1,
            occurred_at=timezone.now() - timedelta(minutes=5),
        )

        self.post_events(self.student_a, [later])
        self.post_events(self.student_a, [earlier])

        exposed = list(
            opportunity.transition_facts.filter(state="exposed").order_by("occurred_at")
        )
        self.assertEqual(len(exposed), 2)
        self.assertTrue(exposed[0].metadata["late_earlier_evidence"])
        self.assertLess(exposed[0].occurred_at, exposed[1].occurred_at)

    def test_terminal_excused_and_unavailable_are_distinct_and_immutable(self):
        self.post_events(self.teacher, [self.release_event(target_layers=["all"])])
        opportunities = {
            item.student_id: item for item in LearningOpportunity.objects.all()
        }

        def intervention(student, reason):
            raw = {
                "event_id": str(uuid.uuid4()),
                "event_name": "intervention.created",
                "schema_version": "1.0",
                "source": "teacher-web",
                "target_student_id": student.id,
                "class_id": self.class_group.id,
                "subject_id": self.subject.id,
                "client_occurred_at": (
                    timezone.now() + timedelta(seconds=1)
                ).isoformat(),
                "payload": {
                    "intervention_type": "opportunity_status",
                    "reason_code": reason,
                    "intensity": "low",
                },
            }
            self.post_events(self.teacher, [raw])
            return LearningEventV2.objects.get(event_id=raw["event_id"])

        excused_source = intervention(self.student_a, "approved_leave")
        unavailable_source = intervention(self.student_b, "device_failure")
        excused = mark_opportunity_terminal(
            opportunity=opportunities[self.student_a.id],
            state=LearningOpportunityTransitionFact.State.EXCUSED,
            source_event=excused_source,
            reason_code="approved_leave",
        )
        unavailable = mark_opportunity_terminal(
            opportunity=opportunities[self.student_b.id],
            state=LearningOpportunityTransitionFact.State.UNAVAILABLE,
            source_event=unavailable_source,
            reason_code="device_failure",
        )

        self.assertEqual(excused.state, "excused")
        self.assertEqual(unavailable.state, "unavailable")
        with self.assertRaises(OpportunityError):
            mark_opportunity_terminal(
                opportunity=opportunities[self.student_a.id],
                state=LearningOpportunityTransitionFact.State.UNAVAILABLE,
                source_event=excused_source,
                reason_code="conflict",
            )
        opportunities[self.student_a.id].required = False
        with self.assertRaises(ValidationError):
            opportunities[self.student_a.id].save()
        excused.reason_code = "tampered"
        with self.assertRaises(ValidationError):
            excused.save()
