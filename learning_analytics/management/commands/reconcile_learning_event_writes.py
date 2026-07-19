import json

from django.core.management.base import BaseCommand, CommandError

from learning_analytics.services.dual_write import reconcile_v1_v2_events
from school.models import School


class Command(BaseCommand):
    help = "检查统一写入服务产生的 V1/V2 学习事件是否一一对应。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--school-code",
            default="",
            help="只检查指定学校代码；留空检查全部学校。",
        )
        parser.add_argument(
            "--max-examples",
            type=int,
            default=20,
            help="最多输出多少条异常示例。",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="发现缺失或映射不一致时返回非零退出码。",
        )

    def handle(self, *args, **options):
        school = None
        school_code = str(options["school_code"] or "").strip()
        if school_code:
            school = School.objects.filter(code=school_code).first()
            if school is None:
                raise CommandError(f"学校代码不存在：{school_code}")
        result = reconcile_v1_v2_events(
            school=school,
            max_examples=max(int(options["max_examples"] or 0), 0),
        )
        self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        if options["check"] and not result["consistent"]:
            raise CommandError(
                "V1/V2 学习事件对账失败："
                f"缺失 {result['missing_v2_count']} 条，"
                f"映射不一致 {result['mapping_mismatch_count']} 条。"
            )
        if result["consistent"]:
            self.stdout.write(self.style.SUCCESS("V1/V2 学习事件对账通过。"))
