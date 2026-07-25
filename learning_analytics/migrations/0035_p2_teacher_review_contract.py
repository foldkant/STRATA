import hashlib
import json
import re

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


TARGET_CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def migrate_legacy_review_state(apps, schema_editor):
    EvaluationPlan = apps.get_model("learning_analytics", "EvaluationPlan")
    EvaluationPlanVersion = apps.get_model(
        "learning_analytics", "EvaluationPlanVersion"
    )
    EvaluationStandard = apps.get_model("learning_analytics", "EvaluationStandard")
    EvaluationStandardVersion = apps.get_model(
        "learning_analytics", "EvaluationStandardVersion"
    )
    EvaluationTrialRecord = apps.get_model(
        "learning_analytics", "EvaluationTrialRecord"
    )
    alias = schema_editor.connection.alias

    EvaluationPlan.objects.using(alias).all().update(
        review_status="draft",
        reviewed_by_id=None,
        reviewed_at=None,
        reviewed_content_hash="",
    )
    EvaluationStandard.objects.using(alias).all().update(
        review_status="draft",
        reviewed_by_id=None,
        reviewed_at=None,
        reviewed_content_hash="",
    )
    EvaluationPlanVersion.objects.using(alias).all().update(
        review_status="legacy_unverified",
        reviewed_by_id=None,
        reviewed_at=None,
        reviewed_content_hash="",
    )
    EvaluationStandardVersion.objects.using(alias).all().update(
        review_status="legacy_unverified",
        reviewed_by_id=None,
        reviewed_at=None,
        reviewed_content_hash="",
    )

    for record in EvaluationTrialRecord.objects.using(alias).filter(
        status="completed"
    ).iterator():
        payload = {
            "school_id": record.school_id,
            "standard_version_id": record.standard_version_id,
            "record_type": record.record_type,
            "title": record.title,
            "status": record.status,
            "activity_date": (
                record.activity_date.isoformat() if record.activity_date else None
            ),
            "participant_count": record.participant_count,
            "agreement_rate": (
                str(record.agreement_rate)
                if record.agreement_rate is not None
                else None
            ),
            "conclusion": record.conclusion,
            "summary": record.summary,
            "issues": record.issues,
            "action_items": record.action_items,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        EvaluationTrialRecord.objects.using(alias).filter(pk=record.pk).update(
            completed_by_id=record.updated_by_id,
            completed_at=record.updated_at or record.created_at,
            completion_hash=hashlib.sha256(encoded).hexdigest(),
        )

    for standard in EvaluationStandard.objects.using(alias).only("id", "plan_id"):
        plan_version_id = (
            EvaluationStandardVersion.objects.using(alias)
            .filter(source_id=standard.id)
            .order_by("-version_no", "-id")
            .values_list("plan_version_id", flat=True)
            .first()
        )
        if plan_version_id is None:
            plan_version_id = (
                EvaluationPlanVersion.objects.using(alias)
                .filter(source_id=standard.plan_id)
                .order_by("-version_no", "-id")
                .values_list("id", flat=True)
                .first()
            )
        if plan_version_id is not None:
            EvaluationStandard.objects.using(alias).filter(pk=standard.id).update(
                plan_version_id=plan_version_id
            )


def reverse_review_state(apps, schema_editor):
    EvaluationPlan = apps.get_model("learning_analytics", "EvaluationPlan")
    EvaluationPlanVersion = apps.get_model(
        "learning_analytics", "EvaluationPlanVersion"
    )
    EvaluationStandard = apps.get_model("learning_analytics", "EvaluationStandard")
    EvaluationStandardVersion = apps.get_model(
        "learning_analytics", "EvaluationStandardVersion"
    )
    alias = schema_editor.connection.alias
    EvaluationPlan.objects.using(alias).all().update(review_status="draft")
    EvaluationStandard.objects.using(alias).all().update(review_status="draft")
    EvaluationPlanVersion.objects.using(alias).all().update(review_status="draft")
    EvaluationStandardVersion.objects.using(alias).all().update(review_status="draft")


class Migration(migrations.Migration):
    dependencies = [
        ("learning_analytics", "0034_learningtarget_learningtargetbackfillissue_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationplan",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="evaluationplan",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reviewed_evaluation_plans",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="evaluationplan",
            name="reviewed_content_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="evaluationplanversion",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="evaluationplanversion",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reviewed_evaluation_plan_versions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="evaluationplanversion",
            name="reviewed_content_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="evaluationstandard",
            name="plan_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="draft_evaluation_standards",
                to="learning_analytics.evaluationplanversion",
            ),
        ),
        migrations.AddField(
            model_name="evaluationstandard",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="evaluationstandard",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reviewed_evaluation_standards",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="evaluationstandard",
            name="reviewed_content_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="evaluationstandardversion",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="evaluationstandardversion",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reviewed_evaluation_standard_versions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="evaluationstandardversion",
            name="reviewed_content_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="evaluationtrialrecord",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="evaluationtrialrecord",
            name="completed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="completed_evaluation_trial_records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="evaluationtrialrecord",
            name="completion_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="evaluationplan",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("reviewed", "教师已完成复核"),
                    ("legacy_unverified", "历史版本待复核"),
                ],
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationstandard",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("reviewed", "教师已完成复核"),
                    ("legacy_unverified", "历史版本待复核"),
                ],
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationplanversion",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("reviewed", "教师已完成复核"),
                    ("legacy_unverified", "历史版本待复核"),
                ],
                default="legacy_unverified",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="evaluationstandardversion",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("draft", "编辑中"),
                    ("reviewed", "教师已完成复核"),
                    ("legacy_unverified", "历史版本待复核"),
                ],
                default="legacy_unverified",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="EvaluationTaskLearningActivity",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "task_code",
                    models.CharField(
                        max_length=32,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="代码必须以字母开头，只能包含字母、数字、下划线或连字符。",
                                regex=TARGET_CODE_PATTERN,
                            )
                        ],
                    ),
                ),
                (
                    "activity_code",
                    models.CharField(
                        max_length=32,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="代码必须以字母开头，只能包含字母、数字、下划线或连字符。",
                                regex=TARGET_CODE_PATTERN,
                            )
                        ],
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "plan_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="task_learning_activity_links",
                        to="learning_analytics.evaluationplanversion",
                    ),
                ),
            ],
            options={
                "ordering": ["plan_version_id", "task_code", "sort_order", "id"]
            },
        ),
        migrations.CreateModel(
            name="EvaluationCriterionEvaluationTask",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "task_code",
                    models.CharField(
                        max_length=32,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="代码必须以字母开头，只能包含字母、数字、下划线或连字符。",
                                regex=TARGET_CODE_PATTERN,
                            )
                        ],
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "criterion",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="evaluation_task_links",
                        to="learning_analytics.evaluationcriterionversion",
                    ),
                ),
            ],
            options={"ordering": ["criterion_id", "sort_order", "id"]},
        ),
        migrations.AddIndex(
            model_name="evaluationtasklearningactivity",
            index=models.Index(
                fields=["plan_version", "task_code"], name="la_task_activity_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationtasklearningactivity",
            constraint=models.UniqueConstraint(
                fields=("plan_version", "task_code", "activity_code"),
                name="uniq_task_learning_activity",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationtasklearningactivity",
            constraint=models.UniqueConstraint(
                fields=("plan_version", "task_code", "sort_order"),
                name="uniq_task_learning_activity_order",
            ),
        ),
        migrations.AddIndex(
            model_name="evaluationcriterionevaluationtask",
            index=models.Index(
                fields=["criterion", "task_code"], name="la_criterion_task_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationcriterionevaluationtask",
            constraint=models.UniqueConstraint(
                fields=("criterion", "task_code"),
                name="uniq_criterion_evaluation_task",
            ),
        ),
        migrations.AddConstraint(
            model_name="evaluationcriterionevaluationtask",
            constraint=models.UniqueConstraint(
                fields=("criterion", "sort_order"),
                name="uniq_criterion_evaluation_task_order",
            ),
        ),
        migrations.RunPython(migrate_legacy_review_state, reverse_review_state),
    ]
