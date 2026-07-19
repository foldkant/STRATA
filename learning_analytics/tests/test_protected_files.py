from __future__ import annotations

import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from api.protected_files import protected_file_url, signed_protected_file_url
from api.serializers import (
    classroom_group_file_row,
    classroom_group_row,
    course_row,
    resource_row,
    student_work_attachment_row,
)
from courses.models import (
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupFile,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
    ResourceFile,
    Subject,
)
from learning.models import StudentWorkAttachment
from school.models import ClassGroup, School, StudentProfile


class ProtectedFileAccessTests(TestCase):
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
        self.school = School.objects.create(name="File School", code="FILE-SCHOOL")
        self.other_school = School.objects.create(
            name="Other File School", code="OTHER-FILE-SCHOOL"
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="Class 1", grade="Grade 1"
        )
        self.other_class = ClassGroup.objects.create(
            school=self.school, name="Class 2", grade="Grade 1"
        )
        self.teacher = User.objects.create_user(
            username="file_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.school_admin = User.objects.create_user(
            username="file_school_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.other_admin = User.objects.create_user(
            username="other_file_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.other_school,
        )
        self.student = self._student("file_student", self.class_group)
        self.other_student = self._student("other_file_student", self.other_class)
        self.subject = Subject.objects.create(
            school=self.school, name="Computing", code="FILE-COMPUTING"
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="Protected course",
            teacher=self.teacher,
            is_active=True,
            cover=SimpleUploadedFile("course-cover.png", b"course-cover"),
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(
            course=self.course, title="Protected lesson", is_active=True
        )
        self.step = LessonStep.objects.create(
            lesson=self.lesson, title="Protected step", status=LessonStep.Status.READY
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="Protected classroom",
            status=ClassroomSession.Status.RUNNING,
        )
        self.resource = Resource.objects.create(
            title="Class resource",
            owner=self.teacher,
            subject=self.subject,
            visibility=Resource.Visibility.CLASSES,
            publish_status=Resource.PublishStatus.PUBLISHED,
            attachment=SimpleUploadedFile("lesson.pptx", b"pptx-data"),
            cover=SimpleUploadedFile("resource-cover.png", b"resource-cover"),
        )
        self.resource.target_classes.add(self.class_group)
        self.extra_file = ResourceFile.objects.create(
            resource=self.resource,
            file=SimpleUploadedFile("supplement.pdf", b"pdf-data"),
            original_name="supplement.pdf",
            file_ext="pdf",
            file_size=8,
        )
        self.work = StudentWorkAttachment.objects.create(
            school=self.school,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            lesson_step=self.step,
            classroom_session=self.session,
            student=self.student,
            question_id="upload-1",
            attachment=SimpleUploadedFile("student-work.zip", b"student-work"),
            original_name="student-work.zip",
            file_ext="zip",
            file_size=12,
        )
        self.collaboration = ClassroomGroupCollaboration.objects.create(
            session=self.session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.OPEN,
            created_by=self.teacher,
        )
        self.group = ClassroomGroup.objects.create(
            collaboration=self.collaboration,
            group_no=1,
            name="Group 1",
            collaboration_document=SimpleUploadedFile("group.docx", b"group-doc"),
            document_original_name="group.docx",
            document_file_ext="docx",
        )
        ClassroomGroupMember.objects.create(
            collaboration=self.collaboration,
            group=self.group,
            student=self.student,
            student_profile=self.student.student_profile,
        )
        self.group_file = ClassroomGroupFile.objects.create(
            group=self.group,
            uploader=self.student,
            attachment=SimpleUploadedFile("group-file.xlsx", b"group-file"),
            original_name="group-file.xlsx",
            file_ext="xlsx",
            file_size=10,
        )
        self.client = APIClient()

    def tearDown(self):
        fields = [
            self.course.cover,
            self.resource.attachment,
            self.resource.cover,
            self.extra_file.file,
            self.work.attachment,
            self.group.collaboration_document,
            self.group_file.attachment,
        ]
        for field in fields:
            field.close()
        super().tearDown()

    def _student(self, username: str, class_group: ClassGroup) -> User:
        student = User.objects.create_user(
            username=username,
            password="123456",
            role=User.Role.STUDENT,
            school=class_group.school,
        )
        StudentProfile.objects.create(
            user=student, class_group=class_group, is_first_use=False
        )
        return student

    def _get(self, user, url):
        self.client.force_authenticate(user=user)
        response = self.client.get(url)
        for closer in list(getattr(response, "_resource_closers", [])):
            closer()
        response._resource_closers = []
        return response

    def test_student_can_open_assigned_course_and_class_resource_files(self):
        urls = [
            protected_file_url("course-cover", self.course.id),
            protected_file_url("resource-attachment", self.resource.id),
            protected_file_url("resource-cover", self.resource.id),
            protected_file_url("resource-extra", self.extra_file.id),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self._get(self.student, url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_student_outside_target_class_cannot_open_resource_files(self):
        urls = [
            protected_file_url("resource-attachment", self.resource.id),
            protected_file_url("resource-cover", self.resource.id),
            protected_file_url("resource-extra", self.extra_file.id),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self._get(self.other_student, url).status_code, 404)

    def test_student_work_is_private_to_owner_and_authorized_staff(self):
        url = protected_file_url("student-work", self.work.id)
        self.assertEqual(self._get(self.student, url).status_code, 200)
        self.assertEqual(self._get(self.other_student, url).status_code, 404)
        self.assertEqual(self._get(self.teacher, url).status_code, 200)
        self.assertEqual(self._get(self.school_admin, url).status_code, 200)
        self.assertEqual(self._get(self.other_admin, url).status_code, 404)

    def test_group_files_are_private_to_members_and_authorized_staff(self):
        urls = [
            protected_file_url("group-file", self.group_file.id),
            protected_file_url("group-document", self.group.id),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self._get(self.student, url).status_code, 200)
                self.assertEqual(self._get(self.other_student, url).status_code, 404)
                self.assertEqual(self._get(self.teacher, url).status_code, 200)
                self.assertEqual(self._get(self.school_admin, url).status_code, 200)
                self.assertEqual(self._get(self.other_admin, url).status_code, 404)

    def test_onlyoffice_signed_url_is_scoped_tamper_proof_and_expiring(self):
        version = self.resource.attachment.name
        url = signed_protected_file_url(
            "resource-attachment", self.resource.id, version=version
        )
        self.assertEqual(self._get(None, url).status_code, 200)
        wrong_version_url = signed_protected_file_url(
            "resource-attachment", self.resource.id, version="old-version"
        )
        self.assertEqual(self._get(None, wrong_version_url).status_code, 404)
        self.assertEqual(self._get(None, f"{url}tampered").status_code, 404)
        with patch("api.protected_files.FILE_TOKEN_MAX_AGE", -1):
            self.assertEqual(self._get(None, url).status_code, 404)

    def test_debug_does_not_expose_media_root_directly(self):
        raw_url = f"/media/{self.resource.attachment.name}"
        self.assertEqual(self._get(self.student, raw_url).status_code, 404)

    def test_serializers_only_return_protected_file_urls(self):
        rows = [
            course_row(self.course),
            resource_row(self.resource, viewer=self.teacher),
            student_work_attachment_row(self.work),
            classroom_group_file_row(self.group_file),
            classroom_group_row(self.group),
        ]
        self.assertNotIn("/media/", repr(rows))
        self.assertIn("/api/v1/files/", repr(rows))
