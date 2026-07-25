from django.contrib import admin

from .models import ClassGroup, School, StudentProfile, TeachingAssignment


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "is_synthetic",
        "status",
        "contact_name",
        "contact_phone",
        "created_at",
    )
    list_filter = ("is_synthetic", "status")
    search_fields = ("name", "code", "contact_name", "contact_phone")


@admin.register(ClassGroup)
class ClassGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "grade", "entry_year")
    list_filter = ("school", "grade")
    search_fields = ("name",)


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "class_group",
        "onboarding_status",
        "is_first_use",
        "score",
    )
    list_filter = ("class_group", "onboarding_status", "is_first_use")
    search_fields = ("user__username", "user__display_name", "student_no")
    exclude = ("current_layer",)


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(admin.ModelAdmin):
    list_display = ("school", "teacher", "class_group", "created_at")
    list_filter = ("school",)
    search_fields = ("teacher__username", "teacher__display_name", "class_group__name")


# Register your models here.
