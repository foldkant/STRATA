import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("aiops", "0002_teacheraiprovider"),
        ("courses", "0029_alter_classroomgroupcollaboration_storage_quota_mb"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuestionDraftGenerationJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("queued", "等待生成"), ("running", "正在生成"), ("succeeded", "草稿已生成"), ("failed", "生成未完成"), ("cancelled", "已取消")], db_index=True, default="queued", max_length=16)),
                ("request_payload", models.JSONField(default=dict)),
                ("result_payload", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("error_fields", models.JSONField(blank=True, default=dict)),
                ("provider", models.CharField(blank=True, max_length=32)),
                ("model", models.CharField(blank=True, max_length=64)),
                ("celery_task_id", models.CharField(blank=True, max_length=128)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="question_draft_generation_jobs", to="courses.subject")),
                ("teacher", models.ForeignKey(limit_choices_to={"role": "teacher"}, on_delete=django.db.models.deletion.CASCADE, related_name="question_draft_generation_jobs", to="accounts.user")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["teacher", "status", "created_at"], name="aiops_qd_teach_s_4d35d1_idx")],
            },
        ),
    ]
