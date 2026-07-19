from __future__ import annotations

from accounts.models import User

from .models import ClassroomChatMessage, ClassroomChatThread


AVATAR_COLORS = ("#2563EB", "#0F766E", "#B45309", "#7C3AED", "#BE123C", "#0369A1", "#4D7C0F", "#C2410C")


def chat_user_row(user: User) -> dict:
    display_name = (user.display_name or user.username).strip()
    return {
        "id": user.id,
        "username": user.username,
        "display_name": display_name,
        "role": user.role,
        "role_label": user.get_role_display(),
        "avatar": {
            "initial": display_name[:1].upper() if display_name else "?",
            "color": AVATAR_COLORS[user.id % len(AVATAR_COLORS)],
        },
    }


def chat_message_row(message: ClassroomChatMessage, *, viewer: User, include_moderation: bool = False) -> dict:
    row = {
        "id": message.id,
        "thread_id": message.thread_id,
        "room_type": message.thread.room_type,
        "target": chat_thread_target_row(message.thread),
        "sender": chat_user_row(message.sender),
        "content": message.content,
        "is_mine": message.sender_id == viewer.id,
        "moderation_status": message.moderation_status,
        "moderation_status_label": message.get_moderation_status_display(),
        "severity": message.severity,
        "severity_label": message.get_severity_display(),
        "review_action": message.review_action,
        "review_action_label": message.get_review_action_display(),
        "review_note": message.review_note,
        "deduction_points": message.deduction_points,
        "reviewed_at": message.reviewed_at,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
    }
    if include_moderation:
        row["moderation_categories"] = message.moderation_categories
        row["matched_rules"] = message.matched_rules
        row["reviewed_by"] = chat_user_row(message.reviewed_by) if message.reviewed_by_id else None
    return row


def chat_thread_target_row(thread: ClassroomChatThread) -> dict | None:
    if thread.room_type == ClassroomChatThread.RoomType.TEACHER_PRIVATE and thread.student_id:
        return chat_user_row(thread.student)
    if thread.room_type == ClassroomChatThread.RoomType.GROUP and thread.group_id:
        return {
            "id": thread.group_id,
            "name": f"第{thread.group.group_no}组",
            "group_no": thread.group.group_no,
        }
    return None
