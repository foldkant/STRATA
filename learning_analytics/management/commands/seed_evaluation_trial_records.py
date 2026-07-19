from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from learning_analytics.evaluation_models import (
    EvaluationStandardVersion,
    EvaluationTrialConclusion,
    EvaluationTrialRecord,
    EvaluationTrialStatus,
    EvaluationTrialType,
)
from school.models import School


TEST_PREFIX = "测试-"


class Command(BaseCommand):
    help = "为教师评价标准页面创建或清理评价试用测试记录。"

    def add_arguments(self, parser):
        parser.add_argument("--school-code", required=True)
        parser.add_argument("--username")
        parser.add_argument("--standard-version-id", type=int)
        parser.add_argument("--purge", action="store_true")

    def handle(self, *args, **options):
        school = School.objects.filter(code=options["school_code"]).first()
        if school is None:
            raise CommandError("未找到指定学校。")

        records = EvaluationTrialRecord.objects.filter(
            school=school,
            title__startswith=TEST_PREFIX,
        )
        if options["purge"]:
            deleted, _ = records.delete()
            self.stdout.write(self.style.SUCCESS(f"已清理 {deleted} 条评价试用测试记录。"))
            return

        teachers = User.objects.filter(
            school=school,
            role=User.Role.TEACHER,
            is_active=True,
        )
        if options.get("username"):
            teacher = teachers.filter(username=options["username"]).first()
        else:
            teacher = None
        if options.get("username") and teacher is None:
            raise CommandError("未找到可用的教师账号。")

        versions = EvaluationStandardVersion.objects.filter(school=school)
        if teacher is not None:
            versions = versions.filter(course__teacher=teacher)
        if options.get("standard_version_id"):
            version = versions.filter(pk=options["standard_version_id"]).first()
        else:
            version = versions.order_by("-published_at", "-id").first()
        if version is None:
            raise CommandError("该教师没有已发布评价标准，请先发布评价标准。")
        teacher = version.course.teacher

        today = timezone.localdate()
        rows = [
            {
                "record_type": EvaluationTrialType.CONTENT_REVIEW,
                "title": f"{TEST_PREFIX}评价内容审核",
                "status": EvaluationTrialStatus.COMPLETED,
                "activity_date": today - timedelta(days=12),
                "participant_count": 4,
                "agreement_rate": None,
                "conclusion": EvaluationTrialConclusion.REVISE,
                "summary": "测试记录：审核人员认为评价目标清楚，但部分星级说明需要进一步区分。",
                "issues": ["二星和三星说明区分不够明显", "一个评分示例描述过于简略"],
                "action_items": ["修改星级说明", "补充评分示例后发布新版本"],
            },
            {
                "record_type": EvaluationTrialType.CLASSROOM_TRIAL,
                "title": f"{TEST_PREFIX}高一课堂试用",
                "status": EvaluationTrialStatus.COMPLETED,
                "activity_date": today - timedelta(days=8),
                "participant_count": 42,
                "agreement_rate": None,
                "conclusion": EvaluationTrialConclusion.READY,
                "summary": "测试记录：学生能够理解任务要求，教师能够在课堂结束前完成主要指标评价。",
                "issues": ["手机端较长说明需要分段显示"],
                "action_items": ["保持当前指标数量", "继续观察两次课堂使用情况"],
            },
            {
                "record_type": EvaluationTrialType.SCORER_TRAINING,
                "title": f"{TEST_PREFIX}教师评分培训",
                "status": EvaluationTrialStatus.COMPLETED,
                "activity_date": today - timedelta(days=5),
                "participant_count": 6,
                "agreement_rate": None,
                "conclusion": EvaluationTrialConclusion.READY,
                "summary": "测试记录：教师完成示例讲解和独立试评，主要分歧集中在边界作品。",
                "issues": ["四星与五星边界作品仍有分歧"],
                "action_items": ["增加一份边界作品评分示例"],
            },
            {
                "record_type": EvaluationTrialType.SCORING_CHECK,
                "title": f"{TEST_PREFIX}评分一致性检查",
                "status": EvaluationTrialStatus.COMPLETED,
                "activity_date": today - timedelta(days=2),
                "participant_count": 6,
                "agreement_rate": Decimal("86.50"),
                "conclusion": EvaluationTrialConclusion.REVISE,
                "summary": "测试记录：六名教师对同一批作品独立评分，整体一致率为 86.50%。",
                "issues": ["边界作品的一致率低于整体水平"],
                "action_items": ["修订边界说明后重新检查"],
            },
        ]

        created_count = 0
        updated_count = 0
        for row in rows:
            _, created = EvaluationTrialRecord.objects.update_or_create(
                school=school,
                standard_version=version,
                title=row["title"],
                defaults={
                    **row,
                    "created_by": teacher,
                    "updated_by": teacher,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"评价标准：{version.title} v{version.version_no}；"
                f"新增 {created_count} 条，更新 {updated_count} 条测试记录。"
            )
        )
