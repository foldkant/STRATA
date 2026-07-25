from __future__ import annotations

import hashlib
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from courses.grouping import build_grouping_plan
from courses.models import ClassroomGroupCollaboration, ClassroomSession, Course
from learning.models import StratificationDecision, StudentSubjectBand
from learning.services.bands import (
    apply_student_subject_band,
    build_content_band_candidate,
)
from school.models import School, StudentProfile


POLICY_VERSION = "acceptance-criterion-v1"
CONFIRMATION = "TEST-DATA-ONLY"


def _simulated_mastery(*, school_code: str, course_id: int, student_id: int) -> float:
    digest = hashlib.sha256(
        f"{school_code}:{course_id}:{student_id}:{POLICY_VERSION}".encode("utf-8")
    ).digest()
    ratio = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
    return round(0.45 + ratio * 0.5, 6)


class Command(BaseCommand):
    help = "为测试学校生成可删除的共同测试层级与动态分组验收数据。"

    def add_arguments(self, parser):
        parser.add_argument("--school-code", required=True)
        parser.add_argument("--confirmation", default="")
        parser.add_argument("--allow-non-synthetic", action="store_true")
        parser.add_argument("--clear", action="store_true")

    def handle(self, *args, **options):
        school = School.objects.filter(code=options["school_code"]).first()
        if school is None:
            raise CommandError("学校不存在。")
        if options["confirmation"] != CONFIRMATION:
            raise CommandError(f"必须提供 --confirmation {CONFIRMATION}。")
        if not school.is_synthetic and not options["allow_non_synthetic"]:
            raise CommandError("非模拟学校必须额外提供 --allow-non-synthetic。")
        if options["clear"]:
            self._clear(school)
            return

        created = 0
        skipped = 0
        distribution = {"A": 0, "B": 0, "C": 0}
        now = timezone.now()
        courses = (
            Course.objects.filter(subject__school=school, subject__isnull=False)
            .select_related("subject", "teacher")
            .prefetch_related("course_classes", "lessons")
            .order_by("id")
        )
        with transaction.atomic():
            for course in courses:
                class_ids = list(
                    course.course_classes.values_list("class_group_id", flat=True)
                )
                lesson_ids = list(course.lessons.values_list("id", flat=True))
                profiles = StudentProfile.objects.select_related("user").filter(
                    class_group_id__in=class_ids,
                    user__school=school,
                    user__is_active=True,
                )
                for profile in profiles:
                    if StudentSubjectBand.objects.filter(
                        student=profile.user,
                        course=course,
                        valid_until__isnull=True,
                        policy_version=POLICY_VERSION,
                    ).exists():
                        skipped += 1
                        continue
                    score = _simulated_mastery(
                        school_code=school.code,
                        course_id=course.id,
                        student_id=profile.user_id,
                    )
                    decision = build_content_band_candidate(
                        student_profile=profile,
                        subject=course.subject,
                        course=course,
                        mastery_score=score,
                        evidence_snapshot={
                            "comparability_status": "verified",
                            "measurement_series": (
                                f"TEST-{school.code}-{course.subject.code}"
                            ),
                            "assessment_version": "acceptance-v1",
                            "is_test_data": True,
                            "task_readiness": {
                                "course_id": course.id,
                                "lesson_ids": lesson_ids,
                                "score": score,
                            },
                            "reasons": ["测试验收共同测试掌握度。"],
                        },
                        policy={
                            "version": POLICY_VERSION,
                            "a_min": 0.8,
                            "b_min": 0.6,
                            "boundary_margin": 0.03,
                        },
                        window_start=now - timedelta(days=7),
                        window_end=now,
                    )
                    band = apply_student_subject_band(
                        decision=decision,
                        selected_band=decision.suggested_layer,
                        confirmed_by=course.teacher,
                        effective_at=now,
                    )
                    decision.status = StratificationDecision.Status.ACCEPTED
                    decision.teacher_selected_layer = band.band
                    decision.review_note = "[测试数据验收] 模拟共同测试层级。"
                    decision.reviewed_by = course.teacher
                    decision.reviewed_at = now
                    decision.save(
                        update_fields=[
                            "status",
                            "teacher_selected_layer",
                            "review_note",
                            "reviewed_by",
                            "reviewed_at",
                        ]
                    )
                    distribution[band.band] += 1
                    created += 1

        grouping_checks = self._check_grouping(school)
        self.stdout.write(
            self.style.SUCCESS(
                f"正式层级测试数据已生成：新增 {created}，跳过 {skipped}，"
                f"A/B/C={distribution['A']}/{distribution['B']}/{distribution['C']}。"
            )
        )
        for row in grouping_checks:
            self.stdout.write(
                f"课堂 {row['session_id']}：{row['effective_strategy']}，"
                f"任务准备度覆盖 {row['coverage']:.0%}，分为 {row['group_count']} 组。"
            )

    def _check_grouping(self, school):
        rows = []
        sessions = ClassroomSession.objects.filter(
            school=school,
            status=ClassroomSession.Status.RUNNING,
            course__subject__isnull=False,
        ).select_related("course__subject", "lesson", "class_group")
        for session in sessions:
            profiles = list(
                StudentProfile.objects.select_related("user")
                .filter(class_group=session.class_group, user__is_active=True)
                .order_by("student_no", "user__username")
            )
            if not profiles:
                continue
            plan = build_grouping_plan(
                session=session,
                profiles=profiles,
                group_size=4,
                strategy=ClassroomGroupCollaboration.GroupingStrategy.AI_LAYER,
                seed=session.id * 1000 + 1,
                plan_version=1,
            )
            rows.append(
                {
                    "session_id": session.id,
                    "effective_strategy": plan.metadata["effective_strategy"],
                    "coverage": plan.metadata["task_readiness_coverage"],
                    "group_count": len(plan.chunks),
                }
            )
        return rows

    def _clear(self, school):
        bands = StudentSubjectBand.objects.filter(
            school=school,
            policy_version=POLICY_VERSION,
        )
        student_ids = list(bands.values_list("student_id", flat=True).distinct())
        band_count = bands.count()
        bands.delete()
        StratificationDecision.objects.filter(
            student_id__in=student_ids,
            policy_version=POLICY_VERSION,
        ).delete()
        self.stdout.write(self.style.SUCCESS(f"已清除 {band_count} 条测试层级。"))
