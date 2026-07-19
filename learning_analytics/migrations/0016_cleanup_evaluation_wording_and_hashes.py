import hashlib
import json

from django.db import migrations


def _clean_text(value):
    return (
        str(value or "")
        .replace("数据表达与解释试点任务蓝图", "数据表达与解释试点评价方案")
        .replace("数据表达与解释形成性量规", "数据表达与解释评价标准")
        .replace("任务蓝图", "评价方案")
        .replace("形成性量规", "评价标准")
        .replace("五星量规", "五星评价标准")
        .replace("量规", "评价标准")
        .replace("时记录 NOT_ASSESSED", "时暂不评价该项")
        .replace("记录 NOT_ASSESSED", "暂不评价该项")
        .replace("NOT_ASSESSED", "暂不评价")
        .replace("下一步形成性行动", "后续教学建议")
        .replace("认知复杂度", "思维要求")
    )


def _clean_value(value):
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean_value(item) for key, item in value.items()}
    return value


def _content_hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cleanup_evaluation_data(apps, schema_editor):
    EvaluationPlan = apps.get_model("learning_analytics", "EvaluationPlan")
    EvaluationPlanVersion = apps.get_model(
        "learning_analytics", "EvaluationPlanVersion"
    )
    EvaluationStandard = apps.get_model(
        "learning_analytics", "EvaluationStandard"
    )
    EvaluationStandardVersion = apps.get_model(
        "learning_analytics", "EvaluationStandardVersion"
    )
    EvaluationCriterionVersion = apps.get_model(
        "learning_analytics", "EvaluationCriterionVersion"
    )

    for plan in EvaluationPlan.objects.all().iterator():
        EvaluationPlan.objects.filter(pk=plan.pk).update(
            title=_clean_text(plan.title),
            learning_goal=_clean_text(plan.learning_goal),
            learning_goals=_clean_value(plan.learning_goals),
            evaluation_basis=_clean_value(plan.evaluation_basis),
            learning_tasks=_clean_value(plan.learning_tasks),
            content_scope=_clean_value(plan.content_scope),
            support_options=_clean_value(plan.support_options),
            scoring_rules=_clean_value(plan.scoring_rules),
            follow_up_suggestion=_clean_text(plan.follow_up_suggestion),
        )

    for version in EvaluationPlanVersion.objects.all().iterator():
        updates = {
            "title": _clean_text(version.title),
            "learning_goal": _clean_text(version.learning_goal),
            "learning_goals": _clean_value(version.learning_goals),
            "evaluation_basis": _clean_value(version.evaluation_basis),
            "learning_tasks": _clean_value(version.learning_tasks),
            "content_scope": _clean_value(version.content_scope),
            "support_options": _clean_value(version.support_options),
            "scoring_rules": _clean_value(version.scoring_rules),
            "follow_up_suggestion": _clean_text(version.follow_up_suggestion),
        }
        payload = {
            "school_id": version.school_id,
            "subject_id": version.subject_id,
            "course_id": version.course_id,
            "title": updates["title"],
            "scope": version.scope,
            "content_version": version.content_version,
            "target_students": version.target_students,
            "learning_goal": updates["learning_goal"],
            "learning_goals": updates["learning_goals"],
            "evaluation_basis": updates["evaluation_basis"],
            "learning_tasks": updates["learning_tasks"],
            "content_scope": updates["content_scope"],
            "thinking_requirements": version.thinking_requirements,
            "support_options": updates["support_options"],
            "scoring_rules": updates["scoring_rules"],
            "follow_up_suggestion": updates["follow_up_suggestion"],
            "review_status": version.review_status,
        }
        updates["content_hash"] = _content_hash(payload)
        EvaluationPlanVersion.objects.filter(pk=version.pk).update(**updates)

    for standard in EvaluationStandard.objects.all().iterator():
        EvaluationStandard.objects.filter(pk=standard.pk).update(
            title=_clean_text(standard.title),
            evaluation_target=_clean_text(standard.evaluation_target),
            criteria=_clean_value(standard.criteria),
        )

    for criterion in EvaluationCriterionVersion.objects.all().iterator():
        EvaluationCriterionVersion.objects.filter(pk=criterion.pk).update(
            title=_clean_text(criterion.title),
            evaluation_target=_clean_text(criterion.evaluation_target),
            evaluation_sources=_clean_value(criterion.evaluation_sources),
            expected_performance=_clean_text(criterion.expected_performance),
            skip_condition=_clean_text(criterion.skip_condition),
            support_options=_clean_value(criterion.support_options),
            common_problems=_clean_value(criterion.common_problems),
            level_1_description=_clean_text(criterion.level_1_description),
            level_2_description=_clean_text(criterion.level_2_description),
            level_3_description=_clean_text(criterion.level_3_description),
            level_4_description=_clean_text(criterion.level_4_description),
            level_5_description=_clean_text(criterion.level_5_description),
            follow_up_suggestion=_clean_text(criterion.follow_up_suggestion),
        )

    for version in EvaluationStandardVersion.objects.all().iterator():
        plan_version = version.plan_version
        criteria_payload = []
        criteria = EvaluationCriterionVersion.objects.filter(
            standard_version_id=version.pk
        ).order_by("sort_order", "id")
        for criterion in criteria:
            examples = []
            for example in criterion.scoring_examples.order_by("sort_order", "id"):
                examples.append(
                    {
                        "level": example.level,
                        "title": _clean_text(example.title),
                        "example_description": _clean_text(
                            example.example_description
                        ),
                        "file_reference": example.file_reference,
                    }
                )
            criteria_payload.append(
                {
                    "code": criterion.code,
                    "dimension": criterion.dimension,
                    "title": criterion.title,
                    "evaluation_target": criterion.evaluation_target,
                    "evaluation_sources": criterion.evaluation_sources,
                    "expected_performance": criterion.expected_performance,
                    "skip_condition": criterion.skip_condition,
                    "support_options": criterion.support_options,
                    "common_problems": criterion.common_problems,
                    "level_descriptions": {
                        "1": criterion.level_1_description,
                        "2": criterion.level_2_description,
                        "3": criterion.level_3_description,
                        "4": criterion.level_4_description,
                        "5": criterion.level_5_description,
                    },
                    "scoring_examples": examples,
                    "follow_up_suggestion": criterion.follow_up_suggestion,
                    "sort_order": criterion.sort_order,
                }
            )
        title = _clean_text(version.title)
        evaluation_target = _clean_text(version.evaluation_target)
        payload = {
            "school_id": version.school_id,
            "subject_id": version.subject_id,
            "course_id": version.course_id,
            "plan_version_hash": plan_version.content_hash,
            "title": title,
            "scope": version.scope,
            "evaluation_target": evaluation_target,
            "review_status": version.review_status,
            "criteria": criteria_payload,
        }
        EvaluationStandardVersion.objects.filter(pk=version.pk).update(
            title=title,
            evaluation_target=evaluation_target,
            content_hash=_content_hash(payload),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("learning_analytics", "0015_rename_rubric_event_fields"),
    ]

    operations = [
        migrations.RunPython(cleanup_evaluation_data, migrations.RunPython.noop),
    ]
