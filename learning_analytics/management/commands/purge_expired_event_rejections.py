from django.core.management.base import BaseCommand
from django.utils import timezone

from learning_analytics.models import LearningEventRejection


class Command(BaseCommand):
    help = "删除超过本地保留期限的加密事件拒绝记录。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="只统计，不执行删除。"
        )

    def handle(self, *args, **options):
        expired = LearningEventRejection.objects.filter(
            retention_expires_at__lte=timezone.now()
        )
        count = expired.count()
        if options["dry_run"]:
            self.stdout.write(f"过期事件拒绝记录：{count} 条。")
            return
        deleted, _ = expired.delete()
        self.stdout.write(self.style.SUCCESS(f"已清理 {deleted} 条过期事件拒绝记录。"))
