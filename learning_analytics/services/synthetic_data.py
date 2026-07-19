from __future__ import annotations

import hashlib
import json
import math
import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from courses.models import (
    ClassroomSession,
    Course,
    CourseClass,
    Lesson,
    LessonStep,
    Subject,
)
from learning.models import LearningEvent
from learning_analytics.models import (
    DataQualityReport,
    LearningOpportunity,
    SyntheticDatasetRun,
    SyntheticStudentTruth,
)
from learning_analytics.services.dual_write import record_learning_event
from learning_analytics.services.quality import (
    create_quality_pipeline_run,
    execute_quality_pipeline,
)
from learning_analytics.services.schema_registry import sync_event_schema_definitions
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment

GENERATOR_VERSION = "synthetic-v1"
EVENT_NAMESPACE = uuid.UUID("d2fe154f-7aaf-46e5-8c8f-a037584854f1")


class SyntheticDataError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SyntheticDataConfig:
    school_code: str
    school_name: str
    seed: int
    class_count: int
    students_per_class: int
    weeks: int
    end_date: date
    mode: str = SyntheticDatasetRun.Mode.ISOLATED_SCHOOL
    teacher_username: str = ""
    scenario: str = "clean_baseline"

    @property
    def start_date(self) -> date:
        return self.end_date - timedelta(days=self.weeks * 7 - 1)

    @property
    def window_start(self):
        return timezone.make_aware(
            datetime.combine(self.start_date, time.min),
            timezone.get_current_timezone(),
        )

    @property
    def window_end(self):
        return timezone.make_aware(
            datetime.combine(self.end_date + timedelta(days=1), time.min),
            timezone.get_current_timezone(),
        )

    def as_dict(self) -> dict:
        return {
            "generator_version": GENERATOR_VERSION,
            "scenario": self.scenario,
            "school_code": self.school_code,
            "school_name": self.school_name,
            "seed": self.seed,
            "class_count": self.class_count,
            "students_per_class": self.students_per_class,
            "weeks": self.weeks,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "mode": self.mode,
            "teacher_username": self.teacher_username,
        }

    @property
    def dataset_key(self) -> str:
        encoded = json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class SyntheticStudentState:
    user: User
    class_group: ClassGroup
    prior_mastery: float
    engagement: float
    self_regulation: float
    response_speed: float
    growth_rate: float
    class_effect: float


def validate_synthetic_config(config: SyntheticDataConfig) -> None:
    if not config.school_code or len(config.school_code) > 32:
        raise SyntheticDataError("模拟学校代码长度必须为 1-32 个字符。")
    if not config.school_name or len(config.school_name) > 128:
        raise SyntheticDataError("模拟学校名称长度必须为 1-128 个字符。")
    if not 1 <= config.class_count <= 24:
        raise SyntheticDataError("班级数必须位于 1-24。")
    if not 2 <= config.students_per_class <= 60:
        raise SyntheticDataError("每班学生数必须位于 2-60。")
    if not 1 <= config.weeks <= 52:
        raise SyntheticDataError("模拟周数必须位于 1-52。")
    if not 0 <= config.seed <= 2**63 - 1:
        raise SyntheticDataError("随机种子必须位于 0 到 2^63-1。")
    if config.end_date >= timezone.localdate():
        raise SyntheticDataError("模拟结束日期必须早于当前日期。")
    if config.scenario != "clean_baseline":
        raise SyntheticDataError("当前仅支持 clean_baseline 合成场景。")
    if config.mode not in {item.value for item in SyntheticDatasetRun.Mode}:
        raise SyntheticDataError("合成数据运行模式不正确。")
    if (
        config.mode == SyntheticDatasetRun.Mode.SCHOOL_OVERLAY
        and not config.teacher_username
    ):
        raise SyntheticDataError("校内测试叠加模式必须指定 --teacher-username。")


def estimate_synthetic_dataset(config: SyntheticDataConfig) -> dict:
    validate_synthetic_config(config)
    students = config.class_count * config.students_per_class
    releases = config.class_count * config.weeks * 2
    fixed_student_events = students * config.weeks * 2
    expected_optional_events = round(students * config.weeks * 3.4)
    return {
        "schools": 1,
        "classes": config.class_count,
        "students": students,
        "weeks": config.weeks,
        "estimated_events": releases + fixed_student_events + expected_optional_events,
        "window_start": config.window_start.isoformat(),
        "window_end": config.window_end.isoformat(),
        "dataset_key": config.dataset_key,
    }


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _decimal(value: float, places: int = 4) -> Decimal:
    return Decimal(f"{value:.{places}f}")


def _event_uuid(dataset_key: str, event_key: str) -> uuid.UUID:
    return uuid.uuid5(EVENT_NAMESPACE, f"{dataset_key}:{event_key}")


def _attempt_uuid(dataset_key: str, attempt_key: str) -> uuid.UUID:
    return uuid.uuid5(EVENT_NAMESPACE, f"{dataset_key}:attempt:{attempt_key}")


def _record_event(
    *,
    run: SyntheticDatasetRun,
    event_key: str,
    occurred_at,
    received_delay_seconds: int,
    counts: dict,
    **kwargs,
):
    metadata = dict(kwargs.pop("legacy_metadata", {}) or {})
    metadata.update(
        {
            "synthetic": True,
            "synthetic_run_id": str(run.run_id),
            "generator_version": run.generator_version,
            "dataset_key": run.dataset_key,
        }
    )
    result = record_learning_event(
        event_id=_event_uuid(run.dataset_key, event_key),
        occurred_at=occurred_at,
        received_at=occurred_at + timedelta(seconds=received_delay_seconds),
        legacy_metadata=metadata,
        synthetic_run=run,
        **kwargs,
    )
    counts["events"] = counts.get("events", 0) + 1
    event_name = result.analytics_event.event_name
    event_names = counts.setdefault("event_names", {})
    event_names[event_name] = event_names.get(event_name, 0) + 1
    return result


def _create_school(config: SyntheticDataConfig) -> School:
    school = School.objects.filter(code=config.school_code).first()
    if config.mode == SyntheticDatasetRun.Mode.SCHOOL_OVERLAY:
        if school is None:
            raise SyntheticDataError("校内测试叠加要求目标学校已经存在。")
        if school.is_synthetic:
            raise SyntheticDataError("校内测试叠加不能写入独立模拟学校。")
        return school
    if school is None:
        return School.objects.create(
            code=config.school_code,
            name=config.school_name,
            is_synthetic=True,
            note="系统生成的合成数据研究学校，不属于正式运营统计。",
        )
    if not school.is_synthetic:
        raise SyntheticDataError("学校代码已被正式学校使用，不能写入合成数据。")
    if (
        school.synthetic_dataset_runs.exclude(dataset_key=config.dataset_key)
        .exclude(status=SyntheticDatasetRun.Status.PURGED)
        .exists()
    ):
        raise SyntheticDataError(
            "该模拟学校已绑定其他生成配置；请更换 --school-code，避免数据混合。"
        )
    return school


def _create_or_resume_run(
    *, school: School, config: SyntheticDataConfig
) -> SyntheticDatasetRun:
    run = SyntheticDatasetRun.objects.filter(dataset_key=config.dataset_key).first()
    if run:
        if run.school_id != school.id:
            raise SyntheticDataError("相同数据集指纹已属于另一所模拟学校。")
        return run
    if config.mode == SyntheticDatasetRun.Mode.ISOLATED_SCHOOL and (
        school.users.exists() or school.classes.exists() or school.subjects.exists()
    ):
        raise SyntheticDataError("模拟学校已有未登记到生成批次的数据，拒绝继续写入。")
    if (
        config.mode == SyntheticDatasetRun.Mode.SCHOOL_OVERLAY
        and school.synthetic_dataset_runs.exclude(
            status=SyntheticDatasetRun.Status.PURGED
        ).exists()
    ):
        raise SyntheticDataError("目标学校已有未清理的校内测试批次。")
    return SyntheticDatasetRun.objects.create(
        dataset_key=config.dataset_key,
        school=school,
        mode=config.mode,
        generator_version=GENERATOR_VERSION,
        seed=config.seed,
        window_start=config.window_start,
        window_end=config.window_end,
        configuration=config.as_dict(),
    )


def _create_student_states(
    *,
    run: SyntheticDatasetRun,
    config: SyntheticDataConfig,
    rng: random.Random,
    classes: list[ClassGroup],
) -> list[SyntheticStudentState]:
    states = []
    username_prefix = (
        f"sim_{run.dataset_key[:8]}"
        if config.mode == SyntheticDatasetRun.Mode.SCHOOL_OVERLAY
        else config.school_code.lower().replace("-", "_")
    )
    for class_index, class_group in enumerate(classes, start=1):
        class_effect = _clamp(rng.gauss(0, 0.055), -0.18, 0.18)
        for student_index in range(1, config.students_per_class + 1):
            user = User(
                username=(f"{username_prefix}_c{class_index:02d}s{student_index:03d}"),
                role=User.Role.STUDENT,
                school=run.school,
                display_name=f"模拟{class_index:02d}-{student_index:03d}",
                is_active=True,
                is_first_login=False,
            )
            if config.mode == SyntheticDatasetRun.Mode.SCHOOL_OVERLAY:
                user.set_password("123456")
            else:
                user.set_unusable_password()
            user.save()
            StudentProfile.objects.create(
                user=user,
                class_group=class_group,
                student_no=f"SIM{class_index:02d}{student_index:03d}",
                current_layer=None,
                score=0,
                is_first_use=False,
                onboarding_status=StudentProfile.OnboardingStatus.ACTIVE,
            )
            prior_mastery = _clamp(rng.betavariate(3.2, 3.0))
            engagement = _clamp(rng.betavariate(3.0, 2.4))
            self_regulation = _clamp(
                0.45 * engagement + 0.55 * rng.betavariate(2.8, 2.7)
            )
            response_speed = _clamp(
                0.35 * prior_mastery + 0.65 * rng.betavariate(3.0, 2.6)
            )
            growth_rate = _clamp(
                rng.gauss(0.018 + 0.014 * self_regulation, 0.008),
                -0.02,
                0.07,
            )
            SyntheticStudentTruth.objects.create(
                synthetic_run=run,
                student=user,
                class_group=class_group,
                prior_mastery=_decimal(prior_mastery),
                engagement=_decimal(engagement),
                self_regulation=_decimal(self_regulation),
                response_speed=_decimal(response_speed),
                growth_rate=_decimal(growth_rate, 5),
                class_effect=_decimal(class_effect, 5),
            )
            states.append(
                SyntheticStudentState(
                    user=user,
                    class_group=class_group,
                    prior_mastery=prior_mastery,
                    engagement=engagement,
                    self_regulation=self_regulation,
                    response_speed=response_speed,
                    growth_rate=growth_rate,
                    class_effect=class_effect,
                )
            )
    return states


def _quality_report_for_run(run: SyntheticDatasetRun) -> DataQualityReport:
    existing = DataQualityReport.objects.filter(
        school=run.school,
        synthetic_run=run,
        window_start=run.window_start,
        window_end=run.window_end,
    ).first()
    if existing:
        return existing
    pipeline_run = create_quality_pipeline_run(
        school=run.school,
        window_start=run.window_start,
        window_end=run.window_end,
        trigger="manual",
        synthetic_run=run,
    )
    return execute_quality_pipeline(pipeline_run)


def _result(run: SyntheticDatasetRun, *, reused: bool) -> dict:
    report = DataQualityReport.objects.filter(
        school=run.school,
        synthetic_run=run,
        window_start=run.window_start,
        window_end=run.window_end,
    ).first()
    return {
        "run_id": str(run.run_id),
        "dataset_key": run.dataset_key,
        "school_code": run.school.code,
        "status": run.status,
        "reused": reused,
        "window_start": run.window_start.isoformat(),
        "window_end": run.window_end.isoformat(),
        "counts": run.counts,
        "manifest_hash": run.manifest_hash,
        "quality": (
            {
                "report_id": str(report.report_id),
                "status": report.status,
                "checks_passed": report.checks_passed,
                "event_count": report.event_count,
                "unconverted_old_event_rate": float(report.unconverted_old_event_rate),
                "old_new_event_difference_rate": float(report.old_new_event_difference_rate),
                "issues": report.issues,
            }
            if report
            else None
        ),
    }


def generate_synthetic_dataset(
    config: SyntheticDataConfig, *, run_quality: bool = True
) -> dict:
    validate_synthetic_config(config)
    sync_event_schema_definitions()
    school = _create_school(config)
    run = _create_or_resume_run(school=school, config=config)
    if run.status == SyntheticDatasetRun.Status.SUCCEEDED:
        if run_quality:
            _quality_report_for_run(run)
        return _result(run, reused=True)

    rng = random.Random(config.seed)
    counts = {
        "schools": 1,
        "classes": 0,
        "teachers": 0,
        "students": 0,
        "subjects": 0,
        "courses": 0,
        "lessons": 0,
        "classroom_sessions": 0,
        "events": 0,
        "event_names": {},
    }
    manifest = hashlib.sha256()
    try:
        with transaction.atomic():
            run.status = SyntheticDatasetRun.Status.RUNNING
            run.error_message = ""
            run.started_at = timezone.now()
            run.finished_at = None
            run.purged_at = None
            run.purge_summary = {}
            run.save(
                update_fields=[
                    "status",
                    "error_message",
                    "started_at",
                    "finished_at",
                    "purged_at",
                    "purge_summary",
                ]
            )
            object_prefix = f"SIM-{run.dataset_key[:8].upper()}"
            if config.mode == SyntheticDatasetRun.Mode.SCHOOL_OVERLAY:
                teacher = User.objects.filter(
                    username=config.teacher_username,
                    role=User.Role.TEACHER,
                    school=school,
                    is_active=True,
                ).first()
                if teacher is None:
                    raise SyntheticDataError("指定教师不存在、已停用或不属于目标学校。")
                counts["teachers"] = 0
            else:
                username_prefix = config.school_code.lower().replace("-", "_")
                teacher = User(
                    username=f"{username_prefix}_teacher",
                    role=User.Role.TEACHER,
                    school=school,
                    display_name="模拟教师",
                    is_active=True,
                    is_first_login=False,
                )
                teacher.set_unusable_password()
                teacher.save()
                counts["teachers"] = 1
            subject = Subject.objects.create(
                school=school,
                name=f"信息科技（{object_prefix}）",
                code=object_prefix,
                created_by=teacher,
            )
            counts["subjects"] = 1
            classes = []
            for class_index in range(1, config.class_count + 1):
                class_group = ClassGroup.objects.create(
                    school=school,
                    name=f"[{object_prefix}] 高一{class_index}班",
                    grade="高一",
                    entry_year=config.start_date.year,
                )
                TeachingAssignment.objects.create(
                    school=school,
                    class_group=class_group,
                    teacher=teacher,
                )
                classes.append(class_group)
            counts["classes"] = len(classes)
            states = _create_student_states(
                run=run,
                config=config,
                rng=rng,
                classes=classes,
            )
            counts["students"] = len(states)
            states_by_class = {
                class_group.id: [
                    state for state in states if state.class_group.id == class_group.id
                ]
                for class_group in classes
            }
            course = Course.objects.create(
                subject=subject,
                title=f"数据与计算（{object_prefix}）",
                introduction="仅用于验证 STRATA 分析自动流程。",
                teacher=teacher,
                teaching_model=Course.TeachingModel.TASK,
                is_active=True,
            )
            counts["courses"] = 1
            for class_group in classes:
                CourseClass.objects.create(
                    course=course,
                    class_group=class_group,
                    created_by=teacher,
                )

            for week_index in range(config.weeks):
                lesson = Lesson.objects.create(
                    course=course,
                    title=f"第 {week_index + 1} 周学习任务",
                    content="合成研究课时。",
                    sort_order=week_index + 1,
                    is_active=True,
                )
                document_step = LessonStep.objects.create(
                    lesson=lesson,
                    title="概念资源学习",
                    step_type=LessonStep.StepType.RESOURCE,
                    sort_order=1,
                    estimated_minutes=12,
                    status=LessonStep.Status.READY,
                    created_by=teacher,
                )
                question_step = LessonStep.objects.create(
                    lesson=lesson,
                    title="概念理解检测",
                    step_type=LessonStep.StepType.QUESTION,
                    sort_order=2,
                    estimated_minutes=10,
                    status=LessonStep.Status.READY,
                    created_by=teacher,
                )
                counts["lessons"] += 1
                lesson_day = config.start_date + timedelta(days=week_index * 7 + 2)
                lesson_start = timezone.make_aware(
                    datetime.combine(lesson_day, time(hour=9)),
                    timezone.get_current_timezone(),
                )
                for class_index, class_group in enumerate(classes, start=1):
                    class_start = lesson_start + timedelta(
                        minutes=(class_index - 1) * 5
                    )
                    session = ClassroomSession.objects.create(
                        school=school,
                        teacher=teacher,
                        course=course,
                        lesson=lesson,
                        class_group=class_group,
                        title=f"{lesson.title} - {class_group.name}",
                        status=ClassroomSession.Status.FINISHED,
                        current_step=question_step,
                        current_step_status=ClassroomSession.StepStatus.CLOSED,
                        started_at=class_start,
                        finished_at=class_start + timedelta(minutes=45),
                    )
                    counts["classroom_sessions"] += 1
                    document_id = f"sim-doc-w{week_index + 1}-c{class_index}"
                    document_version = f"{document_id}@1"
                    document_release = _record_event(
                        run=run,
                        event_key=f"w{week_index}:c{class_index}:document:release",
                        occurred_at=class_start,
                        received_delay_seconds=2,
                        counts=counts,
                        actor=teacher,
                        event_name="content.released",
                        payload={
                            "content_type": "document",
                            "required": True,
                            "target_layers": ["all"],
                        },
                        legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                        class_group=class_group,
                        subject=subject,
                        course=course,
                        lesson=lesson,
                        classroom_session=session,
                        lesson_step=document_step,
                        object_type="document",
                        object_id=document_id,
                        object_version=document_version,
                    )
                    question_id = f"sim-q-w{week_index + 1}-c{class_index}"
                    question_version = f"{question_id}@1"
                    question_release = _record_event(
                        run=run,
                        event_key=f"w{week_index}:c{class_index}:question:release",
                        occurred_at=class_start + timedelta(minutes=15),
                        received_delay_seconds=2,
                        counts=counts,
                        actor=teacher,
                        event_name="content.released",
                        payload={
                            "content_type": "question",
                            "required": True,
                            "target_layers": ["all"],
                        },
                        legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                        class_group=class_group,
                        subject=subject,
                        course=course,
                        lesson=lesson,
                        classroom_session=session,
                        lesson_step=question_step,
                        object_type="question",
                        object_id=question_id,
                        object_version=question_version,
                    )
                    document_opportunities = {
                        item.student_id: item
                        for item in LearningOpportunity.objects.filter(
                            release_event=document_release.analytics_event
                        )
                    }
                    question_opportunities = {
                        item.student_id: item
                        for item in LearningOpportunity.objects.filter(
                            release_event=question_release.analytics_event
                        )
                    }
                    for student_index, state in enumerate(
                        states_by_class[class_group.id], start=1
                    ):
                        student_key = f"c{class_index}:s{student_index}:w{week_index}"
                        entry_at = class_start + timedelta(
                            minutes=1, seconds=rng.randint(0, 90)
                        )
                        _record_event(
                            run=run,
                            event_key=f"{student_key}:lesson-entered",
                            occurred_at=entry_at,
                            received_delay_seconds=rng.randint(1, 8),
                            counts=counts,
                            actor=state.user,
                            event_name="lesson.entered",
                            payload={"entrypoint": "classroom"},
                            legacy_event_type=LearningEvent.EventType.LESSON_ENTER,
                            class_group=class_group,
                            subject=subject,
                            course=course,
                            lesson=lesson,
                            classroom_session=session,
                            object_type="lesson",
                            object_id=lesson.id,
                            object_version=f"lesson-{lesson.id}@1",
                        )
                        _record_event(
                            run=run,
                            event_key=f"{student_key}:heartbeat",
                            occurred_at=entry_at + timedelta(minutes=2),
                            received_delay_seconds=rng.randint(1, 8),
                            counts=counts,
                            actor=state.user,
                            event_name="session.heartbeat",
                            payload={
                                "foreground": True,
                                "idle_seconds": max(
                                    0,
                                    round(
                                        95 * (1 - state.engagement) + rng.gauss(0, 12)
                                    ),
                                ),
                                "network_state": "online",
                            },
                            legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
                            class_group=class_group,
                            subject=subject,
                            course=course,
                            lesson=lesson,
                            classroom_session=session,
                        )
                        resource_probability = _clamp(
                            0.18
                            + 0.58 * state.engagement
                            + 0.18 * state.self_regulation
                        )
                        resource_opened = rng.random() < resource_probability
                        if resource_opened:
                            page = min(
                                12,
                                max(
                                    1,
                                    round(
                                        2
                                        + 8 * state.engagement
                                        + 2 * state.self_regulation
                                        + rng.gauss(0, 1.3)
                                    ),
                                ),
                            )
                            visible_seconds = _clamp(
                                25
                                + 150 * state.engagement
                                + 55 * state.self_regulation
                                + rng.gauss(0, 18),
                                5,
                                300,
                            )
                            document_opportunity = document_opportunities[state.user.id]
                            _record_event(
                                run=run,
                                event_key=f"{student_key}:document-progress",
                                occurred_at=entry_at + timedelta(minutes=5),
                                received_delay_seconds=rng.randint(1, 12),
                                counts=counts,
                                actor=state.user,
                                event_name="document.progress",
                                payload={
                                    "page": page,
                                    "page_count": 12,
                                    "visible_seconds": round(visible_seconds, 2),
                                },
                                legacy_event_type=LearningEvent.EventType.RESOURCE_VIEW,
                                class_group=class_group,
                                subject=subject,
                                course=course,
                                lesson=lesson,
                                classroom_session=session,
                                lesson_step=document_step,
                                object_type="document",
                                object_id=document_id,
                                object_version=document_version,
                                opportunity_id=document_opportunity.opportunity_id,
                                duration_ms=round(visible_seconds * 1000),
                            )

                        mastery = _clamp(
                            state.prior_mastery
                            + state.class_effect
                            + state.growth_rate * week_index
                            + rng.gauss(0, 0.035)
                        )
                        completion_probability = _clamp(
                            0.22
                            + 0.48 * state.engagement
                            + 0.24 * state.self_regulation
                            + (0.06 if resource_opened else -0.04)
                        )
                        submitted = rng.random() < completion_probability
                        correct = False
                        if submitted:
                            correct_probability = _logistic(
                                -2.25
                                + 4.7 * mastery
                                + 0.45 * state.self_regulation
                                + (0.25 if resource_opened else 0)
                            )
                            correct = rng.random() < correct_probability
                            response_ms = round(
                                _clamp(
                                    9000
                                    + 26000 * (1 - state.response_speed)
                                    + 11000 * (1 - mastery)
                                    + rng.gauss(0, 3500),
                                    3500,
                                    70000,
                                )
                            )
                            confidence = max(
                                1,
                                min(
                                    5,
                                    round(
                                        1.4
                                        + 2.7 * mastery
                                        + (0.55 if correct else -0.15)
                                        + rng.gauss(0, 0.45)
                                    ),
                                ),
                            )
                            attempt_id = _attempt_uuid(
                                run.dataset_key, f"{student_key}:{question_id}"
                            )
                            question_opportunity = question_opportunities[state.user.id]
                            submitted_at = class_start + timedelta(
                                minutes=20,
                                milliseconds=response_ms,
                            )
                            _record_event(
                                run=run,
                                event_key=f"{student_key}:item-submitted",
                                occurred_at=submitted_at,
                                received_delay_seconds=rng.randint(1, 10),
                                counts=counts,
                                actor=state.user,
                                event_name="item.submitted",
                                payload={
                                    "question_version": question_version,
                                    "response_kind": "single",
                                    "attempt_no": 1,
                                    "response_time_ms": response_ms,
                                    "learner_confidence_rating": confidence,
                                },
                                legacy_event_type=LearningEvent.EventType.ANSWER_SUBMIT,
                                class_group=class_group,
                                subject=subject,
                                course=course,
                                lesson=lesson,
                                classroom_session=session,
                                lesson_step=question_step,
                                object_type="question",
                                object_id=question_id,
                                object_version=question_version,
                                opportunity_id=question_opportunity.opportunity_id,
                                attempt_id=attempt_id,
                                duration_ms=response_ms,
                            )
                            score = 2 if correct else 0
                            _record_event(
                                run=run,
                                event_key=f"{student_key}:item-graded",
                                occurred_at=submitted_at + timedelta(seconds=3),
                                received_delay_seconds=rng.randint(1, 6),
                                counts=counts,
                                actor=teacher,
                                target_student=state.user,
                                event_name="item.graded",
                                payload={
                                    "grading_state": "final",
                                    "score_raw": score,
                                    "score_max": 2,
                                    "is_correct": correct,
                                    "grader_type": "automatic",
                                },
                                legacy_event_type=(
                                    LearningEvent.EventType.TEACHER_INTERVENTION
                                ),
                                class_group=class_group,
                                subject=subject,
                                course=course,
                                lesson=lesson,
                                classroom_session=session,
                                lesson_step=question_step,
                                object_type="question",
                                object_id=question_id,
                                object_version=question_version,
                                opportunity_id=question_opportunity.opportunity_id,
                                attempt_id=attempt_id,
                                legacy_score=score,
                            )
                            _record_event(
                                run=run,
                                event_key=f"{student_key}:step-completed",
                                occurred_at=submitted_at + timedelta(seconds=5),
                                received_delay_seconds=rng.randint(1, 6),
                                counts=counts,
                                actor=state.user,
                                event_name="lesson.step.completed",
                                payload={
                                    "step_type": LessonStep.StepType.QUESTION,
                                    "completion_source": "student",
                                },
                                legacy_event_type=LearningEvent.EventType.PAGE_VIEW,
                                class_group=class_group,
                                subject=subject,
                                course=course,
                                lesson=lesson,
                                classroom_session=session,
                                lesson_step=question_step,
                                object_type="lesson_step",
                                object_id=question_step.id,
                                object_version=f"step-{question_step.id}@1",
                            )

                        support_probability = _clamp(
                            0.04
                            + (0.16 if not submitted else 0)
                            + (0.12 if submitted and not correct else 0)
                            + 0.12 * (1 - state.engagement)
                        )
                        if rng.random() < support_probability:
                            reason_code = (
                                "missing_required_submission"
                                if not submitted
                                else "incorrect_response_support"
                            )
                            intensity = (
                                "medium"
                                if not submitted or state.engagement < 0.35
                                else "low"
                            )
                            _record_event(
                                run=run,
                                event_key=f"{student_key}:intervention",
                                occurred_at=class_start + timedelta(minutes=38),
                                received_delay_seconds=rng.randint(1, 8),
                                counts=counts,
                                actor=teacher,
                                target_student=state.user,
                                event_name="intervention.created",
                                payload={
                                    "intervention_type": "teacher_support_prompt",
                                    "reason_code": reason_code,
                                    "intensity": intensity,
                                },
                                legacy_event_type=(
                                    LearningEvent.EventType.TEACHER_INTERVENTION
                                ),
                                class_group=class_group,
                                subject=subject,
                                course=course,
                                lesson=lesson,
                                classroom_session=session,
                                object_type="student_support",
                                object_id=f"{state.user.id}-{week_index + 1}",
                                object_version="support-v1",
                            )

            counts["opportunities"] = LearningOpportunity.objects.filter(
                release_event__synthetic_run=run
            ).count()
            counts["student_truths"] = len(states)
            manifest.update(
                json.dumps(
                    {
                        "configuration": config.as_dict(),
                        "counts": counts,
                        "truths": [
                            {
                                "student_id": state.user.id,
                                "prior_mastery": round(state.prior_mastery, 6),
                                "engagement": round(state.engagement, 6),
                                "self_regulation": round(state.self_regulation, 6),
                                "response_speed": round(state.response_speed, 6),
                                "growth_rate": round(state.growth_rate, 6),
                                "class_effect": round(state.class_effect, 6),
                            }
                            for state in states
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            run.counts = counts
            run.manifest_hash = manifest.hexdigest()
            run.status = SyntheticDatasetRun.Status.SUCCEEDED
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "counts",
                    "manifest_hash",
                    "status",
                    "finished_at",
                ]
            )
    except Exception as exc:
        run.status = SyntheticDatasetRun.Status.FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"[:1000]
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        raise

    if run_quality:
        report = _quality_report_for_run(run)
        counts = dict(run.counts)
        counts["quality_report_id"] = str(report.report_id)
        counts["quality_checks_passed"] = report.checks_passed
        run.counts = counts
        run.save(update_fields=["counts"])
    return _result(run, reused=False)
