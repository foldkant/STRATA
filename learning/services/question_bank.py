from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from learning.models import (
    QuestionBankItem,
    QuestionBankItemLifecycleRecord,
    QuestionBankItemVersion,
)


QUESTION_CONTENT_FIELDS = (
    "subject_id",
    "stem",
    "question_type",
    "options",
    "answer",
    "analysis",
    "difficulty",
    "knowledge_point",
    "default_score",
    "item_role",
    "layer_scope",
    "comparison_code",
)


def question_content_payload(question: QuestionBankItem) -> dict:
    return {
        "subject_id": question.subject_id,
        "stem": question.stem,
        "question_type": question.question_type,
        "options": question.options,
        "answer": question.answer,
        "analysis": question.analysis,
        "difficulty": question.difficulty,
        "knowledge_point": question.knowledge_point,
        "default_score": float(question.default_score),
        "item_role": question.item_role,
        "layer_scope": question.layer_scope,
        "comparison_code": question.comparison_code,
    }


def question_content_hash(question: QuestionBankItem) -> str:
    encoded = json.dumps(
        question_content_payload(question),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def ensure_question_version(
    question: QuestionBankItem,
    *,
    actor,
) -> QuestionBankItemVersion:
    content_hash = question_content_hash(question)
    existing = QuestionBankItemVersion.objects.filter(
        school=question.school,
        original_question_id=question.id,
        content_hash=content_hash,
    ).first()
    if existing is not None:
        if question.version_no != existing.version_no or question.content_hash != content_hash:
            QuestionBankItem.objects.filter(pk=question.pk).update(
                version_no=existing.version_no,
                content_hash=content_hash,
            )
            question.version_no = existing.version_no
            question.content_hash = content_hash
        return existing

    latest_version = (
        QuestionBankItemVersion.objects.filter(
            school=question.school,
            original_question_id=question.id,
        )
        .order_by("-version_no")
        .values_list("version_no", flat=True)
        .first()
        or 0
    )
    version_no = latest_version + 1
    version = QuestionBankItemVersion.objects.create(
        question=question,
        original_question_id=question.id,
        school=question.school,
        subject=question.subject,
        creator=question.creator,
        created_by=actor,
        version_no=version_no,
        content_hash=content_hash,
        source=question.source,
        status_snapshot=question.status,
        stem=question.stem,
        question_type=question.question_type,
        options=question.options,
        answer=question.answer,
        analysis=question.analysis,
        difficulty=question.difficulty,
        knowledge_point=question.knowledge_point,
        default_score=question.default_score,
        item_role=question.item_role,
        layer_scope=question.layer_scope,
        comparison_code=question.comparison_code,
    )
    QuestionBankItem.objects.filter(pk=question.pk).update(
        version_no=version_no,
        content_hash=content_hash,
    )
    question.version_no = version_no
    question.content_hash = content_hash
    return version


def record_question_lifecycle(
    question: QuestionBankItem,
    *,
    actor,
    from_status: str,
    to_status: str,
    action: str,
    note: str = "",
) -> QuestionBankItemLifecycleRecord:
    return QuestionBankItemLifecycleRecord.objects.create(
        question=question,
        original_question_id=question.id,
        school=question.school,
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        action=action,
        note=note,
    )


@transaction.atomic
def create_question_items(
    questions: list[QuestionBankItem],
    *,
    actor,
) -> list[QuestionBankItem]:
    for question in questions:
        question.version_no = 1
        question.content_hash = question_content_hash(question)
    created = QuestionBankItem.objects.bulk_create(questions)
    QuestionBankItemVersion.objects.bulk_create(
        [
            QuestionBankItemVersion(
                question=question,
                original_question_id=question.id,
                school=question.school,
                subject=question.subject,
                creator=question.creator,
                created_by=actor,
                version_no=1,
                content_hash=question.content_hash,
                source=question.source,
                status_snapshot=question.status,
                stem=question.stem,
                question_type=question.question_type,
                options=question.options,
                answer=question.answer,
                analysis=question.analysis,
                difficulty=question.difficulty,
                knowledge_point=question.knowledge_point,
                default_score=question.default_score,
                item_role=question.item_role,
                layer_scope=question.layer_scope,
                comparison_code=question.comparison_code,
            )
            for question in created
        ]
    )
    QuestionBankItemLifecycleRecord.objects.bulk_create(
        [
            QuestionBankItemLifecycleRecord(
                question=question,
                original_question_id=question.id,
                school=question.school,
                actor=actor,
                from_status="",
                to_status=question.status,
                action="create",
            )
            for question in created
        ]
    )
    return created


@transaction.atomic
def initialize_question(question: QuestionBankItem, *, actor) -> QuestionBankItemVersion:
    version = ensure_question_version(question, actor=actor)
    record_question_lifecycle(
        question,
        actor=actor,
        from_status="",
        to_status=question.status,
        action="create",
    )
    return version


@transaction.atomic
def transition_question(
    question: QuestionBankItem,
    *,
    actor,
    to_status: str,
    action: str,
    note: str = "",
    library_scope: str | None = None,
) -> QuestionBankItem:
    from_status = question.status
    now = timezone.now()
    question.status = to_status
    update_fields = ["status", "updated_at"]
    if library_scope is not None and question.library_scope != library_scope:
        question.library_scope = library_scope
        update_fields.append("library_scope")

    if to_status == QuestionBankItem.Status.PENDING_REVIEW:
        question.submitted_for_review_at = now
        question.review_note = ""
        update_fields.extend(["submitted_for_review_at", "review_note"])
    elif to_status == QuestionBankItem.Status.DRAFT:
        question.submitted_for_review_at = None
        if action == "return":
            question.reviewed_by = actor
            question.reviewed_at = now
            question.review_note = note
            update_fields.extend(["reviewed_by", "reviewed_at", "review_note"])
        update_fields.append("submitted_for_review_at")
    elif to_status in {QuestionBankItem.Status.TRIAL, QuestionBankItem.Status.ACTIVE}:
        question.reviewed_by = actor
        question.reviewed_at = now
        question.review_note = note
        update_fields.extend(["reviewed_by", "reviewed_at", "review_note"])
    elif to_status == QuestionBankItem.Status.DISABLED:
        question.disabled_by = actor
        question.disabled_at = now
        question.disabled_reason = note
        update_fields.extend(["disabled_by", "disabled_at", "disabled_reason"])

    question.save(update_fields=list(dict.fromkeys(update_fields)))
    record_question_lifecycle(
        question,
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        action=action,
        note=note,
    )
    return question
