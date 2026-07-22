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

# Courses domain endpoints extracted from api.views.
from .views import (
    _student_learning_web_page_context,
    _teacher_classes,
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
