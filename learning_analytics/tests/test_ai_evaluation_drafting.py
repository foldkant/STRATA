from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, Subject
from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumExtractionStatus,
    CurriculumNodeType,
    CurriculumStandard,
    CurriculumStandardNode,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    SchoolStage,
)
from curriculum_standards.retrieval import rebuild_retrieval_index
from learning_analytics.ai_evaluation_models import (
    AIEvaluationDraftSession,
    AIEvaluationDraftStatus,
    AIEvaluationGenerationRecord,
    AIEvaluationTaskKind,
)
from learning_analytics.evaluation_models import (
    EvaluationPlan,
    EvaluationReviewStatus,
    EvaluationStandard,
)
from learning_analytics.services.ai_evaluation_drafting import (
    _normalize_plan_draft,
    _normalize_standard_draft,
    _repair_ai_draft_structure,
    _review_item_map,
    execute_generation_stage,
    run_automatic_checks,
)
from school.models import School


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class AIEvaluationDraftingApiTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="AI Evaluation School", code="AI-EVAL")
        self.other_school = School.objects.create(name="Other AI School", code="AI-OTHER")
        self.admin = User.objects.create_user(
            username="ai_eval_admin",
            password="Admin123!",
            role=User.Role.SUPER_ADMIN,
        )
        self.teacher = User.objects.create_user(
            username="ai_eval_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.same_school_teacher = User.objects.create_user(
            username="ai_eval_same_school_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.school_admin = User.objects.create_user(
            username="ai_eval_school_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.student = User.objects.create_user(
            username="ai_eval_student",
            password="Student123!",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.other_teacher = User.objects.create_user(
            username="ai_eval_other_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.other_school,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="01",
        )
        self.other_subject = Subject.objects.create(
            school=self.other_school,
            name="信息科技",
            code="01",
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与计算",
            teacher=self.teacher,
            is_active=True,
        )
        self.other_course = Course.objects.create(
            subject=self.other_subject,
            title="其他学校课程",
            teacher=self.other_teacher,
            is_active=True,
        )
        self.source = CurriculumStandard.objects.create(
            title="普通高中信息技术课程标准",
            document_type=CurriculumDocumentType.SUBJECT_STANDARD,
            school_stage=SchoolStage.SENIOR_HIGH,
            subject_code="information_technology",
            subject_name="信息技术",
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.version = CurriculumStandardVersion.objects.create(
            source=self.source,
            version_label="2025",
            publication_year=2025,
            effective_year=2025,
            title_snapshot=self.source.title,
            official_title="普通高中信息技术课程标准（2025年版）",
            document_type_snapshot=self.source.document_type,
            school_stage_snapshot=self.source.school_stage,
            subject_code_snapshot=self.source.subject_code,
            subject_name_snapshot=self.source.subject_name,
            source_url="https://example.edu/it-standard",
            pdf_file="curriculum_standards/tests/it-2025.pdf",
            pdf_sha256="1" * 64,
            pdf_size_bytes=1024,
            pdf_page_count=100,
            content_hash="2" * 64,
            extraction_status=CurriculumExtractionStatus.COMPLETED,
            created_by=self.admin,
        )
        self.nodes = []
        for order, (node_type, code, title) in enumerate(
            (
                (CurriculumNodeType.CORE_COMPETENCY, "IT.CORE", "核心素养"),
                (CurriculumNodeType.COURSE_OBJECTIVE, "IT.OBJECTIVE", "课程目标"),
                (CurriculumNodeType.COURSE_CONTENT, "IT.CONTENT", "课程内容"),
                (CurriculumNodeType.ACADEMIC_QUALITY, "IT.QUALITY", "学业质量"),
            ),
            start=1,
        ):
            self.nodes.append(
                CurriculumStandardNode.objects.create(
                    version=self.version,
                    node_type=node_type,
                    code=code,
                    title=title,
                    content=f"{title}原文：运用数据表示方法解决真实问题，并说明选择依据。" * 8,
                    source_page_start=order,
                    source_page_end=order,
                    source_paragraph=title,
                    sort_order=order,
                )
            )
        CurriculumStandardVersion.objects.filter(pk=self.version.pk).update(
            status=CurriculumVersionStatus.PUBLISHED,
            reviewed_by=self.admin,
            published_by=self.admin,
        )
        CurriculumStandard.objects.filter(pk=self.source.pk).update(
            current_version=self.version,
        )
        self.version.refresh_from_db()
        self.source.refresh_from_db()
        rebuild_retrieval_index(self.version, actor=self.admin)
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    @property
    def list_url(self):
        return reverse("analytics_api:teacher_evaluation_ai_drafts")

    def detail_url(self, session_id, action=""):
        names = {
            "": "teacher_evaluation_ai_draft_detail",
            "retrieve": "teacher_evaluation_ai_draft_retrieve",
            "suggest": "teacher_evaluation_ai_draft_suggest_modes",
            "confirm": "teacher_evaluation_ai_draft_confirm_modes",
            "generate": "teacher_evaluation_ai_draft_generate",
            "save": "teacher_evaluation_ai_draft_save_plan",
            "cancel": "teacher_evaluation_ai_draft_cancel",
        }
        return reverse(f"analytics_api:{names[action]}", kwargs={"pk": session_id})

    def context_payload(self):
        return {
            "course_id": self.course.id,
            "school_stage": SchoolStage.SENIOR_HIGH,
            "grade_or_stage": "高一年级",
            "unit_title": "数据表示与可视化",
            "curriculum_standard_version_id": self.version.id,
            "course_content": "围绕校园真实数据，选择适切的数据表示方法并解释设计依据。",
            "evaluation_purpose": "project",
        }

    def ai_mode_payload(self):
        return {
            "suggested_modes": [
                {
                    "mode": "project",
                    "rationale": "真实数据作品能够同时观察问题解决过程与作品质量。",
                    "suitable_materials": ["artifact", "operation", "observation"],
                    "cautions": ["同时保留个人说明，避免只依据小组作品。"],
                    "recommended": True,
                },
                {
                    "mode": "oral_defense",
                    "rationale": "通过答辩核验学生对表示方法选择依据的理解。",
                    "suitable_materials": ["oral_defense"],
                    "cautions": [],
                    "recommended": True,
                },
            ]
        }

    def ai_draft_payload(self):
        node_ids = [node.id for node in self.nodes]
        return {
            "plan_draft": {
                "title": "数据表示项目评价方案",
                "content_version": "2025",
                "target_students": "高一年级本课程学习者",
                "learning_goal": "能够依据问题情境选择数据表示方法并解释其适切性。",
                "learning_goals": [
                    {
                        "code": "G1",
                        "title": "选择数据表示方法",
                        "description": "依据数据特征与表达目的选择表示方法并说明理由。",
                        "curriculum_node_ids": node_ids,
                    }
                ],
                "evaluation_basis": [
                    {
                        "code": "B1",
                        "goal_codes": ["G1"],
                        "description": "作品、操作过程和答辩共同呈现目标达成情况。",
                        "source_types": ["artifact", "operation", "oral_defense"],
                    }
                ],
                "learning_activities": [
                    {
                        "code": "A1",
                        "title": "校园数据可视化项目",
                        "goal_codes": ["G1"],
                        "description": "形成数据作品并解释视觉编码选择。",
                    }
                ],
                "learning_tasks": [
                    {
                        "code": "L1",
                        "title": "完成项目作品",
                        "basis_codes": ["B1"],
                        "description": "完成作品、过程记录和个人说明。",
                    }
                ],
                "evaluation_tasks": [
                    {
                        "code": "T1",
                        "title": "数据可视化项目",
                        "goal_codes": ["G1"],
                        "activity_codes": ["A1"],
                        "mode": "project",
                        "component_modes": [],
                        "evidence_ownership": "both",
                        "material_types": [
                            "artifact",
                            "operation_record",
                            "project_process",
                            "presentation",
                        ],
                        "weight": 100,
                        "description": "综合作品、操作过程、观察记录和答辩进行评价。",
                    }
                ],
                "content_scope": ["数据表示", "数据可视化"],
                "thinking_requirements": ["apply", "evaluate", "create"],
                "support_options": ["提供数据字典", "允许使用可视化工具"],
                "scoring_rules": {
                    "approach": "依据评价指标分别判断表现水平。",
                    "decision_rule": "材料缺失或设备故障时暂不评价，不计为低水平。",
                },
                "follow_up_suggestion": "根据目标级材料安排表示方法辨析或拓展项目。",
            },
            "standard_draft": {
                "title": "数据表示项目评价标准",
                "evaluation_target": "数据表示作品、操作过程与个人答辩",
                "criteria": [
                    {
                        "code": "C1",
                        "dimension": "subject_practice",
                        "title": "表示方法的适切性",
                        "evaluation_target": "作品及其设计说明",
                        "evaluation_sources": ["artifact", "operation", "oral_defense"],
                        "learning_goal_codes": ["G1"],
                        "evaluation_task_codes": ["T1"],
                        "evidence_ownership": "both",
                        "material_types": ["artifact", "operation", "observation", "oral_defense"],
                        "expected_performance": "能够结合数据特征和表达目的说明表示方法选择依据。",
                        "skip_condition": "未获得操作机会、设备故障或材料缺失时暂不评价。",
                        "support_options": ["提供术语提示"],
                        "common_problems": ["只描述图表外观，未说明选择依据"],
                        "level_descriptions": {
                            "1": "在充分帮助下能够指出一种数据表示方法。",
                            "2": "能够选择表示方法，但对选择依据说明不完整。",
                            "3": "能够结合主要数据特征说明表示方法的基本适切性。",
                            "4": "能够比较不同方法并以证据说明当前方案的优势与限制。",
                            "5": "能够根据表达效果迭代方案，并迁移形成可解释的选择原则。",
                        },
                        "scoring_examples": [
                            {
                                "level": 3,
                                "title": "基本达成示例",
                                "example_description": "作品可读，能够说明主要变量与视觉编码的对应关系。",
                            },
                            {
                                "level": 5,
                                "title": "迁移创新示例",
                                "example_description": "比较多个方案并依据受众反馈迭代，清楚说明权衡。",
                            },
                        ],
                        "follow_up_suggestion": "对依据不充分者安排对比辨析，对高水平者增加复杂数据挑战。",
                    }
                ],
            },
        }

    def create_and_retrieve(self):
        response = self.client.post(self.list_url, self.context_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        session_id = response.data["data"]["id"]
        response = self.client.post(self.detail_url(session_id, "retrieve"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {row["node_type"] for row in response.data["data"]["curriculum_references"]},
            set(CurriculumNodeType.values),
        )
        return AIEvaluationDraftSession.objects.get(pk=session_id)

    def generated_session(self):
        session = self.create_and_retrieve()
        with patch("learning_analytics.tasks.run_ai_evaluation_drafting_task.apply_async"):
            response = self.client.post(self.detail_url(session.id, "suggest"), {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        session.refresh_from_db()
        with patch(
            "api.services._call_teacher_chat_json",
            return_value=(self.ai_mode_payload(), json.dumps(self.ai_mode_payload(), ensure_ascii=False)),
        ):
            result = execute_generation_stage(
                session_id=session.id,
                task_kind=AIEvaluationTaskKind.SUGGEST_MODES,
                task_id=session.celery_task_id,
            )
        self.assertEqual(result["status"], "succeeded")
        response = self.client.post(
            self.detail_url(session.id, "confirm"),
            {"modes": ["project", "oral_defense"], "teacher_note": "保留个人答辩材料。"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        with patch("learning_analytics.tasks.run_ai_evaluation_drafting_task.apply_async"):
            response = self.client.post(self.detail_url(session.id, "generate"), {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        session.refresh_from_db()
        draft_payload = self.ai_draft_payload()
        with patch(
            "api.services._call_teacher_chat_json",
            return_value=(draft_payload, json.dumps(draft_payload, ensure_ascii=False)),
        ):
            result = execute_generation_stage(
                session_id=session.id,
                task_kind=AIEvaluationTaskKind.GENERATE_DRAFT,
                task_id=session.celery_task_id,
            )
        self.assertEqual(result["status"], "succeeded")
        session.refresh_from_db()
        self.assertEqual(session.status, AIEvaluationDraftStatus.DRAFT_GENERATED)
        return session

    def test_current_published_alias_match_permissions_and_no_pii(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200, response.data)
        options = response.data["data"]["curriculum_standard_versions"]
        self.assertEqual([row["id"] for row in options], [self.version.id])
        self.assertEqual(options[0]["compatible_course_ids"], [self.course.id])

        response = self.client.post(self.list_url, self.context_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        session_id = response.data["data"]["id"]
        other_client = APIClient()
        other_client.force_authenticate(self.other_teacher)
        response = other_client.get(self.detail_url(session_id))
        self.assertEqual(response.status_code, 404)

        same_school_client = APIClient()
        same_school_client.force_authenticate(self.same_school_teacher)
        response = same_school_client.get(self.detail_url(session_id))
        self.assertEqual(response.status_code, 404)

        for unauthorized_user in (self.admin, self.school_admin, self.student):
            unauthorized_client = APIClient()
            unauthorized_client.force_authenticate(unauthorized_user)
            response = unauthorized_client.get(self.list_url)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(APIClient().get(self.list_url).status_code, 403)

        pii_payload = self.context_payload()
        pii_payload["course_content"] = "请分析学生姓名：张三的手机号13800138000。"
        response = self.client.post(self.list_url, pii_payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(AIEvaluationDraftSession.objects.count(), 1)

    def test_reviewed_only_version_is_rejected_for_new_draft(self):
        CurriculumStandardVersion.objects.filter(pk=self.version.pk).update(
            status=CurriculumVersionStatus.REVIEWED
        )
        response = self.client.post(self.list_url, self.context_payload(), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("curriculum_standard_version_id", response.data["errors"])

    def test_two_stage_background_idempotency_and_generation_audit(self):
        session = self.create_and_retrieve()
        with patch(
            "learning_analytics.tasks.run_ai_evaluation_drafting_task.apply_async"
        ) as dispatch:
            first = self.client.post(self.detail_url(session.id, "suggest"), {}, format="json")
            second = self.client.post(self.detail_url(session.id, "suggest"), {}, format="json")
        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(second.status_code, 202, second.data)
        dispatch.assert_called_once()
        args = dispatch.call_args.kwargs.get("args")
        self.assertEqual(args, [session.id, AIEvaluationTaskKind.SUGGEST_MODES])
        self.assertNotIn("key", json.dumps(dispatch.call_args.kwargs).lower())

        session.refresh_from_db()
        with patch(
            "api.services._call_teacher_chat_json",
            return_value=(self.ai_mode_payload(), json.dumps(self.ai_mode_payload(), ensure_ascii=False)),
        ):
            result = execute_generation_stage(
                session_id=session.id,
                task_kind=AIEvaluationTaskKind.SUGGEST_MODES,
                task_id=session.celery_task_id,
            )
        self.assertEqual(result["status"], "succeeded")
        record = AIEvaluationGenerationRecord.objects.get()
        self.assertEqual(record.raw_response_text, json.dumps(self.ai_mode_payload(), ensure_ascii=False))
        self.assertEqual(record.generation_config["temperature"], 0.4)
        self.assertEqual(record.generation_config["prompt_version"], "ai_evaluation_drafting_v2")
        serialized = json.dumps(
            {
                "prompt": [record.system_prompt, record.user_prompt],
                "config": record.generation_config,
            },
            ensure_ascii=False,
        ).lower()
        self.assertNotIn("authorization", serialized)
        self.assertNotIn("api_key", serialized)

    def test_teacher_can_regenerate_incomplete_draft_without_overwriting_generation_audit(self):
        session = self.generated_session()
        first_draft_record = session.generation_records.get(stage="evaluation_draft")

        with patch(
            "learning_analytics.tasks.run_ai_evaluation_drafting_task.apply_async"
        ) as dispatch:
            response = self.client.post(
                self.detail_url(session.id, "generate"),
                {"regenerate": True},
                format="json",
            )

        self.assertEqual(response.status_code, 202, response.data)
        dispatch.assert_called_once()
        session.refresh_from_db()
        self.assertEqual(session.status, AIEvaluationDraftStatus.DRAFT_QUEUED)
        self.assertEqual(session.plan_draft, {})
        self.assertEqual(session.standard_draft, {})
        self.assertTrue(
            AIEvaluationGenerationRecord.objects.filter(pk=first_draft_record.pk).exists()
        )

        repaired_payload = self.ai_draft_payload()
        with patch(
            "api.services._call_teacher_chat_json",
            return_value=(
                repaired_payload,
                json.dumps(repaired_payload, ensure_ascii=False),
            ),
        ):
            result = execute_generation_stage(
                session_id=session.id,
                task_kind=AIEvaluationTaskKind.GENERATE_DRAFT,
                task_id=session.celery_task_id,
            )

        self.assertEqual(result["status"], "succeeded")
        session.refresh_from_db()
        self.assertEqual(session.status, AIEvaluationDraftStatus.DRAFT_GENERATED)
        self.assertEqual(
            session.generation_records.filter(stage="evaluation_draft").count(),
            2,
        )

    def test_structural_repair_recovers_common_model_shape_errors(self):
        session = self.generated_session()
        malformed = self.ai_draft_payload()
        source_goals = malformed["plan_draft"]["learning_goals"]
        malformed["plan_draft"]["learning_goals"] = [row["code"] for row in source_goals]
        malformed["plan_draft"]["learning_goal"] = source_goals
        malformed["plan_draft"]["evaluation_basis"] = []
        malformed["plan_draft"]["content_scope"] = []
        malformed["plan_draft"]["thinking_requirements"] = []
        malformed["plan_draft"]["scoring_rules"] = {"approach": "", "decision_rule": ""}
        malformed["standard_draft"]["criteria"][0]["level_descriptions"] = [
            {"level": level, "description": f"第 {level} 级可观察表现"}
            for level in range(1, 6)
        ]
        for row in malformed["plan_draft"]["learning_activities"]:
            row["goal_codes"] = []
        for row in malformed["plan_draft"]["learning_tasks"]:
            row["basis_codes"] = []
        for criterion in malformed["standard_draft"]["criteria"]:
            for example in criterion["scoring_examples"]:
                example["title"] = ""
                example["example_description"] = ""

        plan = _normalize_plan_draft(malformed["plan_draft"], session=session)
        standard = _normalize_standard_draft(malformed["standard_draft"], plan=plan)
        repairs = _repair_ai_draft_structure(
            session=session,
            plan=plan,
            standard=standard,
        )
        checks = run_automatic_checks(session=session, plan=plan, standard=standard)

        self.assertTrue(plan["learning_goals"])
        self.assertTrue(plan["evaluation_basis"])
        self.assertIn("evaluation_basis_created", repairs)
        self.assertIn("scoring_examples_completed", repairs)
        self.assertEqual(
            standard["criteria"][0]["level_descriptions"]["1"],
            "第 1 级可观察表现",
        )
        self.assertFalse(checks["blocked"], checks)

    def test_structural_repair_keeps_task_goals_aligned_with_added_activity(self):
        session = self.generated_session()
        payload = self.ai_draft_payload()
        node_ids = [node.id for node in self.nodes]
        payload["plan_draft"]["learning_goals"].append(
            {
                "code": "G2",
                "title": "解释数据表示结果",
                "description": "能够结合任务要求解释数据表示结果。",
                "curriculum_node_ids": node_ids,
            }
        )
        payload["plan_draft"]["evaluation_basis"][0]["goal_codes"].append("G2")
        payload["plan_draft"]["learning_activities"].append(
            {
                "code": "A2",
                "title": "解释与交流",
                "goal_codes": ["G2"],
                "description": "学生说明数据表示方案并回应问题。",
            }
        )

        plan = _normalize_plan_draft(payload["plan_draft"], session=session)
        standard = _normalize_standard_draft(payload["standard_draft"], plan=plan)
        _repair_ai_draft_structure(session=session, plan=plan, standard=standard)
        checks = run_automatic_checks(session=session, plan=plan, standard=standard)
        task = plan["evaluation_tasks"][0]

        self.assertIn("A2", task["activity_codes"])
        self.assertIn("G2", task["goal_codes"])
        self.assertFalse(checks["blocked"], checks)

    def test_project_draft_uses_p2_materials_and_persists_standard_and_examples(self):
        session = self.generated_session()
        task = session.plan_draft["evaluation_tasks"][0]
        self.assertEqual(task["mode"], "project")
        self.assertEqual(
            set(task["material_types"]),
            {"artifact", "operation", "observation", "oral_defense"},
        )
        checks = {row["code"]: row for row in session.automatic_check_result["checks"]}
        self.assertEqual(checks["scoring_examples"]["status"], "passed")
        self.assertIn("作品材料", session.standard_draft["criteria"][0]["evaluation_sources"])
        review_items = _review_item_map(session.plan_draft, session.standard_draft)
        decisions = [
            {
                "item_key": key,
                "item_type": value["item_type"],
                "item_code": value["item_code"],
                "decision": "accepted",
            }
            for key, value in review_items.items()
        ]
        response = self.client.post(
            self.detail_url(session.id, "save"),
            {
                "plan_draft": session.plan_draft,
                "standard_draft": session.standard_draft,
                "review_decisions": decisions,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["data"]["standard"]["ai_assisted"])
        plan = EvaluationPlan.objects.get()
        standard = EvaluationStandard.objects.get()
        self.assertEqual(plan.review_status, EvaluationReviewStatus.DRAFT)
        self.assertEqual(standard.review_status, EvaluationReviewStatus.DRAFT)
        self.assertEqual(standard.plan_id, plan.id)
        self.assertIsNone(standard.plan_version_id)
        self.assertFalse(plan.versions.exists())
        self.assertFalse(standard.versions.exists())
        self.assertEqual(len(standard.criteria[0]["scoring_examples"]), 2)
        session.refresh_from_db()
        self.assertEqual(session.linked_plan_id, plan.id)
        self.assertEqual(session.linked_standard_id, standard.id)

        # 课时设计中的人工继续操作：AI 只保存草稿，教师明确复核后才形成版本。
        response = self.client.post(
            f"/api/v1/teacher/evaluations/plans/{plan.id}/review-confirm/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            f"/api/v1/teacher/evaluations/plans/{plan.id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        plan_version_id = response.data["data"]["latest_version"]["id"]

        response = self.client.patch(
            f"/api/v1/teacher/evaluations/standards/{standard.id}/",
            {"plan_version": plan_version_id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            f"/api/v1/teacher/evaluations/standards/{standard.id}/review-confirm/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            f"/api/v1/teacher/evaluations/standards/{standard.id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        standard.refresh_from_db()
        self.assertEqual(standard.plan_version_id, plan_version_id)
        self.assertEqual(standard.versions.count(), 1)

    def test_save_rejects_partial_teacher_review(self):
        session = self.generated_session()
        response = self.client.post(
            self.detail_url(session.id, "save"),
            {
                "plan_draft": session.plan_draft,
                "standard_draft": session.standard_draft,
                "review_decisions": [
                    {
                        "item_key": "overall:plan",
                        "item_type": "overall",
                        "item_code": "plan",
                        "decision": "accepted",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(EvaluationPlan.objects.count(), 0)
        self.assertEqual(EvaluationStandard.objects.count(), 0)

    def test_save_rechecks_teacher_edits_and_rejects_blocked_mappings(self):
        session = self.generated_session()
        review_items = _review_item_map(session.plan_draft, session.standard_draft)
        decisions = [
            {
                "item_key": key,
                "item_type": value["item_type"],
                "item_code": value["item_code"],
                "decision": "accepted",
            }
            for key, value in review_items.items()
        ]
        bad_weight = deepcopy(session.plan_draft)
        bad_weight["evaluation_tasks"][0]["weight"] = 90
        response = self.client.post(
            self.detail_url(session.id, "save"),
            {
                "plan_draft": bad_weight,
                "standard_draft": session.standard_draft,
                "review_decisions": decisions,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        blocked_codes = {
            row["code"] for row in response.data["errors"]["checks"]
        }
        self.assertIn("weight_total", blocked_codes)

        bad_mapping = deepcopy(session.plan_draft)
        bad_mapping["evaluation_basis"][0]["goal_codes"] = ["UNKNOWN"]
        response = self.client.post(
            self.detail_url(session.id, "save"),
            {
                "plan_draft": bad_mapping,
                "standard_draft": session.standard_draft,
                "review_decisions": decisions,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        blocked_codes = {
            row["code"] for row in response.data["errors"]["checks"]
        }
        self.assertIn("basis_goal_alignment", blocked_codes)
        self.assertEqual(EvaluationPlan.objects.count(), 0)

    def test_dispatch_failure_is_persisted_and_retryable(self):
        session = self.create_and_retrieve()
        with patch(
            "learning_analytics.tasks.run_ai_evaluation_drafting_task.apply_async",
            side_effect=RuntimeError("broker offline"),
        ):
            response = self.client.post(self.detail_url(session.id, "suggest"), {}, format="json")
        self.assertEqual(response.status_code, 503, response.data)
        session.refresh_from_db()
        self.assertEqual(session.status, AIEvaluationDraftStatus.FAILED)
        self.assertEqual(session.last_error_code, "broker_unavailable")
        first_task_id = session.celery_task_id
        with patch("learning_analytics.tasks.run_ai_evaluation_drafting_task.apply_async") as dispatch:
            response = self.client.post(self.detail_url(session.id, "suggest"), {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        session.refresh_from_db()
        self.assertNotEqual(session.celery_task_id, first_task_id)
        self.assertEqual(session.dispatch_count, 2)
        dispatch.assert_called_once()
