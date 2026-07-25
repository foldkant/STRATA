from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from courses.models import Course, CourseClass, Subject
from school.models import ClassGroup

from .models import (
    ResearchCohortAssignment,
    ResearchAnalysisRun,
    ResearchDataLock,
    ResearchExposureRecord,
    ResearchGateDecision,
    ResearchProtocolVersion,
    ResearchRun,
    ResearchStage,
    ResearchStudy,
    canonical_hash,
)


REQUIRED_PROTOCOL_FIELDS = {
    "research_questions": "希望回答的问题",
    "estimands": "需要比较的内容",
    "primary_outcomes": "主要观察内容",
    "safety_outcomes": "学生权益与实施影响",
    "inclusion_criteria": "参与范围",
    "exclusion_criteria": "不纳入分析的情形",
    "missing_data_plan": "缺测与材料不足的处理方法",
    "analysis_plan": "准备采用的分析方法",
    "stopping_rules": "暂停或终止实验的情形",
    "claim_boundary": "结果解释范围",
}


REQUIRED_GATES = {
    ResearchStage.E1: {
        ResearchGateDecision.Gate.ETHICS,
        ResearchGateDecision.Gate.CONSENT,
        ResearchGateDecision.Gate.INSTRUMENT_REVIEW,
        ResearchGateDecision.Gate.RATER_TRAINING,
    },
    ResearchStage.E2: {
        ResearchGateDecision.Gate.PREREGISTRATION,
        ResearchGateDecision.Gate.DATA_GOVERNANCE,
        ResearchGateDecision.Gate.DATA_QUALITY,
    },
    ResearchStage.E3: {
        ResearchGateDecision.Gate.ETHICS,
        ResearchGateDecision.Gate.PREREGISTRATION,
        ResearchGateDecision.Gate.CONSENT,
        ResearchGateDecision.Gate.DATA_QUALITY,
        ResearchGateDecision.Gate.TEACHER_TRAINING,
        ResearchGateDecision.Gate.SAFETY_MONITORING,
    },
    ResearchStage.E4: {
        ResearchGateDecision.Gate.ETHICS,
        ResearchGateDecision.Gate.PREREGISTRATION,
        ResearchGateDecision.Gate.CONSENT,
        ResearchGateDecision.Gate.DATA_QUALITY,
        ResearchGateDecision.Gate.TEACHER_TRAINING,
        ResearchGateDecision.Gate.SAFETY_MONITORING,
        ResearchGateDecision.Gate.POLICY_FREEZE,
    },
    ResearchStage.E5: {
        ResearchGateDecision.Gate.ETHICS,
        ResearchGateDecision.Gate.PREREGISTRATION,
        ResearchGateDecision.Gate.CONSENT,
        ResearchGateDecision.Gate.DATA_QUALITY,
        ResearchGateDecision.Gate.POWER_ANALYSIS,
        ResearchGateDecision.Gate.TEACHER_TRAINING,
        ResearchGateDecision.Gate.SAFETY_MONITORING,
        ResearchGateDecision.Gate.POLICY_FREEZE,
        ResearchGateDecision.Gate.ALLOCATION,
    },
    ResearchStage.E6: {
        ResearchGateDecision.Gate.ETHICS,
        ResearchGateDecision.Gate.PREREGISTRATION,
        ResearchGateDecision.Gate.CONSENT,
        ResearchGateDecision.Gate.DATA_QUALITY,
        ResearchGateDecision.Gate.SAFETY_MONITORING,
        ResearchGateDecision.Gate.POLICY_FREEZE,
        ResearchGateDecision.Gate.EXTERNAL_INDEPENDENCE,
    },
}


STAGE_MODES = {
    ResearchStage.E1: {
        ResearchRun.Mode.BLIND_REVIEW,
        ResearchRun.Mode.COGNITIVE_INTERVIEW,
    },
    ResearchStage.E2: {ResearchRun.Mode.RETROSPECTIVE},
    ResearchStage.E3: {ResearchRun.Mode.SHADOW},
    ResearchStage.E4: {ResearchRun.Mode.CONSULTATION},
    ResearchStage.E5: {ResearchRun.Mode.CLUSTER_TRIAL},
    ResearchStage.E6: {ResearchRun.Mode.EXTERNAL_CONFIRMATION},
}

STAGE_DESIGNS = {
    ResearchStage.E1: {
        ResearchProtocolVersion.DesignType.BLIND_REVIEW,
        ResearchProtocolVersion.DesignType.COGNITIVE_INTERVIEW,
    },
    ResearchStage.E2: {ResearchProtocolVersion.DesignType.RETROSPECTIVE},
    ResearchStage.E3: {ResearchProtocolVersion.DesignType.SHADOW},
    ResearchStage.E4: {ResearchProtocolVersion.DesignType.CONSULTATION},
    ResearchStage.E5: {
        ResearchProtocolVersion.DesignType.CLUSTER_TRIAL,
        ResearchProtocolVersion.DesignType.STEPPED_WEDGE,
    },
    ResearchStage.E6: {
        ResearchProtocolVersion.DesignType.EXTERNAL_CONFIRMATION
    },
}


def _require_school_actor(*, school, actor):
    if not actor or actor.school_id != school.id or actor.role != "school_admin":
        raise ValidationError("只有本校学校管理员可以管理教育实验。")


def _clean_text(value, *, field, max_length=None):
    result = str(value or "").strip()
    if not result:
        raise ValidationError({field: "此项不能为空。"})
    if max_length and len(result) > max_length:
        raise ValidationError({field: f"此项不能超过 {max_length} 个字符。"})
    return result


def _clean_date(value, *, field):
    if value is None or value == "":
        return None
    if hasattr(value, "year") and not hasattr(value, "hour"):
        return value
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValidationError({field: "请输入有效日期。"})
    return parsed


def _clean_datetime(value, *, field, required=False):
    if value is None or value == "":
        if required:
            raise ValidationError({field: "此项不能为空。"})
        return None
    if hasattr(value, "hour"):
        return value
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValidationError({field: "请输入包含时区的有效日期时间。"})
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@transaction.atomic
def create_study(*, school, actor, payload) -> ResearchStudy:
    _require_school_actor(school=school, actor=actor)
    code = _clean_text(payload.get("code"), field="code", max_length=64)
    title = _clean_text(payload.get("title"), field="title", max_length=200)
    if ResearchStudy.objects.filter(school=school, code=code).exists():
        raise ValidationError({"code": "本校已存在相同实验编号。"})
    subject = None
    course = None
    if payload.get("subject_id"):
        subject = Subject.objects.filter(
            pk=payload["subject_id"], school=school
        ).first()
        if subject is None:
            raise ValidationError({"subject_id": "实验学科不存在或不属于本校。"})
    if payload.get("course_id"):
        course = Course.objects.select_related("subject").filter(
            pk=payload["course_id"], subject__school=school
        ).first()
        if course is None:
            raise ValidationError({"course_id": "实验课程不存在或不属于本校。"})
        if subject and course.subject_id != subject.id:
            raise ValidationError({"course_id": "实验课程与所选学科不一致。"})
        subject = subject or course.subject
    study = ResearchStudy(
        school=school,
        code=code,
        title=title,
        subject=subject,
        course=course,
        description=str(payload.get("description") or "").strip(),
        created_by=actor,
        updated_by=actor,
    )
    study.save()
    return study


@transaction.atomic
def register_protocol(*, study_id: int, school, actor, payload) -> ResearchProtocolVersion:
    _require_school_actor(school=school, actor=actor)
    study = ResearchStudy.objects.select_for_update().get(pk=study_id, school=school)
    stage = str(payload.get("stage") or "").strip()
    design_type = str(payload.get("design_type") or "").strip()
    if stage not in ResearchStage.values:
        raise ValidationError({"stage": "请选择教育实验类型。"})
    if design_type not in ResearchProtocolVersion.DesignType.values:
        raise ValidationError({"design_type": "请选择有效的实验安排类型。"})
    if design_type not in STAGE_DESIGNS[stage]:
        raise ValidationError({"design_type": "实验安排方式与所选实验类型不一致。"})
    protocol = payload.get("protocol")
    if not isinstance(protocol, dict):
        raise ValidationError({"protocol": "教育实验方案内容格式不正确。"})
    missing = [label for key, label in REQUIRED_PROTOCOL_FIELDS.items() if not protocol.get(key)]
    if missing:
        raise ValidationError(
            {"protocol": "登记前必须完整填写：" + "、".join(missing) + "。"}
        )
    ethics_ref = str(payload.get("ethics_approval_ref") or "").strip()
    ethics_at = _clean_date(payload.get("ethics_approved_at"), field="ethics_approved_at")
    prereg_ref = str(payload.get("preregistration_ref") or "").strip()
    prereg_at = _clean_datetime(
        payload.get("preregistered_at"), field="preregistered_at"
    )
    if stage != ResearchStage.E2 and (not ethics_ref or not ethics_at):
        raise ValidationError(
            {"ethics_approval_ref": "涉及学生参与的前瞻性教育实验必须先登记伦理审查信息。"}
        )
    if stage in {ResearchStage.E2, ResearchStage.E3, ResearchStage.E4, ResearchStage.E5, ResearchStage.E6} and (
        not prereg_ref or not prereg_at
    ):
        raise ValidationError(
            {"preregistration_ref": "必须在查看实验结果前登记实验方案。"}
        )
    consent_required = bool(payload.get("consent_required", True))
    consent_plan = str(payload.get("consent_plan") or "").strip()
    if consent_required and not consent_plan:
        raise ValidationError({"consent_plan": "请说明知情、退出和未成年人保护安排。"})
    policy_snapshot = payload.get("policy_snapshot") or {}
    if not isinstance(policy_snapshot, dict):
        raise ValidationError({"policy_snapshot": "本次实际使用的教学与评价方案格式不正确。"})
    if stage in {ResearchStage.E4, ResearchStage.E5, ResearchStage.E6} and not policy_snapshot:
        raise ValidationError({"policy_snapshot": "教师辅助试用、班级对照实验和外校复核必须确认本次实际使用的教学与评价方案。"})
    if stage in {ResearchStage.E4, ResearchStage.E5, ResearchStage.E6}:
        required_policy_keys = {
            "evaluation_policy",
            "content_band_policy",
            "grouping_policy",
        }
        missing_policy = sorted(
            key for key in required_policy_keys if not policy_snapshot.get(key)
        )
        if missing_policy:
            raise ValidationError(
                {"policy_snapshot": "请完整填写本次使用的评价方案、动态分层规则和动态分组规则版本。"}
            )
    policy_hash = canonical_hash(policy_snapshot) if policy_snapshot else ""
    latest_no = (
        study.protocol_versions.order_by("-version_no").values_list("version_no", flat=True).first()
        or 0
    )
    now = timezone.now()
    version = ResearchProtocolVersion(
        study=study,
        version_no=latest_no + 1,
        stage=stage,
        design_type=design_type,
        protocol=protocol,
        policy_snapshot=policy_snapshot,
        policy_hash=policy_hash,
        ethics_approval_ref=ethics_ref,
        ethics_approved_at=ethics_at,
        preregistration_ref=prereg_ref,
        preregistered_at=prereg_at,
        consent_required=consent_required,
        consent_plan=consent_plan,
        registered_by=actor,
        registered_at=now,
    )
    version.content_hash = canonical_hash(version.semantic_content())
    duplicate = study.protocol_versions.filter(content_hash=version.content_hash).first()
    if duplicate:
        return duplicate
    version.save()
    study.current_protocol = version
    study.status = ResearchStudy.Status.REGISTERED
    study.updated_by = actor
    study.save(update_fields=["current_protocol", "status", "updated_by", "updated_at"])
    return version


@transaction.atomic
def record_gate_decision(*, protocol_id: int, school, actor, payload):
    _require_school_actor(school=school, actor=actor)
    protocol = ResearchProtocolVersion.objects.select_related("study").get(
        pk=protocol_id, study__school=school
    )
    gate = str(payload.get("gate") or "").strip()
    decision = str(payload.get("decision") or "").strip()
    if gate not in ResearchGateDecision.Gate.values:
        raise ValidationError({"gate": "开展条件类型无效。"})
    if decision not in ResearchGateDecision.Decision.values:
        raise ValidationError({"decision": "开展条件的核对结论无效。"})
    evidence_ref = _clean_text(
        payload.get("evidence_ref"), field="evidence_ref", max_length=255
    )
    sequence = (
        protocol.gate_decisions.filter(gate=gate)
        .order_by("-sequence_no")
        .values_list("sequence_no", flat=True)
        .first()
        or 0
    ) + 1
    now = timezone.now()
    record = ResearchGateDecision(
        protocol=protocol,
        gate=gate,
        sequence_no=sequence,
        decision=decision,
        evidence_ref=evidence_ref,
        note=str(payload.get("note") or "").strip(),
        decided_by=actor,
        decided_at=now,
    )
    record.content_hash = canonical_hash(record.semantic_content())
    record.save()
    return record


@transaction.atomic
def assign_cohort(*, protocol_id: int, school, actor, payload):
    _require_school_actor(school=school, actor=actor)
    protocol = ResearchProtocolVersion.objects.select_related(
        "study", "study__course"
    ).get(pk=protocol_id, study__school=school)
    if protocol.runs.exclude(status=ResearchRun.Status.PLANNED).exists():
        raise ValidationError("教育实验开始后不能直接追加或改写班级安排。")
    class_group = ClassGroup.objects.filter(
        pk=payload.get("class_group_id"), school=school
    ).first()
    if class_group is None:
        raise ValidationError({"class_group_id": "班级不存在或不属于本校。"})
    if protocol.study.course_id and not CourseClass.objects.filter(
        course_id=protocol.study.course_id, class_group=class_group
    ).exists():
        raise ValidationError({"class_group_id": "该班级未关联本次实验课程。"})
    arm = str(payload.get("arm") or "").strip()
    method = str(payload.get("allocation_method") or "").strip()
    if arm not in ResearchCohortAssignment.Arm.values:
        raise ValidationError({"arm": "该班级在实验中的安排无效。"})
    if method not in ResearchCohortAssignment.AllocationMethod.values:
        raise ValidationError({"allocation_method": "班级安排方法无效。"})
    if protocol.cohort_assignments.filter(class_group=class_group).exists():
        raise ValidationError({"class_group_id": "该班级已经纳入当前教育实验方案。"})
    now = timezone.now()
    assignment = ResearchCohortAssignment(
        protocol=protocol,
        class_group=class_group,
        arm=arm,
        allocation_method=method,
        allocation_unit_code=_clean_text(
            payload.get("allocation_unit_code"),
            field="allocation_unit_code",
            max_length=96,
        ),
        development_site=bool(payload.get("development_site", True)),
        prior_policy_access=bool(payload.get("prior_policy_access", False)),
        assigned_by=actor,
        assigned_at=now,
    )
    assignment.content_hash = canonical_hash(assignment.semantic_content())
    assignment.save()
    return assignment


def gate_status(protocol: ResearchProtocolVersion):
    latest = {}
    for record in protocol.gate_decisions.order_by("gate", "-sequence_no", "-id"):
        latest.setdefault(record.gate, record)
    required = REQUIRED_GATES[protocol.stage]
    approved = {
        gate
        for gate, record in latest.items()
        if record.decision == ResearchGateDecision.Decision.APPROVED
    }
    return {
        "required": sorted(required),
        "approved": sorted(approved),
        "missing": sorted(required - approved),
        "latest": latest,
    }


def _validate_cohort_gate(protocol: ResearchProtocolVersion):
    assignments = list(protocol.cohort_assignments.all())
    if protocol.stage in {ResearchStage.E3, ResearchStage.E4} and not assignments:
        raise ValidationError("开始前瞻性实施前，至少需要安排一个观察班或实施班级。")
    if protocol.stage == ResearchStage.E5:
        arms = {item.arm for item in assignments}
        if not {
            ResearchCohortAssignment.Arm.EXPERIMENT,
            ResearchCohortAssignment.Arm.CONTROL,
        }.issubset(arms):
            raise ValidationError("班级对照实验必须同时安排实验班和对照班。")
        if len(assignments) < 4:
            raise ValidationError("当前班级对照实验至少需要四个班级；最终数量应以预先完成的样本量论证为准。")
    if protocol.stage == ResearchStage.E6:
        if not assignments or any(
            item.arm != ResearchCohortAssignment.Arm.EXTERNAL_CONFIRMATION
            or item.development_site
            or item.prior_policy_access
            for item in assignments
        ):
            raise ValidationError("外校独立复核只能纳入未参与方案开发且未提前接触本次方案的班级。")


@transaction.atomic
def create_run(*, protocol_id: int, school, actor, payload):
    _require_school_actor(school=school, actor=actor)
    protocol = ResearchProtocolVersion.objects.select_related("study").get(
        pk=protocol_id, study__school=school
    )
    mode = str(payload.get("mode") or "").strip()
    if mode not in STAGE_MODES[protocol.stage]:
        raise ValidationError({"mode": "实施方式与教育实验类型不一致。"})
    decision_effect = bool(payload.get("decision_effect", False))
    if protocol.stage == ResearchStage.E4 and decision_effect:
        # E4 may support teacher consultation, but it never directly executes a
        # platform decision; actual teacher actions remain separate records.
        raise ValidationError(
            {"decision_effect": "有限咨询只能向教师提供建议，平台不得直接改变教学安排。"}
        )
    run = ResearchRun(
        protocol=protocol,
        run_code=_clean_text(payload.get("run_code"), field="run_code", max_length=96),
        mode=mode,
        decision_effect=decision_effect,
        automatic_action_enabled=False,
        planned_start=_clean_datetime(
            payload.get("planned_start"), field="planned_start"
        ),
        planned_end=_clean_datetime(payload.get("planned_end"), field="planned_end"),
        created_by=actor,
    )
    run.save()
    return run


@transaction.atomic
def activate_run(*, run_id: int, school, actor):
    _require_school_actor(school=school, actor=actor)
    run = ResearchRun.objects.select_for_update().select_related(
        "protocol", "protocol__study"
    ).get(pk=run_id, protocol__study__school=school)
    if run.status != ResearchRun.Status.PLANNED:
        raise ValidationError("只有处于计划中的教育实验实施才能开始。")
    status = gate_status(run.protocol)
    if status["missing"]:
        labels = dict(ResearchGateDecision.Gate.choices)
        raise ValidationError(
            "尚未完成以下开展条件："
            + "、".join(labels[item] for item in status["missing"])
            + "。"
        )
    _validate_cohort_gate(run.protocol)
    run.status = ResearchRun.Status.ACTIVE
    run.activated_by = actor
    run.activated_at = timezone.now()
    run.save(update_fields=["status", "activated_by", "activated_at"])
    study = run.protocol.study
    study.status = ResearchStudy.Status.ACTIVE
    study.updated_by = actor
    study.save(update_fields=["status", "updated_by", "updated_at"])
    return run


@transaction.atomic
def close_run(*, run_id: int, school, actor):
    _require_school_actor(school=school, actor=actor)
    run = ResearchRun.objects.select_for_update().select_related(
        "protocol__study"
    ).get(pk=run_id, protocol__study__school=school)
    if run.status not in {ResearchRun.Status.ACTIVE, ResearchRun.Status.PAUSED}:
        raise ValidationError("只有实施中或已暂停的教育实验可以结束。")
    run.status = ResearchRun.Status.CLOSED
    run.closed_by = actor
    run.closed_at = timezone.now()
    run.save(update_fields=["status", "closed_by", "closed_at"])
    return run


@transaction.atomic
def lock_run_data(*, run_id: int, school, actor, payload):
    _require_school_actor(school=school, actor=actor)
    run = ResearchRun.objects.select_for_update().select_related(
        "protocol__study"
    ).get(pk=run_id, protocol__study__school=school)
    if hasattr(run, "data_lock"):
        raise ValidationError("本次实施已经确认过分析数据范围。")
    now = timezone.now()
    dataset_manifest = payload.get("dataset_manifest")
    variable_dictionary = payload.get("variable_dictionary")
    if not isinstance(dataset_manifest, dict) or not dataset_manifest:
        raise ValidationError({"dataset_manifest": "请提供非空的数据集清单。"})
    if not isinstance(variable_dictionary, list) or not variable_dictionary:
        raise ValidationError({"variable_dictionary": "请提供非空的变量字典。"})
    data_lock = ResearchDataLock(
        run=run,
        decision_as_of=_clean_datetime(
            payload.get("decision_as_of"), field="decision_as_of", required=True
        ),
        data_cutoff=_clean_datetime(
            payload.get("data_cutoff"), field="data_cutoff", required=True
        ),
        dataset_manifest=dataset_manifest,
        variable_dictionary=variable_dictionary,
        row_count=max(int(payload.get("row_count") or 0), 0),
        missingness_summary=payload.get("missingness_summary") or {},
        exclusion_summary=payload.get("exclusion_summary") or {},
        dataset_hash=_clean_text(
            payload.get("dataset_hash"), field="dataset_hash", max_length=64
        ),
        locked_by=actor,
        locked_at=now,
    )
    if len(data_lock.dataset_hash) != 64:
        raise ValidationError({"dataset_hash": "数据集校验值必须是 64 位 SHA-256。"})
    data_lock.content_hash = canonical_hash(data_lock.semantic_content())
    data_lock.save()
    run.status = ResearchRun.Status.DATA_LOCKED
    run.save(update_fields=["status"])
    return data_lock


@transaction.atomic
def record_exposure(*, run_id: int, school, actor, payload):
    _require_school_actor(school=school, actor=actor)
    run = ResearchRun.objects.select_related("protocol__study").get(
        pk=run_id, protocol__study__school=school
    )
    if run.status not in {ResearchRun.Status.ACTIVE, ResearchRun.Status.PAUSED}:
        raise ValidationError("只有实施中或暂停待核查的教育实验可以记录实际实施情况。")
    assignment = ResearchCohortAssignment.objects.filter(
        pk=payload.get("cohort_assignment_id"), protocol=run.protocol
    ).first()
    if assignment is None:
        raise ValidationError({"cohort_assignment_id": "该班级不属于本次已经确认的教育实验方案。"})
    exposure = str(payload.get("actual_exposure") or "").strip()
    if exposure not in ResearchExposureRecord.Exposure.values:
        raise ValidationError({"actual_exposure": "请选择有效的实际实施状态。"})
    observed_on = _clean_date(payload.get("observed_on"), field="observed_on")
    if observed_on is None:
        raise ValidationError({"observed_on": "观察日期不能为空。"})
    fidelity = payload.get("implementation_fidelity")
    if fidelity == "" or fidelity is None:
        fidelity = None
    else:
        fidelity = str(fidelity)
    now = timezone.now()
    record = ResearchExposureRecord(
        run=run,
        cohort_assignment=assignment,
        observed_on=observed_on,
        actual_exposure=exposure,
        contamination_detected=bool(payload.get("contamination_detected", False)),
        implementation_fidelity=fidelity,
        opportunity_summary=payload.get("opportunity_summary") or {},
        note=str(payload.get("note") or "").strip(),
        recorded_by=actor,
        recorded_at=now,
    )
    record.content_hash = canonical_hash(record.semantic_content())
    record.save()
    return record


@transaction.atomic
def record_analysis_run(*, data_lock_id: int, school, actor, payload):
    _require_school_actor(school=school, actor=actor)
    data_lock = ResearchDataLock.objects.select_related(
        "run__protocol__study"
    ).get(pk=data_lock_id, run__protocol__study__school=school)
    status = str(payload.get("status") or "").strip()
    if status not in ResearchAnalysisRun.Status.values:
        raise ValidationError({"status": "分析运行状态无效。"})
    parameters = payload.get("parameters")
    software_versions = payload.get("software_versions")
    result_summary = payload.get("result_summary") or {}
    if not isinstance(parameters, dict) or not parameters:
        raise ValidationError({"parameters": "必须保存分析参数与样本筛选。"})
    if not isinstance(software_versions, dict) or not software_versions:
        raise ValidationError({"software_versions": "必须保存统计软件及代码版本。"})
    if status == ResearchAnalysisRun.Status.COMPLETED and not result_summary:
        raise ValidationError({"result_summary": "完成的分析必须保存结果摘要。"})
    now = timezone.now()
    record = ResearchAnalysisRun(
        data_lock=data_lock,
        analysis_key=_clean_text(
            payload.get("analysis_key"), field="analysis_key", max_length=96
        ),
        status=status,
        parameters=parameters,
        software_versions=software_versions,
        result_summary=result_summary,
        failure_detail=str(payload.get("failure_detail") or "").strip(),
        completed_by=actor,
        completed_at=now,
    )
    record.content_hash = canonical_hash(record.semantic_content())
    record.save()
    return record
