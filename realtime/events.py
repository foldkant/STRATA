from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


logger = logging.getLogger(__name__)


def session_group(session_id: int) -> str:
    return f"classroom_session_{session_id}"


def teacher_group(session_id: int) -> str:
    return f"classroom_teacher_{session_id}"


def user_group(session_id: int, user_id: int) -> str:
    return f"classroom_user_{session_id}_{user_id}"


def publish_chat_event(group_names: list[str], payload: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    for group_name in dict.fromkeys(group_names):
        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {"type": "classroom.event", "payload": payload},
            )
        except Exception:
            logger.warning("Classroom realtime push failed for %s", group_name, exc_info=True)
