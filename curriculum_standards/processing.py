from __future__ import annotations

import time
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    CurriculumExtractionStatus,
    CurriculumProcessingJob,
    CurriculumProcessingJobStatus,
    CurriculumProcessingMode,
    CurriculumProcessingPage,
    CurriculumProcessingPriority,
    CurriculumProcessingStage,
    CurriculumStandardAuditLog,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    canonical_hash,
)
from .services import (
    CurriculumExtractionCancelled,
    _normalize_mean_confidence,
    _save_page_records,
    _structured_hash,
    _structured_text_from_page_records,
    _version_semantic_content,
    create_suggested_framework_nodes,
    extract_pdf_text,
    sha256_file,
)


ACTIVE_JOB_STATUSES = (
    CurriculumProcessingJobStatus.QUEUED,
    CurriculumProcessingJobStatus.RUNNING,
    CurriculumProcessingJobStatus.CANCELLING,
)
FINAL_JOB_STATUSES = (
    CurriculumProcessingJobStatus.SUCCEEDED,
    CurriculumProcessingJobStatus.FAILED,
    CurriculumProcessingJobStatus.CANCELLED,
)
CELERY_PRIORITY = {
    CurriculumProcessingPriority.HIGH: 9,
    CurriculumProcessingPriority.NORMAL: 5,
    CurriculumProcessingPriority.LOW: 1,
}


class ProcessingJobCancelled(Exception):
    pass


class ProcessingJobError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _audit(job: CurriculumProcessingJob, action: str, detail: dict | None = None) -> None:
    CurriculumStandardAuditLog.objects.create(
        version=job.version,
        action=action,
        actor=job.requested_by,
        detail={"processing_job_id": job.id, **(detail or {})},
    )


def reconcile_stale_processing_jobs() -> int:
    """Fail abandoned running jobs; staged rows never affect official pages."""

    stale_seconds = max(
        int(getattr(settings, "CURRICULUM_PROCESSING_STALE_SECONDS", 1800)),
        300,
    )
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = CurriculumProcessingJob.objects.filter(
        status__in=[
            CurriculumProcessingJobStatus.RUNNING,
            CurriculumProcessingJobStatus.CANCELLING,
        ]
    ).filter(
        Q(heartbeat_at__lt=cutoff)
        | Q(heartbeat_at__isnull=True, started_at__lt=cutoff)
    )
    reconciled = 0
    for job_id in candidates.values_list("id", flat=True):
        with transaction.atomic():
            job = (
                CurriculumProcessingJob.objects.select_for_update()
                .select_related("version", "requested_by")
                .filter(pk=job_id, status__in=["running", "cancelling"])
                .first()
            )
            if not job:
                continue
            job.status = CurriculumProcessingJobStatus.FAILED
            job.stage = CurriculumProcessingStage.FAILED
            job.error_code = "worker_lost"
            job.error_message = (
                "后台处理进程长时间未更新进度，任务已安全终止；正式课标文本未被半成品覆盖，可重试。"
            )
            job.finished_at = timezone.now()
            job.save(
                update_fields=[
                    "status",
                    "stage",
                    "error_code",
                    "error_message",
                    "finished_at",
                    "updated_at",
                ]
            )
            _audit(job, "processing_job_failed", {"error_code": "worker_lost"})
            reconciled += 1
    return reconciled


def create_processing_job(
    *,
    version: CurriculumStandardVersion,
    actor,
    mode: str = CurriculumProcessingMode.AUTO,
    priority: str = CurriculumProcessingPriority.LOW,
    retry_of: CurriculumProcessingJob | None = None,
) -> tuple[CurriculumProcessingJob, bool]:
    reconcile_stale_processing_jobs()
    with transaction.atomic():
        version = CurriculumStandardVersion.objects.select_for_update().get(pk=version.pk)
        if version.status != CurriculumVersionStatus.DRAFT:
            raise ValidationError("只有草稿版本可以创建后台文本处理任务。")
        active = (
            version.processing_jobs.filter(status__in=ACTIVE_JOB_STATUSES)
            .select_related("version__source", "requested_by")
            .first()
        )
        if active:
            return active, False
        retry_count = (retry_of.retry_count + 1) if retry_of else 0
        try:
            job = CurriculumProcessingJob.objects.create(
                version=version,
                mode=mode,
                priority=priority,
                status=CurriculumProcessingJobStatus.QUEUED,
                stage=CurriculumProcessingStage.QUEUED,
                progress_total=version.pdf_page_count,
                source_pdf_sha256=version.pdf_sha256,
                source_content_hash=version.content_hash,
                requested_by=actor,
                retry_of=retry_of,
                retry_count=retry_count,
            )
        except IntegrityError:
            active = version.processing_jobs.filter(status__in=ACTIVE_JOB_STATUSES).first()
            if active:
                return active, False
            raise
        _audit(
            job,
            "processing_job_queued",
            {
                "mode": mode,
                "priority": priority,
                "retry_of_id": retry_of.id if retry_of else None,
                "source_pdf_sha256": version.pdf_sha256,
                "source_content_hash": version.content_hash,
            },
        )
        return job, True


def mark_dispatch_failed(job: CurriculumProcessingJob, exc: Exception) -> CurriculumProcessingJob:
    message = str(exc).strip() or exc.__class__.__name__
    with transaction.atomic():
        job = (
            CurriculumProcessingJob.objects.select_for_update()
            .select_related("version", "requested_by")
            .get(pk=job.pk)
        )
        if job.status != CurriculumProcessingJobStatus.QUEUED:
            return job
        job.status = CurriculumProcessingJobStatus.FAILED
        job.stage = CurriculumProcessingStage.FAILED
        job.error_code = "broker_unavailable"
        job.error_message = (
            "后台任务队列当前不可用，任务没有开始，正式课标文本未发生变化。"
            f"请启动队列服务后重试。技术信息：{message[:500]}"
        )
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "stage",
                "error_code",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )
        _audit(job, "processing_job_dispatch_failed", {"error": message[:500]})
        return job


def dispatch_processing_job(
    job: CurriculumProcessingJob,
    *,
    force: bool = False,
) -> CurriculumProcessingJob:
    from .tasks import process_version_pdf

    with transaction.atomic():
        job = (
            CurriculumProcessingJob.objects.select_for_update()
            .select_related("version", "requested_by")
            .get(pk=job.pk)
        )
        if job.status != CurriculumProcessingJobStatus.QUEUED:
            return job
        if job.celery_task_id and not force:
            return job
        task_id = job.celery_task_id or str(uuid.uuid4())
        job.celery_task_id = task_id
        job.dispatch_count += 1
        job.dispatch_attempted_at = timezone.now()
        job.save(
            update_fields=[
                "celery_task_id",
                "dispatch_count",
                "dispatch_attempted_at",
                "updated_at",
            ]
        )
        _audit(
            job,
            "processing_job_redispatch_attempted" if force else "processing_job_dispatch_attempted",
            {"celery_task_id": task_id, "dispatch_count": job.dispatch_count},
        )
    try:
        process_version_pdf.apply_async(
            args=[job.id],
            task_id=task_id,
            queue=getattr(settings, "CURRICULUM_PROCESSING_QUEUE", "curriculum_ocr"),
            priority=CELERY_PRIORITY[job.priority],
            retry=False,
        )
    except Exception as exc:  # broker/transport exceptions differ by deployment
        return mark_dispatch_failed(job, exc)
    job.refresh_from_db()
    return job


def redispatch_stale_queued_jobs(*, stale_seconds: int = 300) -> dict:
    """Safely republish queued jobs after a web-process crash window.

    The same Celery task id is reused.  Duplicate deliveries are harmless because
    only a queued DB row can be claimed; later copies observe a final/running row.
    """

    cutoff = timezone.now() - timedelta(seconds=max(int(stale_seconds), 60))
    rows = list(
        CurriculumProcessingJob.objects.filter(
            status=CurriculumProcessingJobStatus.QUEUED,
        )
        .filter(
            Q(dispatch_attempted_at__lt=cutoff)
            | Q(dispatch_attempted_at__isnull=True, created_at__lt=cutoff)
        )
        .order_by("id")
    )
    redispatched = failed = 0
    for job in rows:
        result = dispatch_processing_job(job, force=True)
        if result.status == CurriculumProcessingJobStatus.FAILED:
            failed += 1
        else:
            redispatched += 1
    return {"selected": len(rows), "redispatched": redispatched, "failed": failed}


def claim_processing_job(
    job_id: int,
    *,
    worker_hostname: str = "",
    task_id: str = "",
    redelivered: bool = False,
) -> CurriculumProcessingJob | None:
    with transaction.atomic():
        job = (
            CurriculumProcessingJob.objects.select_for_update()
            .select_related("version__source", "requested_by")
            .filter(pk=job_id)
            .first()
        )
        if not job:
            return None
        if job.status == CurriculumProcessingJobStatus.CANCELLED:
            return None
        if job.status == CurriculumProcessingJobStatus.CANCELLING:
            finish_job_cancelled(job)
            return None
        recovered = bool(
            job.status == CurriculumProcessingJobStatus.RUNNING
            and redelivered
            and task_id
            and task_id == job.celery_task_id
        )
        if job.status != CurriculumProcessingJobStatus.QUEUED and not recovered:
            return None
        version = job.version
        if version.status != CurriculumVersionStatus.DRAFT:
            raise ProcessingJobError(
                "version_not_draft",
                "课程标准版本已进入复核流程，后台处理没有执行。",
            )
        if (
            version.pdf_sha256 != job.source_pdf_sha256
            or version.content_hash != job.source_content_hash
        ):
            raise ProcessingJobError(
                "source_changed",
                "课程标准草稿在排队期间已变化，请根据当前版本重新创建任务。",
            )
        job.staged_pages.all().delete()
        now = timezone.now()
        job.status = CurriculumProcessingJobStatus.RUNNING
        job.stage = CurriculumProcessingStage.PREPARING
        job.progress_current = 0
        job.progress_total = version.pdf_page_count
        job.started_at = now
        job.heartbeat_at = now
        job.worker_hostname = worker_hostname[:255]
        job.error_code = ""
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "stage",
                "progress_current",
                "progress_total",
                "started_at",
                "heartbeat_at",
                "worker_hostname",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
        _audit(
            job,
            "processing_job_recovered" if recovered else "processing_job_started",
            {
                "worker_hostname": worker_hostname[:255],
                "celery_task_id": task_id,
                "redelivered": redelivered,
            },
        )
        return job


def processing_cancel_requested(job_id: int) -> bool:
    status = CurriculumProcessingJob.objects.filter(pk=job_id).values_list(
        "status", flat=True
    ).first()
    return status in {
        CurriculumProcessingJobStatus.CANCELLING,
        CurriculumProcessingJobStatus.CANCELLED,
    }


def set_processing_stage(job_id: int, phase: str) -> None:
    stage = (
        CurriculumProcessingStage.OCR
        if phase == "ocr"
        else CurriculumProcessingStage.EXTRACTING
    )
    CurriculumProcessingJob.objects.filter(
        pk=job_id,
        status=CurriculumProcessingJobStatus.RUNNING,
    ).update(stage=stage, heartbeat_at=timezone.now(), updated_at=timezone.now())


def stage_processing_page(job_id: int, record: dict, current: int, total: int) -> None:
    with transaction.atomic():
        job = CurriculumProcessingJob.objects.select_for_update().get(pk=job_id)
        if job.status in {
            CurriculumProcessingJobStatus.CANCELLING,
            CurriculumProcessingJobStatus.CANCELLED,
        }:
            raise CurriculumExtractionCancelled()
        if job.status != CurriculumProcessingJobStatus.RUNNING:
            raise ProcessingJobError("invalid_job_state", "后台处理任务已不处于运行状态。")
        confidence = _normalize_mean_confidence(record.get("mean_confidence"))
        CurriculumProcessingPage.objects.update_or_create(
            job=job,
            page_number=record["page_number"],
            defaults={
                "text": record.get("text", ""),
                "extraction_method": record["extraction_method"],
                "mean_confidence": confidence,
                "quality_status": record.get("quality_status", "complete"),
                "quality_message": record.get("quality_message", ""),
            },
        )
        now = timezone.now()
        job.progress_current = current
        job.progress_total = total
        job.heartbeat_at = now
        job.save(
            update_fields=[
                "progress_current",
                "progress_total",
                "heartbeat_at",
                "updated_at",
            ]
        )


def validate_and_promote(job_id: int, extracted) -> CurriculumProcessingJob:
    with transaction.atomic():
        job = (
            CurriculumProcessingJob.objects.select_for_update()
            .select_related("version__source", "requested_by")
            .get(pk=job_id)
        )
        if job.status == CurriculumProcessingJobStatus.CANCELLING:
            raise ProcessingJobCancelled()
        if job.status != CurriculumProcessingJobStatus.RUNNING:
            raise ProcessingJobError("invalid_job_state", "后台处理任务已不处于运行状态。")
        version = CurriculumStandardVersion.objects.select_for_update().get(pk=job.version_id)
        if version.status != CurriculumVersionStatus.DRAFT:
            raise ProcessingJobError(
                "version_not_draft",
                "课程标准版本已进入复核流程，本次结果没有写入。",
            )
        if (
            version.pdf_sha256 != job.source_pdf_sha256
            or version.content_hash != job.source_content_hash
        ):
            raise ProcessingJobError(
                "source_changed",
                "处理期间课程标准草稿已变化，本次结果没有写入。",
            )
        job.stage = CurriculumProcessingStage.VALIDATING
        job.heartbeat_at = timezone.now()
        job.save(update_fields=["stage", "heartbeat_at", "updated_at"])
        staged = list(job.staged_pages.order_by("page_number"))
        expected_numbers = list(range(1, version.pdf_page_count + 1))
        if [page.page_number for page in staged] != expected_numbers:
            raise ProcessingJobError(
                "incomplete_pages",
                f"处理结果未完整覆盖 PDF 的 {version.pdf_page_count} 页，正式文本没有更新。",
            )
        if extracted.status != CurriculumExtractionStatus.COMPLETED:
            code = (
                "ocr_required"
                if extracted.status == CurriculumExtractionStatus.NEEDS_OCR
                else "extraction_failed"
            )
            raise ProcessingJobError(code, extracted.message or "课程标准文本处理失败。")
        records = [
            {
                "page_number": page.page_number,
                "text": page.text,
                "extraction_method": page.extraction_method,
                "mean_confidence": page.mean_confidence,
                "quality_status": page.quality_status,
                "quality_message": page.quality_message,
            }
            for page in staged
        ]
        structured_text = _structured_text_from_page_records(records)
        if sum(page.char_count for page in staged) < 200:
            raise ProcessingJobError(
                "insufficient_text",
                "处理结果有效文本不足 200 字，正式文本没有更新，请人工核对原始 PDF。",
            )

        job.stage = CurriculumProcessingStage.COMMITTING
        job.heartbeat_at = timezone.now()
        job.save(update_fields=["stage", "heartbeat_at", "updated_at"])
        version.nodes.all().delete()
        version.pages.all().delete()
        version.structured_text = structured_text
        version.structured_text_sha256 = _structured_hash(structured_text)
        version.extraction_status = CurriculumExtractionStatus.COMPLETED
        version.extraction_message = extracted.message
        version.extraction_engine = extracted.engine
        version.extraction_engine_version = extracted.engine_version
        version.extraction_config = extracted.config
        version.extracted_at = timezone.now()
        _save_page_records(version, records)
        create_suggested_framework_nodes(
            version=version,
            pages=[record["text"] for record in records],
        )
        version.content_hash = canonical_hash(_version_semantic_content(version))
        version.save()
        from .retrieval import rebuild_retrieval_index

        retrieval_index, _ = rebuild_retrieval_index(version, actor=job.requested_by)

        now = timezone.now()
        job.status = CurriculumProcessingJobStatus.SUCCEEDED
        job.stage = CurriculumProcessingStage.FINISHED
        job.progress_current = version.pdf_page_count
        job.progress_total = version.pdf_page_count
        job.heartbeat_at = now
        job.finished_at = now
        job.result_summary = {
            "page_count": version.pdf_page_count,
            "text_char_count": sum(page.char_count for page in staged),
            "structured_text_sha256": version.structured_text_sha256,
            "version_content_hash": version.content_hash,
            "extraction_engine": extracted.engine,
            "extraction_status": version.extraction_status,
            "retrieval_chunk_count": retrieval_index.chunk_count,
            "retrieval_index_hash": retrieval_index.index_hash,
        }
        job.save(
            update_fields=[
                "status",
                "stage",
                "progress_current",
                "progress_total",
                "heartbeat_at",
                "finished_at",
                "result_summary",
                "updated_at",
            ]
        )
        _audit(job, "processing_job_succeeded", job.result_summary)
        # Successful staging rows are temporary; the governed page records now
        # contain the atomically promoted result.  Failed/cancelled staging is
        # retained for diagnosis and an explicit retry receives a fresh job.
        job.staged_pages.all().delete()
        return job


def finish_job_cancelled(job: CurriculumProcessingJob | int) -> CurriculumProcessingJob:
    job_id = job if isinstance(job, int) else job.pk
    with transaction.atomic():
        job = (
            CurriculumProcessingJob.objects.select_for_update()
            .select_related("version", "requested_by")
            .get(pk=job_id)
        )
        if job.status in FINAL_JOB_STATUSES:
            return job
        job.status = CurriculumProcessingJobStatus.CANCELLED
        job.stage = CurriculumProcessingStage.CANCELLED
        job.finished_at = timezone.now()
        job.error_code = ""
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "stage",
                "finished_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
        _audit(job, "processing_job_cancelled")
        return job


def finish_job_failed(job: CurriculumProcessingJob | int, code: str, message: str) -> CurriculumProcessingJob:
    job_id = job if isinstance(job, int) else job.pk
    with transaction.atomic():
        job = (
            CurriculumProcessingJob.objects.select_for_update()
            .select_related("version", "requested_by")
            .get(pk=job_id)
        )
        if job.status in FINAL_JOB_STATUSES:
            return job
        job.status = CurriculumProcessingJobStatus.FAILED
        job.stage = CurriculumProcessingStage.FAILED
        job.error_code = code[:80]
        job.error_message = str(message)[:4000]
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "stage",
                "error_code",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )
        _audit(job, "processing_job_failed", {"error_code": code, "error": str(message)[:500]})
        return job


def finish_job_failed_safely(job_id: int, code: str, message: str) -> None:
    for delay in (0.0, 0.2, 0.5, 1.0):
        if delay:
            time.sleep(delay)
        close_old_connections()
        try:
            finish_job_failed(job_id, code, message)
            return
        except OperationalError:
            continue


def request_job_cancel(job: CurriculumProcessingJob, *, actor) -> CurriculumProcessingJob:
    with transaction.atomic():
        job = (
            CurriculumProcessingJob.objects.select_for_update()
            .select_related("version", "requested_by")
            .get(pk=job.pk)
        )
        if job.status in FINAL_JOB_STATUSES:
            return job
        now = timezone.now()
        job.cancel_requested_by = actor
        job.cancel_requested_at = now
        if job.status == CurriculumProcessingJobStatus.QUEUED:
            job.status = CurriculumProcessingJobStatus.CANCELLED
            job.stage = CurriculumProcessingStage.CANCELLED
            job.finished_at = now
            action = "processing_job_cancelled"
        else:
            job.status = CurriculumProcessingJobStatus.CANCELLING
            action = "processing_job_cancel_requested"
        job.save(
            update_fields=[
                "status",
                "stage",
                "cancel_requested_by",
                "cancel_requested_at",
                "finished_at",
                "updated_at",
            ]
        )
        CurriculumStandardAuditLog.objects.create(
            version=job.version,
            action=action,
            actor=actor,
            detail={"processing_job_id": job.id},
        )
    # Do not depend on broker remote control (filesystem transport and Windows do
    # not support it reliably).  The worker checks this DB state between pages.
    return job


def retry_processing_job(job: CurriculumProcessingJob, *, actor) -> tuple[CurriculumProcessingJob, bool]:
    job.refresh_from_db()
    if job.status not in {
        CurriculumProcessingJobStatus.FAILED,
        CurriculumProcessingJobStatus.CANCELLED,
    }:
        raise ValidationError("只有失败或已取消的后台任务可以重试。")
    return create_processing_job(
        version=job.version,
        actor=actor,
        mode=job.mode,
        priority=job.priority,
        retry_of=job,
    )


def run_processing_job(
    job_id: int,
    *,
    worker_hostname: str = "",
    task_id: str = "",
    redelivered: bool = False,
) -> None:
    try:
        job = claim_processing_job(
            job_id,
            worker_hostname=worker_hostname,
            task_id=task_id,
            redelivered=redelivered,
        )
        if not job:
            return
        version = job.version
        with version.pdf_file.open("rb") as raw:
            if sha256_file(raw) != job.source_pdf_sha256:
                raise ProcessingJobError(
                    "pdf_hash_mismatch",
                    "原始 PDF 文件校验失败，正式课标文本未发生变化。",
                )
            extracted = extract_pdf_text(
                raw,
                allow_ocr=True,
                force_ocr=job.mode == CurriculumProcessingMode.OCR,
                page_callback=lambda record, current, total: stage_processing_page(
                    job.id, record, current, total
                ),
                cancel_check=lambda: processing_cancel_requested(job.id),
                phase_callback=lambda phase: set_processing_stage(job.id, phase),
            )
        validate_and_promote(job.id, extracted)
    except (CurriculumExtractionCancelled, ProcessingJobCancelled):
        finish_job_cancelled(job_id)
    except ProcessingJobError as exc:
        finish_job_failed_safely(job_id, exc.code, exc.message)
    except OperationalError as exc:
        message = (
            "数据库正忙，任务已安全终止；正式课标文本未被半成品覆盖。"
            "当前使用 SQLite 时请稍后重试，正式部署建议使用 PostgreSQL。"
            f"技术信息：{str(exc)[:500]}"
        )
        finish_job_failed_safely(job_id, "database_locked", message)
    except Exception as exc:
        finish_job_failed_safely(
            job_id,
            "processing_error",
            f"后台处理失败，正式课标文本未被半成品覆盖。技术信息：{str(exc)[:1000]}",
        )


def processing_job_summary(queryset=None) -> dict:
    queryset = queryset if queryset is not None else CurriculumProcessingJob.objects.all()
    counts = {row["status"]: row["count"] for row in queryset.values("status").annotate(count=Count("id"))}
    return {
        "total": sum(counts.values()),
        "queued": counts.get(CurriculumProcessingJobStatus.QUEUED, 0),
        "running": counts.get(CurriculumProcessingJobStatus.RUNNING, 0),
        "succeeded": counts.get(CurriculumProcessingJobStatus.SUCCEEDED, 0),
        "failed": counts.get(CurriculumProcessingJobStatus.FAILED, 0),
        "cancelling": counts.get(CurriculumProcessingJobStatus.CANCELLING, 0),
        "cancelled": counts.get(CurriculumProcessingJobStatus.CANCELLED, 0),
        "active": sum(counts.get(value, 0) for value in ACTIVE_JOB_STATUSES),
    }
