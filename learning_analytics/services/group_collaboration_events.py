from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from courses.models import (
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupFile,
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


class GroupCollaborationEventError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _assignment_version(group: ClassroomGroup, content_kind: str) -> str:
    member_ids = ",".join(
        str(student_id)
        for student_id in group.members.order_by("student_id").values_list(
            "student_id", flat=True
        )
    )
    source = (
        f"group-assignment:v1:{group.collaboration_id}:{group.id}:"
        f"{content_kind}:{member_ids}"
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _release_withdrawn(release: LearningEventV2) -> bool:
    return LearningEventV2.objects.filter(
        school=release.school,
        event_name="content.withdrawn",
        payload__release_event_id=str(release.event_id),
    ).exists()


def _active_release(group: ClassroomGroup, *, object_type: str):
    releases = LearningEventV2.objects.filter(
        school=group.collaboration.session.school,
        event_name="content.released",
        schema_version="1.1",
        classroom_session=group.collaboration.session,
        object_type=object_type,
        object_id=str(group.id),
        legacy_event__metadata__action="group_collaboration_content_released",
    ).order_by("-client_occurred_at", "-id")
    for release in releases:
        if not _release_withdrawn(release):
            return release
    return None


@transaction.atomic
def release_group_collaboration_opportunities(
    *, collaboration: ClassroomGroupCollaboration, actor, occurred_at=None
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"release_events": 0, "opportunities_created": 0}
    occurred_at = occurred_at or timezone.now()
    release_events = 0
    opportunities_created = 0
    groups = collaboration.groups.prefetch_related("members").order_by("group_no", "id")
    for group in groups:
        student_ids = list(group.members.values_list("student_id", flat=True))
        if not student_ids:
            continue
        release_rows = (
            ("classroom_group_document", "document", False),
            ("classroom_group_workspace", "task", False),
        )
        for object_type, content_type, required in release_rows:
            if _active_release(group, object_type=object_type):
                continue
            try:
                result = record_learning_event(
                    actor=actor,
                    event_name="content.released",
                    schema_version="1.1",
                    payload={
                        "content_type": content_type,
                        "required": required,
                        "target_layers": ["all"],
                        "target_student_ids": student_ids,
                    },
                    legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                    class_group=collaboration.session.class_group,
                    subject=collaboration.session.course.subject,
                    course=collaboration.session.course,
                    lesson=collaboration.session.lesson,
                    classroom_session=collaboration.session,
                    object_type=object_type,
                    object_id=group.id,
                    object_version=_assignment_version(group, object_type),
                    legacy_metadata={
                        "action": "group_collaboration_content_released",
                        "classroom_session": collaboration.session_id,
                        "collaboration": collaboration.id,
                        "group": group.id,
                        "content_type": content_type,
                    },
                    occurred_at=occurred_at,
                    source_override="server",
                )
            except EventWriteError as exc:
                raise GroupCollaborationEventError(exc.code, exc.message) from exc
            release_events += 1
            if result.analytics_event:
                opportunities_created += (
                    result.analytics_event.released_opportunities.count()
                )
    return {
        "release_events": release_events,
        "opportunities_created": opportunities_created,
    }


def _active_group_opportunity(
    *, group: ClassroomGroup, student, object_type: str, content_type: str
) -> LearningOpportunity | None:
    opportunities = (
        LearningOpportunity.objects.filter(
            school=group.collaboration.session.school,
            student=student,
            classroom_session=group.collaboration.session,
            content_type=content_type,
            object_id=str(group.id),
            release_event__object_type=object_type,
        )
        .exclude(
            transition_facts__state__in=LearningOpportunityTransitionFact.TERMINAL_STATES
        )
        .order_by("-released_at", "-opportunity_id")
    )
    return opportunities.first()


@transaction.atomic
def record_group_document_opened(
    *, group: ClassroomGroup, student, presentation: str, editor_mode: str
):
    opportunity = None
    if learning_event_write_mode() != "v1_only":
        opportunity = _active_group_opportunity(
            group=group,
            student=student,
            object_type="classroom_group_document",
            content_type=LearningOpportunity.ContentType.DOCUMENT,
        )
    if learning_event_write_mode() != "v1_only" and opportunity is None:
        raise GroupCollaborationEventError(
            "group_document_opportunity_missing",
            "当前学生没有可用的小组协作文档学习机会。",
        )
    session = group.collaboration.session
    try:
        return record_learning_event(
            actor=student,
            target_student=student,
            event_name="group.document.opened",
            payload={
                "document_version": group.document_version,
                "presentation": presentation,
                "editor_mode": editor_mode,
            },
            legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            object_type="classroom_group_document",
            object_id=group.id,
            object_version=(
                opportunity.object_version
                if opportunity
                else _assignment_version(group, "classroom_group_document")
            ),
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            legacy_metadata={
                "action": "group_document_open",
                "classroom_session": session.id,
                "collaboration": group.collaboration_id,
                "group": group.id,
                "document_version": group.document_version,
                "presentation": presentation,
                "editor_mode": editor_mode,
            },
        )
    except EventWriteError as exc:
        raise GroupCollaborationEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_group_file_shared(*, file: ClassroomGroupFile, student):
    group = file.group
    opportunity = None
    if learning_event_write_mode() != "v1_only":
        opportunity = _active_group_opportunity(
            group=group,
            student=student,
            object_type="classroom_group_workspace",
            content_type=LearningOpportunity.ContentType.TASK,
        )
    if learning_event_write_mode() != "v1_only" and opportunity is None:
        raise GroupCollaborationEventError(
            "group_workspace_opportunity_missing",
            "当前学生没有可用的小组共享区学习机会。",
        )
    session = group.collaboration.session
    try:
        return record_learning_event(
            actor=student,
            target_student=student,
            event_name="group.file.shared",
            payload={
                "artifact_version": file.public_id,
                "version_no": file.version_no,
                "file_ext": file.file_ext or "other",
                "file_size": file.file_size,
            },
            legacy_event_type=LearningEvent.EventType.TASK_SUBMIT,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            object_type="classroom_group_workspace",
            object_id=group.id,
            object_version=(
                opportunity.object_version
                if opportunity
                else _assignment_version(group, "classroom_group_workspace")
            ),
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            attempt_id=file.analytics_attempt_id,
            legacy_metadata={
                "action": "group_file_upload",
                "classroom_session": session.id,
                "collaboration": group.collaboration_id,
                "group": group.id,
                "file_public_id": str(file.public_id),
                "file_ext": file.file_ext,
                "file_size": file.file_size,
                "version_no": file.version_no,
            },
        )
    except EventWriteError as exc:
        raise GroupCollaborationEventError(exc.code, exc.message) from exc


@transaction.atomic
def record_group_document_saved(
    *, group: ClassroomGroup, version, verified_editor_ids: list[str]
):
    session = group.collaboration.session
    try:
        return record_learning_event(
            actor=session.teacher,
            event_name="group.document.saved",
            payload={
                "document_version": version.version_no,
                "file_sha256": version.file_sha256,
                "file_size": version.file_size,
                "callback_status": version.callback_status,
                "verified_editor_count": len(verified_editor_ids),
                "attribution": "group_only",
            },
            legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
            class_group=session.class_group,
            subject=session.course.subject,
            course=session.course,
            lesson=session.lesson,
            classroom_session=session,
            object_type="classroom_group_document",
            object_id=group.id,
            object_version=version.file_sha256,
            legacy_metadata={
                "action": "group_document_saved",
                "classroom_session": session.id,
                "collaboration": group.collaboration_id,
                "group": group.id,
                "document_version": version.version_no,
                "file_sha256": version.file_sha256,
                "file_size": version.file_size,
                "callback_status": version.callback_status,
                "verified_editor_count": len(verified_editor_ids),
            },
            source_override="server",
        )
    except EventWriteError as exc:
        raise GroupCollaborationEventError(exc.code, exc.message) from exc


@transaction.atomic
def withdraw_group_collaboration_opportunities(
    *,
    collaboration: ClassroomGroupCollaboration,
    actor,
    reason_code: str,
    occurred_at=None,
) -> dict:
    if learning_event_write_mode() == "v1_only":
        return {"withdrawal_events": 0}
    occurred_at = occurred_at or timezone.now()
    releases = LearningEventV2.objects.filter(
        school=collaboration.session.school,
        event_name="content.released",
        classroom_session=collaboration.session,
        legacy_event__metadata__action="group_collaboration_content_released",
        legacy_event__metadata__collaboration=collaboration.id,
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
                classroom_session=collaboration.session,
                object_type=release.object_type,
                object_id=release.object_id,
                legacy_metadata={
                    "action": "group_collaboration_content_withdrawn",
                    "classroom_session": collaboration.session_id,
                    "collaboration": collaboration.id,
                    "release_event_id": str(release.event_id),
                    "reason_code": reason_code,
                },
                occurred_at=occurred_at,
                source_override="server",
            )
        except EventWriteError as exc:
            raise GroupCollaborationEventError(exc.code, exc.message) from exc
        withdrawal_events += 1
    return {"withdrawal_events": withdrawal_events}


def group_collaboration_has_student_activity(
    collaboration: ClassroomGroupCollaboration,
) -> bool:
    if ClassroomGroupFile.objects.filter(group__collaboration=collaboration).exists():
        return True
    if collaboration.groups.filter(document_versions__version_no__gt=1).exists():
        return True
    group_ids = [
        str(item) for item in collaboration.groups.values_list("id", flat=True)
    ]
    if LearningEventV2.objects.filter(
        school=collaboration.session.school,
        classroom_session=collaboration.session,
        event_name__in={"group.document.opened", "group.file.shared"},
        object_id__in=group_ids,
    ).exists():
        return True
    return LearningEvent.objects.filter(
        class_group=collaboration.session.class_group,
        course=collaboration.session.course,
        lesson=collaboration.session.lesson,
        object_id__in=group_ids,
        metadata__action__in={"group_document_open", "group_file_upload"},
    ).exists()
