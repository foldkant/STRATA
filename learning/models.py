from django.conf import settings
from django.db import models


class LearningEvent(models.Model):
    class EventType(models.TextChoices):
        LOGIN = "login", "登录"
        PAGE_VIEW = "page_view", "页面访问"
        RESOURCE_VIEW = "resource_view", "资源查看"
        LESSON_ENTER = "lesson_enter", "进入课时"
        ANSWER_SUBMIT = "answer_submit", "提交答案"
        TASK_SUBMIT = "task_submit", "提交任务"
        PROJECT_SUBMIT = "project_submit", "提交项目"
        CHAT_MESSAGE = "chat_message", "聊天消息"
        QUESTION_ASK = "question_ask", "提问"
        QUESTION_ANSWER = "question_answer", "回答"
        TEACHER_INTERVENTION = "teacher_intervention", "教师干预"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learning_events")
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT, null=True, blank=True)
    course = models.ForeignKey("courses.Course", on_delete=models.SET_NULL, null=True, blank=True)
    lesson = models.ForeignKey("courses.Lesson", on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    score = models.FloatField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["class_group", "occurred_at"]),
            models.Index(fields=["actor", "occurred_at"]),
            models.Index(fields=["event_type", "occurred_at"]),
        ]
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.actor_id}:{self.event_type}@{self.occurred_at:%Y-%m-%d %H:%M:%S}"


class StudentFeatureSnapshot(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feature_snapshots")
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    features = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "window_start", "window_end"],
                name="uniq_feature_snapshot_window",
            )
        ]
        indexes = [
            models.Index(fields=["class_group", "window_end"]),
        ]


class StratificationDecision(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待教师确认"
        ACCEPTED = "accepted", "已采纳"
        REJECTED = "rejected", "已拒绝"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="layer_decisions")
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT)
    previous_layer = models.CharField(max_length=1)
    suggested_layer = models.CharField(max_length=1)
    confidence = models.FloatField(default=0)
    reasons = models.JSONField(default=list, blank=True)
    model_version = models.ForeignKey("aiops.ModelVersion", on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_layer_decisions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["class_group", "status", "created_at"]),
        ]


class PretestPaper(models.Model):
    class Kind(models.TextChoices):
        LITERACY = "literacy", "素养测试"
        ATTITUDE = "attitude", "学习态度问卷"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        ARCHIVED = "archived", "归档"

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="pretest_papers")
    subject = models.ForeignKey("courses.Subject", on_delete=models.PROTECT, related_name="pretest_papers")
    title = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    version = models.PositiveIntegerField(default=1)
    introduction = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pretest_papers",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "kind", "version"],
                name="uniq_pretest_paper_version_per_subject_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "kind", "status"]),
        ]
        ordering = ["subject__name", "kind", "-version", "-created_at"]

    def __str__(self) -> str:
        return f"{self.subject} - {self.get_kind_display()} v{self.version}"


class PretestQuestion(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE = "single", "单选"
        MULTIPLE = "multiple", "多选"
        SCALE = "scale", "量表"
        TEXT = "text", "简答"

    paper = models.ForeignKey(PretestPaper, on_delete=models.CASCADE, related_name="questions")
    stem = models.TextField()
    question_type = models.CharField(max_length=16, choices=QuestionType.choices, default=QuestionType.SINGLE)
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    score = models.FloatField(default=0)
    dimension = models.CharField(max_length=64, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["paper_id", "sort_order", "id"]
        indexes = [
            models.Index(fields=["paper", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.stem[:48]


class PretestSubmission(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pretest_submissions")
    subject = models.ForeignKey("courses.Subject", on_delete=models.PROTECT, related_name="pretest_submissions")
    paper = models.ForeignKey(PretestPaper, on_delete=models.PROTECT, related_name="submissions")
    answers = models.JSONField(default=dict)
    score = models.FloatField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "paper"], name="uniq_pretest_submission_per_paper"),
        ]
        indexes = [
            models.Index(fields=["subject", "submitted_at"]),
            models.Index(fields=["student", "subject"]),
        ]


class Notice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        ARCHIVED = "archived", "归档"

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="notices")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="teacher_notices")
    target_classes = models.ManyToManyField("school.ClassGroup", related_name="notices", blank=True)
    title = models.CharField(max_length=128)
    content = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    is_pinned = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "teacher", "status", "created_at"]),
            models.Index(fields=["school", "status", "is_pinned"]),
        ]
        ordering = ["-is_pinned", "-published_at", "-created_at"]

    def __str__(self) -> str:
        return self.title


class Feedback(models.Model):
    class Category(models.TextChoices):
        STUDY = "study", "学习问题"
        ACCOUNT = "account", "账号问题"
        RESOURCE = "resource", "资源问题"
        SUGGESTION = "suggestion", "建议反馈"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        PENDING = "pending", "待回复"
        REPLIED = "replied", "已回复"
        CLOSED = "closed", "已关闭"

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="feedback_items")
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT, related_name="feedback_items")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_feedback_items")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_feedback_items")
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.STUDY)
    title = models.CharField(max_length=128)
    content = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reply_content = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "teacher", "status", "created_at"]),
            models.Index(fields=["class_group", "status", "created_at"]),
            models.Index(fields=["student", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

# Create your models here.
