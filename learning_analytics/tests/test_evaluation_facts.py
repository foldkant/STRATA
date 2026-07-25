from __future__ import annotations

import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import (
    ClassroomEvaluationConfig,
    ClassroomEvaluationConfigVersion,
    ClassroomEvaluationSubmission,
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupDocumentVersion,
    ClassroomGroupFile,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Subject,
)
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumNodeType,
    CurriculumStandard,
    CurriculumStandardNode,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    SchoolStage,
)
from curriculum_standards.services import replace_plan_curriculum_references
from learning.models import (
    LessonStepAttempt,
    StudentLearningTargetStateVersion,
    StudentWorkAttachment,
    UnifiedAssessmentMaterial,
)
from learning_analytics.models import (
    ClassroomEvaluationStandardUse,
    EvaluationPlan,
    EvaluationStandard,
    EvaluationSubmissionEvidence,
    LessonStepEvaluationBinding,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
)
from learning_analytics.services.dual_write import reconcile_v1_v2_events
from learning_analytics.services.evaluation import (
    confirm_plan_review,
    confirm_standard_review,
    publish_plan,
    publish_standard,
)
from learning_analytics.services.evaluation_events import (
    EvaluationEventError,
    append_evaluation_submission,
)
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class EvaluationFactTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="评价事实测试学校", code="EVAL-FACT")
        self.subject = Subject.objects.create(
            school=self.school, name="信息科技", code="IT"
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.teacher = User.objects.create_user(
            username="eval_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        curriculum_standard = CurriculumStandard.objects.create(
            title="普通高中信息技术课程标准",
            document_type=CurriculumDocumentType.SUBJECT_STANDARD,
            school_stage=SchoolStage.SENIOR_HIGH,
            subject_code="information_technology",
            subject_name="信息科技",
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        curriculum_version = CurriculumStandardVersion.objects.create(
            source=curriculum_standard,
            version_label="2025-test",
            publication_year=2025,
            effective_year=2025,
            title_snapshot=curriculum_standard.title,
            official_title="普通高中信息技术课程标准（测试版本）",
            document_type_snapshot=curriculum_standard.document_type,
            school_stage_snapshot=curriculum_standard.school_stage,
            subject_code_snapshot=curriculum_standard.subject_code,
            subject_name_snapshot=curriculum_standard.subject_name,
            pdf_file="curriculum_standards/tests/information-technology.pdf",
            pdf_sha256="a" * 64,
            pdf_size_bytes=1024,
            pdf_page_count=4,
            content_hash="b" * 64,
            created_by=self.teacher,
        )
        self.curriculum_nodes = [
            CurriculumStandardNode.objects.create(
                version=curriculum_version,
                node_type=node_type,
                code=code,
                title=title,
                content=f"信息科技课程标准原文：{title}，用于评价事实链测试。",
                source_page_start=index,
                source_page_end=index,
                source_paragraph=title,
                sort_order=index,
            )
            for index, (node_type, code, title) in enumerate(
                (
                    (CurriculumNodeType.CORE_COMPETENCY, "IT.CORE", "核心素养"),
                    (CurriculumNodeType.COURSE_OBJECTIVE, "IT.OBJECTIVE", "课程目标"),
                    (CurriculumNodeType.COURSE_CONTENT, "IT.CONTENT", "课程内容"),
                    (CurriculumNodeType.ACADEMIC_QUALITY, "IT.QUALITY", "学业质量"),
                ),
                start=1,
            )
        ]
        CurriculumStandardVersion.objects.filter(pk=curriculum_version.pk).update(
            status=CurriculumVersionStatus.PUBLISHED,
            reviewed_by=self.teacher,
            published_by=self.teacher,
        )
        CurriculumStandard.objects.filter(pk=curriculum_standard.pk).update(
            current_version=curriculum_version
        )
        self.curriculum_node_ids = [node.id for node in self.curriculum_nodes]
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.students = []
        self.profiles = []
        for index in range(1, 4):
            student = User.objects.create_user(
                username=f"eval_student{index}",
                password="123456",
                role=User.Role.STUDENT,
                school=self.school,
                display_name=f"学生{index}",
            )
            profile = StudentProfile.objects.create(
                user=student,
                class_group=self.class_group,
                is_first_use=False,
            )
            self.students.append(student)
            self.profiles.append(profile)
        self.course = Course.objects.create(
            subject=self.subject,
            title="评价事实课程",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(
            course=self.course, title="评价事实课时", is_active=True
        )
        self.lesson_step = LessonStep.objects.create(
            lesson=self.lesson,
            title="展示评价",
            step_type=LessonStep.StepType.EVALUATION,
            created_by=self.teacher,
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="评价事实课堂",
            status=ClassroomSession.Status.RUNNING,
            current_step=self.lesson_step,
            started_at=timezone.now(),
        )
        self.config = ClassroomEvaluationConfig.objects.create(
            course=self.course,
            enable_self=True,
            enable_peer=True,
            enable_teacher=True,
            self_criteria=[
                {
                    "id": "self-process",
                    "title": "学习过程",
                    "description": "反思学习过程",
                    "sort_order": 10,
                }
            ],
            peer_criteria=[
                {
                    "id": "peer-collaboration",
                    "title": "协作贡献",
                    "description": "评价同伴贡献",
                    "sort_order": 10,
                }
            ],
            teacher_criteria=[
                {
                    "id": "teacher-outcome",
                    "title": "任务达成",
                    "description": "评价任务成果",
                    "sort_order": 10,
                }
            ],
            created_by=self.teacher,
        )
        collaboration = ClassroomGroupCollaboration.objects.create(
            session=self.session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.OPEN,
            created_by=self.teacher,
            opened_at=timezone.now(),
        )
        group = ClassroomGroup.objects.create(
            collaboration=collaboration,
            group_no=1,
            name="第1组",
        )
        for student, profile in zip(self.students, self.profiles, strict=True):
            ClassroomGroupMember.objects.create(
                collaboration=collaboration,
                group=group,
                student=student,
                student_profile=profile,
            )
        self.group = group
        self.client = APIClient()

    def enable_evaluation(self):
        self.client.force_authenticate(self.teacher)
        return self.client.patch(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/",
            {"evaluation_enabled": True},
            format="json",
        )

    def test_teacher_evaluation_payload_includes_every_student(self):
        self.client.force_authenticate(self.teacher)
        response = self.client.get(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["data"]["students"]
        self.assertEqual(len(rows), len(self.students))
        self.assertSetEqual(
            {row["student"]["id"] for row in rows},
            {student.id for student in self.students},
        )

    def test_teacher_evaluation_payload_explains_unbound_current_step(self):
        other_step = LessonStep.objects.create(
            lesson=self.lesson,
            title="已设置评价的导入环节",
            step_type=LessonStep.StepType.INTRO,
            sort_order=5,
            created_by=self.teacher,
        )
        _standard, version, _binding = self.create_formal_binding()
        LessonStepEvaluationBinding.objects.create(
            lesson_step=other_step,
            standard_version=version,
            enable_self=True,
            enable_peer=False,
            enable_teacher=True,
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        LessonStepEvaluationBinding.objects.filter(lesson_step=self.lesson_step).delete()
        self.client.force_authenticate(self.teacher)

        response = self.client.get(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        availability = response.data["data"]["availability"]
        self.assertFalse(availability["can_enable"])
        self.assertEqual(availability["reason_code"], "current_step_unbound")
        self.assertEqual(availability["current_step"]["title"], "展示评价")
        self.assertEqual(availability["bound_steps"][0]["title"], "已设置评价的导入环节")

    def test_frozen_criteria_include_curriculum_alignment_without_false_level_equivalence(self):
        _standard, _version, _binding = self.create_formal_binding()

        enabled = self.enable_evaluation()

        self.assertEqual(enabled.status_code, 200, enabled.data)
        criterion = enabled.data["data"]["config"]["teacher_criteria"][0]
        alignment = criterion["curriculum_alignment"]
        self.assertEqual(alignment["learning_goals"][0]["code"], "G1")
        self.assertEqual(alignment["core_competencies"][0]["title"], "核心素养")
        self.assertEqual(alignment["academic_quality"][0]["title"], "学业质量")
        self.assertEqual(alignment["quality_mapping_status"], "reference_only")
        self.assertIn("不直接等同", alignment["quality_mapping_note"])

    def submit_student(
        self, student, evaluation_type, target=None, rating=4, criterion_id=None
    ):
        self.client.force_authenticate(student)
        if criterion_id is None:
            standard_use = ClassroomEvaluationStandardUse.objects.get(
                session=self.session
            )
            criteria = getattr(standard_use, f"{evaluation_type}_criteria")
            criterion_id = criteria[0]["id"]
        payload = {
            "evaluation_type": evaluation_type,
            "ratings": {criterion_id: rating},
            "comment": "评价正文只保留在业务表",
        }
        if target:
            payload["target"] = target.id
        return self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/evaluation/submit/",
            payload,
            format="json",
        )

    def create_formal_binding(self, *, include_second_criterion=False):
        plan = EvaluationPlan.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            title="课堂作品评价方案",
            content_version="2026.1",
            target_students="参加本课学习的学生",
            learning_goal="学生能够完成任务并说明自己的解决过程。",
            learning_goals=[
                {
                    "code": "G1",
                    "title": "完成任务",
                    "description": "完成课堂任务并说明关键决策。",
                    "curriculum_node_ids": self.curriculum_node_ids,
                }
            ],
            evaluation_basis=[
                {
                    "code": "E1",
                    "goal_codes": ["G1"],
                    "description": "学生作答和上传作品共同作为评价依据。",
                    "source_types": ["课堂作答", "学生作品"],
                }
            ],
            learning_tasks=[
                {
                    "code": "T1",
                    "title": "课堂任务",
                    "basis_codes": ["E1"],
                    "description": "提交答案与作品。",
                }
            ],
            learning_activities=[
                {
                    "code": "A1",
                    "title": "课堂任务实践",
                    "goal_codes": ["G1"],
                    "description": "学生完成课堂任务并说明主要解决步骤。",
                }
            ],
            evaluation_tasks=[
                {
                    "code": "T1",
                    "title": "课堂任务评价",
                    "goal_codes": ["G1"],
                    "activity_codes": ["A1"],
                    "mode": "mixed",
                    "component_modes": ["test", "artifact"],
                    "evidence_ownership": "individual",
                    "material_types": ["answer", "artifact", "score"],
                    "weight": 100,
                    "description": "综合课堂作答、个人作品与评分记录进行评价。",
                }
            ],
            assessment_modes=["mixed"],
            content_scope=["课堂任务"],
            thinking_requirements=["apply"],
            support_options=[],
            scoring_rules={
                "approach": "分项评价",
                "decision_rule": "缺少证据时不评价该项。",
            },
            follow_up_suggestion="根据证据不足的指标安排后续反馈。",
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        replace_plan_curriculum_references(
            plan=plan,
            node_ids=self.curriculum_node_ids,
            actor=self.teacher,
        )
        confirm_plan_review(plan=plan, reviewed_by=self.teacher)
        plan_version = publish_plan(plan, published_by=self.teacher).version
        criteria = [
            {
                "code": "D1",
                "dimension": "subject_practice",
                "title": "任务达成",
                "evaluation_target": "学生课堂作答和上传作品",
                "evaluation_sources": ["课堂作答", "学生作品"],
                "learning_goal_codes": ["G1"],
                "evaluation_task_codes": ["T1"],
                "evidence_ownership": "individual",
                "material_types": ["answer", "artifact", "score"],
                "expected_performance": "学生完成任务并能说明关键步骤。",
                "skip_condition": "没有作答或作品时不评价。",
                "support_options": [],
                "common_problems": ["只提交结果，没有过程说明。"],
                "level_descriptions": {
                    "1": "尚未完成任务，也没有提供可评价的过程说明。",
                    "2": "只完成少量内容，关键步骤和理由仍然缺失。",
                    "3": "基本完成任务，并能说明一个主要解决步骤。",
                    "4": "完整完成任务，能够连贯说明主要步骤和理由。",
                    "5": "高质量完成任务，并能比较不同方案及其取舍。",
                },
                "scoring_examples": [
                    {
                        "level": 2,
                        "title": "过程说明不足",
                        "example_description": "只提交部分结果，缺少关键步骤说明。",
                        "file_reference": "classroom-D1-L2",
                    },
                    {
                        "level": 4,
                        "title": "完整过程说明",
                        "example_description": "完整提交结果并说明主要步骤。",
                        "file_reference": "classroom-D1-L4",
                    },
                ],
                "follow_up_suggestion": "针对缺失步骤给出补充提示。",
            }
        ]
        if include_second_criterion:
            criteria.append(
                {
                    "code": "D2",
                    "dimension": "collaboration",
                    "title": "协作表现",
                    "evaluation_target": "学生小组协作过程",
                    "evaluation_sources": ["课堂观察"],
                    "learning_goal_codes": ["G1"],
                    "evaluation_task_codes": ["T1"],
                    "evidence_ownership": "individual",
                    "material_types": ["observation", "score"],
                    "expected_performance": "学生能参与协作并回应同伴。",
                    "skip_condition": "本节未安排协作时不评价。",
                    "support_options": [],
                    "common_problems": ["缺少可观察的协作过程。"],
                    "level_descriptions": {
                        str(level): f"协作表现等级 {level}" for level in range(1, 6)
                    },
                    "scoring_examples": [
                        {
                            "level": 2,
                            "title": "参与有限",
                            "example_description": "偶尔参与，但缺少对同伴的回应。",
                            "file_reference": "classroom-D2-L2",
                        },
                        {
                            "level": 4,
                            "title": "有效协作",
                            "example_description": "持续参与并能回应同伴。",
                            "file_reference": "classroom-D2-L4",
                        },
                    ],
                    "follow_up_suggestion": "提供明确的协作分工。",
                }
            )
        standard = EvaluationStandard.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            plan=plan,
            plan_version=plan_version,
            title="课堂作品评价标准",
            evaluation_target="学生课堂作答和上传作品",
            criteria=criteria,
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        confirm_standard_review(standard=standard, reviewed_by=self.teacher)
        version = publish_standard(standard, published_by=self.teacher).version
        binding = LessonStepEvaluationBinding.objects.create(
            lesson_step=self.lesson_step,
            standard_version=version,
            enable_self=True,
            enable_peer=True,
            enable_teacher=True,
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        return standard, version, binding

    def create_project_binding(self):
        plan = EvaluationPlan.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            title="信息科技项目成果评价方案",
            content_version="2026.2",
            target_students="参加信息科技项目学习的学生",
            learning_goal="学生能够合作完成信息科技作品并独立说明设计取舍。",
            learning_goals=[
                {
                    "code": "G_PROJECT",
                    "title": "完成项目并说明设计取舍",
                    "description": "合作完成可运行作品，并能独立答辩说明关键决策。",
                    "curriculum_node_ids": self.curriculum_node_ids,
                }
            ],
            evaluation_basis=[
                {
                    "code": "E_PROJECT",
                    "goal_codes": ["G_PROJECT"],
                    "description": "小组最终作品和学生个人答辩共同作为评价依据。",
                    "source_types": ["小组作品", "个人答辩"],
                }
            ],
            learning_activities=[
                {
                    "code": "A_PROJECT",
                    "title": "项目设计与展示",
                    "goal_codes": ["G_PROJECT"],
                    "description": "小组合作设计作品，每名学生独立说明自己的设计判断。",
                }
            ],
            evaluation_tasks=[
                {
                    "code": "T_ARTIFACT",
                    "title": "小组项目作品",
                    "goal_codes": ["G_PROJECT"],
                    "activity_codes": ["A_PROJECT"],
                    "mode": "project",
                    "evidence_ownership": "group",
                    "material_types": ["artifact"],
                    "weight": 60,
                    "description": "依据当前课堂实际小组提交的项目作品进行评价。",
                },
                {
                    "code": "T_DEFENSE",
                    "title": "个人项目答辩",
                    "goal_codes": ["G_PROJECT"],
                    "activity_codes": ["A_PROJECT"],
                    "mode": "oral_defense",
                    "evidence_ownership": "individual",
                    "material_types": ["oral_defense", "observation"],
                    "weight": 40,
                    "description": "依据学生个人答辩中对关键设计取舍的说明进行评价。",
                },
            ],
            assessment_modes=["project", "oral_defense"],
            content_scope=["信息科技项目作品", "项目答辩"],
            thinking_requirements=["apply", "evaluate", "create"],
            support_options=[],
            scoring_rules={
                "approach": "项目作品与个人答辩分项评价",
                "decision_rule": "缺少对应评价材料时该项暂不评价，不以低分替代。",
            },
            follow_up_suggestion="根据作品和答辩的不同表现安排针对性反馈。",
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        replace_plan_curriculum_references(
            plan=plan,
            node_ids=self.curriculum_node_ids,
            actor=self.teacher,
        )
        confirm_plan_review(plan=plan, reviewed_by=self.teacher)
        plan_version = publish_plan(plan, published_by=self.teacher).version
        common_levels = {
            "1": "尚未呈现可辨识的关键表现，需要补充评价材料。",
            "2": "呈现少量关键表现，但作品或说明仍有明显缺漏。",
            "3": "基本呈现预期表现，能够说明主要过程与结果。",
            "4": "完整呈现预期表现，能够清楚说明过程与设计理由。",
            "5": "高质量呈现预期表现，并能比较方案与反思设计取舍。",
        }
        criteria = [
            {
                "code": "C_ARTIFACT",
                "dimension": "task_quality",
                "title": "小组作品质量",
                "evaluation_target": "当前课堂实际小组提交的项目作品",
                "evaluation_sources": ["小组协作文档或小组文件"],
                "learning_goal_codes": ["G_PROJECT"],
                "evaluation_task_codes": ["T_ARTIFACT"],
                "evidence_ownership": "group",
                "material_types": ["artifact"],
                "expected_performance": "小组作品能够运行并体现明确的信息处理方案。",
                "skip_condition": "没有当前实际小组作品时暂不评价该指标。",
                "support_options": [],
                "common_problems": ["只提交个人文件，不能确认实际小组共同成果。"],
                "level_descriptions": common_levels,
                "scoring_examples": [
                    {
                        "level": 2,
                        "title": "作品材料不完整",
                        "example_description": "作品仅呈现局部结果，关键功能和设计说明缺失。",
                        "file_reference": "project-artifact-L2",
                    },
                    {
                        "level": 4,
                        "title": "作品完整可用",
                        "example_description": "作品功能完整，能够体现清晰的信息处理方案。",
                        "file_reference": "project-artifact-L4",
                    },
                ],
                "follow_up_suggestion": "根据作品缺失的关键环节安排小组修订。",
            },
            {
                "code": "C_DEFENSE",
                "dimension": "subject_practice",
                "title": "个人答辩表现",
                "evaluation_target": "学生个人对项目设计取舍的现场说明",
                "evaluation_sources": ["教师现场答辩观察记录"],
                "learning_goal_codes": ["G_PROJECT"],
                "evaluation_task_codes": ["T_DEFENSE"],
                "evidence_ownership": "individual",
                "material_types": ["oral_defense"],
                "expected_performance": "学生能够独立说明关键设计决策及其依据。",
                "skip_condition": "学生未获得答辩机会或教师未观察时暂不评价。",
                "support_options": [],
                "common_problems": ["只能复述小组结果，不能说明自己的设计判断。"],
                "level_descriptions": common_levels,
                "scoring_examples": [
                    {
                        "level": 2,
                        "title": "说明缺少依据",
                        "example_description": "能够描述部分结果，但不能解释关键设计选择。",
                        "file_reference": "project-defense-L2",
                    },
                    {
                        "level": 4,
                        "title": "独立说明清楚",
                        "example_description": "能够独立说明关键决策，并给出合理的设计依据。",
                        "file_reference": "project-defense-L4",
                    },
                ],
                "follow_up_suggestion": "针对学生未能说明的设计环节安排个别追问。",
            },
        ]
        standard = EvaluationStandard.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            plan=plan,
            plan_version=plan_version,
            title="信息科技项目成果评价标准",
            evaluation_target="小组项目作品与学生个人答辩表现",
            criteria=criteria,
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        confirm_standard_review(standard=standard, reviewed_by=self.teacher)
        version = publish_standard(standard, published_by=self.teacher).version
        binding = LessonStepEvaluationBinding.objects.create(
            lesson_step=self.lesson_step,
            standard_version=version,
            enable_self=True,
            enable_peer=False,
            enable_teacher=True,
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        return standard, version, binding

    def create_student_evidence(self, student):
        first_attempt = LessonStepAttempt.objects.create(
            school=self.school,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            lesson_step=self.lesson_step,
            classroom_session=self.session,
            student=student,
            attempt_no=1,
            answer={"q1": "first"},
            answered_count=1,
            question_count=1,
            submitted_at=timezone.now(),
        )
        latest_attempt = LessonStepAttempt.objects.create(
            school=self.school,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            lesson_step=self.lesson_step,
            classroom_session=self.session,
            student=student,
            attempt_no=2,
            answer={"q1": "revised"},
            answered_count=1,
            question_count=1,
            submitted_at=timezone.now(),
        )
        first_work = StudentWorkAttachment.objects.create(
            school=self.school,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            lesson_step=self.lesson_step,
            classroom_session=self.session,
            student=student,
            question_id="file-q1",
            upload_version=1,
            attachment=SimpleUploadedFile("first.txt", b"first"),
            original_name="first.txt",
            file_ext="txt",
            file_size=5,
        )
        latest_work = StudentWorkAttachment.objects.create(
            school=self.school,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            lesson_step=self.lesson_step,
            classroom_session=self.session,
            student=student,
            question_id="file-q1",
            upload_version=2,
            supersedes=first_work,
            attachment=SimpleUploadedFile("revised.txt", b"revised"),
            original_name="revised.txt",
            file_ext="txt",
            file_size=7,
        )
        return first_attempt, latest_attempt, first_work, latest_work

    def test_classroom_evaluation_is_frozen_and_submissions_are_versioned(self):
        _standard, standard_version, _binding = self.create_formal_binding()
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.session.refresh_from_db()
        frozen_use = ClassroomEvaluationStandardUse.objects.get(session=self.session)
        self.assertIsNone(self.session.evaluation_config_version)
        self.assertEqual(frozen_use.standard_version, standard_version)
        self.assertEqual(
            LearningEventV2.objects.filter(
                event_name="content.released",
                legacy_event__metadata__action="classroom_evaluation_released",
            ).count(),
            3,
        )
        self.assertEqual(LearningOpportunity.objects.count(), 9)
        self.assertTrue(
            all(not item.required for item in LearningOpportunity.objects.all())
        )

        self_response = self.submit_student(self.students[0], "self", rating=4)
        peer_response = self.submit_student(
            self.students[0], "peer", target=self.students[1], rating=5
        )
        self.client.force_authenticate(self.teacher)
        teacher_criterion_id = frozen_use.teacher_criteria[0]["id"]
        teacher_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/teacher-submit/",
            {
                "target": self.students[0].id,
                "ratings": {teacher_criterion_id: 3},
                "comment": "教师评价正文",
            },
            format="json",
        )
        revised_self = self.submit_student(self.students[0], "self", rating=5)
        self.assertEqual(self_response.status_code, 200, self_response.data)
        self.assertEqual(peer_response.status_code, 200, peer_response.data)
        self.assertEqual(teacher_response.status_code, 200, teacher_response.data)
        self.assertEqual(revised_self.status_code, 200, revised_self.data)

        self_submissions = list(
            ClassroomEvaluationSubmission.objects.filter(
                evaluation_type="self", evaluator=self.students[0]
            ).order_by("submission_version")
        )
        self.assertEqual([item.submission_version for item in self_submissions], [1, 2])
        self.assertEqual(self_submissions[1].supersedes, self_submissions[0])
        self.assertEqual(self_submissions[0].standard_use, frozen_use)
        self.assertIsNone(self_submissions[0].evaluation_version)
        self.assertNotEqual(
            self_submissions[0].analytics_attempt_id,
            self_submissions[1].analytics_attempt_id,
        )

        events = LearningEventV2.objects.filter(event_name="evaluation.rating.submitted")
        self.assertEqual(events.count(), 4)
        self.assertFalse(events.filter(payload__has_key="comment").exists())
        peer_event = events.get(payload__rater_role="peer")
        self.assertEqual(peer_event.actor, self.students[0])
        self.assertEqual(peer_event.target_student, self.students[1])
        self.assertEqual(peer_event.source, "server")
        self.assertEqual(peer_event.opportunity_record.student, self.students[1])
        self.assertEqual(
            peer_event.payload["criterion_ratings"],
            [{"criterion_id": frozen_use.peer_criteria[0]["id"], "rating": 5}],
        )
        self.assertEqual(
            ClassroomEvaluationConfigVersion.objects.filter(course=self.course).count(),
            0,
        )
        still_frozen = self.submit_student(self.students[1], "self", rating=4)
        self.assertEqual(still_frozen.status_code, 200, still_frozen.data)

        self.client.force_authenticate(self.teacher)
        closed = self.client.patch(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/",
            {"evaluation_enabled": False},
            format="json",
        )
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertTrue(
            LearningOpportunityTransitionFact.objects.filter(state="withdrawn").exists()
        )
        self.assertTrue(reconcile_v1_v2_events(school=self.school)["consistent"])
        self.assertTrue(EvaluationSubmissionEvidence.objects.exists())

    def test_formal_standard_is_frozen_and_submission_links_latest_evidence(self):
        standard, standard_version, binding = self.create_formal_binding()
        _, latest_attempt, _, latest_work = self.create_student_evidence(
            self.students[0]
        )

        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.session.refresh_from_db()
        standard_use = ClassroomEvaluationStandardUse.objects.get(session=self.session)
        self.assertEqual(standard_use.binding, binding)
        self.assertEqual(standard_use.standard_version, standard_version)
        self.assertEqual(
            standard_use.criteria_snapshot[0]["level_descriptions"][4],
            "高质量完成任务，并能比较不同方案及其取舍。",
        )
        criterion_id = f"std_{standard_version.id}_D1"
        self.assertEqual(
            standard_use.self_criteria[0]["criterion_code"],
            "D1",
        )

        response = self.submit_student(
            self.students[0],
            "self",
            rating=4,
            criterion_id=criterion_id,
        )
        self.assertEqual(response.status_code, 200, response.data)
        evidence = EvaluationSubmissionEvidence.objects.select_related(
            "submission", "lesson_step_attempt", "student_work_attachment"
        ).get()
        self.assertEqual(evidence.lesson_step_attempt, latest_attempt)
        self.assertEqual(evidence.student_work_attachment, latest_work)

        expected_version = (
            f"standard:{standard_version.id}:v{standard_version.version_no}:"
            f"{standard_version.content_hash[:12]}"
        )
        event = LearningEventV2.objects.get(
            event_name="evaluation.rating.submitted"
        )
        self.assertEqual(event.object_version, expected_version)
        self.assertEqual(event.payload["evaluation_version"], expected_version)
        self.assertEqual(event.opportunity_record.object_version, expected_version)

        standard.criteria[0]["level_descriptions"]["5"] = "已修改的草稿内容"
        standard.save(update_fields=["criteria", "updated_at"])
        standard_use.refresh_from_db()
        self.assertEqual(
            standard_use.criteria_snapshot[0]["level_descriptions"][4],
            "高质量完成任务，并能比较不同方案及其取舍。",
        )

        self.client.force_authenticate(self.teacher)
        binding_url = (
            f"/api/v1/teacher/evaluations/lesson-steps/{self.lesson_step.id}/binding/"
        )
        changed = self.client.patch(
            binding_url,
            {
                "standard_version": standard_version.id,
                "enable_self": True,
                "enable_peer": False,
                "enable_teacher": True,
            },
            format="json",
        )
        self.assertEqual(changed.status_code, 409, changed.data)
        self.assertEqual(self.client.delete(binding_url).status_code, 409)

    def test_project_group_artifact_and_individual_defense_keep_separate_sources(self):
        _standard, standard_version, _binding = self.create_project_binding()
        group_file = ClassroomGroupFile.objects.create(
            group=self.group,
            uploader=self.students[0],
            attachment=SimpleUploadedFile("group-project.zip", b"group-project"),
            original_name="group-project.zip",
            file_ext="zip",
            file_size=13,
            description="当前实际小组的项目作品",
        )
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        standard_use = ClassroomEvaluationStandardUse.objects.get(session=self.session)
        criteria = {
            item["criterion_code"]: item for item in standard_use.teacher_criteria
        }
        self.assertEqual(
            criteria["C_ARTIFACT"]["learning_goal_codes"], ["G_PROJECT"]
        )
        self.assertEqual(
            criteria["C_ARTIFACT"]["evaluation_task_codes"], ["T_ARTIFACT"]
        )
        self.assertEqual(len(criteria["C_ARTIFACT"]["learning_target_links"]), 1)
        self.assertEqual(
            criteria["C_ARTIFACT"]["learning_target_links"][0]["alignment_status"],
            "complete",
        )
        self.assertEqual(criteria["C_ARTIFACT"]["evidence_ownership"], "group")
        self.assertEqual(criteria["C_ARTIFACT"]["material_types"], ["artifact"])
        self.assertEqual(criteria["C_DEFENSE"]["evidence_ownership"], "individual")
        self.assertEqual(criteria["C_DEFENSE"]["material_types"], ["oral_defense"])

        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/teacher-submit/",
            {
                "target": self.students[0].id,
                "ratings": {
                    criteria["C_ARTIFACT"]["id"]: 4,
                    criteria["C_DEFENSE"]["id"]: 5,
                },
                "comment": "学生已完成个人答辩，能够说明关键设计取舍。",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        evidence = EvaluationSubmissionEvidence.objects.get()
        self.assertEqual(evidence.evidence_ownership, "both")
        self.assertEqual(evidence.group, self.group)
        self.assertIsNone(evidence.lesson_step_attempt)
        self.assertIsNone(evidence.student_work_attachment)
        artifact_row = next(
            item
            for item in evidence.material_manifest
            if item["criterion_code"] == "C_ARTIFACT"
        )
        defense_row = next(
            item
            for item in evidence.material_manifest
            if item["criterion_code"] == "C_DEFENSE"
        )
        self.assertEqual(artifact_row["ownership"], "group")
        self.assertEqual(
            artifact_row["schema_version"], "evaluation-material-manifest-v2"
        )
        self.assertEqual(
            artifact_row["learning_target_links"],
            criteria["C_ARTIFACT"]["learning_target_links"],
        )
        self.assertEqual(artifact_row["status"], "available")
        self.assertEqual(
            artifact_row["source"]["source_type"], "classroom_group_file"
        )
        self.assertEqual(artifact_row["source"]["source_id"], str(group_file.public_id))
        self.assertSetEqual(
            set(artifact_row["participant_student_ids"]),
            {student.id for student in self.students},
        )
        self.assertEqual(defense_row["ownership"], "individual")
        self.assertEqual(defense_row["status"], "available")
        self.assertEqual(
            defense_row["source"]["record_kind"],
            "teacher_attested_live_observation",
        )
        self.assertEqual(defense_row["student_id"], self.students[0].id)
        self.assertEqual(
            standard_use.standard_version_id,
            standard_version.id,
        )
        materials = list(
            UnifiedAssessmentMaterial.objects.select_related(
                "learning_target_version"
            ).order_by("ownership", "id")
        )
        self.assertEqual(len(materials), 2)
        group_material = next(
            item
            for item in materials
            if item.ownership == UnifiedAssessmentMaterial.Ownership.GROUP
        )
        individual_material = next(
            item
            for item in materials
            if item.ownership == UnifiedAssessmentMaterial.Ownership.INDIVIDUAL
        )
        self.assertIsNone(group_material.student_id)
        self.assertEqual(group_material.group_reference, f"classroom_group:{self.group.id}")
        self.assertEqual(individual_material.student, self.students[0])
        self.assertEqual(
            individual_material.learning_target_version,
            group_material.learning_target_version,
        )
        self.assertIsNone(individual_material.score)
        self.assertFalse(
            individual_material.content["eligible_for_learning_target_estimate"]
        )

        target_state = StudentLearningTargetStateVersion.objects.get()
        self.assertEqual(
            target_state.learning_target_version,
            individual_material.learning_target_version,
        )
        self.assertEqual(
            target_state.evidence_status,
            StudentLearningTargetStateVersion.EvidenceStatus.PENDING_REVIEW,
        )
        self.assertEqual(target_state.evidence_coverage, 1)
        self.assertIsNone(target_state.estimate)
        self.assertIsNone(target_state.uncertainty)
        self.assertEqual(len(target_state.material_references), 1)
        self.assertIn(
            str(individual_material.material_id),
            target_state.material_references[0],
        )
        self.assertNotIn(
            str(group_material.material_id),
            " ".join(target_state.material_references),
        )
        self.assertTrue(
            any("小组材料未计入个人" in note for note in target_state.observation_notes)
        )

    def test_group_artifact_cannot_be_replaced_by_individual_work_and_missing_is_not_scored(self):
        self.create_project_binding()
        self.create_student_evidence(self.students[0])
        ClassroomGroupDocumentVersion.objects.create(
            group=self.group,
            version_no=1,
            file=SimpleUploadedFile("blank-template.docx", b"blank-template"),
            file_sha256="c" * 64,
            file_size=14,
            source=ClassroomGroupDocumentVersion.Source.INITIAL,
            verified_editor_ids=[str(self.students[0].id)],
        )
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        standard_use = ClassroomEvaluationStandardUse.objects.get(session=self.session)
        criteria = {
            item["criterion_code"]: item for item in standard_use.teacher_criteria
        }
        artifact_id = criteria["C_ARTIFACT"]["id"]
        defense_id = criteria["C_DEFENSE"]["id"]

        self.client.force_authenticate(self.teacher)
        mismatched = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/teacher-submit/",
            {
                "target": self.students[0].id,
                "ratings": {artifact_id: 4, defense_id: 4},
            },
            format="json",
        )
        self.assertEqual(mismatched.status_code, 400, mismatched.data)
        self.assertIn("缺少可追溯的小组评价材料", mismatched.data["message"])
        self.assertFalse(ClassroomEvaluationSubmission.objects.exists())
        self.assertFalse(EvaluationSubmissionEvidence.objects.exists())
        self.assertFalse(UnifiedAssessmentMaterial.objects.exists())
        self.assertFalse(StudentLearningTargetStateVersion.objects.exists())

        not_scored = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/teacher-submit/",
            {
                "target": self.students[0].id,
                "ratings": {defense_id: 4},
                "not_assessed": {
                    artifact_id: {
                        "reason": "no_evidence",
                        "note": "只有个人文件，没有可确认的实际小组作品。",
                    }
                },
                "comment": "教师已记录学生个人答辩中的关键设计说明。",
            },
            format="json",
        )
        self.assertEqual(not_scored.status_code, 200, not_scored.data)
        submission = ClassroomEvaluationSubmission.objects.get()
        self.assertNotIn(artifact_id, submission.ratings)
        self.assertEqual(
            submission.not_assessed[artifact_id]["reason"], "no_evidence"
        )
        evidence = submission.standard_evidence
        artifact_row = next(
            item
            for item in evidence.material_manifest
            if item["criterion_code"] == "C_ARTIFACT"
        )
        self.assertEqual(artifact_row["status"], "missing")
        self.assertIsNone(artifact_row["source"])
        self.assertEqual(artifact_row["not_assessed_reason"], "no_evidence")
        self.assertIsNone(evidence.student_work_attachment)
        group_material = UnifiedAssessmentMaterial.objects.get(
            ownership=UnifiedAssessmentMaterial.Ownership.GROUP
        )
        self.assertEqual(
            group_material.material_status,
            UnifiedAssessmentMaterial.MaterialStatus.MISSING,
        )
        self.assertIsNone(group_material.score)
        target_state = StudentLearningTargetStateVersion.objects.get()
        self.assertEqual(target_state.evidence_coverage, 1)
        self.assertIsNone(target_state.estimate)

    def test_foreign_classroom_group_is_rejected_before_evidence_is_created(self):
        self.create_project_binding()
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        standard_use = ClassroomEvaluationStandardUse.objects.get(session=self.session)
        criteria = {
            item["criterion_code"]: item for item in standard_use.teacher_criteria
        }
        foreign_session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="其他课堂",
            status=ClassroomSession.Status.FINISHED,
            current_step=self.lesson_step,
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        foreign_collaboration = ClassroomGroupCollaboration.objects.create(
            session=foreign_session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.CLOSED,
            created_by=self.teacher,
            opened_at=timezone.now(),
            closed_at=timezone.now(),
        )
        foreign_group = ClassroomGroup.objects.create(
            collaboration=foreign_collaboration,
            group_no=1,
            name="其他课堂第1组",
        )
        ClassroomGroupMember.objects.create(
            collaboration=foreign_collaboration,
            group=foreign_group,
            student=self.students[0],
            student_profile=self.profiles[0],
        )

        with self.assertRaises(EvaluationEventError) as caught:
            append_evaluation_submission(
                course=self.course,
                class_group=self.class_group,
                session=self.session,
                evaluation_type=ClassroomEvaluationSubmission.EvaluationType.TEACHER,
                evaluator=self.teacher,
                target=self.students[0],
                standard_use=standard_use,
                ratings={
                    criteria["C_ARTIFACT"]["id"]: 4,
                    criteria["C_DEFENSE"]["id"]: 4,
                },
                not_assessed={},
                comment="",
                group=foreign_group,
            )
        self.assertEqual(caught.exception.code, "evaluation_evidence_scope_mismatch")
        self.assertFalse(ClassroomEvaluationSubmission.objects.exists())
        self.assertFalse(EvaluationSubmissionEvidence.objects.exists())

    def test_not_assessed_criterion_is_excluded_from_average_and_keeps_reason(self):
        _standard, _version, _binding = self.create_formal_binding(
            include_second_criterion=True
        )
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        standard_use = ClassroomEvaluationStandardUse.objects.get(session=self.session)
        first_id, second_id = [item["id"] for item in standard_use.self_criteria]

        self.client.force_authenticate(self.students[0])
        response = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/evaluation/submit/",
            {
                "evaluation_type": "self",
                "ratings": {first_id: 4},
                "not_assessed": {
                    second_id: {
                        "reason": "not_observed",
                        "note": "本节课没有安排小组活动。",
                    }
                },
                "comment": "按本节课实际材料填写。",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        submission = ClassroomEvaluationSubmission.objects.get(
            evaluation_type="self", evaluator=self.students[0]
        )
        self.assertEqual(submission.ratings, {first_id: 4})
        self.assertEqual(
            submission.not_assessed[second_id]["reason"],
            "not_observed",
        )
        serialized = response.data["data"]["self_submission"]
        self.assertEqual(
            serialized["not_assessed"][second_id]["reason_label"],
            "本节未安排或未观察到",
        )

        event = LearningEventV2.objects.get(
            event_name="evaluation.rating.submitted"
        )
        self.assertEqual(event.schema_version, "1.1")
        self.assertEqual(
            event.payload["criterion_ratings"],
            [{"criterion_id": first_id, "rating": 4}],
        )
        self.assertEqual(
            event.payload["not_assessed_criteria"],
            [
                {
                    "criterion_id": second_id,
                    "reason_code": "not_observed",
                }
            ],
        )

        self.client.force_authenticate(self.teacher)
        summary_response = self.client.get(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/"
        )
        self.assertEqual(summary_response.status_code, 200, summary_response.data)
        summary = summary_response.data["data"]["summary"]["self"]
        self.assertEqual(summary["average"], 4.0)
        self.assertEqual(summary["rated_item_count"], 1)
        self.assertEqual(summary["not_assessed_item_count"], 1)
        self.assertEqual(summary["total_item_count"], 2)

    def test_evaluation_requires_rating_or_valid_not_assessed_reason_per_criterion(self):
        self.create_formal_binding()
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        criterion_id = ClassroomEvaluationStandardUse.objects.get(
            session=self.session
        ).self_criteria[0]["id"]
        url = f"/api/v1/student/classroom/{self.session.id}/evaluation/submit/"
        self.client.force_authenticate(self.students[0])

        missing = self.client.post(
            url,
            {"evaluation_type": "self", "ratings": {}},
            format="json",
        )
        self.assertEqual(missing.status_code, 400, missing.data)

        both = self.client.post(
            url,
            {
                "evaluation_type": "self",
                "ratings": {criterion_id: 3},
                "not_assessed": {
                    criterion_id: {"reason": "no_evidence", "note": ""}
                },
            },
            format="json",
        )
        self.assertEqual(both.status_code, 400, both.data)

        other_without_note = self.client.post(
            url,
            {
                "evaluation_type": "self",
                "ratings": {},
                "not_assessed": {
                    criterion_id: {"reason": "other", "note": ""}
                },
            },
            format="json",
        )
        self.assertEqual(other_without_note.status_code, 400, other_without_note.data)

        valid_skip = self.client.post(
            url,
            {
                "evaluation_type": "self",
                "ratings": {},
                "not_assessed": {
                    criterion_id: {
                        "reason": "no_evidence",
                        "note": "本节未形成可评价作品。",
                    }
                },
            },
            format="json",
        )
        self.assertEqual(valid_skip.status_code, 200, valid_skip.data)

    def test_student_batch_cannot_forge_peer_rating_for_another_student(self):
        self.create_formal_binding()
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.session.refresh_from_db()
        standard_use = ClassroomEvaluationStandardUse.objects.get(session=self.session)
        opportunity = LearningOpportunity.objects.get(
            student=self.students[1],
            object_id=f"classroom-evaluation:{self.session.id}:peer",
        )
        self.client.force_authenticate(self.students[0])
        response = self.client.post(
            "/api/v1/learning-events/batch/",
            {
                "events": [
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_name": "evaluation.rating.submitted",
                        "schema_version": "1.1",
                        "target_student_id": self.students[1].id,
                        "class_id": self.class_group.id,
                        "subject_id": self.subject.id,
                        "course_id": self.course.id,
                        "session_id": self.session.id,
                        "object_type": "evaluation_standard",
                        "object_id": f"classroom-evaluation:{self.session.id}:peer",
                        "object_version": (
                            f"standard:{standard_use.standard_version_id}:"
                            f"v{standard_use.standard_version.version_no}:"
                            f"{standard_use.standard_version.content_hash[:12]}"
                        ),
                        "opportunity_id": str(opportunity.opportunity_id),
                        "client_occurred_at": timezone.now().isoformat(),
                        "payload": {
                            "evaluation_version": (
                                f"standard:{standard_use.standard_version_id}:"
                                f"v{standard_use.standard_version.version_no}:"
                                f"{standard_use.standard_version.content_hash[:12]}"
                            ),
                            "criterion_ratings": [
                                {
                                    "criterion_id": standard_use.peer_criteria[0]["id"],
                                    "rating": 5,
                                }
                            ],
                            "rater_role": "peer",
                        },
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data["data"]["results"][0]
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error_code"], "target_forbidden")
        self.assertFalse(
            LearningEventV2.objects.filter(
                event_name="evaluation.rating.submitted"
            ).exists()
        )
