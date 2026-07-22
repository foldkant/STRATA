from django.core.management.base import BaseCommand

from curriculum_standards.processing import (
    reconcile_stale_processing_jobs,
    redispatch_stale_queued_jobs,
)


class Command(BaseCommand):
    help = "核对失联任务，并可安全重派长时间未开始的等待任务。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--redispatch-stale-queued",
            action="store_true",
            help="使用同一 task id 重派长时间未开始的等待任务。",
        )
        parser.add_argument(
            "--queued-stale-seconds",
            type=int,
            default=300,
            help="等待任务重派阈值，最小 60 秒。",
        )

    def handle(self, *args, **options):
        count = reconcile_stale_processing_jobs()
        self.stdout.write(f"已将 {count} 个失联运行任务标记为失败。")
        if options["redispatch_stale_queued"]:
            result = redispatch_stale_queued_jobs(
                stale_seconds=options["queued_stale_seconds"]
            )
            self.stdout.write(
                "等待任务重派：选择 {selected}，成功 {redispatched}，失败 {failed}。".format(
                    **result
                )
            )
        self.stdout.write(self.style.SUCCESS("课程标准后台任务核对完成。"))
