from django.urls import path

from . import event_views, school_admin_views

app_name = "analytics_api"
urlpatterns = [
    path(
        "learning-events/batch/",
        event_views.learning_event_batch,
        name="learning_event_batch",
    ),
    path(
        "school-admin/analytics/quality/",
        school_admin_views.school_quality,
        name="school_admin_analytics_quality",
    ),
    path(
        "school-admin/analytics/quality/run/",
        school_admin_views.run_school_quality,
        name="school_admin_analytics_quality_run",
    ),
]
