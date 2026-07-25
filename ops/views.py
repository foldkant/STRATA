from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from aiops.models import ModelVersion, TrainingJob
from learning.models import LearningEvent, StratificationDecision
from school.models import ClassGroup, School, StudentProfile

from .forms import (
    PASSWORD_PATTERN,
    PERSON_NAME_PATTERN,
    PHONE_PATTERN,
    SCHOOL_CODE_PATTERN,
    SCHOOL_NAME_PATTERN,
    USERNAME_PATTERN,
    USERNAME_HELP_TEXT,
    ImportBatchUploadForm,
    SchoolAdminCreateForm,
    SchoolAdminUpdateForm,
    SchoolForm,
    XlsxImportForm,
    _matches,
)
from .models import AuditLog, ImportBatch
from .xlsx import build_workbook, export_rows, normalize_text, read_table_rows, template_response, workbook_response


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _require_super_admin(request):
    user = request.user
    if not user.is_authenticated:
        raise PermissionDenied
    if not (user.is_superuser or user.role == "super_admin"):
        raise PermissionDenied


def _write_audit(request, action, *, school=None, target_type="", target_id="", detail=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        school=school,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else "",
        ip_address=_client_ip(request),
        detail=detail or {},
    )


def _sha256(uploaded_file) -> str:
    hasher = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        hasher.update(chunk)
    uploaded_file.seek(0)
    return hasher.hexdigest()


def _read_manifest(import_batch: ImportBatch) -> dict:
    try:
        with import_batch.package_file.open("rb") as fh:
            with zipfile.ZipFile(fh) as archive:
                names = set(archive.namelist())
                if "manifest.json" not in names:
                    return {"error": "数据采集包缺少 manifest.json", "files": sorted(names)[:30]}
                with archive.open("manifest.json") as manifest_file:
                    raw = manifest_file.read().decode("utf-8")
                    return json.loads(raw)
    except zipfile.BadZipFile:
        return {"error": "数据采集包不是有效的 zip 文件"}
    except UnicodeDecodeError:
        return {"error": "manifest.json 必须使用 UTF-8 编码"}
    except json.JSONDecodeError:
        return {"error": "manifest.json 不是有效的 JSON 文件"}
    except Exception as exc:
        return {"error": str(exc)}


def _base_context(active_page: str, page_title: str) -> dict:
    return {
        "active_page": active_page,
        "page_title": page_title,
        "nav_items": [
            ("dashboard", "数据总览", reverse("super_admin_console")),
            ("schools", "学校管理", reverse("ops_school_list")),
            ("school_admins", "学校管理员", reverse("ops_school_admin_list")),
            ("collection", "跨校数据采集", reverse("ops_import_list")),
            ("analysis", "跨校分析", reverse("ops_cross_school_analysis")),
            ("health", "系统健康", reverse("ops_system_health")),
            ("incidents", "严重故障", reverse("ops_incident_list")),
            ("logs", "操作日志", reverse("ops_audit_log_list")),
        ],
    }


def _paginate(request, queryset, per_page=12):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("page"))


def _status_rows(choices, counts):
    total = sum(counts.values()) or 1
    rows = []
    for value, label in choices:
        count = counts.get(value, 0)
        rows.append(
            {
                "value": value,
                "label": label,
                "count": count,
                "percent": round(count * 100 / total),
            }
        )
    return rows


def _day_series(queryset, date_field: str, days=7):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        queryset.filter(**{f"{date_field}__date__gte": start})
        .annotate(day=TruncDate(date_field))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    by_day = {item["day"]: item["total"] for item in rows}
    values = []
    max_value = 1
    for offset in range(days):
        day = start + timedelta(days=offset)
        count = by_day.get(day, 0)
        max_value = max(max_value, count)
        values.append({"label": day.strftime("%m-%d"), "count": count})
    for item in values:
        item["height"] = max(8, round(item["count"] * 100 / max_value)) if item["count"] else 8
    return values


def _xlsx_filename(prefix: str) -> str:
    return f"{prefix}_{timezone.localtime():%Y%m%d%H%M%S}.xlsx"


def _choice_value(value: str, choices, *, default=None):
    text = normalize_text(value)
    if not text:
        return default
    lookup = {}
    for choice_value, label in choices:
        lookup[choice_value] = choice_value
        lookup[str(label)] = choice_value
    return lookup.get(text)


def _active_value(value: str, *, default=True) -> bool | None:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"启用", "正常", "是", "1", "true", "active", "enabled"}:
        return True
    if text in {"停用", "禁用", "否", "0", "false", "disabled", "inactive"}:
        return False
    return None


def _row_error(row: dict, message: str) -> str:
    return f"第 {row.get('__row_number', '?')} 行：{message}"


def _school_queryset(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    schools = School.objects.annotate(
        class_count=Count("classes", distinct=True),
        user_count=Count("users", distinct=True),
        import_count=Count("import_batches", distinct=True),
        export_count=Count("export_batches", distinct=True),
    ).order_by("name", "code")
    if query:
        schools = schools.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(contact_name__icontains=query))
    if status:
        schools = schools.filter(status=status)
    return schools


def _school_admin_queryset(request):
    User = get_user_model()
    query = request.GET.get("q", "").strip()
    school_id = request.GET.get("school", "").strip()
    admins = User.objects.filter(role="school_admin").select_related("school").order_by("school__name", "username")
    if query:
        admins = admins.filter(
            Q(username__icontains=query) | Q(display_name__icontains=query) | Q(phone__icontains=query)
        )
    if school_id:
        admins = admins.filter(school_id=school_id)
    return admins


SCHOOL_IMPORT_HEADERS = ["学校编号", "学校名称", "状态", "联系人", "联系电话", "学校地址", "备注"]
SCHOOL_ADMIN_IMPORT_HEADERS = ["所属学校编号", "登录账号", "姓名", "联系电话", "初始密码", "状态"]


def _validate_school_import(rows: list[dict]) -> tuple[list[dict], list[str]]:
    errors = []
    records = []
    seen_codes = set()
    seen_names = {}

    for row in rows:
        code = normalize_text(row.get("学校编号")).upper()
        name = normalize_text(row.get("学校名称"))
        status_text = normalize_text(row.get("状态"))
        status = _choice_value(status_text, School.Status.choices, default=School.Status.ACTIVE)
        contact_name = normalize_text(row.get("联系人"))
        contact_phone = normalize_text(row.get("联系电话"))
        address = normalize_text(row.get("学校地址"))
        note = normalize_text(row.get("备注"))

        if not _matches(SCHOOL_CODE_PATTERN, code):
            errors.append(_row_error(row, "学校编号需为 2-32 位大写字母、数字、下划线或短横线。"))
        if code in seen_codes:
            errors.append(_row_error(row, f"学校编号 {code} 在文件中重复。"))
        seen_codes.add(code)

        if not _matches(SCHOOL_NAME_PATTERN, name):
            errors.append(_row_error(row, "学校名称需为 2-80 位，可包含中文、字母、数字、空格、括号和短横线。"))
        if name in seen_names and seen_names[name] != code:
            errors.append(_row_error(row, f"学校名称 {name} 在文件中重复。"))
        seen_names[name] = code

        if status is None:
            errors.append(_row_error(row, "状态只能填写启用、停用或归档。"))
        if contact_name and not _matches(PERSON_NAME_PATTERN, contact_name):
            errors.append(_row_error(row, "联系人需为 2-24 位中文或字母。"))
        if contact_phone and not _matches(PHONE_PATTERN, contact_phone):
            errors.append(_row_error(row, "联系电话格式不正确。"))
        if len(address) > 255:
            errors.append(_row_error(row, "学校地址不能超过 255 个字符。"))

        name_conflict = School.objects.filter(name=name).exclude(code=code).first()
        if name_conflict:
            errors.append(_row_error(row, f"学校名称已被编号 {name_conflict.code} 使用。"))

        records.append(
            {
                "code": code,
                "name": name,
                "status": status,
                "contact_name": contact_name,
                "contact_phone": contact_phone,
                "address": address,
                "note": note,
            }
        )

    return records, errors


def _validate_school_admin_import(rows: list[dict]) -> tuple[list[dict], list[str]]:
    User = get_user_model()
    errors = []
    records = []
    seen_usernames = set()
    school_codes = {normalize_text(row.get("所属学校编号")).upper() for row in rows if normalize_text(row.get("所属学校编号"))}
    schools = {school.code: school for school in School.objects.filter(code__in=school_codes)}

    for row in rows:
        school_code = normalize_text(row.get("所属学校编号")).upper()
        username = normalize_text(row.get("登录账号"))
        display_name = normalize_text(row.get("姓名"))
        phone = normalize_text(row.get("联系电话"))
        password = normalize_text(row.get("初始密码"))
        active = _active_value(row.get("状态"), default=True)
        school = schools.get(school_code)
        existing_user = User.objects.filter(username=username).first() if username else None

        if not _matches(SCHOOL_CODE_PATTERN, school_code):
            errors.append(_row_error(row, "所属学校编号格式不正确。"))
        elif school is None:
            errors.append(_row_error(row, f"找不到学校编号 {school_code}，请先导入学校。"))

        if not _matches(USERNAME_PATTERN, username):
            errors.append(_row_error(row, f"登录账号需为 {USERNAME_HELP_TEXT}。"))
        if username in seen_usernames:
            errors.append(_row_error(row, f"登录账号 {username} 在文件中重复。"))
        seen_usernames.add(username)

        if not _matches(PERSON_NAME_PATTERN, display_name):
            errors.append(_row_error(row, "姓名需为 2-24 位中文或字母。"))
        if phone and not _matches(PHONE_PATTERN, phone):
            errors.append(_row_error(row, "联系电话格式不正确。"))
        if active is None:
            errors.append(_row_error(row, "状态只能填写启用或停用。"))
        if existing_user and existing_user.role != "school_admin":
            errors.append(_row_error(row, f"登录账号 {username} 已被其他角色占用。"))
        if not existing_user and not password:
            errors.append(_row_error(row, "新增学校管理员必须填写初始密码。"))
        if password and not _matches(PASSWORD_PATTERN, password):
            errors.append(_row_error(row, "初始密码需为 8-32 位，并至少包含字母和数字。"))

        records.append(
            {
                "school": school,
                "username": username,
                "display_name": display_name,
                "phone": phone,
                "password": password,
                "is_active": active if active is not None else True,
                "existing_user": existing_user,
            }
        )

    return records, errors


def _build_incidents():
    incidents = []
    for item in ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).select_related("source_school")[:20]:
        incidents.append(
            {
                "time": item.uploaded_at,
                "level": "严重",
                "type": "数据采集失败",
                "target": item.batch_code,
                "school": item.source_school.name if item.source_school else item.source_school_code or "-",
                "detail": item.log or "采集包校验失败。",
                "url": reverse("ops_import_detail", args=[item.pk]),
            }
        )
    for job in TrainingJob.objects.filter(status=TrainingJob.Status.FAILED).select_related("class_group")[:20]:
        incidents.append(
            {
                "time": job.created_at,
                "level": "严重",
                "type": "模型训练失败",
                "target": f"训练任务 #{job.pk}",
                "school": job.class_group.school.name if job.class_group_id else "-",
                "detail": job.logs or "训练任务失败。",
                "url": "",
            }
        )
    return sorted(incidents, key=lambda item: item["time"], reverse=True)[:30]


@login_required(login_url="login")
def super_admin_dashboard(request):
    _require_super_admin(request)

    User = get_user_model()
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)

    school_status_counts = dict(School.objects.values_list("status").annotate(total=Count("id")))
    import_status_counts = dict(ImportBatch.objects.values_list("status").annotate(total=Count("id")))

    context = {
        **_base_context("dashboard", "数据总览"),
        "metrics": [
            {"label": "学校", "value": School.objects.count(), "sub": "已登记学校"},
            {"label": "学校管理员", "value": User.objects.filter(role="school_admin").count(), "sub": "本地管理账号"},
            {"label": "教师", "value": User.objects.filter(role="teacher").count(), "sub": "教师账号"},
            {"label": "学生档案", "value": StudentProfile.objects.count(), "sub": "已建档学生"},
            {"label": "班级", "value": ClassGroup.objects.count(), "sub": "行政/教学班"},
            {"label": "行为事件", "value": LearningEvent.objects.count(), "sub": "学习过程记录"},
        ],
        "daily_school_series": _day_series(School.objects.all(), "created_at", days=7),
        "daily_import_series": _day_series(ImportBatch.objects.all(), "uploaded_at", days=7),
        "school_status_rows": _status_rows(School.Status.choices, school_status_counts),
        "import_status_rows": _status_rows(ImportBatch.Status.choices, import_status_counts),
        "pending_imports": ImportBatch.objects.filter(status=ImportBatch.Status.UPLOADED).count(),
        "failed_imports": ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).count(),
        "recent_imports": ImportBatch.objects.select_related("source_school", "uploaded_by")[:6],
        "recent_logs": AuditLog.objects.select_related("actor", "school")[:8],
        "model_versions": ModelVersion.objects.count(),
        "training_jobs_7d": TrainingJob.objects.filter(created_at__gte=seven_days_ago).count(),
        "pending_decisions": StratificationDecision.objects.filter(status=StratificationDecision.Status.PENDING).count(),
        "last_updated": now,
    }
    return render(request, "ops/dashboard.html", context)


@login_required(login_url="login")
def dashboard_export(request):
    _require_super_admin(request)

    User = get_user_model()
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    school_status_rows = _status_rows(
        School.Status.choices,
        dict(School.objects.values_list("status").annotate(total=Count("id"))),
    )
    import_status_rows = _status_rows(
        ImportBatch.Status.choices,
        dict(ImportBatch.objects.values_list("status").annotate(total=Count("id"))),
    )
    metrics = [
        ["学校", School.objects.count(), "已登记学校"],
        ["学校管理员", User.objects.filter(role="school_admin").count(), "本地管理账号"],
        ["教师", User.objects.filter(role="teacher").count(), "教师账号"],
        ["学生档案", StudentProfile.objects.count(), "已建档学生"],
        ["班级", ClassGroup.objects.count(), "行政/教学班"],
        ["行为事件", LearningEvent.objects.count(), "学习过程记录"],
        ["模型版本", ModelVersion.objects.count(), "班级模型"],
        ["近 7 天训练", TrainingJob.objects.filter(created_at__gte=seven_days_ago).count(), "训练任务"],
        ["待确认分层", StratificationDecision.objects.filter(status=StratificationDecision.Status.PENDING).count(), "教师待处理"],
    ]
    workbook = build_workbook(
        [
            {"title": "指标", "headers": ["指标", "数值", "说明"], "rows": metrics},
            {
                "title": "学校新增趋势",
                "headers": ["日期", "数量"],
                "rows": [[item["label"], item["count"]] for item in _day_series(School.objects.all(), "created_at", days=7)],
            },
            {
                "title": "采集趋势",
                "headers": ["日期", "数量"],
                "rows": [[item["label"], item["count"]] for item in _day_series(ImportBatch.objects.all(), "uploaded_at", days=7)],
            },
            {
                "title": "学校状态",
                "headers": ["状态", "数量", "占比"],
                "rows": [[row["label"], row["count"], f'{row["percent"]}%'] for row in school_status_rows],
            },
            {
                "title": "采集状态",
                "headers": ["状态", "数量", "占比"],
                "rows": [[row["label"], row["count"], f'{row["percent"]}%'] for row in import_status_rows],
            },
            {
                "title": "最近采集",
                "headers": ["批次", "学校编号", "学校", "版本", "状态", "上传人", "上传时间"],
                "rows": [
                    [
                        item.batch_code,
                        item.source_school_code,
                        item.source_school.name if item.source_school else "",
                        item.source_system_version,
                        item.get_status_display(),
                        item.uploaded_by,
                        item.uploaded_at,
                    ]
                    for item in ImportBatch.objects.select_related("source_school", "uploaded_by")[:50]
                ],
            },
            {
                "title": "最近操作",
                "headers": ["时间", "动作", "操作者", "学校", "对象", "IP", "详情"],
                "rows": [
                    [
                        log.created_at,
                        log.action,
                        log.actor,
                        log.school.name if log.school else "",
                        f"{log.target_type} #{log.target_id}" if log.target_id else log.target_type,
                        log.ip_address,
                        log.detail,
                    ]
                    for log in AuditLog.objects.select_related("actor", "school")[:50]
                ],
            },
        ]
    )
    _write_audit(request, "dashboard.export", target_type="dashboard")
    return workbook_response(workbook, _xlsx_filename("数据总览"))


@login_required(login_url="login")
def school_list(request):
    _require_super_admin(request)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    schools = _school_queryset(request)

    context = {
        **_base_context("schools", "学校管理"),
        "schools": _paginate(request, schools, 12),
        "query": query,
        "status": status,
        "status_choices": School.Status.choices,
    }
    return render(request, "ops/schools.html", context)


@login_required(login_url="login")
def school_export(request):
    _require_super_admin(request)

    schools = _school_queryset(request)
    rows = [
        [
            school.code,
            school.name,
            school.get_status_display(),
            school.class_count,
            school.user_count,
            school.import_count,
            school.export_count,
            school.contact_name,
            school.contact_phone,
            school.address,
            school.updated_at,
            school.note,
        ]
        for school in schools
    ]
    _write_audit(request, "school.export", target_type="school", detail={"count": len(rows)})
    return export_rows(
        _xlsx_filename("学校列表"),
        "学校列表",
        ["学校编号", "学校名称", "状态", "班级数", "账号数", "采集数", "导出数", "联系人", "联系电话", "学校地址", "更新时间", "备注"],
        rows,
    )


@login_required(login_url="login")
def school_template(request):
    _require_super_admin(request)

    return template_response(
        "学校批量导入模板.xlsx",
        "学校导入模板",
        SCHOOL_IMPORT_HEADERS,
        [["XLZX", "小榄中学", "启用", "张老师", "13800138000", "中山市小榄镇", ""]],
        instructions=[
            "学校编号必填且唯一，建议使用大写字母、数字、下划线或短横线。",
            "学校名称必填且唯一；状态可填：启用、停用、归档。",
            "再次导入相同学校编号时，系统会更新已有学校信息。",
        ],
        dropdowns={"状态": [label for _, label in School.Status.choices]},
    )


@login_required(login_url="login")
def school_import(request):
    _require_super_admin(request)

    form = XlsxImportForm(request.POST or None, request.FILES or None)
    errors = []
    if request.method == "POST" and form.is_valid():
        try:
            rows = read_table_rows(
                form.cleaned_data["file"],
                required_headers=["学校编号", "学校名称"],
                all_headers=SCHOOL_IMPORT_HEADERS,
            )
            if not rows:
                errors.append("Excel 文件没有可导入的数据行。")
            records, errors = _validate_school_import(rows)
            if not errors:
                created_count = 0
                updated_count = 0
                with transaction.atomic():
                    for record in records:
                        school, created = School.objects.update_or_create(
                            code=record["code"],
                            defaults={
                                "name": record["name"],
                                "status": record["status"],
                                "contact_name": record["contact_name"],
                                "contact_phone": record["contact_phone"],
                                "address": record["address"],
                                "note": record["note"],
                            },
                        )
                        if created:
                            created_count += 1
                        else:
                            updated_count += 1
                    _write_audit(
                        request,
                        "school.bulk_import",
                        target_type="school",
                        detail={"created": created_count, "updated": updated_count},
                    )
                messages.success(request, f"学校批量导入完成：新增 {created_count} 所，更新 {updated_count} 所。")
                return redirect("ops_school_list")
        except ValueError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"导入失败：{exc}")

    context = {
        **_base_context("schools", "批量导入学校"),
        "form": form,
        "errors": errors,
        "template_url": reverse("ops_school_template"),
        "back_url": reverse("ops_school_list"),
        "page_hint": "请先下载模板，按表头填写后上传 xlsx 文件。",
    }
    return render(request, "ops/xlsx_import.html", context)


@login_required(login_url="login")
def school_create(request):
    _require_super_admin(request)

    form = SchoolForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        school = form.save()
        _write_audit(request, "school.create", school=school, target_type="school", target_id=school.id)
        messages.success(request, "学校已创建。")
        return redirect("ops_school_list")

    context = {
        **_base_context("schools", "新增学校"),
        "form": form,
        "form_title": "新增学校",
        "submit_label": "保存学校",
        "back_url": reverse("ops_school_list"),
    }
    return render(request, "ops/school_form.html", context)


@login_required(login_url="login")
def school_update(request, pk):
    _require_super_admin(request)

    school = get_object_or_404(School, pk=pk)
    form = SchoolForm(request.POST or None, instance=school)
    if request.method == "POST" and form.is_valid():
        school = form.save()
        _write_audit(request, "school.update", school=school, target_type="school", target_id=school.id)
        messages.success(request, "学校信息已更新。")
        return redirect("ops_school_list")

    context = {
        **_base_context("schools", "编辑学校"),
        "form": form,
        "school": school,
        "form_title": "编辑学校",
        "submit_label": "保存修改",
        "back_url": reverse("ops_school_list"),
    }
    return render(request, "ops/school_form.html", context)


@login_required(login_url="login")
def school_delete(request, pk):
    _require_super_admin(request)

    school = get_object_or_404(School, pk=pk)
    blockers = []
    if school.classes.exists():
        blockers.append("已有关联班级")
    if school.users.exists():
        blockers.append("已有关联账号")
    if school.import_batches.exists():
        blockers.append("已有采集记录")
    if school.export_batches.exists():
        blockers.append("已有导出记录")

    if request.method == "POST":
        if blockers:
            messages.error(request, "该学校存在关联数据，不能删除；可在编辑页改为停用或归档。")
            return redirect("ops_school_delete", pk=school.pk)
        detail = {"name": school.name, "code": school.code}
        target_id = school.id
        school.delete()
        _write_audit(request, "school.delete", target_type="school", target_id=target_id, detail=detail)
        messages.success(request, "学校已删除。")
        return redirect("ops_school_list")

    context = {
        **_base_context("schools", "删除学校"),
        "school": school,
        "blockers": blockers,
        "back_url": reverse("ops_school_list"),
    }
    return render(request, "ops/school_confirm_delete.html", context)


@login_required(login_url="login")
def school_admin_list(request):
    _require_super_admin(request)

    query = request.GET.get("q", "").strip()
    school_id = request.GET.get("school", "").strip()
    admins = _school_admin_queryset(request)

    context = {
        **_base_context("school_admins", "学校管理员"),
        "admins": _paginate(request, admins, 12),
        "schools": School.objects.order_by("name"),
        "query": query,
        "school_id": school_id,
    }
    return render(request, "ops/school_admins.html", context)


@login_required(login_url="login")
def school_admin_export(request):
    _require_super_admin(request)

    admins = _school_admin_queryset(request)
    rows = [
        [
            school_admin.username,
            school_admin.display_name,
            school_admin.school.code if school_admin.school else "",
            school_admin.school.name if school_admin.school else "",
            school_admin.phone,
            "启用" if school_admin.is_active else "停用",
            "是" if school_admin.is_first_login else "否",
            school_admin.last_login,
            school_admin.date_joined,
        ]
        for school_admin in admins
    ]
    _write_audit(request, "school_admin.export", target_type="user", detail={"count": len(rows)})
    return export_rows(
        _xlsx_filename("学校管理员列表"),
        "学校管理员",
        ["登录账号", "姓名", "学校编号", "所属学校", "联系电话", "状态", "首次登录", "最近登录", "创建时间"],
        rows,
    )


@login_required(login_url="login")
def school_admin_template(request):
    _require_super_admin(request)

    return template_response(
        "学校管理员批量导入模板.xlsx",
        "学校管理员导入模板",
        SCHOOL_ADMIN_IMPORT_HEADERS,
        [["XLZX", "schooladmin1", "学校管理员", "13800138000", "Strata2026", "启用"]],
        instructions=[
            "所属学校编号必须已存在，请先完成学校导入。",
            f"登录账号必填且唯一；{USERNAME_HELP_TEXT}。",
            "新增学校管理员必须填写初始密码，且不能使用 123456 这类低安全密码。",
            "再次导入相同登录账号时，系统会更新姓名、学校、电话和状态；初始密码留空则不修改原密码。",
        ],
        dropdowns={"状态": ["启用", "停用"]},
    )


@login_required(login_url="login")
def school_admin_import(request):
    _require_super_admin(request)

    User = get_user_model()
    form = XlsxImportForm(request.POST or None, request.FILES or None)
    errors = []
    if request.method == "POST" and form.is_valid():
        try:
            rows = read_table_rows(
                form.cleaned_data["file"],
                required_headers=["所属学校编号", "登录账号", "姓名"],
                all_headers=SCHOOL_ADMIN_IMPORT_HEADERS,
            )
            if not rows:
                errors.append("Excel 文件没有可导入的数据行。")
            records, errors = _validate_school_admin_import(rows)
            if not errors:
                created_count = 0
                updated_count = 0
                with transaction.atomic():
                    for record in records:
                        existing_user = record["existing_user"]
                        if existing_user:
                            existing_user.school = record["school"]
                            existing_user.display_name = record["display_name"]
                            existing_user.phone = record["phone"]
                            existing_user.is_active = record["is_active"]
                            if record["password"]:
                                existing_user.set_password(record["password"])
                                existing_user.is_first_login = True
                            existing_user.save()
                            updated_count += 1
                        else:
                            User.objects.create_user(
                                username=record["username"],
                                password=record["password"],
                                display_name=record["display_name"],
                                phone=record["phone"],
                                role="school_admin",
                                school=record["school"],
                                is_active=record["is_active"],
                                is_staff=False,
                                is_first_login=True,
                            )
                            created_count += 1
                    _write_audit(
                        request,
                        "school_admin.bulk_import",
                        target_type="user",
                        detail={"created": created_count, "updated": updated_count},
                    )
                messages.success(request, f"学校管理员批量导入完成：新增 {created_count} 个，更新 {updated_count} 个。")
                return redirect("ops_school_admin_list")
        except ValueError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"导入失败：{exc}")

    context = {
        **_base_context("school_admins", "批量导入学校管理员"),
        "form": form,
        "errors": errors,
        "template_url": reverse("ops_school_admin_template"),
        "back_url": reverse("ops_school_admin_list"),
        "page_hint": "请先下载模板。新增学校管理员必须填写初始密码，更新已有学校管理员时密码可留空。",
    }
    return render(request, "ops/xlsx_import.html", context)


@login_required(login_url="login")
def school_admin_create(request):
    _require_super_admin(request)

    User = get_user_model()
    form = SchoolAdminCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.create_user(
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
            display_name=form.cleaned_data["display_name"],
            phone=form.cleaned_data["phone"],
            role="school_admin",
            school=form.cleaned_data["school"],
            is_active=form.cleaned_data["is_active"],
            is_staff=False,
            is_first_login=True,
        )
        _write_audit(
            request,
            "school_admin.create",
            school=user.school,
            target_type="user",
            target_id=user.id,
            detail={"username": user.username},
        )
        messages.success(request, "学校管理员账号已创建。")
        return redirect("ops_school_admin_list")

    context = {
        **_base_context("school_admins", "新增学校管理员"),
        "form": form,
        "form_title": "新增学校管理员",
        "submit_label": "保存账号",
        "back_url": reverse("ops_school_admin_list"),
    }
    return render(request, "ops/school_admin_form.html", context)


@login_required(login_url="login")
def school_admin_update(request, pk):
    _require_super_admin(request)

    User = get_user_model()
    admin_user = get_object_or_404(User, pk=pk, role="school_admin")
    form = SchoolAdminUpdateForm(request.POST or None, user=admin_user)
    if request.method == "POST" and form.is_valid():
        admin_user.school = form.cleaned_data["school"]
        admin_user.username = form.cleaned_data["username"]
        admin_user.display_name = form.cleaned_data["display_name"]
        admin_user.phone = form.cleaned_data["phone"]
        admin_user.is_active = form.cleaned_data["is_active"]
        if form.cleaned_data["password"]:
            admin_user.set_password(form.cleaned_data["password"])
            admin_user.is_first_login = True
        admin_user.save()
        _write_audit(
            request,
            "school_admin.update",
            school=admin_user.school,
            target_type="user",
            target_id=admin_user.id,
            detail={"username": admin_user.username},
        )
        messages.success(request, "学校管理员账号已更新。")
        return redirect("ops_school_admin_list")

    context = {
        **_base_context("school_admins", "编辑学校管理员"),
        "form": form,
        "admin_user": admin_user,
        "form_title": "编辑学校管理员",
        "submit_label": "保存修改",
        "back_url": reverse("ops_school_admin_list"),
    }
    return render(request, "ops/school_admin_form.html", context)


@login_required(login_url="login")
def school_admin_delete(request, pk):
    _require_super_admin(request)

    User = get_user_model()
    admin_user = get_object_or_404(User.objects.select_related("school"), pk=pk, role="school_admin")
    if admin_user.is_active:
        messages.error(request, "该学校管理员账号仍处于启用状态。请先停用账号，再执行删除。")
        return redirect("ops_school_admin_update", pk=admin_user.pk)

    if request.method == "POST":
        detail = {
            "username": admin_user.username,
            "display_name": admin_user.display_name,
            "school": admin_user.school.name if admin_user.school else "",
            "role": admin_user.role,
        }
        school = admin_user.school
        target_id = admin_user.id
        try:
            admin_user.delete()
        except ProtectedError:
            messages.error(request, "该账号已有业务数据关联，不能物理删除；请保持停用状态。")
            return redirect("ops_school_admin_list")
        _write_audit(request, "school_admin.delete", school=school, target_type="user", target_id=target_id, detail=detail)
        messages.success(request, "学校管理员账号已删除。")
        return redirect("ops_school_admin_list")

    context = {
        **_base_context("school_admins", "删除学校管理员"),
        "admin_user": admin_user,
        "back_url": reverse("ops_school_admin_list"),
    }
    return render(request, "ops/school_admin_confirm_delete.html", context)


@login_required(login_url="login")
def import_list(request):
    _require_super_admin(request)

    form = ImportBatchUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["package_file"]
        now = timezone.now()
        import_batch = form.save(commit=False)
        import_batch.batch_code = f"IMP-{now:%Y%m%d%H%M%S}"
        import_batch.uploaded_by = request.user
        import_batch.status = ImportBatch.Status.UPLOADED
        import_batch.checksum = _sha256(uploaded)
        import_batch.save()

        manifest = _read_manifest(import_batch)
        import_batch.manifest = manifest
        if isinstance(manifest, dict):
            import_batch.source_school_code = str(manifest.get("school_code", ""))
            import_batch.source_system_version = str(manifest.get("system_version", ""))
            if import_batch.source_school_code:
                import_batch.source_school = School.objects.filter(code=import_batch.source_school_code).first()
        if isinstance(manifest, dict) and manifest.get("error"):
            import_batch.status = ImportBatch.Status.FAILED
            import_batch.log = manifest["error"]
            messages.error(request, manifest["error"])
        else:
            import_batch.status = ImportBatch.Status.VALIDATED
            messages.success(request, "数据采集包已上传并完成基础校验。")
        import_batch.save()

        _write_audit(
            request,
            "collection.upload",
            school=import_batch.source_school,
            target_type="import_batch",
            target_id=import_batch.id,
            detail={"batch_code": import_batch.batch_code, "checksum": import_batch.checksum},
        )
        return redirect("ops_import_detail", pk=import_batch.pk)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    imports = ImportBatch.objects.select_related("source_school", "uploaded_by")
    if query:
        imports = imports.filter(
            Q(batch_code__icontains=query)
            | Q(source_school_code__icontains=query)
            | Q(source_system_version__icontains=query)
        )
    if status:
        imports = imports.filter(status=status)

    context = {
        **_base_context("collection", "跨校数据采集"),
        "form": form,
        "imports": _paginate(request, imports, 10),
        "query": query,
        "status": status,
        "status_choices": ImportBatch.Status.choices,
    }
    return render(request, "ops/imports.html", context)


@login_required(login_url="login")
def import_export(request):
    _require_super_admin(request)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    imports = ImportBatch.objects.select_related("source_school", "uploaded_by")
    if query:
        imports = imports.filter(
            Q(batch_code__icontains=query)
            | Q(source_school_code__icontains=query)
            | Q(source_system_version__icontains=query)
        )
    if status:
        imports = imports.filter(status=status)

    rows = [
        [
            item.batch_code,
            item.source_school_code,
            item.source_school.name if item.source_school else "",
            item.source_system_version,
            item.get_status_display(),
            item.uploaded_by,
            item.uploaded_at,
            item.imported_at,
            item.checksum,
            item.log,
        ]
        for item in imports
    ]
    _write_audit(request, "collection.export", target_type="import_batch", detail={"count": len(rows)})
    return export_rows(
        _xlsx_filename("跨校数据采集"),
        "采集记录",
        ["批次", "学校编号", "学校", "版本", "状态", "上传人", "上传时间", "导入时间", "校验值", "日志"],
        rows,
    )


@login_required(login_url="login")
def import_detail(request, pk):
    _require_super_admin(request)

    import_batch = get_object_or_404(ImportBatch.objects.select_related("source_school", "uploaded_by"), pk=pk)
    context = {
        **_base_context("collection", "采集详情"),
        "import_batch": import_batch,
        "manifest_pretty": json.dumps(import_batch.manifest, ensure_ascii=False, indent=2) if import_batch.manifest else "",
        "back_url": reverse("ops_import_list"),
    }
    return render(request, "ops/import_detail.html", context)


@login_required(login_url="login")
def import_delete(request, pk):
    _require_super_admin(request)

    import_batch = get_object_or_404(ImportBatch, pk=pk)
    if request.method == "POST":
        detail = {"batch_code": import_batch.batch_code, "status": import_batch.status}
        target_id = import_batch.id
        school = import_batch.source_school
        if import_batch.package_file:
            import_batch.package_file.delete(save=False)
        import_batch.delete()
        _write_audit(request, "collection.delete", school=school, target_type="import_batch", target_id=target_id, detail=detail)
        messages.success(request, "采集记录已删除。")
        return redirect("ops_import_list")

    context = {
        **_base_context("collection", "删除采集记录"),
        "import_batch": import_batch,
        "back_url": reverse("ops_import_list"),
    }
    return render(request, "ops/import_confirm_delete.html", context)


@login_required(login_url="login")
def cross_school_analysis(request):
    _require_super_admin(request)

    schools = School.objects.annotate(
        class_count=Count("classes", distinct=True),
        user_count=Count("users", distinct=True),
        student_count=Count("classes__students", distinct=True),
        collection_count=Count("import_batches", distinct=True),
    ).order_by("name", "code")

    event_rows = []
    event_total = LearningEvent.objects.count() or 1
    for row in LearningEvent.objects.values("event_type").annotate(count=Count("id")).order_by("-count")[:8]:
        event_rows.append(
            {
                "label": dict(LearningEvent.EventType.choices).get(row["event_type"], row["event_type"]),
                "count": row["count"],
                "percent": round(row["count"] * 100 / event_total),
            }
        )

    school_rows = []
    max_students = 1
    for school in schools:
        max_students = max(max_students, school.student_count)
    for school in schools[:10]:
        school_rows.append(
            {
                "name": school.name,
                "code": school.code,
                "class_count": school.class_count,
                "student_count": school.student_count,
                "collection_count": school.collection_count,
                "percent": round(school.student_count * 100 / max_students) if school.student_count else 0,
            }
        )

    context = {
        **_base_context("analysis", "跨校分析"),
        "metrics": [
            {"label": "学校覆盖", "value": School.objects.count(), "sub": "已登记学校"},
            {"label": "采集批次", "value": ImportBatch.objects.count(), "sub": "上传数据包"},
            {"label": "学生档案", "value": StudentProfile.objects.count(), "sub": "跨校汇总"},
            {"label": "行为事件", "value": LearningEvent.objects.count(), "sub": "学习过程数据"},
            {"label": "模型版本", "value": ModelVersion.objects.count(), "sub": "班级模型"},
            {
                "label": "待确认分层",
                "value": StratificationDecision.objects.filter(status=StratificationDecision.Status.PENDING).count(),
                "sub": "教师待处理",
            },
        ],
        "collection_status_rows": _status_rows(
            ImportBatch.Status.choices,
            dict(ImportBatch.objects.values_list("status").annotate(total=Count("id"))),
        ),
        "event_rows": event_rows,
        "school_rows": school_rows,
        "recent_collections": ImportBatch.objects.select_related("source_school", "uploaded_by")[:8],
    }
    return render(request, "ops/cross_school_analysis.html", context)


@login_required(login_url="login")
def cross_school_analysis_export(request):
    _require_super_admin(request)

    schools = School.objects.annotate(
        class_count=Count("classes", distinct=True),
        user_count=Count("users", distinct=True),
        student_count=Count("classes__students", distinct=True),
        collection_count=Count("import_batches", distinct=True),
    ).order_by("name", "code")
    collection_status_rows = _status_rows(
        ImportBatch.Status.choices,
        dict(ImportBatch.objects.values_list("status").annotate(total=Count("id"))),
    )
    event_total = LearningEvent.objects.count() or 1
    event_rows = []
    for row in LearningEvent.objects.values("event_type").annotate(count=Count("id")).order_by("-count"):
        event_rows.append(
            [
                dict(LearningEvent.EventType.choices).get(row["event_type"], row["event_type"]),
                row["event_type"],
                row["count"],
                f"{round(row['count'] * 100 / event_total)}%",
            ]
        )

    workbook = build_workbook(
        [
            {
                "title": "指标",
                "headers": ["指标", "数值", "说明"],
                "rows": [
                    ["学校覆盖", School.objects.count(), "已登记学校"],
                    ["采集批次", ImportBatch.objects.count(), "上传数据包"],
                    ["学生档案", StudentProfile.objects.count(), "跨校汇总"],
                    ["行为事件", LearningEvent.objects.count(), "学习过程数据"],
                    ["模型版本", ModelVersion.objects.count(), "班级模型"],
                    ["待确认分层", StratificationDecision.objects.filter(status=StratificationDecision.Status.PENDING).count(), "教师待处理"],
                ],
            },
            {
                "title": "学校对比",
                "headers": ["学校编号", "学校名称", "班级数", "账号数", "学生档案", "采集批次"],
                "rows": [[school.code, school.name, school.class_count, school.user_count, school.student_count, school.collection_count] for school in schools],
            },
            {
                "title": "采集状态",
                "headers": ["状态", "数量", "占比"],
                "rows": [[row["label"], row["count"], f'{row["percent"]}%'] for row in collection_status_rows],
            },
            {"title": "行为类型", "headers": ["类型", "编码", "数量", "占比"], "rows": event_rows},
        ]
    )
    _write_audit(request, "analysis.export", target_type="analysis")
    return workbook_response(workbook, _xlsx_filename("跨校分析"))


@login_required(login_url="login")
def system_health(request):
    _require_super_admin(request)

    failed_collections = ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).count()
    running_jobs = TrainingJob.objects.filter(status=TrainingJob.Status.RUNNING).count()
    failed_jobs = TrainingJob.objects.filter(status=TrainingJob.Status.FAILED).count()
    unresolved_risks = failed_collections + failed_jobs

    checks = [
        {
            "name": "数据库",
            "status": "正常",
            "level": "ok",
            "detail": "当前连接可用，页面查询正常。",
        },
        {
            "name": "数据采集",
            "status": "需关注" if failed_collections else "正常",
            "level": "warn" if failed_collections else "ok",
            "detail": f"失败采集批次 {failed_collections} 个。",
        },
        {
            "name": "模型训练",
            "status": "需关注" if failed_jobs else "正常",
            "level": "warn" if failed_jobs else "ok",
            "detail": f"运行中 {running_jobs} 个，失败 {failed_jobs} 个。",
        },
        {
            "name": "审计日志",
            "status": "正常",
            "level": "ok",
            "detail": f"已记录 {AuditLog.objects.count()} 条操作日志。",
        },
    ]

    context = {
        **_base_context("health", "系统健康"),
        "checks": checks,
        "metrics": [
            {"label": "学校", "value": School.objects.count(), "sub": "基础档案"},
            {"label": "采集失败", "value": failed_collections, "sub": "需处理"},
            {"label": "训练失败", "value": failed_jobs, "sub": "近端任务"},
            {"label": "运行任务", "value": running_jobs, "sub": "训练中"},
            {"label": "风险项", "value": unresolved_risks, "sub": "当前汇总"},
            {"label": "日志", "value": AuditLog.objects.count(), "sub": "审计记录"},
        ],
        "failed_collections": ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).select_related("source_school")[:8],
        "failed_jobs": TrainingJob.objects.filter(status=TrainingJob.Status.FAILED).select_related("class_group")[:8],
    }
    return render(request, "ops/system_health.html", context)


@login_required(login_url="login")
def system_health_export(request):
    _require_super_admin(request)

    failed_collections = ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).count()
    running_jobs = TrainingJob.objects.filter(status=TrainingJob.Status.RUNNING).count()
    failed_jobs = TrainingJob.objects.filter(status=TrainingJob.Status.FAILED).count()
    checks = [
        ["数据库", "正常", "当前连接可用，页面查询正常。"],
        ["数据采集", "需关注" if failed_collections else "正常", f"失败采集批次 {failed_collections} 个。"],
        ["模型训练", "需关注" if failed_jobs else "正常", f"运行中 {running_jobs} 个，失败 {failed_jobs} 个。"],
        ["审计日志", "正常", f"已记录 {AuditLog.objects.count()} 条操作日志。"],
    ]
    workbook = build_workbook(
        [
            {"title": "健康检查", "headers": ["检查项", "状态", "说明"], "rows": checks},
            {
                "title": "失败采集",
                "headers": ["批次", "学校编号", "学校", "状态", "上传时间", "日志"],
                "rows": [
                    [
                        item.batch_code,
                        item.source_school_code,
                        item.source_school.name if item.source_school else "",
                        item.get_status_display(),
                        item.uploaded_at,
                        item.log,
                    ]
                    for item in ImportBatch.objects.filter(status=ImportBatch.Status.FAILED).select_related("source_school")
                ],
            },
            {
                "title": "失败训练",
                "headers": ["任务ID", "学校", "班级", "状态", "创建时间", "开始时间", "结束时间", "日志"],
                "rows": [
                    [
                        job.pk,
                        job.class_group.school.name if job.class_group_id else "",
                        job.class_group.name if job.class_group_id else "",
                        job.get_status_display(),
                        job.created_at,
                        job.started_at,
                        job.finished_at,
                        job.logs,
                    ]
                    for job in TrainingJob.objects.filter(status=TrainingJob.Status.FAILED).select_related("class_group__school")
                ],
            },
        ]
    )
    _write_audit(request, "health.export", target_type="health")
    return workbook_response(workbook, _xlsx_filename("系统健康"))


@login_required(login_url="login")
def incident_list(request):
    _require_super_admin(request)

    incidents = _build_incidents()

    context = {
        **_base_context("incidents", "严重故障"),
        "incidents": incidents,
        "incident_count": len(incidents),
    }
    return render(request, "ops/incidents.html", context)


@login_required(login_url="login")
def incident_export(request):
    _require_super_admin(request)

    incidents = _build_incidents()
    _write_audit(request, "incident.export", target_type="incident", detail={"count": len(incidents)})
    return export_rows(
        _xlsx_filename("严重故障"),
        "严重故障",
        ["时间", "级别", "类型", "学校", "对象", "说明"],
        [[item["time"], item["level"], item["type"], item["school"], item["target"], item["detail"]] for item in incidents],
    )


@login_required(login_url="login")
def audit_log_list(request):
    _require_super_admin(request)

    query = request.GET.get("q", "").strip()
    logs = AuditLog.objects.select_related("actor", "school")
    if query:
        logs = logs.filter(
            Q(action__icontains=query)
            | Q(target_type__icontains=query)
            | Q(target_id__icontains=query)
            | Q(actor__username__icontains=query)
            | Q(actor__display_name__icontains=query)
            | Q(school__name__icontains=query)
            | Q(school__code__icontains=query)
        )

    context = {
        **_base_context("logs", "操作日志"),
        "logs": _paginate(request, logs, 14),
        "query": query,
    }
    return render(request, "ops/audit_logs.html", context)


@login_required(login_url="login")
def audit_log_export(request):
    _require_super_admin(request)

    query = request.GET.get("q", "").strip()
    logs = AuditLog.objects.select_related("actor", "school")
    if query:
        logs = logs.filter(
            Q(action__icontains=query)
            | Q(target_type__icontains=query)
            | Q(target_id__icontains=query)
            | Q(actor__username__icontains=query)
            | Q(actor__display_name__icontains=query)
            | Q(school__name__icontains=query)
            | Q(school__code__icontains=query)
        )
    rows = [
        [
            log.created_at,
            log.action,
            log.actor,
            log.school.name if log.school else "",
            log.target_type,
            log.target_id,
            log.ip_address,
            log.detail,
        ]
        for log in logs
    ]
    _write_audit(request, "audit_log.export", target_type="audit_log", detail={"count": len(rows)})
    return export_rows(
        _xlsx_filename("操作日志"),
        "操作日志",
        ["时间", "动作", "操作者", "学校", "对象类型", "对象ID", "IP", "详情"],
        rows,
    )
