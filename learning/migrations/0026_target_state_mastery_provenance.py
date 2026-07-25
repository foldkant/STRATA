from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0025_p4_target_mastery_integrity"),
    ]

    operations = [
        # Historical states stay NULL intentionally: attaching a result would
        # change their hashed semantic content.  Only newly appended states
        # can enter the provenance-gated training-candidate selector.
        migrations.AddField(
            model_name="studentlearningtargetstateversion",
            name="mastery_target_result",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="learning_target_states",
                to="learning.studentmasterytargetresult",
            ),
        ),
    ]
