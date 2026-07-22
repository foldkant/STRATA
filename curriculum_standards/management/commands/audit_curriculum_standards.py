from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from django.core.management.base import BaseCommand

from curriculum_standards.models import (
    CurriculumExtractionStatus,
    CurriculumRetrievalIndex,
    CurriculumStandard,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    canonical_hash,
)
from curriculum_standards.retrieval import _chunk_specs, retrieval_index_is_current, sha256_text
from curriculum_standards.services import _structured_hash, _version_semantic_content


class Command(BaseCommand):
    help = "只读核对课程标准文件、逐页原文、版本关系和检索片段的完整性。"

    def add_arguments(self, parser):
        parser.add_argument("--version-id", action="append", type=int, dest="version_ids")
        parser.add_argument("--published-only", action="store_true")
        parser.add_argument("--skip-pdf-hash", action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument(
            "--strict",
            action="store_true",
            help="存在错误或未完成处理/发布警告时返回非零退出码。",
        )

    def handle(self, *args, **options):
        versions = CurriculumStandardVersion.objects.select_related(
            "source",
            "replaces_version",
        ).prefetch_related("pages", "nodes__parent", "retrieval_chunks")
        version_ids = list(dict.fromkeys(options.get("version_ids") or []))
        if version_ids:
            versions = versions.filter(pk__in=version_ids)
        if options["published_only"]:
            versions = versions.filter(status=CurriculumVersionStatus.PUBLISHED)
        versions = list(versions.order_by("source_id", "publication_year", "id"))

        errors = []
        warnings = []
        rows = []
        missing_version_ids = set(version_ids) - {version.id for version in versions}
        for missing_id in sorted(missing_version_ids):
            errors.append(
                {
                    "version_id": missing_id,
                    "code": "version_missing",
                    "message": "指定的课程标准版本不存在。",
                }
            )

        def add_issue(collection, version, code, message):
            collection.append(
                {
                    "version_id": version.id if version else None,
                    "code": code,
                    "message": message,
                }
            )

        for version in versions:
            pages = list(version.pages.order_by("page_number"))
            nodes = list(version.nodes.order_by("sort_order", "code", "id"))
            row = {
                "version_id": version.id,
                "standard_id": version.source_id,
                "title": version.official_title,
                "version_label": version.version_label,
                "status": version.status,
                "extraction_status": version.extraction_status,
                "pdf_page_count": version.pdf_page_count,
                "page_count": len(pages),
                "node_count": len(nodes),
                "retrieval_chunk_count": version.retrieval_chunks.count(),
            }
            storage = version.pdf_file.storage if version.pdf_file else None
            stored_name = str(version.pdf_file.name or "") if version.pdf_file else ""
            if storage is None or not stored_name or not storage.exists(stored_name):
                add_issue(errors, version, "pdf_missing", "原始 PDF 文件不存在。")
            else:
                if int(version.pdf_file.size) != version.pdf_size_bytes:
                    add_issue(errors, version, "pdf_size_mismatch", "PDF 文件大小与版本记录不一致。")
                if not options["skip_pdf_hash"]:
                    digest = hashlib.sha256()
                    with version.pdf_file.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                    if digest.hexdigest() != version.pdf_sha256:
                        add_issue(errors, version, "pdf_hash_mismatch", "PDF 文件 SHA-256 与版本记录不一致。")
            if not version.source_note.strip() and not version.source_url.strip():
                add_issue(errors, version, "source_missing", "课程标准版本缺少来源地址和来源说明。")
            if version.structured_text_sha256 != _structured_hash(version.structured_text):
                add_issue(errors, version, "structured_hash_mismatch", "结构化文本 SHA-256 不一致。")
            if version.content_hash != canonical_hash(_version_semantic_content(version)):
                add_issue(errors, version, "version_hash_mismatch", "课程标准版本内容哈希不一致。")

            expected_pages = list(range(1, version.pdf_page_count + 1))
            actual_pages = [page.page_number for page in pages]
            if actual_pages != expected_pages:
                add_issue(errors, version, "page_sequence_invalid", "逐页原文未与 PDF 页码完整连续对应。")
            for page in pages:
                if page.char_count != len(page.text):
                    add_issue(errors, version, "page_char_count_mismatch", f"第 {page.page_number} 页字符数不一致。")
                if page.content_hash != canonical_hash(page.semantic_content()):
                    add_issue(errors, version, "page_hash_mismatch", f"第 {page.page_number} 页内容哈希不一致。")

            page_by_number = {page.page_number: page for page in pages}
            for node in nodes:
                if node.content_hash != canonical_hash(node.semantic_content()):
                    add_issue(errors, version, "content_item_hash_mismatch", f"内容条目 {node.code} 哈希不一致。")
                anchored = [
                    page_by_number[number]
                    for number in range(node.source_page_start, node.source_page_end + 1)
                    if number in page_by_number
                ]
                if len(anchored) != node.source_page_end - node.source_page_start + 1:
                    add_issue(errors, version, "content_item_pages_missing", f"内容条目 {node.code} 引用页不存在。")
                    continue
                source_text = re.sub(r"\s+", "", "\n".join(page.text for page in anchored))
                if re.sub(r"\s+", "", node.content) not in source_text:
                    add_issue(errors, version, "content_item_text_untraceable", f"内容条目 {node.code} 无法回到所标页码原文。")
                if node.source_paragraph.strip() and re.sub(r"\s+", "", node.source_paragraph) not in source_text:
                    add_issue(errors, version, "content_item_location_untraceable", f"内容条目 {node.code} 的原文位置无法核对。")

            if version.replaces_version_id:
                if version.replaces_version.source_id != version.source_id:
                    add_issue(errors, version, "replacement_cross_standard", "替代关系跨越了课程标准档案。")
                if not CurriculumStandardVersion.objects.filter(pk=version.replaces_version_id).exists():
                    add_issue(errors, version, "replacement_missing", "被替换的历史版本不存在。")

            if version.extraction_status == CurriculumExtractionStatus.COMPLETED:
                try:
                    index = version.retrieval_index
                except CurriculumRetrievalIndex.DoesNotExist:
                    index = None
                if index is None:
                    target = errors if version.status == CurriculumVersionStatus.PUBLISHED else warnings
                    add_issue(target, version, "retrieval_index_missing", "尚未建立课程标准检索索引。")
                else:
                    if not retrieval_index_is_current(version):
                        add_issue(errors, version, "retrieval_index_stale", "检索索引与课程标准版本哈希不一致。")
                    expected_specs = _chunk_specs(
                        version,
                        max_chars=index.max_chars,
                        overlap_chars=index.overlap_chars,
                    )
                    expected_by_id = {item["chunk_id"]: item for item in expected_specs}
                    actual = list(index.chunks.select_related("source_page", "source_node"))
                    if set(expected_by_id) != {chunk.chunk_id for chunk in actual}:
                        add_issue(errors, version, "retrieval_chunk_set_mismatch", "稳定检索片段 ID 集合与原文重建结果不一致。")
                    for chunk in actual:
                        spec = expected_by_id.get(chunk.chunk_id)
                        if spec is None:
                            continue
                        trace_fields = (
                            "source_kind",
                            "source_locator",
                            "source_object_id",
                            "source_page_id",
                            "source_node_id",
                            "ordinal",
                            "char_start",
                            "char_end",
                            "source_text_sha256",
                            "source_content_hash",
                            "version_content_hash",
                            "pdf_sha256",
                            "source_page_start",
                            "source_page_end",
                        )
                        if any(getattr(chunk, field) != spec[field] for field in trace_fields):
                            add_issue(errors, version, "retrieval_chunk_trace_mismatch", f"检索片段 {chunk.chunk_id} 的版本、页码或原文锚点不一致。")
                        if chunk.text != spec["text"] or chunk.content_sha256 != sha256_text(chunk.text):
                            add_issue(errors, version, "retrieval_chunk_text_mismatch", f"检索片段 {chunk.chunk_id} 正文或哈希不一致。")
                        if chunk.source_page_hashes != spec["source_page_hashes"]:
                            add_issue(errors, version, "retrieval_chunk_trace_mismatch", f"检索片段 {chunk.chunk_id} 页码原文哈希不一致。")
            else:
                add_issue(warnings, version, "text_processing_incomplete", "课程标准文本处理尚未完成。")
            if version.status not in {
                CurriculumVersionStatus.PUBLISHED,
                CurriculumVersionStatus.ARCHIVED,
            }:
                add_issue(warnings, version, "version_unpublished", "课程标准版本尚未完成复核发布。")
            rows.append(row)

        standards = CurriculumStandard.objects.select_related("current_version").all()
        if version_ids or options["published_only"]:
            standards = standards.filter(pk__in={version.source_id for version in versions})
        for standard in standards:
            if standard.is_active and standard.current_version_id is None:
                warnings.append(
                    {
                        "version_id": None,
                        "standard_id": standard.id,
                        "code": "current_version_missing",
                        "message": f"启用中的课程标准档案“{standard.title}”尚无当前发布版本。",
                    }
                )
            if standard.current_version_id and (
                standard.current_version.source_id != standard.id
                or standard.current_version.status != CurriculumVersionStatus.PUBLISHED
            ):
                errors.append(
                    {
                        "version_id": standard.current_version_id,
                        "standard_id": standard.id,
                        "code": "current_version_invalid",
                        "message": "当前使用版本不属于本档案或不是已发布状态。",
                    }
                )

        result = {
            "read_only": True,
            "version_count": len(rows),
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "extraction_status_counts": dict(Counter(row["extraction_status"] for row in rows)),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
            "versions": rows,
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                f"versions={len(rows)} errors={len(errors)} warnings={len(warnings)} read_only=true"
            )
            for issue in [*errors, *warnings]:
                self.stdout.write(
                    f"{issue['code']} version={issue.get('version_id')} {issue['message']}"
                )
        if errors or (options["strict"] and warnings):
            raise SystemExit(2)
