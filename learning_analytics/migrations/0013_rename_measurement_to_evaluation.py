from django.db import migrations, models


SCOPE_MAP = {
    "local_formative": "course",
    "school_common": "school",
    "research_linked": "analysis",
}

REVIEW_STATUS_MAP = {
    "unvalidated": "draft",
    "content_review_pending": "review_pending",
    "content_reviewed": "reviewed",
    "pilot_scheduled": "trial_scheduled",
    "pilot_completed": "trial_completed",
    "validated": "approved",
}

DIMENSION_MAP = {
    "P": "task_quality",
    "S": "learning_method",
    "R": "self_management",
    "C": "collaboration",
    "D": "subject_practice",
    "E": "responsibility",
}


def _move_keys(row, mapping):
    if not isinstance(row, dict):
        return row
    result = dict(row)
    for old_key, new_key in mapping.items():
        if old_key in result and new_key not in result:
            result[new_key] = result.pop(old_key)
    return result


def rename_evaluation_data(apps, schema_editor):
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
        plan.scope = SCOPE_MAP.get(plan.scope, plan.scope)
        plan.review_status = REVIEW_STATUS_MAP.get(
            plan.review_status, plan.review_status
        )
        plan.evaluation_basis = [
            _move_keys(row, {"claim_codes": "goal_codes"})
            for row in (plan.evaluation_basis or [])
        ]
        plan.learning_tasks = [
            _move_keys(row, {"evidence_codes": "basis_codes"})
            for row in (plan.learning_tasks or [])
        ]
        plan.save(
            update_fields=[
                "scope",
                "review_status",
                "evaluation_basis",
                "learning_tasks",
            ]
        )

    for version in EvaluationPlanVersion.objects.all().iterator():
        version.scope = SCOPE_MAP.get(version.scope, version.scope)
        version.review_status = REVIEW_STATUS_MAP.get(
            version.review_status, version.review_status
        )
        version.evaluation_basis = [
            _move_keys(row, {"claim_codes": "goal_codes"})
            for row in (version.evaluation_basis or [])
        ]
        version.learning_tasks = [
            _move_keys(row, {"evidence_codes": "basis_codes"})
            for row in (version.learning_tasks or [])
        ]
        EvaluationPlanVersion.objects.filter(pk=version.pk).update(
            scope=version.scope,
            review_status=version.review_status,
            evaluation_basis=version.evaluation_basis,
            learning_tasks=version.learning_tasks,
        )

    criterion_key_map = {
        "module": "dimension",
        "evaluation_object": "evaluation_target",
        "evidence_sources": "evaluation_sources",
        "observable_evidence": "expected_performance",
        "not_assessed_condition": "skip_condition",
        "allowed_supports": "support_options",
        "counter_examples": "common_problems",
        "anchors": "level_descriptions",
        "anchor_examples": "scoring_examples",
        "next_formative_action": "follow_up_suggestion",
    }
    example_key_map = {
        "evidence_summary": "example_description",
        "artifact_reference": "file_reference",
    }
    for standard in EvaluationStandard.objects.all().iterator():
        standard.scope = SCOPE_MAP.get(standard.scope, standard.scope)
        standard.review_status = REVIEW_STATUS_MAP.get(
            standard.review_status, standard.review_status
        )
        criteria = []
        for row in standard.criteria or []:
            item = _move_keys(row, criterion_key_map)
            if isinstance(item, dict):
                item["dimension"] = DIMENSION_MAP.get(
                    item.get("dimension"), item.get("dimension")
                )
                item["scoring_examples"] = [
                    _move_keys(example, example_key_map)
                    for example in item.get("scoring_examples", [])
                ]
            criteria.append(item)
        standard.criteria = criteria
        standard.save(update_fields=["scope", "review_status", "criteria"])

    for version in EvaluationStandardVersion.objects.all().iterator():
        EvaluationStandardVersion.objects.filter(pk=version.pk).update(
            scope=SCOPE_MAP.get(version.scope, version.scope),
            review_status=REVIEW_STATUS_MAP.get(
                version.review_status, version.review_status
            ),
        )

    for criterion in EvaluationCriterionVersion.objects.all().iterator():
        EvaluationCriterionVersion.objects.filter(pk=criterion.pk).update(
            dimension=DIMENSION_MAP.get(criterion.dimension, criterion.dimension)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("learning_analytics", "0012_rubriccriterionversion_assessmentblueprint_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="AssessmentBlueprint",
            new_name="EvaluationPlan",
        ),
        migrations.RenameModel(
            old_name="AssessmentBlueprintVersion",
            new_name="EvaluationPlanVersion",
        ),
        migrations.RenameModel(
            old_name="RubricDefinition",
            new_name="EvaluationStandard",
        ),
        migrations.RenameModel(
            old_name="RubricDefinitionVersion",
            new_name="EvaluationStandardVersion",
        ),
        migrations.RenameModel(
            old_name="RubricCriterionVersion",
            new_name="EvaluationCriterionVersion",
        ),
        migrations.RenameModel(
            old_name="RubricAnchorExample",
            new_name="EvaluationScoringExample",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationplanversion",
            name="uniq_blueprint_version_no",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationplanversion",
            name="uniq_blueprint_content_hash",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationstandardversion",
            name="uniq_rubric_version_no",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationstandardversion",
            name="uniq_rubric_content_hash",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationcriterionversion",
            name="uniq_rubric_criterion_code",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationcriterionversion",
            name="uniq_rubric_criterion_order",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationscoringexample",
            name="rubric_anchor_example_level_1_5",
        ),
        migrations.RemoveConstraint(
            model_name="evaluationscoringexample",
            name="uniq_rubric_anchor_example_order",
        ),
        migrations.RemoveIndex(
            model_name="evaluationplanversion",
            name="learning_an_intende_46c7ed_idx",
        ),
        migrations.RemoveIndex(
            model_name="evaluationstandardversion",
            name="learning_an_intende_9bbd87_idx",
        ),
        migrations.RenameField("evaluationplan", "intended_use", "scope"),
        migrations.RenameField("evaluationplan", "task_version", "content_version"),
        migrations.RenameField("evaluationplan", "target_population", "target_students"),
        migrations.RenameField("evaluationplan", "course_goal", "learning_goal"),
        migrations.RenameField("evaluationplan", "claims", "learning_goals"),
        migrations.RenameField("evaluationplan", "evidence_rules", "evaluation_basis"),
        migrations.RenameField("evaluationplan", "task_specifications", "learning_tasks"),
        migrations.RenameField("evaluationplan", "content_coverage", "content_scope"),
        migrations.RenameField("evaluationplan", "cognitive_complexity", "thinking_requirements"),
        migrations.RenameField("evaluationplan", "allowed_supports", "support_options"),
        migrations.RenameField("evaluationplan", "scoring_model", "scoring_rules"),
        migrations.RenameField("evaluationplan", "next_formative_action", "follow_up_suggestion"),
        migrations.RenameField("evaluationplan", "validation_status", "review_status"),
        migrations.RenameField("evaluationplanversion", "intended_use", "scope"),
        migrations.RenameField("evaluationplanversion", "task_version", "content_version"),
        migrations.RenameField("evaluationplanversion", "target_population", "target_students"),
        migrations.RenameField("evaluationplanversion", "course_goal", "learning_goal"),
        migrations.RenameField("evaluationplanversion", "claims", "learning_goals"),
        migrations.RenameField("evaluationplanversion", "evidence_rules", "evaluation_basis"),
        migrations.RenameField("evaluationplanversion", "task_specifications", "learning_tasks"),
        migrations.RenameField("evaluationplanversion", "content_coverage", "content_scope"),
        migrations.RenameField("evaluationplanversion", "cognitive_complexity", "thinking_requirements"),
        migrations.RenameField("evaluationplanversion", "allowed_supports", "support_options"),
        migrations.RenameField("evaluationplanversion", "scoring_model", "scoring_rules"),
        migrations.RenameField("evaluationplanversion", "next_formative_action", "follow_up_suggestion"),
        migrations.RenameField("evaluationplanversion", "validation_status", "review_status"),
        migrations.RenameField("evaluationstandard", "blueprint", "plan"),
        migrations.RenameField("evaluationstandard", "intended_use", "scope"),
        migrations.RenameField("evaluationstandard", "evaluation_object", "evaluation_target"),
        migrations.RenameField("evaluationstandard", "validation_status", "review_status"),
        migrations.RenameField("evaluationstandardversion", "blueprint_version", "plan_version"),
        migrations.RenameField("evaluationstandardversion", "intended_use", "scope"),
        migrations.RenameField("evaluationstandardversion", "evaluation_object", "evaluation_target"),
        migrations.RenameField("evaluationstandardversion", "validation_status", "review_status"),
        migrations.RenameField("evaluationcriterionversion", "rubric_version", "standard_version"),
        migrations.RenameField("evaluationcriterionversion", "module", "dimension"),
        migrations.RenameField("evaluationcriterionversion", "evaluation_object", "evaluation_target"),
        migrations.RenameField("evaluationcriterionversion", "evidence_sources", "evaluation_sources"),
        migrations.RenameField("evaluationcriterionversion", "observable_evidence", "expected_performance"),
        migrations.RenameField("evaluationcriterionversion", "not_assessed_condition", "skip_condition"),
        migrations.RenameField("evaluationcriterionversion", "allowed_supports", "support_options"),
        migrations.RenameField("evaluationcriterionversion", "counter_examples", "common_problems"),
        migrations.RenameField("evaluationcriterionversion", "anchor_level_1", "level_1_description"),
        migrations.RenameField("evaluationcriterionversion", "anchor_level_2", "level_2_description"),
        migrations.RenameField("evaluationcriterionversion", "anchor_level_3", "level_3_description"),
        migrations.RenameField("evaluationcriterionversion", "anchor_level_4", "level_4_description"),
        migrations.RenameField("evaluationcriterionversion", "anchor_level_5", "level_5_description"),
        migrations.RenameField("evaluationcriterionversion", "next_formative_action", "follow_up_suggestion"),
        migrations.RenameField("evaluationscoringexample", "evidence_summary", "example_description"),
        migrations.RenameField("evaluationscoringexample", "artifact_reference", "file_reference"),
        migrations.AlterField(
            model_name="evaluationplan",
            name="scope",
            field=models.CharField(
                choices=[
                    ("course", "课程使用"),
                    ("school", "校级通用"),
                    ("analysis", "专项分析"),
                ],
                default="course",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationplan",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("review_pending", "待审核"),
                    ("reviewed", "已审核"),
                    ("trial_scheduled", "待试用"),
                    ("trial_completed", "试用完成"),
                    ("approved", "已启用"),
                ],
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationplanversion",
            name="scope",
            field=models.CharField(
                choices=[
                    ("course", "课程使用"),
                    ("school", "校级通用"),
                    ("analysis", "专项分析"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationplanversion",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("review_pending", "待审核"),
                    ("reviewed", "已审核"),
                    ("trial_scheduled", "待试用"),
                    ("trial_completed", "试用完成"),
                    ("approved", "已启用"),
                ],
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationstandard",
            name="scope",
            field=models.CharField(
                choices=[
                    ("course", "课程使用"),
                    ("school", "校级通用"),
                    ("analysis", "专项分析"),
                ],
                default="course",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationstandard",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("review_pending", "待审核"),
                    ("reviewed", "已审核"),
                    ("trial_scheduled", "待试用"),
                    ("trial_completed", "试用完成"),
                    ("approved", "已启用"),
                ],
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationstandardversion",
            name="scope",
            field=models.CharField(
                choices=[
                    ("course", "课程使用"),
                    ("school", "校级通用"),
                    ("analysis", "专项分析"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationstandardversion",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("review_pending", "待审核"),
                    ("reviewed", "已审核"),
                    ("trial_scheduled", "待试用"),
                    ("trial_completed", "试用完成"),
                    ("approved", "已启用"),
                ],
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationcriterionversion",
            name="dimension",
            field=models.CharField(
                choices=[
                    ("task_quality", "任务完成质量"),
                    ("learning_method", "学习方法"),
                    ("self_management", "自我管理"),
                    ("collaboration", "合作与反馈"),
                    ("subject_practice", "学科实践"),
                    ("responsibility", "规范与责任"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(rename_evaluation_data, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="evaluationplanversion",
            constraint=models.UniqueConstraint(
                fields=("source", "version_no"),
                name="uniq_evaluation_plan_version_no",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationplanversion",
            constraint=models.UniqueConstraint(
                fields=("source", "content_hash"),
                name="uniq_evaluation_plan_content_hash",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationstandardversion",
            constraint=models.UniqueConstraint(
                fields=("source", "version_no"),
                name="uniq_evaluation_standard_version_no",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationstandardversion",
            constraint=models.UniqueConstraint(
                fields=("source", "content_hash"),
                name="uniq_evaluation_standard_content_hash",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationcriterionversion",
            constraint=models.UniqueConstraint(
                fields=("standard_version", "code"),
                name="uniq_evaluation_criterion_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationcriterionversion",
            constraint=models.UniqueConstraint(
                fields=("standard_version", "sort_order"),
                name="uniq_evaluation_criterion_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationscoringexample",
            constraint=models.CheckConstraint(
                condition=models.Q(level__gte=1, level__lte=5),
                name="evaluation_scoring_example_level_1_5",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationscoringexample",
            constraint=models.UniqueConstraint(
                fields=("criterion", "sort_order"),
                name="uniq_evaluation_scoring_example_order",
            ),
        ),
    ]
