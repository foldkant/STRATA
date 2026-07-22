from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from courses.models import (
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomSession,
)
from learning_analytics.evaluation_models import (
    ClassroomEvaluationStandardUse,
    EvaluationDimension,
    EvaluationPlan,
    EvaluationReviewStatus,
    EvaluationScope,
    EvaluationStandard,
)
from learning_analytics.services.evaluation import (
    validate_plan_for_publish,
    validate_standard_for_publish,
)


DELETE_CONFIRMATION = "DELETE_LEGACY_EVALUATION_DATA"


@dataclass(frozen=True)
class RoleSpec:
    key: str
    label: str
    dimension_by_title: dict[str, str]
    sources: list[str]


ROLE_SPECS = (
    RoleSpec(
        key="self",
        label="自评",
        dimension_by_title={
            "个人投入": EvaluationDimension.SELF_MANAGEMENT,
            "知识理解": EvaluationDimension.SUBJECT_PRACTICE,
            "任务完成": EvaluationDimension.TASK_QUALITY,
            "反思改进": EvaluationDimension.LEARNING_METHOD,
        },
        sources=["学生自评", "任务作答或作品", "学习反思"],
    ),
    RoleSpec(
        key="peer",
        label="互评",
        dimension_by_title={
            "团队协作": EvaluationDimension.COLLABORATION,
            "个人贡献": EvaluationDimension.RESPONSIBILITY,
            "沟通支持": EvaluationDimension.COLLABORATION,
        },
        sources=["同伴互评", "小组任务过程", "协作成果"],
    ),
    RoleSpec(
        key="teacher",
        label="师评",
        dimension_by_title={
            "任务达成": EvaluationDimension.TASK_QUALITY,
            "学习过程": EvaluationDimension.LEARNING_METHOD,
            "作品质量": EvaluationDimension.SUBJECT_PRACTICE,
            "课堂表现": EvaluationDimension.RESPONSIBILITY,
        },
        sources=["教师观察", "任务作答或作品", "课堂过程记录"],
    ),
)


def _text(value, fallback: str) -> str:
    cleaned = str(value or "").strip()
    return cleaned or fallback


def _legacy_rows(config: ClassroomEvaluationConfig, key: str) -> list[dict]:
    value = getattr(config, f"{key}_criteria", [])
    return value if isinstance(value, list) else []


def _level_descriptions(*, title: str, expectation: str) -> dict[str, str]:
    return {
        "1": f"尚未形成“{title}”所要求的表现，即使在持续帮助下也缺少可核验的任务证据。",
        "2": f"在较多帮助下能够初步体现“{title}”，但表现不稳定，任务证据仍不完整。",
        "3": f"在适当提示下基本达到“{title}”要求，能够提供支持判断的主要任务证据。",
        "4": f"能够独立、稳定地达到“{title}”要求，并用清楚的任务证据说明自己的表现。",
        "5": f"能够高质量达到“{title}”要求，主动解释、迁移或改进做法，并形成充分证据。{expectation}",
    }


def _criterion(role: RoleSpec, row: dict, index: int) -> dict:
    title = _text(row.get("title"), f"{role.label}指标 {index}")
    description = _text(
        row.get("description"),
        f"结合本次学习任务的作答、作品和过程材料，判断学生在“{title}”方面的具体表现。",
    )
    dimension = role.dimension_by_title.get(title, EvaluationDimension.TASK_QUALITY)
    expectation = f"学生能够结合具体任务材料体现“{title}”：{description}"
    return {
        "code": f"{role.key}_{index:02d}",
        "dimension": dimension,
        "title": f"{title}（{role.label}）",
        "evaluation_target": f"学生在本次任务中的{title}表现",
        "evaluation_sources": role.sources,
        "expected_performance": expectation,
        "skip_condition": "本次任务未提供相关观察机会，或缺少可核验的作答、作品和过程材料时暂不评价。",
        "support_options": [
            "允许查看任务要求和评价说明",
            "允许教师提供必要的过程提示",
        ],
        "common_problems": [
            "缺少能够支持该项判断的具体材料。",
            "只依据一次表现，未结合任务过程进行判断。",
        ],
        "level_descriptions": _level_descriptions(
            title=title,
            expectation=description,
        ),
        "scoring_examples": [
            {
                "level": 2,
                "title": f"{title}证据不足",
                "example_description": "能够在帮助下完成部分要求，但现有作答、作品或过程记录不足以支持稳定判断。",
                "file_reference": "",
            },
            {
                "level": 4,
                "title": f"{title}表现稳定",
                "example_description": "能够独立完成主要要求，并通过作答、作品或过程记录提供清楚且一致的证据。",
                "file_reference": "",
            },
        ],
        "follow_up_suggestion": f"根据“{title}”的具体证据提供针对性反馈，并在后续相似任务中继续观察和复核。",
    }


def _build_criteria(config: ClassroomEvaluationConfig) -> list[dict]:
    criteria = []
    for role in ROLE_SPECS:
        for index, row in enumerate(_legacy_rows(config, role.key), start=1):
            if not isinstance(row, dict):
                continue
            criteria.append(_criterion(role, row, index))
    if not criteria:
        raise CommandError(f"旧评价配置 {config.pk} 没有可迁移的评价指标。")
    if len(criteria) > 12:
        raise CommandError(
            f"旧评价配置 {config.pk} 有 {len(criteria)} 个指标，超过新版单个标准 12 项上限。"
        )
    return criteria


def _plan_defaults(config: ClassroomEvaluationConfig, criteria: list[dict]) -> dict:
    course = config.course
    titles = [item["title"] for item in criteria]
    return {
        "school": course.subject.school,
        "subject": course.subject,
        "course": course,
        "title": f"{course.title}过程性评价方案（迁移草稿）",
        "scope": EvaluationScope.COURSE,
        "content_version": f"legacy-evaluation-config-{config.pk}-v1",
        "target_students": "本课程参与相应学习任务的学生",
        "learning_goal": "通过任务作答、作品和学习过程证据，形成可解释的过程性评价并支持后续教学改进。",
        "learning_goals": [
            {
                "code": "goal_01",
                "title": "完成课程任务并改进学习过程",
                "description": "学生能够结合任务要求完成作答或作品，并根据自评、互评和教师反馈持续改进学习过程。",
            }
        ],
        "evaluation_basis": [
            {
                "code": "basis_01",
                "goal_codes": ["goal_01"],
                "description": "依据学生在具体任务中的作答、作品、学习过程记录以及自评、互评和师评材料进行判断。",
                "source_types": ["任务作答", "学生作品", "学习过程记录", "自评互评师评"],
            }
        ],
        "learning_tasks": [
            {
                "code": "task_01",
                "title": "课程学习任务",
                "basis_codes": ["basis_01"],
                "description": "在教师选定的课程任务或课堂环节中完成作答、作品和必要的过程记录，并参与相应评价。",
            }
        ],
        "content_scope": titles,
        "thinking_requirements": ["understand", "apply", "analyze", "evaluate"],
        "support_options": ["查看任务要求和评价说明", "获得必要的过程提示", "根据反馈修改和补充作品"],
        "scoring_rules": {
            "approach": "分析性五级评价",
            "decision_rule": "每个指标依据本次任务的可核验材料分别评价为 1-5 星；证据不足时选择暂不评价，不计入平均星级。",
        },
        "follow_up_suggestion": "教师根据各指标的材料覆盖和具体表现提供反馈，并在后续相似任务中继续观察、复核和调整教学支持。",
        "review_status": EvaluationReviewStatus.DRAFT,
        "created_by": course.teacher,
        "updated_by": course.teacher,
    }


def _standard_defaults(
    config: ClassroomEvaluationConfig,
    plan: EvaluationPlan,
    criteria: list[dict],
) -> dict:
    course = config.course
    return {
        "school": course.subject.school,
        "subject": course.subject,
        "course": course,
        "plan": plan,
        "title": f"{course.title}过程性评价标准（迁移草稿）",
        "scope": EvaluationScope.COURSE,
        "evaluation_target": "学生在具体课程任务中的学习成果、学习方法、反思改进、协作贡献和学科实践表现",
        "criteria": criteria,
        "review_status": EvaluationReviewStatus.DRAFT,
        "created_by": course.teacher,
        "updated_by": course.teacher,
    }


class Command(BaseCommand):
    help = "将旧课程评价配置迁移为新版可发布草稿，并可在显式确认后清理旧记录。"

    def add_arguments(self, parser):
        parser.add_argument("--teacher", help="仅迁移指定教师用户名。")
        parser.add_argument("--course-id", type=int, help="仅迁移指定课程。")
        parser.add_argument("--delete-legacy", action="store_true", help="迁移成功后删除旧配置、版本和未绑定提交。")
        parser.add_argument("--confirm", default="", help=f"删除旧数据时必须填写 {DELETE_CONFIRMATION}。")
        parser.add_argument("--dry-run", action="store_true", help="执行全部验证后回滚事务。")

    def handle(self, *args, **options):
        if options["delete_legacy"] and options["confirm"] != DELETE_CONFIRMATION:
            raise CommandError(f"删除旧数据必须使用 --confirm {DELETE_CONFIRMATION}。")

        queryset = ClassroomEvaluationConfig.objects.select_related(
            "course__teacher",
            "course__subject__school",
        ).order_by("id")
        if options.get("teacher"):
            queryset = queryset.filter(course__teacher__username=options["teacher"])
        if options.get("course_id"):
            queryset = queryset.filter(course_id=options["course_id"])
        configs = list(queryset)
        if not configs:
            self.stdout.write("没有符合条件的旧评价配置。")
            return

        result = {
            "configs": 0,
            "plans_created": 0,
            "standards_created": 0,
            "legacy_submissions_deleted": 0,
            "legacy_versions_deleted": 0,
            "legacy_configs_deleted": 0,
        }
        with transaction.atomic():
            for config in configs:
                criteria = _build_criteria(config)
                marker = f"legacy-evaluation-config-{config.pk}-v1"
                plan = EvaluationPlan.objects.filter(
                    course=config.course,
                    content_version=marker,
                ).first()
                if plan is None:
                    plan = EvaluationPlan.objects.create(**_plan_defaults(config, criteria))
                    result["plans_created"] += 1
                standard = EvaluationStandard.objects.filter(plan=plan).first()
                if standard is None:
                    standard = EvaluationStandard.objects.create(
                        **_standard_defaults(config, plan, criteria)
                    )
                    result["standards_created"] += 1

                validate_plan_for_publish(plan)
                validate_standard_for_publish(standard)
                result["configs"] += 1

                if options["delete_legacy"]:
                    versions = ClassroomEvaluationConfigVersion.objects.filter(
                        course=config.course
                    )
                    version_ids = list(versions.values_list("id", flat=True))
                    ClassroomSession.objects.filter(
                        evaluation_config_version_id__in=version_ids
                    ).update(evaluation_config_version=None)
                    ClassroomEvaluationStandardUse.objects.filter(
                        evaluation_config_version_id__in=version_ids
                    ).update(
                        evaluation_config_version=None,
                        legacy_compatible=False,
                    )
                    ClassroomEvaluationSubmission.objects.filter(
                        evaluation_version_id__in=version_ids,
                        standard_use__isnull=False,
                    ).update(
                        evaluation_version=None,
                        legacy_compatible=False,
                    )
                    legacy_submissions = ClassroomEvaluationSubmission.objects.filter(
                        evaluation_version_id__in=version_ids,
                        standard_use__isnull=True,
                    )
                    result["legacy_submissions_deleted"] += legacy_submissions.count()
                    legacy_submissions.delete()
                    result["legacy_versions_deleted"] += versions.count()
                    versions.delete()
                    ClassroomEvaluationConfig.objects.filter(pk=config.pk).delete()
                    result["legacy_configs_deleted"] += 1

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "DRY-RUN" if options["dry_run"] else "DONE"
        self.stdout.write(self.style.SUCCESS(f"[{mode}] {result}"))
