from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def canonical_hash(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ImmutableResearchQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("已冻结的研究记录不可批量修改。")

    def delete(self):
        raise ValidationError("已冻结的研究记录不可批量删除。")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("已冻结的研究记录不可批量修改。")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, **kwargs):
        raise ValidationError("研究记录必须逐项校验后保存。")


class ImmutableResearchRecord(models.Model):
    objects = ImmutableResearchQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("已冻结的研究记录不可改写；请追加新记录。")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已冻结的研究记录不可删除。")


class ResearchStage(models.TextChoices):
    E1 = "E1", "内容与可用性研究"
    E2 = "E2", "回顾性测量与预测验证"
    E3 = "E3", "前瞻性影子运行"
    E4 = "E4", "有限咨询试点"
    E5 = "E5", "冻结政策集群试验"
    E6 = "E6", "外部独立确认"


class ResearchStudy(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        REGISTERED = "registered", "已登记"
        ACTIVE = "active", "实施中"
        CLOSED = "closed", "已结束"
        ARCHIVED = "archived", "已归档"

    school = models.ForeignKey(
        "school.School", on_delete=models.PROTECT, related_name="research_studies"
    )
    code = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    subject = models.ForeignKey(
        "courses.Subject",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="research_studies",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="research_studies",
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    current_protocol = models.ForeignKey(
        "ResearchProtocolVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_studies",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_research_studies",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_research_studies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "code"], name="uniq_research_study_code_school"
            )
        ]
        indexes = [models.Index(fields=["school", "status", "created_at"])]
        ordering = ["-created_at", "-id"]

    def clean(self):
        errors = {}
        if self.subject_id and self.subject.school_id != self.school_id:
            errors["subject"] = "研究学科必须属于当前学校。"
        if self.course_id:
            if self.course.subject.school_id != self.school_id:
                errors["course"] = "研究课程必须属于当前学校。"
            elif self.subject_id and self.course.subject_id != self.subject_id:
                errors["course"] = "研究课程与研究学科不一致。"
        for field in ("created_by", "updated_by"):
            actor = getattr(self, field, None)
            if actor and actor.school_id != self.school_id:
                errors[field] = "研究登记人必须属于当前学校。"
        if self.current_protocol_id and self.current_protocol.study_id != self.pk:
            errors["current_protocol"] = "当前协议版本不属于本研究。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and previous.status != self.Status.DRAFT:
                changed = any(
                    getattr(previous, field) != getattr(self, field)
                    for field in (
                        "school_id",
                        "code",
                        "title",
                        "subject_id",
                        "course_id",
                        "description",
                    )
                )
                if changed:
                    raise ValidationError(
                        "研究登记后基本信息不可原地修改；请登记新的协议版本。"
                    )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT or self.protocol_versions.exists():
            raise ValidationError("已登记的研究不可删除。")
        return super().delete(*args, **kwargs)


class ResearchProtocolVersion(ImmutableResearchRecord):
    class DesignType(models.TextChoices):
        BLIND_REVIEW = "blind_review", "独立盲评"
        COGNITIVE_INTERVIEW = "cognitive_interview", "认知访谈"
        RETROSPECTIVE = "retrospective", "回顾性验证"
        SHADOW = "shadow", "影子运行"
        CONSULTATION = "consultation", "有限咨询试点"
        CLUSTER_TRIAL = "cluster_trial", "平行集群试验"
        STEPPED_WEDGE = "stepped_wedge", "阶梯楔形集群试验"
        EXTERNAL_CONFIRMATION = "external_confirmation", "外部独立确认"

    study = models.ForeignKey(
        ResearchStudy, on_delete=models.PROTECT, related_name="protocol_versions"
    )
    version_no = models.PositiveIntegerField()
    stage = models.CharField(max_length=2, choices=ResearchStage.choices)
    design_type = models.CharField(max_length=32, choices=DesignType.choices)
    protocol = models.JSONField(default=dict)
    policy_snapshot = models.JSONField(default=dict, blank=True)
    policy_hash = models.CharField(max_length=64, blank=True, db_index=True)
    ethics_approval_ref = models.CharField(max_length=160, blank=True)
    ethics_approved_at = models.DateField(null=True, blank=True)
    preregistration_ref = models.CharField(max_length=255, blank=True)
    preregistered_at = models.DateTimeField(null=True, blank=True)
    consent_required = models.BooleanField(default=True)
    consent_plan = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registered_research_protocols",
    )
    registered_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["study", "version_no"],
                name="uniq_research_protocol_version_no",
            ),
            models.UniqueConstraint(
                fields=["study", "content_hash"],
                name="uniq_research_protocol_content_hash",
            ),
        ]
        indexes = [models.Index(fields=["stage", "design_type", "registered_at"])]
        ordering = ["-version_no", "-id"]

    def semantic_content(self):
        return {
            "study_id": self.study_id,
            "version_no": self.version_no,
            "stage": self.stage,
            "design_type": self.design_type,
            "protocol": self.protocol,
            "policy_snapshot": self.policy_snapshot,
            "policy_hash": self.policy_hash,
            "ethics_approval_ref": self.ethics_approval_ref,
            "ethics_approved_at": self.ethics_approved_at,
            "preregistration_ref": self.preregistration_ref,
            "preregistered_at": self.preregistered_at,
            "consent_required": self.consent_required,
            "consent_plan": self.consent_plan,
        }

    def clean(self):
        errors = {}
        if self.registered_by_id and self.registered_by.school_id != self.study.school_id:
            errors["registered_by"] = "协议登记人必须属于研究学校。"
        if self.policy_snapshot:
            expected_policy_hash = canonical_hash(self.policy_snapshot)
            if self.policy_hash != expected_policy_hash:
                errors["policy_hash"] = "冻结政策校验值不一致。"
        elif self.policy_hash:
            errors["policy_hash"] = "没有冻结政策时不能填写政策校验值。"
        expected_hash = canonical_hash(self.semantic_content())
        if self.content_hash != expected_hash:
            errors["content_hash"] = "研究协议内容校验值不一致。"
        if errors:
            raise ValidationError(errors)


class ResearchGateDecision(ImmutableResearchRecord):
    class Gate(models.TextChoices):
        ETHICS = "ethics", "伦理审批"
        PREREGISTRATION = "preregistration", "预注册"
        CONSENT = "consent", "知情与退出安排"
        INSTRUMENT_REVIEW = "instrument_review", "评价工具审查"
        RATER_TRAINING = "rater_training", "评分者培训"
        DATA_GOVERNANCE = "data_governance", "数据治理"
        DATA_QUALITY = "data_quality", "数据质量"
        POWER_ANALYSIS = "power_analysis", "功效分析"
        TEACHER_TRAINING = "teacher_training", "教师培训"
        SAFETY_MONITORING = "safety_monitoring", "安全监测"
        POLICY_FREEZE = "policy_freeze", "政策冻结"
        ALLOCATION = "allocation", "集群分配方案"
        EXTERNAL_INDEPENDENCE = "external_independence", "外部独立性"

    class Decision(models.TextChoices):
        APPROVED = "approved", "通过"
        CONDITIONAL = "conditional", "有条件通过"
        REJECTED = "rejected", "不通过"

    protocol = models.ForeignKey(
        ResearchProtocolVersion,
        on_delete=models.PROTECT,
        related_name="gate_decisions",
    )
    gate = models.CharField(max_length=32, choices=Gate.choices)
    sequence_no = models.PositiveIntegerField()
    decision = models.CharField(max_length=16, choices=Decision.choices)
    evidence_ref = models.CharField(max_length=255)
    note = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="research_gate_decisions",
    )
    decided_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["protocol", "gate", "sequence_no"],
                name="uniq_research_gate_sequence",
            )
        ]
        indexes = [models.Index(fields=["protocol", "gate", "decided_at"])]
        ordering = ["gate", "-sequence_no", "-id"]

    def semantic_content(self):
        return {
            "protocol_id": self.protocol_id,
            "protocol_hash": self.protocol.content_hash,
            "gate": self.gate,
            "sequence_no": self.sequence_no,
            "decision": self.decision,
            "evidence_ref": self.evidence_ref,
            "note": self.note,
            "decided_by_id": self.decided_by_id,
            "decided_at": self.decided_at,
        }

    def clean(self):
        errors = {}
        if self.decided_by_id and self.decided_by.school_id != self.protocol.study.school_id:
            errors["decided_by"] = "研究闸门确认人必须属于研究学校。"
        if self.content_hash != canonical_hash(self.semantic_content()):
            errors["content_hash"] = "研究闸门记录校验值不一致。"
        if errors:
            raise ValidationError(errors)


class ResearchCohortAssignment(ImmutableResearchRecord):
    class Arm(models.TextChoices):
        EXPERIMENT = "experiment", "实验组"
        CONTROL = "control", "对照组"
        OBSERVATIONAL = "observational", "观察组"
        EXTERNAL_CONFIRMATION = "external_confirmation", "外部确认组"

    class AllocationMethod(models.TextChoices):
        RANDOM = "random", "随机分配"
        STRATIFIED_RANDOM = "stratified_random", "分层随机分配"
        STEPPED_WEDGE = "stepped_wedge", "阶梯楔形分配"
        MATCHED = "matched", "匹配分配"
        OBSERVATIONAL = "observational", "观察性纳入"

    protocol = models.ForeignKey(
        ResearchProtocolVersion,
        on_delete=models.PROTECT,
        related_name="cohort_assignments",
    )
    class_group = models.ForeignKey(
        "school.ClassGroup",
        on_delete=models.PROTECT,
        related_name="research_cohort_assignments",
    )
    arm = models.CharField(max_length=24, choices=Arm.choices)
    allocation_method = models.CharField(
        max_length=24, choices=AllocationMethod.choices
    )
    allocation_unit_code = models.CharField(max_length=96)
    development_site = models.BooleanField(default=True)
    prior_policy_access = models.BooleanField(default=False)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="research_cohort_assignments",
    )
    assigned_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["protocol", "class_group"],
                name="uniq_research_protocol_class_group",
            ),
            models.UniqueConstraint(
                fields=["protocol", "allocation_unit_code"],
                name="uniq_research_allocation_unit_code",
            ),
        ]
        indexes = [models.Index(fields=["protocol", "arm"])]
        ordering = ["class_group__name", "id"]

    def semantic_content(self):
        return {
            "protocol_id": self.protocol_id,
            "protocol_hash": self.protocol.content_hash,
            "class_group_id": self.class_group_id,
            "arm": self.arm,
            "allocation_method": self.allocation_method,
            "allocation_unit_code": self.allocation_unit_code,
            "development_site": self.development_site,
            "prior_policy_access": self.prior_policy_access,
            "assigned_by_id": self.assigned_by_id,
            "assigned_at": self.assigned_at,
        }

    def clean(self):
        errors = {}
        study = self.protocol.study
        if self.class_group_id and self.class_group.school_id != study.school_id:
            errors["class_group"] = "研究班级必须属于研究学校。"
        if self.assigned_by_id and self.assigned_by.school_id != study.school_id:
            errors["assigned_by"] = "集群分配人必须属于研究学校。"
        if self.protocol.stage == ResearchStage.E6:
            if self.development_site or self.prior_policy_access:
                errors["development_site"] = (
                    "外部确认组必须标记为未参与开发且此前未接触冻结政策。"
                )
            if self.arm != self.Arm.EXTERNAL_CONFIRMATION:
                errors["arm"] = "E6 只能登记外部确认组。"
        if self.content_hash != canonical_hash(self.semantic_content()):
            errors["content_hash"] = "集群分配记录校验值不一致。"
        if errors:
            raise ValidationError(errors)


class ResearchRunQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("研究运行状态必须通过受控流程变更。")

    def delete(self):
        raise ValidationError("研究运行不可批量删除。")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("研究运行状态必须通过受控流程变更。")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, **kwargs):
        raise ValidationError("研究运行必须逐项校验后创建。")


class ResearchRun(models.Model):
    class Mode(models.TextChoices):
        BLIND_REVIEW = "blind_review", "独立盲评"
        COGNITIVE_INTERVIEW = "cognitive_interview", "认知访谈"
        RETROSPECTIVE = "retrospective", "回顾性验证"
        SHADOW = "shadow", "影子运行"
        CONSULTATION = "consultation", "有限咨询"
        CLUSTER_TRIAL = "cluster_trial", "集群试验"
        EXTERNAL_CONFIRMATION = "external_confirmation", "外部确认"

    class Status(models.TextChoices):
        PLANNED = "planned", "计划中"
        ACTIVE = "active", "实施中"
        PAUSED = "paused", "已暂停"
        CLOSED = "closed", "已结束"
        DATA_LOCKED = "data_locked", "数据已锁定"

    protocol = models.ForeignKey(
        ResearchProtocolVersion, on_delete=models.PROTECT, related_name="runs"
    )
    run_code = models.CharField(max_length=96)
    mode = models.CharField(max_length=32, choices=Mode.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PLANNED
    )
    decision_effect = models.BooleanField(default=False)
    automatic_action_enabled = models.BooleanField(default=False)
    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activated_research_runs",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_research_runs",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_research_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ResearchRunQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["protocol", "run_code"], name="uniq_research_run_code"
            )
        ]
        indexes = [models.Index(fields=["protocol", "status", "created_at"])]
        ordering = ["-created_at", "-id"]

    IMMUTABLE_AFTER_START = (
        "protocol_id",
        "run_code",
        "mode",
        "decision_effect",
        "automatic_action_enabled",
        "planned_start",
        "planned_end",
        "created_by_id",
    )

    def clean(self):
        errors = {}
        if self.created_by_id and self.created_by.school_id != self.protocol.study.school_id:
            errors["created_by"] = "研究运行创建人必须属于研究学校。"
        if self.automatic_action_enabled:
            errors["automatic_action_enabled"] = (
                "P6/P7 研究阶段不得启用自动分层、自动分组或自动发布。"
            )
        if self.mode == self.Mode.SHADOW and self.decision_effect:
            errors["decision_effect"] = "影子运行不得影响学生教学安排。"
        if self.protocol.stage in {ResearchStage.E1, ResearchStage.E2, ResearchStage.E3} and self.decision_effect:
            errors["decision_effect"] = "E1—E3 不得产生教学决策效应。"
        if self.planned_start and self.planned_end and self.planned_end <= self.planned_start:
            errors["planned_end"] = "计划结束时间必须晚于开始时间。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.status != self.Status.PLANNED and any(
                getattr(previous, field) != getattr(self, field)
                for field in self.IMMUTABLE_AFTER_START
            ):
                raise ValidationError("研究运行开始后不得改写协议、模式或作用边界。")
            if previous.status != self.status:
                valid_transition = (
                    previous.status == self.Status.PLANNED
                    and self.status == self.Status.ACTIVE
                    and self.activated_by_id
                    and self.activated_at
                ) or (
                    previous.status in {self.Status.ACTIVE, self.Status.PAUSED}
                    and self.status == self.Status.CLOSED
                    and self.closed_by_id
                    and self.closed_at
                ) or (
                    previous.status == self.Status.CLOSED
                    and self.status == self.Status.DATA_LOCKED
                    and hasattr(self, "data_lock")
                )
                if not valid_transition:
                    raise ValidationError(
                        "研究运行只能按计划、启动、结束、数据锁定的顺序转换。"
                    )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.PLANNED:
            raise ValidationError("已开始的研究运行不可删除。")
        return super().delete(*args, **kwargs)


class ResearchExposureRecord(ImmutableResearchRecord):
    class Exposure(models.TextChoices):
        ASSIGNED = "assigned", "按方案实施"
        NOT_DELIVERED = "not_delivered", "未实施"
        CROSSOVER = "crossover", "交叉暴露"
        PARTIAL = "partial", "部分实施"
        UNKNOWN = "unknown", "暂不确定"

    run = models.ForeignKey(
        ResearchRun, on_delete=models.PROTECT, related_name="exposure_records"
    )
    cohort_assignment = models.ForeignKey(
        ResearchCohortAssignment,
        on_delete=models.PROTECT,
        related_name="exposure_records",
    )
    observed_on = models.DateField()
    actual_exposure = models.CharField(max_length=24, choices=Exposure.choices)
    contamination_detected = models.BooleanField(default=False)
    implementation_fidelity = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    opportunity_summary = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="research_exposure_records",
    )
    recorded_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "cohort_assignment", "observed_on"],
                name="uniq_research_exposure_day",
            )
        ]
        indexes = [models.Index(fields=["run", "observed_on"])]
        ordering = ["observed_on", "cohort_assignment_id"]

    def semantic_content(self):
        return {
            "run_id": self.run_id,
            "protocol_hash": self.run.protocol.content_hash,
            "cohort_assignment_id": self.cohort_assignment_id,
            "cohort_hash": self.cohort_assignment.content_hash,
            "observed_on": self.observed_on,
            "actual_exposure": self.actual_exposure,
            "contamination_detected": self.contamination_detected,
            "implementation_fidelity": self.implementation_fidelity,
            "opportunity_summary": self.opportunity_summary,
            "note": self.note,
            "recorded_by_id": self.recorded_by_id,
            "recorded_at": self.recorded_at,
        }

    def clean(self):
        errors = {}
        if self.cohort_assignment.protocol_id != self.run.protocol_id:
            errors["cohort_assignment"] = "实际暴露记录与研究运行协议不一致。"
        if self.recorded_by_id and self.recorded_by.school_id != self.run.protocol.study.school_id:
            errors["recorded_by"] = "实际暴露记录人必须属于研究学校。"
        if self.implementation_fidelity is not None and not (
            0 <= self.implementation_fidelity <= 1
        ):
            errors["implementation_fidelity"] = "实施忠实度必须在 0—1 之间。"
        if self.content_hash != canonical_hash(self.semantic_content()):
            errors["content_hash"] = "实际暴露记录校验值不一致。"
        if errors:
            raise ValidationError(errors)


class ResearchDataLock(ImmutableResearchRecord):
    run = models.OneToOneField(
        ResearchRun, on_delete=models.PROTECT, related_name="data_lock"
    )
    decision_as_of = models.DateTimeField()
    data_cutoff = models.DateTimeField()
    dataset_manifest = models.JSONField(default=dict)
    variable_dictionary = models.JSONField(default=list)
    row_count = models.PositiveIntegerField(default=0)
    missingness_summary = models.JSONField(default=dict, blank=True)
    exclusion_summary = models.JSONField(default=dict, blank=True)
    dataset_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="research_data_locks",
    )
    locked_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-locked_at", "-id"]

    def semantic_content(self):
        return {
            "run_id": self.run_id,
            "protocol_hash": self.run.protocol.content_hash,
            "decision_as_of": self.decision_as_of,
            "data_cutoff": self.data_cutoff,
            "dataset_manifest": self.dataset_manifest,
            "variable_dictionary": self.variable_dictionary,
            "row_count": self.row_count,
            "missingness_summary": self.missingness_summary,
            "exclusion_summary": self.exclusion_summary,
            "dataset_hash": self.dataset_hash,
            "locked_by_id": self.locked_by_id,
            "locked_at": self.locked_at,
        }

    def clean(self):
        errors = {}
        if self.run.status != ResearchRun.Status.CLOSED:
            errors["run"] = "只有已经结束的研究运行才能锁定数据。"
        if self.data_cutoff > self.locked_at:
            errors["data_cutoff"] = "数据截止时间不能晚于锁定时间。"
        if self.decision_as_of > self.data_cutoff:
            errors["decision_as_of"] = "决策时间点不能晚于数据截止时间。"
        if self.locked_by_id and self.locked_by.school_id != self.run.protocol.study.school_id:
            errors["locked_by"] = "数据锁定人必须属于研究学校。"
        if self.content_hash != canonical_hash(self.semantic_content()):
            errors["content_hash"] = "研究数据锁校验值不一致。"
        if errors:
            raise ValidationError(errors)


class ResearchAnalysisRun(ImmutableResearchRecord):
    class Status(models.TextChoices):
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败并保留"

    data_lock = models.ForeignKey(
        ResearchDataLock, on_delete=models.PROTECT, related_name="analysis_runs"
    )
    analysis_key = models.CharField(max_length=96)
    status = models.CharField(max_length=16, choices=Status.choices)
    parameters = models.JSONField(default=dict)
    software_versions = models.JSONField(default=dict)
    result_summary = models.JSONField(default=dict, blank=True)
    failure_detail = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, db_index=True, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="completed_research_analysis_runs",
    )
    completed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["data_lock", "analysis_key"],
                name="uniq_research_analysis_key",
            )
        ]
        ordering = ["-completed_at", "-id"]

    def semantic_content(self):
        return {
            "data_lock_id": self.data_lock_id,
            "data_lock_hash": self.data_lock.content_hash,
            "analysis_key": self.analysis_key,
            "status": self.status,
            "parameters": self.parameters,
            "software_versions": self.software_versions,
            "result_summary": self.result_summary,
            "failure_detail": self.failure_detail,
            "completed_by_id": self.completed_by_id,
            "completed_at": self.completed_at,
        }

    def clean(self):
        errors = {}
        if self.completed_by_id and self.completed_by.school_id != self.data_lock.run.protocol.study.school_id:
            errors["completed_by"] = "分析完成人必须属于研究学校。"
        if self.status == self.Status.FAILED and not self.failure_detail:
            errors["failure_detail"] = "失败运行必须保留失败原因。"
        if self.content_hash != canonical_hash(self.semantic_content()):
            errors["content_hash"] = "研究分析记录校验值不一致。"
        if errors:
            raise ValidationError(errors)
