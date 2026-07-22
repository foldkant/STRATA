from __future__ import annotations

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter
from rest_framework.test import APIClient

from accounts.models import User
from curriculum_standards.models import (
    CurriculumNodeType,
    CurriculumStandard,
    CurriculumStandardAuditLog,
    CurriculumStandardNode,
    CurriculumStandardPage,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
)


def _pdf_upload(page_count: int = 4) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    writer.write(buffer)
    return SimpleUploadedFile(
        "compulsory-information-technology-2022.pdf",
        buffer.getvalue(),
        content_type="application/pdf",
    )


@override_settings(CURRICULUM_REQUIRE_SEPARATE_REVIEWERS=False)
class P1AcceptanceLifecycleTests(TestCase):
    """Acceptance coverage for governed K1-K9 lifecycle and historical access."""

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="p1-lifecycle-tests-")
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.admin = User.objects.create_user(
            username="p1_lifecycle_admin",
            password="password",
            role=User.Role.SUPER_ADMIN,
        )
        self.teacher = User.objects.create_user(
            username="p1_lifecycle_teacher",
            password="password",
            role=User.Role.TEACHER,
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.teacher_client = APIClient()
        self.teacher_client.force_authenticate(self.teacher)

        standard_response = self.admin_client.post(
            reverse("api_super_admin_curriculum_standards"),
            {
                "title": "义务教育信息科技课程标准（2022年版）",
                "document_type": "subject_standard",
                "school_stage": "k1_k9",
                "subject_code": "information_technology",
                "subject_name": "信息科技",
            },
            format="json",
        )
        self.assertEqual(standard_response.status_code, 201, standard_response.data)
        self.standard_id = standard_response.data["data"]["id"]

        self.page_texts = [
            "核心素养原文：学生形成数字素养、计算思维和信息社会责任。"
            + "核心素养说明。" * 40,
            "课程目标原文：学生能够运用信息科技解决真实学习与生活问题。"
            + "课程目标说明。" * 40,
            "课程内容原文：围绕数据、算法、网络和人工智能组织学习内容。"
            + "课程内容说明。" * 40,
            "学业质量原文：学生能够在真实情境中综合运用知识完成任务。"
            + "学业质量说明。" * 40,
        ]
        structured_text = "\n\n".join(
            f"# PDF 第 {page_number} 页\n\n{text}"
            for page_number, text in enumerate(self.page_texts, start=1)
        )
        version_response = self.admin_client.post(
            reverse(
                "api_super_admin_curriculum_standard_versions",
                kwargs={"pk": self.standard_id},
            ),
            {
                "version_label": "2022",
                "publication_year": 2022,
                "effective_year": 2022,
                "official_title": "义务教育信息科技课程标准（2022年版）",
                "issued_by": "中华人民共和国教育部",
                "source_url": "https://example.edu/compulsory-it-2022",
                "source_note": "K1—K9 生命周期验收使用的权威来源记录。",
                "pdf_file": _pdf_upload(),
                "structured_text": structured_text,
            },
            format="multipart",
        )
        self.assertEqual(version_response.status_code, 201, version_response.data)
        self.version_id = version_response.data["data"]["id"]

        definitions = (
            (CurriculumNodeType.CORE_COMPETENCY, "IT.CORE", "核心素养", 1),
            (CurriculumNodeType.COURSE_OBJECTIVE, "IT.OBJECTIVE", "课程目标", 2),
            (CurriculumNodeType.COURSE_CONTENT, "IT.CONTENT", "课程内容", 3),
            (CurriculumNodeType.ACADEMIC_QUALITY, "IT.QUALITY", "学业质量", 4),
        )
        self.node_ids = []
        for order, (node_type, code, title, page_number) in enumerate(definitions):
            response = self.admin_client.post(
                reverse(
                    "api_super_admin_curriculum_standard_version_nodes",
                    kwargs={"pk": self.version_id},
                ),
                {
                    "node_type": node_type,
                    "code": code,
                    "title": title,
                    "content": self.page_texts[page_number - 1],
                    "source_page_start": page_number,
                    "source_page_end": page_number,
                    "source_paragraph": self.page_texts[page_number - 1][:24],
                    "sort_order": order,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)
            self.node_ids.append(response.data["data"]["id"])

        self._publish_version()

    def _publish_version(self):
        response = self.admin_client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_submit_review",
                kwargs={"pk": self.version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.admin_client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_pages_review",
                kwargs={"pk": self.version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.admin_client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_review",
                kwargs={"pk": self.version_id},
            ),
            {"approved": True, "note": "K1—K9 生命周期工程验收。"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.admin_client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_publish",
                kwargs={"pk": self.version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        standard = CurriculumStandard.objects.get(pk=self.standard_id)
        version = CurriculumStandardVersion.objects.get(pk=self.version_id)
        self.assertEqual(standard.school_stage, "k1_k9")
        self.assertEqual(standard.current_version_id, version.id)
        self.assertEqual(version.status, CurriculumVersionStatus.PUBLISHED)

    def _teacher_reference_options(self):
        return self.teacher_client.get(
            reverse("api_curriculum_standard_reference_options"),
            {
                "school_stage": "k1_k9",
                "subject_code": "information_technology",
            },
        )

    def _teacher_search(self):
        return self.teacher_client.get(
            reverse("api_curriculum_retrieval_search"),
            {
                "q": "数字素养",
                "school_stage": "k1_k9",
                "subject_code": "information_technology",
            },
        )

    def test_superadmin_deactivate_and_reactivate_hides_new_teacher_choices_only(self):
        options = self._teacher_reference_options()
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(
            [row["id"] for row in options.data["data"]["standards"]],
            [self.standard_id],
        )
        search = self._teacher_search()
        self.assertEqual(search.status_code, 200, search.data)
        self.assertGreater(search.data["data"]["result_count"], 0)

        version = CurriculumStandardVersion.objects.get(pk=self.version_id)
        original_hash = version.content_hash
        original_page_ids = list(
            CurriculumStandardPage.objects.filter(version=version)
            .order_by("page_number")
            .values_list("id", flat=True)
        )
        original_node_ids = list(
            CurriculumStandardNode.objects.filter(version=version)
            .order_by("sort_order")
            .values_list("id", flat=True)
        )

        response = self.admin_client.patch(
            reverse(
                "api_super_admin_curriculum_standard_detail",
                kwargs={"pk": self.standard_id},
            ),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["data"]["is_active"])
        self.assertEqual(
            self._teacher_reference_options().data["data"]["standards"], []
        )
        self.assertEqual(self._teacher_search().data["data"]["result_count"], 0)

        # Deactivation prevents new selection/search but keeps the immutable
        # version and its directly addressable historical source trace.
        trace = self.teacher_client.get(
            reverse(
                "api_curriculum_standard_node_trace", kwargs={"pk": self.node_ids[0]}
            )
        )
        self.assertEqual(trace.status_code, 200, trace.data)
        self.assertTrue(trace.data["data"]["source_pages"])
        version.refresh_from_db()
        self.assertEqual(version.content_hash, original_hash)
        self.assertEqual(
            list(
                CurriculumStandardPage.objects.filter(version=version)
                .order_by("page_number")
                .values_list("id", flat=True)
            ),
            original_page_ids,
        )
        self.assertEqual(
            list(
                CurriculumStandardNode.objects.filter(version=version)
                .order_by("sort_order")
                .values_list("id", flat=True)
            ),
            original_node_ids,
        )

        response = self.admin_client.patch(
            reverse(
                "api_super_admin_curriculum_standard_detail",
                kwargs={"pk": self.standard_id},
            ),
            {"is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["data"]["is_active"])
        self.assertEqual(
            len(self._teacher_reference_options().data["data"]["standards"]), 1
        )
        self.assertGreater(self._teacher_search().data["data"]["result_count"], 0)

        active_changes = CurriculumStandardAuditLog.objects.filter(
            standard_id=self.standard_id,
            action="standard_updated",
        ).order_by("id")
        self.assertEqual(active_changes.count(), 2)
        self.assertEqual(active_changes[0].detail["before"]["is_active"], True)
        self.assertEqual(active_changes[0].detail["after"]["is_active"], False)
        self.assertEqual(active_changes[1].detail["before"]["is_active"], False)
        self.assertEqual(active_changes[1].detail["after"]["is_active"], True)

    def test_archive_and_restore_api_preserve_version_objects_and_audit_history(self):
        version = CurriculumStandardVersion.objects.get(pk=self.version_id)
        original_pdf_hash = version.pdf_sha256
        original_content_hash = version.content_hash
        original_page_count = version.pages.count()
        original_node_count = version.nodes.count()
        original_chunk_ids = list(
            version.retrieval_chunks.order_by("chunk_id").values_list(
                "chunk_id", flat=True
            )
        )

        response = self.admin_client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_archive",
                kwargs={"pk": self.version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        version.refresh_from_db()
        standard = CurriculumStandard.objects.get(pk=self.standard_id)
        self.assertEqual(version.status, CurriculumVersionStatus.ARCHIVED)
        self.assertIsNone(standard.current_version_id)
        self.assertEqual(standard.versions.count(), 1)
        self.assertEqual(version.pdf_sha256, original_pdf_hash)
        self.assertEqual(version.content_hash, original_content_hash)
        self.assertEqual(version.pages.count(), original_page_count)
        self.assertEqual(version.nodes.count(), original_node_count)
        self.assertEqual(
            list(
                version.retrieval_chunks.order_by("chunk_id").values_list(
                    "chunk_id", flat=True
                )
            ),
            original_chunk_ids,
        )
        self.assertTrue(
            CurriculumStandardAuditLog.objects.filter(
                version=version,
                action="archived",
                actor=self.admin,
            ).exists()
        )
        self.assertEqual(
            self._teacher_reference_options().data["data"]["standards"], []
        )
        historical_trace = self.teacher_client.get(
            reverse(
                "api_curriculum_standard_node_trace", kwargs={"pk": self.node_ids[0]}
            )
        )
        self.assertEqual(historical_trace.status_code, 200, historical_trace.data)

        response = self.admin_client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_restore",
                kwargs={"pk": self.version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        version.refresh_from_db()
        standard.refresh_from_db()
        self.assertEqual(version.status, CurriculumVersionStatus.PUBLISHED)
        self.assertEqual(standard.current_version_id, version.id)
        self.assertEqual(standard.versions.count(), 1)
        self.assertEqual(version.pdf_sha256, original_pdf_hash)
        self.assertEqual(version.content_hash, original_content_hash)
        self.assertEqual(version.pages.count(), original_page_count)
        self.assertEqual(version.nodes.count(), original_node_count)
        self.assertEqual(
            list(
                version.retrieval_chunks.order_by("chunk_id").values_list(
                    "chunk_id", flat=True
                )
            ),
            original_chunk_ids,
        )
        self.assertTrue(
            CurriculumStandardAuditLog.objects.filter(
                version=version,
                action="restored_as_current",
                actor=self.admin,
            ).exists()
        )
        self.assertEqual(
            len(self._teacher_reference_options().data["data"]["standards"]), 1
        )
        self.assertGreater(self._teacher_search().data["data"]["result_count"], 0)
