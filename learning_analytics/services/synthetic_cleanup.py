from __future__ import annotations

from pathlib import Path

from django.conf import settings
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
from learning.models import LearningEvent, StratificationDecision
from learning_analytics.models import (
    AnalyticsPipelineRun,
    AnalyticsTaskRun,
    AssessmentResultFact,
    ClassroomEvaluationStandardUse,
    DataQualityReport,
    EvaluationCriterionVersion,
    EvaluationPlan,
    EvaluationPlanVersion,
    EvaluationScoringExample,
    EvaluationStandard,
    EvaluationStandardVersion,
    EvaluationSubmissionEvidence,
    EvaluationTrialRecord,
    EventIngestionDailyCounter,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
    LessonStepEvaluationBinding,
    ParticipationPointLedger,
    StudentLearningSummary,
    SyntheticDatasetRun,
    SyntheticStudentTruth,
    ClassCalibrationRun,
    DecisionPoint,
    DecisionPointStudent,
    LongitudinalAnalysisRun,
    LongitudinalFeatureResult,
    ModelComparisonRun,
    ModelEvaluationResult,
    ModelPrediction,
    NegativeControlResult,
    OutcomeObservation,
    StudentFeatureSnapshot,
    TrainingDatasetRow,
    TrainingDatasetVersion,
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
        "decision_points": DecisionPoint.objects.filter(synthetic_run=run).count(),
        "datasets": TrainingDatasetVersion.objects.filter(synthetic_run=run).count(),
        "model_runs": ModelComparisonRun.objects.filter(
            dataset__synthetic_run=run
        ).count(),
        "calibration_runs": ClassCalibrationRun.objects.filter(
            dataset__synthetic_run=run
        ).count(),
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

    datasets = TrainingDatasetVersion.objects.filter(synthetic_run=run)
    dataset_ids = list(datasets.values_list("id", flat=True))
    point_ids = list(
        DecisionPoint.objects.filter(synthetic_run=run).values_list("id", flat=True)
    )
    comparison_runs = ModelComparisonRun.objects.filter(dataset_id__in=dataset_ids)
    comparison_ids = list(comparison_runs.values_list("id", flat=True))
    calibration_runs = ClassCalibrationRun.objects.filter(dataset_id__in=dataset_ids)
    artifact_paths = list(
        calibration_runs.exclude(artifact_path="").values_list(
            "artifact_path", flat=True
        )
    )
    # Test students and their generated courses may have acquired summaries,
    # teacher-review candidates, or evaluation drafts during acceptance testing.
    # Remove those derived records before deleting the protected course graph.
    StratificationDecision.objects.filter(student_id__in=student_ids).delete()
    StudentLearningSummary.objects.filter(student_id__in=student_ids).delete()

    standard_versions = EvaluationStandardVersion.objects.filter(
        course_id__in=course_ids
    )
    standard_version_ids = list(standard_versions.values_list("id", flat=True))
    standard_uses = ClassroomEvaluationStandardUse.objects.filter(
        standard_version_id__in=standard_version_ids
    )
    EvaluationSubmissionEvidence.objects.filter(standard_use__in=standard_uses).delete()
    standard_uses.delete()
    LessonStepEvaluationBinding.objects.filter(
        standard_version_id__in=standard_version_ids
    ).delete()
    EvaluationTrialRecord.objects.filter(
        standard_version_id__in=standard_version_ids
    ).delete()
    criteria = EvaluationCriterionVersion.objects.filter(
        standard_version_id__in=standard_version_ids
    )
    EvaluationScoringExample.objects.filter(criterion__in=criteria).delete()
    criteria.delete()
    standard_versions.delete()
    EvaluationStandard.objects.filter(course_id__in=course_ids).delete()
    EvaluationPlanVersion.objects.filter(course_id__in=course_ids).delete()
    EvaluationPlan.objects.filter(course_id__in=course_ids).delete()
    calibration_runs.delete()
    ModelPrediction.objects.filter(run_id__in=comparison_ids).delete()
    NegativeControlResult.objects.filter(run_id__in=comparison_ids).delete()
    ModelEvaluationResult.objects.filter(run_id__in=comparison_ids).delete()
    comparison_runs.delete()
    longitudinal_runs = LongitudinalAnalysisRun.objects.filter(
        dataset_id__in=dataset_ids
    )
    LongitudinalFeatureResult.objects.filter(run__in=longitudinal_runs).delete()
    longitudinal_runs.delete()
    TrainingDatasetRow.objects.filter(dataset_id__in=dataset_ids).delete()
    datasets.delete()
    observations = OutcomeObservation.objects.filter(decision_point_id__in=point_ids)
    observation_versions = list(
        observations.order_by()
        .values_list("observation_version", flat=True)
        .distinct()
    )
    for version in sorted(observation_versions, reverse=True):
        observations.filter(observation_version=version).delete()
    StudentFeatureSnapshot.objects.filter(decision_point_id__in=point_ids).delete()
    DecisionPointStudent.objects.filter(decision_point_id__in=point_ids).delete()
    DecisionPoint.objects.filter(id__in=point_ids).delete()
    base_dir = Path(settings.BASE_DIR).resolve()
    model_root = Path(settings.MODEL_ARTIFACT_ROOT).resolve()
    for artifact_path in artifact_paths:
        candidate = Path(artifact_path)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (base_dir / candidate).resolve()
        )
        if resolved.is_file() and (
            resolved == model_root or model_root in resolved.parents
        ):
            resolved.unlink()

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
