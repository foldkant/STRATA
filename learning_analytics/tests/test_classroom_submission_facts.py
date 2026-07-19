from __future__ import annotations

import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    LearningWebPage,
    LearningWebPageResponse,
    Lesson,
    LessonStep,
    Resource,
    Subject,
)
from learning.models import LessonStepAttempt, StudentWorkAttachment
from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import reconcile_v1_v2_events
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class ClassroomSubmissionFactTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="strata-classroom-tests-")
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.school = School.objects.create(name="课堂事实测试学校", code="CLASS-FACT")
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.teacher = User.objects.create_user(
            username="class_fact_teacher",
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
            username="class_fact_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="学生甲",
        )
        self.peer = User.objects.create_user(
            username="class_fact_peer",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="学生乙",
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
        )
        StudentProfile.objects.create(
            user=self.peer,
            class_group=self.class_group,
            is_first_use=False,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="课堂事实课程",
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
            title="课堂事实课时",
            is_active=True,
        )
        self.step = LessonStep.objects.create(
            lesson=self.lesson,
            title="课堂综合练习",
            status=LessonStep.Status.READY,
            question_items=[
                {
                    "id": "q-single",
                    "question_type": "single",
                    "stem": "二进制 10 对应的十进制数是？",
                    "options": ["1", "2", "3"],
                    "answer": ["2"],
                    "score": 2,
                    "is_required": True,
                    "target_layer": "all",
                },
                {
                    "id": "q-text",
                    "question_type": "text",
                    "stem": "说明二进制适合计算机处理的原因。",
                    "answer": [],
                    "score": 5,
                    "is_required": True,
                    "target_layer": "all",
                },
                {
                    "id": "q-file",
                    "question_type": "file",
                    "stem": "提交本节课的实践作品。",
                    "answer": [],
                    "score": 10,
                    "is_required": True,
                    "target_layer": "all",
                    "file_config": {
                        "allowed_extensions": ["txt"],
                        "max_size_mb": 1,
                    },
                },
            ],
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="课堂事实测试",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        self.client = APIClient()

    def open_step(self):
        self.client.force_authenticate(self.teacher)
        return self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/step/open/",
            {"step_id": self.step.id},
            format="json",
        )

    def upload(self, content: bytes, name: str):
        self.client.force_authenticate(self.student)
        return self.client.post(
            f"/api/v1/student/lesson-steps/{self.step.id}/attachments/",
            {
                "question_id": "q-file",
                "attachment": SimpleUploadedFile(name, content, "text/plain"),
            },
            format="multipart",
        )

    def submit_step(self, attachment_data: dict):
        self.client.force_authenticate(self.student)
        return self.client.post(
            f"/api/v1/student/lesson-steps/{self.step.id}/answer/",
            {
                "answer": {
                    "questions": {
                        "q-single": "2",
                        "q-text": "二进制状态稳定且便于电子电路表示。",
                        "q-file": attachment_data,
                    },
                    "text": "课堂提交",
                }
            },
            format="json",
        )

    def test_release_submission_and_grading_are_versioned_and_reconciled(self):
        opened = self.open_step()
        self.assertEqual(opened.status_code, 200, opened.data)
        self.assertEqual(
            LearningEventV2.objects.filter(event_name="content.released").count(),
            3,
        )
        self.assertEqual(LearningOpportunity.objects.count(), 6)

        first_upload = self.upload(b"first version", "first.txt")
        second_upload = self.upload(b"second version", "second.txt")
        self.assertEqual(first_upload.status_code, 201)
        self.assertEqual(second_upload.status_code, 201, second_upload.data)
        works = list(StudentWorkAttachment.objects.order_by("upload_version"))
        self.assertEqual([item.upload_version for item in works], [1, 2])
        self.assertEqual(works[1].supersedes, works[0])
        self.assertTrue(works[0].attachment.storage.exists(works[0].attachment.name))

        submitted = self.submit_step(second_upload.data["data"])
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.data["data"]["attempt_no"], 1)
        attempt = LessonStepAttempt.objects.get(student=self.student)
        self.assertEqual(attempt.answer_rows.count(), 3)
        self.assertEqual(
            attempt.answer_rows.get(question_id="q-file").attachment,
            works[1],
        )

        submitted_events = LearningEventV2.objects.filter(
            event_name__in=["item.submitted", "task.submitted"]
        )
        self.assertEqual(submitted_events.count(), 4)
        self.assertFalse(submitted_events.filter(payload__has_key="answer").exists())
        facts = AssessmentResultFact.objects.filter(student=self.student)
        self.assertEqual(facts.count(), 4)
        self.assertEqual(
            facts.filter(grading_state="pending").count(),
            3,
        )
        objective = facts.get(
            opportunity__object_id=f"lesson-step-question:{self.step.id}:q-single"
        )
        self.assertEqual(objective.grading_state, "final")
        self.assertEqual(float(objective.score_raw), 2)

        self.client.force_authenticate(self.teacher)
        scored = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/attachments/{works[1].id}/score/",
            {"score": 8, "feedback": "结构完整。"},
            format="json",
        )
        rescored = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/attachments/{works[1].id}/score/",
            {"score": 9, "feedback": "复核后调整。"},
            format="json",
        )
        self.assertEqual(scored.status_code, 200)
        self.assertEqual(rescored.status_code, 200)
        file_facts = AssessmentResultFact.objects.filter(
            attempt_id=works[1].submission_id
        ).order_by("grade_version")
        self.assertEqual(
            list(file_facts.values_list("grading_state", flat=True)),
            ["pending", "final", "revised"],
        )
        self.assertEqual(file_facts.last().supersedes, file_facts[1])

        progress = self.client.get(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/step-progress/"
        )
        self.assertEqual(progress.status_code, 200)
        student_row = next(
            row
            for row in progress.data["data"]["rows"]
            if row["student_id"] == self.student.id
        )
        self.assertTrue(student_row["submitted"])
        self.assertEqual(student_row["attempt_no"], 1)
        file_answer = next(
            row for row in student_row["answers"] if row["question_id"] == "q-file"
        )
        self.assertEqual(file_answer["attachment"]["upload_version"], 2)
        self.assertEqual(file_answer["score"], 9)
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_required_validation_and_close_preserve_completed_denominators(self):
        opened = self.open_step()
        self.assertEqual(opened.status_code, 200, opened.data)
        self.client.force_authenticate(self.student)
        invalid = self.client.post(
            f"/api/v1/student/lesson-steps/{self.step.id}/answer/",
            {"answer": {"questions": {"q-single": "2"}}},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(LessonStepAttempt.objects.exists())

        upload = self.upload(b"submitted", "submitted.txt")
        self.assertEqual(self.submit_step(upload.data["data"]).status_code, 200)
        self.client.force_authenticate(self.teacher)
        closed = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/step/close/",
            {},
            format="json",
        )
        self.assertEqual(closed.status_code, 200)

        student_opportunities = LearningOpportunity.objects.filter(student=self.student)
        peer_opportunities = LearningOpportunity.objects.filter(student=self.peer)
        self.assertFalse(
            LearningOpportunityTransitionFact.objects.filter(
                opportunity__in=student_opportunities,
                state="withdrawn",
            ).exists()
        )
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(
                opportunity__in=peer_opportunities,
                state="withdrawn",
            ).count(),
            3,
        )

    def test_learning_page_open_and_form_submission_keep_answers_out_of_v2(self):
        page = LearningWebPage.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            title="二进制学习任务单",
            revision_no=1,
            schema={
                "schema_version": 1,
                "title": "二进制学习任务单",
                "subtitle": "",
                "accent": "blue",
                "blocks": [
                    {
                        "id": "intro",
                        "type": "content",
                        "title": "任务说明",
                        "body": "完成观察与作答。",
                    },
                    {
                        "id": "form-block",
                        "type": "form",
                        "title": "学习反馈",
                        "form_id": "binary-form",
                        "fields": [
                            {
                                "id": "observation",
                                "type": "short_text",
                                "label": "你的发现",
                                "required": True,
                            }
                        ],
                    },
                ],
            },
        )
        self.step.resource_items = [
            {
                "id": f"learning-page-{page.id}",
                "learning_page_id": page.id,
                "title": page.title,
                "kind": "learning_page",
                "revision_no": 1,
            }
        ]
        self.step.save(update_fields=["resource_items", "updated_at"])
        opened = self.open_step()
        self.assertEqual(opened.status_code, 200, opened.data)
        self.assertEqual(
            LearningOpportunity.objects.filter(content_type="learning_page").count(),
            2,
        )

        self.client.force_authenticate(self.student)
        viewed = self.client.get(
            f"/api/v1/learning-pages/{page.id}/?presentation=embedded"
        )
        self.assertEqual(viewed.status_code, 200, viewed.data)
        opened_event = LearningEventV2.objects.get(event_name="learning_page.opened")
        self.assertEqual(opened_event.payload["presentation"], "embedded")
        self.assertEqual(opened_event.payload["block_count"], 2)
        self.assertEqual(opened_event.payload["form_count"], 1)

        block_viewed = self.client.post(
            f"/api/v1/student/learning-pages/{page.id}/blocks/viewed/",
            {
                "block_id": "intro",
                "block_type": "content",
                "visible_ms": 1650,
                "visibility_ratio": 0.75,
            },
            format="json",
        )
        self.assertEqual(block_viewed.status_code, 201, block_viewed.data)
        block_event = LearningEventV2.objects.get(
            event_name="learning_page.block_viewed"
        )
        self.assertEqual(block_event.duration_ms, 1650)
        self.assertEqual(block_event.payload["block_id"], "intro")
        self.assertNotIn("body", block_event.payload)

        first = self.client.post(
            f"/api/v1/student/learning-pages/{page.id}/submit/",
            {
                "form_id": "binary-form",
                "answers": {"observation": "0 和 1 可以表示两种稳定状态"},
            },
            format="json",
        )
        second = self.client.post(
            f"/api/v1/student/learning-pages/{page.id}/submit/",
            {
                "form_id": "binary-form",
                "answers": {"observation": "修订后的回答"},
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        responses = list(LearningWebPageResponse.objects.order_by("attempt_no"))
        self.assertEqual([item.attempt_no for item in responses], [1, 2])
        self.assertEqual(
            responses[0].answers["observation"],
            "0 和 1 可以表示两种稳定状态",
        )

        submitted_events = list(
            LearningEventV2.objects.filter(
                event_name="learning_page.form_submitted"
            ).order_by("client_occurred_at", "id")
        )
        self.assertEqual(len(submitted_events), 2)
        self.assertEqual(
            [item.attempt_id for item in submitted_events],
            [item.analytics_attempt_id for item in responses],
        )
        self.assertEqual(
            [item.payload["attempt_no"] for item in submitted_events],
            [1, 2],
        )
        self.assertTrue(all("answers" not in item.payload for item in submitted_events))
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])

    def test_classroom_resources_create_typed_opportunities_and_progress_events(self):
        video = Resource.objects.create(
            title="课堂视频",
            attachment=SimpleUploadedFile("lesson.mp4", b"video", "video/mp4"),
            owner=self.teacher,
        )
        document = Resource.objects.create(
            title="课堂课件",
            attachment=SimpleUploadedFile(
                "lesson.pdf", b"%PDF-1.4 test", "application/pdf"
            ),
            owner=self.teacher,
        )
        self.step.step_type = LessonStep.StepType.RESOURCE
        self.step.question_items = []
        self.step.resource_items = [
            {
                "id": video.id,
                "title": video.title,
                "attachment_name": "lesson.mp4",
                "attachment_url": video.attachment.url,
                "file_ext": "mp4",
                "kind": "resource",
            },
            {
                "id": document.id,
                "title": document.title,
                "attachment_name": "lesson.pdf",
                "attachment_url": document.attachment.url,
                "file_ext": "pdf",
                "kind": "resource",
            },
        ]
        self.step.save(
            update_fields=[
                "step_type",
                "question_items",
                "resource_items",
                "updated_at",
            ]
        )

        opened = self.open_step()
        self.assertEqual(opened.status_code, 200, opened.data)
        releases = LearningEventV2.objects.filter(event_name="content.released")
        self.assertEqual(releases.count(), 2)
        self.assertSetEqual(
            set(releases.values_list("payload__content_type", flat=True)),
            {"video", "document"},
        )
        self.assertEqual(LearningOpportunity.objects.count(), 4)
        self.assertFalse(
            LearningOpportunity.objects.filter(content_type="task").exists()
        )

        self.client.force_authenticate(self.student)
        document_opened = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/resources/{document.id}/opened/",
            {"presentation": "embedded"},
            format="json",
        )
        video_progress = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/resources/{video.id}/video-progress/",
            {
                "position_seconds": 12.5,
                "media_seconds": 120,
                "playback_rate": 1,
                "duration_ms": 10_000,
            },
            format="json",
        )
        document_progress = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/resources/{document.id}/document-progress/",
            {"page": 2, "page_count": 8, "visible_seconds": 9.5},
            format="json",
        )
        missing = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/resources/999999/opened/",
            {"presentation": "embedded"},
            format="json",
        )

        self.assertEqual(document_opened.status_code, 201, document_opened.data)
        self.assertEqual(video_progress.status_code, 201, video_progress.data)
        self.assertEqual(document_progress.status_code, 201, document_progress.data)
        self.assertEqual(missing.status_code, 404, missing.data)
        resource_event = LearningEventV2.objects.get(event_name="resource.opened")
        self.assertEqual(resource_event.payload["resource_format"], "document")
        self.assertEqual(resource_event.payload["presentation"], "embedded")
        video_event = LearningEventV2.objects.get(event_name="video.progress")
        self.assertEqual(video_event.duration_ms, 10_000)
        self.assertEqual(video_event.payload["position_seconds"], 12.5)
        document_event = LearningEventV2.objects.get(event_name="document.progress")
        self.assertEqual(document_event.payload["page"], 2)

        video_opportunity = LearningOpportunity.objects.get(
            student=self.student, content_type="video"
        )
        document_opportunity = LearningOpportunity.objects.get(
            student=self.student, content_type="document"
        )
        self.assertSetEqual(
            set(video_opportunity.transition_facts.values_list("state", flat=True)),
            {"assigned", "released", "exposed", "started"},
        )
        self.assertSetEqual(
            set(document_opportunity.transition_facts.values_list("state", flat=True)),
            {"assigned", "released", "exposed", "started"},
        )
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])
