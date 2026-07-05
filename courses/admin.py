from django.contrib import admin

from .models import (
    Activity,
    ClassroomActivity,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "teaching_model", "is_active", "created_at")
    list_filter = ("teaching_model", "is_active")
    search_fields = ("title", "teacher__username", "teacher__display_name")


@admin.register(CourseClass)
class CourseClassAdmin(admin.ModelAdmin):
    list_display = ("course", "class_group", "created_by", "created_at")
    search_fields = ("course__title", "class_group__name", "created_by__username", "created_by__display_name")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "sort_order", "is_active")
    list_filter = ("course", "is_active")
    search_fields = ("title",)


@admin.register(LessonStep)
class LessonStepAdmin(admin.ModelAdmin):
    list_display = ("title", "lesson", "step_type", "target_layer", "status", "sort_order")
    list_filter = ("step_type", "target_layer", "status")
    search_fields = ("title", "lesson__title", "lesson__course__title")


@admin.register(ClassroomSession)
class ClassroomSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "course", "class_group", "status", "created_at")
    list_filter = ("status", "school")
    search_fields = ("title", "teacher__username", "teacher__display_name", "course__title", "class_group__name")


@admin.register(ClassroomActivity)
class ClassroomActivityAdmin(admin.ModelAdmin):
    list_display = ("title", "session", "activity_type", "status", "created_at")
    list_filter = ("activity_type", "status")
    search_fields = ("title", "session__title")


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "is_pinned", "view_count", "created_at")
    list_filter = ("is_pinned",)
    search_fields = ("title", "owner__username", "owner__display_name")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("title", "lesson", "sort_order", "created_at")
    search_fields = ("title",)

# Register your models here.
