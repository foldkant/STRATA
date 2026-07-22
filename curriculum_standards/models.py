from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def curriculum_pdf_upload_path(instance, filename: str) -> str:
    suffix = Path(filename or "standard.pdf").suffix.lower() or ".pdf"
    source_id = instance.source_id or "new"
    label = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in str(instance.version_label or "version")
    ).strip("-")
    return (
        f"curriculum_standards/managed/{instance.source.school_stage}/"
        f"standard_{source_id}/{label or 'version'}/source{suffix}"
    )


class SchoolStage(models.TextChoices):
    COMPULSORY = "k1_k9", "义务教育"
    SENIOR_HIGH = "k10_k12", "普通高中"


class CurriculumDocumentType(models.TextChoices):
    CURRICULUM_PLAN = "curriculum_plan", "课程方案"
    SUBJECT_STANDARD = "subject_standard", "学科课程标准"


class CurriculumVersionStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    REVIEW_PENDING = "review_pending", "待复核"
    REVIEWED = "reviewed", "已复核"
    PUBLISHED = "published", "已发布"
    ARCHIVED = "archived", "已归档"
    DISCARDED = "discarded", "已丢弃"


class CurriculumExtractionStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    COMPLETED = "completed", "已生成结构化文本"
    NEEDS_OCR = "needs_ocr", "需要文字识别"
    FAILED = "failed", "处理失败"


class CurriculumProcessingJobStatus(models.TextChoices):
    QUEUED = "queued", "等待处理"
    RUNNING = "running", "处理中"
    SUCCEEDED = "succeeded", "处理成功"
    FAILED = "failed", "处理失败"
    CANCELLING = "cancelling", "正在取消"
    CANCELLED = "cancelled", "已取消"


class CurriculumProcessingMode(models.TextChoices):
    AUTO = "auto", "自动提取（必要时文字识别）"
    OCR = "ocr", "全文文字识别"


class CurriculumProcessingPriority(models.TextChoices):
    HIGH = "high", "优先"
    NORMAL = "normal", "普通"
    LOW = "low", "后台"


class CurriculumProcessingStage(models.TextChoices):
    QUEUED = "queued", "等待处理"
    PREPARING = "preparing", "校验原始文件"
    EXTRACTING = "extracting", "提取 PDF 文字"
    OCR = "ocr", "逐页文字识别"
    VALIDATING = "validating", "校验处理结果"
    COMMITTING = "committing", "写入处理结果"
    FINISHED = "finished", "处理完成"
    FAILED = "failed", "处理失败"
    CANCELLED = "cancelled", "已取消"


class CurriculumTextExtractionMethod(models.TextChoices):
    EMBEDDED_TEXT = "embedded_text", "PDF 内嵌文字"
    OCR = "ocr", "文字识别"
    MANUAL = "manual", "人工整理"


class CurriculumPageReviewStatus(models.TextChoices):
    NEEDS_REVIEW = "needs_review", "待复核"
    REVIEWED = "reviewed", "已复核"


class CurriculumPageQualityStatus(models.TextChoices):
    COMPLETE = "complete", "文本完整"
    EMPTY = "empty", "未识别到文字"
    LOW_CONFIDENCE = "low_confidence", "识别置信度较低"
    FAILED = "failed", "处理失败"


class CurriculumNodeType(models.TextChoices):
    CORE_COMPETENCY = "core_competency", "核心素养"
    COURSE_OBJECTIVE = "course_objective", "课程目标"
    COURSE_CONTENT = "course_content", "课程内容"
    ACADEMIC_QUALITY = "academic_quality", "学业质量"


class CurriculumRetrievalSourceKind(models.TextChoices):
    PAGE = "page", "逐页原文"
    CONTENT_ITEM = "content_item", "课程标准内容条目"


class CurriculumRetrievalBackend(models.TextChoices):
    KEYWORD = "keyword_v1", "关键词检索 v1"


class CurriculumStandard(models.Model):
    title = models.CharField(max_length=240)
    document_type = models.CharField(
        max_length=32,
        choices=CurriculumDocumentType.choices,
    )
    school_stage = models.CharField(max_length=16, choices=SchoolStage.choices)
    subject_code = models.CharField(max_length=64, blank=True)
    subject_name = models.CharField(max_length=80, blank=True)
    current_version = models.ForeignKey(
        "CurriculumStandardVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_standards",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_curriculum_standards",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_curriculum_standards",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school_stage", "document_type", "subject_code"],
                name="uniq_curriculum_standard_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["school_stage", "document_type", "subject_code"]),
            models.Index(fields=["is_active", "updated_at"]),
        ]
        ordering = ["school_stage", "document_type", "subject_name", "id"]

    def clean(self) -> None:
        errors = {}
        if self.document_type == CurriculumDocumentType.SUBJECT_STANDARD:
            if not self.subject_code.strip():
                errors["subject_code"] = "学科课程标准必须填写学科代码。"
            if not self.subject_name.strip():
                errors["subject_name"] = "学科课程标准必须填写学科名称。"
        if self.current_version_id:
            if self.current_version.source_id != self.pk:
                errors["current_version"] = "当前版本必须属于本课程标准。"
            elif self.current_version.status != CurriculumVersionStatus.PUBLISHED:
                errors["current_version"] = "当前版本必须是已发布版本。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and previous.versions.exists():
                identity_fields = ("school_stage", "document_type", "subject_code")
                if any(
                    getattr(previous, field) != getattr(self, field)
                    for field in identity_fields
                ):
                    raise ValidationError(
                        "课程标准已有版本，不能更改学段、文档类型或学科代码。"
                    )
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class CurriculumStandardVersion(models.Model):
    source = models.ForeignKey(
        CurriculumStandard,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_label = models.CharField(max_length=80)
    publication_year = models.PositiveSmallIntegerField()
    effective_year = models.PositiveSmallIntegerField(null=True, blank=True)
    title_snapshot = models.CharField(max_length=240)
    official_title = models.CharField(max_length=240)
    document_type_snapshot = models.CharField(
        max_length=32,
        choices=CurriculumDocumentType.choices,
    )
    school_stage_snapshot = models.CharField(max_length=16, choices=SchoolStage.choices)
    subject_code_snapshot = models.CharField(max_length=64, blank=True)
    subject_name_snapshot = models.CharField(max_length=80, blank=True)
    issued_by = models.CharField(max_length=160, default="中华人民共和国教育部")
    source_url = models.URLField(max_length=1000, blank=True)
    source_note = models.TextField(blank=True)
    pdf_file = models.FileField(upload_to=curriculum_pdf_upload_path, max_length=500)
    pdf_sha256 = models.CharField(max_length=64, db_index=True)
    pdf_size_bytes = models.PositiveBigIntegerField()
    pdf_page_count = models.PositiveIntegerField()
    structured_text = models.TextField(blank=True)
    structured_format = models.CharField(
        max_length=40,
        default="page_marked_text_v1",
    )
    structured_text_sha256 = models.CharField(max_length=64, blank=True)
    extraction_status = models.CharField(
        max_length=24,
        choices=CurriculumExtractionStatus.choices,
        default=CurriculumExtractionStatus.PENDING,
    )
    extraction_message = models.CharField(max_length=500, blank=True)
    extraction_engine = models.CharField(max_length=120, blank=True)
    extraction_engine_version = models.CharField(max_length=240, blank=True)
    extraction_config = models.JSONField(default=dict, blank=True)
    extracted_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    replaces_version = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replacement_versions",
    )
    status = models.CharField(
        max_length=24,
        choices=CurriculumVersionStatus.choices,
        default=CurriculumVersionStatus.DRAFT,
    )
    review_note = models.TextField(blank=True)
    independent_review = models.BooleanField(default=False)
    independent_publication = models.BooleanField(default=False)
    governance_waiver_note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_curriculum_standard_versions",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_curriculum_standard_versions",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_curriculum_standard_versions",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_curriculum_standard_versions",
    )
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="archived_curriculum_standard_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    IMMUTABLE_CONTENT_FIELDS = (
        "source_id",
        "version_label",
        "publication_year",
        "effective_year",
        "title_snapshot",
        "official_title",
        "document_type_snapshot",
        "school_stage_snapshot",
        "subject_code_snapshot",
        "subject_name_snapshot",
        "issued_by",
        "source_url",
        "source_note",
        "pdf_file",
        "pdf_sha256",
        "pdf_size_bytes",
        "pdf_page_count",
        "structured_text",
        "structured_format",
        "structured_text_sha256",
        "extraction_engine",
        "extraction_engine_version",
        "extraction_config",
        "extracted_at",
        "content_hash",
        "replaces_version_id",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "version_label"],
                name="uniq_curriculum_standard_version_label",
            ),
            models.UniqueConstraint(
                fields=["source", "content_hash"],
                name="uniq_curriculum_standard_content_hash",
            ),
            models.UniqueConstraint(
                fields=["source", "pdf_sha256"],
                name="uniq_curriculum_standard_pdf_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["source", "status", "publication_year"]),
            models.Index(fields=["status", "published_at"]),
        ]
        ordering = ["source_id", "-publication_year", "-id"]

    def clean(self) -> None:
        errors = {}
        if self.source_id:
            snapshots = {
                "title_snapshot": self.source.title,
                "document_type_snapshot": self.source.document_type,
                "school_stage_snapshot": self.source.school_stage,
                "subject_code_snapshot": self.source.subject_code,
                "subject_name_snapshot": self.source.subject_name,
            }
            if not self.pk:
                for field_name, value in snapshots.items():
                    if getattr(self, field_name) != value:
                        errors[field_name] = "版本快照必须与课程标准主记录一致。"
        if self.replaces_version_id:
            if self.replaces_version_id == self.pk:
                errors["replaces_version"] = "版本不能替换自身。"
            elif self.replaces_version.source_id != self.source_id:
                errors["replaces_version"] = "被替换版本必须属于同一课程标准。"
        for field_name in ("pdf_sha256", "content_hash"):
            value = getattr(self, field_name)
            if len(value) != 64:
                errors[field_name] = "校验码格式不正确。"
        if self.pdf_size_bytes < 1:
            errors["pdf_size_bytes"] = "PDF 文件大小快照必须大于 0 字节。"
        if self.structured_text and len(self.structured_text_sha256) != 64:
            errors["structured_text_sha256"] = "结构化文本校验码格式不正确。"
        if self.status in {
            CurriculumVersionStatus.REVIEWED,
            CurriculumVersionStatus.PUBLISHED,
            CurriculumVersionStatus.ARCHIVED,
        } and not self.reviewed_by_id:
            errors["reviewed_by"] = "完成复核后必须记录复核人。"
        if self.status in {
            CurriculumVersionStatus.PUBLISHED,
            CurriculumVersionStatus.ARCHIVED,
        } and not self.published_by_id:
            errors["published_by"] = "发布后必须记录发布人。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and previous.status != CurriculumVersionStatus.DRAFT:
                changed = [
                    field_name
                    for field_name in self.IMMUTABLE_CONTENT_FIELDS
                    if getattr(previous, field_name) != getattr(self, field_name)
                ]
                if changed:
                    raise ValidationError(
                        "已发布课程标准版本的内容不可修改，请建立替换版本。"
                    )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != CurriculumVersionStatus.DRAFT:
            raise ValidationError("已进入复核流程的课程标准版本不能删除。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title_snapshot}（{self.version_label}）"


class CurriculumStandardNode(models.Model):
    version = models.ForeignKey(
        CurriculumStandardVersion,
        on_delete=models.PROTECT,
        related_name="nodes",
    )
    node_type = models.CharField(max_length=32, choices=CurriculumNodeType.choices)
    code = models.CharField(max_length=80)
    title = models.CharField(max_length=240)
    content = models.TextField()
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    source_page_start = models.PositiveIntegerField()
    source_page_end = models.PositiveIntegerField()
    source_paragraph = models.CharField(max_length=240, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    content_hash = models.CharField(max_length=64, editable=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "code"],
                name="uniq_curriculum_node_code",
            ),
        ]
        indexes = [
            models.Index(fields=["version", "node_type", "sort_order"]),
        ]
        ordering = ["version_id", "sort_order", "id"]

    def clean(self) -> None:
        errors = {}
        if self.parent_id and self.parent.version_id != self.version_id:
            errors["parent"] = "上级条目必须属于同一课程标准版本。"
        if self.parent_id and self.parent_id == self.pk:
            errors["parent"] = "内容条目不能作为自身的上级条目。"
        if self.source_page_end < self.source_page_start:
            errors["source_page_end"] = "原文结束页不能早于起始页。"
        if self.version_id and self.version.pk and self.version.pages.exists():
            available_pages = set(
                self.version.pages.values_list("page_number", flat=True)
            )
            expected_pages = set(
                range(self.source_page_start, self.source_page_end + 1)
            )
            if not expected_pages.issubset(available_pages):
                errors["source_page_end"] = "原文页码必须落在该版本实际 PDF 页范围内。"
        if not self.content.strip():
            errors["content"] = "内容条目必须保留对应的课程标准原文。"
        if errors:
            raise ValidationError(errors)

    def semantic_content(self) -> dict:
        return {
            "node_type": self.node_type,
            "code": self.code,
            "title": self.title,
            "content": self.content,
            "parent_code": self.parent.code if self.parent_id else None,
            "source_page_start": self.source_page_start,
            "source_page_end": self.source_page_end,
            "source_paragraph": self.source_paragraph,
            "sort_order": self.sort_order,
        }

    def save(self, *args, **kwargs):
        if self.version_id and self.version.status != CurriculumVersionStatus.DRAFT:
            raise ValidationError("已提交复核的课程标准内容条目不可修改。")
        self.content_hash = canonical_hash(self.semantic_content())
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.version.status != CurriculumVersionStatus.DRAFT:
            raise ValidationError("已提交复核的课程标准内容条目不能删除。")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class CurriculumStandardPage(models.Model):
    version = models.ForeignKey(
        CurriculumStandardVersion,
        on_delete=models.PROTECT,
        related_name="pages",
    )
    page_number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    char_count = models.PositiveIntegerField(default=0)
    extraction_method = models.CharField(
        max_length=24,
        choices=CurriculumTextExtractionMethod.choices,
    )
    mean_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    quality_status = models.CharField(
        max_length=24,
        choices=CurriculumPageQualityStatus.choices,
        default=CurriculumPageQualityStatus.COMPLETE,
    )
    quality_message = models.CharField(max_length=300, blank=True)
    review_status = models.CharField(
        max_length=24,
        choices=CurriculumPageReviewStatus.choices,
        default=CurriculumPageReviewStatus.NEEDS_REVIEW,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_curriculum_standard_pages",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, editable=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "page_number"],
                name="uniq_curriculum_standard_page_number",
            ),
        ]
        indexes = [
            models.Index(fields=["version", "review_status", "page_number"]),
        ]
        ordering = ["version_id", "page_number"]

    def semantic_content(self) -> dict:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "char_count": self.char_count,
            "extraction_method": self.extraction_method,
            "mean_confidence": (
                str(self.mean_confidence) if self.mean_confidence is not None else None
            ),
            "quality_status": self.quality_status,
            "quality_message": self.quality_message,
        }

    def clean(self) -> None:
        errors = {}
        if self.char_count != len(self.text):
            errors["char_count"] = "页级字符数必须与文本内容一致。"
        if self.extraction_method == CurriculumTextExtractionMethod.OCR:
            if self.mean_confidence is None:
                errors["mean_confidence"] = "文字识别页面必须记录平均置信度。"
        elif self.mean_confidence is not None:
            errors["mean_confidence"] = "只有文字识别页面可以记录平均置信度。"
        if self.review_status == CurriculumPageReviewStatus.REVIEWED:
            if not self.reviewed_by_id or not self.reviewed_at:
                errors["review_status"] = "页级文本复核必须记录复核人和复核时间。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.version_id and self.version.status != CurriculumVersionStatus.DRAFT:
            if not self.pk:
                raise ValidationError("已提交复核的页级文本不可新增。")
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and (
                previous.text != self.text
                or previous.extraction_method != self.extraction_method
                or previous.mean_confidence != self.mean_confidence
                or previous.page_number != self.page_number
                or previous.quality_status != self.quality_status
                or previous.quality_message != self.quality_message
            ):
                raise ValidationError("已提交复核的页级文本内容不可修改。")
        self.text = str(self.text or "")
        self.char_count = len(self.text)
        self.content_hash = canonical_hash(self.semantic_content())
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.version.status != CurriculumVersionStatus.DRAFT:
            raise ValidationError("已提交复核的页级文本不可删除。")
        return super().delete(*args, **kwargs)


class CurriculumProcessingJob(models.Model):
    """A durable, database-authoritative PDF processing job."""

    version = models.ForeignKey(
        CurriculumStandardVersion,
        on_delete=models.PROTECT,
        related_name="processing_jobs",
    )
    task_type = models.CharField(max_length=40, default="pdf_text_extraction")
    mode = models.CharField(
        max_length=16,
        choices=CurriculumProcessingMode.choices,
        default=CurriculumProcessingMode.AUTO,
    )
    priority = models.CharField(
        max_length=16,
        choices=CurriculumProcessingPriority.choices,
        default=CurriculumProcessingPriority.LOW,
    )
    status = models.CharField(
        max_length=16,
        choices=CurriculumProcessingJobStatus.choices,
        default=CurriculumProcessingJobStatus.QUEUED,
        db_index=True,
    )
    stage = models.CharField(
        max_length=24,
        choices=CurriculumProcessingStage.choices,
        default=CurriculumProcessingStage.QUEUED,
    )
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    source_pdf_sha256 = models.CharField(max_length=64)
    source_content_hash = models.CharField(max_length=64)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    dispatch_count = models.PositiveSmallIntegerField(default=0)
    dispatch_attempted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_curriculum_processing_jobs",
    )
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retries",
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    cancel_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancelled_curriculum_processing_jobs",
    )
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    worker_hostname = models.CharField(max_length=255, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    result_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version"],
                condition=models.Q(status__in=["queued", "running", "cancelling"]),
                name="uniq_active_curriculum_processing_job",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "priority", "created_at"]),
            models.Index(fields=["version", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        errors = {}
        for field_name in ("source_pdf_sha256", "source_content_hash"):
            if len(str(getattr(self, field_name) or "")) != 64:
                errors[field_name] = "任务来源校验码格式不正确。"
        if self.progress_total and self.progress_current > self.progress_total:
            errors["progress_current"] = "已处理页数不能大于总页数。"
        if self.retry_of_id and self.retry_of.version_id != self.version_id:
            errors["retry_of"] = "重试任务必须属于同一课程标准版本。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("课程标准后台处理任务不可删除。")


class CurriculumProcessingPage(models.Model):
    """Temporary page output promoted only after the whole job succeeds."""

    job = models.ForeignKey(
        CurriculumProcessingJob,
        on_delete=models.CASCADE,
        related_name="staged_pages",
    )
    page_number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    char_count = models.PositiveIntegerField(default=0)
    extraction_method = models.CharField(
        max_length=24,
        choices=CurriculumTextExtractionMethod.choices,
    )
    mean_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    quality_status = models.CharField(
        max_length=24,
        choices=CurriculumPageQualityStatus.choices,
        default=CurriculumPageQualityStatus.COMPLETE,
    )
    quality_message = models.CharField(max_length=300, blank=True)
    content_hash = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "page_number"],
                name="uniq_curriculum_processing_page_number",
            ),
        ]
        ordering = ["job_id", "page_number"]

    def save(self, *args, **kwargs):
        self.text = str(self.text or "")
        self.char_count = len(self.text)
        self.content_hash = canonical_hash(
            {
                "page_number": self.page_number,
                "text": self.text,
                "extraction_method": self.extraction_method,
                "mean_confidence": (
                    str(self.mean_confidence)
                    if self.mean_confidence is not None
                    else None
                ),
                "quality_status": self.quality_status,
                "quality_message": self.quality_message,
            }
        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("课程标准处理暂存页不可单独删除。")


class CurriculumRetrievalIndex(models.Model):
    """A reproducible retrieval-index manifest for exactly one governed version."""

    version = models.OneToOneField(
        CurriculumStandardVersion,
        on_delete=models.CASCADE,
        related_name="retrieval_index",
    )
    backend = models.CharField(
        max_length=32,
        choices=CurriculumRetrievalBackend.choices,
        default=CurriculumRetrievalBackend.KEYWORD,
    )
    strategy = models.CharField(max_length=64, default="char_boundary")
    strategy_version = models.CharField(max_length=32, default="1")
    max_chars = models.PositiveIntegerField(default=1200)
    overlap_chars = models.PositiveIntegerField(default=200)
    chunk_count = models.PositiveIntegerField(default=0)
    index_hash = models.CharField(max_length=64, db_index=True)
    version_content_hash = models.CharField(max_length=64, db_index=True)
    pdf_sha256 = models.CharField(max_length=64, db_index=True)
    built_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="built_curriculum_retrieval_indexes",
    )
    built_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["backend", "built_at"]),
            models.Index(fields=["version_content_hash", "index_hash"]),
        ]
        ordering = ["version_id"]

    def clean(self) -> None:
        errors = {}
        if self.max_chars < 256 or self.max_chars > 8000:
            errors["max_chars"] = "检索片段最大字符数必须在 256 到 8000 之间。"
        if self.overlap_chars >= self.max_chars:
            errors["overlap_chars"] = "检索片段重叠字符数必须小于最大字符数。"
        for field_name in ("index_hash", "version_content_hash", "pdf_sha256"):
            if len(str(getattr(self, field_name) or "")) != 64:
                errors[field_name] = "校验码格式不正确。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CurriculumRetrievalChunk(models.Model):
    """A version-isolated, source-anchored unit for deterministic AI retrieval."""

    version = models.ForeignKey(
        CurriculumStandardVersion,
        on_delete=models.CASCADE,
        related_name="retrieval_chunks",
    )
    index = models.ForeignKey(
        CurriculumRetrievalIndex,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_id = models.CharField(max_length=64, unique=True)
    source_kind = models.CharField(
        max_length=24,
        choices=CurriculumRetrievalSourceKind.choices,
    )
    source_locator = models.CharField(max_length=160)
    source_object_id = models.PositiveBigIntegerField()
    source_page = models.ForeignKey(
        CurriculumStandardPage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="retrieval_chunks",
    )
    source_node = models.ForeignKey(
        CurriculumStandardNode,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="retrieval_chunks",
    )
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    char_start = models.PositiveIntegerField()
    char_end = models.PositiveIntegerField()
    char_count = models.PositiveIntegerField()
    content_sha256 = models.CharField(max_length=64, db_index=True)
    source_text_sha256 = models.CharField(max_length=64, db_index=True)
    source_content_hash = models.CharField(max_length=64, db_index=True)
    version_content_hash = models.CharField(max_length=64, db_index=True)
    pdf_sha256 = models.CharField(max_length=64, db_index=True)
    source_page_start = models.PositiveIntegerField()
    source_page_end = models.PositiveIntegerField()
    source_page_hashes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "source_kind", "source_locator", "ordinal"],
                name="uniq_curriculum_retrieval_source_ordinal",
            ),
            models.CheckConstraint(
                condition=models.Q(source_page_end__gte=models.F("source_page_start")),
                name="curriculum_retrieval_page_range_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["version", "source_kind", "ordinal"]),
            models.Index(fields=["version", "source_page_start", "source_page_end"]),
        ]
        ordering = ["version_id", "source_kind", "source_locator", "ordinal"]

    def clean(self) -> None:
        errors = {}
        if self.source_kind == CurriculumRetrievalSourceKind.PAGE:
            if not self.source_page_id or self.source_node_id:
                errors["source_page"] = "逐页检索片段必须且只能关联逐页原文。"
        elif self.source_kind == CurriculumRetrievalSourceKind.CONTENT_ITEM:
            if not self.source_node_id or self.source_page_id:
                errors["source_node"] = "内容条目检索片段必须且只能关联课程标准内容条目。"
        if self.source_page_end < self.source_page_start:
            errors["source_page_end"] = "原文结束页不能早于起始页。"
        if self.char_end <= self.char_start or self.char_count != self.char_end - self.char_start:
            errors["char_count"] = "检索片段字符位置与字符数不一致。"
        if self.char_count != len(self.text):
            errors["text"] = "检索片段字符数必须与正文一致。"
        for field_name in (
            "chunk_id",
            "content_sha256",
            "source_text_sha256",
            "source_content_hash",
            "version_content_hash",
            "pdf_sha256",
        ):
            if len(str(getattr(self, field_name) or "")) != 64:
                errors[field_name] = "校验码格式不正确。"
        if self.index_id and self.version_id and self.index.version_id != self.version_id:
            errors["index"] = "检索片段和检索索引必须属于同一课程标准版本。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EvaluationPlanCurriculumReference(models.Model):
    plan = models.ForeignKey(
        "learning_analytics.EvaluationPlan",
        on_delete=models.CASCADE,
        related_name="curriculum_references",
    )
    node = models.ForeignKey(
        CurriculumStandardNode,
        on_delete=models.PROTECT,
        related_name="draft_evaluation_plan_references",
    )
    alignment_explanation = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_evaluation_curriculum_references",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "node"],
                name="uniq_evaluation_plan_curriculum_node",
            ),
        ]
        ordering = ["node__sort_order", "id"]

    def clean(self) -> None:
        if self.node_id and self.node.version.status != CurriculumVersionStatus.PUBLISHED:
            raise ValidationError({"node": "只能引用当前已发布课程标准版本的内容条目。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EvaluationPlanVersionCurriculumReference(models.Model):
    plan_version = models.ForeignKey(
        "learning_analytics.EvaluationPlanVersion",
        on_delete=models.PROTECT,
        related_name="curriculum_references",
    )
    node = models.ForeignKey(
        CurriculumStandardNode,
        on_delete=models.PROTECT,
        related_name="published_evaluation_plan_references",
    )
    curriculum_version_hash = models.CharField(max_length=64)
    node_content_hash = models.CharField(max_length=64)
    standard_title = models.CharField(max_length=240)
    version_label = models.CharField(max_length=80)
    node_type = models.CharField(max_length=32, choices=CurriculumNodeType.choices)
    node_code = models.CharField(max_length=80)
    node_title = models.CharField(max_length=240)
    source_page_start = models.PositiveIntegerField()
    source_page_end = models.PositiveIntegerField()
    source_paragraph = models.CharField(max_length=240, blank=True)
    alignment_explanation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "node"],
                name="uniq_evaluation_plan_version_curriculum_node",
            ),
        ]
        ordering = ["node_type", "node_code", "id"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("已发布评价方案的课程标准引用不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已发布评价方案的课程标准引用不可删除。")


class CurriculumStandardAuditLog(models.Model):
    standard = models.ForeignKey(
        CurriculumStandard,
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    version = models.ForeignKey(
        CurriculumStandardVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="curriculum_standard_audit_logs",
    )
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["version", "created_at"])]
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("课程标准审计记录不可修改。")
        if self.version_id:
            self.standard_id = self.version.source_id
        if not self.standard_id:
            raise ValidationError("课程标准审计记录必须关联课程标准档案。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("课程标准审计记录不可删除。")
