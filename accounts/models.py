from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "超级管理员"
        SCHOOL_ADMIN = "school_admin", "学校管理员"
        TEACHER = "teacher", "教师"
        STUDENT = "student", "学生"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    display_name = models.CharField(max_length=64, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_first_login = models.BooleanField(default=True)
    legacy_id = models.IntegerField(null=True, blank=True, db_index=True)

    @property
    def is_platform_admin(self) -> bool:
        return self.role == self.Role.SUPER_ADMIN or self.is_superuser

    @property
    def is_school_admin(self) -> bool:
        return self.role == self.Role.SCHOOL_ADMIN

    def __str__(self) -> str:
        return self.display_name or self.username

# Create your models here.
