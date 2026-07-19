from django.conf import settings
from django.db import models


class School(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        DISABLED = "disabled", "停用"
        ARCHIVED = "archived", "归档"

    name = models.CharField(max_length=128, unique=True)
    code = models.CharField(max_length=32, unique=True)
    contact_name = models.CharField(max_length=64, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_synthetic = models.BooleanField(default=False, db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ClassGroup(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        DISABLED = "disabled", "停用"
        ARCHIVED = "archived", "归档"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField(max_length=64)
    grade = models.CharField(max_length=32, blank=True)
    entry_year = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    graduated_at = models.DateTimeField(null=True, blank=True)
    graduated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graduated_classes",
    )
    teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="teaching_classes",
        limit_choices_to={"role": "teacher"},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"], name="uniq_class_name_per_school"
            ),
        ]
        ordering = ["school_id", "grade", "name"]

    def __str__(self) -> str:
        return f"{self.school.name}-{self.name}"


class StudentProfile(models.Model):
    class Layer(models.TextChoices):
        A = "A", "拓展挑战层"
        B = "B", "核心发展层"
        C = "C", "基础提升层"

    class OnboardingStatus(models.TextChoices):
        NEW = "new", "首次使用"
        PASSWORD_UPDATED = "password_updated", "已改密码"
        CLASS_SELECTED = "class_selected", "已选班级"
        PRETEST_COMPLETED = "pretest_completed", "已完成前测"
        ACTIVE = "active", "已进入平台"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.PROTECT,
        related_name="students",
        null=True,
        blank=True,
    )
    student_no = models.CharField(max_length=32, blank=True)
    current_layer = models.CharField(
        max_length=1, choices=Layer.choices, null=True, blank=True
    )
    current_group_no = models.PositiveIntegerField(null=True, blank=True)
    score = models.FloatField(default=0)
    is_first_use = models.BooleanField(default=True)
    onboarding_status = models.CharField(
        max_length=32,
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.NEW,
    )
    password_updated_at = models.DateTimeField(null=True, blank=True)
    class_selected_at = models.DateTimeField(null=True, blank=True)
    pretest_completed_at = models.DateTimeField(null=True, blank=True)
    legacy_id = models.IntegerField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["class_group", "student_no"],
                condition=~models.Q(student_no=""),
                name="uniq_student_no_per_class_when_present",
            ),
        ]

    def __str__(self) -> str:
        return str(self.user)


class TeachingAssignment(models.Model):
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="teaching_assignments"
    )
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.PROTECT, related_name="teaching_assignments"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teaching_assignments",
        limit_choices_to={"role": "teacher"},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "class_group", "teacher"],
                name="uniq_teaching_assignment_teacher_class",
            ),
        ]
        ordering = ["teacher__username", "class_group__grade", "class_group__name"]

    def __str__(self) -> str:
        return f"{self.teacher} - {self.class_group}"
