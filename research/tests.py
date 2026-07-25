from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from courses.models import Course, CourseClass, Subject
from school.models import ClassGroup, School

from .models import (
    ResearchCohortAssignment,
    ResearchDataLock,
    ResearchGateDecision,
    ResearchProtocolVersion,
    ResearchRun,
    ResearchStage,
    ResearchStudy,
)


def protocol_body():
    return {
        "research_questions": ["冻结政策在指定情境下是否达到预注册门槛？"],
        "estimands": ["班级集群层面的意向治疗效应"],
        "primary_outcomes": ["独立的后测学习结果"],
        "safety_outcomes": ["学习机会差异", "分组变动负担"],
        "inclusion_criteria": ["纳入冻结班级清单中的学生"],
        "exclusion_criteria": ["未获得评价机会"],
        "missing_data_plan": "分别报告缺失原因并进行敏感性分析。",
        "analysis_plan": "按预注册的集群模型报告效应量和置信区间。",
        "stopping_rules": "发生重大机会伤害时暂停。",
        "claim_boundary": "只适用于本学科、学段、版本和参与学校。",
    }


class ResearchGovernanceApiTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="研究治理学校", code="RG-01")
        self.other_school = School.objects.create(name="其他研究学校", code="RG-02")
        self.admin = User.objects.create_user(
            username="research_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.school,
        )
        self.other_admin = User.objects.create_user(
            username="other_research_admin",
            password="Admin123!",
            role=User.Role.SCHOOL_ADMIN,
            school=self.other_school,
        )
        self.teacher = User.objects.create_user(
            username="research_teacher",
            password="Teacher123!",
            role=User.Role.TEACHER,
            school=self.school,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="信息科技",
            code="IT",
            created_by=self.admin,
        )
        self.course = Course.objects.create(
            subject=self.subject,
            title="数据与计算研究课程",
            teacher=self.teacher,
            is_active=True,
        )
        self.classes = [
            ClassGroup.objects.create(
                school=self.school, name=f"高一{i}班", grade="高一"
            )
            for i in range(1, 5)
        ]
        for class_group in self.classes:
            CourseClass.objects.create(
                course=self.course,
                class_group=class_group,
                created_by=self.admin,
            )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def create_study(self, *, code="IT-E3"):
        response = self.client.post(
            "/api/v1/school-admin/research/studies/",
            {
                "code": code,
                "title": "信息科技研究治理验收",
                "subject_id": self.subject.id,
                "course_id": self.course.id,
                "description": "只验证研究治理流程，不生成教育效果结论。",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]["id"]

    def register(self, study_id, *, stage="E3", design_type="shadow"):
        now = timezone.now()
        payload = {
            "stage": stage,
            "design_type": design_type,
            "protocol": protocol_body(),
            "ethics_approval_ref": "IRB-2026-001",
            "ethics_approved_at": now.date().isoformat(),
            "preregistration_ref": "https://example.invalid/prereg/001",
            "preregistered_at": now.isoformat(),
            "consent_required": True,
            "consent_plan": "取得学校、监护人与学生适龄同意，并允许随时退出。",
        }
        if stage in {"E4", "E5", "E6"}:
            payload["policy_snapshot"] = {
                "evaluation_policy": "evaluation-v1",
                "content_band_policy": "band-v1",
                "grouping_policy": "group-v1",
            }
        response = self.client.post(
            f"/api/v1/school-admin/research/studies/{study_id}/register/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]["id"]

    def approve_required_gates(self, protocol_id):
        protocol = ResearchProtocolVersion.objects.get(pk=protocol_id)
        required = {
            item["value"]
            for item in self.client.get(
                f"/api/v1/school-admin/research/protocols/{protocol_id}/"
            ).data["data"]["required_gates"]
        }
        for gate in required:
            response = self.client.post(
                f"/api/v1/school-admin/research/protocols/{protocol_id}/gates/",
                {
                    "gate": gate,
                    "decision": "approved",
                    "evidence_ref": f"EVIDENCE-{protocol.stage}-{gate}",
                    "note": "工程验收记录，不替代真实外部审批。",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)

    def assign(self, protocol_id, class_group, arm, index):
        response = self.client.post(
            f"/api/v1/school-admin/research/protocols/{protocol_id}/cohorts/",
            {
                "class_group_id": class_group.id,
                "arm": arm,
                "allocation_method": "stratified_random",
                "allocation_unit_code": f"CLUSTER-{index}",
                "development_site": True,
                "prior_policy_access": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]

    def test_protocol_is_complete_versioned_and_immutable(self):
        study_id = self.create_study()
        incomplete = self.client.post(
            f"/api/v1/school-admin/research/studies/{study_id}/register/",
            {
                "stage": "E3",
                "design_type": "shadow",
                "protocol": {"research_questions": ["不完整"]},
            },
            format="json",
        )
        self.assertEqual(incomplete.status_code, 400)
        protocol_id = self.register(study_id)
        protocol = ResearchProtocolVersion.objects.get(pk=protocol_id)
        self.assertEqual(len(protocol.content_hash), 64)
        with self.assertRaisesMessage(ValidationError, "不可改写"):
            protocol.protocol = {"research_questions": ["试图覆盖"]}
            protocol.save()
        with self.assertRaisesMessage(ValidationError, "不可批量修改"):
            ResearchProtocolVersion.objects.filter(pk=protocol_id).update(stage="E4")

    def test_shadow_run_requires_all_gates_and_never_changes_teaching(self):
        protocol_id = self.register(self.create_study())
        self.assign(protocol_id, self.classes[0], "observational", 1)
        run_response = self.client.post(
            f"/api/v1/school-admin/research/protocols/{protocol_id}/runs/",
            {
                "run_code": "SHADOW-001",
                "mode": "shadow",
                "decision_effect": False,
            },
            format="json",
        )
        self.assertEqual(run_response.status_code, 201, run_response.data)
        run_id = run_response.data["data"]["id"]
        blocked = self.client.post(
            f"/api/v1/school-admin/research/runs/{run_id}/activate/", {}, format="json"
        )
        self.assertEqual(blocked.status_code, 400)
        self.approve_required_gates(protocol_id)
        activated = self.client.post(
            f"/api/v1/school-admin/research/runs/{run_id}/activate/", {}, format="json"
        )
        self.assertEqual(activated.status_code, 200, activated.data)
        self.assertFalse(activated.data["data"]["decision_effect"])
        self.assertFalse(activated.data["data"]["automatic_action_enabled"])

    def test_e5_requires_frozen_experiment_and_control_clusters_then_locks_data(self):
        protocol_id = self.register(
            self.create_study(code="IT-E5"),
            stage="E5",
            design_type="cluster_trial",
        )
        self.approve_required_gates(protocol_id)
        for index, class_group in enumerate(self.classes, start=1):
            self.assign(
                protocol_id,
                class_group,
                "experiment" if index <= 2 else "control",
                index,
            )
        planned = self.client.post(
            f"/api/v1/school-admin/research/protocols/{protocol_id}/runs/",
            {
                "run_code": "E5-CLUSTER-001",
                "mode": "cluster_trial",
                "decision_effect": True,
            },
            format="json",
        )
        self.assertEqual(planned.status_code, 201, planned.data)
        run_id = planned.data["data"]["id"]
        run = ResearchRun.objects.get(pk=run_id)
        run.status = ResearchRun.Status.DATA_LOCKED
        with self.assertRaisesMessage(ValidationError, "计划、启动、结束、数据锁定"):
            run.save()
        activated = self.client.post(
            f"/api/v1/school-admin/research/runs/{run_id}/activate/", {}, format="json"
        )
        self.assertEqual(activated.status_code, 200, activated.data)
        assignment = ResearchCohortAssignment.objects.filter(
            protocol_id=protocol_id
        ).first()
        exposure = self.client.post(
            f"/api/v1/school-admin/research/runs/{run_id}/exposures/",
            {
                "cohort_assignment_id": assignment.id,
                "observed_on": timezone.localdate().isoformat(),
                "actual_exposure": "assigned",
                "contamination_detected": False,
                "implementation_fidelity": 0.9,
                "opportunity_summary": {"offered": 28, "received": 27},
                "note": "记录实际实施机会，不把计划分配当作实际暴露。",
            },
            format="json",
        )
        self.assertEqual(exposure.status_code, 201, exposure.data)
        closed = self.client.post(
            f"/api/v1/school-admin/research/runs/{run_id}/close/", {}, format="json"
        )
        self.assertEqual(closed.status_code, 200, closed.data)
        now = timezone.now()
        locked = self.client.post(
            f"/api/v1/school-admin/research/runs/{run_id}/data-lock/",
            {
                "decision_as_of": (now - timedelta(days=30)).isoformat(),
                "data_cutoff": now.isoformat(),
                "dataset_manifest": {"diagnostic": "exact-version-1"},
                "variable_dictionary": [
                    {"name": "anonymous_student_id", "role": "identifier"},
                    {"name": "outcome", "role": "primary_outcome"},
                ],
                "row_count": 120,
                "missingness_summary": {"outcome_missing": 3},
                "exclusion_summary": {"not_offered": 1},
                "dataset_hash": "a" * 64,
            },
            format="json",
        )
        self.assertEqual(locked.status_code, 200, locked.data)
        data_lock = ResearchDataLock.objects.get(run_id=run_id)
        self.assertEqual(len(data_lock.content_hash), 64)
        analysis = self.client.post(
            f"/api/v1/school-admin/research/data-locks/{data_lock.id}/analyses/",
            {
                "analysis_key": "PRIMARY-ITT-001",
                "status": "completed",
                "parameters": {"population": "intention_to_treat", "alpha": 0.05},
                "software_versions": {"engine": "SPSS-compatible export", "python": "3.12"},
                "result_summary": {"n": 120, "effect": "engineering-placeholder"},
            },
            format="json",
        )
        self.assertEqual(analysis.status_code, 201, analysis.data)
        export = self.client.get(
            f"/api/v1/school-admin/research/protocols/{protocol_id}/export/"
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn("spreadsheetml", export["Content-Type"])
        with self.assertRaisesMessage(ValidationError, "不可改写"):
            data_lock.row_count = 121
            data_lock.save()

    def test_e6_rejects_development_site_and_cross_school_access(self):
        protocol_id = self.register(
            self.create_study(code="IT-E6"),
            stage="E6",
            design_type="external_confirmation",
        )
        rejected = self.client.post(
            f"/api/v1/school-admin/research/protocols/{protocol_id}/cohorts/",
            {
                "class_group_id": self.classes[0].id,
                "arm": "external_confirmation",
                "allocation_method": "observational",
                "allocation_unit_code": "EXTERNAL-1",
                "development_site": True,
                "prior_policy_access": False,
            },
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        other = APIClient()
        other.force_authenticate(self.other_admin)
        hidden = other.get(
            f"/api/v1/school-admin/research/protocols/{protocol_id}/"
        )
        self.assertEqual(hidden.status_code, 404)

    def test_teacher_cannot_access_research_governance_api(self):
        teacher_client = APIClient()
        teacher_client.force_authenticate(self.teacher)
        response = teacher_client.get("/api/v1/school-admin/research/studies/")
        self.assertEqual(response.status_code, 403)

    def test_information_technology_example_command_only_creates_an_idempotent_draft(self):
        for _ in range(2):
            call_command(
                "seed_information_technology_experiment_example",
                school_code=self.school.code,
                school_admin=self.admin.username,
                course_id=self.course.id,
                confirmation="SEED-INFORMATION-TECHNOLOGY-EXPERIMENT-EXAMPLE",
                stdout=StringIO(),
            )
        study = ResearchStudy.objects.get(
            school=self.school,
            code="IT-CLASS-EXPERIMENT-EXAMPLE",
        )
        self.assertEqual(study.status, ResearchStudy.Status.DRAFT)
        self.assertIsNone(study.current_protocol_id)
        self.assertFalse(study.protocol_versions.exists())
