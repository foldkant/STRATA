from __future__ import annotations

import json
import tempfile
import zipfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from ops.models import ImportBatch
from school.models import School


def collection_zip(*, school_code: str, unsafe: bool = False) -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "school_code": school_code,
                    "system_version": "2.0-test",
                    "schema_version": "1",
                    "exported_at": "2026-07-21T08:00:00+08:00",
                }
            ),
        )
        archive.writestr("../unsafe.txt" if unsafe else "data/summary.json", "{}")
    return payload.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="strata-ops-tests-"))
class SuperAdminConsoleApiTests(TestCase):
    def setUp(self):
        self.formal_school = School.objects.create(
            name="正式学校", code="FORMAL-01", is_synthetic=False
        )
        self.synthetic_school = School.objects.create(
            name="测试学校", code="SYNTHETIC-01", is_synthetic=True
        )
        self.super_admin = User.objects.create_superuser(
            username="super_console",
            password="Admin123!",
            role=User.Role.SUPER_ADMIN,
        )
        self.school_admin = User.objects.create_user(
            username="school_console",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.formal_school,
        )
        self.client = APIClient()

    def upload_package(self, content: bytes, name: str = "collection.zip"):
        return self.client.post(
            "/api/v1/super-admin/collection/",
            {
                "package_file": SimpleUploadedFile(
                    name, content, content_type="application/zip"
                )
            },
            format="multipart",
        )

    def test_collection_upload_validates_and_rejects_duplicate(self):
        self.client.force_authenticate(self.super_admin)
        content = collection_zip(school_code=self.formal_school.code)
        response = self.upload_package(content)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], ImportBatch.Status.VALIDATED)
        self.assertEqual(
            response.data["data"]["source_school"]["id"], self.formal_school.id
        )
        self.assertEqual(response.data["data"]["validation"]["errors"], [])

        duplicate = self.upload_package(content, "duplicate.zip")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(ImportBatch.objects.count(), 1)
        batch_id = response.data["data"]["id"]
        detail = self.client.get(f"/api/v1/super-admin/collection/{batch_id}/")
        exported = self.client.get("/api/v1/super-admin/collection/export/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            exported["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        deleted = self.client.delete(f"/api/v1/super-admin/collection/{batch_id}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(ImportBatch.objects.exists())

    def test_collection_rejects_unsafe_archive_path(self):
        self.client.force_authenticate(self.super_admin)
        response = self.upload_package(
            collection_zip(school_code=self.formal_school.code, unsafe=True)
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], ImportBatch.Status.FAILED)
        self.assertTrue(response.data["data"]["validation"]["errors"])

    def test_cross_school_scope_and_health_are_super_admin_only(self):
        self.client.force_authenticate(self.super_admin)
        formal = self.client.get("/api/v1/super-admin/analysis/")
        with_test = self.client.get(
            "/api/v1/super-admin/analysis/?include_test_data=1"
        )
        health = self.client.get("/api/v1/super-admin/health/")
        analysis_export = self.client.get("/api/v1/super-admin/analysis/export/")
        health_export = self.client.get("/api/v1/super-admin/health/export/")

        self.assertEqual(formal.status_code, 200)
        self.assertEqual(len(formal.data["data"]["schools"]), 1)
        self.assertEqual(len(with_test.data["data"]["schools"]), 2)
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.data["data"]["checks"])
        self.assertEqual(analysis_export.status_code, 200)
        self.assertEqual(health_export.status_code, 200)

        self.client.force_authenticate(self.school_admin)
        for url in (
            "/api/v1/super-admin/collection/",
            "/api/v1/super-admin/analysis/",
            "/api/v1/super-admin/health/",
        ):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_school_dashboard_uses_clear_operational_language(self):
        self.client.force_authenticate(self.school_admin)
        response = self.client.get("/api/v1/school-admin/dashboard/")

        self.assertEqual(response.status_code, 200)
        metric_labels = [item["label"] for item in response.data["data"]["metrics"]]
        reminder_labels = [
            item["label"] for item in response.data["data"]["status_rows"]
        ]
        self.assertNotIn("待处理", metric_labels)
        self.assertNotIn("停用账号", reminder_labels)
        self.assertIn("近 7 天活跃学生", metric_labels)
