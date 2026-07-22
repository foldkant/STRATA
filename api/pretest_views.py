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

# Pretest domain endpoints extracted from api.views.
from .views import (
    _student_profile,
    _student_required_pretest_status,
)

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
