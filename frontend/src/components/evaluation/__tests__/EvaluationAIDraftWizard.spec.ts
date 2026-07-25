import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  EvaluationAIDraftRow,
  EvaluationAIStandardDraft,
  EvaluationOptions,
  EvaluationPlanPayload,
  EvaluationPlanRow,
  EvaluationStandardRow
} from '@/api/evaluation'
import EvaluationAIDraftWizard from '../EvaluationAIDraftWizard.vue'

const apiMocks = vi.hoisted(() => ({
  cancelEvaluationAIDraft: vi.fn(),
  confirmEvaluationAIDraftModes: vi.fn(),
  createEvaluationAIDraft: vi.fn(),
  generateEvaluationAIDraft: vi.fn(),
  getEvaluationAIDraft: vi.fn(),
  getEvaluationAIDrafts: vi.fn(),
  retrieveEvaluationAIDraftReferences: vi.fn(),
  saveEvaluationAIPlanDraft: vi.fn(),
  suggestEvaluationAIDraftModes: vi.fn()
}))

vi.mock('@/api/evaluation', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/evaluation')>(),
  ...apiMocks
}))

const AppSelectStub = defineComponent({
  name: 'AppSelect',
  inheritAttrs: false,
  props: { modelValue: [String, Number] },
  emits: ['update:modelValue', 'change'],
  template: `
    <select
      v-bind="$attrs"
      :value="modelValue"
      @change="$emit('update:modelValue', $event.target.value); $emit('change', $event)"
    ><slot /></select>
  `
})

const optionRows: EvaluationOptions = {
  courses: [{
    id: 9,
    title: '数据与计算',
    subject: { id: 2, name: '信息科技', code: 'IT' },
    school_stage: 'k1_k9',
    is_active: true
  }],
  scopes: [],
  review_statuses: [],
  dimensions: [{ value: 'problem_solving', label: '问题解决' }],
  assessment_modes: [],
  evidence_ownerships: [],
  material_types: [
    { value: 'source_file', label: '源文件' },
    { value: 'reflection', label: '学习反思' }
  ],
  thinking_requirements: [],
  plan_versions: [],
  standard_versions: [],
  trial_types: [],
  trial_statuses: [],
  trial_conclusions: []
}

const context = {
  course_id: 9,
  school_stage: 'k1_k9' as const,
  grade_or_stage: '八年级',
  unit_title: '数据编码与表示',
  curriculum_standard_version_id: 5,
  course_content: '学生通过操作、项目作品和说明理解数据编码与表示。',
  evaluation_purpose: 'formative' as const
}

const references = (['core_competency', 'course_objective', 'course_content', 'academic_quality'] as const).map((nodeType, index) => ({
  id: index + 1,
  node_type: nodeType,
  node_type_label: ['核心素养', '课程目标', '课程内容', '学业质量'][index],
  code: `IT-${index + 1}`,
  title: ['信息意识', '课程目标一', '数据编码', '学业质量二级'][index],
  content: `可追溯课程标准原文 ${index + 1}`,
  parent: null,
  source_page_start: 10 + index,
  source_page_end: 10 + index,
  sort_order: index,
  standard_title: '义务教育信息科技课程标准',
  version_label: '2022年版'
}))

const planDraft: EvaluationPlanPayload = {
  course: 9,
  title: '数据编码与表示评价方案',
  content_version: 'AI-DRAFT-1',
  target_students: '八年级学生',
  learning_goal: '能解释并运用数据编码方法解决问题。',
  learning_goals: [{ code: 'G1', title: '理解数据编码', description: '解释编码规则并作出选择。', curriculum_node_ids: [1, 2, 3, 4] }],
  evaluation_basis: [{ code: 'B1', goal_codes: ['G1'], description: '依据作品与操作记录判断。', source_types: ['source_file'] }],
  learning_activities: [{ code: 'A1', title: '编码方案设计', goal_codes: ['G1'], description: '小组设计、个人说明。' }],
  learning_tasks: [{ code: 'L1', title: '完成编码作品', basis_codes: ['B1'], description: '完成并解释编码方案。' }],
  evaluation_tasks: [{
    code: 'T1',
    title: '编码作品与个人说明',
    goal_codes: ['G1'],
    activity_codes: ['A1'],
    mode: 'project',
    component_modes: ['project', 'oral_defense'],
    evidence_ownership: 'both',
    material_types: ['source_file', 'reflection'],
    weight: 100,
    description: '提交小组作品并完成个人说明。'
  }],
  assessment_modes: ['project'],
  content_scope: ['数据编码'],
  thinking_requirements: ['解释', '设计'],
  support_options: ['提供操作提示'],
  scoring_rules: { approach: '表现水平描述', decision_rule: '综合作品、过程与个人说明判断。' },
  follow_up_suggestion: '根据证据安排有针对性的后续学习。',
  curriculum_node_ids: [1, 2, 3, 4]
}

const standardDraft: EvaluationAIStandardDraft = {
  title: '数据编码与表示评价标准',
  evaluation_target: '学生的数据编码作品、操作过程与个人说明',
  criteria: [{
    code: 'C1',
    dimension: 'problem_solving',
    title: '编码方案的合理性',
    evaluation_target: '编码作品与个人说明',
    evaluation_sources: ['source_file', 'reflection'],
    learning_goal_codes: ['G1'],
    evaluation_task_codes: ['T1'],
    evidence_ownership: 'both',
    material_types: ['source_file', 'reflection'],
    expected_performance: '能够依据任务需求选择并解释编码方案。',
    skip_condition: '未获得操作机会、设备故障或材料缺失时暂不评价。',
    support_options: ['提供操作提示'],
    common_problems: ['只展示小组成果，缺少个人说明'],
    level_descriptions: {
      '1': '尚不能形成可辨认的编码方案或说明。',
      '4': '能独立选择合理方案并清楚解释依据。',
      '2': '能在提示下完成方案，解释尚不完整。',
      '3': '能完成可用方案，并说明主要编码依据。',
      '5': '能优化、验证方案并迁移解释到新情境。'
    },
    scoring_examples: [
      { level: 4, title: '充分达成示例', example_description: '方案合理，验证充分，个人说明清楚。', file_reference: '样例作品 A' },
      { level: 2, title: '发展中示例', example_description: '方案基本可用，但验证与个人说明不完整。', file_reference: '样例作品 B' }
    ],
    follow_up_suggestion: '补充比较不同编码方案的学习活动。'
  }]
}

function session(overrides: Partial<EvaluationAIDraftRow> = {}): EvaluationAIDraftRow {
  return {
    id: 31,
    status: 'context_ready',
    status_label: '已记录教学情境',
    context,
    curriculum_standard_version: {
      id: 5,
      title: '义务教育信息科技课程标准',
      version_label: '2022年版',
      school_stage: 'k1_k9',
      // Deliberately differs from the course Subject id: compatibility must use course ids.
      subject: { id: 99, name: '信息科技', code: 'information_technology' },
      compatible_course_ids: [9],
      content_hash: '1234567890abcdef'
    },
    curriculum_references: [],
    mode_suggestions: [],
    confirmed_modes: [],
    teacher_mode_note: '',
    plan_draft: null,
    standard_draft: null,
    checks: [],
    background_task: null,
    created_at: '2026-07-22T08:00:00+08:00',
    updated_at: '2026-07-22T08:00:00+08:00',
    ...overrides
  }
}

const referenceSession = () => session({
  status: 'references_ready',
  status_label: '课标依据已检索',
  curriculum_references: references
})

const suggestionSession = () => session({
  ...referenceSession(),
  status: 'modes_suggested',
  status_label: '评价方式建议已形成',
  mode_suggestions: [
    { mode: 'project', label: '项目评价', rationale: '课程要求形成作品并说明方案。', suitable_materials: ['作品', '个人说明'], cautions: ['需区分个人与小组材料'], recommended: true },
    { mode: 'test', label: '测试评价', rationale: '可补充检查概念理解。', suitable_materials: ['作答记录'], cautions: [], recommended: false }
  ]
})

const confirmedSession = () => session({
  ...suggestionSession(),
  status: 'modes_confirmed',
  status_label: '教师已确认评价方式',
  confirmed_modes: ['project'],
  teacher_mode_note: '以项目评价为主。'
})

const generatedSession = () => session({
  ...confirmedSession(),
  status: 'draft_generated',
  status_label: '完整初稿已形成',
  plan_draft: planDraft,
  standard_draft: standardDraft,
  checks: [{ code: 'server_trace', label: '服务端追溯检查', status: 'passed', message: '课标依据可追溯。' }]
})

const savedPlan = { id: 73, title: planDraft.title, review_status: 'draft' } as EvaluationPlanRow
const savedStandard = { id: 74, title: standardDraft.title, review_status: 'draft' } as EvaluationStandardRow
let wrapper: VueWrapper | null = null

async function mountWizard(
  recent: EvaluationAIDraftRow[] = [],
  initial: Partial<{
    initialCourseId: number | null
    initialGradeOrStage: string
    initialUnitTitle: string
    initialCourseContent: string
    initialContentSourceLabel: string
  }> = {}
) {
  apiMocks.getEvaluationAIDrafts.mockResolvedValue({
    results: recent,
    curriculum_standard_versions: [session().curriculum_standard_version],
    evaluation_purposes: []
  })
  wrapper = mount(EvaluationAIDraftWizard, {
    props: { options: optionRows, ...initial },
    attachTo: document.body,
    global: {
      components: { AppSelect: AppSelectStub },
      stubs: { Teleport: true }
    }
  })
  await flushPromises()
  return wrapper
}

async function enterContext(view: VueWrapper) {
  await view.get('[data-test="ai-grade"]').setValue('八年级')
  await view.get('[data-test="ai-unit"]').setValue('数据编码与表示')
  await view.get('[data-test="ai-standard"]').setValue('5')
  await view.get('[data-test="ai-content"]').setValue('学生通过操作、项目作品和个人说明理解数据编码与表示。')
}

async function reachReview(view: VueWrapper) {
  await enterContext(view)
  await view.get('[data-test="context-next"]').trigger('click')
  await flushPromises()
  await view.get('[data-test="references-next"]').trigger('click')
  await flushPromises()
  await view.get('[data-test="suggestions-next"]').trigger('click')
  await view.get('[data-test="confirm-modes"]').trigger('click')
  await flushPromises()
  await view.get('[data-test="generate-draft"]').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  Object.values(apiMocks).forEach((mock) => mock.mockReset())
  apiMocks.createEvaluationAIDraft.mockResolvedValue(session())
  apiMocks.retrieveEvaluationAIDraftReferences.mockResolvedValue(referenceSession())
  apiMocks.suggestEvaluationAIDraftModes.mockResolvedValue(suggestionSession())
  apiMocks.confirmEvaluationAIDraftModes.mockResolvedValue(confirmedSession())
  apiMocks.generateEvaluationAIDraft.mockResolvedValue(generatedSession())
  apiMocks.saveEvaluationAIPlanDraft.mockResolvedValue({
    ai_draft: session({ status: 'saved' }),
    plan: savedPlan,
    standard: savedStandard,
    drafts_saved: { plan: true, standard: true }
  })
})

afterEach(() => {
  vi.useRealTimers()
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('EvaluationAIDraftWizard', () => {
  it('exposes an accessible dialog title, busy state and labelled context controls', async () => {
    const view = await mountWizard()
    const dialog = view.get('[role="dialog"]')

    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.attributes('aria-labelledby')).toBe('ai-draft-title')
    expect(view.get('#ai-draft-title').text()).toContain('AI 辅助起草评价方案与评价标准')
    expect(dialog.attributes('aria-busy')).toBe('false')
    expect(view.get('[data-test="ai-course"]').element.closest('label')).not.toBeNull()
    expect(view.get('[data-test="ai-standard"]').element.closest('label')).not.toBeNull()
    expect(view.get('button[aria-label="暂时关闭 AI 辅助起草"]')).toBeTruthy()
  })

  it('prefills the teaching context when opened from lesson design', async () => {
    const view = await mountWizard([], {
      initialCourseId: 9,
      initialGradeOrStage: '八年级',
      initialUnitTitle: '数据与计算 · 数据表达活动',
      initialCourseContent: '学生整理数据、制作可视化作品并完成个人说明。',
      initialContentSourceLabel: '当前课时与本环节'
    })

    expect((view.get('[data-test="ai-course"]').element as HTMLSelectElement).value).toBe('9')
    expect((view.get('[data-test="ai-grade"]').element as HTMLInputElement).value).toBe('八年级')
    expect((view.get('[data-test="ai-unit"]').element as HTMLInputElement).value).toContain('数据表达活动')
    expect((view.get('[data-test="ai-content"]').element as HTMLTextAreaElement).value).toContain('个人说明')
    expect(view.text()).toContain('已从当前课时与本环节自动带入')

    await view.get('[data-test="ai-content"]').setValue('教师补充后的内容。')
    await view.get('[data-test="restore-lesson-content"]').trigger('click')
    expect((view.get('[data-test="ai-content"]').element as HTMLTextAreaElement).value).toContain('制作可视化作品')
  })

  it('gates the workflow by context and states the non-automation boundary', async () => {
    const view = await mountWizard()

    expect(view.text()).toContain('AI 不能发布评价方案')
    expect(view.text()).toContain('不能直接决定评分、学习内容与支持安排或学生分组')
    expect(view.get('[data-test="context-next"]').attributes('disabled')).toBeDefined()
    expect(view.get('[data-test="context-next"]').text()).toMatch(/^请先/)
    expect(view.find('[data-test="generate-draft"]').exists()).toBe(false)

    await enterContext(view)
    expect(view.get('[data-test="context-next"]').attributes('disabled')).toBeUndefined()
    expect(view.get('[data-test="context-next"]').text()).toBe('检索课标依据')
  })

  it('requires the teacher to confirm evaluation modes before generation', async () => {
    const view = await mountWizard()
    await enterContext(view)
    await view.get('[data-test="context-next"]').trigger('click')
    await flushPromises()
    expect(apiMocks.createEvaluationAIDraft).toHaveBeenCalledWith(
      expect.any(Object),
      expect.stringMatching(/^.+$/)
    )
    await view.get('[data-test="references-next"]').trigger('click')
    await flushPromises()
    await view.get('[data-test="suggestions-next"]').trigger('click')

    const testMode = view.findAll('input[type="checkbox"]').find((input) => input.attributes('value') === 'test')!
    await testMode.setValue(true)
    await view.get('textarea[placeholder*="教学考虑"]').setValue('项目评价为主，测试只检查必要概念。')
    await view.get('[data-test="confirm-modes"]').trigger('click')
    await flushPromises()

    expect(apiMocks.confirmEvaluationAIDraftModes).toHaveBeenCalledWith(31, {
      modes: ['project', 'test'],
      teacher_note: '项目评价为主，测试只检查必要概念。'
    })
    expect(view.find('[data-test="generate-draft"]').exists()).toBe(true)
    expect(apiMocks.generateEvaluationAIDraft).not.toHaveBeenCalled()
  })

  it('lets the teacher remove, restore and edit generated items including performance levels', async () => {
    const view = await mountWizard()
    await reachReview(view)

    await view.get('[data-test="review-learning_goal:G1"] [data-test="remove-item"]').trigger('click')
    expect(view.get('[data-test="review-learning_goal:G1"]').text()).toContain('已删除')
    await view.get('[data-test="review-learning_goal:G1"] [data-test="restore-item"]').trigger('click')
    await view.get('[data-test="review-learning_goal:G1"] input').setValue('理解并解释数据编码')
    expect(view.get('[data-test="review-learning_goal:G1"]').text()).toContain('已修改')

    await view.get('[data-test="review-performance_level:C1:4"] textarea').setValue('能独立选择、验证并清楚解释编码方案。')
    expect(view.get('[data-test="review-performance_level:C1:4"]').text()).toContain('已修改')

    const taskWeight = view.get('[data-test="review-evaluation_task:T1"] input[type="number"]')
    await taskWeight.setValue('80')
    expect(view.text()).toContain('当前评价任务权重合计：80 / 100')
    await taskWeight.setValue('100')

    const scoringExample = view.get('[data-test="review-scoring_example:C1:4:1"]')
    await scoringExample.get('textarea').setValue('方案合理、验证充分，并能依据证据完成个人说明。')
    expect(view.get('[data-test="review-scoring_example:C1:4:1"]').text()).toContain('已修改')
  })

  it('batch accepts only pending review items without overwriting teacher changes', async () => {
    const view = await mountWizard()
    await reachReview(view)

    await view.get('[data-test="review-learning_goal:G1"] input').setValue('教师修改后的学习目标')
    await view.get('[data-test="review-learning_activity:A1"] [data-test="remove-item"]').trigger('click')
    await view.get('[data-test="batch-accept-pending"]').trigger('click')
    expect(view.text()).toContain('确认批量采纳')
    await view.get('[data-test="confirm-batch-accept"]').trigger('click')

    expect(view.get('[data-test="review-learning_goal:G1"]').text()).toContain('已修改')
    expect(view.get('[data-test="review-learning_activity:A1"]').text()).toContain('已删除')
    expect(view.get('[data-test="review-evaluation_task:T1"]').text()).toContain('已采纳')
    expect(view.text()).toContain('待审阅 0 项')
    expect(view.get('[data-test="batch-review-complete"]').text()).toContain('已全部处理')
    expect(view.find('[data-test="batch-accept-pending"]').exists()).toBe(false)
  })

  it('explains blocked completion and lets the teacher ask AI to regenerate an incomplete draft', async () => {
    const incomplete = session({
      ...confirmedSession(),
      status: 'draft_generated',
      status_label: '初稿待审阅',
      plan_draft: {
        ...planDraft,
        evaluation_basis: [],
        learning_activities: planDraft.learning_activities.map((item) => ({ ...item, goal_codes: [] }))
      },
      standard_draft: standardDraft,
      checks: [{
        code: 'basis_goal_alignment',
        label: '评价依据与学习目标对应',
        status: 'blocked',
        message: '评价依据缺失。'
      }]
    })
    apiMocks.generateEvaluationAIDraft
      .mockResolvedValueOnce(incomplete)
      .mockResolvedValueOnce(generatedSession())
    const view = await mountWizard()
    await reachReview(view)

    await view.get('[data-test="batch-accept-pending"]').trigger('click')
    await view.get('[data-test="confirm-batch-accept"]').trigger('click')

    const next = view.get('[data-test="review-next"]')
    expect(next.attributes('disabled')).toBeDefined()
    expect(next.text()).toContain('还需处理')
    expect(view.text()).toContain('批量采纳只完成教师审阅记录')

    await view.get('[data-test="request-regenerate-draft"]').trigger('click')
    expect(view.text()).toContain('让 AI 重新完善这份初稿')
    await view.get('[data-test="confirm-regenerate-draft"]').trigger('click')
    await flushPromises()

    expect(apiMocks.generateEvaluationAIDraft).toHaveBeenLastCalledWith(31, { regenerate: true })
    expect(view.text()).toContain('AI 已重新形成完整初稿')
    expect(view.get('[data-test="review-next"]').text()).toContain('待审阅')
  })

  it('saves only reviewed plan and standard drafts without publishing them', async () => {
    const view = await mountWizard()
    await reachReview(view)

    for (const button of view.findAll('[data-test="accept-item"]')) await button.trigger('click')
    await view.get('[data-test="review-next"]').trigger('click')

    expect(view.text()).toContain('评价方案和评价标准均保存为“编辑中”草稿')
    expect(view.get('[data-test="save-draft-only"]').attributes('disabled')).toBeDefined()
    expect(view.get('[data-test="save-draft-only"]').text()).toContain('请先勾选')
    await view.get('[data-test="save-acknowledgement"]').setValue(true)
    expect(view.get('[data-test="save-draft-only"]').text()).toBe('保存为评价草稿')
    await view.get('[data-test="save-draft-only"]').trigger('click')
    await flushPromises()

    expect(apiMocks.saveEvaluationAIPlanDraft).toHaveBeenCalledTimes(1)
    const payload = apiMocks.saveEvaluationAIPlanDraft.mock.calls[0][1]
    expect(payload.plan_draft.title).toBe(planDraft.title)
    expect(payload.standard_draft.criteria[0].level_descriptions['4']).toContain('独立选择')
    expect(payload.review_decisions.some((item: { item_type: string }) => item.item_type === 'evaluation_criterion')).toBe(true)
    expect(payload.review_decisions.some((item: { item_type: string }) => item.item_type === 'performance_level')).toBe(true)
    expect(payload.review_decisions.some((item: { item_type: string }) => item.item_type === 'scoring_example')).toBe(true)
    expect(payload.review_decisions.some((item: { item_key: string }) => item.item_key === 'learning_task:L1')).toBe(true)
    expect(payload.review_decisions.some((item: { item_key: string }) => item.item_key === 'follow_up_suggestion:plan')).toBe(true)
    expect(view.emitted('saved')?.[0]).toEqual([savedPlan, savedStandard])
  })

  it('resumes and polls an unfinished background generation session', async () => {
    vi.useFakeTimers()
    const processing = session({
      ...confirmedSession(),
      status: 'generating_draft',
      status_label: '正在后台生成',
      background_task: { status: 'running', message: '正在生成，可关闭后稍后继续', progress: 45 }
    })
    apiMocks.getEvaluationAIDraft
      .mockResolvedValueOnce(processing)
      .mockResolvedValueOnce(generatedSession())
    const view = await mountWizard([processing])

    await view.findAll('.ai-recent-sessions > button').find((button) => button.text().includes('数据编码与表示'))!.trigger('click')
    await flushPromises()
    expect(view.text()).toContain('正在生成，可关闭后稍后继续')
    await vi.advanceTimersByTimeAsync(1200)
    await flushPromises()

    expect(apiMocks.getEvaluationAIDraft).toHaveBeenCalledTimes(2)
    expect(view.text()).toContain('自动检查并由教师审阅')
  })
})
