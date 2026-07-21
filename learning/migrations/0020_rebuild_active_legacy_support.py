from django.db import migrations


def support_policy(outcome_key):
    if outcome_key == "required_completion_next_7d":
        return {
            "kind": "ratio_higher_is_better",
            "routine_cutoff": 0.8,
            "watch_cutoff": 0.6,
        }
    if outcome_key == "new_overdue_count_next_7d":
        return {
            "kind": "count_lower_is_better",
            "routine_max": 0.5,
            "watch_max": 1.5,
        }
    return {"kind": "unsupported"}


def support_priority(score, policy):
    if policy["kind"] == "ratio_higher_is_better":
        if score >= policy["routine_cutoff"]:
            return "routine"
        if score >= policy["watch_cutoff"]:
            return "watch"
        return "high"
    if policy["kind"] == "count_lower_is_better":
        if score <= policy["routine_max"]:
            return "routine"
        if score <= policy["watch_max"]:
            return "watch"
        return "high"
    return ""


def support_text(priority):
    return {
        "routine": "可安排拓展任务，同时保留共同题用于持续比较。",
        "watch": "保持核心任务，结合薄弱环节安排一次针对性练习。",
        "high": "先提供必要支架和基础任务，完成后再逐步增加难度。",
    }.get(priority, "继续收集学习材料后再安排支持。")


def rebuild_active_legacy_support(apps, schema_editor):
    StratificationDecision = apps.get_model("learning", "StratificationDecision")
    ClassCalibrationRun = apps.get_model("learning_analytics", "ClassCalibrationRun")
    ModelRelease = apps.get_model("learning_analytics", "ModelRelease")

    active_run_ids = ModelRelease.objects.filter(status="active").values_list(
        "calibration_run_id", flat=True
    )
    for run_id in active_run_ids.iterator():
        run = ClassCalibrationRun.objects.filter(pk=run_id).first()
        if run is None or run.decision_purpose != "support":
            continue
        if StratificationDecision.objects.filter(
            calibration_run_id=run_id,
            decision_kind="support",
        ).exists():
            continue
        run_outcome_key = str((run.global_parameters or {}).get("outcome_key") or "")
        legacy_rows = StratificationDecision.objects.filter(
            calibration_run_id=run_id,
            decision_kind="legacy",
            rule_version__startswith="m03-",
        ).order_by("id")
        for legacy in legacy_rows.iterator():
            summary = legacy.learning_summary if isinstance(legacy.learning_summary, dict) else {}
            outcome_key = str(summary.get("outcome_key") or run_outcome_key)
            policy = summary.get("support_policy")
            if not isinstance(policy, dict) or not policy.get("kind"):
                policy = support_policy(outcome_key)
            priority = str(summary.get("support_priority") or "").strip()
            score = summary.get("calibrated_prediction")
            if priority not in {"routine", "watch", "high"}:
                if isinstance(score, (int, float)) and policy.get("kind") != "unsupported":
                    priority = support_priority(float(score), policy)
            if priority not in {"routine", "watch", "high"}:
                continue
            restored_summary = {
                **summary,
                "support_priority": priority,
                "support_policy": policy,
                "restored_from_legacy_decision_id": legacy.id,
                "restored_for_release": True,
            }
            StratificationDecision.objects.get_or_create(
                student_id=legacy.student_id,
                course_id=legacy.course_id,
                window_end=legacy.window_end,
                rule_version=f"release-support-{run_id}-{legacy.id}"[:32],
                defaults={
                    "class_group_id": legacy.class_group_id,
                    "subject_id": legacy.subject_id,
                    "previous_layer": legacy.previous_layer,
                    "suggested_layer": "",
                    "confidence": legacy.confidence,
                    "reasons": legacy.reasons,
                    "missing_data": legacy.missing_data,
                    "learning_summary": restored_summary,
                    "support_suggestion": support_text(priority),
                    "decision_kind": "support",
                    "support_priority": priority,
                    "policy_version": "support-policy-v2",
                    "window_start": legacy.window_start,
                    "calibration_run_id": run_id,
                    "status": "pending",
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0019_restore_active_support_suggestions"),
        ("learning_analytics", "0031_alter_groupingpolicyversion_status_and_more"),
    ]

    operations = [
        migrations.RunPython(
            rebuild_active_legacy_support,
            migrations.RunPython.noop,
        )
    ]
