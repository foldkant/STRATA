import uuid

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

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_events",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, null=True, blank=True
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.SET_NULL, null=True, blank=True
    )
    lesson = models.ForeignKey(
        "courses.Lesson", on_delete=models.SET_NULL, null=True, blank=True
    )
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
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feature_snapshots",
    )
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
        KEPT = "kept", "保持当前安排"
        ADJUSTED = "adjusted", "教师已调整"
        DEFERRED = "deferred", "暂缓处理"
        REJECTED = "rejected", "已拒绝"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="layer_decisions",
    )
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, null=True, blank=True
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.PROTECT, null=True, blank=True
    )
    previous_layer = models.CharField(max_length=1)
    suggested_layer = models.CharField(max_length=1)
    confidence = models.FloatField(default=0)
    reasons = models.JSONField(default=list, blank=True)
    missing_data = models.JSONField(default=list, blank=True)
    learning_summary = models.JSONField(default=dict, blank=True)
    support_suggestion = models.TextField(blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    rule_version = models.CharField(max_length=32, default="transparent-rules-v1")
    teacher_selected_layer = models.CharField(max_length=1, blank=True)
    review_note = models.TextField(blank=True)
    model_version = models.ForeignKey(
        "aiops.ModelVersion", on_delete=models.SET_NULL, null=True, blank=True
    )
    calibration_run = models.ForeignKey(
        "learning_analytics.ClassCalibrationRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stratification_decisions",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course", "window_end", "rule_version"],
                name="uniq_stratification_suggestion_window",
            )
        ]
        indexes = [
            models.Index(fields=["class_group", "status", "created_at"]),
            models.Index(fields=["subject", "status", "created_at"]),
        ]


class PretestPaper(models.Model):
    class Kind(models.TextChoices):
        LITERACY = "literacy", "素养测试"
        ATTITUDE = "attitude", "学习态度问卷"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        ARCHIVED = "archived", "归档"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="pretest_papers"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="pretest_papers"
    )
    title = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    version = models.PositiveIntegerField(default=1)
    introduction = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
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

    paper = models.ForeignKey(
        PretestPaper, on_delete=models.CASCADE, related_name="questions"
    )
    stem = models.TextField()
    question_type = models.CharField(
        max_length=16, choices=QuestionType.choices, default=QuestionType.SINGLE
    )
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
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pretest_submissions",
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="pretest_submissions"
    )
    paper = models.ForeignKey(
        PretestPaper, on_delete=models.PROTECT, related_name="submissions"
    )
    answers = models.JSONField(default=dict)
    score = models.FloatField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "paper"], name="uniq_pretest_submission_per_paper"
            ),
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
        DRAFT = "draft", "草稿"
        PENDING_REVIEW = "pending_review", "待审核"
        TRIAL = "trial", "可试用"
        ACTIVE = "active", "启用"
        DISABLED = "disabled", "停用"

    class Source(models.TextChoices):
        MANUAL = "manual", "手工创建"
        XLSX = "xlsx", "XLSX 导入"
        AI = "ai", "AI 生成"
        COPY = "copy", "复制题目"
        EXISTING = "existing", "既有题目"

    class LibraryScope(models.TextChoices):
        PERSONAL = "personal", "个人题目"
        SCHOOL = "school", "校内共享"

    class ItemRole(models.TextChoices):
        REGULAR = "regular", "普通题"
        COMMON = "common", "共同题"
        LAYERED = "layered", "分层题"

    class LayerScope(models.TextChoices):
        ALL = "all", "全体"
        A = "a", "A"
        B = "b", "B"
        C = "c", "C"
        AB = "ab", "A/B"
        BC = "bc", "B/C"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="question_bank_items"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="question_bank_items"
    )
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
    difficulty = models.CharField(
        max_length=16, choices=Difficulty.choices, default=Difficulty.NORMAL
    )
    knowledge_point = models.CharField(max_length=128, blank=True)
    default_score = models.FloatField(default=2)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DRAFT
    )
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.MANUAL
    )
    library_scope = models.CharField(
        max_length=16,
        choices=LibraryScope.choices,
        default=LibraryScope.PERSONAL,
    )
    item_role = models.CharField(
        max_length=16,
        choices=ItemRole.choices,
        default=ItemRole.REGULAR,
    )
    layer_scope = models.CharField(
        max_length=8,
        choices=LayerScope.choices,
        default=LayerScope.ALL,
    )
    comparison_code = models.CharField(max_length=64, blank=True, db_index=True)
    version_no = models.PositiveIntegerField(default=1)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    submitted_for_review_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_question_bank_items",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    disabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="disabled_question_bank_items",
    )
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "subject", "status", "updated_at"]),
            models.Index(fields=["school", "creator", "status"]),
            models.Index(fields=["school", "library_scope", "status"]),
            models.Index(fields=["school", "status", "submitted_for_review_at"]),
            models.Index(fields=["question_type", "difficulty"]),
            models.Index(fields=["school", "subject", "item_role", "comparison_code"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.stem[:48]


class QuestionBankItemVersion(models.Model):
    question = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versions",
    )
    original_question_id = models.PositiveBigIntegerField()
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="question_bank_item_versions",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="question_bank_item_versions",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_question_bank_item_versions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_question_bank_item_versions",
    )
    version_no = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64)
    source = models.CharField(max_length=16, choices=QuestionBankItem.Source.choices)
    status_snapshot = models.CharField(
        max_length=24, choices=QuestionBankItem.Status.choices
    )
    stem = models.TextField()
    question_type = models.CharField(
        max_length=16, choices=QuestionBankItem.QuestionType.choices
    )
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    analysis = models.TextField(blank=True)
    difficulty = models.CharField(
        max_length=16, choices=QuestionBankItem.Difficulty.choices
    )
    knowledge_point = models.CharField(max_length=128, blank=True)
    default_score = models.FloatField(default=2)
    item_role = models.CharField(
        max_length=16,
        choices=QuestionBankItem.ItemRole.choices,
        default=QuestionBankItem.ItemRole.REGULAR,
    )
    layer_scope = models.CharField(
        max_length=8,
        choices=QuestionBankItem.LayerScope.choices,
        default=QuestionBankItem.LayerScope.ALL,
    )
    comparison_code = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "original_question_id", "version_no"],
                name="uniq_question_bank_item_version",
            ),
            models.UniqueConstraint(
                fields=["school", "original_question_id", "content_hash"],
                name="uniq_question_bank_item_content_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "created_at"]),
            models.Index(fields=["question", "version_no"]),
            models.Index(fields=["content_hash"]),
        ]
        ordering = ["original_question_id", "version_no"]

    def __str__(self) -> str:
        return f"{self.original_question_id}@{self.version_no}"


class KnowledgeComponent(models.Model):
    """A school-owned subject concept used to link item responses over time."""

    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="knowledge_components",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="knowledge_components",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "code"],
                name="uniq_knowledge_component_code",
            ),
            models.UniqueConstraint(
                fields=["school", "subject", "name"],
                name="uniq_knowledge_component_name",
            ),
        ]
        indexes = [models.Index(fields=["school", "subject", "is_active"])]
        ordering = ["subject_id", "code"]

    def __str__(self) -> str:
        return f"{self.subject_id}:{self.code}"


class QuestionVersionKnowledgeComponent(models.Model):
    question_version = models.ForeignKey(
        QuestionBankItemVersion,
        on_delete=models.PROTECT,
        related_name="knowledge_mappings",
    )
    component = models.ForeignKey(
        KnowledgeComponent,
        on_delete=models.PROTECT,
        related_name="question_mappings",
    )
    weight = models.FloatField(default=1.0)
    is_primary = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_question_knowledge_mappings",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question_version", "component"],
                name="uniq_question_version_knowledge_component",
            ),
        ]
        indexes = [
            models.Index(fields=["component", "question_version"]),
            models.Index(fields=["question_version", "is_primary"]),
        ]
        ordering = ["question_version_id", "-is_primary", "component_id"]

    def __str__(self) -> str:
        return f"{self.question_version_id}:{self.component.code}"


class QuestionBankItemLifecycleRecord(models.Model):
    question = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lifecycle_records",
    )
    original_question_id = models.PositiveBigIntegerField()
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="question_bank_lifecycle_records",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="question_bank_lifecycle_actions",
    )
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, choices=QuestionBankItem.Status.choices)
    action = models.CharField(max_length=32)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "to_status", "created_at"]),
            models.Index(fields=["question", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.original_question_id}:{self.from_status}->{self.to_status}"


class CommonQuestionSet(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        ARCHIVED = "archived", "归档"

    class VersionPurpose(models.TextChoices):
        BASELINE = "baseline", "首个版本"
        FOLLOW_UP = "follow_up", "后续版本"
        PARALLEL = "parallel", "平行版本"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="common_question_sets"
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="common_question_sets"
    )
    title = models.CharField(max_length=128)
    grade_scope = models.CharField(max_length=32, blank=True)
    term = models.CharField(max_length=32, blank=True)
    version_no = models.PositiveIntegerField(default=1)
    measurement_series = models.CharField(max_length=96, blank=True, db_index=True)
    version_purpose = models.CharField(
        max_length=16,
        choices=VersionPurpose.choices,
        default=VersionPurpose.BASELINE,
    )
    previous_version = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="next_versions",
    )
    readiness = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_common_question_sets",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_common_question_sets",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "grade_scope", "term", "version_no"],
                name="uniq_common_question_set_version",
            )
        ]
        indexes = [
            models.Index(fields=["school", "subject", "status", "updated_at"]),
            models.Index(fields=["school", "subject", "measurement_series", "version_no"]),
        ]
        ordering = ["subject_id", "grade_scope", "term", "-version_no"]

    def __str__(self) -> str:
        return f"{self.title} v{self.version_no}"


class CommonQuestionSetItem(models.Model):
    question_set = models.ForeignKey(
        CommonQuestionSet, on_delete=models.CASCADE, related_name="items"
    )
    question_version = models.ForeignKey(
        QuestionBankItemVersion,
        on_delete=models.PROTECT,
        related_name="common_set_items",
    )
    anchor_source = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="anchor_successors",
    )
    comparison_code = models.CharField(max_length=64)
    required = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question_set", "question_version"],
                name="uniq_common_set_question_version",
            ),
            models.UniqueConstraint(
                fields=["question_set", "comparison_code"],
                name="uniq_common_set_comparison_code",
            ),
        ]
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.question_set_id}:{self.comparison_code}"


class TestAssessment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "待开启"
        OPEN = "open", "进行中"
        CLOSED = "closed", "已结束"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="test_assessments"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="test_assessments",
        limit_choices_to={"role": "teacher"},
    )
    subject = models.ForeignKey(
        "courses.Subject", on_delete=models.PROTECT, related_name="test_assessments"
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_assessments",
    )
    common_question_set = models.ForeignKey(
        "CommonQuestionSet",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessments",
    )
    common_set_version = models.PositiveIntegerField(null=True, blank=True)
    common_set_hash = models.CharField(max_length=64, blank=True)
    target_classes = models.ManyToManyField(
        "school.ClassGroup", related_name="test_assessments"
    )
    title = models.CharField(max_length=128)
    instruction = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=45)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
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
    assessment = models.ForeignKey(
        TestAssessment, on_delete=models.CASCADE, related_name="questions"
    )
    source_question = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_questions",
    )
    source_version = models.ForeignKey(
        QuestionBankItemVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_questions",
    )
    source_status = models.CharField(
        max_length=24,
        choices=QuestionBankItem.Status.choices,
        default=QuestionBankItem.Status.ACTIVE,
    )
    question_type = models.CharField(
        max_length=16, choices=QuestionBankItem.QuestionType.choices
    )
    stem = models.TextField()
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField(default=list, blank=True)
    analysis = models.TextField(blank=True)
    knowledge_point = models.CharField(max_length=128, blank=True)
    score = models.FloatField(default=2)
    sort_order = models.PositiveIntegerField(default=0)
    item_role = models.CharField(
        max_length=16,
        choices=QuestionBankItem.ItemRole.choices,
        default=QuestionBankItem.ItemRole.REGULAR,
    )
    layer_scope = models.CharField(
        max_length=8,
        choices=QuestionBankItem.LayerScope.choices,
        default=QuestionBankItem.LayerScope.ALL,
    )
    comparison_code = models.CharField(max_length=64, blank=True)

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

    assessment = models.ForeignKey(
        TestAssessment, on_delete=models.PROTECT, related_name="attempts"
    )
    analytics_attempt_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="test_attempts"
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, related_name="test_attempts"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.IN_PROGRESS
    )
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
            models.UniqueConstraint(
                fields=["assessment", "student"], name="uniq_test_attempt_per_student"
            ),
        ]
        indexes = [
            models.Index(fields=["assessment", "class_group", "status"]),
            models.Index(fields=["student", "status", "started_at"]),
        ]
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.assessment} - {self.student}"


class TestAttemptAnswer(models.Model):
    attempt = models.ForeignKey(
        TestAttempt, on_delete=models.CASCADE, related_name="answer_rows"
    )
    question = models.ForeignKey(
        TestAssessmentQuestion, on_delete=models.PROTECT, related_name="attempt_answers"
    )
    answer = models.JSONField(default=list, blank=True)
    auto_score = models.FloatField(default=0)
    manual_score = models.FloatField(null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"],
                name="uniq_test_answer_per_attempt_question",
            ),
        ]
        indexes = [models.Index(fields=["attempt", "question"])]
        ordering = ["question__sort_order", "question_id"]

    @property
    def final_score(self) -> float:
        return self.manual_score if self.manual_score is not None else self.auto_score


class AssessmentComparabilityRecord(models.Model):
    class Status(models.TextChoices):
        COMPARABLE = "comparable", "可以比较"
        NOT_COMPARABLE = "not_comparable", "不可比较"
        INSUFFICIENT = "insufficient", "数据不足"

    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="assessment_comparability_records",
    )
    left_assessment = models.ForeignKey(
        TestAssessment,
        on_delete=models.CASCADE,
        related_name="comparisons_as_left",
    )
    right_assessment = models.ForeignKey(
        TestAssessment,
        on_delete=models.CASCADE,
        related_name="comparisons_as_right",
    )
    status = models.CharField(max_length=24, choices=Status.choices)
    common_question_count = models.PositiveIntegerField(default=0)
    exact_version_match_count = models.PositiveIntegerField(default=0)
    left_sample_size = models.PositiveIntegerField(default=0)
    right_sample_size = models.PositiveIntegerField(default=0)
    reasons = models.JSONField(default=list, blank=True)
    compared_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["left_assessment", "right_assessment"],
                name="uniq_assessment_comparison_pair",
            )
        ]
        indexes = [models.Index(fields=["school", "status", "compared_at"])]
        ordering = ["-compared_at", "-id"]

    def __str__(self) -> str:
        return f"{self.left_assessment_id}:{self.right_assessment_id}:{self.status}"


class Notice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        ARCHIVED = "archived", "归档"

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="notices"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teacher_notices",
    )
    target_classes = models.ManyToManyField(
        "school.ClassGroup", related_name="notices", blank=True
    )
    title = models.CharField(max_length=128)
    content = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
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

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="feedback_items"
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, related_name="feedback_items"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_feedback_items",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_feedback_items",
    )
    category = models.CharField(
        max_length=16, choices=Category.choices, default=Category.STUDY
    )
    title = models.CharField(max_length=128)
    content = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
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
    submission_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="student_work_attachments",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_work_attachments",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="student_work_attachments",
    )
    question_id = models.CharField(max_length=64)
    question_stem = models.TextField(blank=True)
    upload_version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revisions",
    )
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
            models.UniqueConstraint(
                fields=["student", "lesson_step", "question_id", "upload_version"],
                name="uniq_student_work_version",
            ),
        ]
        indexes = [
            models.Index(fields=["class_group", "lesson_step", "question_id"]),
            models.Index(fields=["student", "created_at"]),
            models.Index(fields=["classroom_session", "created_at"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.student_id}:{self.lesson_step_id}:{self.question_id}@{self.upload_version}"


class LessonStepAttempt(models.Model):
    attempt_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    lesson_step = models.ForeignKey(
        "courses.LessonStep",
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    classroom_session = models.ForeignKey(
        "courses.ClassroomSession",
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lesson_step_attempts",
    )
    attempt_no = models.PositiveIntegerField()
    answer = models.JSONField(default=dict, blank=True)
    free_text = models.TextField(blank=True)
    answered_count = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    auto_score = models.FloatField(default=0)
    auto_score_max = models.FloatField(default=0)
    submitted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "classroom_session",
                    "lesson_step",
                    "student",
                    "attempt_no",
                ],
                name="uniq_lesson_step_attempt_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["classroom_session", "lesson_step", "student", "submitted_at"]
            ),
            models.Index(fields=["student", "submitted_at"]),
        ]
        ordering = ["-submitted_at", "-id"]

    def __str__(self) -> str:
        return f"{self.student_id}:{self.lesson_step_id}#{self.attempt_no}"


class LessonStepAttemptAnswer(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE = "single", "单选"
        MULTIPLE = "multiple", "多选"
        JUDGE = "judge", "判断"
        BLANK = "blank", "填空"
        TEXT = "text", "简答"
        FILE = "file", "附件提交"

    attempt = models.ForeignKey(
        LessonStepAttempt,
        on_delete=models.PROTECT,
        related_name="answer_rows",
    )
    question_id = models.CharField(max_length=64)
    question_version = models.CharField(max_length=64)
    question_type = models.CharField(max_length=16, choices=QuestionType.choices)
    response = models.JSONField(default=dict, blank=True)
    is_answered = models.BooleanField(default=False)
    auto_score = models.FloatField(null=True, blank=True)
    score_max = models.FloatField()
    is_correct = models.BooleanField(null=True, blank=True)
    attachment = models.ForeignKey(
        StudentWorkAttachment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attempt_answers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question_id"],
                name="uniq_lesson_step_attempt_question",
            ),
        ]
        indexes = [
            models.Index(fields=["attempt", "question_id"]),
            models.Index(fields=["question_version"]),
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.attempt_id}:{self.question_id}"


# Create your models here.
