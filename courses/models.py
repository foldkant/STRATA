import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def classroom_group_document_upload_path(instance, filename: str) -> str:
    collaboration = instance.collaboration
    session = collaboration.session
    school_id = session.school_id or "unknown"
    class_id = session.class_group_id or "unknown"
    session_id = session.id or "unknown"
    group_id = instance.id or "unknown"
    suffix = (
        str(filename or "").rsplit(".", 1)[-1].lower()
        if "." in str(filename or "")
        else collaboration.document_type
    )
    return f"classroom_group_docs/school_{school_id}/class_{class_id}/session_{session_id}/group_{group_id}/collaboration.{suffix}"


def classroom_group_document_version_upload_path(instance, filename: str) -> str:
    group = instance.group
    session = group.collaboration.session
    school_id = session.school_id or "unknown"
    class_id = session.class_group_id or "unknown"
    session_id = session.id or "unknown"
    group_id = group.id or "unknown"
    suffix = (
        str(filename or "").rsplit(".", 1)[-1].lower()
        if "." in str(filename or "")
        else group.collaboration.document_type
    )
    return (
        f"classroom_group_docs/school_{school_id}/class_{class_id}/"
        f"session_{session_id}/group_{group_id}/versions/"
        f"version_{instance.version_no}.{suffix}"
    )


def classroom_group_file_upload_path(instance, filename: str) -> str:
    group = instance.group
    session = group.collaboration.session
    school_id = session.school_id or "unknown"
    class_id = session.class_group_id or "unknown"
    session_id = session.id or "unknown"
    group_id = group.id or "unknown"
    uploader_id = instance.uploader_id or "unknown"
    return f"classroom_group_files/school_{school_id}/class_{class_id}/session_{session_id}/group_{group_id}/user_{uploader_id}/{filename}"


def resource_extra_file_upload_path(instance, filename: str) -> str:
    resource = instance.resource
    school_id = resource.owner.school_id or "unknown"
    resource_id = resource.id or "unknown"
    return f"resources/school_{school_id}/resource_{resource_id}/extras/{filename}"


def resource_document_version_upload_path(instance, filename: str) -> str:
    resource = instance.resource
    school_id = resource.owner.school_id or "unknown"
    resource_id = resource.id or "unknown"
    suffix = (
        str(filename or "").rsplit(".", 1)[-1].lower()
        if "." in str(filename or "")
        else "bin"
    )
    return (
        f"resources/school_{school_id}/resource_{resource_id}/versions/"
        f"version_{instance.version_no}.{suffix}"
    )


class Subject(models.Model):
    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="subjects"
    )
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
            models.UniqueConstraint(
                fields=["school", "code"], name="uniq_subject_code_per_school"
            ),
            models.UniqueConstraint(
                fields=["school", "name"], name="uniq_subject_name_per_school"
            ),
        ]
        ordering = ["school_id", "name"]

    def __str__(self) -> str:
        return self.name


class Course(models.Model):
    class TeachingModel(models.TextChoices):
        PROJECT = "pbl", "项目式学习"
        TASK = "tbl", "任务驱动学习"

    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT, null=True, blank=True, related_name="courses"
    )
    title = models.CharField(max_length=128)
    introduction = models.TextField(blank=True)
    cover = models.ImageField(upload_to="course_covers/", blank=True)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="courses"
    )
    teaching_model = models.CharField(
        max_length=16, choices=TeachingModel.choices, default=TeachingModel.PROJECT
    )
    is_active = models.BooleanField(default=False)
    legacy_id = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class CourseClass(models.Model):
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="course_classes"
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, related_name="course_classes"
    )
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
            models.UniqueConstraint(
                fields=["course", "class_group"], name="uniq_course_class_group"
            ),
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
    step_type = models.CharField(
        max_length=32, choices=StepType.choices, default=StepType.RESOURCE
    )
    student_instruction = models.TextField(blank=True)
    teacher_note = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)
    estimated_minutes = models.PositiveIntegerField(default=10)
    target_layer = models.CharField(
        max_length=16, choices=TargetLayer.choices, default=TargetLayer.ALL
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
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

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="learning_web_pages"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="learning_web_pages",
        limit_choices_to={"role": "teacher"},
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="learning_web_pages"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="learning_web_pages"
    )
    title = models.CharField(max_length=128)
    schema = models.JSONField(default=dict)
    generation_prompt = models.TextField(blank=True)
    revision_no = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.READY
    )
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
    page = models.ForeignKey(
        LearningWebPage, on_delete=models.CASCADE, related_name="versions"
    )
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
            models.UniqueConstraint(
                fields=["page", "version_no"], name="uniq_learning_web_page_version"
            ),
        ]
        ordering = ["-version_no", "-id"]

    def __str__(self) -> str:
        return f"{self.page} v{self.version_no}"


class LearningWebPageResponse(models.Model):
    analytics_attempt_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False
    )
    school = models.ForeignKey(
        "school.School",
        on_delete=models.CASCADE,
        related_name="learning_web_page_responses",
    )
    page = models.ForeignKey(
        LearningWebPage, on_delete=models.PROTECT, related_name="responses"
    )
    page_version = models.PositiveIntegerField(default=1)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="learning_web_page_responses",
        limit_choices_to={"role": "student"},
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="learning_web_page_responses",
    )
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="learning_web_page_responses"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.PROTECT, related_name="learning_web_page_responses"
    )
    lesson_step = models.ForeignKey(
        LessonStep, on_delete=models.PROTECT, related_name="learning_web_page_responses"
    )
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

    school = models.ForeignKey(
        "school.School", on_delete=models.CASCADE, related_name="classroom_sessions"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="classroom_sessions",
        limit_choices_to={"role": "teacher"},
    )
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="classroom_sessions"
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="classroom_sessions",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup", on_delete=models.PROTECT, related_name="classroom_sessions"
    )
    title = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    current_step = models.ForeignKey(
        LessonStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    current_step_status = models.CharField(
        max_length=16, choices=StepStatus.choices, default=StepStatus.IDLE
    )
    submission_locked = models.BooleanField(default=False)
    is_layered = models.BooleanField(default=False)
    evaluation_enabled = models.BooleanField(default=False)
    evaluation_config_version = models.ForeignKey(
        "ClassroomEvaluationConfigVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="classroom_sessions",
    )
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

    session = models.ForeignKey(
        ClassroomSession, on_delete=models.CASCADE, related_name="activities"
    )
    activity_type = models.CharField(max_length=32, choices=ActivityType.choices)
    title = models.CharField(max_length=128)
    content = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
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
    class ResourceType(models.TextChoices):
        FILE = "file", "文件资源"
        ARTICLE = "article", "图文内容"
        LINK = "link", "外部链接"
        STUDENT_PROJECT = "student_project", "学生项目"

    class Category(models.TextChoices):
        COURSEWARE = "courseware", "课件素材"
        EXTRACURRICULAR = "extracurricular", "课外拓展"
        COMPETITION = "competition", "竞赛资源"
        PROJECT = "project", "学生项目"
        REFERENCE = "reference", "参考资料"
        TOOLKIT = "toolkit", "工具素材"
        OTHER = "other", "其他"

    class Visibility(models.TextChoices):
        PRIVATE = "private", "仅自己"
        CLASSES = "classes", "指定班级"
        SCHOOL = "school", "本校共享"
        EXTERNAL = "external", "跨校共享"

    class PublishStatus(models.TextChoices):
        PUBLISHED = "published", "已发布"
        PENDING = "pending", "待审核"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已退回"
        ARCHIVED = "archived", "已归档"

    class ProjectType(models.TextChoices):
        INDIVIDUAL = "individual", "个人项目"
        GROUP = "group", "小组项目"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=128)
    content = models.TextField(blank=True)
    attachment = models.FileField(upload_to="resources/", blank=True)
    cover = models.ImageField(upload_to="resource_covers/", blank=True)
    resource_type = models.CharField(
        max_length=24, choices=ResourceType.choices, default=ResourceType.FILE
    )
    category = models.CharField(
        max_length=24, choices=Category.choices, default=Category.COURSEWARE
    )
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    publish_status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.PUBLISHED
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resources",
    )
    target_classes = models.ManyToManyField(
        "school.ClassGroup", blank=True, related_name="shared_resources"
    )
    grade_scope = models.CharField(max_length=128, blank=True)
    tags = models.JSONField(default=list, blank=True)
    external_url = models.URLField(max_length=500, blank=True)
    project_type = models.CharField(
        max_length=16, choices=ProjectType.choices, blank=True
    )
    project_members = models.JSONField(default=list, blank=True)
    project_course = models.CharField(max_length=128, blank=True)
    competition_name = models.CharField(max_length=128, blank=True)
    competition_year = models.PositiveSmallIntegerField(null=True, blank=True)
    award_level = models.CharField(max_length=128, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="resources"
    )
    view_count = models.PositiveIntegerField(default=0)
    is_pinned = models.BooleanField(default=False)
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_resources",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["visibility", "publish_status", "updated_at"]),
            models.Index(fields=["resource_type", "category", "updated_at"]),
        ]
        ordering = ["-is_pinned", "-created_at"]

    def __str__(self) -> str:
        return self.title


class ResourceDocumentVersion(models.Model):
    class Source(models.TextChoices):
        INITIAL = "initial", "初始文件"
        ONLYOFFICE_CALLBACK = "onlyoffice_callback", "OnlyOffice 保存"

    resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name="document_versions",
    )
    version_no = models.PositiveIntegerField()
    file = models.FileField(upload_to=resource_document_version_upload_path)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.PositiveBigIntegerField(default=0)
    source = models.CharField(max_length=32, choices=Source.choices)
    callback_status = models.PositiveSmallIntegerField(null=True, blank=True)
    callback_key = models.CharField(max_length=255, blank=True)
    verified_editor_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "version_no"],
                name="uniq_resource_document_version",
            ),
        ]
        indexes = [
            models.Index(fields=["resource", "created_at"]),
            models.Index(fields=["file_sha256"]),
        ]
        ordering = ["resource_id", "version_no"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("资源文档版本是不可变记录，不能原地修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("资源文档版本不能单独删除。")

    def __str__(self) -> str:
        return f"{self.resource} v{self.version_no}"


class ResourceFile(models.Model):
    class Role(models.TextChoices):
        SUPPLEMENT = "supplement", "补充附件"
        PROCESS = "process", "项目过程材料"

    resource = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="extra_files"
    )
    file = models.FileField(upload_to=resource_extra_file_upload_path)
    original_name = models.CharField(max_length=255)
    file_ext = models.CharField(max_length=16, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    role = models.CharField(
        max_length=16, choices=Role.choices, default=Role.SUPPLEMENT
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["resource", "role", "sort_order"])]
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.original_name


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
        STABLE_PROJECT = "stable_project", "项目稳定分组"

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
        default=GroupingStrategy.RANDOM,
    )
    active_plan_version = models.PositiveIntegerField(default=1)
    strategy_version = models.CharField(max_length=32, default="group-policy-v2")
    generation_metadata = models.JSONField(default=dict, blank=True)
    document_type = models.CharField(
        max_length=8, choices=DocumentType.choices, default=DocumentType.DOCX
    )
    storage_quota_mb = models.PositiveIntegerField(default=20)
    allow_student_upload = models.BooleanField(default=True)
    allow_onlyoffice_edit = models.BooleanField(default=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
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
    plan_version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    name = models.CharField(max_length=64)
    layer_hint = models.CharField(max_length=32, blank=True)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_classroom_groups",
    )
    collaboration_document = models.FileField(
        upload_to=classroom_group_document_upload_path, blank=True
    )
    document_original_name = models.CharField(max_length=128, blank=True)
    document_file_ext = models.CharField(max_length=8, blank=True)
    document_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["collaboration", "plan_version", "group_no"],
                name="uniq_classroom_group_no_per_plan",
            ),
        ]
        indexes = [
            models.Index(fields=["collaboration", "is_active", "group_no"]),
            models.Index(fields=["collaboration", "plan_version", "group_no"]),
        ]
        ordering = ["collaboration_id", "group_no", "id"]

    def __str__(self) -> str:
        return self.name


class ClassroomGroupDocumentVersion(models.Model):
    class Source(models.TextChoices):
        INITIAL = "initial", "初始文档"
        ONLYOFFICE_CALLBACK = "onlyoffice_callback", "ONLYOFFICE 回调"

    group = models.ForeignKey(
        ClassroomGroup,
        on_delete=models.CASCADE,
        related_name="document_versions",
    )
    version_no = models.PositiveIntegerField()
    file = models.FileField(upload_to=classroom_group_document_version_upload_path)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.PositiveBigIntegerField(default=0)
    source = models.CharField(max_length=32, choices=Source.choices)
    callback_status = models.PositiveSmallIntegerField(null=True, blank=True)
    callback_key = models.CharField(max_length=255, blank=True)
    verified_editor_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "version_no"],
                name="uniq_classroom_group_document_version",
            ),
        ]
        indexes = [
            models.Index(fields=["group", "created_at"]),
            models.Index(fields=["file_sha256"]),
        ]
        ordering = ["group_id", "version_no"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("小组协作文档版本是不可变证据，不能原地修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("小组协作文档版本不能单独删除。")

    def __str__(self) -> str:
        return f"{self.group} v{self.version_no}"


class ClassroomGroupMember(models.Model):
    class Role(models.TextChoices):
        LEADER = "leader", "组长"
        MEMBER = "member", "成员"
        COORDINATOR = "coordinator", "协调"
        RECORDER = "recorder", "记录"
        RESOURCE = "resource", "资源"
        PRESENTER = "presenter", "展示"
        VERIFIER = "verifier", "核验"

    collaboration = models.ForeignKey(
        ClassroomGroupCollaboration,
        on_delete=models.CASCADE,
        related_name="members",
    )
    group = models.ForeignKey(
        ClassroomGroup, on_delete=models.CASCADE, related_name="members"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="classroom_group_memberships",
    )
    student_profile = models.ForeignKey(
        "school.StudentProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classroom_group_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    plan_version = models.PositiveIntegerField(default=1)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["collaboration", "student", "plan_version"],
                name="uniq_student_per_group_plan",
            ),
            models.UniqueConstraint(
                fields=["group", "student"], name="uniq_student_per_classroom_group"
            ),
        ]
        indexes = [
            models.Index(fields=["collaboration", "student"]),
            models.Index(fields=["group", "role"]),
        ]
        ordering = [
            "group__group_no",
            "role",
            "student__display_name",
            "student__username",
        ]

    def __str__(self) -> str:
        return f"{self.group} - {self.student}"


class ClassroomGroupFile(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    analytics_attempt_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False
    )
    version_no = models.PositiveIntegerField(default=1)
    group = models.ForeignKey(
        ClassroomGroup, on_delete=models.CASCADE, related_name="files"
    )
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
    """Legacy course-level evaluation configuration kept for historical reads only."""

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
    legacy_only = models.BooleanField(default=True, editable=False)
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


class ClassroomEvaluationConfigVersion(models.Model):
    """Legacy immutable snapshot kept for submissions created before standard binding."""

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="evaluation_config_versions",
    )
    version_no = models.PositiveIntegerField()
    config_hash = models.CharField(max_length=64)
    enable_self = models.BooleanField(default=False)
    enable_peer = models.BooleanField(default=False)
    enable_teacher = models.BooleanField(default=False)
    self_criteria = models.JSONField(default=list, blank=True)
    peer_criteria = models.JSONField(default=list, blank=True)
    teacher_criteria = models.JSONField(default=list, blank=True)
    legacy_only = models.BooleanField(default=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_evaluation_config_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "version_no"],
                name="uniq_course_evaluation_version_no",
            ),
            models.UniqueConstraint(
                fields=["course", "config_hash"],
                name="uniq_course_evaluation_config_hash",
            ),
        ]
        indexes = [models.Index(fields=["course", "created_at"])]
        ordering = ["-version_no", "-id"]

    def __str__(self) -> str:
        return f"{self.course} - 评价评价标准 v{self.version_no}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("已发布评价评价标准版本不可修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已发布评价评价标准版本不可删除。")


class ClassroomEvaluationSubmission(models.Model):
    class EvaluationType(models.TextChoices):
        SELF = "self", "自评"
        PEER = "peer", "互评"
        TEACHER = "teacher", "师评"

    class NotAssessedReason(models.TextChoices):
        NO_EVIDENCE = "no_evidence", "缺少作品或答案"
        NOT_OBSERVED = "not_observed", "本节未安排或未观察到"
        NOT_APPLICABLE = "not_applicable", "不适用于当前任务"
        TECHNICAL_ISSUE = "technical_issue", "技术或数据问题"
        OTHER = "other", "其他"

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="evaluation_submissions"
    )
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
    evaluation_version = models.ForeignKey(
        ClassroomEvaluationConfigVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submissions",
    )
    standard_use = models.ForeignKey(
        "learning_analytics.ClassroomEvaluationStandardUse",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submissions",
    )
    legacy_compatible = models.BooleanField(default=False, editable=False)
    submission_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    submission_version = models.PositiveIntegerField(default=1)
    analytics_attempt_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revisions",
    )
    ratings = models.JSONField(default=dict, blank=True)
    not_assessed = models.JSONField(default=dict, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "session",
                    "evaluation_type",
                    "evaluator",
                    "target",
                    "submission_version",
                ],
                condition=Q(session__isnull=False),
                name="uniq_classroom_evaluation_submission_version",
            ),
            models.UniqueConstraint(
                fields=[
                    "course",
                    "evaluation_type",
                    "evaluator",
                    "target",
                    "submission_version",
                ],
                condition=Q(session__isnull=True),
                name="uniq_course_evaluation_submission_version",
            ),
        ]
        indexes = [
            models.Index(fields=["course", "evaluation_type", "updated_at"]),
            models.Index(fields=["class_group", "evaluation_type", "updated_at"]),
            models.Index(fields=["session", "evaluation_type", "updated_at"]),
            models.Index(fields=["target", "updated_at"]),
            models.Index(fields=["group", "evaluation_type"]),
            models.Index(fields=["standard_use", "evaluation_type", "updated_at"]),
        ]
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        scope = self.session_id or f"course:{self.course_id}"
        return f"{scope}:{self.evaluation_type}:{self.evaluator_id}->{self.target_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("评价提交版本不可修改，请追加修订版本。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if not isinstance(self.ratings, dict):
            errors["ratings"] = "评价星级必须是 JSON 对象。"
        if not isinstance(self.not_assessed, dict):
            errors["not_assessed"] = "暂不评价原因必须是 JSON 对象。"
        if isinstance(self.ratings, dict) and isinstance(self.not_assessed, dict):
            overlap = set(map(str, self.ratings)) & set(map(str, self.not_assessed))
            if overlap:
                errors["not_assessed"] = "同一评价指标不能同时评分和暂不评价。"
        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        raise ValidationError("评价提交版本不可直接删除。")


class Activity(models.Model):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="activities"
    )
    title = models.CharField(max_length=128)
    content = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["lesson_id", "sort_order", "id"]

    def __str__(self) -> str:
        return self.title


# Create your models here.
