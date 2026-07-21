from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

from django.db.models import Case, F, IntegerField, Q, Value, When
from django.utils import timezone

from learning.models import StudentSubjectBand


GROUPING_POLICY_VERSION = "group-policy-v2"
MIN_READINESS_COVERAGE = 0.8
BAND_SCORE = {"A": 3.0, "B": 2.0, "C": 1.0}


@dataclass(frozen=True)
class GroupingPlan:
    chunks: list[list]
    metadata: dict


def _balanced_capacities(student_count: int, group_size: int) -> list[int]:
    group_count = max(1, math.ceil(student_count / group_size))
    base, remainder = divmod(student_count, group_count)
    return [base + (1 if index < remainder else 0) for index in range(group_count)]


def _random_chunks(
    profiles: list,
    capacities: list[int],
    seed: int,
    locked_assignments: dict[int, int] | None = None,
) -> list[list]:
    locked_assignments = {
        int(student_id): int(group_no)
        for student_id, group_no in (locked_assignments or {}).items()
    }
    rows = [
        profile for profile in profiles if profile.user_id not in locked_assignments
    ]
    random.Random(seed).shuffle(rows)
    chunks = [[] for _capacity in capacities]
    by_student = {profile.user_id: profile for profile in profiles}
    for student_id, group_no in locked_assignments.items():
        if student_id in by_student and 1 <= group_no <= len(chunks):
            chunks[group_no - 1].append(by_student[student_id])
    offset = 0
    for index, capacity in enumerate(capacities):
        remaining = capacity - len(chunks[index])
        chunks[index].extend(rows[offset : offset + remaining])
        offset += remaining
    return chunks


def _active_formal_bands(session, profiles: list) -> dict[int, StudentSubjectBand]:
    now = timezone.now()
    student_ids = [profile.user_id for profile in profiles]
    rows = (
        StudentSubjectBand.objects.filter(
            student_id__in=student_ids,
            subject=session.course.subject,
            valid_from__lte=now,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gt=now))
        .filter(Q(course=session.course) | Q(course__isnull=True))
        .annotate(
            course_priority=Case(
                When(course=session.course, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("student_id", "course_priority", "-valid_from", "-id")
    )
    result = {}
    for row in rows:
        result.setdefault(row.student_id, row)
    return result


def _task_readiness_score(band: StudentSubjectBand, session) -> float | None:
    evidence = (
        band.evidence_snapshot if isinstance(band.evidence_snapshot, dict) else {}
    )
    task = evidence.get("task_readiness")
    if not isinstance(task, dict):
        return None
    lesson_ids = task.get("lesson_ids", [])
    if task.get("lesson_id") not in (None, ""):
        lesson_ids = [task.get("lesson_id")]
    try:
        normalized_lesson_ids = {int(value) for value in lesson_ids}
    except (TypeError, ValueError):
        return None
    course_id = task.get("course_id")
    lesson_matches = bool(
        session.lesson_id and session.lesson_id in normalized_lesson_ids
    )
    course_matches = str(course_id or "") == str(session.course_id)
    if not lesson_matches and not course_matches:
        return None
    try:
        score = float(task["score"])
    except (KeyError, TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))


def _historical_pair_counts(session) -> Counter:
    from courses.models import ClassroomGroupMember

    rows = ClassroomGroupMember.objects.filter(
        collaboration__session__class_group=session.class_group,
        collaboration__session__course__subject=session.course.subject,
    ).values_list("group_id", "student_id")
    members_by_group = defaultdict(list)
    for group_id, student_id in rows:
        members_by_group[group_id].append(student_id)
    counts = Counter()
    for student_ids in members_by_group.values():
        for pair in combinations(sorted(set(student_ids)), 2):
            counts[pair] += 1
    return counts


def _active_pair_counts(session) -> Counter:
    from courses.models import ClassroomGroupMember

    rows = ClassroomGroupMember.objects.filter(
        collaboration__session=session,
        plan_version=F("collaboration__active_plan_version"),
        group__is_active=True,
    ).values_list("group_id", "student_id")
    members_by_group = defaultdict(list)
    for group_id, student_id in rows:
        members_by_group[group_id].append(student_id)
    counts = Counter()
    for student_ids in members_by_group.values():
        for pair in combinations(sorted(set(student_ids)), 2):
            counts[pair] += 1
    return counts


def _pair_cost(candidate_id: int, group: list, pair_counts: Counter) -> int:
    return sum(
        pair_counts[tuple(sorted((candidate_id, member.user_id)))] for member in group
    )


def _bridged_chunks(
    profiles: list,
    readiness: dict[int, float],
    capacities: list[int],
    pair_counts: Counter,
    seed: int,
) -> list[list]:
    rng = random.Random(seed)
    tie_breakers = {profile.user_id: rng.random() for profile in profiles}
    sorted_rows = sorted(
        profiles,
        key=lambda profile: (
            -readiness[profile.user_id],
            tie_breakers[profile.user_id],
        ),
    )
    ordered = []
    left, right = 0, len(sorted_rows) - 1
    while left <= right:
        ordered.append(sorted_rows[left])
        left += 1
        if left <= right:
            ordered.append(sorted_rows[right])
            right -= 1

    groups = [[] for _capacity in capacities]
    score_sums = [0.0 for _capacity in capacities]
    overall_mean = sum(readiness.values()) / max(len(readiness), 1)
    for profile in ordered:
        candidates = [
            index
            for index, capacity in enumerate(capacities)
            if len(groups[index]) < capacity
        ]
        chosen = min(
            candidates,
            key=lambda index: (
                _pair_cost(profile.user_id, groups[index], pair_counts),
                abs(
                    (score_sums[index] + readiness[profile.user_id])
                    / (len(groups[index]) + 1)
                    - overall_mean
                ),
                len(groups[index]) / capacities[index],
                index,
            ),
        )
        groups[chosen].append(profile)
        score_sums[chosen] += readiness[profile.user_id]
    return groups


def _aligned_chunks(
    profiles: list,
    readiness: dict[int, float],
    capacities: list[int],
    seed: int,
) -> list[list]:
    rng = random.Random(seed)
    tie_breakers = {profile.user_id: rng.random() for profile in profiles}
    rows = sorted(
        profiles,
        key=lambda profile: (
            -readiness[profile.user_id],
            tie_breakers[profile.user_id],
        ),
    )
    chunks = []
    offset = 0
    for capacity in capacities:
        chunks.append(rows[offset : offset + capacity])
        offset += capacity
    return chunks


def _pair_summary(chunks: list[list], pair_counts: Counter) -> dict:
    repeated = []
    for chunk in chunks:
        for left, right in combinations(
            sorted(profile.user_id for profile in chunk), 2
        ):
            repeated.append(pair_counts[(left, right)])
    return {
        "pair_count": len(repeated),
        "prior_repeat_total": sum(repeated),
        "prior_repeat_max": max(repeated, default=0),
    }


def build_grouping_plan(
    *,
    session,
    profiles: list,
    group_size: int,
    strategy: str,
    seed: int,
    plan_version: int,
) -> GroupingPlan:
    from courses.models import ClassroomGroupCollaboration

    capacities = _balanced_capacities(len(profiles), group_size)
    bands = _active_formal_bands(session, profiles)
    pair_counts = _historical_pair_counts(session)
    formal_readiness = {
        student_id: BAND_SCORE[band.band]
        for student_id, band in bands.items()
        if band.band in BAND_SCORE
    }
    task_readiness = {
        student_id: score
        for student_id, band in bands.items()
        if (score := _task_readiness_score(band, session)) is not None
    }
    fallback_reason = ""
    effective_strategy = "random_baseline"
    readiness = {}

    if strategy == ClassroomGroupCollaboration.GroupingStrategy.SAME_LAYER:
        readiness = formal_readiness
        effective_strategy = "readiness_aligned"
    elif strategy == ClassroomGroupCollaboration.GroupingStrategy.BALANCED_LAYER:
        readiness = formal_readiness
        effective_strategy = "readiness_bridged"
    elif strategy == ClassroomGroupCollaboration.GroupingStrategy.AI_LAYER:
        readiness = task_readiness
        effective_strategy = "skill_complementary"
    elif strategy == ClassroomGroupCollaboration.GroupingStrategy.STABLE_PROJECT:
        readiness = task_readiness
        effective_strategy = "stable_project"
    elif strategy == ClassroomGroupCollaboration.GroupingStrategy.MANUAL:
        fallback_reason = "manual_assignments_not_supplied"
    elif strategy != ClassroomGroupCollaboration.GroupingStrategy.RANDOM:
        fallback_reason = "unsupported_strategy"

    coverage = len(readiness) / len(profiles) if profiles else 0.0
    readiness_usable = (
        coverage >= MIN_READINESS_COVERAGE
        and len(set(readiness.values())) >= 2
        and all(profile.user_id in readiness for profile in profiles)
    )
    if effective_strategy != "random_baseline" and not readiness_usable:
        fallback_reason = fallback_reason or "insufficient_valid_readiness"
        effective_strategy = "random_baseline"

    if effective_strategy == "readiness_aligned":
        chunks = _aligned_chunks(profiles, readiness, capacities, seed)
    elif effective_strategy in {
        "readiness_bridged",
        "skill_complementary",
        "stable_project",
    }:
        chunks = _bridged_chunks(
            profiles,
            readiness,
            capacities,
            pair_counts,
            seed,
        )
    else:
        chunks = _random_chunks(profiles, capacities, seed)

    metadata = {
        "strategy_version": GROUPING_POLICY_VERSION,
        "requested_strategy": strategy,
        "effective_strategy": effective_strategy,
        "plan_version": plan_version,
        "seed": seed,
        "formal_band_coverage": round(len(formal_readiness) / len(profiles), 4),
        "task_readiness_coverage": round(len(task_readiness) / len(profiles), 4),
        "fallback_reason": fallback_reason,
        "pair_repeat_summary": _pair_summary(chunks, pair_counts),
    }
    return GroupingPlan(chunks=chunks, metadata=metadata)


def _candidate_readiness(session, profiles: list, strategy: str):
    bands = _active_formal_bands(session, profiles)
    formal = {
        student_id: BAND_SCORE[band.band]
        for student_id, band in bands.items()
        if band.band in BAND_SCORE
    }
    task = {
        student_id: score
        for student_id, band in bands.items()
        if (score := _task_readiness_score(band, session)) is not None
    }
    if strategy == "task":
        return task
    return formal


def _cp_sat_chunks(
    profiles: list,
    capacities: list[int],
    readiness: dict[int, float],
    pair_counts: Counter,
    active_pair_counts: Counter,
    *,
    objective: str,
    seed: int,
    locked_assignments: dict[int, int] | None = None,
) -> tuple[list[list], str]:
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return [], "ortools_unavailable"
    if (
        not profiles
        or not readiness
        or not all(profile.user_id in readiness for profile in profiles)
    ):
        return [], "insufficient_valid_readiness"
    group_count = len(capacities)
    model = cp_model.CpModel()
    assignment = {
        (index, group): model.NewBoolVar(f"student_{index}_group_{group}")
        for index in range(len(profiles))
        for group in range(group_count)
    }
    for index in range(len(profiles)):
        model.Add(sum(assignment[index, group] for group in range(group_count)) == 1)
    for group, capacity in enumerate(capacities):
        members = [assignment[index, group] for index in range(len(profiles))]
        model.Add(sum(members) == capacity)
    profile_index = {profile.user_id: index for index, profile in enumerate(profiles)}
    for student_id, group_no in (locked_assignments or {}).items():
        try:
            index = profile_index[int(student_id)]
            group = int(group_no) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= group < group_count:
            model.Add(assignment[index, group] == 1)

    score_scale = 100
    scores = [
        int(round(readiness[profile.user_id] * score_scale)) for profile in profiles
    ]
    target = round(sum(scores) / max(group_count, 1))
    group_scores = []
    deviations = []
    for group in range(group_count):
        group_score = model.NewIntVar(0, sum(scores), f"group_score_{group}")
        model.Add(
            group_score
            == sum(
                scores[index] * assignment[index, group]
                for index in range(len(profiles))
            )
        )
        deviation = model.NewIntVar(0, sum(scores), f"group_deviation_{group}")
        model.AddAbsEquality(deviation, group_score - target)
        group_scores.append(group_score)
        deviations.append(deviation)

    objective_terms = (
        []
        if objective == "aligned"
        else [
            deviation * (2 if objective == "stable" else 10) for deviation in deviations
        ]
    )
    pair_variables = []
    for left in range(len(profiles)):
        for right in range(left + 1, len(profiles)):
            left_id = profiles[left].user_id
            right_id = profiles[right].user_id
            history_cost = pair_counts[tuple(sorted((left_id, right_id)))]
            active_pair = active_pair_counts[tuple(sorted((left_id, right_id)))]
            readiness_cost = abs(scores[left] - scores[right])
            if objective == "stable" and history_cost == 0 and active_pair == 0:
                continue
            if objective == "aligned" and readiness_cost == 0 and history_cost == 0:
                continue
            weight = history_cost * (5 if objective == "stable" else 100)
            if objective == "aligned":
                weight += readiness_cost * 10
            elif objective == "stable":
                weight -= active_pair * 300
            if weight == 0:
                continue
            for group in range(group_count):
                both = model.NewBoolVar(f"pair_{left}_{right}_{group}")
                model.AddBoolAnd(
                    [assignment[left, group], assignment[right, group]]
                ).OnlyEnforceIf(both)
                model.AddBoolOr(
                    [assignment[left, group].Not(), assignment[right, group].Not()]
                ).OnlyEnforceIf(both.Not())
                pair_variables.append((both, weight))
    objective_terms.extend(variable * weight for variable, weight in pair_variables)
    model.Minimize(sum(objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3.0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(seed % 2_000_000_000)
    status = solver.Solve(model)
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return [], "constraints_unsatisfied"
    chunks = [[] for _ in capacities]
    for index, profile in enumerate(profiles):
        selected = next(
            group
            for group in range(group_count)
            if solver.Value(assignment[index, group])
        )
        chunks[selected].append(profile)
    return chunks, ""


def build_grouping_candidates(
    *,
    session,
    profiles: list,
    group_size: int,
    strategy: str,
    seed: int,
    plan_version: int,
    locked_assignments: dict[int, int] | None = None,
) -> list[dict]:
    capacities = _balanced_capacities(len(profiles), group_size)
    pair_counts = _historical_pair_counts(session)
    active_pair_counts = _active_pair_counts(session)
    candidates = []
    random_chunks = _random_chunks(
        profiles,
        capacities,
        seed,
        locked_assignments=locked_assignments,
    )
    candidates.append(
        {
            "key": "random",
            "label": "随机基线",
            "chunks": random_chunks,
            "metadata": {
                "effective_strategy": "random_baseline",
                "fallback_reason": "",
            },
        }
    )
    if strategy in {"ai_layer", "stable_project"}:
        readiness = _candidate_readiness(session, profiles, "task")
    else:
        readiness = _candidate_readiness(session, profiles, "formal")
    coverage = len(readiness) / len(profiles) if profiles else 0
    if coverage >= MIN_READINESS_COVERAGE and len(set(readiness.values())) >= 2:
        task_objective = (
            "aligned"
            if strategy == "same_layer"
            else "stable"
            if strategy == "stable_project"
            else "bridged"
        )
        candidate_failure_reasons = []
        for key, label, objective in (
            ("task_preferred", "任务准备度优先", task_objective),
            ("stability_preferred", "合作稳定优先", "stable"),
        ):
            chunks, reason = _cp_sat_chunks(
                profiles,
                capacities,
                readiness,
                pair_counts,
                active_pair_counts,
                objective=objective,
                seed=seed + len(candidates),
                locked_assignments=locked_assignments,
            )
            if chunks:
                candidates.append(
                    {
                        "key": key,
                        "label": label,
                        "chunks": chunks,
                        "metadata": {
                            "effective_strategy": {
                                "ai_layer": "skill_complementary",
                                "same_layer": "readiness_aligned",
                                "stable_project": "stable_project",
                            }.get(strategy, "readiness_bridged"),
                            "formal_or_task_coverage": round(coverage, 4),
                            "fallback_reason": reason,
                        },
                    }
                )
            elif reason:
                candidate_failure_reasons.append(reason)
        if len(candidates) == 1 and candidate_failure_reasons:
            candidates[0]["metadata"]["fallback_reason"] = next(
                (
                    item
                    for item in ("ortools_unavailable", "constraints_unsatisfied")
                    if item in candidate_failure_reasons
                ),
                candidate_failure_reasons[0],
            )
    else:
        candidates[0]["metadata"] = {
            "effective_strategy": "random_baseline",
            "formal_or_task_coverage": round(coverage, 4),
            "fallback_reason": "insufficient_valid_readiness",
        }
    return candidates
