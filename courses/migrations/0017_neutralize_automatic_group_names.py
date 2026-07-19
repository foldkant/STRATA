import re

from django.db import migrations


ABILITY_GROUP_NAME = re.compile(r"^[ABC]层第\d+组$")


def neutralize_automatic_group_names(apps, schema_editor):
    classroom_group = apps.get_model("courses", "ClassroomGroup")
    for group in classroom_group.objects.all().iterator():
        old_name = group.name
        if not group.layer_hint and not ABILITY_GROUP_NAME.fullmatch(old_name):
            continue
        neutral_name = f"第{group.group_no}组"
        update_fields = []
        if old_name != neutral_name:
            group.name = neutral_name
            update_fields.append("name")
        suffix = f".{group.document_file_ext}" if group.document_file_ext else ""
        if group.document_original_name == f"{old_name}{suffix}":
            group.document_original_name = f"{neutral_name}{suffix}"
            update_fields.append("document_original_name")
        if update_fields:
            group.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0016_remove_resource_draft_status"),
    ]

    operations = [
        migrations.RunPython(neutralize_automatic_group_names, migrations.RunPython.noop),
    ]
