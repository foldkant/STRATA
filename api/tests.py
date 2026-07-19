from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import (
    ClassroomActivity,
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Resource,
    Subject,
)
from learning.models import LearningEvent, QuestionBankItem, TestAssessment, TestAssessmentQuestion, TestAttempt, TestAttemptAnswer
from learning_analytics.models import (
    AssessmentResultFact,
    LearningEventV2,
    LearningOpportunity,
    LearningOpportunityTransitionFact,
    ParticipationPointLedger,
)
from realtime.models import ClassroomChatConfig, ClassroomChatMessage
from realtime.moderation import moderate_content
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment

from api.services import (
    ServiceError,
    _has_executable_interactive_block,
    _learning_page_generation_mode,
    clean_learning_web_page_schema,
    generate_learning_web_page_schema,
    generate_question_bank_drafts_with_ai,
)


class LearningPageAnimationTests(SimpleTestCase):
    def setUp(self):
        self.lesson = SimpleNamespace(
            title="数据编码",
            course=SimpleNamespace(title="数据与计算", subject_id=None),
        )

    def test_auto_mode_uses_interactive_for_animation_requirement(self):
        self.assertEqual(_learning_page_generation_mode("制作一个可播放的编码动画", "auto"), "interactive")
        self.assertEqual(_learning_page_generation_mode("制作知识梳理任务单", "auto"), "structured")

    def test_interactive_cleaner_preserves_executable_code(self):
        schema = clean_learning_web_page_schema(
            {
                "title": "动画任务单",
                "blocks": [
                    {
                        "id": "animation",
                        "type": "interactive",
                        "title": "编码动画",
                        "html": '<button id="play">播放</button><div id="dot"></div>',
                        "css": "#dot{width:20px;height:20px;background:blue}",
                        "javascript": "document.getElementById('play').addEventListener('click', () => document.getElementById('dot').animate([{transform:'translateX(0)'},{transform:'translateX(200px)'}], 800));",
                    }
                ],
            }
        )
        self.assertTrue(_has_executable_interactive_block(schema))

    @patch("api.services._call_teacher_chat_json")
    def test_interactive_mode_repairs_static_first_result(self, chat_mock):
        chat_mock.side_effect = [
            {
                "title": "静态结果",
                "blocks": [
                    {
                        "id": "steps",
                        "type": "steps",
                        "title": "编码步骤",
                        "items": [{"title": "输入", "body": "输入字符"}],
                    }
                ],
            },
            {
                "title": "动画结果",
                "blocks": [
                    {
                        "id": "animation",
                        "type": "interactive",
                        "title": "编码动画",
                        "html": '<button id="play">播放</button><div id="dot"></div>',
                        "css": "#dot{width:20px;height:20px;background:blue}",
                        "javascript": "document.getElementById('play').addEventListener('click', () => document.getElementById('dot').animate([{opacity:0},{opacity:1}], 800));",
                    }
                ],
            },
        ]

        schema = generate_learning_web_page_schema(
            object(),
            self.lesson,
            "制作一个可以播放的数据编码动画",
            generation_mode="interactive",
        )

        self.assertEqual(chat_mock.call_count, 2)
        self.assertTrue(_has_executable_interactive_block(schema))

    def test_invalid_generation_mode_is_rejected(self):
        with self.assertRaises(ServiceError):
            _learning_page_generation_mode("制作任务单", "unsafe")

    @patch("api.services.write_audit")
    @patch("api.services._call_teacher_chat_json")
    def test_question_bank_ai_drafts_are_cleaned(self, chat_mock, _audit_mock):
        chat_mock.return_value = {
            "questions": [
                {
                    "question_type": "single",
                    "stem": "十进制 2 的二进制表示是？",
                    "options": ["10", "11", "01", "00"],
                    "answer": ["10"],
                    "analysis": "2 对应二进制 10。",
                    "difficulty": "easy",
                    "knowledge_point": "二进制编码",
                    "default_score": 2,
                },
                {
                    "question_type": "single",
                    "stem": "无效题目",
                    "options": ["A"],
                    "answer": ["A"],
                },
                {
                    "question_type": "single",
                    "stem": "答案结构错误的题目",
                    "options": ["A", "B", "C", "D"],
                    "answer": {"value": "A"},
                    "default_score": "NaN",
                },
            ]
        }
        request = SimpleNamespace(user=SimpleNamespace(school=SimpleNamespace()))
        result = generate_question_bank_drafts_with_ai(
            request,
            {"direction": "考查二进制转换", "question_type": "single", "difficulty": "easy", "count": 3},
            subject_name="信息科技",
        )
        self.assertEqual(result["requested_count"], 3)
        self.assertEqual(result["valid_count"], 1)
        self.assertEqual(result["questions"][0]["answer"], ["10"])


class ClassroomChatModerationRuleTests(SimpleTestCase):
    def test_normalizes_obfuscation_and_flags_standalone_abuse(self):
        spaced = moderate_content("你这个傻 · 逼")
        self.assertTrue(spaced.flagged)
        self.assertEqual(spaced.severity, "moderate")

        standalone = moderate_content("垃圾")
        self.assertTrue(standalone.flagged)
        self.assertEqual(standalone.severity, "mild")


class AssessmentWorkflowTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="测试学校", code="TEST-SCHOOL")
        self.subject = Subject.objects.create(school=self.school, name="信息科技", code="IT")
        self.class_group = ClassGroup.objects.create(school=self.school, name="高一1班", grade="高一")
        self.other_class = ClassGroup.objects.create(school=self.school, name="高一2班", grade="高一")
        self.teacher = User.objects.create_user(
            username="teacher1", password="Teacher123!", role=User.Role.TEACHER, school=self.school, display_name="教师一"
        )
        self.teacher2 = User.objects.create_user(
            username="teacher2", password="Teacher123!", role=User.Role.TEACHER, school=self.school, display_name="教师二"
        )
        self.school_admin = User.objects.create_user(
            username="school_admin1",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
            display_name="学校管理员",
        )
        TeachingAssignment.objects.create(school=self.school, class_group=self.class_group, teacher=self.teacher)
        TeachingAssignment.objects.create(school=self.school, class_group=self.class_group, teacher=self.teacher2)
        self.student = User.objects.create_user(
            username="student1", password="123456", role=User.Role.STUDENT, school=self.school, display_name="学生一"
        )
        StudentProfile.objects.create(user=self.student, class_group=self.class_group, is_first_use=False)
        self.other_student = User.objects.create_user(
            username="student2", password="123456", role=User.Role.STUDENT, school=self.school, display_name="学生二"
        )
        StudentProfile.objects.create(user=self.other_student, class_group=self.other_class, is_first_use=False)
        self.client = APIClient()

    def test_shared_question_and_student_auto_grading_workflow(self):
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/v1/teacher/question-bank/",
            {
                "subject": self.subject.id,
                "stem": "十进制 2 的二进制表示是？",
                "question_type": "single",
                "options": ["10", "11", "01"],
                "answer": ["10"],
                "analysis": "2 = 1×2¹ + 0×2⁰",
                "difficulty": "easy",
                "knowledge_point": "二进制",
                "default_score": 5,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        question_id = response.data["data"]["id"]
        self.assertEqual(response.data["data"]["status"], QuestionBankItem.Status.DRAFT)
        self.assertEqual(
            response.data["data"]["library_scope"],
            QuestionBankItem.LibraryScope.PERSONAL,
        )
        question = QuestionBankItem.objects.get(pk=question_id)
        self.assertEqual(question.versions.count(), 1)

        self.client.force_authenticate(self.teacher2)
        response = self.client.get("/api/v1/teacher/question-bank/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(item["id"] == question_id for item in response.data["data"]))

        self.client.force_authenticate(self.school_admin)
        response = self.client.get("/api/v1/school-admin/question-reviews/")
        self.assertFalse(
            any(item["id"] == question_id for item in response.data["data"]["results"])
        )

        self.client.force_authenticate(self.teacher)
        compose = self.client.get("/api/v1/teacher/question-bank/?scope=compose")
        self.assertTrue(any(item["id"] == question_id for item in compose.data["data"]))
        response = self.client.post(
            f"/api/v1/teacher/question-bank/{question_id}/action/",
            {"action": "submit_review"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], QuestionBankItem.Status.PENDING_REVIEW)
        self.assertEqual(
            response.data["data"]["library_scope"],
            QuestionBankItem.LibraryScope.SCHOOL,
        )

        self.client.force_authenticate(self.school_admin)
        review_list = self.client.get("/api/v1/school-admin/question-reviews/?status=pending_review")
        self.assertEqual(review_list.status_code, 200)
        self.assertTrue(any(item["id"] == question_id for item in review_list.data["data"]["results"]))
        response = self.client.post(
            f"/api/v1/school-admin/question-reviews/{question_id}/action/",
            {"action": "approve_trial"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], QuestionBankItem.Status.TRIAL)

        self.client.force_authenticate(self.teacher)
        compose = self.client.get("/api/v1/teacher/question-bank/?scope=compose")
        self.assertTrue(any(item["id"] == question_id for item in compose.data["data"]))
        response = self.client.post(
            "/api/v1/teacher/assessments/",
            {
                "title": "第一单元测试",
                "subject": self.subject.id,
                "course": "",
                "class_ids": [self.class_group.id],
                "instruction": "独立完成",
                "duration_minutes": 30,
                "start_at": "",
                "end_at": "",
                "show_score_after_submit": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        assessment_id = response.data["data"]["id"]
        response = self.client.put(
            f"/api/v1/teacher/assessments/{assessment_id}/questions/",
            {"questions": [{"question_id": question_id, "score": 5}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["total_score"], 5)
        self.assertEqual(self.client.post(f"/api/v1/teacher/assessments/{assessment_id}/publish/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/teacher/assessments/{assessment_id}/open/").status_code, 200)
        self.assertEqual(
            LearningOpportunity.objects.filter(
                student=self.student,
                content_type=LearningOpportunity.ContentType.QUESTION,
            ).count(),
            1,
        )

        self.client.force_authenticate(self.other_student)
        self.assertEqual(self.client.get(f"/api/v1/student/assessments/{assessment_id}/").status_code, 404)

        self.client.force_authenticate(self.student)
        response = self.client.post(f"/api/v1/student/assessments/{assessment_id}/start/")
        self.assertEqual(response.status_code, 200)
        student_detail = self.client.get(f"/api/v1/student/assessments/{assessment_id}/")
        student_question = student_detail.data["data"]["questions"][0]
        self.assertNotIn("source_question", student_question)
        self.assertNotIn("source_version", student_question)
        self.assertNotIn("source_status", student_question)
        assessment_question_id = student_question["id"]
        response = self.client.patch(
            f"/api/v1/student/assessments/{assessment_id}/answer/",
            {"question_id": assessment_question_id, "answer": ["10"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/api/v1/student/assessments/{assessment_id}/submit/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["total_score"], 5)
        attempt = TestAttempt.objects.get(assessment_id=assessment_id, student=self.student)
        self.assertEqual(attempt.status, TestAttempt.Status.GRADED)
        self.assertEqual(attempt.total_score, 5)
        submitted_event = LearningEventV2.objects.get(event_name="item.submitted")
        self.assertEqual(submitted_event.schema_version, "1.1")
        self.assertEqual(submitted_event.attempt_id, attempt.analytics_attempt_id)
        self.assertNotIn("answer", submitted_event.payload)
        graded_event = LearningEventV2.objects.get(event_name="item.graded")
        self.assertEqual(graded_event.schema_version, "1.1")
        result_fact = AssessmentResultFact.objects.get(grading_state="final")
        self.assertEqual(float(result_fact.score_raw), 5)
        self.assertEqual(result_fact.grader_type, "automatic")
        self.assertIsNone(result_fact.grader)
        self.assertEqual(result_fact.source_event.legacy_event.actor, self.student)

        self.client.force_authenticate(self.school_admin)
        response = self.client.post(
            f"/api/v1/school-admin/question-reviews/{question_id}/action/",
            {"action": "activate"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], QuestionBankItem.Status.ACTIVE)

        self.client.force_authenticate(self.teacher2)
        response = self.client.get("/api/v1/teacher/question-bank/")
        shared = next(item for item in response.data["data"] if item["id"] == question_id)
        self.assertFalse(shared["is_owner"])

        self.client.force_authenticate(self.teacher)
        dashboard_response = self.client.get("/api/v1/teacher/assessments/")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(dashboard_response.data["data"][0]["total_score"], 5)

    def test_teacher_close_auto_submits_in_progress_attempt(self):
        question = QuestionBankItem.objects.create(
            school=self.school, subject=self.subject, creator=self.teacher, stem="1+1=?", question_type="single",
            options=["1", "2"], answer=["2"], default_score=2, status=QuestionBankItem.Status.ACTIVE,
            library_scope=QuestionBankItem.LibraryScope.SCHOOL,
        )
        self.client.force_authenticate(self.teacher)
        assessment = self.client.post(
            "/api/v1/teacher/assessments/",
            {"title": "自动收卷测试", "subject": self.subject.id, "course": "", "class_ids": [self.class_group.id], "instruction": "", "duration_minutes": 30, "start_at": "", "end_at": "", "show_score_after_submit": True},
            format="json",
        ).data["data"]
        self.client.put(
            f"/api/v1/teacher/assessments/{assessment['id']}/questions/",
            {"questions": [{"question_id": question.id, "score": 2}]}, format="json",
        )
        self.client.post(f"/api/v1/teacher/assessments/{assessment['id']}/publish/")
        self.client.post(f"/api/v1/teacher/assessments/{assessment['id']}/open/")
        self.client.force_authenticate(self.student)
        self.client.post(f"/api/v1/student/assessments/{assessment['id']}/start/")
        self.client.force_authenticate(self.teacher)
        response = self.client.post(f"/api/v1/teacher/assessments/{assessment['id']}/close/")
        self.assertEqual(response.status_code, 200)
        attempt = TestAttempt.objects.get(assessment_id=assessment["id"], student=self.student)
        self.assertEqual(attempt.status, TestAttempt.Status.GRADED)
        self.assertIsNotNone(attempt.submitted_at)
        opportunity = LearningOpportunity.objects.get(student=self.student)
        self.assertTrue(
            opportunity.transition_facts.filter(state="submitted").exists()
        )
        self.assertTrue(opportunity.transition_facts.filter(state="graded").exists())
        self.assertFalse(opportunity.transition_facts.filter(state="withdrawn").exists())
        self.assertEqual(
            LearningEventV2.objects.filter(event_name="content.withdrawn").count(),
            1,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/teacher/assessments/{assessment['id']}/open/"
            ).status_code,
            400,
        )

    def test_personal_question_can_be_used_without_school_review(self):
        self.client.force_authenticate(self.teacher)
        question = self.client.post(
            "/api/v1/teacher/question-bank/",
            {
                "subject": self.subject.id,
                "stem": "本人直接使用的个人题目",
                "question_type": "judge",
                "options": ["正确", "错误"],
                "answer": ["正确"],
                "analysis": "个人题目无需共享审核。",
                "difficulty": "normal",
                "knowledge_point": "个人题库",
                "default_score": 2,
            },
            format="json",
        ).data["data"]
        assessment = self.client.post(
            "/api/v1/teacher/assessments/",
            {
                "title": "个人题目组卷测试",
                "subject": self.subject.id,
                "course": "",
                "class_ids": [self.class_group.id],
                "instruction": "",
                "duration_minutes": 30,
                "start_at": "",
                "end_at": "",
                "show_score_after_submit": True,
            },
            format="json",
        ).data["data"]
        saved = self.client.put(
            f"/api/v1/teacher/assessments/{assessment['id']}/questions/",
            {"questions": [{"question_id": question["id"], "score": 2}]},
            format="json",
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(
            saved.data["data"]["questions"][0]["source_status"],
            QuestionBankItem.Status.DRAFT,
        )

    def test_question_review_return_creates_new_content_version(self):
        self.client.force_authenticate(self.teacher)
        created = self.client.post(
            "/api/v1/teacher/question-bank/",
            {
                "subject": self.subject.id,
                "stem": "原始题干",
                "question_type": "judge",
                "options": ["正确", "错误"],
                "answer": ["正确"],
                "analysis": "原始解析",
                "difficulty": "normal",
                "knowledge_point": "审核测试",
                "default_score": 2,
            },
            format="json",
        ).data["data"]
        question_id = created["id"]

        self.assertEqual(
            self.client.post(
                f"/api/v1/school-admin/question-reviews/{question_id}/action/",
                {"action": "approve_trial"},
                format="json",
            ).status_code,
            403,
        )
        self.client.post(
            f"/api/v1/teacher/question-bank/{question_id}/action/",
            {"action": "submit_review"},
            format="json",
        )

        self.client.force_authenticate(self.school_admin)
        self.assertEqual(
            self.client.post(
                f"/api/v1/school-admin/question-reviews/{question_id}/action/",
                {"action": "return", "note": ""},
                format="json",
            ).status_code,
            400,
        )
        returned = self.client.post(
            f"/api/v1/school-admin/question-reviews/{question_id}/action/",
            {"action": "return", "note": "请补充题干背景。"},
            format="json",
        )
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.data["data"]["status"], QuestionBankItem.Status.DRAFT)

        self.client.force_authenticate(self.teacher)
        updated = self.client.patch(
            f"/api/v1/teacher/question-bank/{question_id}/",
            {
                "subject": self.subject.id,
                "stem": "补充背景后的题干",
                "question_type": "judge",
                "options": ["正确", "错误"],
                "answer": ["正确"],
                "analysis": "更新解析",
                "difficulty": "normal",
                "knowledge_point": "审核测试",
                "default_score": 2,
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["data"]["version_no"], 2)

        self.client.force_authenticate(self.school_admin)
        detail = self.client.get(f"/api/v1/school-admin/question-reviews/{question_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data["data"]["versions"]), 2)
        self.assertGreaterEqual(len(detail.data["data"]["lifecycle"]), 3)

    def test_randomized_question_and_option_orders_are_stable_per_attempt(self):
        questions = [
            QuestionBankItem.objects.create(
                school=self.school,
                subject=self.subject,
                creator=self.teacher,
                stem=f"随机测试题 {index}",
                question_type=QuestionBankItem.QuestionType.SINGLE,
                options=[f"选项 {index}-A", f"选项 {index}-B", f"选项 {index}-C", f"选项 {index}-D"],
                answer=[f"选项 {index}-A"],
                default_score=2,
                status=QuestionBankItem.Status.ACTIVE,
                library_scope=QuestionBankItem.LibraryScope.SCHOOL,
            )
            for index in range(1, 4)
        ]
        self.client.force_authenticate(self.teacher)
        assessment = self.client.post(
            "/api/v1/teacher/assessments/",
            {
                "title": "随机顺序测试",
                "subject": self.subject.id,
                "course": "",
                "class_ids": [self.class_group.id],
                "instruction": "",
                "duration_minutes": 30,
                "start_at": "",
                "end_at": "",
                "show_score_after_submit": True,
                "randomize_question_order": True,
                "randomize_option_order": True,
            },
            format="json",
        ).data["data"]
        saved = self.client.put(
            f"/api/v1/teacher/assessments/{assessment['id']}/questions/",
            {
                "questions": [{"question_id": item.id, "score": 2} for item in questions],
                "randomize_question_order": True,
                "randomize_option_order": True,
            },
            format="json",
        )
        self.assertTrue(saved.data["data"]["randomize_question_order"])
        self.assertTrue(saved.data["data"]["randomize_option_order"])
        self.client.post(f"/api/v1/teacher/assessments/{assessment['id']}/publish/")
        self.client.post(f"/api/v1/teacher/assessments/{assessment['id']}/open/")

        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post(f"/api/v1/student/assessments/{assessment['id']}/start/").status_code, 200)
        first = self.client.get(f"/api/v1/student/assessments/{assessment['id']}/").data["data"]["questions"]
        second = self.client.get(f"/api/v1/student/assessments/{assessment['id']}/").data["data"]["questions"]
        self.assertEqual(first, second)

        attempt = TestAttempt.objects.get(assessment_id=assessment["id"], student=self.student)
        self.assertEqual(set(attempt.question_order), {item["id"] for item in first})
        self.assertEqual(len(attempt.option_orders), 3)
        source_options = {
            row.id: set(row.options)
            for row in TestAssessmentQuestion.objects.filter(assessment_id=assessment["id"])
        }
        for row in first:
            self.assertEqual(set(row["options"]), source_options[row["id"]])

        first_question = first[0]
        source = TestAssessmentQuestion.objects.get(pk=first_question["id"])
        response = self.client.patch(
            f"/api/v1/student/assessments/{assessment['id']}/answer/",
            {"question_id": source.id, "answer": source.answer},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/api/v1/student/assessments/{assessment['id']}/submit/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["total_score"], 2)

    def test_subjective_grading_requires_every_text_question(self):
        assessment = TestAssessment.objects.create(
            school=self.school,
            teacher=self.teacher,
            subject=self.subject,
            title="主观题批阅测试",
        )
        assessment.target_classes.add(self.class_group)
        question_rows = [
            TestAssessmentQuestion.objects.create(
                assessment=assessment,
                question_type=QuestionBankItem.QuestionType.TEXT,
                stem=f"简答题 {index}",
                answer=[],
                analysis="评分参考",
                score=5,
                sort_order=index * 10,
            )
            for index in range(1, 3)
        ]
        self.client.force_authenticate(self.teacher)
        self.client.post(f"/api/v1/teacher/assessments/{assessment.id}/publish/")
        self.client.post(f"/api/v1/teacher/assessments/{assessment.id}/open/")
        self.client.force_authenticate(self.student)
        self.client.post(f"/api/v1/student/assessments/{assessment.id}/start/")
        for index, question in enumerate(question_rows, start=1):
            self.client.patch(
                f"/api/v1/student/assessments/{assessment.id}/answer/",
                {"question_id": question.id, "answer": [f"学生回答 {index}"]},
                format="json",
            )
        self.client.post(f"/api/v1/student/assessments/{assessment.id}/submit/")
        attempt = TestAttempt.objects.get(assessment=assessment, student=self.student)
        answer_rows = list(
            attempt.answer_rows.select_related("question").order_by("question__sort_order")
        )
        self.client.force_authenticate(self.teacher)
        pending_facts = AssessmentResultFact.objects.filter(grading_state="pending")
        self.assertEqual(pending_facts.count(), 2)
        self.assertTrue(all(item.score_raw is None for item in pending_facts))
        self.assertTrue(all(item.grader is None for item in pending_facts))

        response = self.client.patch(
            f"/api/v1/teacher/test-attempts/{attempt.id}/grade/",
            {"answers": [{"answer_id": answer_rows[0].id, "score": 4, "feedback": "继续完善"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("还有 1 道主观题未评分", response.data["message"])
        self.assertIsNone(TestAttemptAnswer.objects.get(pk=answer_rows[0].id).manual_score)

        response = self.client.patch(
            f"/api/v1/teacher/test-attempts/{attempt.id}/grade/",
            {
                "answers": [
                    {"answer_id": answer_rows[0].id, "score": 4, "feedback": "继续完善"},
                    {"answer_id": answer_rows[1].id, "score": 5, "feedback": "回答完整"},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, TestAttempt.Status.GRADED)
        self.assertEqual(attempt.subjective_score, 9)
        self.assertEqual(
            AssessmentResultFact.objects.filter(grading_state="final").count(),
            2,
        )
        self.assertEqual(
            LearningOpportunityTransitionFact.objects.filter(state="graded").count(),
            2,
        )

        revised = self.client.patch(
            f"/api/v1/teacher/test-attempts/{attempt.id}/grade/",
            {
                "answers": [
                    {
                        "answer_id": answer_rows[0].id,
                        "score": 3,
                        "feedback": "复核后调整",
                    },
                    {
                        "answer_id": answer_rows[1].id,
                        "score": 5,
                        "feedback": "回答完整",
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(revised.status_code, 200)
        revision_fact = AssessmentResultFact.objects.get(grading_state="revised")
        self.assertEqual(float(revision_fact.score_raw), 3)
        self.assertEqual(revision_fact.supersedes.grading_state, "final")
        self.assertEqual(revision_fact.grader, self.teacher)

    def test_question_requires_disable_before_delete(self):
        question = QuestionBankItem.objects.create(
            school=self.school,
            subject=self.subject,
            creator=self.teacher,
            stem="判断题",
            question_type=QuestionBankItem.QuestionType.JUDGE,
            options=["正确", "错误"],
            answer=["正确"],
            default_score=2,
        )
        self.client.force_authenticate(self.teacher)
        self.assertEqual(self.client.delete(f"/api/v1/teacher/question-bank/{question.id}/").status_code, 400)
        self.assertEqual(
            self.client.post(
                f"/api/v1/teacher/question-bank/{question.id}/action/",
                {"action": "disable"},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(self.client.delete(f"/api/v1/teacher/question-bank/{question.id}/").status_code, 200)

    @patch("api.assessment_views.generate_question_bank_drafts_with_ai")
    def test_ai_generate_endpoint_returns_drafts_without_saving(self, generate_mock):
        generate_mock.return_value = {
            "questions": [{
                "draft_id": "ai_test",
                "stem": "AI 草稿题",
                "question_type": "judge",
                "options": ["正确", "错误"],
                "answer": ["正确"],
                "analysis": "解析",
                "difficulty": "normal",
                "knowledge_point": "测试知识点",
                "default_score": 2,
                "selected": True,
            }],
            "requested_count": 1,
            "valid_count": 1,
        }
        self.client.force_authenticate(self.teacher)
        before = QuestionBankItem.objects.count()
        response = self.client.post(
            "/api/v1/teacher/question-bank/ai-generate/",
            {"subject": self.subject.id, "direction": "生成一题判断题", "question_type": "judge", "difficulty": "normal", "count": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["valid_count"], 1)
        self.assertEqual(QuestionBankItem.objects.count(), before)

    def test_ai_confirm_validates_and_bulk_creates_questions(self):
        self.client.force_authenticate(self.teacher)
        valid = {
            "draft_id": "ai_valid",
            "stem": "AI 生成的判断题",
            "question_type": "judge",
            "options": ["正确", "错误"],
            "answer": ["正确"],
            "analysis": "解析",
            "difficulty": "normal",
            "knowledge_point": "知识点",
            "default_score": 2,
            "selected": True,
        }
        response = self.client.post(
            "/api/v1/teacher/question-bank/ai-confirm/",
            {"subject": self.subject.id, "questions": [valid]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["created_count"], 1)
        created = QuestionBankItem.objects.get(stem="AI 生成的判断题", creator=self.teacher)
        self.assertEqual(created.status, QuestionBankItem.Status.DRAFT)
        self.assertEqual(created.source, QuestionBankItem.Source.AI)
        self.assertEqual(created.versions.count(), 1)

        invalid = {**valid, "stem": "无效 AI 题", "options": ["正确", "错误"], "answer": ["不存在"]}
        response = self.client.post(
            "/api/v1/teacher/question-bank/ai-confirm/",
            {"subject": self.subject.id, "questions": [valid, invalid]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(QuestionBankItem.objects.filter(stem="无效 AI 题").exists())


class StudentArchiveTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="档案测试学校", code="ARCHIVE-SCHOOL")
        self.subject = Subject.objects.create(school=self.school, name="信息科技", code="IT")
        self.class_group = ClassGroup.objects.create(school=self.school, name="高一1班", grade="高一")
        self.teacher = User.objects.create_user(
            username="archive_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
            display_name="档案教师",
        )
        self.student = User.objects.create_user(
            username="archive_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="张三",
        )
        self.other_student = User.objects.create_user(
            username="archive_other",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="李四",
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            student_no="2026001",
            current_layer=StudentProfile.Layer.A,
            score=88,
            is_first_use=False,
        )
        StudentProfile.objects.create(user=self.other_student, class_group=self.class_group, is_first_use=False)
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与计算",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(course=self.course, class_group=self.class_group, created_by=self.teacher)
        self.lesson = Lesson.objects.create(course=self.course, title="数据编码", is_active=True)
        self.step = LessonStep.objects.create(
            lesson=self.lesson,
            title="编码练习",
            status=LessonStep.Status.READY,
        )
        self.student_event = LearningEvent.objects.create(
            actor=self.student,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            event_type=LearningEvent.EventType.PAGE_VIEW,
            object_type="lesson_step",
            object_id=str(self.step.id),
            metadata={"action": "step_complete"},
            occurred_at=timezone.now(),
        )
        LearningEvent.objects.create(
            actor=self.other_student,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            event_type=LearningEvent.EventType.PAGE_VIEW,
            object_type="lesson_step",
            object_id=str(self.step.id),
            metadata={"action": "step_complete"},
            occurred_at=timezone.now(),
        )
        assessment = TestAssessment.objects.create(
            school=self.school,
            teacher=self.teacher,
            subject=self.subject,
            course=self.course,
            title="单元测试",
            status=TestAssessment.Status.CLOSED,
        )
        assessment.target_classes.add(self.class_group)
        TestAssessmentQuestion.objects.create(
            assessment=assessment,
            question_type=QuestionBankItem.QuestionType.JUDGE,
            stem="计算机使用二进制。",
            options=["正确", "错误"],
            answer=["正确"],
            score=2,
        )
        TestAttempt.objects.create(
            assessment=assessment,
            student=self.student,
            class_group=self.class_group,
            status=TestAttempt.Status.GRADED,
            objective_score=2,
            total_score=2,
            submitted_at=timezone.now(),
            graded_at=timezone.now(),
        )
        self.client = APIClient()

    def test_student_archive_is_private_and_supports_subject_filter(self):
        self.client.force_authenticate(self.student)
        response = self.client.get("/api/v1/student/profile/")
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["student"]["display_name"], "张三")
        self.assertNotIn("current_layer", data["student"])
        self.assertNotIn("score", data["student"])
        self.assertEqual(data["metrics"]["learning_event_count"], 1)
        self.assertEqual(data["metrics"]["completed_test_count"], 1)
        self.assertEqual(data["courses"][0]["completed_step_count"], 1)
        self.assertEqual(len(data["tests"]), 1)
        self.assertEqual([item["id"] for item in data["recent_events"]], [self.student_event.id])

        response = self.client.get(f"/api/v1/student/profile/?subject={self.subject.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["selected_subject"], self.subject.id)
        self.assertEqual(len(response.data["data"]["courses"]), 1)

        response = self.client.get("/api/v1/student/profile/?subject=999999")
        self.assertEqual(response.status_code, 404)


class ClassroomChatWorkflowTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="聊天测试学校", code="CHAT-SCHOOL")
        self.subject = Subject.objects.create(school=self.school, name="信息科技", code="IT")
        self.class_group = ClassGroup.objects.create(school=self.school, name="高一1班", grade="高一")
        self.other_class = ClassGroup.objects.create(school=self.school, name="高一2班", grade="高一")
        self.teacher = User.objects.create_user(
            username="chat_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
            display_name="方老师",
        )
        self.student = User.objects.create_user(
            username="chat_student1",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="张三",
        )
        self.classmate = User.objects.create_user(
            username="chat_student2",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="李四",
        )
        self.outsider = User.objects.create_user(
            username="chat_outsider",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="王五",
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            score=10,
            is_first_use=False,
        )
        StudentProfile.objects.create(user=self.classmate, class_group=self.class_group, is_first_use=False)
        StudentProfile.objects.create(user=self.outsider, class_group=self.other_class, is_first_use=False)
        TeachingAssignment.objects.create(school=self.school, class_group=self.class_group, teacher=self.teacher)
        self.course = Course.objects.create(subject=self.subject, title="数据与计算", teacher=self.teacher, is_active=True)
        CourseClass.objects.create(course=self.course, class_group=self.class_group, created_by=self.teacher)
        self.lesson = Lesson.objects.create(course=self.course, title="课堂聊天", is_active=True)
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="聊天课堂",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        self.client = APIClient()

    def set_user(self, user):
        self.client.force_authenticate(user)

    def enable(self, **overrides):
        payload = {
            "whole_class_enabled": False,
            "teacher_private_enabled": False,
            "group_chat_enabled": False,
            **overrides,
        }
        self.set_user(self.teacher)
        return self.client.patch(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/chat/settings/",
            payload,
            format="json",
        )

    def send(self, user, room_type, content, target_id=None):
        self.set_user(user)
        return self.client.post(
            f"/api/v1/{'teacher/classroom/sessions' if user.role == 'teacher' else 'student/classroom'}/{self.session.id}/chat/messages/",
            {"room_type": room_type, "target_id": target_id, "content": content},
            format="json",
        )

    def messages(self, user, room_type, target_id=None):
        self.set_user(user)
        prefix = "teacher/classroom/sessions" if user.role == "teacher" else "student/classroom"
        params = {"room_type": room_type}
        if target_id is not None:
            params["target_id"] = target_id
        return self.client.get(
            f"/api/v1/{prefix}/{self.session.id}/chat/messages/",
            params,
        )

    def test_rooms_default_closed_and_private_chat_is_isolated(self):
        response = self.send(self.student, "whole_class", "大家好")
        self.assertEqual(response.status_code, 403)

        response = self.enable(teacher_private_enabled=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["enabled"]["teacher_private"])

        response = self.send(self.student, "teacher_private", "老师，我有一个问题")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["sender"]["display_name"], "张三")

        teacher_messages = self.messages(self.teacher, "teacher_private", self.student.id)
        self.assertEqual(len(teacher_messages.data["data"]["messages"]), 1)
        classmate_messages = self.messages(self.classmate, "teacher_private")
        self.assertEqual(classmate_messages.status_code, 200)
        self.assertEqual(classmate_messages.data["data"]["messages"], [])
        self.set_user(self.classmate)
        classmate_context = self.client.get(f"/api/v1/student/classroom/{self.session.id}/chat/")
        self.assertEqual(classmate_context.data["data"]["threads"], [])

        self.set_user(self.outsider)
        response = self.client.get(f"/api/v1/student/classroom/{self.session.id}/chat/")
        self.assertEqual(response.status_code, 404)

    def test_flagged_message_waits_for_review_and_can_be_allowed(self):
        self.enable(whole_class_enabled=True)
        response = self.send(self.student, "whole_class", "你这个傻逼")
        self.assertEqual(response.status_code, 201)
        message_id = response.data["data"]["id"]
        self.assertEqual(response.data["data"]["moderation_status"], "pending")

        classmate_messages = self.messages(self.classmate, "whole_class")
        self.assertEqual(classmate_messages.data["data"]["messages"], [])

        self.set_user(self.teacher)
        queue = self.client.get(f"/api/v1/teacher/classroom/sessions/{self.session.id}/chat/moderation/")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(queue.data["data"]["count"], 1)
        self.assertIn("侮辱攻击", queue.data["data"]["results"][0]["moderation_categories"])

        reviewed = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/chat/messages/{message_id}/moderate/",
            {"action": "allow", "note": "结合上下文放行"},
            format="json",
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.data["data"]["moderation_status"], "visible")
        classmate_messages = self.messages(self.classmate, "whole_class")
        self.assertEqual(len(classmate_messages.data["data"]["messages"]), 1)

    def test_teacher_confirms_deduction_and_learning_event_is_recorded(self):
        self.enable(whole_class_enabled=True)
        response = self.send(self.student, "whole_class", "我要打死你")
        message_id = response.data["data"]["id"]
        self.assertEqual(response.data["data"]["severity"], "severe")

        self.set_user(self.teacher)
        response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/chat/messages/{message_id}/moderate/",
            {"action": "deduct", "points": 5, "note": "严重威胁性言论"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 5)
        message = ClassroomChatMessage.objects.get(pk=message_id)
        self.assertEqual(message.review_action, "deduct")
        self.assertEqual(message.deduction_points, 5)
        event = LearningEvent.objects.get(object_type="classroom_chat_message", object_id=str(message_id), event_type="teacher_intervention")
        self.assertEqual(event.actor, self.student)
        self.assertEqual(event.score, -5)
        analytics_event = LearningEventV2.objects.get(legacy_event=event)
        self.assertEqual(analytics_event.actor, self.teacher)
        self.assertEqual(analytics_event.target_student, self.student)
        ledger = ParticipationPointLedger.objects.get(source_event=analytics_event)
        self.assertEqual(float(ledger.delta), -5)
        self.assertEqual(float(ledger.balance_after), 5)

        student_messages = self.messages(self.student, "whole_class")
        self.assertEqual(student_messages.data["data"]["messages"], [])
        teacher_messages = self.messages(self.teacher, "whole_class")
        self.assertEqual(len(teacher_messages.data["data"]["messages"]), 1)
        self.assertEqual(teacher_messages.data["data"]["messages"][0]["moderation_status"], "removed")

        self.set_user(self.student)
        context = self.client.get(f"/api/v1/student/classroom/{self.session.id}/chat/")
        feedbacks = context.data["data"]["moderation_feedbacks"]
        self.assertEqual(len(feedbacks), 1)
        self.assertEqual(feedbacks[0]["action"], "deduct")
        self.assertEqual(feedbacks[0]["deduction_points"], 5)
        acknowledged = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/chat/moderation-feedback/{message_id}/ack/",
            {},
            format="json",
        )
        self.assertEqual(acknowledged.status_code, 200)
        context = self.client.get(f"/api/v1/student/classroom/{self.session.id}/chat/")
        self.assertEqual(context.data["data"]["moderation_feedbacks"], [])

        self.set_user(self.teacher)
        repeated = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/chat/messages/{message_id}/moderate/",
            {"action": "deduct", "points": 5},
            format="json",
        )
        self.assertEqual(repeated.status_code, 409)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 5)

    def test_insufficient_points_does_not_commit_chat_review(self):
        self.profile.score = 2
        self.profile.save(update_fields=["score", "updated_at"])
        self.enable(whole_class_enabled=True)
        response = self.send(self.student, "whole_class", "我要打死你")
        message_id = response.data["data"]["id"]

        self.set_user(self.teacher)
        response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/chat/messages/{message_id}/moderate/",
            {"action": "deduct", "points": 5, "note": "积分不足时不应提交审核"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 2)
        message = ClassroomChatMessage.objects.get(pk=message_id)
        self.assertEqual(message.review_action, ClassroomChatMessage.ReviewAction.NONE)
        self.assertEqual(
            message.moderation_status,
            ClassroomChatMessage.ModerationStatus.PENDING,
        )
        self.assertFalse(
            LearningEvent.objects.filter(
                object_type="classroom_chat_message",
                object_id=str(message_id),
                event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
            ).exists()
        )
        self.assertFalse(ParticipationPointLedger.objects.exists())

    def test_group_membership_and_class_finish_are_enforced(self):
        collaboration = ClassroomGroupCollaboration.objects.create(
            session=self.session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.OPEN,
            created_by=self.teacher,
        )
        group = ClassroomGroup.objects.create(collaboration=collaboration, group_no=1, name="第1组")
        ClassroomGroupMember.objects.create(collaboration=collaboration, group=group, student=self.student, student_profile=self.profile)
        response = self.enable(group_chat_enabled=True)
        self.assertEqual(response.status_code, 200)

        response = self.send(self.student, "group", "小组开始讨论", group.id)
        self.assertEqual(response.status_code, 201)
        response = self.send(self.classmate, "group", "越权进入小组", group.id)
        self.assertEqual(response.status_code, 403)

        self.session.status = ClassroomSession.Status.FINISHED
        self.session.finished_at = timezone.now()
        self.session.save(update_fields=["status", "finished_at", "updated_at"])
        config = ClassroomChatConfig.objects.get(session=self.session)
        self.assertFalse(config.group_chat_enabled)
        response = self.send(self.student, "group", "课堂结束后发送", group.id)
        self.assertEqual(response.status_code, 403)


class ClassroomPointDualWriteTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="课堂积分测试学校", code="POINT-SCHOOL")
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school,
            name="高一1班",
            grade="高一",
        )
        self.teacher = User.objects.create_user(
            username="point_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.student = User.objects.create_user(
            username="point_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            score=0,
            is_first_use=False,
        )
        TeachingAssignment.objects.create(
            school=self.school,
            class_group=self.class_group,
            teacher=self.teacher,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="课堂积分课程",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course,
            class_group=self.class_group,
            created_by=self.teacher,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="课堂积分课时",
            is_active=True,
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="课堂积分",
            status=ClassroomSession.Status.RUNNING,
            started_at=timezone.now(),
        )
        self.activity = ClassroomActivity.objects.create(
            session=self.session,
            activity_type=ClassroomActivity.ActivityType.QUICK_ANSWER,
            title="抢答",
            status=ClassroomActivity.Status.OPEN,
            metadata={"command": "quick_answer", "score_defaults": {"plus": 2, "minus": -1}},
            opened_at=timezone.now(),
        )
        LearningEvent.objects.create(
            actor=self.student,
            class_group=self.class_group,
            course=self.course,
            lesson=self.lesson,
            event_type=LearningEvent.EventType.PAGE_VIEW,
            object_type="classroom_activity",
            object_id=str(self.activity.id),
            metadata={
                "action": "classroom_activity_response",
                "command": "quick_answer",
                "response_type": "quick_answer",
            },
            occurred_at=timezone.now(),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    def score(self, action: str, score: float):
        return self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/quick-answer/{self.activity.id}/score/",
            {"action": action, "student_id": self.student.id, "score": score},
            format="json",
        )

    def test_score_replacement_dual_writes_and_keeps_nonnegative_balance(self):
        awarded = self.score("plus", 2)
        deducted = self.score("minus", 1)

        self.assertEqual(awarded.status_code, 200)
        self.assertEqual(deducted.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 0)
        score_events = LearningEvent.objects.filter(
            object_type="classroom_activity",
            object_id=str(self.activity.id),
            metadata__action="quick_answer_score",
        ).order_by("occurred_at", "id")
        self.assertEqual(list(score_events.values_list("score", flat=True)), [2, -1])
        self.assertTrue(all(event.analytics_event_v2 for event in score_events))
        self.assertEqual(
            list(
                ParticipationPointLedger.objects.order_by("recorded_at", "id").values_list(
                    "delta", flat=True
                )
            ),
            [2, -2],
        )


class ResourceCenterWorkflowTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="资源测试学校", code="RESOURCE-SCHOOL")
        self.other_school = School.objects.create(name="外校", code="OTHER-SCHOOL")
        self.subject = Subject.objects.create(school=self.school, name="信息科技", code="IT")
        self.class_group = ClassGroup.objects.create(school=self.school, name="高一1班", grade="高一")
        self.other_class = ClassGroup.objects.create(school=self.other_school, name="高一2班", grade="高一")
        self.teacher = User.objects.create_user(
            username="resource_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
            display_name="资源教师",
        )
        self.school_admin = User.objects.create_user(
            username="resource_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
            display_name="学校管理员",
        )
        self.student = User.objects.create_user(
            username="resource_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="本校学生",
        )
        self.other_student = User.objects.create_user(
            username="other_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.other_school,
            display_name="外校学生",
        )
        StudentProfile.objects.create(user=self.student, class_group=self.class_group, is_first_use=False)
        StudentProfile.objects.create(user=self.other_student, class_group=self.other_class, is_first_use=False)
        TeachingAssignment.objects.create(school=self.school, class_group=self.class_group, teacher=self.teacher)
        self.client = APIClient()

    def test_class_resource_and_student_project_are_visible_to_target_student(self):
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/v1/teacher/resources/",
            {
                "title": "教师个人备课资料",
                "content": "仅教师本人使用。",
                "resource_type": "article",
                "visibility": "private",
                "subject": str(self.subject.id),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["publish_status"], "published")

        response = self.client.post(
            "/api/v1/teacher/resources/",
            {
                "title": "数据采集课外阅读",
                "content": "面向高一学生的课外拓展内容。",
                "resource_type": "article",
                "category": "extracurricular",
                "visibility": "classes",
                "subject": str(self.subject.id),
                "class_ids": f"[{self.class_group.id}]",
                "tags": '["数据采集", "拓展"]',
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["publish_status"], "published")

        project_file = SimpleUploadedFile("project.txt", b"project result", content_type="text/plain")
        process_file = SimpleUploadedFile("timeline.txt", b"optional process", content_type="text/plain")
        response = self.client.post(
            "/api/v1/teacher/resources/",
            {
                "title": "校园数据可视化项目",
                "content": "学生小组完成的数据可视化项目。",
                "resource_type": "student_project",
                "visibility": "school",
                "subject": str(self.subject.id),
                "project_type": "group",
                "project_members": '["张三", "李四"]',
                "attachment": project_file,
                "extra_files": process_file,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        project = Resource.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(project.extra_files.count(), 1)
        self.assertEqual(project.extra_files.first().role, "process")

        self.client.force_authenticate(self.student)
        response = self.client.get("/api/v1/student/resources/")
        self.assertEqual(response.status_code, 200)
        titles = {item["title"] for item in response.data["data"]["results"]}
        self.assertIn("数据采集课外阅读", titles)
        self.assertIn("校园数据可视化项目", titles)

    def test_external_resource_requires_school_admin_approval(self):
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/v1/teacher/resources/",
            {
                "title": "跨校共享案例",
                "content": "可供成员校使用的案例。",
                "resource_type": "article",
                "category": "reference",
                "visibility": "external",
                "subject": str(self.subject.id),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        resource_id = response.data["data"]["id"]
        self.assertEqual(response.data["data"]["publish_status"], "pending")

        self.client.force_authenticate(self.other_student)
        response = self.client.get("/api/v1/student/resources/?scope=external")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 0)

        self.client.force_authenticate(self.school_admin)
        response = self.client.patch(
            f"/api/v1/school-admin/resource-reviews/{resource_id}/",
            {"action": "approve", "note": "内容完整"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["publish_status"], "approved")

        self.client.force_authenticate(self.other_student)
        response = self.client.get("/api/v1/student/resources/?scope=external")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 1)
        response = self.client.post(f"/api/v1/student/resources/{resource_id}/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            LearningEvent.objects.filter(
                actor=self.other_student,
                event_type=LearningEvent.EventType.RESOURCE_VIEW,
                object_type="resource_center",
                object_id=str(resource_id),
            ).exists()
        )
