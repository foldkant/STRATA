from django.core.management.base import BaseCommand, CommandError

from learning_analytics.services.schema_registry import sync_event_schema_definitions


class Command(BaseCommand):
    help = "将代码中的学习事件模式注册表同步到数据库。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="只检查数据库是否已经包含一致的事件模式，不执行写入。",
        )

    def handle(self, *args, **options):
        result = sync_event_schema_definitions(check_only=options["check"])
        if options["check"] and (result["missing"] or result["mismatched"]):
            raise CommandError(
                f"事件模式检查失败：缺失 {result['missing']} 个，不一致 {result['mismatched']} 个。"
            )
        self.stdout.write(
            self.style.SUCCESS(
                "事件模式已就绪："
                f"新增 {result['created']}，一致 {result['unchanged']}，"
                f"缺失 {result['missing']}，不一致 {result['mismatched']}。"
            )
        )
