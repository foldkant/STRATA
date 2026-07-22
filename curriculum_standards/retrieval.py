"""Deterministic, source-traceable curriculum-standard retrieval.

P1 intentionally uses a local ``icontains`` keyword backend for a modest
administrative corpus.  Backend selection is explicit so a later full-text or
vector implementation can replace candidate generation without changing the
governed chunk, version, and page-trace contracts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q

from .models import (
    CurriculumExtractionStatus,
    CurriculumRetrievalBackend,
    CurriculumRetrievalChunk,
    CurriculumRetrievalIndex,
    CurriculumRetrievalSourceKind,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    canonical_hash,
)


DEFAULT_CHUNK_MAX_CHARS = 1200
DEFAULT_CHUNK_OVERLAP_CHARS = 200
CHUNK_STRATEGY = "char_boundary"
CHUNK_STRATEGY_VERSION = "1"
MAX_SEARCH_CANDIDATES = 1000
SUPPORTED_RETRIEVAL_BACKENDS = (CurriculumRetrievalBackend.KEYWORD,)


@dataclass(frozen=True)
class TextSlice:
    ordinal: int
    start: int
    end: int
    text: str


def sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def validate_chunk_config(max_chars: int, overlap_chars: int) -> tuple[int, int]:
    max_chars = int(max_chars)
    overlap_chars = int(overlap_chars)
    errors = {}
    if max_chars < 256 or max_chars > 8000:
        errors["max_chars"] = "检索片段最大字符数必须在 256 到 8000 之间。"
    if overlap_chars < 0 or overlap_chars >= max_chars:
        errors["overlap_chars"] = "重叠字符数必须大于或等于 0，且小于最大字符数。"
    if errors:
        raise ValidationError(errors)
    return max_chars, overlap_chars


def split_retrieval_text(
    text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[TextSlice]:
    """Split one source record deterministically without crossing its page anchor."""

    max_chars, overlap_chars = validate_chunk_config(max_chars, overlap_chars)
    source = str(text or "")
    if not source.strip():
        return []
    result: list[TextSlice] = []
    start = 0
    ordinal = 0
    source_length = len(source)
    boundary_chars = ("\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ")
    while start < source_length:
        hard_end = min(start + max_chars, source_length)
        end = hard_end
        if hard_end < source_length:
            minimum_boundary = start + max(int(max_chars * 0.65), 1)
            candidates = []
            for marker in boundary_chars:
                location = source.rfind(marker, minimum_boundary, hard_end + 1)
                if location >= minimum_boundary:
                    candidates.append(location + len(marker))
            if candidates:
                end = max(candidates)

        left_trimmed = len(source[start:end]) - len(source[start:end].lstrip())
        right_trimmed = len(source[start:end]) - len(source[start:end].rstrip())
        slice_start = start + left_trimmed
        slice_end = end - right_trimmed
        if slice_end > slice_start:
            result.append(
                TextSlice(
                    ordinal=ordinal,
                    start=slice_start,
                    end=slice_end,
                    text=source[slice_start:slice_end],
                )
            )
            ordinal += 1
        if end >= source_length:
            break
        next_start = max(end - overlap_chars, start + 1)
        start = next_start
    return result


def _page_hash_payload(pages: Iterable) -> list[dict]:
    return [
        {
            "page_number": page.page_number,
            "page_content_hash": page.content_hash,
            "page_text_sha256": sha256_text(page.text),
        }
        for page in pages
    ]


def _chunk_id(
    version: CurriculumStandardVersion,
    *,
    source_kind: str,
    source_locator: str,
    source_content_hash: str,
    source_text_sha256: str,
    text_slice: TextSlice,
    content_sha256: str,
    max_chars: int,
    overlap_chars: int,
) -> str:
    # Database primary keys are deliberately excluded. Rebuilding the same
    # governed source in another environment therefore produces the same ID.
    return canonical_hash(
        {
            "schema": "curriculum_retrieval_chunk_v1",
            "school_stage": version.school_stage_snapshot,
            "document_type": version.document_type_snapshot,
            "subject_code": version.subject_code_snapshot,
            "version_label": version.version_label,
            "pdf_sha256": version.pdf_sha256,
            "source_kind": source_kind,
            "source_locator": source_locator,
            "source_content_hash": source_content_hash,
            "source_text_sha256": source_text_sha256,
            "ordinal": text_slice.ordinal,
            "char_start": text_slice.start,
            "char_end": text_slice.end,
            "content_sha256": content_sha256,
            "strategy": CHUNK_STRATEGY,
            "strategy_version": CHUNK_STRATEGY_VERSION,
            "max_chars": max_chars,
            "overlap_chars": overlap_chars,
        }
    )


def _chunk_specs(
    version: CurriculumStandardVersion,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[dict]:
    pages = list(version.pages.order_by("page_number"))
    page_by_number = {page.page_number: page for page in pages}
    specs = []

    def add_source(
        *,
        source_kind: str,
        source_locator: str,
        source_object,
        source_text: str,
        source_content_hash: str,
        page_start: int,
        page_end: int,
    ) -> None:
        page_rows = [
            page_by_number[number]
            for number in range(page_start, page_end + 1)
            if number in page_by_number
        ]
        page_hashes = _page_hash_payload(page_rows)
        source_text_hash = sha256_text(source_text)
        for text_slice in split_retrieval_text(
            source_text,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        ):
            content_hash = sha256_text(text_slice.text)
            specs.append(
                {
                    "chunk_id": _chunk_id(
                        version,
                        source_kind=source_kind,
                        source_locator=source_locator,
                        source_content_hash=source_content_hash,
                        source_text_sha256=source_text_hash,
                        text_slice=text_slice,
                        content_sha256=content_hash,
                        max_chars=max_chars,
                        overlap_chars=overlap_chars,
                    ),
                    "source_kind": source_kind,
                    "source_locator": source_locator,
                    "source_object_id": source_object.id,
                    "source_page_id": (
                        source_object.id
                        if source_kind == CurriculumRetrievalSourceKind.PAGE
                        else None
                    ),
                    "source_node_id": (
                        source_object.id
                        if source_kind == CurriculumRetrievalSourceKind.CONTENT_ITEM
                        else None
                    ),
                    "ordinal": text_slice.ordinal,
                    "text": text_slice.text,
                    "char_start": text_slice.start,
                    "char_end": text_slice.end,
                    "char_count": len(text_slice.text),
                    "content_sha256": content_hash,
                    "source_text_sha256": source_text_hash,
                    "source_content_hash": source_content_hash,
                    "version_content_hash": version.content_hash,
                    "pdf_sha256": version.pdf_sha256,
                    "source_page_start": page_start,
                    "source_page_end": page_end,
                    "source_page_hashes": page_hashes,
                }
            )

    for page in pages:
        add_source(
            source_kind=CurriculumRetrievalSourceKind.PAGE,
            source_locator=f"page:{page.page_number}",
            source_object=page,
            source_text=page.text,
            source_content_hash=page.content_hash,
            page_start=page.page_number,
            page_end=page.page_number,
        )
    for node in version.nodes.select_related("parent").order_by("sort_order", "code", "id"):
        add_source(
            source_kind=CurriculumRetrievalSourceKind.CONTENT_ITEM,
            source_locator=f"content_item:{node.code}",
            source_object=node,
            source_text=node.content,
            source_content_hash=node.content_hash,
            page_start=node.source_page_start,
            page_end=node.source_page_end,
        )
    return specs


_CHUNK_INTEGRITY_FIELDS = (
    "chunk_id",
    "source_kind",
    "source_locator",
    "source_object_id",
    "source_page_id",
    "source_node_id",
    "ordinal",
    "text",
    "char_start",
    "char_end",
    "char_count",
    "content_sha256",
    "source_text_sha256",
    "source_content_hash",
    "version_content_hash",
    "pdf_sha256",
    "source_page_start",
    "source_page_end",
    "source_page_hashes",
)


def _chunk_integrity_digest(rows: Iterable[dict], *, version_id: int) -> str:
    """Hash persisted chunk fields, not just the expected stable chunk IDs."""

    payload = []
    for row in rows:
        item = {field: row[field] for field in _CHUNK_INTEGRITY_FIELDS}
        item["version_id"] = row.get("version_id", version_id)
        payload.append(item)
    payload.sort(key=lambda item: item["chunk_id"])
    return canonical_hash(
        {
            "schema": "curriculum_retrieval_chunk_integrity_v1",
            "chunks": payload,
        }
    )


def _retrieval_index_hash(
    version: CurriculumStandardVersion,
    *,
    specs: list[dict],
    max_chars: int,
    overlap_chars: int,
) -> str:
    return canonical_hash(
        {
            "schema": "curriculum_retrieval_index_v1",
            "version_content_hash": version.content_hash,
            "pdf_sha256": version.pdf_sha256,
            "backend": CurriculumRetrievalBackend.KEYWORD,
            "strategy": CHUNK_STRATEGY,
            "strategy_version": CHUNK_STRATEGY_VERSION,
            "max_chars": max_chars,
            "overlap_chars": overlap_chars,
            "chunk_ids": [spec["chunk_id"] for spec in specs],
        }
    )


def _retrieval_index_matches_specs(
    index: CurriculumRetrievalIndex,
    version: CurriculumStandardVersion,
    *,
    specs: list[dict],
    expected_index_hash: str,
) -> bool:
    if not (
        index.version_id == version.id
        and index.backend == CurriculumRetrievalBackend.KEYWORD
        and index.strategy == CHUNK_STRATEGY
        and index.strategy_version == CHUNK_STRATEGY_VERSION
        and index.version_content_hash == version.content_hash
        and index.pdf_sha256 == version.pdf_sha256
        and index.index_hash == expected_index_hash
        and index.chunk_count == len(specs)
        and index.chunk_count > 0
    ):
        return False
    actual = list(
        index.chunks.order_by("chunk_id").values(
            "version_id",
            *_CHUNK_INTEGRITY_FIELDS,
        )
    )
    if len(actual) != len(specs):
        return False
    return _chunk_integrity_digest(
        actual,
        version_id=version.id,
    ) == _chunk_integrity_digest(
        specs,
        version_id=version.id,
    )


@transaction.atomic
def rebuild_retrieval_index(
    version: CurriculumStandardVersion,
    *,
    actor=None,
    max_chars: int | None = None,
    overlap_chars: int | None = None,
) -> tuple[CurriculumRetrievalIndex, bool]:
    """Atomically replace only the derived index for one immutable version."""

    version = (
        CurriculumStandardVersion.objects.select_for_update()
        .select_related("source")
        .get(pk=version.pk)
    )
    if version.extraction_status != CurriculumExtractionStatus.COMPLETED:
        raise ValidationError("只有完成可读取文本处理的课程标准版本可以建立检索索引。")
    existing = CurriculumRetrievalIndex.objects.filter(version=version).first()
    requested_max = max_chars if max_chars is not None else (
        existing.max_chars if existing else DEFAULT_CHUNK_MAX_CHARS
    )
    requested_overlap = overlap_chars if overlap_chars is not None else (
        existing.overlap_chars if existing else DEFAULT_CHUNK_OVERLAP_CHARS
    )
    requested_max, requested_overlap = validate_chunk_config(
        requested_max,
        requested_overlap,
    )
    if existing and version.status != CurriculumVersionStatus.DRAFT:
        if (requested_max, requested_overlap) != (
            existing.max_chars,
            existing.overlap_chars,
        ):
            raise ValidationError("进入复核流程后的课程标准版本不能改变检索切分策略。")

    specs = _chunk_specs(
        version,
        max_chars=requested_max,
        overlap_chars=requested_overlap,
    )
    if not specs:
        raise ValidationError("课程标准逐页文本为空，无法建立检索片段。")
    index_hash = _retrieval_index_hash(
        version,
        specs=specs,
        max_chars=requested_max,
        overlap_chars=requested_overlap,
    )
    unchanged = bool(
        existing
        and _retrieval_index_matches_specs(
            existing,
            version,
            specs=specs,
            expected_index_hash=index_hash,
        )
    )
    if unchanged:
        return existing, False

    index, _ = CurriculumRetrievalIndex.objects.update_or_create(
        version=version,
        defaults={
            "backend": CurriculumRetrievalBackend.KEYWORD,
            "strategy": CHUNK_STRATEGY,
            "strategy_version": CHUNK_STRATEGY_VERSION,
            "max_chars": requested_max,
            "overlap_chars": requested_overlap,
            "chunk_count": len(specs),
            "index_hash": index_hash,
            "version_content_hash": version.content_hash,
            "pdf_sha256": version.pdf_sha256,
            "built_by": actor,
        },
    )
    index.chunks.all().delete()
    CurriculumRetrievalChunk.objects.bulk_create(
        [
            CurriculumRetrievalChunk(version=version, index=index, **spec)
            for spec in specs
        ],
        batch_size=500,
    )
    return index, True


def retrieval_index_is_current(
    version: CurriculumStandardVersion,
    *,
    index: CurriculumRetrievalIndex | None = None,
) -> bool:
    if index is None:
        try:
            index = version.retrieval_index
        except CurriculumRetrievalIndex.DoesNotExist:
            return False
    if version.extraction_status != CurriculumExtractionStatus.COMPLETED:
        return False
    try:
        max_chars, overlap_chars = validate_chunk_config(
            index.max_chars,
            index.overlap_chars,
        )
        specs = _chunk_specs(
            version,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
    except (TypeError, ValueError, ValidationError):
        return False
    if not specs:
        return False
    expected_index_hash = _retrieval_index_hash(
        version,
        specs=specs,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    return _retrieval_index_matches_specs(
        index,
        version,
        specs=specs,
        expected_index_hash=expected_index_hash,
    )


def _query_terms(query: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if not normalized:
        return []
    terms = [item for item in normalized.split(" ") if len(item) >= 2]
    return list(dict.fromkeys([normalized, *terms]))


def search_retrieval_chunks(
    *,
    query: str,
    version_id: int | None = None,
    school_stage: str = "",
    subject_code: str = "",
    source_kind: str = "",
    include_history: bool = False,
    include_unpublished: bool = False,
    limit: int = 20,
    backend: str = CurriculumRetrievalBackend.KEYWORD,
) -> list[tuple[CurriculumRetrievalChunk, int]]:
    if backend not in SUPPORTED_RETRIEVAL_BACKENDS:
        raise ValidationError({"backend": "当前仅启用本地关键词检索；向量后端尚未配置。"})
    terms = _query_terms(query)
    if not terms:
        raise ValidationError({"q": "请输入至少两个字符的检索词。"})
    limit = min(max(int(limit), 1), 50)
    rows = CurriculumRetrievalChunk.objects.select_related(
        "index",
        "version__source",
        "source_page",
        "source_node",
    ).filter(
        index__backend=backend,
        index__version_content_hash=F("version__content_hash"),
        index__pdf_sha256=F("version__pdf_sha256"),
        version_content_hash=F("version__content_hash"),
        pdf_sha256=F("version__pdf_sha256"),
    )
    if version_id is not None:
        rows = rows.filter(version_id=version_id)
    if include_unpublished:
        rows = rows.exclude(version__status=CurriculumVersionStatus.DISCARDED)
    elif include_history:
        rows = rows.filter(
            version__status__in=[
                CurriculumVersionStatus.PUBLISHED,
                CurriculumVersionStatus.ARCHIVED,
            ],
            version__source__is_active=True,
        )
    else:
        rows = rows.filter(
            version__status=CurriculumVersionStatus.PUBLISHED,
            version__source__is_active=True,
            version__source__current_version_id=F("version_id"),
        )
    if school_stage:
        rows = rows.filter(version__school_stage_snapshot=school_stage)
    if subject_code:
        rows = rows.filter(version__subject_code_snapshot=subject_code)
    if source_kind:
        rows = rows.filter(source_kind=source_kind)

    text_filter = Q()
    for term in terms:
        text_filter |= Q(text__icontains=term)
        text_filter |= Q(source_node__title__icontains=term)
        text_filter |= Q(version__subject_name_snapshot__icontains=term)
    candidates = list(rows.filter(text_filter)[:MAX_SEARCH_CANDIDATES])
    # SQL metadata predicates are only a fast pre-filter.  Verify each
    # candidate version's persisted chunk manifest before serving any row, so
    # a same-count accidental/tampered update cannot enter AI context.
    current_versions: dict[int, bool] = {}
    verified_candidates = []
    for chunk in candidates:
        if chunk.version_id not in current_versions:
            current_versions[chunk.version_id] = retrieval_index_is_current(
                chunk.version,
                index=chunk.index,
            )
        if current_versions[chunk.version_id]:
            verified_candidates.append(chunk)
    candidates = verified_candidates
    normalized_query = re.sub(r"\s+", " ", str(query or "").strip().lower())

    def score(chunk: CurriculumRetrievalChunk) -> int:
        haystack = chunk.text.lower()
        value = haystack.count(normalized_query) * 12
        for term in terms:
            value += haystack.count(term) * 3
            if chunk.source_node_id and term in chunk.source_node.title.lower():
                value += 8
            if term in chunk.version.subject_name_snapshot.lower():
                value += 3
        if chunk.source_kind == CurriculumRetrievalSourceKind.CONTENT_ITEM:
            value += 2
        return value

    scored = [(chunk, score(chunk)) for chunk in candidates]
    scored.sort(
        key=lambda item: (
            -item[1],
            item[0].version_id,
            item[0].source_page_start,
            item[0].ordinal,
            item[0].chunk_id,
        )
    )
    return scored[:limit]
