from __future__ import annotations

from rest_framework import serializers

from courses.models import Course
from learning_analytics.measurement_models import (
    AssessmentBlueprint,
    MeasurementUse,
    MeasurementValidationStatus,
    RubricDefinition,
)


class StrictModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("必须提交 JSON 对象。")
        unknown = sorted(set(data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {"unknown_fields": [f"未登记字段：{field}" for field in unknown]}
            )
        return super().to_internal_value(data)


def _clean_string_list(value, *, field_name: str, max_items: int = 30) -> list[str]:
    if not isinstance(value, list):
        raise serializers.ValidationError("必须是列表。")
    if len(value) > max_items:
        raise serializers.ValidationError(f"{field_name}最多包含 {max_items} 项。")
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            raise serializers.ValidationError(f"{field_name}中的每一项必须是文本。")
        text = item.strip()
        if text:
            cleaned.append(text)
    return cleaned


def _clean_object_list(value, *, field_name: str, max_items: int = 30) -> list[dict]:
    if not isinstance(value, list):
        raise serializers.ValidationError("必须是列表。")
    if len(value) > max_items:
        raise serializers.ValidationError(f"{field_name}最多包含 {max_items} 项。")
    if any(not isinstance(item, dict) for item in value):
        raise serializers.ValidationError(f"{field_name}中的每一项必须是对象。")
    return value


class AssessmentBlueprintWriteSerializer(StrictModelSerializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())

    class Meta:
        model = AssessmentBlueprint
        fields = (
            "course",
            "title",
            "task_version",
            "target_population",
            "course_goal",
            "claims",
            "evidence_rules",
            "task_specifications",
            "content_coverage",
            "cognitive_complexity",
            "allowed_supports",
            "scoring_model",
            "next_formative_action",
        )
        extra_kwargs = {
            "title": {"required": True, "allow_blank": False},
            "claims": {"required": False},
            "evidence_rules": {"required": False},
            "task_specifications": {"required": False},
            "content_coverage": {"required": False},
            "cognitive_complexity": {"required": False},
            "allowed_supports": {"required": False},
            "scoring_model": {"required": False},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["course"].queryset = Course.objects.filter(
                teacher=request.user,
                subject__school=request.user.school,
            ).select_related("subject")

    def validate(self, attrs):
        instance = self.instance
        course = attrs.get("course", instance.course if instance else None)
        if instance and instance.versions.exists() and course.id != instance.course_id:
            raise serializers.ValidationError(
                {"course": "蓝图发布过版本后不能更换课程；请新建蓝图。"}
            )
        return attrs

    def validate_claims(self, value):
        return _clean_object_list(value, field_name="学习主张")

    def validate_evidence_rules(self, value):
        return _clean_object_list(value, field_name="证据规则")

    def validate_task_specifications(self, value):
        return _clean_object_list(value, field_name="任务规格")

    def validate_content_coverage(self, value):
        return _clean_string_list(value, field_name="内容覆盖")

    def validate_cognitive_complexity(self, value):
        return _clean_string_list(value, field_name="认知复杂度", max_items=6)

    def validate_allowed_supports(self, value):
        return _clean_string_list(value, field_name="允许支持")

    def validate_scoring_model(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("评分模型必须是对象。")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        course = validated_data["course"]
        return AssessmentBlueprint.objects.create(
            school=request.user.school,
            subject=course.subject,
            intended_use=MeasurementUse.LOCAL_FORMATIVE,
            validation_status=MeasurementValidationStatus.UNVALIDATED,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )

    def update(self, instance, validated_data):
        request = self.context["request"]
        course = validated_data.get("course", instance.course)
        instance.subject = course.subject
        instance.updated_by = request.user
        instance.intended_use = MeasurementUse.LOCAL_FORMATIVE
        instance.validation_status = MeasurementValidationStatus.UNVALIDATED
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        instance.save()
        return instance


class RubricDefinitionWriteSerializer(StrictModelSerializer):
    blueprint = serializers.PrimaryKeyRelatedField(
        queryset=AssessmentBlueprint.objects.none()
    )

    class Meta:
        model = RubricDefinition
        fields = (
            "blueprint",
            "title",
            "evaluation_object",
            "criteria",
        )
        extra_kwargs = {
            "title": {"required": True, "allow_blank": False},
            "criteria": {"required": False},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["blueprint"].queryset = AssessmentBlueprint.objects.filter(
                school=request.user.school,
                created_by=request.user,
                intended_use=MeasurementUse.LOCAL_FORMATIVE,
            ).select_related("subject", "course")

    def validate(self, attrs):
        instance = self.instance
        blueprint = attrs.get("blueprint", instance.blueprint if instance else None)
        if instance and instance.versions.exists() and blueprint.id != instance.blueprint_id:
            raise serializers.ValidationError(
                {"blueprint": "量规发布过版本后不能更换任务蓝图；请新建量规。"}
            )
        return attrs

    def validate_criteria(self, value):
        return _clean_object_list(value, field_name="量规条目", max_items=12)

    def create(self, validated_data):
        request = self.context["request"]
        blueprint = validated_data["blueprint"]
        return RubricDefinition.objects.create(
            school=request.user.school,
            subject=blueprint.subject,
            course=blueprint.course,
            intended_use=MeasurementUse.LOCAL_FORMATIVE,
            validation_status=MeasurementValidationStatus.UNVALIDATED,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )

    def update(self, instance, validated_data):
        request = self.context["request"]
        blueprint = validated_data.get("blueprint", instance.blueprint)
        instance.subject = blueprint.subject
        instance.course = blueprint.course
        instance.updated_by = request.user
        instance.intended_use = MeasurementUse.LOCAL_FORMATIVE
        instance.validation_status = MeasurementValidationStatus.UNVALIDATED
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        instance.save()
        return instance
