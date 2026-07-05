from __future__ import annotations

from django.conf import settings
from django.db import models


class ExportBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待中"
        RUNNING = "running", "处理中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    school = models.ForeignKey("school.School", on_delete=models.PROTECT, related_name="export_batches")
    batch_code = models.CharField(max_length=64, unique=True)
    system_version = models.CharField(max_length=32, blank=True)
    file = models.FileField(upload_to="exports/", blank=True)
    checksum = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_export_batches",
    )
    exported_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.batch_code


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "已上传"
        VALIDATED = "validated", "已校验"
        IMPORTED = "imported", "已导入"
        FAILED = "failed", "失败"

    source_school = models.ForeignKey(
        "school.School",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_batches",
    )
    batch_code = models.CharField(max_length=64, unique=True)
    source_school_code = models.CharField(max_length=32, blank=True)
    source_system_version = models.CharField(max_length=32, blank=True)
    package_file = models.FileField(upload_to="imports/")
    checksum = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_import_batches",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    log = models.TextField(blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.batch_code


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ops_audit_logs",
    )
    school = models.ForeignKey("school.School", on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["school", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action}@{self.created_at:%Y-%m-%d %H:%M:%S}"
