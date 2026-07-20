from __future__ import annotations

from collections import Counter, defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from learning.models import StratificationDecision
from learning_analytics.models import (
    ClassCalibrationRun,
    ModelRelease,
    SyntheticDatasetRun,
    SyntheticStudentTruth,
)
from learning_analytics.services.model_packages import publish_model_candidate
TEST_REVIEW_NOTE = "[测试数据验收] 已模拟教师采纳模型建议。"


def _validate_test_run(
    *,
    calibration_run: ClassCalibrationRun,
    actor: User,
    confirmation_key: str,
) -> SyntheticDatasetRun:
    synthetic_run = calibration_run.dataset.synthetic_run
    if synthetic_run is None:
        raise ValidationError("只能为带合成批次标记的测试模型补齐分层。")
    if synthetic_run.status != SyntheticDatasetRun.Status.SUCCEEDED:
        raise ValidationError("测试数据批次尚未成功生成，不能补齐分层。")
    if confirmation_key != synthetic_run.dataset_key:
        raise ValidationError("测试数据批次确认指纹不匹配。")
    if not actor.is_active or actor.role not in {
        User.Role.SUPER_ADMIN,
        User.Role.SCHOOL_ADMIN,
    }:
        raise ValidationError("必须使用有效的超级管理员或学校管理员账户。")
    if (
        actor.role == User.Role.SCHOOL_ADMIN
        and actor.school_id != calibration_run.school_id
    ):
        raise ValidationError("学校管理员不能处理其他学校的测试数据。")
    if calibration_run.status != ClassCalibrationRun.Status.CANDIDATE:
        raise ValidationError("只能处理已通过检查的候选模型。")
    return synthetic_run


def _validate_decisions(
    *, calibration_run: ClassCalibrationRun, synthetic_run: SyntheticDatasetRun
) -> list[int]:
    decisions = list(
        StratificationDecision.objects.filter(calibration_run=calibration_run)
        .select_related("course__teacher")
        .order_by("id")
    )
    if not decisions:
        raise ValidationError("候选模型没有生成学生分层建议。")
    invalid_priorities = [
        item.id
        for item in decisions
        if item.decision_kind != StratificationDecision.DecisionKind.SUPPORT
        or item.support_priority
        not in StratificationDecision.SupportPriority.values
    ]
    if invalid_priorities:
        raise ValidationError("候选模型包含无效或空的学习支持建议。")
    if any(not item.course_id or not item.course.teacher_id for item in decisions):
        raise ValidationError("候选模型缺少用于模拟确认的任课教师。")
    student_ids = [item.student_id for item in decisions]
    truth_ids = set(
        SyntheticStudentTruth.objects.filter(
            synthetic_run=synthetic_run,
            student_id__in=student_ids,
        ).values_list("student_id", flat=True)
    )
    missing_truth = sorted(set(student_ids) - truth_ids)
    if missing_truth:
        raise ValidationError("候选模型包含不属于该测试批次的学生。")
    return [item.id for item in decisions]


def complete_synthetic_stratification(
    *,
    calibration_run: ClassCalibrationRun,
    actor: User,
    confirmation_key: str,
) -> dict:
    """Publish and explicitly adopt one synthetic model run for acceptance testing."""

    synthetic_run = _validate_test_run(
        calibration_run=calibration_run,
        actor=actor,
        confirmation_key=confirmation_key,
    )
    decision_ids = _validate_decisions(
        calibration_run=calibration_run,
        synthetic_run=synthetic_run,
    )
    release = publish_model_candidate(calibration_run=calibration_run, actor=actor)
    if release.status != ModelRelease.Status.ACTIVE:
        raise ValidationError("该测试模型不是当前发布版本，不能写入测试层级。")

    applied = 0
    unchanged = 0
    distribution: dict[str, Counter] = defaultdict(Counter)
    now = timezone.now()
    with transaction.atomic():
        decisions = list(
            StratificationDecision.objects.select_for_update()
            .filter(id__in=decision_ids)
            .select_related("class_group", "course__teacher")
            .order_by("id")
        )
        for decision in decisions:
            if (
                decision.status == StratificationDecision.Status.ACCEPTED
                and decision.review_note == TEST_REVIEW_NOTE
            ):
                unchanged += 1
            else:
                decision.status = StratificationDecision.Status.ACCEPTED
                decision.teacher_selected_layer = ""
                decision.review_note = TEST_REVIEW_NOTE
                decision.reviewed_by = decision.course.teacher
                decision.reviewed_at = now
                decision.save(
                    update_fields=[
                        "status",
                        "teacher_selected_layer",
                        "review_note",
                        "reviewed_by",
                        "reviewed_at",
                    ]
                )
                applied += 1
            distribution[decision.class_group.name][decision.support_priority] += 1

    return {
        "synthetic_run_id": str(synthetic_run.run_id),
        "dataset_key": synthetic_run.dataset_key,
        "school_id": calibration_run.school_id,
        "calibration_run_id": calibration_run.id,
        "release_id": release.id,
        "release_version": release.release_version,
        "student_count": len(decision_ids),
        "applied_count": applied,
        "unchanged_count": unchanged,
        "class_distribution": {
            class_name: {layer: 0 for layer in ("A", "B", "C")}
            for class_name, counts in sorted(distribution.items())
        },
        "support_distribution": {
            class_name: {
                priority: counts.get(priority, 0)
                for priority in StratificationDecision.SupportPriority.values
            }
            for class_name, counts in sorted(distribution.items())
        },
    }
