from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("super-admin/export/", views.dashboard_export, name="ops_dashboard_export"),
    path("super-admin/schools/export/", views.school_export, name="ops_school_export"),
    path("super-admin/schools/template/", views.school_template, name="ops_school_template"),
    path("super-admin/schools/import/", views.school_import, name="ops_school_import"),
    path("super-admin/school-admins/export/", views.school_admin_export, name="ops_school_admin_export"),
    path("super-admin/school-admins/template/", views.school_admin_template, name="ops_school_admin_template"),
    path("super-admin/school-admins/import/", views.school_admin_import, name="ops_school_admin_import"),
    path("super-admin/imports/export/", views.import_export, name="ops_import_export"),
    path("super-admin/imports/<int:pk>/", views.import_detail, name="ops_import_detail"),
    path("super-admin/imports/<int:pk>/delete/", views.import_delete, name="ops_import_delete"),
    path("super-admin/analysis/export/", views.cross_school_analysis_export, name="ops_cross_school_analysis_export"),
    path("super-admin/health/export/", views.system_health_export, name="ops_system_health_export"),
    path("super-admin/incidents/export/", views.incident_export, name="ops_incident_export"),
    path("super-admin/audit-logs/export/", views.audit_log_export, name="ops_audit_log_export"),
    path("super-admin/", RedirectView.as_view(url="/app/super-admin", permanent=False, query_string=True), name="super_admin_console"),
    path("super-admin/schools/", RedirectView.as_view(url="/app/super-admin/schools", permanent=False, query_string=True), name="ops_school_list"),
    path("super-admin/schools/new/", RedirectView.as_view(url="/app/super-admin/schools", permanent=False, query_string=True), name="ops_school_create"),
    path("super-admin/schools/<int:pk>/edit/", RedirectView.as_view(url="/app/super-admin/schools", permanent=False, query_string=True), name="ops_school_update"),
    path("super-admin/schools/<int:pk>/delete/", RedirectView.as_view(url="/app/super-admin/schools", permanent=False, query_string=True), name="ops_school_delete"),
    path("super-admin/school-admins/", RedirectView.as_view(url="/app/super-admin/school-admins", permanent=False, query_string=True), name="ops_school_admin_list"),
    path("super-admin/school-admins/new/", RedirectView.as_view(url="/app/super-admin/school-admins", permanent=False, query_string=True), name="ops_school_admin_create"),
    path("super-admin/school-admins/<int:pk>/edit/", RedirectView.as_view(url="/app/super-admin/school-admins", permanent=False, query_string=True), name="ops_school_admin_update"),
    path("super-admin/school-admins/<int:pk>/delete/", RedirectView.as_view(url="/app/super-admin/school-admins", permanent=False, query_string=True), name="ops_school_admin_delete"),
    path("super-admin/imports/", RedirectView.as_view(url="/app/super-admin/collection", permanent=False, query_string=True), name="ops_import_list"),
    path("super-admin/analysis/", RedirectView.as_view(url="/app/super-admin/analysis", permanent=False, query_string=True), name="ops_cross_school_analysis"),
    path("super-admin/health/", RedirectView.as_view(url="/app/super-admin/health", permanent=False, query_string=True), name="ops_system_health"),
    path("super-admin/incidents/", RedirectView.as_view(url="/app/super-admin/health", permanent=False, query_string=True), name="ops_incident_list"),
    path("super-admin/audit-logs/", RedirectView.as_view(url="/app/super-admin/health", permanent=False, query_string=True), name="ops_audit_log_list"),
]
