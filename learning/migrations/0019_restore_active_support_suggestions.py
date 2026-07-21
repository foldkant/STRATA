from django.db import migrations


def restore_active_support_suggestions(apps, schema_editor):
    StratificationDecision = apps.get_model("learning", "StratificationDecision")
    ModelRelease = apps.get_model("learning_analytics", "ModelRelease")

    active_run_ids = ModelRelease.objects.filter(status="active").values_list(
        "calibration_run_id", flat=True
    )
    for run_id in active_run_ids.iterator():
        if StratificationDecision.objects.filter(
            calibration_run_id=run_id,
            decision_kind="support",
        ).exists():
            continue
        legacy_rows = StratificationDecision.objects.filter(
            calibration_run_id=run_id,
            decision_kind="legacy",
            rule_version__startswith="m03-",
        ).order_by("id")
        for legacy in legacy_rows.iterator():
            summary = (
                legacy.learning_summary
                if isinstance(legacy.learning_summary, dict)
                else {}
            )
            priority = str(summary.get("support_priority") or "").strip()
            if priority not in {"routine", "watch", "high"}:
                continue
            restored_summary = {
                **summary,
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
                    "support_suggestion": legacy.support_suggestion,
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
        ("learning", "0018_stratificationdecision_review_reason_code"),
        ("learning_analytics", "0031_alter_groupingpolicyversion_status_and_more"),
    ]

    operations = [
        migrations.RunPython(
            restore_active_support_suggestions,
            migrations.RunPython.noop,
        )
    ]
