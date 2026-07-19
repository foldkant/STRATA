import uuid

from django.db import migrations, models


def populate_response_attempt_ids(apps, schema_editor):
    LearningWebPageResponse = apps.get_model("courses", "LearningWebPageResponse")
    for response in LearningWebPageResponse.objects.filter(
        analytics_attempt_id__isnull=True
    ).iterator():
        response.analytics_attempt_id = uuid.uuid4()
        response.save(update_fields=["analytics_attempt_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0017_neutralize_automatic_group_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningwebpageresponse",
            name="analytics_attempt_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(
            populate_response_attempt_ids,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="learningwebpageresponse",
            name="analytics_attempt_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
