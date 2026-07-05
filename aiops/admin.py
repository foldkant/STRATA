from django.contrib import admin

from .models import ModelVersion, TrainingJob


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "class_group", "status", "algorithm", "trained_at")
    list_filter = ("status", "algorithm", "class_group")
    search_fields = ("name", "version")


@admin.register(TrainingJob)
class TrainingJobAdmin(admin.ModelAdmin):
    list_display = ("class_group", "status", "celery_task_id", "started_at", "finished_at")
    list_filter = ("status", "class_group")

# Register your models here.
