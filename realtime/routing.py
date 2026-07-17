from django.urls import path

from .consumers import ClassroomConsumer

websocket_urlpatterns = [
    path("ws/classrooms/<int:session_id>/chat/", ClassroomConsumer.as_asgi()),
]
