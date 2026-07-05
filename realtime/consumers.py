from __future__ import annotations

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class ClassroomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.class_id = self.scope["url_route"]["kwargs"]["class_id"]
        self.group_name = f"classroom_{self.class_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        payload = json.loads(text_data or "{}")
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "classroom.message",
                "payload": payload,
            },
        )

    async def classroom_message(self, event):
        await self.send(text_data=json.dumps(event["payload"], ensure_ascii=False))
