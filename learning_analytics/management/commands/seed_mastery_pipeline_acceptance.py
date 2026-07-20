from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from courses.models import Course
from learning.models import (
    BandTransitionAudit,
    CommonQuestionSet,
    QuestionBankItem,
    StratificationDecision,
    StudentMasterySnapshot,
    TestAssessment,
    TestAssessmentQuestion,
    TestAttempt,
    TestAttemptAnswer,
)
from learning.services.mastery import create_default_content_band_policy
from school.models import School, StudentProfile


CONFIRMATION = "TEST-DATA-ONLY"
TITLE_PREFIX = "[TEST] 共同掌握夜间任务验收"
MEASUREMENT_SERIES_PREFIX = "TEST-MASTERY"


def _score_ratio(*, school_code: str, student_id: int) -> float:
    digest = hashlib.sha256(
        f"{school_code}:{student_id}:{MEASUREMENT_SERIES_PREFIX}".encode("utf-8")
    ).digest()
    return (0.9, 0.7, 0.4)[digest[0] % 3]


class Command(BaseCommand):
    help = "为共同掌握与夜间分层候选任务生成可清理的测试数据。"

    def add_arguments(self, parser):
        parser.add_argument("--school-code", required=True)
        parser.add_argument("--confirmation", default="")
        parser.add_argument("--allow-non-synthetic", action="store_true")
        parser.add_argument("--student-limit", type=int, default=30)
        parser.add_argument("--clear", action="store_true")

    def handle(self, *args, **options):
        if options["confirmation"] != CONFIRMATION:
            raise CommandError(f"必须提供 --confirmation {CONFIRMATION}。")
        school = School.objects.filter(code=options["school_code"]).first()
        if school is None:
            raise CommandError("学校不存在。")
        if not school.is_synthetic and not options["allow_non_synthetic"]:
            raise CommandError("默认只允许模拟学校；实校验收需额外确认。")
        if options["clear"]:
            self._clear(school)
            return

        limit = max(3, min(int(options["student_limit"]), 300))
        course = (
            Course.objects.filter(subject__school=school, subject__isnull=False)
            .select_related("subject", "teacher")
            .prefetch_related("course_classes")
            .order_by("id")
            .first()
        )
        if course is None:
            raise CommandError("学校没有可用于验收的课程。")
        class_group = course.course_classes.order_by("class_group_id").first()
        if class_group is None:
            raise CommandError("课程没有绑定班级。")
        class_group = class_group.class_group
        profiles = list(
            StudentProfile.objects.select_related("user")
            .filter(
                class_group=class_group,
                user__school=school,
                user__is_active=True,
            )
            .order_by("student_no", "user__username")[:limit]
        )
        if len(profiles) < 3:
            raise CommandError("班级至少需要 3 名启用学生。")
        if TestAssessment.objects.filter(
            school=school,
            title__startswith=TITLE_PREFIX,
        ).exists():
            raise CommandError("验收测试已存在；如需重建请先执行 --clear。")

        with transaction.atomic():
            policy, _created = create_default_content_band_policy(
                school=school,
                subject=course.subject,
                course=course,
                actor=course.teacher,
            )
            question_set = CommonQuestionSet.objects.create(
                school=school,
                subject=course.subject,
                title=TITLE_PREFIX,
                grade_scope=class_group.grade,
                term="验收",
                version_no=1,
                measurement_series=(
                    f"{MEASUREMENT_SERIES_PREFIX}-{school.code}-{course.subject_id}"
                ),
                version_purpose=CommonQuestionSet.VersionPurpose.BASELINE,
                readiness={"purpose": "test_only", "item_count": 30},
                content_hash=hashlib.sha256(
                    f"{school.code}:{course.id}:30".encode("utf-8")
                ).hexdigest(),
                status=CommonQuestionSet.Status.ACTIVE,
                created_by=course.teacher,
                published_by=course.teacher,
                published_at=timezone.now(),
            )
            assessment = TestAssessment.objects.create(
                school=school,
                teacher=course.teacher,
                subject=course.subject,
                course=course,
                common_question_set=question_set,
                common_set_version=question_set.version_no,
                common_set_hash=question_set.content_hash,
                title=f"{TITLE_PREFIX} v1",
                instruction="仅用于测试共同掌握、迁移保护和夜间任务。",
                status=TestAssessment.Status.CLOSED,
                opened_at=timezone.now(),
                closed_at=timezone.now(),
            )
            assessment.target_classes.add(class_group)
            questions = [
                TestAssessmentQuestion.objects.create(
                    assessment=assessment,
                    question_type=QuestionBankItem.QuestionType.SINGLE,
                    stem=f"验收共同题 {index}",
                    options=["A", "B", "C", "D"],
                    answer=["A"],
                    knowledge_point=f"共同知识点 {(index - 1) % 5 + 1}",
                    score=1,
                    sort_order=index,
                    item_role=QuestionBankItem.ItemRole.COMMON,
                    comparison_code=f"TEST-COMMON-{index:02d}",
                )
                for index in range(1, 31)
            ]
            now = timezone.now()
            for profile in profiles:
                ratio = _score_ratio(
                    school_code=school.code,
                    student_id=profile.user_id,
                )
                correct_count = round(ratio * len(questions))
                attempt = TestAttempt.objects.create(
                    assessment=assessment,
                    student=profile.user,
                    class_group=class_group,
                    status=TestAttempt.Status.GRADED,
                    objective_score=correct_count,
                    total_score=correct_count,
                    submitted_at=now,
                    graded_at=now,
                )
                TestAttemptAnswer.objects.bulk_create(
                    [
                        TestAttemptAnswer(
                            attempt=attempt,
                            question=question,
                            answer=["A"] if index < correct_count else ["B"],
                            auto_score=1 if index < correct_count else 0,
                            is_correct=index < correct_count,
                        )
                        for index, question in enumerate(questions)
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"已生成 {len(profiles)} 份测试答卷、30 道共同题；"
                f"层级标准 {policy.policy_version}。"
            )
        )

    def _clear(self, school):
        assessments = TestAssessment.objects.filter(
            school=school,
            title__startswith=TITLE_PREFIX,
        )
        assessment_ids = list(assessments.values_list("id", flat=True))
        snapshots = StudentMasterySnapshot.objects.filter(
            assessment_id__in=assessment_ids
        )
        decisions = StratificationDecision.objects.filter(
            mastery_snapshot__in=snapshots
        )
        BandTransitionAudit.objects.filter(decision__in=decisions).delete()
        decision_count = decisions.count()
        decisions.delete()
        snapshot_count = snapshots.count()
        snapshots.delete()
        TestAttempt.objects.filter(assessment_id__in=assessment_ids).delete()
        set_ids = list(
            assessments.exclude(common_question_set__isnull=True).values_list(
                "common_question_set_id", flat=True
            )
        )
        assessment_count = assessments.count()
        assessments.delete()
        CommonQuestionSet.objects.filter(
            id__in=set_ids,
            title=TITLE_PREFIX,
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"已清理 {assessment_count} 场测试、{snapshot_count} 份掌握结果、"
                f"{decision_count} 条分层候选。"
            )
        )
