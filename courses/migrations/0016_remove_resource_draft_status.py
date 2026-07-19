from django.db import migrations, models
from django.utils import timezone


def publish_resource_drafts(apps, schema_editor):
    Resource = apps.get_model("courses", "Resource")
    Resource.objects.filter(publish_status="draft").update(
        publish_status="published",
        published_at=timezone.now(),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0015_alter_resource_public_id"),
    ]

    operations = [
        migrations.RunPython(publish_resource_drafts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="resource",
            name="publish_status",
            field=models.CharField(
                choices=[
                    ("published", "已发布"),
                    ("pending", "待审核"),
                    ("approved", "已通过"),
                    ("rejected", "已退回"),
                    ("archived", "已归档"),
                ],
                default="published",
                max_length=16,
            ),
        ),
    ]
