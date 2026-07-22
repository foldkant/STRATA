from __future__ import annotations

import io
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib import admin as django_admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import OperationalError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter
from rest_framework.test import APIClient

from accounts.models import User
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumExtractionStatus,
    CurriculumPageQualityStatus,
    CurriculumProcessingJob,
    CurriculumProcessingJobStatus,
    CurriculumProcessingMode,
    CurriculumProcessingPage,
    CurriculumProcessingPriority,
    CurriculumStandard,
    CurriculumStandardPage,
    CurriculumStandardVersion,
    CurriculumTextExtractionMethod,
)
from curriculum_standards.processing import (
    claim_processing_job,
    create_processing_job,
    finish_job_failed,
    reconcile_stale_processing_jobs,
    redispatch_stale_queued_jobs,
    request_job_cancel,
    retry_processing_job,
    run_processing_job,
    stage_processing_page,
)
from curriculum_standards.services import (
    CurriculumExtractionCancelled,
    ExtractedDocument,
    create_version,
)


def pdf_upload(name: str = "standard.pdf", pages: int = 4) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    writer.write(buffer)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/pdf")


def manual_text(marker: str = "原始") -> str:
    headings = ("核心素养", "课程目标", "课程内容", "学业质量")
    return "\n\n".join(
        f"# PDF 第 {page} 页\n\n{heading}\n{marker}{heading}" + "说明" * 50
        for page, heading in enumerate(headings, start=1)
    )


def processed_records(marker: str = "后台处理") -> list[dict]:
    headings = ("核心素养", "课程目标", "课程内容", "学业质量")
    return [
        {
            "page_number": page,
            "text": f"{heading}\n{marker}{heading}" + "正文" * 60,
            "extraction_method": CurriculumTextExtractionMethod.OCR,
            "mean_confidence": 0.98,
            "quality_status": CurriculumPageQualityStatus.COMPLETE,
            "quality_message": "文字识别结果发布前需人工复核。",
        }
        for page, heading in enumerate(headings, start=1)
    ]


def extracted_document(records: list[dict]) -> ExtractedDocument:
    return ExtractedDocument(
        structured_text="temporary",
        pages=[record["text"] for record in records],
        page_records=records,
        status=CurriculumExtractionStatus.COMPLETED,
        message="后台文字识别完成，发布前必须人工复核。",
        engine="test-ocr",
        engine_version="1",
        config={"strategy": "test"},
    )


@override_settings(
    CURRICULUM_REQUIRE_SEPARATE_REVIEWERS=False,
    CURRICULUM_PROCESSING_STALE_SECONDS=300,
)
class CurriculumProcessingJobTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="curriculum-job-tests-")
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))
        self.admin = User.objects.create_user(
            username="superadmin",
            password="password",
            role=User.Role.SUPER_ADMIN,
        )
        self.teacher = User.objects.create_user(
            username="queue_teacher",
            password="password",
            role=User.Role.TEACHER,
        )
        self.standard = CurriculumStandard.objects.create(
            title="普通高中信息科技课程标准",
            document_type=CurriculumDocumentType.SUBJECT_STANDARD,
            school_stage="k10_k12",
            subject_code="information_technology",
            subject_name="信息科技",
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.version = create_version(
            standard=self.standard,
            version_label="2017-2025",
            publication_year=2025,
            effective_year=2025,
            issued_by="中华人民共和国教育部",
            source_url="https://example.edu/standard.pdf",
            official_title="普通高中信息科技课程标准（2017年版2025年修订）",
            source_note="测试原文",
            pdf_file=pdf_upload(),
            structured_text=manual_text(),
            replaces_version=None,
            actor=self.admin,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _job(self, **kwargs) -> CurriculumProcessingJob:
        job, created = create_processing_job(
            version=self.version,
            actor=self.admin,
            mode=kwargs.get("mode", CurriculumProcessingMode.AUTO),
            priority=kwargs.get("priority", CurriculumProcessingPriority.LOW),
        )
        self.assertTrue(created)
        return job

    def _formal_snapshot(self):
        self.version.refresh_from_db()
        return (
            self.version.structured_text,
            self.version.content_hash,
            list(
                self.version.pages.order_by("page_number").values_list(
                    "page_number", "text", "content_hash"
                )
            ),
        )

    def _successful_extractor(self, records=None):
        records = records or processed_records()

        def fake_extract(file_obj, **kwargs):
            kwargs["phase_callback"]("ocr")
            for current, record in enumerate(records, start=1):
                if kwargs["cancel_check"]():
                    raise CurriculumExtractionCancelled()
                kwargs["page_callback"](record, current, len(records))
            return extracted_document(records)

        return fake_extract

    def test_superadmin_create_is_idempotent_and_contract_is_complete(self):
        url = reverse(
            "api_super_admin_curriculum_processing_job_create",
            kwargs={"pk": self.version.id},
        )
        with patch("curriculum_standards.tasks.process_version_pdf.apply_async") as dispatch:
            first = self.client.post(url, {"mode": "auto", "priority": "high"}, format="json")
            second = self.client.post(url, {"mode": "auto", "priority": "high"}, format="json")
        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["data"]["id"], second.data["data"]["id"])
        self.assertEqual(CurriculumProcessingJob.objects.count(), 1)
        dispatch.assert_called_once()
        row = first.data["data"]
        for key in (
            "status_label",
            "stage_label",
            "progress_percent",
            "resource_limit",
            "created_by_display",
            "can_retry",
            "can_cancel",
            "result_summary",
        ):
            self.assertIn(key, row)

    def test_processing_api_is_superadmin_only(self):
        self.client.force_authenticate(self.teacher)
        list_url = reverse("api_super_admin_curriculum_processing_jobs")
        create_url = reverse(
            "api_super_admin_curriculum_processing_job_create",
            kwargs={"pk": self.version.id},
        )
        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.assertEqual(self.client.post(create_url, {}, format="json").status_code, 403)

    def test_broker_failure_is_durable_and_clear(self):
        url = reverse(
            "api_super_admin_curriculum_processing_job_create",
            kwargs={"pk": self.version.id},
        )
        with patch(
            "curriculum_standards.tasks.process_version_pdf.apply_async",
            side_effect=ConnectionError("redis refused connection"),
        ):
            response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        job = CurriculumProcessingJob.objects.get()
        self.assertEqual(job.status, CurriculumProcessingJobStatus.FAILED)
        self.assertEqual(job.error_code, "broker_unavailable")
        self.assertIn("队列当前不可用", job.error_message)
        self.assertTrue(
            job.version.audit_logs.filter(action="processing_job_dispatch_failed").exists()
        )

    def test_success_promotes_all_pages_once_and_keeps_human_review_required(self):
        before = self._formal_snapshot()
        job = self._job()
        with patch(
            "curriculum_standards.processing.extract_pdf_text",
            side_effect=self._successful_extractor(),
        ):
            run_processing_job(job.id, worker_hostname="test-worker", task_id="task-1")
        job.refresh_from_db()
        self.version.refresh_from_db()
        self.assertEqual(job.status, CurriculumProcessingJobStatus.SUCCEEDED)
        self.assertEqual(job.progress_current, 4)
        self.assertNotEqual(self.version.content_hash, before[1])
        self.assertEqual(self.version.extraction_status, CurriculumExtractionStatus.COMPLETED)
        self.assertEqual(self.version.extraction_engine, "test-ocr")
        self.assertEqual(self.version.pages.count(), 4)
        self.assertTrue(
            self.version.pages.exclude(review_status="reviewed").exists(),
            "后台成功不得替代人工复核。",
        )
        self.assertEqual(job.result_summary["page_count"], 4)
        self.assertEqual(job.staged_pages.count(), 0)

    def test_atomic_promotion_rolls_back_when_late_step_fails(self):
        before = self._formal_snapshot()
        job = self._job()
        with (
            patch(
                "curriculum_standards.processing.extract_pdf_text",
                side_effect=self._successful_extractor(),
            ),
            patch(
                "curriculum_standards.processing.create_suggested_framework_nodes",
                side_effect=RuntimeError("late node failure"),
            ),
        ):
            run_processing_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, CurriculumProcessingJobStatus.FAILED)
        self.assertEqual(self._formal_snapshot(), before)
        self.assertEqual(job.staged_pages.count(), 4)

    def test_running_job_cancels_between_pages_without_formal_write(self):
        before = self._formal_snapshot()
        job = self._job()
        records = processed_records()

        def cancelling_extract(file_obj, **kwargs):
            kwargs["phase_callback"]("ocr")
            kwargs["page_callback"](records[0], 1, 4)
            request_job_cancel(
                CurriculumProcessingJob.objects.get(pk=job.id),
                actor=self.admin,
            )
            raise CurriculumExtractionCancelled()

        with patch(
            "curriculum_standards.processing.extract_pdf_text",
            side_effect=cancelling_extract,
        ):
            run_processing_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, CurriculumProcessingJobStatus.CANCELLED)
        self.assertEqual(job.staged_pages.count(), 1)
        self.assertEqual(self._formal_snapshot(), before)

    def test_database_lock_is_reported_as_retryable_failure(self):
        before = self._formal_snapshot()
        job = self._job()
        with patch(
            "curriculum_standards.processing.extract_pdf_text",
            side_effect=OperationalError("database is locked"),
        ):
            run_processing_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, CurriculumProcessingJobStatus.FAILED)
        self.assertEqual(job.error_code, "database_locked")
        self.assertIn("SQLite", job.error_message)
        self.assertEqual(self._formal_snapshot(), before)

    def test_failed_job_retry_creates_auditable_new_job(self):
        failed = self._job()
        finish_job_failed(failed, "test_failure", "测试失败")
        with patch("curriculum_standards.tasks.process_version_pdf.apply_async"):
            response = self.client.post(
                reverse(
                    "api_super_admin_curriculum_processing_job_retry",
                    kwargs={"pk": failed.id},
                ),
                {},
                format="json",
            )
        self.assertEqual(response.status_code, 202, response.data)
        retry = CurriculumProcessingJob.objects.exclude(pk=failed.id).get()
        self.assertEqual(retry.retry_of_id, failed.id)
        self.assertEqual(retry.retry_count, 1)
        self.assertEqual(retry.status, CurriculumProcessingJobStatus.QUEUED)

    def test_active_job_blocks_submission_for_human_review(self):
        self._job()
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_submit_review",
                kwargs={"pk": self.version.id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "draft")

    def test_stale_worker_is_failed_and_no_longer_blocks_new_job(self):
        stale = self._job()
        old = timezone.now() - timedelta(hours=1)
        CurriculumProcessingJob.objects.filter(pk=stale.id).update(
            status=CurriculumProcessingJobStatus.RUNNING,
            started_at=old,
            heartbeat_at=old,
        )
        self.assertEqual(reconcile_stale_processing_jobs(), 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, CurriculumProcessingJobStatus.FAILED)
        self.assertEqual(stale.error_code, "worker_lost")
        replacement, created = create_processing_job(
            version=self.version,
            actor=self.admin,
        )
        self.assertTrue(created)
        self.assertNotEqual(replacement.id, stale.id)

    def test_same_task_redelivery_can_recover_running_job(self):
        job = self._job()
        CurriculumProcessingJob.objects.filter(pk=job.id).update(celery_task_id="same-task")
        claimed = claim_processing_job(job.id, task_id="same-task")
        self.assertIsNotNone(claimed)
        stage_processing_page(job.id, processed_records()[0], 1, 4)
        self.assertEqual(CurriculumProcessingPage.objects.filter(job=job).count(), 1)
        recovered = claim_processing_job(
            job.id,
            task_id="same-task",
            redelivered=True,
            worker_hostname="replacement-worker",
        )
        self.assertIsNotNone(recovered)
        self.assertEqual(CurriculumProcessingPage.objects.filter(job=job).count(), 0)
        self.assertTrue(
            self.version.audit_logs.filter(action="processing_job_recovered").exists()
        )

    def test_stale_queued_dispatch_window_is_safely_redispatched_with_same_task_id(self):
        job = self._job()
        old = timezone.now() - timedelta(hours=1)
        CurriculumProcessingJob.objects.filter(pk=job.id).update(
            celery_task_id="stable-task-id",
            dispatch_count=1,
            dispatch_attempted_at=old,
        )
        with patch("curriculum_standards.tasks.process_version_pdf.apply_async") as dispatch:
            result = redispatch_stale_queued_jobs(stale_seconds=60)
        self.assertEqual(result, {"selected": 1, "redispatched": 1, "failed": 0})
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["task_id"], "stable-task-id")
        job.refresh_from_db()
        self.assertEqual(job.dispatch_count, 2)
        self.assertEqual(job.status, CurriculumProcessingJobStatus.QUEUED)

    def test_management_enqueue_is_repeatable_and_dry_run_is_read_only(self):
        CurriculumStandardVersion.objects.filter(pk=self.version.id).update(
            extraction_status=CurriculumExtractionStatus.NEEDS_OCR
        )
        output = StringIO()
        call_command(
            "enqueue_curriculum_ocr",
            "--all-needs-ocr",
            "--dry-run",
            stdout=output,
        )
        self.assertEqual(CurriculumProcessingJob.objects.count(), 0)
        with patch(
            "curriculum_standards.management.commands.enqueue_curriculum_ocr.dispatch_processing_job",
            side_effect=lambda job: job,
        ):
            call_command("enqueue_curriculum_ocr", "--all-needs-ocr", stdout=StringIO())
            call_command("enqueue_curriculum_ocr", "--all-needs-ocr", stdout=StringIO())
        self.assertEqual(CurriculumProcessingJob.objects.count(), 1)

    def test_processing_models_are_read_only_in_django_admin(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        for model in (CurriculumProcessingJob, CurriculumProcessingPage):
            model_admin = django_admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
