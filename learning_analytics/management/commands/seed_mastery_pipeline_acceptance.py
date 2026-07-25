from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.query import QuerySet
from django.utils import timezone

from courses.models import Course
from learning.models import (
    BandTransitionAudit,
    CommonQuestionSet,
    CommonQuestionSetItem,
    LearningContentRecommendation,
    LearningContentRecommendationTargetState,
    LearningSupportRecommendation,
    QuestionBankItem,
    QuestionBankItemVersion,
    StratificationDecision,
    StudentLearningTargetStateVersion,
    StudentMasterySnapshot,
    StudentMasteryTargetResult,
    StudentSubjectBand,
    TestAssessment,
    TestAssessmentQuestion,
    TestAttempt,
    TestAttemptAnswer,
)
from learning.services.mastery import create_default_content_band_policy
from learning.services.question_bank import ensure_question_version
from learning_analytics.target_models import (
    LearningTargetAlignmentStatus,
    LearningTargetVersion,
)
from school.models import School, StudentProfile


CONFIRMATION = "TEST-DATA-ONLY"
TITLE_PREFIX = "[TEST] 共同掌握夜间任务验收"
MEASUREMENT_SERIES_PREFIX = "TEST-MASTERY"
QUESTION_PREFIX = "[TEST-MASTERY]"


def _score_ratio(*, school_code: str, student_id: int) -> float:
    digest = hashlib.sha256(
        f"{school_code}:{student_id}:{MEASUREMENT_SERIES_PREFIX}".encode("utf-8")
    ).digest()
    return (0.9, 0.7, 0.4)[digest[0] % 3]


def _target_version(*, course: Course, version_id: int | None):
    versions = (
        LearningTargetVersion.objects.select_related("target")
        .prefetch_related("curriculum_alignments")
        .filter(
            target__school=course.subject.school,
            target__subject=course.subject,
            target__course=course,
            alignment_status=LearningTargetAlignmentStatus.COMPLETE,
        )
        .order_by("-published_at", "-id")
    )
    if version_id is not None:
        versions = versions.filter(pk=version_id)
    target_version = next(
        (item for item in versions if item.curriculum_alignments.exists()),
        None,
    )
    if target_version is None:
        requested = f" ID={version_id}" if version_id is not None else ""
        raise CommandError(
            f"课程没有课标依据完整的已发布学习目标版本{requested}；请先发布评价方案。"
        )
    return target_version


class Command(BaseCommand):
    help = "为共同掌握与夜间分层候选任务生成可清理的测试数据。"

    def add_arguments(self, parser):
        parser.add_argument("--school-code", required=True)
        parser.add_argument("--confirmation", default="")
        parser.add_argument("--allow-non-synthetic", action="store_true")
        parser.add_argument("--student-limit", type=int, default=30)
        parser.add_argument("--learning-target-version-id", type=int)
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
        target_version = _target_version(
            course=course,
            version_id=options.get("learning_target_version_id"),
        )
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
                readiness={
                    "purpose": "test_only",
                    "item_count": 30,
                    "learning_target_version_id": target_version.id,
                    "learning_target_version_hash": target_version.content_hash,
                },
                content_hash=hashlib.sha256(
                    (
                        f"{school.code}:{course.id}:{target_version.id}:"
                        f"{target_version.content_hash}:30"
                    ).encode("utf-8")
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
                status=TestAssessment.Status.DRAFT,
            )
            assessment.target_classes.add(class_group)
            questions = []
            for index in range(1, 31):
                source_question = QuestionBankItem.objects.create(
                    school=school,
                    subject=course.subject,
                    creator=course.teacher,
                    stem=f"{QUESTION_PREFIX} 共同题 {index}",
                    question_type=QuestionBankItem.QuestionType.SINGLE,
                    options=["A", "B", "C", "D"],
                    answer=["A"],
                    analysis="仅用于目标版本掌握度工程验收。",
                    difficulty=QuestionBankItem.Difficulty.NORMAL,
                    knowledge_point=f"共同知识点 {(index - 1) % 5 + 1}",
                    default_score=1,
                    status=QuestionBankItem.Status.ACTIVE,
                    source=QuestionBankItem.Source.MANUAL,
                    library_scope=QuestionBankItem.LibraryScope.PERSONAL,
                    item_role=QuestionBankItem.ItemRole.COMMON,
                    comparison_code=f"TEST-COMMON-{index:02d}",
                    learning_target_version=target_version,
                    legacy_unmapped=False,
                )
                source_version = ensure_question_version(
                    source_question,
                    actor=course.teacher,
                )
                CommonQuestionSetItem.objects.create(
                    question_set=question_set,
                    question_version=source_version,
                    comparison_code=source_question.comparison_code,
                    required=True,
                    sort_order=index,
                )
                questions.append(TestAssessmentQuestion.objects.create(
                    assessment=assessment,
                    source_question=source_question,
                    source_version=source_version,
                    source_status=source_question.status,
                    question_type=source_question.question_type,
                    stem=source_question.stem,
                    options=source_question.options,
                    answer=source_question.answer,
                    analysis=source_question.analysis,
                    knowledge_point=source_question.knowledge_point,
                    score=1,
                    sort_order=index,
                    item_role=QuestionBankItem.ItemRole.COMMON,
                    comparison_code=source_question.comparison_code,
                    learning_target_version=target_version,
                    legacy_unmapped=False,
                ))
            now = timezone.now()
            assessment.status = TestAssessment.Status.CLOSED
            assessment.opened_at = now
            assessment.closed_at = now
            assessment.save(
                update_fields=["status", "opened_at", "closed_at", "updated_at"]
            )
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
                f"学习目标 {target_version.code}@{target_version.version_no}；"
                f"层级标准 {policy.policy_version}。"
            )
        )

    @transaction.atomic
    def _clear(self, school):
        assessments = TestAssessment.objects.filter(
            school=school,
            title__startswith=TITLE_PREFIX,
        )
        assessment_ids = list(assessments.values_list("id", flat=True))
        snapshot_ids = list(StudentMasterySnapshot.objects.filter(
            assessment_id__in=assessment_ids
        ).values_list("id", flat=True))
        target_result_ids = list(
            StudentMasteryTargetResult.objects.filter(
                snapshot_id__in=snapshot_ids
            ).values_list("id", flat=True)
        )
        target_state_ids = list(
            StudentLearningTargetStateVersion.objects.filter(
                source_type="common_assessment",
                source_id__in=[str(item) for item in target_result_ids],
            ).values_list("id", flat=True)
        )
        decision_ids = list(
            StratificationDecision.objects.filter(
                mastery_snapshot_id__in=snapshot_ids
            ).values_list("id", flat=True)
        )
        recommendation_ids = list(
            LearningContentRecommendation.objects.filter(
                Q(source_decision_id__in=decision_ids)
                | Q(target_state_id__in=target_state_ids)
                | Q(target_state_links__target_state_id__in=target_state_ids)
            )
            .distinct()
            .values_list("id", flat=True)
        )
        LearningContentRecommendationTargetState.objects.filter(
            Q(recommendation_id__in=recommendation_ids)
            | Q(target_state_id__in=target_state_ids)
        ).delete()
        LearningContentRecommendation.objects.filter(
            id__in=recommendation_ids
        ).delete()
        LearningSupportRecommendation.objects.filter(
            Q(source_decision_id__in=decision_ids)
            | Q(target_state_id__in=target_state_ids)
        ).delete()
        acceptance_bands = StudentSubjectBand.objects.filter(
            Q(source_decision_id__in=decision_ids)
            | Q(mastery_snapshot_id__in=snapshot_ids)
        )
        # The production manager intentionally blocks removal of applied band
        # history.  This command is the explicitly confirmed, title-scoped
        # teardown path for synthetic acceptance data, so use Django's base
        # collector only for the rows proven to originate from this seed.
        QuerySet.delete(acceptance_bands)
        BandTransitionAudit.objects.filter(decision_id__in=decision_ids).delete()
        decision_count = len(decision_ids)
        StratificationDecision.objects.filter(id__in=decision_ids).delete()
        StudentLearningTargetStateVersion.objects.filter(
            id__in=target_state_ids
        ).delete()
        StudentMasteryTargetResult.objects.filter(id__in=target_result_ids).delete()
        snapshot_count = len(snapshot_ids)
        StudentMasterySnapshot.objects.filter(id__in=snapshot_ids).delete()
        TestAttempt.objects.filter(assessment_id__in=assessment_ids).delete()
        question_ids = list(
            assessments.values_list("questions__source_question_id", flat=True)
        )
        question_version_ids = list(
            assessments.values_list("questions__source_version_id", flat=True)
        )
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
        QuestionBankItemVersion.objects.filter(
            id__in=[item for item in question_version_ids if item]
        ).delete()
        QuestionBankItem.objects.filter(
            id__in=[item for item in question_ids if item],
            stem__startswith=QUESTION_PREFIX,
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"已清理 {assessment_count} 场测试、{snapshot_count} 份掌握结果、"
                f"{decision_count} 条分层候选。"
            )
        )
