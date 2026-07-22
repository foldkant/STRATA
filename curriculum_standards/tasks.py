from __future__ import annotations

from celery import shared_task
from django.conf import settings

from .processing import run_processing_job


@shared_task(
    bind=True,
    name="curriculum_standards.process_version_pdf",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=getattr(settings, "CURRICULUM_OCR_TASK_SOFT_TIME_LIMIT", 10800),
    time_limit=getattr(settings, "CURRICULUM_OCR_TASK_TIME_LIMIT", 11100),
)
def process_version_pdf(self, job_id: int) -> None:
    """Process exactly one PDF; durable state lives in Django, not Celery results."""

    run_processing_job(
        int(job_id),
        worker_hostname=str(getattr(self.request, "hostname", "") or ""),
        task_id=str(getattr(self.request, "id", "") or ""),
        redelivered=bool(
            (getattr(self.request, "delivery_info", None) or {}).get("redelivered")
        ),
    )
