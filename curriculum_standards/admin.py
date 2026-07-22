from django.contrib import admin

from .models import (
    CurriculumStandard,
    CurriculumStandardAuditLog,
    CurriculumStandardNode,
    CurriculumStandardPage,
    CurriculumStandardVersion,
    CurriculumProcessingJob,
    CurriculumProcessingPage,
    CurriculumRetrievalChunk,
    CurriculumRetrievalIndex,
    EvaluationPlanCurriculumReference,
    EvaluationPlanVersionCurriculumReference,
)


class GovernanceReadOnlyAdmin(admin.ModelAdmin):
    """Governed records are changed only through the audited service/API workflow."""

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CurriculumStandard)
class CurriculumStandardAdmin(GovernanceReadOnlyAdmin):
    list_display = (
        "title",
        "school_stage",
        "document_type",
        "subject_name",
        "current_version",
        "is_active",
    )
    list_filter = ("school_stage", "document_type", "is_active")
    search_fields = ("title", "subject_code", "subject_name")
    autocomplete_fields = ("current_version", "created_by", "updated_by")


@admin.register(CurriculumStandardVersion)
class CurriculumStandardVersionAdmin(GovernanceReadOnlyAdmin):
    list_display = (
        "official_title",
        "version_label",
        "status",
        "extraction_status",
        "independent_review",
        "published_at",
    )
    list_filter = ("status", "extraction_status", "school_stage_snapshot")
    search_fields = ("official_title", "subject_name_snapshot", "content_hash", "pdf_sha256")
    autocomplete_fields = (
        "source",
        "replaces_version",
        "created_by",
        "submitted_by",
        "reviewed_by",
        "published_by",
        "archived_by",
    )
    readonly_fields = (
        "pdf_sha256",
        "structured_text_sha256",
        "content_hash",
        "created_at",
        "submitted_at",
        "reviewed_at",
        "published_at",
        "archived_at",
    )


@admin.register(CurriculumStandardNode)
class CurriculumStandardNodeAdmin(GovernanceReadOnlyAdmin):
    list_display = ("version", "node_type", "code", "title", "source_page_start")
    list_filter = ("node_type",)
    search_fields = ("code", "title", "content")
    autocomplete_fields = ("version", "parent")
    readonly_fields = ("content_hash", "created_at")


@admin.register(CurriculumStandardPage)
class CurriculumStandardPageAdmin(GovernanceReadOnlyAdmin):
    list_display = (
        "version",
        "page_number",
        "char_count",
        "extraction_method",
        "quality_status",
        "review_status",
    )
    list_filter = ("extraction_method", "quality_status", "review_status")
    search_fields = ("text", "content_hash")
    autocomplete_fields = ("version", "reviewed_by")
    readonly_fields = ("char_count", "content_hash", "created_at")


@admin.register(CurriculumProcessingJob)
class CurriculumProcessingJobAdmin(GovernanceReadOnlyAdmin):
    list_display = (
        "id",
        "version",
        "mode",
        "priority",
        "status",
        "stage",
        "progress_current",
        "progress_total",
        "created_at",
    )
    list_filter = ("status", "stage", "mode", "priority")
    search_fields = ("version__official_title", "celery_task_id", "error_message")
    autocomplete_fields = ("version", "requested_by", "retry_of", "cancel_requested_by")


@admin.register(CurriculumProcessingPage)
class CurriculumProcessingPageAdmin(GovernanceReadOnlyAdmin):
    list_display = ("job", "page_number", "char_count", "extraction_method", "quality_status")
    list_filter = ("extraction_method", "quality_status")
    search_fields = ("text", "content_hash")
    autocomplete_fields = ("job",)


@admin.register(CurriculumRetrievalIndex)
class CurriculumRetrievalIndexAdmin(GovernanceReadOnlyAdmin):
    list_display = (
        "version",
        "backend",
        "strategy_version",
        "chunk_count",
        "built_at",
    )
    list_filter = ("backend", "strategy", "strategy_version")
    search_fields = ("version__official_title", "index_hash", "version_content_hash")
    autocomplete_fields = ("version", "built_by")


@admin.register(CurriculumRetrievalChunk)
class CurriculumRetrievalChunkAdmin(GovernanceReadOnlyAdmin):
    list_display = (
        "chunk_id",
        "version",
        "source_kind",
        "source_page_start",
        "source_page_end",
        "ordinal",
    )
    list_filter = ("source_kind",)
    search_fields = ("chunk_id", "text", "source_locator", "content_sha256")
    autocomplete_fields = ("version", "index", "source_page", "source_node")


@admin.register(EvaluationPlanCurriculumReference)
class EvaluationPlanCurriculumReferenceAdmin(GovernanceReadOnlyAdmin):
    list_display = ("plan", "node", "created_by", "created_at")
    autocomplete_fields = ("plan", "node", "created_by")


@admin.register(EvaluationPlanVersionCurriculumReference)
class EvaluationPlanVersionCurriculumReferenceAdmin(GovernanceReadOnlyAdmin):
    list_display = ("plan_version", "standard_title", "version_label", "node_code")
    readonly_fields = tuple(
        field.name for field in EvaluationPlanVersionCurriculumReference._meta.fields
    )


@admin.register(CurriculumStandardAuditLog)
class CurriculumStandardAuditLogAdmin(GovernanceReadOnlyAdmin):
    list_display = ("standard", "version", "action", "actor", "created_at")
    list_filter = ("action",)
    readonly_fields = tuple(field.name for field in CurriculumStandardAuditLog._meta.fields)
