from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import timedelta

from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsSchoolAdmin, IsStudent, IsTeacher
from api.responses import fail, ok
from api.services import ServiceError, generate_question_bank_drafts_with_ai
from courses.models import Course, Subject
from learning.models import (
    AssessmentComparabilityRecord,
    CommonQuestionSet,
    CommonQuestionSetItem,
    QuestionBankItem,
    TestAssessment,
    TestAssessmentQuestion,
    TestAttempt,
    TestAttemptAnswer,
)
from learning_analytics.services.assessment_events import (
    AssessmentEventError,
    next_manual_grading_state,
    record_assessment_item_grade,
    record_assessment_item_submission,
    release_assessment_opportunities,
    withdraw_assessment_opportunities,
)
from learning.services.question_bank import (
    create_question_items,
    ensure_question_version,
    transition_question,
)
from ops.xlsx import build_workbook, export_rows, read_table_rows, template_response, workbook_response
from school.models import ClassGroup, StudentProfile, TeachingAssignment


class AssessmentError(Exception):
    def __init__(self, message: str, *, errors: dict | None = None, status: int = 400):
        self.message = message
        self.errors = errors or {}
        self.status = status
        super().__init__(message)


def _error(exc: AssessmentError):
    return fail(exc.message, errors=exc.errors, status=exc.status)


def _service_error(exc: ServiceError):
    return fail(exc.message, errors=exc.errors, status=exc.status)


MIN_QUESTION_STAT_SAMPLE = 30


def _teacher_class_ids(user) -> list[int]:
    return list(
        TeachingAssignment.objects.filter(school=user.school, teacher=user).values_list("class_group_id", flat=True)
    )


def _user_row(user) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name or user.username}


def _subject_row(subject) -> dict:
    return {"id": subject.id, "name": subject.name, "code": subject.code}


def _class_row(class_group) -> dict:
    return {"id": class_group.id, "name": class_group.name, "grade": class_group.grade}


def _course_row(course) -> dict | None:
    return {"id": course.id, "title": course.title} if course else None


def _clean_text(value, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _clean_answer_list(value) -> list[str]:
    values = value if isinstance(value, list) else [value] if value not in {None, ""} else []
    result = []
    for item in values:
        text = _clean_text(item, 500)
        if text and text not in result:
            result.append(text)
    return result


def _clean_question_payload(data, *, allow_common=False) -> dict:
    question_type = str(data.get("question_type") or "single").strip()
    allowed_types = {value for value, _ in QuestionBankItem.QuestionType.choices}
    if question_type not in allowed_types:
        raise AssessmentError("题型不正确。", errors={"question_type": ["请选择有效题型。"]})
    stem = _clean_text(data.get("stem"), 2000)
    if len(stem) < 2:
        raise AssessmentError("请填写题干。", errors={"stem": ["题干至少 2 个字符。"]})
    raw_options = data.get("options") if isinstance(data.get("options"), list) else []
    options = []
    for item in raw_options[:10]:
        text = _clean_text(item.get("text") if isinstance(item, dict) else item, 300)
        if text and text not in options:
            options.append(text)
    answer = _clean_answer_list(data.get("answer"))
    if question_type == QuestionBankItem.QuestionType.JUDGE:
        options = ["正确", "错误"]
    if question_type in {QuestionBankItem.QuestionType.SINGLE, QuestionBankItem.QuestionType.MULTIPLE, QuestionBankItem.QuestionType.JUDGE}:
        if len(options) < 2:
            raise AssessmentError("选择类题目至少需要两个选项。", errors={"options": ["请设置至少两个选项。"]})
        if question_type in {QuestionBankItem.QuestionType.SINGLE, QuestionBankItem.QuestionType.JUDGE} and len(answer) != 1:
            raise AssessmentError("单选或判断题必须设置一个答案。", errors={"answer": ["请选择一个正确答案。"]})
        if question_type == QuestionBankItem.QuestionType.MULTIPLE and not answer:
            raise AssessmentError("多选题必须设置答案。", errors={"answer": ["请至少选择一个正确答案。"]})
        if any(item not in options for item in answer):
            raise AssessmentError("参考答案必须来自题目选项。", errors={"answer": ["答案与选项不匹配。"]})
    elif question_type == QuestionBankItem.QuestionType.BLANK and not answer:
        raise AssessmentError("填空题必须设置至少一个参考答案。", errors={"answer": ["请填写参考答案。"]})
    try:
        default_score = float(data.get("default_score") or 0)
    except (TypeError, ValueError):
        default_score = 0
    if default_score <= 0 or default_score > 100:
        raise AssessmentError("默认分值应在 0-100 之间。", errors={"default_score": ["请输入有效分值。"]})
    difficulty = str(data.get("difficulty") or QuestionBankItem.Difficulty.NORMAL)
    if difficulty not in {value for value, _ in QuestionBankItem.Difficulty.choices}:
        difficulty = QuestionBankItem.Difficulty.NORMAL
    item_role = str(data.get("item_role") or QuestionBankItem.ItemRole.REGULAR)
    if item_role not in {value for value, _ in QuestionBankItem.ItemRole.choices}:
        item_role = QuestionBankItem.ItemRole.REGULAR
    if item_role == QuestionBankItem.ItemRole.COMMON and not allow_common:
        item_role = QuestionBankItem.ItemRole.REGULAR
    layer_scope = str(data.get("layer_scope") or QuestionBankItem.LayerScope.ALL)
    if layer_scope not in {value for value, _ in QuestionBankItem.LayerScope.choices}:
        layer_scope = QuestionBankItem.LayerScope.ALL
    if item_role != QuestionBankItem.ItemRole.LAYERED:
        layer_scope = QuestionBankItem.LayerScope.ALL
    elif layer_scope == QuestionBankItem.LayerScope.ALL:
        raise AssessmentError(
            "分层题需要选择适用层级。",
            errors={"layer_scope": ["请选择 A、B、C、A/B 或 B/C。"]},
        )
    comparison_code = _clean_text(data.get("comparison_code"), 64).upper()
    if item_role != QuestionBankItem.ItemRole.COMMON:
        comparison_code = ""
    elif not comparison_code:
        raise AssessmentError(
            "共同题需要填写比较编号。",
            errors={"comparison_code": ["比较编号用于跨班级和跨学期匹配同一道题。"]},
        )
    return {
        "stem": stem,
        "question_type": question_type,
        "options": options,
        "answer": answer,
        "analysis": str(data.get("analysis") or "").strip()[:4000],
        "difficulty": difficulty,
        "knowledge_point": _clean_text(data.get("knowledge_point"), 128),
        "default_score": default_score,
        "item_role": item_role,
        "layer_scope": layer_scope,
        "comparison_code": comparison_code,
    }


def _question_queryset():
    return QuestionBankItem.objects.select_related(
        "school",
        "subject",
        "creator",
        "reviewed_by",
        "disabled_by",
    ).annotate(
        assessment_use_count=Count("assessment_questions", distinct=True),
        response_count=Count(
            "assessment_questions__attempt_answers",
            distinct=True,
        ),
        correct_count=Count(
            "assessment_questions__attempt_answers",
            filter=Q(assessment_questions__attempt_answers__is_correct=True),
            distinct=True,
        ),
        trial_use_count=Count(
            "assessment_questions",
            filter=Q(assessment_questions__source_status=QuestionBankItem.Status.TRIAL),
            distinct=True,
        ),
        trial_response_count=Count(
            "assessment_questions__attempt_answers",
            filter=Q(
                assessment_questions__source_status=QuestionBankItem.Status.TRIAL
            ),
            distinct=True,
        ),
        trial_correct_count=Count(
            "assessment_questions__attempt_answers",
            filter=Q(
                assessment_questions__source_status=QuestionBankItem.Status.TRIAL,
                assessment_questions__attempt_answers__is_correct=True,
            ),
            distinct=True,
        ),
    )


def _question_stats(question: QuestionBankItem) -> dict:
    response_count = int(getattr(question, "response_count", 0) or 0)
    correct_count = int(getattr(question, "correct_count", 0) or 0)
    trial_response_count = int(getattr(question, "trial_response_count", 0) or 0)
    trial_correct_count = int(getattr(question, "trial_correct_count", 0) or 0)
    return {
        "usage_count": int(getattr(question, "assessment_use_count", 0) or 0),
        "response_count": response_count,
        "correct_count": correct_count,
        "correct_rate": round(correct_count * 100 / response_count, 2)
        if response_count >= MIN_QUESTION_STAT_SAMPLE
        else None,
        "data_status": (
            "available" if response_count >= MIN_QUESTION_STAT_SAMPLE else "insufficient"
        ),
        "trial_usage_count": int(getattr(question, "trial_use_count", 0) or 0),
        "trial_response_count": trial_response_count,
        "trial_correct_count": trial_correct_count,
        "trial_correct_rate": round(
            trial_correct_count * 100 / trial_response_count,
            2,
        )
        if trial_response_count >= MIN_QUESTION_STAT_SAMPLE
        else None,
    }


def question_row(question: QuestionBankItem, *, include_answer: bool = True) -> dict:
    stats = _question_stats(question)
    row = {
        "id": question.id,
        "subject": _subject_row(question.subject),
        "creator": _user_row(question.creator),
        "stem": question.stem,
        "question_type": question.question_type,
        "question_type_label": question.get_question_type_display(),
        "options": question.options,
        "difficulty": question.difficulty,
        "difficulty_label": question.get_difficulty_display(),
        "knowledge_point": question.knowledge_point,
        "default_score": question.default_score,
        "status": question.status,
        "status_label": question.get_status_display(),
        "source": question.source,
        "source_label": question.get_source_display(),
        "library_scope": question.library_scope,
        "library_scope_label": question.get_library_scope_display(),
        "item_role": question.item_role,
        "item_role_label": question.get_item_role_display(),
        "layer_scope": question.layer_scope,
        "layer_scope_label": question.get_layer_scope_display(),
        "comparison_code": question.comparison_code,
        "version_no": question.version_no,
        "content_hash": question.content_hash,
        "submitted_for_review_at": question.submitted_for_review_at,
        "reviewed_by": _user_row(question.reviewed_by)
        if question.reviewed_by_id
        else None,
        "reviewed_at": question.reviewed_at,
        "review_note": question.review_note,
        "disabled_by": _user_row(question.disabled_by)
        if question.disabled_by_id
        else None,
        "disabled_at": question.disabled_at,
        "disabled_reason": question.disabled_reason,
        **stats,
        "is_owner": False,
        "created_at": question.created_at,
        "updated_at": question.updated_at,
    }
    if include_answer:
        row.update({"answer": question.answer, "analysis": question.analysis})
    return row


def _question_detail_row(question: QuestionBankItem) -> dict:
    row = question_row(question)
    row["versions"] = [
        {
            "id": version.id,
            "version_no": version.version_no,
            "content_hash": version.content_hash,
            "source": version.source,
            "source_label": version.get_source_display(),
            "status_snapshot": version.status_snapshot,
            "status_snapshot_label": version.get_status_snapshot_display(),
            "created_by": _user_row(version.created_by),
            "created_at": version.created_at,
        }
        for version in question.versions.select_related("created_by").order_by(
            "-version_no"
        )
    ]
    row["lifecycle"] = [
        {
            "id": record.id,
            "from_status": record.from_status,
            "to_status": record.to_status,
            "to_status_label": record.get_to_status_display(),
            "action": record.action,
            "note": record.note,
            "actor": _user_row(record.actor),
            "created_at": record.created_at,
        }
        for record in question.lifecycle_records.select_related("actor").all()[:50]
    ]
    option_counts: dict[str, int] = {}
    answers = TestAttemptAnswer.objects.filter(
        question__source_question=question
    ).values_list("answer", flat=True)
    for answer in answers.iterator(chunk_size=500):
        values = answer if isinstance(answer, list) else []
        for value in values:
            text = str(value or "").strip()
            if text:
                option_counts[text] = option_counts.get(text, 0) + 1
    row["option_distribution"] = [
        {"option": option, "count": option_counts.get(option, 0)}
        for option in question.options
    ]
    return row


QUESTION_IMPORT_HEADERS = ["学科编号", "题目用途", "适用层级", "题型", "题干", "选项", "参考答案", "难度", "知识点", "默认分值", "答案解析"]
QUESTION_TYPE_IMPORT = {label: value for value, label in QuestionBankItem.QuestionType.choices}
QUESTION_DIFFICULTY_IMPORT = {label: value for value, label in QuestionBankItem.Difficulty.choices}
QUESTION_ROLE_IMPORT = {"普通题": QuestionBankItem.ItemRole.REGULAR, "分层题": QuestionBankItem.ItemRole.LAYERED}
QUESTION_LAYER_IMPORT = {label: value for value, label in QuestionBankItem.LayerScope.choices}


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_question_bank_template(request):
    return template_response(
        "我的题目批量导入模板.xlsx",
        "我的题目",
        QUESTION_IMPORT_HEADERS,
        [["IT", "普通题", "全体", "单选", "十进制 2 的二进制表示是？", "10|11|01|00", "10", "基础", "二进制编码", "2", "2 对应二进制 10"]],
        instructions=[
            "学科编号必须使用学校管理员设置的学科编号。",
            "单选、多选、判断题的选项使用英文竖线 | 分隔；多选参考答案也使用 | 分隔。",
            "判断题选项可留空，系统自动使用“正确|错误”；简答题参考答案可留空。",
            "题目用途可选普通题或分层题；分层题适用层级填写 A、B、C、A/B 或 B/C。",
            "导入成功后题目保存到“我的题目”，教师本人可直接组卷；需要校内共享时再申请审核。",
        ],
        dropdowns={
            "题型": [label for _, label in QuestionBankItem.QuestionType.choices],
            "难度": [label for _, label in QuestionBankItem.Difficulty.choices],
            "题目用途": ["普通题", "分层题"],
            "适用层级": ["全体", "A", "B", "C", "A/B", "B/C"],
        },
    )


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_question_bank_export(request):
    questions = _question_queryset().filter(school=request.user.school).filter(
        Q(creator=request.user)
        | Q(
            library_scope=QuestionBankItem.LibraryScope.SCHOOL,
            status=QuestionBankItem.Status.ACTIVE,
        )
    )
    return export_rows(
        f"{request.user.school.code}_题库导出_{timezone.localtime():%Y%m%d%H%M%S}.xlsx",
        "题库导出",
        ["ID", "学科", "学科编号", "题目用途", "适用层级", "比较编号", "题型", "题干", "选项", "参考答案", "难度", "知识点", "默认分值", "答案解析", "创建教师", "来源", "题库范围", "状态", "版本", "试卷使用次数", "作答人数", "正确率", "审核说明", "更新时间"],
        [
            [item.id, item.subject.name, item.subject.code, item.get_item_role_display(), item.get_layer_scope_display(), item.comparison_code, item.get_question_type_display(), item.stem, "|".join(item.options or []), "|".join(item.answer or []), item.get_difficulty_display(), item.knowledge_point, item.default_score, item.analysis, item.creator.display_name or item.creator.username, item.get_source_display(), item.get_library_scope_display(), item.get_status_display(), item.version_no, item.assessment_use_count, item.response_count, round(item.correct_count * 100 / item.response_count, 2) if item.response_count >= MIN_QUESTION_STAT_SAMPLE else "数据不足", item.review_note or item.disabled_reason, item.updated_at]
            for item in questions
        ],
    )


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_question_bank_import(request):
    uploaded = request.FILES.get("file")
    if uploaded is None or not uploaded.name.lower().endswith(".xlsx"):
        return fail("请选择 xlsx 题库文件。", errors={"file": ["只能上传 xlsx 文件。"]}, status=400)
    try:
        rows = read_table_rows(uploaded, required_headers=["学科编号", "题型", "题干"], all_headers=QUESTION_IMPORT_HEADERS)
    except (ValueError, OSError) as exc:
        return fail("题库文件无法读取。", errors={"file": [str(exc)]}, status=400)
    if len(rows) > 1000:
        return fail("单次最多导入 1000 道题。", errors={"file": ["请拆分文件后重试。"]}, status=400)
    subjects = {item.code.upper(): item for item in Subject.objects.filter(school=request.user.school, is_active=True)}
    created = []
    row_errors = []
    for row in rows:
        row_number = row["__row_number"]
        subject = subjects.get(str(row.get("学科编号") or "").strip().upper())
        question_type = QUESTION_TYPE_IMPORT.get(str(row.get("题型") or "").strip())
        difficulty = QUESTION_DIFFICULTY_IMPORT.get(str(row.get("难度") or "").strip(), QuestionBankItem.Difficulty.NORMAL)
        try:
            if subject is None:
                raise AssessmentError("学科编号不存在或已停用。")
            if question_type is None:
                raise AssessmentError("题型不正确。")
            options = [item.strip() for item in str(row.get("选项") or "").split("|") if item.strip()]
            answer = [item.strip() for item in str(row.get("参考答案") or "").split("|") if item.strip()]
            payload = _clean_question_payload({
                "stem": row.get("题干"),
                "question_type": question_type,
                "options": options,
                "answer": answer,
                "analysis": row.get("答案解析"),
                "difficulty": difficulty,
                "knowledge_point": row.get("知识点"),
                "default_score": row.get("默认分值") or 2,
                "item_role": QUESTION_ROLE_IMPORT.get(
                    str(row.get("题目用途") or "普通题").strip(),
                    QuestionBankItem.ItemRole.REGULAR,
                ),
                "layer_scope": QUESTION_LAYER_IMPORT.get(
                    str(row.get("适用层级") or "全体").strip(),
                    QuestionBankItem.LayerScope.ALL,
                ),
            })
            created.append(
                QuestionBankItem(
                    school=request.user.school,
                    subject=subject,
                    creator=request.user,
                    source=QuestionBankItem.Source.XLSX,
                    status=QuestionBankItem.Status.DRAFT,
                    **payload,
                )
            )
        except AssessmentError as exc:
            row_errors.append({"row": row_number, "message": exc.message})
    if created:
        create_question_items(created, actor=request.user)
    return ok(
        {"created": len(created), "failed": len(row_errors), "errors": row_errors[:100]},
        f"题库导入完成：已保存到“我的题目” {len(created)} 道，失败 {len(row_errors)} 道。",
    )


def assessment_question_row(
    question: TestAssessmentQuestion,
    *,
    include_answer: bool,
    options=None,
    include_source_metadata: bool = True,
) -> dict:
    row = {
        "id": question.id,
        "question_type": question.question_type,
        "question_type_label": question.get_question_type_display(),
        "stem": question.stem,
        "options": question.options if options is None else options,
        "knowledge_point": question.knowledge_point,
        "score": question.score,
        "sort_order": question.sort_order,
    }
    if include_source_metadata:
        row.update(
            {
                "source_question": question.source_question_id,
                "source_version": question.source_version_id,
                "source_status": question.source_status,
                "item_role": question.item_role,
                "layer_scope": question.layer_scope,
                "comparison_code": question.comparison_code,
            }
        )
    if include_answer:
        row.update({"answer": question.answer, "analysis": question.analysis})
    return row


def _assessment_total_score(assessment) -> float:
    annotated = getattr(assessment, "total_score", None)
    if annotated is not None:
        return float(annotated or 0)
    return float(assessment.questions.aggregate(total=Sum("score"))["total"] or 0)


def assessment_row(assessment: TestAssessment, *, detail: bool = False, include_answers: bool = True) -> dict:
    classes = list(assessment.target_classes.all())
    row = {
        "id": assessment.id,
        "title": assessment.title,
        "instruction": assessment.instruction,
        "subject": _subject_row(assessment.subject),
        "course": _course_row(assessment.course),
        "common_question_set": (
            {
                "id": assessment.common_question_set_id,
                "title": assessment.common_question_set.title,
                "version_no": assessment.common_set_version,
                "content_hash": assessment.common_set_hash,
            }
            if assessment.common_question_set_id
            else None
        ),
        "teacher": _user_row(assessment.teacher),
        "target_classes": [_class_row(item) for item in classes],
        "duration_minutes": assessment.duration_minutes,
        "status": assessment.status,
        "status_label": assessment.get_status_display(),
        "start_at": assessment.start_at,
        "end_at": assessment.end_at,
        "opened_at": assessment.opened_at,
        "closed_at": assessment.closed_at,
        "show_score_after_submit": assessment.show_score_after_submit,
        "randomize_question_order": assessment.randomize_question_order,
        "randomize_option_order": assessment.randomize_option_order,
        "question_count": getattr(assessment, "question_count", assessment.questions.count()),
        "attempt_count": getattr(assessment, "attempt_count", assessment.attempts.count()),
        "submitted_count": getattr(
            assessment,
            "submitted_count",
            assessment.attempts.exclude(status=TestAttempt.Status.IN_PROGRESS).count(),
        ),
        "total_score": _assessment_total_score(assessment),
        "created_at": assessment.created_at,
        "updated_at": assessment.updated_at,
    }
    if detail:
        row["questions"] = [
            assessment_question_row(question, include_answer=include_answers) for question in assessment.questions.all()
        ]
    return row


def _teacher_assessment(user, pk) -> TestAssessment:
    assessment = (
        TestAssessment.objects.filter(pk=pk, school=user.school, teacher=user, is_active=True)
        .select_related("subject", "course", "teacher")
        .prefetch_related("target_classes", "questions")
        .first()
    )
    if assessment is None:
        raise AssessmentError("测试不存在或无权操作。", status=404)
    return assessment


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_assessment_options(request):
    class_ids = _teacher_class_ids(request.user)
    subjects = Subject.objects.filter(school=request.user.school, is_active=True).order_by("name")
    classes = ClassGroup.objects.filter(pk__in=class_ids, status=ClassGroup.Status.ACTIVE).order_by("grade", "name")
    courses = Course.objects.filter(teacher=request.user, subject__school=request.user.school).select_related("subject")
    return ok({
        "subjects": [_subject_row(item) for item in subjects],
        "classes": [_class_row(item) for item in classes],
        "courses": [{**_course_row(item), "subject": item.subject_id} for item in courses],
        "question_types": [{"value": value, "label": label} for value, label in QuestionBankItem.QuestionType.choices],
        "difficulties": [{"value": value, "label": label} for value, label in QuestionBankItem.Difficulty.choices],
        "question_statuses": [{"value": value, "label": label} for value, label in QuestionBankItem.Status.choices],
            "question_sources": [{"value": value, "label": label} for value, label in QuestionBankItem.Source.choices],
        "item_roles": [{"value": value, "label": label} for value, label in QuestionBankItem.ItemRole.choices],
        "layer_scopes": [{"value": value, "label": label} for value, label in QuestionBankItem.LayerScope.choices],
        "common_question_sets": [
            {
                "id": item.id,
                "title": item.title,
                "subject": item.subject_id,
                "grade_scope": item.grade_scope,
                "term": item.term,
                "version_no": item.version_no,
                "question_count": item.items.count(),
                "items": [
                    {
                        "question_id": row.question_version.original_question_id,
                        "comparison_code": row.comparison_code,
                        "required": row.required,
                    }
                    for row in item.items.all()
                ],
            }
            for item in CommonQuestionSet.objects.filter(
                school=request.user.school,
                status=CommonQuestionSet.Status.ACTIVE,
            ).select_related("subject").prefetch_related("items__question_version")
        ],
    })


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_question_bank(request):
    if request.method == "POST":
        try:
            subject = Subject.objects.filter(pk=request.data.get("subject"), school=request.user.school, is_active=True).first()
            if subject is None:
                raise AssessmentError("请选择本校有效学科。", errors={"subject": ["学科不存在或已停用。"]})
            payload = _clean_question_payload(request.data)
            question = create_question_items(
                [
                    QuestionBankItem(
                        school=request.user.school,
                        subject=subject,
                        creator=request.user,
                        source=QuestionBankItem.Source.MANUAL,
                        status=QuestionBankItem.Status.DRAFT,
                        **payload,
                    )
                ],
                actor=request.user,
            )[0]
            question = _question_queryset().get(pk=question.pk)
            row = question_row(question)
            row["is_owner"] = True
            return ok(
                row,
                "题目已保存到“我的题目”，可直接用于本人组卷。",
                status=201,
            )
        except AssessmentError as exc:
            return _error(exc)

    queryset = _question_queryset().filter(school=request.user.school)
    scope = str(request.query_params.get("scope") or "shared")
    if scope == "mine":
        queryset = queryset.filter(creator=request.user)
    elif scope == "compose":
        queryset = queryset.filter(
            Q(
                library_scope=QuestionBankItem.LibraryScope.SCHOOL,
                status=QuestionBankItem.Status.ACTIVE,
            )
            | Q(
                status__in={
                    QuestionBankItem.Status.DRAFT,
                    QuestionBankItem.Status.TRIAL,
                },
                creator=request.user,
            )
        )
    else:
        queryset = queryset.filter(
            library_scope=QuestionBankItem.LibraryScope.SCHOOL,
            status=QuestionBankItem.Status.ACTIVE,
        )
    subject_id = request.query_params.get("subject")
    question_type = request.query_params.get("question_type")
    difficulty = request.query_params.get("difficulty")
    status_filter = str(request.query_params.get("status") or "").strip()
    source_filter = str(request.query_params.get("source") or "").strip()
    item_role_filter = str(request.query_params.get("item_role") or "").strip()
    query = str(request.query_params.get("q") or "").strip()
    if subject_id:
        queryset = queryset.filter(subject_id=subject_id)
    if question_type:
        queryset = queryset.filter(question_type=question_type)
    if difficulty:
        queryset = queryset.filter(difficulty=difficulty)
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if source_filter:
        queryset = queryset.filter(source=source_filter)
    if item_role_filter:
        queryset = queryset.filter(item_role=item_role_filter)
    if query:
        queryset = queryset.filter(Q(stem__icontains=query) | Q(knowledge_point__icontains=query))
    rows = []
    for question in queryset.order_by("-updated_at", "-id")[:500]:
        row = question_row(question)
        row["is_owner"] = question.creator_id == request.user.id
        rows.append(row)
    return ok(rows)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_question_bank_ai_generate(request):
    subject = Subject.objects.filter(pk=request.data.get("subject"), school=request.user.school, is_active=True).first()
    if subject is None:
        return fail("请选择本校有效学科。", errors={"subject": ["学科不存在或已停用。"]}, status=400)
    try:
        payload = generate_question_bank_drafts_with_ai(request, request.data, subject_name=subject.name)
    except ServiceError as exc:
        return _service_error(exc)
    payload["subject"] = _subject_row(subject)
    return ok(payload, "AI 题目草稿已生成。")


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_question_bank_ai_confirm(request):
    subject = Subject.objects.filter(pk=request.data.get("subject"), school=request.user.school, is_active=True).first()
    if subject is None:
        return fail("请选择本校有效学科。", errors={"subject": ["学科不存在或已停用。"]}, status=400)
    raw_questions = request.data.get("questions") if isinstance(request.data.get("questions"), list) else []
    if not raw_questions:
        return fail("请至少选择一道 AI 题目草稿。", errors={"questions": ["没有选中的题目。"]}, status=400)
    if len(raw_questions) > 20:
        return fail("单次最多确认 20 道题目。", errors={"questions": ["请分批确认。"]}, status=400)
    cleaned = []
    errors = []
    for index, raw in enumerate(raw_questions, start=1):
        if not isinstance(raw, dict):
            errors.append({"index": index, "message": "题目格式不正确。"})
            continue
        try:
            cleaned.append(_clean_question_payload(raw))
        except AssessmentError as exc:
            errors.append({"index": index, "message": exc.message, "fields": exc.errors})
    if errors:
        return fail(
            "部分 AI 题目未通过校验，请修改后再入库。",
            errors={"questions": [f"第 {item['index']} 题：{item['message']}" for item in errors]},
            status=400,
        )
    with transaction.atomic():
        created = create_question_items(
            [
                QuestionBankItem(
                    school=request.user.school,
                    subject=subject,
                    creator=request.user,
                    source=QuestionBankItem.Source.AI,
                    status=QuestionBankItem.Status.DRAFT,
                    **payload,
                )
                for payload in cleaned
            ],
            actor=request.user,
        )
    rows = []
    for question in _question_queryset().filter(pk__in=[item.pk for item in created]):
        row = question_row(question)
        row["is_owner"] = True
        rows.append(row)
    return ok(
        {"created_count": len(rows), "questions": rows},
        f"已保存 {len(rows)} 道 AI 题目到“我的题目”，可直接用于本人组卷。",
        status=201,
    )


@api_view(["PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_question_bank_detail(request, pk):
    question = _question_queryset().filter(
        pk=pk,
        school=request.user.school,
        creator=request.user,
    ).first()
    if question is None:
        return fail("只能维护本人创建的题目。", status=404)
    try:
        if request.method == "DELETE":
            if question.status != QuestionBankItem.Status.DISABLED:
                raise AssessmentError("请先停用题目，再执行删除。")
            question.delete()
            return ok({}, "题目已删除；已生成试卷仍保留题目快照。")
        if question.status != QuestionBankItem.Status.DRAFT:
            raise AssessmentError("只有个人可用或已退回的题目可以修改；其他题目请复制为新的个人题目。")
        subject = Subject.objects.filter(
            pk=request.data.get("subject"),
            school=request.user.school,
            is_active=True,
        ).first()
        if subject is None:
            raise AssessmentError(
                "请选择本校有效学科。",
                errors={"subject": ["学科不存在或已停用。"]},
            )
        payload = _clean_question_payload(request.data)
        for field, value in payload.items():
            setattr(question, field, value)
        question.subject = subject
        question.save()
        ensure_question_version(question, actor=request.user)
        question = _question_queryset().get(pk=question.pk)
        row = question_row(question)
        row["is_owner"] = True
        return ok(row, "个人题目已更新并保留新版本。")
    except AssessmentError as exc:
        return _error(exc)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_question_bank_action(request, pk):
    question = _question_queryset().filter(
        pk=pk,
        school=request.user.school,
        creator=request.user,
    ).first()
    if question is None:
        return fail("只能维护本人创建的题目。", status=404)
    action = str(request.data.get("action") or "").strip()
    note = str(request.data.get("note") or "").strip()[:1000]
    try:
        if action == "submit_review":
            if question.status != QuestionBankItem.Status.DRAFT:
                raise AssessmentError("只有个人可用或已退回的题目可以申请共享。")
            ensure_question_version(question, actor=request.user)
            transition_question(
                question,
                actor=request.user,
                to_status=QuestionBankItem.Status.PENDING_REVIEW,
                action=action,
                library_scope=QuestionBankItem.LibraryScope.SCHOOL,
            )
            message = "校内共享申请已提交学校管理员审核。"
        elif action == "withdraw":
            if question.status != QuestionBankItem.Status.PENDING_REVIEW:
                raise AssessmentError("只有待审核题目可以撤回。")
            transition_question(
                question,
                actor=request.user,
                to_status=QuestionBankItem.Status.DRAFT,
                action=action,
                library_scope=QuestionBankItem.LibraryScope.PERSONAL,
            )
            message = "共享申请已撤回，题目继续作为个人题目使用。"
        elif action == "disable":
            if question.status != QuestionBankItem.Status.DRAFT:
                raise AssessmentError("教师只能停用个人可用或已退回的题目。")
            transition_question(
                question,
                actor=request.user,
                to_status=QuestionBankItem.Status.DISABLED,
                action=action,
                note=note or "教师停止使用草稿",
            )
            message = "个人题目已停用，可以删除。"
        elif action == "copy":
            copied = create_question_items(
                [
                    QuestionBankItem(
                        school=question.school,
                        subject=question.subject,
                        creator=request.user,
                        stem=question.stem,
                        question_type=question.question_type,
                        options=question.options,
                        answer=question.answer,
                        analysis=question.analysis,
                        difficulty=question.difficulty,
                        knowledge_point=question.knowledge_point,
                        default_score=question.default_score,
                        status=QuestionBankItem.Status.DRAFT,
                        source=QuestionBankItem.Source.COPY,
                        library_scope=QuestionBankItem.LibraryScope.PERSONAL,
                    )
                ],
                actor=request.user,
            )[0]
            copied = _question_queryset().get(pk=copied.pk)
            row = question_row(copied)
            row["is_owner"] = True
            return ok(row, "题目已复制为新的个人题目。", status=201)
        else:
            raise AssessmentError("题目操作不正确。")
        question = _question_queryset().get(pk=question.pk)
        row = question_row(question)
        row["is_owner"] = True
        return ok(row, message)
    except AssessmentError as exc:
        return _error(exc)


def _school_admin_question(user, pk) -> QuestionBankItem:
    question = _question_queryset().filter(
        pk=pk,
        school=user.school,
        library_scope=QuestionBankItem.LibraryScope.SCHOOL,
    ).first()
    if question is None:
        raise AssessmentError("题目不存在或不属于本校。", status=404)
    return question


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_question_reviews(request):
    queryset = _question_queryset().filter(
        school=request.user.school,
        library_scope=QuestionBankItem.LibraryScope.SCHOOL,
    )
    status_filter = str(request.query_params.get("status") or "").strip()
    subject_id = request.query_params.get("subject")
    source_filter = str(request.query_params.get("source") or "").strip()
    query = str(request.query_params.get("q") or "").strip()
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if subject_id:
        queryset = queryset.filter(subject_id=subject_id)
    if source_filter:
        queryset = queryset.filter(source=source_filter)
    if query:
        queryset = queryset.filter(
            Q(stem__icontains=query)
            | Q(knowledge_point__icontains=query)
            | Q(creator__display_name__icontains=query)
            | Q(creator__username__icontains=query)
        )
    try:
        page_size = min(max(int(request.query_params.get("page_size") or 30), 1), 100)
        page_number = max(int(request.query_params.get("page") or 1), 1)
    except (TypeError, ValueError):
        page_size = 30
        page_number = 1
    page = Paginator(
        queryset.order_by("-updated_at", "-id"),
        page_size,
    ).get_page(page_number)
    return ok(
        {
            "count": page.paginator.count,
            "page": page.number,
            "page_size": page_size,
            "results": [question_row(question) for question in page.object_list],
        }
    )


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_question_review_detail(request, pk):
    try:
        return ok(_question_detail_row(_school_admin_question(request.user, pk)))
    except AssessmentError as exc:
        return _error(exc)


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_question_review_action(request, pk):
    try:
        question = _school_admin_question(request.user, pk)
        action = str(request.data.get("action") or "").strip()
        note = str(request.data.get("note") or "").strip()[:1000]
        if action == "approve_trial":
            if question.status != QuestionBankItem.Status.PENDING_REVIEW:
                raise AssessmentError("只有待审核题目可以通过为可试用。")
            transition_question(
                question,
                actor=request.user,
                to_status=QuestionBankItem.Status.TRIAL,
                action=action,
                note=note,
            )
            message = "题目已通过审核，可由创建教师试用。"
        elif action == "return":
            if question.status not in {
                QuestionBankItem.Status.PENDING_REVIEW,
                QuestionBankItem.Status.TRIAL,
            }:
                raise AssessmentError("当前题目不能退回修改。")
            if not note:
                raise AssessmentError("退回时需要填写修改说明。", errors={"note": ["请填写退回原因。"]})
            transition_question(
                question,
                actor=request.user,
                to_status=QuestionBankItem.Status.DRAFT,
                action=action,
                note=note,
            )
            message = "题目已退回教师修改。"
        elif action == "activate":
            if question.status != QuestionBankItem.Status.TRIAL:
                raise AssessmentError("只有可试用题目可以正式启用。")
            if int(getattr(question, "trial_response_count", 0) or 0) < 1:
                raise AssessmentError("题目尚无试用作答，不能正式启用。")
            transition_question(
                question,
                actor=request.user,
                to_status=QuestionBankItem.Status.ACTIVE,
                action=action,
                note=note,
            )
            message = "题目已正式启用并进入学校共享题库。"
        elif action == "disable":
            if question.status == QuestionBankItem.Status.DISABLED:
                raise AssessmentError("题目已经停用。")
            if not note:
                raise AssessmentError("停用时需要填写原因。", errors={"note": ["请填写停用原因。"]})
            transition_question(
                question,
                actor=request.user,
                to_status=QuestionBankItem.Status.DISABLED,
                action=action,
                note=note,
            )
            message = "题目已停用；历史试卷和答卷不受影响。"
        else:
            raise AssessmentError("审核操作不正确。")
        return ok(_question_detail_row(_school_admin_question(request.user, pk)), message)
    except AssessmentError as exc:
        return _error(exc)


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_question_reviews_export(request):
    questions = _question_queryset().filter(
        school=request.user.school,
        library_scope=QuestionBankItem.LibraryScope.SCHOOL,
    )
    return export_rows(
        f"{request.user.school.code}_题库审核_{timezone.localtime():%Y%m%d%H%M%S}.xlsx",
        "题库审核",
        [
            "ID",
            "学科",
            "题型",
            "题干",
            "创建教师",
            "来源",
            "状态",
            "版本",
            "试卷使用次数",
            "试用作答人数",
            "试用正确率",
            "审核说明",
            "提交审核时间",
            "更新时间",
        ],
        [
            [
                item.id,
                item.subject.name,
                item.get_question_type_display(),
                item.stem,
                item.creator.display_name or item.creator.username,
                item.get_source_display(),
                item.get_status_display(),
                item.version_no,
                item.assessment_use_count,
                item.trial_response_count,
                round(item.trial_correct_count * 100 / item.trial_response_count, 2)
                if item.trial_response_count >= MIN_QUESTION_STAT_SAMPLE
                else "数据不足",
                item.review_note or item.disabled_reason,
                item.submitted_for_review_at,
                item.updated_at,
            ]
            for item in questions.order_by("-updated_at", "-id")
        ],
    )


def _common_set_row(question_set) -> dict:
    return {
        "id": question_set.id,
        "subject": _subject_row(question_set.subject),
        "title": question_set.title,
        "grade_scope": question_set.grade_scope,
        "term": question_set.term,
        "version_no": question_set.version_no,
        "content_hash": question_set.content_hash,
        "status": question_set.status,
        "status_label": question_set.get_status_display(),
        "question_count": len(getattr(question_set, "prefetched_items", [])),
        "items": [
            {
                "id": item.id,
                "question_id": item.question_version.original_question_id,
                "question_version": item.question_version_id,
                "question_version_no": item.question_version.version_no,
                "stem": item.question_version.stem,
                "comparison_code": item.comparison_code,
                "required": item.required,
                "sort_order": item.sort_order,
            }
            for item in getattr(question_set, "prefetched_items", [])
        ],
        "published_at": question_set.published_at,
        "created_at": question_set.created_at,
        "updated_at": question_set.updated_at,
    }


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_common_question_sets(request):
    if request.method == "GET":
        rows = list(
            CommonQuestionSet.objects.filter(school=request.user.school)
            .select_related("subject")
            .prefetch_related("items__question_version")
        )
        for row in rows:
            row.prefetched_items = list(row.items.all())
        return ok([_common_set_row(row) for row in rows])

    subject = Subject.objects.filter(
        pk=request.data.get("subject"), school=request.user.school, is_active=True
    ).first()
    if subject is None:
        return fail("请选择本校有效学科。", status=400)
    title = _clean_text(request.data.get("title"), 128)
    grade_scope = _clean_text(request.data.get("grade_scope"), 32)
    term = _clean_text(request.data.get("term"), 32)
    raw_items = request.data.get("items") if isinstance(request.data.get("items"), list) else []
    if len(title) < 2 or not raw_items:
        return fail("请填写集合名称并至少选择一道共同题。", status=400)
    question_ids = {
        int(item.get("question_id"))
        for item in raw_items
        if isinstance(item, dict) and str(item.get("question_id")).isdigit()
    }
    questions = {
        item.id: item
        for item in QuestionBankItem.objects.filter(
            id__in=question_ids,
            school=request.user.school,
            subject=subject,
            library_scope=QuestionBankItem.LibraryScope.SCHOOL,
            status=QuestionBankItem.Status.ACTIVE,
        )
    }
    if len(questions) != len(question_ids):
        return fail("共同题只能选择本学科已启用的共享题目。", status=400)
    cleaned_items = []
    seen_codes = set()
    for index, raw in enumerate(raw_items, start=1):
        question = questions.get(int(raw.get("question_id") or 0)) if isinstance(raw, dict) else None
        code = _clean_text(raw.get("comparison_code") if isinstance(raw, dict) else "", 64).upper()
        if question is None or not code or code in seen_codes:
            return fail("每道共同题都需要填写不重复的比较编号。", status=400)
        seen_codes.add(code)
        cleaned_items.append((question, code, bool(raw.get("required", True))))
    with transaction.atomic():
        latest = (
            CommonQuestionSet.objects.select_for_update()
            .filter(
                school=request.user.school,
                subject=subject,
                grade_scope=grade_scope,
                term=term,
            )
            .order_by("-version_no")
            .first()
        )
        CommonQuestionSet.objects.filter(
            school=request.user.school,
            subject=subject,
            grade_scope=grade_scope,
            term=term,
            status=CommonQuestionSet.Status.ACTIVE,
        ).update(status=CommonQuestionSet.Status.ARCHIVED)
        version_rows = []
        for question, code, required in cleaned_items:
            question.item_role = QuestionBankItem.ItemRole.COMMON
            question.layer_scope = QuestionBankItem.LayerScope.ALL
            question.comparison_code = code
            question.save(
                update_fields=[
                    "item_role", "layer_scope", "comparison_code", "updated_at"
                ]
            )
            version_rows.append(
                (ensure_question_version(question, actor=request.user), code, required)
            )
        hash_payload = [
            {
                "comparison_code": code,
                "question_hash": version.content_hash,
                "required": required,
            }
            for version, code, required in version_rows
        ]
        content_hash = hashlib.sha256(
            json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        question_set = CommonQuestionSet.objects.create(
            school=request.user.school,
            subject=subject,
            title=title,
            grade_scope=grade_scope,
            term=term,
            version_no=(latest.version_no + 1 if latest else 1),
            content_hash=content_hash,
            status=CommonQuestionSet.Status.ACTIVE,
            created_by=request.user,
            published_by=request.user,
            published_at=timezone.now(),
        )
        CommonQuestionSetItem.objects.bulk_create(
            [
                CommonQuestionSetItem(
                    question_set=question_set,
                    question_version=version,
                    comparison_code=code,
                    required=required,
                    sort_order=index * 10,
                )
                for index, (version, code, required) in enumerate(version_rows, start=1)
            ]
        )
    question_set.prefetched_items = list(
        question_set.items.select_related("question_version").all()
    )
    return ok(_common_set_row(question_set), "共同题集合已发布。", status=201)


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def school_admin_common_question_set_archive(request, pk):
    question_set = CommonQuestionSet.objects.filter(
        pk=pk, school=request.user.school
    ).first()
    if question_set is None:
        return fail("共同题集合不存在。", status=404)
    if question_set.status == CommonQuestionSet.Status.ARCHIVED:
        return ok({}, "共同题集合已经归档。")
    question_set.status = CommonQuestionSet.Status.ARCHIVED
    question_set.save(update_fields=["status", "updated_at"])
    return ok({}, "共同题集合已归档；历史测试版本不受影响。")


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def school_admin_common_question_sets_export(request):
    rows = list(
        CommonQuestionSet.objects.filter(school=request.user.school)
        .select_related("subject")
        .prefetch_related("items__question_version")
    )
    workbook = build_workbook(
        [
            {
                "title": "共同题集合",
                "headers": ["集合ID", "学科", "名称", "年级范围", "学期", "版本", "状态", "校验码", "发布时间"],
                "rows": [
                    [item.id, item.subject.name, item.title, item.grade_scope, item.term, item.version_no, item.get_status_display(), item.content_hash, item.published_at]
                    for item in rows
                ],
            },
            {
                "title": "共同题明细",
                "headers": ["集合ID", "集合名称", "集合版本", "比较编号", "题目版本", "题目校验码", "题干", "必备题"],
                "rows": [
                    [item.id, item.title, item.version_no, row.comparison_code, row.question_version.version_no, row.question_version.content_hash, row.question_version.stem, "是" if row.required else "否"]
                    for item in rows
                    for row in item.items.all()
                ],
            },
        ]
    )
    return workbook_response(
        workbook,
        f"{request.user.school.code}_共同题集合_{timezone.localtime():%Y%m%d%H%M%S}.xlsx",
    )


def _clean_assessment_payload(user, data, assessment=None) -> tuple[dict, list[ClassGroup]]:
    title = _clean_text(data.get("title"), 128)
    if len(title) < 2:
        raise AssessmentError("请填写测试名称。", errors={"title": ["测试名称至少 2 个字符。"]})
    subject = Subject.objects.filter(pk=data.get("subject"), school=user.school, is_active=True).first()
    if subject is None:
        raise AssessmentError("请选择本校有效学科。", errors={"subject": ["学科不存在或已停用。"]})
    try:
        duration = int(data.get("duration_minutes") or 45)
    except (TypeError, ValueError):
        duration = 0
    if duration < 1 or duration > 300:
        raise AssessmentError("测试时长应为 1-300 分钟。", errors={"duration_minutes": ["请输入有效时长。"]})
    raw_class_ids = data.get("class_ids") if isinstance(data.get("class_ids"), list) else []
    class_ids = {int(item) for item in raw_class_ids if str(item).isdigit()}
    allowed_class_ids = set(_teacher_class_ids(user))
    if not class_ids or not class_ids.issubset(allowed_class_ids):
        raise AssessmentError("请选择本人任教班级。", errors={"class_ids": ["至少选择一个有效任教班级。"]})
    classes = list(ClassGroup.objects.filter(pk__in=class_ids, school=user.school, status=ClassGroup.Status.ACTIVE))
    course = None
    if data.get("course"):
        course = Course.objects.filter(pk=data.get("course"), teacher=user, subject=subject).first()
        if course is None:
            raise AssessmentError("课程与学科不匹配。", errors={"course": ["请选择本人该学科课程。"]})
    common_set = None
    if data.get("common_question_set"):
        common_set = (
            CommonQuestionSet.objects.filter(
                pk=data.get("common_question_set"),
                school=user.school,
                subject=subject,
                status=CommonQuestionSet.Status.ACTIVE,
            )
            .prefetch_related("items")
            .first()
        )
        if common_set is None:
            raise AssessmentError(
                "共同题集合不存在、未启用或与学科不匹配。",
                errors={"common_question_set": ["请选择本学科已启用的共同题集合。"]},
            )
    start_at = data.get("start_at") or None
    end_at = data.get("end_at") or None
    from django.utils.dateparse import parse_datetime
    start_at = parse_datetime(str(start_at)) if start_at else None
    end_at = parse_datetime(str(end_at)) if end_at else None
    if start_at and timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
    if end_at and timezone.is_naive(end_at):
        end_at = timezone.make_aware(end_at, timezone.get_current_timezone())
    if start_at and end_at and end_at <= start_at:
        raise AssessmentError("结束时间必须晚于开始时间。", errors={"end_at": ["请调整时间范围。"]})
    return {
        "title": title,
        "subject": subject,
        "course": course,
        "common_question_set": common_set,
        "common_set_version": common_set.version_no if common_set else None,
        "common_set_hash": common_set.content_hash if common_set else "",
        "instruction": str(data.get("instruction") or "").strip()[:2000],
        "duration_minutes": duration,
        "start_at": start_at,
        "end_at": end_at,
        "show_score_after_submit": bool(data.get("show_score_after_submit", False)),
        "randomize_question_order": bool(data.get("randomize_question_order", False)),
        "randomize_option_order": bool(data.get("randomize_option_order", False)),
    }, classes


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_assessments(request):
    if request.method == "POST":
        try:
            payload, classes = _clean_assessment_payload(request.user, request.data)
            with transaction.atomic():
                assessment = TestAssessment.objects.create(school=request.user.school, teacher=request.user, **payload)
                assessment.target_classes.set(classes)
            return ok(assessment_row(assessment), "测试已创建。", status=201)
        except AssessmentError as exc:
            return _error(exc)
    queryset = (
        TestAssessment.objects.filter(school=request.user.school, teacher=request.user, is_active=True)
        .select_related("subject", "course", "teacher")
        .prefetch_related("target_classes")
        .annotate(
            question_count=Count("questions", distinct=True),
            attempt_count=Count("attempts", distinct=True),
            submitted_count=Count("attempts", filter=~Q(attempts__status=TestAttempt.Status.IN_PROGRESS), distinct=True),
        )
    )
    status_value = request.query_params.get("status")
    if status_value:
        queryset = queryset.filter(status=status_value)
    return ok([assessment_row(item) for item in queryset[:300]])


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsTeacher])
def teacher_assessment_detail(request, pk):
    try:
        assessment = _teacher_assessment(request.user, pk)
        if request.method == "GET":
            return ok(assessment_row(assessment, detail=True))
        if request.method == "DELETE":
            if assessment.status != TestAssessment.Status.DRAFT:
                raise AssessmentError("只有草稿测试可以删除。")
            if assessment.attempts.exists():
                raise AssessmentError("已有学生答卷，不能删除测试。")
            assessment.delete()
            return ok({}, "测试已删除。")
        if assessment.status != TestAssessment.Status.DRAFT:
            raise AssessmentError("只有草稿测试可以修改基本信息。")
        payload, classes = _clean_assessment_payload(request.user, request.data, assessment)
        for field, value in payload.items():
            setattr(assessment, field, value)
        assessment.save()
        assessment.target_classes.set(classes)
        return ok(assessment_row(assessment, detail=True), "测试已更新。")
    except AssessmentError as exc:
        return _error(exc)


def _validate_assessment_question_mix(assessment, sources: list[QuestionBankItem]) -> None:
    common_sources = [
        item for item in sources if item.item_role == QuestionBankItem.ItemRole.COMMON
    ]
    layered_sources = [
        item for item in sources if item.item_role == QuestionBankItem.ItemRole.LAYERED
    ]
    if common_sources and assessment.common_question_set_id is None:
        raise AssessmentError("共同题必须来自已选择的共同题集合。")
    if layered_sources and not common_sources:
        raise AssessmentError("分层题不能替代共同题，请至少加入一道共同题。")
    if assessment.common_question_set_id:
        required_ids = set(
            assessment.common_question_set.items.filter(required=True).values_list(
                "question_version__original_question_id", flat=True
            )
        )
        selected_ids = {item.id for item in common_sources}
        missing = required_ids - selected_ids
        if missing:
            raise AssessmentError(
                "共同测试缺少共同题集合中的必备题，请补齐后再保存。",
                errors={"questions": [f"还缺少 {len(missing)} 道必备共同题。"]},
            )


@api_view(["PUT"])
@permission_classes([IsTeacher])
def teacher_assessment_questions(request, pk):
    try:
        assessment = _teacher_assessment(request.user, pk)
        if assessment.status != TestAssessment.Status.DRAFT:
            raise AssessmentError("只有草稿测试可以调整试题。")
        raw_items = request.data.get("questions") if isinstance(request.data.get("questions"), list) else []
        if not raw_items:
            raise AssessmentError("请至少选择一道题目。", errors={"questions": ["试卷不能为空。"]})
        question_ids = [int(item.get("question_id")) for item in raw_items if isinstance(item, dict) and str(item.get("question_id")).isdigit()]
        source_map = {
            item.id: item
            for item in QuestionBankItem.objects.filter(
                id__in=question_ids,
                school=request.user.school,
                subject=assessment.subject,
            ).filter(
                Q(
                    library_scope=QuestionBankItem.LibraryScope.SCHOOL,
                    status=QuestionBankItem.Status.ACTIVE,
                )
                | Q(
                    status__in={
                        QuestionBankItem.Status.DRAFT,
                        QuestionBankItem.Status.TRIAL,
                    },
                    creator=request.user,
                )
            )
        }
        if len(source_map) != len(set(question_ids)):
            raise AssessmentError("部分题目未启用、不是本人可试用题目或学科不匹配。")
        sources = [source_map[question_id] for question_id in question_ids]
        _validate_assessment_question_mix(assessment, sources)
        snapshots = []
        total_score = 0.0
        for index, raw_item in enumerate(raw_items, start=1):
            source = source_map.get(int(raw_item.get("question_id") or 0))
            if source is None:
                continue
            try:
                score = float(raw_item.get("score") or source.default_score)
            except (TypeError, ValueError):
                score = 0
            if score <= 0 or score > 100:
                raise AssessmentError(f"第 {index} 题分值不正确。")
            total_score += score
            source_version = ensure_question_version(source, actor=source.creator)
            snapshots.append(TestAssessmentQuestion(
                assessment=assessment,
                source_question=source,
                source_version=source_version,
                source_status=source.status,
                question_type=source.question_type,
                stem=source.stem,
                options=source.options,
                answer=source.answer,
                analysis=source.analysis,
                knowledge_point=source.knowledge_point,
                score=score,
                sort_order=index * 10,
                item_role=source.item_role,
                layer_scope=source.layer_scope,
                comparison_code=source.comparison_code,
            ))
        if total_score > 1000:
            raise AssessmentError("试卷总分不能超过 1000 分。")
        with transaction.atomic():
            assessment.questions.all().delete()
            TestAssessmentQuestion.objects.bulk_create(snapshots)
            assessment.randomize_question_order = bool(request.data.get("randomize_question_order", False))
            assessment.randomize_option_order = bool(request.data.get("randomize_option_order", False))
            assessment.save(update_fields=["randomize_question_order", "randomize_option_order", "updated_at"])
        assessment = _teacher_assessment(request.user, pk)
        return ok(assessment_row(assessment, detail=True), "试卷题目已保存。")
    except AssessmentError as exc:
        return _error(exc)


@transaction.atomic
def _change_assessment_status(user, pk, action: str):
    assessment = _teacher_assessment(user, pk)
    now = timezone.now()
    if action == "publish":
        if assessment.status != TestAssessment.Status.DRAFT or not assessment.questions.exists():
            raise AssessmentError("请先完成组卷，再发布测试。")
        snapshots = list(assessment.questions.all())
        common_snapshots = [
            item
            for item in snapshots
            if item.item_role == QuestionBankItem.ItemRole.COMMON
        ]
        if any(item.item_role == QuestionBankItem.ItemRole.LAYERED for item in snapshots) and not common_snapshots:
            raise AssessmentError("分层题不能替代共同题，请至少加入一道共同题。")
        if assessment.common_question_set_id:
            required_ids = set(
                assessment.common_question_set.items.filter(required=True).values_list(
                    "question_version__original_question_id", flat=True
                )
            )
            if required_ids - {item.source_question_id for item in common_snapshots}:
                raise AssessmentError("共同测试仍缺少共同题集合中的必备题。")
        elif common_snapshots:
            raise AssessmentError("共同题必须绑定共同题集合。")
        assessment.status = TestAssessment.Status.PUBLISHED
    elif action == "open":
        if assessment.status not in {TestAssessment.Status.PUBLISHED, TestAssessment.Status.CLOSED}:
            raise AssessmentError("当前状态不能开启测试。")
        if assessment.status == TestAssessment.Status.CLOSED and assessment.attempts.exists():
            raise AssessmentError("已有学生答卷的测试不能重新开启，请复制后创建新测试。")
        if assessment.end_at and assessment.end_at <= now:
            raise AssessmentError("测试结束时间已过，请先调整时间。")
        if assessment.start_at and assessment.start_at > now:
            raise AssessmentError("测试开始时间未到，暂不能提前开启。")
        assessment.status = TestAssessment.Status.OPEN
        assessment.opened_at = now
        assessment.closed_at = None
    elif action == "close":
        if assessment.status != TestAssessment.Status.OPEN:
            raise AssessmentError("只有进行中的测试可以结束。")
        assessment.status = TestAssessment.Status.CLOSED
        assessment.closed_at = now
    assessment.save(update_fields=["status", "opened_at", "closed_at", "updated_at"])
    try:
        if action == "open":
            release_assessment_opportunities(
                assessment=assessment,
                actor=user,
                occurred_at=now,
            )
        elif action == "close":
            for attempt in assessment.attempts.filter(
                status=TestAttempt.Status.IN_PROGRESS
            ).select_related("assessment", "student", "class_group"):
                _submit_attempt(attempt, source_override="server")
            withdraw_assessment_opportunities(
                assessment=assessment,
                actor=user,
                occurred_at=timezone.now(),
            )
    except AssessmentEventError as exc:
        raise AssessmentError(exc.message) from exc
    return assessment


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_assessment_publish(request, pk):
    try:
        return ok(assessment_row(_change_assessment_status(request.user, pk, "publish")), "测试已发布，等待开启。")
    except AssessmentError as exc:
        return _error(exc)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_assessment_open(request, pk):
    try:
        return ok(assessment_row(_change_assessment_status(request.user, pk, "open")), "测试已开启，学生现在可以作答。")
    except AssessmentError as exc:
        return _error(exc)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_assessment_close(request, pk):
    try:
        return ok(assessment_row(_change_assessment_status(request.user, pk, "close")), "测试已结束。")
    except AssessmentError as exc:
        return _error(exc)


def _attempt_row(attempt: TestAttempt, *, include_answers=False) -> dict:
    row = {
        "id": attempt.id,
        "student": _user_row(attempt.student),
        "class_group": _class_row(attempt.class_group),
        "status": attempt.status,
        "status_label": attempt.get_status_display(),
        "objective_score": attempt.objective_score,
        "subjective_score": attempt.subjective_score,
        "total_score": attempt.total_score,
        "started_at": attempt.started_at,
        "submitted_at": attempt.submitted_at,
        "graded_at": attempt.graded_at,
    }
    if include_answers:
        row["answers"] = [{
            "id": item.id,
            "question": assessment_question_row(item.question, include_answer=True),
            "answer": item.answer,
            "auto_score": item.auto_score,
            "manual_score": item.manual_score,
            "final_score": item.final_score,
            "is_correct": item.is_correct,
            "feedback": item.feedback,
        } for item in attempt.answer_rows.select_related("question").all()]
    return row


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if not x_var or not y_var:
        return None
    return round(numerator / math.sqrt(x_var * y_var), 3)


def _assessment_question_statistics(question, submitted_attempts) -> dict:
    answers = list(
        TestAttemptAnswer.objects.filter(
            question=question, attempt__in=submitted_attempts
        ).select_related("attempt")
    )
    answered_rows = [row for row in answers if row.answer]
    correct_count = sum(row.is_correct is True for row in answered_rows)
    option_counts = {str(option): 0 for option in question.options or []}
    if option_counts:
        for row in answered_rows:
            for option in row.answer if isinstance(row.answer, list) else []:
                normalized_option = str(option)
                if normalized_option in option_counts:
                    option_counts[normalized_option] += 1
    sample_size = len(answered_rows)
    insufficient = sample_size < MIN_QUESTION_STAT_SAMPLE
    discrimination = None
    if not insufficient:
        item_scores = [
            float(row.manual_score if row.manual_score is not None else row.auto_score)
            / float(question.score or 1)
            for row in answered_rows
        ]
        total_scores = [
            float(row.attempt.total_score)
            - float(row.manual_score if row.manual_score is not None else row.auto_score)
            for row in answered_rows
        ]
        discrimination = _pearson(item_scores, total_scores)
    return {
        "question": assessment_question_row(question, include_answer=True),
        "sample_size": sample_size,
        "answered_count": sample_size,
        "correct_count": correct_count,
        "correct_rate": None if insufficient else round(correct_count * 100 / sample_size, 1),
        "difficulty": None if insufficient else round(correct_count / sample_size, 3),
        "discrimination": discrimination,
        "option_distribution": [
            {"option": option, "count": count}
            for option, count in option_counts.items()
        ],
        "data_status": "insufficient" if insufficient else "available",
        "data_status_label": (
            f"数据不足（至少需要 {MIN_QUESTION_STAT_SAMPLE} 份有效作答）"
            if insufficient
            else "数据可用"
        ),
        "average_score": round(
            float(
                TestAttemptAnswer.objects.filter(
                    pk__in=[row.pk for row in answered_rows]
                ).aggregate(value=Avg("auto_score"))["value"]
                or 0
            ),
            2,
        ),
    }


def _refresh_assessment_comparability(assessment):
    other_assessments = TestAssessment.objects.filter(
        school=assessment.school,
        subject=assessment.subject,
        is_active=True,
    ).exclude(pk=assessment.pk).exclude(status=TestAssessment.Status.DRAFT)
    current_map = {
        item.comparison_code: item.source_version.content_hash
        for item in assessment.questions.select_related("source_version")
        if item.item_role == QuestionBankItem.ItemRole.COMMON
        and item.comparison_code
        and item.source_version_id
    }
    records = []
    for other in other_assessments:
        if assessment.id < other.id:
            left, right = assessment, other
            left_map, right_map = current_map, {
                item.comparison_code: item.source_version.content_hash
                for item in other.questions.select_related("source_version")
                if item.item_role == QuestionBankItem.ItemRole.COMMON
                and item.comparison_code
                and item.source_version_id
            }
        else:
            left, right = other, assessment
            left_map = {
                item.comparison_code: item.source_version.content_hash
                for item in other.questions.select_related("source_version")
                if item.item_role == QuestionBankItem.ItemRole.COMMON
                and item.comparison_code
                and item.source_version_id
            }
            right_map = current_map
        overlap = set(left_map) & set(right_map)
        exact = sum(left_map[code] == right_map[code] for code in overlap)
        left_sample = left.attempts.exclude(status=TestAttempt.Status.IN_PROGRESS).count()
        right_sample = right.attempts.exclude(status=TestAttempt.Status.IN_PROGRESS).count()
        reasons = []
        if not overlap:
            status = AssessmentComparabilityRecord.Status.NOT_COMPARABLE
            reasons.append("没有相同比较编号的共同题。")
        elif exact != len(overlap):
            status = AssessmentComparabilityRecord.Status.NOT_COMPARABLE
            reasons.append("相同比较编号对应的题目版本不同。")
        elif min(left_sample, right_sample) < MIN_QUESTION_STAT_SAMPLE:
            status = AssessmentComparabilityRecord.Status.INSUFFICIENT
            reasons.append(f"两份测试都需要至少 {MIN_QUESTION_STAT_SAMPLE} 份有效答卷。")
        else:
            status = AssessmentComparabilityRecord.Status.COMPARABLE
            reasons.append("共同题版本和样本量满足比较条件。")
        record, _ = AssessmentComparabilityRecord.objects.update_or_create(
            school=assessment.school,
            left_assessment=left,
            right_assessment=right,
            defaults={
                "status": status,
                "common_question_count": len(overlap),
                "exact_version_match_count": exact,
                "left_sample_size": left_sample,
                "right_sample_size": right_sample,
                "reasons": reasons,
            },
        )
        records.append(record)
    return records


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_assessment_results(request, pk):
    try:
        assessment = _teacher_assessment(request.user, pk)
        attempts = list(assessment.attempts.select_related("student", "class_group").order_by("class_group__name", "student__username"))
        assigned_count = StudentProfile.objects.filter(class_group__in=assessment.target_classes.all(), user__is_active=True).count()
        submitted = [item for item in attempts if item.status != TestAttempt.Status.IN_PROGRESS]
        question_stats = []
        for question in assessment.questions.all():
            question_stats.append(_assessment_question_statistics(question, submitted))
        comparison_records = _refresh_assessment_comparability(assessment)
        return ok({
            "assessment": assessment_row(assessment, detail=True),
            "summary": {
                "assigned_count": assigned_count,
                "started_count": len(attempts),
                "submitted_count": len(submitted),
                "pending_grade_count": sum(item.status == TestAttempt.Status.SUBMITTED for item in attempts),
                "average_score": round(sum(item.total_score for item in submitted) / len(submitted), 2) if submitted else 0,
            },
            "attempts": [_attempt_row(item) for item in attempts],
            "question_stats": question_stats,
            "comparisons": [
                {
                    "id": record.id,
                    "assessment": record.right_assessment_id
                    if record.left_assessment_id == assessment.id
                    else record.left_assessment_id,
                    "status": record.status,
                    "status_label": record.get_status_display(),
                    "common_question_count": record.common_question_count,
                    "exact_version_match_count": record.exact_version_match_count,
                    "left_sample_size": record.left_sample_size,
                    "right_sample_size": record.right_sample_size,
                    "reasons": record.reasons,
                }
                for record in comparison_records
            ],
        })
    except AssessmentError as exc:
        return _error(exc)


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_assessment_results_export(request, pk):
    try:
        assessment = _teacher_assessment(request.user, pk)
    except AssessmentError as exc:
        return _error(exc)
    attempts = list(assessment.attempts.select_related("student", "class_group").order_by("class_group__name", "student__username"))
    submitted = [item for item in attempts if item.status != TestAttempt.Status.IN_PROGRESS]
    assigned_count = StudentProfile.objects.filter(class_group__in=assessment.target_classes.all(), user__is_active=True).count()
    question_rows = []
    for index, question in enumerate(assessment.questions.all(), start=1):
        stats = _assessment_question_statistics(question, submitted)
        question_rows.append([
            index,
            question.get_question_type_display(),
            question.stem,
            question.knowledge_point,
            question.score,
            stats["answered_count"],
            stats["correct_count"],
            stats["correct_rate"] if stats["correct_rate"] is not None else "数据不足",
            stats["difficulty"] if stats["difficulty"] is not None else "数据不足",
            stats["discrimination"] if stats["discrimination"] is not None else "数据不足",
            " | ".join(
                f"{item['option']}:{item['count']}"
                for item in stats["option_distribution"]
            ),
            stats["average_score"],
        ])
    workbook = build_workbook([
        {
            "title": "测试汇总",
            "headers": ["测试名称", "学科", "班级", "试卷总分", "应考人数", "开始人数", "提交人数", "待评分人数", "平均分", "状态"],
            "rows": [[
                assessment.title,
                assessment.subject.name,
                "、".join(item.name for item in assessment.target_classes.all()),
                _assessment_total_score(assessment),
                assigned_count,
                len(attempts),
                len(submitted),
                sum(item.status == TestAttempt.Status.SUBMITTED for item in attempts),
                round(sum(item.total_score for item in submitted) / len(submitted), 2) if submitted else 0,
                assessment.get_status_display(),
            ]],
        },
        {
            "title": "学生成绩",
            "headers": ["登录账号", "学生姓名", "班级", "状态", "客观题得分", "主观题得分", "总分", "开始时间", "提交时间", "评分时间"],
            "rows": [[item.student.username, item.student.display_name, item.class_group.name, item.get_status_display(), item.objective_score, item.subjective_score, item.total_score, item.started_at, item.submitted_at, item.graded_at] for item in attempts],
        },
        {
            "title": "逐题统计",
            "headers": ["题号", "题型", "题干", "知识点", "分值", "作答人数", "正确人数", "正确率(%)", "难度", "区分度", "选项分布", "平均自动得分"],
            "rows": question_rows,
        },
    ])
    return workbook_response(workbook, f"{assessment.title}_成绩分析_{timezone.localtime():%Y%m%d%H%M%S}.xlsx")


@api_view(["GET", "PATCH"])
@permission_classes([IsTeacher])
def teacher_attempt_grade(request, attempt_id):
    attempt = (
        TestAttempt.objects.filter(pk=attempt_id, assessment__teacher=request.user, assessment__school=request.user.school)
        .select_related("assessment", "student", "class_group")
        .first()
    )
    if attempt is None:
        return fail("答卷不存在或无权查看。", status=404)
    if request.method == "GET":
        return ok(_attempt_row(attempt, include_answers=True))
    raw_answers = request.data.get("answers") if isinstance(request.data.get("answers"), list) else []
    answer_map = {item.id: item for item in attempt.answer_rows.select_related("question").all()}
    try:
        with transaction.atomic():
            changed_rows = {}
            for raw in raw_answers:
                if not isinstance(raw, dict) or not str(raw.get("answer_id")).isdigit():
                    continue
                row = answer_map.get(int(raw["answer_id"]))
                if row is None:
                    continue
                score = float(raw.get("score") or 0)
                if score < 0 or score > row.question.score:
                    raise AssessmentError(f"“{row.question.stem[:20]}”评分超出题目分值。")
                feedback = str(raw.get("feedback") or "").strip()[:1000]
                if row.manual_score != score or row.feedback != feedback:
                    row.manual_score = score
                    row.feedback = feedback
                    row.save(update_fields=["manual_score", "feedback", "answered_at"])
                    changed_rows[row.id] = row
            pending_subjective = attempt.answer_rows.filter(
                question__question_type=QuestionBankItem.QuestionType.TEXT,
                manual_score__isnull=True,
            ).count()
            if pending_subjective:
                raise AssessmentError(f"还有 {pending_subjective} 道主观题未评分。")
            _recalculate_attempt(attempt)
            attempt.status = TestAttempt.Status.GRADED
            attempt.graded_at = timezone.now()
            attempt.save(update_fields=["objective_score", "subjective_score", "total_score", "status", "graded_at", "last_saved_at"])
            for row in changed_rows.values():
                record_assessment_item_grade(
                    attempt=attempt,
                    answer_row=row,
                    grading_state=next_manual_grading_state(
                        attempt=attempt,
                        question=row.question,
                    ),
                    score_raw=row.manual_score,
                    grader_type="teacher",
                    actor=request.user,
                    occurred_at=attempt.graded_at,
                )
        return ok(_attempt_row(attempt, include_answers=True), "评分已保存。")
    except (AssessmentError, AssessmentEventError, TypeError, ValueError) as exc:
        if isinstance(exc, AssessmentEventError):
            return _error(AssessmentError(exc.message))
        return _error(exc if isinstance(exc, AssessmentError) else AssessmentError("评分格式不正确。"))


def _student_profile(user) -> StudentProfile:
    profile = StudentProfile.objects.select_related("class_group").filter(user=user).first()
    if profile is None or profile.class_group_id is None:
        raise AssessmentError("请先完成班级选择。", status=403)
    return profile


def _student_assessment(user, pk) -> tuple[TestAssessment, StudentProfile]:
    profile = _student_profile(user)
    assessment = (
        TestAssessment.objects.filter(pk=pk, school=user.school, target_classes=profile.class_group, is_active=True)
        .select_related("subject", "course", "teacher")
        .prefetch_related("target_classes", "questions")
        .first()
    )
    if assessment is None:
        raise AssessmentError("测试不存在或未安排给当前班级。", status=404)
    return assessment, profile


def _is_assessment_available(assessment) -> bool:
    now = timezone.now()
    return (
        assessment.status == TestAssessment.Status.OPEN
        and (not assessment.start_at or assessment.start_at <= now)
        and (not assessment.end_at or assessment.end_at > now)
    )


def _attempt_deadline(attempt) -> timezone.datetime:
    deadline = attempt.started_at + timedelta(minutes=attempt.assessment.duration_minutes)
    if attempt.assessment.end_at and attempt.assessment.end_at < deadline:
        deadline = attempt.assessment.end_at
    if attempt.assessment.closed_at and attempt.assessment.closed_at < deadline:
        deadline = attempt.assessment.closed_at
    return deadline


def _layer_scope_allows(layer_scope: str, current_layer: str | None) -> bool:
    layer = str(current_layer or "").strip().lower()
    return layer in {
        QuestionBankItem.LayerScope.A: {"a"},
        QuestionBankItem.LayerScope.B: {"b"},
        QuestionBankItem.LayerScope.C: {"c"},
        QuestionBankItem.LayerScope.AB: {"a", "b"},
        QuestionBankItem.LayerScope.BC: {"b", "c"},
    }.get(layer_scope, set())


def _eligible_assessment_questions(assessment, profile) -> list[TestAssessmentQuestion]:
    return [
        question
        for question in assessment.questions.all()
        if question.item_role != QuestionBankItem.ItemRole.LAYERED
        or _layer_scope_allows(question.layer_scope, getattr(profile, "current_layer", None))
    ]


def _ensure_attempt_randomization(attempt: TestAttempt) -> None:
    profile = StudentProfile.objects.filter(user_id=attempt.student_id).first()
    questions = _eligible_assessment_questions(attempt.assessment, profile)
    question_ids = [item.id for item in questions]
    saved_question_ids = []
    if isinstance(attempt.question_order, list):
        for value in attempt.question_order:
            try:
                saved_question_ids.append(int(value))
            except (TypeError, ValueError):
                saved_question_ids = []
                break
    question_order_valid = len(saved_question_ids) == len(question_ids) and set(saved_question_ids) == set(question_ids)

    option_orders = attempt.option_orders if isinstance(attempt.option_orders, dict) else {}
    normalized_option_orders = {}
    option_orders_valid = True
    for question in questions:
        original = list(question.options or [])
        if question.question_type not in {
            QuestionBankItem.QuestionType.SINGLE,
            QuestionBankItem.QuestionType.MULTIPLE,
            QuestionBankItem.QuestionType.JUDGE,
        }:
            continue
        saved = option_orders.get(str(question.id))
        if not isinstance(saved, list) or len(saved) != len(original) or set(saved) != set(original):
            option_orders_valid = False
            break
        normalized_option_orders[str(question.id)] = saved

    if question_order_valid and option_orders_valid:
        return

    question_order = question_ids.copy()
    if attempt.assessment.randomize_question_order:
        random.SystemRandom().shuffle(question_order)

    normalized_option_orders = {}
    for question in questions:
        if question.question_type not in {
            QuestionBankItem.QuestionType.SINGLE,
            QuestionBankItem.QuestionType.MULTIPLE,
            QuestionBankItem.QuestionType.JUDGE,
        }:
            continue
        options = list(question.options or [])
        if attempt.assessment.randomize_option_order:
            random.SystemRandom().shuffle(options)
        normalized_option_orders[str(question.id)] = options

    attempt.question_order = question_order
    attempt.option_orders = normalized_option_orders
    attempt.save(update_fields=["question_order", "option_orders"])


def _attempt_questions(attempt: TestAttempt) -> list[dict]:
    _ensure_attempt_randomization(attempt)
    question_map = {item.id: item for item in attempt.assessment.questions.all()}
    rows = []
    for question_id in attempt.question_order:
        question = question_map.get(int(question_id))
        if question is None:
            continue
        rows.append(
            assessment_question_row(
                question,
                include_answer=False,
                options=attempt.option_orders.get(str(question.id), question.options),
                include_source_metadata=False,
            )
        )
    return rows


def _student_test_row(assessment, attempt=None) -> dict:
    row = assessment_row(assessment)
    row["available"] = _is_assessment_available(assessment)
    row["attempt"] = _attempt_row(attempt) if attempt else None
    return row


@api_view(["GET"])
@permission_classes([IsStudent])
def student_assessments(request):
    try:
        profile = _student_profile(request.user)
    except AssessmentError as exc:
        return _error(exc)
    assessments = (
        TestAssessment.objects.filter(school=request.user.school, target_classes=profile.class_group, is_active=True)
        .exclude(status=TestAssessment.Status.DRAFT)
        .select_related("subject", "course", "teacher")
        .prefetch_related("target_classes")
        .annotate(question_count=Count("questions", distinct=True), total_score=Sum("questions__score"))
        .distinct()
    )
    attempts = {item.assessment_id: item for item in TestAttempt.objects.filter(student=request.user, assessment__in=assessments)}
    return ok([_student_test_row(item, attempts.get(item.id)) for item in assessments])


@api_view(["GET"])
@permission_classes([IsStudent])
def student_assessment_detail(request, pk):
    try:
        assessment, _ = _student_assessment(request.user, pk)
        attempt = TestAttempt.objects.filter(assessment=assessment, student=request.user).first()
        if attempt is None:
            return ok({"assessment": _student_test_row(assessment), "attempt": None, "questions": []})
        if attempt.status == TestAttempt.Status.IN_PROGRESS and timezone.now() >= _attempt_deadline(attempt):
            _submit_attempt(attempt)
        questions = _attempt_questions(attempt)
        answers = {item.question_id: item.answer for item in attempt.answer_rows.all()}
        result = None
        if attempt.status != TestAttempt.Status.IN_PROGRESS and assessment.show_score_after_submit:
            result = {"score": attempt.total_score, "total_score": _assessment_total_score(assessment), "status": attempt.status}
        return ok({
            "assessment": _student_test_row(assessment, attempt),
            "attempt": _attempt_row(attempt),
            "questions": questions,
            "answers": answers,
            "deadline": _attempt_deadline(attempt),
            "server_time": timezone.now(),
            "result": result,
        })
    except AssessmentError as exc:
        return _error(exc)


@api_view(["POST"])
@permission_classes([IsStudent])
def student_assessment_start(request, pk):
    try:
        assessment, profile = _student_assessment(request.user, pk)
        if not _is_assessment_available(assessment):
            raise AssessmentError("测试尚未开启或已超过开放时间。", status=403)
        with transaction.atomic():
            attempt, _ = TestAttempt.objects.get_or_create(
                assessment=assessment,
                student=request.user,
                defaults={"class_group": profile.class_group},
            )
            _ensure_attempt_randomization(attempt)
        if attempt.status != TestAttempt.Status.IN_PROGRESS:
            raise AssessmentError("该测试已经提交，不能重复作答。")
        if timezone.now() >= _attempt_deadline(attempt):
            _submit_attempt(attempt)
            raise AssessmentError("作答时间已结束，系统已自动交卷。")
        return ok({"attempt": _attempt_row(attempt), "deadline": _attempt_deadline(attempt)}, "测试已开始。")
    except AssessmentError as exc:
        return _error(exc)


def _normalize_student_answer(question, value) -> list[str]:
    if question.question_type == QuestionBankItem.QuestionType.MULTIPLE:
        return _clean_answer_list(value)
    values = _clean_answer_list(value)
    return values[:1]


@api_view(["PATCH"])
@permission_classes([IsStudent])
def student_assessment_answer(request, pk):
    try:
        assessment, _ = _student_assessment(request.user, pk)
        attempt = TestAttempt.objects.filter(assessment=assessment, student=request.user, status=TestAttempt.Status.IN_PROGRESS).first()
        if attempt is None:
            raise AssessmentError("请先开始测试。")
        if timezone.now() >= _attempt_deadline(attempt):
            _submit_attempt(attempt)
            raise AssessmentError("作答时间已结束，系统已自动交卷。")
        question = assessment.questions.filter(pk=request.data.get("question_id")).first()
        if question is None or question.id not in set(attempt.question_order or []):
            raise AssessmentError("题目不存在。")
        answer = _normalize_student_answer(question, request.data.get("answer"))
        TestAttemptAnswer.objects.update_or_create(attempt=attempt, question=question, defaults={"answer": answer})
        return ok({"question_id": question.id, "answer": answer, "saved_at": timezone.now()}, "答案已保存。")
    except AssessmentError as exc:
        return _error(exc)


def _score_answer(question, answer: list[str]) -> tuple[float, bool | None]:
    expected = [str(item).strip() for item in (question.answer or []) if str(item).strip()]
    actual = [str(item).strip() for item in (answer or []) if str(item).strip()]
    if question.question_type == QuestionBankItem.QuestionType.TEXT:
        return 0, None
    if question.question_type == QuestionBankItem.QuestionType.MULTIPLE:
        correct = set(actual) == set(expected)
    elif question.question_type == QuestionBankItem.QuestionType.BLANK:
        correct = bool(actual) and actual[0].casefold() in {item.casefold() for item in expected}
    else:
        correct = actual[:1] == expected[:1]
    return (question.score if correct else 0), correct


def _recalculate_attempt(attempt):
    objective = 0.0
    subjective = 0.0
    for row in attempt.answer_rows.select_related("question").all():
        if row.question.question_type == QuestionBankItem.QuestionType.TEXT:
            subjective += float(row.manual_score or 0)
        else:
            objective += float(row.manual_score if row.manual_score is not None else row.auto_score)
    attempt.objective_score = objective
    attempt.subjective_score = subjective
    attempt.total_score = objective + subjective


@transaction.atomic
def _submit_attempt(attempt, *, source_override: str | None = "server"):
    if attempt.status != TestAttempt.Status.IN_PROGRESS:
        return attempt
    existing = {item.question_id: item for item in attempt.answer_rows.all()}
    has_subjective = False
    submitted_at = timezone.now()
    submitted_rows = []
    _ensure_attempt_randomization(attempt)
    eligible_ids = [int(item) for item in attempt.question_order]
    question_map = {
        item.id: item
        for item in attempt.assessment.questions.filter(id__in=eligible_ids)
    }
    for question_id in eligible_ids:
        question = question_map.get(question_id)
        if question is None:
            continue
        row = existing.get(question.id)
        if row is None:
            row = TestAttemptAnswer.objects.create(attempt=attempt, question=question, answer=[])
        auto_score, is_correct = _score_answer(question, row.answer)
        row.auto_score = auto_score
        row.is_correct = is_correct
        row.save(update_fields=["auto_score", "is_correct", "answered_at"])
        submitted_rows.append(row)
        has_subjective = has_subjective or question.question_type == QuestionBankItem.QuestionType.TEXT
    _recalculate_attempt(attempt)
    attempt.status = TestAttempt.Status.SUBMITTED if has_subjective else TestAttempt.Status.GRADED
    attempt.submitted_at = submitted_at
    attempt.graded_at = None if has_subjective else attempt.submitted_at
    attempt.save(update_fields=[
        "objective_score", "subjective_score", "total_score", "status", "submitted_at", "graded_at", "last_saved_at"
    ])
    try:
        for row in submitted_rows:
            record_assessment_item_submission(
                attempt=attempt,
                answer_row=row,
                occurred_at=submitted_at,
                source_override=source_override,
            )
            if row.question.question_type == QuestionBankItem.QuestionType.TEXT:
                record_assessment_item_grade(
                    attempt=attempt,
                    answer_row=row,
                    grading_state="pending",
                    score_raw=None,
                    grader_type="teacher",
                    actor=attempt.assessment.teacher,
                    occurred_at=submitted_at,
                    source_override="server",
                )
            else:
                record_assessment_item_grade(
                    attempt=attempt,
                    answer_row=row,
                    grading_state="final",
                    score_raw=row.auto_score,
                    grader_type="automatic",
                    actor=attempt.assessment.teacher,
                    occurred_at=submitted_at,
                    source_override="server",
                )
    except AssessmentEventError as exc:
        raise AssessmentError(exc.message) from exc
    return attempt


@api_view(["POST"])
@permission_classes([IsStudent])
def student_assessment_submit(request, pk):
    try:
        assessment, _ = _student_assessment(request.user, pk)
        attempt = TestAttempt.objects.filter(assessment=assessment, student=request.user).first()
        if attempt is None:
            raise AssessmentError("请先开始测试。")
        if attempt.status != TestAttempt.Status.IN_PROGRESS:
            return ok(_attempt_row(attempt), "测试已经提交。")
        _submit_attempt(attempt, source_override=None)
        result = _attempt_row(attempt)
        if not assessment.show_score_after_submit:
            result["objective_score"] = None
            result["subjective_score"] = None
            result["total_score"] = None
        return ok(result, "测试已提交。")
    except AssessmentError as exc:
        return _error(exc)
