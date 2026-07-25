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
from django.utils.dateparse import parse_datetime
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
    StudentSubjectBand,
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
from learning_analytics.services.evaluation import standard_curriculum_alignment
from learning_analytics.models import (
    ClassroomEvaluationStandardUse,
    GroupingCandidateRun,
    GroupingDecisionPoint,
    GroupingPlanVersion,
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
    activate_reviewed_grouping_plan,
    capture_grouping_outcomes,
    confirm_grouping_candidate,
    generate_grouping_candidate_run,
    mark_grouping_plan_notified,
    record_confirmed_plan_evidence,
    save_grouping_decision_point,
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

# Classroom domain endpoints extracted from api.views.
from . import views as _shared_views
from .views import (
    EVALUATION_TYPE_LABELS,
    OFFICE_FILE_TYPES,
    _classroom_evaluation_source,
    _classroom_group_queryset,
    _evaluation_criteria_field,
    _evaluation_enabled_field,
    _evaluation_student_row,
    _evaluation_submission_average,
    _latest_evaluation_submissions,
    _lesson_step_answer_progress,
    _office_document_type,
    _open_group_collaboration,
    _save_group_file,
    _score_float,
    _student_course_band,
    _teacher_class_ids,
    _validate_evaluation_response,
)


_STUDENT_BAND_LABELS = dict(StudentSubjectBand.Band.choices)


def _student_band_label(band: str | None) -> str:
    return _STUDENT_BAND_LABELS.get(band, "")

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
            "lesson__course",
            "class_group",
            "current_step",
            "current_step__lesson",
        )
        .prefetch_related(
            Prefetch(
                "course__course_classes",
                queryset=CourseClass.objects.select_related("class_group"),
                to_attr="prefetched_course_classes",
            )
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
        "decision_point": _grouping_decision_point_row(run.decision_point),
        "students": list(students.values()),
        "locked_assignments": run.input_snapshot.get("locked_assignments") or {},
        "candidates": candidates,
        "candidate_count": run.candidate_count,
        "conflicts": run.conflict_explanations,
        "selected_candidate_key": run.selected_candidate_key,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


def _grouping_decision_point_row(point: GroupingDecisionPoint) -> dict:
    return {
        "id": point.id,
        "point_id": str(point.point_id),
        "status": point.status,
        "status_label": point.get_status_display(),
        "trigger": point.trigger,
        "task_purpose": point.task_purpose,
        "task_purpose_label": point.get_task_purpose_display(),
        "task_stage": point.task_stage,
        "role_requirements": point.role_requirements,
        "resource_requirements": point.resource_requirements,
        "safety_constraints": point.safety_constraints,
        "opportunity_requirements": point.opportunity_requirements,
        "stability_until": point.stability_until,
        "scheduled_for": point.scheduled_for,
        "created_at": point.created_at,
    }


def _grouping_plan_row(plan: GroupingPlanVersion) -> dict:
    return {
        "id": plan.id,
        "plan_id": str(plan.plan_id),
        "plan_version": plan.plan_version,
        "status": plan.status,
        "status_label": plan.get_status_display(),
        "candidate_key": plan.candidate_key,
        "assignments": plan.assignments,
        "adjustment_note": plan.adjustment_note,
        "confirmed_at": plan.confirmed_at,
        "activated_at": plan.activated_at,
        "notified_at": plan.notified_at,
        "decision_point": _grouping_decision_point_row(plan.decision_point),
    }


def _grouping_draft_settings(collaboration: ClassroomGroupCollaboration) -> dict:
    metadata = (
        collaboration.generation_metadata
        if isinstance(collaboration.generation_metadata, dict)
        else {}
    )
    draft = metadata.get("draft_settings")
    if isinstance(draft, dict):
        return draft
    return {
        "group_size": collaboration.group_size,
        "grouping_strategy": collaboration.grouping_strategy,
        "document_type": collaboration.document_type,
        "storage_quota_mb": collaboration.storage_quota_mb,
        "allow_student_upload": collaboration.allow_student_upload,
        "allow_onlyoffice_edit": collaboration.allow_onlyoffice_edit,
    }


def _setup_classroom_group_collaboration(
    request, session: ClassroomSession, data
) -> ClassroomGroupCollaboration:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ServiceError("只有进行中的课堂可以保存小组合作设置。", status=409)
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
    draft_settings = {
        "group_size": group_size,
        "grouping_strategy": strategy,
        "document_type": document_type,
        "storage_quota_mb": storage_quota_mb,
        "allow_student_upload": allow_student_upload,
        "allow_onlyoffice_edit": allow_onlyoffice_edit,
    }

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
        has_active_groups = collaboration.groups.filter(
            is_active=True,
            plan_version=collaboration.active_plan_version,
        ).exists()
        metadata = (
            dict(collaboration.generation_metadata)
            if isinstance(collaboration.generation_metadata, dict)
            else {}
        )
        metadata["draft_settings"] = draft_settings
        collaboration.generation_metadata = metadata
        if not has_active_groups:
            collaboration.group_size = group_size
            collaboration.grouping_strategy = strategy
            collaboration.document_type = document_type
            collaboration.storage_quota_mb = storage_quota_mb
            collaboration.allow_student_upload = allow_student_upload
            collaboration.allow_onlyoffice_edit = allow_onlyoffice_edit
            collaboration.is_enabled = False
            collaboration.status = ClassroomGroupCollaboration.Status.DRAFT
            collaboration.opened_at = None
            collaboration.closed_at = None
        else:
            # Keep the running plan unchanged. Proposed settings are applied only
            # after a reviewed plan is explicitly activated.
            collaboration.is_enabled = True
            collaboration.status = ClassroomGroupCollaboration.Status.OPEN
        collaboration.save()

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
            "state": "draft_saved",
            "active_groups_preserved": has_active_groups,
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
    return ok(
        classroom_group_collaboration_row(collaboration),
        "小组合作设置已保存；尚未生成、启用或通知任何分组。",
    )


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_classroom_grouping_decision(request, pk):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    if request.method == "GET":
        point = (
            GroupingDecisionPoint.objects.filter(classroom_session=session)
            .order_by("-created_at", "-id")
            .first()
        )
        return ok(_grouping_decision_point_row(point) if point else None)
    collaboration = ClassroomGroupCollaboration.objects.filter(session=session).first()
    if collaboration is None:
        return fail("请先保存小组合作的基础设置。", status=409)
    required_fields = {
        "task_purpose": "任务目的",
        "task_stage": "学习阶段",
        "role_requirements": "小组角色",
        "resource_requirements": "学习资源",
    }
    missing = [label for field, label in required_fields.items() if field not in request.data]
    if missing:
        return fail(f"请先确定：{'、'.join(missing)}。", status=400)
    stability_until = None
    raw_stability_until = request.data.get("stability_until")
    if raw_stability_until:
        stability_until = parse_datetime(str(raw_stability_until))
        if stability_until is None:
            return fail("稳定期结束时间格式不正确。", status=400)
        if timezone.is_naive(stability_until):
            stability_until = timezone.make_aware(stability_until)
    task_context = request.data.get("task_context") or {}
    if not isinstance(task_context, dict):
        return fail("任务补充信息格式不正确。", status=400)
    try:
        point = save_grouping_decision_point(
            session=session,
            actor=request.user,
            task_purpose=str(request.data.get("task_purpose") or ""),
            task_stage=str(request.data.get("task_stage") or ""),
            role_requirements=request.data.get("role_requirements"),
            resource_requirements=request.data.get("resource_requirements"),
            safety_constraints=request.data.get("safety_constraints") or {},
            opportunity_requirements=request.data.get("opportunity_requirements") or {},
            stability_until=stability_until,
            task_context=task_context,
        )
    except ValidationError as exc:
        return fail(exc.messages[0], status=400)
    write_audit(
        request,
        "teacher.classroom.grouping.decision.prepare",
        school=session.school,
        target_type="grouping_decision_point",
        target_id=point.id,
        detail={
            "task_purpose": point.task_purpose,
            "task_stage": point.task_stage,
            "role_count": len(point.role_requirements),
            "resource_count": len(point.resource_requirements),
        },
    )
    return ok(
        _grouping_decision_point_row(point),
        "分组任务信息已保存，可以生成候选方案。",
        status=201,
    )


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
    if collaboration is None:
        return fail("请先保存小组合作设置。", status=409)
    decision_point_id = request.data.get("decision_point_id")
    point = GroupingDecisionPoint.objects.filter(
        pk=decision_point_id,
        classroom_session=session,
        status=GroupingDecisionPoint.Status.OPEN,
    ).first()
    if point is None:
        return fail("请先保存本次分组的任务目的、阶段、角色与资源。", status=409)
    draft_settings = _grouping_draft_settings(collaboration)
    raw_locks = request.data.get("locked_assignments") or {}
    if not isinstance(raw_locks, dict):
        return fail("锁定学生格式不正确。", status=400)
    document_type = str(
        request.data.get("document_type") or draft_settings["document_type"]
    ).lower()
    if document_type not in ClassroomGroupCollaboration.DocumentType.values:
        return fail("协作文档类型不正确。", status=400)
    try:
        storage_quota_mb = _int_in_range(
            request.data.get("storage_quota_mb"),
            int(draft_settings["storage_quota_mb"]),
            10,
            2048,
        )
        run = generate_grouping_candidate_run(
            session=session,
            actor=request.user,
            decision_point=point,
            group_size=request.data.get("group_size") or draft_settings["group_size"],
            requested_strategy=str(
                request.data.get("grouping_strategy")
                or draft_settings["grouping_strategy"]
            ),
            locked_assignments=raw_locks,
            runtime_settings={
                "document_type": document_type,
                "storage_quota_mb": storage_quota_mb,
                "allow_student_upload": str(
                    request.data.get(
                        "allow_student_upload",
                        draft_settings["allow_student_upload"],
                    )
                ).lower()
                not in {"0", "false", "no"},
                "allow_onlyoffice_edit": str(
                    request.data.get(
                        "allow_onlyoffice_edit",
                        draft_settings["allow_onlyoffice_edit"],
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
    ).first()
    if collaboration is None:
        return fail("尚未保存小组合作设置。", status=409)
    candidate_key = str(request.data.get("candidate_key") or "").strip()
    existing_plan = run.plans.filter(collaboration=collaboration).first()
    if existing_plan is not None:
        if existing_plan.candidate_key != candidate_key:
            return fail("该候选运行已经确认，不能改选其他方案。", status=409)
        existing_message = {
            GroupingPlanVersion.Status.REVIEWED: "该分组方案已经完成教师复核，尚未启用。",
            GroupingPlanVersion.Status.ACTIVE: "该分组方案已经启用。",
            GroupingPlanVersion.Status.ARCHIVED: "该分组方案已经归档。",
        }.get(existing_plan.status, "该分组方案已经完成教师复核。")
        return ok(
            _grouping_plan_row(existing_plan),
            existing_message,
        )
    adjustments = request.data.get("adjustments") or {}
    if not isinstance(adjustments, dict):
        return fail("分组调整格式不正确。", status=400)
    try:
        plan, _assignments = confirm_grouping_candidate(
            run=run,
            candidate_key=candidate_key,
            collaboration=collaboration,
            actor=request.user,
            adjustments=adjustments,
            note=str(request.data.get("note") or ""),
        )
    except ValidationError as exc:
        return fail(exc.messages[0], status=400)
    except (GroupCollaborationEventError, ServiceError) as exc:
        if isinstance(exc, ServiceError):
            return _service_fail(exc)
        return fail(exc.message, status=400)
    write_audit(
        request,
        "teacher.classroom.grouping.review",
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
    return ok(
        _grouping_plan_row(plan),
        "分组方案已完成教师复核；尚未启用，也未通知学生。",
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_grouping_activate(request, pk, plan_id):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    plan = (
        GroupingPlanVersion.objects.select_related(
            "decision_point",
            "candidate_run",
            "candidate_run__policy",
            "collaboration",
        )
        .filter(pk=plan_id, decision_point__classroom_session=session)
        .first()
    )
    if plan is None:
        return fail("分组方案不存在。", status=404)
    collaboration = plan.collaboration
    if plan.status == GroupingPlanVersion.Status.ACTIVE:
        return ok(
            {
                "plan": _grouping_plan_row(plan),
                "collaboration": classroom_group_collaboration_row(
                    _with_prefetched_groups(collaboration)
                ),
            },
            "该分组方案已经启用；学生通知仍需单独发送。",
        )
    try:
        with transaction.atomic():
            collaboration = ClassroomGroupCollaboration.objects.select_for_update().get(
                pk=collaboration.pk
            )
            has_active_groups = collaboration.groups.filter(is_active=True).exists()
            plan, _superseded = activate_reviewed_grouping_plan(
                plan=plan,
                actor=request.user,
            )
            if has_active_groups:
                withdraw_group_collaboration_opportunities(
                    collaboration=collaboration,
                    actor=request.user,
                    reason_code="group_plan_replaced",
                )
            _archive_active_classroom_groups(collaboration)
            runtime_settings = plan.candidate_run.input_snapshot.get(
                "runtime_settings"
            ) or {}
            collaboration.active_plan_version = plan.plan_version
            collaboration.group_size = int(
                plan.candidate_run.input_snapshot.get("group_size")
                or collaboration.group_size
            )
            collaboration.grouping_strategy = str(
                plan.candidate_run.input_snapshot.get("requested_strategy")
                or collaboration.grouping_strategy
            )
            collaboration.strategy_version = plan.candidate_run.algorithm_version
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
            collaboration.is_enabled = True
            collaboration.status = ClassroomGroupCollaboration.Status.OPEN
            collaboration.opened_at = collaboration.opened_at or timezone.now()
            collaboration.closed_at = None
            collaboration.generation_metadata = {
                "candidate_run_id": plan.candidate_run_id,
                "candidate_key": plan.candidate_key,
                "policy_id": plan.candidate_run.policy_id,
                "policy_hash": plan.candidate_run.policy.content_hash,
                "plan_id": str(plan.plan_id),
                "task_definition": plan.candidate_run.input_snapshot.get(
                    "task_definition"
                )
                or {},
            }
            collaboration.save()
            _generate_classroom_groups_from_assignments(
                collaboration,
                assignments=plan.assignments,
                plan_version=plan.plan_version,
            )
            record_confirmed_plan_evidence(plan=plan)
            release_group_collaboration_opportunities(
                collaboration=collaboration,
                actor=request.user,
            )
    except ValidationError as exc:
        return fail(exc.messages[0], status=409)
    except GroupCollaborationEventError as exc:
        return fail(exc.message, status=400)
    except ServiceError as exc:
        return _service_fail(exc)
    write_audit(
        request,
        "teacher.classroom.grouping.activate",
        school=session.school,
        target_type="grouping_plan_version",
        target_id=plan.id,
        detail={"plan_version": plan.plan_version},
    )
    collaboration.refresh_from_db()
    plan.refresh_from_db()
    return ok(
        {
            "plan": _grouping_plan_row(plan),
            "collaboration": classroom_group_collaboration_row(
                _with_prefetched_groups(collaboration)
            ),
        },
        "分组方案已启用；尚未通知学生。",
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_classroom_grouping_notify(request, pk, plan_id):
    try:
        session = _teacher_classroom_session(request, pk)
    except ServiceError as exc:
        return _service_fail(exc)
    plan = (
        GroupingPlanVersion.objects.select_related("decision_point", "collaboration")
        .filter(pk=plan_id, decision_point__classroom_session=session)
        .first()
    )
    if plan is None:
        return fail("分组方案不存在。", status=404)
    try:
        with transaction.atomic():
            plan, notified_now = mark_grouping_plan_notified(
                plan=plan,
                actor=request.user,
            )
            if notified_now:
                notice = Notice.objects.create(
                    school=session.school,
                    teacher=request.user,
                    title="课堂分组已更新",
                    content=(
                        f"{session.title}的小组安排已经由教师确认并启用，"
                        "请进入课堂查看自己的小组、角色与学习任务。"
                    ),
                    status=Notice.Status.PUBLISHED,
                    published_at=timezone.now(),
                )
                notice.target_classes.add(session.class_group)
    except ValidationError as exc:
        return fail(exc.messages[0], status=409)
    if notified_now:
        publish_chat_event(
            [session_group(session.id), teacher_group(session.id)],
            {
                "type": "grouping.updated",
                "session_id": session.id,
                "plan_version": plan.plan_version,
            },
        )
        write_audit(
            request,
            "teacher.classroom.grouping.notify",
            school=session.school,
            target_type="grouping_plan_version",
            target_id=plan.id,
            detail={"plan_version": plan.plan_version},
        )
    return ok(
        _grouping_plan_row(plan),
        "学生已收到分组通知。" if notified_now else "该分组通知已经发送。",
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
            active_plan = GroupingPlanVersion.objects.filter(
                collaboration=collaboration,
                plan_version=collaboration.active_plan_version,
                status__in=[
                    GroupingPlanVersion.Status.ACTIVE,
                    GroupingPlanVersion.Status.CONFIRMED,
                ],
            ).first()
            if active_plan:
                active_plan.status = GroupingPlanVersion.Status.ARCHIVED
                active_plan.archived_at = collaboration.closed_at
                active_plan.save(update_fields=["status", "archived_at"])
                active_plan.decision_point.status = GroupingDecisionPoint.Status.CLOSED
                active_plan.decision_point.save(update_fields=["status"])
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


def _bool_value(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _classroom_student_profiles(session: ClassroomSession) -> list[StudentProfile]:
    return list(
        StudentProfile.objects.select_related("user")
        .filter(class_group=session.class_group, user__is_active=True)
        .order_by("user__display_name", "user__username", "id")
    )


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


def _classroom_evaluation_availability(session: ClassroomSession) -> dict:
    bindings = list(
        LessonStepEvaluationBinding.objects.select_related(
            "lesson_step", "standard_version"
        )
        .filter(lesson_step__lesson_id=session.lesson_id)
        .order_by("lesson_step__sort_order", "lesson_step_id")
    )
    current_binding = next(
        (
            binding
            for binding in bindings
            if binding.lesson_step_id == session.current_step_id
        ),
        None,
    )
    frozen_use = (
        ClassroomEvaluationStandardUse.objects.select_related(
            "lesson_step", "standard_version"
        )
        .filter(session=session)
        .first()
    )
    current_step = (
        {
            "id": session.current_step_id,
            "title": session.current_step.title,
        }
        if session.current_step_id
        else None
    )
    bound_steps = [
        {
            "id": binding.lesson_step_id,
            "title": binding.lesson_step.title,
            "standard_version": binding.standard_version_id,
            "standard_title": binding.standard_version.title,
            "version_no": binding.standard_version.version_no,
        }
        for binding in bindings
    ]

    can_enable = True
    reason_code = "ready"
    reason = "当前环节已绑定经过教师复核的评价版本，可以开启课堂评价。"
    recovery = ""
    if session.status != ClassroomSession.Status.RUNNING:
        can_enable = False
        reason_code = "classroom_not_running"
        reason = "课堂尚未开始，暂时不能开放评价。"
        recovery = "请先开始课堂并投放需要评价的教学环节。"
    elif current_step is None:
        can_enable = False
        reason_code = "no_current_step"
        reason = "当前没有正在实施的教学环节，暂时不能开放评价。"
        recovery = "请先投放一个已设置评价方案的教学环节。"
    elif current_binding is None:
        can_enable = False
        reason_code = "current_step_unbound"
        reason = f"当前环节“{current_step['title']}”尚未设置评价方案。"
        recovery = "可返回课时设计为本环节设置评价，或在课堂中投放一个已设置评价的环节。"
    elif frozen_use is not None and frozen_use.lesson_step_id != session.current_step_id:
        can_enable = False
        reason_code = "frozen_for_other_step"
        reason = (
            f"本课堂已固定使用“{frozen_use.lesson_step.title}”环节的评价版本，"
            f"不能用于当前“{current_step['title']}”环节。"
        )
        recovery = "请继续查看已形成的评价记录；后续环节需在新的课堂实施记录中使用对应版本。"

    return {
        "can_enable": can_enable,
        "reason_code": reason_code,
        "reason": reason,
        "recovery": recovery,
        "current_step": current_step,
        "current_binding": (
            {
                "id": current_binding.id,
                "standard_version": current_binding.standard_version_id,
                "standard_title": current_binding.standard_version.title,
                "version_no": current_binding.standard_version.version_no,
            }
            if current_binding
            else None
        ),
        "bound_steps": bound_steps,
    }


def _attach_curriculum_alignment(config, config_row: dict) -> dict:
    """Decorate legacy frozen snapshots with reproducible display-only links."""
    version = getattr(config, "standard_version", None)
    if version is None:
        return config_row
    alignment_by_code = standard_curriculum_alignment(version)
    if not alignment_by_code:
        return config_row
    result = {**config_row}
    for field in ("self_criteria", "peer_criteria", "teacher_criteria"):
        result[field] = [
            {
                **criterion,
                "curriculum_alignment": criterion.get("curriculum_alignment")
                or alignment_by_code.get(str(criterion.get("criterion_code") or ""), {}),
            }
            for criterion in config_row.get(field, [])
        ]
    return result


def _teacher_evaluation_payload(
    session: ClassroomSession,
    config=None,
) -> dict:
    config = config or _classroom_evaluation_source(session)
    config_row = classroom_evaluation_config_row(config)
    config_row = _attach_curriculum_alignment(config, config_row)
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
                **_evaluation_student_row(profile, course=session.course),
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
        "availability": _classroom_evaluation_availability(session),
    }


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
                if enabled:
                    availability = _classroom_evaluation_availability(session)
                    if not availability["can_enable"]:
                        raise ServiceError(
                            f"{availability['reason']} {availability['recovery']}".strip(),
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
            raise ServiceError("评价内容请在课时设计中维护，课堂负责开启和实施。", status=400)
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


class _OnlyOfficeSameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_origin: tuple[str, str, int | None]):
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        if _url_origin(newurl) != self.allowed_origin:
            raise ValueError("ONLYOFFICE 回调下载禁止跳转到其他来源。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_onlyoffice_callback_file(url: str, *, max_bytes: int) -> bytes:
    allowed_origin = _url_origin(settings.ONLYOFFICE_DOCUMENT_SERVER_URL)
    requested_origin = _url_origin(url)
    parsed = urlparse(url)
    if (
        requested_origin != allowed_origin
        or requested_origin[0] not in {"http", "https"}
        or not requested_origin[1]
        or parsed.username
        or parsed.password
    ):
        raise ValueError("ONLYOFFICE 回调下载地址不属于已配置文档服务器。")
    opener = urllib.request.build_opener(
        _OnlyOfficeSameOriginRedirectHandler(allowed_origin)
    )
    with opener.open(url, timeout=30) as response:
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
            data = _shared_views._download_onlyoffice_callback_file(
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
        student_band = _student_course_band(profile, session.course)
        questions = normalize_lesson_question_items(
            step.question_items,
            include_answer=True,
            student_layer=student_band,
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
                "current_layer": student_band or "",
                "current_layer_label": _student_band_label(student_band),
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
        student_band = (
            _student_course_band(profile, activity.session.course) if profile else None
        )
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
                "current_layer": student_band or "",
                "current_layer_label": _student_band_label(student_band),
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
        student_band = _student_course_band(profile, session.course)
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
            "current_layer": student_band or "",
            "current_layer_label": _student_band_label(student_band),
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
