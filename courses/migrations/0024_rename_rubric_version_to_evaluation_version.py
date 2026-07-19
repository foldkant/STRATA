from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0023_group_collaboration_evidence"),
    ]

    operations = [
        migrations.RenameField(
            model_name="classroomevaluationsubmission",
            old_name="rubric_version",
            new_name="evaluation_version",
        ),
    ]
