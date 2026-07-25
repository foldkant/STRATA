import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import type { EvaluationOptions, EvaluationTrialRow } from '@/api/evaluation'
import EvaluationTrialEditorModal from '../EvaluationTrialEditorModal.vue'

const saveEvaluationTrialMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/evaluation', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/evaluation')>(),
  saveEvaluationTrial: saveEvaluationTrialMock
}))

let wrapper: VueWrapper | null = null

const AppSelectStub = defineComponent({
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>'
})

function options(): EvaluationOptions {
  return {
    courses: [],
    scopes: [],
    review_statuses: [],
    dimensions: [],
    assessment_modes: [],
    evidence_ownerships: [],
    material_types: [],
    thinking_requirements: [],
    plan_versions: [],
    standard_versions: [{
      id: 88,
      title: '数据表达评价标准',
      version_no: 3,
      subject: { id: 2, name: '信息科技' },
      course: { id: 9, title: '数据与计算' }
    }],
    trial_types: [
      { value: 'content_review', label: '内容审核' },
      { value: 'scoring_check', label: '评分检查' }
    ],
    trial_statuses: [
      { value: 'planned', label: '待开展' },
      { value: 'completed', label: '已完成' }
    ],
    trial_conclusions: [
      { value: 'pending', label: '待确认' },
      { value: 'accepted', label: '通过' }
    ]
  }
}

function trial(overrides: Partial<EvaluationTrialRow> = {}): EvaluationTrialRow {
  return {
    id: 31,
    standard_version: options().standard_versions[0],
    record_type: 'content_review',
    record_type_label: '内容审核',
    title: '数据表达课堂试用',
    status: 'planned',
    status_label: '待开展',
    activity_date: '2026-07-22',
    participant_count: 0,
    agreement_rate: null,
    conclusion: 'pending',
    conclusion_label: '待确认',
    summary: '',
    issues: [],
    action_items: [],
    created_by: '信息科技教师',
    updated_by: '信息科技教师',
    completion_hash: '',
    completed_by: null,
    completed_at: null,
    created_at: '2026-07-22T08:00:00+08:00',
    updated_at: '2026-07-22T08:00:00+08:00',
    ...overrides
  }
}

function mountEditor(row: EvaluationTrialRow | null) {
  wrapper = mount(EvaluationTrialEditorModal, {
    props: { draft: row, options: options() },
    global: { components: { AppSelect: AppSelectStub } }
  })
  return wrapper
}

beforeEach(() => {
  saveEvaluationTrialMock.mockReset()
  saveEvaluationTrialMock.mockResolvedValue(trial())
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('EvaluationTrialEditorModal', () => {
  it('shows completion audit fields for an immutable completed record without a save action', () => {
    const completedAt = '2026-07-22T09:30:00+08:00'
    const completionHash = '8e7472f07fb9f17b1f15ed08fd80893f4f8e26f724cb9370a98a44e212ab3829'
    const view = mountEditor(trial({
      status: 'completed',
      status_label: '已完成',
      participant_count: 32,
      conclusion: 'accepted',
      conclusion_label: '通过',
      summary: '课堂试用结果符合预期。',
      completed_by: '信息科技教研组长',
      completed_at: completedAt,
      completion_hash: completionHash
    }))

    const audit = view.get('[aria-label="完成记录追溯信息"]')
    expect(audit.text()).toContain('信息科技教研组长')
    expect(audit.text()).toContain(new Date(completedAt).toLocaleString('zh-CN'))
    expect(audit.get('code').text()).toBe(completionHash)
    expect(view.findAll('button').some((button) => button.text() === '保存记录')).toBe(false)
    expect(saveEvaluationTrialMock).not.toHaveBeenCalled()
  })

  it('submits only once when save is clicked twice while the request is pending', async () => {
    let resolveSave!: (row: EvaluationTrialRow) => void
    saveEvaluationTrialMock.mockImplementation(() => new Promise<EvaluationTrialRow>((resolve) => {
      resolveSave = resolve
    }))
    const row = trial()
    const view = mountEditor(row)
    const saveButton = view.findAll('button').find((button) => button.text() === '保存记录')!

    await Promise.all([
      saveButton.trigger('click'),
      saveButton.trigger('click')
    ])

    expect(saveEvaluationTrialMock).toHaveBeenCalledTimes(1)
    expect(saveEvaluationTrialMock).toHaveBeenCalledWith(expect.objectContaining({
      standard_version: 88,
      title: '数据表达课堂试用'
    }), 31)

    resolveSave(row)
    await flushPromises()
    expect(view.emitted('saved')).toEqual([[row]])
  })
})
