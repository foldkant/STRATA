from django.urls import path

from .consumers import ClassroomConsumer

websocket_urlpatterns = [
    path("ws/classes/<int:class_id>/", ClassroomConsumer.as_asgi()),
]
