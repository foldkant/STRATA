from django.conf import settings
from django.db import models
from django.db.models import Q


def classroom_group_document_upload_path(instance, filename: str) -> str:
    collaboration = instance.collaboration
    session = collaboration.session
    school_id = session.school_id or "unknown"
    class_id = session.class_group_id or "unknown"
    session_id = session.id or "unknown"
    group_id = instance.id or "unknown"
    suffix = str(filename or "").rsplit(".", 1)[-1].lower() if "." in str(filename or "") else collaboration.document_type
    return f"classroom_group_docs/school_{school_id}/class_{class_id}/session_{session_id}/group_{group_id}/collaboration.{suffix}"


def classroom_group_file_upload_path(instance, filename: str) -> str:
    group = instance.group
    session = group.collaboration.session
    school_id = session.school_id or "unknown"
    class_id = session.class_group_id or "unknown"
    session_id = session.id or "unknown"
    group_id = group.id or "unknown"
    uploader_id = instance.uploader_id or "unknown"
    return f"classroom_group_files/school_{school_id}/class_{class_id}/session_{session_id}/group_{group_id}/user_{uploader_id}/{filename}"


class Subject(models.Model):
    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=64)
    code = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_subjects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "code"], name="uniq_subject_code_per_school"),
            models.UniqueConstraint(fields=["school", "name"], name="uniq_subject_name_per_school"),
        ]
        ordering = ["school_id", "name"]

    def __str__(self) -> str:
        return self.name


class Course(models.Model):
    class TeachingModel(models.TextChoices):
        PROJECT = "pbl", "项目式学习"
        TASK = "tbl", "任务驱动学习"

    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, null=True, blank=True, related_name="courses")
    title = models.CharField(max_length=128)
    introduction = models.TextField(blank=True)
    cover = models.ImageField(upload_to="course_covers/", blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="courses")
    teaching_model = models.CharField(max_length=16, choices=TeachingModel.choices, default=TeachingModel.PROJECT)
    is_active = models.BooleanField(default=False)
    legacy_id = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class CourseClass(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="course_classes")
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT, related_name="course_classes")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_course_classes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["course", "class_group"], name="uniq_course_class_group"),
        ]
        ordering = ["course_id", "class_group__grade", "class_group__name"]

    def __str__(self) -> str:
        return f"{self.course} - {self.class_group}"


class Lesson(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=128)
    content = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=False)
    legacy_id = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["course_id", "sort_order", "id"]

    def __str__(self) -> str:
        return self.title


class LessonStep(models.Model):
    class StepType(models.TextChoices):
        INTRO = "intro", "导入"
        RESOURCE = "resource", "资源学习"
        QUESTION = "question", "课堂题"
        TASK = "task", "任务实践"
        UPLOAD = "upload", "作品上传"
        DISCUSSION = "discussion", "讨论反馈"
        EVALUATION = "evaluation", "展示评价"
        REFLECTION = "reflection", "小结反思"
        AI_WORKSHEET = "ai_worksheet", "AI 学习单"
        DOCUMENT = "document", "协作文档"

    class TargetLayer(models.TextChoices):
        ALL = "all", "全体"
        A = "A", "A"
        B = "B", "B"
        C = "C", "C"
        AB = "A/B", "A/B"
        BC = "B/C", "B/C"
        ABC = "A/B/C", "A/B/C"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        READY = "ready", "已配置"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="steps")
    title = models.CharField(max_length=128)
    step_type = models.CharField(max_length=32, choices=StepType.choices, default=StepType.RESOURCE)
    student_instruction = models.TextField(blank=True)
    teacher_note = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)
    estimated_minutes = models.PositiveIntegerField(default=10)
    target_layer = models.CharField(max_length=16, choices=TargetLayer.choices, default=TargetLayer.ALL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    resource_items = models.JSONField(default=list, blank=True)
    activity_items = models.JSONField(default=list, blank=True)
    question_items = models.JSONField(default=list, blank=True)
    ai_prompt = models.TextField(blank=True)
    collect_student_log = models.BooleanField(default=True)
    collect_class_log = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_lesson_steps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["lesson", "sort_order", "id"]),
            models.Index(fields=["step_type", "status"]),
        ]
        ordering = ["lesson_id", "sort_order", "id"]

    def __str__(self) -> str:
        return self.title


class LearningWebPage(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        READY = "ready", "可使用"

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="learning_web_pages")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="learning_web_pages",
        limit_choices_to={"role": "teacher"},
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="learning_web_pages")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="learning_web_pages")
    title = models.CharField(max_length=128)
    schema = models.JSONField(default=dict)
    generation_prompt = models.TextField(blank=True)
    revision_no = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["lesson", "is_active", "updated_at"]),
            models.Index(fields=["teacher", "updated_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.title


class LearningWebPageVersion(models.Model):
    page = models.ForeignKey(LearningWebPage, on_delete=models.CASCADE, related_name="versions")
    version_no = models.PositiveIntegerField()
    prompt = models.TextField(blank=True)
    schema = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_learning_web_page_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["page", "version_no"], name="uniq_learning_web_page_version"),
        ]
        ordering = ["-version_no", "-id"]

    def __str__(self) -> str:
        return f"{self.page} v{self.version_no}"


class LearningWebPageResponse(models.Model):
    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="learning_web_page_responses")
    page = models.ForeignKey(LearningWebPage, on_delete=models.PROTECT, related_name="responses")
    page_version = models.PositiveIntegerField(default=1)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="learning_web_page_responses",
        limit_choices_to={"role": "student"},
    )
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT, related_name="learning_web_page_responses")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="learning_web_page_responses")
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT, related_name="learning_web_page_responses")
    lesson_step = models.ForeignKey(LessonStep, on_delete=models.PROTECT, related_name="learning_web_page_responses")
    classroom_session = models.ForeignKey(
        "ClassroomSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_web_page_responses",
    )
    form_id = models.CharField(max_length=64)
    answers = models.JSONField(default=dict)
    attempt_no = models.PositiveIntegerField(default=1)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["page", "student", "form_id", "attempt_no"],
                name="uniq_learning_web_page_form_attempt",
            ),
        ]
        indexes = [
            models.Index(fields=["page", "form_id", "submitted_at"]),
            models.Index(fields=["class_group", "submitted_at"]),
            models.Index(fields=["student", "submitted_at"]),
        ]
        ordering = ["-submitted_at", "-id"]

    def __str__(self) -> str:
        return f"{self.page_id}:{self.form_id}:{self.student_id}#{self.attempt_no}"


class ClassroomSession(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "未开始"
        RUNNING = "running", "进行中"
        FINISHED = "finished", "已结束"

    class StepStatus(models.TextChoices):
        IDLE = "idle", "未投放"
        OPEN = "open", "已投放"
        LOCKED = "locked", "已锁定"
        CLOSED = "closed", "已关闭"

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="classroom_sessions")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="classroom_sessions",
        limit_choices_to={"role": "teacher"},
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="classroom_sessions")
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="classroom_sessions",
    )
    class_group = models.ForeignKey("school.ClassGroup", on_delete=models.PROTECT, related_name="classroom_sessions")
    title = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    current_step = models.ForeignKey(
        LessonStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    current_step_status = models.CharField(max_length=16, choices=StepStatus.choices, default=StepStatus.IDLE)
    submission_locked = models.BooleanField(default=False)
    is_layered = models.BooleanField(default=False)
    evaluation_enabled = models.BooleanField(default=False)
    evaluation_opened_at = models.DateTimeField(null=True, blank=True)
    current_step_started_at = models.DateTimeField(null=True, blank=True)
    current_step_closed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "teacher", "status", "created_at"]),
            models.Index(fields=["class_group", "status", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class ClassroomActivity(models.Model):
    class ActivityType(models.TextChoices):
        SIGN_IN = "sign_in", "签到"
        QUICK_ANSWER = "quick_answer", "抢答"
        QUESTION = "question", "即时题"
        DISCUSSION = "discussion", "讨论"
        TASK = "task", "课堂任务"
        CONFUSION = "confusion", "未懂反馈"
        BROADCAST = "broadcast", "课堂广播"

    class Status(models.TextChoices):
        DRAFT = "draft", "未开启"
        OPEN = "open", "进行中"
        CLOSED = "closed", "已关闭"

    session = models.ForeignKey(ClassroomSession, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=32, choices=ActivityType.choices)
    title = models.CharField(max_length=128)
    content = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "status", "created_at"]),
            models.Index(fields=["activity_type", "status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class Resource(models.Model):
    title = models.CharField(max_length=128)
    content = models.TextField(blank=True)
    attachment = models.FileField(upload_to="resources/", blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="resources")
    view_count = models.PositiveIntegerField(default=0)
    is_pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-created_at"]

    def __str__(self) -> str:
        return self.title


class ClassroomGroupCollaboration(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "未开启"
        OPEN = "open", "进行中"
        CLOSED = "closed", "已关闭"

    class GroupingStrategy(models.TextChoices):
        BALANCED_LAYER = "balanced_layer", "按层级优先分组"
        SAME_LAYER = "same_layer", "同层级分组"
        RANDOM = "random", "随机分组"
        MANUAL = "manual", "手动分组"
        AI_LAYER = "ai_layer", "AI 分层分组"

    class DocumentType(models.TextChoices):
        DOCX = "docx", "Word"
        PPTX = "pptx", "PPT"
        XLSX = "xlsx", "Excel"

    session = models.OneToOneField(
        ClassroomSession,
        on_delete=models.CASCADE,
        related_name="group_collaboration",
    )
    is_enabled = models.BooleanField(default=False)
    group_size = models.PositiveSmallIntegerField(default=4)
    grouping_strategy = models.CharField(
        max_length=32,
        choices=GroupingStrategy.choices,
        default=GroupingStrategy.BALANCED_LAYER,
    )
    document_type = models.CharField(max_length=8, choices=DocumentType.choices, default=DocumentType.DOCX)
    storage_quota_mb = models.PositiveIntegerField(default=100)
    allow_student_upload = models.BooleanField(default=True)
    allow_onlyoffice_edit = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_group_collaborations",
    )
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["grouping_strategy", "updated_at"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.session} - 小组合作"


class ClassroomGroup(models.Model):
    collaboration = models.ForeignKey(
        ClassroomGroupCollaboration,
        on_delete=models.CASCADE,
        related_name="groups",
    )
    group_no = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=64)
    layer_hint = models.CharField(max_length=32, blank=True)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_classroom_groups",
    )
    collaboration_document = models.FileField(upload_to=classroom_group_document_upload_path, blank=True)
    document_original_name = models.CharField(max_length=128, blank=True)
    document_file_ext = models.CharField(max_length=8, blank=True)
    document_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collaboration", "group_no"], name="uniq_classroom_group_no_per_collaboration"),
        ]
        indexes = [
            models.Index(fields=["collaboration", "group_no"]),
        ]
        ordering = ["collaboration_id", "group_no", "id"]

    def __str__(self) -> str:
        return self.name


class ClassroomGroupMember(models.Model):
    class Role(models.TextChoices):
        LEADER = "leader", "组长"
        MEMBER = "member", "成员"

    collaboration = models.ForeignKey(
        ClassroomGroupCollaboration,
        on_delete=models.CASCADE,
        related_name="members",
    )
    group = models.ForeignKey(ClassroomGroup, on_delete=models.CASCADE, related_name="members")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="classroom_group_memberships")
    student_profile = models.ForeignKey(
        "school.StudentProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classroom_group_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collaboration", "student"], name="uniq_student_per_group_collaboration"),
            models.UniqueConstraint(fields=["group", "student"], name="uniq_student_per_classroom_group"),
        ]
        indexes = [
            models.Index(fields=["collaboration", "student"]),
            models.Index(fields=["group", "role"]),
        ]
        ordering = ["group__group_no", "role", "student__display_name", "student__username"]

    def __str__(self) -> str:
        return f"{self.group} - {self.student}"


class ClassroomGroupFile(models.Model):
    group = models.ForeignKey(ClassroomGroup, on_delete=models.CASCADE, related_name="files")
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_classroom_group_files",
    )
    attachment = models.FileField(upload_to=classroom_group_file_upload_path)
    original_name = models.CharField(max_length=255)
    file_ext = models.CharField(max_length=16, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["group", "created_at"]),
            models.Index(fields=["uploader", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.original_name


class ClassroomEvaluationConfig(models.Model):
    course = models.OneToOneField(
        Course,
        on_delete=models.CASCADE,
        related_name="evaluation_config",
    )
    enable_self = models.BooleanField(default=False)
    enable_peer = models.BooleanField(default=False)
    enable_teacher = models.BooleanField(default=False)
    self_criteria = models.JSONField(default=list, blank=True)
    peer_criteria = models.JSONField(default=list, blank=True)
    teacher_criteria = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_course_evaluation_configs",
    )
    opened_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["enable_self", "enable_peer", "enable_teacher"]),
            models.Index(fields=["updated_at"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.course} - 课程评价"


class ClassroomEvaluationSubmission(models.Model):
    class EvaluationType(models.TextChoices):
        SELF = "self", "自评"
        PEER = "peer", "互评"
        TEACHER = "teacher", "师评"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="evaluation_submissions")
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluation_submissions",
    )
    session = models.ForeignKey(
        ClassroomSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="evaluation_submissions",
    )
    evaluation_type = models.CharField(max_length=16, choices=EvaluationType.choices)
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="classroom_evaluations_given",
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="classroom_evaluations_received",
    )
    group = models.ForeignKey(
        ClassroomGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluation_submissions",
    )
    ratings = models.JSONField(default=dict)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "evaluation_type", "evaluator", "target"],
                condition=Q(session__isnull=False),
                name="uniq_classroom_evaluation_submission",
            ),
            models.UniqueConstraint(
                fields=["course", "evaluation_type", "evaluator", "target"],
                condition=Q(session__isnull=True),
                name="uniq_course_evaluation_submission",
            ),
        ]
        indexes = [
            models.Index(fields=["course", "evaluation_type", "updated_at"]),
            models.Index(fields=["class_group", "evaluation_type", "updated_at"]),
            models.Index(fields=["session", "evaluation_type", "updated_at"]),
            models.Index(fields=["target", "updated_at"]),
            models.Index(fields=["group", "evaluation_type"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        scope = self.session_id or f"course:{self.course_id}"
        return f"{scope}:{self.evaluation_type}:{self.evaluator_id}->{self.target_id}"


class Activity(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="activities")
    title = models.CharField(max_length=128)
    content = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["lesson_id", "sort_order", "id"]

    def __str__(self) -> str:
        return self.title

# Create your models here.
