from django.db import models


class TeacherAIProvider(models.Model):
    class Provider(models.TextChoices):
        DEEPSEEK = "deepseek", "DeepSeek"

    teacher = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="ai_providers",
        limit_choices_to={"role": "teacher"},
    )
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.DEEPSEEK)
    base_url = models.URLField(max_length=255, default="https://api.deepseek.com")
    model = models.CharField(max_length=64, default="deepseek-v4-flash")
    api_key_encrypted = models.TextField(blank=True)
    api_key_hint = models.CharField(max_length=16, blank=True)
    is_enabled = models.BooleanField(default=False)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["teacher", "provider"], name="uniq_teacher_ai_provider"),
        ]
        ordering = ["teacher_id", "provider"]

    def __str__(self) -> str:
        return f"{self.teacher_id}:{self.provider}:{self.model}"


class ModelVersion(models.Model):
    class Status(models.TextChoices):
        CANDIDATE = "candidate", "候选"
        CHAMPION = "champion", "生产"
        ARCHIVED = "archived", "归档"
        FAILED = "failed", "失败"

    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.CASCADE, related_name="model_versions")
    name = models.CharField(max_length=128)
    version = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CANDIDATE)
    algorithm = models.CharField(max_length=64, default="rules")
    metrics = models.JSONField(default=dict, blank=True)
    feature_schema = models.JSONField(default=dict, blank=True)
    artifact_uri = models.CharField(max_length=512, blank=True)
    trained_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["class_group", "name", "version"], name="uniq_class_model_version"),
        ]
        indexes = [
            models.Index(fields=["class_group", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name}:{self.version}"


class TrainingJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待中"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.CASCADE, related_name="training_jobs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    celery_task_id = models.CharField(max_length=128, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    logs = models.TextField(blank=True)
    output_model = models.ForeignKey(ModelVersion, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

# Create your models here.
