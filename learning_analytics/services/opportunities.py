from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from learning_analytics.models import (
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from school.models import StudentProfile


class OpportunityError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


EVENT_CONTENT_TYPES = {
    "resource.opened": {
        LearningOpportunity.ContentType.RESOURCE,
        LearningOpportunity.ContentType.VIDEO,
        LearningOpportunity.ContentType.DOCUMENT,
    },
    "video.progress": {LearningOpportunity.ContentType.VIDEO},
    "document.progress": {LearningOpportunity.ContentType.DOCUMENT},
    "group.document.opened": {LearningOpportunity.ContentType.DOCUMENT},
    "group.file.shared": {LearningOpportunity.ContentType.TASK},
    "attendance.recorded": {LearningOpportunity.ContentType.ATTENDANCE},
    "quick_answer.responded": {LearningOpportunity.ContentType.INTERACTION},
    "item.submitted": {LearningOpportunity.ContentType.QUESTION},
    "item.graded": {
        LearningOpportunity.ContentType.QUESTION,
        LearningOpportunity.ContentType.TASK,
    },
    "task.submitted": {LearningOpportunity.ContentType.TASK},
    "learning_page.opened": {LearningOpportunity.ContentType.LEARNING_PAGE},
    "learning_page.block_viewed": {LearningOpportunity.ContentType.LEARNING_PAGE},
    "learning_page.form_submitted": {LearningOpportunity.ContentType.LEARNING_PAGE},
    "evaluation.rating.submitted": {
        LearningOpportunity.ContentType.TASK,
        LearningOpportunity.ContentType.PROJECT,
    },
}


def _payload_datetime(value, *, field_name: str):
    if value is None:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None or timezone.is_naive(parsed):
        raise OpportunityError(
            "release_time_invalid", f"{field_name} 必须包含明确时区。"
        )
    return parsed


def _target_layer_values(target_layers: list[str]) -> set[str]:
    if "all" in target_layers:
        return {"A", "B", "C", "unassigned"}
    values = set()
    for item in target_layers:
        values.update(part for part in item.split("/") if part in {"A", "B", "C"})
    return values


def _delivered_band(target_layers: list[str]) -> str:
    if "all" in target_layers:
        return "all"
    values = _target_layer_values(target_layers)
    return "/".join(item for item in ("A", "B", "C") if item in values)


def _eligible_profiles(release_event: LearningEventV2):
    target_layers = list(release_event.payload.get("target_layers") or ["all"])
    allowed = _target_layer_values(target_layers)
    profiles = StudentProfile.objects.select_related("user").filter(
        class_group=release_event.class_group,
        user__school=release_event.school,
        user__is_active=True,
    )
    explicit_student_ids = release_event.payload.get("target_student_ids")
    if explicit_student_ids:
        profiles = profiles.filter(user_id__in=explicit_student_ids)
    if "unassigned" in allowed:
        return profiles
    return profiles.filter(current_layer__in=allowed)


def _create_transition(
    *,
    opportunity: LearningOpportunity,
    state: str,
    source_event: LearningEventV2,
    occurred_at,
    reason_code: str = "",
    metadata: dict | None = None,
) -> tuple[LearningOpportunityTransitionFact, bool]:
    terminal = (
        LearningOpportunityTransitionFact.objects.select_for_update()
        .filter(
            opportunity=opportunity,
            state__in=LearningOpportunityTransitionFact.TERMINAL_STATES,
        )
        .first()
    )
    if state in LearningOpportunityTransitionFact.TERMINAL_STATES:
        if terminal:
            if terminal.state == state:
                return terminal, False
            raise OpportunityError(
                "opportunity_terminal_conflict", "学习机会已经进入其他终止状态。"
            )
    elif terminal and occurred_at >= terminal.occurred_at:
        raise OpportunityError("opportunity_closed", "事件发生时学习机会已经终止。")

    repeatable_states = {
        LearningOpportunityTransitionFact.State.SUBMITTED,
        LearningOpportunityTransitionFact.State.GRADED,
    }
    earliest = None
    if state not in repeatable_states:
        earliest = (
            LearningOpportunityTransitionFact.objects.filter(
                opportunity=opportunity,
                state=state,
            )
            .order_by("occurred_at", "id")
            .first()
        )
        if earliest and occurred_at >= earliest.occurred_at:
            return earliest, False

    values = dict(metadata or {})
    if earliest:
        values["late_earlier_evidence"] = True
    fact = LearningOpportunityTransitionFact(
        opportunity=opportunity,
        state=state,
        source_event=source_event,
        actor=source_event.actor,
        reason_code=reason_code,
        metadata=values,
        occurred_at=occurred_at,
        recorded_at=source_event.server_received_at,
    )
    try:
        fact.save()
    except IntegrityError:
        existing = LearningOpportunityTransitionFact.objects.get(
            opportunity=opportunity,
            state=state,
            source_event=source_event,
        )
        return existing, False
    return fact, True


@transaction.atomic
def release_learning_opportunities(release_event: LearningEventV2) -> dict:
    if release_event.event_name != "content.released":
        raise OpportunityError(
            "release_event_invalid", "只有 content.released 可以生成学习机会。"
        )
    if not release_event.class_group_id or not release_event.subject_id:
        raise OpportunityError(
            "release_context_missing", "投放事件必须包含班级和学科。"
        )
    if not release_event.object_id or not release_event.object_version:
        raise OpportunityError(
            "content_version_missing", "投放内容必须包含对象 ID 和不可变版本。"
        )

    payload = release_event.payload
    available_from = _payload_datetime(
        payload.get("available_from"), field_name="available_from"
    )
    available_to = _payload_datetime(
        payload.get("available_to"), field_name="available_to"
    )
    assigned_at = release_event.client_occurred_at
    if available_from and available_from > assigned_at:
        raise OpportunityError(
            "future_release_requires_assignment",
            "未来开放的内容必须先使用 content.assigned，不能提前记录为已开放。",
        )
    available_from = assigned_at
    if available_to and available_to <= available_from:
        raise OpportunityError(
            "release_time_invalid", "available_to 必须晚于实际开放时间。"
        )

    target_layers = list(payload.get("target_layers") or ["all"])
    delivered_band = _delivered_band(target_layers)
    profiles = _eligible_profiles(release_event)
    explicit_student_ids = set(payload.get("target_student_ids") or [])
    if explicit_student_ids:
        eligible_student_ids = set(profiles.values_list("user_id", flat=True))
        if eligible_student_ids != explicit_student_ids:
            raise OpportunityError(
                "release_targets_invalid",
                "显式投放学生必须全部是当前班级的启用学生，并符合投放范围。",
            )
    created = 0
    existing = 0
    for profile in profiles.iterator():
        opportunity = LearningOpportunity.objects.filter(
            student=profile.user,
            release_event=release_event,
        ).first()
        if opportunity:
            existing += 1
            continue
        opportunity = LearningOpportunity(
            release_event=release_event,
            school=release_event.school,
            student=profile.user,
            class_group=release_event.class_group,
            subject=release_event.subject,
            course=release_event.course,
            lesson=release_event.lesson,
            classroom_session=release_event.classroom_session,
            lesson_step=release_event.lesson_step,
            assigned_by=release_event.actor,
            content_type=payload["content_type"],
            object_id=release_event.object_id,
            object_version=release_event.object_version,
            required=payload["required"],
            delivered_band=delivered_band,
            assigned_at=assigned_at,
            released_at=assigned_at,
            available_from=available_from,
            available_to=available_to,
        )
        opportunity.save()
        _create_transition(
            opportunity=opportunity,
            state=LearningOpportunityTransitionFact.State.ASSIGNED,
            source_event=release_event,
            occurred_at=assigned_at,
        )
        _create_transition(
            opportunity=opportunity,
            state=LearningOpportunityTransitionFact.State.RELEASED,
            source_event=release_event,
            occurred_at=assigned_at,
        )
        created += 1
    return {"opportunities_created": created, "opportunities_existing": existing}


def resolve_event_opportunity(
    *,
    actor,
    target_student,
    context: dict,
    event_data: dict,
) -> tuple[LearningOpportunity, list[str]]:
    opportunity_id = event_data.get("opportunity_id")
    if not opportunity_id:
        raise OpportunityError("opportunity_required", "该事件必须关联学习机会。")
    opportunity = (
        LearningOpportunity.objects.select_related(
            "student",
            "class_group",
            "subject",
            "course",
            "lesson",
            "classroom_session",
            "lesson_step",
        )
        .filter(opportunity_id=opportunity_id, school=actor.school)
        .first()
    )
    if opportunity is None:
        raise OpportunityError(
            "opportunity_not_found", "学习机会不存在或不属于当前学校。"
        )
    if target_student is None or opportunity.student_id != target_student.id:
        raise OpportunityError("opportunity_forbidden", "学习机会不属于事件目标学生。")

    context_pairs = (
        ("class_group", "class_group_id"),
        ("subject", "subject_id"),
        ("course", "course_id"),
        ("lesson", "lesson_id"),
        ("classroom_session", "classroom_session_id"),
        ("lesson_step", "lesson_step_id"),
    )
    for context_name, opportunity_field in context_pairs:
        context_object = context.get(context_name)
        opportunity_value = getattr(opportunity, opportunity_field)
        if context_object and opportunity_value != context_object.id:
            raise OpportunityError(
                "opportunity_context_mismatch", "学习机会与事件教学上下文不一致。"
            )
    if opportunity.object_id != event_data.get("object_id", ""):
        raise OpportunityError(
            "opportunity_object_mismatch", "学习机会与事件对象不一致。"
        )
    if (
        event_data.get("object_version")
        and opportunity.object_version != event_data["object_version"]
    ):
        raise OpportunityError(
            "opportunity_version_mismatch", "学习机会与事件对象版本不一致。"
        )
    allowed_content_types = EVENT_CONTENT_TYPES.get(event_data["event_name"])
    if allowed_content_types and opportunity.content_type not in allowed_content_types:
        raise OpportunityError(
            "opportunity_type_mismatch", "学习机会内容类型与事件不一致。"
        )

    occurred_at = event_data["client_occurred_at"]
    if occurred_at < opportunity.available_from:
        raise OpportunityError("opportunity_not_open", "事件发生时学习机会尚未开放。")
    terminal = (
        opportunity.transition_facts.filter(
            state__in=LearningOpportunityTransitionFact.TERMINAL_STATES,
            occurred_at__lte=occurred_at,
        )
        .order_by("occurred_at")
        .first()
    )
    if terminal:
        raise OpportunityError(
            "opportunity_closed", f"事件发生时学习机会状态为 {terminal.state}。"
        )

    quality_flags = []
    if opportunity.available_to and occurred_at > opportunity.available_to:
        quality_flags.append("after_opportunity_window")
    return opportunity, quality_flags


@transaction.atomic
def apply_event_to_opportunity(
    *,
    event: LearningEventV2,
    opportunity: LearningOpportunity,
) -> dict:
    states = []
    if event.event_name in {"resource.opened", "group.document.opened"}:
        states.append(LearningOpportunityTransitionFact.State.EXPOSED)
        if event.event_name == "group.document.opened":
            states.append(LearningOpportunityTransitionFact.State.STARTED)
    elif event.event_name == "video.progress":
        states.append(LearningOpportunityTransitionFact.State.EXPOSED)
        if float(event.payload.get("position_seconds") or 0) > 0:
            states.append(LearningOpportunityTransitionFact.State.STARTED)
    elif event.event_name == "document.progress":
        states.append(LearningOpportunityTransitionFact.State.EXPOSED)
        if float(event.payload.get("visible_seconds") or 0) > 0:
            states.append(LearningOpportunityTransitionFact.State.STARTED)
    elif event.event_name in {
        "learning_page.opened",
        "learning_page.block_viewed",
    }:
        states.extend(
            [
                LearningOpportunityTransitionFact.State.EXPOSED,
                LearningOpportunityTransitionFact.State.STARTED,
            ]
        )
    elif event.event_name in {
        "item.submitted",
        "task.submitted",
        "group.file.shared",
        "attendance.recorded",
        "quick_answer.responded",
        "learning_page.form_submitted",
        "evaluation.rating.submitted",
    }:
        states.append(LearningOpportunityTransitionFact.State.SUBMITTED)
    elif event.event_name == "item.graded" and event.payload.get("grading_state") in {
        "final",
        "revised",
    }:
        states.append(LearningOpportunityTransitionFact.State.GRADED)

    created = 0
    for state in states:
        _, was_created = _create_transition(
            opportunity=opportunity,
            state=state,
            source_event=event,
            occurred_at=event.client_occurred_at,
        )
        created += int(was_created)
    return {"opportunity_states_recorded": created}


@transaction.atomic
def withdraw_released_opportunities(withdrawal_event: LearningEventV2) -> dict:
    if withdrawal_event.event_name != "content.withdrawn":
        raise OpportunityError(
            "withdrawal_event_invalid", "撤回服务只接受 content.withdrawn 事件。"
        )
    release_event_id = withdrawal_event.payload["release_event_id"]
    release_event = LearningEventV2.objects.filter(
        school=withdrawal_event.school,
        event_id=release_event_id,
        event_name="content.released",
        class_group=withdrawal_event.class_group,
        subject=withdrawal_event.subject,
    ).first()
    if release_event is None:
        raise OpportunityError(
            "release_event_not_found", "原始投放事件不存在或上下文不一致。"
        )

    opportunities = LearningOpportunity.objects.select_for_update().filter(
        release_event=release_event
    )
    withdrawn = 0
    skipped_completed = 0
    for opportunity in opportunities:
        if opportunity.transition_facts.filter(
            state__in=[
                LearningOpportunityTransitionFact.State.SUBMITTED,
                LearningOpportunityTransitionFact.State.GRADED,
            ],
            occurred_at__lte=withdrawal_event.client_occurred_at,
        ).exists():
            skipped_completed += 1
            continue
        _, created = _create_transition(
            opportunity=opportunity,
            state=LearningOpportunityTransitionFact.State.WITHDRAWN,
            source_event=withdrawal_event,
            occurred_at=withdrawal_event.client_occurred_at,
            reason_code=withdrawal_event.payload["reason_code"],
        )
        withdrawn += int(created)
    return {
        "opportunities_withdrawn": withdrawn,
        "completed_opportunities_preserved": skipped_completed,
    }


@transaction.atomic
def mark_opportunity_terminal(
    *,
    opportunity: LearningOpportunity,
    state: str,
    source_event: LearningEventV2,
    reason_code: str,
) -> LearningOpportunityTransitionFact:
    if state not in {
        LearningOpportunityTransitionFact.State.WITHDRAWN,
        LearningOpportunityTransitionFact.State.EXCUSED,
        LearningOpportunityTransitionFact.State.UNAVAILABLE,
    }:
        raise OpportunityError(
            "terminal_state_invalid", "只允许记录撤回、豁免或不可用状态。"
        )
    fact, _ = _create_transition(
        opportunity=opportunity,
        state=state,
        source_event=source_event,
        occurred_at=source_event.client_occurred_at,
        reason_code=reason_code,
    )
    return fact
