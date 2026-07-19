from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from learning_analytics.services.access_audit import audit_teacher_class_scope


class IsLearningEventClient(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and not user.is_superuser
            and user.school_id
            and user.role in {"teacher", "student"}
        )


def require_teacher_class_scope(
    request,
    class_group,
    *,
    target_type: str,
    target_id=None,
    purpose: str,
    field_categories: list[str] | None = None,
    export_requested: bool = False,
) -> None:
    if audit_teacher_class_scope(
        teacher=request.user,
        class_group=class_group,
        target_type=target_type,
        target_id=target_id,
        purpose=purpose,
        field_categories=field_categories,
        export_requested=export_requested,
    ):
        return
    raise PermissionDenied("无权查看该班级的个体学习分析信息。")
