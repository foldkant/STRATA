from django.conf import settings
from django.db import models


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
