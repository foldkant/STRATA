from __future__ import annotations

from typing import Any

from courses.models import ClassroomSession
from school.models import StudentProfile


def lesson_step_references_resource(
    resource_items: Any,
    resource_id: int,
) -> bool:
    """Return whether a lesson-step resource snapshot references a resource."""

    try:
        expected_id = int(resource_id)
    except (TypeError, ValueError):
        return False
    if not isinstance(resource_items, list):
        return False
    for item in resource_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "resource") != "resource":
            continue
        try:
            item_id = int(item.get("resource_id") or item.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if item_id == expected_id:
            return True
    return False


def student_has_active_classroom_resource_access(
    profile: StudentProfile,
    resource_id: int,
) -> bool:
    """Grant read-only access to resources deployed in the active lesson step."""

    if not profile.class_group_id or not profile.user.school_id:
        return False
    resource_snapshots = (
        ClassroomSession.objects.filter(
            school_id=profile.user.school_id,
            class_group_id=profile.class_group_id,
            status=ClassroomSession.Status.RUNNING,
            current_step__isnull=False,
            current_step_status__in=(
                ClassroomSession.StepStatus.OPEN,
                ClassroomSession.StepStatus.LOCKED,
            ),
        )
        .values_list("current_step__resource_items", flat=True)
        .iterator()
    )
    return any(
        lesson_step_references_resource(items, resource_id)
        for items in resource_snapshots
    )
