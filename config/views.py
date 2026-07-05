from __future__ import annotations

import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache

from .onlyoffice import sign_editor_config


def role_redirect(user):
    if user.is_superuser or user.role == "super_admin":
        return redirect("/app/super-admin")
    if user.role == "school_admin":
        return redirect("/app/school-admin")
    if user.role == "teacher":
        return redirect("/app/teacher")
    if user.role == "student":
        return redirect("/app/student")
    return redirect("/app/login")


def home(request):
    return render(request, "home.html")


@never_cache
def login_view(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user())
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return role_redirect(form.get_user())

    return render(request, "login.html", {"form": form, "next": next_url})


def logout_view(request):
    auth_logout(request)
    return redirect("home")


def favicon(request):
    return redirect(static("brand/favicon.ico"), permanent=False)


@login_required(login_url="login")
def dashboard(request):
    user = request.user
    if user.is_superuser or user.role == "super_admin":
        return redirect("/app/super-admin")
    if user.role == "school_admin":
        return redirect("/app/school-admin")
    if user.role == "teacher":
        return redirect("/app/teacher")
    if user.role == "student":
        return redirect("/app/student")
    return render(request, "dashboard.html")


@never_cache
def frontend_app(request):
    frontend_index = settings.BASE_DIR / "static" / "frontend" / "index.html"
    if frontend_index.exists():
        return HttpResponse(frontend_index.read_text(encoding="utf-8"))
    return render(request, "frontend.html")


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "database": connection.vendor})


def _onlyoffice_test_dir() -> Path:
    path = settings.BASE_DIR / "storage" / "onlyoffice-test"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _onlyoffice_test_doc() -> Path:
    test_dir = _onlyoffice_test_dir()
    document = test_dir / "strata-onlyoffice-test.docx"
    if not document.exists():
        template = (
            settings.BASE_DIR
            / "storage"
            / "media"
            / "resources"
            / "strata-onlyoffice-test.docx"
        )
        if template.exists():
            shutil.copyfile(template, document)
        else:
            with zipfile.ZipFile(document, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "[Content_Types].xml",
                    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
                )
                archive.writestr(
                    "_rels/.rels",
                    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
                )
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>STRATA ONLYOFFICE 协作验证文档</w:t></w:r></w:p>
    <w:p><w:r><w:t>可以用两个不同用户同时打开这个文档，验证自有账户协作。</w:t></w:r></w:p>
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>""",
                )
    return document


def onlyoffice_test_file(request):
    document = _onlyoffice_test_doc()
    return FileResponse(
        document.open("rb"),
        as_attachment=False,
        filename=document.name,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@csrf_exempt
def onlyoffice_test_callback(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": 1})

    status = payload.get("status")
    if status in {2, 6} and payload.get("url"):
        target = _onlyoffice_test_doc()
        backup = _onlyoffice_test_dir() / f"saved-{timezone.localtime():%Y%m%d%H%M%S}.docx"
        try:
            with urllib.request.urlopen(payload["url"], timeout=20) as response:
                data = response.read()
            target.write_bytes(data)
            backup.write_bytes(data)
        except Exception as exc:
            (_onlyoffice_test_dir() / "last-error.txt").write_text(str(exc), encoding="utf-8")
            return JsonResponse({"error": 1})

    (_onlyoffice_test_dir() / "last-callback.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return JsonResponse({"error": 0})


def onlyoffice_test_page(request):
    document = _onlyoffice_test_doc()
    user_id = request.GET.get("user") or (str(request.user.id) if request.user.is_authenticated else "guest")
    user_name = request.GET.get("name") or (
        request.user.display_name or request.user.username if request.user.is_authenticated else "访客"
    )
    mode = request.GET.get("mode", "edit")
    host = request.get_host()
    scheme = "https" if request.is_secure() else "http"
    base_url = f"{scheme}://{host}"
    server_url = settings.ONLYOFFICE_DOCUMENT_SERVER_URL
    config = {
        "document": {
            "fileType": "docx",
            "key": f"strata-test-{document.stat().st_mtime_ns}",
            "title": document.name,
            "url": f"{base_url}/onlyoffice-test/file/",
            "permissions": {
                "edit": mode != "view",
                "comment": True,
                "download": True,
                "print": True,
            },
        },
        "documentType": "word",
        "editorConfig": {
            "callbackUrl": f"{base_url}/onlyoffice-test/callback/",
            "lang": "zh-CN",
            "mode": "view" if mode == "view" else "edit",
            "user": {
                "id": user_id,
                "name": user_name,
            },
            "customization": {
                "autosave": True,
                "forcesave": True,
            },
        },
        "height": "100%",
        "width": "100%",
    }
    config = sign_editor_config(config)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ONLYOFFICE 验证 - STRATA</title>
  <style>
    html, body, #placeholder {{ width: 100%; height: 100%; margin: 0; }}
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .tip {{ position: fixed; z-index: 20; left: 12px; bottom: 12px; padding: 8px 10px; background: rgba(15,23,42,.84); color: white; border-radius: 8px; font-size: 12px; }}
  </style>
  <script src="{server_url}/web-apps/apps/api/documents/api.js"></script>
</head>
<body>
  <div id="placeholder"></div>
  <div class="tip">用户：{user_name} / {user_id}</div>
  <script>
    window.docEditor = new DocsAPI.DocEditor("placeholder", {json.dumps(config, ensure_ascii=False)});
  </script>
</body>
</html>"""
    return HttpResponse(html)
