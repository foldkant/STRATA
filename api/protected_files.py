from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from django.core import signing
from django.db.models import Q
from django.http import FileResponse, Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from courses.models import (
    ClassroomGroup,
    ClassroomGroupFile,
    Course,
    CourseClass,
    Resource,
    ResourceFile,
)
from learning.models import PretestMaterialAttachment, StudentWorkAttachment
from school.models import StudentProfile, TeachingAssignment
from .resource_access import student_has_active_classroom_resource_access

FILE_TOKEN_SALT = "strata.protected-file.v1"
FILE_TOKEN_MAX_AGE = 60 * 60

FILE_PATHS = {
    "course-cover": "courses/{object_id}/cover/",
    "resource-attachment": "resources/{object_id}/attachment/",
    "resource-cover": "resources/{object_id}/cover/",
    "resource-extra": "resource-files/{object_id}/",
    "student-work": "student-work/{object_id}/",
    "group-file": "classroom-group-files/{object_id}/",
    "group-document": "classroom-groups/{object_id}/document/",
}


def protected_file_url(kind: str, object_id: int, *, token: str = "") -> str:
    try:
        suffix = FILE_PATHS[kind].format(object_id=int(object_id))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Unknown protected file kind: {kind}") from exc
    path = f"/api/v1/files/{suffix}"
    return f"{path}?{urlencode({'access_token': token})}" if token else path


def signed_protected_file_url(
    kind: str, object_id: int, *, version: str = ""
) -> str:
    token = signing.dumps(
        {"kind": kind, "object_id": int(object_id), "version": str(version)},
        salt=FILE_TOKEN_SALT,
        compress=True,
    )
    return protected_file_url(kind, object_id, token=token)


def _token_matches(request, *, kind: str, object_id: int, version: str = "") -> bool:
    token = str(request.GET.get("access_token") or "").strip()
    if not token:
        return False
    try:
        payload = signing.loads(token, salt=FILE_TOKEN_SALT, max_age=FILE_TOKEN_MAX_AGE)
        token_object_id = int(payload.get("object_id"))
    except (signing.BadSignature, TypeError, ValueError):
        return False
    return (
        payload.get("kind") == kind
        and token_object_id == int(object_id)
        and str(payload.get("version", "")) == str(version)
    )


def _is_school_admin(user, school_id: int) -> bool:
    return bool(
        user.is_authenticated
        and user.role == "school_admin"
        and not user.is_superuser
        and user.school_id == school_id
    )


def _is_super_admin(user) -> bool:
    return bool(
        user.is_authenticated
        and (user.is_superuser or user.role == "super_admin")
    )


def _student_profile(user):
    if not user.is_authenticated or user.role != "student":
        return None
    return StudentProfile.objects.filter(user=user).select_related("class_group").first()


def _course_access(user, course: Course) -> bool:
    if _is_super_admin(user) or _is_school_admin(user, course.teacher.school_id):
        return True
    if user.is_authenticated and user.role == "teacher":
        return course.teacher_id == user.id and course.teacher.school_id == user.school_id
    profile = _student_profile(user)
    return bool(
        profile
        and profile.class_group_id
        and Course.objects.filter(
            pk=course.pk,
            is_active=True,
            course_classes__class_group_id=profile.class_group_id,
        ).exists()
    )


def _resource_access(user, resource: Resource) -> bool:
    if _is_super_admin(user) or _is_school_admin(user, resource.owner.school_id):
        return True
    if user.is_authenticated and user.role == "teacher":
        if resource.owner_id == user.id and resource.owner.school_id == user.school_id:
            return True
        if resource.owner.school_id != user.school_id:
            return False
        if resource.visibility == Resource.Visibility.SCHOOL:
            return resource.publish_status == Resource.PublishStatus.PUBLISHED
        return (
            resource.visibility == Resource.Visibility.EXTERNAL
            and resource.publish_status == Resource.PublishStatus.APPROVED
        )
    profile = _student_profile(user)
    if not profile or not profile.class_group_id:
        return False
    if student_has_active_classroom_resource_access(profile, resource.id):
        return True
    local_school = Q(owner__school_id=profile.user.school_id)
    allowed = (
        (local_school & Q(
            visibility=Resource.Visibility.SCHOOL,
            publish_status=Resource.PublishStatus.PUBLISHED,
        ))
        | (local_school & Q(
            visibility=Resource.Visibility.CLASSES,
            publish_status=Resource.PublishStatus.PUBLISHED,
            target_classes=profile.class_group_id,
        ))
        | Q(
            visibility=Resource.Visibility.EXTERNAL,
            publish_status=Resource.PublishStatus.APPROVED,
        )
    )
    return Resource.objects.filter(pk=resource.pk).filter(allowed).exists()


def _group_access(user, group: ClassroomGroup) -> bool:
    session = group.collaboration.session
    if _is_super_admin(user) or _is_school_admin(user, session.school_id):
        return True
    if user.is_authenticated and user.role == "teacher":
        return session.teacher_id == user.id
    return group.members.filter(student_id=getattr(user, "id", None)).exists()


def _student_work_access(user, work: StudentWorkAttachment) -> bool:
    if _is_super_admin(user) or _is_school_admin(user, work.school_id):
        return True
    if not user.is_authenticated:
        return False
    if user.role == "student":
        return work.student_id == user.id
    return user.role == "teacher" and work.course.teacher_id == user.id


def _pretest_material_access(user, attachment: PretestMaterialAttachment) -> bool:
    material = attachment.material
    if _is_super_admin(user) or _is_school_admin(user, material.school_id):
        return True
    if not user.is_authenticated:
        return False
    if user.role == "student":
        return attachment.student_id == user.id
    if user.role != "teacher" or user.school_id != material.school_id:
        return False
    if not material.course_id or not material.class_group_id:
        return False
    if material.course.teacher_id != user.id:
        return False
    return (
        CourseClass.objects.filter(
            course_id=material.course_id,
            class_group_id=material.class_group_id,
        ).exists()
        and TeachingAssignment.objects.filter(
            school_id=material.school_id,
            class_group_id=material.class_group_id,
            teacher=user,
        ).exists()
    )


def _file_response(field, *, display_name: str, as_attachment: bool):
    if not field:
        raise Http404
    try:
        handle = field.storage.open(field.name, "rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response = FileResponse(
        handle,
        as_attachment=as_attachment,
        filename=Path(display_name or field.name).name,
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def course_cover(request, pk):
    course = Course.objects.select_related("teacher").filter(pk=pk).first()
    if course is None or not _course_access(request.user, course):
        raise Http404
    return _file_response(
        course.cover,
        display_name=(
            f"course-{course.id}-cover{Path(course.cover.name).suffix}"
            if course.cover
            else "course-cover"
        ),
        as_attachment=False,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def resource_attachment(request, pk):
    resource = Resource.objects.select_related("owner").filter(pk=pk).first()
    if resource is None:
        raise Http404
    version = resource.attachment.name if resource.attachment else ""
    signed_access = _token_matches(
        request, kind="resource-attachment", object_id=resource.id, version=version
    )
    if not signed_access and not _resource_access(request.user, resource):
        raise Http404
    display_name = resource.attachment.name if resource.attachment else resource.title
    if request.user.is_authenticated and request.user.role == "student":
        display_name = f"resource-{resource.id}{Path(version).suffix}"
    return _file_response(
        resource.attachment,
        display_name=display_name,
        as_attachment=True,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def resource_cover(request, pk):
    resource = Resource.objects.select_related("owner").filter(pk=pk).first()
    if resource is None or not _resource_access(request.user, resource):
        raise Http404
    return _file_response(
        resource.cover,
        display_name=(
            f"resource-{resource.id}-cover{Path(resource.cover.name).suffix}"
            if resource.cover
            else "resource-cover"
        ),
        as_attachment=False,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def resource_extra_file(request, pk):
    file = ResourceFile.objects.select_related("resource__owner").filter(pk=pk).first()
    if file is None or not _resource_access(request.user, file.resource):
        raise Http404
    display_name = file.original_name
    if request.user.is_authenticated and request.user.role == "student":
        display_name = f"resource-{file.resource_id}-file-{file.id}{Path(file.file.name).suffix}"
    return _file_response(file.file, display_name=display_name, as_attachment=True)


@api_view(["GET"])
@permission_classes([AllowAny])
def student_work_file(request, pk):
    work = (
        StudentWorkAttachment.objects.select_related("student", "course__teacher")
        .filter(pk=pk)
        .first()
    )
    if work is None or not _student_work_access(request.user, work):
        raise Http404
    return _file_response(work.attachment, display_name=work.original_name, as_attachment=True)


@api_view(["GET"])
@permission_classes([AllowAny])
def pretest_material_file(request, attachment_id):
    attachment = (
        PretestMaterialAttachment.objects.select_related(
            "student",
            "material",
            "material__subject",
            "material__class_group",
            "material__course",
        )
        .filter(attachment_id=attachment_id)
        .first()
    )
    if attachment is None or not _pretest_material_access(request.user, attachment):
        raise Http404
    return _file_response(
        attachment.attachment,
        display_name=attachment.original_name,
        as_attachment=True,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def classroom_group_file(request, pk):
    file = (
        ClassroomGroupFile.objects.select_related(
            "group__collaboration__session", "group__collaboration__session__school"
        )
        .filter(pk=pk)
        .first()
    )
    if file is None or not _group_access(request.user, file.group):
        raise Http404
    display_name = file.original_name
    if request.user.is_authenticated and request.user.role == "student":
        display_name = f"group-{file.group_id}-file-{file.id}{Path(file.attachment.name).suffix}"
    return _file_response(file.attachment, display_name=display_name, as_attachment=True)


@api_view(["GET"])
@permission_classes([AllowAny])
def classroom_group_document(request, pk):
    group = (
        ClassroomGroup.objects.select_related("collaboration__session")
        .filter(pk=pk)
        .first()
    )
    if group is None:
        raise Http404
    version = f"{group.document_version}:{group.collaboration_document.name}"
    signed_access = _token_matches(
        request, kind="group-document", object_id=group.id, version=version
    )
    if not signed_access and not _group_access(request.user, group):
        raise Http404
    display_name = group.document_original_name or f"第{group.group_no}组.{group.document_file_ext or group.collaboration.document_type}"
    return _file_response(
        group.collaboration_document,
        display_name=display_name,
        as_attachment=False,
    )
