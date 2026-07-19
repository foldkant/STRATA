from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Subject,
)
from learning.models import LearningEvent
from learning_analytics.models import (
    AnalyticsPipelineRun,
    AnalyticsTaskRun,
    AssessmentResultFact,
    DataQualityReport,
    EventIngestionDailyCounter,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
    ParticipationPointLedger,
    SyntheticDatasetRun,
    SyntheticStudentTruth,
)
from school.models import ClassGroup, StudentProfile, TeachingAssignment


class SyntheticCleanupError(Exception):
    pass


def synthetic_cleanup_preview(run: SyntheticDatasetRun) -> dict:
    events = LearningEventV2.objects.filter(synthetic_run=run)
    truths = SyntheticStudentTruth.objects.filter(synthetic_run=run)
    return {
        "run_id": str(run.run_id),
        "dataset_key": run.dataset_key,
        "school_code": run.school.code,
        "mode": run.mode,
        "status": run.status,
        "events": events.count(),
        "legacy_events": LearningEvent.objects.filter(
            metadata__synthetic_run_id=str(run.run_id)
        ).count(),
        "students": truths.values("student_id").distinct().count(),
        "classes": truths.values("class_group_id").distinct().count(),
        "opportunities": LearningOpportunity.objects.filter(
            release_event__synthetic_run=run
        ).count(),
        "quality_reports": DataQualityReport.objects.filter(synthetic_run=run).count(),
    }


@transaction.atomic
def purge_synthetic_dataset(*, run: SyntheticDatasetRun, confirmation_key: str) -> dict:
    if confirmation_key != run.dataset_key:
        raise SyntheticCleanupError("数据集确认指纹不匹配，拒绝清理。")
    if run.status == SyntheticDatasetRun.Status.RUNNING:
        raise SyntheticCleanupError("生成批次仍在运行，不能清理。")
    if run.status == SyntheticDatasetRun.Status.PURGED:
        return dict(run.purge_summary or synthetic_cleanup_preview(run))

    preview = synthetic_cleanup_preview(run)
    events = LearningEventV2.objects.filter(synthetic_run=run)
    legacy_ids = list(events.values_list("legacy_event_id", flat=True))
    student_ids = list(
        SyntheticStudentTruth.objects.filter(synthetic_run=run).values_list(
            "student_id", flat=True
        )
    )
    class_ids = list(
        SyntheticStudentTruth.objects.filter(synthetic_run=run)
        .values_list("class_group_id", flat=True)
        .distinct()
    )
    subject_ids = list(
        events.exclude(subject_id=None).values_list("subject_id", flat=True).distinct()
    )
    course_ids = list(
        events.exclude(course_id=None).values_list("course_id", flat=True).distinct()
    )
    lesson_ids = list(
        events.exclude(lesson_id=None).values_list("lesson_id", flat=True).distinct()
    )
    step_ids = list(
        events.exclude(lesson_step_id=None)
        .values_list("lesson_step_id", flat=True)
        .distinct()
    )
    session_ids = list(
        events.exclude(classroom_session_id=None)
        .values_list("classroom_session_id", flat=True)
        .distinct()
    )

    pipeline_runs = AnalyticsPipelineRun.objects.filter(synthetic_run=run)
    DataQualityReport.objects.filter(synthetic_run=run).delete()
    AnalyticsTaskRun.objects.filter(pipeline_run__in=pipeline_runs).delete()
    pipeline_runs.delete()
    EventIngestionDailyCounter.objects.filter(synthetic_run=run).delete()

    AssessmentResultFact.objects.filter(source_event__synthetic_run=run).delete()
    ParticipationPointLedger.objects.filter(source_event__synthetic_run=run).delete()
    LearningOpportunityTransitionFact.objects.filter(
        source_event__synthetic_run=run
    ).delete()
    events.exclude(event_name="content.released").delete()
    LearningOpportunity.objects.filter(release_event__synthetic_run=run).delete()
    LearningEventV2.objects.filter(synthetic_run=run).delete()
    LearningEvent.objects.filter(pk__in=[item for item in legacy_ids if item]).delete()

    SyntheticStudentTruth.objects.filter(synthetic_run=run).delete()
    StudentProfile.objects.filter(user_id__in=student_ids).delete()
    CourseClass.objects.filter(course_id__in=course_ids).delete()
    ClassroomSession.objects.filter(pk__in=session_ids).delete()
    LessonStep.objects.filter(pk__in=step_ids).delete()
    Lesson.objects.filter(pk__in=lesson_ids).delete()
    Course.objects.filter(pk__in=course_ids).delete()
    TeachingAssignment.objects.filter(class_group_id__in=class_ids).delete()
    ClassGroup.objects.filter(pk__in=class_ids).delete()
    Subject.objects.filter(pk__in=subject_ids).delete()
    User.objects.filter(pk__in=student_ids).delete()

    if run.mode == SyntheticDatasetRun.Mode.ISOLATED_SCHOOL:
        User.objects.filter(
            school=run.school,
            role=User.Role.TEACHER,
            username__endswith="_teacher",
        ).delete()

    summary = {
        **preview,
        "status": SyntheticDatasetRun.Status.PURGED,
        "purged_at": timezone.now().isoformat(),
    }
    run.status = SyntheticDatasetRun.Status.PURGED
    run.purged_at = timezone.now()
    run.purge_summary = summary
    run.save(update_fields=["status", "purged_at", "purge_summary"])
    return summary
