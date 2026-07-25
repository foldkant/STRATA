import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import type { EvaluationOptions } from '@/api/evaluation'
import EvaluationStandardEditorModal from '../EvaluationStandardEditorModal.vue'

const saveEvaluationStandardMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/evaluation', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/evaluation')>(),
  saveEvaluationStandard: saveEvaluationStandardMock
}))

let wrapper: VueWrapper | null = null

const AppSelectStub = defineComponent({
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', Number($event.target.value))"><slot /></select>'
})

function options(): EvaluationOptions {
  return {
    courses: [{ id: 9, title: '数据与计算', subject: { id: 2, name: '信息科技', code: 'IT' }, school_stage: 'k1_k9', is_active: true }],
    scopes: [],
    review_statuses: [],
    dimensions: [],
    assessment_modes: [{ value: 'project', label: '项目式评价' }],
    evidence_ownerships: [{ value: 'individual', label: '个人评价材料' }],
    material_types: [{ value: 'artifact', label: '作品材料' }],
    thinking_requirements: [],
    plan_versions: [{
      id: 88,
      source_plan_id: 15,
      title: '数据表达评价方案',
      version_no: 3,
      content_hash: 'abcdef1234567890',
      review_status: 'reviewed',
      subject: { id: 2, name: '信息科技' },
      course: { id: 9, title: '数据与计算' },
      learning_goals: [{ code: 'G1', title: '解释数据', description: '解释数据所表达的信息', curriculum_node_ids: [37] }],
      evaluation_tasks: [{
        code: 'E1',
        title: '项目成果评价',
        goal_codes: ['G1'],
        activity_codes: ['A1'],
        mode: 'project',
        component_modes: [],
        evidence_ownership: 'individual',
        material_types: ['artifact'],
        weight: 100,
        description: '依据项目成果判断学生表现。'
      }]
    }],
    standard_versions: [],
    trial_types: [],
    trial_statuses: [],
    trial_conclusions: []
  }
}

function aiDraft() {
  return {
    id: 31,
    title: 'AI 数据表达评价标准',
    plan: { id: 15, title: '数据表达评价方案' },
    plan_version: options().plan_versions[0],
    subject: { id: 2, name: '信息科技' },
    course: { id: 9, title: '数据与计算' },
    scope: 'lesson',
    scope_label: '课时评价',
    evaluation_target: '学生项目作品与解释过程',
    criterion_count: 1,
    review_status: 'draft' as const,
    review_status_label: '草稿',
    reviewed_by: null,
    reviewed_at: null,
    allowed_actions: { edit: true, review: true, publish: false },
    latest_version: null,
    criteria: [{
      code: 'D1',
      dimension: 'subject_practice',
      title: '数据表达与解释',
      evaluation_target: '学生的数据作品和个人说明',
      evaluation_sources: ['学生作品'],
      learning_goal_codes: ['G1'],
      evaluation_task_codes: ['E1'],
      evidence_ownership: 'individual' as const,
      material_types: ['artifact'],
      expected_performance: '能够选择适当方式表达数据并说明理由。',
      skip_condition: '没有获得完成作品的机会时暂不评价。',
      support_options: [],
      common_problems: ['只呈现图表，没有说明选择理由。'],
      level_descriptions: { '1': '需要较多帮助', '2': '能够部分完成', '3': '能够基本完成', '4': '能够合理完成并解释', '5': '能够迁移运用并反思' },
      scoring_examples: [{ level: 3, title: '基本完成', example_description: '作品完整且有简要说明。', file_reference: '' }, { level: 5, title: '迁移运用', example_description: '能够比较方案并反思改进。', file_reference: '' }],
      follow_up_suggestion: '根据作品证据安排针对性反馈。'
    }],
    created_at: '2026-07-23T09:00:00+08:00',
    updated_at: '2026-07-23T09:00:00+08:00'
  }
}

beforeEach(() => {
  saveEvaluationStandardMock.mockReset()
  saveEvaluationStandardMock.mockResolvedValue({ id: 31 })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('EvaluationStandardEditorModal', () => {
  it('presents AI-generated criteria as reviewable drafts instead of an empty add form', async () => {
    wrapper = mount(EvaluationStandardEditorModal, {
      props: { draft: aiDraft(), options: options(), assistedByAi: true },
      global: {
        components: { AppSelect: AppSelectStub },
        stubs: { EvaluationCriterionModal: { props: ['aiDrafted'], template: '<div class="criterion-stub" :data-ai-drafted="aiDrafted" />' } }
      }
    })

    expect(wrapper.text()).toContain('AI 已起草 1 项评价指标')
    expect(wrapper.text()).toContain('数据表达与解释')
    expect(wrapper.text()).toContain('AI 初稿 · 待教师审阅')
    expect(wrapper.text()).toContain('手工补充指标')
    expect(wrapper.text()).not.toContain('尚未添加评价指标')

    await wrapper.findAll('button').find((button) => button.text() === '审阅')!.trigger('click')
    expect(wrapper.get('.criterion-stub').attributes('data-ai-drafted')).toBe('true')
  })

  it('binds the draft to the exact reviewed and published plan version', async () => {
    wrapper = mount(EvaluationStandardEditorModal, {
      props: { draft: null, options: options() },
      global: {
        components: { AppSelect: AppSelectStub },
        stubs: { EvaluationCriterionModal: true }
      }
    })

    expect(wrapper.text()).toContain('数据表达评价方案 · v3 · abcdef12')
    await wrapper.get('input[placeholder*="五星评价标准"]').setValue('数据表达评价标准')
    await wrapper.get('input[placeholder*="学生作品"]').setValue('学生项目作品与解释过程')
    await wrapper.findAll('button').find((button) => button.text() === '保存草案')!.trigger('click')
    await flushPromises()

    expect(saveEvaluationStandardMock).toHaveBeenCalledTimes(1)
    expect(saveEvaluationStandardMock.mock.calls[0][0]).toMatchObject({
      plan_version: 88,
      title: '数据表达评价标准'
    })
    expect(saveEvaluationStandardMock.mock.calls[0][0]).not.toHaveProperty('plan')
  })

  it('saves an incomplete standard draft before its overall target and criteria are finished', async () => {
    wrapper = mount(EvaluationStandardEditorModal, {
      props: { draft: null, options: options() },
      global: {
        components: { AppSelect: AppSelectStub },
        stubs: { EvaluationCriterionModal: true }
      }
    })

    await wrapper.get('input[placeholder*="五星评价标准"]').setValue('待完善评价标准')
    await wrapper.findAll('button').find((button) => button.text() === '保存草案')!.trigger('click')
    await flushPromises()

    expect(saveEvaluationStandardMock).toHaveBeenCalledTimes(1)
    expect(saveEvaluationStandardMock.mock.calls[0][0]).toMatchObject({
      plan_version: 88,
      title: '待完善评价标准',
      evaluation_target: '',
      criteria: []
    })
  })
})
