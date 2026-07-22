from django.core.management.base import BaseCommand

from curriculum_standards.models import CurriculumProcessingJob, CurriculumProcessingJobStatus


class Command(BaseCommand):
    help = "只读检查课程标准后台队列状态，供 Worker 安全停止脚本使用。"

    def add_arguments(self, parser):
        parser.add_argument("--exit-nonzero-if-active", action="store_true")

    def handle(self, *args, **options):
        counts = {
            status: CurriculumProcessingJob.objects.filter(status=status).count()
            for status in CurriculumProcessingJobStatus.values
        }
        active_workers = (
            counts[CurriculumProcessingJobStatus.RUNNING]
            + counts[CurriculumProcessingJobStatus.CANCELLING]
        )
        self.stdout.write(
            " ".join(f"{status}={counts[status]}" for status in CurriculumProcessingJobStatus.values)
        )
        if options["exit_nonzero_if_active"] and active_workers:
            raise SystemExit(2)
