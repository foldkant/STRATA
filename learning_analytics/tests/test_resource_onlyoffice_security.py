from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from api.protected_files import protected_file_url
from api.views import _download_onlyoffice_callback_file
from config.onlyoffice import encode_jwt
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
    ResourceDocumentVersion,
    Subject,
)
from school.models import ClassGroup, School, StudentProfile


@override_settings(
    ONLYOFFICE_DOCUMENT_SERVER_URL="http://onlyoffice.test",
    ONLYOFFICE_JWT_SECRET="resource-onlyoffice-test-secret",
)
class ResourceOnlyOfficeSecurityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media_directory = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_directory.name)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        cls._media_directory.cleanup()

    def setUp(self):
        self.client = APIClient()
        self.school = School.objects.create(
            name="资源回调测试学校",
            code="RESOURCE-OFFICE",
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.other_class = ClassGroup.objects.create(
            school=self.school,
            name="高一2班",
            grade="高一",
        )
        self.teacher = User.objects.create_user(
            username="resource_callback_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.student = self._student("resource_callback_student", self.class_group)
        self.other_student = self._student(
            "resource_callback_other_student",
            self.other_class,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="课堂资源授权",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="课堂资源课时",
            is_active=True,
        )
        self.resource = Resource.objects.create(
            title="课堂内投放的私有文档",
            owner=self.teacher,
            subject=self.subject,
            visibility=Resource.Visibility.PRIVATE,
            publish_status=Resource.PublishStatus.PUBLISHED,
            attachment=SimpleUploadedFile(
                "classroom-resource.docx",
                b"original resource document",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            ),
        )
        self.step = LessonStep.objects.create(
            lesson=self.lesson,
            title="课堂资源学习",
            status=LessonStep.Status.READY,
            resource_items=[
                {
                    "id": self.resource.id,
                    "kind": "resource",
                    "title": self.resource.title,
                }
            ],
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="课堂资源授权测试",
            status=ClassroomSession.Status.RUNNING,
            current_step=self.step,
            current_step_status=ClassroomSession.StepStatus.OPEN,
        )

    def _student(self, username: str, class_group: ClassGroup):
        user = User.objects.create_user(
            username=username,
            password="Student123!",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=user,
            class_group=class_group,
            is_first_use=False,
        )
        return user

    def test_active_classroom_deployment_grants_read_only_resource_access(self):
        self.client.force_authenticate(self.student)
        config = self.client.get(
            f"/api/v1/resources/{self.resource.id}/office-config/?mode=edit"
        )
        self.assertEqual(config.status_code, 200, config.data)
        self.assertEqual(config.data["data"]["mode"], "view")
        self.assertFalse(config.data["data"]["can_edit"])

        attachment = self.client.get(
            protected_file_url("resource-attachment", self.resource.id)
        )
        self.assertEqual(attachment.status_code, 200)
        attachment.close()

        self.client.force_authenticate(self.other_student)
        denied = self.client.get(
            f"/api/v1/resources/{self.resource.id}/office-config/?mode=view"
        )
        self.assertEqual(denied.status_code, 404)

        self.session.current_step_status = ClassroomSession.StepStatus.CLOSED
        self.session.save(update_fields=["current_step_status", "updated_at"])
        self.client.force_authenticate(self.student)
        closed = self.client.get(
            f"/api/v1/resources/{self.resource.id}/office-config/?mode=view"
        )
        self.assertEqual(closed.status_code, 404)

    def test_resource_callback_requires_signature_and_creates_immutable_version(self):
        self.client.force_authenticate(self.teacher)
        config = self.client.get(
            f"/api/v1/resources/{self.resource.id}/office-config/?mode=edit"
        )
        self.assertEqual(config.status_code, 200, config.data)
        callback_key = config.data["data"]["config"]["document"]["key"]
        self.assertEqual(self.resource.document_versions.count(), 1)
        initial = self.resource.document_versions.get(version_no=1)
        initial_path = initial.file.name

        callback_payload = {
            "key": callback_key,
            "status": 2,
            "url": "http://onlyoffice.test/cache/resource.docx",
            "users": [str(self.teacher.id)],
        }
        self.client.force_authenticate(user=None)
        unsigned = self.client.post(
            f"/api/v1/resources/{self.resource.id}/office-callback/",
            callback_payload,
            format="json",
        )
        self.assertEqual(unsigned.status_code, 403)

        token = encode_jwt(
            callback_payload,
            "resource-onlyoffice-test-secret",
        )
        changed_document = b"changed resource document"
        with patch(
            "api.resource_views._download_onlyoffice_callback_file",
            return_value=changed_document,
        ):
            saved = self.client.post(
                f"/api/v1/resources/{self.resource.id}/office-callback/",
                callback_payload,
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json(), {"error": 0})

        self.resource.refresh_from_db()
        self.assertEqual(self.resource.document_versions.count(), 2)
        current = self.resource.document_versions.get(version_no=2)
        self.assertEqual(
            current.source,
            ResourceDocumentVersion.Source.ONLYOFFICE_CALLBACK,
        )
        self.assertEqual(current.verified_editor_ids, [str(self.teacher.id)])
        self.assertEqual(self.resource.attachment.name, current.file.name)
        self.assertNotEqual(initial_path, current.file.name)
        self.assertTrue(initial.file.storage.exists(initial_path))

        current.callback_key = "tampered"
        with self.assertRaisesMessage(
            Exception,
            "资源文档版本是不可变记录",
        ):
            current.save()

    def test_callback_download_rejects_unconfigured_origin_before_network_access(self):
        with self.assertRaisesMessage(ValueError, "不属于已配置文档服务器"):
            _download_onlyoffice_callback_file(
                "http://127.0.0.1/internal",
                max_bytes=1024,
            )

    def test_callback_rejects_wrong_document_key(self):
        payload = {
            "key": "resource-forged-key",
            "status": 2,
            "url": "http://onlyoffice.test/cache/resource.docx",
        }
        token = encode_jwt(payload, "resource-onlyoffice-test-secret")
        response = self.client.post(
            f"/api/v1/resources/{self.resource.id}/office-callback/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 409)

    @patch("api.classroom_views.urllib.request.build_opener")
    def test_callback_download_rejects_oversized_response(self, build_opener):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {"Content-Length": "2048"}
        response.geturl.return_value = "http://onlyoffice.test/cache/resource.docx"
        build_opener.return_value.open.return_value = response

        with self.assertRaisesMessage(ValueError, "超过允许大小"):
            _download_onlyoffice_callback_file(
                "http://onlyoffice.test/cache/resource.docx",
                max_bytes=1024,
            )
        response.read.assert_not_called()

    @patch("api.classroom_views.urllib.request.build_opener")
    def test_callback_download_rejects_cross_origin_redirect_result(self, build_opener):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {}
        response.geturl.return_value = "http://127.0.0.1/private"
        build_opener.return_value.open.return_value = response

        with self.assertRaisesMessage(ValueError, "跨主机跳转"):
            _download_onlyoffice_callback_file(
                "http://onlyoffice.test/cache/resource.docx",
                max_bytes=1024,
            )
