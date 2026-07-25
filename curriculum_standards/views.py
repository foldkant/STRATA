from __future__ import annotations

import json
from pathlib import Path
import re
from functools import wraps

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.urls import reverse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission

from api.permissions import IsSuperAdmin
from api.responses import fail, ok

from .models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumPageQualityStatus,
    CurriculumPageReviewStatus,
    CurriculumProcessingJob,
    CurriculumProcessingJobStatus,
    CurriculumProcessingMode,
    CurriculumProcessingPriority,
    CurriculumRetrievalChunk,
    CurriculumRetrievalIndex,
    CurriculumRetrievalSourceKind,
    CurriculumStandard,
    CurriculumStandardAuditLog,
    CurriculumStandardNode,
    CurriculumStandardPage,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
)
from .serializers import (
    CurriculumNodeWriteSerializer,
    CurriculumProcessingJobCreateSerializer,
    CurriculumRetrievalIndexBuildSerializer,
    CurriculumRetrievalSearchSerializer,
    CurriculumStandardWriteSerializer,
    CurriculumVersionCreateSerializer,
    CurriculumVersionDraftUpdateSerializer,
)
from .retrieval import (
    SUPPORTED_RETRIEVAL_BACKENDS,
    rebuild_retrieval_index,
    retrieval_index_is_current,
    search_retrieval_chunks,
)
from .processing import (
    create_processing_job,
    dispatch_processing_job,
    processing_job_summary,
    reconcile_stale_processing_jobs,
    resume_processing_job,
    request_job_cancel,
    retry_processing_job,
)
from .services import (
    archive_version,
    compare_curriculum_versions,
    create_version,
    discard_draft_version,
    normalize_structured_text,
    publish_version,
    replace_version_structured_text,
    refresh_version_hash,
    restore_version,
    review_version,
    review_version_pages,
    submit_version_for_review,
    update_page_text,
)


class IsCurriculumStandardReader(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.role in {"super_admin", "school_admin", "teacher"}
            )
        )


def atomic_mutation(view_func):
    """Commit a mutation only when the whole API operation returns successfully."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.method not in {"POST", "PATCH", "PUT", "DELETE"}:
            return view_func(request, *args, **kwargs)
        with transaction.atomic():
            response = view_func(request, *args, **kwargs)
            if getattr(response, "status_code", 200) >= 400:
                transaction.set_rollback(True)
            return response

    return wrapped


def _errors(exc: DjangoValidationError) -> dict:
    if hasattr(exc, "message_dict"):
        return {
            key: [str(item) for item in values]
            for key, values in exc.message_dict.items()
        }
    return {"non_field_errors": [str(item) for item in exc.messages]}


def _actor_name(user) -> str:
    if user is None:
        return ""
    return user.display_name or user.username


def _pdf_url(request, version: CurriculumStandardVersion) -> str:
    path = reverse("api_curriculum_standard_pdf", kwargs={"pk": version.pk})
    return request.build_absolute_uri(path)


def _node_row(
    node: CurriculumStandardNode, *, trace: bool = False, request=None
) -> dict:
    row = {
        "id": node.id,
        "node_type": node.node_type,
        "node_type_label": node.get_node_type_display(),
        "code": node.code,
        "title": node.title,
        "content": node.content,
        "parent": node.parent_id,
        "source_page_start": node.source_page_start,
        "source_page_end": node.source_page_end,
        "source_paragraph": node.source_paragraph,
        "sort_order": node.sort_order,
        "content_hash": node.content_hash,
    }
    if trace:
        version = node.version
        # ``node.content`` is the governed, structured content-item text.  It
        # must not be presented as if it were the complete PDF source page.
        # Return the immutable page records separately so clients can display
        # and verify the actual extracted/OCR text for the cited page range.
        source_pages = list(
            version.pages.select_related("reviewed_by")
            .filter(
                page_number__gte=node.source_page_start,
                page_number__lte=node.source_page_end,
            )
            .order_by("page_number")
        )
        row["source_pages"] = [
            _page_row(page, include_text=True) for page in source_pages
        ]
        row["curriculum_standard"] = {
            "id": version.source_id,
            "title": version.official_title,
            "record_title": version.title_snapshot,
            "document_type": version.document_type_snapshot,
            "school_stage": version.school_stage_snapshot,
            "school_stage_label": version.get_school_stage_snapshot_display(),
            "subject_code": version.subject_code_snapshot,
            "subject_name": version.subject_name_snapshot,
        }
        row["curriculum_version"] = {
            "id": version.id,
            "version_label": version.version_label,
            "publication_year": version.publication_year,
            "issued_by": version.issued_by,
            "source_url": version.source_url,
            "status": version.status,
            "status_label": version.get_status_display(),
            "content_hash": version.content_hash,
            "pdf_sha256": version.pdf_sha256,
            "pdf_size_bytes": version.pdf_size_bytes,
            "pdf_url": _pdf_url(request, version) if request else "",
        }
    return row


def _page_row(page: CurriculumStandardPage, *, include_text: bool = True) -> dict:
    row = {
        "id": page.id,
        "page_number": page.page_number,
        "char_count": page.char_count,
        "extraction_method": page.extraction_method,
        "extraction_method_label": page.get_extraction_method_display(),
        "mean_confidence": (
            float(page.mean_confidence) if page.mean_confidence is not None else None
        ),
        "quality_status": page.quality_status,
        "quality_status_label": page.get_quality_status_display(),
        "quality_message": page.quality_message,
        "review_status": page.review_status,
        "review_status_label": page.get_review_status_display(),
        "reviewed_by": _actor_name(page.reviewed_by),
        "reviewed_at": page.reviewed_at,
        "content_hash": page.content_hash,
    }
    if include_text:
        row["text"] = page.text
    return row


def _retrieval_index_row(index: CurriculumRetrievalIndex) -> dict:
    return {
        "id": index.id,
        "version": index.version_id,
        "backend": index.backend,
        "strategy": index.strategy,
        "strategy_version": index.strategy_version,
        "max_chars": index.max_chars,
        "overlap_chars": index.overlap_chars,
        "chunk_count": index.chunk_count,
        "index_hash": index.index_hash,
        "version_content_hash": index.version_content_hash,
        "pdf_sha256": index.pdf_sha256,
        "built_by": _actor_name(index.built_by),
        "built_at": index.built_at,
        "is_current": retrieval_index_is_current(index.version, index=index),
    }


def _retrieval_chunk_row(
    request, chunk: CurriculumRetrievalChunk, *, score=None
) -> dict:
    version = chunk.version
    row = {
        "chunk_id": chunk.chunk_id,
        "score": score,
        "text": chunk.text,
        "ordinal": chunk.ordinal,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "char_count": chunk.char_count,
        "content_sha256": chunk.content_sha256,
        "source": {
            "kind": chunk.source_kind,
            "locator": chunk.source_locator,
            "object_id": chunk.source_object_id,
            "page_start": chunk.source_page_start,
            "page_end": chunk.source_page_end,
            "source_text_sha256": chunk.source_text_sha256,
            "source_content_hash": chunk.source_content_hash,
            "page_hashes": chunk.source_page_hashes,
            "content_item_code": (
                chunk.source_node.code if chunk.source_node_id else ""
            ),
            "content_item_title": (
                chunk.source_node.title if chunk.source_node_id else ""
            ),
            "content_item_type": (
                chunk.source_node.node_type if chunk.source_node_id else ""
            ),
        },
        "curriculum_standard": {
            "id": version.source_id,
            "title": version.title_snapshot,
            "school_stage": version.school_stage_snapshot,
            "subject_code": version.subject_code_snapshot,
            "subject_name": version.subject_name_snapshot,
        },
        "curriculum_version": {
            "id": version.id,
            "version_label": version.version_label,
            "status": version.status,
            "content_hash": chunk.version_content_hash,
            "pdf_sha256": chunk.pdf_sha256,
            "source_url": version.source_url,
            "pdf_url": _pdf_url(request, version),
            "pages_url": request.build_absolute_uri(
                reverse("api_curriculum_standard_pages", kwargs={"pk": version.id})
            ),
        },
    }
    if score is None:
        row.pop("score")
    return row


def _version_row(
    request,
    version: CurriculumStandardVersion,
    *,
    detail: bool = False,
    include_nodes: bool = False,
) -> dict:
    pages = getattr(version, "prefetched_page_summaries", None)
    if pages is None:
        pages = list(
            version.pages.only(
                "id",
                "version_id",
                "char_count",
                "quality_status",
                "review_status",
            ).all()
        )
    quality_counts = {
        value: sum(1 for page in pages if page.quality_status == value)
        for value in CurriculumPageQualityStatus.values
    }
    row = {
        "id": version.id,
        "standard": version.source_id,
        "version_label": version.version_label,
        "publication_year": version.publication_year,
        "effective_year": version.effective_year,
        "title": version.official_title,
        "record_title": version.title_snapshot,
        "document_type": version.document_type_snapshot,
        "document_type_label": version.get_document_type_snapshot_display(),
        "school_stage": version.school_stage_snapshot,
        "school_stage_label": version.get_school_stage_snapshot_display(),
        "subject_code": version.subject_code_snapshot,
        "subject_name": version.subject_name_snapshot,
        "issued_by": version.issued_by,
        "source_url": version.source_url,
        "source_note": version.source_note,
        "pdf_url": _pdf_url(request, version),
        "pdf_sha256": version.pdf_sha256,
        "pdf_size_bytes": version.pdf_size_bytes,
        "pdf_page_count": version.pdf_page_count,
        "structured_format": version.structured_format,
        "structured_text_sha256": version.structured_text_sha256,
        "extraction_status": version.extraction_status,
        "extraction_status_label": version.get_extraction_status_display(),
        "extraction_message": version.extraction_message,
        "extraction_engine": version.extraction_engine,
        "extraction_engine_version": version.extraction_engine_version,
        "extraction_config": version.extraction_config,
        "extracted_at": version.extracted_at,
        "content_hash": version.content_hash,
        "status": version.status,
        "status_label": version.get_status_display(),
        "independent_review": version.independent_review,
        "independent_publication": version.independent_publication,
        "governance_waiver_note": version.governance_waiver_note,
        "replaces_version": version.replaces_version_id,
        "node_count": len(version.nodes.all()),
        "page_count": len(pages),
        "text_char_count": sum(page.char_count for page in pages),
        "page_quality_counts": quality_counts,
        "unreviewed_page_count": sum(
            1
            for page in pages
            if page.review_status != CurriculumPageReviewStatus.REVIEWED
        ),
        "structured_markdown_url": request.build_absolute_uri(
            reverse("api_curriculum_standard_markdown", kwargs={"pk": version.pk})
        ),
        "structured_json_url": request.build_absolute_uri(
            reverse("api_curriculum_standard_json", kwargs={"pk": version.pk})
        ),
        "structured_jsonl_url": request.build_absolute_uri(
            reverse("api_curriculum_standard_jsonl", kwargs={"pk": version.pk})
        ),
        "created_by": _actor_name(version.created_by),
        "submitted_by": _actor_name(version.submitted_by),
        "reviewed_by": _actor_name(version.reviewed_by),
        "published_by": _actor_name(version.published_by),
        "archived_by": _actor_name(version.archived_by),
        "created_at": version.created_at,
        "submitted_at": version.submitted_at,
        "reviewed_at": version.reviewed_at,
        "published_at": version.published_at,
        "archived_at": version.archived_at,
    }
    if detail:
        row["structured_text"] = version.structured_text
        row["review_note"] = version.review_note
        row["audit_logs"] = [
            {
                "id": audit.id,
                "action": audit.action,
                "actor": _actor_name(audit.actor),
                "detail": audit.detail,
                "created_at": audit.created_at,
            }
            for audit in version.audit_logs.select_related("actor").all()
        ]
    if include_nodes:
        row["nodes"] = [_node_row(node) for node in version.nodes.all()]
    return row


def _standard_row(
    request, standard: CurriculumStandard, *, detail: bool = False
) -> dict:
    current = standard.current_version
    version_count = getattr(standard, "version_count", None)
    if version_count is None:
        version_count = len(standard.versions.all())
    row = {
        "id": standard.id,
        "title": standard.title,
        "document_type": standard.document_type,
        "document_type_label": standard.get_document_type_display(),
        "school_stage": standard.school_stage,
        "school_stage_label": standard.get_school_stage_display(),
        "subject_code": standard.subject_code,
        "subject_name": standard.subject_name,
        "is_active": standard.is_active,
        "current_version": (
            _version_row(request, current) if current else None
        ),
        "version_count": version_count,
        "created_at": standard.created_at,
        "updated_at": standard.updated_at,
    }
    if detail:
        row["versions"] = [
            _version_row(request, version) for version in standard.versions.all()
        ]
        row["audit_logs"] = [
            {
                "id": audit.id,
                "version": audit.version_id,
                "action": audit.action,
                "actor": _actor_name(audit.actor),
                "detail": audit.detail,
                "created_at": audit.created_at,
            }
            for audit in standard.audit_logs.select_related("actor").all()
        ]
    return row


def _version_summary_row(version: CurriculumStandardVersion | None) -> dict | None:
    """Return only the fields needed to render the standards directory."""
    if version is None:
        return None
    return {
        "id": version.id,
        "standard": version.source_id,
        "version_label": version.version_label,
        "publication_year": version.publication_year,
        "effective_year": version.effective_year,
        "title": version.official_title,
        "status": version.status,
        "status_label": version.get_status_display(),
        "content_hash": version.content_hash,
        "pdf_sha256": version.pdf_sha256,
        "extraction_status": version.extraction_status,
        "extraction_status_label": version.get_extraction_status_display(),
        "created_at": version.created_at,
        "published_at": version.published_at,
    }


def _standard_summary_row(standard: CurriculumStandard) -> dict:
    return {
        "id": standard.id,
        "title": standard.title,
        "document_type": standard.document_type,
        "document_type_label": standard.get_document_type_display(),
        "school_stage": standard.school_stage,
        "school_stage_label": standard.get_school_stage_display(),
        "subject_code": standard.subject_code,
        "subject_name": standard.subject_name,
        "is_active": standard.is_active,
        "current_version": _version_summary_row(standard.current_version),
        "version_count": standard.version_count,
        "created_at": standard.created_at,
        "updated_at": standard.updated_at,
    }


def _page_summaries_prefetch() -> Prefetch:
    return Prefetch(
        "pages",
        queryset=CurriculumStandardPage.objects.only(
            "id",
            "version_id",
            "char_count",
            "quality_status",
            "review_status",
        ),
        to_attr="prefetched_page_summaries",
    )


def _standards_queryset():
    page_summaries = CurriculumStandardPage.objects.only(
        "id",
        "version_id",
        "char_count",
        "quality_status",
        "review_status",
    )
    return CurriculumStandard.objects.select_related(
        "current_version"
    ).prefetch_related(
        "current_version__nodes",
        Prefetch(
            "current_version__pages",
            queryset=page_summaries,
            to_attr="prefetched_page_summaries",
        ),
        Prefetch(
            "versions",
            queryset=CurriculumStandardVersion.objects.select_related(
                "source",
                "created_by",
                "submitted_by",
                "reviewed_by",
                "published_by",
                "archived_by",
            )
            .defer("structured_text")
            .prefetch_related(
                "nodes",
                Prefetch(
                    "pages",
                    queryset=page_summaries,
                    to_attr="prefetched_page_summaries",
                ),
            ),
        ),
    )


def _reader_can_access_version(request, version: CurriculumStandardVersion) -> bool:
    return bool(
        request.user.is_platform_admin
        or version.status
        in {CurriculumVersionStatus.PUBLISHED, CurriculumVersionStatus.ARCHIVED}
    )


def _subject_name_aliases(value: str) -> set[str]:
    normalized = re.sub(r"\s+", "", str(value or ""))
    groups = (
        {"信息科技", "信息技术"},
        {"政治", "思想政治"},
        {"生物", "生物学"},
        {"体育", "体育与健康"},
        {"道德与法治", "思想品德"},
    )
    for group in groups:
        if normalized in group:
            return group
    return {normalized} if normalized else set()


@api_view(["GET", "POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_standards(request):
    if request.method == "GET":
        rows = (
            CurriculumStandard.objects.select_related("current_version")
            .annotate(version_count=Count("versions", distinct=True))
            .order_by("school_stage", "document_type", "subject_name", "title", "id")
        )
        query = str(request.query_params.get("q") or "").strip()
        stage = str(request.query_params.get("school_stage") or "").strip()
        document_type = str(request.query_params.get("document_type") or "").strip()
        subject_code = str(request.query_params.get("subject_code") or "").strip()
        if query:
            rows = rows.filter(
                Q(title__icontains=query)
                | Q(subject_name__icontains=query)
                | Q(subject_code__icontains=query)
            )
        if stage:
            rows = rows.filter(school_stage=stage)
        if document_type:
            rows = rows.filter(document_type=document_type)
        if subject_code:
            rows = rows.filter(subject_code=subject_code)
        try:
            page = max(1, int(request.query_params.get("page") or 1))
            page_size = min(
                50, max(1, int(request.query_params.get("page_size") or 8))
            )
        except (TypeError, ValueError):
            return fail(
                "分页条件不正确。",
                errors={"page": ["页码和每页数量必须是整数。"]},
                status=400,
            )
        summary = rows.aggregate(
            total=Count("id"),
            published=Count(
                "id",
                filter=Q(
                    is_active=True,
                    current_version__status=CurriculumVersionStatus.PUBLISHED,
                ),
            ),
            k1_k9=Count("id", filter=Q(school_stage="k1_k9")),
            k10_k12=Count("id", filter=Q(school_stage="k10_k12")),
        )
        total = int(summary["total"] or 0)
        page_count = max(1, (total + page_size - 1) // page_size)
        if page > page_count:
            page = page_count
        offset = (page - 1) * page_size
        page_rows = list(rows[offset : offset + page_size])
        return ok(
            {
                "standards": [_standard_summary_row(item) for item in page_rows],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "page_count": page_count,
                    "total": total,
                },
                "summary": summary,
                "school_stages": [
                    {"value": value, "label": label}
                    for value, label in CurriculumStandard._meta.get_field(
                        "school_stage"
                    ).choices
                ],
                "document_types": [
                    {"value": value, "label": label}
                    for value, label in CurriculumDocumentType.choices
                ],
                "version_statuses": [
                    {"value": value, "label": label}
                    for value, label in CurriculumVersionStatus.choices
                ],
                "node_types": [
                    {"value": value, "label": label}
                    for value, label in CurriculumNodeType.choices
                ],
            }
        )

    serializer = CurriculumStandardWriteSerializer(
        data=request.data,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("课程标准档案未创建。", errors=serializer.errors, status=400)
    try:
        with transaction.atomic():
            standard = serializer.save()
            CurriculumStandardAuditLog.objects.create(
                standard=standard,
                action="standard_created",
                actor=request.user,
                detail={
                    "school_stage": standard.school_stage,
                    "document_type": standard.document_type,
                    "subject_code": standard.subject_code,
                },
            )
    except (DjangoValidationError, IntegrityError) as exc:
        errors = (
            _errors(exc)
            if isinstance(exc, DjangoValidationError)
            else {"non_field_errors": ["相同学段、文档类型和学科代码的档案已经存在。"]}
        )
        return fail("课程标准档案未创建。", errors=errors, status=409)
    standard = _standards_queryset().get(pk=standard.pk)
    return ok(
        _standard_row(request, standard, detail=True),
        "课程标准档案已创建。",
        status=201,
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_standard_detail(request, pk: int):
    standard = _standards_queryset().filter(pk=pk).first()
    if standard is None:
        return fail("课程标准档案不存在。", status=404)
    if request.method == "GET":
        return ok(_standard_row(request, standard, detail=True))
    serializer = CurriculumStandardWriteSerializer(
        standard,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    if not serializer.is_valid():
        return fail("课程标准档案未保存。", errors=serializer.errors, status=400)
    before = {
        "title": standard.title,
        "subject_name": standard.subject_name,
        "is_active": standard.is_active,
    }
    try:
        with transaction.atomic():
            standard = serializer.save()
            CurriculumStandardAuditLog.objects.create(
                standard=standard,
                action="standard_updated",
                actor=request.user,
                detail={
                    "before": before,
                    "after": {
                        "title": standard.title,
                        "subject_name": standard.subject_name,
                        "is_active": standard.is_active,
                    },
                },
            )
    except (DjangoValidationError, IntegrityError) as exc:
        errors = (
            _errors(exc)
            if isinstance(exc, DjangoValidationError)
            else {"non_field_errors": ["课程标准档案与现有记录重复。"]}
        )
        return fail("课程标准档案未保存。", errors=errors, status=409)
    standard = _standards_queryset().get(pk=standard.pk)
    return ok(_standard_row(request, standard, detail=True), "课程标准档案已保存。")


@api_view(["GET", "POST"])
@permission_classes([IsSuperAdmin])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@atomic_mutation
def super_admin_standard_versions(request, pk: int):
    standard = CurriculumStandard.objects.filter(pk=pk).first()
    if standard is None:
        return fail("课程标准档案不存在。", status=404)
    if request.method == "GET":
        versions = (
            standard.versions.select_related(
                "source",
                "created_by",
                "submitted_by",
                "reviewed_by",
                "published_by",
                "archived_by",
            )
            .prefetch_related("nodes", _page_summaries_prefetch())
            .all()
        )
        return ok([_version_row(request, item) for item in versions])

    serializer = CurriculumVersionCreateSerializer(
        data=request.data,
        context={"standard": standard},
    )
    if not serializer.is_valid():
        return fail("课程标准版本未创建。", errors=serializer.errors, status=400)
    try:
        version = create_version(
            standard=standard,
            actor=request.user,
            **serializer.validated_data,
        )
    except DjangoValidationError as exc:
        return fail("课程标准版本未创建。", errors=_errors(exc), status=400)
    except IntegrityError:
        return fail(
            "课程标准版本未创建。",
            errors={"version_label": ["相同版本标识或相同内容已经存在。"]},
            status=409,
        )
    version = (
        CurriculumStandardVersion.objects.select_related(
            "source",
            "created_by",
            "submitted_by",
            "reviewed_by",
            "published_by",
            "archived_by",
        )
        .prefetch_related(
            "nodes",
            _page_summaries_prefetch(),
            "audit_logs__actor",
        )
        .get(pk=version.pk)
    )
    return ok(
        _version_row(request, version, detail=True, include_nodes=True),
        "课程标准版本已创建。",
        status=201,
    )


def _version_for_admin(pk: int):
    return (
        CurriculumStandardVersion.objects.select_related(
            "source",
            "created_by",
            "submitted_by",
            "reviewed_by",
            "published_by",
            "archived_by",
        )
        .prefetch_related(
            "nodes",
            _page_summaries_prefetch(),
            "audit_logs__actor",
        )
        .filter(pk=pk)
        .first()
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSuperAdmin])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@atomic_mutation
def super_admin_version_detail(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    if request.method == "GET":
        return ok(_version_row(request, version, detail=True, include_nodes=True))
    if request.method == "DELETE":
        if version.status != CurriculumVersionStatus.DRAFT:
            return fail("已进入复核流程的课程标准版本不能删除。", status=409)
        try:
            discard_draft_version(version, actor=request.user)
        except DjangoValidationError as exc:
            return fail("课程标准草稿版本未删除。", errors=_errors(exc), status=409)
        return ok(message="课程标准草稿版本已丢弃，文件和审计记录已保留。")
    if version.status != CurriculumVersionStatus.DRAFT:
        return fail("只有草稿版本可以修改；已发布内容请建立替换版本。", status=409)
    serializer = CurriculumVersionDraftUpdateSerializer(
        data=request.data,
        partial=True,
        context={"version": version},
    )
    if not serializer.is_valid():
        return fail("课程标准版本未保存。", errors=serializer.errors, status=400)
    values = serializer.validated_data
    before_version_hash = version.content_hash
    if "structured_text" in values:
        text = normalize_structured_text(values.pop("structured_text"))
        try:
            version = replace_version_structured_text(
                version,
                structured_text=text,
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return fail("结构化文本未保存。", errors=_errors(exc), status=409)
    for field_name, value in values.items():
        setattr(version, field_name, value)
    try:
        version.save()
        refresh_version_hash(version)
    except (DjangoValidationError, IntegrityError) as exc:
        errors = (
            _errors(exc)
            if isinstance(exc, DjangoValidationError)
            else {"non_field_errors": ["相同版本标识或相同内容已经存在。"]}
        )
        return fail("课程标准版本未保存。", errors=errors, status=409)
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="draft_metadata_updated",
        actor=request.user,
        detail={
            "before_hash": before_version_hash,
            "after_hash": version.content_hash,
            "updated_fields": sorted(values.keys()),
        },
    )
    version = _version_for_admin(version.pk)
    return ok(
        _version_row(request, version, detail=True, include_nodes=True),
        "课程标准版本已保存。",
    )


@api_view(["GET", "POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_version_nodes(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    if request.method == "GET":
        return ok([_node_row(node) for node in version.nodes.all()])
    if version.status != CurriculumVersionStatus.DRAFT:
        return fail("只有草稿版本可以新增课程标准内容条目。", status=409)
    serializer = CurriculumNodeWriteSerializer(
        data=request.data,
        context={"version": version},
    )
    if not serializer.is_valid():
        return fail("课程标准内容条目未创建。", errors=serializer.errors, status=400)
    try:
        before_hash = version.content_hash
        node = serializer.save()
        refresh_version_hash(version)
    except (DjangoValidationError, IntegrityError) as exc:
        errors = (
            _errors(exc)
            if isinstance(exc, DjangoValidationError)
            else {"code": ["同一版本内的条目代码不能重复。"]}
        )
        return fail("课程标准内容条目未创建。", errors=errors, status=409)
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="content_item_created",
        actor=request.user,
        detail={
            "content_item_id": node.id,
            "code": node.code,
            "before_hash": before_hash,
            "after_hash": version.content_hash,
        },
    )
    return ok(_node_row(node), "课程标准内容条目已创建。", status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_node_detail(request, pk: int):
    node = (
        CurriculumStandardNode.objects.select_related("version").filter(pk=pk).first()
    )
    if node is None:
        return fail("课程标准内容条目不存在。", status=404)
    if node.version.status != CurriculumVersionStatus.DRAFT:
        return fail("已提交复核的课程标准内容条目不可修改或删除。", status=409)
    version = node.version
    if request.method == "DELETE":
        item_detail = {
            "content_item_id": node.id,
            "code": node.code,
            "content_hash": node.content_hash,
            "before_hash": version.content_hash,
        }
        node.delete()
        refresh_version_hash(version)
        item_detail["after_hash"] = version.content_hash
        CurriculumStandardAuditLog.objects.create(
            version=version,
            action="content_item_deleted",
            actor=request.user,
            detail=item_detail,
        )
        return ok(message="课程标准内容条目已删除。")
    serializer = CurriculumNodeWriteSerializer(
        node,
        data=request.data,
        partial=True,
        context={"version": version},
    )
    if not serializer.is_valid():
        return fail("课程标准内容条目未保存。", errors=serializer.errors, status=400)
    try:
        before_item_hash = node.content_hash
        before_version_hash = version.content_hash
        node = serializer.save()
        refresh_version_hash(version)
    except (DjangoValidationError, IntegrityError) as exc:
        errors = (
            _errors(exc)
            if isinstance(exc, DjangoValidationError)
            else {"code": ["同一版本内的条目代码不能重复。"]}
        )
        return fail("课程标准内容条目未保存。", errors=errors, status=409)
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="content_item_updated",
        actor=request.user,
        detail={
            "content_item_id": node.id,
            "code": node.code,
            "before_item_hash": before_item_hash,
            "after_item_hash": node.content_hash,
            "before_version_hash": before_version_hash,
            "after_version_hash": version.content_hash,
        },
    )
    return ok(_node_row(node), "课程标准内容条目已保存。")


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_version_pages(request, pk: int):
    version = _version_for_admin(pk)
    if version is None or not _reader_can_access_version(request, version):
        return fail("课程标准版本不存在。", status=404)
    pages = version.pages.select_related("reviewed_by").all()
    query = str(request.query_params.get("q") or "").strip()
    quality_status = str(request.query_params.get("quality_status") or "").strip()
    review_status = str(request.query_params.get("review_status") or "").strip()
    if query:
        pages = pages.filter(text__icontains=query)
    if quality_status in CurriculumPageQualityStatus.values:
        pages = pages.filter(quality_status=quality_status)
    if review_status in CurriculumPageReviewStatus.values:
        pages = pages.filter(review_status=review_status)
    return ok(
        {
            "version": {
                "id": version.id,
                "title": version.title_snapshot,
                "version_label": version.version_label,
                "content_hash": version.content_hash,
            },
            "pages": [_page_row(page) for page in pages],
        }
    )


@api_view(["PATCH"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_page_detail(request, pk: int):
    page = (
        CurriculumStandardPage.objects.select_related("version").filter(pk=pk).first()
    )
    if page is None:
        return fail("课程标准逐页文本不存在。", status=404)
    if "text" not in request.data:
        return fail(
            "逐页文本未保存。",
            errors={"text": ["请提交修订后的页级文本。"]},
            status=400,
        )
    try:
        page = update_page_text(
            page,
            text=str(request.data.get("text") or ""),
            actor=request.user,
        )
    except DjangoValidationError as exc:
        return fail("逐页文本未保存。", errors=_errors(exc), status=409)
    page = CurriculumStandardPage.objects.select_related("reviewed_by").get(pk=page.pk)
    return ok(_page_row(page), "逐页文本已保存，发布前需重新复核。")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_version_pages_review(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    raw_page_ids = request.data.get("page_ids")
    if raw_page_ids is not None and not isinstance(raw_page_ids, list):
        return fail(
            "逐页文本复核结果未保存。",
            errors={"page_ids": ["页记录编号必须是列表；不传表示确认全部页面。"]},
            status=400,
        )
    try:
        count = review_version_pages(
            version,
            actor=request.user,
            page_ids=raw_page_ids,
        )
    except (DjangoValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, DjangoValidationError):
            errors = _errors(exc)
        else:
            errors = {"page_ids": ["页记录编号必须是整数。"]}
        return fail("逐页文本复核结果未保存。", errors=errors, status=400)
    version = _version_for_admin(version.pk)
    return ok(
        {
            "reviewed_page_count": count,
            "version": _version_row(
                request,
                version,
                detail=True,
                include_nodes=True,
            ),
        },
        "逐页文本复核结果已保存。",
    )


def _workflow_response(request, version, message: str):
    version = _version_for_admin(version.pk)
    return ok(_version_row(request, version, detail=True, include_nodes=True), message)


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_version_submit_review(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    try:
        version = submit_version_for_review(version, actor=request.user)
    except DjangoValidationError as exc:
        return fail("课程标准版本未提交复核。", errors=_errors(exc), status=400)
    return _workflow_response(request, version, "课程标准版本已提交复核。")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_version_review(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    approved = request.data.get("approved") is True or str(
        request.data.get("approved")
    ).lower() in {"1", "true", "yes"}
    note = str(request.data.get("note") or "").strip()
    try:
        version = review_version(
            version,
            actor=request.user,
            approved=approved,
            note=note,
        )
    except DjangoValidationError as exc:
        return fail("课程标准复核结果未保存。", errors=_errors(exc), status=400)
    message = "课程标准版本已通过复核。" if approved else "课程标准版本已退回修改。"
    return _workflow_response(request, version, message)


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_version_publish(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    try:
        version = publish_version(version, actor=request.user)
    except DjangoValidationError as exc:
        return fail("课程标准版本未发布。", errors=_errors(exc), status=400)
    return _workflow_response(request, version, "课程标准版本已发布并设为当前版本。")


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_version_archive(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    try:
        version = archive_version(version, actor=request.user)
    except DjangoValidationError as exc:
        return fail("课程标准版本未归档。", errors=_errors(exc), status=400)
    return _workflow_response(
        request, version, "课程标准版本已归档，历史引用保持不变。"
    )


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_version_restore(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    try:
        version = restore_version(version, actor=request.user)
    except DjangoValidationError as exc:
        return fail("课程标准版本未恢复。", errors=_errors(exc), status=400)
    return _workflow_response(request, version, "课程标准历史版本已恢复为当前版本。")


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def reference_options(request):
    rows = _standards_queryset().filter(
        is_active=True,
        document_type=CurriculumDocumentType.SUBJECT_STANDARD,
        current_version__status=CurriculumVersionStatus.PUBLISHED,
    )
    stage = str(request.query_params.get("school_stage") or "").strip()
    subject_code = str(request.query_params.get("subject_code") or "").strip()
    subject_name = str(request.query_params.get("subject_name") or "").strip()
    node_type = str(request.query_params.get("node_type") or "").strip()
    include_history = str(
        request.query_params.get("include_history") or ""
    ).lower() in {
        "1",
        "true",
        "yes",
    }
    if stage:
        rows = rows.filter(school_stage=stage)
    identity_filter = Q()
    if subject_code:
        identity_filter |= Q(subject_code=subject_code)
    aliases = _subject_name_aliases(subject_name)
    if aliases:
        identity_filter |= Q(subject_name__in=aliases)
    if subject_code or aliases:
        rows = rows.filter(identity_filter)
    result = []
    for standard in rows:
        item = _standard_row(request, standard)
        if node_type and item["current_version"]:
            item["current_version"]["nodes"] = [
                node
                for node in item["current_version"]["nodes"]
                if node["node_type"] == node_type
            ]
        if include_history:
            historical = [
                version
                for version in standard.versions.all()
                if version.status
                in {CurriculumVersionStatus.PUBLISHED, CurriculumVersionStatus.ARCHIVED}
            ]
            item["versions"] = [
                _version_row(request, version, include_nodes=True)
                for version in historical
            ]
        result.append(item)
    return ok({"standards": result})


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_node_trace(request, pk: int):
    node = (
        CurriculumStandardNode.objects.select_related("version__source", "parent")
        .filter(pk=pk)
        .first()
    )
    if node is None:
        return fail("课程标准内容条目不存在。", status=404)
    if (
        node.version.status
        not in {
            CurriculumVersionStatus.PUBLISHED,
            CurriculumVersionStatus.ARCHIVED,
        }
        and not request.user.is_platform_admin
    ):
        return fail("课程标准内容条目不存在。", status=404)
    return ok(_node_row(node, trace=True, request=request))


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_standard_pdf(request, pk: int):
    version = (
        CurriculumStandardVersion.objects.select_related("source").filter(pk=pk).first()
    )
    if version is None or not version.pdf_file:
        return fail("课程标准 PDF 不存在。", status=404)
    if (
        version.status
        not in {
            CurriculumVersionStatus.PUBLISHED,
            CurriculumVersionStatus.ARCHIVED,
        }
        and not request.user.is_platform_admin
    ):
        return fail("课程标准 PDF 不存在。", status=404)
    response = FileResponse(
        version.pdf_file.open("rb"),
        content_type="application/pdf",
        as_attachment=False,
        filename=Path(version.pdf_file.name).name,
    )
    response["ETag"] = f'"{version.pdf_sha256}"'
    response["Cache-Control"] = "private, max-age=3600"
    return response


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_standard_markdown(request, pk: int):
    version = (
        CurriculumStandardVersion.objects.select_related("source")
        .prefetch_related("nodes__parent")
        .filter(pk=pk)
        .first()
    )
    if version is None or not _reader_can_access_version(request, version):
        return fail("课程标准版本不存在。", status=404)
    header = (
        f"---\n"
        f"title: {json.dumps(version.official_title, ensure_ascii=False)}\n"
        f"version: {json.dumps(version.version_label, ensure_ascii=False)}\n"
        f"publication_year: {version.publication_year}\n"
        f"school_stage: {version.school_stage_snapshot}\n"
        f"subject_code: {version.subject_code_snapshot}\n"
        f"source_url: {json.dumps(version.source_url, ensure_ascii=False)}\n"
        f"pdf_sha256: {version.pdf_sha256}\n"
        f"pdf_size_bytes: {version.pdf_size_bytes}\n"
        f"structured_text_sha256: {version.structured_text_sha256}\n"
        f"extraction_engine: {json.dumps(version.extraction_engine, ensure_ascii=False)}\n"
        f"extraction_engine_version: {json.dumps(version.extraction_engine_version, ensure_ascii=False)}\n"
        f"extraction_config: {json.dumps(version.extraction_config, ensure_ascii=False, sort_keys=True)}\n"
        f"extracted_at: {json.dumps(version.extracted_at.isoformat() if version.extracted_at else None)}\n"
        f"content_hash: {version.content_hash}\n"
        f"content_item_count: {version.nodes.count()}\n"
        f"---\n\n"
    )
    content_items = ""
    if version.nodes.exists():
        sections = ["\n\n# 课程标准结构化内容条目\n"]
        for node in version.nodes.all():
            sections.append(
                f"\n## {node.get_node_type_display()}：{node.title}\n\n"
                f"- 条目代码：`{node.code}`\n"
                f"- 原文位置：PDF 第 {node.source_page_start}—{node.source_page_end} 页，"
                f"{node.source_paragraph}\n"
                f"- 内容校验码：`{node.content_hash}`\n\n"
                f"{node.content}\n"
            )
        content_items = "".join(sections)
    response = HttpResponse(
        header + version.structured_text + content_items,
        content_type="text/markdown; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="curriculum-standard-{version.id}.md"'
    )
    response["ETag"] = f'"{version.content_hash}"'
    return response


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_standard_json(request, pk: int):
    """Download one self-contained, source-traceable JSON document.

    JSONL remains available for streaming/indexing workflows.  This endpoint
    gives administrators and downstream AI preparation jobs a regular JSON
    object with explicit collections and the same immutable source anchors.
    """

    version = (
        CurriculumStandardVersion.objects.select_related("source")
        .prefetch_related("nodes__parent", "pages__reviewed_by")
        .filter(pk=pk)
        .first()
    )
    if version is None or not _reader_can_access_version(request, version):
        return fail("课程标准版本不存在。", status=404)

    pages = list(version.pages.order_by("page_number"))
    content_items = list(version.nodes.all())
    retrieval = None
    if retrieval_index_is_current(version):
        index = CurriculumRetrievalIndex.objects.select_related(
            "version__source",
            "built_by",
        ).get(version=version)
        chunks = index.chunks.select_related("version__source", "source_node").all()
        retrieval = {
            "index": _retrieval_index_row(index),
            "chunks": [_retrieval_chunk_row(request, chunk) for chunk in chunks],
        }

    payload = {
        "schema": "curriculum_standard_export_v1",
        "standard": {
            "id": version.source_id,
            "title": version.title_snapshot,
            "document_type": version.document_type_snapshot,
            "school_stage": version.school_stage_snapshot,
            "subject_code": version.subject_code_snapshot,
            "subject_name": version.subject_name_snapshot,
        },
        "version": {
            "id": version.id,
            "official_title": version.official_title,
            "version_label": version.version_label,
            "publication_year": version.publication_year,
            "effective_year": version.effective_year,
            "issued_by": version.issued_by,
            "status": version.status,
            "source_url": version.source_url,
            "source_note": version.source_note,
            "pdf_sha256": version.pdf_sha256,
            "pdf_size_bytes": version.pdf_size_bytes,
            "pdf_page_count": version.pdf_page_count,
            "structured_text_sha256": version.structured_text_sha256,
            "content_hash": version.content_hash,
            "extraction_engine": version.extraction_engine,
            "extraction_engine_version": version.extraction_engine_version,
            "extraction_config": version.extraction_config,
            "extracted_at": version.extracted_at,
        },
        "structured_text": version.structured_text,
        "pages": [_page_row(page, include_text=True) for page in pages],
        "content_items": [_node_row(node) for node in content_items],
        "retrieval": retrieval,
    }
    response = JsonResponse(
        payload,
        json_dumps_params={"ensure_ascii": False, "separators": (",", ":")},
    )
    response["Content-Disposition"] = (
        f'attachment; filename="curriculum-standard-{version.id}.json"'
    )
    response["ETag"] = f'"{version.content_hash}"'
    return response


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_standard_jsonl(request, pk: int):
    version = (
        CurriculumStandardVersion.objects.select_related("source")
        .prefetch_related("nodes__parent", "pages")
        .filter(pk=pk)
        .first()
    )
    if version is None or not _reader_can_access_version(request, version):
        return fail("课程标准版本不存在。", status=404)
    lines = [
        json.dumps(
            {
                "record_type": "metadata",
                "standard_id": version.source_id,
                "version_id": version.id,
                "title": version.official_title,
                "version_label": version.version_label,
                "school_stage": version.school_stage_snapshot,
                "subject_code": version.subject_code_snapshot,
                "subject_name": version.subject_name_snapshot,
                "source_url": version.source_url,
                "source_note": version.source_note,
                "pdf_sha256": version.pdf_sha256,
                "pdf_size_bytes": version.pdf_size_bytes,
                "structured_text_sha256": version.structured_text_sha256,
                "extraction_engine": version.extraction_engine,
                "extraction_engine_version": version.extraction_engine_version,
                "extraction_config": version.extraction_config,
                "extracted_at": (
                    version.extracted_at.isoformat() if version.extracted_at else None
                ),
                "content_hash": version.content_hash,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    ]
    for page in version.pages.order_by("page_number"):
        lines.append(
            json.dumps(
                {
                    "record_type": "page",
                    "standard_id": version.source_id,
                    "version_id": version.id,
                    "version_label": version.version_label,
                    "content_hash": version.content_hash,
                    "page_number": page.page_number,
                    "text": page.text,
                    "char_count": page.char_count,
                    "extraction_method": page.extraction_method,
                    "mean_confidence": (
                        float(page.mean_confidence)
                        if page.mean_confidence is not None
                        else None
                    ),
                    "quality_status": page.quality_status,
                    "review_status": page.review_status,
                    "page_content_hash": page.content_hash,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    for node in version.nodes.all():
        lines.append(
            json.dumps(
                {
                    "record_type": "content_item",
                    "standard_id": version.source_id,
                    "version_id": version.id,
                    "version_label": version.version_label,
                    "version_content_hash": version.content_hash,
                    "pdf_sha256": version.pdf_sha256,
                    "node_type": node.node_type,
                    "node_type_label": node.get_node_type_display(),
                    "code": node.code,
                    "title": node.title,
                    "content": node.content,
                    "parent_code": node.parent.code if node.parent_id else None,
                    "source_page_start": node.source_page_start,
                    "source_page_end": node.source_page_end,
                    "source_paragraph": node.source_paragraph,
                    "content_hash": node.content_hash,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    if retrieval_index_is_current(version):
        index = CurriculumRetrievalIndex.objects.get(version=version)
        lines.append(
            json.dumps(
                {
                    "record_type": "retrieval_index",
                    "standard_id": version.source_id,
                    "version_id": version.id,
                    "version_label": version.version_label,
                    "version_content_hash": version.content_hash,
                    "pdf_sha256": version.pdf_sha256,
                    "backend": index.backend,
                    "strategy": index.strategy,
                    "strategy_version": index.strategy_version,
                    "max_chars": index.max_chars,
                    "overlap_chars": index.overlap_chars,
                    "chunk_count": index.chunk_count,
                    "index_hash": index.index_hash,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        for chunk in index.chunks.select_related("source_node").all():
            lines.append(
                json.dumps(
                    {
                        "record_type": "retrieval_chunk",
                        "standard_id": version.source_id,
                        "version_id": version.id,
                        "version_label": version.version_label,
                        "version_content_hash": chunk.version_content_hash,
                        "pdf_sha256": chunk.pdf_sha256,
                        "chunk_id": chunk.chunk_id,
                        "source_kind": chunk.source_kind,
                        "source_locator": chunk.source_locator,
                        "source_object_id": chunk.source_object_id,
                        "source_page_start": chunk.source_page_start,
                        "source_page_end": chunk.source_page_end,
                        "source_page_hashes": chunk.source_page_hashes,
                        "source_text_sha256": chunk.source_text_sha256,
                        "source_content_hash": chunk.source_content_hash,
                        "content_item_code": (
                            chunk.source_node.code if chunk.source_node_id else ""
                        ),
                        "ordinal": chunk.ordinal,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "content_sha256": chunk.content_sha256,
                        "text": chunk.text,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
    response = HttpResponse(
        "\n".join(lines) + ("\n" if lines else ""),
        content_type="application/x-ndjson; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="curriculum-standard-{version.id}.jsonl"'
    )
    response["ETag"] = f'"{version.content_hash}"'
    return response


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_standard_compare(request):
    try:
        from_id = int(request.query_params.get("from_id"))
        to_id = int(request.query_params.get("to_id"))
    except (TypeError, ValueError):
        return fail(
            "课程标准版本比较参数不正确。",
            errors={"version_ids": ["请提交 from_id 和 to_id。"]},
            status=400,
        )
    versions = {
        version.id: version
        for version in CurriculumStandardVersion.objects.select_related("source")
        .prefetch_related("nodes")
        .filter(pk__in={from_id, to_id})
    }
    if len(versions) != len({from_id, to_id}):
        return fail("课程标准版本不存在。", status=404)
    left = versions[from_id]
    right = versions[to_id]
    if not _reader_can_access_version(request, left) or not _reader_can_access_version(
        request, right
    ):
        return fail("课程标准版本不存在。", status=404)
    try:
        result = compare_curriculum_versions(left, right)
    except DjangoValidationError as exc:
        return fail("课程标准版本无法比较。", errors=_errors(exc), status=400)
    return ok(result)


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
@atomic_mutation
def super_admin_rebuild_retrieval_index(request, pk: int):
    version = _version_for_admin(pk)
    if version is None:
        return fail("课程标准版本不存在。", status=404)
    serializer = CurriculumRetrievalIndexBuildSerializer(data=request.data)
    if not serializer.is_valid():
        return fail("课程标准检索索引未建立。", errors=serializer.errors, status=400)
    try:
        index, rebuilt = rebuild_retrieval_index(
            version,
            actor=request.user,
            **serializer.validated_data,
        )
    except DjangoValidationError as exc:
        return fail("课程标准检索索引未建立。", errors=_errors(exc), status=409)
    if rebuilt:
        CurriculumStandardAuditLog.objects.create(
            version=version,
            action="retrieval_index_rebuilt",
            actor=request.user,
            detail={
                "index_hash": index.index_hash,
                "chunk_count": index.chunk_count,
                "backend": index.backend,
                "strategy": index.strategy,
                "strategy_version": index.strategy_version,
                "max_chars": index.max_chars,
                "overlap_chars": index.overlap_chars,
            },
        )
    index = CurriculumRetrievalIndex.objects.select_related(
        "version",
        "built_by",
    ).get(pk=index.pk)
    return ok(
        _retrieval_index_row(index),
        "课程标准检索索引已重建。" if rebuilt else "课程标准检索索引已经是最新版本。",
    )


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_retrieval_chunks(request, pk: int):
    version = (
        CurriculumStandardVersion.objects.select_related("source").filter(pk=pk).first()
    )
    if version is None or not _reader_can_access_version(request, version):
        return fail("课程标准版本不存在。", status=404)
    index = (
        CurriculumRetrievalIndex.objects.select_related(
            "version",
            "built_by",
        )
        .filter(version=version)
        .first()
    )
    if index is None or not retrieval_index_is_current(version, index=index):
        return fail(
            "课程标准检索索引尚未建立或已经过期。",
            errors={"retrieval_index": ["请由超级管理员重建该版本的检索索引。"]},
            status=409,
        )
    try:
        offset = max(int(request.query_params.get("offset", 0)), 0)
        limit = min(max(int(request.query_params.get("limit", 50)), 1), 200)
    except (TypeError, ValueError):
        return fail(
            "检索片段分页参数不正确。",
            errors={"pagination": ["offset 和 limit 必须为整数。"]},
            status=400,
        )
    source_kind = str(request.query_params.get("source_kind") or "").strip()
    if source_kind and source_kind not in CurriculumRetrievalSourceKind.values:
        return fail(
            "检索片段来源类型不正确。",
            errors={"source_kind": ["请选择已登记的来源类型。"]},
            status=400,
        )
    rows = index.chunks.select_related(
        "version__source",
        "source_page",
        "source_node",
    )
    if source_kind:
        rows = rows.filter(source_kind=source_kind)
    total = rows.count()
    page = list(rows[offset : offset + limit])
    return ok(
        {
            "index": _retrieval_index_row(index),
            "count": total,
            "offset": offset,
            "limit": limit,
            "chunks": [_retrieval_chunk_row(request, chunk) for chunk in page],
        }
    )


@api_view(["GET"])
@permission_classes([IsCurriculumStandardReader])
def curriculum_retrieval_search(request):
    serializer = CurriculumRetrievalSearchSerializer(data=request.query_params)
    if not serializer.is_valid():
        return fail("课程标准检索参数不正确。", errors=serializer.errors, status=400)
    values = serializer.validated_data
    is_platform_admin = bool(
        request.user.is_superuser or request.user.role == "super_admin"
    )
    if values.get("include_unpublished") and not is_platform_admin:
        return fail("只有超级管理员可以检索未发布课程标准。", status=403)
    try:
        results = search_retrieval_chunks(
            query=values["q"],
            version_id=values.get("version_id"),
            school_stage=values.get("school_stage", ""),
            subject_code=values.get("subject_code", ""),
            source_kind=values.get("source_kind", ""),
            include_history=values.get("include_history", False),
            include_unpublished=values.get("include_unpublished", False),
            backend=values.get("backend", "keyword_v1"),
            limit=values.get("limit", 20),
        )
    except DjangoValidationError as exc:
        return fail("课程标准检索未执行。", errors=_errors(exc), status=400)
    return ok(
        {
            "query": values["q"],
            "backend": values.get("backend", "keyword_v1"),
            "available_backends": list(SUPPORTED_RETRIEVAL_BACKENDS),
            "version_scope": (
                values.get("version_id")
                or (
                    "published_history"
                    if values.get("include_history")
                    else "current_published"
                )
            ),
            "result_count": len(results),
            "results": [
                _retrieval_chunk_row(request, chunk, score=score)
                for chunk, score in results
            ],
        }
    )


def _processing_job_queryset():
    return CurriculumProcessingJob.objects.select_related(
        "version__source",
        "requested_by",
        "cancel_requested_by",
        "retry_of",
    )


def _processing_job_row(job: CurriculumProcessingJob) -> dict:
    total = int(job.progress_total or 0)
    current = int(job.progress_current or 0)
    progress_percent = round(min(current / total * 100, 100), 1) if total else 0.0
    if job.status == CurriculumProcessingJobStatus.SUCCEEDED:
        progress_percent = 100.0
    return {
        "id": job.id,
        "version": job.version_id,
        "version_label": job.version.version_label,
        "standard": job.version.source_id,
        "standard_title": job.version.official_title,
        "subject_name": job.version.subject_name_snapshot,
        "task_type": job.task_type,
        "mode": job.mode,
        "mode_label": job.get_mode_display(),
        "priority": job.priority,
        "priority_label": job.get_priority_display(),
        "status": job.status,
        "status_label": job.get_status_display(),
        "stage": job.stage,
        "stage_label": job.get_stage_display(),
        "progress_current": current,
        "progress_total": total,
        "progress_percent": progress_percent,
        "resource_limit": {
            "queue": getattr(settings, "CURRICULUM_PROCESSING_QUEUE", "curriculum_ocr"),
            "one_pdf_per_task": True,
            "worker_concurrency": 1,
            "result_state": "database",
        },
        "requested_by": job.requested_by_id,
        "created_by_display": _actor_name(job.requested_by),
        "cancel_requested_by_display": _actor_name(job.cancel_requested_by),
        "celery_task_id": job.celery_task_id,
        "retry_of": job.retry_of_id,
        "retry_count": job.retry_count,
        "can_retry": (
            job.status
            in {
                CurriculumProcessingJobStatus.FAILED,
                CurriculumProcessingJobStatus.CANCELLED,
            }
            and job.version.status == CurriculumVersionStatus.DRAFT
        ),
        "can_resume": (
            job.status == CurriculumProcessingJobStatus.QUEUED
            and job.version.status == CurriculumVersionStatus.DRAFT
        ),
        "can_cancel": job.status
        in {
            CurriculumProcessingJobStatus.QUEUED,
            CurriculumProcessingJobStatus.RUNNING,
        },
        "worker_hostname": job.worker_hostname,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "result_summary": job.result_summary,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "heartbeat_at": job.heartbeat_at,
        "finished_at": job.finished_at,
        "cancel_requested_at": job.cancel_requested_at,
        "updated_at": job.updated_at,
    }


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def super_admin_processing_jobs(request):
    reconcile_stale_processing_jobs()
    rows = _processing_job_queryset()
    status_value = str(request.query_params.get("status") or "").strip()
    version_value = str(request.query_params.get("version") or "").strip()
    standard_value = str(request.query_params.get("standard") or "").strip()
    if status_value:
        if status_value not in CurriculumProcessingJobStatus.values:
            return fail(
                "后台任务状态筛选值不正确。",
                errors={"status": ["请选择已登记的任务状态。"]},
                status=400,
            )
        rows = rows.filter(status=status_value)
    for value, field_name, label in (
        (version_value, "version_id", "version"),
        (standard_value, "version__source_id", "standard"),
    ):
        if not value:
            continue
        try:
            numeric_value = int(value)
        except ValueError:
            return fail(
                "后台任务筛选参数不正确。",
                errors={label: ["必须提交整数编号。"]},
                status=400,
            )
        rows = rows.filter(**{field_name: numeric_value})
    return ok(
        {
            "jobs": [_processing_job_row(job) for job in rows],
            "summary": processing_job_summary(),
            "statuses": [
                {"value": value, "label": label}
                for value, label in CurriculumProcessingJobStatus.choices
            ],
            "priorities": [
                {"value": value, "label": label}
                for value, label in CurriculumProcessingPriority.choices
            ],
            "modes": [
                {"value": value, "label": label}
                for value, label in CurriculumProcessingMode.choices
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def super_admin_processing_job_detail(request, pk: int):
    reconcile_stale_processing_jobs()
    job = _processing_job_queryset().filter(pk=pk).first()
    if not job:
        return fail("课程标准后台任务不存在。", status=404)
    return ok(_processing_job_row(job))


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_create_processing_job(request, pk: int):
    version = (
        CurriculumStandardVersion.objects.select_related("source").filter(pk=pk).first()
    )
    if not version:
        return fail("课程标准版本不存在。", status=404)
    serializer = CurriculumProcessingJobCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return fail("后台处理任务未创建。", errors=serializer.errors, status=400)
    try:
        job, created = create_processing_job(
            version=version,
            actor=request.user,
            **serializer.validated_data,
        )
    except DjangoValidationError as exc:
        return fail("后台处理任务未创建。", errors=_errors(exc), status=409)
    if created:
        job = dispatch_processing_job(job)
    job = _processing_job_queryset().get(pk=job.pk)
    if not created:
        return ok(_processing_job_row(job), "该版本已有等待或正在运行的任务。")
    message = (
        "后台任务已创建并进入队列。"
        if job.status != CurriculumProcessingJobStatus.FAILED
        else job.error_message
    )
    return ok(_processing_job_row(job), message, status=202)


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_cancel_processing_job(request, pk: int):
    job = _processing_job_queryset().filter(pk=pk).first()
    if not job:
        return fail("课程标准后台任务不存在。", status=404)
    job = request_job_cancel(job, actor=request.user)
    job = _processing_job_queryset().get(pk=job.pk)
    if job.status == CurriculumProcessingJobStatus.CANCELLING:
        message = "取消请求已记录；正在处理的任务会在当前页结束后安全停止。"
    elif job.status == CurriculumProcessingJobStatus.CANCELLED:
        message = "后台任务已取消。"
    else:
        message = "后台任务已经结束，无需取消。"
    return ok(
        _processing_job_row(job),
        message,
    )


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_retry_processing_job(request, pk: int):
    job = _processing_job_queryset().filter(pk=pk).first()
    if not job:
        return fail("课程标准后台任务不存在。", status=404)
    try:
        retry_job, created = retry_processing_job(job, actor=request.user)
    except DjangoValidationError as exc:
        return fail("后台任务不能重试。", errors=_errors(exc), status=409)
    if created:
        retry_job = dispatch_processing_job(retry_job)
    retry_job = _processing_job_queryset().get(pk=retry_job.pk)
    if not created:
        message = "该版本已有等待或正在运行的任务，未重复创建。"
    elif retry_job.status == CurriculumProcessingJobStatus.FAILED:
        message = retry_job.error_message
    else:
        message = "重试任务已创建并进入队列。"
    return ok(_processing_job_row(retry_job), message, status=202 if created else 200)


@api_view(["POST"])
@permission_classes([IsSuperAdmin])
def super_admin_resume_processing_job(request, pk: int):
    job = _processing_job_queryset().filter(pk=pk).first()
    if not job:
        return fail("课程标准后台任务不存在。", status=404)
    try:
        job = resume_processing_job(job, actor=request.user)
    except DjangoValidationError as exc:
        return fail("后台任务不能继续处理。", errors=_errors(exc), status=409)
    job = _processing_job_queryset().get(pk=job.pk)
    if job.status == CurriculumProcessingJobStatus.FAILED:
        return ok(_processing_job_row(job), job.error_message, status=202)
    return ok(
        _processing_job_row(job),
        "任务已重新发送至后台队列，将从已保存的状态继续处理。",
        status=202,
    )
