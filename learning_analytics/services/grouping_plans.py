from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations

from django.core.exceptions import ValidationError
from django.db import transaction
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
)
from school.models import StudentProfile


ALGORITHM_VERSION = "group-cp-sat-v1"
DEFAULT_ROLES = ["coordinator", "recorder", "resource", "presenter", "verifier"]


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


def _assignment_rows(candidate, roles: list[str]) -> list[dict]:
    rows = []
    for group_no, chunk in enumerate(candidate["chunks"], start=1):
        members = []
        for index, profile in enumerate(chunk):
            role = roles[index % len(roles)] if roles else "member"
            members.append(
                {
                    "student_id": profile.user_id,
                    "role": role,
                    "locked": False,
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


def _candidate_payload(candidate, roles, readiness):
    assignments = _assignment_rows(candidate, roles)
    metrics = _fairness_metrics(assignments, readiness)
    return {
        "key": candidate["key"],
        "label": candidate["label"],
        "assignments": assignments,
        "metadata": candidate["metadata"],
        "fairness": metrics,
    }


@transaction.atomic
def generate_grouping_candidate_run(
    *,
    session: ClassroomSession,
    actor,
    group_size: int | None = None,
    requested_strategy: str = "ai_layer",
    locked_assignments: dict[int, int] | None = None,
    runtime_settings: dict | None = None,
) -> GroupingCandidateRun:
    if session.status != ClassroomSession.Status.RUNNING:
        raise ValidationError("只有进行中的课堂可以生成分组候选。")
    policy = active_or_default_grouping_policy(session=session, actor=actor)
    profiles = _profiles(session)
    if not profiles:
        raise ValidationError("当前班级没有可分组的启用学生。")
    group_size = int(group_size or policy.group_size)
    if not policy.min_group_size <= group_size <= policy.max_group_size:
        raise ValidationError("每组人数不符合当前分组标准。")
    point, _created = GroupingDecisionPoint.objects.get_or_create(
        classroom_session=session,
        lesson_step=session.current_step,
        status__in=[
            GroupingDecisionPoint.Status.OPEN,
            GroupingDecisionPoint.Status.CANDIDATE_READY,
        ],
        defaults={
            "school": session.school,
            "class_group": session.class_group,
            "course": session.course,
            "policy": policy,
            "trigger": GroupingDecisionPoint.Trigger.TEACHER_REQUEST,
            "task_context": {
                "lesson_id": session.lesson_id,
                "lesson_step_id": session.current_step_id,
            },
            "scheduled_for": timezone.now(),
            "status": GroupingDecisionPoint.Status.OPEN,
            "created_by": actor,
        },
    )
    seed = session.id * 100_000 + point.id
    normalized_locks = {
        str(int(student_id)): int(group_no)
        for student_id, group_no in (locked_assignments or {}).items()
        if str(student_id).isdigit() and str(group_no).isdigit()
    }
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
        "active_plan_version": getattr(
            getattr(session, "group_collaboration", None), "active_plan_version", 0
        ),
    }
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
    readiness = _readiness_map(session, profiles)
    payloads = [
        _candidate_payload(candidate, policy.role_scheme or DEFAULT_ROLES, readiness)
        for candidate in candidates
    ]
    conflicts = []
    if len(payloads) == 1 and payloads[0]["key"] == "random":
        reason = payloads[0]["metadata"].get("fallback_reason")
        if reason:
            conflicts.append({"code": reason})
    run.candidates = payloads
    run.conflict_explanations = conflicts
    run.candidate_count = len(payloads)
    run.status = (
        GroupingCandidateRun.Status.READY
        if payloads
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
        blockers = []
        if metrics["student_count"] != metrics["unique_student_count"]:
            blockers.append("student_assignment_duplicate")
        if metrics["unique_student_count"] != len(profiles):
            blockers.append("student_assignment_missing")
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
    assigned_ids = [
        member["student_id"] for group in assignments for member in group["members"]
    ]
    if set(assigned_ids) != expected_ids or len(assigned_ids) != len(expected_ids):
        raise ValidationError("每名学生必须且只能进入一个小组。")
    group_sizes = [len(group["members"]) for group in assignments]
    if any(
        size < run.policy.min_group_size or size > run.policy.max_group_size
        for size in group_sizes
    ):
        raise ValidationError("调整后的小组人数不符合当前分组标准。")
    locked_assignments = {
        int(student_id): int(group_no)
        for student_id, group_no in (
            run.input_snapshot.get("locked_assignments") or {}
        ).items()
    }
    final_groups = {
        int(member["student_id"]): int(group["group_no"])
        for group in assignments
        for member in group["members"]
    }
    if any(
        final_groups.get(student_id) != group_no
        for student_id, group_no in locked_assignments.items()
    ):
        raise ValidationError("已锁定学生不能移动到其他小组。")
    readiness = _readiness_map(
        run.decision_point.classroom_session,
        _profiles(run.decision_point.classroom_session),
    )
    adjusted_metrics = _fairness_metrics(assignments, readiness)
    GroupingFairnessAudit.objects.update_or_create(
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
            status=GroupingPlanVersion.Status.CONFIRMED,
        )
        .first()
    )
    next_version = (
        active.plan_version if active else collaboration.active_plan_version
    ) + 1
    now = timezone.now()
    if active:
        active.status = GroupingPlanVersion.Status.ARCHIVED
        active.archived_at = now
        active.save(update_fields=["status", "archived_at"])
    plan = GroupingPlanVersion.objects.create(
        decision_point=run.decision_point,
        collaboration=collaboration,
        candidate_run=run,
        supersedes=active,
        plan_version=next_version,
        candidate_key=candidate_key,
        assignments=assignments,
        status=GroupingPlanVersion.Status.CONFIRMED,
        adjustment_note=note[:500],
        confirmed_by=actor,
        confirmed_at=now,
    )
    GroupingTeacherDecision.objects.create(
        candidate_run=run,
        plan=plan,
        action=(
            GroupingTeacherDecision.Action.ADJUST
            if adjustments
            else GroupingTeacherDecision.Action.ACCEPT
        ),
        candidate_key=candidate_key,
        adjustments=adjustments or {},
        note=note[:500],
        actor=actor,
    )
    run.selected_candidate_key = candidate_key
    run.save(update_fields=["selected_candidate_key"])
    run.decision_point.status = GroupingDecisionPoint.Status.CONFIRMED
    run.decision_point.save(update_fields=["status"])
    return plan, assignments


def record_confirmed_plan_evidence(*, plan: GroupingPlanVersion):
    now = plan.confirmed_at
    subject = plan.decision_point.course.subject
    class_group = plan.decision_point.class_group
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
            GroupingOpportunityAudit.objects.update_or_create(
                plan=plan,
                student_id=member["student_id"],
                defaults={
                    "group_no": group["group_no"],
                    "role": member.get("role", ""),
                    "opportunities": {
                        "collaboration": True,
                        "document_edit": True,
                        "presentation": member.get("role") == "presenter",
                        "leadership": member.get("role") == "coordinator",
                    },
                },
            )


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
