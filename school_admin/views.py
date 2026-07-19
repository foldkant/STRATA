from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import ProtectedError
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from aiops.models import ModelVersion, TrainingJob
from courses.models import Course
from learning.models import LearningEvent, StratificationDecision
from ops.models import AuditLog, ExportBatch
from ops.forms import PERSON_NAME_PATTERN, PHONE_PATTERN, TEACHING_PASSWORD_PATTERN, USERNAME_PATTERN, _matches
from ops.xlsx import build_workbook, export_rows, normalize_text, read_table_rows, template_response, workbook_response
from school.models import ClassGroup, StudentProfile

from .forms import TeacherCreateForm, TeacherImportForm, TeacherPasswordResetForm, TeacherUpdateForm

TEACHER_USERNAME_HELP_TEXT = "5-32 位，以字母开头，可包含字母、数字和下划线；例如 teacher1，下划线可用但不是必需"


def _require_school_admin(request):
    user = request.user
    if not user.is_authenticated:
        raise PermissionDenied
    if user.is_superuser or user.role == "super_admin":
        raise PermissionDenied
    if user.role != "school_admin":
        raise PermissionDenied
    if not user.school_id:
        raise PermissionDenied


def _school(request):
    return request.user.school


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _write_audit(request, action, *, target_type="", target_id="", detail=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        school=_school(request),
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else "",
        ip_address=_client_ip(request),
        detail=detail or {},
    )


def _base_context(request, active_page: str, page_title: str) -> dict:
    return {
        "active_page": active_page,
        "page_title": page_title,
        "school": _school(request),
        "nav_items": [
            ("dashboard", "管理首页", reverse("school_admin_dashboard")),
            ("teachers", "教师管理", reverse("school_admin_teacher_list")),
            ("students", "学生管理", reverse("school_admin_student_list")),
            ("classes", "班级管理", reverse("school_admin_class_list")),
            ("teaching", "任课关系", reverse("school_admin_teaching_list")),
            ("permissions", "教师权限", reverse("school_admin_teacher_permission_list")),
            ("question_bank", "题库中心", reverse("school_admin_placeholder", args=["question-bank"])),
            ("evaluations", "评价管理", reverse("school_admin_placeholder", args=["evaluations"])),
            ("models", "分层分析", reverse("school_admin_model_overview")),
            ("exports", "数据导出", reverse("school_admin_export_center")),
            ("settings", "系统设置", reverse("school_admin_placeholder", args=["settings"])),
            ("logs", "操作日志", reverse("school_admin_log_list")),
        ],
    }


def _xlsx_filename(prefix: str) -> str:
    return f"{prefix}_{timezone.localtime():%Y%m%d%H%M%S}.xlsx"


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


def _school_users(request):
    User = get_user_model()
    return User.objects.filter(school=_school(request))


def _teacher_queryset(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    teachers = _school_users(request).filter(role="teacher").order_by("username")
    if query:
        teachers = teachers.filter(Q(username__icontains=query) | Q(display_name__icontains=query) | Q(phone__icontains=query))
    if status == "active":
        teachers = teachers.filter(is_active=True)
    elif status == "disabled":
        teachers = teachers.filter(is_active=False)
    return teachers


def _school_classes(request):
    return ClassGroup.objects.filter(school=_school(request))


def _school_learning_events(request):
    return LearningEvent.objects.filter(class_group__school=_school(request))


def _school_courses(request):
    return Course.objects.filter(teacher__school=_school(request))


def _dashboard_data(request):
    now = timezone.now()
    today = timezone.localdate()
    school = _school(request)
    users = _school_users(request)
    classes = _school_classes(request)
    events = _school_learning_events(request)
    training_jobs = TrainingJob.objects.filter(class_group__school=school)
    decisions = StratificationDecision.objects.filter(class_group__school=school)

    inactive_accounts = users.filter(is_active=False).count()
    first_login_accounts = users.filter(is_first_login=True, is_active=True).count()
    failed_training = training_jobs.filter(status=TrainingJob.Status.FAILED).count()
    running_training = training_jobs.filter(status=TrainingJob.Status.RUNNING).count()
    pending_decisions = decisions.filter(status=StratificationDecision.Status.PENDING).count()
    failed_exports = ExportBatch.objects.filter(school=school, status=ExportBatch.Status.FAILED).count()

    return {
        "now": now,
        "metrics": [
            {"label": "教师", "value": users.filter(role="teacher").count(), "sub": "本校教师"},
            {"label": "学生", "value": StudentProfile.objects.filter(class_group__school=school).count(), "sub": "已建档学生"},
            {"label": "班级", "value": classes.count(), "sub": "本校班级"},
            {"label": "课程", "value": _school_courses(request).count(), "sub": "本校教师课程"},
            {"label": "今日行为", "value": events.filter(occurred_at__date=today).count(), "sub": "学习过程事件"},
            {
                "label": "待处理",
                "value": inactive_accounts + first_login_accounts + failed_training + pending_decisions + failed_exports,
                "sub": "账号、训练和导出",
            },
        ],
        "login_series": _day_series(events.filter(event_type=LearningEvent.EventType.LOGIN), "occurred_at", days=7),
        "event_series": _day_series(events, "occurred_at", days=7),
        "status_rows": [
            {"label": "停用账号", "count": inactive_accounts, "level": "warn" if inactive_accounts else "ok"},
            {"label": "首次登录未改密", "count": first_login_accounts, "level": "warn" if first_login_accounts else "ok"},
            {"label": "训练失败", "count": failed_training, "level": "failed" if failed_training else "ok"},
            {"label": "训练中", "count": running_training, "level": "warn" if running_training else "ok"},
            {"label": "待确认分层", "count": pending_decisions, "level": "warn" if pending_decisions else "ok"},
            {"label": "导出失败", "count": failed_exports, "level": "failed" if failed_exports else "ok"},
        ],
        "recent_logs": AuditLog.objects.filter(school=school).select_related("actor")[:8],
        "recent_exports": ExportBatch.objects.filter(school=school).select_related("exported_by")[:8],
        "training_jobs": training_jobs.select_related("class_group")[:8],
    }


TEACHER_IMPORT_HEADERS = ["登录账号", "姓名", "联系电话", "初始密码", "状态"]


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


def _validate_teacher_import(request, rows: list[dict]) -> tuple[list[dict], list[str]]:
    User = get_user_model()
    errors = []
    records = []
    seen_usernames = set()

    for row in rows:
        username = normalize_text(row.get("登录账号"))
        display_name = normalize_text(row.get("姓名"))
        phone = normalize_text(row.get("联系电话"))
        password = normalize_text(row.get("初始密码"))
        active = _active_value(row.get("状态"), default=True)
        existing_user = User.objects.filter(username=username).first() if username else None

        if not _matches(USERNAME_PATTERN, username):
            errors.append(_row_error(row, f"登录账号需为 {TEACHER_USERNAME_HELP_TEXT}。"))
        if username in seen_usernames:
            errors.append(_row_error(row, f"登录账号 {username} 在文件中重复。"))
        seen_usernames.add(username)

        if not _matches(PERSON_NAME_PATTERN, display_name):
            errors.append(_row_error(row, "姓名需为 2-24 位中文或字母。"))
        if phone and not _matches(PHONE_PATTERN, phone):
            errors.append(_row_error(row, "联系电话格式不正确。"))
        if active is None:
            errors.append(_row_error(row, "状态只能填写启用或停用。"))
        if existing_user and existing_user.role != "teacher":
            errors.append(_row_error(row, f"登录账号 {username} 已被其他角色占用。"))
        if existing_user and existing_user.school_id != request.user.school_id:
            errors.append(_row_error(row, f"登录账号 {username} 不属于本校，不能更新。"))
        if not existing_user and not password:
            errors.append(_row_error(row, "新增教师必须填写初始密码。"))
        if password and not _matches(TEACHING_PASSWORD_PATTERN, password):
            errors.append(_row_error(row, "教师初始密码需为 6-32 位，可使用字母、数字和常用符号。"))

        records.append(
            {
                "username": username,
                "display_name": display_name,
                "phone": phone,
                "password": password,
                "is_active": active if active is not None else True,
                "existing_user": existing_user,
            }
        )

    return records, errors


@login_required(login_url="login")
def dashboard(request):
    _require_school_admin(request)
    context = {
        **_base_context(request, "dashboard", "管理首页"),
        **_dashboard_data(request),
    }
    return render(request, "school_admin/dashboard.html", context)


@login_required(login_url="login")
def dashboard_export(request):
    _require_school_admin(request)
    data = _dashboard_data(request)
    workbook = build_workbook(
        [
            {
                "title": "指标",
                "headers": ["指标", "数值", "说明"],
                "rows": [[item["label"], item["value"], item["sub"]] for item in data["metrics"]],
            },
            {
                "title": "登录趋势",
                "headers": ["日期", "数量"],
                "rows": [[item["label"], item["count"]] for item in data["login_series"]],
            },
            {
                "title": "行为趋势",
                "headers": ["日期", "数量"],
                "rows": [[item["label"], item["count"]] for item in data["event_series"]],
            },
            {
                "title": "待处理",
                "headers": ["事项", "数量", "状态"],
                "rows": [[row["label"], row["count"], row["level"]] for row in data["status_rows"]],
            },
        ]
    )
    return workbook_response(workbook, _xlsx_filename(f"{_school(request).code}_管理首页"))


@login_required(login_url="login")
def teacher_list(request):
    _require_school_admin(request)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    teachers = _teacher_queryset(request)
    context = {
        **_base_context(request, "teachers", "教师管理"),
        "teachers": teachers,
        "query": query,
        "status": status,
    }
    return render(request, "school_admin/teachers.html", context)


@login_required(login_url="login")
def teacher_export(request):
    _require_school_admin(request)
    rows = [
        [
            teacher.username,
            teacher.display_name,
            teacher.phone,
            "启用" if teacher.is_active else "停用",
            "是" if teacher.is_first_login else "否",
            teacher.last_login,
            teacher.date_joined,
            teacher.teaching_classes.filter(school=_school(request)).count(),
        ]
        for teacher in _teacher_queryset(request)
    ]
    _write_audit(request, "teacher.export", target_type="user", detail={"count": len(rows)})
    return export_rows(
        _xlsx_filename(f"{_school(request).code}_教师管理"),
        "教师管理",
        ["登录账号", "姓名", "联系电话", "状态", "首次登录", "最近登录", "创建时间", "任课班级数"],
        rows,
    )


@login_required(login_url="login")
def teacher_template(request):
    _require_school_admin(request)

    return template_response(
        "教师批量导入模板.xlsx",
        "教师导入模板",
        TEACHER_IMPORT_HEADERS,
        [["teacher1", "张老师", "13800138000", "123456", "启用"]],
        instructions=[
            f"登录账号必填且唯一，{TEACHER_USERNAME_HELP_TEXT}。",
            "新增教师必须填写初始密码；教师和学生允许使用 123456 这类课堂简易密码。",
            "更新已有教师时，初始密码留空则不修改原密码；状态可填：启用、停用。",
        ],
        dropdowns={"状态": ["启用", "停用"]},
    )


@login_required(login_url="login")
def teacher_import(request):
    _require_school_admin(request)

    User = get_user_model()
    form = TeacherImportForm(request.POST or None, request.FILES or None)
    errors = []
    if request.method == "POST" and form.is_valid():
        try:
            rows = read_table_rows(
                form.cleaned_data["file"],
                required_headers=["登录账号", "姓名"],
                all_headers=TEACHER_IMPORT_HEADERS,
            )
            if not rows:
                errors.append("Excel 文件没有可导入的数据行。")
            records, errors = _validate_teacher_import(request, rows)
            if not errors:
                created_count = 0
                updated_count = 0
                with transaction.atomic():
                    for record in records:
                        existing_user = record["existing_user"]
                        if existing_user:
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
                                role="teacher",
                                school=_school(request),
                                is_active=record["is_active"],
                                is_staff=False,
                                is_first_login=True,
                            )
                            created_count += 1
                    _write_audit(
                        request,
                        "teacher.bulk_import",
                        target_type="user",
                        detail={"created": created_count, "updated": updated_count},
                    )
                messages.success(request, f"教师批量导入完成：新增 {created_count} 个，更新 {updated_count} 个。")
                return redirect("school_admin_teacher_list")
        except ValueError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"导入失败：{exc}")

    context = {
        **_base_context(request, "teachers", "批量导入教师"),
        "form": form,
        "errors": errors,
        "template_url": reverse("school_admin_teacher_template"),
        "back_url": reverse("school_admin_teacher_list"),
        "page_hint": "请先下载模板。新增教师必须填写初始密码，更新已有教师时密码可留空。",
    }
    return render(request, "school_admin/xlsx_import.html", context)


@login_required(login_url="login")
def teacher_create(request):
    _require_school_admin(request)

    User = get_user_model()
    form = TeacherCreateForm(request.POST or None, school=_school(request))
    if request.method == "POST" and form.is_valid():
        teacher = User.objects.create_user(
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
            display_name=form.cleaned_data["display_name"],
            phone=form.cleaned_data["phone"],
            role="teacher",
            school=_school(request),
            is_active=form.cleaned_data["is_active"],
            is_staff=False,
            is_first_login=True,
        )
        _write_audit(request, "teacher.create", target_type="user", target_id=teacher.id, detail={"username": teacher.username})
        messages.success(request, "教师已创建。")
        return redirect("school_admin_teacher_list")

    context = {
        **_base_context(request, "teachers", "新增教师"),
        "form": form,
        "form_title": "新增教师",
        "submit_label": "保存教师",
        "back_url": reverse("school_admin_teacher_list"),
    }
    return render(request, "school_admin/teacher_form.html", context)


@login_required(login_url="login")
def teacher_update(request, pk):
    _require_school_admin(request)

    teacher = get_object_or_404(_school_users(request), pk=pk, role="teacher")
    form = TeacherUpdateForm(request.POST or None, teacher=teacher, school=_school(request))
    if request.method == "POST" and form.is_valid():
        teacher.username = form.cleaned_data["username"]
        teacher.display_name = form.cleaned_data["display_name"]
        teacher.phone = form.cleaned_data["phone"]
        teacher.is_active = form.cleaned_data["is_active"]
        teacher.save()
        _write_audit(request, "teacher.update", target_type="user", target_id=teacher.id, detail={"username": teacher.username})
        messages.success(request, "教师信息已更新。")
        return redirect("school_admin_teacher_list")

    context = {
        **_base_context(request, "teachers", "编辑教师"),
        "form": form,
        "teacher": teacher,
        "form_title": "编辑教师",
        "submit_label": "保存修改",
        "back_url": reverse("school_admin_teacher_list"),
    }
    return render(request, "school_admin/teacher_form.html", context)


@login_required(login_url="login")
def teacher_toggle_active(request, pk):
    _require_school_admin(request)

    teacher = get_object_or_404(_school_users(request), pk=pk, role="teacher")
    if request.method == "POST":
        teacher.is_active = not teacher.is_active
        teacher.save(update_fields=["is_active"])
        _write_audit(
            request,
            "teacher.enable" if teacher.is_active else "teacher.disable",
            target_type="user",
            target_id=teacher.id,
            detail={"username": teacher.username},
        )
        messages.success(request, "教师状态已更新。")
        return redirect("school_admin_teacher_list")

    context = {
        **_base_context(request, "teachers", "更新教师状态"),
        "teacher": teacher,
        "action_label": "停用" if teacher.is_active else "启用",
        "back_url": reverse("school_admin_teacher_list"),
    }
    return render(request, "school_admin/teacher_toggle_confirm.html", context)


@login_required(login_url="login")
def teacher_delete(request, pk):
    _require_school_admin(request)

    teacher = get_object_or_404(_school_users(request), pk=pk, role="teacher")
    if teacher.is_active:
        messages.error(request, "该教师账号仍处于启用状态。请先停用账号，再执行删除。")
        return redirect("school_admin_teacher_update", pk=teacher.pk)

    if request.method == "POST":
        detail = {
            "username": teacher.username,
            "display_name": teacher.display_name,
            "role": teacher.role,
            "school": _school(request).name,
        }
        target_id = teacher.id
        try:
            teacher.delete()
        except ProtectedError:
            messages.error(request, "该教师账号已有课程、资源或其他业务数据关联，不能物理删除；请保持停用状态。")
            return redirect("school_admin_teacher_list")
        _write_audit(request, "teacher.delete", target_type="user", target_id=target_id, detail=detail)
        messages.success(request, "教师账号已删除。")
        return redirect("school_admin_teacher_list")

    context = {
        **_base_context(request, "teachers", "删除教师"),
        "account": teacher,
        "account_label": "教师",
        "back_url": reverse("school_admin_teacher_list"),
    }
    return render(request, "school_admin/account_confirm_delete.html", context)


@login_required(login_url="login")
def teacher_reset_password(request, pk):
    _require_school_admin(request)

    teacher = get_object_or_404(_school_users(request), pk=pk, role="teacher")
    form = TeacherPasswordResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        teacher.set_password(form.cleaned_data["password"])
        teacher.is_first_login = True
        teacher.save(update_fields=["password", "is_first_login"])
        _write_audit(request, "teacher.reset_password", target_type="user", target_id=teacher.id, detail={"username": teacher.username})
        messages.success(request, "教师密码已重置。")
        return redirect("school_admin_teacher_list")

    context = {
        **_base_context(request, "teachers", "重置教师密码"),
        "form": form,
        "teacher": teacher,
        "form_title": "重置教师密码",
        "submit_label": "保存新密码",
        "back_url": reverse("school_admin_teacher_list"),
    }
    return render(request, "school_admin/teacher_form.html", context)


@login_required(login_url="login")
def student_list(request):
    _require_school_admin(request)
    query = request.GET.get("q", "").strip()
    class_id = request.GET.get("class", "").strip()
    students = StudentProfile.objects.filter(class_group__school=_school(request)).select_related("user", "class_group")
    if query:
        students = students.filter(Q(user__username__icontains=query) | Q(user__display_name__icontains=query) | Q(student_no__icontains=query))
    if class_id:
        students = students.filter(class_group_id=class_id)
    context = {
        **_base_context(request, "students", "学生管理"),
        "students": students.order_by("class_group__grade", "class_group__name", "student_no"),
        "classes": _school_classes(request).order_by("grade", "name"),
        "query": query,
        "class_id": class_id,
    }
    return render(request, "school_admin/students.html", context)


@login_required(login_url="login")
def class_list(request):
    _require_school_admin(request)
    classes = (
        _school_classes(request)
        .annotate(student_count=Count("students", distinct=True), teacher_count=Count("teachers", distinct=True))
        .order_by("grade", "name")
    )
    context = {
        **_base_context(request, "classes", "班级管理"),
        "classes": classes,
    }
    return render(request, "school_admin/classes.html", context)


@login_required(login_url="login")
def teaching_list(request):
    _require_school_admin(request)
    classes = _school_classes(request).prefetch_related("teachers").order_by("grade", "name")
    context = {
        **_base_context(request, "teaching", "任课关系"),
        "classes": classes,
    }
    return render(request, "school_admin/teaching.html", context)


@login_required(login_url="login")
def teacher_permission_list(request):
    _require_school_admin(request)
    teachers = _school_users(request).filter(role="teacher").order_by("username")
    context = {
        **_base_context(request, "permissions", "教师权限"),
        "teachers": teachers,
    }
    return render(request, "school_admin/teacher_permissions.html", context)


@login_required(login_url="login")
def model_overview(request):
    _require_school_admin(request)
    class_ids = list(_school_classes(request).values_list("id", flat=True))
    context = {
        **_base_context(request, "models", "模型与训练"),
        "model_versions": ModelVersion.objects.filter(class_group_id__in=class_ids).select_related("class_group")[:20],
        "training_jobs": TrainingJob.objects.filter(class_group_id__in=class_ids).select_related("class_group")[:20],
    }
    return render(request, "school_admin/model_overview.html", context)


@login_required(login_url="login")
def export_center(request):
    _require_school_admin(request)
    context = {
        **_base_context(request, "exports", "数据导出"),
        "exports": ExportBatch.objects.filter(school=_school(request)).select_related("exported_by")[:20],
    }
    return render(request, "school_admin/export_center.html", context)


@login_required(login_url="login")
def log_list(request):
    _require_school_admin(request)
    logs = AuditLog.objects.filter(school=_school(request)).select_related("actor")
    context = {
        **_base_context(request, "logs", "操作日志"),
        "logs": logs[:50],
    }
    return render(request, "school_admin/logs.html", context)


@login_required(login_url="login")
def placeholder(request, slug):
    _require_school_admin(request)
    labels = {
        "question-bank": ("question_bank", "题库中心", "公共题库、知识点、审核和使用记录将在第二阶段接入。"),
        "evaluations": ("evaluations", "评价管理", "评价方案和评价标准已迁移到 Vue 学校管理员页面。"),
        "settings": ("settings", "系统设置", "本校展示、学年学期、密码策略和上传限制将在第二阶段接入。"),
    }
    active_page, title, hint = labels.get(slug, ("dashboard", "模块建设中", "该模块尚未开放。"))
    context = {
        **_base_context(request, active_page, title),
        "hint": hint,
    }
    return render(request, "school_admin/placeholder.html", context)
