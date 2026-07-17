from __future__ import annotations

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from courses.models import ClassroomSession
from school.models import StudentProfile

from .events import session_group, teacher_group, user_group


class ClassroomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = int(self.scope["url_route"]["kwargs"]["session_id"])
        access = await self._access_context()
        if access is None:
            await self.close(code=4403)
            return

        self.joined_groups = [session_group(self.session_id)]
        if access == "teacher":
            self.joined_groups.append(teacher_group(self.session_id))
        else:
            self.joined_groups.append(user_group(self.session_id, self.scope["user"].id))

        for group_name in self.joined_groups:
            await self.channel_layer.group_add(group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({"type": "chat.connected", "session_id": self.session_id}))

    async def disconnect(self, close_code):
        for group_name in getattr(self, "joined_groups", []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            payload = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            payload = {}
        if payload.get("type") == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))

    async def classroom_event(self, event):
        await self.send(text_data=json.dumps(event["payload"], ensure_ascii=False, default=str))

    @database_sync_to_async
    def _access_context(self) -> str | None:
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not user.is_active:
            return None
        session = ClassroomSession.objects.filter(pk=self.session_id, school_id=user.school_id).first()
        if session is None or session.status != ClassroomSession.Status.RUNNING:
            return None
        if user.role == "teacher" and session.teacher_id == user.id:
            return "teacher"
        if user.role != "student":
            return None
        has_access = StudentProfile.objects.filter(user=user, class_group_id=session.class_group_id).exists()
        return "student" if has_access else None
