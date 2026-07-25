import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { ApiError } from '@/api/client'
import type { EvaluationOptions, EvaluationPlanRow, EvaluationReviewStatus } from '@/api/evaluation'
import EvaluationManagementView from '../EvaluationManagementView.vue'

const apiMocks = vi.hoisted(() => ({
  getEvaluationOptions: vi.fn(),
  getEvaluationPlans: vi.fn(),
  getEvaluationStandards: vi.fn(),
  getEvaluationTrials: vi.fn(),
  getEvaluationPlan: vi.fn(),
  getEvaluationStandard: vi.fn(),
  reviewEvaluationPlan: vi.fn(),
  reviewEvaluationStandard: vi.fn(),
  publishEvaluationPlan: vi.fn(),
  publishEvaluationStandard: vi.fn()
}))

vi.mock('@/api/evaluation', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/evaluation')>(),
  ...apiMocks
}))

let wrapper: VueWrapper | null = null

const AppShellStub = defineComponent({ template: '<main><slot /></main>' })
const NoticeLineStub = defineComponent({
  props: ['message', 'tone'],
  emits: ['dismiss'],
  template: '<p class="notice-stub" :data-tone="tone">{{ message }}</p>'
})
const ConfirmDialogStub = defineComponent({
  props: ['open', 'title', 'message', 'confirmLabel', 'loading'],
  emits: ['close', 'confirm'],
  template: '<section v-if="open" class="confirm-stub"><h2>{{ title }}</h2><p>{{ message }}</p><button :disabled="loading" @click="$emit(\'confirm\')">{{ confirmLabel }}</button></section>'
})
const EvaluationAIDraftWizardStub = defineComponent({
  emits: ['close', 'saved'],
  template: '<section class="ai-draft-stub"><button @click="$emit(\'close\')">关闭 AI 起草</button></section>'
})

function planRow(overrides: Partial<EvaluationPlanRow> = {}): EvaluationPlanRow {
  return {
    id: 15,
    title: '数据表达评价方案',
    subject: { id: 2, name: '信息科技' },
    course: { id: 9, title: '数据与计算' },
    scope: 'course',
    scope_label: '课程使用',
    content_version: '1.0',
    goal_count: 1,
    basis_count: 1,
    task_count: 1,
    activity_count: 1,
    evaluation_task_count: 1,
    review_status: 'draft',
    review_status_label: '编辑中',
    reviewed_by: null,
    reviewed_at: null,
    allowed_actions: { edit: true, review: true, publish: false },
    latest_version: null,
    curriculum_reference_count: 4,
    created_at: '2026-07-22T08:00:00+08:00',
    updated_at: '2026-07-22T08:00:00+08:00',
    ...overrides
  }
}

function options(planStatus: EvaluationReviewStatus = 'reviewed'): EvaluationOptions {
  return {
    courses: [{ id: 9, title: '数据与计算', subject: { id: 2, name: '信息科技', code: 'IT' }, school_stage: 'k1_k9', is_active: true }],
    scopes: [],
    review_statuses: [],
    dimensions: [],
    assessment_modes: [],
    evidence_ownerships: [],
    material_types: [],
    thinking_requirements: [],
    plan_versions: [{
      id: 88,
      source_plan_id: 15,
      title: '数据表达评价方案',
      version_no: 3,
      content_hash: 'abcdef1234567890',
      review_status: planStatus,
      subject: { id: 2, name: '信息科技' },
      course: { id: 9, title: '数据与计算' },
      learning_goals: [],
      evaluation_tasks: []
    }],
    standard_versions: [],
    trial_types: [],
    trial_statuses: [],
    trial_conclusions: []
  }
}

async function mountView(optionRows: EvaluationOptions = options()) {
  apiMocks.getEvaluationOptions.mockResolvedValue(optionRows)
  apiMocks.getEvaluationPlans.mockResolvedValue([planRow()])
  apiMocks.getEvaluationStandards.mockResolvedValue([])
  apiMocks.getEvaluationTrials.mockResolvedValue([])
  wrapper = mount(EvaluationManagementView, {
    attachTo: document.body,
    global: {
      stubs: {
        AppShell: AppShellStub,
        NoticeLine: NoticeLineStub,
        ConfirmDialog: ConfirmDialogStub,
        EvaluationAIDraftWizard: EvaluationAIDraftWizardStub,
        EvaluationPlanEditorModal: true,
        EvaluationStandardEditorModal: true,
        EvaluationTrialEditorModal: true,
        RouterLink: defineComponent({ template: '<a><slot /></a>' })
      }
    }
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  Object.values(apiMocks).forEach((mock) => mock.mockReset())
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('EvaluationManagementView P2 actions', () => {
  it('keeps AI assistance visible as a secondary entry and opens the draft wizard', async () => {
    const view = await mountView()
    const aiButton = view.get('[data-test="open-ai-draft"]')

    expect(aiButton.classes()).toContain('secondary-button')
    await aiButton.trigger('click')
    expect(view.find('.ai-draft-stub').exists()).toBe(true)
  })

  it('uses server allowed_actions and prevents duplicate review confirmation requests', async () => {
    const reviewed = planRow({ review_status: 'reviewed', review_status_label: '已复核' })
    let resolveReview: ((row: EvaluationPlanRow) => void) | undefined
    apiMocks.reviewEvaluationPlan.mockReturnValue(new Promise((resolve) => { resolveReview = resolve }))
    const view = await mountView()

    const planRowElement = view.find('tbody tr')
    expect(planRowElement.findAll('button').find((button) => button.text() === '复核确认')).toBeDefined()
    expect(planRowElement.findAll('button').find((button) => button.text() === '发布版本')!.attributes('disabled')).toBeDefined()

    await planRowElement.findAll('button').find((button) => button.text() === '复核确认')!.trigger('click')
    const confirm = view.findAll('.confirm-stub').find((dialog) => dialog.text().includes('复核确认'))!
    const confirmButton = confirm.get('button')
    await confirmButton.trigger('click')
    await confirmButton.trigger('click')
    expect(apiMocks.reviewEvaluationPlan).toHaveBeenCalledTimes(1)

    resolveReview?.(reviewed)
    await flushPromises()
  })

  it.each(['legacy_unverified', 'draft'] as const)('disables creating a standard when only %s plan versions are available', async (status) => {
    const view = await mountView(options(status))
    await view.findAll('[role="tab"]').find((button) => button.text().includes('评价指标与表现水平'))!.trigger('click')
    const createButton = view.findAll('button').find((button) => button.text() === '新建标准')!
    expect(createButton.attributes('disabled')).toBeDefined()
  })

  it('shows the review field and recovery message returned by the server', async () => {
    apiMocks.reviewEvaluationPlan.mockRejectedValue(new ApiError(
      '评价方案复核未通过。',
      400,
      { evaluation_tasks: ['每个学习活动都必须有对应评价任务。'] }
    ))
    const view = await mountView()
    const reviewButton = view.find('tbody tr').findAll('button').find((button) => button.text() === '复核确认')!
    await reviewButton.trigger('click')
    const confirm = view.findAll('.confirm-stub').find((dialog) => dialog.text().includes('复核确认'))!
    await confirm.get('button').trigger('click')
    await flushPromises()

    expect(view.get('.notice-stub').text()).toBe('评价任务：每个学习活动都必须有对应评价任务。')
  })
})
