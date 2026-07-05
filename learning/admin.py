from django.contrib import admin

from .models import LearningEvent, StratificationDecision, StudentFeatureSnapshot


@admin.register(LearningEvent)
class LearningEventAdmin(admin.ModelAdmin):
    list_display = ("actor", "event_type", "class_group", "course", "lesson", "occurred_at")
    list_filter = ("event_type", "class_group", "occurred_at")
    search_fields = ("actor__username", "actor__display_name", "object_type", "object_id")


@admin.register(StudentFeatureSnapshot)
class StudentFeatureSnapshotAdmin(admin.ModelAdmin):
    list_display = ("student", "class_group", "window_start", "window_end", "created_at")
    list_filter = ("class_group", "window_end")


@admin.register(StratificationDecision)
class StratificationDecisionAdmin(admin.ModelAdmin):
    list_display = ("student", "class_group", "previous_layer", "suggested_layer", "confidence", "status")
    list_filter = ("class_group", "status", "suggested_layer")

# Register your models here.
