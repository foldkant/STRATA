from __future__ import annotations

import io
import json
import shutil
import tempfile
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter
from rest_framework.test import APIClient

from accounts.models import User
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumRetrievalChunk,
    CurriculumRetrievalSourceKind,
    CurriculumStandard,
    CurriculumStandardAuditLog,
    CurriculumStandardNode,
    CurriculumStandardVersion,
)
from curriculum_standards.retrieval import (
    rebuild_retrieval_index,
    retrieval_index_is_current,
    sha256_text,
    split_retrieval_text,
)
from curriculum_standards.services import (
    create_version,
    publish_version,
    refresh_version_hash,
    review_version,
    review_version_pages,
    submit_version_for_review,
)


def pdf_upload(pages: int = 4) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    writer.write(buffer)
    return SimpleUploadedFile("standard.pdf", buffer.getvalue(), content_type="application/pdf")


def page_texts(marker: str = "") -> list[str]:
    return [
        f"核心素养原文{marker}" + "数字意识与计算思维。" * 90,
        f"课程目标原文{marker}" + "运用信息科技解决真实问题。" * 80,
        f"课程内容原文{marker}" + "数据、算法与网络学习内容。" * 80,
        f"学业质量原文{marker}" + "能够在真实情境中综合运用知识。" * 80,
    ]


def marked_text(marker: str = "") -> str:
    return "\n\n".join(
        f"# PDF 第 {number} 页\n\n{text}"
        for number, text in enumerate(page_texts(marker), start=1)
    )


@override_settings(CURRICULUM_REQUIRE_SEPARATE_REVIEWERS=False)
class CurriculumRetrievalTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="curriculum-retrieval-tests-")
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))
        self.admin = User.objects.create_user(
            username="retrieval_admin",
            password="password",
            role=User.Role.SUPER_ADMIN,
        )
        self.teacher = User.objects.create_user(
            username="retrieval_teacher",
            password="password",
            role=User.Role.TEACHER,
        )
        self.standard = CurriculumStandard.objects.create(
            title="普通高中信息科技课程标准",
            document_type=CurriculumDocumentType.SUBJECT_STANDARD,
            school_stage="k10_k12",
            subject_code="information_technology",
            subject_name="信息科技",
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.version = create_version(
            standard=self.standard,
            version_label="2017-2025",
            publication_year=2025,
            effective_year=2025,
            issued_by="中华人民共和国教育部",
            source_url="https://example.edu/standard.pdf",
            official_title="普通高中信息科技课程标准（2017年版2025年修订）",
            source_note="测试使用的可追溯课程标准原文。",
            pdf_file=pdf_upload(),
            structured_text=marked_text(),
            replaces_version=None,
            actor=self.admin,
        )
        definitions = (
            (CurriculumNodeType.CORE_COMPETENCY, "CS.CORE", "核心素养", 1),
            (CurriculumNodeType.COURSE_OBJECTIVE, "CS.OBJECTIVE", "课程目标", 2),
            (CurriculumNodeType.COURSE_CONTENT, "CS.CONTENT", "课程内容", 3),
            (CurriculumNodeType.ACADEMIC_QUALITY, "CS.QUALITY", "学业质量", 4),
        )
        texts = page_texts()
        for order, (node_type, code, title, page_number) in enumerate(definitions):
            CurriculumStandardNode.objects.create(
                version=self.version,
                node_type=node_type,
                code=code,
                title=title,
                content=texts[page_number - 1],
                source_page_start=page_number,
                source_page_end=page_number,
                source_paragraph=texts[page_number - 1][:20],
                sort_order=order,
            )
        refresh_version_hash(self.version)
        self.version.refresh_from_db()

    def _publish(self):
        submit_version_for_review(self.version, actor=self.admin)
        review_version_pages(self.version, actor=self.admin)
        review_version(self.version, actor=self.admin, approved=True, note="已逐页核对。")
        publish_version(self.version, actor=self.admin)
        self.version.refresh_from_db()

    def test_split_and_rebuild_produce_stable_source_anchored_chunks(self):
        slices = split_retrieval_text("甲" * 1600, max_chars=300, overlap_chars=50)
        self.assertGreater(len(slices), 1)
        self.assertTrue(all(len(item.text) <= 300 for item in slices))
        self.assertLessEqual(slices[1].start, slices[0].end)

        index, rebuilt = rebuild_retrieval_index(
            self.version,
            actor=self.admin,
            max_chars=300,
            overlap_chars=50,
        )
        self.assertTrue(rebuilt)
        first_ids = list(index.chunks.order_by("chunk_id").values_list("chunk_id", flat=True))
        index, rebuilt = rebuild_retrieval_index(
            self.version,
            actor=self.admin,
            max_chars=300,
            overlap_chars=50,
        )
        self.assertFalse(rebuilt)
        self.assertEqual(
            first_ids,
            list(index.chunks.order_by("chunk_id").values_list("chunk_id", flat=True)),
        )
        chunk = index.chunks.filter(
            source_kind=CurriculumRetrievalSourceKind.CONTENT_ITEM
        ).first()
        self.assertEqual(chunk.version_content_hash, self.version.content_hash)
        self.assertEqual(chunk.pdf_sha256, self.version.pdf_sha256)
        self.assertEqual(chunk.source_page_hashes[0]["page_number"], chunk.source_page_start)
        self.assertEqual(len(chunk.source_text_sha256), 64)
        self.assertTrue(retrieval_index_is_current(self.version))

        original_text = chunk.text
        original_source_text_sha256 = chunk.source_text_sha256
        original_source_content_hash = chunk.source_content_hash
        tampered_text = "X" * len(original_text)
        CurriculumRetrievalChunk.objects.filter(pk=chunk.pk).update(
            text=tampered_text,
            content_sha256=sha256_text(tampered_text),
            source_text_sha256="0" * 64,
            source_content_hash="1" * 64,
            source_page_hashes=[{"tampered": True}],
        )
        self.assertEqual(index.chunks.count(), len(first_ids))
        self.assertFalse(retrieval_index_is_current(self.version))

        index, rebuilt = rebuild_retrieval_index(
            self.version,
            actor=self.admin,
            max_chars=300,
            overlap_chars=50,
        )
        self.assertTrue(rebuilt)
        restored = index.chunks.get(chunk_id=chunk.chunk_id)
        self.assertEqual(restored.text, original_text)
        self.assertEqual(restored.source_text_sha256, original_source_text_sha256)
        self.assertEqual(restored.source_content_hash, original_source_content_hash)
        self.assertTrue(retrieval_index_is_current(self.version))

        CurriculumRetrievalChunk.objects.filter(pk=restored.pk).update(chunk_id="f" * 64)
        self.assertFalse(retrieval_index_is_current(self.version))
        index, rebuilt = rebuild_retrieval_index(
            self.version,
            actor=self.admin,
            max_chars=300,
            overlap_chars=50,
        )
        self.assertTrue(rebuilt)
        self.assertEqual(
            first_ids,
            list(index.chunks.order_by("chunk_id").values_list("chunk_id", flat=True)),
        )
        self.assertTrue(retrieval_index_is_current(self.version))

    def test_search_filters_unpublished_and_returns_pdf_trace(self):
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        teacher_client = APIClient()
        teacher_client.force_authenticate(self.teacher)

        search_url = reverse("api_curriculum_retrieval_search")
        response = teacher_client.get(search_url, {"q": "数字意识"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result_count"], 0)

        response = admin_client.get(
            search_url,
            {
                "q": "数字意识",
                "version_id": self.version.id,
                "include_unpublished": "true",
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertGreater(response.data["data"]["result_count"], 0)
        draft_result = response.data["data"]["results"][0]
        self.assertEqual(draft_result["curriculum_version"]["id"], self.version.id)
        self.assertEqual(len(draft_result["source"]["source_text_sha256"]), 64)

        response = teacher_client.get(
            search_url,
            {
                "q": "数字意识",
                "version_id": self.version.id,
                "include_unpublished": "true",
            },
        )
        self.assertEqual(response.status_code, 403)

        self._publish()
        response = teacher_client.get(search_url, {"q": "数字意识"})
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data["data"]["results"][0]
        self.assertEqual(result["curriculum_version"]["status"], "published")
        self.assertEqual(result["curriculum_version"]["id"], self.version.id)
        self.assertIn("/pdf/", result["curriculum_version"]["pdf_url"])
        self.assertTrue(result["source"]["page_hashes"])

    def test_node_trace_separates_content_item_from_real_source_pages_and_enforces_access(self):
        node = self.version.nodes.get(code="CS.CORE")
        node.source_page_end = 2
        node.save()
        refresh_version_hash(self.version)
        self.version.refresh_from_db()
        expected_pages = list(
            self.version.pages.filter(page_number__range=(1, 2)).order_by("page_number")
        )
        trace_url = reverse("api_curriculum_standard_node_trace", kwargs={"pk": node.id})

        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        response = admin_client.get(trace_url)
        self.assertEqual(response.status_code, 200, response.data)
        trace = response.data["data"]
        self.assertEqual(trace["content"], node.content)
        self.assertEqual(
            [item["page_number"] for item in trace["source_pages"]],
            [page.page_number for page in expected_pages],
        )
        for source_page, expected_page in zip(trace["source_pages"], expected_pages):
            self.assertEqual(source_page["text"], expected_page.text)
            self.assertEqual(source_page["content_hash"], expected_page.content_hash)
            self.assertEqual(source_page["review_status"], expected_page.review_status)

        teacher_client = APIClient()
        teacher_client.force_authenticate(self.teacher)
        self.assertEqual(teacher_client.get(trace_url).status_code, 404)

        self._publish()
        school_admin = User.objects.create_user(
            username="retrieval_school_admin",
            password="password",
            role=User.Role.SCHOOL_ADMIN,
        )
        student = User.objects.create_user(
            username="retrieval_student",
            password="password",
            role=User.Role.STUDENT,
        )
        for reader in (self.teacher, school_admin):
            reader_client = APIClient()
            reader_client.force_authenticate(reader)
            response = reader_client.get(trace_url)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(
                [item["text"] for item in response.data["data"]["source_pages"]],
                [page.text for page in expected_pages],
            )
        student_client = APIClient()
        student_client.force_authenticate(student)
        self.assertEqual(student_client.get(trace_url).status_code, 403)
        self.assertIn(APIClient().get(trace_url).status_code, {401, 403})

    def test_rebuild_list_permissions_jsonl_and_read_only_audit_command(self):
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        teacher_client = APIClient()
        teacher_client.force_authenticate(self.teacher)
        rebuild_url = reverse(
            "api_super_admin_curriculum_retrieval_index_rebuild",
            kwargs={"pk": self.version.id},
        )
        self.assertEqual(teacher_client.post(rebuild_url, {}, format="json").status_code, 403)
        response = admin_client.post(
            rebuild_url,
            {"max_chars": 500, "overlap_chars": 100},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["max_chars"], 500)

        self._publish()
        chunks_url = reverse("api_curriculum_retrieval_chunks", kwargs={"pk": self.version.id})
        response = teacher_client.get(chunks_url, {"limit": 5})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]["chunks"]), 5)
        self.assertTrue(response.data["data"]["index"]["is_current"])

        jsonl = teacher_client.get(
            reverse("api_curriculum_standard_jsonl", kwargs={"pk": self.version.id})
        )
        self.assertEqual(jsonl.status_code, 200)
        body = jsonl.content.decode("utf-8")
        self.assertIn('"record_type":"retrieval_index"', body)
        self.assertIn('"record_type":"retrieval_chunk"', body)

        before = CurriculumRetrievalChunk.objects.count()
        output = StringIO()
        call_command(
            "audit_curriculum_standards",
            "--version-id",
            str(self.version.id),
            "--skip-pdf-hash",
            "--json",
            stdout=output,
        )
        report = json.loads(output.getvalue())
        self.assertTrue(report["read_only"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(CurriculumRetrievalChunk.objects.count(), before)

        dry_run = StringIO()
        call_command(
            "build_curriculum_retrieval_index",
            "--version-id",
            str(self.version.id),
            "--dry-run",
            "--json",
            stdout=dry_run,
        )
        self.assertEqual(json.loads(dry_run.getvalue())["versions"][0]["result"], "would_build")

    def test_build_command_requires_super_admin_actor_and_audits_real_rebuild(self):
        args = (
            "build_curriculum_retrieval_index",
            "--version-id",
            str(self.version.id),
        )
        with self.assertRaises(CommandError):
            call_command(*args)
        with self.assertRaises(CommandError):
            call_command(*args, "--actor", self.teacher.username)

        self.version.retrieval_index.delete()
        audit_rows = CurriculumStandardAuditLog.objects.filter(
            version=self.version,
            action="retrieval_index_rebuilt",
        )
        self.assertEqual(audit_rows.count(), 0)

        output = StringIO()
        call_command(
            *args,
            "--actor",
            self.admin.username,
            "--json",
            stdout=output,
        )
        self.assertEqual(json.loads(output.getvalue())["versions"][0]["result"], "rebuilt")
        audit = audit_rows.get()
        self.assertEqual(audit.actor_id, self.admin.id)
        self.assertEqual(audit.detail["source"], "management_command")
        self.assertEqual(audit.detail["chunk_count"], self.version.retrieval_chunks.count())

        second_output = StringIO()
        call_command(
            *args,
            "--actor",
            self.admin.username,
            "--json",
            stdout=second_output,
        )
        self.assertEqual(
            json.loads(second_output.getvalue())["versions"][0]["result"],
            "unchanged",
        )
        self.assertEqual(audit_rows.count(), 1)
