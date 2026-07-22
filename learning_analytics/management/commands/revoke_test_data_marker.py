from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from learning_analytics.models import TestDataObjectMarker
from learning_analytics.services.test_data_governance import (
    SAFE_TEST_DATA_TARGET_MODELS,
    revoke_test_data_object_marker,
)


CONFIRMATION = "REVOKE_TEST_DATA_MARKER"


class Command(BaseCommand):
    help = "撤销误标的测试数据对象标记，保留原批次、对象和撤销审计记录。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--target",
            required=True,
            help="精确对象，格式为 app_label.ModelName:pk。",
        )
        parser.add_argument(
            "--actor", required=True, help="执行撤销的超级管理员用户名。"
        )
        parser.add_argument(
            "--reason", required=True, help="误标证据和撤销原因，至少 10 个字符。"
        )
        parser.add_argument(
            "--confirm",
            default="",
            help=f"正式撤销必须填写 {CONFIRMATION}。",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="核对标记和执行权限，但不写数据库。",
        )

    def handle(self, *args, **options):
        model_label, separator, raw_pk = str(options["target"] or "").partition(":")
        if not separator or "." not in model_label or not raw_pk.strip():
            raise CommandError("目标格式错误；应使用 app_label.ModelName:pk。")
        app_label, model_name = model_label.split(".", 1)
        app_label = app_label.strip().lower()
        model_name = model_name.strip().lower()
        canonical_model = f"{app_label}.{model_name}"
        if canonical_model not in SAFE_TEST_DATA_TARGET_MODELS:
            raise CommandError(f"不允许处理该模型：{canonical_model}。")

        user_model = get_user_model()
        try:
            actor = user_model.objects.get(username=options["actor"])
        except user_model.DoesNotExist as exc:
            raise CommandError("找不到指定执行人。") from exc
        if not (actor.is_superuser or actor.role == "super_admin"):
            raise CommandError("只有超级管理员可以撤销测试数据对象标记。")

        try:
            marker = TestDataObjectMarker.objects.select_related("batch").get(
                app_label=app_label,
                model_name=model_name,
                object_pk=raw_pk.strip(),
            )
        except TestDataObjectMarker.DoesNotExist as exc:
            raise CommandError("找不到指定测试数据对象标记。") from exc

        result = {
            "batch_code": marker.batch.batch_code,
            "target": f"{canonical_model}:{marker.object_pk}",
            "active_before": marker.is_active,
            "reason": options["reason"].strip(),
        }
        if options["dry_run"]:
            result["database_write"] = 0
            self.stdout.write(
                self.style.SUCCESS(
                    "[DRY-RUN] "
                    + json.dumps(result, ensure_ascii=False, sort_keys=True)
                )
            )
            return
        if options["confirm"] != CONFIRMATION:
            raise CommandError(f"正式撤销必须使用 --confirm {CONFIRMATION}。")

        try:
            marker, changed = revoke_test_data_object_marker(
                marker=marker,
                actor=actor,
                reason=options["reason"],
            )
        except ValidationError as exc:
            raise CommandError("；".join(exc.messages)) from exc
        result.update(
            {
                "changed": changed,
                "active_after": marker.is_active,
                "revoked_at": marker.revoked_at.isoformat()
                if marker.revoked_at
                else None,
            }
        )
        label = "[REVOKED]" if changed else "[UNCHANGED]"
        self.stdout.write(
            self.style.SUCCESS(
                label + " " + json.dumps(result, ensure_ascii=False, sort_keys=True)
            )
        )
