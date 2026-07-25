from __future__ import annotations

import re
import time
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Max
from django.utils import timezone

from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationPlanVersion,
    EvaluationScoringExample,
    EvaluationCriterionVersion,
    EvaluationStandard,
    EvaluationStandardVersion,
    EvaluationDimension,
    EvaluationMode,
    EvaluationReviewStatus,
    EvidenceOwnership,
    canonical_content_hash,
)
from learning_analytics.target_models import (
    EvaluationBasisLearningTarget,
    EvaluationCriterionEvaluationTask,
    EvaluationCriterionLearningTarget,
    EvaluationTaskLearningActivity,
    EvaluationTaskLearningTarget,
    LearningActivityLearningTarget,
    LearningTarget,
    LearningTargetAlignmentStatus,
    LearningTargetCurriculumAlignment,
    LearningTargetVersion,
)
from curriculum_standards.models import CurriculumNodeType
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
MATERIAL_TYPE_VALUES = {
    "answer",
    "artifact",
    "operation",
    "oral_defense",
    "observation",
    "score",
}
MODE_MATERIAL_TYPES = {
    EvaluationMode.TEST: {"answer", "score"},
    EvaluationMode.OPERATION: {"operation", "observation"},
    EvaluationMode.PROJECT: {"artifact", "operation", "observation", "oral_defense"},
    EvaluationMode.ARTIFACT: {"artifact"},
    EvaluationMode.ORAL_DEFENSE: {"oral_defense"},
}
PUBLISH_MAX_ATTEMPTS = 3
PUBLISH_LOCK_RETRY_SECONDS = (0.0, 0.01, 0.03)
REQUIRED_CURRICULUM_NODE_TYPES = {
    CurriculumNodeType.CORE_COMPETENCY,
    CurriculumNodeType.COURSE_OBJECTIVE,
    CurriculumNodeType.COURSE_CONTENT,
    CurriculumNodeType.ACADEMIC_QUALITY,
}


def _curriculum_numbered_labels(content: str, *, prefix: str = "", limit: int = 8) -> list[str]:
    """Extract short official subheadings without inventing curriculum mappings."""
    rows = []
    seen = set()
    if prefix:
        matches = re.findall(rf"(?:^|\n)\s*({re.escape(prefix)}\s*[一二三四五六七八九十\d]+)", content or "")
    else:
        matches = re.findall(r"(?:^|\n)\s*\d+\s*[.．、]\s*([^\n]{2,36})", content or "")
    for raw in matches:
        label = re.sub(r"\s+", " ", str(raw or "")).strip(" ：:。；;")
        if not label or label in seen:
            continue
        seen.add(label)
        rows.append(label)
        if len(rows) >= limit:
            break
    return rows


def standard_curriculum_alignment(version: EvaluationStandardVersion) -> dict[str, dict]:
    """Build display-only curriculum links for each rubric criterion.

    The published plan proves which curriculum nodes support each learning goal.
    It does not prove that a local five-level rubric equals the curriculum's
    official academic-quality levels, so the response records that distinction.
    """
    plan_version = version.plan_version
    goals = {
        str(row.get("code") or "").strip(): row
        for row in (plan_version.learning_goals or [])
        if isinstance(row, dict) and str(row.get("code") or "").strip()
    }
    references = {
        reference.node_id: reference
        for reference in plan_version.curriculum_references.select_related("node").all()
    }

    result = {}
    for criterion in version.criteria.all():
        linked_goals = [
            goals[code]
            for code in criterion.learning_goal_codes
            if code in goals
        ]
        node_ids = {
            int(node_id)
            for goal in linked_goals
            for node_id in (goal.get("curriculum_node_ids") or [])
            if str(node_id).isdigit()
        }
        linked_references = [references[node_id] for node_id in node_ids if node_id in references]

        core_competencies = []
        academic_quality = []
        for reference in linked_references:
            node = reference.node
            base = {
                "node_id": node.id,
                "title": reference.node_title,
                "page_start": reference.source_page_start,
                "page_end": reference.source_page_end,
                "source_paragraph": reference.source_paragraph,
            }
            if reference.node_type == CurriculumNodeType.CORE_COMPETENCY:
                core_competencies.append(
                    {
                        **base,
                        "elements": _curriculum_numbered_labels(node.content, limit=8),
                    }
                )
            elif reference.node_type == CurriculumNodeType.ACADEMIC_QUALITY:
                academic_quality.append(
                    {
                        **base,
                        "level_labels": _curriculum_numbered_labels(
                            node.content, prefix="水平", limit=6
                        ),
                    }
                )

        result[criterion.code] = {
            "learning_goals": [
                {
                    "code": str(goal.get("code") or ""),
                    "title": str(goal.get("title") or ""),
                    "description": str(goal.get("description") or ""),
                }
                for goal in linked_goals
            ],
            "core_competencies": core_competencies,
            "academic_quality": academic_quality,
            "quality_mapping_status": "reference_only",
            "quality_mapping_note": (
                "本评价标准的1—5级为课堂表现水平，不直接等同于课程标准中的学业质量等级；"
                "当前仅显示可追溯的学业质量原文依据。"
            ),
        }
    return result


@dataclass(frozen=True)
class PublishResult:
    version: EvaluationPlanVersion | EvaluationStandardVersion
    created: bool


class EvaluationPublishConflict(Exception):
    """A bounded publish retry could not resolve a database race safely."""


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
    curriculum_node_types = dict(
        plan.curriculum_references.values_list("node_id", "node__node_type")
    )
    curriculum_node_ids = set(curriculum_node_types)
    if not curriculum_node_ids:
        raise ValidationError("评价方案必须选择至少一条已发布课程标准内容作为课标依据。")
    cleaned_learning_goals = []
    goal_codes = set()
    for index, row in enumerate(learning_goals, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"learning_goals": f"第 {index} 条学习目标格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 条目标代码")
        if code in goal_codes:
            raise ValidationError({"learning_goals": f"学习目标代码 {code} 重复。"})
        goal_codes.add(code)
        goal_curriculum_ids = row.get("curriculum_node_ids") or []
        if not isinstance(goal_curriculum_ids, list):
            raise ValidationError(
                {"learning_goals": f"学习目标 {code} 的课标依据必须是列表。"}
            )
        try:
            goal_curriculum_ids = [int(item) for item in goal_curriculum_ids]
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {"learning_goals": f"学习目标 {code} 的课标依据格式不正确。"}
            ) from exc
        if not goal_curriculum_ids:
            raise ValidationError(
                {"learning_goals": f"学习目标 {code} 必须关联至少一条课标依据。"}
            )
        if len(goal_curriculum_ids) != len(set(goal_curriculum_ids)):
            raise ValidationError(
                {"learning_goals": f"学习目标 {code} 的课标依据不能重复。"}
            )
        unknown_nodes = sorted(set(goal_curriculum_ids) - curriculum_node_ids)
        if unknown_nodes:
            raise ValidationError(
                {"learning_goals": f"学习目标 {code} 引用了未选择的课标依据。"}
            )
        covered_node_types = {
            curriculum_node_types[node_id] for node_id in goal_curriculum_ids
        }
        missing_node_types = REQUIRED_CURRICULUM_NODE_TYPES - covered_node_types
        if missing_node_types:
            labels = dict(CurriculumNodeType.choices)
            missing_labels = "、".join(
                labels[node_type] for node_type in CurriculumNodeType.values
                if node_type in missing_node_types
            )
            raise ValidationError(
                {
                    "learning_goals": (
                        f"学习目标 {code} 的课标依据不完整，尚缺：{missing_labels}。"
                    )
                }
            )
        cleaned_learning_goals.append(
            {
                "code": code,
                "title": _require_text(row.get("title"), label=f"第 {index} 条目标名称"),
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 条目标说明",
                    min_length=8,
                ),
                "curriculum_node_ids": goal_curriculum_ids,
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
        if len(linked_learning_goals) != len(set(linked_learning_goals)):
            raise ValidationError(
                {"evaluation_basis": f"评价依据 {code} 的关联目标不能重复。"}
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

    activity_specs = plan.learning_activities
    if not isinstance(activity_specs, list) or not activity_specs:
        raise ValidationError({"learning_activities": "至少需要一个学习活动。"})
    cleaned_activities = []
    activity_codes = set()
    goals_with_activity = set()
    for index, row in enumerate(activity_specs, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"learning_activities": f"第 {index} 个学习活动格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 个活动代码")
        if code in activity_codes:
            raise ValidationError({"learning_activities": f"活动代码 {code} 重复。"})
        linked_goals = _require_text_list(
            row.get("goal_codes"),
            label=f"第 {index} 个活动关联目标",
        )
        if len(linked_goals) != len(set(linked_goals)):
            raise ValidationError(
                {"learning_activities": f"学习活动 {code} 的关联目标不能重复。"}
            )
        unknown_goals = sorted(set(linked_goals) - goal_codes)
        if unknown_goals:
            raise ValidationError(
                {"learning_activities": f"活动 {code} 引用了未知学习目标：{', '.join(unknown_goals)}。"}
            )
        activity_codes.add(code)
        goals_with_activity.update(linked_goals)
        cleaned_activities.append(
            {
                "code": code,
                "title": _require_text(row.get("title"), label=f"第 {index} 个活动名称"),
                "goal_codes": linked_goals,
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 个活动说明",
                    min_length=8,
                ),
            }
        )
    missing_goal_activities = sorted(goal_codes - goals_with_activity)
    if missing_goal_activities:
        raise ValidationError(
            {"learning_activities": f"以下学习目标尚未关联学习活动：{', '.join(missing_goal_activities)}。"}
        )

    assessment_modes = _require_text_list(plan.assessment_modes, label="评价方式")
    allowed_modes = set(EvaluationMode.values)
    invalid_modes = sorted(set(assessment_modes) - allowed_modes)
    if invalid_modes:
        raise ValidationError({"assessment_modes": f"包含未知评价方式：{', '.join(invalid_modes)}。"})
    task_specs = plan.evaluation_tasks
    if not isinstance(task_specs, list) or not task_specs:
        raise ValidationError({"evaluation_tasks": "至少需要一个评价任务。"})
    cleaned_evaluation_tasks = []
    task_codes = set()
    task_modes = []
    goals_with_evaluation = set()
    activities_with_evaluation = set()
    activities_by_code = {row["code"]: row for row in cleaned_activities}
    for index, row in enumerate(task_specs, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"evaluation_tasks": f"第 {index} 个评价任务格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 个评价任务代码")
        if code in task_codes:
            raise ValidationError({"evaluation_tasks": f"评价任务代码 {code} 重复。"})
        linked_goals = _require_text_list(row.get("goal_codes"), label=f"评价任务 {code} 关联目标")
        linked_activities = _require_text_list(
            row.get("activity_codes"), label=f"评价任务 {code} 关联活动"
        )
        if len(linked_goals) != len(set(linked_goals)):
            raise ValidationError(
                {"evaluation_tasks": f"评价任务 {code} 的关联目标不能重复。"}
            )
        if len(linked_activities) != len(set(linked_activities)):
            raise ValidationError(
                {"evaluation_tasks": f"评价任务 {code} 的关联活动不能重复。"}
            )
        if set(linked_goals) - goal_codes:
            raise ValidationError({"evaluation_tasks": f"评价任务 {code} 引用了未知学习目标。"})
        if set(linked_activities) - activity_codes:
            raise ValidationError({"evaluation_tasks": f"评价任务 {code} 引用了未知学习活动。"})
        linked_activity_rows = [activities_by_code[item] for item in linked_activities]
        task_goal_set = set(linked_goals)
        for activity in linked_activity_rows:
            if not task_goal_set.intersection(activity["goal_codes"]):
                raise ValidationError(
                    {
                        "evaluation_tasks": (
                            f"评价任务 {code} 与学习活动 {activity['code']} 没有共同学习目标。"
                        )
                    }
                )
        supported_task_goals = {
            goal_code
            for activity in linked_activity_rows
            for goal_code in activity["goal_codes"]
            if goal_code in task_goal_set
        }
        if task_goal_set - supported_task_goals:
            raise ValidationError(
                {"evaluation_tasks": f"评价任务 {code} 的每个学习目标都必须由所关联学习活动支持。"}
            )
        mode = str(row.get("mode") or "").strip()
        if mode not in allowed_modes or mode not in assessment_modes:
            raise ValidationError({"evaluation_tasks": f"评价任务 {code} 的评价方式未在方案中启用。"})
        raw_component_modes = row.get("component_modes") or []
        if not isinstance(raw_component_modes, list):
            raise ValidationError({"evaluation_tasks": f"评价任务 {code} 的混合评价组成方式必须是列表。"})
        component_modes = [str(item or "").strip() for item in raw_component_modes]
        if mode == EvaluationMode.MIXED:
            if (
                len(component_modes) < 2
                or len(component_modes) != len(set(component_modes))
                or any(item not in MODE_MATERIAL_TYPES for item in component_modes)
            ):
                raise ValidationError(
                    {"evaluation_tasks": f"混合评价任务 {code} 至少需要两种不重复的非混合评价方式。"}
                )
        elif component_modes:
            raise ValidationError(
                {"evaluation_tasks": f"非混合评价任务 {code} 不能设置组成评价方式。"}
            )
        ownership = str(row.get("evidence_ownership") or "").strip()
        if ownership not in EvidenceOwnership.values:
            raise ValidationError({"evaluation_tasks": f"评价任务 {code} 必须区分个人或小组评价材料。"})
        material_types = _require_text_list(
            row.get("material_types"), label=f"评价任务 {code} 的评价材料"
        )
        if set(material_types) - MATERIAL_TYPE_VALUES:
            raise ValidationError({"evaluation_tasks": f"评价任务 {code} 包含未知评价材料类型。"})
        required_modes = component_modes if mode == EvaluationMode.MIXED else [mode]
        for required_mode in required_modes:
            if not set(material_types).intersection(MODE_MATERIAL_TYPES[required_mode]):
                raise ValidationError(
                    {
                        "evaluation_tasks": (
                            f"评价任务 {code} 缺少与{dict(EvaluationMode.choices)[required_mode]}相符的评价材料。"
                        )
                    }
                )
        try:
            weight = float(row.get("weight", 0))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {"evaluation_tasks": f"评价任务 {code} 的权重必须是数字。"}
            ) from exc
        if not 0 < weight <= 100:
            raise ValidationError(
                {"evaluation_tasks": f"评价任务 {code} 的权重必须大于 0 且不超过 100。"}
            )
        task_codes.add(code)
        task_modes.append(mode)
        goals_with_evaluation.update(linked_goals)
        activities_with_evaluation.update(linked_activities)
        cleaned_evaluation_tasks.append(
            {
                "code": code,
                "title": _require_text(row.get("title"), label=f"第 {index} 个评价任务名称"),
                "goal_codes": linked_goals,
                "activity_codes": linked_activities,
                "mode": mode,
                "component_modes": component_modes,
                "evidence_ownership": ownership,
                "material_types": material_types,
                "weight": round(weight, 4),
                "description": _require_text(
                    row.get("description"), label=f"评价任务 {code} 说明", min_length=8
                ),
            }
        )
    if goal_codes - goals_with_evaluation:
        raise ValidationError({"evaluation_tasks": "每条学习目标都必须有对应评价任务。"})
    if activity_codes - activities_with_evaluation:
        raise ValidationError({"evaluation_tasks": "每个学习活动都必须有对应评价任务。"})
    derived_modes = list(dict.fromkeys(task_modes))
    if len(assessment_modes) != len(set(assessment_modes)) or set(assessment_modes) != set(
        derived_modes
    ):
        raise ValidationError(
            {"assessment_modes": "方案评价方式必须与全部评价任务所使用方式的去重集合完全一致。"}
        )
    total_weight = sum(row["weight"] for row in cleaned_evaluation_tasks)
    if abs(total_weight - 100) > 0.001:
        raise ValidationError(
            {"evaluation_tasks": f"全部评价任务权重之和必须为 100%，当前为 {total_weight:g}%。"}
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
        "learning_activities": cleaned_activities,
        # 旧字段仅保留用于读取历史版本；新版本以 learning_activities 为唯一语义来源。
        "learning_tasks": [],
        "evaluation_tasks": cleaned_evaluation_tasks,
        "assessment_modes": derived_modes,
        "content_scope": content_scope,
        "thinking_requirements": thinking_requirements,
        "support_options": support_options,
        "scoring_rules": scoring_rules,
        "follow_up_suggestion": next_action,
    }


def _contains_forbidden_standard_term(value) -> str | None:
    serialized = str(value or "")
    return next((term for term in FORBIDDEN_EVALUATION_TERMS if term in serialized), None)


def validate_standard_for_publish(
    standard: EvaluationStandard,
    *,
    plan_version: EvaluationPlanVersion | None = None,
) -> list[dict]:
    _require_text(standard.title, label="评价标准名称", min_length=2)
    _require_text(standard.evaluation_target, label="评价对象", min_length=4)
    criteria = standard.criteria
    if not isinstance(criteria, list) or not criteria:
        raise ValidationError({"criteria": "至少需要一个评价指标。"})
    if len(criteria) > 12:
        raise ValidationError({"criteria": "单个评价标准最多包含 12 个指标。"})

    if plan_version is None:
        plan_version = standard.plan_version
    if plan_version is None:
        raise ValidationError("评价标准必须绑定一个明确的已复核评价方案版本。")
    if standard.plan_version_id != plan_version.id:
        raise ValidationError("评价标准复核所用方案版本与草稿绑定版本不一致。")
    if plan_version.source_id != standard.plan_id:
        raise ValidationError("评价标准必须绑定对应评价方案的已发布版本。")
    if (
        plan_version.review_status != EvaluationReviewStatus.REVIEWED
        or not plan_version.reviewed_by_id
        or not plan_version.reviewed_at
        or plan_version.reviewed_content_hash != plan_version.content_hash
    ):
        raise ValidationError("评价标准只能使用教师已完成复核的评价方案版本。")

    cleaned = []
    codes = set()
    plan_goal_codes = {
        str(row.get("code") or "")
        for row in plan_version.learning_goals
        if isinstance(row, dict)
    }
    plan_tasks = {
        str(row.get("code") or ""): row
        for row in plan_version.evaluation_tasks
        if isinstance(row, dict) and str(row.get("code") or "")
    }
    plan_task_codes = set(plan_tasks)
    covered_task_codes: set[str] = set()
    task_ownership_coverage: dict[str, set[str]] = {
        task_code: set() for task_code in plan_task_codes
    }
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
        learning_goal_codes = _require_text_list(
            row.get("learning_goal_codes"),
            label=f"评价指标 {code} 关联学习目标",
        )
        evaluation_task_codes = _require_text_list(
            row.get("evaluation_task_codes"),
            label=f"评价指标 {code} 关联评价任务",
        )
        if len(learning_goal_codes) != len(set(learning_goal_codes)):
            raise ValidationError(
                {"criteria": f"评价指标 {code} 的关联学习目标不能重复。"}
            )
        if len(evaluation_task_codes) != len(set(evaluation_task_codes)):
            raise ValidationError(
                {"criteria": f"评价指标 {code} 的关联评价任务不能重复。"}
            )
        if set(learning_goal_codes) - plan_goal_codes:
            raise ValidationError({"criteria": f"评价指标 {code} 引用了未知学习目标。"})
        if set(evaluation_task_codes) - plan_task_codes:
            raise ValidationError({"criteria": f"评价指标 {code} 引用了未知评价任务。"})
        linked_tasks = [plan_tasks[task_code] for task_code in evaluation_task_codes]
        linked_task_goals = {
            str(goal_code)
            for task in linked_tasks
            for goal_code in (task.get("goal_codes") or [])
        }
        if set(learning_goal_codes) - linked_task_goals:
            raise ValidationError(
                {"criteria": f"评价指标 {code} 关联的学习目标必须来自其所选评价任务。"}
            )
        for task in linked_tasks:
            task_goals = {str(item) for item in (task.get("goal_codes") or [])}
            if not task_goals.intersection(learning_goal_codes):
                raise ValidationError(
                    {"criteria": f"评价指标 {code} 与评价任务 {task.get('code')} 没有共同学习目标。"}
                )
        evidence_ownership = str(row.get("evidence_ownership") or "").strip()
        if evidence_ownership not in EvidenceOwnership.values:
            raise ValidationError({"criteria": f"评价指标 {code} 必须明确个人或小组评价材料。"})
        for task in linked_tasks:
            task_ownership = str(task.get("evidence_ownership") or "")
            if task_ownership != EvidenceOwnership.BOTH and evidence_ownership != task_ownership:
                raise ValidationError(
                    {"criteria": f"评价指标 {code} 的材料归属与评价任务 {task.get('code')} 不一致。"}
                )
            covered_ownerships = (
                {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
                if evidence_ownership == EvidenceOwnership.BOTH
                else {evidence_ownership}
            )
            task_ownership_coverage[str(task.get("code") or "")].update(
                covered_ownerships
            )
        material_types = _require_text_list(
            row.get("material_types"),
            label=f"评价指标 {code} 的评价材料类型",
        )
        if set(material_types) - MATERIAL_TYPE_VALUES:
            raise ValidationError({"criteria": f"评价指标 {code} 包含未知评价材料类型。"})
        for task in linked_tasks:
            task_material_types = {
                str(item) for item in (task.get("material_types") or [])
            }
            if not set(material_types).intersection(task_material_types):
                raise ValidationError(
                    {"criteria": f"评价指标 {code} 与评价任务 {task.get('code')} 没有共同的评价材料类型。"}
                )
        covered_task_codes.update(evaluation_task_codes)
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
            "learning_goal_codes": learning_goal_codes,
            "evaluation_task_codes": evaluation_task_codes,
            "evidence_ownership": evidence_ownership,
            "material_types": material_types,
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
    uncovered = sorted(plan_task_codes - covered_task_codes)
    if uncovered:
        raise ValidationError(
            {"criteria": f"以下评价任务尚未设置评价指标：{', '.join(uncovered)}。"}
        )
    incomplete_both = sorted(
        task_code
        for task_code, task in plan_tasks.items()
        if str(task.get("evidence_ownership") or "") == EvidenceOwnership.BOTH
        and task_ownership_coverage[task_code]
        != {EvidenceOwnership.INDIVIDUAL, EvidenceOwnership.GROUP}
    )
    if incomplete_both:
        raise ValidationError(
            {
                "criteria": (
                    "以下评价任务要求分别保存个人与小组评价材料，但评价指标尚未同时覆盖两类材料："
                    f"{', '.join(incomplete_both)}。"
                )
            }
        )
    return cleaned


def plan_content_payload(plan: EvaluationPlan) -> dict:
    payload = validate_plan_for_publish(plan)
    references = curriculum_reference_payload(plan)
    if references:
        payload["curriculum_references"] = references
    return payload


def plan_content_hash(plan: EvaluationPlan) -> str:
    return canonical_content_hash(plan_content_payload(plan))


def standard_content_payload(
    standard: EvaluationStandard,
    *,
    plan_version: EvaluationPlanVersion | None = None,
) -> dict:
    plan_version = plan_version or standard.plan_version
    if plan_version is None:
        raise ValidationError("评价标准必须绑定一个明确的评价方案版本。")
    cleaned_criteria = validate_standard_for_publish(
        standard,
        plan_version=plan_version,
    )
    if plan_version.scope != standard.scope:
        raise ValidationError("评价标准的使用范围必须与评价方案一致。")
    return {
        "school_id": standard.school_id,
        "subject_id": standard.subject_id,
        "course_id": standard.course_id,
        "plan_version_id": plan_version.id,
        "plan_version_hash": plan_version.content_hash,
        "title": _require_text(standard.title, label="评价标准名称", min_length=2),
        "scope": standard.scope,
        "evaluation_target": _require_text(
            standard.evaluation_target,
            label="评价对象",
            min_length=4,
        ),
        "criteria": cleaned_criteria,
    }


def standard_content_hash(standard: EvaluationStandard) -> str:
    return canonical_content_hash(standard_content_payload(standard))


def _require_teacher_scope(*, course, actor) -> None:
    if course is None or course.teacher_id != getattr(actor, "id", None):
        raise ValidationError("只有该课程教师可以完成评价内容复核。")
    if course.teacher.school_id != getattr(actor, "school_id", None):
        raise ValidationError("教师与评价内容不属于同一学校。")


@transaction.atomic
def confirm_plan_review(*, plan: EvaluationPlan, reviewed_by) -> EvaluationPlan:
    plan = EvaluationPlan.objects.select_for_update().select_related("course__teacher").get(
        pk=plan.pk
    )
    _require_teacher_scope(course=plan.course, actor=reviewed_by)
    content_hash = plan_content_hash(plan)
    if (
        plan.review_status == EvaluationReviewStatus.REVIEWED
        and plan.reviewed_by_id == reviewed_by.id
        and plan.reviewed_at
        and plan.reviewed_content_hash == content_hash
    ):
        return plan
    plan.review_status = EvaluationReviewStatus.REVIEWED
    plan.reviewed_by = reviewed_by
    plan.reviewed_at = timezone.now()
    plan.reviewed_content_hash = content_hash
    plan.updated_by = reviewed_by
    plan.save()
    return plan


@transaction.atomic
def confirm_standard_review(
    *, standard: EvaluationStandard, reviewed_by
) -> EvaluationStandard:
    standard = (
        EvaluationStandard.objects.select_for_update()
        .select_related("course__teacher", "plan_version", "plan")
        .get(pk=standard.pk)
    )
    _require_teacher_scope(course=standard.course, actor=reviewed_by)
    content_hash = standard_content_hash(standard)
    if (
        standard.review_status == EvaluationReviewStatus.REVIEWED
        and standard.reviewed_by_id == reviewed_by.id
        and standard.reviewed_at
        and standard.reviewed_content_hash == content_hash
    ):
        return standard
    standard.review_status = EvaluationReviewStatus.REVIEWED
    standard.reviewed_by = reviewed_by
    standard.reviewed_at = timezone.now()
    standard.reviewed_content_hash = content_hash
    standard.updated_by = reviewed_by
    standard.save()
    return standard


def _require_review_audit(*, source, current_hash: str, label: str) -> None:
    if (
        source.review_status != EvaluationReviewStatus.REVIEWED
        or not source.reviewed_by_id
        or not source.reviewed_at
        or source.reviewed_content_hash != current_hash
    ):
        raise ValidationError(f"{label}当前内容尚未由课程教师完成复核，不能发布。")


def _learning_target_hash(
    *,
    plan_version: EvaluationPlanVersion,
    goal: dict,
    curriculum_references: list,
) -> str:
    """Hash the exact target wording and immutable curriculum snapshots."""

    return canonical_content_hash(
        {
            "plan_version_hash": plan_version.content_hash,
            "code": goal["code"],
            "title": goal["title"],
            "description": goal["description"],
            "curriculum_references": [
                {
                    "node_type": reference.node_type,
                    "node_code": reference.node_code,
                    "node_content_hash": reference.node_content_hash,
                    "curriculum_version_hash": reference.curriculum_version_hash,
                }
                for reference in curriculum_references
            ],
        }
    )


def _ensure_plan_learning_target_versions(
    plan_version: EvaluationPlanVersion,
) -> dict[str, LearningTargetVersion]:
    """Create or verify the immutable target chain for one published plan.

    Missing derived links may be added to an older published plan, but an
    existing target version or link is never updated or removed.
    """

    if not plan_version.course_id:
        raise ValidationError("正式学习目标必须绑定具体课程。")
    references = list(
        plan_version.curriculum_references.select_related("node").order_by(
            "node_type", "node_code", "node_id", "id"
        )
    )
    references_by_node = {reference.node_id: reference for reference in references}
    target_versions: dict[str, LearningTargetVersion] = {}
    goal_codes: set[str] = set()

    for goal in plan_version.learning_goals or []:
        if not isinstance(goal, dict):
            raise ValidationError("已发布方案包含无法建立正式关系的学习目标。")
        code = _require_code(goal.get("code"), label="学习目标代码")
        if code in goal_codes:
            raise ValidationError(f"已发布方案中的学习目标代码 {code} 不唯一。")
        goal_codes.add(code)
        title = _require_text(goal.get("title"), label=f"学习目标 {code} 名称")
        description = _require_text(
            goal.get("description"),
            label=f"学习目标 {code} 说明",
            min_length=8,
        )
        raw_node_ids = goal.get("curriculum_node_ids")
        if not isinstance(raw_node_ids, list):
            raise ValidationError(f"学习目标 {code} 的课程标准依据格式不正确。")
        try:
            node_ids = [int(node_id) for node_id in raw_node_ids]
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"学习目标 {code} 的课程标准依据格式不正确。"
            ) from exc
        if not node_ids or len(node_ids) != len(set(node_ids)):
            raise ValidationError(f"学习目标 {code} 的课程标准依据为空或存在重复。")
        missing_reference_ids = set(node_ids) - set(references_by_node)
        if missing_reference_ids:
            raise ValidationError(f"学习目标 {code} 的课程标准依据不属于该方案版本。")
        goal_references = sorted(
            (references_by_node[node_id] for node_id in node_ids),
            key=lambda row: (row.node_type, row.node_code, row.node_id, row.id),
        )
        covered_types = {reference.node_type for reference in goal_references}
        if REQUIRED_CURRICULUM_NODE_TYPES - covered_types:
            raise ValidationError(
                f"学习目标 {code} 必须同时对应核心素养、课程目标、课程内容和学业质量。"
            )

        target, _created = LearningTarget.objects.select_for_update().get_or_create(
            school_id=plan_version.school_id,
            subject_id=plan_version.subject_id,
            course_id=plan_version.course_id,
            code=code,
            defaults={"created_by_id": plan_version.published_by_id},
        )
        if (
            target.school_id != plan_version.school_id
            or target.subject_id != plan_version.subject_id
            or target.course_id != plan_version.course_id
            or target.code != code
        ):
            raise ValidationError(f"学习目标 {code} 的逻辑身份与方案范围不一致。")

        target_hash = _learning_target_hash(
            plan_version=plan_version,
            goal={"code": code, "title": title, "description": description},
            curriculum_references=goal_references,
        )
        target_version = LearningTargetVersion.objects.filter(
            plan_version=plan_version,
            code=code,
        ).first()
        if target_version is None:
            latest_no = (
                LearningTargetVersion.objects.filter(target=target).aggregate(
                    latest=Max("version_no")
                )["latest"]
                or 0
            )
            target_version = LearningTargetVersion.objects.create(
                target=target,
                plan_version=plan_version,
                version_no=latest_no + 1,
                code=code,
                title=title,
                description=description,
                content_hash=target_hash,
                alignment_status=LearningTargetAlignmentStatus.COMPLETE,
                published_by_id=plan_version.published_by_id,
            )
        else:
            expected = {
                "target_id": target.id,
                "title": title,
                "description": description,
                "content_hash": target_hash,
                "alignment_status": LearningTargetAlignmentStatus.COMPLETE,
                "published_by_id": plan_version.published_by_id,
            }
            mismatches = [
                field_name
                for field_name, value in expected.items()
                if getattr(target_version, field_name) != value
            ]
            if mismatches:
                raise ValidationError(
                    f"学习目标 {code} 已有版本与发布快照不一致，不能改写历史记录。"
                )

        desired_reference_ids = {reference.id for reference in goal_references}
        current_alignments = {
            link.plan_reference_id: link
            for link in target_version.curriculum_alignments.all()
        }
        if set(current_alignments) - desired_reference_ids:
            raise ValidationError(
                f"学习目标 {code} 已有额外课程标准依据，不能改写历史记录。"
            )
        for sort_order, reference in enumerate(goal_references):
            current = current_alignments.get(reference.id)
            if current is not None:
                if current.sort_order != sort_order:
                    raise ValidationError(
                        f"学习目标 {code} 的课程标准依据顺序与历史记录不一致。"
                    )
                continue
            LearningTargetCurriculumAlignment.objects.create(
                target_version=target_version,
                plan_reference=reference,
                sort_order=sort_order,
            )
        target_versions[code] = target_version

    def synchronize_coded_links(
        *,
        rows,
        relation_label: str,
        code_field: str,
        model,
    ) -> None:
        if not isinstance(rows, list):
            raise ValidationError(f"已发布方案中的{relation_label}格式不正确。")
        desired_links: dict[tuple[str, int], int] = {}
        seen_codes: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValidationError(
                    f"已发布方案包含无法建立学习目标关系的{relation_label}。"
                )
            relation_code = _require_code(
                row.get("code"), label=f"{relation_label}代码"
            )
            if relation_code in seen_codes:
                raise ValidationError(
                    f"已发布方案中的{relation_label}代码 {relation_code} 不唯一。"
                )
            seen_codes.add(relation_code)
            linked_codes = _require_text_list(
                row.get("goal_codes"),
                label=f"{relation_label} {relation_code} 关联目标",
            )
            if len(linked_codes) != len(set(linked_codes)):
                raise ValidationError(
                    f"{relation_label} {relation_code} 的关联学习目标不能重复。"
                )
            for sort_order, code in enumerate(linked_codes):
                target_version = target_versions.get(code)
                if target_version is None:
                    raise ValidationError(
                        f"{relation_label} {relation_code} 引用了未知学习目标 {code}。"
                    )
                desired_links[(relation_code, target_version.id)] = sort_order

        current_links = {
            (getattr(link, code_field), link.target_version_id): link
            for link in model.objects.filter(plan_version=plan_version)
        }
        if set(current_links) - set(desired_links):
            raise ValidationError(
                f"{relation_label}已有额外学习目标关系，不能改写历史记录。"
            )
        for key, sort_order in desired_links.items():
            current = current_links.get(key)
            if current is not None:
                if current.sort_order != sort_order:
                    raise ValidationError(
                        f"{relation_label}与学习目标的顺序和历史记录不一致。"
                    )
                continue
            relation_code, target_version_id = key
            model.objects.create(
                plan_version=plan_version,
                target_version_id=target_version_id,
                sort_order=sort_order,
                **{code_field: relation_code},
            )

    synchronize_coded_links(
        rows=plan_version.evaluation_basis,
        relation_label="评价依据",
        code_field="basis_code",
        model=EvaluationBasisLearningTarget,
    )
    synchronize_coded_links(
        rows=plan_version.learning_activities,
        relation_label="学习活动",
        code_field="activity_code",
        model=LearningActivityLearningTarget,
    )
    synchronize_coded_links(
        rows=plan_version.evaluation_tasks,
        relation_label="评价任务",
        code_field="task_code",
        model=EvaluationTaskLearningTarget,
    )
    desired_task_activities: dict[tuple[str, str], int] = {}
    for task in plan_version.evaluation_tasks or []:
        if not isinstance(task, dict):
            raise ValidationError("已发布方案包含无法建立学习活动关系的评价任务。")
        task_code = _require_code(task.get("code"), label="评价任务代码")
        activity_codes = _require_text_list(
            task.get("activity_codes"),
            label=f"评价任务 {task_code} 关联活动",
        )
        if len(activity_codes) != len(set(activity_codes)):
            raise ValidationError(f"评价任务 {task_code} 的学习活动关系存在重复。")
        for sort_order, activity_code in enumerate(activity_codes):
            desired_task_activities[(task_code, activity_code)] = sort_order
    current_task_activities = {
        (link.task_code, link.activity_code): link
        for link in EvaluationTaskLearningActivity.objects.filter(
            plan_version=plan_version
        )
    }
    if set(current_task_activities) - set(desired_task_activities):
        raise ValidationError("评价任务已有额外学习活动关系，不能改写历史记录。")
    for (task_code, activity_code), sort_order in desired_task_activities.items():
        current = current_task_activities.get((task_code, activity_code))
        if current is not None:
            if current.sort_order != sort_order:
                raise ValidationError("评价任务与学习活动的顺序和历史记录不一致。")
            continue
        EvaluationTaskLearningActivity.objects.create(
            plan_version=plan_version,
            task_code=task_code,
            activity_code=activity_code,
            sort_order=sort_order,
        )
    return target_versions


def _ensure_standard_learning_target_links(
    standard_version: EvaluationStandardVersion,
) -> None:
    target_versions = _ensure_plan_learning_target_versions(
        standard_version.plan_version
    )
    for criterion in standard_version.criteria.all():
        desired_codes = [str(code) for code in (criterion.learning_goal_codes or [])]
        if not desired_codes or len(desired_codes) != len(set(desired_codes)):
            raise ValidationError(
                f"评价指标 {criterion.code} 的学习目标关系为空或存在重复。"
            )
        desired_links = {}
        for sort_order, code in enumerate(desired_codes):
            target_version = target_versions.get(code)
            if target_version is None:
                raise ValidationError(f"评价指标 {criterion.code} 引用了未知学习目标 {code}。")
            desired_links[target_version.id] = sort_order
        current_links = {
            link.target_version_id: link
            for link in criterion.learning_target_links.all()
        }
        if set(current_links) - set(desired_links):
            raise ValidationError(
                f"评价指标 {criterion.code} 已有额外学习目标关系，不能改写历史记录。"
            )
        for target_version_id, sort_order in desired_links.items():
            current = current_links.get(target_version_id)
            if current is not None:
                if current.sort_order != sort_order:
                    raise ValidationError(
                        f"评价指标 {criterion.code} 的学习目标顺序与历史记录不一致。"
                    )
                continue
            EvaluationCriterionLearningTarget.objects.create(
                criterion=criterion,
                target_version_id=target_version_id,
                sort_order=sort_order,
            )
        desired_task_codes = [
            str(code) for code in (criterion.evaluation_task_codes or [])
        ]
        if not desired_task_codes or len(desired_task_codes) != len(
            set(desired_task_codes)
        ):
            raise ValidationError(
                f"评价指标 {criterion.code} 的评价任务关系为空或存在重复。"
            )
        current_task_links = {
            link.task_code: link for link in criterion.evaluation_task_links.all()
        }
        if set(current_task_links) - set(desired_task_codes):
            raise ValidationError(
                f"评价指标 {criterion.code} 已有额外评价任务关系，不能改写历史记录。"
            )
        for sort_order, task_code in enumerate(desired_task_codes):
            current = current_task_links.get(task_code)
            if current is not None:
                if current.sort_order != sort_order:
                    raise ValidationError(
                        f"评价指标 {criterion.code} 的评价任务顺序与历史记录不一致。"
                    )
                continue
            EvaluationCriterionEvaluationTask.objects.create(
                criterion=criterion,
                task_code=task_code,
                sort_order=sort_order,
            )


def _publish_plan_once(*, plan_id: int, published_by) -> PublishResult:
    with transaction.atomic():
        plan = (
            EvaluationPlan.objects.select_for_update()
            .select_related("course__teacher", "reviewed_by")
            .get(pk=plan_id)
        )
        _require_teacher_scope(course=plan.course, actor=published_by)
        payload = plan_content_payload(plan)
        content_hash = canonical_content_hash(payload)
        _require_review_audit(
            source=plan,
            current_hash=content_hash,
            label="评价方案",
        )
        existing = plan.versions.filter(content_hash=content_hash).first()
        if existing:
            _ensure_plan_learning_target_versions(existing)
            return PublishResult(existing, False)
        latest = plan.versions.order_by("-version_no").first()
        version = EvaluationPlanVersion.objects.create(
            source=plan,
            school=plan.school,
            subject=plan.subject,
            course=plan.course,
            version_no=(latest.version_no + 1) if latest else 1,
            content_hash=content_hash,
            review_status=EvaluationReviewStatus.REVIEWED,
            reviewed_by=plan.reviewed_by,
            reviewed_at=plan.reviewed_at,
            reviewed_content_hash=plan.reviewed_content_hash,
            published_by=published_by,
            **{
                key: value
                for key, value in payload.items()
                if not key.endswith("_id") and key != "curriculum_references"
            },
        )
        if payload.get("curriculum_references"):
            copy_plan_curriculum_references(plan=plan, plan_version=version)
        _ensure_plan_learning_target_versions(version)
        return PublishResult(version, True)


def _publish_standard_once(*, standard_id: int, published_by) -> PublishResult:
    with transaction.atomic():
        standard = (
            EvaluationStandard.objects.select_for_update()
            .select_related(
                "plan",
                "plan_version",
                "course__teacher",
                "reviewed_by",
            )
            .get(pk=standard_id)
        )
        _require_teacher_scope(course=standard.course, actor=published_by)
        if standard.plan_version_id is None:
            raise ValidationError("评价标准必须绑定一个明确的评价方案版本。")
        payload = standard_content_payload(
            standard,
            plan_version=standard.plan_version,
        )
        content_hash = canonical_content_hash(payload)
        _require_review_audit(
            source=standard,
            current_hash=content_hash,
            label="评价标准",
        )
        _ensure_plan_learning_target_versions(standard.plan_version)
        existing = standard.versions.filter(content_hash=content_hash).first()
        if existing:
            _ensure_standard_learning_target_links(existing)
            return PublishResult(existing, False)
        latest = standard.versions.order_by("-version_no").first()
        version = EvaluationStandardVersion.objects.create(
            source=standard,
            plan_version=standard.plan_version,
            school=standard.school,
            subject=standard.subject,
            course=standard.course,
            version_no=(latest.version_no + 1) if latest else 1,
            content_hash=content_hash,
            title=payload["title"],
            scope=standard.scope,
            evaluation_target=payload["evaluation_target"],
            review_status=EvaluationReviewStatus.REVIEWED,
            reviewed_by=standard.reviewed_by,
            reviewed_at=standard.reviewed_at,
            reviewed_content_hash=standard.reviewed_content_hash,
            published_by=published_by,
        )
        for raw_criterion in payload["criteria"]:
            criterion_data = dict(raw_criterion)
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
        _ensure_standard_learning_target_links(version)
        return PublishResult(version, True)


def _locked_database_error(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _retry_pause(attempt: int) -> None:
    delay = PUBLISH_LOCK_RETRY_SECONDS[min(attempt, len(PUBLISH_LOCK_RETRY_SECONDS) - 1)]
    if delay:
        time.sleep(delay)


def _published_plan_winner(*, plan_id: int):
    reviewed_hash = EvaluationPlan.objects.filter(pk=plan_id).values_list(
        "reviewed_content_hash", flat=True
    ).first()
    if not reviewed_hash:
        return None
    return EvaluationPlanVersion.objects.filter(
        source_id=plan_id,
        content_hash=reviewed_hash,
    ).first()


def _published_standard_winner(*, standard_id: int):
    reviewed_hash = EvaluationStandard.objects.filter(pk=standard_id).values_list(
        "reviewed_content_hash", flat=True
    ).first()
    if not reviewed_hash:
        return None
    return EvaluationStandardVersion.objects.filter(
        source_id=standard_id,
        content_hash=reviewed_hash,
    ).first()


def publish_plan(
    plan: EvaluationPlan,
    *,
    published_by,
) -> PublishResult:
    last_error = None
    for attempt in range(PUBLISH_MAX_ATTEMPTS):
        try:
            return _publish_plan_once(plan_id=plan.pk, published_by=published_by)
        except IntegrityError as exc:
            last_error = exc
            try:
                winner = _published_plan_winner(plan_id=plan.pk)
            except OperationalError as lookup_exc:
                last_error = lookup_exc
                winner = None
            if winner is not None:
                try:
                    with transaction.atomic():
                        _ensure_plan_learning_target_versions(winner)
                    return PublishResult(winner, False)
                except (IntegrityError, OperationalError) as repair_exc:
                    last_error = repair_exc
            _retry_pause(attempt)
        except OperationalError as exc:
            last_error = exc
            if not _locked_database_error(exc):
                break
            _retry_pause(attempt)
    raise EvaluationPublishConflict("评价方案发布发生并发冲突，请稍后重试。") from last_error


def publish_standard(
    standard: EvaluationStandard,
    *,
    published_by,
) -> PublishResult:
    last_error = None
    for attempt in range(PUBLISH_MAX_ATTEMPTS):
        try:
            return _publish_standard_once(
                standard_id=standard.pk,
                published_by=published_by,
            )
        except IntegrityError as exc:
            last_error = exc
            try:
                winner = _published_standard_winner(standard_id=standard.pk)
            except OperationalError as lookup_exc:
                last_error = lookup_exc
                winner = None
            if winner is not None:
                try:
                    with transaction.atomic():
                        _ensure_standard_learning_target_links(winner)
                    return PublishResult(winner, False)
                except (IntegrityError, OperationalError) as repair_exc:
                    last_error = repair_exc
            _retry_pause(attempt)
        except OperationalError as exc:
            last_error = exc
            if not _locked_database_error(exc):
                break
            _retry_pause(attempt)
    raise EvaluationPublishConflict("评价标准发布发生并发冲突，请稍后重试。") from last_error
