from __future__ import annotations

import json
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.http import JsonResponse
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import TruncDate
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from config.onlyoffice import sign_editor_config
from aiops.models import ModelVersion, TrainingJob
from courses.models import (
    ClassroomActivity,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
    Subject,
)
from learning.models import Feedback, LearningEvent, Notice, PretestPaper, PretestQuestion, PretestSubmission, StratificationDecision
from ops.models import AuditLog, ExportBatch, ImportBatch
from ops.xlsx import export_rows, template_response
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment

from .permissions import IsSchoolAdmin, IsStudent, IsSuperAdmin, IsTeacher
from .responses import fail, ok, page_data
from .serializers import (
    account_row,
    classroom_activity_row,
    classroom_session_row,
    class_group_row,
    clean_resource_ext,
    course_row,
    feedback_row,
    lesson_row,
    lesson_step_row,
    notice_row,
    pretest_paper_row,
    pretest_question_row,
    resource_row,
    school_row,
    student_row,
    student_classroom_row,
    student_course_row,
    student_feedback_row,
    student_lesson_step_row,
    student_notice_row,
    student_pretest_paper_row,
    student_profile_summary,
    student_teacher_row,
    subject_row,
    teacher_ai_provider_row,
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


def _paginate(request, rows, per_page=20):
    try:
        page_size = min(max(int(request.GET.get("page_size", per_page)), 1), 100)
    except ValueError:
        page_size = per_page
    paginator = Paginator(rows, page_size)
    return paginator.get_page(request.GET.get("page") or 1)


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
        {"label": (start + timedelta(days=offset)).strftime("%m-%d"), "count": by_day.get(start + timedelta(days=offset), 0)}
        for offset in range(days)
    ]


def _day_distinct_series(queryset, date_field: str, distinct_field: str, days=7) -> list[dict]:
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
        {"label": (start + timedelta(days=offset)).strftime("%m-%d"), "count": by_day.get(start + timedelta(days=offset), 0)}
        for offset in range(days)
    ]


def _choice_counts(queryset, field: str, choices) -> list[dict]:
    rows = queryset.values(field).annotate(count=Count("id"))
    by_value = {item[field]: item["count"] for item in rows}
    return [{"label": label, "value": value, "count": by_value.get(value, 0)} for value, label in choices]


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
            "label": f"{class_group.grade} {class_group.name}".strip() or class_group.name,
            "count": getattr(class_group, "student_count", 0),
        }
        for class_group in classes
    ]


def _class_teacher_counts(classes) -> list[dict]:
    return [
        {
            "label": f"{class_group.grade} {class_group.name}".strip() or class_group.name,
            "count": getattr(class_group, "teacher_count", 0),
        }
        for class_group in classes
    ]


def _class_event_counts(classes) -> list[dict]:
    return [
        {
            "label": f"{class_group.grade} {class_group.name}".strip() or class_group.name,
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


def _school(request):
    return request.user.school


def _school_users(request):
    User = get_user_model()
    return User.objects.filter(school=_school(request))


def _service_fail(exc: ServiceError):
    return fail(exc.message, errors=exc.errors, status=exc.status)


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
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    school_scale_rows = list(
        School.objects.annotate(
            student_count=Count("users__student_profile", distinct=True),
            class_count=Count("classes", distinct=True),
        ).order_by("-student_count", "name")[:10]
    )

    data = {
        "metrics": [
            {"label": "学校", "value": School.objects.count(), "sub": "已登记学校"},
            {"label": "学校管理员", "value": User.objects.filter(role="school_admin").count(), "sub": "本地管理账号"},
            {"label": "教师", "value": User.objects.filter(role="teacher").count(), "sub": "教师账号"},
            {"label": "学生档案", "value": StudentProfile.objects.count(), "sub": "已建档学生"},
            {"label": "班级", "value": ClassGroup.objects.count(), "sub": "行政/教学班"},
            {"label": "行为事件", "value": LearningEvent.objects.count(), "sub": "学习过程记录"},
        ],
        "status": {
            "pending_imports": ImportBatch.objects.filter(status=ImportBatch.Status.UPLOADED).count(),
            "failed_imports": ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).count(),
            "model_versions": ModelVersion.objects.count(),
            "training_jobs_7d": TrainingJob.objects.filter(created_at__gte=timezone.now() - timedelta(days=7)).count(),
            "pending_decisions": StratificationDecision.objects.filter(status=StratificationDecision.Status.PENDING).count(),
        },
        "charts": {
            "school_status": _choice_counts(School.objects.all(), "status", School.Status.choices),
            "import_status": _choice_counts(ImportBatch.objects.all(), "status", ImportBatch.Status.choices),
            "account_roles": _choice_counts(User.objects.all(), "role", User.Role.choices),
            "learning_events_7d": _day_series(LearningEvent.objects.all(), "occurred_at", days=7),
            "training_jobs_7d": _day_series(
                TrainingJob.objects.filter(created_at__gte=timezone.now() - timedelta(days=7)),
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
            for item in ImportBatch.objects.select_related("source_school", "uploaded_by")[:6]
        ],
        "recent_logs": [
            {"id": log.id, "action": log.action, "actor": str(log.actor) if log.actor_id else "", "created_at": log.created_at}
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
    schools = School.objects.annotate(
        class_count=Count("classes", distinct=True),
        user_count=Count("users", distinct=True),
    ).order_by("name", "code")
    if query:
        schools = schools.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(contact_name__icontains=query))
    if status:
        schools = schools.filter(status=status)
    page = _paginate(request, schools)
    page.object_list = [school_row(school) for school in page.object_list]
    return ok(page_data(page))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSuperAdmin])
def super_admin_school_detail(request, pk):
    school = School.objects.annotate(
        class_count=Count("classes", distinct=True),
        user_count=Count("users", distinct=True),
    ).filter(pk=pk).first()
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
    users = User.objects.filter(role="school_admin").select_related("school").order_by("school__name", "username")
    if query:
        users = users.filter(Q(username__icontains=query) | Q(display_name__icontains=query) | Q(phone__icontains=query))
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
    user = User.objects.filter(pk=pk, role="school_admin").select_related("school").first()
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
    user = User.objects.filter(pk=pk, role="school_admin").select_related("school").first()
    if user is None:
        return fail("学校管理员不存在。", status=404)
    is_active = bool(request.data.get("is_active"))
    set_account_active(request, user, is_active, action_prefix="school_admin")
    return ok(account_row(user), "账号状态已更新")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_school_admin_reset_password(request, pk):
    User = get_user_model()
    user = User.objects.filter(pk=pk, role="school_admin").select_related("school").first()
    if user is None:
        return fail("学校管理员不存在。", status=404)
    try:
        reset_school_admin_password(request, user, str(request.data.get("password", "")))
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
    decisions = StratificationDecision.objects.filter(class_group__school=school)
    today = timezone.localdate()
    inactive_accounts = users.filter(is_active=False).count()
    first_login_accounts = users.filter(is_first_login=True, is_active=True).count()
    pending_onboarding = StudentProfile.objects.filter(user__school=school, is_first_use=True, user__is_active=True).count()
    pending_pretest = (
        StudentProfile.objects.filter(user__school=school, user__is_active=True)
        .exclude(onboarding_status__in=[StudentProfile.OnboardingStatus.PRETEST_COMPLETED, StudentProfile.OnboardingStatus.ACTIVE])
        .count()
    )
    failed_training = training_jobs.filter(status=TrainingJob.Status.FAILED).count()
    pending_decisions = decisions.filter(status=StratificationDecision.Status.PENDING).count()
    failed_exports = ExportBatch.objects.filter(school=school, status=ExportBatch.Status.FAILED).count()
    class_rows = list(
        classes.annotate(student_count=Count("students", distinct=True), teacher_count=Count("teachers", distinct=True))
        .order_by("grade", "name")[:12]
    )
    teacher_rows = list(
        users.filter(role="teacher")
        .annotate(class_count=Count("teaching_assignments__class_group", distinct=True))
        .order_by("-class_count", "display_name", "username")[:12]
    )
    last_7d_events = events.filter(occurred_at__gte=timezone.now() - timedelta(days=7))
    active_students = students.filter(user__is_active=True)
    class_activity_rows = list(
        classes.annotate(event_count=Count("learningevent", filter=Q(learningevent__occurred_at__gte=timezone.now() - timedelta(days=7)), distinct=True))
        .order_by("-event_count", "grade", "name")[:12]
    )

    data = {
        "school": {"id": school.id, "name": school.name, "code": school.code},
        "metrics": [
            {"label": "教师", "value": users.filter(role="teacher").count(), "sub": "本校教师"},
            {"label": "学生", "value": students.count(), "sub": "已建档学生"},
            {"label": "班级", "value": classes.count(), "sub": "本校班级"},
            {"label": "课程", "value": Course.objects.filter(teacher__school=school).count(), "sub": "本校教师课程"},
            {"label": "今日行为", "value": events.filter(occurred_at__date=today).count(), "sub": "学习过程事件"},
            {
                "label": "待处理",
                "value": inactive_accounts
                + first_login_accounts
                + pending_onboarding
                + pending_pretest
                + failed_training
                + pending_decisions
                + failed_exports,
                "sub": "账号、前测、训练和导出",
            },
        ],
        "login_series": _day_series(events.filter(event_type=LearningEvent.EventType.LOGIN), "occurred_at", days=7),
        "event_series": _day_series(events, "occurred_at", days=7),
        "charts": {
            "account_roles": _choice_counts(users, "role", [("teacher", "教师"), ("student", "学生")]),
            "account_status": _flag_counts(users, "is_active", "启用", "停用"),
            "student_onboarding": _choice_counts(students, "onboarding_status", StudentProfile.OnboardingStatus.choices),
            "student_class_status": [
                {"label": "已分班", "value": "assigned", "count": active_students.filter(class_group__isnull=False).count()},
                {"label": "未分班", "value": "unassigned", "count": active_students.filter(class_group__isnull=True).count()},
            ],
            "student_layers": [
                {"label": label, "value": value, "count": students.filter(current_layer=value).count()}
                for value, label in StudentProfile.Layer.choices
            ]
            + [{"label": "未分层", "value": "unassigned", "count": students.filter(current_layer__isnull=True).count()}],
            "class_status": _choice_counts(classes, "status", ClassGroup.Status.choices),
            "class_students": _class_student_counts(class_rows),
            "class_teachers": _class_teacher_counts(class_rows),
            "teacher_load": _teacher_class_counts(teacher_rows),
            "class_activity": _class_event_counts(class_activity_rows),
            "event_types": _event_type_counts(last_7d_events),
            "pretest_status": _choice_counts(PretestPaper.objects.filter(school=school), "status", PretestPaper.Status.choices),
            "training_status": _choice_counts(training_jobs, "status", TrainingJob.Status.choices),
            "login_series": _day_series(events.filter(event_type=LearningEvent.EventType.LOGIN), "occurred_at", days=7),
            "event_series": _day_series(events, "occurred_at", days=7),
            "active_students_7d": _day_distinct_series(last_7d_events.filter(actor__role="student"), "occurred_at", "actor", days=7),
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
            {"label": "停用账号", "count": inactive_accounts, "level": "warn" if inactive_accounts else "ok"},
            {"label": "首次登录未改密", "count": first_login_accounts, "level": "warn" if first_login_accounts else "ok"},
            {"label": "新生首次使用", "count": pending_onboarding, "level": "warn" if pending_onboarding else "ok"},
            {"label": "未完成前测", "count": pending_pretest, "level": "warn" if pending_pretest else "ok"},
            {"label": "训练失败", "count": failed_training, "level": "failed" if failed_training else "ok"},
            {"label": "待确认分层", "count": pending_decisions, "level": "warn" if pending_decisions else "ok"},
            {"label": "导出失败", "count": failed_exports, "level": "failed" if failed_exports else "ok"},
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
        teachers = teachers.filter(Q(username__icontains=query) | Q(display_name__icontains=query) | Q(phone__icontains=query))
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
        teachers = teachers.filter(Q(username__icontains=query) | Q(display_name__icontains=query) | Q(phone__icontains=query))
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
        ["登录账号", "姓名", "联系电话", "状态", "首次登录", "最近登录", "创建时间", "任课班级数"],
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
        return fail("请选择 xlsx 文件。", errors={"file": ["请选择 xlsx 文件。"]}, status=400)
    if not uploaded_file.name.lower().endswith(".xlsx"):
        return fail("只能上传 xlsx 文件。", errors={"file": ["只能上传 xlsx 文件。"]}, status=400)
    try:
        result = import_teachers_from_xlsx(request, uploaded_file)
    except ServiceError as exc:
        return _service_fail(exc)
    except ValueError as exc:
        return fail(str(exc), errors={"file": [str(exc)]}, status=400)
    return ok(result, f"教师批量导入完成：新增 {result['created_count']} 个，更新 {result['updated_count']} 个。")


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
    students = StudentProfile.objects.filter(user__school=_school(request)).select_related("user", "class_group")
    if query:
        students = students.filter(
            Q(user__username__icontains=query) | Q(user__display_name__icontains=query) | Q(student_no__icontains=query)
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
    page = _paginate(request, students.order_by("class_group__grade", "class_group__name", "student_no"))
    page.object_list = [student_row(profile) for profile in page.object_list]
    return ok(page_data(page))


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_students_export(request):
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    status = request.GET.get("status", "").strip()
    layer = request.GET.get("layer", "").strip()
    students = StudentProfile.objects.filter(user__school=_school(request)).select_related("user", "class_group")
    if query:
        students = students.filter(
            Q(user__username__icontains=query) | Q(user__display_name__icontains=query) | Q(student_no__icontains=query)
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
        for profile in students.order_by("class_group__grade", "class_group__name", "student_no")
    ]
    return export_rows(
        _xlsx_filename(f"{_school(request).code}_学生管理"),
        "学生管理",
        ["登录账号", "姓名", "学号", "班级", "联系电话", "层级", "小组号", "积分", "首次使用状态", "账号状态", "最近登录", "更新时间"],
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
        return fail("请选择 xlsx 文件。", errors={"file": ["请选择 xlsx 文件。"]}, status=400)
    if not uploaded_file.name.lower().endswith(".xlsx"):
        return fail("只能上传 xlsx 文件。", errors={"file": ["只能上传 xlsx 文件。"]}, status=400)
    try:
        result = import_students_from_xlsx(request, uploaded_file)
    except ServiceError as exc:
        return _service_fail(exc)
    except ValueError as exc:
        return fail(str(exc), errors={"file": [str(exc)]}, status=400)
    return ok(result, f"学生批量导入完成：新增 {result['created_count']} 个，更新 {result['updated_count']} 个。")


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
    page.object_list = [class_group_row(class_group) for class_group in page.object_list]
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
    return ok(result, f"已毕业归档 {result['graduated_count']} 个班级，并停用 {result['disabled_students']} 个学生账号。")


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSchoolAdmin])
def school_admin_class_detail(request, pk):
    class_group = (
        ClassGroup.objects.filter(pk=pk, school=_school(request))
        .annotate(student_count=Count("students", distinct=True), teacher_count=Count("teachers", distinct=True))
        .first()
    )
    if class_group is None:
        return fail("班级不存在。", status=404)

    if request.method == "GET":
        return ok(class_group_row(class_group))
    if request.method == "PATCH":
        try:
            class_group = save_class_group(request, request.data, class_group=class_group)
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
        .annotate(course_count=Count("courses", distinct=True), pretest_count=Count("pretest_papers", distinct=True))
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
        .annotate(question_count=Count("questions", distinct=True), submission_count=Count("submissions", distinct=True))
    )
    if subject_id:
        papers = papers.filter(subject_id=subject_id)
    if kind:
        papers = papers.filter(kind=kind)
    if status:
        papers = papers.filter(status=status)
    if query:
        papers = papers.filter(Q(title__icontains=query) | Q(subject__name__icontains=query) | Q(subject__code__icontains=query))
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
        .annotate(question_count=Count("questions", distinct=True), submission_count=Count("submissions", distinct=True))
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
    paper = PretestPaper.objects.filter(pk=pk, school=_school(request)).select_related("subject").first()
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
    paper = PretestPaper.objects.filter(pk=pk, school=_school(request)).select_related("subject").first()
    if paper is None:
        return fail("前测套卷不存在。", status=404)
    paper = archive_pretest_paper(request, paper)
    paper.question_count = paper.questions.count()
    paper.submission_count = paper.submissions.count()
    return ok(pretest_paper_row(paper), "前测套卷已归档")


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_pretest_questions(request, paper_id):
    paper = PretestPaper.objects.filter(pk=paper_id, school=_school(request)).select_related("subject").first()
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
        PretestQuestion.objects.filter(pk=pk, paper_id=paper_id, paper__school=_school(request))
        .select_related("paper", "paper__subject")
        .first()
    )
    if question is None:
        return fail("题目不存在。", status=404)

    if request.method == "PATCH":
        try:
            question = save_pretest_question(request, question.paper, request.data, question=question)
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
    teachers = User.objects.filter(school=school, role="teacher", is_active=True).order_by("username")
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
        classes_by_teacher.setdefault(assignment.teacher_id, []).append(assignment.class_group)
    return [teaching_teacher_row(teacher, classes_by_teacher.get(teacher.id, [])) for teacher in teachers]


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
    assignments = TeachingAssignment.objects.filter(school=school).select_related("school", "class_group", "teacher")
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
        for item in _teaching_teacher_rows(list(_filtered_teaching_teachers(request)), _school(request))
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
            assignment = save_teaching_assignment(request, request.data, assignment=assignment)
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
        .annotate(student_count=Count("students", distinct=True), teacher_count=Count("teachers", distinct=True))
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
    students = StudentProfile.objects.filter(user__school=school, class_group_id__in=class_ids)
    events = LearningEvent.objects.filter(class_group_id__in=class_ids)
    decisions = StratificationDecision.objects.filter(class_group_id__in=class_ids)
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
                filter=Q(learningevent__occurred_at__gte=timezone.now() - timedelta(days=7)),
                distinct=True,
            ),
        ).order_by("grade", "name")
    )
    active_students = students.filter(user__is_active=True)
    pending_decisions = decisions.filter(status=StratificationDecision.Status.PENDING).count()
    first_login_students = active_students.filter(user__is_first_login=True).count()
    pending_pretest = (
        active_students.exclude(
            onboarding_status__in=[
                StudentProfile.OnboardingStatus.PRETEST_COMPLETED,
                StudentProfile.OnboardingStatus.ACTIVE,
            ]
        ).count()
    )
    inactive_students = students.filter(user__is_active=False).count()

    data = {
        "school": {"id": school.id, "name": school.name, "code": school.code},
        "metrics": [
            {"label": "任教班级", "value": len(class_ids), "sub": "学校已分配"},
            {"label": "学生", "value": students.count(), "sub": "任教班级内"},
            {"label": "课程", "value": courses.count(), "sub": "本人课程"},
            {"label": "资源", "value": resources.count(), "sub": "本人上传"},
            {"label": "今日行为", "value": events.filter(occurred_at__date=today).count(), "sub": "任教班级内"},
            {"label": "待确认分层", "value": pending_decisions, "sub": "AI 分层建议"},
        ],
        "charts": {
            "event_series": _day_series(events, "occurred_at", days=7),
            "login_series": _day_series(events.filter(event_type=LearningEvent.EventType.LOGIN), "occurred_at", days=7),
            "active_students_7d": _day_distinct_series(
                last_7d_events.filter(actor__role="student"),
                "occurred_at",
                "actor",
                days=7,
            ),
            "class_students": _class_student_counts(class_rows),
            "class_activity": _class_event_counts(class_rows),
            "student_layers": [
                {"label": label, "value": value, "count": students.filter(current_layer=value).count()}
                for value, label in StudentProfile.Layer.choices
            ]
            + [{"label": "未分层", "value": "unassigned", "count": students.filter(current_layer__isnull=True).count()}],
            "event_types": _event_type_counts(last_7d_events),
            "decision_status": _choice_counts(decisions, "status", StratificationDecision.Status.choices),
            "training_status": _choice_counts(training_jobs, "status", TrainingJob.Status.choices),
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
            {"label": "待确认分层", "count": pending_decisions, "level": "warn" if pending_decisions else "ok"},
            {"label": "学生首次登录", "count": first_login_students, "level": "warn" if first_login_students else "ok"},
            {"label": "未完成前测", "count": pending_pretest, "level": "warn" if pending_pretest else "ok"},
            {"label": "停用学生账号", "count": inactive_students, "level": "failed" if inactive_students else "ok"},
        ],
    }
    return ok(data)


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_classes(request):
    return ok([class_group_row(class_group) for class_group in _teacher_classes(request)])


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
            return fail("班级筛选条件不正确。", errors={"class": ["班级筛选条件不正确。"]}, status=400)
        if selected_class_id not in class_ids:
            return fail("无权查看该班级。", errors={"class": ["无权查看该班级。"]}, status=403)
        students = students.filter(class_group_id=selected_class_id)
    if status == "active":
        students = students.filter(user__is_active=True)
    elif status == "disabled":
        students = students.filter(user__is_active=False)
    if layer in {"A", "B", "C"}:
        students = students.filter(current_layer=layer)
    elif layer == "unassigned":
        students = students.filter(current_layer__isnull=True)

    page = _paginate(request, students.order_by("class_group__grade", "class_group__name", "student_no", "user__username"))
    page.object_list = [student_row(profile) for profile in page.object_list]
    return ok(page_data(page))


def _teacher_student_ids_from_payload(request):
    raw_ids = request.data.get("ids") if hasattr(request.data, "get") else None
    if not isinstance(raw_ids, list):
        raise ServiceError("请选择要操作的学生。", errors={"ids": ["请选择要操作的学生。"]}, status=400)

    ids: list[int] = []
    for raw_id in raw_ids:
        try:
            student_id = int(raw_id)
        except (TypeError, ValueError):
            raise ServiceError("所选学生包含无效编号。", errors={"ids": ["所选学生包含无效编号。"]}, status=400)
        if student_id <= 0:
            raise ServiceError("所选学生包含无效编号。", errors={"ids": ["所选学生包含无效编号。"]}, status=400)
        if student_id not in ids:
            ids.append(student_id)

    if not ids:
        raise ServiceError("请选择要操作的学生。", errors={"ids": ["请选择要操作的学生。"]}, status=400)
    if len(ids) > 100:
        raise ServiceError("单次最多重置 100 个学生密码。", errors={"ids": ["单次最多重置 100 个学生密码。"]}, status=400)
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

    profiles = list(_teacher_students(request).filter(pk__in=ids).order_by("class_group__grade", "class_group__name", "student_no"))
    found_ids = {profile.id for profile in profiles}
    missing = [str(student_id) for student_id in ids if student_id not in found_ids]
    if missing:
        return fail("部分学生不存在或不在你的任教班级中。", errors={"ids": [f"无权操作：{', '.join(missing)}"]}, status=404)

    inactive = [profile for profile in profiles if not profile.user.is_active]
    if inactive:
        names = ", ".join(profile.user.display_name or profile.user.username for profile in inactive[:10])
        return fail("所选学生包含停用账号，请联系学校管理员处理。", errors={"ids": [f"停用账号：{names}"]}, status=400)

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
                queryset=CourseClass.objects.select_related("class_group").order_by("class_group__grade", "class_group__name"),
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
        courses = courses.filter(Q(title__icontains=query) | Q(introduction__icontains=query))
    if subject_id:
        try:
            courses = courses.filter(subject_id=int(subject_id))
        except ValueError:
            return None, fail("学科筛选条件不正确。", errors={"subject": ["学科筛选条件不正确。"]}, status=400)
    if status == "published":
        courses = courses.filter(is_active=True)
    elif status == "draft":
        courses = courses.filter(is_active=False)
    elif status:
        return None, fail("状态筛选条件不正确。", errors={"status": ["状态筛选条件不正确。"]}, status=400)
    return courses, None


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_course_options(request):
    courses = (
        _teacher_courses_queryset(request)
        .filter(course_classes__isnull=False)
        .prefetch_related(
            Prefetch("lessons", queryset=Lesson.objects.order_by("sort_order", "id"), to_attr="prefetched_lessons")
        )
        .distinct()
        .order_by("-is_active", "-updated_at")
    )
    return ok(
        {
            "subjects": [
                subject_row(subject)
                for subject in Subject.objects.filter(school=_school(request), is_active=True).annotate(
                    course_count=Count("courses", distinct=True),
                    pretest_count=Count("pretest_papers", distinct=True),
                )
            ],
            "classes": [class_group_row(class_group) for class_group in _teacher_classes(request)],
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


def _resource_can_open(request, resource: Resource) -> bool:
    user = request.user
    if not user.is_authenticated:
        return False
    if user.role == "teacher":
        return resource.owner_id == user.id and resource.owner.school_id == user.school_id
    if user.role == "student":
        try:
            profile = user.student_profile
        except StudentProfile.DoesNotExist:
            return False
        if not profile.class_group_id or resource.owner.school_id != user.school_id:
            return False
        return _student_teachers(profile).filter(pk=resource.owner_id).exists()
    return user.role in {"school_admin", "super_admin"} and (not user.school_id or resource.owner.school_id == user.school_id)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def resource_office_config(request, pk):
    resource = Resource.objects.select_related("owner", "owner__school").filter(pk=pk).first()
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
    attachment_url = request.build_absolute_uri(f"/{resource.attachment.url.lstrip('/')}")
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
            with resource.attachment.storage.open(resource.attachment.name, "wb") as target:
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
            resource = save_teacher_resource(request, request.data, uploaded_file=request.FILES.get("attachment"))
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(resource_row(resource), "资源已上传", status=201)

    query = request.GET.get("q", "").strip()
    resources = Resource.objects.filter(owner=request.user, owner__school=_school(request)).order_by("-is_pinned", "-updated_at")
    if query:
        resources = resources.filter(Q(title__icontains=query) | Q(content__icontains=query) | Q(attachment__icontains=query))
    page = _paginate(request, resources)
    page.object_list = [resource_row(resource) for resource in page.object_list]
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
        return ok(resource_row(resource))
    if request.method == "PATCH":
        try:
            resource = save_teacher_resource(request, request.data, resource=resource, uploaded_file=request.FILES.get("attachment"))
        except ServiceError as exc:
            return _service_fail(exc)
        return ok(resource_row(resource), "资源已更新")

    try:
        delete_teacher_resource(request, resource)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok({}, "资源已删除")


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
            .prefetch_related(Prefetch("lessons", queryset=Lesson.objects.order_by("sort_order", "id"), to_attr="prefetched_lessons"))
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
            course = save_teacher_course_cover(request, course, request.FILES.get("cover"))
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
        course = set_teacher_course_classes(request, _teacher_course(request, pk), request.data)
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

    return ok([lesson_row(lesson) for lesson in _teacher_lessons_queryset(request, course)])


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
            lesson = save_teacher_lesson(request, lesson.course, request.data, lesson=lesson)
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

    return ok([lesson_step_row(step) for step in _teacher_lesson_steps_queryset(lesson)])


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
        LessonStep.objects.select_related("lesson", "lesson__course", "lesson__course__teacher")
        .filter(pk=pk, lesson__course__teacher=request.user, lesson__course__teacher__school=_school(request))
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


def _teacher_classroom_sessions(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    class_id = request.GET.get("class", "").strip()
    course_id = request.GET.get("course", "").strip()
    sessions = (
        ClassroomSession.objects.filter(school=_school(request), teacher=request.user)
        .select_related("school", "teacher", "course", "course__subject", "lesson", "class_group", "current_step", "current_step__lesson")
        .annotate(
            activity_count=Count("activities", distinct=True),
            open_activity_count=Count("activities", filter=Q(activities__status=ClassroomActivity.Status.OPEN), distinct=True),
        )
        .order_by("-created_at")
    )
    if query:
        sessions = sessions.filter(Q(title__icontains=query) | Q(course__title__icontains=query) | Q(lesson__title__icontains=query))
    if status:
        if status not in {item.value for item in ClassroomSession.Status}:
            return None, fail("课堂状态筛选条件不正确。", errors={"status": ["课堂状态筛选条件不正确。"]}, status=400)
        sessions = sessions.filter(status=status)
    if class_id:
        try:
            selected_class_id = int(class_id)
        except ValueError:
            return None, fail("班级筛选条件不正确。", errors={"class": ["班级筛选条件不正确。"]}, status=400)
        if selected_class_id not in set(_teacher_class_ids(request)):
            return None, fail("无权查看该班级课堂。", errors={"class": ["无权查看该班级课堂。"]}, status=403)
        sessions = sessions.filter(class_group_id=selected_class_id)
    if course_id:
        try:
            sessions = sessions.filter(course_id=int(course_id))
        except ValueError:
            return None, fail("课程筛选条件不正确。", errors={"course": ["课程筛选条件不正确。"]}, status=400)
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
        return ok(classroom_session_row(session, include_activities=True), "课堂已创建", status=201)

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
        session = start_classroom_session(request, _teacher_classroom_session(request, pk))
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "课堂已开始")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_session_finish(request, pk):
    try:
        session = finish_classroom_session(request, _teacher_classroom_session(request, pk))
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "课堂已结束")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_session_restart(request, pk):
    try:
        session = restart_classroom_session(request, _teacher_classroom_session(request, pk))
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "课堂已重新开始")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_step_open(request, pk):
    try:
        session = set_classroom_current_step(request, _teacher_classroom_session(request, pk), request.data)
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "环节已投放")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_step_lock(request, pk):
    try:
        session = lock_classroom_current_step(request, _teacher_classroom_session(request, pk))
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "当前环节已锁定提交")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_step_close(request, pk):
    try:
        session = close_classroom_current_step(request, _teacher_classroom_session(request, pk))
        session = _teacher_classroom_session(request, session.pk)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_session_row(session), "当前环节已关闭")


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

    return ok([classroom_activity_row(activity) for activity in session.activities.order_by("-created_at")])


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
            activity = save_classroom_activity(request, activity.session, request.data, activity=activity)
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
        activity = open_classroom_activity(request, _teacher_classroom_activity(request, pk))
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(classroom_activity_row(activity), "课堂活动已开启")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_activity_close(request, pk):
    try:
        activity = close_classroom_activity(request, _teacher_classroom_activity(request, pk))
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
        notices = notices.filter(Q(title__icontains=query) | Q(content__icontains=query))
    if status:
        notices = notices.filter(status=status)
    if class_id:
        try:
            selected_class_id = int(class_id)
        except ValueError:
            return None, fail("班级筛选条件不正确。", errors={"class": ["班级筛选条件不正确。"]}, status=400)
        if selected_class_id not in set(_teacher_class_ids(request)):
            return None, fail("无权查看该班级公告。", errors={"class": ["无权查看该班级公告。"]}, status=403)
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
            return None, fail("班级筛选条件不正确。", errors={"class": ["班级筛选条件不正确。"]}, status=400)
        if selected_class_id not in set(_teacher_class_ids(request)):
            return None, fail("无权查看该班级反馈。", errors={"class": ["无权查看该班级反馈。"]}, status=403)
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
        StudentProfile.objects.select_related("user", "class_group", "class_group__school")
        .filter(user=request.user, user__school=_school(request))
        .first()
    )
    if profile is None:
        raise ServiceError("学生档案不存在，请联系学校管理员。", status=404)
    return profile


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
    return get_user_model().objects.filter(id__in=teacher_ids, role="teacher", school=profile.user.school).order_by("display_name", "username")


def _student_current_classroom(profile: StudentProfile) -> ClassroomSession | None:
    if not profile.class_group_id:
        return None
    return (
        ClassroomSession.objects.select_related("teacher", "course", "course__subject", "lesson", "class_group", "current_step", "current_step__lesson")
        .filter(
            school=profile.user.school,
            class_group=profile.class_group,
            status=ClassroomSession.Status.RUNNING,
        )
        .order_by("-started_at", "-created_at")
        .first()
    )


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
        PretestSubmission.objects.filter(student=user, paper_id__in=[paper.id for paper in latest_by_kind.values()])
        .values_list("paper_id", flat=True)
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
    return {"required": bool(latest_by_kind), "completed": not missing, "missing": missing}


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
            lesson_count=Count("lessons", filter=Q(lessons__is_active=True), distinct=True),
            step_count=Count(
                "lessons__steps",
                filter=Q(lessons__is_active=True, lessons__steps__status=LessonStep.Status.READY),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                "lessons",
                queryset=Lesson.objects.filter(is_active=True).order_by("sort_order", "id"),
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
            Lesson.objects.select_related("course", "course__subject", "course__teacher")
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


def _student_lesson_classroom_session(profile: StudentProfile, lesson: Lesson) -> ClassroomSession | None:
    if not profile.class_group_id:
        return None
    return (
        ClassroomSession.objects.select_related("teacher", "course", "course__subject", "lesson", "class_group", "current_step")
        .filter(school=profile.user.school, class_group=profile.class_group, lesson=lesson)
        .order_by("-created_at", "-id")
        .first()
    )


def _ensure_student_lesson_workspace_allowed(profile: StudentProfile, lesson: Lesson) -> None:
    session = _student_lesson_classroom_session(profile, lesson)
    if session is None:
        raise ServiceError("该课时尚未启用课堂教学，暂不能进入。", status=403)
    if session.status == ClassroomSession.Status.RUNNING:
        raise ServiceError("该课时正在课堂教学中，请从课堂入口进入。", status=403)
    raise ServiceError("该课时属于课堂教学，教师启用课堂后才能进入。", status=403)


def _ensure_student_step_classroom_open(profile: StudentProfile, step: LessonStep, *, for_answer: bool = False) -> None:
    session = _student_lesson_classroom_session(profile, step.lesson)
    if session is None:
        raise ServiceError("该课时尚未启用课堂教学，暂不能学习该环节。", status=403)
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("课堂尚未开始，暂不能学习该环节。", status=403)
    if session.current_step_id != step.id or session.current_step_status == ClassroomSession.StepStatus.IDLE:
        raise ServiceError("教师尚未投放该环节。", status=403)
    if session.current_step_status == ClassroomSession.StepStatus.CLOSED:
        raise ServiceError("当前环节已关闭。", status=403)
    if for_answer and session.submission_locked:
        raise ServiceError("当前环节已锁定提交。", status=403)


def _student_lesson_step(profile: StudentProfile, step_id) -> LessonStep:
    try:
        step = (
            LessonStep.objects.select_related("lesson", "lesson__course", "lesson__course__subject", "lesson__course__teacher")
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


def _write_student_event(
    request,
    profile: StudentProfile,
    event_type: str,
    *,
    course: Course | None = None,
    lesson: Lesson | None = None,
    object_type: str = "",
    object_id: str | int = "",
    duration_ms: int = 0,
    score=None,
    metadata: dict | None = None,
) -> LearningEvent:
    return LearningEvent.objects.create(
        actor=request.user,
        class_group=profile.class_group,
        course=course,
        lesson=lesson,
        event_type=event_type,
        object_type=object_type,
        object_id=str(object_id) if object_id else "",
        duration_ms=max(int(duration_ms or 0), 0),
        score=score,
        metadata=metadata or {},
        occurred_at=timezone.now(),
    )


def _student_dashboard_data(request, profile: StudentProfile) -> dict:
    courses = list(_student_course_queryset(profile)[:8])
    for course in courses:
        course.latest_lesson = course.student_lessons[0] if getattr(course, "student_lessons", []) else None

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
        todo_rows.append({"label": "首次使用", "detail": "请完成改密、选班和前测。", "level": "warn", "path": "/student/onboarding"})
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

    return {
        "profile": student_profile_summary(profile),
        "current_classroom": student_classroom_row(current_classroom, student_layer=profile.current_layer),
        "metrics": [
            {"label": "我的课程", "value": len(courses), "sub": "当前班级可见"},
            {"label": "学习事件", "value": events.count(), "sub": "已记录行为"},
            {"label": "近 7 天学习", "value": events.filter(occurred_at__gte=timezone.now() - timedelta(days=7)).count(), "sub": "行为事件"},
            {"label": "公告", "value": len(notices), "sub": "近期发布"},
        ],
        "todo_rows": todo_rows[:6],
        "course_rows": [
            student_course_row(course, pretest_status=_student_required_pretest_status(request.user, course.subject))
            for course in courses
        ],
        "notice_rows": [student_notice_row(notice) for notice in notices],
        "teachers": [student_teacher_row(teacher) for teacher in _student_teachers(profile)],
    }


@api_view(["GET"])
@permission_classes([IsStudent])
def student_me(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(
        {
            "user": user_summary(request.user),
            "profile": student_profile_summary(profile),
            "current_classroom": student_classroom_row(_student_current_classroom(profile), student_layer=profile.current_layer),
            "teachers": [student_teacher_row(teacher) for teacher in _student_teachers(profile)],
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
            for class_group in ClassGroup.objects.filter(school=_school(request), status=ClassGroup.Status.ACTIVE).order_by("grade", "name")
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
    if len(password) < 6 or len(password) > 32 or any(char.isspace() for char in password):
        return fail("密码需为 6-32 位，不能包含空格。", errors={"password": ["密码需为 6-32 位，不能包含空格。"]}, status=400)
    request.user.set_password(password)
    request.user.is_first_login = False
    request.user.save(update_fields=["password", "is_first_login"])
    update_session_auth_hash(request, request.user)
    profile.password_updated_at = timezone.now()
    profile.onboarding_status = StudentProfile.OnboardingStatus.PASSWORD_UPDATED
    profile.save(update_fields=["password_updated_at", "onboarding_status", "updated_at"])
    write_audit(request, "student.onboarding.password", school=request.user.school, target_type="student_profile", target_id=profile.id)
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
        return fail("请选择班级。", errors={"class_group": ["请选择班级。"]}, status=400)
    class_group = ClassGroup.objects.filter(id=class_id, school=request.user.school, status=ClassGroup.Status.ACTIVE).first()
    if class_group is None:
        return fail("班级不存在或不可选择。", errors={"class_group": ["班级不存在或不可选择。"]}, status=404)
    profile.class_group = class_group
    profile.class_selected_at = timezone.now()
    profile.onboarding_status = StudentProfile.OnboardingStatus.CLASS_SELECTED
    profile.save(update_fields=["class_group", "class_selected_at", "onboarding_status", "updated_at"])
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
    subjects = Subject.objects.filter(school=request.user.school, is_active=True).order_by("name")
    return ok(
        [
            {"subject": subject_row(subject), "pretest_status": _student_required_pretest_status(request.user, subject)}
            for subject in subjects
        ]
    )


@api_view(["GET"])
@permission_classes([IsStudent])
def student_pretests_for_subject(request, subject_id):
    subject = Subject.objects.filter(id=subject_id, school=request.user.school, is_active=True).first()
    if subject is None:
        return fail("学科不存在或已停用。", status=404)
    papers = (
        PretestPaper.objects.filter(school=request.user.school, subject=subject, status=PretestPaper.Status.PUBLISHED)
        .annotate(question_count=Count("questions", distinct=True), submission_count=Count("submissions", distinct=True))
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
def student_pretest_paper(request, paper_id):
    paper = (
        PretestPaper.objects.select_related("subject")
        .prefetch_related("questions")
        .filter(pk=paper_id, school=request.user.school, status=PretestPaper.Status.PUBLISHED)
        .first()
    )
    if paper is None:
        return fail("前测不存在或未发布。", status=404)
    if request.method == "GET":
        return ok(student_pretest_paper_row(paper, include_questions=True))

    answers = request.data.get("answers")
    if not isinstance(answers, dict):
        return fail("请提交前测答案。", errors={"answers": ["请提交前测答案。"]}, status=400)
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
        if question.answer and question.question_type in {PretestQuestion.QuestionType.SINGLE, PretestQuestion.QuestionType.MULTIPLE}:
            expected = question.answer if isinstance(question.answer, list) else [question.answer]
            actual = answer if isinstance(answer, list) else [answer]
            if sorted(map(str, actual)) == sorted(map(str, expected)):
                score += float(question.score or 0)
    if errors:
        return fail("前测答案校验失败。", errors=errors, status=400)

    submission = PretestSubmission.objects.create(student=request.user, subject=paper.subject, paper=paper, answers=answers, score=score)
    try:
        profile = _student_profile(request)
        status = _student_required_pretest_status(request.user, paper.subject)
        if status["required"] and status["completed"]:
            profile.pretest_completed_at = timezone.now()
            profile.onboarding_status = StudentProfile.OnboardingStatus.PRETEST_COMPLETED
            profile.is_first_use = False
            profile.save(update_fields=["pretest_completed_at", "onboarding_status", "is_first_use", "updated_at"])
    except ServiceError:
        profile = None
    _write_student_event(
        request,
        profile or StudentProfile(user=request.user),
        LearningEvent.EventType.ANSWER_SUBMIT,
        object_type="pretest_paper",
        object_id=paper.id,
        score=score,
        metadata={"subject": paper.subject_id, "kind": paper.kind, "submission": submission.id},
    )
    return ok({"id": submission.id, "score": submission.score, "submitted_at": submission.submitted_at}, "前测已提交。")


@api_view(["GET"])
@permission_classes([IsStudent])
def student_courses(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    rows = []
    for course in _student_course_queryset(profile):
        course.latest_lesson = course.student_lessons[0] if getattr(course, "student_lessons", []) else None
        rows.append(student_course_row(course, pretest_status=_student_required_pretest_status(request.user, course.subject)))
    return ok(rows)


@api_view(["GET"])
@permission_classes([IsStudent])
def student_course_detail(request, pk):
    try:
        profile = _student_profile(request)
        course = _student_course(profile, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    lessons = Lesson.objects.filter(course=course, is_active=True).annotate(
        step_count=Count("steps", filter=Q(steps__status=LessonStep.Status.READY), distinct=True)
    ).order_by("sort_order", "id")
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
    row = student_course_row(course, pretest_status=_student_required_pretest_status(request.user, course.subject))
    rows = []
    for lesson in lesson_rows:
        lesson_data = lesson_row(lesson) | {"step_count": getattr(lesson, "step_count", 0)}
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
    lessons = Lesson.objects.filter(course=course, is_active=True).annotate(
        step_count=Count("steps", filter=Q(steps__status=LessonStep.Status.READY), distinct=True)
    ).order_by("sort_order", "id")
    return ok([lesson_row(lesson) | {"step_count": getattr(lesson, "step_count", 0)} for lesson in lessons])


@api_view(["GET"])
@permission_classes([IsStudent])
def student_lesson_workspace(request, lesson_id):
    try:
        profile = _student_profile(request)
        lesson = _student_lesson(profile, lesson_id)
        _ensure_student_lesson_workspace_allowed(profile, lesson)
    except ServiceError as exc:
        return _service_fail(exc)
    steps = LessonStep.objects.filter(lesson=lesson, status=LessonStep.Status.READY).order_by("sort_order", "id")
    return ok(
        {
            "course": student_course_row(lesson.course, pretest_status=_student_required_pretest_status(request.user, lesson.course.subject)),
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
    _write_student_event(
        request,
        profile,
        LearningEvent.EventType.LESSON_ENTER,
        course=lesson.course,
        lesson=lesson,
        object_type="lesson",
        object_id=lesson.id,
    )
    return ok({}, "已记录进入课时。")


@api_view(["POST"])
@permission_classes([IsStudent])
def student_lesson_step_enter(request, step_id):
    try:
        profile = _student_profile(request)
        step = _student_lesson_step(profile, step_id)
    except ServiceError as exc:
        return _service_fail(exc)
    _write_student_event(
        request,
        profile,
        LearningEvent.EventType.PAGE_VIEW,
        course=step.lesson.course,
        lesson=step.lesson,
        object_type="lesson_step",
        object_id=step.id,
        metadata={"action": "step_enter", "step_type": step.step_type},
    )
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
    _write_student_event(
        request,
        profile,
        LearningEvent.EventType.PAGE_VIEW,
        course=step.lesson.course,
        lesson=step.lesson,
        object_type="lesson_step",
        object_id=step.id,
        duration_ms=duration_ms,
        metadata={"action": "step_complete", "step_type": step.step_type},
    )
    return ok({}, "已记录完成环节。")


@api_view(["POST"])
@permission_classes([IsStudent])
def student_lesson_step_answer(request, step_id):
    try:
        profile = _student_profile(request)
        step = _student_lesson_step(profile, step_id)
        _ensure_student_step_classroom_open(profile, step, for_answer=True)
    except ServiceError as exc:
        return _service_fail(exc)
    answer = request.data.get("answer", "")
    _write_student_event(
        request,
        profile,
        LearningEvent.EventType.ANSWER_SUBMIT,
        course=step.lesson.course,
        lesson=step.lesson,
        object_type="lesson_step",
        object_id=step.id,
        metadata={"step_type": step.step_type, "answer": answer},
    )
    return ok({}, "答案已提交。")


@api_view(["GET"])
@permission_classes([IsStudent])
def student_current_classroom(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    return ok(student_classroom_row(_student_current_classroom(profile), student_layer=profile.current_layer))


@api_view(["GET"])
@permission_classes([IsStudent])
def student_classroom_detail(request, pk):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    session = (
        ClassroomSession.objects.select_related("teacher", "course", "course__subject", "lesson", "class_group", "current_step", "current_step__lesson")
        .filter(pk=pk, school=request.user.school, class_group=profile.class_group)
        .first()
    )
    if session is None:
        return fail("课堂不存在或无权进入。", status=404)
    if session.status != ClassroomSession.Status.RUNNING:
        return fail("课堂尚未开始，暂不能进入。", status=403)
    return ok(student_classroom_row(session, student_layer=profile.current_layer))


@api_view(["GET"])
@permission_classes([IsStudent])
def student_notices(request):
    try:
        profile = _student_profile(request)
    except ServiceError as exc:
        return _service_fail(exc)
    notices = (
        Notice.objects.filter(school=request.user.school, status=Notice.Status.PUBLISHED, target_classes=profile.class_group)
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
        category = str(request.data.get("category", Feedback.Category.STUDY)).strip() or Feedback.Category.STUDY
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
    feedback_items = Feedback.objects.filter(school=request.user.school, student=request.user).select_related("teacher").order_by("-created_at")
    if query:
        feedback_items = feedback_items.filter(Q(title__icontains=query) | Q(content__icontains=query))
    page = _paginate(request, feedback_items)
    page.object_list = [student_feedback_row(item) for item in page.object_list]
    return ok(page_data(page))


@api_view(["GET"])
@permission_classes([IsStudent])
def student_feedback_detail(request, pk):
    feedback = Feedback.objects.filter(pk=pk, school=request.user.school, student=request.user).select_related("teacher").first()
    if feedback is None:
        return fail("留言反馈不存在。", status=404)
    return ok(student_feedback_row(feedback))
