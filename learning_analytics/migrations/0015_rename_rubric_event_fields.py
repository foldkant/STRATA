from django.db import migrations, models


def _replace_text(value):
    return (
        str(value or "")
        .replace("rubric.rating.submitted", "evaluation.rating.submitted")
        .replace("evaluation_rubric", "evaluation_standard")
        .replace("classroom-rubric", "classroom-evaluation")
        .replace("course-rubric", "course-evaluation")
        .replace("classroom_rubric", "classroom_evaluation")
        .replace("course_rubric", "course_evaluation")
    )


def _replace_payload(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if "rubric_version" in result and "evaluation_version" not in result:
        result["evaluation_version"] = result.pop("rubric_version")
    if "action" in result:
        result["action"] = _replace_text(result["action"])
    return result


def rename_evaluation_event_data(apps, schema_editor):
    EventSchemaDefinition = apps.get_model(
        "learning_analytics", "EventSchemaDefinition"
    )
    LearningEventV2 = apps.get_model("learning_analytics", "LearningEventV2")
    LearningOpportunity = apps.get_model(
        "learning_analytics", "LearningOpportunity"
    )
    AssessmentResultFact = apps.get_model(
        "learning_analytics", "AssessmentResultFact"
    )
    LearningEvent = apps.get_model("learning", "LearningEvent")

    EventSchemaDefinition.objects.filter(
        event_name="rubric.rating.submitted"
    ).update(
        event_name="evaluation.rating.submitted",
        description="学生或教师按已发布评价标准提交逐项五星评价。",
    )

    for event in LearningEventV2.objects.all().iterator():
        updates = {}
        renamed_event = _replace_text(event.event_name)
        renamed_object_type = _replace_text(event.object_type)
        renamed_object_id = _replace_text(event.object_id)
        renamed_payload = _replace_payload(event.payload)
        if renamed_event != event.event_name:
            updates["event_name"] = renamed_event
        if renamed_object_type != event.object_type:
            updates["object_type"] = renamed_object_type
        if renamed_object_id != event.object_id:
            updates["object_id"] = renamed_object_id
        if renamed_payload != event.payload:
            updates["payload"] = renamed_payload
        if updates:
            LearningEventV2.objects.filter(pk=event.pk).update(**updates)

    for opportunity in LearningOpportunity.objects.all().iterator():
        updates = {}
        if opportunity.content_type == "rubric":
            updates["content_type"] = "evaluation"
        renamed_object_id = _replace_text(opportunity.object_id)
        if renamed_object_id != opportunity.object_id:
            updates["object_id"] = renamed_object_id
        if updates:
            LearningOpportunity.objects.filter(pk=opportunity.pk).update(**updates)

    AssessmentResultFact.objects.filter(grader_type="rubric").update(
        grader_type="evaluation"
    )

    for event in LearningEvent.objects.all().iterator():
        metadata = _replace_payload(event.metadata)
        object_type = _replace_text(event.object_type)
        object_id = _replace_text(event.object_id)
        updates = {}
        if metadata != event.metadata:
            updates["metadata"] = metadata
        if object_type != event.object_type:
            updates["object_type"] = object_type
        if object_id != event.object_id:
            updates["object_id"] = object_id
        if updates:
            LearningEvent.objects.filter(pk=event.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0008_lesson_step_attempts_and_attachment_versions"),
        ("learning_analytics", "0014_rename_learning_an_school__1a117e_idx_learning_an_school__668f4d_idx_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="learningeventv2",
            old_name="rubric_version",
            new_name="evaluation_version",
        ),
        migrations.AlterField(
            model_name="assessmentresultfact",
            name="grader_type",
            field=models.CharField(
                choices=[
                    ("automatic", "自动评分"),
                    ("teacher", "教师评分"),
                    ("evaluation", "评价标准评分"),
                ],
                max_length=16,
            ),
        ),
        migrations.RunPython(rename_evaluation_event_data, migrations.RunPython.noop),
    ]
