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


def _day_series(queryset, date_field: str, days=7) -> list[dict]:
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        queryset.filter(**{f"{date_field}__date__gte": start})
        .annotate(day=TruncDate(date_field))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    by_day = {item["day"]: item["total"] for item in rows}
    return [
        {
            "label": (start + timedelta(days=offset)).strftime("%m-%d"),
            "count": by_day.get(start + timedelta(days=offset), 0),
        }
        for offset in range(days)
    ]


def _day_distinct_series(
    queryset, date_field: str, distinct_field: str, days=7
) -> list[dict]:
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        queryset.filter(**{f"{date_field}__date__gte": start})
        .annotate(day=TruncDate(date_field))
        .values("day")
        .annotate(total=Count(distinct_field, distinct=True))
        .order_by("day")
    )
    by_day = {item["day"]: item["total"] for item in rows}
    return [
        {
            "label": (start + timedelta(days=offset)).strftime("%m-%d"),
            "count": by_day.get(start + timedelta(days=offset), 0),
        }
        for offset in range(days)
    ]


def _choice_counts(queryset, field: str, choices) -> list[dict]:
    rows = queryset.values(field).annotate(count=Count("id"))
    by_value = {item[field]: item["count"] for item in rows}
    return [
        {"label": label, "value": value, "count": by_value.get(value, 0)}
        for value, label in choices
    ]


def _flag_counts(queryset, field: str, true_label: str, false_label: str) -> list[dict]:
    rows = queryset.values(field).annotate(count=Count("id"))
    by_value = {bool(item[field]): item["count"] for item in rows}
    return [
        {"label": true_label, "value": "true", "count": by_value.get(True, 0)},
        {"label": false_label, "value": "false", "count": by_value.get(False, 0)},
    ]


def _class_student_counts(classes) -> list[dict]:
    return [
        {
            "label": f"{class_group.grade} {class_group.name}".strip()
            or class_group.name,
            "count": getattr(class_group, "student_count", 0),
        }
        for class_group in classes
    ]


def _class_teacher_counts(classes) -> list[dict]:
    return [
        {
            "label": f"{class_group.grade} {class_group.name}".strip()
            or class_group.name,
            "count": getattr(class_group, "teacher_count", 0),
        }
        for class_group in classes
    ]


def _class_event_counts(classes) -> list[dict]:
    return [
        {
            "label": f"{class_group.grade} {class_group.name}".strip()
            or class_group.name,
            "count": getattr(class_group, "event_count", 0),
        }
        for class_group in classes
    ]


def _teacher_class_counts(teachers) -> list[dict]:
    return [
        {
            "label": teacher.display_name or teacher.username,
            "count": getattr(teacher, "class_count", 0),
        }
        for teacher in teachers
    ]


def _event_type_counts(queryset) -> list[dict]:
    rows = queryset.values("event_type").annotate(count=Count("id"))
    by_value = {item["event_type"]: item["count"] for item in rows}
    return [
        {"label": label, "value": value, "count": by_value.get(value, 0)}
        for value, label in LearningEvent.EventType.choices
    ]


def _school_users(request):
    User = get_user_model()
    return User.objects.filter(school=_school(request))


def _xlsx_filename(prefix: str) -> str:
    return f"{prefix}_{timezone.localtime():%Y%m%d%H%M%S}.xlsx"


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_token_view(request):
    return ok({"csrf_token": get_token(request)})


@api_view(["POST"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def login_view(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    if not username or not password:
        return fail("请输入账号和密码。", status=400)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return fail("账号或密码不正确。", status=400)
    if not user.is_active:
        return fail("账号已停用，请联系管理员。", status=403)
    auth_login(request, user)
    return ok(user_summary(user), "登录成功")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    auth_logout(request)
    return ok({}, "已退出")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    return ok(user_summary(request.user))


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def super_admin_dashboard(request):
    User = get_user_model()
    operational_schools = School.objects.filter(is_synthetic=False)
    operational_users = User.objects.filter(
        Q(school__is_synthetic=False) | Q(school__isnull=True)
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    school_scale_rows = list(
        operational_schools.annotate(
            student_count=Count("users__student_profile", distinct=True),
            class_count=Count("classes", distinct=True),
        ).order_by("-student_count", "name")[:10]
    )

    pending_imports = ImportBatch.objects.filter(
        status=ImportBatch.Status.UPLOADED
    ).count()
    failed_imports = ImportBatch.objects.filter(
        status=ImportBatch.Status.FAILED
    ).count()
    failed_training_jobs = TrainingJob.objects.filter(
        status=TrainingJob.Status.FAILED
    ).count()
    pending_decisions = visible_published_decisions(
        StratificationDecision.objects.filter(class_group__school__is_synthetic=False)
    ).filter(
        status=StratificationDecision.Status.PENDING,
        decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
    ).count()
    data = {
        "metrics": [
            {
                "label": "学校",
                "value": operational_schools.count(),
                "sub": "已登记学校",
            },
            {
                "label": "学校管理员",
                "value": operational_users.filter(role="school_admin").count(),
                "sub": "本地管理账号",
            },
            {
                "label": "教师",
                "value": operational_users.filter(role="teacher").count(),
                "sub": "教师账号",
            },
            {
                "label": "学生档案",
                "value": StudentProfile.objects.filter(
                    user__school__is_synthetic=False
                ).count(),
                "sub": "已建档学生",
            },
            {
                "label": "班级",
                "value": ClassGroup.objects.filter(school__is_synthetic=False).count(),
                "sub": "行政/教学班",
            },
            {
                "label": "行为事件",
                "value": LearningEvent.objects.filter(
                    actor__school__is_synthetic=False
                ).count(),
                "sub": "学习过程记录",
            },
        ],
        "status": {
            "pending_imports": pending_imports,
            "failed_imports": failed_imports,
            "model_versions": ModelVersion.objects.count(),
            "training_jobs_7d": TrainingJob.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=7)
            ).count(),
            "pending_decisions": pending_decisions,
        },
        "status_rows": [
            {
                "label": "待校验采集包",
                "count": pending_imports,
                "level": "warn" if pending_imports else "ok",
                "path": "/super-admin/collection?status=uploaded",
            },
            {
                "label": "采集校验失败",
                "count": failed_imports,
                "level": "failed" if failed_imports else "ok",
                "path": "/super-admin/collection?status=failed",
            },
            {
                "label": "训练失败",
                "count": failed_training_jobs,
                "level": "failed" if failed_training_jobs else "ok",
                "path": "/super-admin/health",
            },
            {
                "label": "教师待确认层级",
                "count": pending_decisions,
                "level": "warn" if pending_decisions else "ok",
                "path": "/super-admin/analysis",
            },
        ],
        "charts": {
            "school_status": _choice_counts(
                operational_schools, "status", School.Status.choices
            ),
            "import_status": _choice_counts(
                ImportBatch.objects.all(), "status", ImportBatch.Status.choices
            ),
            "account_roles": _choice_counts(
                operational_users, "role", User.Role.choices
            ),
            "learning_events_7d": _day_series(
                LearningEvent.objects.filter(actor__school__is_synthetic=False),
                "occurred_at",
                days=7,
            ),
            "training_jobs_7d": _day_series(
                TrainingJob.objects.filter(
                    created_at__gte=timezone.now() - timedelta(days=7)
                ),
                "created_at",
                days=7,
            ),
            "school_students": [
                {"label": school.name, "count": getattr(school, "student_count", 0)}
                for school in school_scale_rows
            ],
            "school_classes": [
                {"label": school.name, "count": getattr(school, "class_count", 0)}
                for school in school_scale_rows
            ],
        },
        "recent_imports": [
            {
                "id": item.id,
                "batch_code": item.batch_code,
                "source_school_code": item.source_school_code,
                "source_system_version": item.source_system_version,
                "status": item.status,
                "status_label": item.get_status_display(),
                "uploaded_at": item.uploaded_at,
            }
            for item in ImportBatch.objects.select_related(
                "source_school", "uploaded_by"
            )[:6]
        ],
        "recent_logs": [
            {
                "id": log.id,
                "action": log.action,
                "actor": str(log.actor) if log.actor_id else "",
                "created_at": log.created_at,
            }
            for log in AuditLog.objects.select_related("actor", "school")[:8]
        ],
    }
    return ok(data)


@api_view(["GET", "POST"])
@permission_classes([IsSuperAdmin])
def super_admin_schools(request):
    if request.method == "POST":
        try:
            school = save_school(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(school_row(school), "学校已创建", status=201)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    schools = (
        School.objects.filter(is_synthetic=False)
        .annotate(
            class_count=Count("classes", distinct=True),
            user_count=Count("users", distinct=True),
        )
        .order_by("name", "code")
    )
    if query:
        schools = schools.filter(
            Q(name__icontains=query)
            | Q(code__icontains=query)
            | Q(contact_name__icontains=query)
        )
    if status:
        schools = schools.filter(status=status)
    page = _paginate(request, schools)
    page.object_list = [school_row(school) for school in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSuperAdmin])
def super_admin_school_detail(request, pk):
    school = (
        School.objects.filter(is_synthetic=False)
        .annotate(
            class_count=Count("classes", distinct=True),
            user_count=Count("users", distinct=True),
        )
        .filter(pk=pk)
        .first()
    )
    if school is None:
        return fail("学校不存在。", status=404)

    if request.method == "GET":
        return ok(school_row(school))
    if request.method == "PATCH":
        try:
            school = save_school(request, request.data, school=school)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(school_row(school), "学校信息已更新")

    try:
        delete_school(request, school)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "学校已删除")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_schools_bulk_disable(request):
    try:
        result = bulk_disable_schools(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, f"已停用 {result['updated_count']} 个学校。")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_schools_bulk_delete(request):
    try:
        result = bulk_delete_schools(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, result["message"])


@api_view(["GET", "POST"])
@permission_classes([IsSuperAdmin])
def super_admin_school_admins(request):
    User = get_user_model()
    if request.method == "POST":
        try:
            user = create_school_admin(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(account_row(user), "学校管理员已创建", status=201)

    query = request.GET.get("q", "").strip()
    school_id = request.GET.get("school", "").strip()
    status = request.GET.get("status", "").strip()
    users = (
        User.objects.filter(role="school_admin", school__is_synthetic=False)
        .select_related("school")
        .order_by("school__name", "username")
    )
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(display_name__icontains=query)
            | Q(phone__icontains=query)
        )
    if school_id:
        users = users.filter(school_id=school_id)
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "disabled":
        users = users.filter(is_active=False)
    page = _paginate(request, users)
    page.object_list = [account_row(user) for user in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSuperAdmin])
def super_admin_school_admin_detail(request, pk):
    User = get_user_model()
    user = (
        User.objects.filter(pk=pk, role="school_admin").select_related("school").first()
    )
    if user is None:
        return fail("学校管理员不存在。", status=404)

    if request.method == "GET":
        return ok(account_row(user))
    if request.method == "PATCH":
        try:
            user = update_school_admin(request, user, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(account_row(user), "学校管理员已更新")

    try:
        delete_account(request, user, action_prefix="school_admin")
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "学校管理员已删除")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_school_admins_bulk_disable(request):
    try:
        result = bulk_disable_school_admin_accounts(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, f"已停用 {result['updated_count']} 个学校管理员账号。")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_school_admins_bulk_delete(request):
    try:
        result = bulk_delete_school_admin_accounts(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, result["message"])


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_school_admin_set_active(request, pk):
    User = get_user_model()
    user = (
        User.objects.filter(pk=pk, role="school_admin").select_related("school").first()
    )
    if user is None:
        return fail("学校管理员不存在。", status=404)
    is_active = bool(request.data.get("is_active"))
    set_account_active(request, user, is_active, action_prefix="school_admin")
    return ok(account_row(user), "账号状态已更新")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_school_admin_reset_password(request, pk):
    User = get_user_model()
    user = (
        User.objects.filter(pk=pk, role="school_admin").select_related("school").first()
    )
    if user is None:
        return fail("学校管理员不存在。", status=404)
    try:
        reset_school_admin_password(
            request, user, str(request.data.get("password", ""))
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(account_row(user), "密码已重置")


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_dashboard(request):
    school = _school(request)
    users = _school_users(request)
    classes = ClassGroup.objects.filter(school=school)
    students = StudentProfile.objects.filter(user__school=school)
    events = LearningEvent.objects.filter(class_group__school=school)
    training_jobs = TrainingJob.objects.filter(class_group__school=school)
    decisions = visible_published_decisions(
        StratificationDecision.objects.filter(class_group__school=school)
    )
    today = timezone.localdate()
    first_login_accounts = users.filter(is_first_login=True, is_active=True).count()
    pending_onboarding = StudentProfile.objects.filter(
        user__school=school, is_first_use=True, user__is_active=True
    ).count()
    pending_pretest = (
        StudentProfile.objects.filter(user__school=school, user__is_active=True)
        .exclude(
            onboarding_status__in=[
                StudentProfile.OnboardingStatus.PRETEST_COMPLETED,
                StudentProfile.OnboardingStatus.ACTIVE,
            ]
        )
        .count()
    )
    students_without_class = students.filter(
        user__is_active=True, class_group__isnull=True
    ).count()
    pending_resource_reviews = Resource.objects.filter(
        owner__school=school,
        visibility=Resource.Visibility.EXTERNAL,
        publish_status=Resource.PublishStatus.PENDING,
    ).count()
    pending_question_reviews = QuestionBankItem.objects.filter(
        school=school,
        library_scope=QuestionBankItem.LibraryScope.SCHOOL,
        status=QuestionBankItem.Status.PENDING_REVIEW,
    ).count()
    failed_training = training_jobs.filter(status=TrainingJob.Status.FAILED).count()
    pending_decisions = decisions.filter(
        status=StratificationDecision.Status.PENDING,
        decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
    ).count()
    failed_exports = ExportBatch.objects.filter(
        school=school, status=ExportBatch.Status.FAILED
    ).count()
    class_rows = list(
        classes.annotate(
            student_count=Count("students", distinct=True),
            teacher_count=Count("teachers", distinct=True),
        ).order_by("grade", "name")[:12]
    )
    teacher_rows = list(
        users.filter(role="teacher")
        .annotate(class_count=Count("teaching_assignments__class_group", distinct=True))
        .order_by("-class_count", "display_name", "username")[:12]
    )
    last_7d_events = events.filter(occurred_at__gte=timezone.now() - timedelta(days=7))
    active_students = students.filter(user__is_active=True)
    active_student_count_7d = last_7d_events.filter(actor__role="student").values(
        "actor_id"
    ).distinct().count()
    class_activity_rows = list(
        classes.annotate(
            event_count=Count(
                "learningevent",
                filter=Q(
                    learningevent__occurred_at__gte=timezone.now() - timedelta(days=7)
                ),
                distinct=True,
            )
        ).order_by("-event_count", "grade", "name")[:12]
    )

    data = {
        "school": {"id": school.id, "name": school.name, "code": school.code},
        "metrics": [
            {
                "label": "教师",
                "value": users.filter(role="teacher").count(),
                "sub": "本校教师",
            },
            {"label": "学生", "value": students.count(), "sub": "已建档学生"},
            {"label": "班级", "value": classes.count(), "sub": "本校班级"},
            {
                "label": "课程",
                "value": Course.objects.filter(teacher__school=school).count(),
                "sub": "本校教师课程",
            },
            {
                "label": "今日行为",
                "value": events.filter(occurred_at__date=today).count(),
                "sub": "学习过程事件",
            },
            {
                "label": "近 7 天活跃学生",
                "value": active_student_count_7d,
                "sub": "产生过学习行为",
            },
        ],
        "login_series": _day_series(
            events.filter(event_type=LearningEvent.EventType.LOGIN),
            "occurred_at",
            days=7,
        ),
        "event_series": _day_series(events, "occurred_at", days=7),
        "charts": {
            "account_roles": _choice_counts(
                users, "role", [("teacher", "教师"), ("student", "学生")]
            ),
            "account_status": _flag_counts(users, "is_active", "启用", "停用"),
            "student_onboarding": _choice_counts(
                students, "onboarding_status", StudentProfile.OnboardingStatus.choices
            ),
            "student_class_status": [
                {
                    "label": "已分班",
                    "value": "assigned",
                    "count": active_students.filter(class_group__isnull=False).count(),
                },
                {
                    "label": "未分班",
                    "value": "unassigned",
                    "count": active_students.filter(class_group__isnull=True).count(),
                },
            ],
            "student_layers": [
                {
                    "label": label,
                    "value": value,
                    "count": students.filter(current_layer=value).count(),
                }
                for value, label in StudentProfile.Layer.choices
            ]
            + [
                {
                    "label": "未分层",
                    "value": "unassigned",
                    "count": students.filter(current_layer__isnull=True).count(),
                }
            ],
            "class_status": _choice_counts(
                classes, "status", ClassGroup.Status.choices
            ),
            "class_students": _class_student_counts(class_rows),
            "class_teachers": _class_teacher_counts(class_rows),
            "teacher_load": _teacher_class_counts(teacher_rows),
            "class_activity": _class_event_counts(class_activity_rows),
            "event_types": _event_type_counts(last_7d_events),
            "pretest_status": _choice_counts(
                PretestPaper.objects.filter(school=school),
                "status",
                PretestPaper.Status.choices,
            ),
            "pretest_completion": [
                {
                    "label": "已完成首次前测",
                    "value": "completed",
                    "count": active_students.filter(
                        onboarding_status__in=[
                            StudentProfile.OnboardingStatus.PRETEST_COMPLETED,
                            StudentProfile.OnboardingStatus.ACTIVE,
                        ]
                    ).count(),
                },
                {
                    "label": "尚未完成",
                    "value": "pending",
                    "count": pending_pretest,
                },
            ],
            "training_status": _choice_counts(
                training_jobs, "status", TrainingJob.Status.choices
            ),
            "login_series": _day_series(
                events.filter(event_type=LearningEvent.EventType.LOGIN),
                "occurred_at",
                days=7,
            ),
            "event_series": _day_series(events, "occurred_at", days=7),
            "active_students_7d": _day_distinct_series(
                last_7d_events.filter(actor__role="student"),
                "occurred_at",
                "actor",
                days=7,
            ),
        },
        "recent_classes": [
            {
                "id": class_group.id,
                "name": class_group.name,
                "grade": class_group.grade,
                "student_count": getattr(class_group, "student_count", 0),
                "teacher_count": getattr(class_group, "teacher_count", 0),
                "status_label": class_group.get_status_display(),
            }
            for class_group in class_rows[:8]
        ],
        "status_rows": [
            {
                "label": "首次登录未改密",
                "count": first_login_accounts,
                "level": "warn" if first_login_accounts else "ok",
                "detail": "启用账号尚未完成首次改密",
                "path": "/school-admin/teachers",
            },
            {
                "label": "新生入门未完成",
                "count": pending_onboarding,
                "level": "warn" if pending_onboarding else "ok",
                "detail": "仍处于首次使用流程",
                "path": "/school-admin/students",
            },
            {
                "label": "未分班学生",
                "count": students_without_class,
                "level": "warn" if students_without_class else "ok",
                "detail": "启用学生尚未匹配班级",
                "path": "/school-admin/students",
            },
            {
                "label": "待审核资源",
                "count": pending_resource_reviews,
                "level": "warn" if pending_resource_reviews else "ok",
                "detail": "教师申请跨校共享的资源",
                "path": "/school-admin/resource-reviews",
            },
            {
                "label": "待审核题目",
                "count": pending_question_reviews,
                "level": "warn" if pending_question_reviews else "ok",
                "detail": "教师提交到校内共享题库",
                "path": "/school-admin/question-reviews",
            },
            {
                "label": "训练失败",
                "count": failed_training,
                "level": "failed" if failed_training else "ok",
                "detail": "需要查看失败原因或重新运行",
                "path": "/school-admin/models",
            },
            {
                "label": "教师待确认层级",
                "count": pending_decisions,
                "level": "warn" if pending_decisions else "ok",
                "detail": "由任课教师确认，不由学校管理员代替处理",
                "path": "/school-admin/models",
            },
            {
                "label": "导出失败",
                "count": failed_exports,
                "level": "failed" if failed_exports else "ok",
                "detail": "数据采集包或报表导出失败",
                "path": "/school-admin/data-quality",
            },
        ],
    }
    return ok(data)


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teachers(request):
    if request.method == "POST":
        try:
            teacher = create_teacher(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(account_row(teacher), "教师已创建", status=201)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    teachers = _school_users(request).filter(role="teacher").order_by("username")
    if query:
        teachers = teachers.filter(
            Q(username__icontains=query)
            | Q(display_name__icontains=query)
            | Q(phone__icontains=query)
        )
    if status == "active":
        teachers = teachers.filter(is_active=True)
    elif status == "disabled":
        teachers = teachers.filter(is_active=False)
    page = _paginate(request, teachers)
    page.object_list = [account_row(teacher) for teacher in page.object_list]
    return ok(page_data(page))


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_teachers_export(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    teachers = _school_users(request).filter(role="teacher").order_by("username")
    if query:
        teachers = teachers.filter(
            Q(username__icontains=query)
            | Q(display_name__icontains=query)
            | Q(phone__icontains=query)
        )
    if status == "active":
        teachers = teachers.filter(is_active=True)
    elif status == "disabled":
        teachers = teachers.filter(is_active=False)
    rows = [
        [
            teacher.username,
            teacher.display_name,
            teacher.phone,
            "启用" if teacher.is_active else "停用",
            "是" if teacher.is_first_login else "否",
            teacher.last_login,
            teacher.date_joined,
            teacher.teaching_classes.filter(school=_school(request)).count(),
        ]
        for teacher in teachers
    ]
    return export_rows(
        _xlsx_filename(f"{_school(request).code}_教师管理"),
        "教师管理",
        [
            "登录账号",
            "姓名",
            "联系电话",
            "状态",
            "首次登录",
            "最近登录",
            "创建时间",
            "任课班级数",
        ],
        rows,
    )


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_teachers_template(request):
    return template_response(
        "教师批量导入模板.xlsx",
        "教师导入模板",
        TEACHER_IMPORT_HEADERS,
        [["teacher1", "张老师", "13800138000", "123456", "启用"]],
        instructions=[
            "登录账号必填且唯一；5-32 位，以字母开头，可包含字母、数字和下划线。",
            "新增教师必须填写初始密码；教师允许使用 123456 这类课堂简易密码。",
            "更新已有教师时，初始密码留空则不修改原密码；状态可填：启用、停用。",
        ],
        dropdowns={"状态": ["启用", "停用"]},
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teachers_import(request):
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return fail(
            "请选择 xlsx 文件。", errors={"file": ["请选择 xlsx 文件。"]}, status=400
        )
    if not uploaded_file.name.lower().endswith(".xlsx"):
        return fail(
            "只能上传 xlsx 文件。",
            errors={"file": ["只能上传 xlsx 文件。"]},
            status=400,
        )
    try:
        result = import_teachers_from_xlsx(request, uploaded_file)
    except ServiceError as exc:
        return _service_fail(exc)
    except ValueError as exc:
        return fail(str(exc), errors={"file": [str(exc)]}, status=400)
    return ok(
        result,
        f"教师批量导入完成：新增 {result['created_count']} 个，更新 {result['updated_count']} 个。",
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teachers_bulk_disable(request):
    try:
        result = bulk_disable_teacher_accounts(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, f"已停用 {result['updated_count']} 个教师账号。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teachers_bulk_delete(request):
    try:
        result = bulk_delete_teacher_accounts(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, result["message"])


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_teacher_detail(request, pk):
    teacher = _school_users(request).filter(pk=pk, role="teacher").first()
    if teacher is None:
        return fail("教师不存在。", status=404)

    if request.method == "GET":
        return ok(account_row(teacher))
    if request.method == "PATCH":
        try:
            teacher = update_teacher(request, teacher, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(account_row(teacher), "教师已更新")

    try:
        delete_account(request, teacher, action_prefix="teacher")
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "教师已删除")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teacher_set_active(request, pk):
    teacher = _school_users(request).filter(pk=pk, role="teacher").first()
    if teacher is None:
        return fail("教师不存在。", status=404)
    is_active = bool(request.data.get("is_active"))
    set_account_active(request, teacher, is_active, action_prefix="teacher")
    return ok(account_row(teacher), "教师状态已更新")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teacher_reset_password(request, pk):
    teacher = _school_users(request).filter(pk=pk, role="teacher").first()
    if teacher is None:
        return fail("教师不存在。", status=404)
    try:
        reset_teacher_password(request, teacher, str(request.data.get("password", "")))
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(account_row(teacher), "密码已重置")




















@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_classes(request):
    if request.method == "POST":
        try:
            class_group = save_class_group(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        class_group.student_count = 0
        class_group.teacher_count = 0
        return ok(class_group_row(class_group), "班级已创建", status=201)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    classes = ClassGroup.objects.filter(school=_school(request)).annotate(
        student_count=Count("students", distinct=True),
        teacher_count=Count("teachers", distinct=True),
    )
    if query:
        classes = classes.filter(Q(name__icontains=query) | Q(grade__icontains=query))
    if status:
        classes = classes.filter(status=status)
    page = _paginate(request, classes.order_by("grade", "name"))
    page.object_list = [
        class_group_row(class_group) for class_group in page.object_list
    ]
    return ok(page_data(page))


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_classes_bulk_create(request):
    try:
        created = bulk_create_class_groups(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    for class_group in created:
        class_group.student_count = 0
        class_group.teacher_count = 0
    return ok(
        {
            "created_count": len(created),
            "results": [class_group_row(class_group) for class_group in created],
        },
        "班级已批量创建",
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_classes_promote(request):
    try:
        promoted = promote_class_groups(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    for class_group in promoted:
        class_group.student_count = class_group.students.count()
        class_group.teacher_count = class_group.teachers.count()
    return ok(
        {
            "promoted_count": len(promoted),
            "results": [class_group_row(class_group) for class_group in promoted],
        },
        "班级已升班",
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_classes_bulk_disable(request):
    try:
        result = bulk_disable_class_groups(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, f"已停用 {result['updated_count']} 个班级。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_classes_bulk_delete(request):
    try:
        result = bulk_delete_class_groups(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, result["message"])


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_classes_graduate(request):
    try:
        result = graduate_class_groups(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(
        result,
        f"已毕业归档 {result['graduated_count']} 个班级，并停用 {result['disabled_students']} 个学生账号。",
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_class_detail(request, pk):
    class_group = (
        ClassGroup.objects.filter(pk=pk, school=_school(request))
        .annotate(
            student_count=Count("students", distinct=True),
            teacher_count=Count("teachers", distinct=True),
        )
        .first()
    )
    if class_group is None:
        return fail("班级不存在。", status=404)

    if request.method == "GET":
        return ok(class_group_row(class_group))
    if request.method == "PATCH":
        try:
            class_group = save_class_group(
                request, request.data, class_group=class_group
            )
        except ServiceError as exc:
            return _service_fail(exc)
        class_group.student_count = class_group.students.count()
        class_group.teacher_count = class_group.teachers.count()
        return ok(class_group_row(class_group), "班级已更新")

    try:
        delete_class_group(request, class_group)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "班级已删除")


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_subjects(request):
    if request.method == "POST":
        try:
            subject = save_subject(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        subject.course_count = 0
        subject.pretest_count = 0
        return ok(subject_row(subject), "学科已创建", status=201)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    subjects = Subject.objects.filter(school=_school(request)).annotate(
        course_count=Count("courses", distinct=True),
        pretest_count=Count("pretest_papers", distinct=True),
    )
    if query:
        subjects = subjects.filter(Q(name__icontains=query) | Q(code__icontains=query))
    if status == "active":
        subjects = subjects.filter(is_active=True)
    elif status == "disabled":
        subjects = subjects.filter(is_active=False)
    return ok([subject_row(subject) for subject in subjects.order_by("name")])


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_subject_detail(request, pk):
    subject = (
        Subject.objects.filter(pk=pk, school=_school(request))
        .annotate(
            course_count=Count("courses", distinct=True),
            pretest_count=Count("pretest_papers", distinct=True),
        )
        .first()
    )
    if subject is None:
        return fail("学科不存在。", status=404)

    if request.method == "GET":
        return ok(subject_row(subject))
    if request.method == "PATCH":
        try:
            subject = save_subject(request, request.data, subject=subject)
        except ServiceError as exc:
            return _service_fail(exc)
        subject.course_count = subject.courses.count()
        subject.pretest_count = subject.pretest_papers.count()
        return ok(subject_row(subject), "学科已更新")

    try:
        delete_subject(request, subject)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "学科已删除")
















@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_teaching_options(request):
    User = get_user_model()
    school = _school(request)
    classes = ClassGroup.objects.filter(school=school).order_by("grade", "name")
    teachers = User.objects.filter(
        school=school, role="teacher", is_active=True
    ).order_by("username")
    return ok(
        {
            "classes": [class_group_row(class_group) for class_group in classes],
            "teachers": [account_row(teacher) for teacher in teachers],
        }
    )


def _filtered_teaching_teachers(request):
    User = get_user_model()
    school = _school(request)
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    teacher_id = request.GET.get("teacher", "").strip()
    teachers = User.objects.filter(school=school, role="teacher").order_by("username")
    if query:
        teachers = teachers.filter(
            Q(username__icontains=query)
            | Q(display_name__icontains=query)
            | Q(teaching_assignments__class_group__name__icontains=query)
            | Q(teaching_assignments__class_group__grade__icontains=query)
        )
    if class_id:
        teachers = teachers.filter(teaching_assignments__class_group_id=class_id)
    if teacher_id:
        teachers = teachers.filter(id=teacher_id)
    return teachers.distinct()


def _teaching_teacher_rows(teachers, school):
    teacher_ids = [teacher.id for teacher in teachers]
    assignments = (
        TeachingAssignment.objects.filter(school=school, teacher_id__in=teacher_ids)
        .select_related("class_group")
        .order_by("class_group__grade", "class_group__name")
    )
    classes_by_teacher = {teacher_id: [] for teacher_id in teacher_ids}
    for assignment in assignments:
        classes_by_teacher.setdefault(assignment.teacher_id, []).append(
            assignment.class_group
        )
    return [
        teaching_teacher_row(teacher, classes_by_teacher.get(teacher.id, []))
        for teacher in teachers
    ]


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teaching_assignments(request):
    if request.method == "POST":
        try:
            assignment = save_teaching_assignment(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(teaching_assignment_row(assignment), "任课关系已创建", status=201)

    school = _school(request)
    page = _paginate(request, _filtered_teaching_teachers(request))
    page.object_list = _teaching_teacher_rows(page.object_list, school)
    return ok(page_data(page))


def _filtered_teaching_assignments(request):
    school = _school(request)
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    teacher_id = request.GET.get("teacher", "").strip()
    assignments = TeachingAssignment.objects.filter(school=school).select_related(
        "school", "class_group", "teacher"
    )
    if query:
        assignments = assignments.filter(
            Q(class_group__name__icontains=query)
            | Q(class_group__grade__icontains=query)
            | Q(teacher__username__icontains=query)
            | Q(teacher__display_name__icontains=query)
        )
    if class_id:
        assignments = assignments.filter(class_group_id=class_id)
    if teacher_id:
        assignments = assignments.filter(teacher_id=teacher_id)
    return assignments


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_teaching_export(request):
    rows = [
        [
            item["teacher"]["username"],
            item["teacher"]["display_name"],
            item["teacher"]["phone"],
            item["class_count"],
            "、".join(
                f"{class_group['grade']} {class_group['name']}".strip()
                for class_group in item["classes"]
            ),
        ]
        for item in _teaching_teacher_rows(
            list(_filtered_teaching_teachers(request)), _school(request)
        )
    ]
    return export_rows(
        _xlsx_filename(f"{_school(request).code}_任课关系"),
        "任课关系",
        ["教师账号", "教师姓名", "联系电话", "任教班级数", "任教班级"],
        rows,
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_teaching_bulk_save(request):
    try:
        result = bulk_save_teaching_assignments(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(
        result,
        f"任教班级已保存：新增 {result['created_count']} 个，保留 {result['updated_count']} 个，移除 {result['deleted_count']} 个。",
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_teaching_assignment_detail(request, pk):
    assignment = (
        TeachingAssignment.objects.filter(pk=pk, school=_school(request))
        .select_related("school", "class_group", "teacher")
        .first()
    )
    if assignment is None:
        return fail("任课关系不存在。", status=404)

    if request.method == "GET":
        return ok(teaching_assignment_row(assignment))
    if request.method == "PATCH":
        try:
            assignment = save_teaching_assignment(
                request, request.data, assignment=assignment
            )
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(teaching_assignment_row(assignment), "任课关系已更新")

    try:
        delete_teaching_assignment(request, assignment)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "任课关系已删除")


def _teacher_class_ids(request) -> list[int]:
    return list(
        TeachingAssignment.objects.filter(school=_school(request), teacher=request.user)
        .values_list("class_group_id", flat=True)
        .distinct()
    )


def _teacher_classes(request):
    class_ids = _teacher_class_ids(request)
    return (
        ClassGroup.objects.filter(school=_school(request), id__in=class_ids)
        .annotate(
            student_count=Count("students", distinct=True),
            teacher_count=Count("teachers", distinct=True),
        )
        .order_by("grade", "name")
    )




@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_dashboard(request):
    school = _school(request)
    class_ids = _teacher_class_ids(request)
    classes = ClassGroup.objects.filter(school=school, id__in=class_ids)
    students = StudentProfile.objects.filter(
        user__school=school, class_group_id__in=class_ids
    )
    events = LearningEvent.objects.filter(class_group_id__in=class_ids)
    decisions = visible_teacher_decisions(
        teacher=request.user,
        class_ids=class_ids,
    )
    courses = Course.objects.filter(teacher=request.user)
    resources = Resource.objects.filter(owner=request.user)
    training_jobs = TrainingJob.objects.filter(class_group_id__in=class_ids)
    today = timezone.localdate()
    last_7d_events = events.filter(occurred_at__gte=timezone.now() - timedelta(days=7))
    class_rows = list(
        classes.annotate(
            student_count=Count("students", distinct=True),
            event_count=Count(
                "learningevent",
                filter=Q(
                    learningevent__occurred_at__gte=timezone.now() - timedelta(days=7)
                ),
                distinct=True,
            ),
        ).order_by("grade", "name")
    )
    active_students = students.filter(user__is_active=True)
    pending_decisions = decisions.filter(
        status=StratificationDecision.Status.PENDING,
        decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
    ).count()
    pending_support = decisions.filter(
        status=StratificationDecision.Status.PENDING,
        decision_kind=StratificationDecision.DecisionKind.SUPPORT,
    ).count()
    first_login_students = active_students.filter(user__is_first_login=True).count()
    pending_pretest = active_students.exclude(
        onboarding_status__in=[
            StudentProfile.OnboardingStatus.PRETEST_COMPLETED,
            StudentProfile.OnboardingStatus.ACTIVE,
        ]
    ).count()
    inactive_students = students.filter(user__is_active=False).count()

    data = {
        "school": {"id": school.id, "name": school.name, "code": school.code},
        "metrics": [
            {"label": "任教班级", "value": len(class_ids), "sub": "学校已分配"},
            {"label": "学生", "value": students.count(), "sub": "任教班级内"},
            {"label": "课程", "value": courses.count(), "sub": "本人课程"},
            {"label": "资源", "value": resources.count(), "sub": "本人上传"},
            {
                "label": "今日行为",
                "value": events.filter(occurred_at__date=today).count(),
                "sub": "任教班级内",
            },
            {
                "label": "待确认分层",
                "value": pending_decisions,
                "sub": "本人课程的层级建议",
            },
        ],
        "charts": {
            "event_series": _day_series(events, "occurred_at", days=7),
            "login_series": _day_series(
                events.filter(event_type=LearningEvent.EventType.LOGIN),
                "occurred_at",
                days=7,
            ),
            "active_students_7d": _day_distinct_series(
                last_7d_events.filter(actor__role="student"),
                "occurred_at",
                "actor",
                days=7,
            ),
            "class_students": _class_student_counts(class_rows),
            "class_activity": _class_event_counts(class_rows),
            "student_layers": [
                {
                    "label": label,
                    "value": value,
                    "count": students.filter(current_layer=value).count(),
                }
                for value, label in StudentProfile.Layer.choices
            ]
            + [
                {
                    "label": "未分层",
                    "value": "unassigned",
                    "count": students.filter(current_layer__isnull=True).count(),
                }
            ],
            "event_types": _event_type_counts(last_7d_events),
            "decision_status": _choice_counts(
                decisions, "status", StratificationDecision.Status.choices
            ),
            "training_status": _choice_counts(
                training_jobs, "status", TrainingJob.Status.choices
            ),
        },
        "class_rows": [
            {
                "id": class_group.id,
                "name": class_group.name,
                "grade": class_group.grade,
                "student_count": getattr(class_group, "student_count", 0),
                "event_count": getattr(class_group, "event_count", 0),
                "status_label": class_group.get_status_display(),
            }
            for class_group in class_rows[:10]
        ],
        "todo_rows": [
            {
                "label": "待确认分层",
                "count": pending_decisions,
                "level": "warn" if pending_decisions else "ok",
                "path": "/teacher/stratification?view=pending",
            },
            {
                "label": "待查看学习支持",
                "count": pending_support,
                "level": "warn" if pending_support else "ok",
                "path": "/teacher/stratification?view=pending",
            },
            {
                "label": "学生首次登录",
                "count": first_login_students,
                "level": "warn" if first_login_students else "ok",
                "path": "/teacher/students",
            },
            {
                "label": "未完成前测",
                "count": pending_pretest,
                "level": "warn" if pending_pretest else "ok",
                "path": "/teacher/students",
            },
            {
                "label": "停用学生账号",
                "count": inactive_students,
                "level": "failed" if inactive_students else "ok",
                "path": "/teacher/students",
            },
        ],
    }
    return ok(data)


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classes(request):
    return ok(
        [class_group_row(class_group) for class_group in _teacher_classes(request)]
    )


@api_view(["GET", "PATCH", "POST"])
@permission_classes([IsTeacher])
def teacher_ai_provider(request):
    if request.method == "GET":
        return ok(teacher_ai_provider_row(get_teacher_ai_provider(request.user)))
    try:
        provider = save_teacher_ai_provider(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(teacher_ai_provider_row(provider), "AI 接入配置已保存。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_ai_provider_test(request):
    try:
        provider = test_teacher_ai_provider(request)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(teacher_ai_provider_row(provider), "AI 接入测试通过。")
















OFFICE_FILE_TYPES = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}




def _office_document_type(file_ext: str) -> str:
    if file_ext in {"ppt", "pptx"}:
        return "slide"
    if file_ext in {"xls", "xlsx"}:
        return "cell"
    return "word"
























































































GROUP_FILE_ALLOWED_EXTENSIONS = {
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "pdf",
    "zip",
    "rar",
    "7z",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "bmp",
    "mp4",
    "webm",
    "mov",
    "mp3",
    "wav",
    "m4a",
    "txt",
    "md",
    "csv",
}






















def _classroom_group_queryset(collaboration: ClassroomGroupCollaboration):
    return (
        collaboration.groups.filter(
            is_active=True,
            plan_version=collaboration.active_plan_version,
        )
        .annotate(
            used_storage_bytes=Sum("files__file_size"),
            file_count=Count("files", distinct=True),
        )
        .prefetch_related(
            Prefetch(
                "members",
                queryset=ClassroomGroupMember.objects.select_related(
                    "student", "student_profile"
                ),
                to_attr="prefetched_members",
            ),
            Prefetch(
                "files",
                queryset=ClassroomGroupFile.objects.select_related("uploader"),
                to_attr="prefetched_files",
            ),
        )
        .select_related("leader", "collaboration", "collaboration__session")
        .order_by("group_no", "id")
    )


















def _group_storage_used(group: ClassroomGroup) -> int:
    return group.files.aggregate(total=Sum("file_size")).get("total") or 0


def _validate_group_file_upload(
    collaboration: ClassroomGroupCollaboration, group: ClassroomGroup, uploaded_file
) -> tuple[str, int]:
    if uploaded_file is None:
        raise ServiceError(
            "请选择要上传的小组文件。",
            errors={"attachment": ["请选择要上传的小组文件。"]},
            status=400,
        )
    file_size = int(getattr(uploaded_file, "size", 0) or 0)
    if file_size <= 0:
        raise ServiceError(
            "上传文件为空。", errors={"attachment": ["上传文件为空。"]}, status=400
        )
    ext = clean_resource_ext(Path(getattr(uploaded_file, "name", "")).suffix)
    if ext not in GROUP_FILE_ALLOWED_EXTENSIONS:
        raise ServiceError(
            "文件格式不在小组共享区允许范围内。",
            errors={
                "attachment": ["支持 Office、PDF、压缩包、图片、音视频和常见文本文件。"]
            },
            status=400,
        )
    quota_bytes = collaboration.storage_quota_mb * 1024 * 1024
    used_bytes = _group_storage_used(group)
    if used_bytes + file_size > quota_bytes:
        remaining_mb = max((quota_bytes - used_bytes) / 1024 / 1024, 0)
        raise ServiceError(
            f"小组共享空间不足，剩余约 {remaining_mb:.1f}MB。",
            errors={"attachment": [f"小组共享空间不足，剩余约 {remaining_mb:.1f}MB。"]},
            status=400,
        )
    return ext, file_size


def _save_group_file(
    request, group: ClassroomGroup, uploaded_file, description: str = ""
) -> ClassroomGroupFile:
    collaboration = group.collaboration
    file_ext, file_size = _validate_group_file_upload(
        collaboration, group, uploaded_file
    )
    return ClassroomGroupFile.objects.create(
        group=group,
        uploader=request.user,
        attachment=uploaded_file,
        original_name=Path(getattr(uploaded_file, "name", "") or "attachment").name[
            :255
        ],
        file_ext=file_ext,
        file_size=file_size,
        description=description[:255],
    )














EVALUATION_TYPE_LABELS = {
    ClassroomEvaluationSubmission.EvaluationType.SELF: "自评",
    ClassroomEvaluationSubmission.EvaluationType.PEER: "互评",
    ClassroomEvaluationSubmission.EvaluationType.TEACHER: "师评",
}




def _evaluation_criteria_field(evaluation_type: str) -> str:
    return {
        ClassroomEvaluationSubmission.EvaluationType.SELF: "self_criteria",
        ClassroomEvaluationSubmission.EvaluationType.PEER: "peer_criteria",
        ClassroomEvaluationSubmission.EvaluationType.TEACHER: "teacher_criteria",
    }[evaluation_type]


def _evaluation_enabled_field(evaluation_type: str) -> str:
    return {
        ClassroomEvaluationSubmission.EvaluationType.SELF: "enable_self",
        ClassroomEvaluationSubmission.EvaluationType.PEER: "enable_peer",
        ClassroomEvaluationSubmission.EvaluationType.TEACHER: "enable_teacher",
    }[evaluation_type]


def _clean_evaluation_criteria(raw_items, *, required: bool, label: str) -> list[dict]:
    if not isinstance(raw_items, list):
        raw_items = []
    rows: list[dict] = []
    errors: list[str] = []
    seen_ids = set()
    for index, item in enumerate(raw_items[:20], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title and not description:
            continue
        if len(title) < 2 or len(title) > 80:
            errors.append(f"{label}第 {index} 项标题需为 2-80 个字符。")
            continue
        if len(description) > 300:
            errors.append(f"{label}第 {index} 项说明不能超过 300 个字符。")
            continue
        criterion_id = str(item.get("id") or "").strip()
        if not criterion_id or criterion_id in seen_ids:
            criterion_id = f"{label.lower()}_{index}"
        seen_ids.add(criterion_id)
        try:
            sort_order = int(item.get("sort_order") or index * 10)
        except (TypeError, ValueError):
            sort_order = index * 10
        rows.append(
            {
                "id": criterion_id[:64],
                "title": title,
                "description": description,
                "sort_order": sort_order,
            }
        )
    if len(raw_items) > 20:
        errors.append(f"{label}最多设置 20 个评价项。")
    if required and not rows:
        errors.append(f"开启{label}后至少需要 1 个评价项。")
    if errors:
        raise ServiceError(
            "评价内容校验失败。", errors={"criteria": errors}, status=400
        )
    return sorted(rows, key=lambda row: (row["sort_order"], row["id"]))


def _open_group_collaboration(
    session: ClassroomSession,
) -> ClassroomGroupCollaboration | None:
    return ClassroomGroupCollaboration.objects.filter(
        session=session,
        is_enabled=True,
        status=ClassroomGroupCollaboration.Status.OPEN,
    ).first()




def _course_class_groups(course: Course) -> list[ClassGroup]:
    return list(
        ClassGroup.objects.filter(course_classes__course=course)
        .annotate(student_count=Count("students", distinct=True))
        .order_by("grade", "name", "id")
    )


def _course_class_group(course: Course, class_group_id=None) -> ClassGroup | None:
    class_groups = _course_class_groups(course)
    if class_group_id:
        try:
            wanted_id = int(class_group_id)
        except (TypeError, ValueError):
            wanted_id = 0
        for class_group in class_groups:
            if class_group.id == wanted_id:
                return class_group
    return class_groups[0] if class_groups else None


def _course_student_profiles(
    course: Course, class_group: ClassGroup | None
) -> list[StudentProfile]:
    if class_group is None:
        return []
    return list(
        StudentProfile.objects.select_related("user")
        .filter(class_group=class_group, user__is_active=True)
        .order_by("user__display_name", "user__username", "id")
    )


def _evaluation_student_row(profile: StudentProfile) -> dict:
    return {
        "student": account_row(profile.user),
        "profile": teacher_student_profile_summary(profile),
    }


def _validate_evaluation_response(
    config: ClassroomEvaluationConfig | ClassroomEvaluationConfigVersion,
    evaluation_type: str,
    ratings,
    not_assessed,
) -> tuple[dict[str, int], dict[str, dict[str, str]]]:
    field = _evaluation_criteria_field(evaluation_type)
    criteria = classroom_evaluation_config_row(config).get(field, [])
    criterion_ids = {item["id"] for item in criteria}
    if not isinstance(ratings, dict):
        ratings = {}
    if not isinstance(not_assessed, dict):
        not_assessed = {}
    ratings = {str(key): value for key, value in ratings.items()}
    not_assessed = {str(key): value for key, value in not_assessed.items()}
    cleaned: dict[str, int] = {}
    cleaned_not_assessed: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    reason_labels = dict(ClassroomEvaluationSubmission.NotAssessedReason.choices)
    for criterion in criteria:
        criterion_id = criterion["id"]
        has_rating = criterion_id in ratings
        has_not_assessed = criterion_id in not_assessed
        if has_rating and has_not_assessed:
            errors.append(f"{criterion['title']}不能同时评分和暂不评价。")
            continue
        if has_rating:
            try:
                value = int(ratings[criterion_id])
            except (TypeError, ValueError):
                errors.append(f"{criterion['title']}需要选择 1-5 星。")
                continue
            if value < 1 or value > 5:
                errors.append(f"{criterion['title']}只能选择 1-5 星。")
                continue
            cleaned[criterion_id] = value
            continue
        if has_not_assessed:
            raw_reason = not_assessed[criterion_id]
            if isinstance(raw_reason, str):
                reason = raw_reason.strip()
                note = ""
            elif isinstance(raw_reason, dict):
                reason = str(raw_reason.get("reason") or "").strip()
                note = str(raw_reason.get("note") or "").strip()
            else:
                reason = ""
                note = ""
            if reason not in reason_labels:
                errors.append(f"{criterion['title']}需要选择暂不评价原因。")
                continue
            if len(note) > 200:
                errors.append(
                    f"{criterion['title']}的暂不评价说明不能超过 200 个字符。"
                )
                continue
            if (
                reason == ClassroomEvaluationSubmission.NotAssessedReason.OTHER
                and not note
            ):
                errors.append(f"{criterion['title']}选择其他原因时需要填写说明。")
                continue
            cleaned_not_assessed[criterion_id] = {"reason": reason, "note": note}
            continue
        errors.append(f"{criterion['title']}需要选择 1-5 星或暂不评价。")
    extra = [
        key for key in set(ratings) | set(not_assessed) if str(key) not in criterion_ids
    ]
    if extra:
        errors.append("评价结果包含无效评价项。")
    if errors:
        raise ServiceError("评价内容校验失败。", errors={"ratings": errors}, status=400)
    return cleaned, cleaned_not_assessed


def _evaluation_submission_average(
    criteria: list[dict], submissions: list[ClassroomEvaluationSubmission]
) -> dict:
    criterion_rows = []
    values = []
    not_assessed_total = 0
    for criterion in criteria:
        criterion_values = []
        criterion_not_assessed = 0
        for submission in submissions:
            ratings = submission.ratings if isinstance(submission.ratings, dict) else {}
            not_assessed = (
                submission.not_assessed
                if isinstance(submission.not_assessed, dict)
                else {}
            )
            if criterion["id"] in not_assessed:
                criterion_not_assessed += 1
                not_assessed_total += 1
            value = ratings.get(criterion["id"])
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= 5:
                criterion_values.append(number)
                values.append(number)
        criterion_rows.append(
            {
                "id": criterion["id"],
                "title": criterion["title"],
                "average": (
                    round(sum(criterion_values) / len(criterion_values), 2)
                    if criterion_values
                    else None
                ),
                "count": len(criterion_values),
                "not_assessed_count": criterion_not_assessed,
            }
        )
    total_items = len(criteria) * len(submissions)
    rated_items = len(values)
    return {
        "average": round(sum(values) / len(values), 2) if values else None,
        "rated_item_count": rated_items,
        "not_assessed_item_count": not_assessed_total,
        "unanswered_item_count": max(total_items - rated_items - not_assessed_total, 0),
        "total_item_count": total_items,
        "criteria": criterion_rows,
    }


def _latest_evaluation_submissions(
    submissions: list[ClassroomEvaluationSubmission],
) -> list[ClassroomEvaluationSubmission]:
    rows = []
    seen = set()
    for submission in submissions:
        key = (
            submission.session_id,
            submission.evaluation_type,
            submission.evaluator_id,
            submission.target_id,
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(submission)
    return rows




def _classroom_evaluation_source(session: ClassroomSession):
    standard_use = (
        ClassroomEvaluationStandardUse.objects.select_related(
            "standard_version", "binding", "lesson_step"
        )
        .filter(session=session)
        .first()
    )
    if standard_use is not None:
        return standard_use
    binding = (
        LessonStepEvaluationBinding.objects.select_related("standard_version")
        .prefetch_related("standard_version__criteria")
        .filter(lesson_step_id=session.current_step_id)
        .first()
    )
    if binding is not None:
        criteria = standard_binding_criteria(binding)
        return {
            "id": binding.id,
            "course_id": session.course_id,
            "session_id": session.id,
            "enable_self": binding.enable_self,
            "enable_peer": binding.enable_peer,
            "enable_teacher": binding.enable_teacher,
            "self_criteria": criteria if binding.enable_self else [],
            "peer_criteria": criteria if binding.enable_peer else [],
            "teacher_criteria": criteria if binding.enable_teacher else [],
            "version_no": binding.standard_version.version_no,
            "config_hash": binding.standard_version.content_hash,
            "standard_version_id": binding.standard_version_id,
            "standard_title": binding.standard_version.title,
            "created_at": binding.created_at,
            "updated_at": binding.updated_at,
            "frozen": False,
            "legacy_compatible": False,
        }
    if session.evaluation_config_version_id:
        return session.evaluation_config_version
    return None




def _teacher_course_evaluation_payload(
    course: Course,
    *,
    class_group: ClassGroup | None = None,
    config: ClassroomEvaluationConfig | None = None,
) -> dict:
    config = config or ClassroomEvaluationConfig.objects.filter(course=course).first()
    config_row = classroom_evaluation_config_row(config)
    class_options = _course_class_groups(course)
    class_group = class_group or (class_options[0] if class_options else None)
    profiles = _course_student_profiles(course, class_group)
    target_ids = [profile.user_id for profile in profiles]
    submissions = list(
        ClassroomEvaluationSubmission.objects.select_related(
            "evaluator", "target", "group", "session", "evaluation_version"
        )
        .filter(course=course, target_id__in=target_ids)
        .order_by("-updated_at", "-id")
    )
    current_submissions = _latest_evaluation_submissions(submissions)
    submissions_by_type = {
        evaluation_type: [
            item
            for item in current_submissions
            if item.evaluation_type == evaluation_type
        ]
        for evaluation_type in EVALUATION_TYPE_LABELS
    }
    summary = {}
    totals = {
        ClassroomEvaluationSubmission.EvaluationType.SELF: len(profiles),
        ClassroomEvaluationSubmission.EvaluationType.PEER: len(
            submissions_by_type[ClassroomEvaluationSubmission.EvaluationType.PEER]
        ),
        ClassroomEvaluationSubmission.EvaluationType.TEACHER: len(profiles),
    }
    for evaluation_type, label in EVALUATION_TYPE_LABELS.items():
        criteria = config_row.get(_evaluation_criteria_field(evaluation_type), [])
        type_submissions = submissions_by_type[evaluation_type]
        summary[evaluation_type] = {
            "label": label,
            "enabled": bool(config_row.get(_evaluation_enabled_field(evaluation_type))),
            "submitted": len(type_submissions),
            "total": totals[evaluation_type],
            **_evaluation_submission_average(criteria, type_submissions),
        }

    teacher_by_target = {}
    for item in submissions_by_type[
        ClassroomEvaluationSubmission.EvaluationType.TEACHER
    ]:
        if (
            item.evaluator_id == course.teacher_id
            and item.session_id is None
            and item.target_id not in teacher_by_target
        ):
            teacher_by_target[item.target_id] = item
    self_by_target = {}
    for item in submissions_by_type[ClassroomEvaluationSubmission.EvaluationType.SELF]:
        if item.evaluator_id == item.target_id and item.target_id not in self_by_target:
            self_by_target[item.target_id] = item
    peer_by_target: dict[int, list[ClassroomEvaluationSubmission]] = {}
    for item in submissions_by_type[ClassroomEvaluationSubmission.EvaluationType.PEER]:
        peer_by_target.setdefault(item.target_id, []).append(item)

    student_rows = []
    peer_criteria = config_row.get("peer_criteria", [])
    for profile in profiles:
        peer_submissions = peer_by_target.get(profile.user_id, [])
        student_rows.append(
            {
                **_evaluation_student_row(profile),
                "self_submission": classroom_evaluation_submission_row(
                    self_by_target.get(profile.user_id)
                ),
                "teacher_submission": classroom_evaluation_submission_row(
                    teacher_by_target.get(profile.user_id)
                ),
                "peer_submission_count": len(peer_submissions),
                "peer_average": (
                    _evaluation_submission_average(peer_criteria, peer_submissions)[
                        "average"
                    ]
                    if peer_criteria
                    else None
                ),
            }
        )

    return {
        "course": course_row(course),
        "class_options": [class_group_row(item) for item in class_options],
        "selected_class_group": class_group_row(class_group) if class_group else None,
        "config": config_row,
        "summary": summary,
        "students": student_rows,
        "recent_submissions": [
            classroom_evaluation_submission_row(item)
            for item in current_submissions[:50]
        ],
        "peer_available": False,
    }


def _save_course_evaluation_config(
    request, course: Course, data
) -> ClassroomEvaluationConfig:
    raise ServiceError(
        "课程级评价设置已停止使用，请在评价标准页面制定标准，并在课时设计中选择。",
        status=410,
    )


def _configured_evaluation_type_count(config: ClassroomEvaluationConfig | None) -> int:
    if config is None:
        return 0
    config_row = classroom_evaluation_config_row(config)
    count = 0
    for evaluation_type in EVALUATION_TYPE_LABELS:
        if config_row.get(_evaluation_criteria_field(evaluation_type)):
            count += 1
    return count








def _teacher_course_evaluation_class_group(
    request, course: Course
) -> ClassGroup | None:
    raw_value = request.GET.get("class_group")
    if request.method in {"POST", "PATCH"}:
        raw_value = request.data.get("class_group", raw_value)
    return _course_class_group(course, raw_value)


































def _score_float(value, fallback: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def _clean_answer_text(value) -> str:
    return str(value or "").strip()


def _answer_to_list(value) -> list[str]:
    if isinstance(value, list):
        return [_clean_answer_text(item) for item in value if _clean_answer_text(item)]
    text = _clean_answer_text(value)
    return [text] if text else []


def _answer_display(value) -> str:
    if isinstance(value, list):
        return "、".join(_answer_to_list(value))
    if isinstance(value, dict):
        attachment_name = _clean_answer_text(
            value.get("attachment_name")
            or value.get("original_name")
            or value.get("filename")
        )
        if attachment_name:
            return attachment_name
        return json.dumps(value, ensure_ascii=False)
    return _clean_answer_text(value)


def _question_answer_value(answer, question_id: str):
    if not isinstance(answer, dict):
        return None
    questions = answer.get("questions")
    if not isinstance(questions, dict):
        return None
    return questions.get(str(question_id))


def _answer_text_value(answer) -> str:
    if isinstance(answer, dict):
        return _clean_answer_text(answer.get("text"))
    return _clean_answer_text(answer)


def _question_answered(value) -> bool:
    if isinstance(value, list):
        return any(_clean_answer_text(item) for item in value)
    if isinstance(value, dict):
        return bool(
            value.get("attachment_id")
            or value.get("id")
            or value.get("attachment_url")
            or _clean_answer_text(value.get("answer"))
            or _clean_answer_text(value.get("text"))
        )
    return bool(_clean_answer_text(value))


def _answer_attachment_value(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    attachment_url = _clean_answer_text(value.get("attachment_url") or value.get("url"))
    attachment_name = _clean_answer_text(
        value.get("attachment_name")
        or value.get("original_name")
        or value.get("filename")
    )
    attachment_id = value.get("attachment_id") or value.get("id")
    if not (attachment_id or attachment_url or attachment_name):
        return None
    try:
        attachment_id = int(attachment_id) if attachment_id else None
    except (TypeError, ValueError):
        attachment_id = None
    score = value.get("score")
    try:
        score = float(score) if score is not None and score != "" else None
    except (TypeError, ValueError):
        score = None
    return {
        "id": attachment_id,
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
        "file_ext": clean_resource_ext(
            value.get("file_ext"), attachment_name, attachment_url
        ),
        "attachment_size": int(
            value.get("attachment_size") or value.get("file_size") or 0
        ),
        "score": score,
        "feedback": _clean_answer_text(value.get("feedback")),
        "evaluated_at": value.get("evaluated_at"),
    }


def _score_lesson_question(question: dict, value) -> dict:
    question_type = str(question.get("question_type") or "")
    expected = _answer_to_list(question.get("answer"))
    actual = [] if question_type == "file" else _answer_to_list(value)
    max_score = _score_float(question.get("score"))
    answer_text = _answer_display(value)
    auto_gradable = question_type in {"single", "multiple", "judge", "blank"} and bool(
        expected
    )
    attachment = _answer_attachment_value(value) if question_type == "file" else None
    is_correct = None
    score = attachment.get("score") if attachment else None

    if auto_gradable:
        if question_type == "multiple":
            is_correct = sorted(actual) == sorted(expected)
        elif question_type == "blank":
            is_correct = bool(actual) and (
                actual[0] in expected or sorted(actual) == sorted(expected)
            )
        else:
            is_correct = bool(actual) and actual[0] == expected[0]
        score = max_score if is_correct else 0

    return {
        "question_id": str(question.get("id") or ""),
        "question_type": question_type,
        "question_type_label": question.get("question_type_label") or question_type,
        "stem": question.get("stem") or "",
        "required": bool(question.get("is_required", True)),
        "answer_values": actual,
        "answer_text": answer_text,
        "is_answered": _question_answered(value),
        "auto_gradable": auto_gradable,
        "is_correct": is_correct,
        "score": score,
        "max_score": max_score,
        "attachment": attachment,
    }


def _lesson_step_answer_progress(questions: list[dict], answer) -> dict:
    answer_rows = []
    answered_count = 0
    auto_score = 0.0
    auto_score_max = 0.0
    auto_gradable_count = 0
    correct_count = 0
    for question in questions:
        value = _question_answer_value(answer, str(question.get("id") or ""))
        row = _score_lesson_question(question, value)
        answer_rows.append(row)
        if row["is_answered"]:
            answered_count += 1
        if row["auto_gradable"]:
            auto_gradable_count += 1
            auto_score_max += _score_float(row["max_score"])
            auto_score += _score_float(row["score"])
            if row["is_correct"]:
                correct_count += 1
    return {
        "answers": answer_rows,
        "text": _answer_text_value(answer),
        "answered_count": answered_count,
        "question_count": len(questions),
        "required_count": sum(
            1 for question in questions if question.get("is_required", True)
        ),
        "auto_score": round(auto_score, 2),
        "auto_score_max": round(auto_score_max, 2),
        "auto_gradable_count": auto_gradable_count,
        "correct_count": correct_count,
    }


















































def _teacher_notices(request):
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    status = request.GET.get("status", "").strip()
    notices = (
        Notice.objects.filter(school=_school(request), teacher=request.user)
        .prefetch_related("target_classes")
        .order_by("-is_pinned", "-published_at", "-created_at")
    )
    if query:
        notices = notices.filter(
            Q(title__icontains=query) | Q(content__icontains=query)
        )
    if status:
        notices = notices.filter(status=status)
    if class_id:
        try:
            selected_class_id = int(class_id)
        except ValueError:
            return None, fail(
                "班级筛选条件不正确。",
                errors={"class": ["班级筛选条件不正确。"]},
                status=400,
            )
        if selected_class_id not in set(_teacher_class_ids(request)):
            return None, fail(
                "无权查看该班级公告。",
                errors={"class": ["无权查看该班级公告。"]},
                status=403,
            )
        notices = notices.filter(target_classes__id=selected_class_id)
    return notices.distinct(), None


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_notices(request):
    if request.method == "POST":
        try:
            notice = save_teacher_notice(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        notice = Notice.objects.prefetch_related("target_classes").get(pk=notice.pk)
        return ok(notice_row(notice), "公告已创建", status=201)

    notices, error_response = _teacher_notices(request)
    if error_response is not None:
        return error_response
    page = _paginate(request, notices)
    page.object_list = [notice_row(notice) for notice in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_notice_detail(request, pk):
    notice = (
        Notice.objects.filter(pk=pk, school=_school(request), teacher=request.user)
        .prefetch_related("target_classes")
        .first()
    )
    if notice is None:
        return fail("公告不存在或无权操作。", status=404)

    if request.method == "GET":
        return ok(notice_row(notice))
    if request.method == "PATCH":
        try:
            notice = save_teacher_notice(request, request.data, notice=notice)
        except ServiceError as exc:
            return _service_fail(exc)
        notice = Notice.objects.prefetch_related("target_classes").get(pk=notice.pk)
        return ok(notice_row(notice), "公告已更新")

    try:
        delete_teacher_notice(request, notice)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "公告已删除")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_notice_publish(request, pk):
    notice = (
        Notice.objects.filter(pk=pk, school=_school(request), teacher=request.user)
        .prefetch_related("target_classes")
        .first()
    )
    if notice is None:
        return fail("公告不存在或无权操作。", status=404)
    try:
        notice = publish_teacher_notice(request, notice)
    except ServiceError as exc:
        return _service_fail(exc)
    notice = Notice.objects.prefetch_related("target_classes").get(pk=notice.pk)
    return ok(notice_row(notice), "公告已发布")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_notice_archive(request, pk):
    notice = (
        Notice.objects.filter(pk=pk, school=_school(request), teacher=request.user)
        .prefetch_related("target_classes")
        .first()
    )
    if notice is None:
        return fail("公告不存在或无权操作。", status=404)
    notice = archive_teacher_notice(request, notice)
    notice = Notice.objects.prefetch_related("target_classes").get(pk=notice.pk)
    return ok(notice_row(notice), "公告已归档")


def _teacher_feedback_items(request):
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    status = request.GET.get("status", "").strip()
    category = request.GET.get("category", "").strip()
    feedback_items = (
        Feedback.objects.filter(school=_school(request), teacher=request.user)
        .select_related("student", "class_group")
        .order_by("-created_at")
    )
    if query:
        feedback_items = feedback_items.filter(
            Q(title__icontains=query)
            | Q(content__icontains=query)
            | Q(student__username__icontains=query)
            | Q(student__display_name__icontains=query)
        )
    if status:
        feedback_items = feedback_items.filter(status=status)
    if category:
        feedback_items = feedback_items.filter(category=category)
    if class_id:
        try:
            selected_class_id = int(class_id)
        except ValueError:
            return None, fail(
                "班级筛选条件不正确。",
                errors={"class": ["班级筛选条件不正确。"]},
                status=400,
            )
        if selected_class_id not in set(_teacher_class_ids(request)):
            return None, fail(
                "无权查看该班级反馈。",
                errors={"class": ["无权查看该班级反馈。"]},
                status=403,
            )
        feedback_items = feedback_items.filter(class_group_id=selected_class_id)
    return feedback_items, None


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_feedback_items(request):
    feedback_items, error_response = _teacher_feedback_items(request)
    if error_response is not None:
        return error_response
    page = _paginate(request, feedback_items)
    page.object_list = [feedback_row(item) for item in page.object_list]
    return ok(page_data(page))


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_feedback_detail(request, pk):
    feedback = (
        Feedback.objects.filter(pk=pk, school=_school(request), teacher=request.user)
        .select_related("student", "class_group")
        .first()
    )
    if feedback is None:
        return fail("留言反馈不存在或无权查看。", status=404)
    return ok(feedback_row(feedback))


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_feedback_reply(request, pk):
    feedback = (
        Feedback.objects.filter(pk=pk, school=_school(request), teacher=request.user)
        .select_related("student", "class_group")
        .first()
    )
    if feedback is None:
        return fail("留言反馈不存在或无权操作。", status=404)
    try:
        feedback = reply_teacher_feedback(request, feedback, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(feedback_row(feedback), "留言反馈已回复")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_feedback_close(request, pk):
    feedback = (
        Feedback.objects.filter(pk=pk, school=_school(request), teacher=request.user)
        .select_related("student", "class_group")
        .first()
    )
    if feedback is None:
        return fail("留言反馈不存在或无权操作。", status=404)
    feedback = close_teacher_feedback(request, feedback)
    return ok(feedback_row(feedback), "留言反馈已关闭")


def _student_profile(request) -> StudentProfile:
    profile = (
        StudentProfile.objects.select_related(
            "user", "class_group", "class_group__school"
        )
        .filter(user=request.user, user__school=_school(request))
        .first()
    )
    if profile is None:
        raise ServiceError("学生档案不存在，请联系学校管理员。", status=404)
    return profile


def _student_course_band(profile: StudentProfile, course: Course | None) -> str | None:
    if course is None or course.subject_id is None:
        return None
    return resolve_student_band(
        student=profile.user,
        subject=course.subject,
        course=course,
    )




def _student_current_classroom(profile: StudentProfile) -> ClassroomSession | None:
    if not profile.class_group_id:
        return None
    session = (
        ClassroomSession.objects.select_related(
            "teacher",
            "course",
            "course__subject",
            "lesson",
            "class_group",
            "current_step",
            "current_step__lesson",
        )
        .filter(
            school=profile.user.school,
            class_group=profile.class_group,
            status=ClassroomSession.Status.RUNNING,
        )
        .order_by("-started_at", "-created_at")
        .first()
    )
    if session is not None:
        session.prefetched_activities = list(
            session.activities.filter(status=ClassroomActivity.Status.OPEN).order_by(
                "-opened_at", "-created_at"
            )
        )
    return session


def _student_required_pretest_status(user, subject: Subject | None) -> dict:
    if subject is None:
        return {"required": False, "completed": True, "missing": []}

    papers = list(
        PretestPaper.objects.filter(
            school=user.school,
            subject=subject,
            status=PretestPaper.Status.PUBLISHED,
        ).order_by("kind", "-version")
    )
    if not papers:
        return {"required": False, "completed": True, "missing": []}

    latest_by_kind: dict[str, PretestPaper] = {}
    for paper in papers:
        latest_by_kind.setdefault(paper.kind, paper)

    submitted_paper_ids = set(
        PretestSubmission.objects.filter(
            student=user, paper_id__in=[paper.id for paper in latest_by_kind.values()]
        ).values_list("paper_id", flat=True)
    )
    missing = [
        {
            "kind": paper.kind,
            "kind_label": paper.get_kind_display(),
            "paper_id": paper.id,
            "title": paper.title,
        }
        for paper in latest_by_kind.values()
        if paper.id not in submitted_paper_ids
    ]
    return {
        "required": bool(latest_by_kind),
        "completed": not missing,
        "missing": missing,
    }










def _student_lesson_classroom_session(
    profile: StudentProfile, lesson: Lesson
) -> ClassroomSession | None:
    if not profile.class_group_id:
        return None
    return (
        ClassroomSession.objects.select_related(
            "teacher",
            "course",
            "course__subject",
            "lesson",
            "class_group",
            "current_step",
        )
        .filter(
            school=profile.user.school, class_group=profile.class_group, lesson=lesson
        )
        .order_by("-created_at", "-id")
        .first()
    )




def _ensure_student_step_classroom_open(
    profile: StudentProfile, step: LessonStep, *, for_answer: bool = False
) -> ClassroomSession:
    session = _student_lesson_classroom_session(profile, step.lesson)
    if session is None:
        raise ServiceError("该课时尚未启用课堂教学，暂不能学习该环节。", status=403)
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("课堂尚未开始，暂不能学习该环节。", status=403)
    if (
        session.current_step_id != step.id
        or session.current_step_status == ClassroomSession.StepStatus.IDLE
    ):
        raise ServiceError("教师尚未投放该环节。", status=403)
    if session.current_step_status == ClassroomSession.StepStatus.CLOSED:
        raise ServiceError("当前环节已关闭。", status=403)
    if for_answer and session.submission_locked:
        raise ServiceError("当前环节已锁定提交。", status=403)
    return session




def _lesson_step_contains_learning_web_page(
    step: LessonStep | None, page_id: int
) -> bool:
    if step is None or not isinstance(step.resource_items, list):
        return False
    for item in step.resource_items:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "learning_page":
            continue
        try:
            if int(item.get("learning_page_id") or 0) == page_id:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _student_learning_web_page_context(request, page_id, *, for_submit: bool = False):
    profile = _student_profile(request)
    page = (
        LearningWebPage.objects.select_related("school", "teacher", "course", "lesson")
        .filter(
            pk=page_id,
            school=request.user.school,
            is_active=True,
            status=LearningWebPage.Status.READY,
        )
        .first()
    )
    if page is None:
        raise ServiceError("学习网页不存在或已停用。", status=404)
    session = _student_current_classroom(profile)
    if (
        session is None
        or session.course_id != page.course_id
        or session.lesson_id != page.lesson_id
    ):
        raise ServiceError("该学习网页不属于当前课堂。", status=403)
    step = session.current_step
    if step is None or not _lesson_step_contains_learning_web_page(step, page.id):
        raise ServiceError("教师尚未投放该学习网页。", status=403)
    _ensure_student_step_classroom_open(profile, step, for_answer=for_submit)
    return profile, page, session, step


















STUDENT_ARCHIVE_EVENT_LABELS = {
    LearningEvent.EventType.LOGIN: "登录平台",
    LearningEvent.EventType.PAGE_VIEW: "浏览学习内容",
    LearningEvent.EventType.RESOURCE_VIEW: "查看学习资源",
    LearningEvent.EventType.LESSON_ENTER: "进入课时学习",
    LearningEvent.EventType.ANSWER_SUBMIT: "提交学习作答",
    LearningEvent.EventType.TASK_SUBMIT: "提交课堂作品",
    LearningEvent.EventType.PROJECT_SUBMIT: "提交项目成果",
    LearningEvent.EventType.CHAT_MESSAGE: "参与课堂交流",
    LearningEvent.EventType.QUESTION_ASK: "提出问题",
    LearningEvent.EventType.QUESTION_ANSWER: "参与回答",
}
















































def _student_classroom_resource_context(request, session_id):
    profile = _student_profile(request)
    session = (
        ClassroomSession.objects.select_related(
            "teacher",
            "course",
            "course__subject",
            "lesson",
            "class_group",
            "current_step",
            "current_step__lesson",
        )
        .filter(
            pk=session_id,
            school=request.user.school,
            class_group=profile.class_group,
        )
        .first()
    )
    if session is None:
        raise ServiceError("课堂不存在或无权进入。", status=404)
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("课堂尚未开始或已经结束。", status=403)
    if not session.current_step_id:
        raise ServiceError("教师尚未投放学习环节。", status=403)
    if session.current_step_status in {
        ClassroomSession.StepStatus.IDLE,
        ClassroomSession.StepStatus.CLOSED,
    }:
        raise ServiceError("当前学习环节尚未开放或已经关闭。", status=403)
    ensure_classroom_step_opportunities(session=session)
    return profile, session, session.current_step


# Compatibility re-exports. New code should import from the domain modules.
from .course_views import (
    _learning_web_page_response_summary,
    _teacher_course_rows,
    _teacher_courses_queryset,
    _teacher_learning_web_page,
    _teacher_lesson_steps_queryset,
    _teacher_lessons_queryset,
    learning_web_page_view,
    teacher_course_archive,
    teacher_course_classes,
    teacher_course_cover,
    teacher_course_detail,
    teacher_course_evaluation,
    teacher_course_evaluation_ai_generate,
    teacher_course_evaluation_submit,
    teacher_course_lessons,
    teacher_course_options,
    teacher_course_publish,
    teacher_courses,
    teacher_learning_web_page_detail,
    teacher_learning_web_page_responses,
    teacher_learning_web_page_revise,
    teacher_lesson_archive,
    teacher_lesson_detail,
    teacher_lesson_learning_web_pages,
    teacher_lesson_publish,
    teacher_lesson_step_ai_generate_questions,
    teacher_lesson_step_detail,
    teacher_lesson_steps,
    teacher_lesson_steps_reorder,
)
from .classroom_views import (
    _archive_active_classroom_groups,
    _attendance_events_for_activity,
    _blank_docx_bytes,
    _blank_office_bytes,
    _blank_pptx_bytes,
    _blank_xlsx_bytes,
    _bool_value,
    _classroom_student_profiles,
    _download_onlyoffice_callback_file,
    _ensure_group_document,
    _generate_classroom_groups,
    _generate_classroom_groups_from_assignments,
    _group_document_access,
    _group_document_bytes,
    _group_document_key,
    _grouping_candidate_run_row,
    _int_in_range,
    _office_group,
    _onlyoffice_callback_token,
    _peer_possible_count,
    _quick_answer_defaults,
    _quick_answer_response_events,
    _quick_answer_score_events,
    _random_pick_score_events,
    _save_group_document_version,
    _setup_classroom_group_collaboration,
    _student_profiles_for_grouping,
    _teacher_attendance_payload,
    _teacher_classroom_group,
    _teacher_classroom_sessions,
    _teacher_classroom_step_progress_payload,
    _teacher_evaluation_payload,
    _teacher_quick_answer_payload,
    _teacher_random_pick_payload,
    _teacher_random_pick_preview_payload,
    _teacher_random_pick_student_rows,
    _url_origin,
    _verified_onlyoffice_editor_ids,
    _with_prefetched_groups,
    _write_group_document_open_event,
    _zip_content,
    classroom_group_office_callback,
    classroom_group_office_config,
    teacher_classroom_activities,
    teacher_classroom_activity_close,
    teacher_classroom_activity_detail,
    teacher_classroom_activity_open,
    teacher_classroom_attachment_score,
    teacher_classroom_attendance,
    teacher_classroom_attendance_mark,
    teacher_classroom_command,
    teacher_classroom_evaluation,
    teacher_classroom_evaluation_ai_generate,
    teacher_classroom_evaluation_submit,
    teacher_classroom_group_collaboration,
    teacher_classroom_group_collaboration_close,
    teacher_classroom_group_collaboration_setup,
    teacher_classroom_group_files,
    teacher_classroom_grouping_candidates,
    teacher_classroom_grouping_confirm,
    teacher_classroom_quick_answer,
    teacher_classroom_quick_answer_score,
    teacher_classroom_random_pick,
    teacher_classroom_random_pick_preview,
    teacher_classroom_random_pick_score,
    teacher_classroom_session_detail,
    teacher_classroom_session_finish,
    teacher_classroom_session_restart,
    teacher_classroom_session_start,
    teacher_classroom_sessions,
    teacher_classroom_step_close,
    teacher_classroom_step_lock,
    teacher_classroom_step_open,
    teacher_classroom_step_progress,
)
from .pretest_views import (
    _school_pretest_papers,
    school_admin_pretest_paper_archive,
    school_admin_pretest_paper_detail,
    school_admin_pretest_paper_publish,
    school_admin_pretest_papers,
    school_admin_pretest_question_detail,
    school_admin_pretest_questions,
    student_pretest_paper,
    student_pretests_for_subject,
    student_pretests_required,
)
from .resource_views import (
    _resource_can_open,
    _resource_file_ext,
    _resource_rows_queryset,
    _student_resource_access_q,
    resource_office_callback,
    resource_office_config,
    school_admin_resource_reviews,
    student_classroom_resource_opened,
    student_resource_detail,
    student_resources,
    teacher_resource_detail,
    teacher_resource_extra_file,
    teacher_resources,
)
from .student_views import (
    _clean_learning_web_page_answers,
    _ensure_student_can_learn_course,
    _ensure_student_lesson_workspace_allowed,
    _finite_request_number,
    _learning_web_page_form,
    _student_archive_event_label,
    _student_course,
    _student_course_queryset,
    _student_dashboard_data,
    _student_evaluation_context,
    _student_evaluation_payload,
    _student_group_collaboration_context,
    _student_lesson,
    _student_lesson_step,
    _student_profile_archive_data,
    _student_step_question,
    _student_teachers,
    _teacher_student_ids_from_payload,
    _teacher_students,
    _validate_student_work_file,
    school_admin_student_detail,
    school_admin_student_reset_password,
    school_admin_student_set_active,
    school_admin_students,
    school_admin_students_bulk_delete,
    school_admin_students_bulk_disable,
    school_admin_students_export,
    school_admin_students_import,
    school_admin_students_template,
    student_classroom_activity_response,
    student_classroom_detail,
    student_classroom_document_progress,
    student_classroom_evaluation,
    student_classroom_evaluation_submit,
    student_classroom_group_collaboration,
    student_classroom_group_file_upload,
    student_classroom_score_feedback_ack,
    student_classroom_video_progress,
    student_course_detail,
    student_course_lessons,
    student_courses,
    student_current_classroom,
    student_dashboard,
    student_feedback,
    student_feedback_detail,
    student_learning_web_page_block_viewed,
    student_learning_web_page_submit,
    student_lesson_enter,
    student_lesson_step_answer,
    student_lesson_step_attachment,
    student_lesson_step_complete,
    student_lesson_step_enter,
    student_lesson_workspace,
    student_me,
    student_notices,
    student_onboarding,
    student_onboarding_class,
    student_onboarding_classes,
    student_onboarding_password,
    student_profile_archive,
    teacher_student_reset_password,
    teacher_students,
    teacher_students_bulk_reset_password,
)
