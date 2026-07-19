from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from learning_analytics.models import EventIngestionDailyCounter

LATE_FLAGS = {"late_arrival_24h", "very_late_arrival_7d"}
SCHEMA_ERROR_CODES = {"schema_invalid", "schema_not_registered"}


@transaction.atomic
def record_ingestion_outcome(
    *,
    school,
    source: str,
    status: str,
    received_at=None,
    quality_errors: list[str] | None = None,
    error_code: str = "",
    event_name: str = "",
) -> None:
    if source == "migration":
        return
    if status not in {"accepted", "duplicate", "rejected"}:
        raise ValueError("Unknown learning-event ingestion outcome.")
    received_at = received_at or timezone.now()
    counter_date = timezone.localdate(received_at)
    counter, _ = EventIngestionDailyCounter.objects.select_for_update().get_or_create(
        school=school,
        counter_date=counter_date,
        source=source,
    )
    updates = {f"{status}_count": F(f"{status}_count") + 1}
    flags = set(quality_errors or [])
    if status == "accepted" and flags.intersection(LATE_FLAGS):
        updates["late_count"] = F("late_count") + 1
    if status == "accepted" and event_name == "client.offline":
        updates["offline_count"] = F("offline_count") + 1
    if status == "rejected":
        if error_code in SCHEMA_ERROR_CODES:
            updates["schema_error_count"] = F("schema_error_count") + 1
        else:
            updates["context_error_count"] = F("context_error_count") + 1
    EventIngestionDailyCounter.objects.filter(pk=counter.pk).update(**updates)
