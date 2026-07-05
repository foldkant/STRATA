from django.contrib import admin

from .models import AuditLog, ExportBatch, ImportBatch


@admin.register(ExportBatch)
class ExportBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_code", "school", "status", "exported_by", "exported_at", "created_at")
    list_filter = ("status", "school")
    search_fields = ("batch_code", "school__name", "school__code")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_code", "source_school_code", "source_school", "status", "uploaded_by", "uploaded_at")
    list_filter = ("status", "source_school")
    search_fields = ("batch_code", "source_school_code", "source_school__name")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "school", "target_type", "target_id", "created_at")
    list_filter = ("action", "school")
    search_fields = ("action", "target_type", "target_id", "actor__username")
