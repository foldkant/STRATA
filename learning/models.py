from django.conf import settings
from django.db import models


def student_work_upload_path(instance, filename: str) -> str:
    school_id = instance.school_id or "unknown"
    class_id = instance.class_group_id or "unknown"
    step_id = instance.lesson_step_id or "unknown"
    student_id = instance.student_id or "unknown"
    return f"student_work/school_{school_id}/class_{class_id}/step_{step_id}/student_{student_id}/{filename}"


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


class QuestionBankItem(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE = "single", "单选"
        MULTIPLE = "multiple", "多选"
        JUDGE = "judge", "判断"
        BLANK = "blank", "填空"
        TEXT = "text", "简答"

    class Difficulty(models.TextChoices):
        EASY = "easy", "基础"
        NORMAL = "normal", "适中"
        HARD = "hard", "挑战"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        DISABLED = "disabled", "停用"

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="question_bank_items")
    subject = models.ForeignKey("courses.Subject", on_delete=models.PROTECT, related_name="question_bank_items")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_question_bank_items",
        limit_choices_to={"role": "teacher"},
    )
    stem = models.TextField()
    question_type = models.CharField(max_length=16, choices=QuestionType.choices)
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    analysis = models.TextField(blank=True)
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, default=Difficulty.NORMAL)
    knowledge_point = models.CharField(max_length=128, blank=True)
    default_score = models.FloatField(default=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "subject", "status", "updated_at"]),
            models.Index(fields=["school", "creator", "status"]),
            models.Index(fields=["question_type", "difficulty"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.stem[:48]


class TestAssessment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "待开启"
        OPEN = "open", "进行中"
        CLOSED = "closed", "已结束"

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="test_assessments")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="test_assessments",
        limit_choices_to={"role": "teacher"},
    )
    subject = models.ForeignKey("courses.Subject", on_delete=models.PROTECT, related_name="test_assessments")
    course = models.ForeignKey("courses.Course", on_delete=models.SET_NULL, null=True, blank=True, related_name="test_assessments")
    target_classes = models.ManyToManyField("school.ClassGroup", related_name="test_assessments")
    title = models.CharField(max_length=128)
    instruction = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=45)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    show_score_after_submit = models.BooleanField(default=False)
    randomize_question_order = models.BooleanField(default=False)
    randomize_option_order = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "teacher", "status", "updated_at"]),
            models.Index(fields=["school", "status", "start_at", "end_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.title


class TestAssessmentQuestion(models.Model):
    assessment = models.ForeignKey(TestAssessment, on_delete=models.CASCADE, related_name="questions")
    source_question = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_questions",
    )
    question_type = models.CharField(max_length=16, choices=QuestionBankItem.QuestionType.choices)
    stem = models.TextField()
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    analysis = models.TextField(blank=True)
    knowledge_point = models.CharField(max_length=128, blank=True)
    score = models.FloatField(default=2)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["assessment", "sort_order", "id"])]
        ordering = ["assessment_id", "sort_order", "id"]

    def __str__(self) -> str:
        return self.stem[:48]


class TestAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "答题中"
        SUBMITTED = "submitted", "已提交"
        GRADED = "graded", "已评分"

    assessment = models.ForeignKey(TestAssessment, on_delete=models.PROTECT, related_name="attempts")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="test_attempts")
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT, related_name="test_attempts")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    objective_score = models.FloatField(default=0)
    subjective_score = models.FloatField(default=0)
    total_score = models.FloatField(default=0)
    question_order = models.JSONField(default=list, blank=True)
    option_orders = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_saved_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["assessment", "student"], name="uniq_test_attempt_per_student"),
        ]
        indexes = [
            models.Index(fields=["assessment", "class_group", "status"]),
            models.Index(fields=["student", "status", "started_at"]),
        ]
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.assessment} - {self.student}"


class TestAttemptAnswer(models.Model):
    attempt = models.ForeignKey(TestAttempt, on_delete=models.CASCADE, related_name="answer_rows")
    question = models.ForeignKey(TestAssessmentQuestion, on_delete=models.PROTECT, related_name="attempt_answers")
    answer = models.JSONField(default=list, blank=True)
    auto_score = models.FloatField(default=0)
    manual_score = models.FloatField(null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "question"], name="uniq_test_answer_per_attempt_question"),
        ]
        indexes = [models.Index(fields=["attempt", "question"])]
        ordering = ["question__sort_order", "question_id"]

    @property
    def final_score(self) -> float:
        return self.manual_score if self.manual_score is not None else self.auto_score


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


class StudentWorkAttachment(models.Model):
    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="student_work_attachments")
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT, related_name="student_work_attachments")
    course = models.ForeignKey("courses.Course", on_delete=models.PROTECT, related_name="student_work_attachments")
    lesson = models.ForeignKey("courses.Lesson", on_delete=models.PROTECT, related_name="student_work_attachments")
    lesson_step = models.ForeignKey("courses.LessonStep", on_delete=models.PROTECT, related_name="student_work_attachments")
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_work_attachments",
    )
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="student_work_attachments")
    question_id = models.CharField(max_length=64)
    question_stem = models.TextField(blank=True)
    attachment = models.FileField(upload_to=student_work_upload_path)
    original_name = models.CharField(max_length=255)
    file_ext = models.CharField(max_length=16, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    score = models.FloatField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluated_student_work_attachments",
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "lesson_step", "question_id"], name="uniq_student_work_per_step_question"),
        ]
        indexes = [
            models.Index(fields=["class_group", "lesson_step", "question_id"]),
            models.Index(fields=["student", "created_at"]),
            models.Index(fields=["classroom_session", "created_at"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.student_id}:{self.lesson_step_id}:{self.question_id}"

# Create your models here.
