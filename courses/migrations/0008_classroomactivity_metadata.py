from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0007_classroomsession_is_layered"),
    ]

    operations = [
        migrations.AddField(
            model_name="classroomactivity",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
