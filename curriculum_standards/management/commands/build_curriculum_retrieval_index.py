from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from curriculum_standards.models import (
    CurriculumExtractionStatus,
    CurriculumStandardAuditLog,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
)
from curriculum_standards.retrieval import rebuild_retrieval_index


class Command(BaseCommand):
    help = "为指定课程标准版本建立稳定、可追溯的本地检索片段索引。"

    def add_arguments(self, parser):
        parser.add_argument("--version-id", action="append", type=int, dest="version_ids")
        parser.add_argument("--all-published", action="store_true")
        parser.add_argument("--all-completed", action="store_true")
        parser.add_argument(
            "--include-unpublished",
            action="store_true",
            help="与 --all-completed 配合时明确允许处理未发布版本。",
        )
        parser.add_argument("--max-chars", type=int)
        parser.add_argument("--overlap-chars", type=int)
        parser.add_argument("--actor", default="")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        version_ids = list(dict.fromkeys(options.get("version_ids") or []))
        if not (version_ids or options["all_published"] or options["all_completed"]):
            raise CommandError(
                "请使用 --version-id、--all-published 或 --all-completed 明确选择版本。"
            )
        if options["all_completed"] and not options["include_unpublished"]:
            raise CommandError(
                "--all-completed 会包含草稿；必须同时显式使用 --include-unpublished。"
            )

        if not options["dry_run"] and not options["actor"]:
            raise CommandError(
                "非 dry-run 建立检索索引时必须使用 --actor 指定超级管理员账号。"
            )

        selected = Q()
        if version_ids:
            selected |= Q(pk__in=version_ids)
        if options["all_published"]:
            selected |= Q(status=CurriculumVersionStatus.PUBLISHED)
        if options["all_completed"]:
            selected |= Q(extraction_status=CurriculumExtractionStatus.COMPLETED)
        versions = (
            CurriculumStandardVersion.objects.select_related("source")
            .filter(selected)
            .order_by("school_stage_snapshot", "subject_name_snapshot", "publication_year", "id")
        )
        if not options["include_unpublished"] and not version_ids:
            versions = versions.filter(status=CurriculumVersionStatus.PUBLISHED)
        missing_ids = set(version_ids) - set(versions.values_list("id", flat=True))
        if missing_ids:
            raise CommandError(f"课程标准版本不存在：{sorted(missing_ids)}")

        actor = None
        if options["actor"]:
            User = get_user_model()
            actor = (
                User.objects.filter(username=options["actor"])
                .filter(Q(is_superuser=True) | Q(role="super_admin"))
                .first()
            )
            if actor is None:
                raise CommandError("未找到指定的超级管理员账号。")

        rows = []
        failed = 0
        for version in versions:
            item = {
                "version_id": version.id,
                "title": version.official_title,
                "version_label": version.version_label,
                "status": version.status,
                "extraction_status": version.extraction_status,
            }
            if options["dry_run"]:
                item["result"] = "would_build"
                rows.append(item)
                continue
            try:
                with transaction.atomic():
                    index, rebuilt = rebuild_retrieval_index(
                        version,
                        actor=actor,
                        max_chars=options.get("max_chars"),
                        overlap_chars=options.get("overlap_chars"),
                    )
                    if rebuilt:
                        CurriculumStandardAuditLog.objects.create(
                            version=version,
                            action="retrieval_index_rebuilt",
                            actor=actor,
                            detail={
                                "index_hash": index.index_hash,
                                "chunk_count": index.chunk_count,
                                "backend": index.backend,
                                "strategy": index.strategy,
                                "strategy_version": index.strategy_version,
                                "max_chars": index.max_chars,
                                "overlap_chars": index.overlap_chars,
                                "source": "management_command",
                            },
                        )
            except ValidationError as exc:
                failed += 1
                item.update({"result": "failed", "errors": exc.messages})
            else:
                item.update(
                    {
                        "result": "rebuilt" if rebuilt else "unchanged",
                        "chunk_count": index.chunk_count,
                        "index_hash": index.index_hash,
                        "backend": index.backend,
                    }
                )
            rows.append(item)

        result = {
            "selected": len(rows),
            "failed": failed,
            "dry_run": bool(options["dry_run"]),
            "versions": rows,
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                self.stdout.write(
                    f"{row['version_id']} {row['version_label']} {row['result']} "
                    f"chunks={row.get('chunk_count', '-')}"
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"已检查 {len(rows)} 个版本；失败 {failed} 个。"
                )
            )
        if failed:
            raise CommandError("部分课程标准检索索引建立失败。")
