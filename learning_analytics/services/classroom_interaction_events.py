from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from courses.models import ClassroomActivity, ClassroomSession
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
from school.models import StudentProfile


class ClassroomInteractionEventError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _activity_command(activity: ClassroomActivity) -> str:
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    return str(metadata.get("command") or activity.activity_type)


def is_quick_answer_activity(activity: ClassroomActivity) -> bool:
    return _activity_command(activity) == "quick_answer"


def is_random_call_activity(activity: ClassroomActivity) -> bool:
    return _activity_command(activity) == "random_pick"


def interaction_activity_version(activity: ClassroomActivity) -> str:
    source = f"classroom-interaction:v1:{activity.session_id}:{activity.id}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _release_withdrawn(release: LearningEventV2) -> bool:
    return LearningEventV2.objects.filter(
        school=release.school,
        event_name="content.withdrawn",
        payload__release_event_id=str(release.event_id),
    ).exists()


def _active_quick_answer_release(activity: ClassroomActivity):
    releases = LearningEventV2.objects.filter(
        school=activity.session.school,
        event_name="content.released",
        classroom_session=activity.session,
        object_type="classroom_activity",
        object_id=str(activity.id),
        object_version=interaction_activity_version(activity),
        legacy_event__metadata__action="quick_answer_content_released",
    ).order_by("-client_occurred_at", "-id")
    for release in releases:
        if not _release_withdrawn(release):
            return release
    return None


@transaction.atomic
def release_quick_answer_opportunities(
    *, activity: ClassroomActivity, actor, occurred_at=None
) -> dict:
    if not is_quick_answer_activity(activity):
        return {"release_events": 0, "opportunities_created": 0}
    if learning_event_write_mode() == "v1_only":
        return {"release_events": 0, "opportunities_created": 0}
    existing = _active_quick_answer_release(activity)
    if existing:
        return {
            "release_events": 0,
            "opportunities_created": existing.released_opportunities.count(),
        }
    session = activity.session
    occurred_at = occurred_at or activity.opened_at or timezone.now()
    try:
        result = record_learning_event(
            actor=actor,
            event_name="content.released",
            schema_version="1.3",
            payload={
                "content_type": "interaction",
                "required": False,
                "target_layers": ["all"],
            },
            legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            object_type="classroom_activity",
            object_id=activity.id,
            object_version=interaction_activity_version(activity),
            legacy_metadata={
                "action": "quick_answer_content_released",
                "classroom_session": session.id,
                "activity": activity.id,
            },
            occurred_at=occurred_at,
            source_override="server",
        )
    except EventWriteError as exc:
        raise ClassroomInteractionEventError(exc.code, exc.message) from exc
    return {
        "release_events": 1,
        "opportunities_created": (
            result.analytics_event.released_opportunities.count()
            if result.analytics_event
            else 0
        ),
    }


def _active_quick_answer_opportunity(
    *, activity: ClassroomActivity, student
) -> LearningOpportunity | None:
    return (
        LearningOpportunity.objects.filter(
            school=activity.session.school,
            student=student,
            classroom_session=activity.session,
            content_type=LearningOpportunity.ContentType.INTERACTION,
            object_id=str(activity.id),
            object_version=interaction_activity_version(activity),
            release_event__object_type="classroom_activity",
        )
        .exclude(
            transition_facts__state__in=LearningOpportunityTransitionFact.TERMINAL_STATES
        )
        .order_by("-released_at", "-opportunity_id")
        .first()
    )


def _quick_answer_legacy_events(activity: ClassroomActivity):
    return LearningEvent.objects.filter(
        object_type="classroom_activity",
        object_id=str(activity.id),
        metadata__action="classroom_activity_response",
        metadata__command="quick_answer",
        metadata__response_type="quick_answer",
    ).order_by("occurred_at", "id")


@transaction.atomic
def record_quick_answer_response(
    *, activity: ClassroomActivity, student, content: str = "", occurred_at=None
) -> bool:
    activity = (
        ClassroomActivity.objects.select_for_update(of=("self",))
        .select_related(
            "session",
            "session__school",
            "session__class_group",
            "session__course",
            "session__course__subject",
            "session__lesson",
            "session__teacher",
        )
        .get(pk=activity.pk)
    )
    if not is_quick_answer_activity(activity):
        raise ClassroomInteractionEventError(
            "quick_answer_activity_invalid", "该课堂活动不是抢答。"
        )
    if (
        activity.session.status != ClassroomSession.Status.RUNNING
        or activity.status != ClassroomActivity.Status.OPEN
    ):
        raise ClassroomInteractionEventError(
            "quick_answer_closed", "抢答已关闭，不能继续响应。"
        )

    existing_events = _quick_answer_legacy_events(activity)
    if existing_events.filter(actor=student).exists():
        return False

    opportunity = None
    if learning_event_write_mode() != "v1_only":
        release_quick_answer_opportunities(
            activity=activity,
            actor=activity.session.teacher,
            occurred_at=activity.opened_at or timezone.now(),
        )
        opportunity = _active_quick_answer_opportunity(
            activity=activity,
            student=student,
        )
        if opportunity is None:
            raise ClassroomInteractionEventError(
                "quick_answer_opportunity_missing",
                "当前学生没有可用的抢答机会。",
            )

    responded_student_ids = set(existing_events.values_list("actor_id", flat=True))
    response_rank = len(responded_student_ids) + 1
    occurred_at = occurred_at or timezone.now()
    opened_at = activity.opened_at or occurred_at
    response_latency_ms = max(int((occurred_at - opened_at).total_seconds() * 1000), 0)
    response_latency_ms = min(response_latency_ms, 7_200_000)
    try:
        record_learning_event(
            actor=student,
            target_student=student,
            event_name="quick_answer.responded",
            payload={
                "response_rank": response_rank,
                "response_latency_ms": response_latency_ms,
            },
            legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
            legacy_actor=student,
            class_group=activity.session.class_group,
            subject=activity.session.course.subject,
            course=activity.session.course,
            lesson=activity.session.lesson,
            classroom_session=activity.session,
            object_type="classroom_activity",
            object_id=activity.id,
            object_version=(
                opportunity.object_version
                if opportunity
                else interaction_activity_version(activity)
            ),
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            legacy_metadata={
                "action": "classroom_activity_response",
                "response_type": "quick_answer",
                "command": "quick_answer",
                "quick_answer": True,
                "activity_title": activity.title,
                "content": str(content or "")[:1000],
                "response_rank": response_rank,
                "response_latency_ms": response_latency_ms,
            },
            occurred_at=occurred_at,
            source_override="server",
        )
    except EventWriteError as exc:
        raise ClassroomInteractionEventError(exc.code, exc.message) from exc
    return True


@transaction.atomic
def record_random_call_selected(
    *, activity: ClassroomActivity, actor, selection_method: str
) -> bool:
    if not is_random_call_activity(activity):
        return False
    existing = LearningEvent.objects.filter(
        object_type="classroom_activity",
        object_id=str(activity.id),
        metadata__action="random_call_selected",
    ).first()
    if existing:
        return False
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    picked = (
        metadata.get("picked_student")
        if isinstance(metadata.get("picked_student"), dict)
        else {}
    )
    try:
        student_id = int(picked.get("user_id") or 0)
    except (TypeError, ValueError):
        student_id = 0
    profile = (
        StudentProfile.objects.select_related("user")
        .filter(
            user_id=student_id,
            class_group=activity.session.class_group,
            user__is_active=True,
        )
        .first()
    )
    if profile is None:
        raise ClassroomInteractionEventError(
            "random_call_student_invalid", "被点名学生不属于当前课堂班级。"
        )
    eligible_count = StudentProfile.objects.filter(
        class_group=activity.session.class_group,
        user__is_active=True,
    ).count()
    previous = LearningEventV2.objects.filter(
        school=activity.session.school,
        event_name="random_call.selected",
        classroom_session=activity.session,
    )
    selection_sequence = previous.count() + 1
    prior_selection_count = previous.filter(target_student=profile.user).count()
    try:
        record_learning_event(
            actor=actor,
            target_student=profile.user,
            event_name="random_call.selected",
            payload={
                "selection_method": selection_method,
                "eligible_student_count": eligible_count,
                "selection_sequence": selection_sequence,
                "prior_selection_count": prior_selection_count,
            },
            legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
            legacy_actor=profile.user,
            class_group=activity.session.class_group,
            subject=activity.session.course.subject,
            course=activity.session.course,
            lesson=activity.session.lesson,
            classroom_session=activity.session,
            object_type="classroom_activity",
            object_id=activity.id,
            object_version=interaction_activity_version(activity),
            legacy_metadata={
                "action": "random_call_selected",
                "command": "random_pick",
                "activity_title": activity.title,
                "selection_method": selection_method,
                "eligible_student_count": eligible_count,
                "selection_sequence": selection_sequence,
                "prior_selection_count": prior_selection_count,
            },
            source_override="server",
        )
    except EventWriteError as exc:
        raise ClassroomInteractionEventError(exc.code, exc.message) from exc
    return True


def _quick_answer_releases(*, session: ClassroomSession, activity=None):
    releases = LearningEventV2.objects.filter(
        school=session.school,
        event_name="content.released",
        classroom_session=session,
        legacy_event__metadata__action="quick_answer_content_released",
    ).select_related("class_group", "subject", "course", "lesson")
    if activity is not None:
        releases = releases.filter(object_id=str(activity.id))
    return releases


@transaction.atomic
def withdraw_quick_answer_opportunities(
    *,
    session: ClassroomSession,
    actor,
    reason_code: str,
    activity: ClassroomActivity | None = None,
    occurred_at=None,
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"withdrawal_events": 0}
    occurred_at = occurred_at or timezone.now()
    withdrawal_events = 0
    for release in _quick_answer_releases(session=session, activity=activity):
        if _release_withdrawn(release):
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
                    "action": "quick_answer_content_withdrawn",
                    "classroom_session": session.id,
                    "activity": int(release.object_id),
                    "release_event_id": str(release.event_id),
                    "reason_code": reason_code,
                },
                occurred_at=occurred_at,
                source_override="server",
            )
        except EventWriteError as exc:
            raise ClassroomInteractionEventError(exc.code, exc.message) from exc
        withdrawal_events += 1
    return {"withdrawal_events": withdrawal_events}
