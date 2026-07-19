from __future__ import annotations

from learning_analytics.models import SensitiveInferenceAccessLog
from school.models import TeachingAssignment


def teacher_has_class_scope(*, teacher, class_group) -> bool:
    if not teacher or not getattr(teacher, "is_authenticated", False):
        return False
    if (
        teacher.role != "teacher"
        or teacher.is_superuser
        or teacher.school_id != class_group.school_id
    ):
        return False
    return TeachingAssignment.objects.filter(
        school_id=class_group.school_id,
        class_group=class_group,
        teacher=teacher,
    ).exists()


def record_sensitive_inference_access(
    *,
    actor,
    school,
    class_group=None,
    target_type: str,
    target_id: str | int | None = None,
    purpose: str,
    field_categories: list[str] | None = None,
    export_requested: bool = False,
    access_granted: bool,
    denial_reason: str = "",
) -> SensitiveInferenceAccessLog:
    return SensitiveInferenceAccessLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        actor_role=str(getattr(actor, "role", "") or "")[:20],
        school=school,
        class_group=class_group,
        target_type=target_type[:64],
        target_id=str(target_id or "")[:64],
        purpose=purpose[:128],
        field_categories=list(field_categories or []),
        export_requested=export_requested,
        access_granted=access_granted,
        denial_reason=denial_reason[:255],
    )


def audit_teacher_class_scope(
    *,
    teacher,
    class_group,
    target_type: str,
    target_id: str | int | None = None,
    purpose: str,
    field_categories: list[str] | None = None,
    export_requested: bool = False,
) -> bool:
    allowed = teacher_has_class_scope(teacher=teacher, class_group=class_group)
    record_sensitive_inference_access(
        actor=teacher,
        school=class_group.school,
        class_group=class_group,
        target_type=target_type,
        target_id=target_id,
        purpose=purpose,
        field_categories=field_categories,
        export_requested=export_requested,
        access_granted=allowed,
        denial_reason="" if allowed else "教师不在该班级有效任课范围内。",
    )
    return allowed
