from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
    Subject,
)
from school.models import ClassGroup, School, StudentProfile


class Command(BaseCommand):
    help = "Create the minimal isolated teaching context used by the browser quality gate."

    @transaction.atomic
    def handle(self, *args, **options):
        if any(
            model.objects.exists()
            for model in (User, School, Course, Resource, ClassroomSession)
        ):
            raise CommandError(
                "端到端质量门禁数据只能写入全新的隔离数据库，当前数据库已有业务数据。"
            )

        school = School.objects.create(
            name="端到端测试学校",
            code="E2E",
            is_synthetic=True,
        )
        class_group = ClassGroup.objects.create(
            school=school,
            name="七年级1班",
            grade="七年级",
        )
        User.objects.create_user(
            username="e2e_super",
            password="E2eSmoke123!",
            role=User.Role.SUPER_ADMIN,
            display_name="平台测试管理员",
            is_first_login=False,
        )
        User.objects.create_user(
            username="e2e_school",
            password="E2eSmoke123!",
            role=User.Role.SCHOOL_ADMIN,
            school=school,
            display_name="学校测试管理员",
            is_first_login=False,
        )
        teacher = User.objects.create_user(
            username="e2e_teacher",
            password="E2eSmoke123!",
            role=User.Role.TEACHER,
            school=school,
            display_name="信息科技测试教师",
            is_first_login=False,
        )
        student = User.objects.create_user(
            username="e2e_student",
            password="E2eSmoke123!",
            role=User.Role.STUDENT,
            school=school,
            display_name="测试学生",
            is_first_login=False,
        )
        StudentProfile.objects.create(
            user=student,
            class_group=class_group,
            student_no="E2E001",
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        class_group.teachers.add(teacher)

        subject = Subject.objects.create(
            school=school,
            name="信息科技",
            code="IT",
        )
        course = Course.objects.create(
            subject=subject,
            title="数据与计算",
            teacher=teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=course,
            class_group=class_group,
            created_by=teacher,
        )
        lesson = Lesson.objects.create(
            course=course,
            title="图像编码与数据量估算",
            content="通过实例理解图像编码。",
            is_active=True,
        )
        resource = Resource.objects.create(
            title="演示文稿1",
            content="用于端到端验证课堂投放资源的访问权限。",
            attachment=SimpleUploadedFile(
                "e2e-demo.pptx",
                b"isolated e2e presentation placeholder",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation"
                ),
            ),
            resource_type=Resource.ResourceType.FILE,
            category=Resource.Category.COURSEWARE,
            visibility=Resource.Visibility.PRIVATE,
            publish_status=Resource.PublishStatus.PUBLISHED,
            subject=subject,
            owner=teacher,
            published_at=timezone.now(),
        )
        step = LessonStep.objects.create(
            lesson=lesson,
            title="分析图像编码",
            step_type=LessonStep.StepType.RESOURCE,
            student_instruction="阅读演示文稿，比较不同编码方案。",
            status=LessonStep.Status.READY,
            resource_items=[
                {
                    "id": resource.id,
                    "title": resource.title,
                    "attachment_url": (
                        f"/api/v1/files/resources/{resource.id}/attachment/"
                    ),
                    "attachment_name": "e2e-demo.pptx",
                    "file_ext": "pptx",
                    "kind": "resource",
                    "resource_type": Resource.ResourceType.FILE,
                }
            ],
            created_by=teacher,
        )
        session = ClassroomSession.objects.create(
            school=school,
            teacher=teacher,
            course=course,
            lesson=lesson,
            class_group=class_group,
            title="图像编码课堂",
            status=ClassroomSession.Status.RUNNING,
            current_step=step,
            current_step_status=ClassroomSession.StepStatus.OPEN,
            evaluation_enabled=True,
            current_step_started_at=timezone.now(),
            started_at=timezone.now(),
        )

        if (course.id, lesson.id, resource.id, session.id) != (1, 1, 1, 1):
            raise CommandError(
                "隔离数据库的关键对象编号不是 1，请检查数据库是否真正为空。"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "端到端质量门禁数据已建立：课程 1、课时 1、资源 1、课堂 1。"
            )
        )
