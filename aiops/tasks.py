from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from .models import QuestionDraftGenerationJob, TeacherAIProvider, TrainingJob


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


@shared_task(
    bind=True,
    acks_late=True,
    name="aiops.generate_question_bank_drafts",
)
def generate_question_bank_drafts_task(self, job_id: int) -> int:
    from types import SimpleNamespace

    from api.pretest_services import generate_question_bank_drafts_with_ai
    from api.services import ServiceError

    job = (
        QuestionDraftGenerationJob.objects.select_related(
            "teacher__school", "subject"
        )
        .filter(pk=job_id)
        .first()
    )
    if job is None or job.status == QuestionDraftGenerationJob.Status.CANCELLED:
        return job_id

    job.status = QuestionDraftGenerationJob.Status.RUNNING
    job.started_at = timezone.now()
    job.finished_at = None
    job.error_message = ""
    job.error_fields = {}
    job.attempt_count += 1
    job.celery_task_id = str(getattr(self.request, "id", "") or job.celery_task_id)
    job.save(
        update_fields=[
            "status",
            "started_at",
            "finished_at",
            "error_message",
            "error_fields",
            "attempt_count",
            "celery_task_id",
            "updated_at",
        ]
    )

    request = SimpleNamespace(user=job.teacher, META={})
    try:
        result = generate_question_bank_drafts_with_ai(
            request,
            job.request_payload,
            subject_name=job.subject.name,
        )
        result["subject"] = {
            "id": job.subject_id,
            "name": job.subject.name,
            "code": job.subject.code,
        }
        provider = TeacherAIProvider.objects.filter(teacher=job.teacher).first()
        job.result_payload = result
        job.provider = provider.provider if provider else ""
        job.model = provider.model if provider else ""
        job.status = QuestionDraftGenerationJob.Status.SUCCEEDED
    except ServiceError as exc:
        job.error_message = exc.message
        job.error_fields = exc.errors
        job.status = QuestionDraftGenerationJob.Status.FAILED
    except Exception:
        # External service details stay in server logs; the teacher receives a
        # recoverable message without internal paths or credentials.
        job.error_message = "后台生成任务未完成，请稍后重试。"
        job.error_fields = {}
        job.status = QuestionDraftGenerationJob.Status.FAILED
        raise
    finally:
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "result_payload",
                "error_message",
                "error_fields",
                "provider",
                "model",
                "finished_at",
                "updated_at",
            ]
        )
    return job.id
