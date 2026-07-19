from django.contrib import admin

from .models import (
    AssessmentResultFact,
    AnalyticsOperatingMode,
    AnalyticsPipelineRun,
    AnalyticsTaskRun,
    AssessmentBlueprint,
    AssessmentBlueprintVersion,
    DataQualityReport,
    EventSchemaDefinition,
    EventIngestionDailyCounter,
    LearningEventRejection,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
    ParticipationPointLedger,
    RubricAnchorExample,
    RubricCriterionVersion,
    RubricDefinition,
    RubricDefinitionVersion,
    SensitiveInferenceAccessLog,
    SyntheticDatasetRun,
)


@admin.register(EventSchemaDefinition)
class EventSchemaDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "event_name",
        "schema_version",
        "status",
        "privacy_class",
        "analysis_unit",
        "updated_at",
    )
    list_filter = ("status", "privacy_class", "analysis_unit")
    search_fields = ("event_name", "description", "schema_version")
    readonly_fields = (
        "event_name",
        "schema_version",
        "description",
        "status",
        "privacy_class",
        "analysis_unit",
        "payload_schema",
        "required_context_fields",
        "allowed_sources",
        "requires_target_student",
        "requires_opportunity",
        "schema_hash",
        "activated_at",
        "retired_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(LearningEventV2)
class LearningEventV2Admin(admin.ModelAdmin):
    list_display = (
        "event_name",
        "schema_version",
        "school",
        "target_student",
        "quality_status",
        "client_occurred_at",
        "server_received_at",
    )
    list_filter = ("quality_status", "privacy_class", "event_name", "school")
    search_fields = (
        "event_id",
        "actor__username",
        "target_student__username",
        "object_id",
    )
    readonly_fields = tuple(field.name for field in LearningEventV2._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(LearningEventRejection)
class LearningEventRejectionAdmin(admin.ModelAdmin):
    list_display = (
        "event_name",
        "schema_version",
        "school",
        "actor",
        "error_code",
        "is_replayable",
        "replay_status",
        "server_received_at",
        "retention_expires_at",
    )
    list_filter = ("error_code", "is_replayable", "replay_status", "school")
    search_fields = ("rejection_id", "event_id", "event_name", "actor__username")
    exclude = ("encrypted_envelope",)
    readonly_fields = tuple(
        field.name
        for field in LearningEventRejection._meta.fields
        if field.name != "encrypted_envelope"
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(LearningOpportunity)
class LearningOpportunityAdmin(admin.ModelAdmin):
    list_display = (
        "opportunity_id",
        "student",
        "class_group",
        "subject",
        "content_type",
        "object_id",
        "required",
        "released_at",
    )
    list_filter = ("content_type", "required", "subject", "school")
    search_fields = (
        "opportunity_id",
        "student__username",
        "object_id",
        "object_version",
    )
    exclude = ("delivered_band",)
    readonly_fields = tuple(
        field.name
        for field in LearningOpportunity._meta.fields
        if field.name != "delivered_band"
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(LearningOpportunityTransitionFact)
class LearningOpportunityTransitionFactAdmin(admin.ModelAdmin):
    list_display = (
        "transition_id",
        "opportunity",
        "state",
        "reason_code",
        "occurred_at",
        "recorded_at",
    )
    list_filter = ("state", "occurred_at")
    search_fields = ("transition_id", "opportunity__opportunity_id", "reason_code")
    readonly_fields = tuple(
        field.name for field in LearningOpportunityTransitionFact._meta.fields
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AssessmentResultFact)
class AssessmentResultFactAdmin(admin.ModelAdmin):
    list_display = (
        "result_id",
        "student",
        "object_id",
        "grade_version",
        "grading_state",
        "score_raw",
        "score_max",
        "graded_at",
    )
    list_filter = ("grading_state", "grader_type", "subject", "school")
    search_fields = (
        "result_id",
        "attempt_id",
        "student__username",
        "object_id",
    )
    readonly_fields = tuple(field.name for field in AssessmentResultFact._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ParticipationPointLedger)
class ParticipationPointLedgerAdmin(admin.ModelAdmin):
    list_display = (
        "entry_id",
        "student",
        "class_group",
        "entry_type",
        "delta",
        "balance_after",
        "reason_code",
        "recorded_at",
    )
    list_filter = ("entry_type", "reason_code", "class_group", "school")
    search_fields = (
        "entry_id",
        "student__username",
        "awarded_by__username",
        "reason_code",
    )
    readonly_fields = tuple(
        field.name for field in ParticipationPointLedger._meta.fields
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AnalyticsOperatingMode)
class AnalyticsOperatingModeAdmin(admin.ModelAdmin):
    list_display = ("school", "mode", "updated_by", "updated_at")
    list_filter = ("mode",)
    search_fields = ("school__name", "school__code", "reason")


@admin.register(SensitiveInferenceAccessLog)
class SensitiveInferenceAccessLogAdmin(admin.ModelAdmin):
    list_display = (
        "actor",
        "actor_role",
        "school",
        "class_group",
        "purpose",
        "access_granted",
        "created_at",
    )
    list_filter = ("access_granted", "actor_role", "school", "created_at")
    search_fields = (
        "actor__username",
        "purpose",
        "target_type",
        "target_id",
        "denial_reason",
    )
    readonly_fields = (
        "request_id",
        "school",
        "actor",
        "actor_role",
        "class_group",
        "target_type",
        "target_id",
        "purpose",
        "field_categories",
        "export_requested",
        "access_granted",
        "denial_reason",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ReadOnlyAnalyticsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(EventIngestionDailyCounter)
class EventIngestionDailyCounterAdmin(ReadOnlyAnalyticsAdmin):
    list_display = (
        "school",
        "synthetic_run",
        "counter_date",
        "source",
        "accepted_count",
        "duplicate_count",
        "rejected_count",
        "late_count",
    )
    list_filter = ("source", "counter_date", "school", "synthetic_run")
    readonly_fields = tuple(
        field.name for field in EventIngestionDailyCounter._meta.fields
    )


@admin.register(AnalyticsPipelineRun)
class AnalyticsPipelineRunAdmin(ReadOnlyAnalyticsAdmin):
    list_display = (
        "run_id",
        "school",
        "synthetic_run",
        "pipeline_type",
        "trigger",
        "status",
        "attempt_no",
        "created_at",
    )
    list_filter = ("pipeline_type", "trigger", "status", "school", "synthetic_run")
    readonly_fields = tuple(field.name for field in AnalyticsPipelineRun._meta.fields)


@admin.register(AnalyticsTaskRun)
class AnalyticsTaskRunAdmin(ReadOnlyAnalyticsAdmin):
    list_display = (
        "task_id",
        "pipeline_run",
        "task_name",
        "status",
        "attempt_no",
        "created_at",
    )
    list_filter = ("task_name", "status")
    readonly_fields = tuple(field.name for field in AnalyticsTaskRun._meta.fields)


@admin.register(DataQualityReport)
class DataQualityReportAdmin(ReadOnlyAnalyticsAdmin):
    list_display = (
        "report_id",
        "school",
        "synthetic_run",
        "status",
        "gate_passed",
        "event_count",
        "window_end",
    )
    list_filter = ("status", "gate_passed", "school", "synthetic_run")
    readonly_fields = tuple(field.name for field in DataQualityReport._meta.fields)


@admin.register(SyntheticDatasetRun)
class SyntheticDatasetRunAdmin(ReadOnlyAnalyticsAdmin):
    list_display = (
        "run_id",
        "school",
        "mode",
        "generator_version",
        "seed",
        "status",
        "window_start",
        "window_end",
    )
    list_filter = ("mode", "status", "generator_version", "school")
    search_fields = ("run_id", "dataset_key", "school__code", "school__name")
    readonly_fields = tuple(field.name for field in SyntheticDatasetRun._meta.fields)


@admin.register(AssessmentBlueprint)
class AssessmentBlueprintAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "school",
        "subject",
        "course",
        "intended_use",
        "validation_status",
        "updated_at",
    )
    list_filter = ("intended_use", "validation_status", "school", "subject")
    search_fields = ("title", "course__title", "created_by__username")


@admin.register(RubricDefinition)
class RubricDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "school",
        "subject",
        "blueprint",
        "intended_use",
        "validation_status",
        "updated_at",
    )
    list_filter = ("intended_use", "validation_status", "school", "subject")
    search_fields = ("title", "blueprint__title", "created_by__username")


@admin.register(AssessmentBlueprintVersion)
class AssessmentBlueprintVersionAdmin(ReadOnlyAnalyticsAdmin):
    list_display = (
        "source",
        "version_no",
        "intended_use",
        "validation_status",
        "published_by",
        "published_at",
    )
    list_filter = ("intended_use", "validation_status", "school", "subject")
    readonly_fields = tuple(
        field.name for field in AssessmentBlueprintVersion._meta.fields
    )


@admin.register(RubricDefinitionVersion)
class RubricDefinitionVersionAdmin(ReadOnlyAnalyticsAdmin):
    list_display = (
        "source",
        "version_no",
        "blueprint_version",
        "intended_use",
        "validation_status",
        "published_at",
    )
    list_filter = ("intended_use", "validation_status", "school", "subject")
    readonly_fields = tuple(
        field.name for field in RubricDefinitionVersion._meta.fields
    )


@admin.register(RubricCriterionVersion)
class RubricCriterionVersionAdmin(ReadOnlyAnalyticsAdmin):
    list_display = ("rubric_version", "code", "module", "title", "sort_order")
    list_filter = ("module",)
    search_fields = ("code", "title", "rubric_version__title")
    readonly_fields = tuple(field.name for field in RubricCriterionVersion._meta.fields)


@admin.register(RubricAnchorExample)
class RubricAnchorExampleAdmin(ReadOnlyAnalyticsAdmin):
    list_display = ("criterion", "level", "title", "sort_order")
    list_filter = ("level",)
    search_fields = ("title", "criterion__code", "criterion__title")
    readonly_fields = tuple(field.name for field in RubricAnchorExample._meta.fields)
