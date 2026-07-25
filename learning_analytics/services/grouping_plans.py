from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta
from itertools import combinations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from courses.grouping import build_grouping_candidates
from courses.models import ClassroomGroupCollaboration, ClassroomSession
from learning.models import StudentMasterySnapshot, StudentSubjectBand
from learning_analytics.models import (
    GroupingCandidateRun,
    GroupingDecisionPoint,
    GroupingFairnessAudit,
    GroupingOpportunityAudit,
    GroupingOutcomeSnapshot,
    GroupingPairHistory,
    GroupingPlanVersion,
    GroupingPolicyVersion,
    GroupingTeacherDecision,
    LearningOpportunity,
)
from school.models import StudentProfile


ALGORITHM_VERSION = "group-cp-sat-v1"
DEFAULT_ROLES = ["coordinator", "recorder", "resource", "presenter", "verifier"]
ALLOWED_ROLES = set(DEFAULT_ROLES) | {"leader", "member"}


def _canonical_hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _normalized_string_list(value, *, label: str, allow_empty: bool = True) -> list:
    if not isinstance(value, list):
        raise ValidationError(f"{label}必须是列表。")
    normalized = []
    for item in value:
        if isinstance(item, str):
            item = item.strip()
            if not item:
                raise ValidationError(f"{label}不能包含空值。")
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(item)
        else:
            raise ValidationError(f"{label}中的内容格式不正确。")
    if not allow_empty and not normalized:
        raise ValidationError(f"请至少设置一项{label}。")
    return normalized


def _normalized_pairs(value, *, label: str) -> list[tuple[int, int]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{label}必须是学生编号对列表。")
    pairs = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValidationError(f"{label}中的每一项必须包含两名学生。")
        try:
            left, right = sorted((int(row[0]), int(row[1])))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label}中的学生编号不正确。") from exc
        if left == right:
            raise ValidationError(f"{label}不能把同一名学生与自己配对。")
        pairs.append((left, right))
    return sorted(set(pairs))


@transaction.atomic
def save_grouping_decision_point(
    *,
    session: ClassroomSession,
    actor,
    task_purpose: str,
    task_stage: str,
    role_requirements: list,
    resource_requirements: list,
    safety_constraints: dict | None = None,
    opportunity_requirements: dict | None = None,
    stability_until=None,
    trigger: str = GroupingDecisionPoint.Trigger.TEACHER_REQUEST,
    task_context: dict | None = None,
) -> GroupingDecisionPoint:
    """Save the immutable task definition before any candidate is generated."""
    if session.status != ClassroomSession.Status.RUNNING:
        raise ValidationError("只有进行中的课堂可以准备动态分组任务。")
    if task_purpose not in GroupingDecisionPoint.TaskPurpose.values:
        raise ValidationError("分组任务目的不正确。")
    task_stage = str(task_stage or "").strip()
    if not task_stage:
        raise ValidationError("请填写本次分组所处的学习阶段。")
    roles = _normalized_string_list(
        role_requirements,
        label="小组角色",
        allow_empty=False,
    )
    if len(set(roles)) != len(roles) or any(
        role not in ALLOWED_ROLES for role in roles
    ):
        raise ValidationError("小组角色设置不正确或存在重复。")
    resources = _normalized_string_list(resource_requirements, label="学习资源")
    safety = safety_constraints or {}
    opportunity = opportunity_requirements or {}
    if not isinstance(safety, dict):
        raise ValidationError("安全约束设置必须是对象。")
    if not isinstance(opportunity, dict):
        raise ValidationError("学习机会设置必须是对象。")
    safety = dict(safety)
    safety["prohibited_pairs"] = [
        list(pair)
        for pair in _normalized_pairs(
            safety.get("prohibited_pairs") or safety.get("must_separate"),
            label="需要分开的学生组合",
        )
    ]
    required_group_roles = opportunity.get("required_group_roles") or []
    required_group_roles = _normalized_string_list(
        required_group_roles,
        label="每组必设角色",
    )
    if any(role not in roles for role in required_group_roles):
        raise ValidationError("每组必设角色必须包含在本次小组角色中。")
    opportunity = dict(opportunity)
    opportunity["required_group_roles"] = required_group_roles
    required_for_every_student = opportunity.get("required_for_every_student") or [
        "collaboration"
    ]
    opportunity["required_for_every_student"] = _normalized_string_list(
        required_for_every_student,
        label="每名学生的参与机会",
        allow_empty=False,
    )
    policy = active_or_default_grouping_policy(session=session, actor=actor)
    scheduled_for = timezone.now()
    if stability_until is None:
        stability_until = scheduled_for + timedelta(days=policy.stability_window_days)
    point = (
        GroupingDecisionPoint.objects.select_for_update()
        .filter(
            classroom_session=session,
            lesson_step=session.current_step,
            status=GroupingDecisionPoint.Status.OPEN,
            candidate_runs__isnull=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if point is None:
        point = GroupingDecisionPoint(
            school=session.school,
            class_group=session.class_group,
            course=session.course,
            classroom_session=session,
            lesson_step=session.current_step,
            policy=policy,
            created_by=actor,
        )
    point.policy = policy
    point.trigger = trigger
    point.task_purpose = task_purpose
    point.task_stage = task_stage
    point.role_requirements = roles
    point.resource_requirements = resources
    point.safety_constraints = safety
    point.opportunity_requirements = opportunity
    point.stability_until = stability_until
    point.task_context = {
        "lesson_id": session.lesson_id,
        "lesson_step_id": session.current_step_id,
        **(task_context or {}),
    }
    point.scheduled_for = scheduled_for
    point.status = GroupingDecisionPoint.Status.OPEN
    point.save()
    return point


def _strategy_value(value: str) -> str:
    return {
        "random": GroupingPolicyVersion.Strategy.RANDOM_BASELINE,
        "balanced_layer": GroupingPolicyVersion.Strategy.READINESS_BRIDGED,
        "same_layer": GroupingPolicyVersion.Strategy.READINESS_ALIGNED,
        "ai_layer": GroupingPolicyVersion.Strategy.SKILL_COMPLEMENTARY,
        "stable_project": GroupingPolicyVersion.Strategy.STABLE_PROJECT,
        "manual": GroupingPolicyVersion.Strategy.MANUAL,
    }.get(value, GroupingPolicyVersion.Strategy.RANDOM_BASELINE)


@transaction.atomic
def active_or_default_grouping_policy(*, session: ClassroomSession, actor):
    query = GroupingPolicyVersion.objects.filter(
        school=session.school,
        status=GroupingPolicyVersion.Status.ACTIVE,
    )
    policy = query.filter(course=session.course).first()
    if policy is None:
        policy = query.filter(
            course__isnull=True,
            subject=session.course.subject,
        ).first()
    if policy:
        return policy
    strategy = _strategy_value(
        getattr(
            getattr(session, "group_collaboration", None),
            "grouping_strategy",
            "random",
        )
    )
    version_no = (
        GroupingPolicyVersion.objects.filter(school=session.school)
        .order_by("-version_no")
        .values_list("version_no", flat=True)
        .first()
        or 0
    ) + 1
    definition = {
        "strategy": strategy,
        "group_size": 4,
        "min_group_size": 2,
        "max_group_size": 5,
        "roles": DEFAULT_ROLES,
        "hard_constraints": {"one_group_per_student": True},
        "objective_weights": {
            "readiness_balance": 10,
            "pair_repeat": 100,
            "stability": 50,
        },
    }
    return GroupingPolicyVersion.objects.create(
        school=session.school,
        subject=session.course.subject,
        course=session.course,
        name=f"{session.course.title}课堂分组标准",
        version_no=version_no,
        policy_version=f"group-policy-v{version_no}",
        strategy=strategy,
        group_size=definition["group_size"],
        min_group_size=definition["min_group_size"],
        max_group_size=definition["max_group_size"],
        role_scheme=definition["roles"],
        hard_constraints=definition["hard_constraints"],
        objective_weights=definition["objective_weights"],
        stability_window_days=14,
        status=GroupingPolicyVersion.Status.ACTIVE,
        content_hash=_canonical_hash(definition),
        created_by=actor,
        published_by=actor,
        published_at=timezone.now(),
    )


def _profiles(session: ClassroomSession) -> list[StudentProfile]:
    return list(
        StudentProfile.objects.select_related("user")
        .filter(class_group=session.class_group, user__is_active=True)
        .order_by("student_no", "user__display_name", "user__username", "id")
    )


def _readiness_map(session, profiles) -> dict[int, float]:
    rows = StudentSubjectBand.objects.filter(
        student_id__in=[profile.user_id for profile in profiles],
        subject=session.course.subject,
        course=session.course,
        valid_until__isnull=True,
    ).order_by("student_id", "-valid_from")
    result = {}
    for row in rows:
        evidence = (
            row.evidence_snapshot if isinstance(row.evidence_snapshot, dict) else {}
        )
        task = evidence.get("task_readiness")
        if isinstance(task, dict) and task.get("score") is not None:
            try:
                result.setdefault(row.student_id, float(task["score"]))
            except (TypeError, ValueError):
                pass
    return result


def _assignment_rows(
    candidate,
    roles: list[str],
    *,
    locked_assignments: dict[int, int] | None = None,
) -> list[dict]:
    locked_assignments = {
        int(student_id): int(group_no)
        for student_id, group_no in (locked_assignments or {}).items()
    }
    rows = []
    for group_no, chunk in enumerate(candidate["chunks"], start=1):
        members = []
        for index, profile in enumerate(chunk):
            role = roles[index % len(roles)] if roles else "member"
            members.append(
                {
                    "student_id": profile.user_id,
                    "role": role,
                    "locked": locked_assignments.get(profile.user_id) == group_no,
                }
            )
        rows.append({"group_no": group_no, "members": members})
    return rows


def _fairness_metrics(assignments: list[dict], readiness: dict[int, float]) -> dict:
    sizes = [len(group["members"]) for group in assignments]
    means = []
    role_counts = {}
    student_ids = []
    for group in assignments:
        scores = [
            readiness[item["student_id"]]
            for item in group["members"]
            if item["student_id"] in readiness
        ]
        if scores:
            means.append(sum(scores) / len(scores))
        for item in group["members"]:
            student_ids.append(item["student_id"])
            role_counts[item["role"]] = role_counts.get(item["role"], 0) + 1
    return {
        "student_count": len(student_ids),
        "unique_student_count": len(set(student_ids)),
        "group_count": len(assignments),
        "min_group_size": min(sizes, default=0),
        "max_group_size": max(sizes, default=0),
        "group_size_gap": max(sizes, default=0) - min(sizes, default=0),
        "readiness_mean_gap": (
            round(max(means) - min(means), 6) if len(means) >= 2 else 0
        ),
        "role_counts": role_counts,
    }


def _assignment_signature(assignments: list[dict]) -> tuple:
    return tuple(
        sorted(
            (
                int(group["group_no"]),
                tuple(
                    sorted(
                        (int(member["student_id"]), str(member.get("role") or ""))
                        for member in group["members"]
                    )
                ),
            )
            for group in assignments
        )
    )


def _candidate_payload(candidate, roles, readiness, *, locked_assignments=None):
    assignments = _assignment_rows(
        candidate,
        roles,
        locked_assignments=locked_assignments,
    )
    metrics = _fairness_metrics(assignments, readiness)
    return {
        "key": candidate["key"],
        "label": candidate["label"],
        "assignments": assignments,
        "metadata": candidate["metadata"],
        "fairness": metrics,
    }


def _assignment_constraint_blockers(
    *,
    assignments: list[dict],
    expected_student_ids: set[int],
    policy: GroupingPolicyVersion,
    decision_point: GroupingDecisionPoint,
    locked_assignments: dict[int, int] | None = None,
) -> list[str]:
    blockers = []
    members = [
        member for group in assignments for member in (group.get("members") or [])
    ]
    assigned_ids = [int(member.get("student_id") or 0) for member in members]
    if len(assigned_ids) != len(set(assigned_ids)):
        blockers.append("student_assignment_duplicate")
    if set(assigned_ids) != expected_student_ids:
        blockers.append("student_assignment_missing")
    group_sizes = [len(group.get("members") or []) for group in assignments]
    if any(
        size < policy.min_group_size or size > policy.max_group_size
        for size in group_sizes
    ):
        blockers.append("group_size_out_of_range")
    assignment_by_student = {
        int(member["student_id"]): int(group["group_no"])
        for group in assignments
        for member in (group.get("members") or [])
    }
    for student_id, group_no in (locked_assignments or {}).items():
        if assignment_by_student.get(int(student_id)) != int(group_no):
            blockers.append("teacher_lock_changed")
            break
    prohibited_pairs = _normalized_pairs(
        (decision_point.safety_constraints or {}).get("prohibited_pairs"),
        label="需要分开的学生组合",
    )
    member_sets = [
        {int(member["student_id"]) for member in (group.get("members") or [])}
        for group in assignments
    ]
    if any(
        {left, right}.issubset(member_ids)
        for left, right in prohibited_pairs
        for member_ids in member_sets
    ):
        blockers.append("prohibited_pair_together")
    required_roles = set(
        (decision_point.opportunity_requirements or {}).get("required_group_roles")
        or []
    )
    if required_roles and any(
        not required_roles.issubset(
            {str(member.get("role") or "") for member in group.get("members") or []}
        )
        for group in assignments
    ):
        blockers.append("required_group_role_missing")
    if any(str(member.get("role") or "") not in ALLOWED_ROLES for member in members):
        blockers.append("invalid_member_role")
    return sorted(set(blockers))


@transaction.atomic
def generate_grouping_candidate_run(
    *,
    session: ClassroomSession,
    actor,
    decision_point: GroupingDecisionPoint,
    group_size: int | None = None,
    requested_strategy: str = "ai_layer",
    locked_assignments: dict[int, int] | None = None,
    runtime_settings: dict | None = None,
) -> GroupingCandidateRun:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ValidationError("只有进行中的课堂可以生成分组候选。")
    if decision_point.classroom_session_id != session.id:
        raise ValidationError("分组任务定义不属于当前课堂。")
    if decision_point.status != GroupingDecisionPoint.Status.OPEN:
        raise ValidationError("当前分组任务已经生成过候选，请新建分组任务。")
    decision_point.full_clean()
    policy = decision_point.policy
    profiles = _profiles(session)
    if not profiles:
        raise ValidationError("当前班级没有可分组的启用学生。")
    group_size = int(group_size or policy.group_size)
    if not policy.min_group_size <= group_size <= policy.max_group_size:
        raise ValidationError("每组人数不符合当前分组标准。")
    if len(decision_point.role_requirements) > group_size:
        raise ValidationError("每组人数不能少于已经确定的小组角色数量。")
    point = GroupingDecisionPoint.objects.select_for_update().get(pk=decision_point.pk)
    if point.status != GroupingDecisionPoint.Status.OPEN:
        raise ValidationError("当前分组任务已经生成过候选，请新建分组任务。")
    seed = session.id * 100_000 + point.id
    if locked_assignments is not None and not isinstance(locked_assignments, dict):
        raise ValidationError("锁定学生格式不正确。")
    normalized_locks = {}
    for student_id, group_no in (locked_assignments or {}).items():
        try:
            normalized_locks[str(int(student_id))] = int(group_no)
        except (TypeError, ValueError) as exc:
            raise ValidationError("锁定学生与小组编号必须是整数。") from exc
    student_ids = {profile.user_id for profile in profiles}
    group_count = max(1, math.ceil(len(profiles) / group_size))
    base_size, remainder = divmod(len(profiles), group_count)
    group_capacities = {
        group_no: base_size + (1 if group_no <= remainder else 0)
        for group_no in range(1, group_count + 1)
    }
    unknown_students = set(map(int, normalized_locks)) - student_ids
    if unknown_students:
        raise ValidationError("锁定学生不在当前课堂班级中。")
    prohibited_pairs = _normalized_pairs(
        (point.safety_constraints or {}).get("prohibited_pairs"),
        label="需要分开的学生组合",
    )
    unknown_safety_students = {
        student_id for pair in prohibited_pairs for student_id in pair
    } - student_ids
    if unknown_safety_students:
        raise ValidationError("安全约束中包含不属于当前课堂班级的学生。")
    if any(
        group_no < 1 or group_no > group_count for group_no in normalized_locks.values()
    ):
        raise ValidationError("锁定学生的小组编号不在可用范围内。")
    lock_counts = {
        group_no: list(normalized_locks.values()).count(group_no)
        for group_no in set(normalized_locks.values())
    }
    if any(
        count > group_capacities[group_no] for group_no, count in lock_counts.items()
    ):
        raise ValidationError("同一小组的锁定学生人数超过每组人数。")
    input_snapshot = {
        "student_ids": [profile.user_id for profile in profiles],
        "group_size": group_size,
        "requested_strategy": requested_strategy,
        "policy_id": policy.id,
        "policy_hash": policy.content_hash,
        "locked_assignments": normalized_locks,
        "runtime_settings": runtime_settings or {},
        "task_definition": {
            "decision_point_id": point.id,
            "task_purpose": point.task_purpose,
            "task_stage": point.task_stage,
            "role_requirements": point.role_requirements,
            "resource_requirements": point.resource_requirements,
            "safety_constraints": point.safety_constraints,
            "opportunity_requirements": point.opportunity_requirements,
            "stability_until": (
                point.stability_until.isoformat() if point.stability_until else None
            ),
        },
        "active_plan_version": getattr(
            getattr(session, "group_collaboration", None), "active_plan_version", 0
        ),
    }
    required_for_every_student = set(
        point.opportunity_requirements.get("required_for_every_student") or []
    )
    runtime_settings = input_snapshot["runtime_settings"]
    if "document_edit" in required_for_every_student and not runtime_settings.get(
        "allow_onlyoffice_edit", True
    ):
        raise ValidationError("本次任务要求每名学生获得文档编辑机会，请开启在线编辑。")
    if "file_share" in required_for_every_student and not runtime_settings.get(
        "allow_student_upload", True
    ):
        raise ValidationError("本次任务要求每名学生获得文件分享机会，请开启学生上传。")
    input_hash = _canonical_hash(input_snapshot)
    existing = GroupingCandidateRun.objects.filter(
        decision_point=point,
        input_hash=input_hash,
        algorithm_version=ALGORITHM_VERSION,
    ).first()
    if existing:
        return existing
    run = GroupingCandidateRun.objects.create(
        decision_point=point,
        policy=policy,
        algorithm_version=ALGORITHM_VERSION,
        seed=seed,
        status=GroupingCandidateRun.Status.BUILDING,
        input_snapshot=input_snapshot,
        input_hash=input_hash,
        created_by=actor,
    )
    candidates = build_grouping_candidates(
        session=session,
        profiles=profiles,
        group_size=group_size,
        strategy=requested_strategy,
        seed=seed,
        plan_version=input_snapshot["active_plan_version"] + 1,
        locked_assignments=normalized_locks,
    )
    # Even when readiness data are unavailable, teachers must compare alternatives
    # instead of receiving a single auto-selected default.  Generate deterministic
    # random alternatives while retaining every teacher lock.
    candidate_keys = {candidate["key"] for candidate in candidates}
    for offset in range(1, 9):
        if len(candidates) >= 2:
            break
        alternatives = build_grouping_candidates(
            session=session,
            profiles=profiles,
            group_size=group_size,
            strategy="random",
            seed=seed + offset * 997,
            plan_version=input_snapshot["active_plan_version"] + 1,
            locked_assignments=normalized_locks,
        )
        if not alternatives:
            continue
        alternative = dict(alternatives[0])
        alternative["key"] = "random_alternative"
        alternative["label"] = "随机备选"
        alternative["metadata"] = {
            **(alternative.get("metadata") or {}),
            "alternative_seed": seed + offset * 997,
        }
        if alternative["key"] not in candidate_keys:
            candidates.append(alternative)
            candidate_keys.add(alternative["key"])
    readiness = _readiness_map(session, profiles)
    payloads = [
        _candidate_payload(
            candidate,
            point.role_requirements,
            readiness,
            locked_assignments=normalized_locks,
        )
        for candidate in candidates
    ]
    if (
        payloads
        and len({_assignment_signature(item["assignments"]) for item in payloads}) < 2
    ):
        alternative = json.loads(json.dumps(payloads[0]))
        alternative["key"] = "role_opportunity_alternative"
        alternative["label"] = "角色机会轮换备选"
        alternative["metadata"] = {
            **(alternative.get("metadata") or {}),
            "alternative_basis": "role_opportunity_rotation",
        }
        for group in alternative["assignments"]:
            roles = [member["role"] for member in group["members"]]
            if len(roles) > 1:
                roles = roles[1:] + roles[:1]
                for member, role in zip(group["members"], roles, strict=True):
                    member["role"] = role
        alternative["fairness"] = _fairness_metrics(
            alternative["assignments"], readiness
        )
        payloads.append(alternative)
    conflicts = []
    for payload in payloads:
        reason = (payload.get("metadata") or {}).get("fallback_reason")
        if reason and {"code": reason} not in conflicts:
            conflicts.append({"code": reason})
    run.candidates = payloads
    run.conflict_explanations = conflicts
    run.candidate_count = len(payloads)
    expected_student_ids = {profile.user_id for profile in profiles}
    candidate_blockers = {
        candidate["key"]: _assignment_constraint_blockers(
            assignments=candidate["assignments"],
            expected_student_ids=expected_student_ids,
            policy=policy,
            decision_point=point,
            locked_assignments={
                int(student_id): int(group_no)
                for student_id, group_no in normalized_locks.items()
            },
        )
        for candidate in payloads
    }
    for candidate in payloads:
        candidate["constraint_status"] = (
            "blocked" if candidate_blockers[candidate["key"]] else "passed"
        )
        candidate["constraint_blockers"] = candidate_blockers[candidate["key"]]
    run.status = (
        GroupingCandidateRun.Status.READY
        if any(not blockers for blockers in candidate_blockers.values())
        else GroupingCandidateRun.Status.BLOCKED
    )
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            "candidates",
            "conflict_explanations",
            "candidate_count",
            "status",
            "finished_at",
        ]
    )
    point.status = GroupingDecisionPoint.Status.CANDIDATE_READY
    point.save(update_fields=["status"])
    for candidate in payloads:
        metrics = candidate["fairness"]
        blockers = candidate_blockers[candidate["key"]]
        GroupingFairnessAudit.objects.create(
            candidate_run=run,
            candidate_key=candidate["key"],
            status=(
                GroupingFairnessAudit.Status.BLOCKED
                if blockers
                else GroupingFairnessAudit.Status.PASSED
            ),
            metrics=metrics,
            blockers=blockers,
        )
    return run


def adjusted_assignments(candidate: dict, adjustments: dict | None) -> list[dict]:
    assignments = json.loads(json.dumps(candidate["assignments"]))
    adjustments = adjustments if isinstance(adjustments, dict) else {}
    student_groups = {
        int(key): int(value)
        for key, value in (adjustments.get("student_groups") or {}).items()
    }
    roles = {
        int(key): str(value) for key, value in (adjustments.get("roles") or {}).items()
    }
    by_student = {}
    for group in assignments:
        for member in group["members"]:
            by_student[member["student_id"]] = member
    if student_groups:
        for group in assignments:
            group["members"] = [
                member
                for member in group["members"]
                if member["student_id"] not in student_groups
            ]
        groups_by_no = {group["group_no"]: group for group in assignments}
        for student_id, group_no in student_groups.items():
            if student_id not in by_student or group_no not in groups_by_no:
                raise ValidationError("调整后的学生或小组不存在。")
            groups_by_no[group_no]["members"].append(by_student[student_id])
    for group in assignments:
        for member in group["members"]:
            if member["student_id"] in roles:
                member["role"] = roles[member["student_id"]]
    return assignments


@transaction.atomic
def confirm_grouping_candidate(
    *,
    run: GroupingCandidateRun,
    candidate_key: str,
    collaboration: ClassroomGroupCollaboration,
    actor,
    adjustments: dict | None = None,
    note: str = "",
) -> tuple[GroupingPlanVersion, list[dict]]:
    if run.status != GroupingCandidateRun.Status.READY:
        raise ValidationError("当前分组候选不可确认。")
    if (
        run.selected_candidate_key
        or run.plans.filter(collaboration=collaboration).exists()
    ):
        raise ValidationError("该分组候选已经确认。")
    candidate = next(
        (item for item in run.candidates if item.get("key") == candidate_key), None
    )
    if candidate is None:
        raise ValidationError("分组候选不存在。")
    fairness = GroupingFairnessAudit.objects.filter(
        candidate_run=run,
        candidate_key=candidate_key,
    ).first()
    if fairness and fairness.status == GroupingFairnessAudit.Status.BLOCKED:
        raise ValidationError("该分组候选未通过完整性检查。")
    assignments = adjusted_assignments(candidate, adjustments)
    expected_ids = set(run.input_snapshot.get("student_ids") or [])
    locked_assignments = {
        int(student_id): int(group_no)
        for student_id, group_no in (
            run.input_snapshot.get("locked_assignments") or {}
        ).items()
    }
    blockers = _assignment_constraint_blockers(
        assignments=assignments,
        expected_student_ids={int(value) for value in expected_ids},
        policy=run.policy,
        decision_point=run.decision_point,
        locked_assignments=locked_assignments,
    )
    blocker_messages = {
        "student_assignment_duplicate": "每名学生只能进入一个小组。",
        "student_assignment_missing": "每名学生都必须进入一个小组。",
        "group_size_out_of_range": "调整后的小组人数不符合当前分组标准。",
        "teacher_lock_changed": "已锁定学生不能移动到其他小组。",
        "prohibited_pair_together": "调整结果违反了学生安全分开约束。",
        "required_group_role_missing": "调整结果缺少每组必设角色。",
        "invalid_member_role": "调整结果包含不正确的小组角色。",
    }
    if blockers:
        raise ValidationError(blocker_messages.get(blockers[0], "分组约束检查未通过。"))
    readiness = _readiness_map(
        run.decision_point.classroom_session,
        _profiles(run.decision_point.classroom_session),
    )
    adjusted_metrics = _fairness_metrics(assignments, readiness)
    GroupingFairnessAudit.objects.get_or_create(
        candidate_run=run,
        candidate_key=candidate_key,
        defaults={
            "status": GroupingFairnessAudit.Status.PASSED,
            "metrics": adjusted_metrics,
            "blockers": [],
        },
    )
    active = (
        GroupingPlanVersion.objects.select_for_update()
        .filter(
            collaboration=collaboration,
            status__in=[
                GroupingPlanVersion.Status.ACTIVE,
                GroupingPlanVersion.Status.CONFIRMED,
            ],
        )
        .first()
    )
    latest_plan_version = (
        GroupingPlanVersion.objects.filter(collaboration=collaboration).aggregate(
            value=Max("plan_version")
        )["value"]
        or 0
    )
    latest_group_version = (
        collaboration.groups.aggregate(value=Max("plan_version"))["value"] or 0
    )
    next_version = max(latest_plan_version, latest_group_version) + 1
    now = timezone.now()
    plan = GroupingPlanVersion.objects.create(
        decision_point=run.decision_point,
        collaboration=collaboration,
        candidate_run=run,
        supersedes=active,
        plan_version=next_version,
        candidate_key=candidate_key,
        assignments=assignments,
        status=GroupingPlanVersion.Status.REVIEWED,
        adjustment_note=note[:500],
        confirmed_by=actor,
        confirmed_at=now,
    )
    decision_adjustments = json.loads(json.dumps(adjustments or {}))
    decision_adjustments["reviewed_fairness"] = adjusted_metrics
    GroupingTeacherDecision.objects.create(
        candidate_run=run,
        plan=plan,
        action=(
            GroupingTeacherDecision.Action.ADJUST
            if adjustments
            else GroupingTeacherDecision.Action.ACCEPT
        ),
        candidate_key=candidate_key,
        adjustments=decision_adjustments,
        note=note[:500],
        actor=actor,
    )
    run.selected_candidate_key = candidate_key
    run.save(update_fields=["selected_candidate_key"])
    run.decision_point.status = GroupingDecisionPoint.Status.REVIEWED
    run.decision_point.save(update_fields=["status"])
    return plan, assignments


@transaction.atomic
def activate_reviewed_grouping_plan(
    *,
    plan: GroupingPlanVersion,
    actor,
) -> tuple[GroupingPlanVersion, GroupingPlanVersion | None]:
    """Activate only a teacher-reviewed plan; no classroom groups are created here."""
    plan = (
        GroupingPlanVersion.objects.select_for_update()
        .select_related("decision_point", "candidate_run", "candidate_run__policy")
        .get(pk=plan.pk)
    )
    if plan.status == GroupingPlanVersion.Status.ACTIVE:
        return plan, None
    if plan.status != GroupingPlanVersion.Status.REVIEWED:
        raise ValidationError("只有教师已复核的分组方案可以启用。")
    current_active = (
        GroupingPlanVersion.objects.select_for_update()
        .filter(
            collaboration=plan.collaboration,
            status__in=[
                GroupingPlanVersion.Status.ACTIVE,
                GroupingPlanVersion.Status.CONFIRMED,
            ],
        )
        .exclude(pk=plan.pk)
        .select_related("decision_point")
        .first()
    )
    now = timezone.now()
    if (
        current_active
        and current_active.decision_point.stability_until
        and current_active.decision_point.stability_until > now
    ):
        local_until = timezone.localtime(current_active.decision_point.stability_until)
        raise ValidationError(
            f"当前小组仍在稳定期内（至 {local_until:%Y-%m-%d %H:%M}），暂不能替换。"
        )
    current_student_ids = {
        profile.user_id for profile in _profiles(plan.decision_point.classroom_session)
    }
    expected_student_ids = {
        int(value)
        for value in plan.candidate_run.input_snapshot.get("student_ids") or []
    }
    if current_student_ids != expected_student_ids:
        raise ValidationError("班级成员已发生变化，请重新生成分组候选。")
    locked_assignments = {
        int(student_id): int(group_no)
        for student_id, group_no in (
            plan.candidate_run.input_snapshot.get("locked_assignments") or {}
        ).items()
    }
    blockers = _assignment_constraint_blockers(
        assignments=plan.assignments,
        expected_student_ids=expected_student_ids,
        policy=plan.candidate_run.policy,
        decision_point=plan.decision_point,
        locked_assignments=locked_assignments,
    )
    if blockers:
        raise ValidationError("分组方案在启用前复核未通过，请重新生成候选。")
    if current_active:
        current_active.status = GroupingPlanVersion.Status.ARCHIVED
        current_active.archived_at = now
        current_active.save(update_fields=["status", "archived_at"])
        current_active.decision_point.status = GroupingDecisionPoint.Status.CLOSED
        current_active.decision_point.save(update_fields=["status"])
    plan.status = GroupingPlanVersion.Status.ACTIVE
    plan.activated_by = actor
    plan.activated_at = now
    plan.save(update_fields=["status", "activated_by", "activated_at"])
    plan.decision_point.status = GroupingDecisionPoint.Status.ACTIVE
    plan.decision_point.save(update_fields=["status"])
    return plan, current_active


@transaction.atomic
def mark_grouping_plan_notified(
    *,
    plan: GroupingPlanVersion,
    actor,
) -> tuple[GroupingPlanVersion, bool]:
    plan = (
        GroupingPlanVersion.objects.select_for_update()
        .select_related("decision_point")
        .get(pk=plan.pk)
    )
    if plan.status != GroupingPlanVersion.Status.ACTIVE:
        raise ValidationError("只有已启用的分组方案可以通知学生。")
    if plan.notified_at:
        return plan, False
    plan.notified_by = actor
    plan.notified_at = timezone.now()
    plan.save(update_fields=["notified_by", "notified_at"])
    plan.decision_point.status = GroupingDecisionPoint.Status.NOTIFIED
    plan.decision_point.save(update_fields=["status"])
    return plan, True


def record_confirmed_plan_evidence(*, plan: GroupingPlanVersion):
    if plan.status != GroupingPlanVersion.Status.ACTIVE or not plan.activated_at:
        raise ValidationError("只有已经启用的分组方案可以记录实际分组与机会。")
    now = plan.activated_at
    subject = plan.decision_point.course.subject
    class_group = plan.decision_point.class_group
    opportunity_requirements = plan.decision_point.opportunity_requirements or {}
    required_for_every_student = set(
        opportunity_requirements.get("required_for_every_student") or []
    )
    runtime_settings = plan.candidate_run.input_snapshot.get("runtime_settings") or {}
    for group in plan.assignments:
        member_ids = sorted(item["student_id"] for item in group["members"])
        for left, right in combinations(member_ids, 2):
            row, _created = GroupingPairHistory.objects.get_or_create(
                school=plan.decision_point.school,
                class_group=class_group,
                subject=subject,
                left_student_id=left,
                right_student_id=right,
                defaults={"last_collaborated_at": now},
            )
            row.collaboration_count += 1
            row.last_collaborated_at = now
            row.save(update_fields=["collaboration_count", "last_collaborated_at"])
        for member in group["members"]:
            allocated = {
                "collaboration": True,
                "document_edit": bool(
                    runtime_settings.get("allow_onlyoffice_edit", True)
                ),
                "file_share": bool(runtime_settings.get("allow_student_upload", True)),
                "presentation": member.get("role") == "presenter",
                "leadership": member.get("role") in {"coordinator", "leader"},
            }
            for key in required_for_every_student:
                allocated.setdefault(str(key), True)
            audit, created = GroupingOpportunityAudit.objects.get_or_create(
                plan=plan,
                student_id=member["student_id"],
                defaults={
                    "group_no": group["group_no"],
                    "role": member.get("role", ""),
                    "opportunities": {
                        "allocated": allocated,
                        "required_for_every_student": sorted(
                            required_for_every_student
                        ),
                        "resource_requirements": plan.decision_point.resource_requirements,
                        "activated_at": now.isoformat(),
                    },
                },
            )
            if not created and (
                audit.group_no != group["group_no"]
                or audit.role != member.get("role", "")
                or audit.opportunities
                != {
                    "allocated": allocated,
                    "required_for_every_student": sorted(required_for_every_student),
                    "resource_requirements": plan.decision_point.resource_requirements,
                    "activated_at": now.isoformat(),
                }
            ):
                raise ValidationError("分组学习机会记录与已保存版本不一致。")


def capture_grouping_outcomes(*, collaboration: ClassroomGroupCollaboration) -> int:
    plan = GroupingPlanVersion.objects.filter(
        collaboration=collaboration,
        plan_version=collaboration.active_plan_version,
    ).first()
    if plan is None:
        return 0
    observed_at = collaboration.closed_at or timezone.now()
    created = 0
    groups = collaboration.groups.filter(
        plan_version=collaboration.active_plan_version,
    ).prefetch_related("members", "files")
    for group in groups:
        individual_results = []
        files = list(group.files.all())
        for member in group.members.all():
            opportunity_rows = (
                LearningOpportunity.objects.filter(
                    classroom_session=collaboration.session,
                    student_id=member.student_id,
                    object_id=str(group.id),
                )
                .prefetch_related("transition_facts")
                .order_by("content_type", "opportunity_id")
            )
            actual_opportunities = [
                {
                    "opportunity_id": str(opportunity.opportunity_id),
                    "content_type": opportunity.content_type,
                    "states": [
                        fact.state
                        for fact in opportunity.transition_facts.order_by(
                            "occurred_at", "recorded_at", "id"
                        )
                    ],
                }
                for opportunity in opportunity_rows
            ]
            mastery = (
                StudentMasterySnapshot.objects.filter(
                    student_id=member.student_id,
                    subject=plan.decision_point.course.subject,
                    observed_at__lte=observed_at,
                )
                .order_by("-observed_at", "-id")
                .first()
            )
            individual_results.append(
                {
                    "student_id": member.student_id,
                    "role": member.role,
                    "shared_file_count": sum(
                        1 for item in files if item.uploader_id == member.student_id
                    ),
                    "actual_opportunities": actual_opportunities,
                    "mastery_snapshot_id": mastery.id if mastery else None,
                    "mastery_score": mastery.mastery_score if mastery else None,
                    "mastery_data_status": mastery.data_status if mastery else "",
                }
            )
        _row, was_created = GroupingOutcomeSnapshot.objects.get_or_create(
            plan=plan,
            group_no=group.group_no,
            observed_at=observed_at,
            defaults={
                "group_result": {
                    "document_version": group.document_version,
                    "shared_file_count": len(files),
                    "member_count": group.members.count(),
                },
                "individual_results": individual_results,
            },
        )
        created += int(was_created)
    return created
