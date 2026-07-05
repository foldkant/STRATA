from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0005_lessonstep_question_items"),
    ]

    operations = [
        migrations.AddField(
            model_name="classroomsession",
            name="current_step",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="courses.lessonstep",
            ),
        ),
        migrations.AddField(
            model_name="classroomsession",
            name="current_step_status",
            field=models.CharField(
                choices=[
                    ("idle", "未投放"),
                    ("open", "已投放"),
                    ("locked", "已锁定"),
                    ("closed", "已关闭"),
                ],
                default="idle",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="classroomsession",
            name="submission_locked",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="classroomsession",
            name="current_step_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="classroomsession",
            name="current_step_closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
