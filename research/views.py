from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError
from rest_framework.decorators import api_view, permission_classes

from api.permissions import IsSchoolAdmin
from api.responses import fail, ok
from api.services import write_audit
from courses.models import Course, Subject
from ops.xlsx import build_workbook, workbook_response
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
)
from .services import (
    REQUIRED_GATES,
    activate_run,
    assign_cohort,
    close_run,
    create_run,
    create_study,
    gate_status,
    lock_run_data,
    record_analysis_run,
    record_exposure,
    record_gate_decision,
    register_protocol,
)


def _errors(exc: ValidationError):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"non_field_errors": exc.messages}


def _gate_row(record):
    return {
        "id": record.id,
        "gate": record.gate,
        "gate_label": record.get_gate_display(),
        "sequence_no": record.sequence_no,
        "decision": record.decision,
        "decision_label": record.get_decision_display(),
        "evidence_ref": record.evidence_ref,
        "note": record.note,
        "content_hash": record.content_hash,
        "decided_by": record.decided_by.get_full_name() or record.decided_by.username,
        "decided_at": record.decided_at,
    }


def _cohort_row(item):
    return {
        "id": item.id,
        "class_group_id": item.class_group_id,
        "class_group_name": item.class_group.name,
        "arm": item.arm,
        "arm_label": item.get_arm_display(),
        "allocation_method": item.allocation_method,
        "allocation_method_label": item.get_allocation_method_display(),
        "allocation_unit_code": item.allocation_unit_code,
        "development_site": item.development_site,
        "prior_policy_access": item.prior_policy_access,
        "content_hash": item.content_hash,
        "assigned_at": item.assigned_at,
    }


def _run_row(run):
    data_lock = None
    try:
        lock = run.data_lock
    except ObjectDoesNotExist:
        lock = None
    if lock:
        data_lock = {
            "id": lock.id,
            "decision_as_of": lock.decision_as_of,
            "data_cutoff": lock.data_cutoff,
            "row_count": lock.row_count,
            "dataset_hash": lock.dataset_hash,
            "content_hash": lock.content_hash,
            "locked_at": lock.locked_at,
        }
    return {
        "id": run.id,
        "run_code": run.run_code,
        "mode": run.mode,
        "mode_label": run.get_mode_display(),
        "status": run.status,
        "status_label": run.get_status_display(),
        "decision_effect": run.decision_effect,
        "automatic_action_enabled": run.automatic_action_enabled,
        "planned_start": run.planned_start,
        "planned_end": run.planned_end,
        "activated_at": run.activated_at,
        "closed_at": run.closed_at,
        "exposure_count": run.exposure_records.count(),
        "data_lock": data_lock,
    }


def _exposure_row(record):
    return {
        "id": record.id,
        "run_id": record.run_id,
        "cohort_assignment_id": record.cohort_assignment_id,
        "class_group_name": record.cohort_assignment.class_group.name,
        "observed_on": record.observed_on,
        "actual_exposure": record.actual_exposure,
        "actual_exposure_label": record.get_actual_exposure_display(),
        "contamination_detected": record.contamination_detected,
        "implementation_fidelity": record.implementation_fidelity,
        "opportunity_summary": record.opportunity_summary,
        "note": record.note,
        "content_hash": record.content_hash,
        "recorded_at": record.recorded_at,
    }


def _analysis_row(record):
    return {
        "id": record.id,
        "data_lock_id": record.data_lock_id,
        "analysis_key": record.analysis_key,
        "status": record.status,
        "status_label": record.get_status_display(),
        "parameters": record.parameters,
        "software_versions": record.software_versions,
        "result_summary": record.result_summary,
        "failure_detail": record.failure_detail,
        "content_hash": record.content_hash,
        "completed_at": record.completed_at,
    }


def _protocol_row(protocol, *, detail=False):
    status = gate_status(protocol)
    gate_labels = dict(ResearchGateDecision.Gate.choices)
    row = {
        "id": protocol.id,
        "version_no": protocol.version_no,
        "stage": protocol.stage,
        "stage_label": protocol.get_stage_display(),
        "design_type": protocol.design_type,
        "design_type_label": protocol.get_design_type_display(),
        "content_hash": protocol.content_hash,
        "policy_hash": protocol.policy_hash,
        "ethics_approval_ref": protocol.ethics_approval_ref,
        "ethics_approved_at": protocol.ethics_approved_at,
        "preregistration_ref": protocol.preregistration_ref,
        "preregistered_at": protocol.preregistered_at,
        "registered_at": protocol.registered_at,
        "required_gates": [
            {"value": gate, "label": gate_labels[gate]}
            for gate in status["required"]
        ],
        "approved_gates": status["approved"],
        "missing_gates": [
            {"value": gate, "label": gate_labels[gate]}
            for gate in status["missing"]
        ],
        "cohort_count": protocol.cohort_assignments.count(),
        "run_count": protocol.runs.count(),
    }
    if detail:
        row.update(
            {
                "protocol": protocol.protocol,
                "policy_snapshot": protocol.policy_snapshot,
                "consent_required": protocol.consent_required,
                "consent_plan": protocol.consent_plan,
                "gate_decisions": [
                    _gate_row(item)
                    for item in status["latest"].values()
                ],
                "cohort_assignments": [
                    _cohort_row(item)
                    for item in protocol.cohort_assignments.select_related(
                        "class_group"
                    )
                ],
                "runs": [
                    _run_row(item)
                    for item in protocol.runs.select_related(
                        "protocol"
                    ).order_by("-created_at")
                ],
            }
        )
    return row


def _study_row(study, *, detail=False):
    row = {
        "id": study.id,
        "code": study.code,
        "title": study.title,
        "description": study.description,
        "status": study.status,
        "status_label": study.get_status_display(),
        "subject_id": study.subject_id,
        "subject_name": study.subject.name if study.subject_id else "",
        "course_id": study.course_id,
        "course_title": study.course.title if study.course_id else "",
        "current_protocol_id": study.current_protocol_id,
        "created_at": study.created_at,
        "updated_at": study.updated_at,
    }
    if study.current_protocol_id:
        row["current_protocol"] = _protocol_row(
            study.current_protocol, detail=detail
        )
    else:
        row["current_protocol"] = None
    if detail:
        row["protocol_versions"] = [
            _protocol_row(item)
            for item in study.protocol_versions.all().order_by("-version_no")
        ]
    return row


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def research_options(request):
    school = request.user.school
    return ok(
        {
            "stages": [
                {"value": value, "label": label}
                for value, label in ResearchStage.choices
            ],
            "design_types": [
                {"value": value, "label": label}
                for value, label in ResearchProtocolVersion.DesignType.choices
            ],
            "gates": [
                {"value": value, "label": label}
                for value, label in ResearchGateDecision.Gate.choices
            ],
            "gate_decisions": [
                {"value": value, "label": label}
                for value, label in ResearchGateDecision.Decision.choices
            ],
            "arms": [
                {"value": value, "label": label}
                for value, label in ResearchCohortAssignment.Arm.choices
            ],
            "allocation_methods": [
                {"value": value, "label": label}
                for value, label in ResearchCohortAssignment.AllocationMethod.choices
            ],
            "run_modes": [
                {"value": value, "label": label}
                for value, label in ResearchRun.Mode.choices
            ],
            "subjects": list(
                Subject.objects.filter(school=school).values("id", "name")
            ),
            "courses": list(
                Course.objects.filter(subject__school=school, is_active=True).values(
                    "id", "title", "subject_id"
                )
            ),
            "classes": list(
                ClassGroup.objects.filter(
                    school=school, status=ClassGroup.Status.ACTIVE
                ).values("id", "name", "grade")
            ),
            "required_gates": {
                stage: sorted(gates) for stage, gates in REQUIRED_GATES.items()
            },
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def research_studies(request):
    school = request.user.school
    if request.method == "GET":
        studies = ResearchStudy.objects.filter(school=school).select_related(
            "subject", "course", "current_protocol"
        )
        return ok([_study_row(item) for item in studies])
    try:
        study = create_study(school=school, actor=request.user, payload=request.data)
    except (ValidationError, IntegrityError) as exc:
        if isinstance(exc, ValidationError):
            return fail("教育实验草稿尚不能保存。", errors=_errors(exc))
        return fail("实验编号或关联对象冲突。")
    write_audit(
        request,
        "research.study.create",
        school=school,
        target_type="research_study",
        target_id=study.id,
        detail={"code": study.code},
    )
    return ok(_study_row(study), "教育实验草稿已建立。", status=201)


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def research_study_detail(request, pk):
    try:
        study = (
            ResearchStudy.objects.filter(school=request.user.school)
            .select_related("subject", "course", "current_protocol")
            .prefetch_related("protocol_versions")
            .get(pk=pk)
        )
    except ResearchStudy.DoesNotExist:
        return fail("教育实验不存在。", status=404)
    return ok(_study_row(study, detail=True))


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def research_protocol_register(request, pk):
    try:
        protocol = register_protocol(
            study_id=pk,
            school=request.user.school,
            actor=request.user,
            payload=request.data,
        )
    except (ResearchStudy.DoesNotExist, ValidationError, IntegrityError) as exc:
        if isinstance(exc, ResearchStudy.DoesNotExist):
            return fail("教育实验不存在。", status=404)
        if isinstance(exc, ValidationError):
            return fail("教育实验方案尚不能确认。", errors=_errors(exc))
        return fail("教育实验方案版本冲突，请刷新后重试。", status=409)
    write_audit(
        request,
        "research.protocol.register",
        school=request.user.school,
        target_type="research_protocol_version",
        target_id=protocol.id,
        detail={"stage": protocol.stage, "content_hash": protocol.content_hash},
    )
    return ok(_protocol_row(protocol, detail=True), "教育实验方案版本已确认。")


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def research_protocol_detail(request, pk):
    try:
        protocol = ResearchProtocolVersion.objects.select_related(
            "study"
        ).get(pk=pk, study__school=request.user.school)
    except ResearchProtocolVersion.DoesNotExist:
        return fail("教育实验方案版本不存在。", status=404)
    return ok(_protocol_row(protocol, detail=True))


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def research_protocol_gate(request, pk):
    try:
        record = record_gate_decision(
            protocol_id=pk,
            school=request.user.school,
            actor=request.user,
            payload=request.data,
        )
    except (ResearchProtocolVersion.DoesNotExist, ValidationError, IntegrityError) as exc:
        if isinstance(exc, ResearchProtocolVersion.DoesNotExist):
            return fail("教育实验方案版本不存在。", status=404)
        if isinstance(exc, ValidationError):
            return fail("开展条件的核对结果尚不能保存。", errors=_errors(exc))
        return fail("开展条件记录冲突，请刷新后重试。", status=409)
    write_audit(
        request,
        "research.gate.record",
        school=request.user.school,
        target_type="research_gate_decision",
        target_id=record.id,
        detail={"gate": record.gate, "decision": record.decision},
    )
    return ok(_gate_row(record), "开展条件的核对结果已保存。", status=201)


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def research_protocol_cohort(request, pk):
    try:
        assignment = assign_cohort(
            protocol_id=pk,
            school=request.user.school,
            actor=request.user,
            payload=request.data,
        )
    except (ResearchProtocolVersion.DoesNotExist, ValidationError, IntegrityError) as exc:
        if isinstance(exc, ResearchProtocolVersion.DoesNotExist):
            return fail("教育实验方案版本不存在。", status=404)
        if isinstance(exc, ValidationError):
            return fail("班级安排尚不能保存。", errors=_errors(exc))
        return fail("班级或分配编号已经存在。", status=409)
    write_audit(
        request,
        "research.cohort.freeze",
        school=request.user.school,
        target_type="research_cohort_assignment",
        target_id=assignment.id,
        detail={"arm": assignment.arm, "class_group_id": assignment.class_group_id},
    )
    return ok(_cohort_row(assignment), "班级及其在教育实验中的安排已保存。", status=201)


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def research_protocol_run(request, pk):
    try:
        run = create_run(
            protocol_id=pk,
            school=request.user.school,
            actor=request.user,
            payload=request.data,
        )
    except (ResearchProtocolVersion.DoesNotExist, ValidationError, IntegrityError) as exc:
        if isinstance(exc, ResearchProtocolVersion.DoesNotExist):
            return fail("教育实验方案版本不存在。", status=404)
        if isinstance(exc, ValidationError):
            return fail("教育实验实施计划尚不能保存。", errors=_errors(exc))
        return fail("本次实施编号已经存在。", status=409)
    write_audit(
        request,
        "research.run.plan",
        school=request.user.school,
        target_type="research_run",
        target_id=run.id,
        detail={"mode": run.mode},
    )
    return ok(_run_row(run), "教育实验实施计划已建立。", status=201)


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def research_run_activate(request, pk):
    try:
        run = activate_run(
            run_id=pk, school=request.user.school, actor=request.user
        )
    except (ResearchRun.DoesNotExist, ValidationError) as exc:
        if isinstance(exc, ResearchRun.DoesNotExist):
            return fail("教育实验实施记录不存在。", status=404)
        return fail("本次教育实验尚不能开始。", errors=_errors(exc))
    write_audit(
        request,
        "research.run.activate",
        school=request.user.school,
        target_type="research_run",
        target_id=run.id,
        detail={"protocol_hash": run.protocol.content_hash},
    )
    return ok(_run_row(run), "本次教育实验实施已经开始。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def research_run_close(request, pk):
    try:
        run = close_run(run_id=pk, school=request.user.school, actor=request.user)
    except (ResearchRun.DoesNotExist, ValidationError) as exc:
        if isinstance(exc, ResearchRun.DoesNotExist):
            return fail("教育实验实施记录不存在。", status=404)
        return fail("本次实施尚不能结束。", errors=_errors(exc))
    write_audit(
        request,
        "research.run.close",
        school=request.user.school,
        target_type="research_run",
        target_id=run.id,
    )
    return ok(_run_row(run), "本次实施已经结束，可以整理后测、问卷和实施记录。")


@api_view(["POST"])
@permission_classes([IsSchoolAdmin])
def research_run_lock(request, pk):
    try:
        data_lock = lock_run_data(
            run_id=pk,
            school=request.user.school,
            actor=request.user,
            payload=request.data,
        )
    except (ResearchRun.DoesNotExist, ValidationError, IntegrityError) as exc:
        if isinstance(exc, ResearchRun.DoesNotExist):
            return fail("教育实验实施记录不存在。", status=404)
        if isinstance(exc, ValidationError):
            return fail("用于分析的数据范围尚不能确认。", errors=_errors(exc))
        return fail("本次实施已经确认过分析数据范围。", status=409)
    write_audit(
        request,
        "research.data.lock",
        school=request.user.school,
        target_type="research_data_lock",
        target_id=data_lock.id,
        detail={
            "dataset_hash": data_lock.dataset_hash,
            "content_hash": data_lock.content_hash,
        },
    )
    return ok(_run_row(data_lock.run), "本次用于分析的数据范围已经确认。")


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def research_run_exposures(request, pk):
    school = request.user.school
    if request.method == "GET":
        records = ResearchExposureRecord.objects.filter(
            run_id=pk, run__protocol__study__school=school
        ).select_related("run", "cohort_assignment__class_group")
        return ok([_exposure_row(item) for item in records])
    try:
        record = record_exposure(
            run_id=pk, school=school, actor=request.user, payload=request.data
        )
    except (ResearchRun.DoesNotExist, ValidationError, IntegrityError) as exc:
        if isinstance(exc, ResearchRun.DoesNotExist):
            return fail("教育实验实施记录不存在。", status=404)
        if isinstance(exc, ValidationError):
            return fail("实际实施情况尚不能保存。", errors=_errors(exc))
        return fail("该班级在同一日期已经记录过实际实施情况。", status=409)
    write_audit(
        request,
        "research.exposure.record",
        school=school,
        target_type="research_exposure_record",
        target_id=record.id,
        detail={
            "actual_exposure": record.actual_exposure,
            "contamination_detected": record.contamination_detected,
        },
    )
    return ok(_exposure_row(record), "实际实施与污染情况已追加保存。", status=201)


@api_view(["GET", "POST"])
@permission_classes([IsSchoolAdmin])
def research_data_lock_analyses(request, pk):
    school = request.user.school
    if request.method == "GET":
        records = ResearchAnalysisRun.objects.filter(
            data_lock_id=pk,
            data_lock__run__protocol__study__school=school,
        ).select_related("data_lock")
        return ok([_analysis_row(item) for item in records])
    try:
        record = record_analysis_run(
            data_lock_id=pk,
            school=school,
            actor=request.user,
            payload=request.data,
        )
    except (ResearchDataLock.DoesNotExist, ValidationError, IntegrityError) as exc:
        if isinstance(exc, ResearchDataLock.DoesNotExist):
            return fail("尚未确认用于分析的数据范围。", status=404)
        if isinstance(exc, ValidationError):
            return fail("分析记录尚不能保存。", errors=_errors(exc))
        return fail("同一份分析数据下的分析编号已经存在。", status=409)
    write_audit(
        request,
        "research.analysis.record",
        school=school,
        target_type="research_analysis_run",
        target_id=record.id,
        detail={"analysis_key": record.analysis_key, "status": record.status},
    )
    return ok(_analysis_row(record), "分析记录已保存。", status=201)


@api_view(["GET"])
@permission_classes([IsSchoolAdmin])
def research_protocol_export(request, pk):
    try:
        protocol = ResearchProtocolVersion.objects.select_related(
            "study", "study__subject", "study__course"
        ).get(pk=pk, study__school=request.user.school)
    except ResearchProtocolVersion.DoesNotExist:
        return fail("教育实验方案版本不存在。", status=404)
    gates = list(
        protocol.gate_decisions.select_related("decided_by").order_by(
            "gate", "sequence_no"
        )
    )
    cohorts = list(
        protocol.cohort_assignments.select_related("class_group").order_by(
            "class_group__name"
        )
    )
    runs = list(protocol.runs.order_by("created_at"))
    exposures = list(
        ResearchExposureRecord.objects.filter(run__protocol=protocol)
        .select_related("run", "cohort_assignment__class_group")
        .order_by("observed_on", "id")
    )
    locks = list(
        ResearchDataLock.objects.filter(run__protocol=protocol)
        .select_related("run")
        .order_by("locked_at")
    )
    analyses = list(
        ResearchAnalysisRun.objects.filter(data_lock__run__protocol=protocol)
        .select_related("data_lock__run")
        .order_by("completed_at")
    )
    write_audit(
        request,
        "research.protocol.export",
        school=request.user.school,
        target_type="research_protocol_version",
        target_id=protocol.id,
        detail={"content_hash": protocol.content_hash},
    )
    workbook = build_workbook(
        [
            {
                "title": "实验方案",
                "headers": ["项目", "内容"],
                "rows": [
                    ["实验编号", protocol.study.code],
                    ["实验名称", protocol.study.title],
                    ["学科", protocol.study.subject.name if protocol.study.subject_id else ""],
                    ["课程", protocol.study.course.title if protocol.study.course_id else ""],
                    ["阶段", protocol.get_stage_display()],
                    ["实验安排类型", protocol.get_design_type_display()],
                    ["方案版本", protocol.version_no],
                    ["方案校验值", protocol.content_hash],
                    ["政策校验值", protocol.policy_hash],
                    ["伦理审批", protocol.ethics_approval_ref],
                    ["预注册", protocol.preregistration_ref],
                    ["实验方案内容", protocol.protocol],
                    ["冻结政策", protocol.policy_snapshot],
                ],
            },
            {
                "title": "开展条件",
                "headers": ["核对项目", "序号", "结论", "材料", "说明", "确认人", "确认时间", "校验值"],
                "rows": [
                    [item.get_gate_display(), item.sequence_no, item.get_decision_display(), item.evidence_ref, item.note, item.decided_by.username, item.decided_at, item.content_hash]
                    for item in gates
                ],
            },
            {
                "title": "班级安排",
                "headers": ["班级", "组别", "方法", "分配编号", "开发学校", "提前接触政策", "校验值"],
                "rows": [
                    [item.class_group.name, item.get_arm_display(), item.get_allocation_method_display(), item.allocation_unit_code, item.development_site, item.prior_policy_access, item.content_hash]
                    for item in cohorts
                ],
            },
            {
                "title": "实施与分析数据",
                "headers": ["实施编号", "方式", "状态", "影响教学", "自动执行", "开始时间", "结束时间", "数据校验值"],
                "rows": [
                    [item.run_code, item.get_mode_display(), item.get_status_display(), item.decision_effect, item.automatic_action_enabled, item.activated_at, item.closed_at, next((lock.dataset_hash for lock in locks if lock.run_id == item.id), "")]
                    for item in runs
                ],
            },
            {
                "title": "实际暴露",
                "headers": ["实施编号", "班级", "日期", "实际安排", "条件交叉", "方案执行情况", "学习机会摘要", "说明", "校验值"],
                "rows": [
                    [item.run.run_code, item.cohort_assignment.class_group.name, item.observed_on, item.get_actual_exposure_display(), item.contamination_detected, item.implementation_fidelity, item.opportunity_summary, item.note, item.content_hash]
                    for item in exposures
                ],
            },
            {
                "title": "变量字典",
                "headers": ["实施编号", "变量说明"],
                "rows": [
                    [lock.run.run_code, variable]
                    for lock in locks
                    for variable in lock.variable_dictionary
                ],
            },
            {
                "title": "分析记录",
                "headers": ["实施编号", "分析编号", "状态", "参数", "软件版本", "结果摘要", "失败原因", "校验值"],
                "rows": [
                    [item.data_lock.run.run_code, item.analysis_key, item.get_status_display(), item.parameters, item.software_versions, item.result_summary, item.failure_detail, item.content_hash]
                    for item in analyses
                ],
            },
        ]
    )
    return workbook_response(
        workbook,
        f"教育实验-{protocol.study.code}-v{protocol.version_no}.xlsx",
    )
