from __future__ import annotations

import copy
import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Subject
from learning_analytics.models import LearningEventRejection, LearningEventV2
from learning_analytics.services.quarantine import decrypt_quarantined_envelope
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class LearningEventBatchApiTests(TestCase):
    endpoint = "/api/v1/learning-events/batch/"

    def setUp(self):
        sync_event_schema_definitions()
        self.school = School.objects.create(name="批量事件学校", code="EVENT-BATCH")
        self.other_school = School.objects.create(name="外校", code="EVENT-OTHER")
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.other_class = ClassGroup.objects.create(
            school=self.school, name="高一2班", grade="高一"
        )
        self.subject = Subject.objects.create(
            school=self.school, name="信息科技", code="IT"
        )
        self.teacher = User.objects.create_user(
            username="batch_teacher",
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
            username="batch_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        self.peer = User.objects.create_user(
            username="batch_peer",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.peer,
            class_group=self.class_group,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        self.school_admin = User.objects.create_user(
            username="batch_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.client = APIClient()

    def heartbeat_event(self, **overrides):
        value = {
            "event_id": str(uuid.uuid4()),
            "event_name": "session.heartbeat",
            "schema_version": "1.0",
            "source": "student-web",
            "client_version": "2.0.0",
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "client_session_id": str(uuid.uuid4()),
            "client_sequence": 1,
            "client_occurred_at": timezone.now().isoformat(),
            "duration_ms": 30_000,
            "payload": {
                "foreground": True,
                "idle_seconds": 2,
                "network_state": "online",
            },
        }
        value.update(overrides)
        return value

    def post_events(self, actor, events):
        self.client.force_authenticate(actor)
        return self.client.post(
            self.endpoint,
            {
                "batch_id": str(uuid.uuid4()),
                "sent_at": timezone.now().isoformat(),
                "events": events,
            },
            format="json",
        )

    def test_accepts_event_and_rebuilds_actor_school_and_target(self):
        raw = self.heartbeat_event()
        response = self.post_events(self.student, [raw])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"]["counts"],
            {"accepted": 1, "duplicate": 0, "rejected": 0},
        )
        event = LearningEventV2.objects.get()
        self.assertEqual(event.actor, self.student)
        self.assertEqual(event.target_student, self.student)
        self.assertEqual(event.school, self.school)
        self.assertEqual(event.class_group, self.class_group)
        self.assertEqual(event.source, "student-web")
        self.assertEqual(event.client_sequence, 1)
        self.assertEqual(event.quality_status, LearningEventV2.QualityStatus.ACCEPTED)
        self.assertTrue(event.idempotency_key)
        self.assertTrue(event.event_fingerprint)

    def test_exact_and_secondary_idempotent_retries_are_duplicates(self):
        raw = self.heartbeat_event()
        first = self.post_events(self.student, [raw])
        exact_retry = self.post_events(self.student, [raw])
        changed_uuid = copy.deepcopy(raw)
        changed_uuid["event_id"] = str(uuid.uuid4())
        secondary_retry = self.post_events(self.student, [changed_uuid])

        self.assertEqual(first.data["data"]["results"][0]["status"], "accepted")
        self.assertEqual(exact_retry.data["data"]["results"][0]["status"], "duplicate")
        self.assertEqual(
            secondary_retry.data["data"]["results"][0]["status"], "duplicate"
        )
        self.assertEqual(LearningEventV2.objects.count(), 1)
        self.assertEqual(LearningEventRejection.objects.count(), 0)

    def test_idempotency_conflict_is_rejected_and_encrypted(self):
        raw = self.heartbeat_event()
        self.post_events(self.student, [raw])
        conflicting = copy.deepcopy(raw)
        conflicting["event_id"] = str(uuid.uuid4())
        conflicting["payload"]["idle_seconds"] = 99
        conflicting["private_probe"] = "CONFIDENTIAL-PLAINTEXT"

        response = self.post_events(self.student, [conflicting])

        result = response.data["data"]["results"][0]
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error_code"], "schema_invalid")
        rejection = LearningEventRejection.objects.get()
        self.assertNotIn("CONFIDENTIAL-PLAINTEXT", rejection.encrypted_envelope)
        decrypted = decrypt_quarantined_envelope(rejection.encrypted_envelope)
        self.assertEqual(decrypted["private_probe"], "CONFIDENTIAL-PLAINTEXT")
        self.assertTrue(rejection.is_replayable)

    def test_same_sequence_with_different_valid_content_is_idempotency_conflict(self):
        raw = self.heartbeat_event()
        self.post_events(self.student, [raw])
        conflicting = copy.deepcopy(raw)
        conflicting["event_id"] = str(uuid.uuid4())
        conflicting["payload"]["idle_seconds"] = 8

        response = self.post_events(self.student, [conflicting])

        result = response.data["data"]["results"][0]
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error_code"], "idempotency_conflict")
        self.assertEqual(LearningEventV2.objects.count(), 1)

    def test_accepts_out_of_order_and_marks_late_arrival(self):
        client_session_id = str(uuid.uuid4())
        recent = self.heartbeat_event(
            client_session_id=client_session_id, client_sequence=2
        )
        late = self.heartbeat_event(
            client_session_id=client_session_id,
            client_sequence=1,
            client_occurred_at=(timezone.now() - timedelta(days=2)).isoformat(),
        )

        response = self.post_events(self.student, [recent, late])

        self.assertEqual(response.data["data"]["counts"]["accepted"], 2)
        results = response.data["data"]["results"]
        self.assertEqual(results[0]["quality_errors"], [])
        self.assertEqual(results[1]["quality_errors"], ["late_arrival_24h"])
        self.assertEqual(
            LearningEventV2.objects.get(client_sequence=1).quality_errors,
            ["late_arrival_24h"],
        )

    def test_rejects_spoofed_scope_and_unknown_fields_per_item(self):
        spoofed_target = self.heartbeat_event(target_student_id=self.peer.id)
        spoofed_school = self.heartbeat_event(
            school_id=self.other_school.id, actor_id=self.peer.id
        )
        response = self.post_events(self.student, [spoofed_target, spoofed_school])

        results = response.data["data"]["results"]
        self.assertEqual([item["status"] for item in results], ["rejected", "rejected"])
        self.assertEqual(results[0]["error_code"], "target_forbidden")
        self.assertEqual(results[1]["error_code"], "schema_invalid")
        self.assertEqual(LearningEventV2.objects.count(), 0)
        self.assertEqual(LearningEventRejection.objects.count(), 2)

    def test_teacher_can_submit_only_for_assigned_class(self):
        accepted = {
            "event_id": str(uuid.uuid4()),
            "event_name": "intervention.created",
            "schema_version": "1.0",
            "source": "teacher-web",
            "target_student_id": self.student.id,
            "class_id": self.class_group.id,
            "subject_id": self.subject.id,
            "client_occurred_at": timezone.now().isoformat(),
            "payload": {
                "intervention_type": "individual_guidance",
                "reason_code": "task_blocked",
                "intensity": "low",
            },
        }
        denied = copy.deepcopy(accepted)
        denied["event_id"] = str(uuid.uuid4())
        denied["class_id"] = self.other_class.id

        response = self.post_events(self.teacher, [accepted, denied])

        self.assertEqual(response.data["data"]["results"][0]["status"], "accepted")
        self.assertEqual(
            response.data["data"]["results"][1]["error_code"], "class_scope_forbidden"
        )
        event = LearningEventV2.objects.get()
        self.assertEqual(event.actor, self.teacher)
        self.assertEqual(event.target_student, self.student)

    def test_school_admin_and_oversized_batches_are_rejected(self):
        forbidden = self.post_events(self.school_admin, [self.heartbeat_event()])
        self.assertEqual(forbidden.status_code, 403)

        events = [self.heartbeat_event() for _ in range(201)]
        oversized = self.post_events(self.student, events)
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(LearningEventV2.objects.count(), 0)
        self.assertEqual(LearningEventRejection.objects.count(), 0)
