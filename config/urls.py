"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from .views import (
    dashboard,
    favicon,
    frontend_app,
    health,
    home,
    login_view,
    logout_view,
    onlyoffice_test_callback,
    onlyoffice_test_file,
    onlyoffice_test_page,
)

urlpatterns = [
    path("", home, name="home"),
    path("favicon.ico", favicon, name="favicon"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("dashboard/", dashboard, name="dashboard"),
    path("ops/", include("ops.urls")),
    path("school-admin/", include("school_admin.urls")),
    path("api/v1/", include("api.urls")),
    path("api/health/", health, name="health"),
    path("onlyoffice-test/", onlyoffice_test_page, name="onlyoffice_test"),
    path("onlyoffice-test/file/", onlyoffice_test_file, name="onlyoffice_test_file"),
    path("onlyoffice-test/callback/", onlyoffice_test_callback, name="onlyoffice_test_callback"),
    path('admin/', admin.site.urls),
    re_path(r"^app(?:/.*)?$", frontend_app, name="frontend_app"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
