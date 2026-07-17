from django.contrib import admin

from .models import ClassroomChatConfig, ClassroomChatMessage, ClassroomChatReadState, ClassroomChatThread


@admin.register(ClassroomChatConfig)
class ClassroomChatConfigAdmin(admin.ModelAdmin):
    list_display = ("session", "whole_class_enabled", "teacher_private_enabled", "group_chat_enabled", "updated_at")
    list_filter = ("whole_class_enabled", "teacher_private_enabled", "group_chat_enabled")


@admin.register(ClassroomChatThread)
class ClassroomChatThreadAdmin(admin.ModelAdmin):
    list_display = ("session", "room_type", "student", "group", "updated_at")
    list_filter = ("room_type",)
    search_fields = ("session__title", "student__username", "student__display_name", "group__name")


@admin.register(ClassroomChatMessage)
class ClassroomChatMessageAdmin(admin.ModelAdmin):
    list_display = ("thread", "sender", "moderation_status", "severity", "review_action", "created_at")
    list_filter = ("moderation_status", "severity", "review_action")
    search_fields = ("sender__username", "sender__display_name", "content")
    readonly_fields = ("content_fingerprint", "created_at", "updated_at")


@admin.register(ClassroomChatReadState)
class ClassroomChatReadStateAdmin(admin.ModelAdmin):
    list_display = ("thread", "user", "last_read_message", "last_read_at")
    search_fields = ("user__username", "user__display_name")
