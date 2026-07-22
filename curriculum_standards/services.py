from __future__ import annotations

import hashlib
import io
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from importlib.metadata import PackageNotFoundError, version as package_version
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .models import (
    CurriculumDocumentType,
    CurriculumExtractionStatus,
    CurriculumNodeType,
    CurriculumPageQualityStatus,
    CurriculumPageReviewStatus,
    CurriculumProcessingJobStatus,
    CurriculumStandard,
    CurriculumStandardAuditLog,
    CurriculumStandardNode,
    CurriculumStandardPage,
    CurriculumStandardVersion,
    CurriculumTextExtractionMethod,
    CurriculumVersionStatus,
    EvaluationPlanCurriculumReference,
    EvaluationPlanVersionCurriculumReference,
    canonical_hash,
)

MAX_PDF_BYTES = 100 * 1024 * 1024
CONFIDENCE_QUANTUM = Decimal("0.0001")
REQUIRED_ALIGNMENT_NODE_TYPES = frozenset(CurriculumNodeType.values)
SUBJECT_NAME_EQUIVALENTS = (
    frozenset({"信息科技", "信息技术"}),
    frozenset({"政治", "思想政治"}),
    frozenset({"生物", "生物学"}),
    frozenset({"体育", "体育与健康"}),
    frozenset({"道德与法治", "思想品德"}),
)


@dataclass(frozen=True)
class ExtractedDocument:
    structured_text: str
    pages: list[str]
    page_records: list[dict]
    status: str
    message: str
    engine: str
    engine_version: str
    config: dict


class CurriculumExtractionCancelled(Exception):
    """Raised between pages when an administrator requests cancellation."""


def _package_version(name: str) -> str:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return "unknown"


def _rewind(file_obj) -> None:
    try:
        file_obj.seek(0)
    except (AttributeError, OSError):
        pass


def sha256_file(file_obj) -> str:
    digest = hashlib.sha256()
    _rewind(file_obj)
    if hasattr(file_obj, "chunks"):
        for chunk in file_obj.chunks():
            digest.update(chunk)
    else:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    _rewind(file_obj)
    return digest.hexdigest()


def file_size_bytes(file_obj) -> int:
    size = getattr(file_obj, "size", None)
    if size is not None:
        return int(size)
    _rewind(file_obj)
    file_obj.seek(0, io.SEEK_END)
    size = int(file_obj.tell())
    _rewind(file_obj)
    return size


def normalize_structured_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def validate_pdf_upload(file_obj) -> None:
    name = str(getattr(file_obj, "name", "") or "")
    if Path(name).suffix.lower() != ".pdf":
        raise ValidationError({"pdf_file": "课程标准原始文件必须是 PDF。"})
    size = getattr(file_obj, "size", None)
    if size is not None and int(size) > MAX_PDF_BYTES:
        raise ValidationError({"pdf_file": "单个课程标准 PDF 不能超过 100 MB。"})
    _rewind(file_obj)
    header = file_obj.read(5)
    _rewind(file_obj)
    if header != b"%PDF-":
        raise ValidationError({"pdf_file": "文件内容不是有效的 PDF。"})


def pdf_page_count(file_obj) -> int:
    _rewind(file_obj)
    try:
        from pypdf import PdfReader

        count = len(PdfReader(file_obj).pages)
    except Exception as exc:
        raise ValidationError({"pdf_file": "PDF 结构损坏或无法读取。"}) from exc
    finally:
        _rewind(file_obj)
    if count < 1:
        raise ValidationError({"pdf_file": "PDF 不包含可读取页面。"})
    return count


def _ocr_pdf_pages(
    file_obj,
    *,
    page_callback: Callable[[dict, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict]:
    try:
        import fitz
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "服务器未安装课程标准文字识别依赖（PyMuPDF、RapidOCR）。"
        ) from exc

    _rewind(file_obj)
    raw = file_obj.read()
    _rewind(file_obj)
    document = fitz.open(stream=raw, filetype="pdf")
    engine = RapidOCR()
    records = []
    try:
        for page_number, page in enumerate(document, start=1):
            if cancel_check and cancel_check():
                raise CurriculumExtractionCancelled()
            scale = float(getattr(settings, "CURRICULUM_OCR_SCALE", 1.5))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height,
                pixmap.width,
                pixmap.n,
            )
            result, _ = engine(image)
            result = result or []
            lines = [normalize_structured_text(str(item[1])) for item in result if item[1]]
            confidences = [float(item[2]) for item in result if len(item) > 2]
            text = normalize_structured_text("\n".join(line for line in lines if line))
            record = {
                    "page_number": page_number,
                    "text": text,
                    "extraction_method": CurriculumTextExtractionMethod.OCR,
                    "mean_confidence": (
                        round(sum(confidences) / len(confidences), 4)
                        if confidences
                        else 0.0
                    ),
                    "quality_status": (
                        CurriculumPageQualityStatus.EMPTY
                        if not text
                        else (
                            CurriculumPageQualityStatus.LOW_CONFIDENCE
                            if confidences and sum(confidences) / len(confidences) < 0.75
                            else CurriculumPageQualityStatus.COMPLETE
                        )
                    ),
                    "quality_message": (
                        "本页未识别到文字。"
                        if not text
                        else "文字识别结果发布前需人工复核。"
                    ),
                }
            records.append(record)
            if page_callback:
                page_callback(record, page_number, len(document))
        if cancel_check and cancel_check():
            raise CurriculumExtractionCancelled()
    finally:
        document.close()
    return records


def _structured_text_from_page_records(records: list[dict]) -> str:
    return normalize_structured_text(
        "\n\n".join(
            f"# PDF 第 {record['page_number']} 页\n\n{record['text']}"
            for record in records
        )
    )


def _manual_page_records(text: str, *, expected_page_count: int) -> list[dict]:
    pattern = re.compile(r"(?m)^# PDF 第 (\d+) 页\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        if expected_page_count != 1:
            raise ValidationError(
                {
                    "structured_text": (
                        f"该 PDF 共 {expected_page_count} 页；人工结构化文本必须逐页添加页码标记。"
                    )
                }
            )
        return [
            {
                "page_number": 1,
                "text": text,
                "extraction_method": CurriculumTextExtractionMethod.MANUAL,
                "mean_confidence": None,
                "quality_status": CurriculumPageQualityStatus.COMPLETE,
                "quality_message": "管理员提交的文本需在发布前复核。",
            }
        ]
    page_numbers = [int(match.group(1)) for match in matches]
    if page_numbers != list(range(1, expected_page_count + 1)):
        raise ValidationError(
            {
                "structured_text": (
                    f"页码标记必须从 1 到 {expected_page_count} 完整、唯一且连续。"
                )
            }
        )
    records = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        records.append(
            {
                "page_number": int(match.group(1)),
                "text": normalize_structured_text(text[match.end():end]),
                "extraction_method": CurriculumTextExtractionMethod.MANUAL,
                "mean_confidence": None,
                "quality_status": (
                    CurriculumPageQualityStatus.COMPLETE
                    if normalize_structured_text(text[match.end():end])
                    else CurriculumPageQualityStatus.EMPTY
                ),
                "quality_message": "管理员提交的文本需在发布前复核。",
            }
        )
    return records


def extract_pdf_text(
    file_obj,
    *,
    allow_ocr: bool = False,
    force_ocr: bool = False,
    page_callback: Callable[[dict, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    phase_callback: Callable[[str], None] | None = None,
) -> ExtractedDocument:
    if phase_callback:
        phase_callback("extracting")
    if cancel_check and cancel_check():
        raise CurriculumExtractionCancelled()
    _rewind(file_obj)
    try:
        from pypdf import PdfReader
    except ImportError:
        return ExtractedDocument(
            structured_text="",
            pages=[],
            page_records=[],
            status=CurriculumExtractionStatus.FAILED,
            message="服务器未安装 pypdf，需上传结构化文本。",
            engine="unavailable",
            engine_version="",
            config={"strategy": "embedded_text_first", "allow_ocr": allow_ocr},
        )

    try:
        reader = PdfReader(file_obj)
        pages = [normalize_structured_text(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # malformed/encrypted documents vary by producer
        _rewind(file_obj)
        return ExtractedDocument(
            structured_text="",
            pages=[],
            page_records=[],
            status=CurriculumExtractionStatus.FAILED,
            message=f"PDF 文本提取失败：{str(exc)[:300]}",
            engine="pypdf",
            engine_version=_package_version("pypdf"),
            config={"strategy": "embedded_text_first", "allow_ocr": allow_ocr},
        )
    finally:
        _rewind(file_obj)

    if force_ocr:
        if phase_callback:
            phase_callback("ocr")
        try:
            page_records = _ocr_pdf_pages(
                file_obj,
                page_callback=page_callback,
                cancel_check=cancel_check,
            )
        except RuntimeError as exc:
            return ExtractedDocument(
                structured_text="",
                pages=pages,
                page_records=[],
                status=CurriculumExtractionStatus.FAILED,
                message=str(exc),
                engine="pypdf",
                engine_version=_package_version("pypdf"),
                config={"strategy": "forced_ocr", "allow_ocr": True},
            )
        ocr_pages = [record["text"] for record in page_records]
        ocr_chars = sum(len(page) for page in ocr_pages)
        confidences = [
            float(record["mean_confidence"])
            for record in page_records
            if record.get("text") and record.get("mean_confidence") is not None
        ]
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return ExtractedDocument(
            structured_text=(
                _structured_text_from_page_records(page_records)
                if ocr_chars >= 200
                else ""
            ),
            pages=ocr_pages,
            page_records=page_records,
            status=(
                CurriculumExtractionStatus.COMPLETED
                if ocr_chars >= 200
                else CurriculumExtractionStatus.FAILED
            ),
            message=(
                f"已对 {len(page_records)} 页进行文字识别；平均置信度 "
                f"{mean_confidence:.3f}，发布前必须人工复核。"
                if ocr_chars >= 200
                else "全文文字识别完成，但有效文本不足 200 字，请人工核对原始 PDF。"
            ),
            engine="pypdf+PyMuPDF+rapidocr_onnxruntime",
            engine_version=(
                f"pypdf={_package_version('pypdf')};"
                f"PyMuPDF={_package_version('PyMuPDF')};"
                f"rapidocr-onnxruntime={_package_version('rapidocr-onnxruntime')}"
            ),
            config={
                "strategy": "forced_ocr",
                "ocr_scale": float(getattr(settings, "CURRICULUM_OCR_SCALE", 1.5)),
                "minimum_document_chars": 200,
            },
        )

    useful_chars = sum(len(page) for page in pages)
    if useful_chars < 200:
        if allow_ocr:
            if phase_callback:
                phase_callback("ocr")
            try:
                page_records = _ocr_pdf_pages(
                    file_obj,
                    page_callback=page_callback,
                    cancel_check=cancel_check,
                )
            except RuntimeError as exc:
                return ExtractedDocument(
                    structured_text="",
                    pages=pages,
                    page_records=[],
                    status=CurriculumExtractionStatus.FAILED,
                    message=str(exc),
                    engine="pypdf",
                    engine_version=_package_version("pypdf"),
                    config={"strategy": "embedded_text_then_ocr", "allow_ocr": True},
                )
            ocr_pages = [record["text"] for record in page_records]
            ocr_chars = sum(len(page) for page in ocr_pages)
            confidences = [
                float(record["mean_confidence"])
                for record in page_records
                if record.get("text") and record.get("mean_confidence") is not None
            ]
            if ocr_chars >= 200:
                mean_confidence = (
                    sum(confidences) / len(confidences) if confidences else 0.0
                )
                return ExtractedDocument(
                    structured_text=_structured_text_from_page_records(page_records),
                    pages=ocr_pages,
                    page_records=page_records,
                    status=CurriculumExtractionStatus.COMPLETED,
                    message=(
                        f"已对 {len(page_records)} 页进行文字识别；"
                        f"平均置信度 {mean_confidence:.3f}，发布前必须人工复核。"
                    ),
                    engine="pypdf+PyMuPDF+rapidocr_onnxruntime",
                    engine_version=(
                        f"pypdf={_package_version('pypdf')};"
                        f"PyMuPDF={_package_version('PyMuPDF')};"
                        f"rapidocr-onnxruntime={_package_version('rapidocr-onnxruntime')}"
                    ),
                    config={
                        "strategy": "embedded_text_then_ocr",
                        "ocr_scale": float(getattr(settings, "CURRICULUM_OCR_SCALE", 1.5)),
                        "minimum_document_chars": 200,
                    },
                )
        page_records = [
            {
                "page_number": page_number,
                "text": page,
                "extraction_method": CurriculumTextExtractionMethod.EMBEDDED_TEXT,
                "mean_confidence": None,
                "quality_status": (
                    CurriculumPageQualityStatus.COMPLETE
                    if page
                    else CurriculumPageQualityStatus.EMPTY
                ),
                "quality_message": "" if page else "PDF 本页未提取到内嵌文字。",
            }
            for page_number, page in enumerate(pages, start=1)
        ]
        if page_callback:
            for current, record in enumerate(page_records, start=1):
                if cancel_check and cancel_check():
                    raise CurriculumExtractionCancelled()
                page_callback(record, current, len(page_records))
        return ExtractedDocument(
            structured_text="",
            pages=pages,
            page_records=page_records,
            status=CurriculumExtractionStatus.NEEDS_OCR,
            message="PDF 未包含足够的可提取文字，需要文字识别或人工上传结构化文本。",
            engine="pypdf",
            engine_version=_package_version("pypdf"),
            config={
                "strategy": "embedded_text_first",
                "allow_ocr": allow_ocr,
                "minimum_document_chars": 200,
            },
        )
    page_records = [
        {
            "page_number": page_number,
            "text": page,
            "extraction_method": CurriculumTextExtractionMethod.EMBEDDED_TEXT,
            "mean_confidence": None,
            "quality_status": (
                CurriculumPageQualityStatus.COMPLETE
                if page
                else CurriculumPageQualityStatus.EMPTY
            ),
            "quality_message": "" if page else "PDF 本页未提取到内嵌文字。",
        }
        for page_number, page in enumerate(pages, start=1)
    ]
    if page_callback:
        for current, record in enumerate(page_records, start=1):
            if cancel_check and cancel_check():
                raise CurriculumExtractionCancelled()
            page_callback(record, current, len(page_records))
    structured = _structured_text_from_page_records(page_records)
    return ExtractedDocument(
        structured_text=normalize_structured_text(structured),
        pages=pages,
        page_records=page_records,
        status=CurriculumExtractionStatus.COMPLETED,
        message="已按 PDF 页码生成结构化文本。",
        engine="pypdf",
        engine_version=_package_version("pypdf"),
        config={
            "strategy": "embedded_text_first",
            "allow_ocr": allow_ocr,
            "minimum_document_chars": 200,
        },
    )


def _version_semantic_content(version: CurriculumStandardVersion) -> dict:
    nodes = list(version.nodes.order_by("sort_order", "code")) if version.pk else []
    pages = list(version.pages.order_by("page_number")) if version.pk else []
    return {
        "source_identity": {
            "school_stage": version.school_stage_snapshot,
            "document_type": version.document_type_snapshot,
            "subject_code": version.subject_code_snapshot,
        },
        "version_label": version.version_label,
        "publication_year": version.publication_year,
        "effective_year": version.effective_year,
        "title_snapshot": version.title_snapshot,
        "official_title": version.official_title,
        "document_type_snapshot": version.document_type_snapshot,
        "school_stage_snapshot": version.school_stage_snapshot,
        "subject_code_snapshot": version.subject_code_snapshot,
        "subject_name_snapshot": version.subject_name_snapshot,
        "issued_by": version.issued_by,
        "source_url": version.source_url,
        "source_note": version.source_note,
        "pdf_sha256": version.pdf_sha256,
        "pdf_size_bytes": version.pdf_size_bytes,
        "pdf_page_count": version.pdf_page_count,
        "structured_format": version.structured_format,
        "structured_text_sha256": version.structured_text_sha256,
        "extraction_engine": version.extraction_engine,
        "extraction_engine_version": version.extraction_engine_version,
        "extraction_config": version.extraction_config,
        "replaces_version_hash": (
            version.replaces_version.content_hash
            if version.replaces_version_id
            else None
        ),
        "nodes": [
            {
                "code": node.code,
                "node_type": node.node_type,
                "content_hash": node.content_hash,
            }
            for node in nodes
        ],
        "pages": [
            {
                "page_number": page.page_number,
                "content_hash": page.content_hash,
            }
            for page in pages
        ],
    }


def refresh_version_hash(version: CurriculumStandardVersion) -> str:
    version.content_hash = canonical_hash(_version_semantic_content(version))
    version.save(update_fields=["content_hash"])
    if (
        version.extraction_status == CurriculumExtractionStatus.COMPLETED
        and version.pages.exists()
    ):
        from .retrieval import rebuild_retrieval_index

        rebuild_retrieval_index(version)
    return version.content_hash


def _structured_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _normalize_mean_confidence(value) -> Decimal | None:
    """Store OCR confidence without binary-float decimal noise."""
    if value is None:
        return None
    try:
        confidence = Decimal(str(value)).quantize(
            CONFIDENCE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({"mean_confidence": "文字识别置信度格式无效。"}) from exc
    if confidence < 0 or confidence > 1:
        raise ValidationError({"mean_confidence": "文字识别置信度必须在 0 到 1 之间。"})
    return confidence


def _save_page_records(
    version: CurriculumStandardVersion,
    records: list[dict],
) -> None:
    for record in records:
        CurriculumStandardPage.objects.create(
            version=version,
            page_number=record["page_number"],
            text=record.get("text", ""),
            extraction_method=record["extraction_method"],
            mean_confidence=_normalize_mean_confidence(
                record.get("mean_confidence")
            ),
            quality_status=record.get(
                "quality_status",
                CurriculumPageQualityStatus.COMPLETE,
            ),
            quality_message=record.get("quality_message", ""),
            review_status=CurriculumPageReviewStatus.NEEDS_REVIEW,
        )


def _page_record_char_count(records: Iterable[dict]) -> int:
    """Count source-page characters without counting generated page markers."""
    return sum(len(str(record.get("text", "") or "")) for record in records)


def _persist_new_version(
    version: CurriculumStandardVersion,
    *,
    page_records: list[dict],
    source_pages: list[str],
    actor,
    audit_action: str,
    audit_detail: dict,
) -> CurriculumStandardVersion:
    try:
        with transaction.atomic():
            version.save()
            CurriculumStandardAuditLog.objects.create(
                version=version,
                action=audit_action,
                actor=actor,
                detail=audit_detail,
            )
            _save_page_records(version, page_records)
            if source_pages:
                create_suggested_framework_nodes(version=version, pages=source_pages)
            refresh_version_hash(version)
    except Exception:
        stored_name = str(version.pdf_file.name or "").replace("\\", "/")
        if stored_name.startswith("curriculum_standards/managed/"):
            storage = version.pdf_file.storage
            if storage.exists(stored_name):
                storage.delete(stored_name)
        raise
    return version


@transaction.atomic
def replace_version_structured_text(
    version: CurriculumStandardVersion,
    *,
    structured_text: str,
    actor,
) -> CurriculumStandardVersion:
    version = CurriculumStandardVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != CurriculumVersionStatus.DRAFT:
        raise ValidationError("只有草稿版本可以替换结构化文本。")
    if version.nodes.exists():
        raise ValidationError("请先删除草稿中的课程标准内容条目，再替换结构化文本。")
    before_hash = version.content_hash
    text = normalize_structured_text(structured_text)
    version.pages.all().delete()
    page_records = (
        _manual_page_records(text, expected_page_count=version.pdf_page_count)
        if text
        else []
    )
    _save_page_records(version, page_records)
    version.structured_text = text
    version.structured_text_sha256 = _structured_hash(text)
    version.extraction_status = (
        CurriculumExtractionStatus.COMPLETED
        if _page_record_char_count(page_records) >= 200
        else CurriculumExtractionStatus.PENDING
    )
    version.extraction_message = (
        "使用管理员提交并确认的结构化文本。"
        if text
        else "等待生成结构化文本。"
    )
    version.extraction_engine = "manual_upload"
    version.extraction_engine_version = "1"
    version.extraction_config = {
        "strategy": "page_marked_text",
        "expected_page_count": version.pdf_page_count,
    }
    version.extracted_at = timezone.now()
    version.content_hash = canonical_hash(_version_semantic_content(version))
    version.save()
    from .retrieval import rebuild_retrieval_index

    if version.extraction_status == CurriculumExtractionStatus.COMPLETED:
        rebuild_retrieval_index(version, actor=actor)
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="structured_text_replaced",
        actor=actor,
        detail={"before_hash": before_hash, "after_hash": version.content_hash},
    )
    return version


@transaction.atomic
def update_page_text(
    page: CurriculumStandardPage,
    *,
    text: str,
    actor,
) -> CurriculumStandardPage:
    page = CurriculumStandardPage.objects.select_for_update().select_related("version").get(
        pk=page.pk
    )
    version = page.version
    if version.status != CurriculumVersionStatus.DRAFT:
        raise ValidationError("只有草稿版本可以修订逐页文本。")
    if version.nodes.exists():
        raise ValidationError("请先删除草稿中的课程标准内容条目，再修订逐页文本。")
    before_page_hash = page.content_hash
    before_version_hash = version.content_hash
    page.text = normalize_structured_text(text)
    page.extraction_method = CurriculumTextExtractionMethod.MANUAL
    page.mean_confidence = None
    page.quality_status = (
        CurriculumPageQualityStatus.COMPLETE
        if page.text
        else CurriculumPageQualityStatus.EMPTY
    )
    page.quality_message = "管理员人工修订，发布前需再次复核。"
    page.review_status = CurriculumPageReviewStatus.NEEDS_REVIEW
    page.reviewed_by = None
    page.reviewed_at = None
    page.save()
    records = [
        {"page_number": item.page_number, "text": item.text}
        for item in version.pages.order_by("page_number")
    ]
    structured = _structured_text_from_page_records(records)
    version.structured_text = structured
    version.structured_text_sha256 = _structured_hash(structured)
    version.extraction_status = (
        CurriculumExtractionStatus.COMPLETED
        if _page_record_char_count(records) >= 200
        else CurriculumExtractionStatus.PENDING
    )
    version.extraction_message = "逐页文本已由管理员人工修订。"
    version.extraction_engine = "manual_revision"
    version.extraction_engine_version = "1"
    version.extraction_config = {
        "strategy": "page_revision",
        "expected_page_count": version.pdf_page_count,
    }
    version.extracted_at = timezone.now()
    version.content_hash = canonical_hash(_version_semantic_content(version))
    version.save()
    from .retrieval import rebuild_retrieval_index

    if version.extraction_status == CurriculumExtractionStatus.COMPLETED:
        rebuild_retrieval_index(version, actor=actor)
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="page_text_updated",
        actor=actor,
        detail={
            "page_id": page.id,
            "page_number": page.page_number,
            "before_page_hash": before_page_hash,
            "after_page_hash": page.content_hash,
            "before_version_hash": before_version_hash,
            "after_version_hash": version.content_hash,
        },
    )
    return page


def reprocess_version_text(
    version: CurriculumStandardVersion,
    *,
    actor,
    enable_ocr: bool,
) -> CurriculumStandardVersion:
    initial = CurriculumStandardVersion.objects.get(pk=version.pk)
    if initial.status != CurriculumVersionStatus.DRAFT:
        raise ValidationError("只有草稿版本可以重新生成结构化文本。")
    initial_pdf_hash = initial.pdf_sha256
    initial_content_hash = initial.content_hash
    with initial.pdf_file.open("rb") as raw:
        extracted = extract_pdf_text(raw, allow_ocr=enable_ocr)
    with transaction.atomic():
        version = CurriculumStandardVersion.objects.select_for_update().get(pk=initial.pk)
        if version.status != CurriculumVersionStatus.DRAFT:
            raise ValidationError("处理期间版本已进入复核流程，本次结果未写入。")
        if (
            version.pdf_sha256 != initial_pdf_hash
            or version.content_hash != initial_content_hash
        ):
            raise ValidationError("处理期间课程标准草稿已变化，请重新执行。")
        version.nodes.all().delete()
        version.pages.all().delete()
        version.structured_text = extracted.structured_text
        version.structured_text_sha256 = _structured_hash(extracted.structured_text)
        version.extraction_status = extracted.status
        version.extraction_message = extracted.message
        version.extraction_engine = extracted.engine
        version.extraction_engine_version = extracted.engine_version
        version.extraction_config = extracted.config
        version.extracted_at = timezone.now()
        _save_page_records(version, extracted.page_records)
        if extracted.pages:
            create_suggested_framework_nodes(version=version, pages=extracted.pages)
        version.content_hash = canonical_hash(_version_semantic_content(version))
        version.save()
        from .retrieval import rebuild_retrieval_index

        if version.extraction_status == CurriculumExtractionStatus.COMPLETED:
            rebuild_retrieval_index(version, actor=actor)
        CurriculumStandardAuditLog.objects.create(
            version=version,
            action="text_reprocessed",
            actor=actor,
            detail={
                "enable_ocr": enable_ocr,
                "extraction_status": extracted.status,
                "page_count": len(extracted.page_records),
                "extraction_engine": extracted.engine,
                "extraction_engine_version": extracted.engine_version,
                "extraction_config": extracted.config,
            },
        )
    return version


@transaction.atomic
def discard_draft_version(
    version: CurriculumStandardVersion,
    *,
    actor,
) -> CurriculumStandardVersion:
    version = CurriculumStandardVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != CurriculumVersionStatus.DRAFT:
        raise ValidationError("已进入复核流程的课程标准版本不能删除。")
    if EvaluationPlanCurriculumReference.objects.filter(node__version=version).exists():
        raise ValidationError("该草稿已有评价方案引用，请先解除引用。")
    version.status = CurriculumVersionStatus.DISCARDED
    version.save(update_fields=["status"])
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="draft_discarded",
        actor=actor,
        detail={"content_hash": version.content_hash},
    )
    return version


def create_version(
    *,
    standard: CurriculumStandard,
    version_label: str,
    publication_year: int,
    effective_year: int | None,
    issued_by: str,
    source_url: str,
    official_title: str = "",
    source_note: str = "",
    pdf_file,
    structured_text: str,
    replaces_version: CurriculumStandardVersion | None,
    enable_ocr: bool = False,
    actor,
) -> CurriculumStandardVersion:
    validate_pdf_upload(pdf_file)
    if replaces_version and replaces_version.source_id != standard.id:
        raise ValidationError({"replaces_version": "被替换版本必须属于同一课程标准。"})

    pdf_hash = sha256_file(pdf_file)
    pdf_size = file_size_bytes(pdf_file)
    duplicate = standard.versions.filter(pdf_sha256=pdf_hash).first()
    if duplicate:
        raise ValidationError(
            {"pdf_file": f"该课程标准原文已登记为版本 {duplicate.version_label}。"}
        )
    actual_page_count = pdf_page_count(pdf_file)
    extracted = None
    clean_text = normalize_structured_text(structured_text)
    if clean_text:
        extraction_status = CurriculumExtractionStatus.COMPLETED
        extraction_message = "使用管理员提交并确认的结构化文本。"
        page_records = _manual_page_records(
            clean_text,
            expected_page_count=actual_page_count,
        )
        extraction_engine = "manual_upload"
        extraction_engine_version = "1"
        extraction_config = {
            "strategy": "page_marked_text",
            "expected_page_count": actual_page_count,
        }
    else:
        extracted = extract_pdf_text(pdf_file, allow_ocr=enable_ocr)
        clean_text = extracted.structured_text
        extraction_status = extracted.status
        extraction_message = extracted.message
        page_records = extracted.page_records
        extraction_engine = extracted.engine
        extraction_engine_version = extracted.engine_version
        extraction_config = extracted.config

    version = CurriculumStandardVersion(
        source=standard,
        version_label=str(version_label).strip(),
        publication_year=publication_year,
        effective_year=effective_year,
        title_snapshot=standard.title,
        official_title=str(official_title or standard.title).strip(),
        document_type_snapshot=standard.document_type,
        school_stage_snapshot=standard.school_stage,
        subject_code_snapshot=standard.subject_code,
        subject_name_snapshot=standard.subject_name,
        issued_by=str(issued_by or "中华人民共和国教育部").strip(),
        source_url=str(source_url or "").strip(),
        source_note=str(source_note or "").strip(),
        pdf_file=pdf_file,
        pdf_sha256=pdf_hash,
        pdf_size_bytes=pdf_size,
        pdf_page_count=actual_page_count,
        structured_text=clean_text,
        structured_text_sha256=_structured_hash(clean_text),
        extraction_status=extraction_status,
        extraction_message=extraction_message,
        extraction_engine=extraction_engine,
        extraction_engine_version=extraction_engine_version,
        extraction_config=extraction_config,
        extracted_at=timezone.now(),
        replaces_version=replaces_version,
        status=CurriculumVersionStatus.DRAFT,
        created_by=actor,
        content_hash="0" * 64,
    )
    source_pages = (
        extracted.pages
        if extracted is not None
        else [record.get("text", "") for record in page_records]
    )
    return _persist_new_version(
        version,
        page_records=page_records,
        source_pages=source_pages,
        actor=actor,
        audit_action="created",
        audit_detail={
            "pdf_sha256": version.pdf_sha256,
            "pdf_size_bytes": version.pdf_size_bytes,
            "extraction_status": version.extraction_status,
            "extraction_engine": version.extraction_engine,
            "extraction_engine_version": version.extraction_engine_version,
            "extraction_config": version.extraction_config,
            "replaces_version_id": version.replaces_version_id,
        },
    )


def create_version_from_existing_file(
    *,
    standard: CurriculumStandard,
    file_path: Path,
    media_root: Path,
    version_label: str,
    publication_year: int,
    effective_year: int | None,
    issued_by: str,
    source_url: str,
    official_title: str,
    source_note: str,
    replaces_version: CurriculumStandardVersion | None,
    enable_ocr: bool = False,
    actor,
) -> CurriculumStandardVersion:
    relative_name = file_path.resolve().relative_to(media_root.resolve()).as_posix()
    with file_path.open("rb") as raw:
        validate_pdf_upload(File(raw, name=file_path.name))
        pdf_hash = sha256_file(raw)
        pdf_size = file_size_bytes(raw)
        actual_page_count = pdf_page_count(raw)

    duplicate = standard.versions.filter(pdf_sha256=pdf_hash).first()
    if duplicate:
        raise ValidationError(
            {"pdf_file": f"该课程标准原文已登记为版本 {duplicate.version_label}。"}
        )
    with file_path.open("rb") as raw:
        extracted = extract_pdf_text(raw, allow_ocr=enable_ocr)

    clean_text = extracted.structured_text
    version = CurriculumStandardVersion(
        source=standard,
        version_label=version_label,
        publication_year=publication_year,
        effective_year=effective_year,
        title_snapshot=standard.title,
        official_title=str(official_title or standard.title).strip(),
        document_type_snapshot=standard.document_type,
        school_stage_snapshot=standard.school_stage,
        subject_code_snapshot=standard.subject_code,
        subject_name_snapshot=standard.subject_name,
        issued_by=issued_by,
        source_url=source_url,
        source_note=source_note,
        pdf_file=relative_name,
        pdf_sha256=pdf_hash,
        pdf_size_bytes=pdf_size,
        pdf_page_count=actual_page_count,
        structured_text=clean_text,
        structured_text_sha256=_structured_hash(clean_text),
        extraction_status=extracted.status,
        extraction_message=extracted.message,
        extraction_engine=extracted.engine,
        extraction_engine_version=extracted.engine_version,
        extraction_config=extracted.config,
        extracted_at=timezone.now(),
        replaces_version=replaces_version,
        status=CurriculumVersionStatus.DRAFT,
        created_by=actor,
        content_hash="0" * 64,
    )
    return _persist_new_version(
        version,
        page_records=extracted.page_records,
        source_pages=extracted.pages,
        actor=actor,
        audit_action="imported",
        audit_detail={
            "source_path": relative_name,
            "pdf_sha256": pdf_hash,
            "pdf_size_bytes": pdf_size,
            "extraction_status": extracted.status,
            "extraction_engine": extracted.engine,
            "extraction_engine_version": extracted.engine_version,
            "extraction_config": extracted.config,
        },
    )


def _line_is_heading(line: str, keyword_pattern: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    if len(compact) > 32:
        return False
    compact = re.sub(
        r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）)",
        "",
        compact,
    )
    return bool(re.search(keyword_pattern, compact)) and not re.search(r"\.{2,}|…{2,}", compact)


def _find_heading(
    rows: list[tuple[int, str]],
    pattern: str,
    *,
    minimum_page: int = 3,
    subsection: bool = False,
) -> int | None:
    candidates = [
        index
        for index, (page, line) in enumerate(rows)
        if page >= minimum_page and _line_is_heading(line, pattern)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda start: sum(
            len(line)
            for _, line in rows[start:_section_end(rows, start, subsection=subsection)]
        ),
    )


def _section_end(rows: list[tuple[int, str]], start: int, *, subsection: bool) -> int:
    start_heading = re.sub(r"\s+", "", rows[start][1])
    containing_major_heading = None
    if subsection:
        for previous in range(start - 1, -1, -1):
            candidate = re.sub(r"\s+", "", rows[previous][1])
            if re.match(r"^[一二三四五六七八九十]+、", candidate):
                containing_major_heading = candidate
                break
    for index in range(start + 1, len(rows)):
        line = re.sub(r"\s+", "", rows[index][1])
        if subsection and re.match(r"^（[一二三四五六七八九十]+）", line):
            if line == start_heading:
                continue
            return index
        if re.match(r"^[一二三四五六七八九十]+、", line):
            # Printed standards often repeat the current major heading in the
            # page header. It is continuation context, not a new section.
            if line == start_heading or (
                subsection and line == containing_major_heading
            ):
                continue
            return index
    return len(rows)


def suggest_framework_nodes(pages: list[str]) -> list[dict]:
    rows: list[tuple[int, str]] = []
    for page_number, page_text in enumerate(pages, start=1):
        rows.extend(
            (page_number, line.strip())
            for line in page_text.splitlines()
            if line.strip()
        )
    definitions = (
        (
            CurriculumNodeType.CORE_COMPETENCY,
            "CS.CORE_COMPETENCY",
            "核心素养",
            r"^(学科)?核心素养(内涵)?$",
            True,
        ),
        (
            CurriculumNodeType.COURSE_OBJECTIVE,
            "CS.COURSE_OBJECTIVE",
            "课程目标",
            r"^课程目标$|^目标要求$",
            False,
        ),
        (
            CurriculumNodeType.COURSE_CONTENT,
            "CS.COURSE_CONTENT",
            "课程内容",
            r"^课程内容$",
            False,
        ),
        (
            CurriculumNodeType.ACADEMIC_QUALITY,
            "CS.ACADEMIC_QUALITY",
            "学业质量",
            r"^学业质量$",
            False,
        ),
    )
    suggestions = []
    for sort_order, (node_type, code, title, pattern, subsection) in enumerate(definitions):
        start = _find_heading(rows, pattern, subsection=subsection)
        if start is None:
            continue
        end = _section_end(rows, start, subsection=subsection)
        selected = rows[start:end]
        content = normalize_structured_text("\n".join(line for _, line in selected))
        if len(content) < 30:
            continue
        suggestions.append(
            {
                "node_type": node_type,
                "code": code,
                "title": title,
                "content": content,
                "source_page_start": selected[0][0],
                "source_page_end": selected[-1][0],
                "source_paragraph": selected[0][1][:240],
                "sort_order": sort_order,
            }
        )
    return suggestions


def create_suggested_framework_nodes(
    *,
    version: CurriculumStandardVersion,
    pages: list[str],
) -> list[CurriculumStandardNode]:
    if version.status != CurriculumVersionStatus.DRAFT:
        return []
    created = []
    for values in suggest_framework_nodes(pages):
        if version.nodes.filter(code=values["code"]).exists():
            continue
        created.append(CurriculumStandardNode.objects.create(version=version, **values))
    return created


def validate_version_for_review(version: CurriculumStandardVersion) -> None:
    errors = {}
    if version.extraction_status != CurriculumExtractionStatus.COMPLETED:
        errors["structured_text"] = "发布前必须完成可读取文本处理。"
    source_char_count = sum(version.pages.values_list("char_count", flat=True))
    if source_char_count < 200:
        errors["structured_text"] = "结构化文本内容过少，请核对 PDF 转换结果。"
    if not version.pdf_file or len(version.pdf_sha256) != 64:
        errors["pdf_file"] = "缺少可核验的课程标准 PDF。"
    if version.document_type_snapshot == CurriculumDocumentType.SUBJECT_STANDARD:
        present = set(version.nodes.values_list("node_type", flat=True))
        missing = REQUIRED_ALIGNMENT_NODE_TYPES - present
        if missing:
            labels = dict(CurriculumNodeType.choices)
            errors["nodes"] = "缺少以下课程标准内容条目：" + "、".join(
                labels[item] for item in sorted(missing)
            )
        for node in version.nodes.all():
            if not node.source_paragraph.strip():
                errors["nodes"] = "每个课程标准内容条目必须填写原文位置。"
                break
            page_text = "\n".join(
                version.pages.filter(
                    page_number__gte=node.source_page_start,
                    page_number__lte=node.source_page_end,
                ).values_list("text", flat=True)
            )
            normalized_location = re.sub(r"\s+", "", node.source_paragraph)
            normalized_page_text = re.sub(r"\s+", "", page_text)
            if normalized_location not in normalized_page_text:
                errors["nodes"] = (
                    f"内容条目 {node.code} 的原文位置无法在所填页码范围内核验。"
                )
                break
            normalized_content = re.sub(r"\s+", "", node.content)
            if normalized_content not in normalized_page_text:
                errors["nodes"] = (
                    f"内容条目 {node.code} 的原文内容无法在所填页码范围内连续核验。"
                )
                break
    if version.nodes.filter(source_page_start__lt=1).exists():
        errors["nodes"] = "课程标准内容条目必须保留 PDF 原文页码。"
    pages = list(version.pages.order_by("page_number"))
    if not pages:
        errors["pages"] = "发布前必须生成逐页可检索文本。"
    elif [page.page_number for page in pages] != list(
        range(1, version.pdf_page_count + 1)
    ):
        errors["pages"] = (
            f"逐页文本必须与 PDF 的 {version.pdf_page_count} 页完整对应。"
        )
    if errors:
        raise ValidationError(errors)


def validate_version_for_publish(version: CurriculumStandardVersion) -> None:
    validate_version_for_review(version)
    errors = {}
    if version.pages.exclude(
        review_status=CurriculumPageReviewStatus.REVIEWED
    ).exists():
        errors["pages"] = "所有逐页文本完成复核后才能发布。"
    if version.pages.filter(quality_status=CurriculumPageQualityStatus.FAILED).exists():
        errors["pages"] = "仍有处理失败页，修复并重新复核后才能发布。"
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def submit_version_for_review(version: CurriculumStandardVersion, *, actor) -> CurriculumStandardVersion:
    version = CurriculumStandardVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != CurriculumVersionStatus.DRAFT:
        raise ValidationError("只有草稿版本可以提交复核。")
    if version.processing_jobs.filter(
        status__in=[
            CurriculumProcessingJobStatus.QUEUED,
            CurriculumProcessingJobStatus.RUNNING,
            CurriculumProcessingJobStatus.CANCELLING,
        ]
    ).exists():
        raise ValidationError("课程标准仍有后台文本处理任务，完成或取消后才能提交复核。")
    validate_version_for_review(version)
    refresh_version_hash(version)
    version.status = CurriculumVersionStatus.REVIEW_PENDING
    version.submitted_by = actor
    version.submitted_at = timezone.now()
    version.reviewed_by = None
    version.reviewed_at = None
    version.review_note = ""
    version.independent_review = False
    version.independent_publication = False
    version.governance_waiver_note = ""
    version.save(
        update_fields=[
            "status",
            "submitted_by",
            "submitted_at",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "independent_review",
            "independent_publication",
            "governance_waiver_note",
        ]
    )
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="submitted_for_review",
        actor=actor,
        detail={"content_hash": version.content_hash},
    )
    return version


@transaction.atomic
def review_version(
    version: CurriculumStandardVersion,
    *,
    actor,
    approved: bool,
    note: str,
) -> CurriculumStandardVersion:
    version = CurriculumStandardVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != CurriculumVersionStatus.REVIEW_PENDING:
        raise ValidationError("只有待复核版本可以登记复核结果。")
    reviewer_is_independent = actor.id not in {
        version.created_by_id,
        version.submitted_by_id,
    }
    if settings.CURRICULUM_REQUIRE_SEPARATE_REVIEWERS and not reviewer_is_independent:
        raise ValidationError("复核人不能与版本创建人或提交人相同。")
    if approved:
        validate_version_for_publish(version)
    version.review_note = str(note or "").strip()
    version.independent_review = reviewer_is_independent
    version.governance_waiver_note = (
        "开发环境仅有一个超级管理员，本次未完成独立复核，不得据此声称已通过生产治理审查。"
        if approved and not reviewer_is_independent
        else ""
    )
    version.reviewed_by = actor
    version.reviewed_at = timezone.now()
    version.status = (
        CurriculumVersionStatus.REVIEWED if approved else CurriculumVersionStatus.DRAFT
    )
    update_fields = [
        "review_note",
        "reviewed_by",
        "reviewed_at",
        "status",
        "independent_review",
        "governance_waiver_note",
    ]
    if not approved:
        version.submitted_by = None
        version.submitted_at = None
        update_fields.extend(["submitted_by", "submitted_at"])
    version.save(update_fields=update_fields)
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="review_approved" if approved else "review_returned",
        actor=actor,
        detail={
            "note": version.review_note,
            "independent_review": version.independent_review,
            "governance_waiver": version.governance_waiver_note,
        },
    )
    return version


def _archive_current_version(
    standard: CurriculumStandard,
    *,
    actor,
    except_version_id: int | None = None,
) -> None:
    current = standard.current_version
    if current is None or current.id == except_version_id:
        return
    current.status = CurriculumVersionStatus.ARCHIVED
    current.archived_by = actor
    current.archived_at = timezone.now()
    current.save(update_fields=["status", "archived_by", "archived_at"])
    CurriculumStandardAuditLog.objects.create(
        version=current,
        action="superseded",
        actor=actor,
        detail={"replacement_version_id": except_version_id},
    )


@transaction.atomic
def publish_version(version: CurriculumStandardVersion, *, actor) -> CurriculumStandardVersion:
    version = (
        CurriculumStandardVersion.objects.select_for_update()
        .select_related("source__current_version")
        .get(pk=version.pk)
    )
    if version.status != CurriculumVersionStatus.REVIEWED:
        raise ValidationError("课程标准版本完成复核后才能发布。")
    publisher_is_independent = actor.id != version.reviewed_by_id
    if settings.CURRICULUM_REQUIRE_SEPARATE_REVIEWERS and not publisher_is_independent:
        raise ValidationError("发布人不能与复核人相同。")
    validate_version_for_publish(version)
    from .retrieval import rebuild_retrieval_index, retrieval_index_is_current

    if not retrieval_index_is_current(version):
        rebuild_retrieval_index(version, actor=actor)
    standard = CurriculumStandard.objects.select_for_update().get(pk=version.source_id)
    _archive_current_version(standard, actor=actor, except_version_id=version.id)
    now = timezone.now()
    version.status = CurriculumVersionStatus.PUBLISHED
    version.published_by = actor
    version.published_at = now
    version.independent_publication = publisher_is_independent
    if not publisher_is_independent:
        version.governance_waiver_note = (
            "开发环境仅有一个超级管理员，本次复核与发布未实现职责分离。"
        )
    version.archived_by = None
    version.archived_at = None
    version.save(
        update_fields=[
            "status",
            "published_by",
            "published_at",
            "independent_publication",
            "governance_waiver_note",
            "archived_by",
            "archived_at",
        ]
    )
    standard.current_version = version
    standard.updated_by = actor
    standard.save(update_fields=["current_version", "updated_by", "updated_at"])
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="published",
        actor=actor,
        detail={
            "content_hash": version.content_hash,
            "independent_review": version.independent_review,
            "independent_publication": version.independent_publication,
            "governance_waiver": version.governance_waiver_note,
        },
    )
    return version


@transaction.atomic
def review_version_pages(
    version: CurriculumStandardVersion,
    *,
    actor,
    page_ids: list[int] | None = None,
) -> int:
    version = CurriculumStandardVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != CurriculumVersionStatus.REVIEW_PENDING:
        raise ValidationError("只有待复核版本可以确认逐页文本。")
    if (
        settings.CURRICULUM_REQUIRE_SEPARATE_REVIEWERS
        and actor.id in {version.created_by_id, version.submitted_by_id}
    ):
        raise ValidationError("逐页文本复核人不能与版本创建人或提交人相同。")
    pages = version.pages.all()
    if page_ids is not None:
        normalized = list(dict.fromkeys(int(page_id) for page_id in page_ids))
        pages = pages.filter(pk__in=normalized)
        if pages.count() != len(normalized):
            raise ValidationError("部分逐页文本记录不存在或不属于该版本。")
    now = timezone.now()
    count = pages.update(
        review_status=CurriculumPageReviewStatus.REVIEWED,
        reviewed_by=actor,
        reviewed_at=now,
    )
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="pages_reviewed",
        actor=actor,
        detail={"page_count": count, "page_ids": page_ids or "all"},
    )
    return count


@transaction.atomic
def archive_version(version: CurriculumStandardVersion, *, actor) -> CurriculumStandardVersion:
    version = CurriculumStandardVersion.objects.select_for_update().select_related("source").get(
        pk=version.pk
    )
    if version.status != CurriculumVersionStatus.PUBLISHED:
        raise ValidationError("只有已发布课程标准版本可以归档。")
    version.status = CurriculumVersionStatus.ARCHIVED
    version.archived_by = actor
    version.archived_at = timezone.now()
    version.save(update_fields=["status", "archived_by", "archived_at"])
    standard = CurriculumStandard.objects.select_for_update().get(pk=version.source_id)
    if standard.current_version_id == version.id:
        standard.current_version = None
        standard.updated_by = actor
        standard.save(update_fields=["current_version", "updated_by", "updated_at"])
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="archived",
        actor=actor,
    )
    return version


@transaction.atomic
def restore_version(version: CurriculumStandardVersion, *, actor) -> CurriculumStandardVersion:
    version = CurriculumStandardVersion.objects.select_for_update().select_related("source").get(
        pk=version.pk
    )
    if version.status != CurriculumVersionStatus.ARCHIVED:
        raise ValidationError("只有已归档课程标准版本可以恢复为当前版本。")
    standard = CurriculumStandard.objects.select_for_update().get(pk=version.source_id)
    _archive_current_version(standard, actor=actor, except_version_id=version.id)
    version.status = CurriculumVersionStatus.PUBLISHED
    version.archived_by = None
    version.archived_at = None
    version.save(update_fields=["status", "archived_by", "archived_at"])
    standard.current_version = version
    standard.updated_by = actor
    standard.save(update_fields=["current_version", "updated_by", "updated_at"])
    CurriculumStandardAuditLog.objects.create(
        version=version,
        action="restored_as_current",
        actor=actor,
        detail={"content_hash": version.content_hash},
    )
    return version


def validate_curriculum_nodes(
    nodes: Iterable[CurriculumStandardNode],
    *,
    require_complete: bool = True,
) -> list[CurriculumStandardNode]:
    rows = list(nodes)
    if not rows:
        return rows
    version_ids = {row.version_id for row in rows}
    if len(version_ids) != 1:
        raise ValidationError("一份评价方案必须引用同一课程标准版本中的内容条目。")
    version = rows[0].version
    if version.status != CurriculumVersionStatus.PUBLISHED:
        raise ValidationError("评价方案只能引用当前已发布的课程标准版本。")
    if version.source.current_version_id != version.id:
        raise ValidationError("新评价方案只能引用课程标准的当前版本。")
    if version.document_type_snapshot != CurriculumDocumentType.SUBJECT_STANDARD:
        raise ValidationError("评价方案必须引用学科课程标准，而不是课程方案。")
    present = {row.node_type for row in rows}
    missing = REQUIRED_ALIGNMENT_NODE_TYPES - present
    if require_complete and missing:
        labels = dict(CurriculumNodeType.choices)
        raise ValidationError(
            "课程标准引用必须覆盖："
            + "、".join(labels[item] for item in sorted(missing))
            + "。"
        )
    return rows


def _normalized_subject_name(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    text = re.sub(r"(?:学科|课程)$", "", text)
    for group in SUBJECT_NAME_EQUIVALENTS:
        if text in group:
            return sorted(group)[0]
    return text


def subject_names_equivalent(left: str, right: str) -> bool:
    return bool(
        _normalized_subject_name(left)
        and _normalized_subject_name(left) == _normalized_subject_name(right)
    )


def validate_plan_subject_alignment(plan, nodes: Iterable[CurriculumStandardNode]) -> None:
    rows = list(nodes)
    if not rows:
        return
    local_subject = _normalized_subject_name(plan.subject.name)
    standard_subject = _normalized_subject_name(
        rows[0].version.subject_name_snapshot
    )
    if not local_subject or local_subject != standard_subject:
        raise ValidationError(
            f"评价方案学科“{plan.subject.name}”与所选课程标准学科"
            f"“{rows[0].version.subject_name_snapshot}”不一致。"
        )


@transaction.atomic
def replace_plan_curriculum_references(*, plan, node_ids: list[int], actor) -> None:
    normalized = list(dict.fromkeys(int(node_id) for node_id in node_ids))
    nodes = list(
        CurriculumStandardNode.objects.select_related("version__source").filter(
            id__in=normalized
        )
    )
    if len(nodes) != len(normalized):
        raise ValidationError("部分课程标准内容条目不存在或不可访问。")
    validate_curriculum_nodes(nodes, require_complete=False)
    validate_plan_subject_alignment(plan, nodes)
    EvaluationPlanCurriculumReference.objects.filter(plan=plan).delete()
    EvaluationPlanCurriculumReference.objects.bulk_create(
        [
            EvaluationPlanCurriculumReference(plan=plan, node=node, created_by=actor)
            for node in nodes
        ]
    )


def curriculum_reference_payload(plan) -> list[dict]:
    refs = list(
        plan.curriculum_references.select_related("node__version__source").order_by(
            "node__sort_order", "node_id"
        )
    )
    if not refs:
        return []
    nodes = [ref.node for ref in refs]
    validate_curriculum_nodes(nodes, require_complete=True)
    validate_plan_subject_alignment(plan, nodes)
    return [
        {
            "node_type": ref.node.node_type,
            "node_code": ref.node.code,
            "node_content_hash": ref.node.content_hash,
            "curriculum_version_hash": ref.node.version.content_hash,
            "alignment_explanation": ref.alignment_explanation,
        }
        for ref in refs
    ]


def copy_plan_curriculum_references(*, plan, plan_version) -> None:
    refs = list(
        plan.curriculum_references.select_related("node__version").order_by("node_id")
    )
    for ref in refs:
        node = ref.node
        version = node.version
        EvaluationPlanVersionCurriculumReference.objects.create(
            plan_version=plan_version,
            node=node,
            curriculum_version_hash=version.content_hash,
            node_content_hash=node.content_hash,
            standard_title=version.official_title,
            version_label=version.version_label,
            node_type=node.node_type,
            node_code=node.code,
            node_title=node.title,
            source_page_start=node.source_page_start,
            source_page_end=node.source_page_end,
            source_paragraph=node.source_paragraph,
            alignment_explanation=ref.alignment_explanation,
        )


def compare_curriculum_versions(
    left: CurriculumStandardVersion,
    right: CurriculumStandardVersion,
) -> dict:
    if left.source_id != right.source_id:
        raise ValidationError("只能比较同一课程标准档案下的两个版本。")
    left_nodes = {node.code: node for node in left.nodes.all()}
    right_nodes = {node.code: node for node in right.nodes.all()}
    comparisons = []
    for code in sorted(set(left_nodes) | set(right_nodes)):
        before = left_nodes.get(code)
        after = right_nodes.get(code)
        if before is None:
            change_type = "added"
        elif after is None:
            change_type = "removed"
        elif before.content_hash == after.content_hash:
            change_type = "unchanged"
        else:
            change_type = "modified"
        comparisons.append(
            {
                "code": code,
                "change_type": change_type,
                "before": (
                    {
                        "id": before.id,
                        "node_type": before.node_type,
                        "title": before.title,
                        "content_hash": before.content_hash,
                        "source_page_start": before.source_page_start,
                        "source_page_end": before.source_page_end,
                        "source_paragraph": before.source_paragraph,
                    }
                    if before
                    else None
                ),
                "after": (
                    {
                        "id": after.id,
                        "node_type": after.node_type,
                        "title": after.title,
                        "content_hash": after.content_hash,
                        "source_page_start": after.source_page_start,
                        "source_page_end": after.source_page_end,
                        "source_paragraph": after.source_paragraph,
                    }
                    if after
                    else None
                ),
            }
        )
    metadata_fields = (
        "version_label",
        "publication_year",
        "effective_year",
        "issued_by",
        "source_url",
        "source_note",
        "official_title",
        "pdf_sha256",
        "structured_text_sha256",
        "content_hash",
    )
    metadata_changes = [
        {
            "field": field,
            "before": getattr(left, field),
            "after": getattr(right, field),
        }
        for field in metadata_fields
        if getattr(left, field) != getattr(right, field)
    ]
    counts = {
        change_type: sum(
            1 for row in comparisons if row["change_type"] == change_type
        )
        for change_type in ("added", "removed", "modified", "unchanged")
    }
    return {
        "standard_id": left.source_id,
        "standard_title": left.title_snapshot,
        "from_version": {
            "id": left.id,
            "version_label": left.version_label,
            "content_hash": left.content_hash,
            "pdf_sha256": left.pdf_sha256,
            "structured_text_sha256": left.structured_text_sha256,
        },
        "to_version": {
            "id": right.id,
            "version_label": right.version_label,
            "content_hash": right.content_hash,
            "pdf_sha256": right.pdf_sha256,
            "structured_text_sha256": right.structured_text_sha256,
        },
        "metadata_changes": metadata_changes,
        "content_item_counts": counts,
        "content_items": comparisons,
    }
