from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from api.services import (
    ServiceError,
    delete_pretest_question,
    publish_pretest_paper,
    save_pretest_paper,
    save_pretest_question,
)
from courses.models import Course, CourseClass, Subject
from learning.models import (
    DiagnosticAdministration,
    PretestPaper,
    PretestMaterialAttachment,
    PretestPaperVersion,
    PretestQuestion,
    PretestSubmission,
    StudentLearningTargetStateVersion,
    UnifiedAssessmentMaterial,
)
from learning.services.diagnostic_administrations import (
    publish_diagnostic_administration,
    replace_diagnostic_assignments,
)
from learning_analytics.schemas.registry import (
    EventPayloadValidationError,
    validate_event_payload,
)
from learning_analytics.services.operational_events import record_pretest_submitted
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class PretestDiagnosticIntegrityTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="诊断完整性学校", code="P3-INTEGRITY")
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="七年级1班",
            grade="七年级",
        )
        self.admin = User.objects.create_user(
            username="p3_integrity_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.student = User.objects.create_user(
            username="p3_integrity_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            current_layer=StudentProfile.Layer.A,
        )
        self.request = RequestFactory().post("/api/v1/school-admin/pretests/1/publish/")
        self.request.user = self.admin

    def create_paper(
        self,
        *,
        version: int = 1,
        status: str = PretestPaper.Status.DRAFT,
        target_code: str = "IT-ENTRY-01",
    ) -> PretestPaper:
        paper = PretestPaper.objects.create(
            school=self.school,
            subject=self.subject,
            title=f"信息科技学习起点诊断 v{version}",
            # These legacy-integrity fixtures intentionally exercise unmapped
            # questionnaire material. Exact literacy targets have dedicated
            # coverage in test_learning_target_versions.
            kind=PretestPaper.Kind.ATTITUDE,
            version=version,
            status=status,
            created_by=self.admin,
        )
        PretestQuestion.objects.create(
            paper=paper,
            stem="识别给定问题所需的数据类型",
            question_type=PretestQuestion.QuestionType.SINGLE,
            options=[
                {"label": "A", "text": "数值"},
                {"label": "B", "text": "文本"},
            ],
            answer=["A"],
            score=2,
            learning_target_code=target_code,
            learning_target_name="根据问题需要识别数据类型",
        )
        return paper

    def create_version(self, paper: PretestPaper) -> PretestPaperVersion:
        question = paper.questions.get()
        version = PretestPaperVersion.objects.create(
            source=paper,
            version_no=paper.version,
            title=paper.title,
            kind=paper.kind,
            introduction=paper.introduction,
            question_snapshot=[
                {
                    "id": question.id,
                    "stem": question.stem,
                    "question_type": question.question_type,
                    "options": question.options,
                    "answer": question.answer,
                    "score": question.score,
                    "dimension": question.dimension,
                    "learning_target_code": question.learning_target_code,
                    "learning_target_name": question.learning_target_name,
                    "material_requirements": [],
                    "sort_order": 0,
                    "is_required": True,
                }
            ],
            published_by=self.admin,
        )
        if paper.status == PretestPaper.Status.PUBLISHED:
            course = (
                Course.objects.filter(
                    subject=self.subject,
                    course_classes__class_group=self.class_group,
                )
                .order_by("id")
                .first()
            )
            administration = DiagnosticAdministration.objects.create(
                school=self.school,
                subject=self.subject,
                course=course,
                paper_version=version,
                purpose=DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
                batch_code=f"P3-{paper.id}-{version.id}",
                title=f"{paper.title}实施批次",
                open_at=timezone.now() - timedelta(hours=1),
                close_at=timezone.now() + timedelta(days=30),
                created_by=self.admin,
            )
            replace_diagnostic_assignments(
                administration_id=administration.id,
                school=self.school,
                payload={
                    "assignments": [
                        {
                            "class_group_id": self.class_group.id,
                            "cohort_role": "unassigned",
                            "opportunity_status": "offered",
                        }
                    ]
                },
            )
            publish_diagnostic_administration(
                administration_id=administration.id,
                school=self.school,
                actor=self.admin,
            )
        return version

    def test_migration_backfills_only_immutable_papers_and_keeps_global_layer(self):
        draft = self.create_paper(version=1, target_code="")
        published = self.create_paper(
            version=2,
            status=PretestPaper.Status.PUBLISHED,
            target_code="",
        )
        migration = importlib.import_module(
            "learning.migrations.0021_pretestquestion_learning_target_code_and_more"
        )

        migration.backfill_published_diagnostic_versions(apps, None)

        self.assertFalse(PretestPaperVersion.objects.filter(source=draft).exists())
        self.assertEqual(draft.questions.get().learning_target_code, "")
        self.assertTrue(PretestPaperVersion.objects.filter(source=published).exists())
        self.assertTrue(published.questions.get().learning_target_code.startswith("ENTRY-"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_layer, StudentProfile.Layer.A)

    def test_publish_is_idempotent_and_archives_the_previous_version(self):
        previous = self.create_paper(version=1, status=PretestPaper.Status.PUBLISHED)
        self.create_version(previous)
        draft = self.create_paper(version=2)

        published = publish_pretest_paper(self.request, draft)

        self.assertEqual(published.status, PretestPaper.Status.PUBLISHED)
        previous.refresh_from_db()
        self.assertEqual(previous.status, PretestPaper.Status.ARCHIVED)
        self.assertEqual(PretestPaperVersion.objects.filter(source=draft).count(), 1)
        with self.assertRaises(ServiceError) as caught:
            publish_pretest_paper(self.request, draft)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(PretestPaperVersion.objects.filter(source=draft).count(), 1)

    def test_publish_rolls_back_snapshot_and_status_when_audit_write_fails(self):
        draft = self.create_paper()

        with patch(
            "api.pretest_services._shared_services.write_audit",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                publish_pretest_paper(self.request, draft)

        draft.refresh_from_db()
        self.assertEqual(draft.status, PretestPaper.Status.DRAFT)
        self.assertFalse(PretestPaperVersion.objects.filter(source=draft).exists())

    def test_existing_snapshot_is_reported_as_conflict_without_changing_draft(self):
        draft = self.create_paper()
        self.create_version(draft)

        with self.assertRaises(ServiceError) as caught:
            publish_pretest_paper(self.request, draft)

        self.assertEqual(caught.exception.status, 409)
        draft.refresh_from_db()
        self.assertEqual(draft.status, PretestPaper.Status.DRAFT)

    def test_missing_opportunity_event_has_status_and_never_coerces_score_to_zero(self):
        sync_event_schema_definitions()
        paper = self.create_paper(status=PretestPaper.Status.PUBLISHED)
        version = self.create_version(paper)
        submission = PretestSubmission.objects.create(
            student=self.student,
            subject=self.subject,
            paper=paper,
            paper_version=version,
            answers={},
            score=None,
            opportunity_status=PretestSubmission.OpportunityStatus.DEVICE_ISSUE,
            target_results=[],
        )

        event_write = record_pretest_submitted(
            submission=submission,
            profile=self.profile,
        )

        self.assertEqual(event_write.analytics_event.schema_version, "1.1")
        payload = event_write.analytics_event.payload
        self.assertEqual(payload["opportunity_status"], "device_issue")
        self.assertIsNone(payload.get("score_raw"))
        self.assertNotEqual(payload.get("score_raw"), 0)
        self.assertIsNone(event_write.legacy_event.score)

    def test_pretest_event_schema_rejects_a_score_without_an_opportunity(self):
        with self.assertRaises(EventPayloadValidationError):
            validate_event_payload(
                "pretest.submitted",
                "1.1",
                {
                    "paper_kind": "literacy",
                    "paper_version": 1,
                    "submission_id": 1,
                    "answer_count": 0,
                    "opportunity_status": "not_offered",
                    "score_raw": 0,
                },
            )

    def test_subjective_material_review_appends_score_and_target_state_versions(self):
        sync_event_schema_definitions()
        teacher = User.objects.create_user(
            username="p3_integrity_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        course = Course.objects.create(
            subject=self.subject,
            title="信息科技学习起点诊断课程",
            teacher=teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=course,
            class_group=self.class_group,
            created_by=teacher,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=teacher,
        )
        paper = self.create_paper(status=PretestPaper.Status.PUBLISHED)
        question = paper.questions.get()
        question.question_type = PretestQuestion.QuestionType.TEXT
        question.answer = []
        question.score = 10
        question.material_requirements = ["简答说明"]
        question.save()
        version = self.create_version(paper)

        client = APIClient()
        client.force_authenticate(self.student)
        submitted = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": version.content_hash,
                "answers": {str(question.id): "说明数据类型与任务需求之间的关系。"},
                "task_statuses": {str(question.id): "observed"},
            },
            format="json",
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        source_material = UnifiedAssessmentMaterial.objects.get(
            source_type="learning_entry_diagnostic",
            student=self.student,
        )
        self.assertEqual(
            source_material.material_status,
            UnifiedAssessmentMaterial.MaterialStatus.PENDING_REVIEW,
        )
        initial_state = StudentLearningTargetStateVersion.objects.get(
            source_type="learning_entry_diagnostic",
            student=self.student,
        )
        self.assertEqual(
            initial_state.evidence_status,
            StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW,
        )
        self.assertIsNone(initial_state.estimate)
        self.assertIsNotNone(initial_state.valid_until)
        self.assertEqual(
            initial_state.valid_until,
            initial_state.valid_from + timedelta(days=90),
        )

        other_teacher = User.objects.create_user(
            username="p3_integrity_same_subject_other_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        other_course = Course.objects.create(
            subject=self.subject,
            title="同班同学科不同诊断课程",
            teacher=other_teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=other_course,
            class_group=self.class_group,
            created_by=other_teacher,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=other_teacher,
        )
        client.force_authenticate(other_teacher)
        cross_course_pending = client.get(
            "/api/v1/teacher/pretest-materials/pending/"
        )
        self.assertEqual(cross_course_pending.status_code, 200, cross_course_pending.data)
        self.assertEqual(cross_course_pending.data["data"], [])
        cross_course_review = client.post(
            f"/api/v1/teacher/pretest-materials/{source_material.material_id}/review/",
            {"score": 8, "score_max": 10},
            format="json",
        )
        self.assertEqual(cross_course_review.status_code, 404, cross_course_review.data)

        client.force_authenticate(teacher)
        pending = client.get("/api/v1/teacher/pretest-materials/pending/")
        self.assertEqual(pending.status_code, 200, pending.data)
        self.assertEqual(len(pending.data["data"]), 1)

        changed_max = client.post(
            f"/api/v1/teacher/pretest-materials/{source_material.material_id}/review/",
            {"score": 8, "score_max": 9, "feedback": "评分满分不得被客户端修改。"},
            format="json",
        )
        self.assertEqual(changed_max.status_code, 409, changed_max.data)
        self.assertFalse(
            UnifiedAssessmentMaterial.objects.filter(
                source_type="learning_entry_diagnostic_review"
            ).exists()
        )

        reviewed = client.post(
            f"/api/v1/teacher/pretest-materials/{source_material.material_id}/review/",
            {"score": 8, "score_max": 10, "feedback": "能够结合任务说明数据类型。"},
            format="json",
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        source_material.refresh_from_db()
        self.assertEqual(
            source_material.material_status,
            UnifiedAssessmentMaterial.MaterialStatus.PENDING_REVIEW,
        )
        score_material = UnifiedAssessmentMaterial.objects.get(
            source_type="learning_entry_diagnostic_review"
        )
        self.assertEqual(score_material.material_type, "score")
        self.assertEqual(score_material.score, 8)
        latest_state = StudentLearningTargetStateVersion.objects.filter(
            student=self.student,
            learning_target_code=question.learning_target_code,
        ).order_by("-observed_at", "-id").first()
        self.assertNotEqual(latest_state.id, initial_state.id)
        self.assertEqual(
            latest_state.evidence_status,
            StudentLearningTargetStateVersion.EvidenceStatus.INSUFFICIENT,
        )
        self.assertIsNone(latest_state.estimate)
        self.assertTrue(latest_state.legacy_unmapped)
        self.assertEqual(
            latest_state.valid_until,
            latest_state.valid_from + timedelta(days=90),
        )

        repeated = client.post(
            f"/api/v1/teacher/pretest-materials/{source_material.material_id}/review/",
            {"score": 8, "score_max": 10},
            format="json",
        )
        self.assertEqual(repeated.status_code, 409, repeated.data)

    def test_stale_draft_objects_cannot_edit_or_delete_after_publish(self):
        draft = self.create_paper()
        stale_paper = PretestPaper.objects.get(pk=draft.pk)
        stale_question = PretestQuestion.objects.get(paper=draft)
        publish_pretest_paper(self.request, draft)
        published_version = draft.published_versions.get()
        with self.assertRaises(ValidationError):
            PretestPaperVersion.objects.filter(pk=published_version.pk).update(
                title="不应写入"
            )
        with self.assertRaises(ValidationError):
            PretestPaperVersion.objects.filter(pk=published_version.pk).delete()

        with self.assertRaises(ServiceError) as paper_error:
            save_pretest_paper(
                self.request,
                {
                    "subject": self.subject.id,
                    "title": "过期页面试图修改诊断",
                    "kind": draft.kind,
                    "version": draft.version,
                    "introduction": "不应写入",
                },
                paper=stale_paper,
            )
        self.assertEqual(paper_error.exception.status, 409)

        with self.assertRaises(ServiceError) as question_error:
            save_pretest_question(self.request, stale_paper, {}, question=stale_question)
        self.assertEqual(question_error.exception.status, 409)

        with self.assertRaises(ServiceError) as delete_error:
            delete_pretest_question(self.request, stale_question)
        self.assertEqual(delete_error.exception.status, 409)
        self.assertTrue(PretestQuestion.objects.filter(pk=stale_question.pk).exists())

    def test_student_get_uses_immutable_snapshot_and_post_rejects_stale_version(self):
        paper = self.create_paper(status=PretestPaper.Status.PUBLISHED)
        question = paper.questions.get()
        version = self.create_version(paper)
        original_stem = question.stem
        original_target_name = question.learning_target_name
        question.stem = "发布后被错误修改的实时题目"
        question.learning_target_name = "发布后实时字段"
        question.save()

        client = APIClient()
        client.force_authenticate(self.student)
        fetched = client.get(f"/api/v1/student/pretests/papers/{paper.id}/")
        self.assertEqual(fetched.status_code, 200, fetched.data)
        payload = fetched.data["data"]
        self.assertEqual(payload["published_version"]["id"], version.id)
        self.assertEqual(payload["published_version"]["content_hash"], version.content_hash)
        self.assertEqual(payload["questions"][0]["stem"], original_stem)
        self.assertEqual(
            payload["questions"][0]["learning_target_name"], original_target_name
        )
        self.assertNotIn("answer", payload["questions"][0])

        missing_version = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {"answers": {str(question.id): "A"}},
            format="json",
        )
        self.assertEqual(missing_version.status_code, 400, missing_version.data)
        stale_version = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": "0" * 64,
                "answers": {str(question.id): "A"},
            },
            format="json",
        )
        self.assertEqual(stale_version.status_code, 409, stale_version.data)
        unknown_task = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": version.content_hash,
                "answers": {"999999": "A"},
                "opportunity_status": "device_issue",
            },
            format="json",
        )
        self.assertEqual(unknown_task.status_code, 400, unknown_task.data)
        wrong_answer_type = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": version.content_hash,
                "answers": {str(question.id): ["A"]},
            },
            format="json",
        )
        self.assertEqual(wrong_answer_type.status_code, 400, wrong_answer_type.data)
        self.assertFalse(PretestSubmission.objects.filter(student=self.student).exists())

    def test_actual_attachment_is_hashed_bound_protected_and_in_material_manifest(self):
        sync_event_schema_definitions()
        teacher = User.objects.create_user(
            username="p3_attachment_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        course = Course.objects.create(
            subject=self.subject,
            title="诊断附件复核课程",
            teacher=teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=course,
            class_group=self.class_group,
            created_by=teacher,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=teacher,
        )
        paper = self.create_paper(status=PretestPaper.Status.PUBLISHED)
        question = paper.questions.get()
        question.question_type = PretestQuestion.QuestionType.OPERATION
        question.answer = []
        question.score = 10
        question.material_requirements = ["操作截图", "过程说明"]
        question.save()
        version = self.create_version(paper)
        file_data = b"\x89PNG\r\n\x1a\noperation-evidence"
        upload = SimpleUploadedFile(
            "../../操作过程.png",
            file_data,
            content_type="image/png",
        )
        client = APIClient()
        client.force_authenticate(self.student)
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            submitted = client.post(
                f"/api/v1/student/pretests/papers/{paper.id}/",
                {
                    "payload": json.dumps(
                        {
                            "paper_version_id": version.id,
                            "content_hash": version.content_hash,
                            "answers": {str(question.id): "完成数据导入并核验三条记录。"},
                            "task_statuses": {str(question.id): "observed"},
                        },
                        ensure_ascii=False,
                    ),
                    f"attachment_{question.id}": upload,
                },
                format="multipart",
            )
            self.assertEqual(submitted.status_code, 200, submitted.data)
            attachment = PretestMaterialAttachment.objects.get(student=self.student)
            material = attachment.material
            submission = attachment.submission
            self.assertEqual(attachment.paper_version, version)
            self.assertEqual(submission.paper_version, version)
            self.assertEqual(attachment.question_id, str(question.id))
            self.assertEqual(attachment.original_name, "操作过程.png")
            self.assertEqual(attachment.file_size, len(file_data))
            self.assertEqual(attachment.file_sha256, hashlib.sha256(file_data).hexdigest())
            self.assertNotIn("操作过程", attachment.attachment.name)
            self.assertEqual(material.recorded_by, self.student)
            self.assertEqual(len(material.content_hash), 64)
            self.assertEqual(material.content["paper_version_id"], version.id)
            self.assertEqual(material.content["paper_content_hash"], version.content_hash)
            self.assertEqual(
                material.content["process_explanation"],
                "完成数据导入并核验三条记录。",
            )
            self.assertEqual(
                material.content["attachments"][0]["file_sha256"],
                attachment.file_sha256,
            )

            own_download = client.get(
                f"/api/v1/files/pretest-materials/{attachment.attachment_id}/"
            )
            self.assertEqual(own_download.status_code, 200)
            self.assertEqual(b"".join(own_download.streaming_content), file_data)

            other_student = User.objects.create_user(
                username="p3_attachment_other_student",
                password="123456",
                role=User.Role.STUDENT,
                school=self.school,
            )
            StudentProfile.objects.create(
                user=other_student,
                class_group=self.class_group,
            )
            client.force_authenticate(other_student)
            denied = client.get(
                f"/api/v1/files/pretest-materials/{attachment.attachment_id}/"
            )
            self.assertEqual(denied.status_code, 404)

            client.force_authenticate(teacher)
            teacher_download = client.get(
                f"/api/v1/files/pretest-materials/{attachment.attachment_id}/"
            )
            self.assertEqual(teacher_download.status_code, 200)
            teacher_download.close()

            other_teacher = User.objects.create_user(
                username="p3_attachment_same_subject_other_teacher",
                password="Teacher123!",
                role=User.Role.TEACHER,
                school=self.school,
            )
            other_course = Course.objects.create(
                subject=self.subject,
                title="同班同学科但不同课程",
                teacher=other_teacher,
                is_active=True,
            )
            CourseClass.objects.create(
                course=other_course,
                class_group=self.class_group,
                created_by=other_teacher,
            )
            TeachingAssignment.objects.create(
                school=self.school,
                class_group=self.class_group,
                teacher=other_teacher,
            )
            client.force_authenticate(other_teacher)
            cross_course_download = client.get(
                f"/api/v1/files/pretest-materials/{attachment.attachment_id}/"
            )
            self.assertEqual(cross_course_download.status_code, 404)

            client.force_authenticate(self.admin)
            admin_download = client.get(
                f"/api/v1/files/pretest-materials/{attachment.attachment_id}/"
            )
            self.assertEqual(admin_download.status_code, 200)
            admin_download.close()

            other_paper = self.create_paper(
                version=2,
                status=PretestPaper.Status.PUBLISHED,
                target_code="IT-ENTRY-02",
            )
            other_version = self.create_version(other_paper)
            wrong_binding = PretestMaterialAttachment(
                material=material,
                submission=submission,
                paper_version=other_version,
                student=self.student,
                question_id=str(question.id),
                attachment=ContentFile(file_data, name="wrong.png"),
                original_name="wrong.png",
                file_ext="png",
                content_type="image/png",
                file_size=len(file_data),
                file_sha256=hashlib.sha256(file_data + b"wrong").hexdigest(),
            )
            with self.assertRaises(ValidationError):
                wrong_binding.full_clean()
            material.content = {"tampered": True}
            with self.assertRaises(ValidationError):
                material.save()
            with self.assertRaises(ValidationError):
                material.delete()

    @override_settings(PRETEST_MATERIAL_MAX_FILE_MB=1)
    def test_attachment_rejects_unsupported_signature_and_oversize(self):
        paper = self.create_paper(status=PretestPaper.Status.PUBLISHED)
        question = paper.questions.get()
        question.question_type = PretestQuestion.QuestionType.SHORT_PROJECT
        question.answer = []
        question.score = 10
        question.save()
        version = self.create_version(paper)
        client = APIClient()
        client.force_authenticate(self.student)

        base_payload = {
            "paper_version_id": version.id,
            "content_hash": version.content_hash,
            "answers": {str(question.id): "提交短项目材料。"},
            "task_statuses": {str(question.id): "observed"},
        }
        bad_type = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "payload": json.dumps(base_payload),
                f"attachment_{question.id}": SimpleUploadedFile(
                    "program.exe", b"MZ-not-allowed", content_type="application/octet-stream"
                ),
            },
            format="multipart",
        )
        self.assertEqual(bad_type.status_code, 400, bad_type.data)

        bad_signature = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "payload": json.dumps(base_payload),
                f"attachment_{question.id}": SimpleUploadedFile(
                    "fake.png", b"not-a-png", content_type="image/png"
                ),
            },
            format="multipart",
        )
        self.assertEqual(bad_signature.status_code, 400, bad_signature.data)

        oversize = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "payload": json.dumps(base_payload),
                f"attachment_{question.id}": SimpleUploadedFile(
                    "large.txt",
                    b"a" * (1024 * 1024 + 1),
                    content_type="text/plain",
                ),
            },
            format="multipart",
        )
        self.assertEqual(oversize.status_code, 400, oversize.data)
        self.assertFalse(PretestSubmission.objects.filter(student=self.student).exists())
        self.assertFalse(PretestMaterialAttachment.objects.exists())

    @override_settings(LEARNING_ENTRY_DIAGNOSTIC_VALIDITY_DAYS=45)
    def test_missing_or_device_issue_never_requires_attachment_or_lowers_state(self):
        sync_event_schema_definitions()
        paper = self.create_paper(status=PretestPaper.Status.PUBLISHED)
        question = paper.questions.get()
        version = self.create_version(paper)
        client = APIClient()
        client.force_authenticate(self.student)

        student_not_offered = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": version.content_hash,
                "answers": {},
                "opportunity_status": "not_offered",
            },
            format="json",
        )
        self.assertEqual(student_not_offered.status_code, 400, student_not_offered.data)

        device_issue = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": version.content_hash,
                "answers": {},
                "opportunity_status": "device_issue",
            },
            format="json",
        )
        self.assertEqual(device_issue.status_code, 200, device_issue.data)
        result = device_issue.data["data"]["target_results"][0]
        self.assertEqual(result["learning_target_code"], question.learning_target_code)
        self.assertEqual(result["learning_target_name"], question.learning_target_name)
        self.assertEqual(result["evidence_status"], "not_observed")
        self.assertIsNone(result["estimate"])
        submission = PretestSubmission.objects.get(student=self.student)
        self.assertIsNone(submission.score)
        material = UnifiedAssessmentMaterial.objects.get(student=self.student)
        self.assertEqual(material.material_status, "device_issue")
        self.assertIsNone(material.score)
        self.assertFalse(PretestMaterialAttachment.objects.exists())
        state = StudentLearningTargetStateVersion.objects.get(student=self.student)
        self.assertEqual(state.evidence_status, "not_observed")
        self.assertIsNone(state.estimate)
        self.assertEqual(state.valid_until, state.valid_from + timedelta(days=45))

        repeated_exception = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": version.content_hash,
                "answers": {},
                "opportunity_status": "missing",
            },
            format="json",
        )
        self.assertEqual(repeated_exception.status_code, 200, repeated_exception.data)
        self.assertEqual(
            repeated_exception.data["data"]["completion"]["exception"],
            "missing",
        )
        self.assertEqual(PretestSubmission.objects.filter(student=self.student).count(), 2)

    def test_mixed_non_observation_keeps_the_specific_target_reason(self):
        paper = self.create_paper()
        submission = PretestSubmission.objects.create(
            student=self.student,
            subject=self.subject,
            paper=paper,
            answers={},
            opportunity_status=PretestSubmission.OpportunityStatus.MISSING,
            task_statuses={"1": "missing", "2": "device_issue"},
            target_results=[
                {
                    "learning_target_code": "IT-MIXED-01",
                    "learning_target_name": "混合异常记录",
                    "evidence_status": "partial",
                    "estimate": 0.5,
                    "reason": "device_issue,missing",
                }
            ],
        )
        result = submission.target_results[0]
        self.assertEqual(result["evidence_status"], "not_observed")
        self.assertIsNone(result["estimate"])
        self.assertEqual(result["reason"], "device_issue,missing")

    def test_observed_submission_does_not_write_global_completion_or_total_score(self):
        sync_event_schema_definitions()
        self.profile.is_first_use = True
        self.profile.pretest_completed_at = None
        self.profile.save(update_fields=["is_first_use", "pretest_completed_at", "updated_at"])
        original_onboarding_status = self.profile.onboarding_status
        paper = self.create_paper(status=PretestPaper.Status.PUBLISHED)
        question = paper.questions.get()
        version = self.create_version(paper)
        client = APIClient()
        client.force_authenticate(self.student)

        submitted = client.post(
            f"/api/v1/student/pretests/papers/{paper.id}/",
            {
                "paper_version_id": version.id,
                "content_hash": version.content_hash,
                "answers": {str(question.id): "A"},
                "task_statuses": {str(question.id): "observed"},
            },
            format="json",
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertIsNone(submitted.data["data"]["score"])
        submission = PretestSubmission.objects.get(student=self.student)
        self.assertIsNone(submission.score)
        material = UnifiedAssessmentMaterial.objects.get(
            student=self.student,
            material_type=UnifiedAssessmentMaterial.MaterialType.ANSWER,
        )
        self.assertEqual(material.score, 2)
        self.assertEqual(material.score_max, 2)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_first_use)
        self.assertIsNone(self.profile.pretest_completed_at)
        self.assertEqual(self.profile.onboarding_status, original_onboarding_status)

    def test_objective_task_requires_positive_finite_score_and_answer(self):
        paper = self.create_paper()
        question = paper.questions.get()
        base = {
            "stem": question.stem,
            "question_type": "single",
            "options": question.options,
            "dimension": "数据意识",
            "learning_target_code": question.learning_target_code,
            "learning_target_name": question.learning_target_name,
            "material_requirements": [],
            "sort_order": 0,
            "is_required": True,
        }
        with self.assertRaises(ServiceError) as empty_answer:
            save_pretest_question(
                self.request,
                paper,
                {**base, "answer": [], "score": 0},
                question=question,
            )
        self.assertIn("answer", empty_answer.exception.errors)
        self.assertIn("score", empty_answer.exception.errors)

        with self.assertRaises(ServiceError) as infinite_score:
            save_pretest_question(
                self.request,
                paper,
                {**base, "answer": ["A"], "score": float("inf")},
                question=question,
            )
        self.assertIn("score", infinite_score.exception.errors)
