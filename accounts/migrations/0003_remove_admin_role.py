from django.db import migrations, models


def forward_admin_to_super_admin(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="admin").update(role="super_admin", is_staff=True, is_superuser=True)


def backward_super_admin_to_admin(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(username="admin", role="super_admin").update(role="admin")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_school_alter_user_role"),
    ]

    operations = [
        migrations.RunPython(forward_admin_to_super_admin, backward_super_admin_to_admin),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("super_admin", "超级管理员"),
                    ("school_admin", "学校管理员"),
                    ("teacher", "教师"),
                    ("student", "学生"),
                ],
                default="student",
                max_length=20,
            ),
        ),
    ]
