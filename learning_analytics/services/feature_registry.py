from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.db import transaction

from learning_analytics.feature_models import (
    FeatureDefinition,
    FeatureSetVersion,
    OutcomeDefinition,
    canonical_hash,
)


FEATURE_SET_KEY = "strata_initial_features"
FEATURE_SET_VERSION = "1.0"


def _code_hash(generator_key: str, version: str = "1") -> str:
    return hashlib.sha256(f"{generator_key}:{version}".encode()).hexdigest()


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    group: str
    role: str
    data_type: str
    formula: str
    windows: tuple[str, ...]
    min_n: int
    events: tuple[str, ...]
    uses: tuple[str, ...]
    missing: tuple[str, ...]
    generator: str
    model_input: bool
    description: str = ""
    competing: tuple[str, ...] = ()
    fairness_note: str = ""


COMMON_MISSING = (
    "NO_OPPORTUNITY",
    "NOT_STARTED",
    "IN_PROGRESS",
    "OFFLINE",
    "DATA_ERROR",
    "INSUFFICIENT_N",
    "NOT_APPLICABLE",
)


FEATURE_SPECS = (
    FeatureSpec(
        "prior_due_required_count",
        "既往到期必做任务数",
        "F0",
        "instructional_opportunity",
        "count",
        "窗口内已经到期且未被撤回、豁免或标记不可用的必做学习机会数量。",
        ("7d", "30d"),
        0,
        ("content.released", "content.withdrawn"),
        ("description", "model"),
        COMMON_MISSING,
        "prior_due_required_count",
        True,
        "描述学生实际获得的任务机会，不解释为学生能力。",
    ),
    FeatureSpec(
        "prior_graded_item_count",
        "既往已评分题目数",
        "F0",
        "baseline_state",
        "count",
        "窗口内在分析时间点前已形成最终评分的题目机会数量。",
        ("14d", "30d"),
        0,
        ("item.graded",),
        ("description", "model"),
        COMMON_MISSING,
        "prior_graded_item_count",
        True,
    ),
    FeatureSpec(
        "prior_score_ratio",
        "既往题目得分率",
        "F0",
        "baseline_state",
        "ratio",
        "窗口内首次最终评分原始得分之和除以满分之和。",
        ("14d", "30d"),
        5,
        ("item.graded",),
        ("description", "model"),
        COMMON_MISSING,
        "first_attempt_score_ratio",
        True,
        "只表示当时已评分题目表现，不能跨不可比测试直接解释为能力。",
    ),
    FeatureSpec(
        "opp_completion_rate",
        "必做任务完成率",
        "E1",
        "behavior_evidence",
        "ratio",
        "已提交必做机会数除以已到期且符合条件的必做机会数。",
        ("7d", "30d"),
        3,
        ("content.released", "item.submitted", "task.submitted"),
        ("description", "model"),
        COMMON_MISSING,
        "opp_completion_rate",
        True,
    ),
    FeatureSpec(
        "on_time_submission_rate",
        "按时提交率",
        "E1",
        "behavior_evidence",
        "ratio",
        "截止时间前最终提交的必做任务数除以窗口内已到期必做任务数。",
        ("30d",),
        3,
        ("item.submitted", "task.submitted"),
        ("description", "model"),
        COMMON_MISSING,
        "on_time_submission_rate",
        True,
    ),
    FeatureSpec(
        "active_minutes",
        "有效活动分钟",
        "E1",
        "behavior_evidence",
        "duration",
        "合并前台且空闲不超过 120 秒的相邻心跳区间，单段最多计 120 秒。",
        ("7d", "30d"),
        0,
        ("session.heartbeat",),
        ("description", "model"),
        COMMON_MISSING,
        "active_minutes",
        True,
        "技术活动量，不解释为注意力、努力或认知投入。",
        ("设备共享", "自动锁屏", "心跳中断"),
    ),
    FeatureSpec(
        "active_days_ratio",
        "有效活动天数比例",
        "E1",
        "behavior_evidence",
        "ratio",
        "有效活动至少 5 分钟的日期数除以存在学习机会的日期数。",
        ("7d", "30d"),
        3,
        ("session.heartbeat", "content.released"),
        ("description", "model"),
        COMMON_MISSING,
        "active_days_ratio",
        True,
    ),
    FeatureSpec(
        "resource_completion_rate",
        "资源完成率",
        "E1",
        "behavior_evidence",
        "ratio",
        "达到已登记完成规则的必看资源数除以已投放必看资源数。",
        ("7d", "30d"),
        3,
        ("video.progress", "document.progress"),
        ("description", "model"),
        COMMON_MISSING,
        "resource_completion_rate",
        True,
        "视频按 90% 进度、文档按 90% 页码计算；没有完成规则的资源不以打开替代完成。",
    ),
    FeatureSpec(
        "first_attempt_score_ratio",
        "首次作答得分率",
        "E1",
        "behavior_evidence",
        "ratio",
        "每个题目机会首次尝试最终评分的得分之和除以满分之和。",
        ("14d", "30d"),
        5,
        ("item.submitted", "item.graded"),
        ("description", "model"),
        COMMON_MISSING,
        "first_attempt_score_ratio",
        True,
    ),
    FeatureSpec(
        "first_attempt_accuracy",
        "首次作答正确率",
        "E1",
        "behavior_evidence",
        "ratio",
        "首次作答中有明确正确性判断的正确题数除以对应题数。",
        ("14d", "30d"),
        5,
        ("item.submitted", "item.graded"),
        ("description", "model"),
        COMMON_MISSING,
        "first_attempt_accuracy",
        True,
    ),
    FeatureSpec(
        "retry_gain_ratio",
        "重试得分变化",
        "E2",
        "behavior_evidence",
        "continuous",
        "允许重试题目中后续最终得分率与首次最终得分率之差。",
        ("30d",),
        3,
        ("item.submitted", "item.graded"),
        ("research",),
        COMMON_MISSING,
        "not_validated",
        False,
        "研究候选，重试政策和题目等价性尚未验证。",
    ),
    FeatureSpec(
        "response_time_median_z",
        "作答时长相对位置",
        "E2",
        "behavior_evidence",
        "continuous",
        "按题目版本和交互方式在训练范围内标准化的有效作答时长中位数。",
        ("30d", "unit"),
        5,
        ("item.submitted",),
        ("research",),
        COMMON_MISSING,
        "fold_only",
        False,
        "只能在训练折内拟合，普通快照不预先计算标准分。",
    ),
    FeatureSpec(
        "answer_revision_rate",
        "提交前答案修改比例",
        "E2",
        "behavior_evidence",
        "ratio",
        "提交前发生有效答案修改的题目数除以已提交题目数。",
        ("30d",),
        5,
        ("item.submitted",),
        ("research",),
        COMMON_MISSING,
        "not_collected",
        False,
        "当前事件没有记录提交前修改轨迹。",
    ),
    FeatureSpec(
        "challenge_persistence_rate",
        "挑战任务完成比例",
        "E2",
        "behavior_evidence",
        "ratio",
        "已开始难题中形成提交的题目数比例，难题必须绑定已发布难度版本。",
        ("30d",),
        3,
        ("item.submitted",),
        ("research",),
        COMMON_MISSING,
        "not_validated",
        False,
        "题目难度版本未达到统一使用条件前不计算。",
    ),
    FeatureSpec(
        "help_request_rate",
        "主动求助比例",
        "E2",
        "behavior_evidence",
        "ratio",
        "主动求助次数除以经过验证的可求助挑战片段数。",
        ("30d", "unit"),
        3,
        (),
        ("research",),
        COMMON_MISSING,
        "not_collected",
        False,
        "尚未建立统一求助事件和挑战片段。",
    ),
    FeatureSpec(
        "help_latency_minutes",
        "求助等待分钟",
        "E2",
        "behavior_evidence",
        "duration",
        "可求助挑战片段开始到首次有效求助的分钟数中位数。",
        ("30d", "unit"),
        3,
        (),
        ("research",),
        COMMON_MISSING,
        "not_collected",
        False,
        "尚未建立统一求助事件和挑战片段。",
    ),
    FeatureSpec(
        "reflection_completion_rate",
        "反思提交比例",
        "E2",
        "behavior_evidence",
        "ratio",
        "已提交反思数除以明确要求反思的学习机会数。",
        ("30d",),
        3,
        ("lesson.step.completed",),
        ("research",),
        COMMON_MISSING,
        "not_validated",
        False,
        "反思任务类型与完成规则尚未形成统一版本。",
    ),
    FeatureSpec(
        "evaluation_teacher_mean",
        "教师评价均值",
        "E3",
        "baseline_state",
        "continuous",
        "同一已验证评价标准版本下教师逐项星级的平均值。",
        ("30d",),
        2,
        ("evaluation.rating.submitted",),
        ("research",),
        COMMON_MISSING,
        "validated_evaluation_only",
        False,
        "教师课程评价可用于反馈；未验证为学校或研究用途前不进入模型。",
    ),
    FeatureSpec(
        "self_teacher_gap_abs",
        "自评与师评差异",
        "E3",
        "behavior_evidence",
        "continuous",
        "同一任务、同一评价标准版本下自评与师评逐项绝对差均值。",
        ("30d", "unit"),
        2,
        ("evaluation.rating.submitted",),
        ("research",),
        COMMON_MISSING,
        "validated_evaluation_only",
        False,
        "只用于反思和测量研究，不进入首期风险或层级模型。",
    ),
    FeatureSpec(
        "peer_feedback_quality",
        "同伴反馈质量",
        "E3",
        "behavior_evidence",
        "continuous",
        "使用已验证反馈评价标准对具体性、可执行性和证据性评分。",
        ("30d", "unit"),
        3,
        ("evaluation.rating.submitted",),
        ("research",),
        COMMON_MISSING,
        "validated_evaluation_only",
        False,
        "自动文本评分不能替代人工验证。",
    ),
    FeatureSpec(
        "collab_contribution_rate",
        "协作贡献比例",
        "E3",
        "behavior_evidence",
        "ratio",
        "按已公布角色和贡献机会校正的有效贡献比例。",
        ("30d", "unit"),
        1,
        ("group.document.saved", "group.file.shared"),
        ("research",),
        COMMON_MISSING,
        "validated_collaboration_only",
        False,
        "聊天条数、编辑次数和组内占比不能直接表示贡献质量。",
    ),
    FeatureSpec(
        "intervention_count",
        "教师支持次数",
        "F4",
        "treatment",
        "count",
        "窗口内教师对学生创建的结构化支持事件数量。",
        ("7d", "30d"),
        0,
        ("intervention.created",),
        ("audit",),
        COMMON_MISSING,
        "intervention_count",
        False,
        "只用于教学条件审查，不能据此降低学生层级。",
    ),
    FeatureSpec(
        "post_intervention_change",
        "支持前后变化",
        "F4",
        "post_treatment",
        "continuous",
        "可匹配支持前后同口径结果的描述性变化。",
        ("30d",),
        1,
        ("intervention.created",),
        ("audit", "research"),
        COMMON_MISSING,
        "not_validated",
        False,
        "支持后的变量不能用于预测同一次支持前的决定。",
    ),
    FeatureSpec(
        "offline_opportunity_rate",
        "离线机会比例",
        "F4",
        "data_quality",
        "ratio",
        "离线覆盖的学习机会时长除以全部机会时长。",
        ("7d", "30d"),
        1,
        ("client.offline",),
        ("audit",),
        COMMON_MISSING,
        "not_collected",
        False,
        "当前离线事件尚不能可靠映射到每个学习机会时长。",
    ),
    FeatureSpec(
        "event_quality_flag_rate",
        "异常学习记录比例",
        "F4",
        "data_quality",
        "ratio",
        "被隔离、旧事件未映射或带质量错误的学生事件数除以学生全部事件数。",
        ("7d", "30d"),
        1,
        (),
        ("audit",),
        COMMON_MISSING,
        "event_quality_flag_rate",
        False,
        "只降低数据可信度，不能改变学习支持判断方向。",
    ),
)


@dataclass(frozen=True)
class OutcomeSpec:
    key: str
    label: str
    outcome_type: str
    horizon_days: int
    min_denominator: int
    formula: str
    eligibility: str
    evidence: tuple[str, ...]
    generator: str
    description: str = ""


OUTCOME_SPECS = (
    OutcomeSpec(
        "required_completion_next_7d",
        "随后 7 日必做任务完成率",
        "ratio",
        7,
        3,
        "分析时间点后 7 日内已提交必做机会数除以已到期且符合条件的必做机会数。",
        "至少 3 个有效已到期机会；撤回、豁免和不可用机会不进入分母。",
        ("content.released", "item.submitted", "task.submitted"),
        "required_completion_next_7d",
    ),
    OutcomeSpec(
        "new_overdue_count_next_7d",
        "随后 7 日新增逾期任务数",
        "count",
        7,
        1,
        "分析时间点后 7 日内到期、但截止前没有提交的有效必做机会数量。",
        "至少 1 个有截止时间的有效必做机会。",
        ("content.released", "item.submitted", "task.submitted"),
        "new_overdue_count_next_7d",
    ),
)


def _feature_defaults(spec: FeatureSpec) -> dict:
    return {
        "label": spec.label,
        "description": spec.description,
        "evidence_group": spec.group,
        "causal_role": spec.role,
        "data_type": spec.data_type,
        "formula": spec.formula,
        "windows": list(spec.windows),
        "min_n": spec.min_n,
        "allowed_events": list(spec.events),
        "allowed_uses": list(spec.uses),
        "missing_codes": list(spec.missing),
        "competing_explanations": list(spec.competing),
        "fairness_note": spec.fairness_note,
        "model_input_allowed": spec.model_input,
        "generator_key": spec.generator,
        "code_hash": _code_hash(spec.generator),
        "status": FeatureDefinition.Status.ACTIVE,
    }


def _outcome_defaults(spec: OutcomeSpec) -> dict:
    return {
        "label": spec.label,
        "description": spec.description,
        "outcome_type": spec.outcome_type,
        "horizon_days": spec.horizon_days,
        "min_denominator": spec.min_denominator,
        "formula": spec.formula,
        "eligibility_rule": spec.eligibility,
        "allowed_evidence": list(spec.evidence),
        "missing_codes": list(COMMON_MISSING),
        "generator_key": spec.generator,
        "code_hash": _code_hash(spec.generator),
        "status": OutcomeDefinition.Status.ACTIVE,
    }


@transaction.atomic
def sync_feature_and_outcome_definitions() -> dict:
    features = []
    for spec in FEATURE_SPECS:
        defaults = _feature_defaults(spec)
        definition = FeatureDefinition.objects.filter(
            feature_key=spec.key,
            version="1.0",
        ).first()
        if definition is None:
            definition = FeatureDefinition.objects.create(
                feature_key=spec.key,
                version="1.0",
                **defaults,
            )
        else:
            expected = FeatureDefinition(
                feature_key=spec.key,
                version="1.0",
                **defaults,
            )
            if definition.definition_hash != canonical_hash(
                expected.semantic_definition()
            ):
                raise RuntimeError(
                    f"特征定义 {spec.key}@1.0 与代码不一致，请登记新版本。"
                )
        features.append(definition)

    manifest = [
        {
            "feature_key": item.feature_key,
            "version": item.version,
            "definition_hash": item.definition_hash,
            "windows": item.windows,
            "evidence_group": item.evidence_group,
            "model_input_allowed": item.model_input_allowed,
        }
        for item in features
    ]
    feature_set = FeatureSetVersion.objects.filter(
        set_key=FEATURE_SET_KEY,
        version=FEATURE_SET_VERSION,
    ).first()
    if feature_set is None:
        feature_set = FeatureSetVersion.objects.create(
            set_key=FEATURE_SET_KEY,
            version=FEATURE_SET_VERSION,
            label="首期学习分析特征",
            definition_manifest=manifest,
            allowed_views=[
                "operational_available",
                "reconstructed_complete",
            ],
            status=FeatureSetVersion.Status.ACTIVE,
        )
    elif feature_set.definition_manifest != manifest:
        raise RuntimeError("首期特征集清单与代码不一致，请登记新版本。")

    outcomes = []
    for spec in OUTCOME_SPECS:
        defaults = _outcome_defaults(spec)
        definition = OutcomeDefinition.objects.filter(
            outcome_key=spec.key,
            version="1.0",
        ).first()
        if definition is None:
            definition = OutcomeDefinition.objects.create(
                outcome_key=spec.key,
                version="1.0",
                **defaults,
            )
        else:
            expected = OutcomeDefinition(
                outcome_key=spec.key,
                version="1.0",
                **defaults,
            )
            if definition.definition_hash != canonical_hash(
                expected.semantic_definition()
            ):
                raise RuntimeError(
                    f"未来结果定义 {spec.key}@1.0 与代码不一致，请登记新版本。"
                )
        outcomes.append(definition)
    return {
        "feature_count": len(features),
        "feature_set": feature_set,
        "outcome_count": len(outcomes),
    }
