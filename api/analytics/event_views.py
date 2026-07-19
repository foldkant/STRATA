from __future__ import annotations

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes

from api.responses import fail, ok
from learning_analytics.services.event_ingestion import (
    EventIngestionError,
    event_source_for_actor,
    ingest_learning_event,
    record_rejected_learning_event,
)

from .permissions import IsLearningEventClient
from .serializers import LearningEventBatchSerializer, LearningEventEnvelopeSerializer


def _flatten_errors(detail, prefix: str = "") -> list[dict]:
    if isinstance(detail, dict):
        result = []
        for key, value in detail.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            result.extend(_flatten_errors(value, field))
        return result
    if isinstance(detail, list):
        result = []
        for item in detail:
            result.extend(_flatten_errors(item, prefix))
        return result
    return [{"field": prefix or "event", "message": str(detail)}]


def _rejected_result(
    *,
    index: int,
    raw_event: dict,
    rejection,
    code: str,
    message: str,
    errors: list[dict],
):
    return {
        "index": index,
        "event_id": str(raw_event.get("event_id") or "")[:64],
        "status": "rejected",
        "error_code": code,
        "message": message,
        "errors": errors,
        "rejection_id": str(rejection.rejection_id),
    }


@api_view(["POST"])
@permission_classes([IsLearningEventClient])
def learning_event_batch(request):
    batch_serializer = LearningEventBatchSerializer(data=request.data)
    if not batch_serializer.is_valid():
        return fail(
            "事件批次格式不正确。",
            errors=batch_serializer.errors,
            status=400,
        )

    source = event_source_for_actor(request.user)
    received_at = timezone.now()
    results = []
    for index, raw_event in enumerate(batch_serializer.validated_data["events"]):
        serializer = LearningEventEnvelopeSerializer(
            data=raw_event,
            context={"expected_source": source},
        )
        if not serializer.is_valid():
            errors = _flatten_errors(serializer.errors)
            rejection = record_rejected_learning_event(
                actor=request.user,
                raw_envelope=raw_event,
                source=source,
                error_code="schema_invalid",
                errors=errors,
                received_at=received_at,
            )
            results.append(
                _rejected_result(
                    index=index,
                    raw_event=raw_event,
                    rejection=rejection,
                    code="schema_invalid",
                    message="事件信封或载荷不符合登记模式。",
                    errors=errors,
                )
            )
            continue

        try:
            result = ingest_learning_event(
                actor=request.user,
                event_data=serializer.validated_data,
                received_at=received_at,
            )
        except EventIngestionError as exc:
            errors = exc.errors or [{"field": "event", "message": exc.message}]
            rejection = record_rejected_learning_event(
                actor=request.user,
                raw_envelope=raw_event,
                source=source,
                error_code=exc.code,
                errors=errors,
                received_at=received_at,
            )
            results.append(
                _rejected_result(
                    index=index,
                    raw_event=raw_event,
                    rejection=rejection,
                    code=exc.code,
                    message=exc.message,
                    errors=errors,
                )
            )
            continue

        result["index"] = index
        results.append(result)

    counts = {
        status: sum(1 for item in results if item["status"] == status)
        for status in ("accepted", "duplicate", "rejected")
    }
    return ok(
        {
            "batch_id": str(batch_serializer.validated_data.get("batch_id") or ""),
            "server_received_at": received_at,
            "counts": counts,
            "results": results,
        },
        message="事件批次已处理。",
    )
