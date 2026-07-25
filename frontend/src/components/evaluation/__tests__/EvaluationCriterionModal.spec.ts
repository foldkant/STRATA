import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import type { EvaluationOptions, EvaluationPlanVersionOption } from '@/api/evaluation'
import EvaluationCriterionModal from '../EvaluationCriterionModal.vue'

let wrapper: VueWrapper | null = null

const AppSelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>'
})

function options(): EvaluationOptions {
  return {
    courses: [],
    scopes: [],
    review_statuses: [],
    dimensions: [{ value: 'subject_practice', label: '学科实践' }],
    assessment_modes: [],
    evidence_ownerships: [
      { value: 'individual', label: '个人评价材料' },
      { value: 'group', label: '小组评价材料' },
      { value: 'both', label: '个人与小组评价材料' }
    ],
    material_types: [
      { value: 'answer', label: '作答记录' },
      { value: 'artifact', label: '作品材料' },
      { value: 'operation', label: '操作记录' }
    ],
    thinking_requirements: [],
    plan_versions: [],
    standard_versions: [],
    trial_types: [],
    trial_statuses: [],
    trial_conclusions: []
  }
}

function planVersion(): EvaluationPlanVersionOption {
  return {
    id: 88,
    source_plan_id: 15,
    title: '数据表达评价方案',
    version_no: 3,
    content_hash: 'abcdef1234567890',
    review_status: 'reviewed',
    subject: { id: 2, name: '信息科技' },
    course: { id: 9, title: '数据与计算' },
    learning_goals: [{ code: 'G1', title: '解释数据', description: '解释数据所表达的信息', curriculum_node_ids: [37] }],
    evaluation_tasks: [
      {
        code: 'E1',
        title: '小组项目成果',
        goal_codes: ['G1'],
        activity_codes: ['A1'],
        mode: 'project',
        component_modes: [],
        evidence_ownership: 'both',
        material_types: ['answer', 'artifact'],
        weight: 50,
        description: '分别收集个人解释与小组作品。'
      },
      {
        code: 'E2',
        title: '个人答辩',
        goal_codes: ['G1'],
        activity_codes: ['A1'],
        mode: 'oral_defense',
        component_modes: [],
        evidence_ownership: 'individual',
        material_types: ['answer', 'operation'],
        weight: 50,
        description: '记录每名学生的个人答辩表现。'
      }
    ]
  }
}

function mountEditor() {
  wrapper = mount(EvaluationCriterionModal, {
    props: {
      criterion: null,
      options: options(),
      planVersion: planVersion(),
      suggestedCode: 'D4'
    },
    global: { components: { AppSelect: AppSelectStub } }
  })
  return wrapper
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('EvaluationCriterionModal', () => {
  it('labels an empty indicator as a manual supplement, not an AI result', () => {
    const view = mountEditor()
    expect(view.text()).toContain('手工补充评价指标')
    expect(view.text()).toContain('这是一项手工补充指标')
  })

  it('limits ownership while allowing compatible materials to cover each selected task', async () => {
    const view = mountEditor()
    const taskField = view.findAll('fieldset').find((field) => field.text().includes('对应评价任务'))!
    const taskChecks = taskField.findAll('input[type="checkbox"]')
    await taskChecks[0].setValue(true)
    await taskChecks[1].setValue(true)

    const ownershipField = view.findAll('label').find((label) => label.text().includes('评价材料归属'))!
    expect(ownershipField.findAll('option').map((option) => option.text())).toEqual(['个人评价材料'])
    const materialField = view.findAll('fieldset').find((field) => field.text().includes('评价材料类型'))!
    expect(materialField.findAll('label').map((label) => label.text())).toEqual([
      '作答记录',
      '作品材料',
      '操作记录'
    ])
    expect(materialField.text()).toContain('所选材料需覆盖每个关联任务')
  })

  it('explains that personal and group materials remain separate when both is selected', async () => {
    const view = mountEditor()
    const taskField = view.findAll('fieldset').find((field) => field.text().includes('对应评价任务'))!
    await taskField.find('input[type="checkbox"]').setValue(true)
    const ownershipField = view.findAll('label').find((label) => label.text().includes('评价材料归属'))!
    await ownershipField.get('select').setValue('both')

    expect(view.text()).toContain('个人评价材料与小组评价材料分别记录，小组材料不替代个人材料')
    expect(view.text()).not.toContain('指标代码')
  })
})
