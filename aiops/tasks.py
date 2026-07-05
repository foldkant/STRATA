from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from .models import TrainingJob


@shared_task
def train_class_model(training_job_id: int) -> int:
    job = TrainingJob.objects.select_related("class_group").get(id=training_job_id)
    job.status = TrainingJob.Status.RUNNING
    job.started_at = timezone.now()
    job.logs = "Training pipeline placeholder. Feature aggregation and model fitting will be implemented next."
    job.save(update_fields=["status", "started_at", "logs"])

    job.status = TrainingJob.Status.SUCCEEDED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at"])
    return job.id
