from __future__ import annotations

from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from courses.models import Course
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationScope,
    EvaluationReviewStatus,
    EvaluationStandard,
    EvaluationStandardVersion,
    EvaluationTrialConclusion,
    EvaluationTrialRecord,
    EvaluationTrialStatus,
    EvaluationTrialType,
)
from curriculum_standards.models import CurriculumStandardNode
from curriculum_standards.services import (
    replace_plan_curriculum_references,
    subject_names_equivalent,
    validate_curriculum_nodes,
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


class EvaluationPlanWriteSerializer(StrictModelSerializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    curriculum_node_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        write_only=True,
        max_length=100,
    )

    class Meta:
        model = EvaluationPlan
        fields = (
            "course",
            "title",
            "content_version",
            "target_students",
            "learning_goal",
            "learning_goals",
            "evaluation_basis",
            "learning_tasks",
            "content_scope",
            "thinking_requirements",
            "support_options",
            "scoring_rules",
            "follow_up_suggestion",
            "curriculum_node_ids",
        )
        extra_kwargs = {
            "title": {"required": True, "allow_blank": False},
            "learning_goals": {"required": False},
            "evaluation_basis": {"required": False},
            "learning_tasks": {"required": False},
            "content_scope": {"required": False},
            "thinking_requirements": {"required": False},
            "support_options": {"required": False},
            "scoring_rules": {"required": False},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["course"].queryset = Course.objects.filter(
                subject__school=request.user.school,
                teacher=request.user,
            ).select_related("subject")

    def validate(self, attrs):
        instance = self.instance
        course = attrs.get("course", instance.course if instance else None)
        if instance and instance.versions.exists() and course.id != instance.course_id:
            raise serializers.ValidationError(
                {"course": "评价方案发布过版本后不能更换课程，请新建方案。"}
            )
        has_node_ids = "curriculum_node_ids" in attrs
        node_ids = attrs.get("curriculum_node_ids")
        node = None
        if node_ids:
            node = CurriculumStandardNode.objects.select_related("version").filter(
                pk=node_ids[0]
            ).first()
        elif not has_node_ids and instance and instance.curriculum_references.exists():
            node = (
                CurriculumStandardNode.objects.select_related("version")
                .filter(draft_evaluation_plan_references__plan=instance)
                .first()
            )
        if node and not subject_names_equivalent(
                course.subject.name,
                node.version.subject_name_snapshot,
        ):
            raise serializers.ValidationError(
                {
                    "curriculum_node_ids": (
                        f"课程学科“{course.subject.name}”与所选课程标准学科"
                        f"“{node.version.subject_name_snapshot}”不一致。"
                    )
                }
            )
        return attrs

    def validate_learning_goals(self, value):
        return _clean_object_list(value, field_name="学习目标")

    def validate_evaluation_basis(self, value):
        return _clean_object_list(value, field_name="评价依据")

    def validate_learning_tasks(self, value):
        return _clean_object_list(value, field_name="学习任务")

    def validate_content_scope(self, value):
        return _clean_string_list(value, field_name="评价内容")

    def validate_thinking_requirements(self, value):
        return _clean_string_list(value, field_name="思维要求", max_items=6)

    def validate_support_options(self, value):
        return _clean_string_list(value, field_name="可用帮助")

    def validate_scoring_rules(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("评分规则必须是对象。")
        return value

    def validate_curriculum_node_ids(self, value):
        normalized = list(dict.fromkeys(value))
        nodes = list(
            CurriculumStandardNode.objects.select_related("version__source").filter(
                pk__in=normalized
            )
        )
        if len(nodes) != len(normalized):
            raise serializers.ValidationError("部分课程标准内容条目不存在。")
        try:
            validate_curriculum_nodes(nodes, require_complete=False)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return normalized

    def create(self, validated_data):
        request = self.context["request"]
        curriculum_node_ids = validated_data.pop("curriculum_node_ids", [])
        course = validated_data["course"]
        with transaction.atomic():
            plan = EvaluationPlan.objects.create(
                school=request.user.school,
                subject=course.subject,
                scope=EvaluationScope.COURSE,
                review_status=EvaluationReviewStatus.DRAFT,
                created_by=request.user,
                updated_by=request.user,
                **validated_data,
            )
            if curriculum_node_ids:
                replace_plan_curriculum_references(
                    plan=plan,
                    node_ids=curriculum_node_ids,
                    actor=request.user,
                )
        return plan

    def update(self, instance, validated_data):
        request = self.context["request"]
        curriculum_node_ids = validated_data.pop("curriculum_node_ids", None)
        course = validated_data.get("course", instance.course)
        instance.subject = course.subject
        instance.updated_by = request.user
        instance.scope = EvaluationScope.COURSE
        instance.review_status = EvaluationReviewStatus.DRAFT
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        with transaction.atomic():
            instance.save()
            if curriculum_node_ids is not None:
                replace_plan_curriculum_references(
                    plan=instance,
                    node_ids=curriculum_node_ids,
                    actor=request.user,
                )
        return instance


class EvaluationStandardWriteSerializer(StrictModelSerializer):
    plan = serializers.PrimaryKeyRelatedField(
        queryset=EvaluationPlan.objects.none()
    )

    class Meta:
        model = EvaluationStandard
        fields = (
            "plan",
            "title",
            "evaluation_target",
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
            self.fields["plan"].queryset = EvaluationPlan.objects.filter(
                school=request.user.school,
                scope=EvaluationScope.COURSE,
                course__teacher=request.user,
            ).select_related("subject", "course")

    def validate(self, attrs):
        instance = self.instance
        plan = attrs.get("plan", instance.plan if instance else None)
        if instance and instance.versions.exists() and plan.id != instance.plan_id:
            raise serializers.ValidationError(
                {"plan": "评价标准发布过版本后不能更换评价方案，请新建标准。"}
            )
        return attrs

    def validate_criteria(self, value):
        return _clean_object_list(value, field_name="评价指标", max_items=12)

    def create(self, validated_data):
        request = self.context["request"]
        plan = validated_data["plan"]
        return EvaluationStandard.objects.create(
            school=request.user.school,
            subject=plan.subject,
            course=plan.course,
            scope=EvaluationScope.COURSE,
            review_status=EvaluationReviewStatus.DRAFT,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )

    def update(self, instance, validated_data):
        request = self.context["request"]
        plan = validated_data.get("plan", instance.plan)
        instance.subject = plan.subject
        instance.course = plan.course
        instance.updated_by = request.user
        instance.scope = EvaluationScope.COURSE
        instance.review_status = EvaluationReviewStatus.DRAFT
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        instance.save()
        return instance


class EvaluationTrialRecordWriteSerializer(StrictModelSerializer):
    standard_version = serializers.PrimaryKeyRelatedField(
        queryset=EvaluationStandardVersion.objects.none()
    )

    class Meta:
        model = EvaluationTrialRecord
        fields = (
            "standard_version",
            "record_type",
            "title",
            "status",
            "activity_date",
            "participant_count",
            "agreement_rate",
            "conclusion",
            "summary",
            "issues",
            "action_items",
        )
        extra_kwargs = {
            "title": {"required": True, "allow_blank": False},
            "issues": {"required": False},
            "action_items": {"required": False},
            "summary": {"required": False},
            "participant_count": {"required": False},
            "agreement_rate": {"required": False, "allow_null": True},
            "conclusion": {"required": False},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["standard_version"].queryset = (
                EvaluationStandardVersion.objects.filter(
                    school=request.user.school,
                    course__teacher=request.user,
                ).select_related("source", "subject", "course")
            )

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("请填写记录名称。")
        return value

    def validate_issues(self, value):
        return _clean_string_list(value, field_name="发现的问题", max_items=20)

    def validate_action_items(self, value):
        return _clean_string_list(value, field_name="后续处理", max_items=20)

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.status == EvaluationTrialStatus.COMPLETED:
            raise serializers.ValidationError("已完成记录不能修改，请新增一条补充记录。")

        status = attrs.get(
            "status",
            instance.status if instance else EvaluationTrialStatus.PLANNED,
        )
        record_type = attrs.get(
            "record_type",
            instance.record_type if instance else None,
        )
        agreement_rate = attrs.get(
            "agreement_rate",
            instance.agreement_rate if instance else None,
        )
        conclusion = attrs.get(
            "conclusion",
            instance.conclusion if instance else EvaluationTrialConclusion.PENDING,
        )
        participant_count = attrs.get(
            "participant_count",
            instance.participant_count if instance else 0,
        )
        summary = attrs.get("summary", instance.summary if instance else "").strip()
        activity_date = attrs.get(
            "activity_date",
            instance.activity_date if instance else None,
        )

        errors = {}
        if record_type == EvaluationTrialType.SCORING_CHECK:
            if status == EvaluationTrialStatus.COMPLETED and agreement_rate is None:
                errors["agreement_rate"] = ["完成评分一致性检查时必须填写一致率。"]
        elif agreement_rate is not None:
            errors["agreement_rate"] = ["只有评分一致性检查可以填写一致率。"]

        if status == EvaluationTrialStatus.COMPLETED:
            if participant_count < 1:
                errors["participant_count"] = ["完成记录至少需要 1 名参与者。"]
            if not summary:
                errors["summary"] = ["完成记录必须填写结果说明。"]
            if conclusion == EvaluationTrialConclusion.PENDING:
                errors["conclusion"] = ["完成记录必须选择处理结论。"]
            if activity_date is None:
                errors["activity_date"] = ["请选择完成日期。"]
        elif conclusion != EvaluationTrialConclusion.PENDING:
            errors["conclusion"] = ["未完成记录的处理结论应为待确认。"]

        if errors:
            raise serializers.ValidationError(errors)
        attrs["summary"] = summary
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return EvaluationTrialRecord.objects.create(
            school=request.user.school,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )

    def update(self, instance, validated_data):
        instance.updated_by = self.context["request"].user
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        instance.save()
        return instance
