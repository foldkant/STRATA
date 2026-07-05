from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and (user.is_superuser or user.role == "super_admin"))


class IsSchoolAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role == "school_admin"
            and not user.is_superuser
            and user.school_id
        )


class IsTeacher(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role == "teacher"
            and not user.is_superuser
            and user.school_id
        )


class IsStudent(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role == "student"
            and not user.is_superuser
            and user.school_id
        )
