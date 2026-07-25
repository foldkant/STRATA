import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import AppSelect from '@/components/AppSelect.vue'
import type {
  ClassroomGroupCollaborationPayload,
  ClassroomGroupCollaborationRow,
  GroupingCandidate,
  GroupingCandidateRun,
  GroupingDecisionPayload,
  GroupingDecisionPoint,
  GroupingPlanVersion
} from '@/api/teacher'
import ClassroomGroupCollaborationModal from './ClassroomGroupCollaborationModal.vue'

let wrapper: VueWrapper | null = null

const form: ClassroomGroupCollaborationPayload = {
  group_size: 4,
  grouping_strategy: 'balanced_layer',
  document_type: 'docx',
  storage_quota_mb: 20,
  allow_student_upload: true,
  allow_onlyoffice_edit: true
}

const decisionForm: GroupingDecisionPayload = {
  task_purpose: 'project_learning',
  task_stage: '项目方案形成',
  role_requirements: ['coordinator', 'recorder', 'presenter', 'verifier'],
  resource_requirements: ['项目任务单', '共享素材库'],
  safety_constraints: { prohibited_pairs: [] },
  opportunity_requirements: {
    required_group_roles: ['coordinator', 'recorder'],
    required_for_every_student: ['collaboration']
  },
  stability_until: '2026-08-05T10:00'
}

const collaboration: ClassroomGroupCollaborationRow = {
  id: 12,
  session: 8,
  is_enabled: false,
  status: 'draft',
  status_label: '草稿',
  group_size: 4,
  grouping_strategy: 'balanced_layer',
  grouping_strategy_label: '同伴互助',
  document_type: 'docx',
  document_type_label: 'Word 文档',
  storage_quota_mb: 20,
  allow_student_upload: true,
  allow_onlyoffice_edit: true,
  group_count: 0,
  my_group_id: null,
  my_group: null,
  groups: [],
  opened_at: null,
  closed_at: null,
  created_at: '2026-07-22T08:00:00+08:00',
  updated_at: '2026-07-22T08:00:00+08:00'
}

function decision(status: GroupingDecisionPoint['status'] = 'open'): GroupingDecisionPoint {
  return {
    id: 21,
    point_id: 'decision-21',
    status,
    status_label: status,
    trigger: 'teacher_request',
    task_purpose: 'project_learning',
    task_purpose_label: '项目学习',
    task_stage: '项目方案形成',
    role_requirements: ['coordinator', 'recorder', 'presenter', 'verifier'],
    resource_requirements: ['项目任务单', '共享素材库'],
    safety_constraints: { prohibited_pairs: [] },
    opportunity_requirements: {
      required_group_roles: ['coordinator', 'recorder'],
      required_for_every_student: ['collaboration']
    },
    stability_until: '2026-08-05T10:00:00+08:00',
    scheduled_for: '2026-07-22T10:00:00+08:00',
    created_at: '2026-07-22T10:00:00+08:00'
  }
}

function candidate(key: string, label: string): GroupingCandidate {
  return {
    key,
    label,
    assignments: [
      {
        group_no: 1,
        members: [
          {
            student_id: key === 'a' ? 101 : 102,
            username: key === 'a' ? 'student-a' : 'student-b',
            display_name: key === 'a' ? '学生甲' : '学生乙',
            student_no: key === 'a' ? 'S101' : 'S102',
            role: 'coordinator',
            locked: false
          }
        ]
      }
    ],
    metadata: { internal_basis: 'must-not-be-rendered' },
    fairness: {
      student_count: 1,
      unique_student_count: 1,
      min_group_size: 1,
      max_group_size: 1,
      group_size_gap: 0,
      readiness_mean_gap: 0,
      role_counts: { coordinator: 1 }
    },
    constraint_status: 'passed',
    constraint_blockers: []
  }
}

const candidates = [candidate('a', '方案甲'), candidate('b', '方案乙')]

function candidateRun(selectedCandidateKey = ''): GroupingCandidateRun {
  return {
    id: 31,
    run_id: 'run-31',
    status: 'ready',
    status_label: '可复核',
    algorithm_version: 'group-cp-sat-v1',
    policy: {
      id: 1,
      name: '课堂分组标准',
      strategy: 'skill_complementary',
      strategy_label: '任务互补',
      min_group_size: 2,
      max_group_size: 5,
      roles: ['coordinator', 'recorder', 'presenter', 'verifier']
    },
    decision_point: decision('candidate_ready'),
    students: candidates.map((item) => item.assignments[0].members[0]),
    locked_assignments: {},
    candidates,
    candidate_count: 2,
    conflicts: [],
    selected_candidate_key: selectedCandidateKey,
    created_at: '2026-07-22T10:01:00+08:00',
    finished_at: '2026-07-22T10:01:02+08:00'
  }
}

function plan(status: GroupingPlanVersion['status'], notifiedAt: string | null = null): GroupingPlanVersion {
  return {
    id: 41,
    plan_id: 'plan-41',
    plan_version: 1,
    status,
    status_label: status,
    candidate_key: 'a',
    assignments: candidates[0].assignments,
    adjustment_note: '',
    confirmed_at: '2026-07-22T10:05:00+08:00',
    activated_at: status === 'active' ? '2026-07-22T10:06:00+08:00' : null,
    notified_at: notifiedAt,
    decision_point: decision(status === 'reviewed' ? 'reviewed' : notifiedAt ? 'notified' : 'active')
  }
}

function mountModal(overrides: Record<string, unknown> = {}) {
  wrapper = mount(ClassroomGroupCollaborationModal, {
    attachTo: document.body,
    props: {
      open: true,
      loading: false,
      sessionTitle: '信息科技项目课堂',
      classLabel: '七年级 1 班',
      statusMessage: '',
      draftSaved: false,
      collaboration: null,
      strategyOptions: [
        { value: 'balanced_layer', label: '同伴互助', description: '形成可比较候选' },
        { value: 'random', label: '日常随机', description: '形成随机候选' }
      ],
      students: [
        { student_id: 101, username: 'student-a', display_name: '学生甲', student_no: 'S101' },
        { student_id: 102, username: 'student-b', display_name: '学生乙', student_no: 'S102' }
      ],
      decision: null,
      groupingRun: null,
      selectedCandidate: null,
      plan: null,
      fallbackMessage: '',
      collaborationStatusText: '未启用',
      groups: [],
      form: { ...form },
      decisionForm: {
        ...decisionForm,
        role_requirements: [...decisionForm.role_requirements],
        resource_requirements: [...decisionForm.resource_requirements],
        safety_constraints: { prohibited_pairs: [] },
        opportunity_requirements: {
          required_group_roles: [...decisionForm.opportunity_requirements.required_group_roles],
          required_for_every_student: [...decisionForm.opportunity_requirements.required_for_every_student]
        }
      },
      candidateKey: '',
      groupingDraft: [],
      groupingLocks: {},
      groupingNote: '',
      activeDocument: null,
      ...overrides
    },
    global: {
      components: { AppSelect },
      stubs: { OnlyOfficeEditor: true }
    }
  })
  return wrapper
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('teacher classroom grouping workflow', () => {
  it('starts with an explicit draft-only action and never promises automatic default grouping', async () => {
    const view = mountModal()
    await flushPromises()

    expect(view.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(view.findAll('.grouping-stepper li')).toHaveLength(6)
    expect(view.get('[data-step="1"]').text()).toContain('仅保存为草稿')
    expect(view.text()).toContain('系统不会默认自动分组')
    expect(view.text()).toContain('系统不会仅因保存设置而自动分组')
    expect(view.find('[data-action="generate"]').exists()).toBe(false)
    expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭')

    await view.get('[data-action="save-draft"]').trigger('click')
    expect(view.emitted('saveDraft')).toHaveLength(1)
  })

  it('requires the education task, roles, resources, safety, opportunities and stability period before candidates', async () => {
    const view = mountModal({ collaboration, draftSaved: true })

    expect(view.get('[data-step="2"]').text()).toContain('学习任务目的')
    expect(view.text()).toContain('学习阶段')
    expect(view.text()).toContain('小组角色')
    expect(view.text()).toContain('可用学习资源')
    expect(view.text()).toContain('学生安全约束')
    expect(view.text()).toContain('学习机会要求')
    expect(view.text()).toContain('小组稳定期结束时间')
    expect(view.text()).toContain('当前确认：无需设置学生分开约束')

    const action = view.get<HTMLButtonElement>('[data-action="save-decision"]')
    expect(action.attributes()).not.toHaveProperty('disabled')
    await action.trigger('click')
    expect(view.emitted('saveDecision')).toHaveLength(1)
  })

  it('keeps generation, review, activation and notification as four separate teacher actions', async () => {
    const point = decision('open')
    const view = mountModal({ collaboration, draftSaved: true, decision: point })

    expect(view.get('[data-step="3"]').text()).toContain('至少两套候选方案')
    await view.get('[data-action="generate"]').trigger('click')
    expect(view.emitted('generateCandidates')).toHaveLength(1)

    const run = candidateRun()
    await view.setProps({ groupingRun: run, decision: run.decision_point })
    expect(view.get('[data-step="4"]').text()).toContain('复核只保存教师决定，不会启用分组')
    expect(view.text()).not.toContain('must-not-be-rendered')
    expect(view.get<HTMLButtonElement>('[data-action="confirm-review"]').attributes()).toHaveProperty('disabled')

    await view.findAll('[role="tab"]')[0].trigger('click')
    expect(view.emitted('selectCandidate')).toEqual([['a']])
    await view.setProps({
      candidateKey: 'a',
      selectedCandidate: candidates[0],
      groupingDraft: candidates[0].assignments
    })
    await view.get('[data-action="confirm-review"]').trigger('click')
    expect(view.emitted('confirmReview')).toHaveLength(1)
    expect(view.emitted('activate')).toBeUndefined()

    await view.setProps({ plan: plan('reviewed') })
    expect(view.get('[data-step="5"]').text()).toContain('此操作不会自动发送学生通知')
    await view.get('[data-action="activate"]').trigger('click')
    expect(view.emitted('activate')).toHaveLength(1)
    expect(view.emitted('notifyStudents')).toBeUndefined()

    await view.setProps({ plan: plan('active') })
    expect(view.get('[data-step="6"]').text()).toContain('已启用，尚未通知')
    expect(view.text()).toContain('不呈现教师内部判断依据')
    await view.get('[data-action="notify"]').trigger('click')
    expect(view.emitted('notifyStudents')).toHaveLength(1)

    await view.setProps({ plan: plan('active', '2026-07-22T10:07:00+08:00') })
    expect(view.get('[data-step="6"]').text()).toContain('分组流程已完成')
    expect(view.find('[data-action="notify"]').exists()).toBe(false)
  })
})
