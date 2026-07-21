from django.db.models import Q

from learning.models import StratificationDecision


def visible_published_decisions(queryset=None):
    """Hide unpublished model candidates while retaining transparent suggestions."""
    decisions = queryset if queryset is not None else StratificationDecision.objects.all()
    return (
        decisions.filter(
            ~Q(rule_version__startswith="m03-")
            | Q(calibration_run__releases__status="active")
        )
        .exclude(decision_kind=StratificationDecision.DecisionKind.LEGACY)
        .distinct()
    )


def visible_teacher_decisions(*, teacher, class_ids):
    """Return decisions a teacher may act on in the stratification workspace."""
    return visible_published_decisions(
        StratificationDecision.objects.filter(
            class_group_id__in=class_ids,
            course__teacher=teacher,
        )
    )
