from __future__ import annotations

from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from config.onlyoffice import encode_jwt
from courses.models import (
    ClassroomGroupCollaboration,
    ClassroomGroupDocumentVersion,
    ClassroomGroupFile,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    Subject,
)
from learning.models import LearningEvent
from learning_analytics.models import (
    GroupingOpportunityAudit,
    GroupingOutcomeSnapshot,
    GroupingPairHistory,
    GroupingPlanVersion,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import reconcile_v1_v2_events
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class GroupCollaborationEventTests(TestCase):
    jwt_secret = "group-callback-test-secret"

    def setUp(self):
        self.media = TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media.name,
            ONLYOFFICE_JWT_SECRET=self.jwt_secret,
            ONLYOFFICE_DOCUMENT_SERVER_URL="http://onlyoffice.test",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media.cleanup)

        self.school = School.objects.create(name="协作测试学校", code="GROUP-EVENT")
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.subject = Subject.objects.create(
            school=self.school, name="信息科技", code="IT-GROUP"
        )
        self.teacher = User.objects.create_user(
            username="group_teacher",
            password="Teacher123!",
            display_name="协作教师",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.course = Course.objects.create(
            title="协作课程",
            teacher=self.teacher,
            subject=self.subject,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(title="协作课时", course=self.course)
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="小组协作课堂",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        self.students = []
        for index in range(1, 5):
            student = User.objects.create_user(
                username=f"group_student{index}",
                password="123456",
                display_name=f"学生{index}",
                role=User.Role.STUDENT,
                school=self.school,
            )
            StudentProfile.objects.create(
                user=student,
                class_group=self.class_group,
                is_first_use=False,
                onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
            )
            self.students.append(student)
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    def setup_collaboration(self):
        response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/setup/",
            {
                "group_size": 2,
                "grouping_strategy": "random",
                "document_type": "docx",
                "storage_quota_mb": 10,
                "allow_student_upload": True,
                "allow_onlyoffice_edit": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return ClassroomGroupCollaboration.objects.get(session=self.session)

    def test_group_storage_defaults_to_twenty_mb(self):
        response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/setup/",
            {
                "group_size": 2,
                "grouping_strategy": "random",
                "document_type": "docx",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["storage_quota_mb"], 20)
        self.assertEqual(
            ClassroomGroupCollaboration.objects.get(session=self.session).storage_quota_mb,
            20,
        )

    def test_group_opportunities_are_member_scoped_and_evidence_blocks_regrouping(self):
        collaboration = self.setup_collaboration()
        groups = list(
            collaboration.groups.prefetch_related("members").order_by("group_no")
        )
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(group.document_versions.count() == 1 for group in groups))

        releases = LearningEventV2.objects.filter(
            event_name="content.released",
            schema_version="1.1",
            classroom_session=self.session,
        )
        self.assertEqual(releases.count(), 4)
        self.assertEqual(LearningOpportunity.objects.count(), 8)
        for release in releases:
            group = next(item for item in groups if str(item.id) == release.object_id)
            member_ids = set(group.members.values_list("student_id", flat=True))
            self.assertSetEqual(set(release.payload["target_student_ids"]), member_ids)
            self.assertSetEqual(
                set(
                    release.released_opportunities.values_list("student_id", flat=True)
                ),
                member_ids,
            )

        group = groups[0]
        student = group.members.order_by("id").first().student
        self.client.force_authenticate(student)
        opened = self.client.get(
            f"/api/v1/classroom/groups/{group.id}/office-config/?mode=edit"
        )
        self.assertEqual(opened.status_code, 200, opened.data)
        opened_event = LearningEventV2.objects.get(event_name="group.document.opened")
        self.assertEqual(opened_event.target_student, student)
        self.assertEqual(opened_event.payload["editor_mode"], "edit")
        document_opportunity = LearningOpportunity.objects.get(
            student=student,
            content_type=LearningOpportunity.ContentType.DOCUMENT,
            object_id=str(group.id),
        )
        self.assertSetEqual(
            set(document_opportunity.transition_facts.values_list("state", flat=True)),
            {"assigned", "released", "exposed", "started"},
        )

        uploaded = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/group-collaboration/files/",
            {
                "attachment": SimpleUploadedFile(
                    "team-notes.txt", b"group evidence", "text/plain"
                ),
                "description": "阶段讨论记录",
            },
            format="multipart",
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        group_file = ClassroomGroupFile.objects.get()
        shared_event = LearningEventV2.objects.get(event_name="group.file.shared")
        self.assertEqual(shared_event.attempt_id, group_file.analytics_attempt_id)
        self.assertEqual(shared_event.payload["file_ext"], "txt")
        self.assertNotIn("filename", shared_event.payload)
        self.assertNotIn("description", shared_event.payload)

        self.client.force_authenticate(self.teacher)
        regenerate = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/setup/",
            {
                "group_size": 2,
                "grouping_strategy": "random",
                "document_type": "docx",
                "regenerate": True,
            },
            format="json",
        )
        self.assertEqual(regenerate.status_code, 200, regenerate.data)
        collaboration.refresh_from_db()
        self.assertEqual(collaboration.active_plan_version, 2)
        self.assertEqual(collaboration.groups.count(), 4)
        self.assertEqual(collaboration.groups.filter(is_active=True).count(), 2)
        self.assertEqual(collaboration.groups.filter(is_active=False).count(), 2)
        self.assertTrue(ClassroomGroupFile.objects.filter(pk=group_file.pk).exists())

        closed = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/close/",
            {},
            format="json",
        )
        self.assertEqual(closed.status_code, 200, closed.data)
        collaboration.refresh_from_db()
        self.assertEqual(
            collaboration.status, ClassroomGroupCollaboration.Status.CLOSED
        )
        self.assertFalse(collaboration.is_enabled)
        self.assertTrue(
            document_opportunity.transition_facts.filter(state="withdrawn").exists()
        )
        workspace_opportunity = LearningOpportunity.objects.get(
            student=student,
            content_type=LearningOpportunity.ContentType.TASK,
            object_id=str(group.id),
        )
        self.assertTrue(
            workspace_opportunity.transition_facts.filter(state="submitted").exists()
        )
        self.assertFalse(
            workspace_opportunity.transition_facts.filter(state="withdrawn").exists()
        )
        self.client.force_authenticate(student)
        closed_document = self.client.get(
            f"/api/v1/classroom/groups/{group.id}/office-config/?mode=view"
        )
        self.assertEqual(closed_document.status_code, 200, closed_document.data)
        self.assertFalse(closed_document.data["data"]["can_edit"])
        self.assertEqual(closed_document.data["data"]["mode"], "view")
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_candidate_plan_confirmation_preserves_history_and_captures_outcomes(self):
        collaboration = self.setup_collaboration()
        original_group_ids = list(collaboration.groups.values_list("id", flat=True))

        candidate_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/candidates/",
            {
                "group_size": 2,
                "grouping_strategy": "random",
                "document_type": "pptx",
                "storage_quota_mb": 25,
                "allow_student_upload": True,
                "allow_onlyoffice_edit": True,
                "locked_assignments": {},
            },
            format="json",
        )
        self.assertEqual(candidate_response.status_code, 201, candidate_response.data)
        run = candidate_response.data["data"]
        candidate = run["candidates"][0]
        self.assertEqual(candidate["key"], "random")
        self.assertEqual(candidate["fairness"]["unique_student_count"], 4)

        confirm_payload = {
            "candidate_key": candidate["key"],
            "adjustments": {
                "student_groups": {
                    str(member["student_id"]): group["group_no"]
                    for group in candidate["assignments"]
                    for member in group["members"]
                },
                "roles": {
                    str(member["student_id"]): member["role"]
                    for group in candidate["assignments"]
                    for member in group["members"]
                },
            },
            "note": "课堂分组候选验收",
        }
        event_push = patch("api.views.publish_chat_event")
        mocked_push = event_push.start()
        self.addCleanup(event_push.stop)
        confirm_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/candidates/{run['id']}/confirm/",
            confirm_payload,
            format="json",
        )
        self.assertEqual(confirm_response.status_code, 200, confirm_response.data)
        mocked_push.assert_called_once()
        self.assertEqual(mocked_push.call_args.args[1]["type"], "grouping.updated")
        collaboration.refresh_from_db()
        self.assertEqual(collaboration.active_plan_version, 2)
        self.assertEqual(collaboration.document_type, "pptx")
        self.assertTrue(
            collaboration.groups.filter(
                pk__in=original_group_ids, is_active=False
            ).exists()
        )
        self.assertEqual(
            collaboration.members.filter(plan_version=2)
            .values("student_id")
            .distinct()
            .count(),
            4,
        )
        plan = GroupingPlanVersion.objects.get(
            collaboration=collaboration,
            plan_version=2,
        )
        self.assertEqual(GroupingOpportunityAudit.objects.filter(plan=plan).count(), 4)
        self.assertGreater(
            GroupingPairHistory.objects.filter(class_group=self.class_group).count(), 0
        )

        plan_count = GroupingPlanVersion.objects.filter(
            collaboration=collaboration
        ).count()
        pair_counts = list(
            GroupingPairHistory.objects.filter(class_group=self.class_group)
            .order_by("id")
            .values_list("id", "collaboration_count")
        )
        repeated_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/candidates/{run['id']}/confirm/",
            confirm_payload,
            format="json",
        )
        self.assertEqual(repeated_response.status_code, 200, repeated_response.data)
        self.assertEqual(
            GroupingPlanVersion.objects.filter(collaboration=collaboration).count(),
            plan_count,
        )
        self.assertEqual(
            list(
                GroupingPairHistory.objects.filter(class_group=self.class_group)
                .order_by("id")
                .values_list("id", "collaboration_count")
            ),
            pair_counts,
        )
        mocked_push.assert_called_once()

        close_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/close/",
            {},
            format="json",
        )
        self.assertEqual(close_response.status_code, 200, close_response.data)
        self.assertEqual(GroupingOutcomeSnapshot.objects.filter(plan=plan).count(), 2)
        outcome = GroupingOutcomeSnapshot.objects.filter(plan=plan).first()
        self.assertIn("document_version", outcome.group_result)
        self.assertIn("shared_file_count", outcome.group_result)
        self.assertTrue(outcome.individual_results)
        self.assertSetEqual(
            set(outcome.individual_results[0]),
            {
                "student_id",
                "role",
                "shared_file_count",
                "mastery_snapshot_id",
                "mastery_score",
                "mastery_data_status",
            },
        )

    def test_candidate_confirmation_rejects_moving_a_locked_student(self):
        self.setup_collaboration()
        locked_student_id = self.students[0].id
        candidate_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/candidates/",
            {
                "group_size": 2,
                "grouping_strategy": "random",
                "locked_assignments": {str(locked_student_id): 1},
            },
            format="json",
        )
        self.assertEqual(candidate_response.status_code, 201, candidate_response.data)
        run = candidate_response.data["data"]
        candidate = run["candidates"][0]
        source_group = next(
            group
            for group in candidate["assignments"]
            if any(
                member["student_id"] == locked_student_id for member in group["members"]
            )
        )
        target_group = next(
            group
            for group in candidate["assignments"]
            if group["group_no"] != source_group["group_no"]
        )
        swap_student_id = target_group["members"][0]["student_id"]
        confirm_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/group-collaboration/candidates/{run['id']}/confirm/",
            {
                "candidate_key": candidate["key"],
                "adjustments": {
                    "student_groups": {
                        str(locked_student_id): target_group["group_no"],
                        str(swap_student_id): source_group["group_no"],
                    }
                },
            },
            format="json",
        )
        self.assertEqual(confirm_response.status_code, 400, confirm_response.data)
        self.assertFalse(
            GroupingPlanVersion.objects.filter(candidate_run_id=run["id"]).exists()
        )

    def test_onlyoffice_callback_requires_signed_payload_and_versions_real_changes(
        self,
    ):
        collaboration = self.setup_collaboration()
        group = collaboration.groups.order_by("group_no").first()
        self.assertEqual(group.document_versions.count(), 1)

        config_response = self.client.get(
            f"/api/v1/classroom/groups/{group.id}/office-config/?mode=edit"
        )
        self.assertEqual(config_response.status_code, 200, config_response.data)
        callback_key = config_response.data["data"]["config"]["document"]["key"]
        callback_payload = {
            "key": callback_key,
            "status": 2,
            "url": "http://onlyoffice.test/cache/group-document.docx",
            "users": [str(self.teacher.id)],
            "actions": [{"type": 0, "userId": str(self.teacher.id)}],
        }
        token = encode_jwt(callback_payload, self.jwt_secret)
        changed_document = b"changed group office document"

        self.client.force_authenticate(user=None)
        with patch(
            "api.views._download_onlyoffice_callback_file",
            return_value=changed_document,
        ):
            callback = self.client.post(
                f"/api/v1/classroom/groups/{group.id}/office-callback/",
                callback_payload,
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
        self.assertEqual(callback.status_code, 200, callback.content)
        self.assertEqual(callback.json(), {"error": 0})

        group.refresh_from_db()
        self.assertEqual(group.document_version, 2)
        self.assertEqual(group.document_versions.count(), 2)
        version = group.document_versions.get(version_no=2)
        self.assertEqual(
            version.source,
            ClassroomGroupDocumentVersion.Source.ONLYOFFICE_CALLBACK,
        )
        self.assertEqual(version.verified_editor_ids, [str(self.teacher.id)])
        saved_event = LearningEventV2.objects.get(event_name="group.document.saved")
        self.assertIsNone(saved_event.target_student)
        self.assertEqual(saved_event.analysis_unit, "group")
        self.assertEqual(saved_event.payload["attribution"], "group_only")
        self.assertEqual(saved_event.payload["verified_editor_count"], 1)

        with patch(
            "api.views._download_onlyoffice_callback_file",
            return_value=changed_document,
        ):
            duplicate = self.client.post(
                f"/api/v1/classroom/groups/{group.id}/office-callback/",
                callback_payload,
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
        self.assertEqual(duplicate.status_code, 200, duplicate.content)
        self.assertEqual(group.document_versions.count(), 2)
        self.assertEqual(
            LearningEventV2.objects.filter(event_name="group.document.saved").count(),
            1,
        )

        version.callback_key = "tampered"
        with self.assertRaises(ValidationError):
            version.save()

        tampered_payload = dict(callback_payload)
        tampered_payload["url"] = "http://attacker.test/stolen.docx"
        rejected = self.client.post(
            f"/api/v1/classroom/groups/{group.id}/office-callback/",
            tampered_payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(rejected.status_code, 403, rejected.content)
        self.assertEqual(group.document_versions.count(), 2)
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_finishing_classroom_closes_collaboration_and_withdraws_open_work(self):
        collaboration = self.setup_collaboration()
        self.assertEqual(LearningOpportunity.objects.count(), 8)

        finished = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/finish/",
            {},
            format="json",
        )
        self.assertEqual(finished.status_code, 200, finished.data)
        collaboration.refresh_from_db()
        self.assertEqual(
            collaboration.status, ClassroomGroupCollaboration.Status.CLOSED
        )
        self.assertFalse(collaboration.is_enabled)
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                opportunity__classroom_session=self.session,
                state="withdrawn",
            ).count(),
            8,
        )

    @override_settings(LEARNING_EVENT_WRITE_MODE="v1_only")
    def test_v1_only_rollback_mode_keeps_group_document_and_upload_available(self):
        collaboration = self.setup_collaboration()
        group = collaboration.groups.prefetch_related("members").first()
        student = group.members.first().student
        self.assertEqual(LearningOpportunity.objects.count(), 0)

        self.client.force_authenticate(student)
        opened = self.client.get(
            f"/api/v1/classroom/groups/{group.id}/office-config/?mode=edit"
        )
        uploaded = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/group-collaboration/files/",
            {
                "attachment": SimpleUploadedFile(
                    "fallback.txt", b"fallback evidence", "text/plain"
                )
            },
            format="multipart",
        )
        self.assertEqual(opened.status_code, 200, opened.data)
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        self.assertEqual(LearningEventV2.objects.count(), 0)
        self.assertSetEqual(
            set(
                LearningEvent.objects.filter(actor=student).values_list(
                    "metadata__action", flat=True
                )
            ),
            {"group_document_open", "group_file_upload"},
        )
