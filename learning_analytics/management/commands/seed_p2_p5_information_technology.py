from __future__ import annotations

from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import RequestFactory
from django.utils import timezone

from accounts.models import User
from api.analytics.evaluation_serializers import (
    EvaluationPlanWriteSerializer,
    EvaluationStandardWriteSerializer,
)
from api.services import publish_pretest_paper, save_pretest_question
from courses.models import Course, CourseClass
from curriculum_standards.models import (
    CurriculumNodeType,
    CurriculumStandard,
    CurriculumVersionStatus,
    SchoolStage,
)
from curriculum_standards.services import subject_names_equivalent
from learning.models import (
    DiagnosticAdministration,
    DiagnosticAdministrationAssignment,
    PretestPaper,
    PretestQuestion,
)
from learning.services.diagnostic_administrations import (
    create_diagnostic_administration,
    publish_diagnostic_administration,
    replace_diagnostic_assignments,
)
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationPlanVersion,
    EvaluationStandard,
    EvaluationTrialConclusion,
    EvaluationTrialRecord,
    EvaluationTrialStatus,
    EvaluationTrialType,
)
from learning_analytics.services.evaluation import (
    confirm_plan_review,
    confirm_standard_review,
    publish_plan,
    publish_standard,
)
from school.models import School


CONFIRMATION = "SEED-P2-P5-INFORMATION-TECHNOLOGY"
TITLE_PREFIX = "【信息科技示例】"


def _request_for(user):
    request = RequestFactory().post("/internal/p2-p5-seed/")
    request.user = user
    return request


def _curriculum_context(*, course: Course, school_stage: str):
    standards = (
        CurriculumStandard.objects.filter(
            school_stage=school_stage,
            current_version__status=CurriculumVersionStatus.PUBLISHED,
        )
        .select_related("current_version")
        .order_by("-current_version__publication_year", "-current_version_id")
    )
    standard = next(
        (
            item
            for item in standards
            if subject_names_equivalent(
                course.subject.name,
                item.current_version.subject_name_snapshot,
            )
        ),
        None,
    )
    if standard is None:
        raise CommandError("未找到与该课程学科、学段相符的当前已发布课程标准。")
    required_types = {
        CurriculumNodeType.CORE_COMPETENCY,
        CurriculumNodeType.COURSE_OBJECTIVE,
        CurriculumNodeType.COURSE_CONTENT,
        CurriculumNodeType.ACADEMIC_QUALITY,
    }
    nodes = list(
        standard.current_version.nodes.filter(node_type__in=required_types).order_by(
            "sort_order", "id"
        )
    )
    found_types = {node.node_type for node in nodes}
    missing = required_types - found_types
    if missing:
        raise CommandError(
            "当前课程标准尚未形成完整的核心素养—课程目标—课程内容—学业质量内容条目。"
        )
    return standard.current_version, nodes


def _plan_payload(*, course, version, nodes, mode: str) -> dict:
    node_ids = [node.id for node in nodes]
    common = {
        "course": course.id,
        "content_version": f"课程标准 {version.version_label}",
        "target_students": "本课程中正在学习数据表示、数据处理与问题解决的学生",
        "learning_goal": "学生能够依据真实问题需要选择数据表示与处理方法，并说明选择理由。",
        "learning_goals": [
            {
                "code": "IT_DATA_01",
                "title": "依据任务需要表示和处理数据",
                "description": "学生能够分析任务中的数据特点，选择适当的表示或处理方法，并对选择作出有依据的说明。",
                "curriculum_node_ids": node_ids,
            }
        ],
        "evaluation_basis": [
            {
                "code": "IT_EVIDENCE_01",
                "goal_codes": ["IT_DATA_01"],
                "description": "学生提交的作答、操作过程、作品或说明应共同呈现其对数据特点、方法选择与结果解释的理解。",
                "source_types": ["学生作答", "操作记录", "作品材料", "口头或书面说明"],
            }
        ],
        "content_scope": ["数据表示", "数据处理", "方法选择与结果解释"],
        "thinking_requirements": ["apply", "analyze", "evaluate"],
        "support_options": ["任务说明", "数据字典", "操作提示卡"],
        "scoring_rules": {
            "approach": "按评价指标分别判断",
            "decision_rule": "只依据实际形成的评价材料判断；材料缺失、设备问题或未获得机会时标记为暂不评价，不折算为低分。",
        },
        "follow_up_suggestion": "教师依据材料覆盖、不确定性和各指标表现安排补充观察、反馈或下一阶段学习任务。",
        "curriculum_node_ids": node_ids,
    }
    if mode == "test":
        return {
            **common,
            "title": f"{TITLE_PREFIX}信息科技测试式评价方案",
            "learning_activities": [
                {
                    "code": "IT_ACTIVITY_TEST",
                    "title": "数据表示情境分析",
                    "goal_codes": ["IT_DATA_01"],
                    "description": "学生阅读数据问题情境，判断适当的数据表示或处理方法并说明理由。",
                }
            ],
            "evaluation_tasks": [
                {
                    "code": "IT_TASK_TEST",
                    "title": "数据表示情境测试",
                    "goal_codes": ["IT_DATA_01"],
                    "activity_codes": ["IT_ACTIVITY_TEST"],
                    "mode": "test",
                    "evidence_ownership": "individual",
                    "material_types": ["answer", "score"],
                    "weight": 100,
                    "description": "学生独立完成情境题，并通过选择与简要说明呈现对数据表示方法的理解。",
                }
            ],
            "assessment_modes": ["test"],
        }
    if mode == "operation":
        return {
            **common,
            "title": f"{TITLE_PREFIX}信息科技操作式评价方案",
            "learning_activities": [
                {
                    "code": "IT_ACTIVITY_OPERATION",
                    "title": "数据整理与可视化操作",
                    "goal_codes": ["IT_DATA_01"],
                    "description": "学生使用指定工具完成数据整理、表示与结果检查，并保留关键操作过程。",
                }
            ],
            "evaluation_tasks": [
                {
                    "code": "IT_TASK_OPERATION",
                    "title": "数据处理操作任务",
                    "goal_codes": ["IT_DATA_01"],
                    "activity_codes": ["IT_ACTIVITY_OPERATION"],
                    "mode": "operation",
                    "evidence_ownership": "individual",
                    "material_types": ["operation", "observation"],
                    "weight": 100,
                    "description": "学生独立完成数据导入、整理、表示和结果核验，系统或教师保存操作与观察记录。",
                }
            ],
            "assessment_modes": ["operation"],
        }
    return {
        **common,
        "title": f"{TITLE_PREFIX}信息科技项目式评价方案",
        "learning_activities": [
            {
                "code": "IT_ACTIVITY_PROJECT",
                "title": "校园数据问题项目",
                "goal_codes": ["IT_DATA_01"],
                "description": "小组围绕校园数据问题经历方案设计、数据处理、作品形成与展示交流。",
            },
            {
                "code": "IT_ACTIVITY_DEFENSE",
                "title": "个人说明与答辩",
                "goal_codes": ["IT_DATA_01"],
                "description": "每名学生说明本人承担的工作、关键方法选择及对项目结果的理解。",
            },
        ],
        "evaluation_tasks": [
            {
                "code": "IT_TASK_PROJECT_GROUP",
                "title": "小组数据作品",
                "goal_codes": ["IT_DATA_01"],
                "activity_codes": ["IT_ACTIVITY_PROJECT"],
                "mode": "project",
                "evidence_ownership": "group",
                "material_types": ["artifact"],
                "weight": 60,
                "description": "小组提交可追溯的数据作品与项目说明，作为小组共同成果材料。",
            },
            {
                "code": "IT_TASK_PROJECT_INDIVIDUAL",
                "title": "个人方法说明与答辩",
                "goal_codes": ["IT_DATA_01"],
                "activity_codes": ["IT_ACTIVITY_DEFENSE"],
                "mode": "oral_defense",
                "evidence_ownership": "individual",
                "material_types": ["oral_defense", "observation"],
                "weight": 40,
                "description": "学生独立说明关键方法选择、本人贡献和结果解释，形成可归因到个人的评价材料。",
            },
        ],
        "assessment_modes": ["project", "oral_defense"],
    }


def _criterion(*, code, title, task_code, ownership, material_types, target):
    return {
        "code": code,
        "dimension": "subject_practice",
        "title": title,
        "evaluation_target": target,
        "evaluation_sources": ["任务提交材料", "过程记录", "学生说明"],
        "learning_goal_codes": ["IT_DATA_01"],
        "evaluation_task_codes": [task_code],
        "evidence_ownership": ownership,
        "material_types": material_types,
        "expected_performance": "学生能够根据数据特点与任务需要选择适当方法，并使用任务材料说明选择理由和结果。",
        "skip_condition": "未获得该任务机会、设备问题或未形成规定材料时，本指标暂不评价并记录原因。",
        "support_options": ["任务说明", "数据字典", "操作提示卡"],
        "common_problems": ["只呈现结果而没有说明方法选择，不能充分支持本指标判断。"],
        "level_descriptions": {
            "1": "材料显示方法与数据特点明显不匹配，且尚未形成可核验的理由说明。",
            "2": "能够完成部分任务，但方法选择主要依赖模仿，理由与数据特点联系较弱。",
            "3": "方法基本适合主要数据特点，能够说明一项与任务需要有关的选择理由。",
            "4": "方法适合数据和使用情境，能够连贯说明关键处理步骤、选择理由与结果。",
            "5": "能够比较可行方法的差异与限制，作出有依据的选择，并检验结果的合理性。",
        },
        "scoring_examples": [
            {
                "level": 2,
                "title": "完成操作但理由不足",
                "example_description": "学生完成主要步骤，但只能说出照示例操作，未联系数据特点解释方法选择。",
                "file_reference": f"{code}-L2",
            },
            {
                "level": 4,
                "title": "方法、理由与结果相互支持",
                "example_description": "学生能联系数据类型、任务对象和结果用途解释方法，并对处理结果进行核验。",
                "file_reference": f"{code}-L4",
            },
        ],
        "follow_up_suggestion": "根据尚未充分呈现的关键表现安排补充说明、操作修正或新的迁移任务。",
    }


def _standard_payload(plan_version: EvaluationPlanVersion, mode: str) -> dict:
    if mode == "project":
        criteria = [
            _criterion(
                code="IT_PROJECT_GROUP",
                title="小组作品的数据处理质量",
                task_code="IT_TASK_PROJECT_GROUP",
                ownership="group",
                material_types=["artifact"],
                target="小组提交的数据作品与项目说明",
            ),
            _criterion(
                code="IT_PROJECT_INDIVIDUAL",
                title="个人方法理解与说明",
                task_code="IT_TASK_PROJECT_INDIVIDUAL",
                ownership="individual",
                material_types=["oral_defense"],
                target="学生个人的方法说明与答辩材料",
            ),
        ]
    elif mode == "operation":
        criteria = [
            _criterion(
                code="IT_OPERATION",
                title="数据处理操作与核验",
                task_code="IT_TASK_OPERATION",
                ownership="individual",
                material_types=["operation"],
                target="学生个人操作记录与结果核验材料",
            )
        ]
    else:
        criteria = [
            _criterion(
                code="IT_TEST",
                title="数据表示方法判断与说明",
                task_code="IT_TASK_TEST",
                ownership="individual",
                material_types=["answer"],
                target="学生个人测试作答与理由说明",
            )
        ]
    return {
        "plan_version": plan_version.id,
        "title": f"{TITLE_PREFIX}信息科技{ {'test': '测试式', 'operation': '操作式', 'project': '项目式'}[mode] }评价标准",
        "evaluation_target": "与学习目标对应的学生作答、操作、作品及个人说明材料",
        "criteria": criteria,
    }


class Command(BaseCommand):
    help = "生成带明确示例标识的信息科技评价方案；可选生成学习起点诊断，不生成教育效果结论。"

    def add_arguments(self, parser):
        parser.add_argument("--school-code", required=True)
        parser.add_argument("--course-id", type=int, required=True)
        parser.add_argument(
            "--class-group-id",
            dest="class_group_ids",
            action="append",
            type=int,
            required=False,
            help=(
                "只把诊断验收批次指派给明确指定的课程班级；"
                "可重复，且必须显式提供。"
            ),
        )
        parser.add_argument(
            "--school-stage",
            choices=[SchoolStage.COMPULSORY, SchoolStage.SENIOR_HIGH],
            required=True,
        )
        parser.add_argument("--school-admin", required=True)
        parser.add_argument(
            "--publish-diagnostic",
            action="store_true",
            help=(
                "显式发布诊断验收批次；未提供时仅保存为草案。"
            ),
        )
        parser.add_argument(
            "--evaluation-only",
            action="store_true",
            help="只生成教师端的测试式、操作式和项目式评价示例，不建立学习起点诊断批次。",
        )
        parser.add_argument(
            "--allow-non-synthetic",
            action="store_true",
            help="仅与 --evaluation-only 同时使用，允许在开发学校中建立有明确示例标识的数据。",
        )
        parser.add_argument("--confirmation", default="")

    def handle(self, *args, **options):
        if options["confirmation"] != CONFIRMATION:
            raise CommandError(f"必须提供 --confirmation {CONFIRMATION}。")
        school = School.objects.filter(code=options["school_code"]).first()
        if school is None:
            raise CommandError("学校不存在。")
        if not school.is_synthetic and not (
            options["allow_non_synthetic"] and options["evaluation_only"]
        ):
            raise CommandError(
                "验收数据命令只允许在 is_synthetic=True 的隔离学校中运行；"
                "开发学校只允许使用 --evaluation-only --allow-non-synthetic 建立明确标识的评价示例，"
                "禁止向真实班级发布示例诊断。"
            )
        course = (
            Course.objects.select_related("subject", "teacher")
            .filter(pk=options["course_id"], subject__school=school, is_active=True)
            .first()
        )
        if course is None:
            raise CommandError("课程不存在、不属于该学校或已停用。")
        if not subject_names_equivalent(course.subject.name, "信息科技"):
            raise CommandError("该命令当前只允许用于信息科技/信息技术课程。")
        admin = User.objects.filter(
            username=options["school_admin"],
            school=school,
            role=User.Role.SCHOOL_ADMIN,
            is_active=True,
        ).first()
        if admin is None:
            raise CommandError("未找到该校有效的学校管理员账号。")
        version, nodes = _curriculum_context(
            course=course,
            school_stage=options["school_stage"],
        )
        teacher_request = SimpleNamespace(user=course.teacher)
        created_objects: list[str] = []
        diagnostic_target_version = None
        project_standard_version = None

        with transaction.atomic():
            for mode in ("test", "operation", "project"):
                payload = _plan_payload(
                    course=course,
                    version=version,
                    nodes=nodes,
                    mode=mode,
                )
                plan = EvaluationPlan.objects.filter(
                    school=school,
                    course=course,
                    title=payload["title"],
                ).first()
                if plan is None or not plan.versions.exists():
                    serializer = EvaluationPlanWriteSerializer(
                        instance=plan,
                        data=payload,
                        context={"request": teacher_request},
                    )
                    serializer.is_valid(raise_exception=True)
                    plan = serializer.save()
                    confirm_plan_review(
                        plan=plan,
                        reviewed_by=course.teacher,
                    )
                    plan_version = publish_plan(
                        plan,
                        published_by=course.teacher,
                    ).version
                else:
                    plan_version = plan.versions.order_by(
                        "-version_no", "-id"
                    ).first()
                created_objects.append(
                    f"learning_analytics.EvaluationPlan:{plan.pk}"
                )
                if mode == "test":
                    diagnostic_target_version = (
                        plan_version.learning_target_versions.select_related(
                            "target"
                        ).get(code="IT_DATA_01")
                    )

                standard_payload = _standard_payload(plan_version, mode)
                standard = EvaluationStandard.objects.filter(
                    school=school,
                    plan=plan,
                    title=standard_payload["title"],
                ).first()
                if standard is None or not standard.versions.exists():
                    serializer = EvaluationStandardWriteSerializer(
                        instance=standard,
                        data=standard_payload,
                        context={"request": teacher_request},
                    )
                    serializer.is_valid(raise_exception=True)
                    standard = serializer.save()
                    confirm_standard_review(
                        standard=standard,
                        reviewed_by=course.teacher,
                    )
                    publish_standard(standard, published_by=course.teacher)
                if mode == "project":
                    project_standard_version = standard.versions.order_by(
                        "-version_no", "-id"
                    ).first()
                created_objects.append(
                    f"learning_analytics.EvaluationStandard:{standard.pk}"
                )

            if options["evaluation_only"]:
                if project_standard_version is None:
                    raise CommandError("项目式评价标准版本尚未生成。")
                trial, _ = EvaluationTrialRecord.objects.get_or_create(
                    school=school,
                    standard_version=project_standard_version,
                    title=f"{TITLE_PREFIX}项目评价课堂试用计划",
                    defaults={
                        "record_type": EvaluationTrialType.CLASSROOM_TRIAL,
                        "status": EvaluationTrialStatus.PLANNED,
                        "activity_date": timezone.localdate(),
                        "participant_count": 0,
                        "conclusion": EvaluationTrialConclusion.PENDING,
                        "summary": "计划观察学生是否理解任务要求，以及小组作品与个人说明材料是否足以支持评价判断。",
                        "issues": [],
                        "action_items": [
                            "试用后记录材料不足、设备问题和未获得评价机会的情况。",
                            "比较教师对同一作品和个人说明的评分判断是否一致。",
                        ],
                        "created_by": course.teacher,
                        "updated_by": course.teacher,
                    },
                )
                created_objects.append(
                    f"learning_analytics.EvaluationTrialRecord:{trial.pk}"
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"已准备 3 套信息科技评价示例（测试式、操作式、项目式）"
                        f"和 1 条课堂试用计划；"
                        f"课程标准版本：{version.official_title}。"
                    )
                )
                self.stdout.write("这些内容带有“信息科技示例”标识，可由课程教师继续修改。")
                for target in created_objects:
                    self.stdout.write(f"  --target {target}")
                return

            diagnostic_title = f"{TITLE_PREFIX}信息科技学习起点诊断"
            paper = PretestPaper.objects.filter(
                school=school,
                subject=course.subject,
                title=diagnostic_title,
            ).first()
            if paper is None:
                next_version = (
                    PretestPaper.objects.filter(
                        school=school,
                        subject=course.subject,
                        kind=PretestPaper.Kind.LITERACY,
                    ).order_by("-version").values_list("version", flat=True).first()
                    or 0
                ) + 1
                paper = PretestPaper.objects.create(
                    school=school,
                    subject=course.subject,
                    title=diagnostic_title,
                    kind=PretestPaper.Kind.LITERACY,
                    version=next_version,
                    introduction="用于检查学生在数据表示、操作和简短项目任务方面的学习起点；材料不足不记为低水平。",
                    status=PretestPaper.Status.DRAFT,
                    created_by=admin,
                )
            if paper.status == PretestPaper.Status.DRAFT:
                if diagnostic_target_version is None:
                    raise CommandError("信息科技学习目标冻结版本尚未生成。")
                paper.questions.all().delete()
                admin_request = _request_for(admin)
                questions = [
                    {
                        "stem": "面对包含姓名、日期和数量的数据表，哪一种说法最符合按数据特点选择表示方式的要求？",
                        "question_type": "single",
                        "options": [
                            {"label": "A", "text": "先识别字段含义与数据类型，再选择表示方式"},
                            {"label": "B", "text": "所有字段一律按文本处理"},
                            {"label": "C", "text": "只根据表格颜色选择处理方法"},
                        ],
                        "answer": ["A"],
                        "score": 5,
                        "dimension": "数据与编码",
                        "learning_target_code": diagnostic_target_version.code,
                        "learning_target_name": diagnostic_target_version.title,
                        "learning_target_version_id": diagnostic_target_version.id,
                        "material_requirements": ["独立作答"],
                        "sort_order": 10,
                        "is_required": True,
                    },
                    {
                        "stem": "按任务要求完成一组数据的导入、整理和可视化，并提交关键操作步骤与结果截图。",
                        "question_type": "operation",
                        "answer": [],
                        "score": 10,
                        "dimension": "数据处理",
                        "learning_target_code": diagnostic_target_version.code,
                        "learning_target_name": diagnostic_target_version.title,
                        "learning_target_version_id": diagnostic_target_version.id,
                        "material_requirements": ["操作步骤", "结果截图"],
                        "sort_order": 20,
                        "is_required": True,
                    },
                    {
                        "stem": "说明你选择该数据表示方式的理由，并指出它可能存在的一项限制。",
                        "question_type": "text",
                        "answer": [],
                        "score": 5,
                        "dimension": "问题解决",
                        "learning_target_code": diagnostic_target_version.code,
                        "learning_target_name": diagnostic_target_version.title,
                        "learning_target_version_id": diagnostic_target_version.id,
                        "material_requirements": ["书面说明"],
                        "sort_order": 30,
                        "is_required": True,
                    },
                    {
                        "stem": "围绕一个校园数据问题完成简短项目：提出问题、整理少量数据、形成一种表示并解释结果。",
                        "question_type": "short_project",
                        "answer": [],
                        "score": 15,
                        "dimension": "数字化学习与创新",
                        "learning_target_code": diagnostic_target_version.code,
                        "learning_target_name": diagnostic_target_version.title,
                        "learning_target_version_id": diagnostic_target_version.id,
                        "material_requirements": ["项目作品", "个人说明"],
                        "sort_order": 40,
                        "is_required": False,
                    },
                ]
                for question in questions:
                    save_pretest_question(admin_request, paper, question)
                publish_pretest_paper(admin_request, paper)

            paper_version = paper.published_versions.order_by(
                "-version_no", "-id"
            ).first()
            if paper_version is None:
                raise CommandError("学习起点诊断尚未形成已发布版本。")
            course_classes = list(
                CourseClass.objects.filter(course=course)
                .select_related("class_group")
                .order_by("class_group__name", "class_group_id")
            )
            requested_class_group_ids = {
                int(value) for value in (options.get("class_group_ids") or [])
            }
            if requested_class_group_ids:
                course_classes = [
                    item
                    for item in course_classes
                    if item.class_group_id in requested_class_group_ids
                ]
                found_class_group_ids = {
                    item.class_group_id for item in course_classes
                }
                missing_class_group_ids = sorted(
                    requested_class_group_ids - found_class_group_ids
                )
                if missing_class_group_ids:
                    raise CommandError(
                        "指定班级未与该课程关联："
                        + "、".join(str(value) for value in missing_class_group_ids)
                        + "。"
                    )
            if not course_classes:
                raise CommandError("该课程尚未关联班级，不能发布学习起点诊断实施批次。")
            batch_code = f"P2P5-IT-ENTRY-C{course.id}"
            administration = DiagnosticAdministration.objects.filter(
                school=school,
                batch_code=batch_code,
            ).first()
            if administration is None:
                administration = create_diagnostic_administration(
                    school=school,
                    actor=admin,
                    payload={
                        "subject_id": course.subject_id,
                        "course_id": course.id,
                        "paper_version_id": paper_version.id,
                        "purpose": DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC,
                        "batch_code": batch_code,
                        "title": f"{TITLE_PREFIX}信息科技学习起点诊断实施批次",
                    },
                )
            elif (
                administration.course_id != course.id
                or administration.paper_version_id != paper_version.id
                or administration.purpose
                != DiagnosticAdministration.Purpose.ENTRY_DIAGNOSTIC
            ):
                raise CommandError("同名验收批次已存在，但冻结课程、用途或诊断版本不一致。")
            expected_class_group_ids = {
                item.class_group_id for item in course_classes
            }
            if administration.status != DiagnosticAdministration.Status.DRAFT:
                actual_class_group_ids = set(
                    administration.assignments.values_list(
                        "class_group_id", flat=True
                    )
                )
                if actual_class_group_ids != expected_class_group_ids:
                    raise CommandError(
                        "同名验收批次已发布，但冻结班级清单与"
                        "本次明确指定的班级不一致；不可原地覆盖。"
                    )
            if administration.status == DiagnosticAdministration.Status.DRAFT:
                administration = replace_diagnostic_assignments(
                    administration_id=administration.id,
                    school=school,
                    payload={
                        "expected_updated_at": administration.updated_at,
                        "assignments": [
                            {
                                "class_group_id": item.class_group_id,
                                "cohort_role": DiagnosticAdministrationAssignment.CohortRole.UNASSIGNED,
                                "opportunity_status": DiagnosticAdministrationAssignment.OpportunityStatus.OFFERED,
                            }
                            for item in course_classes
                        ],
                    },
                )
                if options["publish_diagnostic"]:
                    administration = publish_diagnostic_administration(
                        administration_id=administration.id,
                        school=school,
                        actor=admin,
                    )
            created_objects.extend(
                [
                    f"learning.PretestPaper:{paper.pk}",
                    f"learning.DiagnosticAdministration:{administration.pk}",
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"已准备 3 套信息科技评价方案/标准、1 套学习起点诊断"
                f"和 1 个精确版本实施批次（{administration.get_status_display()}）；"
                f"课标版本：{version.official_title}。"
            )
        )
        self.stdout.write("建议登记为验收测试数据的非个人根对象：")
        for target in created_objects:
            self.stdout.write(f"  --target {target}")
