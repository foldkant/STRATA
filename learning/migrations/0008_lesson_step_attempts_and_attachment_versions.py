import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def populate_attachment_submission_ids(apps, schema_editor):
    StudentWorkAttachment = apps.get_model("learning", "StudentWorkAttachment")
    for attachment in StudentWorkAttachment.objects.filter(
        submission_id__isnull=True
    ).iterator():
        attachment.submission_id = uuid.uuid4()
        attachment.save(update_fields=["submission_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0017_neutralize_automatic_group_names"),
        ("learning", "0007_testattempt_analytics_attempt_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="studentworkattachment",
            name="uniq_student_work_per_step_question",
        ),
        migrations.AddField(
            model_name="studentworkattachment",
            name="submission_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="studentworkattachment",
            name="upload_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="studentworkattachment",
            name="supersedes",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="revisions",
                to="learning.studentworkattachment",
            ),
        ),
        migrations.RunPython(
            populate_attachment_submission_ids,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="studentworkattachment",
            name="submission_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddConstraint(
            model_name="studentworkattachment",
            constraint=models.UniqueConstraint(
                fields=("student", "lesson_step", "question_id", "upload_version"),
                name="uniq_student_work_version",
            ),
        ),
        migrations.CreateModel(
            name="LessonStepAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "attempt_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("attempt_no", models.PositiveIntegerField()),
                ("answer", models.JSONField(blank=True, default=dict)),
                ("free_text", models.TextField(blank=True)),
                ("answered_count", models.PositiveIntegerField(default=0)),
                ("question_count", models.PositiveIntegerField(default=0)),
                ("auto_score", models.FloatField(default=0)),
                ("auto_score_max", models.FloatField(default=0)),
                ("submitted_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "class_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lesson_step_attempts",
                        to="school.classgroup",
                    ),
                ),
                (
                    "classroom_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lesson_step_attempts",
                        to="courses.classroomsession",
                    ),
                ),
                (
                    "course",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lesson_step_attempts",
                        to="courses.course",
                    ),
                ),
                (
                    "lesson",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lesson_step_attempts",
                        to="courses.lesson",
                    ),
                ),
                (
                    "lesson_step",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attempts",
                        to="courses.lessonstep",
                    ),
                ),
                (
                    "school",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lesson_step_attempts",
                        to="school.school",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lesson_step_attempts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-submitted_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=[
                            "classroom_session",
                            "lesson_step",
                            "student",
                            "submitted_at",
                        ],
                        name="learning_le_classro_ebacbd_idx",
                    ),
                    models.Index(
                        fields=["student", "submitted_at"],
                        name="learning_le_student_918619_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "classroom_session",
                            "lesson_step",
                            "student",
                            "attempt_no",
                        ),
                        name="uniq_lesson_step_attempt_version",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="LessonStepAttemptAnswer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("question_id", models.CharField(max_length=64)),
                ("question_version", models.CharField(max_length=64)),
                (
                    "question_type",
                    models.CharField(
                        choices=[
                            ("single", "单选"),
                            ("multiple", "多选"),
                            ("judge", "判断"),
                            ("blank", "填空"),
                            ("text", "简答"),
                            ("file", "附件提交"),
                        ],
                        max_length=16,
                    ),
                ),
                ("response", models.JSONField(blank=True, default=dict)),
                ("is_answered", models.BooleanField(default=False)),
                ("auto_score", models.FloatField(blank=True, null=True)),
                ("score_max", models.FloatField()),
                ("is_correct", models.BooleanField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "attachment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attempt_answers",
                        to="learning.studentworkattachment",
                    ),
                ),
                (
                    "attempt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="answer_rows",
                        to="learning.lessonstepattempt",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
                "indexes": [
                    models.Index(
                        fields=["attempt", "question_id"],
                        name="learning_le_attempt_3f9a70_idx",
                    ),
                    models.Index(
                        fields=["question_version"],
                        name="learning_le_questio_7d1f97_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("attempt", "question_id"),
                        name="uniq_lesson_step_attempt_question",
                    ),
                ],
            },
        ),
    ]
