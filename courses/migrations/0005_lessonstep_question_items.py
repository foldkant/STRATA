from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0004_lessonstep"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonstep",
            name="question_items",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
