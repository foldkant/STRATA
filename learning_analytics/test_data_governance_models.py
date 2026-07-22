from __future__ import annotations

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


TEST_BATCH_CODE_PATTERN = re.compile(r"^TEST-[A-Z0-9][A-Z0-9._-]{2,63}$")


class TestDataBatch(models.Model):
    """Immutable manifest for one explicitly identified non-production data batch."""

    class Purpose(models.TextChoices):
        DEVELOPMENT_TESTING = "development_testing", "开发测试"
        ACCEPTANCE_TESTING = "acceptance_testing", "验收测试"
        MIGRATION_VERIFICATION = "migration_verification", "迁移验证"
        RESEARCH_SANDBOX = "research_sandbox", "研究沙盒"

    class SourceKind(models.TextChoices):
        HISTORICAL_MANUAL = "historical_manual", "历史或手工测试数据"
        SCRIPTED_FIXTURE = "scripted_fixture", "脚本生成测试数据"
        MIGRATION_RESULT = "migration_result", "迁移验证结果"

    batch_code = models.CharField(max_length=72, unique=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    source_kind = models.CharField(max_length=32, choices=SourceKind.choices)
    description = models.TextField()
    target_count = models.PositiveIntegerField()
    manifest_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_test_data_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["purpose", "created_at"],
                name="la_tdb_purpose_created",
            )
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        errors = {}
        if not TEST_BATCH_CODE_PATTERN.fullmatch(self.batch_code or ""):
            errors["batch_code"] = (
                "测试数据批次编号必须以 TEST- 开头，且只包含大写字母、数字、点、横线或下划线。"
            )
        if self.target_count < 1:
            errors["target_count"] = "测试数据批次至少应包含一个明确对象。"
        if not re.fullmatch(r"[0-9a-f]{64}", self.manifest_hash or ""):
            errors["manifest_hash"] = "批次清单校验值必须是 64 位小写 SHA-256。"
        if not (self.description or "").strip():
            errors["description"] = "必须说明该测试数据批次的来源和用途。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "测试数据批次清单不可修改；范围变化时必须建立新批次。"
            )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("测试数据批次清单不可删除；清理数据后仍须保留审计记录。")

    def __str__(self) -> str:
        return self.batch_code


class TestDataObjectMarker(models.Model):
    """Immutable exact-object membership in a test-data batch.

    The marker is deliberately not inferred from titles such as ``test`` or ``SIM``.
    It identifies exactly one model and primary key and remains as an audit record if
    the target is later removed.
    """

    batch = models.ForeignKey(
        TestDataBatch,
        on_delete=models.PROTECT,
        related_name="object_markers",
    )
    app_label = models.CharField(max_length=64)
    model_name = models.CharField(max_length=64)
    object_pk = models.CharField(max_length=64)
    object_label = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_data_object_markers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_test_data_object_markers",
    )
    revocation_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["app_label", "model_name", "object_pk"],
                name="uniq_test_data_object_marker",
            )
        ]
        indexes = [
            models.Index(
                fields=["batch", "created_at"],
                name="la_tdmark_batch_created",
            ),
            models.Index(
                fields=["app_label", "model_name", "object_pk"],
                name="la_tdmark_object_lookup",
            ),
        ]
        ordering = ["batch_id", "app_label", "model_name", "object_pk"]

    def clean(self) -> None:
        errors = {}
        if self.app_label != (self.app_label or "").lower():
            errors["app_label"] = "应用名称必须使用小写规范名称。"
        if self.model_name != (self.model_name or "").lower():
            errors["model_name"] = "模型名称必须使用小写规范名称。"
        if not (self.object_pk or "").strip():
            errors["object_pk"] = "必须记录测试对象的主键。"
        if not (self.object_label or "").strip():
            errors["object_label"] = "必须保存对象名称快照，供迁移复核。"
        revocation_fields_present = bool(
            self.revoked_at
            or self.revoked_by_id
            or (self.revocation_reason or "").strip()
        )
        if self.is_active and revocation_fields_present:
            errors["is_active"] = "仍生效的测试数据对象标记不能包含撤销信息。"
        if not self.is_active:
            if not self.revoked_at:
                errors["revoked_at"] = "撤销测试数据标记必须记录撤销时间。"
            if not (self.revocation_reason or "").strip():
                errors["revocation_reason"] = "撤销测试数据标记必须记录原因。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "测试数据对象标记不可修改；纠错必须走单独的受控审计流程。"
            )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("测试数据对象标记不可删除。")

    def __str__(self) -> str:
        status = "active" if self.is_active else "revoked"
        return (
            f"{self.batch.batch_code}:{self.app_label}.{self.model_name}:"
            f"{self.object_pk}:{status}"
        )
