from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0005_questionbankitem_testassessment_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="testassessment",
            name="randomize_option_order",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="testassessment",
            name="randomize_question_order",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="testattempt",
            name="option_orders",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="testattempt",
            name="question_order",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
