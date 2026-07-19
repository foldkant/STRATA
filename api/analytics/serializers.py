from __future__ import annotations

from rest_framework import serializers

from learning_analytics.schemas.registry import (
    EventPayloadValidationError,
    validate_event_payload,
)


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("必须是 JSON 对象。")
        unknown = sorted(set(data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {"unknown_fields": [f"未登记字段：{field}" for field in unknown]}
            )
        return super().to_internal_value(data)


class LearningEventEnvelopeSerializer(StrictSerializer):
    event_id = serializers.UUIDField()
    event_name = serializers.CharField(max_length=128)
    schema_version = serializers.RegexField(r"^\d+\.\d+$", max_length=16)
    source = serializers.ChoiceField(
        choices=("student-web", "teacher-web"), required=False
    )
    client_version = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    target_student_id = serializers.IntegerField(
        min_value=1, required=False, allow_null=True
    )
    class_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    subject_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    course_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    lesson_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    session_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    step_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    object_type = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    object_id = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    object_version = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    opportunity_id = serializers.UUIDField(required=False, allow_null=True)
    attempt_id = serializers.UUIDField(required=False, allow_null=True)
    client_session_id = serializers.UUIDField(required=False, allow_null=True)
    client_sequence = serializers.IntegerField(
        min_value=0, required=False, allow_null=True
    )
    client_occurred_at = serializers.DateTimeField()
    duration_ms = serializers.IntegerField(
        min_value=0, max_value=86_400_000, required=False, allow_null=True
    )
    payload = serializers.DictField()

    def validate(self, attrs):
        source = attrs.get("source")
        expected_source = self.context.get("expected_source")
        if source and expected_source and source != expected_source:
            raise serializers.ValidationError(
                {"source": "事件来源与当前登录角色不一致。"}
            )
        has_session = attrs.get("client_session_id") is not None
        has_sequence = attrs.get("client_sequence") is not None
        if has_session != has_sequence:
            raise serializers.ValidationError(
                {
                    "client_sequence": "client_session_id 与 client_sequence 必须同时提供。"
                }
            )
        try:
            attrs["payload"] = validate_event_payload(
                attrs["event_name"],
                attrs["schema_version"],
                attrs["payload"],
            )
        except EventPayloadValidationError as exc:
            raise serializers.ValidationError({"payload": str(exc)}) from exc
        return attrs


class LearningEventBatchSerializer(StrictSerializer):
    batch_id = serializers.UUIDField(required=False)
    sent_at = serializers.DateTimeField(required=False)
    events = serializers.ListField(
        child=serializers.JSONField(),
        min_length=1,
        max_length=200,
    )

    def validate_events(self, value):
        if any(not isinstance(item, dict) for item in value):
            raise serializers.ValidationError("每个事件都必须是 JSON 对象。")
        return value
