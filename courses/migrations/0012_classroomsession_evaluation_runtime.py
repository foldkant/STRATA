from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0011_course_evaluation_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="classroomsession",
            name="evaluation_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="classroomsession",
            name="evaluation_opened_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
