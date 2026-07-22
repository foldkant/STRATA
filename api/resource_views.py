from __future__ import annotations

import hashlib
import json
import math
import urllib.request
import zipfile
from io import BytesIO
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login as auth_login,
    logout as auth_logout,
    update_session_auth_hash,
)
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.http import JsonResponse
from django.db.models import Count, F, Max, Prefetch, Q, Sum, TextField
from django.db.models.functions import Cast, TruncDate
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from config.onlyoffice import (
    OnlyOfficeJWTError,
    sign_editor_config,
    verify_callback_payload,
)
from aiops.models import ModelVersion, TrainingJob
from courses.models import (
    ClassroomActivity,
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupDocumentVersion,
    ClassroomGroupFile,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    LearningWebPage,
    LearningWebPageResponse,
    LearningWebPageVersion,
    Lesson,
    LessonStep,
    Resource,
    ResourceFile,
    Subject,
)
from courses.grouping import build_grouping_plan
from learning.models import (
    Feedback,
    LearningEvent,
    LessonStepAttempt,
    LessonStepAttemptAnswer,
    Notice,
    PretestPaper,
    PretestQuestion,
    PretestSubmission,
    QuestionBankItem,
    StratificationDecision,
    StudentWorkAttachment,
    TestAssessment,
    TestAttempt,
)
from learning.services.bands import resolve_student_band
from learning.services.stratification_visibility import (
    visible_published_decisions,
    visible_teacher_decisions,
)
from learning_analytics.services.classroom_events import (
    ClassroomEventError,
    classroom_question,
    classroom_question_version,
    ensure_classroom_attachment_submission,
    ensure_classroom_step_opportunities,
    next_classroom_grading_state,
    record_classroom_attachment_submission,
    record_classroom_attempt_events,
    record_classroom_document_progress,
    record_classroom_item_grade,
    record_classroom_resource_opened,
    record_classroom_video_progress,
    record_learning_page_block_viewed,
    record_learning_page_form_submission,
    record_learning_page_opened,
)
from learning_analytics.services.attendance_events import (
    AttendanceEventError,
    is_attendance_activity,
    record_attendance_status,
)
from learning_analytics.services.classroom_interaction_events import (
    ClassroomInteractionEventError,
    record_quick_answer_response,
)
from learning_analytics.services.dual_write import (
    EventWriteError,
    record_classroom_point_adjustment,
)
from learning_analytics.services.evaluation_events import (
    EvaluationEventError,
    append_evaluation_submission,
    freeze_classroom_evaluation_standard,
    release_classroom_evaluation_opportunities,
    standard_binding_criteria,
    withdraw_classroom_evaluation_opportunities,
)
from learning_analytics.models import (
    ClassroomEvaluationStandardUse,
    GroupingCandidateRun,
    LessonStepEvaluationBinding,
)
from learning_analytics.services.group_collaboration_events import (
    GroupCollaborationEventError,
    record_group_document_opened,
    record_group_document_saved,
    record_group_file_shared,
    release_group_collaboration_opportunities,
    withdraw_group_collaboration_opportunities,
)
from learning_analytics.services.grouping_plans import (
    capture_grouping_outcomes,
    confirm_grouping_candidate,
    generate_grouping_candidate_run,
    record_confirmed_plan_evidence,
)
from learning_analytics.services.operational_events import (
    record_classroom_interaction_response,
    record_intervention_acknowledged,
    record_lesson_entered,
    record_lesson_step_completed,
    record_lesson_step_entered,
    record_pretest_submitted,
    record_resource_center_opened,
)
from ops.models import AuditLog, ExportBatch, ImportBatch
from ops.xlsx import export_rows, template_response
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment
from realtime.events import publish_chat_event, session_group, teacher_group

from .permissions import IsSchoolAdmin, IsStudent, IsSuperAdmin, IsTeacher
from .protected_files import signed_protected_file_url
from .responses import fail, ok, page_data
from .view_utils import current_school as _school
from .view_utils import paginate as _paginate
from .view_utils import service_error_response as _service_fail
from .serializers import (
    account_row,
    classroom_activity_row,
    classroom_evaluation_config_row,
    classroom_evaluation_submission_row,
    classroom_group_collaboration_row,
    classroom_group_file_row,
    classroom_session_row,
    classroom_attendance_row,
    class_group_row,
    clean_resource_ext,
    course_row,
    feedback_row,
    lesson_row,
    learning_web_page_response_row,
    learning_web_page_row,
    learning_web_page_version_row,
    lesson_step_has_layered_questions,
    lesson_step_row,
    normalize_lesson_question_items,
    notice_row,
    pretest_paper_row,
    pretest_question_row,
    resource_row,
    school_row,
    student_row,
    student_classroom_row,
    student_classroom_group_collaboration_row,
    student_classroom_group_row,
    student_course_row,
    student_feedback_row,
    student_lesson_step_row,
    student_notice_row,
    student_pretest_paper_row,
    student_profile_summary,
    student_teacher_row,
    student_work_attachment_row,
    subject_row,
    teacher_ai_provider_row,
    teacher_student_profile_summary,
    teaching_assignment_row,
    teaching_teacher_row,
    user_summary,
)
from .services import (
    ServiceError,
    bulk_create_class_groups,
    bulk_delete_class_groups,
    bulk_delete_school_admin_accounts,
    bulk_delete_schools,
    bulk_delete_students,
    bulk_delete_teacher_accounts,
    bulk_disable_class_groups,
    bulk_disable_school_admin_accounts,
    bulk_disable_schools,
    bulk_disable_students,
    bulk_disable_teacher_accounts,
    bulk_save_teaching_assignments,
    archive_pretest_paper,
    create_school_admin,
    create_student,
    create_teacher,
    delete_account,
    delete_class_group,
    delete_pretest_paper,
    delete_pretest_question,
    delete_school,
    delete_student,
    delete_teaching_assignment,
    delete_subject,
    graduate_class_groups,
    import_students_from_xlsx,
    import_teachers_from_xlsx,
    get_teacher_ai_provider,
    generate_lesson_step_questions_with_ai,
    generate_learning_web_page_schema,
    publish_pretest_paper,
    promote_class_groups,
    reset_school_admin_password,
    reset_student_password,
    reset_teacher_password,
    archive_teacher_notice,
    save_class_group,
    save_teacher_ai_provider,
    save_teacher_notice,
    save_pretest_paper,
    save_pretest_question,
    save_school,
    save_subject,
    save_teaching_assignment,
    set_account_active,
    set_student_active,
    publish_teacher_notice,
    restart_classroom_session,
    reply_teacher_feedback,
    close_teacher_feedback,
    archive_teacher_course,
    archive_teacher_lesson,
    close_classroom_activity,
    close_classroom_current_step,
    delete_classroom_activity,
    delete_classroom_session,
    delete_teacher_course,
    delete_teacher_lesson,
    finish_classroom_session,
    lock_classroom_current_step,
    open_classroom_activity,
    publish_teacher_course,
    publish_teacher_lesson,
    save_classroom_activity,
    save_classroom_session,
    set_classroom_current_step,
    save_teacher_course,
    save_teacher_course_cover,
    save_teacher_lesson,
    save_lesson_step,
    save_teacher_resource,
    set_teacher_course_classes,
    delete_teacher_course_cover,
    delete_teacher_resource,
    start_classroom_session,
    test_teacher_ai_provider,
    reorder_lesson_steps,
    run_classroom_command,
    _teacher_classroom_activity,
    _teacher_classroom_session,
    _teacher_course,
    _teacher_lesson,
    _teacher_resource,
    delete_lesson_step,
    delete_teacher_notice,
    update_student,
    update_school_admin,
    update_teacher,
    write_audit,
    STUDENT_IMPORT_HEADERS,
    TEACHER_IMPORT_HEADERS,
)

# Resources domain endpoints extracted from api.views.
from .views import (
    OFFICE_FILE_TYPES,
    _office_document_type,
    _student_classroom_resource_context,
)

def _resource_file_ext(resource: Resource) -> str:
    if not resource.attachment:
        return ""
    name = resource.attachment.name.rsplit("/", 1)[-1]
    return clean_resource_ext(name, resource.attachment.url)


def _resource_rows_queryset():
    return Resource.objects.select_related(
        "owner", "owner__school", "subject", "reviewed_by"
    ).prefetch_related(
        "target_classes",
        "extra_files",
    )


def _student_resource_access_q(profile: StudentProfile) -> Q:
    local_school = Q(owner__school_id=profile.user.school_id)
    school_shared = local_school & Q(
        visibility=Resource.Visibility.SCHOOL,
        publish_status=Resource.PublishStatus.PUBLISHED,
    )
    class_shared = local_school & Q(
        visibility=Resource.Visibility.CLASSES,
        publish_status=Resource.PublishStatus.PUBLISHED,
        target_classes=profile.class_group,
    )
    external_shared = Q(
        visibility=Resource.Visibility.EXTERNAL,
        publish_status=Resource.PublishStatus.APPROVED,
    )
    return school_shared | class_shared | external_shared


def _resource_can_open(request, resource: Resource) -> bool:
    user = request.user
    if not user.is_authenticated:
        return False
    if user.role == "teacher":
        if resource.owner_id == user.id and resource.owner.school_id == user.school_id:
            return True
        if resource.visibility == Resource.Visibility.SCHOOL:
            return (
                resource.owner.school_id == user.school_id
                and resource.publish_status == Resource.PublishStatus.PUBLISHED
            )
        return (
            resource.visibility == Resource.Visibility.EXTERNAL
            and resource.publish_status == Resource.PublishStatus.APPROVED
        )
    if user.role == "student":
        try:
            profile = user.student_profile
        except StudentProfile.DoesNotExist:
            return False
        if not profile.class_group_id:
            return False
        return (
            _resource_rows_queryset()
            .filter(pk=resource.pk)
            .filter(_student_resource_access_q(profile))
            .exists()
        )
    return user.role in {"school_admin", "super_admin"} and (
        not user.school_id or resource.owner.school_id == user.school_id
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def resource_office_config(request, pk):
    resource = _resource_rows_queryset().filter(pk=pk).first()
    if resource is None or not _resource_can_open(request, resource):
        return fail("资源不存在或无权预览。", status=404)
    file_ext = _resource_file_ext(resource)
    if file_ext not in OFFICE_FILE_TYPES:
        return fail("该资源不是 Office 文档。", status=400)
    if not resource.attachment:
        return fail("该资源没有附件。", status=400)

    requested_mode = request.GET.get("mode", "view").strip().lower()
    can_edit = request.user.role == "teacher" and resource.owner_id == request.user.id
    mode = "edit" if requested_mode == "edit" and can_edit else "view"
    attachment_name = resource.attachment.name.rsplit("/", 1)[-1]
    attachment_url = request.build_absolute_uri(
        signed_protected_file_url(
            "resource-attachment",
            resource.id,
            version=resource.attachment.name,
        )
    )
    base_url = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}"
    config = {
        "document": {
            "fileType": file_ext,
            "key": f"resource-{resource.id}-{int(resource.updated_at.timestamp())}",
            "title": attachment_name or resource.title,
            "url": attachment_url,
            "permissions": {
                "edit": mode == "edit",
                "comment": can_edit,
                "download": True,
                "print": True,
            },
        },
        "documentType": _office_document_type(file_ext),
        "editorConfig": {
            "callbackUrl": f"{base_url}/api/v1/resources/{resource.id}/office-callback/",
            "lang": "zh-CN",
            "mode": mode,
            "user": {
                "id": str(request.user.id),
                "name": request.user.display_name or request.user.username,
            },
            "customization": {
                "autosave": True,
                "forcesave": True,
            },
        },
        "height": "100%",
        "width": "100%",
    }
    config = sign_editor_config(config)
    return ok(
        {
            "server_url": settings.ONLYOFFICE_DOCUMENT_SERVER_URL,
            "mode": mode,
            "can_edit": can_edit,
            "config": config,
        }
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def resource_office_callback(request, pk):
    resource = Resource.objects.filter(pk=pk).first()
    if resource is None or not resource.attachment:
        return JsonResponse({"error": 1}, status=404)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": 1})

    status = payload.get("status")
    if status in {2, 6} and payload.get("url"):
        try:
            with urllib.request.urlopen(payload["url"], timeout=30) as response:
                data = response.read()
            with resource.attachment.storage.open(
                resource.attachment.name, "wb"
            ) as target:
                target.write(data)
            resource.save(update_fields=["updated_at"])
        except Exception:
            return JsonResponse({"error": 1})
    return JsonResponse({"error": 0})


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def teacher_resources(request):
    if request.method == "POST":
        try:
            resource = save_teacher_resource(
                request,
                request.data,
                uploaded_file=request.FILES.get("attachment"),
                cover_file=request.FILES.get("cover"),
                extra_files=request.FILES.getlist("extra_files"),
            )
        except ServiceError as exc:
            return _service_fail(exc)
        resource = _resource_rows_queryset().get(pk=resource.pk)
        return ok(
            resource_row(resource, viewer=request.user), "资源已保存。", status=201
        )

    query = request.GET.get("q", "").strip()
    scope = request.GET.get("scope", "mine").strip()
    resources = _resource_rows_queryset()
    if scope == "school":
        resources = resources.filter(
            owner__school=_school(request),
            visibility=Resource.Visibility.SCHOOL,
            publish_status=Resource.PublishStatus.PUBLISHED,
        )
    elif scope == "external":
        resources = resources.filter(
            visibility=Resource.Visibility.EXTERNAL,
            publish_status=Resource.PublishStatus.APPROVED,
        )
    elif scope == "projects":
        resources = resources.filter(
            resource_type=Resource.ResourceType.STUDENT_PROJECT
        ).filter(
            Q(owner=request.user)
            | Q(
                owner__school=_school(request),
                visibility=Resource.Visibility.SCHOOL,
                publish_status=Resource.PublishStatus.PUBLISHED,
            )
            | Q(
                visibility=Resource.Visibility.EXTERNAL,
                publish_status=Resource.PublishStatus.APPROVED,
            )
        )
    else:
        resources = resources.filter(owner=request.user, owner__school=_school(request))
    resource_type = request.GET.get("resource_type", "").strip()
    category = request.GET.get("category", "").strip()
    subject_id = request.GET.get("subject", "").strip()
    if resource_type:
        resources = resources.filter(resource_type=resource_type)
    if category:
        resources = resources.filter(category=category)
    if subject_id.isdigit():
        resources = resources.filter(subject_id=int(subject_id))
    if query:
        resources = resources.annotate(
            tags_text=Cast("tags", output_field=TextField()),
            project_members_text=Cast("project_members", output_field=TextField()),
        ).filter(
            Q(title__icontains=query)
            | Q(content__icontains=query)
            | Q(attachment__icontains=query)
            | Q(tags_text__icontains=query)
            | Q(project_members_text__icontains=query)
        )
    resources = resources.distinct().order_by("-is_pinned", "-updated_at")
    page = _paginate(request, resources)
    page.object_list = [
        resource_row(resource, viewer=request.user) for resource in page.object_list
    ]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def teacher_resource_detail(request, pk):
    try:
        resource = _teacher_resource(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "GET":
        resource = _resource_rows_queryset().get(pk=resource.pk)
        return ok(resource_row(resource, viewer=request.user))
    if request.method == "PATCH":
        try:
            resource = save_teacher_resource(
                request,
                request.data,
                resource=resource,
                uploaded_file=request.FILES.get("attachment"),
                cover_file=request.FILES.get("cover"),
                extra_files=request.FILES.getlist("extra_files"),
            )
        except ServiceError as exc:
            return _service_fail(exc)
        resource = _resource_rows_queryset().get(pk=resource.pk)
        return ok(resource_row(resource, viewer=request.user), "资源已更新。")

    try:
        delete_teacher_resource(request, resource)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "资源已删除。")


@api_view(["DELETE"])
@permission_classes([IsTeacher])
def teacher_resource_extra_file(request, pk, file_id):
    try:
        resource = _teacher_resource(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    extra_file = ResourceFile.objects.filter(pk=file_id, resource=resource).first()
    if extra_file is None:
        return fail("附件不存在或无权操作。", status=404)
    if extra_file.file:
        extra_file.file.delete(save=False)
    extra_file.delete()
    write_audit(
        request,
        "resource.extra_file.delete",
        school=request.user.school,
        target_type="resource",
        target_id=resource.id,
        detail={"file_id": file_id},
    )
    return ok({}, "附件已删除。")


@api_view(["GET", "PATCH"])
@permission_classes([IsSchoolAdmin])
def school_admin_resource_reviews(request, pk=None):
    resources = _resource_rows_queryset().filter(
        owner__school=_school(request),
        visibility=Resource.Visibility.EXTERNAL,
    )
    if request.method == "GET":
        status_filter = request.GET.get("status", "").strip()
        if status_filter:
            resources = resources.filter(publish_status=status_filter)
        query = request.GET.get("q", "").strip()
        if query:
            resources = resources.filter(
                Q(title__icontains=query) | Q(owner__display_name__icontains=query)
            )
        page = _paginate(request, resources.order_by("publish_status", "-updated_at"))
        page.object_list = [
            resource_row(resource, viewer=request.user) for resource in page.object_list
        ]
        return ok(page_data(page))

    resource = resources.filter(pk=pk).first()
    if resource is None:
        return fail("资源不存在或无权审核。", status=404)
    action = str(request.data.get("action", "")).strip()
    note = str(request.data.get("note", "")).strip()
    if action not in {"approve", "reject"}:
        return fail(
            "审核操作不正确。", errors={"action": ["请选择通过或退回。"]}, status=400
        )
    if action == "reject" and not note:
        return fail(
            "退回时需要填写原因。", errors={"note": ["请填写退回原因。"]}, status=400
        )
    resource.publish_status = (
        Resource.PublishStatus.APPROVED
        if action == "approve"
        else Resource.PublishStatus.REJECTED
    )
    resource.review_note = note
    resource.reviewed_by = request.user
    resource.reviewed_at = timezone.now()
    resource.published_at = timezone.now() if action == "approve" else None
    resource.save(
        update_fields=[
            "publish_status",
            "review_note",
            "reviewed_by",
            "reviewed_at",
            "published_at",
            "updated_at",
        ]
    )
    write_audit(
        request,
        f"resource.review.{action}",
        school=request.user.school,
        target_type="resource",
        target_id=resource.id,
        detail={"title": resource.title, "note": note},
    )
    reviewed = _resource_rows_queryset().get(pk=resource.pk)
    return ok(resource_row(reviewed, viewer=request.user), "资源审核结果已保存。")


@api_view(["GET"])
@permission_classes([IsStudent])
def student_resources(request):
    try:
        profile = request.user.student_profile
    except StudentProfile.DoesNotExist:
        return fail("学生档案不存在。", status=404)
    if not profile.class_group_id:
        return ok(page_data(_paginate(request, Resource.objects.none())))

    resources = _resource_rows_queryset().filter(_student_resource_access_q(profile))
    query = request.GET.get("q", "").strip()
    scope = request.GET.get("scope", "all").strip()
    if scope == "projects":
        resources = resources.filter(
            resource_type=Resource.ResourceType.STUDENT_PROJECT
        )
    elif scope == "external":
        resources = resources.filter(visibility=Resource.Visibility.EXTERNAL)
    elif scope == "school":
        resources = resources.filter(owner__school=request.user.school).exclude(
            visibility=Resource.Visibility.EXTERNAL
        )
    subject_id = request.GET.get("subject", "").strip()
    if subject_id.isdigit():
        resources = resources.filter(subject_id=int(subject_id))
    if query:
        resources = resources.annotate(
            tags_text=Cast("tags", output_field=TextField()),
            project_members_text=Cast("project_members", output_field=TextField()),
        ).filter(
            Q(title__icontains=query)
            | Q(content__icontains=query)
            | Q(tags_text__icontains=query)
            | Q(project_members_text__icontains=query)
        )
    page = _paginate(
        request,
        resources.distinct().order_by("-is_pinned", "-published_at", "-updated_at"),
    )
    page.object_list = [
        resource_row(resource, viewer=request.user) for resource in page.object_list
    ]
    return ok(page_data(page))


@api_view(["GET", "POST"])
@permission_classes([IsStudent])
def student_resource_detail(request, pk):
    try:
        profile = request.user.student_profile
    except StudentProfile.DoesNotExist:
        return fail("学生档案不存在。", status=404)
    resource = (
        _resource_rows_queryset()
        .filter(pk=pk)
        .filter(_student_resource_access_q(profile))
        .distinct()
        .first()
    )
    if resource is None:
        return fail("资源不存在或暂未向你开放。", status=404)
    if request.method == "POST":
        try:
            with transaction.atomic():
                Resource.objects.filter(pk=resource.pk).update(
                    view_count=F("view_count") + 1
                )
                record_resource_center_opened(
                    resource=resource,
                    student=request.user,
                    profile=profile,
                )
        except EventWriteError as exc:
            return fail(exc.message, status=500)
        resource.view_count += 1
    return ok(resource_row(resource, viewer=request.user))


@api_view(["POST"])
@permission_classes([IsStudent])
def student_classroom_resource_opened(request, pk, resource_id):
    try:
        _profile, session, step = _student_classroom_resource_context(request, pk)
        record_classroom_resource_opened(
            session=session,
            step=step,
            resource_id=resource_id,
            student=request.user,
            presentation=str(request.data.get("presentation") or "embedded"),
        )
    except ServiceError as exc:
        return _service_fail(exc)
    except ClassroomEventError as exc:
        status = 404 if exc.code == "classroom_resource_missing" else 400
        return fail(exc.message, status=status)
    return ok({}, "资源打开行为已记录。", status=201)
