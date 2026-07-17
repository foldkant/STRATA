from django.contrib import admin

from .models import (
    LearningEvent,
    QuestionBankItem,
    StratificationDecision,
    StudentFeatureSnapshot,
    TestAssessment,
    TestAssessmentQuestion,
    TestAttempt,
    TestAttemptAnswer,
)


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


@admin.register(QuestionBankItem)
class QuestionBankItemAdmin(admin.ModelAdmin):
    list_display = ("stem", "school", "subject", "question_type", "difficulty", "creator", "status", "usage_count")
    list_filter = ("school", "subject", "question_type", "difficulty", "status")
    search_fields = ("stem", "knowledge_point", "creator__username", "creator__display_name")


class TestAssessmentQuestionInline(admin.TabularInline):
    model = TestAssessmentQuestion
    extra = 0


@admin.register(TestAssessment)
class TestAssessmentAdmin(admin.ModelAdmin):
    list_display = ("title", "school", "subject", "teacher", "status", "duration_minutes", "opened_at", "closed_at")
    list_filter = ("school", "subject", "status")
    search_fields = ("title", "teacher__username", "teacher__display_name")
    inlines = (TestAssessmentQuestionInline,)


class TestAttemptAnswerInline(admin.TabularInline):
    model = TestAttemptAnswer
    extra = 0


@admin.register(TestAttempt)
class TestAttemptAdmin(admin.ModelAdmin):
    list_display = ("assessment", "student", "class_group", "status", "total_score", "started_at", "submitted_at")
    list_filter = ("status", "class_group", "assessment")
    search_fields = ("student__username", "student__display_name", "assessment__title")
    inlines = (TestAttemptAnswerInline,)

# Register your models here.
