import hashlib
import json

from django.db import migrations


def repair_evaluation_schema_hash(apps, schema_editor):
    EventSchemaDefinition = apps.get_model(
        "learning_analytics", "EventSchemaDefinition"
    )
    definition = EventSchemaDefinition.objects.filter(
        event_name="evaluation.rating.submitted",
        schema_version="1.0",
    ).first()
    if definition is None:
        return

    semantic_definition = {
        "event_name": definition.event_name,
        "schema_version": definition.schema_version,
        "privacy_class": definition.privacy_class,
        "analysis_unit": definition.analysis_unit,
        "payload_schema": definition.payload_schema,
        "required_context_fields": definition.required_context_fields,
        "allowed_sources": definition.allowed_sources,
        "requires_target_student": definition.requires_target_student,
        "requires_opportunity": definition.requires_opportunity,
    }
    encoded = json.dumps(
        semantic_definition,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    schema_hash = hashlib.sha256(encoded).hexdigest()
    if definition.schema_hash != schema_hash:
        EventSchemaDefinition.objects.filter(pk=definition.pk).update(
            schema_hash=schema_hash
        )


class Migration(migrations.Migration):

    dependencies = [
        ("learning_analytics", "0019_lessonstepevaluationbinding_and_more"),
    ]

    operations = [
        migrations.RunPython(
            repair_evaluation_schema_hash,
            migrations.RunPython.noop,
        ),
    ]
