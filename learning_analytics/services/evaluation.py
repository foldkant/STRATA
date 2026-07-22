from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationPlanVersion,
    EvaluationScoringExample,
    EvaluationCriterionVersion,
    EvaluationStandard,
    EvaluationStandardVersion,
    EvaluationDimension,
    canonical_content_hash,
)
from curriculum_standards.services import (
    copy_plan_curriculum_references,
    curriculum_reference_payload,
)

CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
THINKING_REQUIREMENT_VALUES = {
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
}
FORBIDDEN_EVALUATION_TERMS = {
    "出勤",
    "签到",
    "按时率",
    "完成率",
    "在线时长",
    "服从",
    "积分",
}


@dataclass(frozen=True)
class PublishResult:
    version: EvaluationPlanVersion | EvaluationStandardVersion
    created: bool


def _require_text(value, *, label: str, min_length: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < min_length:
        raise ValidationError(f"{label}不能为空。")
    return text


def _require_code(value, *, label: str) -> str:
    code = _require_text(value, label=label)
    if not CODE_PATTERN.fullmatch(code):
        raise ValidationError(f"{label}必须以字母开头，只能包含字母、数字、下划线或连字符。")
    return code


def _require_text_list(
    value,
    *,
    label: str,
    min_items: int = 1,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{label}必须是列表。")
    cleaned = [str(item or "").strip() for item in value]
    if any(not item for item in cleaned):
        raise ValidationError(f"{label}不能包含空白项。")
    if not allow_empty and len(cleaned) < min_items:
        raise ValidationError(f"{label}至少需要 {min_items} 项。")
    return cleaned


def validate_plan_for_publish(plan: EvaluationPlan) -> dict:
    title = _require_text(plan.title, label="方案名称", min_length=2)
    content_version = _require_text(plan.content_version, label="适用内容版本")
    target_students = _require_text(plan.target_students, label="适用学生")
    learning_goal = _require_text(plan.learning_goal, label="学习目标", min_length=8)
    next_action = _require_text(
        plan.follow_up_suggestion,
        label="后续教学建议",
        min_length=8,
    )

    if not plan.course_id:
        raise ValidationError("评价方案必须绑定课程。")

    learning_goals = plan.learning_goals
    if not isinstance(learning_goals, list) or not learning_goals:
        raise ValidationError({"learning_goals": "至少需要一条学习目标。"})
    cleaned_learning_goals = []
    goal_codes = set()
    for index, row in enumerate(learning_goals, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"learning_goals": f"第 {index} 条学习目标格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 条目标代码")
        if code in goal_codes:
            raise ValidationError({"learning_goals": f"学习目标代码 {code} 重复。"})
        goal_codes.add(code)
        cleaned_learning_goals.append(
            {
                "code": code,
                "title": _require_text(row.get("title"), label=f"第 {index} 条目标名称"),
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 条目标说明",
                    min_length=8,
                ),
            }
        )

    evaluation_basis = plan.evaluation_basis
    if not isinstance(evaluation_basis, list) or not evaluation_basis:
        raise ValidationError({"evaluation_basis": "至少需要一条评价依据。"})
    cleaned_evidence = []
    basis_codes = set()
    learning_goals_with_evidence = set()
    for index, row in enumerate(evaluation_basis, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"evaluation_basis": f"第 {index} 条评价依据格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 条依据代码")
        if code in basis_codes:
            raise ValidationError({"evaluation_basis": f"评价依据代码 {code} 重复。"})
        linked_learning_goals = _require_text_list(
            row.get("goal_codes"),
            label=f"第 {index} 条依据关联目标",
        )
        unknown_learning_goals = sorted(set(linked_learning_goals) - goal_codes)
        if unknown_learning_goals:
            raise ValidationError(
                {"evaluation_basis": f"评价依据 {code} 引用了未知目标：{', '.join(unknown_learning_goals)}。"}
            )
        basis_codes.add(code)
        learning_goals_with_evidence.update(linked_learning_goals)
        cleaned_evidence.append(
            {
                "code": code,
                "goal_codes": linked_learning_goals,
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 条依据说明",
                    min_length=8,
                ),
                "source_types": _require_text_list(
                    row.get("source_types"),
                    label=f"第 {index} 条材料来源",
                ),
            }
        )
    missing_learning_goals = sorted(goal_codes - learning_goals_with_evidence)
    if missing_learning_goals:
        raise ValidationError(
            {"evaluation_basis": f"以下学习目标尚无评价依据：{', '.join(missing_learning_goals)}。"}
        )

    task_specs = plan.learning_tasks
    if not isinstance(task_specs, list) or not task_specs:
        raise ValidationError({"learning_tasks": "至少需要一个学习任务。"})
    cleaned_tasks = []
    task_codes = set()
    evidence_with_task = set()
    for index, row in enumerate(task_specs, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"learning_tasks": f"第 {index} 个学习任务格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 个任务代码")
        if code in task_codes:
            raise ValidationError({"learning_tasks": f"任务代码 {code} 重复。"})
        linked_evidence = _require_text_list(
            row.get("basis_codes"),
            label=f"第 {index} 个任务关联依据",
        )
        unknown_evidence = sorted(set(linked_evidence) - basis_codes)
        if unknown_evidence:
            raise ValidationError(
                {"learning_tasks": f"任务 {code} 引用了未知评价依据：{', '.join(unknown_evidence)}。"}
            )
        task_codes.add(code)
        evidence_with_task.update(linked_evidence)
        cleaned_tasks.append(
            {
                "code": code,
                "title": _require_text(row.get("title"), label=f"第 {index} 个任务名称"),
                "basis_codes": linked_evidence,
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 个任务说明",
                    min_length=8,
                ),
            }
        )
    missing_evidence = sorted(basis_codes - evidence_with_task)
    if missing_evidence:
        raise ValidationError(
            {"learning_tasks": f"以下评价依据尚未关联学习任务：{', '.join(missing_evidence)}。"}
        )

    content_scope = _require_text_list(
        plan.content_scope,
        label="评价内容",
    )
    thinking_requirements = _require_text_list(
        plan.thinking_requirements,
        label="思维要求",
    )
    invalid_complexity = sorted(set(thinking_requirements) - THINKING_REQUIREMENT_VALUES)
    if invalid_complexity:
        raise ValidationError(
            {"thinking_requirements": f"包含未知思维要求：{', '.join(invalid_complexity)}。"}
        )
    support_options = _require_text_list(
        plan.support_options,
        label="可用帮助",
        min_items=0,
        allow_empty=True,
    )
    if not isinstance(plan.scoring_rules, dict):
        raise ValidationError({"scoring_rules": "评分规则必须是对象。"})
    scoring_rules = {
        "approach": _require_text(
            plan.scoring_rules.get("approach"),
            label="评分方式",
            min_length=4,
        ),
        "decision_rule": _require_text(
            plan.scoring_rules.get("decision_rule"),
            label="评分判定说明",
            min_length=8,
        ),
    }

    return {
        "school_id": plan.school_id,
        "subject_id": plan.subject_id,
        "course_id": plan.course_id,
        "title": title,
        "scope": plan.scope,
        "content_version": content_version,
        "target_students": target_students,
        "learning_goal": learning_goal,
        "learning_goals": cleaned_learning_goals,
        "evaluation_basis": cleaned_evidence,
        "learning_tasks": cleaned_tasks,
        "content_scope": content_scope,
        "thinking_requirements": thinking_requirements,
        "support_options": support_options,
        "scoring_rules": scoring_rules,
        "follow_up_suggestion": next_action,
        "review_status": plan.review_status,
    }


def _contains_forbidden_standard_term(value) -> str | None:
    serialized = str(value or "")
    return next((term for term in FORBIDDEN_EVALUATION_TERMS if term in serialized), None)


def validate_standard_for_publish(standard: EvaluationStandard) -> list[dict]:
    _require_text(standard.title, label="评价标准名称", min_length=2)
    _require_text(standard.evaluation_target, label="评价对象", min_length=4)
    criteria = standard.criteria
    if not isinstance(criteria, list) or not criteria:
        raise ValidationError({"criteria": "至少需要一个评价指标。"})
    if len(criteria) > 12:
        raise ValidationError({"criteria": "单个评价标准最多包含 12 个指标。"})

    cleaned = []
    codes = set()
    allowed_dimensions = {value for value, _ in EvaluationDimension.choices}
    for index, row in enumerate(criteria, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"criteria": f"第 {index} 个评价指标格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 个评价指标代码")
        if code in codes:
            raise ValidationError({"criteria": f"评价指标代码 {code} 重复。"})
        codes.add(code)
        dimension = str(row.get("dimension") or "")
        if dimension not in allowed_dimensions:
            raise ValidationError({"criteria": f"评价指标 {code} 的评价方面不正确。"})
        evaluation_sources = _require_text_list(
            row.get("evaluation_sources"),
            label=f"评价指标 {code} 的材料来源",
        )
        support_options = _require_text_list(
            row.get("support_options", []),
            label=f"评价指标 {code} 的可用帮助",
            min_items=0,
            allow_empty=True,
        )
        common_problems = _require_text_list(
            row.get("common_problems"),
            label=f"评价指标 {code} 的常见问题",
        )
        level_descriptions = row.get("level_descriptions")
        if not isinstance(level_descriptions, dict):
            raise ValidationError({"criteria": f"评价指标 {code} 缺少五个星级说明。"})
        cleaned_level_descriptions = {}
        for level in range(1, 6):
            anchor = _require_text(
                level_descriptions.get(str(level), level_descriptions.get(level)),
                label=f"评价指标 {code} 的 {level} 星说明",
                min_length=8,
            )
            cleaned_level_descriptions[str(level)] = anchor
        if len(set(cleaned_level_descriptions.values())) != 5:
            raise ValidationError({"criteria": f"评价指标 {code} 的五个星级说明必须各不相同。"})

        examples = row.get("scoring_examples")
        if not isinstance(examples, list) or len(examples) < 2:
            raise ValidationError({"criteria": f"评价指标 {code} 至少需要两个评分示例。"})
        cleaned_examples = []
        example_levels = set()
        for example_index, example in enumerate(examples, start=1):
            if not isinstance(example, dict):
                raise ValidationError({"criteria": f"评价指标 {code} 的评分示例格式不正确。"})
            try:
                level = int(example.get("level"))
            except (TypeError, ValueError) as exc:
                raise ValidationError({"criteria": f"评价指标 {code} 的示例星级不正确。"}) from exc
            if level < 1 or level > 5:
                raise ValidationError({"criteria": f"评价指标 {code} 的示例星级必须为 1-5。"})
            example_levels.add(level)
            cleaned_examples.append(
                {
                    "level": level,
                    "title": _require_text(
                        example.get("title"),
                        label=f"评价指标 {code} 第 {example_index} 个示例名称",
                    ),
                    "example_description": _require_text(
                        example.get("example_description"),
                        label=f"评价指标 {code} 第 {example_index} 个示例说明",
                        min_length=8,
                    ),
                    "file_reference": str(example.get("file_reference") or "").strip(),
                }
            )
        if len(example_levels) < 2:
            raise ValidationError({"criteria": f"评价指标 {code} 的评分示例至少覆盖两个星级。"})

        cleaned_row = {
            "code": code,
            "dimension": dimension,
            "title": _require_text(row.get("title"), label=f"评价指标 {code} 名称"),
            "evaluation_target": _require_text(
                row.get("evaluation_target"),
                label=f"评价指标 {code} 的评价对象",
                min_length=4,
            ),
            "evaluation_sources": evaluation_sources,
            "expected_performance": _require_text(
                row.get("expected_performance"),
                label=f"评价指标 {code} 的具体表现",
                min_length=8,
            ),
            "skip_condition": _require_text(
                row.get("skip_condition"),
                label=f"评价指标 {code} 的暂不评价条件",
                min_length=8,
            ),
            "support_options": support_options,
            "common_problems": common_problems,
            "level_descriptions": cleaned_level_descriptions,
            "scoring_examples": cleaned_examples,
            "follow_up_suggestion": _require_text(
                row.get("follow_up_suggestion"),
                label=f"评价指标 {code} 的后续教学建议",
                min_length=8,
            ),
            "sort_order": index - 1,
        }
        forbidden = _contains_forbidden_standard_term(cleaned_row)
        if forbidden:
            raise ValidationError(
                {"criteria": f"评价指标 {code} 包含“{forbidden}”；这类运行数据不能直接作为学科评价标准。"}
            )
        cleaned.append(cleaned_row)
    return cleaned


@transaction.atomic
def publish_plan(
    plan: EvaluationPlan,
    *,
    published_by,
) -> PublishResult:
    plan = EvaluationPlan.objects.select_for_update().get(pk=plan.pk)
    payload = validate_plan_for_publish(plan)
    curriculum_references = curriculum_reference_payload(plan)
    if curriculum_references:
        payload["curriculum_references"] = curriculum_references
    content_hash = canonical_content_hash(payload)
    existing = plan.versions.filter(content_hash=content_hash).first()
    if existing:
        return PublishResult(existing, False)
    latest = plan.versions.order_by("-version_no").first()
    version = EvaluationPlanVersion.objects.create(
        source=plan,
        school=plan.school,
        subject=plan.subject,
        course=plan.course,
        version_no=(latest.version_no + 1) if latest else 1,
        content_hash=content_hash,
        published_by=published_by,
        **{
            key: value
            for key, value in payload.items()
            if not key.endswith("_id") and key != "curriculum_references"
        },
    )
    if curriculum_references:
        copy_plan_curriculum_references(plan=plan, plan_version=version)
    return PublishResult(version, True)


@transaction.atomic
def publish_standard(
    standard: EvaluationStandard,
    *,
    published_by,
) -> PublishResult:
    standard = EvaluationStandard.objects.select_for_update().select_related("plan").get(pk=standard.pk)
    cleaned_criteria = validate_standard_for_publish(standard)
    plan_version = standard.plan.versions.order_by("-version_no").first()
    if plan_version is None:
        raise ValidationError("请先发布该评价标准绑定的评价方案。")
    if plan_version.scope != standard.scope:
        raise ValidationError("评价标准的使用范围必须与评价方案一致。")
    payload = {
        "school_id": standard.school_id,
        "subject_id": standard.subject_id,
        "course_id": standard.course_id,
        "plan_version_hash": plan_version.content_hash,
        "title": _require_text(standard.title, label="评价标准名称", min_length=2),
        "scope": standard.scope,
        "evaluation_target": _require_text(
            standard.evaluation_target,
            label="评价对象",
            min_length=4,
        ),
        "review_status": standard.review_status,
        "criteria": cleaned_criteria,
    }
    content_hash = canonical_content_hash(payload)
    existing = standard.versions.filter(content_hash=content_hash).first()
    if existing:
        return PublishResult(existing, False)
    latest = standard.versions.order_by("-version_no").first()
    version = EvaluationStandardVersion.objects.create(
        source=standard,
        plan_version=plan_version,
        school=standard.school,
        subject=standard.subject,
        course=standard.course,
        version_no=(latest.version_no + 1) if latest else 1,
        content_hash=content_hash,
        title=payload["title"],
        scope=standard.scope,
        evaluation_target=payload["evaluation_target"],
        review_status=standard.review_status,
        published_by=published_by,
    )
    for criterion_data in cleaned_criteria:
        level_descriptions = criterion_data.pop("level_descriptions")
        examples = criterion_data.pop("scoring_examples")
        criterion = EvaluationCriterionVersion.objects.create(
            standard_version=version,
            level_1_description=level_descriptions["1"],
            level_2_description=level_descriptions["2"],
            level_3_description=level_descriptions["3"],
            level_4_description=level_descriptions["4"],
            level_5_description=level_descriptions["5"],
            **criterion_data,
        )
        for sort_order, example in enumerate(examples):
            EvaluationScoringExample.objects.create(
                criterion=criterion,
                sort_order=sort_order,
                **example,
            )
    return PublishResult(version, True)
