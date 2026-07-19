from __future__ import annotations

import hashlib
import json

from django.db import transaction

from learning.models import LearningEvent, QuestionBankItem
from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    learning_event_write_mode,
    record_learning_event,
)


class AssessmentEventError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def assessment_question_object_id(question) -> str:
    return f"assessment-question:{question.id}"


def assessment_question_version(question) -> str:
    snapshot = {
        "assessment_id": question.assessment_id,
        "question_id": question.id,
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options,
        "answer": question.answer,
        "analysis": question.analysis,
        "knowledge_point": question.knowledge_point,
        "score": str(question.score),
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def release_assessment_opportunities(*, assessment, actor, occurred_at) -> dict:
    created = 0
    release_events = 0
    questions = list(assessment.questions.order_by("sort_order", "id"))
    classes = list(assessment.target_classes.order_by("id"))
    for class_group in classes:
        for question in questions:
            try:
                result = record_learning_event(
                    actor=actor,
                    event_name="content.released",
                    payload={
                        "content_type": "question",
                        "required": True,
                        "available_to": assessment.end_at,
                        "target_layers": ["all"],
                    },
                    legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                    class_group=class_group,
                    subject=assessment.subject,
                    course=assessment.course,
                    object_type="test_assessment_question",
                    object_id=assessment_question_object_id(question),
                    object_version=assessment_question_version(question),
                    legacy_metadata={
                        "action": "assessment_question_released",
                        "assessment_id": assessment.id,
                        "question_id": question.id,
                        "class_group_id": class_group.id,
                    },
                    occurred_at=occurred_at,
                )
            except EventWriteError as exc:
                raise AssessmentEventError(exc.code, exc.message) from exc
            release_events += 1
            if result.analytics_event:
                created += result.analytics_event.released_opportunities.count()
    return {"release_events": release_events, "opportunities_created": created}


@transaction.atomic
def withdraw_assessment_opportunities(*, assessment, actor, occurred_at) -> dict:
    releases = LearningEventV2.objects.filter(
        school=assessment.school,
        event_name="content.released",
        legacy_event__metadata__action="assessment_question_released",
        legacy_event__metadata__assessment_id=assessment.id,
    ).select_related("class_group", "subject", "course")
    withdrawn_events = 0
    for release in releases:
        if LearningEventV2.objects.filter(
            school=assessment.school,
            event_name="content.withdrawn",
            payload__release_event_id=str(release.event_id),
        ).exists():
            continue
        try:
            record_learning_event(
                actor=actor,
                event_name="content.withdrawn",
                payload={
                    "release_event_id": release.event_id,
                    "reason_code": "assessment_closed",
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=release.class_group,
                subject=release.subject,
                course=release.course,
                object_type="test_assessment",
                object_id=assessment.id,
                legacy_metadata={
                    "action": "assessment_question_withdrawn",
                    "assessment_id": assessment.id,
                    "release_event_id": str(release.event_id),
                },
                occurred_at=occurred_at,
            )
        except EventWriteError as exc:
            raise AssessmentEventError(exc.code, exc.message) from exc
        withdrawn_events += 1
    return {"withdrawal_events": withdrawn_events}


def assessment_opportunity_for(*, attempt, question) -> LearningOpportunity | None:
    if learning_event_write_mode() == "v1_only":
        return None
    opportunities = (
        LearningOpportunity.objects.filter(
            school=attempt.assessment.school,
            student=attempt.student,
            class_group=attempt.class_group,
            subject=attempt.assessment.subject,
            content_type=LearningOpportunity.ContentType.QUESTION,
            object_id=assessment_question_object_id(question),
            object_version=assessment_question_version(question),
            release_event__legacy_event__metadata__action="assessment_question_released",
            release_event__legacy_event__metadata__assessment_id=attempt.assessment_id,
        )
        .order_by("-released_at", "-created_at")
        .distinct()
    )
    for opportunity in opportunities:
        if not opportunity.transition_facts.filter(
            state__in=LearningOpportunityTransitionFact.TERMINAL_STATES
        ).exists():
            return opportunity
    raise AssessmentEventError(
        "assessment_opportunity_missing",
        "该试题没有可用的学习机会，请重新开启测试后再提交。",
    )


def _response_kind(question) -> str:
    return {
        QuestionBankItem.QuestionType.SINGLE: "single",
        QuestionBankItem.QuestionType.MULTIPLE: "multiple",
        QuestionBankItem.QuestionType.JUDGE: "judge",
        QuestionBankItem.QuestionType.BLANK: "blank",
        QuestionBankItem.QuestionType.TEXT: "text",
    }[question.question_type]


def _event_version(*, opportunity, question) -> str:
    return (
        opportunity.object_version
        if opportunity is not None
        else assessment_question_version(question)
    )


def record_assessment_item_submission(
    *,
    attempt,
    answer_row,
    occurred_at,
    source_override: str | None = None,
):
    question = answer_row.question
    opportunity = assessment_opportunity_for(attempt=attempt, question=question)
    version = _event_version(opportunity=opportunity, question=question)
    try:
        return record_learning_event(
            actor=attempt.student,
            target_student=attempt.student,
            event_name="item.submitted",
            schema_version="1.1",
            source_override=source_override,
            payload={
                "question_version": version,
                "response_kind": _response_kind(question),
                "attempt_no": 1,
                "response_time_ms": None,
            },
            legacy_event_type=LearningEvent.EventType.ANSWER_SUBMIT,
            legacy_actor=attempt.student,
            class_group=attempt.class_group,
            subject=attempt.assessment.subject,
            course=attempt.assessment.course,
            object_type="test_assessment_question",
            object_id=assessment_question_object_id(question),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=attempt.analytics_attempt_id,
            legacy_metadata={
                "action": "test_item_submitted",
                "assessment_id": attempt.assessment_id,
                "attempt_id": attempt.id,
                "question_id": question.id,
                "response_kind": _response_kind(question),
            },
            occurred_at=occurred_at,
        )
    except EventWriteError as exc:
        raise AssessmentEventError(exc.code, exc.message) from exc


def record_assessment_item_grade(
    *,
    attempt,
    answer_row,
    grading_state: str,
    score_raw,
    grader_type: str,
    actor,
    occurred_at,
    source_override: str | None = None,
):
    question = answer_row.question
    opportunity = assessment_opportunity_for(attempt=attempt, question=question)
    version = _event_version(opportunity=opportunity, question=question)
    if question.question_type == QuestionBankItem.QuestionType.TEXT:
        is_correct = None
    elif grader_type == "teacher" and score_raw is not None:
        is_correct = float(score_raw) == float(question.score)
    else:
        is_correct = answer_row.is_correct
    legacy_type = (
        LearningEvent.EventType.TEACHER_INTERVENTION
        if grader_type == "teacher"
        else LearningEvent.EventType.ANSWER_SUBMIT
    )
    try:
        return record_learning_event(
            actor=actor,
            target_student=attempt.student,
            event_name="item.graded",
            source_override=source_override,
            payload={
                "grading_state": grading_state,
                "score_raw": score_raw,
                "score_max": question.score,
                "is_correct": is_correct,
                "grader_type": grader_type,
            },
            legacy_event_type=legacy_type,
            legacy_actor=attempt.student,
            class_group=attempt.class_group,
            subject=attempt.assessment.subject,
            course=attempt.assessment.course,
            object_type="test_assessment_question",
            object_id=assessment_question_object_id(question),
            object_version=version,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=attempt.analytics_attempt_id,
            legacy_score=score_raw,
            legacy_metadata={
                "action": "test_item_graded",
                "assessment_id": attempt.assessment_id,
                "attempt_id": attempt.id,
                "question_id": question.id,
                "grading_state": grading_state,
                "grader_type": grader_type,
            },
            occurred_at=occurred_at,
        )
    except EventWriteError as exc:
        raise AssessmentEventError(exc.code, exc.message) from exc


def next_manual_grading_state(*, attempt, question) -> str:
    if learning_event_write_mode() == "v1_only":
        return AssessmentResultFact.GradingState.FINAL
    opportunity = assessment_opportunity_for(attempt=attempt, question=question)
    mature_exists = AssessmentResultFact.objects.filter(
        opportunity=opportunity,
        attempt_id=attempt.analytics_attempt_id,
        grading_state__in=[
            AssessmentResultFact.GradingState.FINAL,
            AssessmentResultFact.GradingState.REVISED,
        ],
    ).exists()
    return (
        AssessmentResultFact.GradingState.REVISED
        if mature_exists
        else AssessmentResultFact.GradingState.FINAL
    )
