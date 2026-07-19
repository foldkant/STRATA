from __future__ import annotations

import json
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from api.serializers import classroom_group_collaboration_row
from courses.models import (
    ClassroomGroup,
    ClassroomGroupCollaboration,
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Subject,
)
from learning_analytics.models import (
    AnalyticsOperatingMode,
    EvaluationPlan,
    EvaluationStandard,
    EventSchemaDefinition,
    LessonStepEvaluationBinding,
    LearningOpportunity,
    LearningEventV2,
    SensitiveInferenceAccessLog,
)
from learning_analytics.schemas.registry import (
    EVENT_SCHEMA_REGISTRY,
    EventPayloadValidationError,
    validate_event_payload,
)
from learning_analytics.services.access_audit import audit_teacher_class_scope
from learning_analytics.services.evaluation import publish_plan, publish_standard
from learning_analytics.services.operating_mode import transition_operating_mode
from learning_analytics.services.opportunities import release_learning_opportunities
from learning_analytics.services.schema_registry import (
    ensure_event_schema_definition,
    sync_event_schema_definitions,
)
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment


class AnalyticsSecurityModelTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="分析测试学校", code="ANALYTICS-TEST")
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.other_class = ClassGroup.objects.create(
            school=self.school, name="高一2班", grade="高一"
        )
        self.teacher = User.objects.create_user(
            username="analytics_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        TeachingAssignment.objects.create(
            school=self.school, class_group=self.class_group, teacher=self.teacher
        )

    def test_operating_mode_requires_safe_transition_path(self):
        with self.assertRaises(ValidationError):
            transition_operating_mode(
                school=self.school,
                target_mode=AnalyticsOperatingMode.Mode.ACTIVE,
                actor=self.teacher,
            )

        state = transition_operating_mode(
            school=self.school,
            target_mode=AnalyticsOperatingMode.Mode.SHADOW,
            actor=self.teacher,
        )
        self.assertEqual(state.mode, AnalyticsOperatingMode.Mode.SHADOW)
        state = transition_operating_mode(
            school=self.school,
            target_mode=AnalyticsOperatingMode.Mode.TEACHER_REVIEW,
            actor=self.teacher,
        )
        self.assertEqual(state.mode, AnalyticsOperatingMode.Mode.TEACHER_REVIEW)

        with self.assertRaises(ValidationError):
            transition_operating_mode(
                school=self.school,
                target_mode=AnalyticsOperatingMode.Mode.SUSPENDED,
                actor=self.teacher,
            )
        state = transition_operating_mode(
            school=self.school,
            target_mode=AnalyticsOperatingMode.Mode.SUSPENDED,
            actor=self.teacher,
            reason="学习数据检查失败",
        )
        self.assertEqual(state.mode, AnalyticsOperatingMode.Mode.SUSPENDED)

    def test_teacher_class_scope_is_audited_for_allowed_and_denied_access(self):
        self.assertTrue(
            audit_teacher_class_scope(
                teacher=self.teacher,
                class_group=self.class_group,
                target_type="student_subject_band",
                purpose="teacher_review",
                field_categories=["content_band", "uncertainty"],
            )
        )
        self.assertFalse(
            audit_teacher_class_scope(
                teacher=self.teacher,
                class_group=self.other_class,
                target_type="student_subject_band",
                purpose="teacher_review",
                field_categories=["content_band"],
            )
        )
        logs = list(SensitiveInferenceAccessLog.objects.order_by("created_at"))
        self.assertEqual([item.access_granted for item in logs], [True, False])
        self.assertIn("不在该班级", logs[1].denial_reason)

        logs[0].purpose = "tampered"
        with self.assertRaises(ValidationError):
            logs[0].save()


class LearningEventV2SchemaTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="事件测试学校", code="EVENT-V2")
        self.other_school = School.objects.create(
            name="其他事件学校", code="EVENT-V2-OTHER"
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.subject = Subject.objects.create(
            school=self.school, name="信息科技", code="IT"
        )
        self.student = User.objects.create_user(
            username="event_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
        )
        StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        self.other_student = User.objects.create_user(
            username="event_other_student",
            password="123456",
            role=User.Role.STUDENT,
            school=self.other_school,
        )
        self.schema = ensure_event_schema_definition("item.submitted", "1.0")
        release_schema = ensure_event_schema_definition("content.released", "1.0")
        release_event = LearningEventV2.objects.create(
            schema_definition=release_schema,
            event_name="content.released",
            schema_version="1.0",
            source="teacher-web",
            actor=User.objects.create_user(
                username="event_teacher",
                password="Teacher123!",
                role=User.Role.TEACHER,
                school=self.school,
            ),
            school=self.school,
            class_group=self.class_group,
            subject=self.subject,
            object_type="question",
            object_id="question-1",
            object_version="question-1@1",
            client_occurred_at=timezone.now(),
            privacy_class=EventSchemaDefinition.PrivacyClass.OPERATIONAL,
            analysis_unit=EventSchemaDefinition.AnalysisUnit.CLASS,
            payload={
                "content_type": "question",
                "required": True,
                "target_layers": ["all"],
            },
            quality_status=LearningEventV2.QualityStatus.ACCEPTED,
        )
        release_learning_opportunities(release_event)
        self.opportunity = LearningOpportunity.objects.get(student=self.student)

    def build_event(self, **overrides):
        values = {
            "schema_definition": self.schema,
            "event_name": "item.submitted",
            "schema_version": "1.0",
            "source": "student-web",
            "actor": self.student,
            "target_student": self.student,
            "school": self.school,
            "class_group": self.class_group,
            "subject": self.subject,
            "object_type": "question",
            "object_id": "question-1",
            "object_version": "question-1@1",
            "opportunity_id": self.opportunity.opportunity_id,
            "opportunity_record": self.opportunity,
            "attempt_id": uuid.uuid4(),
            "client_session_id": uuid.uuid4(),
            "client_sequence": 1,
            "client_occurred_at": timezone.now(),
            "privacy_class": EventSchemaDefinition.PrivacyClass.ASSESSMENT,
            "analysis_unit": EventSchemaDefinition.AnalysisUnit.STUDENT,
            "payload": {
                "question_version": "question-1@1",
                "response_kind": "single",
                "attempt_no": 1,
                "response_time_ms": 4200,
                "learner_confidence_rating": 4,
            },
            "quality_status": LearningEventV2.QualityStatus.ACCEPTED,
        }
        values.update(overrides)
        return LearningEventV2(**values)

    def test_registry_sync_and_strict_payload_validation(self):
        result = sync_event_schema_definitions()
        self.assertEqual(result["created"], len(EVENT_SCHEMA_REGISTRY) - 2)
        self.assertEqual(
            EventSchemaDefinition.objects.count(), len(EVENT_SCHEMA_REGISTRY)
        )
        checked = sync_event_schema_definitions(check_only=True)
        self.assertEqual(checked["missing"], 0)
        self.assertEqual(checked["mismatched"], 0)

        with self.assertRaises(EventPayloadValidationError):
            validate_event_payload(
                "item.submitted",
                "1.0",
                {
                    "question_version": "question-1@1",
                    "response_kind": "single",
                    "attempt_no": 1,
                    "response_time_ms": 4200,
                    "answer_text": "事件表禁止复制答卷正文",
                },
            )
        with self.assertRaises(EventPayloadValidationError):
            validate_event_payload(
                "item.submitted",
                "1.0",
                {
                    "question_version": "question-1@1",
                    "response_kind": "single",
                    "attempt_no": 1,
                },
            )
        normalized = validate_event_payload(
            "item.submitted",
            "1.1",
            {
                "question_version": "question-1@1",
                "response_kind": "single",
                "attempt_no": 1,
                "response_time_ms": None,
            },
        )
        self.assertNotIn("response_time_ms", normalized)

    def test_event_is_validated_normalized_and_immutable(self):
        event = self.build_event()
        event.save()
        self.assertEqual(event.payload["learner_confidence_rating"], 4)
        self.assertEqual(event.quality_status, LearningEventV2.QualityStatus.ACCEPTED)

        event.object_id = "tampered"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_event_rejects_invalid_scope_source_and_payload(self):
        cases = (
            {"target_student": self.other_student},
            {"source": "unknown-client"},
            {"opportunity_id": None},
            {
                "payload": {
                    "question_version": "question-1@1",
                    "response_kind": "single",
                    "attempt_no": 1,
                    "response_time_ms": -1,
                }
            },
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    self.build_event(**overrides).save()

    def test_active_schema_definition_cannot_be_overwritten(self):
        self.schema.payload_schema = {"type": "object", "properties": {}}
        with self.assertRaises(ValidationError):
            self.schema.save()


class StudentHiddenStratificationContractTests(TestCase):
    forbidden_keys = {
        "current_layer",
        "current_layer_label",
        "current_group_no",
        "target_layer",
        "target_layer_label",
        "layer_scores",
        "use_layer_scores",
        "is_layered",
        "layer_hint",
        "grouping_strategy",
        "grouping_strategy_label",
        "confidence",
    }

    def setUp(self):
        self.school = School.objects.create(
            name="隐性分层测试学校", code="HIDDEN-LAYER"
        )
        self.subject = Subject.objects.create(
            school=self.school, name="信息科技", code="IT"
        )
        self.class_group = ClassGroup.objects.create(
            school=self.school, name="高一1班", grade="高一"
        )
        self.teacher = User.objects.create_user(
            username="hidden_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
            display_name="测试教师",
        )
        TeachingAssignment.objects.create(
            school=self.school, class_group=self.class_group, teacher=self.teacher
        )
        self.student = User.objects.create_user(
            username="hidden_student_a",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="学生甲",
        )
        self.peer = User.objects.create_user(
            username="hidden_student_b",
            password="123456",
            role=User.Role.STUDENT,
            school=self.school,
            display_name="学生乙",
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            class_group=self.class_group,
            student_no="2026001",
            current_layer=StudentProfile.Layer.A,
            current_group_no=1,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        self.peer_profile = StudentProfile.objects.create(
            user=self.peer,
            class_group=self.class_group,
            student_no="2026002",
            current_layer=StudentProfile.Layer.B,
            current_group_no=1,
            is_first_use=False,
            onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与计算",
            teacher=self.teacher,
            is_active=True,
        )
        CourseClass.objects.create(
            course=self.course, class_group=self.class_group, created_by=self.teacher
        )
        self.lesson = Lesson.objects.create(
            course=self.course, title="数据编码", is_active=True
        )
        self.step = LessonStep.objects.create(
            lesson=self.lesson,
            title="分层练习",
            status=LessonStep.Status.READY,
            target_layer=LessonStep.TargetLayer.A,
            question_items=[
                {
                    "id": "question-a",
                    "question_type": "single",
                    "stem": "二进制 10 对应十进制几？",
                    "options": ["1", "2", "3", "4"],
                    "answer": ["2"],
                    "score": 2,
                    "target_layer": "A",
                    "use_layer_scores": True,
                    "layer_scores": {"A": 4, "B": 3, "C": 2},
                },
                {
                    "id": "question-b-file",
                    "question_type": "file",
                    "stem": "提交基础练习文件",
                    "score": 2,
                    "target_layer": "B",
                    "file_config": {"allowed_extensions": ["docx"], "max_size_mb": 10},
                },
            ],
        )
        self.session = ClassroomSession.objects.create(
            school=self.school,
            teacher=self.teacher,
            course=self.course,
            lesson=self.lesson,
            class_group=self.class_group,
            title="数据编码课堂",
            status=ClassroomSession.Status.RUNNING,
            current_step=self.step,
            current_step_status=ClassroomSession.StepStatus.OPEN,
            evaluation_enabled=True,
            started_at=timezone.now(),
        )
        self.collaboration = ClassroomGroupCollaboration.objects.create(
            session=self.session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.OPEN,
            grouping_strategy=ClassroomGroupCollaboration.GroupingStrategy.SAME_LAYER,
            created_by=self.teacher,
        )
        self.group = ClassroomGroup.objects.create(
            collaboration=self.collaboration,
            group_no=1,
            name="A层第1组",
            layer_hint="A",
            leader=self.student,
        )
        ClassroomGroupMember.objects.create(
            collaboration=self.collaboration,
            group=self.group,
            student=self.student,
            student_profile=self.profile,
            role=ClassroomGroupMember.Role.LEADER,
        )
        ClassroomGroupMember.objects.create(
            collaboration=self.collaboration,
            group=self.group,
            student=self.peer,
            student_profile=self.peer_profile,
        )
        plan = EvaluationPlan.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            title="协作评价方案",
            content_version="1.0",
            target_students="本课堂学生",
            learning_goal="学生能够参与小组协作。",
            learning_goals=[
                {
                    "code": "G1",
                    "title": "参与协作",
                    "description": "学生能够主动参与小组任务并回应同伴。",
                }
            ],
            evaluation_basis=[
                {
                    "code": "E1",
                    "goal_codes": ["G1"],
                    "description": "以课堂协作过程为依据。",
                    "source_types": ["课堂观察"],
                }
            ],
            learning_tasks=[
                {
                    "code": "T1",
                    "title": "小组任务",
                    "basis_codes": ["E1"],
                    "description": "共同完成小组任务。",
                }
            ],
            content_scope=["小组任务"],
            thinking_requirements=["apply"],
            support_options=[],
            scoring_rules={"approach": "分项评价", "decision_rule": "缺少材料时暂不评价。"},
            follow_up_suggestion="根据协作情况提供支持。",
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        publish_plan(plan, published_by=self.teacher)
        standard = EvaluationStandard.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            plan=plan,
            title="协作评价标准",
            evaluation_target="学生小组协作过程",
            criteria=[
                {
                    "code": "cooperation",
                    "dimension": "collaboration",
                    "title": "协作表现",
                    "evaluation_target": "学生小组协作过程",
                    "evaluation_sources": ["课堂观察"],
                    "expected_performance": "学生参与任务并回应同伴。",
                    "skip_condition": "未安排协作时暂不评价。",
                    "support_options": [],
                    "common_problems": ["未参与小组交流。"],
                    "level_descriptions": {
                        str(level): f"协作表现等级 {level}" for level in range(1, 6)
                    },
                    "scoring_examples": [
                        {
                            "level": 2,
                            "title": "参与有限",
                            "example_description": "偶尔参与，回应较少。",
                            "file_reference": "",
                        },
                        {
                            "level": 4,
                            "title": "有效协作",
                            "example_description": "持续参与并回应同伴。",
                            "file_reference": "",
                        },
                    ],
                    "follow_up_suggestion": "教师根据观察结果进一步明确协作分工。",
                }
            ],
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        standard_version = publish_standard(
            standard, published_by=self.teacher
        ).version
        LessonStepEvaluationBinding.objects.create(
            lesson_step=self.step,
            standard_version=standard_version,
            enable_self=False,
            enable_peer=True,
            enable_teacher=False,
            created_by=self.teacher,
            updated_by=self.teacher,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.student)

    def assert_hidden_contract(self, value):
        if isinstance(value, dict):
            for key, nested in value.items():
                self.assertNotIn(key, self.forbidden_keys, f"学生响应泄漏字段：{key}")
                self.assert_hidden_contract(nested)
        elif isinstance(value, list):
            for item in value:
                self.assert_hidden_contract(item)

    def test_student_me_and_classroom_hide_internal_layer_fields(self):
        me_response = self.client.get("/api/v1/student/me/")
        self.assertEqual(me_response.status_code, 200)
        self.assert_hidden_contract(me_response.data["data"])

        response = self.client.get(f"/api/v1/student/classroom/{self.session.id}/")
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assert_hidden_contract(data)
        questions = data["current_step"]["question_items"]
        self.assertEqual([item["id"] for item in questions], ["question-a"])
        self.assertNotIn("answer", questions[0])

    def test_student_group_and_peer_evaluation_hide_strategy_and_member_layers(self):
        response = self.client.get(
            f"/api/v1/student/classroom/{self.session.id}/group-collaboration/"
        )
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assert_hidden_contract(data)
        self.assertEqual(data["my_group"]["name"], "第1组")
        self.assertEqual(data["my_group"]["document"]["attachment_name"], "第1组.docx")
        self.assertNotIn("A层", json.dumps(data, ensure_ascii=False, default=str))

        response = self.client.get(
            f"/api/v1/student/classroom/{self.session.id}/evaluation/"
        )
        self.assertEqual(response.status_code, 200)
        self.assert_hidden_contract(response.data["data"])
        self.assertEqual(
            response.data["data"]["peer_targets"][0]["display_name"], "学生乙"
        )

    def test_student_cannot_submit_hidden_question_by_direct_id(self):
        response = self.client.post(
            f"/api/v1/student/lesson-steps/{self.step.id}/attachments/",
            {"question_id": "question-b-file"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 404)

    def test_teacher_serialization_keeps_private_grouping_evidence(self):
        data = classroom_group_collaboration_row(self.collaboration)
        self.assertEqual(
            data["grouping_strategy"],
            ClassroomGroupCollaboration.GroupingStrategy.SAME_LAYER,
        )
        self.assertEqual(data["groups"][0]["layer_hint"], "A")
        self.assertEqual(data["groups"][0]["members"][0]["current_layer"], "A")
