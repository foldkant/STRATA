from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from courses.models import Course
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
)
from curriculum_standards.services import (
    replace_plan_curriculum_references,
    subject_names_equivalent,
)
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationScope,
    EvaluationReviewStatus,
    EvaluationStandard,
)
from learning_analytics.services.evaluation import (
    confirm_plan_review,
    confirm_standard_review,
    publish_plan,
    publish_standard,
)


PLAN_TITLE = "数据表达与解释试点评价方案"
STANDARD_TITLE = "数据表达与解释评价标准"

REQUIRED_CURRICULUM_NODE_TYPES = {
    CurriculumNodeType.CORE_COMPETENCY,
    CurriculumNodeType.COURSE_OBJECTIVE,
    CurriculumNodeType.COURSE_CONTENT,
    CurriculumNodeType.ACADEMIC_QUALITY,
}


def curriculum_context(*, course: Course, version_id: int | None = None):
    versions = CurriculumStandardVersion.objects.filter(
        status=CurriculumVersionStatus.PUBLISHED,
        source__document_type=CurriculumDocumentType.SUBJECT_STANDARD,
        source__is_active=True,
    ).select_related("source")
    if version_id is not None:
        versions = versions.filter(pk=version_id)
    versions = list(versions.order_by("-publication_year", "-id"))
    versions.sort(
        key=lambda item: item.source.current_version_id == item.id,
        reverse=True,
    )
    for version in versions:
        if not subject_names_equivalent(
            course.subject.name,
            version.subject_name_snapshot,
        ):
            continue
        nodes = list(
            version.nodes.filter(node_type__in=REQUIRED_CURRICULUM_NODE_TYPES)
            .order_by("sort_order", "id")
        )
        if {node.node_type for node in nodes} == REQUIRED_CURRICULUM_NODE_TYPES:
            return version, nodes
    requested = f" ID={version_id}" if version_id is not None else ""
    raise CommandError(
        f"未找到与课程学科匹配且包含四类完整依据的已发布课程标准版本{requested}。"
    )


def criterion(
    *,
    code: str,
    dimension: str,
    title: str,
    evaluation_target: str,
    evaluation_sources: list[str],
    learning_goal_codes: list[str],
    evaluation_task_codes: list[str],
    evidence_ownership: str,
    material_types: list[str],
    expected_performance: str,
    skip_condition: str,
    support_options: list[str],
    common_problems: list[str],
    level_descriptions: list[str],
    examples: list[dict],
    follow_up_suggestion: str,
) -> dict:
    return {
        "code": code,
        "dimension": dimension,
        "title": title,
        "evaluation_target": evaluation_target,
        "evaluation_sources": evaluation_sources,
        "learning_goal_codes": learning_goal_codes,
        "evaluation_task_codes": evaluation_task_codes,
        "evidence_ownership": evidence_ownership,
        "material_types": material_types,
        "expected_performance": expected_performance,
        "skip_condition": skip_condition,
        "support_options": support_options,
        "common_problems": common_problems,
        "level_descriptions": {str(index): value for index, value in enumerate(level_descriptions, start=1)},
        "scoring_examples": examples,
        "follow_up_suggestion": follow_up_suggestion,
    }


def pilot_criteria() -> list[dict]:
    return [
        criterion(
            code="P1",
            dimension="task_quality",
            title="成果准确性与可读性",
            evaluation_target="学生提交的数据可视化作品及配套说明",
            evaluation_sources=["最终可视化作品", "作品说明文本"],
            learning_goal_codes=["C1", "C2"],
            evaluation_task_codes=["T1"],
            evidence_ownership="individual",
            material_types=["artifact"],
            expected_performance="作品中的数据、比例、标签和视觉编码保持一致，并能让目标读者准确读取主要信息。",
            skip_condition="未提供可打开的最终作品，或作品不包含可检查的数据表达时记录 暂不评价。",
            support_options=["教师提供的数据字典", "图表类型参考表"],
            common_problems=["版面美观但数据映射错误的作品不能被判断为高质量成果。"],
            level_descriptions=[
                "作品存在关键数据错误或编码冲突，目标读者无法可靠读取主要信息。",
                "作品能呈现部分信息，但标签、比例或编码仍有多处影响理解的问题。",
                "作品主要数据与编码正确，目标读者能够读取核心信息，但细节表达仍可改进。",
                "作品数据准确、编码一致、标注清楚，能够有效支持目标读者理解主要结论。",
                "作品在准确清晰基础上进一步优化信息层次，并能处理例外值与潜在误读风险。",
            ],
            examples=[
                {
                    "level": 2,
                    "title": "标签不完整样例",
                    "example_description": "图形能够显示趋势，但坐标含义和单位缺失，读者需要猜测数据含义。",
                    "file_reference": "SIM-P1-L2",
                },
                {
                    "level": 4,
                    "title": "准确清晰样例",
                    "example_description": "数据值、单位、图例和视觉编码一致，主要结论可以被直接读取。",
                    "file_reference": "SIM-P1-L4",
                },
            ],
            follow_up_suggestion="让学生先定位一个最可能造成误读的表达细节，再依据目标读者需求完成一次定向修订。",
        ),
        criterion(
            code="S1",
            dimension="learning_method",
            title="表示策略选择与论证",
            evaluation_target="图表类型、视觉编码选择及其书面解释",
            evaluation_sources=["设计说明", "方案比较记录", "最终作品"],
            learning_goal_codes=["C2"],
            evaluation_task_codes=["T1"],
            evidence_ownership="individual",
            material_types=["artifact"],
            expected_performance="学生能够把数据类型、表达目的和目标读者联系起来，解释所选方案并比较合理替代方案。",
            skip_condition="只有最终作品而没有任何策略说明或可追问解释时记录 暂不评价。",
            support_options=["图表类型参考表", "教师提出的澄清问题"],
            common_problems=["仅说明自己喜欢某种图表，不构成基于数据和目的的策略论证。"],
            level_descriptions=[
                "方案选择与数据类型或表达目的冲突，且无法给出相关理由。",
                "方案基本可用，但理由主要来自个人偏好，未连接数据特点与读者需求。",
                "方案适合主要数据特点，并能说明一个与表达目的相关的选择理由。",
                "方案同时考虑数据特点、表达目的和读者需求，并能比较一个合理替代方案。",
                "方案论证系统评估多个替代方案的收益与限制，并根据约束作出可辩护的选择。",
            ],
            examples=[
                {
                    "level": 2,
                    "title": "偏好式说明样例",
                    "example_description": "学生说明选择折线图是因为看起来更好，但没有讨论变量类型和表达目的。",
                    "file_reference": "SIM-S1-L2",
                },
                {
                    "level": 5,
                    "title": "权衡式论证样例",
                    "example_description": "学生比较折线图与柱状图的解释优势，并结合时间连续性和读者任务作出选择。",
                    "file_reference": "SIM-S1-L5",
                },
            ],
            follow_up_suggestion="要求学生为当前方案补充一个替代方案，并用同一组数据说明两种方案各自可能造成的理解差异。",
        ),
        criterion(
            code="R1",
            dimension="self_management",
            title="检查、反馈与修订",
            evaluation_target="初稿、检查记录、反馈回应和修订版本之间的变化",
            evaluation_sources=["版本记录", "检查清单", "反馈回应说明"],
            learning_goal_codes=["C3"],
            evaluation_task_codes=["T2"],
            evidence_ownership="individual",
            material_types=["artifact", "observation"],
            expected_performance="学生能够发现与目标相关的问题，依据证据选择修订重点，并说明修订后产生的实际变化。",
            skip_condition="任务没有提供修订机会，或仅保留最终版本而无法观察修订过程时记录 暂不评价。",
            support_options=["教师提供的检查清单", "同伴针对作品提出的具体反馈"],
            common_problems=["只改变颜色或字体但未回应已识别问题，不能证明进行了有效调节。"],
            level_descriptions=[
                "未识别明显问题，或修订与任务目标无关，作品关键缺陷保持不变。",
                "能够指出表面问题，但修订缺少证据依据，或未改善主要表达缺陷。",
                "能够依据一条反馈或检查结果修订主要问题，并描述修订前后的变化。",
                "能够整合多项证据确定修订优先级，修订后明显改善作品与目标的一致性。",
                "能够持续检查修订效果，解释保留与拒绝反馈的理由，并形成可迁移的检查策略。",
            ],
            examples=[
                {
                    "level": 1,
                    "title": "装饰性修改样例",
                    "example_description": "学生只更换背景颜色，没有处理数据标签错误和读者无法比较的问题。",
                    "file_reference": "SIM-R1-L1",
                },
                {
                    "level": 4,
                    "title": "证据驱动修订样例",
                    "example_description": "学生根据检查记录调整比例和标注，并说明这些变化如何减少读者误解。",
                    "file_reference": "SIM-R1-L4",
                },
            ],
            follow_up_suggestion="让学生把本次最有效的一条检查方法写成可复用步骤，并在下一项数据任务中再次使用。",
        ),
        criterion(
            code="D1",
            dimension="subject_practice",
            title="数据处理与表达实践",
            evaluation_target="从原始数据到可视化成果的数据整理、转换和表达过程",
            evaluation_sources=["处理后的数据表", "转换说明", "最终可视化作品"],
            learning_goal_codes=["C1", "C2"],
            evaluation_task_codes=["T1"],
            evidence_ownership="individual",
            material_types=["operation"],
            expected_performance="学生能够保持数据含义与单位一致，合理处理缺失值或异常值，并让处理过程可以被复核。",
            skip_condition="未提供数据处理过程，且无法从作品或说明判断数据如何转换时记录 暂不评价。",
            support_options=["电子表格函数提示", "教师提供的数据字段说明"],
            common_problems=["得到正确图形但无法说明数据清洗和转换步骤，不足以证明完整的数据实践。"],
            level_descriptions=[
                "数据处理改变原始含义或引入明显错误，且过程无法被复核。",
                "完成基本整理但存在单位、缺失值或转换记录不一致的问题。",
                "主要处理步骤正确并保留基本说明，结果能够支持当前表达任务。",
                "数据整理、转换和异常处理有清晰依据，过程可复核且与表达目标一致。",
                "数据实践准确可复现，并能主动评估处理选择对结论和解释边界的影响。",
            ],
            examples=[
                {
                    "level": 2,
                    "title": "单位混用样例",
                    "example_description": "学生完成数据汇总，但把百分数与小数混在同一列，导致表达结果存在偏差。",
                    "file_reference": "SIM-D1-L2",
                },
                {
                    "level": 5,
                    "title": "可复现处理样例",
                    "example_description": "学生记录清洗与转换步骤，并解释异常值处理对最终结论可能造成的影响。",
                    "file_reference": "SIM-D1-L5",
                },
            ],
            follow_up_suggestion="提供一组包含缺失值和异常值的新数据，让学生复用并解释自己的处理规则。",
        ),
        criterion(
            code="E1",
            dimension="responsibility",
            title="数据来源与表达责任",
            evaluation_target="数据来源说明、隐私处理和可视化表达中的责任性决策",
            evaluation_sources=["数据来源说明", "隐私处理记录", "作品中的注释与边界说明"],
            learning_goal_codes=["C4"],
            evaluation_task_codes=["T3"],
            evidence_ownership="individual",
            material_types=["artifact"],
            expected_performance="学生能够说明数据来源，识别隐私和误导风险，并采取与任务情境相匹配的保护或说明措施。",
            skip_condition="任务未涉及真实或可识别数据，且没有设置来源与表达责任观察机会时记录 暂不评价。",
            support_options=["数据使用规范", "教师提供的隐私检查问题"],
            common_problems=["只在作品末尾写数据来自网络，但无法说明具体来源和使用边界，不构成充分证据。"],
            level_descriptions=[
                "忽略明显的数据来源、隐私或误导风险，并发布可能造成伤害的表达。",
                "能够意识到一般风险，但来源说明或保护措施不完整，仍可能识别个体或误导读者。",
                "说明主要数据来源并采取基本保护措施，能够避免任务中的明显责任风险。",
                "能够识别具体风险，采用适当保护和边界说明，并解释这些措施与情境的关系。",
                "能够系统评估利益相关者与潜在后果，在透明表达、数据效用和隐私保护之间作出可辩护权衡。",
            ],
            examples=[
                {
                    "level": 2,
                    "title": "来源笼统样例",
                    "example_description": "学生写明数据来自网络，但没有具体出处，也未处理可能识别个人的字段。",
                    "file_reference": "SIM-E1-L2",
                },
                {
                    "level": 4,
                    "title": "风险说明样例",
                    "example_description": "学生登记具体来源、移除可识别字段，并在作品中解释样本和结论边界。",
                    "file_reference": "SIM-E1-L4",
                },
            ],
            follow_up_suggestion="让学生针对同一数据情境比较两种公开方式，并说明不同利益相关者可能承担的风险。",
        ),
    ]


class Command(BaseCommand):
    help = "为合成工程轨道创建一个可重复发布的数据与计算评价方案和五星评价标准。"

    def add_arguments(self, parser):
        parser.add_argument("--teacher", default="foldkant")
        parser.add_argument("--course-id", type=int)
        parser.add_argument("--curriculum-version-id", type=int)
        parser.add_argument("--no-publish", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        teacher = User.objects.filter(
            username=options["teacher"],
            role=User.Role.TEACHER,
        ).first()
        if teacher is None:
            raise CommandError("未找到指定教师。")

        courses = Course.objects.filter(
            teacher=teacher,
            subject__school=teacher.school,
        ).select_related("subject")
        if options.get("course_id"):
            course = courses.filter(pk=options["course_id"]).first()
        else:
            course = courses.filter(title__contains="SIM-").order_by("id").first()
        if course is None:
            raise CommandError("未找到教师的模拟课程；请使用 --course-id 指定课程。")

        curriculum_version, curriculum_nodes = curriculum_context(
            course=course,
            version_id=options.get("curriculum_version_id"),
        )
        curriculum_node_ids = [node.id for node in curriculum_nodes]

        plan_defaults = {
            "school": teacher.school,
            "subject": course.subject,
            "scope": EvaluationScope.COURSE,
            "content_version": "SIM-2026.1",
            "target_students": "高一年级信息科技课程中完成数据表达任务的学生；仅用于合成工程验证。",
            "learning_goal": "学生能够整理真实情境数据，选择适当的表达方式，解释设计依据，并根据证据修订作品。",
            "learning_goals": [
                {"code": "C1", "title": "准确表达数据", "description": "学生能够保持数据含义、单位和视觉编码一致，生成可被目标读者正确理解的成果。", "curriculum_node_ids": curriculum_node_ids},
                {"code": "C2", "title": "论证表示策略", "description": "学生能够联系数据特点、表达目的和读者需求，解释选择并比较合理替代方案。", "curriculum_node_ids": curriculum_node_ids},
                {"code": "C3", "title": "依据证据修订", "description": "学生能够使用检查结果和反馈识别问题，选择修订重点并说明修订效果。", "curriculum_node_ids": curriculum_node_ids},
                {"code": "C4", "title": "负责任地使用数据", "description": "学生能够说明数据来源，识别隐私与误导风险，并采取与情境相匹配的措施。", "curriculum_node_ids": curriculum_node_ids},
            ],
            "evaluation_basis": [
                {"code": "EV1", "goal_codes": ["C1", "C2"], "description": "最终作品和设计说明共同显示表达准确性及表示策略的可辩护程度。", "source_types": ["最终可视化作品", "设计说明文本"]},
                {"code": "EV2", "goal_codes": ["C2", "C3"], "description": "版本记录、检查清单和反馈回应显示策略调整与修订是否由证据驱动。", "source_types": ["版本记录", "检查清单", "反馈回应"]},
                {"code": "EV3", "goal_codes": ["C4"], "description": "来源登记、隐私处理和表达边界说明显示学生的数据责任实践。", "source_types": ["来源说明", "隐私处理记录", "边界说明"]},
            ],
            "learning_activities": [
                {"code": "A1", "title": "数据整理与表达设计", "goal_codes": ["C1", "C2"], "description": "学生整理校园情境数据，比较可行的表示策略并形成可视化初稿。"},
                {"code": "A2", "title": "检查反馈与证据修订", "goal_codes": ["C2", "C3"], "description": "学生依据检查结果与具体反馈修订作品，并解释关键变化的证据。"},
                {"code": "A3", "title": "来源登记与风险检查", "goal_codes": ["C4"], "description": "学生登记数据来源，检查隐私与误导风险并说明成果适用边界。"},
            ],
            "learning_tasks": [],
            "evaluation_tasks": [
                {"code": "T1", "title": "校园数据可视化作品", "goal_codes": ["C1", "C2"], "activity_codes": ["A1"], "mode": "project", "evidence_ownership": "individual", "material_types": ["artifact", "operation"], "weight": 50, "description": "学生独立提交可视化作品、数据处理过程与设计说明，呈现准确表达和策略选择。"},
                {"code": "T2", "title": "检查与修订记录", "goal_codes": ["C2", "C3"], "activity_codes": ["A2"], "mode": "artifact", "evidence_ownership": "individual", "material_types": ["artifact", "observation"], "weight": 30, "description": "学生提交初稿、检查记录、反馈回应和修订说明，呈现证据驱动的调整过程。"},
                {"code": "T3", "title": "数据来源与责任说明", "goal_codes": ["C4"], "activity_codes": ["A3"], "mode": "artifact", "evidence_ownership": "individual", "material_types": ["artifact"], "weight": 20, "description": "学生提交数据来源、隐私处理与表达边界说明，呈现负责任的数据实践。"},
            ],
            "assessment_modes": ["project", "artifact"],
            "content_scope": ["数据整理与转换", "数据可视化", "方案比较与论证", "反馈与修订", "数据来源与责任"],
            "thinking_requirements": ["apply", "analyze", "evaluate", "create"],
            "support_options": ["教师提供的数据字典", "图表类型参考表", "电子表格函数提示", "针对作品的澄清问题"],
            "scoring_rules": {
                "approach": "分析式五星评价标准逐项判断",
                "decision_rule": "每个条目只依据登记证据独立判断；没有观察机会时记录 暂不评价，不以低星级替代缺失证据。",
            },
            "follow_up_suggestion": "依据证据最薄弱且可干预的条目安排下一次反馈、对比案例或修订任务，不使用总星数直接决定学生层级。",
            "review_status": EvaluationReviewStatus.DRAFT,
            "reviewed_by": None,
            "reviewed_at": None,
            "reviewed_content_hash": "",
            "updated_by": teacher,
        }
        plan, created = EvaluationPlan.objects.update_or_create(
            course=course,
            created_by=teacher,
            title=PLAN_TITLE,
            defaults=plan_defaults,
        )
        replace_plan_curriculum_references(
            plan=plan,
            node_ids=curriculum_node_ids,
            actor=teacher,
        )

        plan_version = None
        if not options["no_publish"]:
            confirm_plan_review(plan=plan, reviewed_by=teacher)
            plan_version = publish_plan(plan, published_by=teacher).version
        else:
            plan_version = plan.versions.filter(
                review_status=EvaluationReviewStatus.REVIEWED,
                reviewed_by__isnull=False,
                reviewed_at__isnull=False,
            ).order_by("-version_no", "-id").first()

        standard, standard_created = EvaluationStandard.objects.update_or_create(
            plan=plan,
            created_by=teacher,
            title=STANDARD_TITLE,
            defaults={
                "school": teacher.school,
                "subject": course.subject,
                "course": course,
                "scope": EvaluationScope.COURSE,
                "plan_version": plan_version,
                "evaluation_target": "校园数据可视化作品、策略说明、修订过程和数据责任说明",
                "criteria": pilot_criteria(),
                "review_status": EvaluationReviewStatus.DRAFT,
                "reviewed_by": None,
                "reviewed_at": None,
                "reviewed_content_hash": "",
                "updated_by": teacher,
            },
        )

        standard_version = None
        if not options["no_publish"]:
            confirm_standard_review(standard=standard, reviewed_by=teacher)
            standard_version = publish_standard(standard, published_by=teacher).version

        self.stdout.write(
            self.style.SUCCESS(
                "\n".join(
                    [
                        f"课程：{course.id} {course.title}",
                        f"课程标准：{curriculum_version.id} {curriculum_version.version_label}",
                        f"评价方案：{plan.id} ({'created' if created else 'updated'})"
                        + (f" v{plan_version.version_no}" if plan_version else " draft"),
                        f"评价标准：{standard.id} ({'created' if standard_created else 'updated'})"
                        + (f" v{standard_version.version_no}" if standard_version else " draft"),
                        "验证状态：unvalidated；仅允许用于合成工程轨道。",
                    ]
                )
            )
        )
