from django.urls import path
from django.views.generic import RedirectView

from . import views


urlpatterns = [
    path(
        "",
        RedirectView.as_view(url="/app/school-admin", permanent=False, query_string=True),
        name="school_admin_dashboard",
    ),
    path("export/", views.dashboard_export, name="school_admin_dashboard_export"),
    path(
        "teachers/",
        RedirectView.as_view(url="/app/school-admin/teachers", permanent=False, query_string=True),
        name="school_admin_teacher_list",
    ),
    path("teachers/export/", views.teacher_export, name="school_admin_teacher_export"),
    path("teachers/template/", views.teacher_template, name="school_admin_teacher_template"),
    path("teachers/import/", views.teacher_import, name="school_admin_teacher_import"),
    path("teachers/new/", views.teacher_create, name="school_admin_teacher_create"),
    path("teachers/<int:pk>/edit/", views.teacher_update, name="school_admin_teacher_update"),
    path("teachers/<int:pk>/toggle-active/", views.teacher_toggle_active, name="school_admin_teacher_toggle_active"),
    path("teachers/<int:pk>/delete/", views.teacher_delete, name="school_admin_teacher_delete"),
    path("teachers/<int:pk>/reset-password/", views.teacher_reset_password, name="school_admin_teacher_reset_password"),
    path(
        "students/",
        RedirectView.as_view(url="/app/school-admin/students", permanent=False, query_string=True),
        name="school_admin_student_list",
    ),
    path(
        "classes/",
        RedirectView.as_view(url="/app/school-admin/classes", permanent=False, query_string=True),
        name="school_admin_class_list",
    ),
    path(
        "teaching/",
        RedirectView.as_view(url="/app/school-admin/teaching", permanent=False, query_string=True),
        name="school_admin_teaching_list",
    ),
    path(
        "pretests/",
        RedirectView.as_view(url="/app/school-admin/pretests", permanent=False, query_string=True),
        name="school_admin_pretest_list",
    ),
    path("teacher-permissions/", views.teacher_permission_list, name="school_admin_teacher_permission_list"),
    path(
        "models/",
        RedirectView.as_view(url="/app/school-admin/models", permanent=False, query_string=True),
        name="school_admin_model_overview",
    ),
    path("exports/", views.export_center, name="school_admin_export_center"),
    path("logs/", views.log_list, name="school_admin_log_list"),
    path("module/<slug:slug>/", views.placeholder, name="school_admin_placeholder"),
]
