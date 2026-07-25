from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from courses.models import Course
from curriculum_standards.services import subject_names_equivalent
from research.models import ResearchStudy
from school.models import School


CONFIRMATION = "SEED-INFORMATION-TECHNOLOGY-EXPERIMENT-EXAMPLE"
EXAMPLE_CODE = "IT-CLASS-EXPERIMENT-EXAMPLE"
EXAMPLE_TITLE = "【示例草稿】信息科技项目式学习班级对照实验"


class Command(BaseCommand):
    help = "为学校管理员建立一项明确标识的信息科技教育实验草稿，不安排班级、不生成研究结论。"

    def add_arguments(self, parser):
        parser.add_argument("--school-code", required=True)
        parser.add_argument("--school-admin", required=True)
        parser.add_argument("--course-id", type=int, required=True)
        parser.add_argument("--confirmation", default="")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["confirmation"] != CONFIRMATION:
            raise CommandError(f"必须提供 --confirmation {CONFIRMATION}。")
        school = School.objects.filter(code=options["school_code"]).first()
        if school is None:
            raise CommandError("学校不存在。")
        admin = User.objects.filter(
            username=options["school_admin"],
            school=school,
            role=User.Role.SCHOOL_ADMIN,
            is_active=True,
        ).first()
        if admin is None:
            raise CommandError("未找到该校有效的学校管理员账号。")
        course = (
            Course.objects.select_related("subject")
            .filter(pk=options["course_id"], subject__school=school, is_active=True)
            .first()
        )
        if course is None:
            raise CommandError("课程不存在、不属于该校或已经停用。")
        if not subject_names_equivalent(course.subject.name, "信息科技"):
            raise CommandError("示例当前只用于信息科技或信息技术课程。")

        study, created = ResearchStudy.objects.get_or_create(
            school=school,
            code=EXAMPLE_CODE,
            defaults={
                "title": EXAMPLE_TITLE,
                "subject": course.subject,
                "course": course,
                "description": (
                    "在共同学习起点诊断基础上，比较项目式学习与常规教学安排中，"
                    "学生在数据处理、问题解决、作品表达和个人说明方面的学习表现；"
                    "后测可由表现任务、作品评价和学生问卷共同构成。"
                ),
                "created_by": admin,
                "updated_by": admin,
            },
        )
        if not created and study.current_protocol_id:
            raise CommandError("同编号实验已经进入正式方案登记，示例命令不会覆盖。")
        self.stdout.write(
            self.style.SUCCESS(
                f"{'已建立' if created else '已存在'}教育实验示例草稿：{study.title}。"
            )
        )
        self.stdout.write("草稿未安排班级、未启动实验，也未生成任何教育效果结论。")
