from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from accounts.models import User
from curriculum_standards.models import (
    CurriculumExtractionStatus,
    CurriculumStandard,
    CurriculumStandardAuditLog,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    SchoolStage,
)


def _pdf_bytes(marker: str) -> bytes:
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Subject": marker})
    writer.write(buffer)
    return buffer.getvalue()


class ImportCurriculumStandardsCommandTests(TestCase):
    def setUp(self):
        self.media_root = Path(tempfile.mkdtemp(prefix="curriculum-import-tests-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media_root))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.actor = User.objects.create_user(
            username="curriculum_import_admin",
            password="password",
            role=User.Role.SUPER_ADMIN,
        )
        self.fixture_root = self.media_root / "curriculum_standards" / "official"
        fixtures = {
            "K1-K9/2022/13_information_technology.pdf": "compulsory-2022",
            (
                "K10-K12/2020/15.普通高中信息技术课程标准"
                "（2017年版2020年修订）.pdf"
            ): "senior-high-2020",
            (
                "K10-K12/2025/09.普通高中信息技术课程标准"
                "（2025年修订）.pdf"
            ): "senior-high-2025",
            # The command deliberately never scans this working directory.
            "current/13_information_technology.pdf": "uncontrolled-current-copy",
        }
        for relative_name, marker in fixtures.items():
            path = self.fixture_root / relative_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_pdf_bytes(marker))

    def _run_import(self) -> str:
        stdout = io.StringIO()
        call_command(
            "import_curriculum_standards",
            root=str(self.fixture_root),
            actor=self.actor.username,
            stdout=stdout,
        )
        return stdout.getvalue()

    def test_first_import_registers_expected_authoritative_versions_as_drafts(self):
        output = self._run_import()

        self.assertIn("新增 3", output)
        self.assertEqual(CurriculumStandard.objects.count(), 2)
        self.assertEqual(CurriculumStandardVersion.objects.count(), 3)
        self.assertEqual(
            CurriculumStandardAuditLog.objects.filter(action="imported").count(),
            3,
        )
        self.assertFalse(
            CurriculumStandardVersion.objects.filter(
                pdf_file__contains="current"
            ).exists()
        )

        compulsory = CurriculumStandard.objects.get(
            school_stage=SchoolStage.COMPULSORY,
            subject_code="information_technology",
        )
        self.assertEqual(compulsory.subject_name, "信息科技")
        compulsory_version = compulsory.versions.get(version_label="2022")
        self.assertEqual(compulsory_version.status, CurriculumVersionStatus.DRAFT)
        self.assertEqual(
            compulsory_version.extraction_status,
            CurriculumExtractionStatus.NEEDS_OCR,
        )

        senior_high = CurriculumStandard.objects.get(
            school_stage=SchoolStage.SENIOR_HIGH,
            subject_code="information_technology",
        )
        self.assertEqual(senior_high.subject_name, "信息科技")
        old_version = senior_high.versions.get(version_label="2017-2020")
        new_version = senior_high.versions.get(version_label="2017-2025")
        self.assertEqual(old_version.status, CurriculumVersionStatus.DRAFT)
        self.assertEqual(new_version.status, CurriculumVersionStatus.DRAFT)
        self.assertIsNone(old_version.replaces_version_id)
        self.assertEqual(new_version.replaces_version_id, old_version.id)
        self.assertIn("信息科技", new_version.official_title)

    def test_repeated_import_is_idempotent_when_source_files_are_unchanged(self):
        first_output = self._run_import()
        self.assertIn("新增 3", first_output)
        versions_before = {
            (version.source_id, version.version_label): (
                version.id,
                version.pdf_sha256,
                version.content_hash,
                version.replaces_version_id,
                version.status,
            )
            for version in CurriculumStandardVersion.objects.order_by("id")
        }
        standards_before = {
            (standard.school_stage, standard.document_type, standard.subject_code): (
                standard.id,
                standard.title,
                standard.subject_name,
            )
            for standard in CurriculumStandard.objects.order_by("id")
        }
        imported_audits_before = CurriculumStandardAuditLog.objects.filter(
            action="imported"
        ).count()

        second_output = self._run_import()

        self.assertIn("新增 0", second_output)
        self.assertIn("跳过 3", second_output)
        self.assertEqual(
            {
                (version.source_id, version.version_label): (
                    version.id,
                    version.pdf_sha256,
                    version.content_hash,
                    version.replaces_version_id,
                    version.status,
                )
                for version in CurriculumStandardVersion.objects.order_by("id")
            },
            versions_before,
        )
        self.assertEqual(
            {
                (standard.school_stage, standard.document_type, standard.subject_code): (
                    standard.id,
                    standard.title,
                    standard.subject_name,
                )
                for standard in CurriculumStandard.objects.order_by("id")
            },
            standards_before,
        )
        self.assertEqual(
            CurriculumStandardAuditLog.objects.filter(action="imported").count(),
            imported_audits_before,
        )
