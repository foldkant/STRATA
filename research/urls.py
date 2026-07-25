from django.urls import path

from . import views


urlpatterns = [
    path("school-admin/research/options/", views.research_options),
    path("school-admin/research/studies/", views.research_studies),
    path("school-admin/research/studies/<int:pk>/", views.research_study_detail),
    path(
        "school-admin/research/studies/<int:pk>/register/",
        views.research_protocol_register,
    ),
    path(
        "school-admin/research/protocols/<int:pk>/",
        views.research_protocol_detail,
    ),
    path(
        "school-admin/research/protocols/<int:pk>/gates/",
        views.research_protocol_gate,
    ),
    path(
        "school-admin/research/protocols/<int:pk>/cohorts/",
        views.research_protocol_cohort,
    ),
    path(
        "school-admin/research/protocols/<int:pk>/runs/",
        views.research_protocol_run,
    ),
    path(
        "school-admin/research/runs/<int:pk>/activate/",
        views.research_run_activate,
    ),
    path(
        "school-admin/research/runs/<int:pk>/close/",
        views.research_run_close,
    ),
    path(
        "school-admin/research/runs/<int:pk>/data-lock/",
        views.research_run_lock,
    ),
    path(
        "school-admin/research/runs/<int:pk>/exposures/",
        views.research_run_exposures,
    ),
    path(
        "school-admin/research/data-locks/<int:pk>/analyses/",
        views.research_data_lock_analyses,
    ),
    path(
        "school-admin/research/protocols/<int:pk>/export/",
        views.research_protocol_export,
    ),
]
