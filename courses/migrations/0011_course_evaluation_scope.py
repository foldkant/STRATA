# Generated manually on 2026-07-10

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def forwards(apps, schema_editor):
    ClassroomEvaluationConfig = apps.get_model("courses", "ClassroomEvaluationConfig")
    ClassroomEvaluationSubmission = apps.get_model("courses", "ClassroomEvaluationSubmission")
    ClassroomSession = apps.get_model("courses", "ClassroomSession")

    session_scope = {
        session_id: (course_id, class_group_id)
        for session_id, course_id, class_group_id in ClassroomSession.objects.values_list(
            "id",
            "course_id",
            "class_group_id",
        )
    }

    seen_course_ids = set()
    for config in ClassroomEvaluationConfig.objects.order_by("-updated_at", "-id"):
        course_id, _class_group_id = session_scope.get(config.session_id, (None, None))
        if not course_id or course_id in seen_course_ids:
            config.delete()
            continue
        config.course_id = course_id
        config.save(update_fields=["course"])
        seen_course_ids.add(course_id)

    for submission in ClassroomEvaluationSubmission.objects.all().iterator():
        course_id, class_group_id = session_scope.get(submission.session_id, (None, None))
        if not course_id:
            submission.delete()
            continue
        submission.course_id = course_id
        submission.class_group_id = class_group_id
        submission.save(update_fields=["course", "class_group"])


class Migration(migrations.Migration):

    dependencies = [
        ("school", "0008_simplify_teaching_assignment"),
        ("courses", "0010_classroomevaluationconfig_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="classroomevaluationsubmission",
            name="uniq_classroom_evaluation_submission",
        ),
        migrations.AddField(
            model_name="classroomevaluationconfig",
            name="course",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="evaluation_config",
                to="courses.course",
            ),
        ),
        migrations.AddField(
            model_name="classroomevaluationsubmission",
            name="class_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="evaluation_submissions",
                to="school.classgroup",
            ),
        ),
        migrations.AddField(
            model_name="classroomevaluationsubmission",
            name="course",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="evaluation_submissions",
                to="courses.course",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="classroomevaluationconfig",
            name="course",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="evaluation_config",
                to="courses.course",
            ),
        ),
        migrations.AlterField(
            model_name="classroomevaluationsubmission",
            name="course",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="evaluation_submissions",
                to="courses.course",
            ),
        ),
        migrations.AlterField(
            model_name="classroomevaluationsubmission",
            name="session",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="evaluation_submissions",
                to="courses.classroomsession",
            ),
        ),
        migrations.RemoveField(
            model_name="classroomevaluationconfig",
            name="session",
        ),
        migrations.AlterField(
            model_name="classroomevaluationconfig",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_course_evaluation_configs",
                to="accounts.user",
            ),
        ),
        migrations.AddConstraint(
            model_name="classroomevaluationsubmission",
            constraint=models.UniqueConstraint(
                condition=Q(("session__isnull", False)),
                fields=("session", "evaluation_type", "evaluator", "target"),
                name="uniq_classroom_evaluation_submission",
            ),
        ),
        migrations.AddConstraint(
            model_name="classroomevaluationsubmission",
            constraint=models.UniqueConstraint(
                condition=Q(("session__isnull", True)),
                fields=("course", "evaluation_type", "evaluator", "target"),
                name="uniq_course_evaluation_submission",
            ),
        ),
        migrations.AddIndex(
            model_name="classroomevaluationsubmission",
            index=models.Index(fields=["course", "evaluation_type", "updated_at"], name="courses_cla_course__18e3db_idx"),
        ),
        migrations.AddIndex(
            model_name="classroomevaluationsubmission",
            index=models.Index(fields=["class_group", "evaluation_type", "updated_at"], name="courses_cla_class_g_6c7841_idx"),
        ),
    ]
