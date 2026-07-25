import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import QuestionBankView from '../QuestionBankView.vue'

const {
  getAssessmentOptions,
  getQuestionBank,
  generateQuestionBankDrafts,
  confirmQuestionBankDrafts,
  getLatestQuestionBankDraftJob,
  getQuestionBankDraftJob
} = vi.hoisted(() => ({
  getAssessmentOptions: vi.fn(),
  getQuestionBank: vi.fn(),
  generateQuestionBankDrafts: vi.fn(),
  confirmQuestionBankDrafts: vi.fn(),
  getLatestQuestionBankDraftJob: vi.fn(),
  getQuestionBankDraftJob: vi.fn()
}))

vi.mock('@/api/assessments', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/assessments')>()
  return {
    ...original,
    getAssessmentOptions,
    getQuestionBank,
    generateQuestionBankDrafts,
    confirmQuestionBankDrafts,
    getLatestQuestionBankDraftJob,
    getQuestionBankDraftJob
  }
})

const AppSelectStub = defineComponent({
  name: 'AppSelect',
  inheritAttrs: false,
  props: { modelValue: [String, Number], value: [String, Number] },
  emits: ['update:modelValue', 'change'],
  template: `
    <select
      v-bind="$attrs"
      :value="modelValue ?? value"
      @change="$emit('update:modelValue', $event.target.value); $emit('change', $event)"
    ><slot /></select>
  `
})

function mountView() {
  return mount(QuestionBankView, {
    global: {
      components: { AppSelect: AppSelectStub },
      stubs: {
        AppShell: { template: '<main><slot /></main>' },
        NoticeLine: { props: ['message'], template: '<p>{{ message }}</p>' }
      }
    }
  })
}

afterEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
})

describe('teacher question bank learning-target binding', () => {
  it('requires the teacher to select an exact target version before confirming AI drafts', async () => {
    vi.useFakeTimers()
    getAssessmentOptions.mockResolvedValue({
      subjects: [{ id: 1, name: '信息科技', code: 'IT' }],
      classes: [],
      courses: [{ id: 10, title: '高一信息科技', subject: 1 }],
      question_types: [{ value: 'single', label: '单选' }],
      difficulties: [{ value: 'normal', label: '适中' }],
      question_statuses: [],
      question_sources: [],
      item_roles: [],
      layer_scopes: [],
      learning_target_versions: [{
        id: 101,
        code: 'IT-DATA-01',
        title: '能够依据需求组织与处理数据',
        subject: 1,
        course: 10,
        course_title: '高一信息科技',
        content_hash: 'a'.repeat(64)
      }],
      common_question_sets: []
    })
    getQuestionBank.mockResolvedValue([])
    getLatestQuestionBankDraftJob.mockResolvedValue(null)
    generateQuestionBankDrafts.mockResolvedValue({
      id: 91,
      status: 'queued',
      status_label: '等待生成',
      subject: { id: 1, name: '信息科技', code: 'IT' },
      result: {},
      error_message: '',
      error_fields: {},
      attempt_count: 0,
      created_at: '2026-07-24T00:00:00Z',
      started_at: null,
      finished_at: null
    })
    getQuestionBankDraftJob.mockResolvedValue({
      id: 91,
      status: 'succeeded',
      status_label: '草稿已生成',
      subject: { id: 1, name: '信息科技', code: 'IT' },
      result: {
        subject: { id: 1, name: '信息科技', code: 'IT' },
        requested_count: 1,
        valid_count: 1,
        questions: [{
          draft_id: 'draft-1',
          selected: true,
          subject: 1,
          stem: '判断数据表示是否符合给定需求。',
          question_type: 'single',
          options: ['符合', '不符合'],
          answer: ['符合'],
          analysis: '依据给定需求核对数据表示。',
          difficulty: 'normal',
          knowledge_point: '数据表示',
          default_score: 2,
          item_role: 'regular',
          layer_scope: 'all'
        }]
      },
      error_message: '',
      error_fields: {},
      attempt_count: 1,
      created_at: '2026-07-24T00:00:00Z',
      started_at: '2026-07-24T00:00:01Z',
      finished_at: '2026-07-24T00:00:02Z'
    })
    confirmQuestionBankDrafts.mockResolvedValue({ created_count: 1, questions: [] })

    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('.assessment-ai-button').trigger('click')
    await wrapper.get('.assessment-ai-settings textarea').setValue('围绕数据表示与实际需求设计题目')
    await wrapper.get('.assessment-ai-settings .primary-button').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1600)
    await flushPromises()

    await wrapper.get('.assessment-ai-modal > .modal-actions .primary-button').trigger('click')
    expect(confirmQuestionBankDrafts).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请选择对应的学习目标版本')

    await wrapper.get('.assessment-ai-target-field select').setValue('101')
    await wrapper.get('.assessment-ai-modal > .modal-actions .primary-button').trigger('click')
    await flushPromises()

    expect(confirmQuestionBankDrafts).toHaveBeenCalledWith(
      1,
      expect.arrayContaining([
        expect.objectContaining({ learning_target_version_id: '101' })
      ])
    )
  })
})
