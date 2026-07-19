from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError, transaction

from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)


class AssessmentResultError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _decimal(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@transaction.atomic
def record_assessment_result(
    *,
    event: LearningEventV2,
    opportunity: LearningOpportunity,
) -> tuple[AssessmentResultFact, bool]:
    if event.event_name != "item.graded":
        raise AssessmentResultError(
            "grading_event_invalid",
            "评分结果事实只能来源于 item.graded 事件。",
        )
    if event.opportunity_record_id != opportunity.opportunity_id:
        raise AssessmentResultError(
            "grading_opportunity_mismatch",
            "评分事件与学习机会不一致。",
        )
    if not event.attempt_id:
        raise AssessmentResultError(
            "grading_attempt_required",
            "评分事件必须关联作答尝试。",
        )

    existing = AssessmentResultFact.objects.filter(source_event=event).first()
    if existing:
        return existing, False

    opportunity = LearningOpportunity.objects.select_for_update().get(
        opportunity_id=opportunity.opportunity_id
    )
    submitted = opportunity.transition_facts.filter(
        state=LearningOpportunityTransitionFact.State.SUBMITTED,
        source_event__attempt_id=event.attempt_id,
        occurred_at__lte=event.client_occurred_at,
    ).exists()
    if not submitted:
        raise AssessmentResultError(
            "grading_submission_required",
            "作答尚未形成提交事实，不能记录评分。",
        )

    previous = (
        AssessmentResultFact.objects.filter(
            opportunity=opportunity,
            attempt_id=event.attempt_id,
        )
        .order_by("-grade_version")
        .first()
    )
    grading_state = event.payload["grading_state"]
    supersedes = None
    if previous and event.client_occurred_at < previous.graded_at:
        raise AssessmentResultError(
            "grading_time_conflict",
            "评分事件早于当前评分版本，不能改变成熟状态顺序。",
        )
    if grading_state == AssessmentResultFact.GradingState.PENDING:
        if previous and previous.is_mature:
            raise AssessmentResultError(
                "mature_grade_cannot_return_pending",
                "作答已有成熟评分，不能退回待评分状态。",
            )
        supersedes = previous
    elif grading_state == AssessmentResultFact.GradingState.FINAL:
        if previous and previous.is_mature:
            raise AssessmentResultError(
                "final_grade_already_exists",
                "作答已有最终评分，后续修改必须使用 revised 状态。",
            )
        supersedes = previous
    elif grading_state == AssessmentResultFact.GradingState.REVISED:
        if previous is None or not previous.is_mature:
            raise AssessmentResultError(
                "revised_grade_requires_mature_predecessor",
                "修订评分必须引用已有最终或修订评分。",
            )
        supersedes = previous

    fact = AssessmentResultFact(
        opportunity=opportunity,
        source_event=event,
        supersedes=supersedes,
        school=opportunity.school,
        student=opportunity.student,
        class_group=opportunity.class_group,
        subject=opportunity.subject,
        course=opportunity.course,
        lesson=opportunity.lesson,
        classroom_session=opportunity.classroom_session,
        lesson_step=opportunity.lesson_step,
        grader=(
            event.actor
            if event.payload["grader_type"] == "teacher"
            and event.payload["grading_state"]
            in {
                AssessmentResultFact.GradingState.FINAL,
                AssessmentResultFact.GradingState.REVISED,
            }
            and event.source == "teacher-web"
            and event.actor_id
            and event.actor.role == event.actor.Role.TEACHER
            else None
        ),
        attempt_id=event.attempt_id,
        object_id=opportunity.object_id,
        object_version=opportunity.object_version,
        grade_version=(previous.grade_version + 1 if previous else 1),
        grading_state=grading_state,
        score_raw=_decimal(event.payload.get("score_raw")),
        score_max=_decimal(event.payload["score_max"]),
        is_correct=event.payload.get("is_correct"),
        grader_type=event.payload["grader_type"],
        graded_at=event.client_occurred_at,
        recorded_at=event.server_received_at,
    )
    try:
        fact.save()
    except IntegrityError as exc:
        raise AssessmentResultError(
            "grading_version_conflict",
            "评分版本并发冲突，请重新读取后再评分。",
        ) from exc
    return fact, True
