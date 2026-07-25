import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import type { EvaluationOptions, EvaluationPlanRow, EvaluationTask } from '@/api/evaluation'
import EvaluationPlanEditorModal from '../EvaluationPlanEditorModal.vue'

const saveEvaluationPlanMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/evaluation', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/evaluation')>(),
  saveEvaluationPlan: saveEvaluationPlanMock
}))

let wrapper: VueWrapper | null = null

const AppSelectStub = defineComponent({
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue', 'change'],
  template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event)"><slot /></select>'
})

const TraceModalStub = defineComponent({
  name: 'CurriculumReferenceTraceModal',
  props: { nodeId: Number },
  emits: ['close'],
  template: '<div data-test="reference-trace">{{ nodeId }}</div>'
})

function options(): EvaluationOptions {
  return {
    courses: [{
      id: 9,
      title: '数据与计算',
      subject: { id: 2, name: '信息科技', code: 'IT' },
      school_stage: 'k1_k9',
      is_active: true
    }, {
      id: 10,
      title: '算法与程序设计',
      subject: { id: 2, name: '信息科技', code: 'IT' },
      school_stage: 'k10_k12',
      is_active: true
    }],
    scopes: [],
    review_statuses: [],
    dimensions: [],
    assessment_modes: [
      { value: 'test', label: '测试式评价' },
      { value: 'operation', label: '操作式评价' },
      { value: 'project', label: '项目式评价' },
      { value: 'artifact', label: '作品评价' },
      { value: 'oral_defense', label: '答辩评价' },
      { value: 'mixed', label: '混合评价' }
    ],
    evidence_ownerships: [
      { value: 'individual', label: '个人评价材料' },
      { value: 'group', label: '小组评价材料' },
      { value: 'both', label: '个人与小组评价材料' }
    ],
    material_types: [{ value: 'artifact', label: '作品材料' }],
    thinking_requirements: [{ value: 'apply', label: '应用' }],
    plan_versions: [],
    standard_versions: [],
    trial_types: [],
    trial_statuses: [],
    trial_conclusions: []
  }
}

function evaluationTask(overrides: Partial<EvaluationTask> = {}): EvaluationTask {
  return {
    code: 'E1',
    title: '项目成果评价',
    goal_codes: ['G1'],
    activity_codes: ['A1'],
    mode: 'project',
    component_modes: [],
    evidence_ownership: 'individual',
    material_types: ['artifact'],
    weight: 100,
    description: '根据项目成果判断学习目标达成情况。',
    ...overrides
  }
}

function draft(overrides: Partial<EvaluationPlanRow> = {}): EvaluationPlanRow {
  return {
    id: 15,
    title: '数据表达评价方案',
    subject: { id: 2, name: '信息科技' },
    course: { id: 9, title: '数据与计算' },
    scope: 'course',
    scope_label: '课程',
    content_version: '1.0',
    goal_count: 0,
    basis_count: 0,
    task_count: 0,
    activity_count: 0,
    evaluation_task_count: 0,
    review_status: 'draft',
    review_status_label: '编辑中',
    reviewed_by: null,
    reviewed_at: null,
    allowed_actions: { edit: true, review: true, publish: false },
    latest_version: null,
    target_students: '',
    learning_goal: '',
    learning_goals: [],
    evaluation_basis: [],
    learning_activities: [],
    learning_tasks: [],
    evaluation_tasks: [],
    assessment_modes: [],
    content_scope: [],
    thinking_requirements: [],
    support_options: [],
    scoring_rules: { approach: '', decision_rule: '' },
    follow_up_suggestion: '',
    curriculum_node_ids: [37],
    curriculum_references: [{
      id: 37,
      node_type: 'course_objective',
      code: 'IT-K9-02',
      title: '课程目标条目',
      content: '课程标准原文',
      parent: null,
      source_page_start: 18,
      source_page_end: 18,
      sort_order: 1,
      standard_title: '义务教育信息科技课程标准（2022年版）',
      version_label: '2022年版'
    }],
    created_at: '2026-07-22T08:00:00+08:00',
    updated_at: '2026-07-22T08:00:00+08:00',
    ...overrides
  }
}

function mountEditor(row: EvaluationPlanRow | null, initial: Record<string, unknown> = {}) {
  wrapper = mount(EvaluationPlanEditorModal, {
    props: { draft: row, options: options(), ...initial },
    global: {
      components: { AppSelect: AppSelectStub },
      stubs: {
        CurriculumReferencePickerModal: true,
        CurriculumReferenceTraceModal: TraceModalStub
      }
    }
  })
  return wrapper
}

beforeEach(() => {
  saveEvaluationPlanMock.mockReset()
  saveEvaluationPlanMock.mockResolvedValue(draft())
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('EvaluationPlanEditorModal', () => {
  it('prefills and locks the course context supplied by lesson design', () => {
    const view = mountEditor(null, {
      initialCourseId: 10,
      initialTitle: '算法课时评价方案',
      initialTargetStudents: '高一年级',
      initialContentScope: ['算法设计与验证'],
      contextLabel: '算法设计 · 验证算法',
      lockCourse: true
    })

    expect((view.get('select').element as HTMLSelectElement).value).toBe('10')
    expect(view.get('select').attributes('disabled')).toBeDefined()
    expect((view.get('input[placeholder*="数据表达与解释"]').element as HTMLInputElement).value).toBe('算法课时评价方案')
    expect(view.text()).toContain('当前课时：算法设计 · 验证算法')
  })

  it('opens the original-text trace from a selected curriculum reference', async () => {
    const view = mountEditor(draft())
    const traceButton = view.findAll('button').find((button) => button.text() === '查看原文')
    expect(traceButton).toBeDefined()
    await traceButton!.trigger('click')
    expect(view.get('[data-test="reference-trace"]').text()).toBe('37')
  })

  it('saves an incomplete draft when the required course and title are present', async () => {
    const view = mountEditor(null)
    await view.get('input[placeholder*="数据表达与解释"]')!.setValue('未完成方案草案')
    const saveButton = view.findAll('button').find((button) => button.text() === '保存草案')
    await saveButton!.trigger('click')
    await flushPromises()

    expect(saveEvaluationPlanMock).toHaveBeenCalledTimes(1)
    const payload = saveEvaluationPlanMock.mock.calls[0][0]
    expect(payload.title).toBe('未完成方案草案')
    expect(payload.curriculum_node_ids).toEqual([])
    expect(payload.learning_goals).toEqual([])
  })

  it('derives plan assessment modes only from evaluation task modes', async () => {
    const view = mountEditor(draft({
      evaluation_tasks: [
        evaluationTask({ code: 'E1', mode: 'project', weight: 50 }),
        evaluationTask({
          code: 'E2',
          mode: 'mixed',
          component_modes: ['operation', 'oral_defense'],
          weight: 50
        })
      ],
      assessment_modes: ['test']
    }))
    await view.findAll('button').find((button) => button.text().includes('材料与评分安排'))!.trigger('click')
    expect(view.text()).toContain('项目式评价、混合评价')
    expect(view.text()).toContain('由各评价任务的方式自动汇总')

    await view.findAll('button').find((button) => button.text() === '保存草案')!.trigger('click')
    await flushPromises()
    const payload = saveEvaluationPlanMock.mock.calls[0][0]
    expect(payload.assessment_modes).toEqual(['project', 'mixed'])
    expect(payload.evaluation_tasks[1].component_modes).toEqual(['operation', 'oral_defense'])
  })

  it('uses stable generated codes and removes downstream references with deleted nodes', async () => {
    const view = mountEditor(draft({
      learning_goals: [
        { code: 'G1', title: '目标一', description: '目标一的具体表现说明', curriculum_node_ids: [37] },
        { code: 'G3', title: '目标三', description: '目标三的具体表现说明', curriculum_node_ids: [37] }
      ],
      evaluation_basis: [{ code: 'B1', goal_codes: ['G1', 'G3'], description: '依据说明', source_types: ['作品'] }],
      learning_activities: [
        { code: 'A1', title: '活动一', goal_codes: ['G1'], description: '活动一的学习过程说明' },
        { code: 'A3', title: '活动三', goal_codes: ['G3'], description: '活动三的学习过程说明' }
      ],
      evaluation_tasks: [evaluationTask({ goal_codes: ['G1'], activity_codes: ['A1'] })]
    }))
    await view.findAll('button').find((button) => button.text().includes('活动与评价任务'))!.trigger('click')
    await view.get('button[aria-label="删除学习目标 1"]').trigger('click')
    await view.get('button[aria-label="删除学习活动 1"]').trigger('click')
    await view.findAll('button').find((button) => button.text() === '新增目标')!.trigger('click')
    await view.findAll('button').find((button) => button.text() === '新增活动')!.trigger('click')
    await view.findAll('button').find((button) => button.text() === '保存草案')!.trigger('click')
    await flushPromises()

    const payload = saveEvaluationPlanMock.mock.calls[0][0]
    expect(payload.learning_goals.map((item: { code: string }) => item.code)).toEqual(['G3', 'G4'])
    expect(payload.learning_activities.map((item: { code: string }) => item.code)).toEqual(['A3', 'A4'])
    expect(payload.evaluation_basis[0].goal_codes).toEqual(['G3'])
    expect(payload.evaluation_tasks[0].goal_codes).toEqual([])
    expect(payload.evaluation_tasks[0].activity_codes).toEqual([])
  })

  it('clears every curriculum reference when an unpublished draft changes course', async () => {
    const view = mountEditor(draft({
      learning_goals: [{
        code: 'G1',
        title: '解释数据',
        description: '解释数据所表达的实际信息',
        curriculum_node_ids: [37]
      }]
    }))
    await view.get('select').setValue('10')
    await view.findAll('button').find((button) => button.text() === '保存草案')!.trigger('click')
    await flushPromises()

    const payload = saveEvaluationPlanMock.mock.calls[0][0]
    expect(payload.course).toBe('10')
    expect(payload.curriculum_node_ids).toEqual([])
    expect(payload.learning_goals[0].curriculum_node_ids).toEqual([])
  })
})
