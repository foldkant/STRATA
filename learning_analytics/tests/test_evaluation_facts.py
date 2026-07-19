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
    ClassroomGroupMember,
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Subject,
)
from learning.models import LessonStepAttempt, StudentWorkAttachment
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
from learning_analytics.services.evaluation import publish_plan, publish_standard
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

    def submit_student(
        self, student, evaluation_type, target=None, rating=4, criterion_id=None
    ):
        self.client.force_authenticate(student)
        criterion_id = criterion_id or (
            "self-process" if evaluation_type == "self" else "peer-collaboration"
        )
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

    def create_formal_binding(self):
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
        publish_plan(plan, published_by=self.teacher)
        standard = EvaluationStandard.objects.create(
            school=self.school,
            subject=self.subject,
            course=self.course,
            plan=plan,
            title="课堂作品评价标准",
            evaluation_target="学生课堂作答和上传作品",
            criteria=[
                {
                    "code": "D1",
                    "dimension": "subject_practice",
                    "title": "任务达成",
                    "evaluation_target": "学生课堂作答和上传作品",
                    "evaluation_sources": ["课堂作答", "学生作品"],
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
                            "example_description": "学生提交了部分结果，但没有说明关键步骤和选择理由。",
                            "file_reference": "classroom-D1-L2",
                        },
                        {
                            "level": 4,
                            "title": "完整过程说明",
                            "example_description": "学生完整提交结果，并连贯说明主要步骤和选择理由。",
                            "file_reference": "classroom-D1-L4",
                        },
                    ],
                    "follow_up_suggestion": "针对缺失步骤给出补充提示。",
                }
            ],
            created_by=self.teacher,
            updated_by=self.teacher,
        )
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
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.session.refresh_from_db()
        frozen_version = self.session.evaluation_config_version
        self.assertIsNotNone(frozen_version)
        self.assertEqual(frozen_version.version_no, 1)
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
        teacher_response = self.client.post(
            f"/api/v1/teacher/classroom/sessions/{self.session.id}/evaluation/teacher-submit/",
            {
                "target": self.students[0].id,
                "ratings": {"teacher-outcome": 3},
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
        self.assertEqual(self_submissions[0].evaluation_version, frozen_version)
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
            [{"criterion_id": "peer-collaboration", "rating": 5}],
        )

        self.config.self_criteria = [
            {
                "id": "new-self-item",
                "title": "新评价项",
                "description": "只用于后续课堂",
                "sort_order": 10,
            }
        ]
        self.config.save(update_fields=["self_criteria", "updated_at"])
        self.client.force_authenticate(self.teacher)
        saved = self.client.post(
            f"/api/v1/teacher/courses/{self.course.id}/evaluation/",
            {
                "enable_self": True,
                "enable_peer": True,
                "enable_teacher": True,
                "self_criteria": self.config.self_criteria,
                "peer_criteria": self.config.peer_criteria,
                "teacher_criteria": self.config.teacher_criteria,
            },
            format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(
            ClassroomEvaluationConfigVersion.objects.filter(course=self.course).count(),
            2,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.evaluation_config_version, frozen_version)
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
        self.assertFalse(EvaluationSubmissionEvidence.objects.exists())

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
            self.session.evaluation_config_version.self_criteria[0]["criterion_code"],
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
                "enable_peer": True,
                "enable_teacher": True,
            },
            format="json",
        )
        self.assertEqual(changed.status_code, 409, changed.data)
        self.assertEqual(self.client.delete(binding_url).status_code, 409)

    def test_not_assessed_criterion_is_excluded_from_average_and_keeps_reason(self):
        self.config.self_criteria = [
            *self.config.self_criteria,
            {
                "id": "self-collaboration",
                "title": "协作表现",
                "description": "根据本节课实际协作材料评价",
                "sort_order": 20,
            },
        ]
        self.config.save(update_fields=["self_criteria", "updated_at"])
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)

        self.client.force_authenticate(self.students[0])
        response = self.client.post(
            f"/api/v1/student/classroom/{self.session.id}/evaluation/submit/",
            {
                "evaluation_type": "self",
                "ratings": {"self-process": 4},
                "not_assessed": {
                    "self-collaboration": {
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
        self.assertEqual(submission.ratings, {"self-process": 4})
        self.assertEqual(
            submission.not_assessed["self-collaboration"]["reason"],
            "not_observed",
        )
        serialized = response.data["data"]["self_submission"]
        self.assertEqual(
            serialized["not_assessed"]["self-collaboration"]["reason_label"],
            "本节未安排或未观察到",
        )

        event = LearningEventV2.objects.get(
            event_name="evaluation.rating.submitted"
        )
        self.assertEqual(event.schema_version, "1.1")
        self.assertEqual(
            event.payload["criterion_ratings"],
            [{"criterion_id": "self-process", "rating": 4}],
        )
        self.assertEqual(
            event.payload["not_assessed_criteria"],
            [
                {
                    "criterion_id": "self-collaboration",
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
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
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
                "ratings": {"self-process": 3},
                "not_assessed": {
                    "self-process": {"reason": "no_evidence", "note": ""}
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
                    "self-process": {"reason": "other", "note": ""}
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
                    "self-process": {
                        "reason": "no_evidence",
                        "note": "本节未形成可评价作品。",
                    }
                },
            },
            format="json",
        )
        self.assertEqual(valid_skip.status_code, 200, valid_skip.data)

    def test_student_batch_cannot_forge_peer_rating_for_another_student(self):
        enabled = self.enable_evaluation()
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.session.refresh_from_db()
        version = self.session.evaluation_config_version
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
                        "object_version": version.config_hash,
                        "opportunity_id": str(opportunity.opportunity_id),
                        "client_occurred_at": timezone.now().isoformat(),
                        "payload": {
                            "evaluation_version": (
                                f"course:{self.course.id}:v{version.version_no}:"
                                f"{version.config_hash[:12]}"
                            ),
                            "criterion_ratings": [
                                {
                                    "criterion_id": "peer-collaboration",
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
