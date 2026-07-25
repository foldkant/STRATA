import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResearchGovernanceView from '../ResearchGovernanceView.vue'

const mocks = vi.hoisted(() => ({
  getResearchOptions: vi.fn(),
  getResearchStudies: vi.fn(),
  getResearchStudy: vi.fn(),
  createResearchStudy: vi.fn(),
  registerResearchProtocol: vi.fn(),
  recordResearchGate: vi.fn(),
  freezeResearchCohort: vi.fn(),
  createResearchRun: vi.fn(),
  activateResearchRun: vi.fn(),
  closeResearchRun: vi.fn(),
  lockResearchRunData: vi.fn()
}))

vi.mock('@/api/research', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/research')>(),
  ...mocks
}))

const protocol = {
  id: 9,
  version_no: 1,
  stage: 'E5',
  stage_label: '班级对照实验',
  design_type: 'cluster_trial',
  design_type_label: '班级对照实验',
  content_hash: 'a'.repeat(64),
  policy_hash: 'b'.repeat(64),
  protocol: {
    research_questions: ['项目式学习是否有助于学生的数据问题解决表现？'],
    estimands: ['实验班与对照班共同后测差异'],
    primary_outcomes: ['数据处理表现任务', '学生学习体验问卷'],
    safety_outcomes: ['额外学习负担'],
    inclusion_criteria: ['参加共同前测的班级'],
    missing_data_plan: '缺测单独标记，不补成低分。'
  },
  ethics_approval_ref: 'IRB-001',
  ethics_approved_at: '2026-07-01',
  preregistration_ref: 'REG-001',
  preregistered_at: '2026-07-02T08:00:00+08:00',
  registered_at: '2026-07-02T09:00:00+08:00',
  required_gates: [
    { value: 'ethics', label: '伦理审批' },
    { value: 'data_quality', label: '数据质量' }
  ],
  approved_gates: ['ethics'],
  missing_gates: [{ value: 'data_quality', label: '数据质量' }],
  cohort_count: 0,
  run_count: 0,
  cohort_assignments: [],
  runs: []
}

const study = {
  id: 3,
  code: 'IT-EXPERIMENT-001',
  title: '信息科技项目式学习班级对照实验',
  description: '比较项目式学习与常规教学安排中的学生学习表现。',
  status: 'registered',
  status_label: '已登记',
  subject_id: 1,
  subject_name: '信息科技',
  course_id: 2,
  course_title: '数据与计算',
  current_protocol_id: 9,
  current_protocol: protocol,
  protocol_versions: [protocol],
  created_at: '2026-07-01T08:00:00+08:00',
  updated_at: '2026-07-02T09:00:00+08:00'
}

async function mountView() {
  mocks.getResearchOptions.mockResolvedValue({
    stages: [],
    design_types: [],
    gates: [{ value: 'ethics', label: '伦理审批' }, { value: 'data_quality', label: '数据质量' }],
    gate_decisions: [{ value: 'approved', label: '通过' }],
    arms: [],
    allocation_methods: [{ value: 'stratified_random', label: '分层随机分配' }],
    run_modes: [],
    subjects: [{ id: 1, name: '信息科技' }],
    courses: [{ id: 2, title: '数据与计算', subject_id: 1 }],
    classes: [{ id: 4, name: '高一1班', grade: '高一' }],
    required_gates: { E5: ['ethics', 'data_quality'] }
  })
  mocks.getResearchStudies.mockResolvedValue([study])
  mocks.getResearchStudy.mockResolvedValue(study)
  const wrapper = mount(ResearchGovernanceView, {
    attachTo: document.body,
    global: {
      stubs: {
        AppShell: { template: '<main><slot /></main>' },
        NoticeLine: { props: ['message'], template: '<p>{{ message }}</p>' }
      }
    }
  })
  await flushPromises()
  return wrapper
}

afterEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('学校管理员教育实验工作台', () => {
  it('以教育实验流程呈现共同测量、班级安排与开展条件', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('共同前测')
    expect(wrapper.text()).toContain('实验班与对照班')
    expect(wrapper.text()).toContain('学生权益审查')
    expect(wrapper.text()).toContain('1/2 项完成')

    const tabLabels = wrapper.findAll('.experiment-tabs button').map((item) => item.text())
    expect(tabLabels).toEqual(['1 实验方案', '2 班级安排', '3 实施记录', '4 分析准备'])
    await wrapper.get('.section-heading .primary-button').trigger('click')
    await nextTick()

    const dialog = wrapper.get('[aria-labelledby="condition-modal-title"]')
    expect(dialog.element.contains(document.activeElement)).toBe(true)
    expect(dialog.text()).toContain('保存核对结果')
  })
})
