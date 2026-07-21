from __future__ import annotations

import json
import os
import shutil
import socket
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser

from aiops.models import ModelVersion, TrainingJob
from courses.models import Course
from learning.models import LearningEvent, StratificationDecision
from learning.services.stratification_visibility import visible_published_decisions
from ops.collection import (
    CollectionPackageError,
    inspect_collection_package,
    sha256_file,
    validate_collection_upload,
)
from ops.models import AuditLog, ImportBatch
from ops.xlsx import build_workbook, export_rows, workbook_response
from school.models import ClassGroup, School, StudentProfile

from .permissions import IsSuperAdmin
from .responses import fail, ok, page_data
from .services import write_audit
from .view_utils import paginate


def _xlsx_filename(prefix: str) -> str:
    return f"{prefix}_{timezone.localtime():%Y%m%d%H%M%S}.xlsx"


def _choice_counts(queryset, field: str, choices) -> list[dict]:
    counts = dict(queryset.values_list(field).annotate(total=Count("id")))
    return [
        {"label": str(label), "value": value, "count": int(counts.get(value, 0))}
        for value, label in choices
    ]


def _day_series(queryset, date_field: str, *, days: int) -> list[dict]:
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
    return [
        {
            "label": (start + timedelta(days=offset)).strftime("%m-%d"),
            "count": int(by_day.get(start + timedelta(days=offset), 0)),
        }
        for offset in range(days)
    ]


def _import_row(item: ImportBatch, *, include_manifest: bool = False) -> dict:
    validation = item.manifest.get("_validation", {}) if isinstance(item.manifest, dict) else {}
    row = {
        "id": item.id,
        "batch_code": item.batch_code,
        "source_school_code": item.source_school_code,
        "source_school": (
            {"id": item.source_school_id, "name": item.source_school.name}
            if item.source_school_id
            else None
        ),
        "source_system_version": item.source_system_version,
        "status": item.status,
        "status_label": item.get_status_display(),
        "uploaded_by": (
            item.uploaded_by.display_name or item.uploaded_by.username
            if item.uploaded_by_id
            else ""
        ),
        "uploaded_at": item.uploaded_at,
        "imported_at": item.imported_at,
        "checksum": item.checksum,
        "log": item.log,
        "validation": validation,
        "package_name": Path(item.package_file.name).name if item.package_file else "",
    }
    if include_manifest:
        row["manifest"] = item.manifest
    return row


def _collection_queryset(request):
    rows = ImportBatch.objects.select_related("source_school", "uploaded_by")
    query = str(request.GET.get("q") or "").strip()
    status = str(request.GET.get("status") or "").strip()
    if query:
        rows = rows.filter(
            Q(batch_code__icontains=query)
            | Q(source_school_code__icontains=query)
            | Q(source_system_version__icontains=query)
            | Q(source_school__name__icontains=query)
        )
    if status in ImportBatch.Status.values:
        rows = rows.filter(status=status)
    return rows


@api_view(["GET", "POST"])
@permission_classes([IsSuperAdmin])
@parser_classes([MultiPartParser, FormParser])
def collection_batches(request):
    if request.method == "GET":
        rows = _collection_queryset(request)
        page = paginate(request, rows, per_page=20)
        page.object_list = [_import_row(item) for item in page.object_list]
        status_counts = _choice_counts(
            ImportBatch.objects.all(), "status", ImportBatch.Status.choices
        )
        return ok({**page_data(page), "status_counts": status_counts})

    uploaded = request.FILES.get("package_file")
    if uploaded is None:
        return fail(
            "请选择数据采集包。",
            errors={"package_file": ["请选择 ZIP 数据采集包。"]},
            status=400,
        )
    try:
        validate_collection_upload(uploaded)
    except CollectionPackageError as exc:
        return fail(str(exc), errors={"package_file": [str(exc)]}, status=400)

    checksum = sha256_file(uploaded)
    duplicate = ImportBatch.objects.filter(checksum=checksum).first()
    if duplicate:
        return fail(
            f"该采集包已上传，批次为 {duplicate.batch_code}。",
            errors={"package_file": ["请勿重复上传相同的数据采集包。"]},
            status=409,
        )

    now = timezone.now()
    batch = ImportBatch.objects.create(
        batch_code=f"IMP-{now:%Y%m%d%H%M%S%f}",
        package_file=uploaded,
        checksum=checksum,
        status=ImportBatch.Status.UPLOADED,
        uploaded_by=request.user,
    )
    with batch.package_file.open("rb") as package_file:
        result = inspect_collection_package(package_file)
    manifest = dict(result["manifest"])
    school_code = str(manifest.get("school_code") or "").strip()
    source_school = School.objects.filter(code=school_code).first() if school_code else None
    warnings = list(result["warnings"])
    if school_code and source_school is None:
        warnings.append("学校编号尚未匹配学校档案，可先登记学校后再核对。")
    manifest["_validation"] = {
        "errors": result["errors"],
        "warnings": warnings,
        "file_count": result["file_count"],
        "uncompressed_size": result["uncompressed_size"],
        "validated_at": now.isoformat(),
    }
    batch.manifest = manifest
    batch.source_school_code = school_code[:32]
    batch.source_system_version = str(manifest.get("system_version") or "")[:32]
    batch.source_school = source_school
    batch.status = (
        ImportBatch.Status.FAILED if result["errors"] else ImportBatch.Status.VALIDATED
    )
    batch.log = "；".join(result["errors"] or warnings)
    batch.save(
        update_fields=[
            "manifest",
            "source_school_code",
            "source_system_version",
            "source_school",
            "status",
            "log",
        ]
    )
    write_audit(
        request,
        "collection.upload",
        school=source_school,
        target_type="import_batch",
        target_id=batch.id,
        detail={
            "batch_code": batch.batch_code,
            "checksum": batch.checksum,
            "status": batch.status,
            "error_count": len(result["errors"]),
            "warning_count": len(warnings),
        },
    )
    message = "采集包已完成基础校验。" if not result["errors"] else "采集包已登记，但校验未通过。"
    return ok(_import_row(batch, include_manifest=True), message, status=201)


@api_view(["GET", "DELETE"])
@permission_classes([IsSuperAdmin])
def collection_batch_detail(request, pk: int):
    batch = (
        ImportBatch.objects.select_related("source_school", "uploaded_by")
        .filter(pk=pk)
        .first()
    )
    if batch is None:
        return fail("采集记录不存在。", status=404)
    if request.method == "GET":
        return ok(_import_row(batch, include_manifest=True))
    if batch.status == ImportBatch.Status.IMPORTED:
        return fail("已汇入的数据采集记录不能删除。", status=409)
    detail = {"batch_code": batch.batch_code, "status": batch.status}
    school = batch.source_school
    target_id = batch.id
    if batch.package_file:
        batch.package_file.delete(save=False)
    batch.delete()
    write_audit(
        request,
        "collection.delete",
        school=school,
        target_type="import_batch",
        target_id=target_id,
        detail=detail,
    )
    return ok({}, "采集记录已删除。")


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def collection_batches_export(request):
    rows = [
        [
            item.batch_code,
            item.source_school_code,
            item.source_school.name if item.source_school_id else "",
            item.source_system_version,
            item.get_status_display(),
            item.uploaded_by,
            item.uploaded_at,
            item.imported_at,
            item.checksum,
            item.log,
        ]
        for item in _collection_queryset(request)
    ]
    write_audit(
        request,
        "collection.export",
        target_type="import_batch",
        detail={"count": len(rows)},
    )
    return export_rows(
        _xlsx_filename("跨校数据采集"),
        "采集记录",
        ["批次", "学校编号", "学校", "版本", "状态", "上传人", "上传时间", "汇入时间", "校验值", "日志"],
        rows,
    )


def _analysis_data(*, include_test_data: bool) -> dict:
    schools = School.objects.all()
    if not include_test_data:
        schools = schools.filter(is_synthetic=False)
    schools = list(schools.order_by("name", "code"))
    school_ids = [school.id for school in schools]
    users = get_user_model().objects.filter(school_id__in=school_ids)
    students = StudentProfile.objects.filter(user__school_id__in=school_ids)
    events = LearningEvent.objects.filter(actor__school_id__in=school_ids)
    jobs = TrainingJob.objects.filter(class_group__school_id__in=school_ids)
    decisions = visible_published_decisions(
        StratificationDecision.objects.filter(class_group__school_id__in=school_ids)
    )
    imports = ImportBatch.objects.filter(
        Q(source_school_id__in=school_ids) | Q(source_school__isnull=True)
    )
    cutoff_7d = timezone.now() - timedelta(days=7)
    cutoff_30d = timezone.now() - timedelta(days=30)

    school_rows = []
    for school in schools:
        school_students = students.filter(user__school=school)
        student_count = school_students.count()
        school_events_30d = events.filter(actor__school=school, occurred_at__gte=cutoff_30d)
        active_students_7d = school_events_30d.filter(
            actor__role="student", occurred_at__gte=cutoff_7d
        ).values("actor_id").distinct().count()
        assigned_layers = school_students.exclude(current_layer__isnull=True).count()
        school_rows.append(
            {
                "id": school.id,
                "name": school.name,
                "code": school.code,
                "is_test_data": school.is_synthetic,
                "status": school.status,
                "status_label": school.get_status_display(),
                "teacher_count": users.filter(school=school, role="teacher").count(),
                "student_count": student_count,
                "class_count": ClassGroup.objects.filter(school=school).count(),
                "course_count": Course.objects.filter(teacher__school=school).count(),
                "events_30d": school_events_30d.count(),
                "events_per_student_30d": round(
                    school_events_30d.count() / student_count, 1
                ) if student_count else 0,
                "active_students_7d": active_students_7d,
                "active_rate_7d": round(active_students_7d * 100 / student_count, 1)
                if student_count
                else 0,
                "layer_coverage": round(assigned_layers * 100 / student_count, 1)
                if student_count
                else 0,
                "collection_count": ImportBatch.objects.filter(source_school=school).count(),
            }
        )

    layer_rows = [
        {
            "label": str(label),
            "value": value,
            "count": students.filter(current_layer=value).count(),
        }
        for value, label in StudentProfile.Layer.choices
    ]
    layer_rows.append(
        {
            "label": "未分层",
            "value": "unassigned",
            "count": students.filter(current_layer__isnull=True).count(),
        }
    )
    event_type_counts = dict(
        events.filter(occurred_at__gte=cutoff_30d)
        .values_list("event_type")
        .annotate(total=Count("id"))
    )
    event_types = [
        {
            "label": str(label),
            "value": value,
            "count": int(event_type_counts.get(value, 0)),
        }
        for value, label in LearningEvent.EventType.choices
        if event_type_counts.get(value, 0)
    ]
    return {
        "scope": {
            "include_test_data": include_test_data,
            "formal_schools": School.objects.filter(is_synthetic=False).count(),
            "test_schools": School.objects.filter(is_synthetic=True).count(),
        },
        "metrics": [
            {"label": "学校", "value": len(schools), "sub": "当前统计范围"},
            {"label": "学生", "value": students.count(), "sub": "已建档学生"},
            {"label": "班级", "value": ClassGroup.objects.filter(school_id__in=school_ids).count(), "sub": "当前范围"},
            {"label": "近 30 天行为", "value": events.filter(occurred_at__gte=cutoff_30d).count(), "sub": "学习过程记录"},
            {"label": "模型版本", "value": ModelVersion.objects.filter(class_group__school_id__in=school_ids).count(), "sub": "班级模型"},
            {
                "label": "教师待确认层级",
                "value": decisions.filter(
                    status=StratificationDecision.Status.PENDING,
                    decision_kind=StratificationDecision.DecisionKind.CONTENT_BAND,
                ).count(),
                "sub": "已发布的层级建议",
            },
        ],
        "charts": {
            "school_students": [{"label": row["name"], "count": row["student_count"]} for row in school_rows],
            "school_activity": [{"label": row["name"], "count": row["events_per_student_30d"]} for row in school_rows],
            "school_active_rate": [{"label": row["name"], "count": row["active_rate_7d"]} for row in school_rows],
            "school_layer_coverage": [{"label": row["name"], "count": row["layer_coverage"]} for row in school_rows],
            "layers": layer_rows,
            "event_types": event_types[:10],
            "event_series_30d": _day_series(events, "occurred_at", days=30),
            "collection_status": _choice_counts(imports, "status", ImportBatch.Status.choices),
            "training_status": _choice_counts(jobs, "status", TrainingJob.Status.choices),
        },
        "schools": school_rows,
        "recent_collections": [
            _import_row(item)
            for item in imports.select_related("source_school", "uploaded_by")[:8]
        ],
    }


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def cross_school_analysis(request):
    include_test_data = str(request.GET.get("include_test_data") or "") in {"1", "true"}
    return ok(_analysis_data(include_test_data=include_test_data))


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def cross_school_analysis_export(request):
    include_test_data = str(request.GET.get("include_test_data") or "") in {"1", "true"}
    data = _analysis_data(include_test_data=include_test_data)
    workbook = build_workbook(
        [
            {
                "title": "学校对比",
                "headers": ["学校编号", "学校名称", "数据性质", "教师", "学生", "班级", "课程", "近30天行为", "生均行为", "7天活跃率", "分层覆盖率", "采集批次"],
                "rows": [
                    [
                        row["code"], row["name"], "测试数据" if row["is_test_data"] else "正式数据",
                        row["teacher_count"], row["student_count"], row["class_count"], row["course_count"],
                        row["events_30d"], row["events_per_student_30d"], f'{row["active_rate_7d"]}%',
                        f'{row["layer_coverage"]}%', row["collection_count"],
                    ]
                    for row in data["schools"]
                ],
            },
            {
                "title": "当前分层",
                "headers": ["层级", "数量"],
                "rows": [[row["label"], row["count"]] for row in data["charts"]["layers"]],
            },
            {
                "title": "行为类型",
                "headers": ["类型", "数量"],
                "rows": [[row["label"], row["count"]] for row in data["charts"]["event_types"]],
            },
            {
                "title": "近30天趋势",
                "headers": ["日期", "行为事件"],
                "rows": [[row["label"], row["count"]] for row in data["charts"]["event_series_30d"]],
            },
        ]
    )
    write_audit(
        request,
        "analysis.export",
        target_type="analysis",
        detail={"include_test_data": include_test_data, "school_count": len(data["schools"])},
    )
    return workbook_response(workbook, _xlsx_filename("跨校分析"))


def _tcp_check(url: str, *, timeout: float = 0.7) -> tuple[bool, str]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "地址未配置"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} 可连接"
    except OSError as exc:
        return False, f"{host}:{port} 无法连接（{exc.__class__.__name__}）"


def _health_data() -> dict:
    now = timezone.now()
    checks = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks.append({"key": "database", "name": "数据库", "status": "正常", "level": "ok", "detail": f"{connection.vendor} 连接正常。"})
    except Exception as exc:
        checks.append({"key": "database", "name": "数据库", "status": "异常", "level": "failed", "detail": f"连接失败：{exc.__class__.__name__}"})

    try:
        executor = MigrationExecutor(connection)
        pending_migrations = len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    except Exception:
        pending_migrations = -1
    checks.append(
        {
            "key": "migrations",
            "name": "数据库更新",
            "status": "正常" if pending_migrations == 0 else "需处理",
            "level": "ok" if pending_migrations == 0 else "failed",
            "detail": "数据库结构已是最新版本。" if pending_migrations == 0 else f"有 {pending_migrations if pending_migrations >= 0 else '未知'} 项数据库更新未执行。",
        }
    )

    redis_ok, redis_detail = _tcp_check(settings.REDIS_URL)
    checks.append({"key": "realtime", "name": "实时与任务服务", "status": "正常" if redis_ok else "未连接", "level": "ok" if redis_ok else "warn", "detail": redis_detail})
    office_ok, office_detail = _tcp_check(settings.ONLYOFFICE_DOCUMENT_SERVER_URL)
    checks.append({"key": "onlyoffice", "name": "文档服务", "status": "正常" if office_ok else "未连接", "level": "ok" if office_ok else "warn", "detail": office_detail})

    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(media_root)
    disk_free_gb = round(disk.free / 1024 / 1024 / 1024, 1)
    disk_percent = round(disk.free * 100 / disk.total, 1) if disk.total else 0
    storage_ok = os.access(media_root, os.W_OK) and disk_percent >= 10
    checks.append({"key": "storage", "name": "文件存储", "status": "正常" if storage_ok else "需关注", "level": "ok" if storage_ok else "warn", "detail": f"可用 {disk_free_gb}GB（{disk_percent}%），目录{'可写' if os.access(media_root, os.W_OK) else '不可写'}。"})

    frontend_index = Path(settings.BASE_DIR) / "static" / "frontend" / "index.html"
    checks.append({"key": "frontend", "name": "前端资源", "status": "正常" if frontend_index.exists() else "缺失", "level": "ok" if frontend_index.exists() else "failed", "detail": "Vue 构建文件存在。" if frontend_index.exists() else "请重新执行前端构建。"})

    failed_collections = ImportBatch.objects.filter(status=ImportBatch.Status.FAILED)
    failed_jobs = TrainingJob.objects.filter(status=TrainingJob.Status.FAILED)
    stale_jobs = TrainingJob.objects.filter(status=TrainingJob.Status.RUNNING, started_at__lt=now - timedelta(hours=2))
    checks.append({"key": "collection", "name": "数据采集", "status": "正常" if not failed_collections.exists() else "需处理", "level": "ok" if not failed_collections.exists() else "failed", "detail": f"失败采集 {failed_collections.count()} 个。"})
    checks.append({"key": "training", "name": "模型训练", "status": "正常" if not failed_jobs.exists() and not stale_jobs.exists() else "需处理", "level": "ok" if not failed_jobs.exists() and not stale_jobs.exists() else "failed", "detail": f"失败 {failed_jobs.count()} 个，长时间运行 {stale_jobs.count()} 个。"})

    incidents = []
    for item in failed_collections.select_related("source_school")[:10]:
        incidents.append({"id": f"collection-{item.id}", "time": item.uploaded_at, "type": "数据采集失败", "target": item.batch_code, "school": item.source_school.name if item.source_school_id else item.source_school_code or "-", "detail": item.log or "采集包校验失败", "path": f"/super-admin/collection?q={item.batch_code}"})
    for job in failed_jobs.select_related("class_group__school")[:10]:
        incidents.append({"id": f"training-{job.id}", "time": job.created_at, "type": "模型训练失败", "target": f"训练任务 #{job.id}", "school": job.class_group.school.name, "detail": job.logs or "训练任务失败", "path": ""})
    incidents.sort(key=lambda item: item["time"], reverse=True)
    logs = [
        {
            "id": item.id,
            "created_at": item.created_at,
            "action": item.action,
            "actor": item.actor.display_name or item.actor.username if item.actor_id else "系统",
            "school": item.school.name if item.school_id else "-",
            "target": f"{item.target_type} {item.target_id}".strip() or "-",
            "ip_address": item.ip_address or "-",
            "detail": item.detail,
        }
        for item in AuditLog.objects.select_related("actor", "school")[:20]
    ]
    level_counts = {
        "ok": sum(1 for item in checks if item["level"] == "ok"),
        "warn": sum(1 for item in checks if item["level"] == "warn"),
        "failed": sum(1 for item in checks if item["level"] == "failed"),
    }
    return {
        "checked_at": now,
        "metrics": [
            {"label": "正常检查", "value": level_counts["ok"], "sub": "当前可用"},
            {"label": "提醒", "value": level_counts["warn"], "sub": "不阻断运行"},
            {"label": "异常", "value": level_counts["failed"], "sub": "需要处理"},
            {"label": "失败采集", "value": failed_collections.count(), "sub": "校验未通过"},
            {"label": "失败训练", "value": failed_jobs.count(), "sub": "训练任务"},
            {"label": "可用空间", "value": disk_free_gb, "sub": "GB"},
        ],
        "checks": checks,
        "incidents": incidents[:20],
        "audit_logs": logs,
    }


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def system_health(request):
    return ok(_health_data())


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def system_health_export(request):
    data = _health_data()
    workbook = build_workbook(
        [
            {
                "title": "健康检查",
                "headers": ["检查项", "状态", "级别", "说明"],
                "rows": [[item["name"], item["status"], item["level"], item["detail"]] for item in data["checks"]],
            },
            {
                "title": "严重故障",
                "headers": ["时间", "类型", "学校", "对象", "说明"],
                "rows": [[item["time"], item["type"], item["school"], item["target"], item["detail"]] for item in data["incidents"]],
            },
            {
                "title": "最近操作",
                "headers": ["时间", "动作", "操作者", "学校", "对象", "IP", "详情"],
                "rows": [[item["created_at"], item["action"], item["actor"], item["school"], item["target"], item["ip_address"], json.dumps(item["detail"], ensure_ascii=False)] for item in data["audit_logs"]],
            },
        ]
    )
    write_audit(request, "health.export", target_type="health")
    return workbook_response(workbook, _xlsx_filename("系统健康"))
