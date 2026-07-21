from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0017_stratificationdecision_abstain_reason_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="stratificationdecision",
            name="review_reason_code",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
