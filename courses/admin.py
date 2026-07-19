from django.contrib import admin

from .models import (
    Activity,
    ClassroomActivity,
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupDocumentVersion,
    ClassroomGroupFile,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    LearningWebPage,
    LearningWebPageResponse,
    LearningWebPageVersion,
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
    search_fields = (
        "course__title",
        "class_group__name",
        "created_by__username",
        "created_by__display_name",
    )


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "sort_order", "is_active")
    list_filter = ("course", "is_active")
    search_fields = ("title",)


@admin.register(LessonStep)
class LessonStepAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "lesson",
        "step_type",
        "target_layer",
        "status",
        "sort_order",
    )
    list_filter = ("step_type", "target_layer", "status")
    search_fields = ("title", "lesson__title", "lesson__course__title")


@admin.register(LearningWebPage)
class LearningWebPageAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "lesson",
        "teacher",
        "revision_no",
        "status",
        "is_active",
        "updated_at",
    )
    list_filter = ("status", "is_active", "school")
    search_fields = (
        "title",
        "lesson__title",
        "course__title",
        "teacher__username",
        "teacher__display_name",
    )


@admin.register(LearningWebPageVersion)
class LearningWebPageVersionAdmin(admin.ModelAdmin):
    list_display = ("page", "version_no", "created_by", "created_at")
    search_fields = ("page__title", "created_by__username", "created_by__display_name")


@admin.register(LearningWebPageResponse)
class LearningWebPageResponseAdmin(admin.ModelAdmin):
    list_display = (
        "page",
        "form_id",
        "student",
        "class_group",
        "attempt_no",
        "submitted_at",
    )
    list_filter = ("form_id", "school")
    search_fields = (
        "page__title",
        "student__username",
        "student__display_name",
        "class_group__name",
    )


@admin.register(ClassroomSession)
class ClassroomSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "course", "class_group", "status", "created_at")
    list_filter = ("status", "school")
    search_fields = (
        "title",
        "teacher__username",
        "teacher__display_name",
        "course__title",
        "class_group__name",
    )


@admin.register(ClassroomActivity)
class ClassroomActivityAdmin(admin.ModelAdmin):
    list_display = ("title", "session", "activity_type", "status", "created_at")
    list_filter = ("activity_type", "status")
    search_fields = ("title", "session__title")


@admin.register(ClassroomGroupCollaboration)
class ClassroomGroupCollaborationAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "status",
        "grouping_strategy",
        "document_type",
        "storage_quota_mb",
        "updated_at",
    )
    list_filter = ("status", "grouping_strategy", "document_type")
    search_fields = (
        "session__title",
        "session__course__title",
        "session__class_group__name",
    )


@admin.register(ClassroomGroup)
class ClassroomGroupAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "collaboration",
        "group_no",
        "layer_hint",
        "leader",
        "updated_at",
    )
    list_filter = ("layer_hint",)
    search_fields = (
        "name",
        "collaboration__session__title",
        "leader__username",
        "leader__display_name",
    )


@admin.register(ClassroomGroupMember)
class ClassroomGroupMemberAdmin(admin.ModelAdmin):
    list_display = ("group", "student", "role", "joined_at")
    list_filter = ("role",)
    search_fields = ("group__name", "student__username", "student__display_name")


@admin.register(ClassroomGroupDocumentVersion)
class ClassroomGroupDocumentVersionAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "version_no",
        "source",
        "file_size",
        "callback_status",
        "created_at",
    )
    list_filter = ("source", "callback_status")
    search_fields = ("group__name", "file_sha256", "callback_key")
    readonly_fields = tuple(
        field.name for field in ClassroomGroupDocumentVersion._meta.fields
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClassroomGroupFile)
class ClassroomGroupFileAdmin(admin.ModelAdmin):
    list_display = (
        "original_name",
        "group",
        "uploader",
        "file_ext",
        "file_size",
        "created_at",
    )
    list_filter = ("file_ext",)
    search_fields = (
        "original_name",
        "group__name",
        "uploader__username",
        "uploader__display_name",
    )


@admin.register(ClassroomEvaluationConfig)
class ClassroomEvaluationConfigAdmin(admin.ModelAdmin):
    list_display = (
        "course",
        "enable_self",
        "enable_peer",
        "enable_teacher",
        "updated_at",
    )
    list_filter = ("enable_self", "enable_peer", "enable_teacher")
    search_fields = ("course__title", "course__subject__name")


@admin.register(ClassroomEvaluationConfigVersion)
class ClassroomEvaluationConfigVersionAdmin(admin.ModelAdmin):
    list_display = ("course", "version_no", "config_hash", "created_by", "created_at")
    search_fields = ("course__title", "course__subject__name", "config_hash")
    readonly_fields = tuple(
        field.name for field in ClassroomEvaluationConfigVersion._meta.fields
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClassroomEvaluationSubmission)
class ClassroomEvaluationSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "course",
        "class_group",
        "session",
        "evaluation_type",
        "evaluator",
        "target",
        "submission_version",
        "evaluation_version",
        "updated_at",
    )
    list_filter = ("evaluation_type",)
    search_fields = (
        "course__title",
        "class_group__name",
        "session__title",
        "evaluator__username",
        "evaluator__display_name",
        "target__username",
        "target__display_name",
    )
    readonly_fields = tuple(
        field.name for field in ClassroomEvaluationSubmission._meta.fields
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
