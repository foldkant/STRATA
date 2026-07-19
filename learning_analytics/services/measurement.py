from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from learning_analytics.measurement_models import (
    AssessmentBlueprint,
    AssessmentBlueprintVersion,
    RubricAnchorExample,
    RubricCriterionVersion,
    RubricDefinition,
    RubricDefinitionVersion,
    RubricModule,
    canonical_content_hash,
)

CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
COGNITIVE_COMPLEXITY_VALUES = {
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
}
FORBIDDEN_RUBRIC_TERMS = {
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
    version: AssessmentBlueprintVersion | RubricDefinitionVersion
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


def validate_blueprint_for_publish(blueprint: AssessmentBlueprint) -> dict:
    title = _require_text(blueprint.title, label="蓝图名称", min_length=2)
    task_version = _require_text(blueprint.task_version, label="任务版本")
    target_population = _require_text(blueprint.target_population, label="目标学生总体")
    course_goal = _require_text(blueprint.course_goal, label="学科或课程目标", min_length=8)
    next_action = _require_text(
        blueprint.next_formative_action,
        label="下一步形成性行动",
        min_length=8,
    )

    if not blueprint.course_id:
        raise ValidationError("教师本地形成性蓝图必须绑定课程。")

    claims = blueprint.claims
    if not isinstance(claims, list) or not claims:
        raise ValidationError({"claims": "至少需要一条可解释的学习主张。"})
    cleaned_claims = []
    claim_codes = set()
    for index, row in enumerate(claims, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"claims": f"第 {index} 条学习主张格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 条主张代码")
        if code in claim_codes:
            raise ValidationError({"claims": f"学习主张代码 {code} 重复。"})
        claim_codes.add(code)
        cleaned_claims.append(
            {
                "code": code,
                "title": _require_text(row.get("title"), label=f"第 {index} 条主张名称"),
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 条主张说明",
                    min_length=8,
                ),
            }
        )

    evidence_rules = blueprint.evidence_rules
    if not isinstance(evidence_rules, list) or not evidence_rules:
        raise ValidationError({"evidence_rules": "至少需要一条证据规则。"})
    cleaned_evidence = []
    evidence_codes = set()
    claims_with_evidence = set()
    for index, row in enumerate(evidence_rules, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"evidence_rules": f"第 {index} 条证据规则格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 条证据代码")
        if code in evidence_codes:
            raise ValidationError({"evidence_rules": f"证据规则代码 {code} 重复。"})
        linked_claims = _require_text_list(
            row.get("claim_codes"),
            label=f"第 {index} 条证据关联主张",
        )
        unknown_claims = sorted(set(linked_claims) - claim_codes)
        if unknown_claims:
            raise ValidationError(
                {"evidence_rules": f"证据 {code} 引用了未知主张：{', '.join(unknown_claims)}。"}
            )
        evidence_codes.add(code)
        claims_with_evidence.update(linked_claims)
        cleaned_evidence.append(
            {
                "code": code,
                "claim_codes": linked_claims,
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 条证据说明",
                    min_length=8,
                ),
                "source_types": _require_text_list(
                    row.get("source_types"),
                    label=f"第 {index} 条证据来源",
                ),
            }
        )
    missing_claims = sorted(claim_codes - claims_with_evidence)
    if missing_claims:
        raise ValidationError(
            {"evidence_rules": f"以下主张尚无证据规则：{', '.join(missing_claims)}。"}
        )

    task_specs = blueprint.task_specifications
    if not isinstance(task_specs, list) or not task_specs:
        raise ValidationError({"task_specifications": "至少需要一个任务规格。"})
    cleaned_tasks = []
    task_codes = set()
    evidence_with_task = set()
    for index, row in enumerate(task_specs, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"task_specifications": f"第 {index} 个任务规格格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 个任务代码")
        if code in task_codes:
            raise ValidationError({"task_specifications": f"任务代码 {code} 重复。"})
        linked_evidence = _require_text_list(
            row.get("evidence_codes"),
            label=f"第 {index} 个任务关联证据",
        )
        unknown_evidence = sorted(set(linked_evidence) - evidence_codes)
        if unknown_evidence:
            raise ValidationError(
                {"task_specifications": f"任务 {code} 引用了未知证据：{', '.join(unknown_evidence)}。"}
            )
        task_codes.add(code)
        evidence_with_task.update(linked_evidence)
        cleaned_tasks.append(
            {
                "code": code,
                "title": _require_text(row.get("title"), label=f"第 {index} 个任务名称"),
                "evidence_codes": linked_evidence,
                "description": _require_text(
                    row.get("description"),
                    label=f"第 {index} 个任务说明",
                    min_length=8,
                ),
            }
        )
    missing_evidence = sorted(evidence_codes - evidence_with_task)
    if missing_evidence:
        raise ValidationError(
            {"task_specifications": f"以下证据尚无任务触发：{', '.join(missing_evidence)}。"}
        )

    content_coverage = _require_text_list(
        blueprint.content_coverage,
        label="内容覆盖",
    )
    cognitive_complexity = _require_text_list(
        blueprint.cognitive_complexity,
        label="认知复杂度",
    )
    invalid_complexity = sorted(set(cognitive_complexity) - COGNITIVE_COMPLEXITY_VALUES)
    if invalid_complexity:
        raise ValidationError(
            {"cognitive_complexity": f"包含未知认知复杂度：{', '.join(invalid_complexity)}。"}
        )
    allowed_supports = _require_text_list(
        blueprint.allowed_supports,
        label="允许支持",
        min_items=0,
        allow_empty=True,
    )
    if not isinstance(blueprint.scoring_model, dict):
        raise ValidationError({"scoring_model": "评分模型必须是对象。"})
    scoring_model = {
        "approach": _require_text(
            blueprint.scoring_model.get("approach"),
            label="评分方式",
            min_length=4,
        ),
        "decision_rule": _require_text(
            blueprint.scoring_model.get("decision_rule"),
            label="证据解释规则",
            min_length=8,
        ),
    }

    return {
        "school_id": blueprint.school_id,
        "subject_id": blueprint.subject_id,
        "course_id": blueprint.course_id,
        "title": title,
        "intended_use": blueprint.intended_use,
        "task_version": task_version,
        "target_population": target_population,
        "course_goal": course_goal,
        "claims": cleaned_claims,
        "evidence_rules": cleaned_evidence,
        "task_specifications": cleaned_tasks,
        "content_coverage": content_coverage,
        "cognitive_complexity": cognitive_complexity,
        "allowed_supports": allowed_supports,
        "scoring_model": scoring_model,
        "next_formative_action": next_action,
        "validation_status": blueprint.validation_status,
    }


def _contains_forbidden_rubric_term(value) -> str | None:
    serialized = str(value or "")
    return next((term for term in FORBIDDEN_RUBRIC_TERMS if term in serialized), None)


def validate_rubric_for_publish(rubric: RubricDefinition) -> list[dict]:
    _require_text(rubric.title, label="量规名称", min_length=2)
    _require_text(rubric.evaluation_object, label="量规评价对象", min_length=4)
    criteria = rubric.criteria
    if not isinstance(criteria, list) or not criteria:
        raise ValidationError({"criteria": "至少需要一个量规条目。"})
    if len(criteria) > 12:
        raise ValidationError({"criteria": "单个量规最多包含 12 个条目。"})

    cleaned = []
    codes = set()
    allowed_modules = {value for value, _ in RubricModule.choices}
    for index, row in enumerate(criteria, start=1):
        if not isinstance(row, dict):
            raise ValidationError({"criteria": f"第 {index} 个量规条目格式不正确。"})
        code = _require_code(row.get("code"), label=f"第 {index} 个量规条目代码")
        if code in codes:
            raise ValidationError({"criteria": f"量规条目代码 {code} 重复。"})
        codes.add(code)
        module = str(row.get("module") or "")
        if module not in allowed_modules:
            raise ValidationError({"criteria": f"量规条目 {code} 的模块不正确。"})
        evidence_sources = _require_text_list(
            row.get("evidence_sources"),
            label=f"量规条目 {code} 的证据来源",
        )
        allowed_supports = _require_text_list(
            row.get("allowed_supports", []),
            label=f"量规条目 {code} 的允许支持",
            min_items=0,
            allow_empty=True,
        )
        counter_examples = _require_text_list(
            row.get("counter_examples"),
            label=f"量规条目 {code} 的反例",
        )
        anchors = row.get("anchors")
        if not isinstance(anchors, dict):
            raise ValidationError({"criteria": f"量规条目 {code} 缺少五级文字锚点。"})
        cleaned_anchors = {}
        for level in range(1, 6):
            anchor = _require_text(
                anchors.get(str(level), anchors.get(level)),
                label=f"量规条目 {code} 的 {level} 星锚点",
                min_length=8,
            )
            cleaned_anchors[str(level)] = anchor
        if len(set(cleaned_anchors.values())) != 5:
            raise ValidationError({"criteria": f"量规条目 {code} 的五个锚点必须各不相同。"})

        examples = row.get("anchor_examples")
        if not isinstance(examples, list) or len(examples) < 2:
            raise ValidationError({"criteria": f"量规条目 {code} 至少需要两份锚定样例。"})
        cleaned_examples = []
        example_levels = set()
        for example_index, example in enumerate(examples, start=1):
            if not isinstance(example, dict):
                raise ValidationError({"criteria": f"量规条目 {code} 的锚定样例格式不正确。"})
            try:
                level = int(example.get("level"))
            except (TypeError, ValueError) as exc:
                raise ValidationError({"criteria": f"量规条目 {code} 的样例星级不正确。"}) from exc
            if level < 1 or level > 5:
                raise ValidationError({"criteria": f"量规条目 {code} 的样例星级必须为 1-5。"})
            example_levels.add(level)
            cleaned_examples.append(
                {
                    "level": level,
                    "title": _require_text(
                        example.get("title"),
                        label=f"量规条目 {code} 第 {example_index} 个样例名称",
                    ),
                    "evidence_summary": _require_text(
                        example.get("evidence_summary"),
                        label=f"量规条目 {code} 第 {example_index} 个样例说明",
                        min_length=8,
                    ),
                    "artifact_reference": str(example.get("artifact_reference") or "").strip(),
                }
            )
        if len(example_levels) < 2:
            raise ValidationError({"criteria": f"量规条目 {code} 的锚定样例至少覆盖两个星级。"})

        cleaned_row = {
            "code": code,
            "module": module,
            "title": _require_text(row.get("title"), label=f"量规条目 {code} 名称"),
            "evaluation_object": _require_text(
                row.get("evaluation_object"),
                label=f"量规条目 {code} 的评价对象",
                min_length=4,
            ),
            "evidence_sources": evidence_sources,
            "observable_evidence": _require_text(
                row.get("observable_evidence"),
                label=f"量规条目 {code} 的可观察证据",
                min_length=8,
            ),
            "not_assessed_condition": _require_text(
                row.get("not_assessed_condition"),
                label=f"量规条目 {code} 的不可观察条件",
                min_length=8,
            ),
            "allowed_supports": allowed_supports,
            "counter_examples": counter_examples,
            "anchors": cleaned_anchors,
            "anchor_examples": cleaned_examples,
            "next_formative_action": _require_text(
                row.get("next_formative_action"),
                label=f"量规条目 {code} 的下一步形成性行动",
                min_length=8,
            ),
            "sort_order": index - 1,
        }
        forbidden = _contains_forbidden_rubric_term(cleaned_row)
        if forbidden:
            raise ValidationError(
                {"criteria": f"量规条目 {code} 包含“{forbidden}”；该类运行或服从指标不能进入学科量规。"}
            )
        cleaned.append(cleaned_row)
    return cleaned


@transaction.atomic
def publish_blueprint(
    blueprint: AssessmentBlueprint,
    *,
    published_by,
) -> PublishResult:
    blueprint = AssessmentBlueprint.objects.select_for_update().get(pk=blueprint.pk)
    payload = validate_blueprint_for_publish(blueprint)
    content_hash = canonical_content_hash(payload)
    existing = blueprint.versions.filter(content_hash=content_hash).first()
    if existing:
        return PublishResult(existing, False)
    latest = blueprint.versions.order_by("-version_no").first()
    version = AssessmentBlueprintVersion.objects.create(
        source=blueprint,
        school=blueprint.school,
        subject=blueprint.subject,
        course=blueprint.course,
        version_no=(latest.version_no + 1) if latest else 1,
        content_hash=content_hash,
        published_by=published_by,
        **{key: value for key, value in payload.items() if not key.endswith("_id")},
    )
    return PublishResult(version, True)


@transaction.atomic
def publish_rubric(
    rubric: RubricDefinition,
    *,
    published_by,
) -> PublishResult:
    rubric = RubricDefinition.objects.select_for_update().select_related("blueprint").get(pk=rubric.pk)
    cleaned_criteria = validate_rubric_for_publish(rubric)
    blueprint_version = rubric.blueprint.versions.order_by("-version_no").first()
    if blueprint_version is None:
        raise ValidationError("请先发布该量规绑定的任务蓝图。")
    if blueprint_version.intended_use != rubric.intended_use:
        raise ValidationError("量规用途必须与任务蓝图发布版本一致。")
    payload = {
        "school_id": rubric.school_id,
        "subject_id": rubric.subject_id,
        "course_id": rubric.course_id,
        "blueprint_version_hash": blueprint_version.content_hash,
        "title": _require_text(rubric.title, label="量规名称", min_length=2),
        "intended_use": rubric.intended_use,
        "evaluation_object": _require_text(
            rubric.evaluation_object,
            label="量规评价对象",
            min_length=4,
        ),
        "validation_status": rubric.validation_status,
        "criteria": cleaned_criteria,
    }
    content_hash = canonical_content_hash(payload)
    existing = rubric.versions.filter(content_hash=content_hash).first()
    if existing:
        return PublishResult(existing, False)
    latest = rubric.versions.order_by("-version_no").first()
    version = RubricDefinitionVersion.objects.create(
        source=rubric,
        blueprint_version=blueprint_version,
        school=rubric.school,
        subject=rubric.subject,
        course=rubric.course,
        version_no=(latest.version_no + 1) if latest else 1,
        content_hash=content_hash,
        title=payload["title"],
        intended_use=rubric.intended_use,
        evaluation_object=payload["evaluation_object"],
        validation_status=rubric.validation_status,
        published_by=published_by,
    )
    for criterion_data in cleaned_criteria:
        anchors = criterion_data.pop("anchors")
        examples = criterion_data.pop("anchor_examples")
        criterion = RubricCriterionVersion.objects.create(
            rubric_version=version,
            anchor_level_1=anchors["1"],
            anchor_level_2=anchors["2"],
            anchor_level_3=anchors["3"],
            anchor_level_4=anchors["4"],
            anchor_level_5=anchors["5"],
            **criterion_data,
        )
        for sort_order, example in enumerate(examples):
            RubricAnchorExample.objects.create(
                criterion=criterion,
                sort_order=sort_order,
                **example,
            )
    return PublishResult(version, True)
