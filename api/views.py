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
def school_admin_students(request):
    if request.method == "POST":
        try:
            profile = create_student(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(student_row(profile), "学生已创建", status=201)

    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    status = request.GET.get("status", "").strip()
    layer = request.GET.get("layer", "").strip()
    students = StudentProfile.objects.filter(
        user__school=_school(request)
    ).select_related("user", "class_group")
    if query:
        students = students.filter(
            Q(user__username__icontains=query)
            | Q(user__display_name__icontains=query)
            | Q(student_no__icontains=query)
        )
    if class_id:
        students = students.filter(class_group_id=class_id)
    if status == "active":
        students = students.filter(user__is_active=True)
    elif status == "disabled":
        students = students.filter(user__is_active=False)
    if layer in {"A", "B", "C"}:
        students = students.filter(current_layer=layer)
    elif layer == "unassigned":
        students = students.filter(current_layer__isnull=True)
    page = _paginate(
        request,
        students.order_by("class_group__grade", "class_group__name", "student_no"),
    )
    page.object_list = [student_row(profile) for profile in page.object_list]
    return ok(page_data(page))


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_students_export(request):
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    status = request.GET.get("status", "").strip()
    layer = request.GET.get("layer", "").strip()
    students = StudentProfile.objects.filter(
        user__school=_school(request)
    ).select_related("user", "class_group")
    if query:
        students = students.filter(
            Q(user__username__icontains=query)
            | Q(user__display_name__icontains=query)
            | Q(student_no__icontains=query)
        )
    if class_id:
        students = students.filter(class_group_id=class_id)
    if status == "active":
        students = students.filter(user__is_active=True)
    elif status == "disabled":
        students = students.filter(user__is_active=False)
    if layer in {"A", "B", "C"}:
        students = students.filter(current_layer=layer)
    elif layer == "unassigned":
        students = students.filter(current_layer__isnull=True)
    rows = [
        [
            profile.user.username,
            profile.user.display_name,
            profile.student_no,
            profile.class_group.name if profile.class_group_id else "",
            profile.user.phone,
            profile.current_layer or "",
            profile.current_group_no or "",
            profile.score,
            profile.get_onboarding_status_display(),
            "启用" if profile.user.is_active else "停用",
            profile.user.last_login,
            profile.updated_at,
        ]
        for profile in students.order_by(
            "class_group__grade", "class_group__name", "student_no"
        )
    ]
    return export_rows(
        _xlsx_filename(f"{_school(request).code}_学生管理"),
        "学生管理",
        [
            "登录账号",
            "姓名",
            "学号",
            "班级",
            "联系电话",
            "层级",
            "小组号",
            "积分",
            "首次使用状态",
            "账号状态",
            "最近登录",
            "更新时间",
        ],
        rows,
    )


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_students_template(request):
    return template_response(
        "学生批量导入模板.xlsx",
        "学生导入模板",
        STUDENT_IMPORT_HEADERS,
        [["student1", "李同学", "", "高一1班", "", "123456", "", "", "0", "启用"]],
        instructions=[
            "登录账号和姓名必填；新增学生必须填写初始密码。",
            "班级、学号、层级都可以留空；新生没有学号时可先不填。",
            "再次导入相同登录账号时，系统会按账号更新学号、班级、联系电话、层级、小组号、积分和状态。",
            "班级按班级名称匹配，例如：高一1班。",
        ],
        dropdowns={"状态": ["启用", "停用"], "层级": ["", "A", "B", "C"]},
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_students_import(request):
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
        result = import_students_from_xlsx(request, uploaded_file)
    except ServiceError as exc:
        return _service_fail(exc)
    except ValueError as exc:
        return fail(str(exc), errors={"file": [str(exc)]}, status=400)
    return ok(
        result,
        f"学生批量导入完成：新增 {result['created_count']} 个，更新 {result['updated_count']} 个。",
    )


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_students_bulk_disable(request):
    try:
        result = bulk_disable_students(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, f"已停用 {result['updated_count']} 个学生账号。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_students_bulk_delete(request):
    try:
        result = bulk_delete_students(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(result, result["message"])


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_student_detail(request, pk):
    profile = (
        StudentProfile.objects.filter(pk=pk, user__school=_school(request))
        .select_related("user", "class_group")
        .first()
    )
    if profile is None:
        return fail("学生不存在。", status=404)

    if request.method == "GET":
        return ok(student_row(profile))
    if request.method == "PATCH":
        try:
            profile = update_student(request, profile, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(student_row(profile), "学生已更新")

    try:
        delete_student(request, profile)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "学生已删除")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_student_set_active(request, pk):
    profile = (
        StudentProfile.objects.filter(pk=pk, user__school=_school(request))
        .select_related("user", "class_group")
        .first()
    )
    if profile is None:
        return fail("学生不存在。", status=404)
    set_student_active(request, profile, bool(request.data.get("is_active")))
    return ok(student_row(profile), "学生状态已更新")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_student_reset_password(request, pk):
    profile = (
        StudentProfile.objects.filter(pk=pk, user__school=_school(request))
        .select_related("user", "class_group")
        .first()
    )
    if profile is None:
        return fail("学生不存在。", status=404)
    try:
        reset_student_password(request, profile, str(request.data.get("password", "")))
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(student_row(profile), "密码已重置")


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


def _school_pretest_papers(request):
    subject_id = request.GET.get("subject", "").strip()
    kind = request.GET.get("kind", "").strip()
    status = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()
    papers = (
        PretestPaper.objects.filter(school=_school(request))
        .select_related("subject")
        .annotate(
            question_count=Count("questions", distinct=True),
            submission_count=Count("submissions", distinct=True),
        )
    )
    if subject_id:
        papers = papers.filter(subject_id=subject_id)
    if kind:
        papers = papers.filter(kind=kind)
    if status:
        papers = papers.filter(status=status)
    if query:
        papers = papers.filter(
            Q(title__icontains=query)
            | Q(subject__name__icontains=query)
            | Q(subject__code__icontains=query)
        )
    return papers.order_by("subject__name", "kind", "-version", "-created_at")


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_papers(request):
    if request.method == "POST":
        try:
            paper = save_pretest_paper(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        paper.question_count = 0
        paper.submission_count = 0
        return ok(pretest_paper_row(paper), "前测套卷已创建", status=201)

    page = _paginate(request, _school_pretest_papers(request))
    page.object_list = [pretest_paper_row(paper) for paper in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_paper_detail(request, pk):
    paper = (
        PretestPaper.objects.filter(pk=pk, school=_school(request))
        .select_related("subject")
        .prefetch_related("questions")
        .annotate(
            question_count=Count("questions", distinct=True),
            submission_count=Count("submissions", distinct=True),
        )
        .first()
    )
    if paper is None:
        return fail("前测套卷不存在。", status=404)

    if request.method == "GET":
        return ok(pretest_paper_row(paper, include_questions=True))
    if request.method == "PATCH":
        try:
            paper = save_pretest_paper(request, request.data, paper=paper)
        except ServiceError as exc:
            return _service_fail(exc)
        paper.question_count = paper.questions.count()
        paper.submission_count = paper.submissions.count()
        return ok(pretest_paper_row(paper), "前测套卷已更新")

    try:
        delete_pretest_paper(request, paper)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "前测套卷已删除")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_paper_publish(request, pk):
    paper = (
        PretestPaper.objects.filter(pk=pk, school=_school(request))
        .select_related("subject")
        .first()
    )
    if paper is None:
        return fail("前测套卷不存在。", status=404)
    try:
        paper = publish_pretest_paper(request, paper)
    except ServiceError as exc:
        return _service_fail(exc)
    paper.question_count = paper.questions.count()
    paper.submission_count = paper.submissions.count()
    return ok(pretest_paper_row(paper), "前测套卷已发布")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_paper_archive(request, pk):
    paper = (
        PretestPaper.objects.filter(pk=pk, school=_school(request))
        .select_related("subject")
        .first()
    )
    if paper is None:
        return fail("前测套卷不存在。", status=404)
    paper = archive_pretest_paper(request, paper)
    paper.question_count = paper.questions.count()
    paper.submission_count = paper.submissions.count()
    return ok(pretest_paper_row(paper), "前测套卷已归档")


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_questions(request, paper_id):
    paper = (
        PretestPaper.objects.filter(pk=paper_id, school=_school(request))
        .select_related("subject")
        .first()
    )
    if paper is None:
        return fail("前测套卷不存在。", status=404)
    if request.method == "POST":
        try:
            question = save_pretest_question(request, paper, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(pretest_question_row(question), "题目已创建", status=201)

    questions = paper.questions.order_by("sort_order", "id")
    return ok([pretest_question_row(question) for question in questions])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_question_detail(request, paper_id, pk):
    question = (
        PretestQuestion.objects.filter(
            pk=pk, paper_id=paper_id, paper__school=_school(request)
        )
        .select_related("paper", "paper__subject")
        .first()
    )
    if question is None:
        return fail("题目不存在。", status=404)

    if request.method == "PATCH":
        try:
            question = save_pretest_question(
                request, question.paper, request.data, question=question
            )
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(pretest_question_row(question), "题目已更新")

    try:
        delete_pretest_question(request, question)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "题目已删除")


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


def _teacher_students(request):
    class_ids = _teacher_class_ids(request)
    return StudentProfile.objects.filter(
        user__school=_school(request),
        class_group_id__in=class_ids,
    ).select_related("user", "class_group")


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


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_students(request):
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    status = request.GET.get("status", "").strip()
    layer = request.GET.get("layer", "").strip()
    students = _teacher_students(request)
    class_ids = set(_teacher_class_ids(request))

    if query:
        students = students.filter(
            Q(user__username__icontains=query)
            | Q(user__display_name__icontains=query)
            | Q(student_no__icontains=query)
        )
    if class_id:
        try:
            selected_class_id = int(class_id)
        except ValueError:
            return fail(
                "班级筛选条件不正确。",
                errors={"class": ["班级筛选条件不正确。"]},
                status=400,
            )
        if selected_class_id not in class_ids:
            return fail(
                "无权查看该班级。", errors={"class": ["无权查看该班级。"]}, status=403
            )
        students = students.filter(class_group_id=selected_class_id)
    if status == "active":
        students = students.filter(user__is_active=True)
    elif status == "disabled":
        students = students.filter(user__is_active=False)
    if layer in {"A", "B", "C"}:
        students = students.filter(current_layer=layer)
    elif layer == "unassigned":
        students = students.filter(current_layer__isnull=True)

    page = _paginate(
        request,
        students.order_by(
            "class_group__grade", "class_group__name", "student_no", "user__username"
        ),
    )
    page.object_list = [student_row(profile) for profile in page.object_list]
    return ok(page_data(page))


def _teacher_student_ids_from_payload(request):
    raw_ids = request.data.get("ids") if hasattr(request.data, "get") else None
    if not isinstance(raw_ids, list):
        raise ServiceError(
            "请选择要操作的学生。", errors={"ids": ["请选择要操作的学生。"]}, status=400
        )

    ids: list[int] = []
    for raw_id in raw_ids:
        try:
            student_id = int(raw_id)
        except (TypeError, ValueError):
            raise ServiceError(
                "所选学生包含无效编号。",
                errors={"ids": ["所选学生包含无效编号。"]},
                status=400,
            )
        if student_id <= 0:
            raise ServiceError(
                "所选学生包含无效编号。",
                errors={"ids": ["所选学生包含无效编号。"]},
                status=400,
            )
        if student_id not in ids:
            ids.append(student_id)

    if not ids:
        raise ServiceError(
            "请选择要操作的学生。", errors={"ids": ["请选择要操作的学生。"]}, status=400
        )
    if len(ids) > 100:
        raise ServiceError(
            "单次最多重置 100 个学生密码。",
            errors={"ids": ["单次最多重置 100 个学生密码。"]},
            status=400,
        )
    return ids


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_student_reset_password(request, pk):
    profile = _teacher_students(request).filter(pk=pk).first()
    if profile is None:
        return fail("学生不存在或不在你的任教班级中。", status=404)
    if not profile.user.is_active:
        return fail("学生账号已停用，请联系学校管理员处理。", status=400)

    profile.user.set_password("123456")
    profile.user.is_first_login = True
    profile.user.save(update_fields=["password", "is_first_login"])
    write_audit(
        request,
        "teacher.student.reset_password",
        school=_school(request),
        target_type="student_profile",
        target_id=profile.id,
        detail={
            "username": profile.user.username,
            "class_group": profile.class_group.name if profile.class_group_id else "",
            "reset_to_default": True,
        },
    )
    return ok(student_row(profile), "学生密码已重置为 123456。")


@api_view(["POST"])
@permission_classes([IsTeacher])
@transaction.atomic
def teacher_students_bulk_reset_password(request):
    try:
        ids = _teacher_student_ids_from_payload(request)
    except ServiceError as exc:
        return _service_fail(exc)

    profiles = list(
        _teacher_students(request)
        .filter(pk__in=ids)
        .order_by("class_group__grade", "class_group__name", "student_no")
    )
    found_ids = {profile.id for profile in profiles}
    missing = [str(student_id) for student_id in ids if student_id not in found_ids]
    if missing:
        return fail(
            "部分学生不存在或不在你的任教班级中。",
            errors={"ids": [f"无权操作：{', '.join(missing)}"]},
            status=404,
        )

    inactive = [profile for profile in profiles if not profile.user.is_active]
    if inactive:
        names = ", ".join(
            profile.user.display_name or profile.user.username
            for profile in inactive[:10]
        )
        return fail(
            "所选学生包含停用账号，请联系学校管理员处理。",
            errors={"ids": [f"停用账号：{names}"]},
            status=400,
        )

    for profile in profiles:
        profile.user.set_password("123456")
        profile.user.is_first_login = True
        profile.user.save(update_fields=["password", "is_first_login"])

    write_audit(
        request,
        "teacher.student.bulk_reset_password",
        school=_school(request),
        target_type="student_profile",
        detail={
            "ids": ids,
            "count": len(profiles),
            "reset_to_default": True,
        },
    )
    return ok(
        {
            "updated_count": len(profiles),
            "results": [student_row(profile) for profile in profiles],
        },
        f"已将 {len(profiles)} 个学生密码重置为 123456。",
    )


def _teacher_courses_queryset(request):
    return (
        Course.objects.filter(teacher=request.user, teacher__school=_school(request))
        .select_related("subject", "teacher")
        .annotate(
            lesson_count=Count("lessons", distinct=True),
            class_count=Count("course_classes", distinct=True),
            session_count=Count("classroom_sessions", distinct=True),
        )
        .prefetch_related(
            Prefetch(
                "course_classes",
                queryset=CourseClass.objects.select_related("class_group").order_by(
                    "class_group__grade", "class_group__name"
                ),
                to_attr="prefetched_course_classes",
            )
        )
    )


def _teacher_course_rows(request):
    query = request.GET.get("q", "").strip()
    subject_id = request.GET.get("subject", "").strip()
    status = request.GET.get("status", "").strip()
    courses = _teacher_courses_queryset(request).order_by("-updated_at", "-created_at")
    if query:
        courses = courses.filter(
            Q(title__icontains=query) | Q(introduction__icontains=query)
        )
    if subject_id:
        try:
            courses = courses.filter(subject_id=int(subject_id))
        except ValueError:
            return None, fail(
                "学科筛选条件不正确。",
                errors={"subject": ["学科筛选条件不正确。"]},
                status=400,
            )
    if status == "published":
        courses = courses.filter(is_active=True)
    elif status == "draft":
        courses = courses.filter(is_active=False)
    elif status:
        return None, fail(
            "状态筛选条件不正确。",
            errors={"status": ["状态筛选条件不正确。"]},
            status=400,
        )
    return courses, None


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_course_options(request):
    courses = (
        _teacher_courses_queryset(request)
        .filter(course_classes__isnull=False)
        .prefetch_related(
            Prefetch(
                "lessons",
                queryset=Lesson.objects.order_by("sort_order", "id"),
                to_attr="prefetched_lessons",
            )
        )
        .distinct()
        .order_by("-is_active", "-updated_at")
    )
    return ok(
        {
            "subjects": [
                subject_row(subject)
                for subject in Subject.objects.filter(
                    school=_school(request), is_active=True
                ).annotate(
                    course_count=Count("courses", distinct=True),
                    pretest_count=Count("pretest_papers", distinct=True),
                )
            ],
            "classes": [
                class_group_row(class_group)
                for class_group in _teacher_classes(request)
            ],
            "courses": [course_row(course, include_lessons=True) for course in courses],
            "activity_types": [
                {"value": value, "label": label}
                for value, label in ClassroomActivity.ActivityType.choices
            ],
        }
    )


OFFICE_FILE_TYPES = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}


def _resource_file_ext(resource: Resource) -> str:
    if not resource.attachment:
        return ""
    name = resource.attachment.name.rsplit("/", 1)[-1]
    return clean_resource_ext(name, resource.attachment.url)


def _office_document_type(file_ext: str) -> str:
    if file_ext in {"ppt", "pptx"}:
        return "slide"
    if file_ext in {"xls", "xlsx"}:
        return "cell"
    return "word"


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


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_courses(request):
    if request.method == "POST":
        try:
            course = save_teacher_course(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        course = _teacher_courses_queryset(request).get(pk=course.pk)
        return ok(course_row(course), "课程已创建", status=201)

    courses, error_response = _teacher_course_rows(request)
    if error_response is not None:
        return error_response
    page = _paginate(request, courses)
    page.object_list = [course_row(course) for course in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_course_detail(request, pk):
    try:
        course = _teacher_course(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "GET":
        course = (
            _teacher_courses_queryset(request)
            .prefetch_related(
                Prefetch(
                    "lessons",
                    queryset=Lesson.objects.order_by("sort_order", "id"),
                    to_attr="prefetched_lessons",
                )
            )
            .get(pk=course.pk)
        )
        return ok(course_row(course, include_lessons=True))
    if request.method == "PATCH":
        try:
            course = save_teacher_course(request, request.data, course=course)
        except ServiceError as exc:
            return _service_fail(exc)
        course = _teacher_courses_queryset(request).get(pk=course.pk)
        return ok(course_row(course), "课程已更新")

    try:
        delete_teacher_course(request, course)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "课程已删除")


@api_view(["POST", "DELETE"])
@permission_classes([IsTeacher])
@parser_classes([MultiPartParser, FormParser])
def teacher_course_cover(request, pk):
    try:
        course = _teacher_course(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "POST":
        try:
            course = save_teacher_course_cover(
                request, course, request.FILES.get("cover")
            )
        except ServiceError as exc:
            return _service_fail(exc)
        course = _teacher_courses_queryset(request).get(pk=course.pk)
        return ok(course_row(course), "课程封面已更新")

    try:
        course = delete_teacher_course_cover(request, course)
    except ServiceError as exc:
        return _service_fail(exc)
    course = _teacher_courses_queryset(request).get(pk=course.pk)
    return ok(course_row(course), "课程封面已移除")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_course_publish(request, pk):
    try:
        course = publish_teacher_course(request, _teacher_course(request, pk))
    except ServiceError as exc:
        return _service_fail(exc)
    course = _teacher_courses_queryset(request).get(pk=course.pk)
    return ok(course_row(course), "课程已发布")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_course_archive(request, pk):
    try:
        course = archive_teacher_course(request, _teacher_course(request, pk))
    except ServiceError as exc:
        return _service_fail(exc)
    course = _teacher_courses_queryset(request).get(pk=course.pk)
    return ok(course_row(course), "课程已停用")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_course_classes(request, pk):
    try:
        course = set_teacher_course_classes(
            request, _teacher_course(request, pk), request.data
        )
    except ServiceError as exc:
        return _service_fail(exc)
    course = _teacher_courses_queryset(request).get(pk=course.pk)
    return ok(course_row(course), "课程班级范围已更新")


def _teacher_lessons_queryset(request, course):
    return (
        Lesson.objects.filter(course=course)
        .select_related("course")
        .annotate(
            activity_count=Count("activities", distinct=True),
            session_count=Count("classroom_sessions", distinct=True),
        )
        .order_by("sort_order", "id")
    )


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_course_lessons(request, course_id):
    try:
        course = _teacher_course(request, course_id)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "POST":
        try:
            lesson = save_teacher_lesson(request, course, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        lesson = _teacher_lessons_queryset(request, course).get(pk=lesson.pk)
        return ok(lesson_row(lesson), "课时已创建", status=201)

    return ok(
        [lesson_row(lesson) for lesson in _teacher_lessons_queryset(request, course)]
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_lesson_detail(request, pk):
    try:
        lesson = _teacher_lesson(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "GET":
        return ok(lesson_row(lesson))
    if request.method == "PATCH":
        try:
            lesson = save_teacher_lesson(
                request, lesson.course, request.data, lesson=lesson
            )
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(lesson_row(lesson), "课时已更新")

    try:
        delete_teacher_lesson(request, lesson)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "课时已删除")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_lesson_publish(request, pk):
    try:
        lesson = publish_teacher_lesson(request, _teacher_lesson(request, pk))
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(lesson_row(lesson), "课时已发布")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_lesson_archive(request, pk):
    try:
        lesson = archive_teacher_lesson(request, _teacher_lesson(request, pk))
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(lesson_row(lesson), "课时已停用")


def _teacher_lesson_steps_queryset(lesson):
    return LessonStep.objects.filter(lesson=lesson).order_by("sort_order", "id")


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_lesson_steps(request, lesson_id):
    try:
        lesson = _teacher_lesson(request, lesson_id)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "POST":
        try:
            step = save_lesson_step(request, lesson, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(lesson_step_row(step), "课时环节已创建", status=201)

    return ok(
        [lesson_step_row(step) for step in _teacher_lesson_steps_queryset(lesson)]
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_lesson_steps_reorder(request, lesson_id):
    try:
        lesson = _teacher_lesson(request, lesson_id)
        steps = reorder_lesson_steps(request, lesson, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok([lesson_step_row(step) for step in steps], "课时环节排序已保存")


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_lesson_step_detail(request, pk):
    step = (
        LessonStep.objects.select_related(
            "lesson", "lesson__course", "lesson__course__teacher"
        )
        .filter(
            pk=pk,
            lesson__course__teacher=request.user,
            lesson__course__teacher__school=_school(request),
        )
        .first()
    )
    if step is None:
        return fail("课时环节不存在或无权操作。", status=404)

    if request.method == "GET":
        return ok(lesson_step_row(step))
    if request.method == "PATCH":
        try:
            step = save_lesson_step(request, step.lesson, request.data, step=step)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(lesson_step_row(step), "课时环节已更新")

    try:
        delete_lesson_step(request, step)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "课时环节已删除")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_lesson_step_ai_generate_questions(request):
    try:
        payload = generate_lesson_step_questions_with_ai(request, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(payload, "AI 题目草稿已生成")


def _teacher_learning_web_page(request, pk) -> LearningWebPage:
    try:
        page_id = int(pk)
    except (TypeError, ValueError):
        page_id = 0
    page = (
        LearningWebPage.objects.select_related(
            "school", "teacher", "course", "lesson", "lesson__course"
        )
        .filter(pk=page_id, school=_school(request), teacher=request.user)
        .first()
    )
    if page is None:
        raise ServiceError("学习网页不存在或无权操作。", status=404)
    return page


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_lesson_learning_web_pages(request, lesson_id):
    try:
        lesson = _teacher_lesson(request, lesson_id)
        if request.method == "POST":
            direction = str(request.data.get("direction") or "").strip()
            generation_mode = str(request.data.get("generation_mode") or "auto").strip()
            schema = generate_learning_web_page_schema(
                request, lesson, direction, generation_mode=generation_mode
            )
            with transaction.atomic():
                page = LearningWebPage.objects.create(
                    school=_school(request),
                    teacher=request.user,
                    course=lesson.course,
                    lesson=lesson,
                    title=str(schema.get("title") or lesson.title)[:128],
                    schema=schema,
                    generation_prompt=direction,
                    revision_no=1,
                    status=LearningWebPage.Status.READY,
                )
                LearningWebPageVersion.objects.create(
                    page=page,
                    version_no=1,
                    prompt=direction,
                    schema=schema,
                    created_by=request.user,
                )
            write_audit(
                request,
                "teacher.learning_web_page.create",
                school=_school(request),
                target_type="learning_web_page",
                target_id=page.id,
                detail={
                    "lesson": lesson.id,
                    "course": lesson.course_id,
                    "form_count": learning_web_page_row(page)["form_count"],
                },
            )
            return ok(learning_web_page_row(page), "AI 学习网页已生成。", status=201)
    except ServiceError as exc:
        return _service_fail(exc)

    pages = (
        LearningWebPage.objects.filter(
            lesson=lesson, teacher=request.user, school=_school(request), is_active=True
        )
        .select_related("school", "teacher", "course", "lesson")
        .annotate(response_count=Count("responses", distinct=True))
        .order_by("-updated_at", "-id")
    )
    return ok([learning_web_page_row(page) for page in pages])


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_learning_web_page_detail(request, pk):
    try:
        page = _teacher_learning_web_page(request, pk)
        if request.method == "GET":
            row = learning_web_page_row(page)
            row["versions"] = [
                learning_web_page_version_row(item)
                for item in page.versions.select_related("created_by").all()[:20]
            ]
            return ok(row)
        if request.method == "PATCH":
            title = str(request.data.get("title") or page.title).strip()
            if len(title) < 2 or len(title) > 128:
                raise ServiceError(
                    "网页标题需为 2-128 个字符。",
                    errors={"title": ["请填写网页标题。"]},
                    status=400,
                )
            page.title = title
            page.status = LearningWebPage.Status.READY
            page.save(update_fields=["title", "status", "updated_at"])
            return ok(learning_web_page_row(page), "学习网页已保存。")
        page.is_active = False
        page.save(update_fields=["is_active", "updated_at"])
        write_audit(
            request,
            "teacher.learning_web_page.disable",
            school=page.school,
            target_type="learning_web_page",
            target_id=page.id,
            detail={"lesson": page.lesson_id},
        )
        return ok({}, "学习网页已停用，历史提交保留。")
    except ServiceError as exc:
        return _service_fail(exc)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_learning_web_page_revise(request, pk):
    try:
        page = _teacher_learning_web_page(request, pk)
        if not page.is_active:
            raise ServiceError("该学习网页已停用。", status=400)
        direction = str(request.data.get("direction") or "").strip()
        generation_mode = str(request.data.get("generation_mode") or "auto").strip()
        schema = generate_learning_web_page_schema(
            request,
            page.lesson,
            direction,
            current_page=page,
            generation_mode=generation_mode,
        )
        with transaction.atomic():
            page = LearningWebPage.objects.select_for_update().get(pk=page.pk)
            page.revision_no += 1
            page.title = str(schema.get("title") or page.title)[:128]
            page.schema = schema
            page.generation_prompt = direction
            page.status = LearningWebPage.Status.READY
            page.save(
                update_fields=[
                    "revision_no",
                    "title",
                    "schema",
                    "generation_prompt",
                    "status",
                    "updated_at",
                ]
            )
            for step in LessonStep.objects.select_for_update().filter(
                lesson=page.lesson
            ):
                items = (
                    step.resource_items if isinstance(step.resource_items, list) else []
                )
                changed = False
                updated_items = []
                for item in items:
                    if isinstance(item, dict) and item.get("kind") == "learning_page":
                        try:
                            bound_page_id = int(item.get("learning_page_id") or 0)
                        except (TypeError, ValueError):
                            bound_page_id = 0
                        if bound_page_id == page.id:
                            item = {
                                **item,
                                "title": page.title,
                                "revision_no": page.revision_no,
                            }
                            changed = True
                    updated_items.append(item)
                if changed:
                    step.resource_items = updated_items
                    step.save(update_fields=["resource_items", "updated_at"])
            LearningWebPageVersion.objects.create(
                page=page,
                version_no=page.revision_no,
                prompt=direction,
                schema=schema,
                created_by=request.user,
            )
        write_audit(
            request,
            "teacher.learning_web_page.revise",
            school=page.school,
            target_type="learning_web_page",
            target_id=page.id,
            detail={"lesson": page.lesson_id, "revision_no": page.revision_no},
        )
        return ok(
            learning_web_page_row(page), f"学习网页已更新至 v{page.revision_no}。"
        )
    except ServiceError as exc:
        return _service_fail(exc)


def _learning_web_page_response_summary(
    page: LearningWebPage, responses: list[LearningWebPageResponse]
) -> dict:
    schema = page.schema if isinstance(page.schema, dict) else {}
    blocks = schema.get("blocks") if isinstance(schema.get("blocks"), list) else []
    forms = [
        item for item in blocks if isinstance(item, dict) and item.get("type") == "form"
    ]
    form_rows = []
    for form in forms:
        form_id = str(form.get("form_id") or "")
        form_responses = [item for item in responses if item.form_id == form_id]
        fields = []
        raw_fields = form.get("fields") if isinstance(form.get("fields"), list) else []
        for field in raw_fields:
            if not isinstance(field, dict):
                continue
            field_id = str(field.get("id") or "")
            field_type = str(field.get("type") or "short_text")
            values = [
                item.answers.get(field_id)
                for item in form_responses
                if isinstance(item.answers, dict) and field_id in item.answers
            ]
            stats = {"answered": len(values)}
            if field_type in {"single", "multiple", "select", "scale"}:
                options = [str(item) for item in field.get("options", [])]
                counts = {option: 0 for option in options}
                for value in values:
                    selected = value if isinstance(value, list) else [value]
                    for selected_value in selected:
                        key = str(selected_value)
                        if key in counts:
                            counts[key] += 1
                stats["options"] = [
                    {"label": option, "count": counts[option]} for option in options
                ]
            elif field_type == "number":
                numbers = [
                    float(value) for value in values if isinstance(value, (int, float))
                ]
                stats.update(
                    {
                        "average": (
                            round(sum(numbers) / len(numbers), 2) if numbers else None
                        ),
                        "min": min(numbers) if numbers else None,
                        "max": max(numbers) if numbers else None,
                    }
                )
            else:
                recent = []
                for response in form_responses[:20]:
                    value = (
                        response.answers.get(field_id)
                        if isinstance(response.answers, dict)
                        else None
                    )
                    if value is not None and value != "":
                        recent.append(
                            {
                                "student": response.student.display_name
                                or response.student.username,
                                "value": str(value)[:2000],
                                "submitted_at": response.submitted_at,
                            }
                        )
                stats["recent"] = recent
            fields.append(
                {
                    "id": field_id,
                    "label": field.get("label") or field_id,
                    "type": field_type,
                    "stats": stats,
                }
            )
        form_rows.append(
            {
                "form_id": form_id,
                "title": form.get("title") or form_id,
                "submission_count": len(form_responses),
                "student_count": len({item.student_id for item in form_responses}),
                "fields": fields,
            }
        )
    return {
        "page": learning_web_page_row(page),
        "summary": {
            "submission_count": len(responses),
            "student_count": len({item.student_id for item in responses}),
            "form_count": len(forms),
        },
        "forms": form_rows,
        "responses": [learning_web_page_response_row(item) for item in responses[:100]],
    }


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_learning_web_page_responses(request, pk):
    try:
        page = _teacher_learning_web_page(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    responses_query = LearningWebPageResponse.objects.filter(page=page)
    classroom_session = None
    classroom_session_id = str(request.GET.get("classroom_session") or "").strip()
    if classroom_session_id:
        try:
            classroom_session_pk = int(classroom_session_id)
        except (TypeError, ValueError):
            return fail(
                "课堂场次参数不正确。",
                errors={"classroom_session": ["请输入有效的课堂场次编号。"]},
                status=400,
            )
        classroom_session = (
            ClassroomSession.objects.select_related("class_group", "course", "lesson")
            .filter(
                pk=classroom_session_pk, school=_school(request), teacher=request.user
            )
            .first()
        )
        if classroom_session is None:
            return fail("课堂场次不存在或无权查看。", status=404)
        if (
            classroom_session.course_id != page.course_id
            or classroom_session.lesson_id != page.lesson_id
        ):
            return fail("该学习网页不属于当前课堂课时。", status=400)
        responses_query = responses_query.filter(classroom_session=classroom_session)

    responses = list(
        responses_query.select_related(
            "student", "class_group", "classroom_session"
        ).order_by("-submitted_at", "-id")
    )
    payload = _learning_web_page_response_summary(page, responses)
    if classroom_session is not None:
        schema = page.schema if isinstance(page.schema, dict) else {}
        form_ids = {
            str(item.get("form_id") or "")
            for item in schema.get("blocks", [])
            if isinstance(item, dict)
            and item.get("type") == "form"
            and str(item.get("form_id") or "")
        }
        responses_by_student: dict[int, list[LearningWebPageResponse]] = {}
        for response in responses:
            responses_by_student.setdefault(response.student_id, []).append(response)
        profiles = list(
            StudentProfile.objects.filter(
                class_group=classroom_session.class_group,
                user__school=_school(request),
                user__role="student",
                user__is_active=True,
            )
            .select_related("user")
            .order_by("user__display_name", "user__username")
        )
        student_rows = []
        completed_count = 0
        started_count = 0
        for profile in profiles:
            student_responses = responses_by_student.get(profile.user_id, [])
            submitted_form_ids = {
                item.form_id for item in student_responses if item.form_id
            }
            completed = bool(form_ids) and form_ids.issubset(submitted_form_ids)
            started = bool(student_responses)
            if completed:
                completed_count += 1
            elif started:
                started_count += 1
            student_rows.append(
                {
                    "student": user_summary(profile.user),
                    "student_no": profile.student_no,
                    "current_layer": profile.current_layer or "",
                    "status": (
                        "completed"
                        if completed
                        else "started"
                        if started
                        else "pending"
                    ),
                    "status_label": (
                        "已完成" if completed else "进行中" if started else "未开始"
                    ),
                    "submitted_form_count": len(submitted_form_ids & form_ids),
                    "form_count": len(form_ids),
                    "submission_count": len(student_responses),
                    "last_submitted_at": (
                        student_responses[0].submitted_at if student_responses else None
                    ),
                }
            )
        total_count = len(profiles)
        payload["summary"].update(
            {
                "class_student_count": total_count,
                "completed_student_count": completed_count,
                "started_student_count": started_count,
                "pending_student_count": max(
                    total_count - completed_count - started_count, 0
                ),
                "completion_rate": (
                    round(completed_count * 100 / total_count, 1) if total_count else 0
                ),
            }
        )
        payload["scope"] = {
            "classroom_session": {
                "id": classroom_session.id,
                "title": classroom_session.title,
                "status": classroom_session.status,
                "status_label": classroom_session.get_status_display(),
            },
            "class_group": class_group_row(classroom_session.class_group),
        }
        payload["students"] = student_rows
    return ok(payload)


def _teacher_classroom_sessions(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    class_id = request.GET.get("class", "").strip()
    course_id = request.GET.get("course", "").strip()
    sessions = (
        ClassroomSession.objects.filter(school=_school(request), teacher=request.user)
        .select_related(
            "school",
            "teacher",
            "course",
            "course__subject",
            "lesson",
            "class_group",
            "current_step",
            "current_step__lesson",
        )
        .annotate(
            activity_count=Count("activities", distinct=True),
            open_activity_count=Count(
                "activities",
                filter=Q(activities__status=ClassroomActivity.Status.OPEN),
                distinct=True,
            ),
        )
        .order_by("-created_at")
    )
    if query:
        sessions = sessions.filter(
            Q(title__icontains=query)
            | Q(course__title__icontains=query)
            | Q(lesson__title__icontains=query)
        )
    if status:
        if status not in {item.value for item in ClassroomSession.Status}:
            return None, fail(
                "课堂状态筛选条件不正确。",
                errors={"status": ["课堂状态筛选条件不正确。"]},
                status=400,
            )
        sessions = sessions.filter(status=status)
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
                "无权查看该班级课堂。",
                errors={"class": ["无权查看该班级课堂。"]},
                status=403,
            )
        sessions = sessions.filter(class_group_id=selected_class_id)
    if course_id:
        try:
            sessions = sessions.filter(course_id=int(course_id))
        except ValueError:
            return None, fail(
                "课程筛选条件不正确。",
                errors={"course": ["课程筛选条件不正确。"]},
                status=400,
            )
    return sessions, None


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_classroom_sessions(request):
    if request.method == "POST":
        try:
            session = save_classroom_session(request, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        session = _teacher_classroom_session(request, session.pk)
        return ok(
            classroom_session_row(session, include_activities=True),
            "课堂已创建",
            status=201,
        )

    sessions, error_response = _teacher_classroom_sessions(request)
    if error_response is not None:
        return error_response
    page = _paginate(request, sessions)
    page.object_list = [classroom_session_row(session) for session in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_classroom_session_detail(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "GET":
        session.prefetched_activities = list(session.activities.order_by("-created_at"))
        return ok(classroom_session_row(session, include_activities=True))
    if request.method == "PATCH":
        try:
            session = save_classroom_session(request, request.data, session=session)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(classroom_session_row(session), "课堂已更新")

    try:
        delete_classroom_session(request, session)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "课堂已删除")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_session_start(request, pk):
    try:
        session = start_classroom_session(
            request, _teacher_classroom_session(request, pk)
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "课堂已开始")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_session_finish(request, pk):
    try:
        session = finish_classroom_session(
            request, _teacher_classroom_session(request, pk)
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "课堂已结束")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_session_restart(request, pk):
    try:
        session = restart_classroom_session(
            request, _teacher_classroom_session(request, pk)
        )
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "课堂已重新开始")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_step_open(request, pk):
    try:
        session = set_classroom_current_step(
            request, _teacher_classroom_session(request, pk), request.data
        )
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "环节已投放")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_step_lock(request, pk):
    try:
        session = lock_classroom_current_step(
            request, _teacher_classroom_session(request, pk)
        )
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "当前环节已锁定提交")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_step_close(request, pk):
    try:
        session = close_classroom_current_step(
            request, _teacher_classroom_session(request, pk)
        )
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "当前环节已关闭")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_command(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
        activity = run_classroom_command(request, session, request.data)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_activity_row(activity), "课堂指令已执行")


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


def _int_in_range(value, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, min_value), max_value)


def _zip_content(files: dict[str, str | bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _blank_docx_bytes(title: str) -> bytes:
    safe_title = escape(title or "小组协作文档")
    return _zip_content(
        {
            "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
            "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
            "word/document.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{safe_title}</w:t></w:r></w:p>
    <w:p><w:r><w:t>请在这里完成小组协作内容。</w:t></w:r></w:p>
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
    </w:sectPr>
  </w:body>
</w:document>""",
        }
    )


def _blank_xlsx_bytes(title: str) -> bytes:
    from openpyxl import Workbook

    buffer = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "小组协作"
    sheet["A1"] = title or "小组协作表格"
    sheet["A2"] = "请在这里完成小组协作内容。"
    workbook.save(buffer)
    return buffer.getvalue()


def _blank_pptx_bytes(title: str) -> bytes:
    safe_title = escape(title or "小组协作演示")
    return _zip_content(
        {
            "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
</Types>""",
            "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>""",
            "ppt/presentation.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000" type="wideScreen"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>""",
            "ppt/_rels/presentation.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>""",
            "ppt/slides/slide1.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
    <p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="914400" y="914400"/><a:ext cx="10363200" cy="1000000"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{safe_title}</a:t></a:r></a:p></p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>""",
            "ppt/slides/_rels/slide1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>""",
            "ppt/slideLayouts/slideLayout1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>""",
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>""",
            "ppt/slideMasters/slideMaster1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>""",
            "ppt/slideMasters/_rels/slideMaster1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>""",
            "ppt/theme/theme1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="STRATA">
  <a:themeElements><a:clrScheme name="STRATA"><a:dk1><a:srgbClr val="0F172A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:accent1><a:srgbClr val="1F6FEB"/></a:accent1><a:accent2><a:srgbClr val="14B8A6"/></a:accent2><a:accent3><a:srgbClr val="F59E0B"/></a:accent3><a:accent4><a:srgbClr val="22C55E"/></a:accent4><a:accent5><a:srgbClr val="64748B"/></a:accent5><a:accent6><a:srgbClr val="94A3B8"/></a:accent6><a:hlink><a:srgbClr val="1F6FEB"/></a:hlink><a:folHlink><a:srgbClr val="64748B"/></a:folHlink></a:clrScheme><a:fontScheme name="STRATA"><a:majorFont><a:latin typeface="Microsoft YaHei"/></a:majorFont><a:minorFont><a:latin typeface="Microsoft YaHei"/></a:minorFont></a:fontScheme><a:fmtScheme name="STRATA"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements>
</a:theme>""",
        }
    )


def _blank_office_bytes(file_ext: str, title: str) -> bytes:
    if file_ext == "xlsx":
        return _blank_xlsx_bytes(title)
    if file_ext == "pptx":
        return _blank_pptx_bytes(title)
    return _blank_docx_bytes(title)


def _group_document_key(group: ClassroomGroup) -> str:
    return (
        f"classroom-group-{group.id}-{group.document_version}-"
        f"{int(group.updated_at.timestamp())}"
    )


def _group_document_bytes(group: ClassroomGroup) -> bytes:
    if not group.collaboration_document:
        return b""
    with group.collaboration_document.storage.open(
        group.collaboration_document.name, "rb"
    ) as source:
        return source.read()


def _save_group_document_version(
    group: ClassroomGroup,
    *,
    data: bytes,
    version_no: int,
    source: str,
    callback_status: int | None = None,
    callback_key: str = "",
    verified_editor_ids: list[str] | None = None,
    deduplicate: bool = True,
) -> tuple[ClassroomGroupDocumentVersion, bool]:
    file_sha256 = hashlib.sha256(data).hexdigest()
    existing = (
        group.document_versions.filter(file_sha256=file_sha256).first()
        if deduplicate
        else None
    )
    if existing:
        return existing, False
    version = ClassroomGroupDocumentVersion(
        group=group,
        version_no=version_no,
        file_sha256=file_sha256,
        file_size=len(data),
        source=source,
        callback_status=callback_status,
        callback_key=callback_key[:255],
        verified_editor_ids=list(verified_editor_ids or []),
    )
    filename = f"version_{version_no}.{group.document_file_ext or group.collaboration.document_type}"
    version.file.save(filename, ContentFile(data), save=False)
    try:
        version.save()
    except Exception:
        if version.file:
            version.file.delete(save=False)
        raise
    return version, True


def _ensure_group_document(group: ClassroomGroup) -> ClassroomGroup:
    file_ext = group.collaboration.document_type
    if group.collaboration_document and group.document_file_ext == file_ext:
        if not group.document_versions.filter(
            version_no=group.document_version
        ).exists():
            _save_group_document_version(
                group,
                data=_group_document_bytes(group),
                version_no=group.document_version,
                source=ClassroomGroupDocumentVersion.Source.INITIAL,
                deduplicate=False,
            )
        return group
    has_existing_document = bool(group.collaboration_document)
    if group.collaboration_document:
        group.collaboration_document.delete(save=False)
    filename = f"{group.name}.{file_ext}"
    group.collaboration_document.save(
        filename, ContentFile(_blank_office_bytes(file_ext, group.name)), save=False
    )
    group.document_original_name = filename
    group.document_file_ext = file_ext
    group.document_version = (
        (group.document_version + 1) if has_existing_document else 1
    )
    group.save(
        update_fields=[
            "collaboration_document",
            "document_original_name",
            "document_file_ext",
            "document_version",
            "updated_at",
        ]
    )
    _save_group_document_version(
        group,
        data=_group_document_bytes(group),
        version_no=group.document_version,
        source=ClassroomGroupDocumentVersion.Source.INITIAL,
        deduplicate=False,
    )
    return group


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


def _with_prefetched_groups(
    collaboration: ClassroomGroupCollaboration,
) -> ClassroomGroupCollaboration:
    collaboration.prefetched_groups = list(_classroom_group_queryset(collaboration))
    return collaboration


def _student_profiles_for_grouping(session: ClassroomSession) -> list[StudentProfile]:
    return list(
        StudentProfile.objects.select_related("user")
        .filter(class_group=session.class_group, user__is_active=True)
        .order_by("student_no", "user__display_name", "user__username", "id")
    )


def _archive_active_classroom_groups(
    collaboration: ClassroomGroupCollaboration,
) -> None:
    ClassroomGroup.objects.filter(
        collaboration=collaboration,
        is_active=True,
    ).update(is_active=False, closed_at=timezone.now())


def _generate_classroom_groups(
    collaboration: ClassroomGroupCollaboration,
    *,
    plan_version: int,
) -> None:
    profiles = _student_profiles_for_grouping(collaboration.session)
    if not profiles:
        raise ServiceError("当前班级没有可分组的启用学生。", status=400)

    plan = build_grouping_plan(
        session=collaboration.session,
        profiles=profiles,
        group_size=collaboration.group_size,
        strategy=collaboration.grouping_strategy,
        seed=collaboration.session_id * 1000 + plan_version,
        plan_version=plan_version,
    )
    collaboration.generation_metadata = plan.metadata
    collaboration.save(update_fields=["generation_metadata", "updated_at"])
    for group_no, members in enumerate(plan.chunks, start=1):
        if not members:
            continue
        group_name = f"第{group_no}组"
        leader = members[0].user
        group = ClassroomGroup.objects.create(
            collaboration=collaboration,
            group_no=group_no,
            plan_version=plan_version,
            name=group_name,
            leader=leader,
        )
        ClassroomGroupMember.objects.bulk_create(
            [
                ClassroomGroupMember(
                    collaboration=collaboration,
                    group=group,
                    student=profile.user,
                    student_profile=profile,
                    plan_version=plan_version,
                    role=(
                        ClassroomGroupMember.Role.LEADER
                        if index == 0
                        else ClassroomGroupMember.Role.MEMBER
                    ),
                )
                for index, profile in enumerate(members)
            ]
        )
        _ensure_group_document(group)


def _generate_classroom_groups_from_assignments(
    collaboration: ClassroomGroupCollaboration,
    *,
    assignments: list[dict],
    plan_version: int,
) -> None:
    profiles = {
        profile.user_id: profile
        for profile in _student_profiles_for_grouping(collaboration.session)
    }
    valid_roles = set(ClassroomGroupMember.Role.values)
    for group_row in sorted(assignments, key=lambda row: int(row["group_no"])):
        group_no = int(group_row["group_no"])
        members = list(group_row.get("members") or [])
        if not members:
            continue
        leader_id = next(
            (
                int(member["student_id"])
                for member in members
                if member.get("role")
                in {
                    ClassroomGroupMember.Role.COORDINATOR,
                    ClassroomGroupMember.Role.LEADER,
                }
            ),
            int(members[0]["student_id"]),
        )
        group = ClassroomGroup.objects.create(
            collaboration=collaboration,
            group_no=group_no,
            plan_version=plan_version,
            name=f"第{group_no}组",
            leader_id=leader_id,
        )
        member_rows = []
        for member in members:
            student_id = int(member["student_id"])
            profile = profiles.get(student_id)
            if profile is None:
                raise ServiceError("分组中包含不属于当前班级的学生。", status=400)
            role = str(member.get("role") or ClassroomGroupMember.Role.MEMBER)
            if role not in valid_roles:
                raise ServiceError("小组角色不正确。", status=400)
            member_rows.append(
                ClassroomGroupMember(
                    collaboration=collaboration,
                    group=group,
                    student_id=student_id,
                    student_profile=profile,
                    plan_version=plan_version,
                    role=role,
                )
            )
        ClassroomGroupMember.objects.bulk_create(member_rows)
        _ensure_group_document(group)


def _grouping_candidate_run_row(run: GroupingCandidateRun) -> dict:
    student_ids = [int(value) for value in run.input_snapshot.get("student_ids", [])]
    students = {
        profile.user_id: {
            "student_id": profile.user_id,
            "username": profile.user.username,
            "display_name": profile.user.display_name or profile.user.username,
            "student_no": profile.student_no,
        }
        for profile in StudentProfile.objects.select_related("user").filter(
            user_id__in=student_ids,
            class_group=run.decision_point.class_group,
        )
    }
    candidates = []
    for candidate in run.candidates or []:
        row = dict(candidate)
        assignments = []
        for group in candidate.get("assignments") or []:
            group_row = {"group_no": group.get("group_no"), "members": []}
            for member in group.get("members") or []:
                student = students.get(int(member.get("student_id") or 0), {})
                group_row["members"].append({**member, **student})
            assignments.append(group_row)
        row["assignments"] = assignments
        candidates.append(row)
    return {
        "id": run.id,
        "run_id": str(run.run_id),
        "status": run.status,
        "status_label": run.get_status_display(),
        "algorithm_version": run.algorithm_version,
        "policy": {
            "id": run.policy_id,
            "name": run.policy.name,
            "strategy": run.policy.strategy,
            "strategy_label": run.policy.get_strategy_display(),
            "min_group_size": run.policy.min_group_size,
            "max_group_size": run.policy.max_group_size,
            "roles": run.policy.role_scheme,
        },
        "students": list(students.values()),
        "locked_assignments": run.input_snapshot.get("locked_assignments") or {},
        "candidates": candidates,
        "conflicts": run.conflict_explanations,
        "selected_candidate_key": run.selected_candidate_key,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


def _setup_classroom_group_collaboration(
    request, session: ClassroomSession, data
) -> ClassroomGroupCollaboration:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("只有进行中的课堂可以开启小组合作。", status=409)
    group_size = _int_in_range(data.get("group_size"), 4, 2, 12)
    storage_quota_mb = _int_in_range(data.get("storage_quota_mb"), 20, 10, 2048)
    strategy = str(
        data.get("grouping_strategy")
        or ClassroomGroupCollaboration.GroupingStrategy.RANDOM
    ).strip()
    if strategy not in {
        item.value for item in ClassroomGroupCollaboration.GroupingStrategy
    }:
        raise ServiceError(
            "分组策略不正确。",
            errors={"grouping_strategy": ["分组策略不正确。"]},
            status=400,
        )
    document_type = (
        str(data.get("document_type") or ClassroomGroupCollaboration.DocumentType.DOCX)
        .strip()
        .lower()
    )
    if document_type not in {
        item.value for item in ClassroomGroupCollaboration.DocumentType
    }:
        raise ServiceError(
            "协作文档类型不正确。",
            errors={"document_type": ["协作文档类型不正确。"]},
            status=400,
        )
    allow_student_upload = str(
        data.get("allow_student_upload", "true")
    ).lower() not in {"0", "false", "no"}
    allow_onlyoffice_edit = str(
        data.get("allow_onlyoffice_edit", "true")
    ).lower() not in {"0", "false", "no"}
    regenerate = str(data.get("regenerate", "")).lower() in {"1", "true", "yes"}

    with transaction.atomic():
        (
            collaboration,
            created,
        ) = ClassroomGroupCollaboration.objects.select_for_update().get_or_create(
            session=session,
            defaults={
                "created_by": request.user,
                "group_size": group_size,
                "grouping_strategy": strategy,
                "document_type": document_type,
                "storage_quota_mb": storage_quota_mb,
                "allow_student_upload": allow_student_upload,
                "allow_onlyoffice_edit": allow_onlyoffice_edit,
            },
        )
        has_groups = collaboration.groups.filter(
            is_active=True,
            plan_version=collaboration.active_plan_version,
        ).exists()
        grouping_configuration_changed = has_groups and (
            collaboration.group_size != group_size
            or collaboration.grouping_strategy != strategy
            or collaboration.document_type != document_type
        )
        if grouping_configuration_changed and not regenerate:
            raise ServiceError(
                "已有分组；修改人数、策略或文档类型时必须执行重新分组。",
                status=400,
            )
        collaboration_was_open = (
            collaboration.is_enabled
            and collaboration.status == ClassroomGroupCollaboration.Status.OPEN
        )
        collaboration.group_size = group_size
        collaboration.grouping_strategy = strategy
        collaboration.document_type = document_type
        collaboration.storage_quota_mb = storage_quota_mb
        collaboration.allow_student_upload = allow_student_upload
        collaboration.allow_onlyoffice_edit = allow_onlyoffice_edit
        collaboration.is_enabled = True
        collaboration.status = ClassroomGroupCollaboration.Status.OPEN
        if not collaboration_was_open:
            collaboration.opened_at = timezone.now()
        collaboration.closed_at = None
        if (regenerate and has_groups) or (not created and not has_groups):
            latest_plan_version = (
                collaboration.groups.order_by("-plan_version")
                .values_list("plan_version", flat=True)
                .first()
            )
            collaboration.active_plan_version = (
                latest_plan_version + 1 if latest_plan_version else 1
            )
        collaboration.save()

        if regenerate and has_groups:
            try:
                withdraw_group_collaboration_opportunities(
                    collaboration=collaboration,
                    actor=request.user,
                    reason_code="group_regenerated",
                )
            except GroupCollaborationEventError as exc:
                raise ServiceError(exc.message, status=400) from exc

        if created or regenerate or not has_groups:
            _archive_active_classroom_groups(collaboration)
            _generate_classroom_groups(
                collaboration,
                plan_version=collaboration.active_plan_version,
            )
        else:
            for group in collaboration.groups.filter(
                is_active=True,
                plan_version=collaboration.active_plan_version,
            ):
                _ensure_group_document(group)
        try:
            release_group_collaboration_opportunities(
                collaboration=collaboration,
                actor=request.user,
            )
        except GroupCollaborationEventError as exc:
            raise ServiceError(exc.message, status=400) from exc

    write_audit(
        request,
        "teacher.classroom.group_collaboration.setup",
        school=session.school,
        target_type="classroom_session",
        target_id=session.id,
        detail={
            "group_size": group_size,
            "grouping_strategy": strategy,
            "document_type": document_type,
            "storage_quota_mb": storage_quota_mb,
            "regenerate": regenerate,
        },
    )
    return _with_prefetched_groups(collaboration)


def _teacher_classroom_group(
    request, session: ClassroomSession, group_id
) -> ClassroomGroup:
    try:
        group = (
            ClassroomGroup.objects.select_related(
                "collaboration", "collaboration__session", "leader"
            )
            .filter(pk=int(group_id), collaboration__session=session)
            .filter(
                is_active=True,
                plan_version=F("collaboration__active_plan_version"),
            )
            .first()
        )
    except (TypeError, ValueError):
        group = None
    if group is None:
        raise ServiceError("小组不存在或不属于当前课堂。", status=404)
    return group


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


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classroom_group_collaboration(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    collaboration = (
        ClassroomGroupCollaboration.objects.select_related(
            "session",
            "session__school",
            "session__course",
            "session__lesson",
            "session__class_group",
        )
        .filter(session=session)
        .first()
    )
    return ok(
        classroom_group_collaboration_row(_with_prefetched_groups(collaboration))
        if collaboration
        else None
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_group_collaboration_setup(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
        collaboration = _setup_classroom_group_collaboration(
            request, session, request.data
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_group_collaboration_row(collaboration), "小组合作已开启")


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_classroom_grouping_candidates(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    if request.method == "GET":
        run = (
            GroupingCandidateRun.objects.select_related(
                "policy",
                "decision_point",
                "decision_point__class_group",
            )
            .filter(decision_point__classroom_session=session)
            .order_by("-created_at", "-id")
            .first()
        )
        return ok(_grouping_candidate_run_row(run) if run else None)

    collaboration = ClassroomGroupCollaboration.objects.filter(session=session).first()
    if collaboration is None or not collaboration.is_enabled:
        return fail("请先保存并开启小组合作设置。", status=409)
    raw_locks = request.data.get("locked_assignments") or {}
    if not isinstance(raw_locks, dict):
        return fail("锁定学生格式不正确。", status=400)
    document_type = str(
        request.data.get("document_type") or collaboration.document_type
    ).lower()
    if document_type not in ClassroomGroupCollaboration.DocumentType.values:
        return fail("协作文档类型不正确。", status=400)
    try:
        storage_quota_mb = _int_in_range(
            request.data.get("storage_quota_mb"),
            collaboration.storage_quota_mb,
            10,
            2048,
        )
        run = generate_grouping_candidate_run(
            session=session,
            actor=request.user,
            group_size=request.data.get("group_size") or collaboration.group_size,
            requested_strategy=str(
                request.data.get("grouping_strategy") or collaboration.grouping_strategy
            ),
            locked_assignments=raw_locks,
            runtime_settings={
                "document_type": document_type,
                "storage_quota_mb": storage_quota_mb,
                "allow_student_upload": str(
                    request.data.get(
                        "allow_student_upload", collaboration.allow_student_upload
                    )
                ).lower()
                not in {"0", "false", "no"},
                "allow_onlyoffice_edit": str(
                    request.data.get(
                        "allow_onlyoffice_edit", collaboration.allow_onlyoffice_edit
                    )
                ).lower()
                not in {"0", "false", "no"},
            },
        )
    except (ValidationError, ValueError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        return fail(message, status=400)
    write_audit(
        request,
        "teacher.classroom.grouping.candidates",
        school=session.school,
        target_type="grouping_candidate_run",
        target_id=run.id,
        detail={
            "candidate_count": run.candidate_count,
            "locked_student_count": len(raw_locks),
        },
    )
    return ok(_grouping_candidate_run_row(run), "分组候选已生成。", status=201)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_grouping_confirm(request, pk, run_id):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    run = (
        GroupingCandidateRun.objects.select_related(
            "policy",
            "decision_point",
            "decision_point__classroom_session",
        )
        .filter(pk=run_id, decision_point__classroom_session=session)
        .first()
    )
    if run is None:
        return fail("分组候选不存在。", status=404)
    collaboration = ClassroomGroupCollaboration.objects.filter(
        session=session,
        is_enabled=True,
        status=ClassroomGroupCollaboration.Status.OPEN,
    ).first()
    if collaboration is None:
        return fail("小组合作尚未开启。", status=409)
    candidate_key = str(request.data.get("candidate_key") or "").strip()
    existing_plan = run.plans.filter(collaboration=collaboration).first()
    if existing_plan is not None:
        if existing_plan.candidate_key != candidate_key:
            return fail("该候选运行已经确认，不能改选其他方案。", status=409)
        return ok(
            classroom_group_collaboration_row(_with_prefetched_groups(collaboration)),
            "该分组已经生效。",
        )
    adjustments = request.data.get("adjustments") or {}
    if not isinstance(adjustments, dict):
        return fail("分组调整格式不正确。", status=400)
    try:
        with transaction.atomic():
            withdraw_group_collaboration_opportunities(
                collaboration=collaboration,
                actor=request.user,
                reason_code="group_plan_replaced",
            )
            plan, assignments = confirm_grouping_candidate(
                run=run,
                candidate_key=candidate_key,
                collaboration=collaboration,
                actor=request.user,
                adjustments=adjustments,
                note=str(request.data.get("note") or ""),
            )
            _archive_active_classroom_groups(collaboration)
            collaboration.active_plan_version = plan.plan_version
            collaboration.group_size = int(
                run.input_snapshot.get("group_size") or collaboration.group_size
            )
            collaboration.grouping_strategy = str(
                run.input_snapshot.get("requested_strategy")
                or collaboration.grouping_strategy
            )
            collaboration.strategy_version = run.algorithm_version
            runtime_settings = run.input_snapshot.get("runtime_settings") or {}
            collaboration.document_type = str(
                runtime_settings.get("document_type") or collaboration.document_type
            )
            collaboration.storage_quota_mb = int(
                runtime_settings.get("storage_quota_mb")
                or collaboration.storage_quota_mb
            )
            collaboration.allow_student_upload = bool(
                runtime_settings.get(
                    "allow_student_upload", collaboration.allow_student_upload
                )
            )
            collaboration.allow_onlyoffice_edit = bool(
                runtime_settings.get(
                    "allow_onlyoffice_edit", collaboration.allow_onlyoffice_edit
                )
            )
            collaboration.generation_metadata = {
                "candidate_run_id": run.id,
                "candidate_key": candidate_key,
                "policy_id": run.policy_id,
                "policy_hash": run.policy.content_hash,
                "plan_id": str(plan.plan_id),
            }
            collaboration.save(
                update_fields=[
                    "active_plan_version",
                    "group_size",
                    "grouping_strategy",
                    "strategy_version",
                    "generation_metadata",
                    "document_type",
                    "storage_quota_mb",
                    "allow_student_upload",
                    "allow_onlyoffice_edit",
                    "updated_at",
                ]
            )
            _generate_classroom_groups_from_assignments(
                collaboration,
                assignments=assignments,
                plan_version=plan.plan_version,
            )
            record_confirmed_plan_evidence(plan=plan)
            release_group_collaboration_opportunities(
                collaboration=collaboration,
                actor=request.user,
            )
    except ValidationError as exc:
        return fail(exc.messages[0], status=400)
    except (GroupCollaborationEventError, ServiceError) as exc:
        if isinstance(exc, ServiceError):
            return _service_fail(exc)
        return fail(exc.message, status=400)
    write_audit(
        request,
        "teacher.classroom.grouping.confirm",
        school=session.school,
        target_type="grouping_plan_version",
        target_id=plan.id,
        detail={
            "candidate_run_id": run.id,
            "candidate_key": candidate_key,
            "plan_version": plan.plan_version,
            "adjusted": bool(adjustments),
        },
    )
    publish_chat_event(
        [session_group(session.id), teacher_group(session.id)],
        {
            "type": "grouping.updated",
            "session_id": session.id,
            "plan_version": plan.plan_version,
        },
    )
    collaboration = ClassroomGroupCollaboration.objects.get(pk=collaboration.pk)
    return ok(
        classroom_group_collaboration_row(_with_prefetched_groups(collaboration)),
        "新分组已生效。",
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_group_collaboration_close(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
        with transaction.atomic():
            collaboration = (
                ClassroomGroupCollaboration.objects.select_for_update()
                .filter(session=session)
                .first()
            )
            if collaboration is None:
                raise ServiceError("当前课堂尚未开启小组合作。", status=404)
            withdraw_group_collaboration_opportunities(
                collaboration=collaboration,
                actor=request.user,
                reason_code="group_collaboration_closed",
            )
            collaboration.is_enabled = False
            collaboration.status = ClassroomGroupCollaboration.Status.CLOSED
            collaboration.closed_at = timezone.now()
            collaboration.save(
                update_fields=["is_enabled", "status", "closed_at", "updated_at"]
            )
            capture_grouping_outcomes(collaboration=collaboration)
    except ServiceError as exc:
        return _service_fail(exc)
    except GroupCollaborationEventError as exc:
        return fail(exc.message, status=400)
    write_audit(
        request,
        "teacher.classroom.group_collaboration.close",
        school=session.school,
        target_type="classroom_session",
        target_id=session.id,
    )
    return ok(
        classroom_group_collaboration_row(_with_prefetched_groups(collaboration)),
        "小组合作已关闭",
    )


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def teacher_classroom_group_files(request, pk, group_id):
    try:
        session = _teacher_classroom_session(request, pk)
        group = _teacher_classroom_group(request, session, group_id)
    except ServiceError as exc:
        return _service_fail(exc)
    if request.method == "GET":
        return ok(
            [
                classroom_group_file_row(file)
                for file in group.files.select_related("uploader").all()
            ]
        )
    if (
        session.status != ClassroomSession.Status.RUNNING
        or not group.collaboration.is_enabled
        or group.collaboration.status != ClassroomGroupCollaboration.Status.OPEN
    ):
        return fail("只有进行中的小组合作可以上传共享文件。", status=409)
    try:
        file = _save_group_file(
            request,
            group,
            request.FILES.get("attachment"),
            str(request.data.get("description") or "").strip(),
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_group_file_row(file), "小组文件已上传", status=201)


EVALUATION_TYPE_LABELS = {
    ClassroomEvaluationSubmission.EvaluationType.SELF: "自评",
    ClassroomEvaluationSubmission.EvaluationType.PEER: "互评",
    ClassroomEvaluationSubmission.EvaluationType.TEACHER: "师评",
}


def _bool_value(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


def _classroom_student_profiles(session: ClassroomSession) -> list[StudentProfile]:
    return list(
        StudentProfile.objects.select_related("user")
        .filter(class_group=session.class_group, user__is_active=True)
        .order_by("user__display_name", "user__username", "id")
    )


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


def _peer_possible_count(session: ClassroomSession) -> int:
    collaboration = _open_group_collaboration(session)
    if collaboration is None:
        return 0
    count = 0
    for group in collaboration.groups.filter(
        is_active=True,
        plan_version=collaboration.active_plan_version,
    ).prefetch_related("members"):
        member_count = group.members.count()
        count += member_count * max(member_count - 1, 0)
    return count


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


def _teacher_evaluation_payload(
    session: ClassroomSession,
    config=None,
) -> dict:
    config = config or _classroom_evaluation_source(session)
    config_row = classroom_evaluation_config_row(config)
    runtime_enabled = bool(session.evaluation_enabled)
    profiles = _classroom_student_profiles(session)
    submissions = list(
        ClassroomEvaluationSubmission.objects.select_related(
            "evaluator",
            "target",
            "group",
            "evaluation_version",
            "standard_use__standard_version",
        )
        .filter(course=session.course, session=session)
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
        ClassroomEvaluationSubmission.EvaluationType.PEER: _peer_possible_count(
            session
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
            item.evaluator_id == session.teacher_id
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
        "runtime_enabled": runtime_enabled,
        "runtime_opened_at": session.evaluation_opened_at,
        "config": config_row,
        "summary": summary,
        "students": student_rows,
        "recent_submissions": [
            classroom_evaluation_submission_row(item)
            for item in current_submissions[:50]
        ],
        "peer_available": _open_group_collaboration(session) is not None,
    }


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


@api_view(["GET", "POST", "PATCH"])
@permission_classes([IsTeacher])
def teacher_classroom_evaluation(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
        if request.method in {"POST", "PATCH"}:
            binding = (
                LessonStepEvaluationBinding.objects.select_related(
                    "standard_version", "lesson_step__lesson__course"
                )
                .prefetch_related("standard_version__criteria")
                .filter(lesson_step_id=session.current_step_id)
                .first()
            )
            if "evaluation_enabled" in request.data:
                enabled = _bool_value(request.data.get("evaluation_enabled", False))
                if enabled and session.status != ClassroomSession.Status.RUNNING:
                    raise ServiceError("请先开启课堂，再开放评价。", status=400)
                if enabled and binding is None:
                    raise ServiceError(
                        "当前环节尚未选择评价标准，请先在课时设计中完成设置。",
                        status=400,
                    )
                with transaction.atomic():
                    session = ClassroomSession.objects.select_for_update().get(
                        pk=session.pk
                    )
                    was_enabled = session.evaluation_enabled
                    standard_use = ClassroomEvaluationStandardUse.objects.filter(
                        session=session
                    ).first()
                    if enabled and standard_use is None:
                        standard_use = freeze_classroom_evaluation_standard(
                            session=session, binding=binding, actor=request.user
                        )
                    session.evaluation_enabled = enabled
                    update_fields = ["evaluation_enabled", "updated_at"]
                    if enabled and not was_enabled:
                        session.evaluation_opened_at = timezone.now()
                        update_fields.append("evaluation_opened_at")
                    session.save(update_fields=update_fields)
                    if enabled:
                        release_classroom_evaluation_opportunities(
                            session=session,
                            actor=request.user,
                            version=standard_use,
                            occurred_at=session.evaluation_opened_at,
                        )
                    elif was_enabled:
                        withdraw_classroom_evaluation_opportunities(
                            session=session,
                            actor=request.user,
                            reason_code="evaluation_closed",
                        )
                write_audit(
                    request,
                    "teacher.classroom.evaluation.toggle",
                    school=session.school,
                    target_type="classroom_session",
                    target_id=session.id,
                    detail={
                        "enabled": enabled,
                        "course": session.course_id,
                        "lesson": session.lesson_id,
                        "class_group": session.class_group_id,
                    },
                )
                return ok(
                    _teacher_evaluation_payload(session, standard_use),
                    "课堂评价已开启。" if enabled else "课堂评价已关闭。",
                )
            raise ServiceError(
                "评价内容请在评价标准页面维护，课堂只负责开启和执行。",
                status=400,
            )
    except ServiceError as exc:
        return _service_fail(exc)
    except EvaluationEventError as exc:
        return fail(exc.message, status=400)
    return ok(_teacher_evaluation_payload(session))


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_evaluation_ai_generate(request, pk):
    return fail("课堂中不能修改评价内容，请在评价标准页面维护。", status=410)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_evaluation_submit(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
        standard_use = (
            ClassroomEvaluationStandardUse.objects.select_related("standard_version")
            .filter(session=session)
            .first()
        )
        if not session.evaluation_enabled or standard_use is None:
            raise ServiceError("本课堂尚未开启评价。", status=400)
        config_row = classroom_evaluation_config_row(standard_use)
        if not config_row["enable_teacher"]:
            raise ServiceError("本课堂尚未开启师评。", status=400)
        try:
            target_id = int(request.data.get("target"))
        except (TypeError, ValueError):
            raise ServiceError(
                "请选择要评价的学生。", errors={"target": ["请选择学生。"]}, status=400
            )
        profile = (
            StudentProfile.objects.select_related("user")
            .filter(
                user_id=target_id, class_group=session.class_group, user__is_active=True
            )
            .first()
        )
        if profile is None:
            raise ServiceError("学生不属于当前课堂班级。", status=404)
        ratings, not_assessed = _validate_evaluation_response(
            standard_use,
            ClassroomEvaluationSubmission.EvaluationType.TEACHER,
            request.data.get("ratings"),
            request.data.get("not_assessed"),
        )
        comment = str(request.data.get("comment") or "").strip()
        if len(comment) > 1000:
            raise ServiceError(
                "评价备注不能超过 1000 个字符。",
                errors={"comment": ["评价备注不能超过 1000 个字符。"]},
                status=400,
            )
        append_evaluation_submission(
            course=session.course,
            class_group=session.class_group,
            session=session,
            evaluation_type=ClassroomEvaluationSubmission.EvaluationType.TEACHER,
            evaluator=request.user,
            target=profile.user,
            standard_use=standard_use,
            ratings=ratings,
            not_assessed=not_assessed,
            comment=comment,
            group=None,
        )
    except ServiceError as exc:
        return _service_fail(exc)
    except EvaluationEventError as exc:
        return fail(exc.message, status=400)
    return ok(_teacher_evaluation_payload(session, standard_use), "师评已保存。")


def _teacher_course_evaluation_class_group(
    request, course: Course
) -> ClassGroup | None:
    raw_value = request.GET.get("class_group")
    if request.method in {"POST", "PATCH"}:
        raw_value = request.data.get("class_group", raw_value)
    return _course_class_group(course, raw_value)


@api_view(["GET", "POST", "PATCH"])
@permission_classes([IsTeacher])
def teacher_course_evaluation(request, pk):
    return fail(
        "课程级评价入口已停止使用。评价标准在评价标准页面维护，课堂结果在课堂教学中查看。",
        status=410,
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_course_evaluation_ai_generate(request, pk):
    return fail("请在评价标准页面维护评价内容。", status=410)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_course_evaluation_submit(request, pk):
    return fail("课程级师评已停止使用，请在具体课堂中执行师评。", status=410)


def _student_evaluation_context(request, session_id):
    profile = _student_profile(request)
    session = (
        ClassroomSession.objects.select_related(
            "teacher",
            "course",
            "lesson",
            "class_group",
            "evaluation_config_version",
            "evaluation_standard_use__standard_version",
        )
        .filter(
            pk=session_id, school=request.user.school, class_group=profile.class_group
        )
        .first()
    )
    if session is None:
        raise ServiceError("课堂不存在或无权进入。", status=404)
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("课堂尚未开始，暂不能评价。", status=403)
    config = _classroom_evaluation_source(session)
    collaboration = _open_group_collaboration(session)
    group = None
    if collaboration is not None:
        member = (
            ClassroomGroupMember.objects.select_related("group")
            .filter(
                collaboration=collaboration,
                student=request.user,
                plan_version=collaboration.active_plan_version,
                group__is_active=True,
            )
            .first()
        )
        group = member.group if member else None
    return profile, session, config, collaboration, group


def _student_evaluation_payload(
    request,
    session: ClassroomSession,
    config,
    group: ClassroomGroup | None,
) -> dict:
    config_row = classroom_evaluation_config_row(config)
    public_config = {
        key: config_row.get(key)
        for key in (
            "id",
            "course",
            "session",
            "enable_self",
            "enable_peer",
            "enable_teacher",
            "self_criteria",
            "peer_criteria",
            "teacher_criteria",
            "opened_at",
            "created_at",
            "updated_at",
        )
    }
    runtime_enabled = bool(session.evaluation_enabled)
    submissions = list(
        ClassroomEvaluationSubmission.objects.select_related(
            "evaluator",
            "target",
            "group",
            "evaluation_version",
            "standard_use__standard_version",
        )
        .filter(course=session.course, session=session, evaluator=request.user)
        .order_by("-updated_at", "-id")
    )
    submissions = _latest_evaluation_submissions(submissions)
    self_submission = next(
        (
            item
            for item in submissions
            if item.evaluation_type == ClassroomEvaluationSubmission.EvaluationType.SELF
            and item.target_id == request.user.id
        ),
        None,
    )
    peer_submissions = [
        item
        for item in submissions
        if item.evaluation_type == ClassroomEvaluationSubmission.EvaluationType.PEER
    ]
    peer_targets = []
    if runtime_enabled and config and config_row["enable_peer"] and group is not None:
        members = getattr(group, "prefetched_members", None)
        if members is None:
            members = group.members.select_related("student", "student_profile").all()
        existing_by_target = {item.target_id: item for item in peer_submissions}
        for member in members:
            if member.student_id == request.user.id:
                continue
            peer_targets.append(
                {
                    "student_id": member.student_id,
                    "username": member.student.username,
                    "display_name": member.student.display_name
                    or member.student.username,
                    "student_no": (
                        member.student_profile.student_no
                        if member.student_profile
                        else ""
                    ),
                    "submission": classroom_evaluation_submission_row(
                        existing_by_target.get(member.student_id)
                    ),
                }
            )
    return {
        "runtime_enabled": runtime_enabled,
        "runtime_opened_at": session.evaluation_opened_at,
        "config": {
            **public_config,
            "enable_self": bool(runtime_enabled and config_row["enable_self"]),
            "enable_peer": bool(
                runtime_enabled and config_row["enable_peer"] and group is not None
            ),
            "teacher_criteria": [],
            "enable_teacher": False,
            "self_criteria": (
                config_row["self_criteria"]
                if runtime_enabled and config_row["enable_self"]
                else []
            ),
            "peer_criteria": (
                config_row["peer_criteria"]
                if runtime_enabled and config_row["enable_peer"] and group is not None
                else []
            ),
        },
        "self_submission": classroom_evaluation_submission_row(self_submission),
        "peer_targets": peer_targets,
        "my_group": (
            student_classroom_group_row(group, include_files=False) if group else None
        ),
    }


@api_view(["GET"])
@permission_classes([IsStudent])
def student_classroom_evaluation(request, pk):
    try:
        _profile, session, config, _collaboration, group = _student_evaluation_context(
            request, pk
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(_student_evaluation_payload(request, session, config, group))


@api_view(["POST"])
@permission_classes([IsStudent])
def student_classroom_evaluation_submit(request, pk):
    try:
        _profile, session, config, _collaboration, group = _student_evaluation_context(
            request, pk
        )
        if not session.evaluation_enabled:
            raise ServiceError("教师尚未开放课堂评价。", status=400)
        standard_use = (
            config if isinstance(config, ClassroomEvaluationStandardUse) else None
        )
        legacy_version = (
            config if isinstance(config, ClassroomEvaluationConfigVersion) else None
        )
        if standard_use is None and legacy_version is None:
            raise ServiceError("教师尚未开启课堂评价。", status=400)
        evaluation_type = str(request.data.get("evaluation_type") or "").strip()
        if evaluation_type not in {
            ClassroomEvaluationSubmission.EvaluationType.SELF,
            ClassroomEvaluationSubmission.EvaluationType.PEER,
        }:
            raise ServiceError(
                "评价类型不正确。",
                errors={"evaluation_type": ["请选择自评或互评。"]},
                status=400,
            )
        config_row = classroom_evaluation_config_row(config)
        if not config_row.get(_evaluation_enabled_field(evaluation_type)):
            raise ServiceError(
                f"教师尚未开启{EVALUATION_TYPE_LABELS[evaluation_type]}。", status=400
            )
        if evaluation_type == ClassroomEvaluationSubmission.EvaluationType.SELF:
            target = request.user
            target_group = None
        else:
            if group is None:
                raise ServiceError("本课堂尚未开启你所在小组的互评。", status=400)
            try:
                target_id = int(request.data.get("target"))
            except (TypeError, ValueError):
                raise ServiceError(
                    "请选择互评对象。",
                    errors={"target": ["请选择同组成员。"]},
                    status=400,
                )
            if target_id == request.user.id:
                raise ServiceError(
                    "互评对象不能是自己。",
                    errors={"target": ["请选择同组成员。"]},
                    status=400,
                )
            member = (
                group.members.select_related("student")
                .filter(student_id=target_id)
                .first()
            )
            if member is None:
                raise ServiceError("互评对象必须是同组成员。", status=403)
            target = member.student
            target_group = group
        ratings, not_assessed = _validate_evaluation_response(
            config,
            evaluation_type,
            request.data.get("ratings"),
            request.data.get("not_assessed"),
        )
        comment = str(request.data.get("comment") or "").strip()
        if len(comment) > 1000:
            raise ServiceError(
                "评价备注不能超过 1000 个字符。",
                errors={"comment": ["评价备注不能超过 1000 个字符。"]},
                status=400,
            )
        append_evaluation_submission(
            course=session.course,
            class_group=session.class_group,
            session=session,
            evaluation_type=evaluation_type,
            evaluator=request.user,
            target=target,
            evaluation_version=legacy_version,
            standard_use=standard_use,
            ratings=ratings,
            not_assessed=not_assessed,
            comment=comment,
            group=target_group,
        )
    except ServiceError as exc:
        return _service_fail(exc)
    except EvaluationEventError as exc:
        return fail(exc.message, status=400)
    return ok(
        _student_evaluation_payload(request, session, config, group),
        f"{EVALUATION_TYPE_LABELS[evaluation_type]}已提交。",
    )


def _office_group(group_id) -> ClassroomGroup | None:
    try:
        return (
            ClassroomGroup.objects.select_related(
                "collaboration",
                "collaboration__session",
                "collaboration__session__school",
                "collaboration__session__course",
                "collaboration__session__lesson",
                "collaboration__session__class_group",
                "leader",
            )
            .filter(pk=int(group_id))
            .first()
        )
    except (TypeError, ValueError):
        return None


def _group_document_access(request, group: ClassroomGroup) -> tuple[bool, bool]:
    user = request.user
    if not user.is_authenticated:
        return False, False
    session = group.collaboration.session
    is_current_group = (
        group.is_active
        and group.plan_version == group.collaboration.active_plan_version
    )
    if user.role == "teacher":
        can_open = session.teacher_id == user.id and session.school_id == user.school_id
        return can_open, can_open and is_current_group
    if user.role == "student":
        try:
            profile = user.student_profile
        except StudentProfile.DoesNotExist:
            return False, False
        if (
            profile.class_group_id != session.class_group_id
            or session.school_id != user.school_id
        ):
            return False, False
        is_member = ClassroomGroupMember.objects.filter(
            group=group, student=user
        ).exists()
        can_open = is_member
        can_edit = (
            can_open
            and is_current_group
            and session.status == ClassroomSession.Status.RUNNING
            and group.collaboration.is_enabled
            and group.collaboration.status == ClassroomGroupCollaboration.Status.OPEN
            and group.collaboration.allow_onlyoffice_edit
        )
        return can_open, can_edit
    if user.role == "school_admin":
        return user.school_id == session.school_id, False
    if user.role == "super_admin":
        return True, False
    return False, False


def _write_group_document_open_event(
    request, group: ClassroomGroup, *, presentation: str, editor_mode: str
) -> None:
    if (
        request.user.role != "student"
        or not group.is_active
        or group.plan_version != group.collaboration.active_plan_version
    ):
        return
    record_group_document_opened(
        group=group,
        student=request.user,
        presentation=presentation,
        editor_mode=editor_mode,
    )


def _onlyoffice_callback_token(request, payload: dict) -> str:
    authorization = str(request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(payload.get("token") or "").strip()


def _url_origin(value: str) -> tuple[str, str, int | None]:
    parsed = urlparse(value)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def _download_onlyoffice_callback_file(url: str, *, max_bytes: int) -> bytes:
    allowed_origin = _url_origin(settings.ONLYOFFICE_DOCUMENT_SERVER_URL)
    requested_origin = _url_origin(url)
    if (
        requested_origin != allowed_origin
        or requested_origin[0] not in {"http", "https"}
        or not requested_origin[1]
    ):
        raise ValueError("ONLYOFFICE 回调下载地址不属于已配置文档服务器。")
    with urllib.request.urlopen(url, timeout=30) as response:
        if _url_origin(response.geturl()) != allowed_origin:
            raise ValueError("ONLYOFFICE 回调下载发生了跨主机跳转。")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("ONLYOFFICE 回调文件超过允许大小。")
        data = response.read(max_bytes + 1)
    if not data or len(data) > max_bytes:
        raise ValueError("ONLYOFFICE 回调文件为空或超过允许大小。")
    return data


def _verified_onlyoffice_editor_ids(payload: dict) -> list[str]:
    values = []
    raw_values = list(payload.get("users") or [])
    for action in payload.get("actions") or []:
        if isinstance(action, dict):
            raw_values.append(action.get("userId"))
    for value in raw_values:
        text = str(value or "").strip()[:128]
        if text and text not in values:
            values.append(text)
        if len(values) >= 2000:
            break
    return values


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def classroom_group_office_config(request, group_id):
    group = _office_group(group_id)
    if group is None:
        return fail("小组文档不存在。", status=404)
    can_open, can_edit = _group_document_access(request, group)
    if not can_open:
        return fail("无权打开该小组协作文档。", status=403)

    group = _ensure_group_document(group)
    file_ext = group.document_file_ext or group.collaboration.document_type
    if file_ext not in OFFICE_FILE_TYPES:
        return fail("小组协作文档类型不支持网页内编辑。", status=400)

    requested_mode = request.GET.get("mode", "view").strip().lower()
    mode = "edit" if requested_mode == "edit" and can_edit else "view"
    attachment_url = request.build_absolute_uri(
        signed_protected_file_url(
            "group-document",
            group.id,
            version=(f"{group.document_version}:{group.collaboration_document.name}"),
        )
    )
    base_url = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}"
    document_title = group.document_original_name or f"{group.name}.{file_ext}"
    if request.user.role == "student":
        document_title = f"第{group.group_no}组.{file_ext}"
    config = {
        "document": {
            "fileType": file_ext,
            "key": _group_document_key(group),
            "title": document_title,
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
            "callbackUrl": f"{base_url}/api/v1/classroom/groups/{group.id}/office-callback/",
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
    try:
        _write_group_document_open_event(
            request,
            group,
            presentation="embedded",
            editor_mode=mode,
        )
    except GroupCollaborationEventError as exc:
        return fail(exc.message, status=400)
    return ok(
        {
            "server_url": settings.ONLYOFFICE_DOCUMENT_SERVER_URL,
            "mode": mode,
            "can_edit": can_edit,
            "config": sign_editor_config(config),
        }
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def classroom_group_office_callback(request, group_id):
    group = _office_group(group_id)
    if group is None or not group.collaboration_document:
        return JsonResponse({"error": 1}, status=404)
    payload = request.data if isinstance(request.data, dict) else {}
    if not payload:
        return JsonResponse({"error": 1}, status=400)
    token = _onlyoffice_callback_token(request, payload)
    unsigned_payload = {key: value for key, value in payload.items() if key != "token"}
    try:
        verified_payload = verify_callback_payload(token, unsigned_payload)
    except OnlyOfficeJWTError:
        return JsonResponse({"error": 1}, status=403)

    callback_key = str(unsigned_payload.get("key") or "")
    valid_keys = {_group_document_key(group)}
    valid_keys.update(
        item
        for item in group.document_versions.order_by("-version_no").values_list(
            "callback_key", flat=True
        )[:5]
        if item
    )
    if callback_key not in valid_keys:
        return JsonResponse({"error": 1}, status=409)

    status = unsigned_payload.get("status")
    if status in {2, 6} and unsigned_payload.get("url"):
        try:
            max_bytes = (
                min(max(group.collaboration.storage_quota_mb, 10), 512) * 1024 * 1024
            )
            data = _download_onlyoffice_callback_file(
                str(unsigned_payload["url"]), max_bytes=max_bytes
            )
            file_sha256 = hashlib.sha256(data).hexdigest()
            with transaction.atomic():
                group = (
                    ClassroomGroup.objects.select_for_update(of=("self",))
                    .select_related(
                        "collaboration",
                        "collaboration__session",
                        "collaboration__session__teacher",
                        "collaboration__session__school",
                        "collaboration__session__class_group",
                        "collaboration__session__course",
                        "collaboration__session__course__subject",
                        "collaboration__session__lesson",
                    )
                    .get(pk=group.pk)
                )
                latest = group.document_versions.order_by("-version_no").first()
                if latest and latest.file_sha256 == file_sha256:
                    return JsonResponse({"error": 0})
                next_version = (
                    max(
                        group.document_version,
                        latest.version_no if latest else 0,
                    )
                    + 1
                )
                editor_ids = _verified_onlyoffice_editor_ids(verified_payload)
                version, created = _save_group_document_version(
                    group,
                    data=data,
                    version_no=next_version,
                    source=ClassroomGroupDocumentVersion.Source.ONLYOFFICE_CALLBACK,
                    callback_status=int(status),
                    callback_key=callback_key,
                    verified_editor_ids=editor_ids,
                )
                if not created:
                    return JsonResponse({"error": 0})
                group.document_version = next_version
                group.updated_at = timezone.now()
                group.save(update_fields=["document_version", "updated_at"])
                record_group_document_saved(
                    group=group,
                    version=version,
                    verified_editor_ids=editor_ids,
                )
                with group.collaboration_document.storage.open(
                    group.collaboration_document.name, "wb"
                ) as target:
                    target.write(data)
        except (ValueError, OSError, GroupCollaborationEventError):
            return JsonResponse({"error": 1})
    return JsonResponse({"error": 0})


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


def _teacher_classroom_step_progress_payload(session: ClassroomSession) -> dict:
    step = (
        session.current_step
        if getattr(session, "current_step", None) and session.current_step_id
        else None
    )
    if step is None:
        return {
            "step": None,
            "summary": {
                "total": 0,
                "submitted": 0,
                "not_submitted": 0,
                "question_count": 0,
                "required_count": 0,
                "auto_score_avg": None,
                "auto_score_max": 0,
            },
            "rows": [],
        }

    profiles = list(
        StudentProfile.objects.select_related("user")
        .filter(class_group=session.class_group, user__is_active=True)
        .order_by("user__display_name", "user__username", "id")
    )
    threshold = session.current_step_started_at or session.started_at
    events = LearningEvent.objects.filter(
        actor_id__in=[profile.user_id for profile in profiles],
        event_type=LearningEvent.EventType.ANSWER_SUBMIT,
        object_type="lesson_step",
        object_id=str(step.id),
    ).select_related("actor")
    if threshold:
        events = events.filter(occurred_at__gte=threshold)

    latest_by_student = {}
    for event in events.order_by("actor_id", "-occurred_at", "-id"):
        latest_by_student.setdefault(event.actor_id, event)
    latest_attempt_by_student = {}
    attempts = (
        LessonStepAttempt.objects.filter(
            classroom_session=session,
            lesson_step=step,
            student_id__in=[profile.user_id for profile in profiles],
        )
        .prefetch_related("answer_rows__attachment")
        .order_by("student_id", "-attempt_no", "-id")
    )
    for attempt in attempts:
        latest_attempt_by_student.setdefault(attempt.student_id, attempt)
    work_by_student_question = {}
    works = StudentWorkAttachment.objects.filter(
        lesson_step=step,
        student_id__in=[profile.user_id for profile in profiles],
    ).order_by("student_id", "question_id", "-upload_version", "-id")
    for item in works:
        work_by_student_question.setdefault((item.student_id, item.question_id), item)

    apply_layering = lesson_step_has_layered_questions(step)
    rows = []
    auto_score_sum = 0.0
    auto_score_rows = 0
    max_auto_score = 0.0
    for profile in profiles:
        questions = normalize_lesson_question_items(
            step.question_items,
            include_answer=True,
            student_layer=_student_course_band(profile, session.course),
            apply_layering=apply_layering,
        )
        attempt = latest_attempt_by_student.get(profile.user_id)
        event = latest_by_student.get(profile.user_id) if attempt is None else None
        metadata = event.metadata if event and isinstance(event.metadata, dict) else {}
        answer = (
            attempt.answer if attempt else metadata.get("answer") if event else None
        )
        progress = _lesson_step_answer_progress(questions, answer)
        attempt_answer_rows = (
            {item.question_id: item for item in attempt.answer_rows.all()}
            if attempt
            else {}
        )
        for answer_row in progress["answers"]:
            if answer_row["question_type"] != "file":
                continue
            attempt_answer = attempt_answer_rows.get(answer_row["question_id"])
            work = (
                attempt_answer.attachment
                if attempt_answer and attempt_answer.attachment_id
                else work_by_student_question.get(
                    (profile.user_id, answer_row["question_id"])
                )
            )
            if not work:
                continue
            attachment_payload = student_work_attachment_row(work)
            answer_row["attachment"] = attachment_payload
            answer_row["answer_text"] = attachment_payload["attachment_name"]
            answer_row["is_answered"] = True
            answer_row["score"] = attachment_payload["score"]
        submitted = attempt is not None or event is not None
        if submitted and progress["auto_score_max"] > 0:
            auto_score_sum += progress["auto_score"]
            auto_score_rows += 1
        max_auto_score = max(max_auto_score, progress["auto_score_max"])
        rows.append(
            {
                "student_id": profile.user_id,
                "profile_id": profile.id,
                "username": profile.user.username,
                "display_name": profile.user.display_name or profile.user.username,
                "student_no": profile.student_no,
                "current_layer": profile.current_layer or "",
                "current_layer_label": (
                    profile.get_current_layer_display() if profile.current_layer else ""
                ),
                "submitted": submitted,
                "submitted_at": (
                    attempt.submitted_at
                    if attempt
                    else event.occurred_at
                    if event
                    else None
                ),
                "event_id": event.id if event else None,
                "attempt_id": str(attempt.attempt_id) if attempt else None,
                "attempt_no": attempt.attempt_no if attempt else None,
                "text": progress["text"],
                "answered_count": progress["answered_count"],
                "question_count": progress["question_count"],
                "required_count": progress["required_count"],
                "auto_score": progress["auto_score"] if submitted else None,
                "auto_score_max": progress["auto_score_max"],
                "auto_gradable_count": progress["auto_gradable_count"],
                "correct_count": progress["correct_count"],
                "answers": progress["answers"] if submitted else [],
            }
        )

    submitted_count = sum(1 for row in rows if row["submitted"])
    return {
        "step": {
            "id": step.id,
            "title": step.title,
            "step_type": step.step_type,
            "step_type_label": step.get_step_type_display(),
            "is_layered": apply_layering,
        },
        "summary": {
            "total": len(rows),
            "submitted": submitted_count,
            "not_submitted": len(rows) - submitted_count,
            "question_count": max((row["question_count"] for row in rows), default=0),
            "required_count": max((row["required_count"] for row in rows), default=0),
            "auto_score_avg": (
                round(auto_score_sum / auto_score_rows, 2) if auto_score_rows else None
            ),
            "auto_score_max": round(max_auto_score, 2),
        },
        "rows": rows,
    }


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classroom_step_progress(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(_teacher_classroom_step_progress_payload(session))


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_attachment_score(request, pk, attachment_id):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    attachment = (
        StudentWorkAttachment.objects.select_related(
            "student", "lesson_step", "lesson", "course", "class_group"
        )
        .filter(
            pk=attachment_id,
            class_group=session.class_group,
            lesson_step=session.current_step,
        )
        .first()
    )
    if attachment is None:
        return fail("附件提交不存在或无权评分。", status=404)
    question = next(
        (
            item
            for item in normalize_lesson_question_items(
                attachment.lesson_step.question_items, include_answer=True
            )
            if str(item.get("id")) == attachment.question_id
        ),
        None,
    )
    if question is None:
        return fail("附件对应的课堂题目已不存在，不能评分。", status=409)
    max_score = _score_float(question.get("score") if question else 100, 100)
    if max_score <= 0:
        return fail("该附件题未设置有效分值，不能评分。", status=400)
    try:
        score = float(request.data.get("score"))
    except (TypeError, ValueError):
        return fail(
            "分数必须是数字。", errors={"score": ["分数必须是数字。"]}, status=400
        )
    if score < 0 or score > max_score:
        return fail(
            f"分数需在 0-{max_score:g} 之间。",
            errors={"score": [f"分数需在 0-{max_score:g} 之间。"]},
            status=400,
        )
    feedback = str(request.data.get("feedback") or "").strip()
    if len(feedback) > 1000:
        return fail(
            "反馈不能超过 1000 个字符。",
            errors={"feedback": ["反馈不能超过 1000 个字符。"]},
            status=400,
        )

    try:
        with transaction.atomic():
            ensure_classroom_step_opportunities(session=session)
            ensure_classroom_attachment_submission(work=attachment)
            grading_state = next_classroom_grading_state(
                session=session,
                student=attachment.student,
                question=question,
                attempt_id=attachment.submission_id,
            )
            evaluated_at = timezone.now()
            attachment.score = score
            attachment.feedback = feedback
            attachment.evaluated_by = request.user
            attachment.evaluated_at = evaluated_at
            attachment.save(
                update_fields=[
                    "score",
                    "feedback",
                    "evaluated_by",
                    "evaluated_at",
                    "updated_at",
                ]
            )
            record_classroom_item_grade(
                session=session,
                student=attachment.student,
                question=question,
                attempt_id=attachment.submission_id,
                score_raw=score,
                score_max=max_score,
                is_correct=None,
                grading_state=grading_state,
                grader_type="teacher",
                actor=request.user,
                occurred_at=evaluated_at,
            )
    except ClassroomEventError as exc:
        return fail(exc.message, status=400)
    return ok(student_work_attachment_row(attachment), "附件评分已保存。")


def _attendance_events_for_activity(activity: ClassroomActivity):
    return (
        LearningEvent.objects.filter(
            object_type="classroom_activity",
            object_id=str(activity.id),
            metadata__action="classroom_activity_response",
            metadata__command="sign_in",
        )
        .select_related("actor")
        .order_by("actor_id", "-occurred_at", "-id")
    )


def _teacher_attendance_payload(activity: ClassroomActivity) -> dict:
    profiles = (
        StudentProfile.objects.select_related("user")
        .filter(class_group=activity.session.class_group, user__is_active=True)
        .order_by("user__display_name", "user__username")
    )
    latest_by_student = {}
    for event in _attendance_events_for_activity(activity):
        latest_by_student.setdefault(event.actor_id, event)
    rows = [
        classroom_attendance_row(
            activity, profile, latest_by_student.get(profile.user_id)
        )
        for profile in profiles
    ]
    summary = {
        "total": len(rows),
        "signed": sum(1 for row in rows if row["status"] == "signed"),
        "late": sum(1 for row in rows if row["status"] == "late"),
        "leave": sum(1 for row in rows if row["status"] == "leave"),
        "absent": sum(1 for row in rows if row["status"] == "absent"),
        "not_signed": sum(1 for row in rows if row["status"] == "not_signed"),
    }
    return {
        "activity": classroom_activity_row(activity),
        "summary": summary,
        "rows": rows,
    }


def _quick_answer_response_events(activity: ClassroomActivity):
    return (
        LearningEvent.objects.filter(
            object_type="classroom_activity",
            object_id=str(activity.id),
            metadata__action="classroom_activity_response",
            metadata__command="quick_answer",
            metadata__response_type="quick_answer",
        )
        .select_related("actor", "actor__student_profile")
        .order_by("occurred_at", "id")
    )


def _quick_answer_score_events(activity: ClassroomActivity):
    return (
        LearningEvent.objects.filter(
            object_type="classroom_activity",
            object_id=str(activity.id),
            metadata__action="quick_answer_score",
        )
        .select_related("actor")
        .order_by("actor_id", "-occurred_at", "-id")
    )


def _quick_answer_defaults(activity: ClassroomActivity) -> dict:
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    defaults = (
        metadata.get("score_defaults")
        if isinstance(metadata.get("score_defaults"), dict)
        else {}
    )
    try:
        plus = float(defaults.get("plus", 2))
    except (TypeError, ValueError):
        plus = 2
    try:
        minus = float(defaults.get("minus", -1))
    except (TypeError, ValueError):
        minus = -1
    return {"plus": plus, "minus": minus}


def _teacher_quick_answer_payload(activity: ClassroomActivity) -> dict:
    score_by_student = {}
    for event in _quick_answer_score_events(activity):
        score_by_student.setdefault(event.actor_id, event)

    rows = []
    for index, event in enumerate(_quick_answer_response_events(activity), start=1):
        profile = getattr(event.actor, "student_profile", None)
        score_event = score_by_student.get(event.actor_id)
        score_metadata = (
            score_event.metadata
            if score_event and isinstance(score_event.metadata, dict)
            else {}
        )
        rows.append(
            {
                "rank": index,
                "event_id": event.id,
                "student_id": event.actor_id,
                "username": event.actor.username,
                "display_name": event.actor.display_name or event.actor.username,
                "student_no": getattr(profile, "student_no", "") if profile else "",
                "current_layer": getattr(profile, "current_layer", "") or "",
                "current_layer_label": (
                    profile.get_current_layer_display()
                    if profile and profile.current_layer
                    else ""
                ),
                "responded_at": event.occurred_at,
                "score": score_event.score if score_event else None,
                "score_action": str(score_metadata.get("score_action") or ""),
                "score_note": str(score_metadata.get("score_note") or ""),
                "scored_at": score_event.occurred_at if score_event else None,
            }
        )

    defaults = _quick_answer_defaults(activity)
    summary = {
        "total": len(rows),
        "scored": sum(1 for row in rows if row["score"] is not None),
        "plus": sum(1 for row in rows if row["score_action"] == "plus"),
        "minus": sum(1 for row in rows if row["score_action"] == "minus"),
    }
    return {
        "activity": classroom_activity_row(activity),
        "summary": summary,
        "score_defaults": defaults,
        "rows": rows,
    }


def _random_pick_score_events(activity: ClassroomActivity):
    return (
        LearningEvent.objects.filter(
            object_type="classroom_activity",
            object_id=str(activity.id),
            metadata__action="random_pick_score",
        )
        .select_related("actor")
        .order_by("actor_id", "-occurred_at", "-id")
    )


def _teacher_random_pick_student_rows(
    session: ClassroomSession,
    *,
    picked_user_id: int = 0,
    score_by_student: dict | None = None,
) -> tuple[list[dict], dict | None]:
    score_by_student = score_by_student or {}
    students = []
    picked_row = None
    profiles = (
        StudentProfile.objects.select_related("user")
        .filter(class_group=session.class_group, user__is_active=True)
        .order_by("user__display_name", "user__username")
    )
    for profile in profiles:
        score_event = score_by_student.get(profile.user_id)
        score_metadata = (
            score_event.metadata
            if score_event and isinstance(score_event.metadata, dict)
            else {}
        )
        row = {
            "student_id": profile.user_id,
            "profile_id": profile.id,
            "username": profile.user.username,
            "display_name": profile.user.display_name or profile.user.username,
            "student_no": profile.student_no,
            "current_layer": profile.current_layer or "",
            "current_layer_label": (
                profile.get_current_layer_display() if profile.current_layer else ""
            ),
            "is_picked": profile.user_id == picked_user_id,
            "score": score_event.score if score_event else None,
            "score_action": str(score_metadata.get("score_action") or ""),
            "score_note": str(score_metadata.get("score_note") or ""),
            "scored_at": score_event.occurred_at if score_event else None,
        }
        if row["is_picked"]:
            picked_row = row
        students.append(row)
    return students, picked_row


def _teacher_random_pick_preview_payload(session: ClassroomSession) -> dict:
    students, _ = _teacher_random_pick_student_rows(session)
    return {
        "summary": {"total": len(students), "picked": 0, "scored": 0},
        "score_defaults": {"plus": 2, "minus": -1},
        "picked_student": None,
        "students": students,
    }


def _teacher_random_pick_payload(activity: ClassroomActivity) -> dict:
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    picked = (
        metadata.get("picked_student")
        if isinstance(metadata.get("picked_student"), dict)
        else {}
    )
    picked_user_id = int(picked.get("user_id") or 0)
    score_by_student = {}
    for event in _random_pick_score_events(activity):
        score_by_student.setdefault(event.actor_id, event)

    students, picked_row = _teacher_random_pick_student_rows(
        activity.session,
        picked_user_id=picked_user_id,
        score_by_student=score_by_student,
    )

    defaults = _quick_answer_defaults(activity)
    summary = {
        "total": len(students),
        "picked": 1 if picked_row else 0,
        "scored": 1 if picked_row and picked_row["score"] is not None else 0,
    }
    return {
        "activity": classroom_activity_row(activity),
        "summary": summary,
        "score_defaults": defaults,
        "picked_student": picked_row,
        "students": students,
    }


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classroom_random_pick_preview(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    if session.status != ClassroomSession.Status.RUNNING:
        return fail("请先开始课堂，再使用随机点名。", status=400)
    return ok(_teacher_random_pick_preview_payload(session))


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classroom_attendance(request, pk, activity_id):
    try:
        session = _teacher_classroom_session(request, pk)
        activity = _teacher_classroom_activity(request, activity_id)
    except ServiceError as exc:
        return _service_fail(exc)
    if activity.session_id != session.id:
        return fail("签到活动不属于当前课堂。", status=404)
    if not is_attendance_activity(activity):
        return fail("该课堂活动不是签到。", status=400)
    return ok(_teacher_attendance_payload(activity))


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classroom_quick_answer(request, pk, activity_id):
    try:
        session = _teacher_classroom_session(request, pk)
        activity = _teacher_classroom_activity(request, activity_id)
    except ServiceError as exc:
        return _service_fail(exc)
    if activity.session_id != session.id:
        return fail("抢答活动不属于当前课堂。", status=404)
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    if metadata.get("command") != "quick_answer":
        return fail("该课堂活动不是抢答。", status=400)
    return ok(_teacher_quick_answer_payload(activity))


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classroom_random_pick(request, pk, activity_id):
    try:
        session = _teacher_classroom_session(request, pk)
        activity = _teacher_classroom_activity(request, activity_id)
    except ServiceError as exc:
        return _service_fail(exc)
    if activity.session_id != session.id:
        return fail("随机点名活动不属于当前课堂。", status=404)
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    if metadata.get("command") != "random_pick":
        return fail("该课堂活动不是随机点名。", status=400)
    return ok(_teacher_random_pick_payload(activity))


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_random_pick_score(request, pk, activity_id):
    try:
        session = _teacher_classroom_session(request, pk)
        activity = _teacher_classroom_activity(request, activity_id)
    except ServiceError as exc:
        return _service_fail(exc)
    if activity.session_id != session.id:
        return fail("随机点名活动不属于当前课堂。", status=404)
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    if metadata.get("command") != "random_pick":
        return fail("该课堂活动不是随机点名。", status=400)
    picked = (
        metadata.get("picked_student")
        if isinstance(metadata.get("picked_student"), dict)
        else {}
    )
    picked_user_id = int(picked.get("user_id") or 0)
    action = str(request.data.get("action") or "").strip()
    defaults = _quick_answer_defaults(activity)
    if action == "plus":
        default_score = defaults["plus"]
        default_label = "加分"
    elif action == "minus":
        default_score = defaults["minus"]
        default_label = "减分"
    else:
        return fail(
            "评分动作不正确。", errors={"action": ["请选择加分或减分。"]}, status=400
        )
    try:
        student_id = int(request.data.get("student_id") or picked_user_id)
    except (TypeError, ValueError):
        student_id = picked_user_id
    if not picked_user_id or student_id != picked_user_id:
        return fail("只能给本次被点名的学生评分。", status=400)
    profile = (
        StudentProfile.objects.select_related("user")
        .filter(
            user_id=student_id, class_group=session.class_group, user__is_active=True
        )
        .first()
    )
    if profile is None:
        return fail("学生不属于当前课堂班级。", status=404)
    try:
        score = float(request.data.get("score", default_score))
    except (TypeError, ValueError):
        score = default_score
    score = abs(score) if action == "plus" else -abs(score)
    score = min(max(score, -100), 100)
    note = str(request.data.get("note") or default_label).strip()[:500]
    try:
        record_classroom_point_adjustment(
            teacher=request.user,
            student_profile=profile,
            classroom_session=session,
            object_type="classroom_activity",
            object_id=activity.id,
            reason_code="random_pick_score_adjustment",
            requested_score=score,
            previous_event_action="random_pick_score",
            legacy_metadata={
                "action": "random_pick_score",
                "command": "random_pick",
                "response_type": "random_pick_score",
                "score_action": action,
                "score_note": note,
                "activity_title": activity.title,
                "session": session.id,
                "default_score": default_score,
                "ai_feature": "random_pick_score",
            },
        )
    except EventWriteError as exc:
        return fail(exc.message, status=400)
    return ok(_teacher_random_pick_payload(activity), "随机点名评分已记录。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_quick_answer_score(request, pk, activity_id):
    try:
        session = _teacher_classroom_session(request, pk)
        activity = _teacher_classroom_activity(request, activity_id)
    except ServiceError as exc:
        return _service_fail(exc)
    if activity.session_id != session.id:
        return fail("抢答活动不属于当前课堂。", status=404)
    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    if metadata.get("command") != "quick_answer":
        return fail("该课堂活动不是抢答。", status=400)

    action = str(request.data.get("action") or "").strip()
    defaults = _quick_answer_defaults(activity)
    if action == "plus":
        default_score = defaults["plus"]
        default_label = "加分"
    elif action == "minus":
        default_score = defaults["minus"]
        default_label = "减分"
    else:
        return fail(
            "评分动作不正确。", errors={"action": ["请选择加分或减分。"]}, status=400
        )
    try:
        student_id = int(request.data.get("student_id"))
    except (TypeError, ValueError):
        return fail(
            "学生编号不正确。", errors={"student_id": ["请选择学生。"]}, status=400
        )
    profile = (
        StudentProfile.objects.select_related("user")
        .filter(
            user_id=student_id, class_group=session.class_group, user__is_active=True
        )
        .first()
    )
    if profile is None:
        return fail("学生不属于当前课堂班级。", status=404)
    has_responded = (
        _quick_answer_response_events(activity).filter(actor_id=student_id).exists()
    )
    if not has_responded:
        return fail("该学生还没有参与本次抢答。", status=400)
    try:
        score = float(request.data.get("score", default_score))
    except (TypeError, ValueError):
        score = default_score
    if action == "plus":
        score = abs(score)
    else:
        score = -abs(score)
    score = min(max(score, -100), 100)
    note = str(request.data.get("note") or default_label).strip()[:500]
    try:
        record_classroom_point_adjustment(
            teacher=request.user,
            student_profile=profile,
            classroom_session=session,
            object_type="classroom_activity",
            object_id=activity.id,
            reason_code="quick_answer_score_adjustment",
            requested_score=score,
            previous_event_action="quick_answer_score",
            legacy_metadata={
                "action": "quick_answer_score",
                "command": "quick_answer",
                "response_type": "quick_answer_score",
                "score_action": action,
                "score_note": note,
                "activity_title": activity.title,
                "session": session.id,
                "default_score": default_score,
                "ai_feature": "quick_answer_score",
            },
        )
    except EventWriteError as exc:
        return fail(exc.message, status=400)
    return ok(_teacher_quick_answer_payload(activity), "抢答评分已记录。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_attendance_mark(request, pk, activity_id):
    try:
        session = _teacher_classroom_session(request, pk)
        activity = _teacher_classroom_activity(request, activity_id)
    except ServiceError as exc:
        return _service_fail(exc)
    if activity.session_id != session.id:
        return fail("签到活动不属于当前课堂。", status=404)
    if not is_attendance_activity(activity):
        return fail("该课堂活动不是签到。", status=400)
    status = str(request.data.get("status") or "").strip()
    if status not in {"signed", "late", "leave", "absent"}:
        return fail(
            "签到状态不正确。",
            errors={"status": ["请选择已签到、迟到、请假或缺勤。"]},
            status=400,
        )
    try:
        student_id = int(request.data.get("student_id"))
    except (TypeError, ValueError):
        return fail(
            "学生编号不正确。", errors={"student_id": ["请选择学生。"]}, status=400
        )
    profile = (
        StudentProfile.objects.select_related("user")
        .filter(
            user_id=student_id, class_group=session.class_group, user__is_active=True
        )
        .first()
    )
    if profile is None:
        return fail("学生不属于当前课堂班级。", status=404)
    note = str(request.data.get("note") or "").strip()[:500]
    try:
        record_attendance_status(
            activity=activity,
            student=profile.user,
            recorder=request.user,
            attendance_status=status,
            recorded_by="teacher",
            note=note,
        )
    except AttendanceEventError as exc:
        return fail(exc.message, status=400)
    return ok(_teacher_attendance_payload(activity), "签到状态已更新。")


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_classroom_activities(request, session_id):
    try:
        session = _teacher_classroom_session(request, session_id)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "POST":
        try:
            activity = save_classroom_activity(request, session, request.data)
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(classroom_activity_row(activity), "课堂活动已创建", status=201)

    return ok(
        [
            classroom_activity_row(activity)
            for activity in session.activities.order_by("-created_at")
        ]
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_classroom_activity_detail(request, pk):
    try:
        activity = _teacher_classroom_activity(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)

    if request.method == "GET":
        return ok(classroom_activity_row(activity))
    if request.method == "PATCH":
        try:
            activity = save_classroom_activity(
                request, activity.session, request.data, activity=activity
            )
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(classroom_activity_row(activity), "课堂活动已更新")

    try:
        delete_classroom_activity(request, activity)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "课堂活动已删除")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_activity_open(request, pk):
    try:
        activity = open_classroom_activity(
            request, _teacher_classroom_activity(request, pk)
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_activity_row(activity), "课堂活动已开启")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_activity_close(request, pk):
    try:
        activity = close_classroom_activity(
            request, _teacher_classroom_activity(request, pk)
        )
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_activity_row(activity), "课堂活动已关闭")


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


def _student_teachers(profile: StudentProfile):
    if not profile.class_group_id:
        return get_user_model().objects.none()
    teacher_ids = (
        TeachingAssignment.objects.filter(
            school=profile.user.school,
            class_group=profile.class_group,
            teacher__is_active=True,
        )
        .values_list("teacher_id", flat=True)
        .distinct()
    )
    return (
        get_user_model()
        .objects.filter(id__in=teacher_ids, role="teacher", school=profile.user.school)
        .order_by("display_name", "username")
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


def _ensure_student_can_learn_course(user, course: Course) -> None:
    status = _student_required_pretest_status(user, course.subject)
    if status["required"] and not status["completed"]:
        subject_name = course.subject.name if course.subject_id else "该学科"
        raise ServiceError(f"请先完成{subject_name}前测。", status=403)


def _student_course_queryset(profile: StudentProfile):
    if not profile.class_group_id:
        return Course.objects.none()
    return (
        Course.objects.filter(
            is_active=True,
            teacher__school=profile.user.school,
            course_classes__class_group=profile.class_group,
        )
        .select_related("subject", "teacher")
        .annotate(
            lesson_count=Count(
                "lessons", filter=Q(lessons__is_active=True), distinct=True
            ),
            step_count=Count(
                "lessons__steps",
                filter=Q(
                    lessons__is_active=True,
                    lessons__steps__status=LessonStep.Status.READY,
                ),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                "lessons",
                queryset=Lesson.objects.filter(is_active=True).order_by(
                    "sort_order", "id"
                ),
                to_attr="student_lessons",
            )
        )
        .distinct()
        .order_by("-updated_at", "-created_at")
    )


def _student_course(profile: StudentProfile, course_id) -> Course:
    try:
        course = _student_course_queryset(profile).filter(pk=int(course_id)).first()
    except (TypeError, ValueError):
        course = None
    if course is None:
        raise ServiceError("课程不存在或当前不可学习。", status=404)
    return course


def _student_lesson(profile: StudentProfile, lesson_id) -> Lesson:
    try:
        lesson = (
            Lesson.objects.select_related(
                "course", "course__subject", "course__teacher"
            )
            .filter(
                pk=int(lesson_id),
                is_active=True,
                course__is_active=True,
                course__teacher__school=profile.user.school,
                course__course_classes__class_group=profile.class_group,
            )
            .first()
        )
    except (TypeError, ValueError):
        lesson = None
    if lesson is None:
        raise ServiceError("课时不存在或当前不可学习。", status=404)
    _ensure_student_can_learn_course(profile.user, lesson.course)
    return lesson


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


def _ensure_student_lesson_workspace_allowed(
    profile: StudentProfile, lesson: Lesson
) -> None:
    session = _student_lesson_classroom_session(profile, lesson)
    if session is None:
        raise ServiceError("该课时尚未启用课堂教学，暂不能进入。", status=403)
    if session.status == ClassroomSession.Status.RUNNING:
        raise ServiceError("该课时正在课堂教学中，请从课堂入口进入。", status=403)
    raise ServiceError("该课时属于课堂教学，教师启用课堂后才能进入。", status=403)


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


def _student_lesson_step(profile: StudentProfile, step_id) -> LessonStep:
    try:
        step = (
            LessonStep.objects.select_related(
                "lesson",
                "lesson__course",
                "lesson__course__subject",
                "lesson__course__teacher",
            )
            .filter(
                pk=int(step_id),
                status=LessonStep.Status.READY,
                lesson__is_active=True,
                lesson__course__is_active=True,
                lesson__course__teacher__school=profile.user.school,
                lesson__course__course_classes__class_group=profile.class_group,
            )
            .first()
        )
    except (TypeError, ValueError):
        step = None
    if step is None:
        raise ServiceError("课时环节不存在或当前不可学习。", status=404)
    _ensure_student_can_learn_course(profile.user, step.lesson.course)
    _ensure_student_step_classroom_open(profile, step)
    return step


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


def _learning_web_page_form(schema: dict, form_id: str) -> dict | None:
    blocks = (
        schema.get("blocks")
        if isinstance(schema, dict) and isinstance(schema.get("blocks"), list)
        else []
    )
    return next(
        (
            item
            for item in blocks
            if isinstance(item, dict)
            and item.get("type") == "form"
            and str(item.get("form_id") or "") == form_id
        ),
        None,
    )


def _clean_learning_web_page_answers(form: dict, raw_answers) -> dict:
    answers = raw_answers if isinstance(raw_answers, dict) else {}
    cleaned = {}
    errors = {}
    fields = form.get("fields") if isinstance(form.get("fields"), list) else []
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_id = str(field.get("id") or "")
        field_type = str(field.get("type") or "short_text")
        value = answers.get(field_id)
        empty = value is None or value == "" or isinstance(value, list) and not value
        if field.get("required", True) and empty:
            errors[field_id] = ["该项必填。"]
            continue
        if empty:
            cleaned[field_id] = [] if field_type == "multiple" else ""
            continue
        options = [str(item) for item in field.get("options", [])]
        if field_type in {"single", "select", "scale"}:
            value = str(value)
            if value not in options:
                errors[field_id] = ["选项不正确。"]
                continue
            cleaned[field_id] = value
        elif field_type == "multiple":
            values = value if isinstance(value, list) else [value]
            selected = []
            for item in values:
                item = str(item)
                if item in options and item not in selected:
                    selected.append(item)
            if field.get("required", True) and not selected:
                errors[field_id] = ["请至少选择一项。"]
                continue
            cleaned[field_id] = selected
        elif field_type == "number":
            try:
                number = float(value)
            except (TypeError, ValueError):
                errors[field_id] = ["请输入数字。"]
                continue
            minimum = field.get("min")
            maximum = field.get("max")
            if minimum is not None and number < float(minimum):
                errors[field_id] = [f"不能小于 {minimum}。"]
                continue
            if maximum is not None and number > float(maximum):
                errors[field_id] = [f"不能大于 {maximum}。"]
                continue
            cleaned[field_id] = number
        else:
            text = str(value).strip()
            max_length = 8000 if field_type == "long_text" else 1000
            if len(text) > max_length:
                errors[field_id] = [f"内容不能超过 {max_length} 个字符。"]
                continue
            cleaned[field_id] = text
    if errors:
        raise ServiceError("表单内容校验失败。", errors=errors, status=400)
    return cleaned


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def learning_web_page_view(request, pk):
    try:
        if request.user.role == "teacher":
            page = _teacher_learning_web_page(request, pk)
        elif request.user.role == "student":
            _profile, page, session, step = _student_learning_web_page_context(
                request, pk
            )
            ensure_classroom_step_opportunities(session=session)
            record_learning_page_opened(
                session=session,
                step=step,
                page=page,
                student=request.user,
                presentation=str(request.GET.get("presentation") or "unknown"),
            )
        else:
            raise ServiceError("当前角色无权查看学习网页。", status=403)
    except ServiceError as exc:
        return _service_fail(exc)
    except ClassroomEventError as exc:
        return fail(exc.message, status=400)
    return ok(learning_web_page_row(page))


@api_view(["POST"])
@permission_classes([IsStudent])
def student_learning_web_page_block_viewed(request, pk):
    try:
        _profile, page, session, step = _student_learning_web_page_context(request, pk)
        block_id = str(request.data.get("block_id") or "").strip()
        block_type = str(request.data.get("block_type") or "").strip()
        try:
            visible_ms = int(request.data.get("visible_ms"))
            visibility_ratio = float(request.data.get("visibility_ratio", 0.5))
        except (TypeError, ValueError) as exc:
            raise ServiceError("区块可见时长或比例格式不正确。", status=400) from exc
        if not block_id or len(block_id) > 64:
            raise ServiceError("学习网页区块编号不正确。", status=400)
        if not 250 <= visible_ms <= 3_600_000:
            raise ServiceError("区块可见时长需在 0.25 秒至 1 小时之间。", status=400)
        if not 0 <= visibility_ratio <= 1:
            raise ServiceError("区块可见比例需在 0 到 1 之间。", status=400)
        ensure_classroom_step_opportunities(session=session)
        record_learning_page_block_viewed(
            session=session,
            step=step,
            page=page,
            student=request.user,
            block_id=block_id,
            block_type=block_type,
            visible_ms=visible_ms,
            visibility_ratio=visibility_ratio,
        )
    except ServiceError as exc:
        return _service_fail(exc)
    except ClassroomEventError as exc:
        return fail(exc.message, status=400)
    return ok({}, "区块学习行为已记录。", status=201)


@api_view(["POST"])
@permission_classes([IsStudent])
def student_learning_web_page_submit(request, pk):
    try:
        profile, page, session, step = _student_learning_web_page_context(
            request, pk, for_submit=True
        )
        form_id = str(request.data.get("form_id") or "").strip()
        form = _learning_web_page_form(
            page.schema if isinstance(page.schema, dict) else {}, form_id
        )
        if form is None:
            raise ServiceError(
                "表单不存在或已被教师修改。",
                errors={"form_id": ["请刷新网页后重试。"]},
                status=400,
            )
        answers = _clean_learning_web_page_answers(form, request.data.get("answers"))
        with transaction.atomic():
            ensure_classroom_step_opportunities(session=session)
            latest_attempt = (
                LearningWebPageResponse.objects.filter(
                    page=page, student=request.user, form_id=form_id
                )
                .aggregate(max_attempt=Max("attempt_no"))
                .get("max_attempt")
                or 0
            )
            response = LearningWebPageResponse.objects.create(
                school=request.user.school,
                page=page,
                page_version=page.revision_no,
                student=request.user,
                class_group=profile.class_group,
                course=page.course,
                lesson=page.lesson,
                lesson_step=step,
                classroom_session=session,
                form_id=form_id,
                answers=answers,
                attempt_no=latest_attempt + 1,
            )
            record_learning_page_form_submission(response=response)
    except ServiceError as exc:
        return _service_fail(exc)
    except ClassroomEventError as exc:
        return fail(exc.message, status=400)
    return ok(learning_web_page_response_row(response), "表单已提交。", status=201)


def _student_dashboard_data(request, profile: StudentProfile) -> dict:
    courses = list(_student_course_queryset(profile)[:8])
    for course in courses:
        course.latest_lesson = (
            course.student_lessons[0]
            if getattr(course, "student_lessons", [])
            else None
        )

    events = LearningEvent.objects.filter(actor=request.user)
    notices = (
        Notice.objects.filter(
            school=request.user.school,
            status=Notice.Status.PUBLISHED,
            target_classes=profile.class_group,
        )
        .select_related("teacher")
        .order_by("-is_pinned", "-published_at", "-created_at")[:5]
        if profile.class_group_id
        else []
    )
    current_classroom = _student_current_classroom(profile)

    todo_rows = []
    if request.user.is_first_login or profile.is_first_use:
        todo_rows.append(
            {
                "label": "首次使用",
                "detail": "请完成改密、选班和前测。",
                "level": "warn",
                "path": "/student/onboarding",
            }
        )
    for course in courses:
        status = _student_required_pretest_status(request.user, course.subject)
        if status["required"] and not status["completed"]:
            todo_rows.append(
                {
                    "label": f"{course.subject.name if course.subject_id else '学科'}前测",
                    "detail": "进入课程前需要完成素养测试和学习态度问卷。",
                    "level": "warn",
                    "path": f"/student/pretests/{course.subject_id}",
                }
            )
            break
    if current_classroom:
        todo_rows.insert(
            0,
            {
                "label": "正在上课",
                "detail": current_classroom.title,
                "level": "live",
                "path": f"/student/classroom/{current_classroom.id}",
            },
        )
    if profile.class_group_id:
        now = timezone.now()
        pending_test = (
            TestAssessment.objects.filter(
                school=request.user.school,
                target_classes=profile.class_group,
                status=TestAssessment.Status.OPEN,
                is_active=True,
            )
            .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
            .filter(Q(end_at__isnull=True) | Q(end_at__gt=now))
            .exclude(
                attempts__student=request.user,
                attempts__status__in=[
                    TestAttempt.Status.SUBMITTED,
                    TestAttempt.Status.GRADED,
                ],
            )
            .order_by("end_at", "opened_at", "id")
            .first()
        )
        if pending_test:
            todo_rows.append(
                {
                    "label": "待完成测试",
                    "detail": pending_test.title,
                    "level": "warn",
                    "path": f"/student/assessments/{pending_test.id}",
                }
            )

    return {
        "profile": student_profile_summary(profile),
        "current_classroom": student_classroom_row(
            current_classroom,
            student_layer=_student_course_band(
                profile,
                current_classroom.course if current_classroom else None,
            ),
            student_user=request.user,
        ),
        "metrics": [
            {"label": "我的课程", "value": len(courses), "sub": "当前班级可见"},
            {"label": "学习事件", "value": events.count(), "sub": "已记录行为"},
            {
                "label": "近 7 天学习",
                "value": events.filter(
                    occurred_at__gte=timezone.now() - timedelta(days=7)
                ).count(),
                "sub": "行为事件",
            },
            {"label": "公告", "value": len(notices), "sub": "近期发布"},
        ],
        "todo_rows": todo_rows[:6],
        "course_rows": [
            student_course_row(
                course,
                pretest_status=_student_required_pretest_status(
                    request.user, course.subject
                ),
            )
            for course in courses
        ],
        "notice_rows": [student_notice_row(notice) for notice in notices],
        "teachers": [
            student_teacher_row(teacher) for teacher in _student_teachers(profile)
        ],
    }


@api_view(["GET"])
@permission_classes([IsStudent])
def student_me(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    current_classroom = _student_current_classroom(profile)
    return ok(
        {
            "user": user_summary(request.user),
            "profile": student_profile_summary(profile),
            "current_classroom": student_classroom_row(
                current_classroom,
                student_layer=_student_course_band(
                    profile,
                    current_classroom.course if current_classroom else None,
                ),
                student_user=request.user,
            ),
            "teachers": [
                student_teacher_row(teacher) for teacher in _student_teachers(profile)
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_dashboard(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(_student_dashboard_data(request, profile))


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


def _student_archive_event_label(event: LearningEvent) -> str:
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    action = str(metadata.get("action") or "")
    action_labels = {
        "step_enter": "进入学习环节",
        "step_complete": "完成学习环节",
        "learning_web_page_view": "查看 AI 学习任务单",
        "learning_web_page_form_submit": "提交 AI 学习任务单",
        "student_work_attachment_upload": "提交课堂作品",
        "lesson_step_answer_submit": "提交课堂题目",
    }
    return (
        action_labels.get(action)
        or STUDENT_ARCHIVE_EVENT_LABELS.get(event.event_type)
        or event.get_event_type_display()
    )


def _student_profile_archive_data(request, profile: StudentProfile) -> dict:
    raw_subject = request.query_params.get("subject")
    subject_id = None
    if raw_subject not in {None, ""}:
        try:
            subject_id = int(raw_subject)
        except (TypeError, ValueError):
            raise ServiceError(
                "学科参数不正确。", errors={"subject": ["请选择有效学科。"]}, status=400
            )
        selected_subject = Subject.objects.filter(
            pk=subject_id, school=request.user.school, is_active=True
        ).first()
        if selected_subject is None:
            raise ServiceError(
                "学科不存在或已停用。",
                errors={"subject": ["请选择有效学科。"]},
                status=404,
            )
    else:
        selected_subject = None

    courses = list(_student_course_queryset(profile))
    attempts = list(
        TestAttempt.objects.filter(student=request.user)
        .select_related(
            "assessment",
            "assessment__subject",
            "assessment__course",
            "assessment__teacher",
        )
        .annotate(total_possible=Sum("assessment__questions__score"))
        .order_by("-submitted_at", "-started_at")
    )
    pretests = list(
        PretestSubmission.objects.filter(student=request.user)
        .select_related("subject", "paper")
        .order_by("-submitted_at")
    )
    works = list(
        StudentWorkAttachment.objects.filter(student=request.user)
        .select_related(
            "course", "course__subject", "lesson", "lesson_step", "evaluated_by"
        )
        .order_by("-updated_at")
    )
    evaluations = list(
        ClassroomEvaluationSubmission.objects.filter(target=request.user)
        .select_related("course", "course__subject", "evaluator", "session")
        .order_by("-updated_at")
    )

    relevant_subjects = {}
    for course in courses:
        if course.subject_id:
            relevant_subjects[course.subject_id] = course.subject
    for attempt in attempts:
        if attempt.assessment.subject_id:
            relevant_subjects[attempt.assessment.subject_id] = (
                attempt.assessment.subject
            )
    for submission in pretests:
        relevant_subjects[submission.subject_id] = submission.subject
    if selected_subject is not None:
        relevant_subjects[selected_subject.id] = selected_subject

    if subject_id:
        courses = [item for item in courses if item.subject_id == subject_id]
        attempts = [
            item for item in attempts if item.assessment.subject_id == subject_id
        ]
        pretests = [item for item in pretests if item.subject_id == subject_id]
        works = [item for item in works if item.course.subject_id == subject_id]
        evaluations = [
            item for item in evaluations if item.course.subject_id == subject_id
        ]

    events = LearningEvent.objects.filter(actor=request.user)
    if subject_id:
        events = events.filter(course__subject_id=subject_id)

    course_rows = []
    for course in courses:
        course_events = events.filter(course=course)
        visited_lessons = (
            course_events.filter(
                event_type=LearningEvent.EventType.LESSON_ENTER,
                lesson_id__isnull=False,
            )
            .values("lesson_id")
            .distinct()
            .count()
        )
        completed_steps = set(
            course_events.filter(
                object_type="lesson_step", metadata__action="step_complete"
            )
            .exclude(object_id="")
            .values_list("object_id", flat=True)
        )
        step_count = int(getattr(course, "step_count", 0) or 0)
        latest_event = course_events.order_by("-occurred_at").first()
        course_rows.append(
            {
                "id": course.id,
                "title": course.title,
                "subject": subject_row(course.subject) if course.subject_id else None,
                "teacher": student_teacher_row(course.teacher),
                "lesson_count": int(getattr(course, "lesson_count", 0) or 0),
                "visited_lesson_count": visited_lessons,
                "step_count": step_count,
                "completed_step_count": (
                    min(len(completed_steps), step_count)
                    if step_count
                    else len(completed_steps)
                ),
                "progress_percent": (
                    round(min(len(completed_steps) * 100 / step_count, 100), 1)
                    if step_count
                    else 0
                ),
                "event_count": course_events.count(),
                "last_activity_at": latest_event.occurred_at if latest_event else None,
            }
        )

    test_rows = [
        {
            "id": attempt.id,
            "assessment_id": attempt.assessment_id,
            "title": attempt.assessment.title,
            "subject": subject_row(attempt.assessment.subject),
            "course": (
                {
                    "id": attempt.assessment.course_id,
                    "title": attempt.assessment.course.title,
                }
                if attempt.assessment.course_id
                else None
            ),
            "status": attempt.status,
            "status_label": attempt.get_status_display(),
            "objective_score": attempt.objective_score,
            "subjective_score": attempt.subjective_score,
            "total_score": attempt.total_score,
            "total_possible": float(getattr(attempt, "total_possible", 0) or 0),
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "graded_at": attempt.graded_at,
        }
        for attempt in attempts[:50]
    ]

    pretest_rows = [
        {
            "id": submission.id,
            "subject": subject_row(submission.subject),
            "paper_title": submission.paper.title,
            "kind": submission.paper.kind,
            "kind_label": submission.paper.get_kind_display(),
            "score": submission.score,
            "submitted_at": submission.submitted_at,
        }
        for submission in pretests[:30]
    ]

    work_rows = []
    for work in works[:50]:
        payload = student_work_attachment_row(work)
        work_rows.append(
            {
                **payload,
                "course_title": work.course.title,
                "subject": (
                    subject_row(work.course.subject) if work.course.subject_id else None
                ),
                "lesson_title": work.lesson.title,
                "step_title": work.lesson_step.title,
                "status": "evaluated" if work.evaluated_at else "submitted",
                "status_label": "已评价" if work.evaluated_at else "已提交",
            }
        )

    evaluation_rows = []
    for submission in evaluations[:50]:
        ratings = submission.ratings if isinstance(submission.ratings, dict) else {}
        numeric_ratings = [
            float(value)
            for value in ratings.values()
            if isinstance(value, (int, float))
        ]
        evaluation_rows.append(
            {
                "id": submission.id,
                "course": {
                    "id": submission.course_id,
                    "title": submission.course.title,
                },
                "subject": (
                    subject_row(submission.course.subject)
                    if submission.course.subject_id
                    else None
                ),
                "evaluation_type": submission.evaluation_type,
                "evaluation_type_label": submission.get_evaluation_type_display(),
                "average_rating": (
                    round(sum(numeric_ratings) / len(numeric_ratings), 1)
                    if numeric_ratings
                    else None
                ),
                "comment": submission.comment,
                "evaluator_label": (
                    submission.evaluator.display_name
                    if submission.evaluation_type
                    == ClassroomEvaluationSubmission.EvaluationType.TEACHER
                    else submission.get_evaluation_type_display()
                ),
                "updated_at": submission.updated_at,
            }
        )

    event_distribution = []
    event_count = events.count()
    distribution_counts = (
        events.values("event_type").annotate(value=Count("id")).order_by("-value")
    )
    for item in distribution_counts:
        label = STUDENT_ARCHIVE_EVENT_LABELS.get(item["event_type"])
        if not label:
            continue
        event_distribution.append(
            {
                "event_type": item["event_type"],
                "label": label,
                "value": item["value"],
                "percent": (
                    round(item["value"] * 100 / event_count, 1) if event_count else 0
                ),
            }
        )

    recent_events = []
    for event in events.select_related("course", "lesson").order_by("-occurred_at")[
        :60
    ]:
        recent_events.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "label": _student_archive_event_label(event),
                "course": (
                    {"id": event.course_id, "title": event.course.title}
                    if event.course_id
                    else None
                ),
                "lesson": (
                    {"id": event.lesson_id, "title": event.lesson.title}
                    if event.lesson_id
                    else None
                ),
                "duration_ms": event.duration_ms,
                "occurred_at": event.occurred_at,
            }
        )

    active_days = (
        events.annotate(day=TruncDate("occurred_at")).values("day").distinct().count()
    )
    completed_tests = sum(item.status == TestAttempt.Status.GRADED for item in attempts)
    latest_event = events.order_by("-occurred_at").first()
    return {
        "student": {
            "id": request.user.id,
            "username": request.user.username,
            "display_name": request.user.display_name or request.user.username,
            "student_no": profile.student_no,
            "school": (
                {"id": request.user.school_id, "name": request.user.school.name}
                if request.user.school_id
                else None
            ),
            "class_group": (
                class_group_row(profile.class_group) if profile.class_group_id else None
            ),
        },
        "subjects": [
            subject_row(item)
            for item in sorted(relevant_subjects.values(), key=lambda row: row.name)
        ],
        "selected_subject": subject_id,
        "metrics": {
            "course_count": len(courses),
            "active_day_count": active_days,
            "learning_event_count": event_count,
            "completed_test_count": completed_tests,
            "work_count": len(works),
            "last_activity_at": latest_event.occurred_at if latest_event else None,
        },
        "courses": course_rows,
        "pretests": pretest_rows,
        "tests": test_rows,
        "works": work_rows,
        "evaluations": evaluation_rows,
        "event_distribution": event_distribution,
        "recent_events": recent_events,
    }


@api_view(["GET"])
@permission_classes([IsStudent])
def student_profile_archive(request):
    try:
        profile = _student_profile(request)
        return ok(_student_profile_archive_data(request, profile))
    except ServiceError as exc:
        return _service_fail(exc)


@api_view(["GET"])
@permission_classes([IsStudent])
def student_onboarding(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(_student_dashboard_data(request, profile))


@api_view(["GET"])
@permission_classes([IsStudent])
def student_onboarding_classes(request):
    return ok(
        [
            class_group_row(class_group)
            for class_group in ClassGroup.objects.filter(
                school=_school(request), status=ClassGroup.Status.ACTIVE
            ).order_by("grade", "name")
        ]
    )


@api_view(["POST"])
@permission_classes([IsStudent])
def student_onboarding_password(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    password = str(request.data.get("password", "")).strip()
    if (
        len(password) < 6
        or len(password) > 32
        or any(char.isspace() for char in password)
    ):
        return fail(
            "密码需为 6-32 位，不能包含空格。",
            errors={"password": ["密码需为 6-32 位，不能包含空格。"]},
            status=400,
        )
    request.user.set_password(password)
    request.user.is_first_login = False
    request.user.save(update_fields=["password", "is_first_login"])
    update_session_auth_hash(request, request.user)
    profile.password_updated_at = timezone.now()
    profile.onboarding_status = StudentProfile.OnboardingStatus.PASSWORD_UPDATED
    profile.save(
        update_fields=["password_updated_at", "onboarding_status", "updated_at"]
    )
    write_audit(
        request,
        "student.onboarding.password",
        school=request.user.school,
        target_type="student_profile",
        target_id=profile.id,
    )
    return ok(student_profile_summary(profile), "密码已更新。")


@api_view(["POST"])
@permission_classes([IsStudent])
def student_onboarding_class(request):
    try:
        profile = _student_profile(request)
        class_id = int(request.data.get("class_group"))
    except (ServiceError, TypeError, ValueError) as exc:
        if isinstance(exc, ServiceError):
            return _service_fail(exc)
        return fail(
            "请选择班级。", errors={"class_group": ["请选择班级。"]}, status=400
        )
    class_group = ClassGroup.objects.filter(
        id=class_id, school=request.user.school, status=ClassGroup.Status.ACTIVE
    ).first()
    if class_group is None:
        return fail(
            "班级不存在或不可选择。",
            errors={"class_group": ["班级不存在或不可选择。"]},
            status=404,
        )
    profile.class_group = class_group
    profile.class_selected_at = timezone.now()
    profile.onboarding_status = StudentProfile.OnboardingStatus.CLASS_SELECTED
    profile.save(
        update_fields=[
            "class_group",
            "class_selected_at",
            "onboarding_status",
            "updated_at",
        ]
    )
    write_audit(
        request,
        "student.onboarding.class",
        school=request.user.school,
        target_type="student_profile",
        target_id=profile.id,
        detail={"class_group": class_group.id},
    )
    return ok(student_profile_summary(profile), "班级已选择。")


@api_view(["GET"])
@permission_classes([IsStudent])
def student_pretests_required(request):
    subjects = Subject.objects.filter(
        school=request.user.school, is_active=True
    ).order_by("name")
    return ok(
        [
            {
                "subject": subject_row(subject),
                "pretest_status": _student_required_pretest_status(
                    request.user, subject
                ),
            }
            for subject in subjects
        ]
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_pretests_for_subject(request, subject_id):
    subject = Subject.objects.filter(
        id=subject_id, school=request.user.school, is_active=True
    ).first()
    if subject is None:
        return fail("学科不存在或已停用。", status=404)
    papers = (
        PretestPaper.objects.filter(
            school=request.user.school,
            subject=subject,
            status=PretestPaper.Status.PUBLISHED,
        )
        .annotate(
            question_count=Count("questions", distinct=True),
            submission_count=Count("submissions", distinct=True),
        )
        .order_by("kind", "-version")
    )
    latest_by_kind: dict[str, PretestPaper] = {}
    for paper in papers:
        latest_by_kind.setdefault(paper.kind, paper)
    return ok(
        {
            "subject": subject_row(subject),
            "pretest_status": _student_required_pretest_status(request.user, subject),
            "papers": [pretest_paper_row(paper) for paper in latest_by_kind.values()],
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsStudent])
@transaction.atomic
def student_pretest_paper(request, paper_id):
    paper = (
        PretestPaper.objects.select_related("subject")
        .prefetch_related("questions")
        .filter(
            pk=paper_id,
            school=request.user.school,
            status=PretestPaper.Status.PUBLISHED,
        )
        .first()
    )
    if paper is None:
        return fail("前测不存在或未发布。", status=404)
    if request.method == "GET":
        return ok(student_pretest_paper_row(paper, include_questions=True))

    answers = request.data.get("answers")
    if not isinstance(answers, dict):
        return fail(
            "请提交前测答案。", errors={"answers": ["请提交前测答案。"]}, status=400
        )
    if PretestSubmission.objects.filter(student=request.user, paper=paper).exists():
        return fail("该前测已完成。", status=400)

    errors: dict[str, list[str]] = {}
    score = 0.0
    for question in paper.questions.all():
        key = str(question.id)
        answer = answers.get(key)
        if question.is_required and (answer is None or answer == "" or answer == []):
            errors[key] = ["该题必答。"]
            continue
        if question.answer and question.question_type in {
            PretestQuestion.QuestionType.SINGLE,
            PretestQuestion.QuestionType.MULTIPLE,
        }:
            expected = (
                question.answer
                if isinstance(question.answer, list)
                else [question.answer]
            )
            actual = answer if isinstance(answer, list) else [answer]
            if sorted(map(str, actual)) == sorted(map(str, expected)):
                score += float(question.score or 0)
    if errors:
        return fail("前测答案校验失败。", errors=errors, status=400)

    submission = PretestSubmission.objects.create(
        student=request.user,
        subject=paper.subject,
        paper=paper,
        answers=answers,
        score=score,
    )
    try:
        profile = _student_profile(request)
        status = _student_required_pretest_status(request.user, paper.subject)
        if status["required"] and status["completed"]:
            profile.pretest_completed_at = timezone.now()
            profile.onboarding_status = (
                StudentProfile.OnboardingStatus.PRETEST_COMPLETED
            )
            profile.is_first_use = False
            profile.save(
                update_fields=[
                    "pretest_completed_at",
                    "onboarding_status",
                    "is_first_use",
                    "updated_at",
                ]
            )
    except ServiceError:
        profile = None
    if profile is None:
        transaction.set_rollback(True)
        return fail("学生档案不存在，前测提交未保存。", status=500)
    try:
        record_pretest_submitted(submission=submission, profile=profile)
    except EventWriteError as exc:
        transaction.set_rollback(True)
        return fail(exc.message, status=500)
    return ok(
        {
            "id": submission.id,
            "score": submission.score,
            "submitted_at": submission.submitted_at,
        },
        "前测已提交。",
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_courses(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    rows = []
    for course in _student_course_queryset(profile):
        course.latest_lesson = (
            course.student_lessons[0]
            if getattr(course, "student_lessons", [])
            else None
        )
        rows.append(
            student_course_row(
                course,
                pretest_status=_student_required_pretest_status(
                    request.user, course.subject
                ),
            )
        )
    return ok(rows)


@api_view(["GET"])
@permission_classes([IsStudent])
def student_course_detail(request, pk):
    try:
        profile = _student_profile(request)
        course = _student_course(profile, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    lessons = (
        Lesson.objects.filter(course=course, is_active=True)
        .annotate(
            step_count=Count(
                "steps", filter=Q(steps__status=LessonStep.Status.READY), distinct=True
            )
        )
        .order_by("sort_order", "id")
    )
    lesson_rows = list(lessons)
    classroom_by_lesson = {}
    if profile.class_group_id and lesson_rows:
        sessions = (
            ClassroomSession.objects.filter(
                school=request.user.school,
                class_group=profile.class_group,
                lesson_id__in=[lesson.id for lesson in lesson_rows],
            )
            .select_related("current_step")
            .order_by("lesson_id", "-created_at", "-id")
        )
        for session in sessions:
            classroom_by_lesson.setdefault(session.lesson_id, session)
    row = student_course_row(
        course,
        pretest_status=_student_required_pretest_status(request.user, course.subject),
    )
    rows = []
    for lesson in lesson_rows:
        lesson_data = lesson_row(lesson) | {
            "step_count": getattr(lesson, "step_count", 0)
        }
        session = classroom_by_lesson.get(lesson.id)
        lesson_data["classroom_session"] = (
            {
                "id": session.id,
                "status": session.status,
                "status_label": session.get_status_display(),
                "current_step_status": session.current_step_status,
                "current_step_status_label": session.get_current_step_status_display(),
                "current_step_id": session.current_step_id,
                "submission_locked": session.submission_locked,
            }
            if session
            else None
        )
        rows.append(lesson_data)
    row["lessons"] = rows
    return ok(row)


@api_view(["GET"])
@permission_classes([IsStudent])
def student_course_lessons(request, course_id):
    try:
        profile = _student_profile(request)
        course = _student_course(profile, course_id)
    except ServiceError as exc:
        return _service_fail(exc)
    lessons = (
        Lesson.objects.filter(course=course, is_active=True)
        .annotate(
            step_count=Count(
                "steps", filter=Q(steps__status=LessonStep.Status.READY), distinct=True
            )
        )
        .order_by("sort_order", "id")
    )
    return ok(
        [
            lesson_row(lesson) | {"step_count": getattr(lesson, "step_count", 0)}
            for lesson in lessons
        ]
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_lesson_workspace(request, lesson_id):
    try:
        profile = _student_profile(request)
        lesson = _student_lesson(profile, lesson_id)
        _ensure_student_lesson_workspace_allowed(profile, lesson)
    except ServiceError as exc:
        return _service_fail(exc)
    steps = LessonStep.objects.filter(
        lesson=lesson, status=LessonStep.Status.READY
    ).order_by("sort_order", "id")
    return ok(
        {
            "course": student_course_row(
                lesson.course,
                pretest_status=_student_required_pretest_status(
                    request.user, lesson.course.subject
                ),
            ),
            "lesson": lesson_row(lesson),
            "steps": [student_lesson_step_row(step) for step in steps],
        }
    )


@api_view(["POST"])
@permission_classes([IsStudent])
def student_lesson_enter(request, lesson_id):
    try:
        profile = _student_profile(request)
        lesson = _student_lesson(profile, lesson_id)
        _ensure_student_lesson_workspace_allowed(profile, lesson)
    except ServiceError as exc:
        return _service_fail(exc)
    try:
        record_lesson_entered(student=request.user, profile=profile, lesson=lesson)
    except EventWriteError as exc:
        return fail(exc.message, status=500)
    return ok({}, "已记录进入课时。")


@api_view(["POST"])
@permission_classes([IsStudent])
def student_lesson_step_enter(request, step_id):
    try:
        profile = _student_profile(request)
        step = _student_lesson_step(profile, step_id)
    except ServiceError as exc:
        return _service_fail(exc)
    try:
        record_lesson_step_entered(student=request.user, profile=profile, step=step)
    except EventWriteError as exc:
        return fail(exc.message, status=500)
    return ok({}, "已记录进入环节。")


@api_view(["POST"])
@permission_classes([IsStudent])
def student_lesson_step_complete(request, step_id):
    try:
        profile = _student_profile(request)
        step = _student_lesson_step(profile, step_id)
    except ServiceError as exc:
        return _service_fail(exc)
    duration_ms = request.data.get("duration_ms", 0)
    try:
        record_lesson_step_completed(
            student=request.user,
            profile=profile,
            step=step,
            duration_ms=duration_ms,
        )
    except EventWriteError as exc:
        return fail(exc.message, status=500)
    return ok({}, "已记录完成环节。")


def _student_step_question(
    profile: StudentProfile, step: LessonStep, question_id: str
) -> dict:
    questions = normalize_lesson_question_items(
        step.question_items,
        include_answer=False,
        student_layer=_student_course_band(profile, step.lesson.course),
        apply_layering=lesson_step_has_layered_questions(step),
    )
    question = next(
        (item for item in questions if str(item.get("id")) == str(question_id)), None
    )
    if question is None:
        raise ServiceError("题目不存在或当前层级不可提交。", status=404)
    return question


def _validate_student_work_file(question: dict, uploaded_file) -> tuple[str, int]:
    if uploaded_file is None:
        raise ServiceError(
            "请选择要上传的文件。",
            errors={"attachment": ["请选择要上传的文件。"]},
            status=400,
        )
    config = (
        question.get("file_config")
        if isinstance(question.get("file_config"), dict)
        else {}
    )
    allowed_extensions = (
        config.get("allowed_extensions")
        if isinstance(config.get("allowed_extensions"), list)
        else []
    )
    allowed_extensions = [
        clean_resource_ext(item)
        for item in allowed_extensions
        if clean_resource_ext(item)
    ]
    if not allowed_extensions:
        allowed_extensions = [
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
        ]
    try:
        max_size_mb = int(config.get("max_size_mb", 100) or 100)
    except (TypeError, ValueError):
        max_size_mb = 100
    max_size = min(max(max_size_mb, 1), 512) * 1024 * 1024
    file_size = int(getattr(uploaded_file, "size", 0) or 0)
    if file_size <= 0:
        raise ServiceError(
            "上传文件为空。", errors={"attachment": ["上传文件为空。"]}, status=400
        )
    if file_size > max_size:
        raise ServiceError(
            f"文件不能超过 {max_size_mb}MB。",
            errors={"attachment": [f"文件不能超过 {max_size_mb}MB。"]},
            status=400,
        )
    ext = clean_resource_ext(Path(getattr(uploaded_file, "name", "")).suffix)
    if ext not in allowed_extensions:
        raise ServiceError(
            f"文件格式不支持，请上传：{', '.join(allowed_extensions)}。",
            errors={
                "attachment": [
                    f"文件格式不支持，请上传：{', '.join(allowed_extensions)}。"
                ]
            },
            status=400,
        )
    return ext, file_size


@api_view(["POST"])
@permission_classes([IsStudent])
@parser_classes([MultiPartParser, FormParser])
def student_lesson_step_attachment(request, step_id):
    try:
        profile = _student_profile(request)
        step = _student_lesson_step(profile, step_id)
        session = _ensure_student_step_classroom_open(profile, step, for_answer=True)
        question_id = str(request.data.get("question_id") or "").strip()
        question = _student_step_question(profile, step, question_id)
        if question.get("question_type") != "file":
            raise ServiceError("当前题目不是附件提交题。", status=400)
        uploaded_file = request.FILES.get("attachment")
        file_ext, file_size = _validate_student_work_file(question, uploaded_file)
    except ServiceError as exc:
        return _service_fail(exc)

    try:
        with transaction.atomic():
            ensure_classroom_step_opportunities(session=session)
            previous_work = (
                StudentWorkAttachment.objects.select_for_update()
                .filter(
                    student=request.user,
                    lesson_step=step,
                    question_id=question_id,
                )
                .order_by("-upload_version", "-id")
                .first()
            )
            work = StudentWorkAttachment(
                school=request.user.school,
                class_group=profile.class_group,
                course=step.lesson.course,
                lesson=step.lesson,
                lesson_step=step,
                classroom_session=session,
                student=request.user,
                question_id=question_id,
                question_stem=str(question.get("stem") or "")[:1000],
                upload_version=(
                    previous_work.upload_version + 1 if previous_work else 1
                ),
                supersedes=previous_work,
                attachment=uploaded_file,
                original_name=Path(
                    getattr(uploaded_file, "name", "") or "attachment"
                ).name[:255],
                file_ext=file_ext,
                file_size=file_size,
            )
            work.save()
            record_classroom_attachment_submission(work=work)
    except ClassroomEventError as exc:
        return fail(exc.message, status=400)

    payload = student_work_attachment_row(work)
    return ok(payload, "附件已上传。", status=201)


@api_view(["POST"])
@permission_classes([IsStudent])
def student_lesson_step_answer(request, step_id):
    try:
        profile = _student_profile(request)
        step = _student_lesson_step(profile, step_id)
        session = _ensure_student_step_classroom_open(profile, step, for_answer=True)
    except ServiceError as exc:
        return _service_fail(exc)
    answer = request.data.get("answer", "")
    questions = normalize_lesson_question_items(
        step.question_items,
        include_answer=True,
        student_layer=_student_course_band(profile, step.lesson.course),
        apply_layering=lesson_step_has_layered_questions(step),
    )
    progress = _lesson_step_answer_progress(questions, answer)
    missing = [
        row["stem"]
        for row in progress["answers"]
        if row["required"] and not row["is_answered"]
    ]
    if missing:
        return fail(
            f"请完成必答题：{missing[0]}",
            errors={"answer": [f"请完成必答题：{missing[0]}"]},
            status=400,
        )
    if not questions and not _answer_text_value(answer):
        return fail(
            "请先填写作答内容。",
            errors={"answer": ["请先填写作答内容。"]},
            status=400,
        )

    try:
        with transaction.atomic():
            ensure_classroom_step_opportunities(session=session)
            latest_attempt = (
                LessonStepAttempt.objects.select_for_update()
                .filter(
                    classroom_session=session,
                    lesson_step=step,
                    student=request.user,
                )
                .order_by("-attempt_no", "-id")
                .first()
            )
            attempt_no = latest_attempt.attempt_no + 1 if latest_attempt else 1
            if attempt_no > 100:
                raise ServiceError("当前环节提交次数已达到上限。", status=400)
            submitted_at = timezone.now()
            attempt = LessonStepAttempt.objects.create(
                school=request.user.school,
                class_group=profile.class_group,
                course=step.lesson.course,
                lesson=step.lesson,
                lesson_step=step,
                classroom_session=session,
                student=request.user,
                attempt_no=attempt_no,
                answer=answer,
                free_text=_answer_text_value(answer),
                answered_count=progress["answered_count"],
                question_count=progress["question_count"],
                auto_score=progress["auto_score"],
                auto_score_max=progress["auto_score_max"],
                submitted_at=submitted_at,
            )
            for row in progress["answers"]:
                question_id = row["question_id"]
                raw_question = classroom_question(step, question_id)
                response = _question_answer_value(answer, question_id)
                attachment = None
                if row["question_type"] == "file" and row["is_answered"]:
                    attachment_value = _answer_attachment_value(response)
                    attachment = StudentWorkAttachment.objects.filter(
                        pk=attachment_value.get("id") if attachment_value else None,
                        student=request.user,
                        classroom_session=session,
                        lesson_step=step,
                        question_id=question_id,
                    ).first()
                    if attachment is None:
                        raise ServiceError(
                            f"附件题“{row['stem'][:30]}”的上传记录无效，请重新上传。",
                            status=400,
                        )
                LessonStepAttemptAnswer.objects.create(
                    attempt=attempt,
                    question_id=question_id,
                    question_version=classroom_question_version(step, raw_question),
                    question_type=row["question_type"],
                    response=response,
                    is_answered=row["is_answered"],
                    auto_score=row["score"] if row["auto_gradable"] else None,
                    score_max=row["max_score"],
                    is_correct=row["is_correct"],
                    attachment=attachment,
                )
            record_classroom_attempt_events(attempt=attempt)
    except ServiceError as exc:
        return _service_fail(exc)
    except ClassroomEventError as exc:
        return fail(exc.message, status=400)
    return ok(
        {
            "attempt_id": str(attempt.attempt_id),
            "attempt_no": attempt.attempt_no,
            "answered_count": progress["answered_count"],
            "question_count": progress["question_count"],
            "auto_score": progress["auto_score"],
            "auto_score_max": progress["auto_score_max"],
        },
        "答案已提交。",
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_current_classroom(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    session = _student_current_classroom(profile)
    return ok(
        student_classroom_row(
            session,
            student_layer=_student_course_band(
                profile,
                session.course if session else None,
            ),
            student_user=request.user,
        )
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_classroom_detail(request, pk):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
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
        .filter(pk=pk, school=request.user.school, class_group=profile.class_group)
        .first()
    )
    if session is None:
        return fail("课堂不存在或无权进入。", status=404)
    if session.status != ClassroomSession.Status.RUNNING:
        return fail("课堂尚未开始，暂不能进入。", status=403)
    return ok(
        student_classroom_row(
            session,
            student_layer=_student_course_band(profile, session.course),
            student_user=request.user,
        )
    )


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


def _finite_request_number(data, field, *, minimum, maximum, integer=False):
    try:
        value = int(data.get(field)) if integer else float(data.get(field))
    except (TypeError, ValueError):
        raise ServiceError(
            "资源学习进度参数不正确。",
            errors={field: ["请输入有效数值。"]},
            status=400,
        )
    if not math.isfinite(float(value)) or value < minimum or value > maximum:
        raise ServiceError(
            "资源学习进度参数不正确。",
            errors={field: [f"数值必须在 {minimum} 到 {maximum} 之间。"]},
            status=400,
        )
    return value


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


@api_view(["POST"])
@permission_classes([IsStudent])
def student_classroom_video_progress(request, pk, resource_id):
    try:
        _profile, session, step = _student_classroom_resource_context(request, pk)
        position_seconds = _finite_request_number(
            request.data, "position_seconds", minimum=0, maximum=86_400
        )
        media_seconds = _finite_request_number(
            request.data, "media_seconds", minimum=0.001, maximum=86_400
        )
        playback_rate = _finite_request_number(
            request.data, "playback_rate", minimum=0.25, maximum=4
        )
        duration_ms = _finite_request_number(
            request.data,
            "duration_ms",
            minimum=0,
            maximum=600_000,
            integer=True,
        )
        record_classroom_video_progress(
            session=session,
            step=step,
            resource_id=resource_id,
            student=request.user,
            position_seconds=position_seconds,
            media_seconds=media_seconds,
            playback_rate=playback_rate,
            duration_ms=duration_ms,
        )
    except ServiceError as exc:
        return _service_fail(exc)
    except ClassroomEventError as exc:
        status = 404 if exc.code == "classroom_resource_missing" else 400
        return fail(exc.message, status=status)
    return ok({}, "视频进度已记录。", status=201)


@api_view(["POST"])
@permission_classes([IsStudent])
def student_classroom_document_progress(request, pk, resource_id):
    try:
        _profile, session, step = _student_classroom_resource_context(request, pk)
        page = _finite_request_number(
            request.data, "page", minimum=1, maximum=100_000, integer=True
        )
        page_count = _finite_request_number(
            request.data, "page_count", minimum=1, maximum=100_000, integer=True
        )
        visible_seconds = _finite_request_number(
            request.data, "visible_seconds", minimum=0, maximum=3_600
        )
        record_classroom_document_progress(
            session=session,
            step=step,
            resource_id=resource_id,
            student=request.user,
            page=page,
            page_count=page_count,
            visible_seconds=visible_seconds,
        )
    except ServiceError as exc:
        return _service_fail(exc)
    except ClassroomEventError as exc:
        status = 404 if exc.code == "classroom_resource_missing" else 400
        return fail(exc.message, status=status)
    return ok({}, "文档进度已记录。", status=201)


def _student_group_collaboration_context(request, session_id):
    profile = _student_profile(request)
    session = (
        ClassroomSession.objects.select_related(
            "teacher", "course", "lesson", "class_group"
        )
        .filter(
            pk=session_id, school=request.user.school, class_group=profile.class_group
        )
        .first()
    )
    if session is None:
        raise ServiceError("课堂不存在或无权进入。", status=404)
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("课堂尚未开始，暂不能进入小组合作。", status=403)
    collaboration = (
        ClassroomGroupCollaboration.objects.select_related("session")
        .filter(
            session=session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.OPEN,
        )
        .first()
    )
    if collaboration is None:
        return profile, session, None, None
    member = (
        ClassroomGroupMember.objects.select_related(
            "group", "group__collaboration", "student_profile", "student"
        )
        .filter(
            collaboration=collaboration,
            student=request.user,
            plan_version=collaboration.active_plan_version,
            group__is_active=True,
        )
        .first()
    )
    return profile, session, collaboration, member.group if member else None


@api_view(["GET"])
@permission_classes([IsStudent])
def student_classroom_group_collaboration(request, pk):
    try:
        profile, session, collaboration, group = _student_group_collaboration_context(
            request, pk
        )
    except ServiceError as exc:
        return _service_fail(exc)
    if collaboration is None or group is None:
        return ok(None)
    group = (
        _classroom_group_queryset(collaboration).filter(pk=group.pk).first() or group
    )
    return ok(student_classroom_group_collaboration_row(collaboration, my_group=group))


@api_view(["POST"])
@permission_classes([IsStudent])
@parser_classes([MultiPartParser, FormParser])
def student_classroom_group_file_upload(request, pk):
    file = None
    try:
        with transaction.atomic():
            (
                _profile,
                _session,
                collaboration,
                group,
            ) = _student_group_collaboration_context(request, pk)
            if collaboration is None or group is None:
                raise ServiceError("教师尚未开启你的小组合作。", status=404)
            if not collaboration.allow_student_upload:
                raise ServiceError("教师当前未开放小组共享文件上传。", status=403)
            file = _save_group_file(
                request,
                group,
                request.FILES.get("attachment"),
                str(request.data.get("description") or "").strip(),
            )
            record_group_file_shared(file=file, student=request.user)
    except ServiceError as exc:
        if file and file.attachment:
            file.attachment.delete(save=False)
        return _service_fail(exc)
    except GroupCollaborationEventError as exc:
        if file and file.attachment:
            file.attachment.delete(save=False)
        return fail(exc.message, status=400)
    return ok(classroom_group_file_row(file), "小组文件已上传", status=201)


@api_view(["POST"])
@permission_classes([IsStudent])
def student_classroom_activity_response(request, pk, activity_id):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    session = (
        ClassroomSession.objects.select_related(
            "teacher", "course", "lesson", "class_group"
        )
        .filter(pk=pk, school=request.user.school, class_group=profile.class_group)
        .first()
    )
    if session is None:
        return fail("课堂不存在或无权进入。", status=404)
    if session.status != ClassroomSession.Status.RUNNING:
        return fail("课堂尚未开始，暂不能响应。", status=403)
    activity = session.activities.filter(
        pk=activity_id, status=ClassroomActivity.Status.OPEN
    ).first()
    if activity is None:
        return fail("课堂活动不存在或已关闭。", status=404)

    metadata = activity.metadata if isinstance(activity.metadata, dict) else {}
    command = str(metadata.get("command") or activity.activity_type)
    response_type = str(request.data.get("response_type") or command).strip() or command
    content = str(request.data.get("content") or "").strip()[:1000]
    existing_query = LearningEvent.objects.filter(
        actor=request.user,
        object_type="classroom_activity",
        object_id=str(activity.id),
        metadata__action="classroom_activity_response",
        metadata__response_type=response_type,
    )
    if command == "sign_in":
        existing_query = existing_query.filter(metadata__source="student")
    existing = existing_query.first()
    if existing is not None and command != "quick_answer":
        return ok(classroom_activity_row(activity), "已记录过本次响应。")

    if command == "sign_in":
        try:
            record_attendance_status(
                activity=activity,
                student=request.user,
                recorder=request.user,
                attendance_status="signed",
                recorded_by="student",
            )
        except AttendanceEventError as exc:
            return fail(exc.message, status=400)
        return ok(classroom_activity_row(activity), "课堂响应已记录。")

    if command == "quick_answer":
        try:
            record_quick_answer_response(
                activity=activity,
                student=request.user,
                content=content,
            )
        except ClassroomInteractionEventError as exc:
            return fail(exc.message, status=400)
        return ok(classroom_activity_row(activity), "课堂响应已记录。")

    try:
        record_classroom_interaction_response(
            student=request.user,
            profile=profile,
            session=session,
            activity=activity,
            response_type=response_type,
            command=command,
            content=content,
        )
    except EventWriteError as exc:
        return fail(exc.message, status=500)
    return ok(classroom_activity_row(activity), "课堂响应已记录。")


@api_view(["POST"])
@permission_classes([IsStudent])
def student_classroom_score_feedback_ack(request, pk, activity_id):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    session = (
        ClassroomSession.objects.select_related(
            "teacher", "course", "lesson", "class_group"
        )
        .filter(pk=pk, school=request.user.school, class_group=profile.class_group)
        .first()
    )
    if session is None:
        return fail("课堂不存在或无权进入。", status=404)
    activity = session.activities.filter(pk=activity_id).first()
    if activity is None:
        return fail("课堂活动不存在。", status=404)
    try:
        score_event_id = int(request.data.get("score_event_id"))
    except (TypeError, ValueError):
        return fail(
            "评分事件不正确。",
            errors={"score_event_id": ["请提供评分事件。"]},
            status=400,
        )
    score_event = LearningEvent.objects.filter(
        Q(metadata__action="quick_answer_score")
        | Q(metadata__action="random_pick_score"),
        pk=score_event_id,
        actor=request.user,
        object_type="classroom_activity",
        object_id=str(activity.id),
    ).first()
    if score_event is None:
        return fail("评分反馈不存在或不属于当前学生。", status=404)
    existing = LearningEvent.objects.filter(
        Q(metadata__action="classroom_score_feedback_ack")
        | Q(metadata__action="quick_answer_score_feedback_ack"),
        actor=request.user,
        object_type="classroom_activity",
        object_id=str(activity.id),
        metadata__score_event_id=score_event.id,
    ).first()
    if existing is None:
        score_metadata = (
            score_event.metadata if isinstance(score_event.metadata, dict) else {}
        )
        try:
            record_intervention_acknowledged(
                student=request.user,
                profile=profile,
                session=session,
                object_type="classroom_activity",
                object_id=activity.id,
                intervention_type="score_feedback",
                action=str(score_metadata.get("command") or "score_feedback"),
                points=score_event.score,
                legacy_score=score_event.score,
                legacy_metadata={
                    "action": "classroom_score_feedback_ack",
                    "command": score_metadata.get("command", ""),
                    "score_event_id": score_event.id,
                    "score": score_event.score,
                    "score_action": score_metadata.get("score_action", ""),
                    "activity_title": activity.title,
                },
            )
        except EventWriteError as exc:
            return fail(exc.message, status=500)
    return ok({"score_event_id": score_event.id}, "评分反馈已确认。")


@api_view(["GET"])
@permission_classes([IsStudent])
def student_notices(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    notices = (
        Notice.objects.filter(
            school=request.user.school,
            status=Notice.Status.PUBLISHED,
            target_classes=profile.class_group,
        )
        .select_related("teacher")
        .order_by("-is_pinned", "-published_at", "-created_at")
    )
    page = _paginate(request, notices)
    page.object_list = [student_notice_row(notice) for notice in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "POST"])
@permission_classes([IsStudent])
def student_feedback(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    if not profile.class_group_id:
        return fail("请先完成班级选择。", status=400)

    if request.method == "POST":
        errors: dict[str, list[str]] = {}
        title = str(request.data.get("title", "")).strip()
        content = str(request.data.get("content", "")).strip()
        category = (
            str(request.data.get("category", Feedback.Category.STUDY)).strip()
            or Feedback.Category.STUDY
        )
        try:
            teacher_id = int(request.data.get("teacher"))
        except (TypeError, ValueError):
            teacher_id = 0
        teacher = _student_teachers(profile).filter(pk=teacher_id).first()
        if teacher is None:
            errors["teacher"] = ["请选择任课教师。"]
        if category not in {item.value for item in Feedback.Category}:
            errors["category"] = ["反馈类型不正确。"]
        if len(title) < 2 or len(title) > 128:
            errors["title"] = ["标题需为 2-128 个字符。"]
        if len(content) < 2 or len(content) > 3000:
            errors["content"] = ["内容需为 2-3000 个字符。"]
        if errors:
            return fail("留言反馈校验失败。", errors=errors, status=400)
        feedback = Feedback.objects.create(
            school=request.user.school,
            class_group=profile.class_group,
            teacher=teacher,
            student=request.user,
            category=category,
            title=title,
            content=content,
        )
        write_audit(
            request,
            "student.feedback.create",
            school=request.user.school,
            target_type="feedback",
            target_id=feedback.id,
            detail={"teacher": teacher.id, "category": category},
        )
        return ok(student_feedback_row(feedback), "留言已提交。", status=201)

    query = request.GET.get("q", "").strip()
    feedback_items = (
        Feedback.objects.filter(school=request.user.school, student=request.user)
        .select_related("teacher")
        .order_by("-created_at")
    )
    if query:
        feedback_items = feedback_items.filter(
            Q(title__icontains=query) | Q(content__icontains=query)
        )
    page = _paginate(request, feedback_items)
    page.object_list = [student_feedback_row(item) for item in page.object_list]
    return ok(page_data(page))


@api_view(["GET"])
@permission_classes([IsStudent])
def student_feedback_detail(request, pk):
    feedback = (
        Feedback.objects.filter(pk=pk, school=request.user.school, student=request.user)
        .select_related("teacher")
        .first()
    )
    if feedback is None:
        return fail("留言反馈不存在。", status=404)
    return ok(student_feedback_row(feedback))
