from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver


def _sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


class DiagnosticAdministrationQuerySet(models.QuerySet):
    def _assert_drafts(self):
        if self.exclude(status="draft").exists():
            raise ValidationError("已发布的诊断实施批次不可批量修改或删除。")

    def update(self, **kwargs):
        self._assert_drafts()
        return super().update(**kwargs)

    def delete(self):
        self._assert_drafts()
        return super().delete()


class ImmutableDiagnosticBindingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("诊断提交绑定不可批量修改。")

    def delete(self):
        raise ValidationError("诊断提交绑定不可批量删除。")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("诊断提交绑定不可批量修改。")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, **kwargs):
        raise ValidationError("诊断提交绑定必须逐项校验后保存。")


class DiagnosticAdministration(models.Model):
    """A frozen administration of one exact learning-entry diagnostic version."""

    class Purpose(models.TextChoices):
        ENTRY_DIAGNOSTIC = "entry_diagnostic", "学习起点诊断"
        RESEARCH_PRETEST = "research_pretest", "教育实验前测"
        RESEARCH_POSTTEST = "research_posttest", "教育实验后测"
        PILOT = "pilot", "诊断工具试测"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        CLOSED = "closed", "已关闭"

    school = models.ForeignKey(
        "school.School",
        on_delete=models.PROTECT,
        related_name="diagnostic_administrations",
    )
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        related_name="diagnostic_administrations",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="diagnostic_administrations",
    )
    paper_version = models.ForeignKey(
        "learning.PretestPaperVersion",
        on_delete=models.PROTECT,
        related_name="diagnostic_administrations",
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    batch_code = models.CharField(max_length=64)
    title = models.CharField(max_length=160)
    open_at = models.DateTimeField(null=True, blank=True)
    close_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    content_hash = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_diagnostic_administrations",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_diagnostic_administrations",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_diagnostic_administrations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    objects = DiagnosticAdministrationQuerySet.as_manager()

    IMMUTABLE_AFTER_PUBLISH = (
        "school_id",
        "subject_id",
        "course_id",
        "paper_version_id",
        "purpose",
        "batch_code",
        "title",
        "open_at",
        "close_at",
        "content_hash",
        "created_by_id",
        "created_at",
        "published_by_id",
        "published_at",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "batch_code"],
                name="uniq_diagnostic_batch_per_school",
            ),
            models.CheckConstraint(
                condition=Q(close_at__isnull=True)
                | Q(open_at__isnull=True)
                | Q(close_at__gt=models.F("open_at")),
                name="diagnostic_close_after_open",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="draft",
                        content_hash="",
                        published_by__isnull=True,
                        published_at__isnull=True,
                        closed_by__isnull=True,
                        closed_at__isnull=True,
                    )
                    | Q(
                        status="published",
                        content_hash__gt="",
                        published_by__isnull=False,
                        published_at__isnull=False,
                        closed_by__isnull=True,
                        closed_at__isnull=True,
                    )
                    | Q(
                        status="closed",
                        content_hash__gt="",
                        published_by__isnull=False,
                        published_at__isnull=False,
                        closed_by__isnull=False,
                        closed_at__isnull=False,
                    )
                ),
                name="diagnostic_lifecycle_fields_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "subject", "status"]),
            models.Index(fields=["course", "status"]),
            models.Index(fields=["purpose", "status", "open_at", "close_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.batch_code} - {self.title}"

    def assignment_snapshot(self) -> list[dict]:
        if not self.pk:
            return []
        return [
            {
                "class_group_id": item[0],
                "cohort_role": item[1],
                "opportunity_status": item[2],
            }
            for item in self.assignments.order_by("class_group_id").values_list(
                "class_group_id", "cohort_role", "opportunity_status"
            )
        ]

    def semantic_content(self, assignments: list[dict] | None = None) -> dict:
        version = self.paper_version
        return {
            "schema_version": 1,
            "administration_id": self.pk,
            "school_id": self.school_id,
            "subject_id": self.subject_id,
            "course_id": self.course_id,
            "purpose": self.purpose,
            "batch_code": self.batch_code,
            "title": self.title,
            "open_at": self.open_at,
            "close_at": self.close_at,
            "paper_version": {
                "id": self.paper_version_id,
                "source_id": version.source_id,
                "version_no": version.version_no,
                "content_hash": version.content_hash,
            },
            "assignments": assignments if assignments is not None else self.assignment_snapshot(),
        }

    def expected_content_hash(self, assignments: list[dict] | None = None) -> str:
        return _sha256(self.semantic_content(assignments))

    def clean(self):
        errors: dict[str, str] = {}
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "诊断实施的学科必须属于当前学校。"
        if self.course_id:
            if self.course.subject_id != self.subject_id:
                errors["course"] = "诊断实施的课程必须对应所选学科。"
            elif self.course.subject.school_id != self.school_id:
                errors["course"] = "诊断实施的课程必须属于当前学校。"
        if self.paper_version_id:
            paper = self.paper_version.source
            if paper.school_id != self.school_id:
                errors["paper_version"] = "诊断版本必须属于当前学校。"
            if paper.subject_id != self.subject_id:
                errors["paper_version"] = "诊断版本必须对应所选学科。"
        if self.open_at and self.close_at and self.close_at <= self.open_at:
            errors["close_at"] = "关闭时间必须晚于开放时间。"
        for field in ("created_by", "published_by", "closed_by"):
            user_id = getattr(self, f"{field}_id", None)
            if user_id and getattr(self, field).school_id not in {None, self.school_id}:
                errors[field] = "操作人必须属于当前学校。"
        if self.status == self.Status.DRAFT:
            if self.content_hash or self.published_by_id or self.published_at:
                errors["status"] = "草稿不能包含发布信息。"
            if self.closed_by_id or self.closed_at:
                errors["status"] = "草稿不能包含关闭信息。"
        elif self.status == self.Status.PUBLISHED:
            if not self.content_hash or not self.published_by_id or not self.published_at:
                errors["status"] = "发布时必须冻结内容校验值、发布人和发布时间。"
            if self.closed_by_id or self.closed_at:
                errors["status"] = "已发布且未关闭的批次不能包含关闭信息。"
        elif self.status == self.Status.CLOSED:
            if not all(
                [
                    self.content_hash,
                    self.published_by_id,
                    self.published_at,
                    self.closed_by_id,
                    self.closed_at,
                ]
            ):
                errors["status"] = "关闭批次必须保留完整的发布与关闭记录。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        original = None
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
        if original and original.status != self.Status.DRAFT:
            changed = [
                field
                for field in self.IMMUTABLE_AFTER_PUBLISH
                if getattr(original, field) != getattr(self, field)
            ]
            valid_close = (
                original.status == self.Status.PUBLISHED
                and self.status == self.Status.CLOSED
                and self.closed_by_id
                and self.closed_at
            )
            if changed or not (self.status == original.status or valid_close):
                raise ValidationError(
                    "已发布的诊断实施批次不可更换诊断版本、班级安排或实施口径。"
                )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("已发布的诊断实施批次不可删除。")
        return super().delete(*args, **kwargs)


class DiagnosticAdministrationAssignmentQuerySet(models.QuerySet):
    def _assert_drafts(self):
        if self.exclude(
            administration__status=DiagnosticAdministration.Status.DRAFT
        ).exists():
            raise ValidationError("已发布的班级指派不可批量修改或删除。")

    def update(self, **kwargs):
        self._assert_drafts()
        return super().update(**kwargs)

    def delete(self):
        self._assert_drafts()
        return super().delete()


class DiagnosticAdministrationAssignment(models.Model):
    class CohortRole(models.TextChoices):
        EXPERIMENT = "experiment", "实验班"
        CONTROL = "control", "对照班"
        UNASSIGNED = "unassigned", "未设置实验角色"

    class OpportunityStatus(models.TextChoices):
        OFFERED = "offered", "已提供评价机会"
        NOT_OFFERED = "not_offered", "未提供评价机会"

    administration = models.ForeignKey(
        DiagnosticAdministration,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="diagnostic_administration_assignments",
    )
    cohort_role = models.CharField(
        max_length=16,
        choices=CohortRole.choices,
        default=CohortRole.UNASSIGNED,
    )
    opportunity_status = models.CharField(
        max_length=16,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.OFFERED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = DiagnosticAdministrationAssignmentQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["administration", "class_group"],
                name="uniq_diagnostic_assignment_class",
            ),
        ]
        indexes = [
            models.Index(fields=["class_group", "opportunity_status"]),
            models.Index(fields=["administration", "cohort_role"]),
        ]
        ordering = ["administration_id", "class_group_id"]

    def clean(self):
        errors: dict[str, str] = {}
        if self.class_group_id and self.class_group.school_id != self.administration.school_id:
            errors["class_group"] = "诊断实施班级必须属于当前学校。"
        if self.administration.course_id and self.class_group_id:
            from courses.models import CourseClass

            if not CourseClass.objects.filter(
                course_id=self.administration.course_id,
                class_group_id=self.class_group_id,
            ).exists():
                errors["class_group"] = "诊断实施班级尚未关联所选课程。"
        if self.administration.status != DiagnosticAdministration.Status.DRAFT:
            errors["administration"] = "已发布的班级、实验角色和评价机会安排不可修改。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            current = type(self).objects.get(pk=self.pk)
            if current.administration.status != DiagnosticAdministration.Status.DRAFT:
                raise ValidationError("已发布的班级指派不可修改。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.administration.status != DiagnosticAdministration.Status.DRAFT:
            raise ValidationError("已发布的班级指派不可删除。")
        return super().delete(*args, **kwargs)


class DiagnosticSubmissionBinding(models.Model):
    """Immutable proof that a submission used the administration's exact version."""

    administration = models.ForeignKey(
        DiagnosticAdministration,
        on_delete=models.PROTECT,
        related_name="submission_bindings",
    )
    assignment = models.ForeignKey(
        DiagnosticAdministrationAssignment,
        on_delete=models.PROTECT,
        related_name="submission_bindings",
    )
    submission = models.OneToOneField(
        "learning.PretestSubmission",
        on_delete=models.PROTECT,
        related_name="diagnostic_binding",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="diagnostic_submission_bindings",
    )
    attempt_no = models.PositiveSmallIntegerField(default=1)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64, editable=False)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableDiagnosticBindingQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["administration", "student", "attempt_no"],
                name="uniq_diagnostic_student_attempt",
            ),
            models.UniqueConstraint(
                fields=["administration", "student", "idempotency_key"],
                name="uniq_diagnostic_student_idempotency",
            ),
            models.CheckConstraint(
                condition=Q(attempt_no__gt=0),
                name="diagnostic_attempt_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["administration", "student"]),
            models.Index(fields=["assignment", "created_at"]),
        ]
        ordering = ["administration_id", "student_id", "attempt_no"]

    def semantic_content(self) -> dict:
        return {
            "administration_id": self.administration_id,
            "administration_content_hash": self.administration.content_hash,
            "assignment_id": self.assignment_id,
            "submission_id": self.submission_id,
            "submission_content_hash": self.submission.content_hash,
            "student_id": self.student_id,
            "attempt_no": self.attempt_no,
            "idempotency_key": self.idempotency_key,
            "request_hash": self.request_hash,
            "paper_version_id": self.submission.paper_version_id,
        }

    def clean(self):
        errors: dict[str, str] = {}
        administration = self.administration
        assignment = self.assignment
        submission = self.submission
        if administration.status != DiagnosticAdministration.Status.PUBLISHED:
            errors["administration"] = "只能向当前已发布的诊断实施批次提交材料。"
        if assignment.administration_id != administration.id:
            errors["assignment"] = "班级指派不属于该诊断实施批次。"
        if assignment.opportunity_status != DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED:
            errors["assignment"] = "未提供评价机会的班级不能形成学生提交。"
        if submission.student_id != self.student_id:
            errors["student"] = "诊断提交与学生身份不一致。"
        if submission.attempt_no != self.attempt_no:
            errors["attempt_no"] = "诊断实施尝试序号与提交记录不一致。"
        if submission.paper_version_id != administration.paper_version_id:
            errors["submission"] = "诊断提交未绑定本批次冻结的诊断版本。"
        if submission.administration_id != administration.id:
            errors["submission"] = "诊断提交记录与实施批次绑定不一致。"
        if submission.idempotency_key != self.idempotency_key:
            errors["idempotency_key"] = "诊断提交与绑定记录的幂等标识不一致。"
        if submission.paper_id != administration.paper_version.source_id:
            errors["submission"] = "诊断提交与本批次冻结的诊断工具不一致。"
        if submission.subject_id != administration.subject_id:
            errors["submission"] = "诊断提交的学科与实施批次不一致。"
        if self.student.school_id != administration.school_id:
            errors["student"] = "学生与诊断实施学校不一致。"
        try:
            class_group_id = self.student.student_profile.class_group_id
        except (AttributeError, ObjectDoesNotExist):
            class_group_id = None
        if class_group_id != assignment.class_group_id:
            errors["student"] = "学生当前班级与诊断实施指派班级不一致。"
        if not self.idempotency_key.strip():
            errors["idempotency_key"] = "提交必须携带有效的幂等标识。"
        if len(self.request_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.request_hash.lower()
        ):
            errors["request_hash"] = "提交请求摘要格式不正确。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("诊断提交与实施批次的绑定不可修改。")
        self.content_hash = _sha256(self.semantic_content())
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("诊断提交与实施批次的绑定不可删除。")


# Imported lazily to keep model validation independent from the accounts app module.
from django.core.exceptions import ObjectDoesNotExist  # noqa: E402


@receiver(pre_delete, sender=DiagnosticAdministrationAssignment)
def _protect_published_diagnostic_assignment(sender, instance, **kwargs):
    if instance.administration.status != DiagnosticAdministration.Status.DRAFT:
        raise ValidationError("已发布的班级指派不可删除。")
