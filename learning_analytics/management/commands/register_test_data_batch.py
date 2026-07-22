from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from learning_analytics.models import TestDataBatch, TestDataObjectMarker
from learning_analytics.services.test_data_governance import (
    build_test_data_manifest,
    resolve_explicit_test_data_targets,
)


CONFIRMATION = "REGISTER_TEST_DATA"


class Command(BaseCommand):
    help = (
        "把明确指定的非个人业务对象登记到不可变测试数据批次；"
        "不会根据标题、前缀或内容自动推断。"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-code", required=True, help="以 TEST- 开头的唯一批次编号。"
        )
        parser.add_argument(
            "--purpose",
            required=True,
            choices=[value for value, _ in TestDataBatch.Purpose.choices],
            help="该批次唯一允许的数据用途。",
        )
        parser.add_argument(
            "--source-kind",
            required=True,
            choices=[value for value, _ in TestDataBatch.SourceKind.choices],
            help="测试数据来源类型。",
        )
        parser.add_argument(
            "--description", required=True, help="来源、范围和禁止用途说明。"
        )
        parser.add_argument(
            "--target",
            action="append",
            required=True,
            help="明确对象，格式为 app_label.ModelName:pk；可重复。",
        )
        parser.add_argument(
            "--actor", required=True, help="执行登记的超级管理员用户名。"
        )
        parser.add_argument(
            "--confirm",
            default="",
            help=f"正式登记必须填写 {CONFIRMATION}。",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="完成全部对象和权限校验并输出清单，但不写数据库。",
        )

    def handle(self, *args, **options):
        user_model = get_user_model()
        try:
            actor = user_model.objects.get(username=options["actor"])
        except user_model.DoesNotExist as exc:
            raise CommandError("找不到指定执行人。") from exc
        if not (actor.is_superuser or actor.role == "super_admin"):
            raise CommandError("只有超级管理员可以登记测试数据批次。")

        try:
            targets = resolve_explicit_test_data_targets(options["target"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        manifest, manifest_hash = build_test_data_manifest(targets)

        result = {
            "batch_code": options["batch_code"],
            "purpose": options["purpose"],
            "source_kind": options["source_kind"],
            "target_count": len(targets),
            "manifest_hash": manifest_hash,
            "targets": manifest,
        }
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "[DRY-RUN] "
                    + json.dumps(result, ensure_ascii=False, sort_keys=True)
                )
            )
            return
        if options["confirm"] != CONFIRMATION:
            raise CommandError(f"正式登记必须使用 --confirm {CONFIRMATION}。")

        with transaction.atomic():
            existing_batch = TestDataBatch.objects.filter(
                batch_code=options["batch_code"]
            ).first()
            if existing_batch is not None:
                expected = {
                    "purpose": options["purpose"],
                    "source_kind": options["source_kind"],
                    "description": options["description"].strip(),
                    "target_count": len(targets),
                    "manifest_hash": manifest_hash,
                }
                actual = {key: getattr(existing_batch, key) for key in expected}
                marker_keys = {
                    f"{marker.app_label}.{marker.model_name}:{marker.object_pk}"
                    for marker in existing_batch.object_markers.all()
                }
                target_keys = {target.canonical_key for target in targets}
                if actual != expected or marker_keys != target_keys:
                    raise CommandError(
                        "同名批次已经存在但清单或用途不同；不可覆盖，请建立新的批次编号。"
                    )
                result["created"] = False
                self.stdout.write(
                    self.style.SUCCESS(
                        "[UNCHANGED] "
                        + json.dumps(result, ensure_ascii=False, sort_keys=True)
                    )
                )
                return

            occupied = {
                f"{marker.app_label}.{marker.model_name}:{marker.object_pk}": marker.batch.batch_code
                for marker in TestDataObjectMarker.objects.select_related(
                    "batch"
                ).filter(
                    app_label__in={target.app_label for target in targets},
                    model_name__in={target.model_name for target in targets},
                    object_pk__in={target.object_pk for target in targets},
                )
            }
            conflicts = {
                target.canonical_key: occupied[target.canonical_key]
                for target in targets
                if target.canonical_key in occupied
            }
            if conflicts:
                raise CommandError(
                    "以下对象已属于其他测试批次："
                    + json.dumps(conflicts, ensure_ascii=False, sort_keys=True)
                )

            batch = TestDataBatch.objects.create(
                batch_code=options["batch_code"],
                purpose=options["purpose"],
                source_kind=options["source_kind"],
                description=options["description"].strip(),
                target_count=len(targets),
                manifest_hash=manifest_hash,
                created_by=actor,
            )
            for target in targets:
                TestDataObjectMarker.objects.create(
                    batch=batch,
                    app_label=target.app_label,
                    model_name=target.model_name,
                    object_pk=target.object_pk,
                    object_label=target.object_label,
                    marked_by=actor,
                )

        result["created"] = True
        self.stdout.write(
            self.style.SUCCESS(
                "[CREATED] " + json.dumps(result, ensure_ascii=False, sort_keys=True)
            )
        )
