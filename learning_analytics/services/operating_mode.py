from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from learning_analytics.models import AnalyticsOperatingMode

ALLOWED_MODE_TRANSITIONS = {
    AnalyticsOperatingMode.Mode.COLLECT_ONLY: {AnalyticsOperatingMode.Mode.SHADOW},
    AnalyticsOperatingMode.Mode.SHADOW: {
        AnalyticsOperatingMode.Mode.COLLECT_ONLY,
        AnalyticsOperatingMode.Mode.TEACHER_REVIEW,
        AnalyticsOperatingMode.Mode.SUSPENDED,
    },
    AnalyticsOperatingMode.Mode.TEACHER_REVIEW: {
        AnalyticsOperatingMode.Mode.SHADOW,
        AnalyticsOperatingMode.Mode.ACTIVE,
        AnalyticsOperatingMode.Mode.SUSPENDED,
    },
    AnalyticsOperatingMode.Mode.ACTIVE: {
        AnalyticsOperatingMode.Mode.TEACHER_REVIEW,
        AnalyticsOperatingMode.Mode.SUSPENDED,
    },
    AnalyticsOperatingMode.Mode.SUSPENDED: {
        AnalyticsOperatingMode.Mode.COLLECT_ONLY,
        AnalyticsOperatingMode.Mode.SHADOW,
    },
}


@transaction.atomic
def transition_operating_mode(
    *, school, target_mode: str, actor=None, reason: str = ""
) -> AnalyticsOperatingMode:
    valid_modes = {choice.value for choice in AnalyticsOperatingMode.Mode}
    if target_mode not in valid_modes:
        raise ValidationError({"mode": "分析运行状态不正确。"})

    state, _ = AnalyticsOperatingMode.objects.select_for_update().get_or_create(
        school=school
    )
    if state.mode == target_mode:
        return state
    if target_mode not in ALLOWED_MODE_TRANSITIONS[state.mode]:
        raise ValidationError(
            {"mode": f"不能从 {state.mode} 直接切换到 {target_mode}。"}
        )
    if target_mode == AnalyticsOperatingMode.Mode.SUSPENDED and not reason.strip():
        raise ValidationError({"reason": "暂停分析运行时必须填写原因。"})

    state.mode = target_mode
    state.reason = reason.strip()[:500]
    state.updated_by = actor
    state.save(update_fields=["mode", "reason", "updated_by", "updated_at"])
    return state
