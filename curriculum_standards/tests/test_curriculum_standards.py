from __future__ import annotations

from decimal import Decimal
import shutil
import tempfile
import io
from pathlib import Path

from django.contrib import admin as django_admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient
from pypdf import PdfWriter

from accounts.models import User
from courses.models import Course, Subject
from learning_analytics.evaluation_models import EvaluationPlan
from learning_analytics.services.evaluation import confirm_plan_review, publish_plan
from school.models import School

from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumPageQualityStatus,
    CurriculumStandard,
    CurriculumStandardAuditLog,
    CurriculumStandardNode,
    CurriculumStandardPage,
    CurriculumStandardVersion,
    CurriculumTextExtractionMethod,
    CurriculumVersionStatus,
    EvaluationPlanCurriculumReference,
    EvaluationPlanVersionCurriculumReference,
)
from curriculum_standards.services import (
    _save_page_records,
    create_version_from_existing_file,
    replace_plan_curriculum_references,
    suggest_framework_nodes,
)


def pdf_bytes(marker: str, *, pages: int = 4) -> bytes:
    buffer = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Subject": marker})
    writer.write(buffer)
    return buffer.getvalue()


def fake_pdf(name: str, marker: str, *, pages: int = 4) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        pdf_bytes(marker, pages=pages),
        content_type="application/pdf",
    )


def structured_text(suffix: str = "") -> str:
    sections = [
        (1, "（一）学科核心素养内涵", "核心素养原文"),
        (2, "三、课程目标", "课程目标原文"),
        (3, "五、课程内容", "课程内容原文"),
        (4, "六、学业质量", "学业质量原文"),
    ]
    return "\n\n".join(
        f"# PDF 第 {page} 页\n\n{heading}\n{body}{suffix}" + "说明" * 35
        for page, heading, body in sections
    )


@override_settings(CURRICULUM_REQUIRE_SEPARATE_REVIEWERS=False)
class CurriculumStandardApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="curriculum-tests-")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))
        self.admin = User.objects.create_user(
            username="curriculum_admin",
            password="password",
            role=User.Role.SUPER_ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse("api_super_admin_curriculum_standards"),
            {
                "title": "普通高中信息科技课程标准",
                "document_type": CurriculumDocumentType.SUBJECT_STANDARD,
                "school_stage": "k10_k12",
                "subject_code": "information_technology",
                "subject_name": "信息科技",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.standard_id = response.data["data"]["id"]

    def _create_version(self, label="2017-2025", marker="v1", suffix=""):
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_versions",
                kwargs={"pk": self.standard_id},
            ),
            {
                "version_label": label,
                "publication_year": int(label[-4:]),
                "effective_year": int(label[-4:]),
                "official_title": f"普通高中信息科技课程标准（{label}）",
                "issued_by": "中华人民共和国教育部",
                "source_url": "https://example.edu/standard",
                "source_note": "测试用教育部正式文件。",
                "pdf_file": fake_pdf(f"{label}.pdf", marker),
                "structured_text": structured_text(suffix),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]["id"]

    def _add_framework_items(self, version_id, suffix=""):
        definitions = (
            (
                CurriculumNodeType.CORE_COMPETENCY,
                "CS.CORE",
                "核心素养",
                1,
                "（一）学科核心素养内涵",
                "核心素养原文",
            ),
            (
                CurriculumNodeType.COURSE_OBJECTIVE,
                "CS.OBJECTIVE",
                "课程目标",
                2,
                "三、课程目标",
                "课程目标原文",
            ),
            (
                CurriculumNodeType.COURSE_CONTENT,
                "CS.CONTENT",
                "课程内容",
                3,
                "五、课程内容",
                "课程内容原文",
            ),
            (
                CurriculumNodeType.ACADEMIC_QUALITY,
                "CS.QUALITY",
                "学业质量",
                4,
                "六、学业质量",
                "学业质量原文",
            ),
        )
        ids = []
        for order, (node_type, code, title, page, paragraph, content) in enumerate(
            definitions
        ):
            response = self.client.post(
                reverse(
                    "api_super_admin_curriculum_standard_version_nodes",
                    kwargs={"pk": version_id},
                ),
                {
                    "node_type": node_type,
                    "code": code,
                    "title": title,
                    "content": f"{paragraph}\n{content}{suffix}" + "说明" * 35,
                    "source_page_start": page,
                    "source_page_end": page,
                    "source_paragraph": paragraph,
                    "sort_order": order,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)
            ids.append(response.data["data"]["id"])
        return ids

    def test_ocr_confidence_float_noise_is_normalized_before_page_validation(self):
        version_id = self._create_version()
        version = CurriculumStandardVersion.objects.get(pk=version_id)
        version.pages.all().delete()

        _save_page_records(
            version,
            [
                {
                    "page_number": 1,
                    "text": "信息科技课程标准原文",
                    "extraction_method": CurriculumTextExtractionMethod.OCR,
                    "mean_confidence": 0.9123000000000001,
                    "quality_status": CurriculumPageQualityStatus.COMPLETE,
                    "quality_message": "文字识别结果发布前需人工复核。",
                }
            ],
        )

        page = version.pages.get()
        self.assertEqual(page.mean_confidence, Decimal("0.9123"))

    def test_standard_directory_is_server_paginated_summary(self):
        for index in range(12):
            CurriculumStandard.objects.create(
                title=f"信息科技课程标准目录测试 {index + 1}",
                document_type=CurriculumDocumentType.SUBJECT_STANDARD,
                school_stage="k1_k9",
                subject_code=f"it-budget-{index + 1}",
                subject_name=f"信息科技 {index + 1}",
                created_by=self.admin,
                updated_by=self.admin,
            )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                reverse("api_super_admin_curriculum_standards"),
                {"page": 1, "page_size": 8},
            )

        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data["data"]
        self.assertEqual(len(payload["standards"]), 8)
        self.assertEqual(payload["pagination"]["total"], 13)
        self.assertEqual(payload["pagination"]["page_count"], 2)
        self.assertNotIn(
            "nodes",
            payload["standards"][0].get("current_version") or {},
        )
        self.assertLess(len(response.content), 20_000)
        self.assertLessEqual(
            len(captured),
            6,
            f"课程标准目录查询数超出预算：{len(captured)}",
        )

    def _publish(self, version_id):
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_submit_review",
                kwargs={"pk": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_pages_review",
                kwargs={"pk": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_review",
                kwargs={"pk": version_id},
            ),
            {"approved": True, "note": "已核对原文、页码和内容条目。"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_publish",
                kwargs={"pk": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_publish_trace_pages_and_sidecars(self):
        version_id = self._create_version()
        node_ids = self._add_framework_items(version_id)
        self._publish(version_id)
        version = CurriculumStandardVersion.objects.get(pk=version_id)
        self.assertEqual(version.status, CurriculumVersionStatus.PUBLISHED)
        self.assertEqual(version.pages.count(), 4)
        self.assertGreater(version.pdf_size_bytes, 0)
        self.assertEqual(len(version.content_hash), 64)

        school = School.objects.create(name="测试学校", code="CS-T")
        teacher = User.objects.create_user(
            username="curriculum_teacher",
            password="password",
            role=User.Role.TEACHER,
            school=school,
        )
        self.client.force_authenticate(teacher)
        options = self.client.get(
            reverse("api_curriculum_standard_reference_options"),
            {"subject_code": "01", "subject_name": "信息技术"},
        )
        self.assertEqual(options.status_code, 200)
        self.assertEqual(
            options.data["data"]["standards"][0]["current_version"]["id"], version_id
        )
        trace = self.client.get(
            reverse("api_curriculum_standard_node_trace", kwargs={"pk": node_ids[0]})
        )
        self.assertEqual(trace.status_code, 200)
        self.assertEqual(trace.data["data"]["source_page_start"], 1)
        markdown = self.client.get(
            reverse("api_curriculum_standard_markdown", kwargs={"pk": version_id})
        )
        self.assertContains(markdown, "课程标准结构化内容条目")
        jsonl = self.client.get(
            reverse("api_curriculum_standard_jsonl", kwargs={"pk": version_id})
        )
        self.assertContains(jsonl, '"pdf_size_bytes":')
        self.assertContains(jsonl, '"record_type":"content_item"')
        structured_json = self.client.get(
            reverse("api_curriculum_standard_json", kwargs={"pk": version_id})
        )
        self.assertEqual(structured_json.status_code, 200)
        self.assertEqual(
            structured_json["Content-Disposition"],
            f'attachment; filename="curriculum-standard-{version_id}.json"',
        )
        self.assertEqual(structured_json["ETag"], f'"{version.content_hash}"')
        structured_payload = structured_json.json()
        self.assertEqual(structured_payload["schema"], "curriculum_standard_export_v1")
        self.assertEqual(structured_payload["version"]["id"], version_id)
        self.assertEqual(len(structured_payload["pages"]), 4)
        self.assertEqual(
            len(structured_payload["content_items"]),
            CurriculumStandardNode.objects.filter(version_id=version_id).count(),
        )
        self.assertEqual(structured_payload["pages"][0]["page_number"], 1)
        self.assertTrue(structured_payload["pages"][0]["text"])
        self.assertEqual(structured_payload["content_items"][0]["source_page_start"], 1)
        self.assertIsNotNone(structured_payload["retrieval"])

    def test_replacement_compare_and_published_content_is_immutable(self):
        first_id = self._create_version("2017-2020", "first")
        first_nodes = self._add_framework_items(first_id)
        self._publish(first_id)
        second_id = self._create_version("2017-2025", "second")
        self._add_framework_items(second_id)
        self._publish(second_id)
        self.assertEqual(
            CurriculumStandardVersion.objects.get(pk=first_id).status,
            CurriculumVersionStatus.ARCHIVED,
        )
        response = self.client.get(
            reverse("api_curriculum_standard_compare"),
            {"from_id": first_id, "to_id": second_id},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["data"]["content_item_counts"]["unchanged"],
            CurriculumStandardNode.objects.filter(version_id=first_id).count(),
        )
        response = self.client.patch(
            reverse(
                "api_super_admin_curriculum_standard_node_detail",
                kwargs={"pk": first_nodes[0]},
            ),
            {"title": "试图改写历史"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)

    def test_duplicate_pdf_and_out_of_range_source_page_are_rejected(self):
        first_id = self._create_version("2017-2020", "same")
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_versions",
                kwargs={"pk": self.standard_id},
            ),
            {
                "version_label": "duplicate-label",
                "publication_year": 2021,
                "pdf_file": fake_pdf("duplicate.pdf", "same"),
                "structured_text": structured_text(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400, response.data)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_nodes",
                kwargs={"pk": first_id},
            ),
            {
                "node_type": CurriculumNodeType.CORE_COMPETENCY,
                "code": "CS.INVALID",
                "title": "错误位置",
                "content": "课程标准原文" * 20,
                "source_page_start": 999,
                "source_page_end": 999,
                "source_paragraph": "错误位置",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.data)

    def test_discard_imported_draft_never_deletes_official_asset(self):
        official = (
            Path(self.media_root) / "curriculum_standards" / "official" / "source.pdf"
        )
        official.parent.mkdir(parents=True)
        official.write_bytes(pdf_bytes("official", pages=1))
        standard = CurriculumStandard.objects.get(pk=self.standard_id)
        version = create_version_from_existing_file(
            standard=standard,
            file_path=official,
            media_root=Path(self.media_root),
            version_label="official-draft",
            publication_year=2022,
            effective_year=2022,
            issued_by="中华人民共和国教育部",
            source_url="",
            official_title="正式文件",
            source_note="本地受控资产",
            replaces_version=None,
            actor=self.admin,
        )
        response = self.client.delete(
            reverse(
                "api_super_admin_curriculum_standard_version_detail",
                kwargs={"pk": version.id},
            )
        )
        self.assertEqual(response.status_code, 200, response.data)
        version.refresh_from_db()
        self.assertEqual(version.status, CurriculumVersionStatus.DISCARDED)
        self.assertTrue(official.exists())

    def test_numbered_headings_prefer_body_over_table_of_contents(self):
        pages = [
            "目录\n三、课程目标\n五、课程内容\n六、学业质量",
            "",
            "三、课程目标\n（一）学科核心素养内涵\n核心素养正文" + "内容" * 40,
            "三、课程目标\n核心素养续页正文"
            + "内容" * 40
            + "\n（二）目标要求\n要求正文",
            "五、课程内容\n课程内容正文" + "内容" * 40,
            "五、课程内容\n课程内容续页正文" + "内容" * 40,
            "六、学业质量\n学业质量正文" + "内容" * 40,
            "六、学业质量\n学业质量续页正文" + "内容" * 40,
        ]
        rows = suggest_framework_nodes(pages)
        self.assertEqual(
            {row["node_type"] for row in rows}, set(CurriculumNodeType.values)
        )
        self.assertTrue(all(row["source_page_start"] >= 3 for row in rows))
        by_type = {row["node_type"]: row for row in rows}
        self.assertEqual(
            (
                by_type[CurriculumNodeType.CORE_COMPETENCY]["source_page_start"],
                by_type[CurriculumNodeType.CORE_COMPETENCY]["source_page_end"],
            ),
            (3, 4),
        )
        self.assertEqual(
            (
                by_type[CurriculumNodeType.COURSE_OBJECTIVE]["source_page_start"],
                by_type[CurriculumNodeType.COURSE_OBJECTIVE]["source_page_end"],
            ),
            (3, 4),
        )
        self.assertEqual(
            (
                by_type[CurriculumNodeType.COURSE_CONTENT]["source_page_start"],
                by_type[CurriculumNodeType.COURSE_CONTENT]["source_page_end"],
            ),
            (5, 6),
        )
        self.assertEqual(
            (
                by_type[CurriculumNodeType.ACADEMIC_QUALITY]["source_page_start"],
                by_type[CurriculumNodeType.ACADEMIC_QUALITY]["source_page_end"],
            ),
            (7, 8),
        )

    def test_version_patch_rolls_back_text_pages_hash_and_audit_on_late_conflict(self):
        self._create_version("2017-2020", "first")
        version_id = self._create_version("2017-2025", "second")
        version = CurriculumStandardVersion.objects.get(pk=version_id)
        version.nodes.all().delete()
        before_text = version.structured_text
        before_hash = version.content_hash
        before_pages = list(
            version.pages.order_by("page_number").values_list(
                "page_number", "text", "content_hash"
            )
        )
        before_audits = version.audit_logs.count()

        response = self.client.patch(
            reverse(
                "api_super_admin_curriculum_standard_version_detail",
                kwargs={"pk": version_id},
            ),
            {
                "version_label": "2017-2020",
                "structured_text": structured_text("-changed"),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        version.refresh_from_db()
        self.assertEqual(version.version_label, "2017-2025")
        self.assertEqual(version.structured_text, before_text)
        self.assertEqual(version.content_hash, before_hash)
        self.assertEqual(
            list(
                version.pages.order_by("page_number").values_list(
                    "page_number", "text", "content_hash"
                )
            ),
            before_pages,
        )
        self.assertEqual(version.audit_logs.count(), before_audits)

    def test_reader_and_writer_permissions_are_separated_by_role(self):
        reader_url = reverse("api_curriculum_standard_reference_options")
        write_url = reverse(
            "api_super_admin_curriculum_standard_detail",
            kwargs={"pk": self.standard_id},
        )
        teacher = User.objects.create_user(
            username="curriculum_permission_teacher",
            password="password",
            role=User.Role.TEACHER,
        )
        school_admin = User.objects.create_user(
            username="curriculum_permission_school_admin",
            password="password",
            role=User.Role.SCHOOL_ADMIN,
        )
        student = User.objects.create_user(
            username="curriculum_permission_student",
            password="password",
            role=User.Role.STUDENT,
        )

        for reader in (teacher, school_admin):
            self.client.force_authenticate(reader)
            self.assertEqual(self.client.get(reader_url).status_code, 200)
            self.assertEqual(
                self.client.patch(
                    write_url, {"title": "unauthorized"}, format="json"
                ).status_code,
                403,
            )

        self.client.force_authenticate(student)
        self.assertEqual(self.client.get(reader_url).status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(reader_url).status_code, {401, 403})
        self.assertNotEqual(
            CurriculumStandard.objects.get(pk=self.standard_id).title,
            "unauthorized",
        )

    @override_settings(CURRICULUM_REQUIRE_SEPARATE_REVIEWERS=True)
    def test_production_review_and_publish_require_separate_people(self):
        version_id = self._create_version("2017-2025", "separation")
        self._add_framework_items(version_id)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_submit_review",
                kwargs={"pk": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_review",
                kwargs={"pk": version_id},
            ),
            {"approved": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

        reviewer = User.objects.create_user(
            username="curriculum_independent_reviewer",
            password="password",
            role=User.Role.SUPER_ADMIN,
        )
        self.client.force_authenticate(reviewer)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_pages_review",
                kwargs={"pk": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_review",
                kwargs={"pk": version_id},
            ),
            {"approved": True, "note": "independent review"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_publish",
                kwargs={"pk": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            CurriculumStandardVersion.objects.get(pk=version_id).status,
            CurriculumVersionStatus.REVIEWED,
        )

    def test_manual_text_for_multi_page_pdf_requires_complete_page_markers(self):
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_versions",
                kwargs={"pk": self.standard_id},
            ),
            {
                "version_label": "missing-page-markers",
                "publication_year": 2025,
                "pdf_file": fake_pdf("missing-markers.pdf", "missing-markers"),
                "structured_text": "content without page markers" * 30,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(
            CurriculumStandardVersion.objects.filter(
                source_id=self.standard_id,
                version_label="missing-page-markers",
            ).exists()
        )

    def test_content_item_body_must_be_verifiable_in_source_pages(self):
        version_id = self._create_version("2017-2025", "forged-node")
        node_ids = self._add_framework_items(version_id)
        response = self.client.patch(
            reverse(
                "api_super_admin_curriculum_standard_node_detail",
                kwargs={"pk": node_ids[0]},
            ),
            {"content": "forged curriculum claim" * 30},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            reverse(
                "api_super_admin_curriculum_standard_version_submit_review",
                kwargs={"pk": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            CurriculumStandardVersion.objects.get(pk=version_id).status,
            CurriculumVersionStatus.DRAFT,
        )

    def test_governed_django_admin_models_are_strictly_read_only(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        governed_models = (
            CurriculumStandard,
            CurriculumStandardVersion,
            CurriculumStandardPage,
            CurriculumStandardNode,
            CurriculumStandardAuditLog,
            EvaluationPlanCurriculumReference,
            EvaluationPlanVersionCurriculumReference,
        )
        for model in governed_models:
            model_admin = django_admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request), model.__name__)
            self.assertFalse(model_admin.has_change_permission(request), model.__name__)
            self.assertFalse(model_admin.has_delete_permission(request), model.__name__)


@override_settings(CURRICULUM_REQUIRE_SEPARATE_REVIEWERS=False)
class EvaluationCurriculumReferenceTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="评价测试学校", code="EV-CS")
        self.teacher = User.objects.create_user(
            username="evaluation_teacher_cs",
            password="password",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息技术",
            code="01",
            created_by=self.teacher,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="信息科技课程",
            teacher=self.teacher,
        )
        self.standard = CurriculumStandard.objects.create(
            title="普通高中信息科技课程标准",
            document_type=CurriculumDocumentType.SUBJECT_STANDARD,
            school_stage="k10_k12",
            subject_code="information_technology",
            subject_name="信息科技",
            created_by=self.teacher,
            updated_by=self.teacher,
        )

    def _published_version(self, label, suffix):
        version = CurriculumStandardVersion.objects.create(
            source=self.standard,
            version_label=label,
            publication_year=int(label[-4:]),
            effective_year=int(label[-4:]),
            title_snapshot=self.standard.title,
            official_title=f"普通高中信息科技课程标准（{label}）",
            document_type_snapshot=self.standard.document_type,
            school_stage_snapshot=self.standard.school_stage,
            subject_code_snapshot=self.standard.subject_code,
            subject_name_snapshot=self.standard.subject_name,
            issued_by="中华人民共和国教育部",
            source_url="https://example.edu",
            source_note="测试来源",
            pdf_file=f"curriculum_standards/official/{label}.pdf",
            pdf_sha256=("a" if suffix == "a" else "b") * 64,
            pdf_size_bytes=1024,
            pdf_page_count=4,
            structured_text=structured_text(suffix),
            structured_text_sha256=("c" if suffix == "a" else "d") * 64,
            extraction_status="completed",
            content_hash=("e" if suffix == "a" else "f") * 64,
            status=CurriculumVersionStatus.DRAFT,
            created_by=self.teacher,
            submitted_by=self.teacher,
            reviewed_by=self.teacher,
            published_by=self.teacher,
        )
        for order, node_type in enumerate(CurriculumNodeType.values, start=1):
            CurriculumStandardNode.objects.create(
                version=version,
                node_type=node_type,
                code=f"CS.{node_type}",
                title=dict(CurriculumNodeType.choices)[node_type],
                content=f"{node_type}-{suffix}",
                source_page_start=order,
                source_page_end=order,
                source_paragraph=f"位置{order}",
                sort_order=order,
            )
        CurriculumStandardVersion.objects.filter(pk=version.pk).update(
            status=CurriculumVersionStatus.PUBLISHED
        )
        version.refresh_from_db()
        self.standard.current_version = version
        self.standard.save()
        return version

    def _plan(self):
        return EvaluationPlan.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            title="课程标准对齐评价方案",
            content_version="第一单元",
            target_students="高一年级学生",
            learning_goal="学生能够运用信息科技方法解决真实问题。",
            learning_goals=[
                {
                    "code": "G1",
                    "title": "问题解决",
                    "description": "能够运用数字工具完成真实问题解决任务。",
                }
            ],
            evaluation_basis=[
                {
                    "code": "E1",
                    "goal_codes": ["G1"],
                    "description": "根据学生完成任务时形成的作品和说明进行评价。",
                    "source_types": ["学生作品"],
                }
            ],
            learning_activities=[
                {
                    "code": "A1",
                    "title": "完成项目探究",
                    "goal_codes": ["G1"],
                    "description": "学生围绕真实问题完成项目作品并说明问题解决过程。",
                }
            ],
            learning_tasks=[
                {
                    "code": "T1",
                    "title": "完成项目任务",
                    "basis_codes": ["E1"],
                    "description": "完成项目作品并说明问题解决过程和改进依据。",
                }
            ],
            evaluation_tasks=[
                {
                    "code": "ET1",
                    "title": "项目作品评价",
                    "goal_codes": ["G1"],
                    "activity_codes": ["A1"],
                    "mode": "project",
                    "evidence_ownership": "individual",
                    "material_types": ["artifact"],
                    "weight": 100,
                    "description": "依据个人项目作品和过程说明判断学习目标达成情况。",
                }
            ],
            assessment_modes=["project"],
            content_scope=["数据与计算"],
            thinking_requirements=["apply"],
            support_options=[],
            scoring_rules={
                "approach": "按评价标准评分",
                "decision_rule": "依据作品证据逐项判断达成表现并保留原始记录。",
            },
            follow_up_suggestion="根据学生的具体表现提供针对性的学习支持。",
            created_by=self.teacher,
            updated_by=self.teacher,
        )

    def test_reference_change_creates_new_plan_version_without_rewriting_history(self):
        first = self._published_version("2017-2020", "a")
        plan = self._plan()
        first_node_ids = list(first.nodes.values_list("id", flat=True))
        replace_plan_curriculum_references(
            plan=plan,
            node_ids=first_node_ids,
            actor=self.teacher,
        )
        plan.learning_goals = [
            {
                **goal,
                "curriculum_node_ids": first_node_ids,
            }
            for goal in plan.learning_goals
        ]
        plan.save(update_fields=["learning_goals", "updated_at"])
        confirm_plan_review(plan=plan, reviewed_by=self.teacher)
        first_plan_version = publish_plan(plan, published_by=self.teacher).version
        first_reference_hashes = list(
            first_plan_version.curriculum_references.values_list(
                "node_content_hash", flat=True
            )
        )
        first.status = CurriculumVersionStatus.ARCHIVED
        first.save(update_fields=["status"])
        second = self._published_version("2017-2025", "b")
        second_node_ids = list(second.nodes.values_list("id", flat=True))
        replace_plan_curriculum_references(
            plan=plan,
            node_ids=second_node_ids,
            actor=self.teacher,
        )
        plan.learning_goals = [
            {
                **goal,
                "curriculum_node_ids": second_node_ids,
            }
            for goal in plan.learning_goals
        ]
        plan.save(update_fields=["learning_goals", "updated_at"])
        confirm_plan_review(plan=plan, reviewed_by=self.teacher)
        second_plan_version = publish_plan(plan, published_by=self.teacher).version
        self.assertNotEqual(first_plan_version.id, second_plan_version.id)
        self.assertNotEqual(
            first_plan_version.content_hash, second_plan_version.content_hash
        )
        self.assertEqual(
            list(
                first_plan_version.curriculum_references.values_list(
                    "node_content_hash", flat=True
                )
            ),
            first_reference_hashes,
        )

    def test_subject_mismatch_is_rejected(self):
        version = self._published_version("2017-2025", "a")
        other_subject = Subject.objects.create(
            school=self.school,
            name="数学",
            code="02",
            created_by=self.teacher,
        )
        self.course.subject = other_subject
        self.course.save(update_fields=["subject"])
        self.subject = other_subject
        plan = self._plan()
        with self.assertRaises(ValidationError):
            replace_plan_curriculum_references(
                plan=plan,
                node_ids=list(version.nodes.values_list("id", flat=True)),
                actor=self.teacher,
            )
