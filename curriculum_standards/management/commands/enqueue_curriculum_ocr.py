from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from curriculum_standards.models import (
    CurriculumExtractionStatus,
    CurriculumProcessingJobStatus,
    CurriculumProcessingMode,
    CurriculumProcessingPriority,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
)
from curriculum_standards.processing import (
    ACTIVE_JOB_STATUSES,
    create_processing_job,
    dispatch_processing_job,
)


class Command(BaseCommand):
    help = "逐份将课程标准 PDF 加入后台文字识别队列（可重复执行）。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--version-id",
            action="append",
            type=int,
            dest="version_ids",
            help="指定课程标准版本编号；可重复提交。",
        )
        parser.add_argument(
            "--all-needs-ocr",
            action="store_true",
            help="选择所有状态为“需要文字识别”的草稿版本。",
        )
        parser.add_argument("--dry-run", action="store_true", help="只显示计划，不创建任务。")
        parser.add_argument("--actor", default="superadmin", help="任务发起人的用户名。")
        parser.add_argument(
            "--priority",
            choices=CurriculumProcessingPriority.values,
            default=CurriculumProcessingPriority.LOW,
        )
    def handle(self, *args, **options):
        version_ids = options.get("version_ids") or []
        if not version_ids and not options["all_needs_ocr"]:
            raise CommandError("请提交 --version-id，或使用 --all-needs-ocr。")
        user_model = get_user_model()
        actor = user_model.objects.filter(username=options["actor"]).first()
        if not actor or not getattr(actor, "is_platform_admin", False):
            raise CommandError("任务发起人必须是有效的超级管理员账户。")

        versions = CurriculumStandardVersion.objects.select_related("source").filter(
            status=CurriculumVersionStatus.DRAFT
        )
        if options["all_needs_ocr"] and version_ids:
            versions = versions.filter(
                extraction_status=CurriculumExtractionStatus.NEEDS_OCR
            ) | versions.filter(pk__in=version_ids)
        elif options["all_needs_ocr"]:
            versions = versions.filter(extraction_status=CurriculumExtractionStatus.NEEDS_OCR)
        else:
            versions = versions.filter(pk__in=version_ids)
        versions = versions.distinct().order_by("id")

        selected = created = skipped = failed = 0
        for version in versions:
            selected += 1
            active = version.processing_jobs.filter(status__in=ACTIVE_JOB_STATUSES).first()
            if active:
                skipped += 1
                self.stdout.write(
                    f"跳过 version={version.id}：已有活动任务 job={active.id} ({active.status})。"
                )
                continue
            self.stdout.write(
                f"计划 version={version.id}：{version.official_title}（{version.version_label}）"
            )
            if options["dry_run"]:
                continue
            job, was_created = create_processing_job(
                version=version,
                actor=actor,
                mode=CurriculumProcessingMode.OCR,
                priority=options["priority"],
            )
            if not was_created:
                skipped += 1
                continue
            created += 1
            job = dispatch_processing_job(job)
            if job.status == CurriculumProcessingJobStatus.FAILED:
                failed += 1
                self.stderr.write(
                    f"派发失败 job={job.id} version={version.id}：{job.error_message}"
                )
            else:
                self.stdout.write(f"已入队 job={job.id} version={version.id}。")

        missing_ids = set(version_ids) - set(versions.values_list("id", flat=True))
        if missing_ids:
            self.stderr.write(
                "以下版本不存在或不是草稿，未入队：" + ", ".join(map(str, sorted(missing_ids)))
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"完成：选择 {selected}，新建 {created}，跳过 {skipped}，派发失败 {failed}。"
            )
        )
