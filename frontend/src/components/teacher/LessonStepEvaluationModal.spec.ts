import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import type { EvaluationOptions, LessonStepEvaluationBindingContext } from '@/api/evaluation'
import LessonStepEvaluationModal from './LessonStepEvaluationModal.vue'

const apiMocks = vi.hoisted(() => ({
  deleteLessonStepEvaluationBinding: vi.fn(),
  getEvaluationOptions: vi.fn(),
  getEvaluationStandard: vi.fn(),
  getLessonStepEvaluationBinding: vi.fn(),
  publishEvaluationPlan: vi.fn(),
  publishEvaluationStandard: vi.fn(),
  reviewEvaluationPlan: vi.fn(),
  reviewEvaluationStandard: vi.fn(),
  saveLessonStepEvaluationBinding: vi.fn()
}))

vi.mock('@/api/evaluation', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/evaluation')>(),
  ...apiMocks
}))

vi.mock('@/components/evaluation/EvaluationAIDraftWizard.vue', () => ({
  default: {
    name: 'EvaluationAIDraftWizard',
    props: ['options', 'initialCourseId', 'initialGradeOrStage', 'initialUnitTitle', 'initialCourseContent'],
    emits: ['close', 'saved'],
    template: `
      <section
        class="ai-wizard-stub"
        :data-course="initialCourseId"
        :data-grade="initialGradeOrStage"
        :data-unit="initialUnitTitle"
        :data-content="initialCourseContent"
      ><button data-test="finish-ai-draft" @click="$emit('saved', { id: 101, title: 'AI课时评价方案', review_status: 'draft' }, { id: 102, title: 'AI课时评价标准', review_status: 'draft', criterion_count: 2 })">保存初稿</button></section>
    `
  }
}))

vi.mock('@/components/evaluation/EvaluationPlanEditorModal.vue', () => ({
  default: {
    name: 'EvaluationPlanEditorModal',
    props: ['draft', 'options', 'initialCourseId', 'contextLabel'],
    emits: ['close', 'saved'],
    template: '<section class="plan-editor-stub"><button data-test="save-manual-plan" @click="$emit(\'saved\', draft ? { ...draft, title: \'修改后的 AI 评价方案\' } : { id: 201, title: \'课时手工评价方案\', review_status: \'draft\' })">保存方案</button></section>'
  }
}))

vi.mock('@/components/evaluation/EvaluationStandardEditorModal.vue', () => ({
  default: {
    name: 'EvaluationStandardEditorModal',
    props: ['draft', 'options', 'initialPlanVersionId', 'contextLabel', 'assistedByAi'],
    emits: ['close', 'saved'],
    template: '<section class="standard-editor-stub" :data-plan-version="initialPlanVersionId" :data-draft-id="draft?.id" :data-assisted-by-ai="assistedByAi"><button data-test="save-manual-standard" @click="$emit(\'saved\', { id: 301, title: \'课时手工评价标准\', review_status: \'draft\' })">保存标准</button></section>'
  }
}))

const options = {
  courses: [{ id: 9, title: '数据与计算', subject: { id: 2, name: '信息科技', code: 'IT' }, school_stage: 'k1_k9', is_active: true }],
  scopes: [],
  review_statuses: [],
  dimensions: [],
  assessment_modes: [],
  evidence_ownerships: [],
  material_types: [],
  thinking_requirements: [],
  plan_versions: [],
  standard_versions: [],
  trial_types: [],
  trial_statuses: [],
  trial_conclusions: []
} satisfies EvaluationOptions

const context: LessonStepEvaluationBindingContext = {
  binding: null,
  standards: [{
    id: 88,
    title: '数据表达课堂评价',
    version_no: 2,
    review_status: 'reviewed',
    review_status_label: '已复核',
    criterion_count: 1,
    criteria: [{
      id: 901,
      code: 'D1',
      title: '数据表达与解释',
      dimension: 'problem_solving',
      dimension_label: '问题解决',
      evaluation_target: '学生的数据作品和个人说明',
      evaluation_sources: ['教师评价'],
      expected_performance: '能够选择适当方式表达数据并说明理由。',
      level_descriptions: ['材料不足', '能够完成', '基本合理', '合理并能解释', '能够迁移并反思'],
      skip_condition: '未获得操作机会',
      support_options: [],
      common_problems: [],
      follow_up_suggestion: '根据作品证据补充教学。'
    }]
  }],
  use_boundaries: [
    { code: 'classroom_feedback', label: '课堂反馈', status: 'available', status_label: '绑定后可用', description: '用于课堂反馈。' },
    { code: 'learning_state_update', label: '学习情况更新', status: 'requires_review', status_label: '需另行审查', description: '材料合格后才可作为候选依据。' },
    { code: 'research_and_model', label: '后续教学安排', status: 'not_direct', status_label: '需教师再确认', description: '不会直接决定学生后续学习内容、支持方式或分组。' }
  ]
}

let wrapper: VueWrapper | null = null

async function mountModal() {
  wrapper = mount(LessonStepEvaluationModal, {
    props: {
      open: true,
      lessonStepId: 41,
      lessonStepTitle: '制作数据图表',
      lessonTitle: '数据表达',
      courseId: 9,
      courseTitle: '数据与计算',
      gradeOrStage: '八年级',
      courseContent: '学生整理数据、制作图表并完成个人说明。',
      returnPath: '/teacher/lessons/7/design'
    },
    attachTo: document.body,
    global: {
      stubs: {
        Teleport: true,
        RouterLink: { props: ['to'], template: '<a><slot /></a>' }
      }
    }
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  Object.values(apiMocks).forEach((mock) => mock.mockReset())
  apiMocks.getLessonStepEvaluationBinding.mockResolvedValue(context)
  apiMocks.getEvaluationOptions.mockResolvedValue(options)
  apiMocks.reviewEvaluationPlan.mockResolvedValue({ id: 201, title: '课时手工评价方案', review_status: 'reviewed' })
  apiMocks.publishEvaluationPlan.mockResolvedValue({
    id: 201,
    title: '课时手工评价方案',
    review_status: 'reviewed',
    latest_version: { id: 701, version_no: 1 }
  })
  apiMocks.getEvaluationStandard.mockResolvedValue({ id: 102, title: 'AI课时评价标准', review_status: 'draft' })
  apiMocks.reviewEvaluationStandard.mockResolvedValue({ id: 301, title: '课时手工评价标准', review_status: 'reviewed' })
  apiMocks.publishEvaluationStandard.mockResolvedValue({
    id: 301,
    title: '课时手工评价标准',
    review_status: 'reviewed',
    latest_version: { id: 702, version_no: 1 }
  })
  apiMocks.saveLessonStepEvaluationBinding.mockResolvedValue({
    id: 51,
    lesson_step: 41,
    standard_version: 88,
    standard_title: '数据表达课堂评价',
    version_no: 2,
    enable_self: true,
    enable_peer: false,
    enable_teacher: true,
    locked: false,
    criteria: context.standards[0].criteria,
    created_at: '2026-07-22T10:00:00+08:00',
    updated_at: '2026-07-22T10:00:00+08:00'
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('LessonStepEvaluationModal', () => {
  it('turns an empty course into a clear creation choice without a disabled save action', async () => {
    apiMocks.getLessonStepEvaluationBinding.mockResolvedValueOnce({
      binding: null,
      standards: [],
      use_boundaries: context.use_boundaries
    })
    const view = await mountModal()

    expect(view.findAll('[data-test="lesson-manual-draft"]')).toHaveLength(1)
    expect(view.findAll('[data-test="lesson-ai-draft"]')).toHaveLength(1)
    expect(view.find('.step-evaluation-types').exists()).toBe(false)
    expect(view.text()).toContain('先为本环节建立评价方案')
    expect(view.get('[data-test="lesson-manual-draft"]').attributes('disabled')).toBeUndefined()
    expect(view.findAll('button').some((button) => button.text().includes('确认绑定到本环节'))).toBe(false)
  })

  it('shows the teaching workflow and separates classroom, learning-state and follow-up uses', async () => {
    const view = await mountModal()

    expect(view.text()).toContain('课时设计中的评价')
    expect(view.text()).toContain('课堂反馈')
    expect(view.text()).toContain('学习情况更新')
    expect(view.text()).toContain('后续教学安排')
    expect(view.text()).toContain('不会直接决定学生后续学习内容、支持方式或分组')
  })

  it('opens AI drafting inside the lesson context with prefilled teaching information', async () => {
    const view = await mountModal()

    await view.get('[data-test="lesson-ai-draft"]').trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(view.find('.ai-wizard-stub').exists()).toBe(true))

    const wizard = view.get('.ai-wizard-stub')
    expect(apiMocks.getEvaluationOptions).toHaveBeenCalledTimes(1)
    expect(wizard.attributes('data-course')).toBe('9')
    expect(wizard.attributes('data-grade')).toBe('八年级')
    expect(wizard.attributes('data-unit')).toContain('制作数据图表')
    expect(wizard.attributes('data-content')).toContain('个人说明')

    await wizard.get('[data-test="finish-ai-draft"]').trigger('click')
    await flushPromises()
    expect(view.text()).toContain('草稿不会自动进入课堂')
    expect(view.text()).toContain('完成方案复核，继续设置评价指标')

    await view.get('[data-test="authoring-continue"]').trigger('click')
    await flushPromises()
    expect(apiMocks.reviewEvaluationPlan).toHaveBeenCalledWith(101)
    expect(apiMocks.getEvaluationStandard).toHaveBeenCalledWith(102)
    expect(view.find('.standard-editor-stub').exists()).toBe(true)
    expect(view.get('.standard-editor-stub').attributes('data-draft-id')).toBe('102')
    expect(view.get('.standard-editor-stub').attributes('data-assisted-by-ai')).toBe('true')
  })

  it('keeps AI-generated criteria when the teacher edits and saves the evaluation plan', async () => {
    const view = await mountModal()

    await view.get('[data-test="lesson-ai-draft"]').trigger('click')
    await flushPromises()
    await view.get('[data-test="finish-ai-draft"]').trigger('click')
    await flushPromises()

    await view.findAll('button').find((button) => button.text() === '返回修改评价方案')!.trigger('click')
    await view.get('[data-test="save-manual-plan"]').trigger('click')
    await flushPromises()

    expect(view.text()).toContain('AI 起草的 2 项评价指标仍保留')
    await view.get('[data-test="authoring-continue"]').trigger('click')
    await flushPromises()

    expect(apiMocks.getEvaluationStandard).toHaveBeenCalledWith(102)
    expect(view.get('.standard-editor-stub').attributes('data-draft-id')).toBe('102')
    expect(view.get('.standard-editor-stub').attributes('data-assisted-by-ai')).toBe('true')
  })

  it('creates, reviews, publishes and binds a manual evaluation without leaving lesson design', async () => {
    const view = await mountModal()

    await view.get('[data-test="lesson-manual-draft"]').trigger('click')
    await flushPromises()
    await view.get('[data-test="save-manual-plan"]').trigger('click')
    await flushPromises()
    expect(view.text()).toContain('课时手工评价方案')

    await view.get('[data-test="authoring-continue"]').trigger('click')
    await flushPromises()
    expect(apiMocks.reviewEvaluationPlan).toHaveBeenCalledWith(201)
    expect(apiMocks.publishEvaluationPlan).toHaveBeenCalledWith(201)
    expect(view.get('.standard-editor-stub').attributes('data-plan-version')).toBe('701')

    await view.get('[data-test="save-manual-standard"]').trigger('click')
    await flushPromises()
    await view.get('[data-test="authoring-publish-bind"]').trigger('click')
    await flushPromises()

    expect(apiMocks.reviewEvaluationStandard).toHaveBeenCalledWith(301)
    expect(apiMocks.publishEvaluationStandard).toHaveBeenCalledWith(301)
    expect(apiMocks.saveLessonStepEvaluationBinding).toHaveBeenCalledWith(41, {
      standard_version: 702,
      enable_self: false,
      enable_peer: false,
      enable_teacher: true
    })
    expect(view.text()).toContain('可以在课堂中使用')
    expect(view.emitted('saved')?.[0]?.[0]).toMatchObject({ id: 51, lesson_step: 41 })
  })

  it('binds an exact reviewed version and keeps classroom evaluation methods explicit', async () => {
    const view = await mountModal()
    const selfAssessment = view.findAll('.step-evaluation-types input[type="checkbox"]')[0]
    await selfAssessment.setValue(true)
    await view.findAll('button').find((button) => button.text().includes('确认绑定到本环节'))!.trigger('click')
    await flushPromises()

    expect(apiMocks.saveLessonStepEvaluationBinding).toHaveBeenCalledWith(41, {
      standard_version: 88,
      enable_self: true,
      enable_peer: false,
      enable_teacher: true
    })
    expect(view.text()).toContain('绑定成功')
    expect(view.emitted('saved')?.[0]?.[0]).toMatchObject({ id: 51, lesson_step: 41 })
  })
})
