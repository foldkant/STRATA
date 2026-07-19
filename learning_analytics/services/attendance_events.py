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


class AttendanceEventError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_attendance_activity(activity: ClassroomActivity) -> bool:
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    return (
        metadata.get("command") == "sign_in"
        or activity.activity_type == ClassroomActivity.ActivityType.SIGN_IN
    )


def attendance_activity_version(activity: ClassroomActivity) -> str:
    source = f"attendance:v1:{activity.session_id}:{activity.id}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _release_withdrawn(release: LearningEventV2) -> bool:
    return LearningEventV2.objects.filter(
        school=release.school,
        event_name="content.withdrawn",
        payload__release_event_id=str(release.event_id),
    ).exists()


def _active_attendance_release(activity: ClassroomActivity):
    version = attendance_activity_version(activity)
    releases = LearningEventV2.objects.filter(
        school=activity.session.school,
        event_name="content.released",
        classroom_session=activity.session,
        object_type="classroom_activity",
        object_id=str(activity.id),
        object_version=version,
        legacy_event__metadata__action="attendance_content_released",
    ).order_by("-client_occurred_at", "-id")
    for release in releases:
        if not _release_withdrawn(release):
            return release
    return None


@transaction.atomic
def release_attendance_opportunities(
    *, activity: ClassroomActivity, actor, occurred_at=None
) -> dict:
    if not is_attendance_activity(activity):
        return {"release_events": 0, "opportunities_created": 0}
    if learning_event_write_mode() == "v1_only":
        return {"release_events": 0, "opportunities_created": 0}
    existing = _active_attendance_release(activity)
    if existing:
        return {
            "release_events": 0,
            "opportunities_created": existing.released_opportunities.count(),
        }
    occurred_at = occurred_at or activity.opened_at or timezone.now()
    session = activity.session
    try:
        result = record_learning_event(
            actor=actor,
            event_name="content.released",
            schema_version="1.2",
            payload={
                "content_type": "attendance",
                "required": True,
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
            object_version=attendance_activity_version(activity),
            legacy_metadata={
                "action": "attendance_content_released",
                "classroom_session": session.id,
                "activity": activity.id,
            },
            occurred_at=occurred_at,
            source_override="server",
        )
    except EventWriteError as exc:
        raise AttendanceEventError(exc.code, exc.message) from exc
    return {
        "release_events": 1,
        "opportunities_created": (
            result.analytics_event.released_opportunities.count()
            if result.analytics_event
            else 0
        ),
    }


def _active_attendance_opportunity(
    *, activity: ClassroomActivity, student
) -> LearningOpportunity | None:
    return (
        LearningOpportunity.objects.filter(
            school=activity.session.school,
            student=student,
            classroom_session=activity.session,
            content_type=LearningOpportunity.ContentType.ATTENDANCE,
            object_id=str(activity.id),
            object_version=attendance_activity_version(activity),
            release_event__object_type="classroom_activity",
        )
        .exclude(
            transition_facts__state__in=LearningOpportunityTransitionFact.TERMINAL_STATES
        )
        .order_by("-released_at", "-opportunity_id")
        .first()
    )


def _attendance_events(activity: ClassroomActivity, student):
    return LearningEvent.objects.filter(
        actor=student,
        object_type="classroom_activity",
        object_id=str(activity.id),
        metadata__action="classroom_activity_response",
        metadata__command="sign_in",
    ).order_by("occurred_at", "id")


@transaction.atomic
def record_attendance_status(
    *,
    activity: ClassroomActivity,
    student,
    recorder,
    attendance_status: str,
    recorded_by: str,
    note: str = "",
    occurred_at=None,
):
    if attendance_status not in {"signed", "late", "leave", "absent"}:
        raise AttendanceEventError("attendance_status_invalid", "签到状态不正确。")
    if recorded_by not in {"student", "teacher"}:
        raise AttendanceEventError("attendance_source_invalid", "签到记录来源不正确。")
    activity = (
        ClassroomActivity.objects.select_for_update()
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
    if not is_attendance_activity(activity):
        raise AttendanceEventError(
            "attendance_activity_invalid", "该课堂活动不是签到。"
        )
    if not activity.opened_at:
        raise AttendanceEventError(
            "attendance_not_open", "签到尚未开启，不能记录考勤状态。"
        )
    if activity.session.status != ClassroomSession.Status.RUNNING:
        raise AttendanceEventError(
            "attendance_session_closed", "课堂已结束，不能再修改签到状态。"
        )

    opportunity = None
    if learning_event_write_mode() != "v1_only":
        release_attendance_opportunities(
            activity=activity,
            actor=activity.session.teacher,
            occurred_at=activity.opened_at or timezone.now(),
        )
        opportunity = _active_attendance_opportunity(
            activity=activity,
            student=student,
        )
        if opportunity is None:
            raise AttendanceEventError(
                "attendance_opportunity_missing",
                "当前学生没有可用的签到机会。",
            )

    previous_events = list(_attendance_events(activity, student))
    previous = previous_events[-1] if previous_events else None
    previous_metadata = (
        previous.metadata if previous and isinstance(previous.metadata, dict) else {}
    )
    try:
        previous_revision = int(previous_metadata.get("attendance_revision_no") or 0)
    except (TypeError, ValueError):
        previous_revision = 0
    revision_no = max(previous_revision, len(previous_events)) + 1
    supersedes_event_id = previous_metadata.get("analytics_event_id") or None
    labels = {"signed": "已签到", "late": "迟到", "leave": "请假", "absent": "缺勤"}
    occurred_at = occurred_at or timezone.now()
    try:
        return record_learning_event(
            actor=recorder,
            target_student=student,
            event_name="attendance.recorded",
            payload={
                "attendance_status": attendance_status,
                "recorded_by": recorded_by,
                "revision_no": revision_no,
                "supersedes_event_id": supersedes_event_id,
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
                else attendance_activity_version(activity)
            ),
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            legacy_metadata={
                "action": "classroom_activity_response",
                "response_type": "sign_in",
                "command": "sign_in",
                "attendance_status": attendance_status,
                "attendance_status_label": labels[attendance_status],
                "source": recorded_by,
                "note": str(note or "")[:500],
                "activity_title": activity.title,
                "attendance_revision_no": revision_no,
                "supersedes_event_id": supersedes_event_id,
            },
            occurred_at=occurred_at,
        )
    except EventWriteError as exc:
        raise AttendanceEventError(exc.code, exc.message) from exc


@transaction.atomic
def withdraw_attendance_opportunities(
    *, session: ClassroomSession, actor, reason_code: str, occurred_at=None
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"withdrawal_events": 0}
    occurred_at = occurred_at or timezone.now()
    releases = LearningEventV2.objects.filter(
        school=session.school,
        event_name="content.released",
        classroom_session=session,
        legacy_event__metadata__action="attendance_content_released",
    ).select_related("class_group", "subject", "course", "lesson")
    withdrawal_events = 0
    for release in releases:
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
                    "action": "attendance_content_withdrawn",
                    "classroom_session": session.id,
                    "release_event_id": str(release.event_id),
                    "reason_code": reason_code,
                },
                occurred_at=occurred_at,
                source_override="server",
            )
        except EventWriteError as exc:
            raise AttendanceEventError(exc.code, exc.message) from exc
        withdrawal_events += 1
    return {"withdrawal_events": withdrawal_events}
