from __future__ import annotations

from django.conf import settings
from django.db import models


class ClassroomChatConfig(models.Model):
    session = models.OneToOneField(
        "courses.ClassroomSession",
        on_delete=models.CASCADE,
        related_name="chat_config",
    )
    whole_class_enabled = models.BooleanField(default=False)
    teacher_private_enabled = models.BooleanField(default=False)
    group_chat_enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_classroom_chat_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.session_id}:chat-config"


class ClassroomChatThread(models.Model):
    class RoomType(models.TextChoices):
        WHOLE_CLASS = "whole_class", "全班聊天"
        TEACHER_PRIVATE = "teacher_private", "与老师聊天"
        GROUP = "group", "小组聊天"

    session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.CASCADE,
        related_name="chat_threads",
    )
    room_type = models.CharField(max_length=24, choices=RoomType.choices)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="private_classroom_chat_threads",
    )
    group = models.ForeignKey(
        "courses.ClassroomGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_threads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session"],
                condition=models.Q(room_type="whole_class"),
                name="uniq_whole_class_chat_thread",
            ),
            models.UniqueConstraint(
                fields=["session", "student"],
                condition=models.Q(room_type="teacher_private"),
                name="uniq_private_chat_thread_per_student",
            ),
            models.UniqueConstraint(
                fields=["session", "group"],
                condition=models.Q(room_type="group"),
                name="uniq_group_chat_thread",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(room_type="whole_class", student__isnull=True, group__isnull=True)
                    | models.Q(room_type="teacher_private", student__isnull=False, group__isnull=True)
                    | models.Q(room_type="group", student__isnull=True, group__isnull=False)
                ),
                name="valid_classroom_chat_thread_target",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "room_type", "updated_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        target = self.student_id or self.group_id or "class"
        return f"{self.session_id}:{self.room_type}:{target}"


class ClassroomChatMessage(models.Model):
    class ModerationStatus(models.TextChoices):
        VISIBLE = "visible", "已发送"
        PENDING = "pending", "待教师审核"
        REMOVED = "removed", "已撤回"

    class Severity(models.TextChoices):
        NONE = "none", "正常"
        MILD = "mild", "轻微"
        MODERATE = "moderate", "一般"
        SEVERE = "severe", "严重"

    class ReviewAction(models.TextChoices):
        NONE = "none", "未处理"
        ALLOW = "allow", "放行"
        WARN = "warn", "警告"
        REMOVE = "remove", "撤回"
        DEDUCT = "deduct", "扣分"

    thread = models.ForeignKey(ClassroomChatThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="classroom_chat_messages",
    )
    content = models.TextField(max_length=500)
    content_fingerprint = models.CharField(max_length=64, db_index=True)
    moderation_status = models.CharField(
        max_length=16,
        choices=ModerationStatus.choices,
        default=ModerationStatus.VISIBLE,
    )
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.NONE)
    moderation_categories = models.JSONField(default=list, blank=True)
    matched_rules = models.JSONField(default=list, blank=True)
    review_action = models.CharField(max_length=16, choices=ReviewAction.choices, default=ReviewAction.NONE)
    review_note = models.CharField(max_length=255, blank=True)
    deduction_points = models.FloatField(default=0)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_classroom_chat_messages",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["thread", "moderation_status", "created_at"]),
            models.Index(fields=["sender", "created_at"]),
        ]
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.thread_id}:{self.sender_id}#{self.id}"


class ClassroomChatReadState(models.Model):
    thread = models.ForeignKey(ClassroomChatThread, on_delete=models.CASCADE, related_name="read_states")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="classroom_chat_read_states",
    )
    last_read_message = models.ForeignKey(
        ClassroomChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="read_by_states",
    )
    last_read_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["thread", "user"], name="uniq_classroom_chat_read_state"),
        ]
        indexes = [models.Index(fields=["user", "last_read_at"])]

    def __str__(self) -> str:
        return f"{self.thread_id}:{self.user_id}"
