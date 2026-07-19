from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from learning_analytics.models import EventSchemaDefinition
from learning_analytics.schemas.registry import (
    EVENT_SCHEMA_REGISTRY,
    EventSchemaSpec,
    get_event_schema_spec,
)


def _definition_values(spec: EventSchemaSpec) -> dict:
    return {
        "description": spec.description,
        "status": EventSchemaDefinition.Status.ACTIVE,
        "privacy_class": spec.privacy_class,
        "analysis_unit": spec.analysis_unit,
        "payload_schema": spec.payload_schema,
        "required_context_fields": list(spec.required_context_fields),
        "allowed_sources": list(spec.allowed_sources),
        "requires_target_student": spec.requires_target_student,
        "requires_opportunity": spec.requires_opportunity,
        "schema_hash": spec.schema_hash,
        "activated_at": timezone.now(),
    }


@transaction.atomic
def sync_event_schema_definitions(*, check_only: bool = False) -> dict[str, int]:
    result = {"created": 0, "unchanged": 0, "missing": 0, "mismatched": 0}
    for spec in EVENT_SCHEMA_REGISTRY.values():
        definition = EventSchemaDefinition.objects.filter(
            event_name=spec.event_name,
            schema_version=spec.schema_version,
        ).first()
        if definition is None:
            if check_only:
                result["missing"] += 1
                continue
            EventSchemaDefinition.objects.create(
                event_name=spec.event_name,
                schema_version=spec.schema_version,
                **_definition_values(spec),
            )
            result["created"] += 1
            continue
        if definition.schema_hash != spec.schema_hash:
            result["mismatched"] += 1
            continue
        result["unchanged"] += 1
    if result["mismatched"]:
        raise ValidationError(
            "数据库中的已登记模式与代码不一致；请提升 schema_version，禁止覆盖原版本。"
        )
    return result


def ensure_event_schema_definition(
    event_name: str, schema_version: str
) -> EventSchemaDefinition:
    spec = get_event_schema_spec(event_name, schema_version)
    definition = EventSchemaDefinition.objects.filter(
        event_name=event_name,
        schema_version=schema_version,
    ).first()
    if definition is None:
        definition = EventSchemaDefinition.objects.create(
            event_name=event_name,
            schema_version=schema_version,
            **_definition_values(spec),
        )
    if definition.schema_hash != spec.schema_hash:
        raise ValidationError("事件模式定义与代码注册表不一致。")
    if definition.status != EventSchemaDefinition.Status.ACTIVE:
        raise ValidationError("事件模式当前未启用。")
    return definition
