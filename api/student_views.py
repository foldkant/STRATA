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

# Students domain endpoints extracted from api.views.
from .views import (
    EVALUATION_TYPE_LABELS,
    STUDENT_ARCHIVE_EVENT_LABELS,
    _answer_attachment_value,
    _answer_text_value,
    _classroom_evaluation_source,
    _classroom_group_queryset,
    _ensure_student_step_classroom_open,
    _evaluation_enabled_field,
    _latest_evaluation_submissions,
    _lesson_step_answer_progress,
    _open_group_collaboration,
    _question_answer_value,
    _save_group_file,
    _student_classroom_resource_context,
    _student_course_band,
    _student_current_classroom,
    _student_learning_web_page_context,
    _student_lesson_classroom_session,
    _student_profile,
    _student_required_pretest_status,
    _teacher_class_ids,
    _validate_evaluation_response,
    _xlsx_filename,
)

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


def _teacher_students(request):
    class_ids = _teacher_class_ids(request)
    return StudentProfile.objects.filter(
        user__school=_school(request),
        class_group_id__in=class_ids,
    ).select_related("user", "class_group")


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


def _ensure_student_lesson_workspace_allowed(
    profile: StudentProfile, lesson: Lesson
) -> None:
    session = _student_lesson_classroom_session(profile, lesson)
    if session is None:
        raise ServiceError("该课时尚未启用课堂教学，暂不能进入。", status=403)
    if session.status == ClassroomSession.Status.RUNNING:
        raise ServiceError("该课时正在课堂教学中，请从课堂入口进入。", status=403)
    raise ServiceError("该课时属于课堂教学，教师启用课堂后才能进入。", status=403)


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
