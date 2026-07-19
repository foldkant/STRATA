from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from courses.models import (
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
)
from learning.models import LearningEvent
from learning_analytics.models import (
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    learning_event_write_mode,
    record_learning_event,
)


class EvaluationEventError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


EVALUATION_TYPES = {
    ClassroomEvaluationSubmission.EvaluationType.SELF,
    ClassroomEvaluationSubmission.EvaluationType.PEER,
    ClassroomEvaluationSubmission.EvaluationType.TEACHER,
}


def _criteria_rows(raw_items) -> list[dict]:
    rows = []
    seen = set()
    for index, item in enumerate(raw_items if isinstance(raw_items, list) else [], 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        criterion_id = str(item.get("id") or f"crit_{index}").strip()[:64]
        if not criterion_id or criterion_id in seen:
            continue
        seen.add(criterion_id)
        try:
            sort_order = int(item.get("sort_order") or index * 10)
        except (TypeError, ValueError):
            sort_order = index * 10
        rows.append(
            {
                "id": criterion_id,
                "title": title[:80],
                "description": str(item.get("description") or "").strip()[:300],
                "sort_order": sort_order,
            }
        )
    return sorted(rows, key=lambda item: (item["sort_order"], item["id"]))


def evaluation_config_snapshot(config) -> dict:
    self_criteria = _criteria_rows(config.self_criteria)
    peer_criteria = _criteria_rows(config.peer_criteria)
    teacher_criteria = _criteria_rows(config.teacher_criteria)
    return {
        "enable_self": bool(config.enable_self or self_criteria),
        "enable_peer": bool(config.enable_peer or peer_criteria),
        "enable_teacher": bool(config.enable_teacher or teacher_criteria),
        "self_criteria": self_criteria,
        "peer_criteria": peer_criteria,
        "teacher_criteria": teacher_criteria,
    }


def evaluation_config_hash(snapshot: dict) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def publish_evaluation_config_version(
    *, config: ClassroomEvaluationConfig, actor=None
) -> ClassroomEvaluationConfigVersion:
    config = ClassroomEvaluationConfig.objects.select_for_update().get(pk=config.pk)
    snapshot = evaluation_config_snapshot(config)
    config_hash = evaluation_config_hash(snapshot)
    existing = ClassroomEvaluationConfigVersion.objects.filter(
        course=config.course,
        config_hash=config_hash,
    ).first()
    if existing:
        return existing
    latest_no = (
        ClassroomEvaluationConfigVersion.objects.filter(course=config.course).aggregate(
            value=Max("version_no")
        )["value"]
        or 0
    )
    return ClassroomEvaluationConfigVersion.objects.create(
        course=config.course,
        version_no=latest_no + 1,
        config_hash=config_hash,
        created_by=actor or config.created_by,
        **snapshot,
    )


def evaluation_version_label(version: ClassroomEvaluationConfigVersion) -> str:
    return (
        f"course:{version.course_id}:v{version.version_no}:{version.config_hash[:12]}"
    )


def _criteria_for_type(version, evaluation_type: str) -> list[dict]:
    field = {
        "self": "self_criteria",
        "peer": "peer_criteria",
        "teacher": "teacher_criteria",
    }.get(evaluation_type)
    return _criteria_rows(getattr(version, field, [])) if field else []


def _type_enabled(version, evaluation_type: str) -> bool:
    field = {
        "self": "enable_self",
        "peer": "enable_peer",
        "teacher": "enable_teacher",
    }.get(evaluation_type)
    return bool(
        field
        and getattr(version, field, False)
        and _criteria_for_type(version, evaluation_type)
    )


def classroom_evaluation_object_id(session, evaluation_type: str) -> str:
    return f"classroom-evaluation:{session.id}:{evaluation_type}"


def course_evaluation_object_id(course, class_group, evaluation_type: str) -> str:
    return f"course-evaluation:{course.id}:{class_group.id}:{evaluation_type}"


@transaction.atomic
def release_classroom_evaluation_opportunities(
    *, session, actor, version: ClassroomEvaluationConfigVersion, occurred_at=None
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"release_events": 0, "opportunities_created": 0}
    occurred_at = occurred_at or timezone.now()
    existing_ids = set(
        LearningEventV2.objects.filter(
            school=session.school,
            event_name="content.released",
            classroom_session=session,
            legacy_event__metadata__action="classroom_evaluation_released",
            client_occurred_at__gte=session.evaluation_opened_at or occurred_at,
        ).values_list("object_id", flat=True)
    )
    release_events = 0
    opportunities_created = 0
    for evaluation_type in sorted(EVALUATION_TYPES):
        if not _type_enabled(version, evaluation_type):
            continue
        object_id = classroom_evaluation_object_id(session, evaluation_type)
        if object_id in existing_ids:
            continue
        try:
            result = record_learning_event(
                actor=actor,
                event_name="content.released",
                payload={
                    "content_type": LearningOpportunity.ContentType.TASK,
                    "required": False,
                    "target_layers": ["all"],
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=session.class_group,
                subject=session.course.subject,
                course=session.course,
                lesson=session.lesson,
                classroom_session=session,
                object_type="evaluation_standard",
                object_id=object_id,
                object_version=version.config_hash,
                legacy_metadata={
                    "action": "classroom_evaluation_released",
                    "classroom_session": session.id,
                    "evaluation_type": evaluation_type,
                    "evaluation_version": evaluation_version_label(version),
                },
                occurred_at=occurred_at,
            )
        except EventWriteError as exc:
            raise EvaluationEventError(exc.code, exc.message) from exc
        release_events += 1
        if result.analytics_event:
            opportunities_created += (
                result.analytics_event.released_opportunities.count()
            )
    return {
        "release_events": release_events,
        "opportunities_created": opportunities_created,
    }


@transaction.atomic
def withdraw_classroom_evaluation_opportunities(
    *, session, actor, reason_code: str, occurred_at=None
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"withdrawal_events": 0}
    occurred_at = occurred_at or timezone.now()
    releases = LearningEventV2.objects.filter(
        school=session.school,
        event_name="content.released",
        classroom_session=session,
        legacy_event__metadata__action="classroom_evaluation_released",
    ).select_related("class_group", "subject", "course", "lesson")
    withdrawal_events = 0
    for release in releases:
        if LearningEventV2.objects.filter(
            school=session.school,
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
                    "reason_code": reason_code,
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=release.class_group,
                subject=release.subject,
                course=release.course,
                lesson=release.lesson,
                classroom_session=session,
                object_type=release.object_type,
                object_id=release.object_id,
                legacy_metadata={
                    "action": "classroom_evaluation_withdrawn",
                    "classroom_session": session.id,
                    "release_event_id": str(release.event_id),
                    "reason_code": reason_code,
                },
                occurred_at=occurred_at,
            )
        except EventWriteError as exc:
            raise EvaluationEventError(exc.code, exc.message) from exc
        withdrawal_events += 1
    return {"withdrawal_events": withdrawal_events}


def _active_evaluation_opportunity(*, student, object_id: str, object_version: str):
    if learning_event_write_mode() == "v1_only":
        return None
    opportunities = LearningOpportunity.objects.filter(
        student=student,
        content_type=LearningOpportunity.ContentType.TASK,
        object_id=object_id,
        object_version=object_version,
    ).order_by("-released_at", "-created_at")
    for opportunity in opportunities:
        if not opportunity.transition_facts.filter(
            state__in=LearningOpportunityTransitionFact.TERMINAL_STATES
        ).exists():
            return opportunity
    raise EvaluationEventError(
        "evaluation_opportunity_missing",
        "评价机会不存在或已经关闭，请重新开启评价后再提交。",
    )


@transaction.atomic
def _ensure_course_evaluation_opportunities(
    *, course, class_group, version, evaluation_type: str, actor, occurred_at=None
):
    if learning_event_write_mode() == "v1_only":
        return
    object_id = course_evaluation_object_id(course, class_group, evaluation_type)
    old_releases = LearningEventV2.objects.filter(
        school=actor.school,
        event_name="content.released",
        class_group=class_group,
        course=course,
        object_id=object_id,
        legacy_event__metadata__action="course_evaluation_released",
    ).exclude(object_version=version.config_hash)
    for release in old_releases.select_related("class_group", "subject", "course"):
        if LearningEventV2.objects.filter(
            school=actor.school,
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
                    "reason_code": "evaluation_revised",
                },
                legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                class_group=release.class_group,
                subject=release.subject,
                course=release.course,
                object_type=release.object_type,
                object_id=release.object_id,
                legacy_metadata={
                    "action": "course_evaluation_withdrawn",
                    "release_event_id": str(release.event_id),
                    "reason_code": "evaluation_revised",
                },
                occurred_at=occurred_at or timezone.now(),
            )
        except EventWriteError as exc:
            raise EvaluationEventError(exc.code, exc.message) from exc
    exists = LearningEventV2.objects.filter(
        school=actor.school,
        event_name="content.released",
        class_group=class_group,
        course=course,
        object_id=object_id,
        object_version=version.config_hash,
        legacy_event__metadata__action="course_evaluation_released",
    ).exists()
    if exists:
        return
    try:
        record_learning_event(
            actor=actor,
            event_name="content.released",
            payload={
                "content_type": LearningOpportunity.ContentType.TASK,
                "required": False,
                "target_layers": ["all"],
            },
            legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
            class_group=class_group,
            subject=course.subject,
            course=course,
            object_type="evaluation_standard",
            object_id=object_id,
            object_version=version.config_hash,
            legacy_metadata={
                "action": "course_evaluation_released",
                "evaluation_type": evaluation_type,
                "evaluation_version": evaluation_version_label(version),
            },
            occurred_at=occurred_at or timezone.now(),
        )
    except EventWriteError as exc:
        raise EvaluationEventError(exc.code, exc.message) from exc


@transaction.atomic
def append_evaluation_submission(
    *,
    course,
    class_group,
    evaluation_type: str,
    evaluator,
    target,
    evaluation_version: ClassroomEvaluationConfigVersion,
    ratings: dict,
    comment: str,
    session=None,
    group=None,
) -> ClassroomEvaluationSubmission:
    if evaluation_version.course_id != course.id:
        raise EvaluationEventError("evaluation_course_mismatch", "评价评价标准不属于当前课程。")
    query = ClassroomEvaluationSubmission.objects.select_for_update().filter(
        course=course,
        session=session,
        evaluation_type=evaluation_type,
        evaluator=evaluator,
        target=target,
    )
    previous = query.order_by("-submission_version", "-id").first()
    submission = ClassroomEvaluationSubmission.objects.create(
        course=course,
        class_group=class_group,
        session=session,
        evaluation_type=evaluation_type,
        evaluator=evaluator,
        target=target,
        group=group,
        evaluation_version=evaluation_version,
        submission_version=(previous.submission_version + 1 if previous else 1),
        supersedes=previous,
        ratings=ratings,
        comment=comment,
    )
    if session:
        release_classroom_evaluation_opportunities(
            session=session,
            actor=session.teacher,
            version=evaluation_version,
        )
        object_id = classroom_evaluation_object_id(session, evaluation_type)
    else:
        _ensure_course_evaluation_opportunities(
            course=course,
            class_group=class_group,
            version=evaluation_version,
            evaluation_type=evaluation_type,
            actor=course.teacher,
        )
        object_id = course_evaluation_object_id(course, class_group, evaluation_type)
    opportunity = _active_evaluation_opportunity(
        student=target,
        object_id=object_id,
        object_version=evaluation_version.config_hash,
    )
    criterion_order = {
        item["id"]: index
        for index, item in enumerate(
            _criteria_for_type(evaluation_version, evaluation_type)
        )
    }
    criterion_ratings = [
        {"criterion_id": criterion_id, "rating": int(value)}
        for criterion_id, value in sorted(
            ratings.items(), key=lambda item: criterion_order.get(str(item[0]), 1000)
        )
    ]
    try:
        record_learning_event(
            actor=evaluator,
            target_student=target,
            event_name="evaluation.rating.submitted",
            payload={
                "evaluation_version": evaluation_version_label(evaluation_version),
                "criterion_ratings": criterion_ratings,
                "rater_role": evaluation_type,
            },
            legacy_event_type=(
                LearningEvent.EventType.TEACHER_INTERVENTION
                if evaluation_type
                == ClassroomEvaluationSubmission.EvaluationType.TEACHER
                else LearningEvent.EventType.ANSWER_SUBMIT
            ),
            legacy_actor=evaluator,
            class_group=class_group,
            subject=course.subject,
            course=course,
            lesson=session.lesson if session else None,
            classroom_session=session,
            object_type="evaluation_standard",
            object_id=object_id,
            object_version=evaluation_version.config_hash,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=submission.analytics_attempt_id,
            legacy_metadata={
                "action": f"{evaluation_type}_evaluation_submit",
                "evaluation_submission": submission.id,
                "submission_version": submission.submission_version,
                "target_id": target.id,
                "group_id": group.id if group else None,
                "evaluation_version": evaluation_version_label(evaluation_version),
                "ratings": ratings,
            },
            occurred_at=timezone.now(),
            source_override=(
                "server"
                if evaluation_type == ClassroomEvaluationSubmission.EvaluationType.PEER
                else None
            ),
        )
    except EventWriteError as exc:
        raise EvaluationEventError(exc.code, exc.message) from exc
    return submission
