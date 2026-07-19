from django.urls import path

from . import event_views, measurement_views, school_admin_views

app_name = "analytics_api"
urlpatterns = [
    path(
        "teacher/measurement/options/",
        measurement_views.measurement_options,
        name="teacher_measurement_options",
    ),
    path(
        "teacher/measurement/blueprints/",
        measurement_views.blueprints,
        name="teacher_measurement_blueprints",
    ),
    path(
        "teacher/measurement/blueprints/<int:pk>/",
        measurement_views.blueprint_detail,
        name="teacher_measurement_blueprint_detail",
    ),
    path(
        "teacher/measurement/blueprints/<int:pk>/publish/",
        measurement_views.publish_blueprint_view,
        name="teacher_measurement_blueprint_publish",
    ),
    path(
        "teacher/measurement/rubrics/",
        measurement_views.rubrics,
        name="teacher_measurement_rubrics",
    ),
    path(
        "teacher/measurement/rubrics/<int:pk>/",
        measurement_views.rubric_detail,
        name="teacher_measurement_rubric_detail",
    ),
    path(
        "teacher/measurement/rubrics/<int:pk>/publish/",
        measurement_views.publish_rubric_view,
        name="teacher_measurement_rubric_publish",
    ),
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
    path(
        "school-admin/analytics/quality/export/",
        school_admin_views.export_school_quality,
        name="school_admin_analytics_quality_export",
    ),
]
