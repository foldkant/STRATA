from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone

from learning_analytics.models import TestDataObjectMarker


# P0 deliberately starts with non-personal root objects. Adding a model requires a
# reviewed code change; a command-line operator cannot widen this boundary.
SAFE_TEST_DATA_TARGET_MODELS = frozenset(
    {
        "courses.activity",
        "courses.classroomactivity",
        "courses.classroomsession",
        "courses.course",
        "courses.learningwebpage",
        "courses.lesson",
        "courses.resource",
        "courses.subject",
        "learning.diagnosticadministration",
        "learning.pretestpaper",
        "learning_analytics.evaluationplan",
        "learning_analytics.evaluationstandard",
        "learning_analytics.evaluationtrialrecord",
    }
)


@dataclass(frozen=True, slots=True)
class ExplicitTestDataTarget:
    app_label: str
    model_name: str
    object_pk: str
    object_label: str

    @property
    def model_label(self) -> str:
        return f"{self.app_label}.{self.model_name}"

    @property
    def canonical_key(self) -> str:
        return f"{self.model_label}:{self.object_pk}"

    def as_manifest_item(self) -> dict[str, str]:
        return {
            "model": self.model_label,
            "object_pk": self.object_pk,
            "object_label": self.object_label,
        }


def resolve_explicit_test_data_targets(
    raw_targets: list[str],
) -> list[ExplicitTestDataTarget]:
    if not raw_targets:
        raise ValueError("至少需要一个 --target。")

    resolved: list[ExplicitTestDataTarget] = []
    seen: set[str] = set()
    for raw_target in raw_targets:
        model_label, separator, raw_pk = str(raw_target or "").partition(":")
        if not separator or "." not in model_label or not raw_pk.strip():
            raise ValueError(
                f"目标格式错误：{raw_target!r}；应使用 app_label.ModelName:pk。"
            )
        app_label, model_name = model_label.split(".", 1)
        app_label = app_label.strip().lower()
        model_name = model_name.strip().lower()
        canonical_model = f"{app_label}.{model_name}"
        if canonical_model not in SAFE_TEST_DATA_TARGET_MODELS:
            allowed = "、".join(sorted(SAFE_TEST_DATA_TARGET_MODELS))
            raise ValueError(
                f"不允许把 {canonical_model} 登记为测试数据对象；P0 白名单为：{allowed}。"
            )

        model = apps.get_model(app_label, model_name)
        if model is None:
            raise ValueError(f"找不到模型：{canonical_model}。")
        object_pk = str(raw_pk).strip()
        try:
            instance = model._default_manager.get(pk=object_pk)
        except (ObjectDoesNotExist, ValueError, TypeError) as exc:
            raise ValueError(f"找不到对象：{canonical_model}:{object_pk}。") from exc

        target = ExplicitTestDataTarget(
            app_label=app_label,
            model_name=model_name,
            object_pk=str(instance.pk),
            object_label=str(instance)[:255],
        )
        if target.canonical_key in seen:
            raise ValueError(f"目标重复：{target.canonical_key}。")
        seen.add(target.canonical_key)
        resolved.append(target)

    return sorted(resolved, key=lambda item: item.canonical_key)


def build_test_data_manifest(
    targets: list[ExplicitTestDataTarget],
) -> tuple[list[dict[str, str]], str]:
    manifest = [target.as_manifest_item() for target in targets]
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return manifest, hashlib.sha256(payload).hexdigest()


def is_explicit_test_data_object(instance) -> bool:
    """Return whether an exact object has an immutable manual test marker."""

    if instance is None or instance.pk is None:
        return False
    return TestDataObjectMarker.objects.filter(
        app_label=instance._meta.app_label,
        model_name=instance._meta.model_name,
        object_pk=str(instance.pk),
        is_active=True,
    ).exists()


def explicit_test_data_object_pks(model) -> tuple[str, ...]:
    """Return active exact-object test markers for one model.

    This deliberately does not infer or cascade from a marked parent. Callers that
    operate on child evidence must resolve and check their governing root object.
    """

    return tuple(
        TestDataObjectMarker.objects.filter(
            app_label=model._meta.app_label,
            model_name=model._meta.model_name,
            is_active=True,
        )
        .order_by("object_pk")
        .values_list("object_pk", flat=True)
    )


def exclude_explicit_test_data_objects(queryset):
    """Exclude active exact-object markers from a queryset of the same model."""

    object_pks = explicit_test_data_object_pks(queryset.model)
    if not object_pks:
        return queryset
    return queryset.exclude(pk__in=object_pks)


def assert_no_explicit_test_data_objects(queryset, *, usage: str) -> None:
    """Block a formal operation if its exact root queryset contains test data."""

    object_pks = explicit_test_data_object_pks(queryset.model)
    conflicts = list(
        queryset.filter(pk__in=object_pks).values_list("pk", flat=True)[:20]
    )
    if conflicts:
        raise ValidationError(
            f"{usage} 包含已登记测试数据对象，必须先从正式范围排除："
            + "、".join(str(value) for value in conflicts)
        )


@transaction.atomic
def revoke_test_data_object_marker(
    *, marker: TestDataObjectMarker, actor, reason: str
) -> tuple[TestDataObjectMarker, bool]:
    """Revoke a mistaken marker while retaining its immutable audit row."""

    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ValidationError("撤销原因至少需要 10 个字符，以便后续审计。")
    if not (actor.is_superuser or actor.role == "super_admin"):
        raise ValidationError("只有超级管理员可以撤销测试数据对象标记。")

    locked = TestDataObjectMarker.objects.select_for_update().get(pk=marker.pk)
    if not locked.is_active:
        return locked, False
    revoked_at = timezone.now()
    TestDataObjectMarker.objects.filter(pk=locked.pk, is_active=True).update(
        is_active=False,
        revoked_at=revoked_at,
        revoked_by=actor,
        revocation_reason=reason,
    )
    locked.refresh_from_db()
    return locked, True
