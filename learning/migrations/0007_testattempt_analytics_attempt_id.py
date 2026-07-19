import uuid

from django.db import migrations, models


def populate_attempt_ids(apps, schema_editor):
    TestAttempt = apps.get_model("learning", "TestAttempt")
    for attempt in TestAttempt.objects.filter(
        analytics_attempt_id__isnull=True
    ).iterator():
        attempt.analytics_attempt_id = uuid.uuid4()
        attempt.save(update_fields=["analytics_attempt_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0006_testassessment_randomization"),
    ]

    operations = [
        migrations.AddField(
            model_name="testattempt",
            name="analytics_attempt_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_attempt_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="testattempt",
            name="analytics_attempt_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
