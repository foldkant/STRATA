from django.urls import path

from . import event_views

app_name = "analytics_api"
urlpatterns = [
    path(
        "learning-events/batch/",
        event_views.learning_event_batch,
        name="learning_event_batch",
    ),
]
