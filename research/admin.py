from django.contrib import admin

from .models import (
    ResearchAnalysisRun,
    ResearchCohortAssignment,
    ResearchDataLock,
    ResearchExposureRecord,
    ResearchGateDecision,
    ResearchProtocolVersion,
    ResearchRun,
    ResearchStudy,
)


class ImmutableResearchAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser and obj is None)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ResearchStudy)
class ResearchStudyAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "school", "status", "current_protocol", "updated_at")
    list_filter = ("status", "school")
    search_fields = ("code", "title", "school__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ResearchProtocolVersion)
class ResearchProtocolVersionAdmin(ImmutableResearchAdmin):
    list_display = ("study", "version_no", "stage", "design_type", "registered_at")
    list_filter = ("stage", "design_type")
    search_fields = ("study__code", "study__title", "content_hash")
    readonly_fields = tuple(field.name for field in ResearchProtocolVersion._meta.fields)


@admin.register(ResearchGateDecision)
class ResearchGateDecisionAdmin(ImmutableResearchAdmin):
    list_display = ("protocol", "gate", "sequence_no", "decision", "decided_at")
    list_filter = ("gate", "decision")
    readonly_fields = tuple(field.name for field in ResearchGateDecision._meta.fields)


@admin.register(ResearchCohortAssignment)
class ResearchCohortAssignmentAdmin(ImmutableResearchAdmin):
    list_display = ("protocol", "class_group", "arm", "allocation_method", "assigned_at")
    list_filter = ("arm", "allocation_method")
    readonly_fields = tuple(field.name for field in ResearchCohortAssignment._meta.fields)


@admin.register(ResearchRun)
class ResearchRunAdmin(admin.ModelAdmin):
    list_display = ("run_code", "protocol", "mode", "status", "activated_at", "closed_at")
    list_filter = ("mode", "status")
    readonly_fields = tuple(field.name for field in ResearchRun._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser and obj is None)

    def has_delete_permission(self, request, obj=None):
        return False


for model in (ResearchExposureRecord, ResearchDataLock, ResearchAnalysisRun):
    admin.site.register(
        model,
        type(
            f"{model.__name__}Admin",
            (ImmutableResearchAdmin,),
            {"readonly_fields": tuple(field.name for field in model._meta.fields)},
        ),
    )
