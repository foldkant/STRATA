from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0006_classroom_session_step_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="classroomsession",
            name="is_layered",
            field=models.BooleanField(default=False),
        ),
    ]
