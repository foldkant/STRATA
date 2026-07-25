import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StratificationView from '../StratificationView.vue'
import type { StratificationSuggestionRow } from '@/api/learningAnalytics'

const analyticsMocks = vi.hoisted(() => ({
  getStratificationOverview: vi.fn(),
  getStratificationSuggestions: vi.fn(),
  getLearningSummaries: vi.fn(),
  refreshLearningSummaries: vi.fn(),
  reviewStratificationSuggestion: vi.fn(),
  bulkReviewStratificationSuggestions: vi.fn(),
  manuallyAdjustStratification: vi.fn()
}))
const teacherMocks = vi.hoisted(() => ({ getTeacherCourseOptions: vi.fn() }))

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
vi.mock('@/api/learningAnalytics', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/learningAnalytics')>(),
  ...analyticsMocks
}))
vi.mock('@/api/teacher', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/teacher')>(),
  ...teacherMocks
}))

const AppSelectStub = defineComponent({
  name: 'AppSelect',
  inheritAttrs: false,
  props: { modelValue: [String, Number], value: [String, Number] },
  emits: ['update:modelValue', 'change'],
  template: `<select v-bind="$attrs" :value="modelValue ?? value" @change="$emit('update:modelValue', $event.target.value); $emit('change', $event)"><slot /></select>`
})

function suggestion(): StratificationSuggestionRow {
  return {
    id: 91,
    student: { id: 7, username: 'student7', display_name: '测试学生', student_no: 'S007' },
    class_group: { id: 3, name: '七年级1班', grade: '七年级' },
    subject: { id: 2, name: '信息科技' },
    course: { id: 5, title: '数据与计算' },
    previous_layer: '',
    current_layer: 'A',
    current_layer_label: '拓展挑战层',
    suggested_layer: 'A',
    confidence: 0,
    reasons: ['两个学习目标的共同测试材料满足当前标准。'],
    missing_data: [],
    learning_summary: {},
    support_suggestion: '',
    decision_kind: 'content_band' as const,
    support_priority: '' as const,
    recommendation_status: 'confirmed',
    recommendation_status_label: '已确认',
    target_state: null,
    target_states: [
      {
        id: 101,
        learning_target_version_id: 201,
        learning_target_code: 'IT-DATA-01',
        learning_target_name: '依据需求选择数据表示方式',
        evidence_status: 'available' as const,
        evidence_coverage: 0.9,
        estimate: 0.85,
        uncertainty: 0.12,
        valid_until: '2026-08-20T00:00:00+08:00',
        content_hash: 'a'.repeat(64)
      },
      {
        id: 102,
        learning_target_version_id: 202,
        learning_target_code: 'IT-DATA-02',
        learning_target_name: '使用工具处理并解释数据',
        evidence_status: 'available' as const,
        evidence_coverage: 0.85,
        estimate: 0.82,
        uncertainty: 0.14,
        valid_until: '2026-08-20T00:00:00+08:00',
        content_hash: 'b'.repeat(64)
      }
    ],
    abstain_reason: '',
    transition_checks: {},
    mastery_snapshot_id: 55,
    rule_version: 'content-policy-1',
    source_label: '共同测试层级建议',
    window_start: '2026-07-01T00:00:00+08:00',
    window_end: '2026-07-20T00:00:00+08:00',
    status: 'accepted',
    status_label: '已采纳',
    teacher_selected_layer: 'A',
    review_reason_code: '',
    review_reason_label: '',
    review_note: '',
    reviewed_by: '信息科技教师',
    reviewed_at: '2026-07-21T00:00:00+08:00',
    created_at: '2026-07-20T00:00:00+08:00'
  }
}

async function mountView(suggestionRows?: StratificationSuggestionRow[]) {
  const row = suggestion()
  const rows = suggestionRows || [row]
  teacherMocks.getTeacherCourseOptions.mockResolvedValue({
    courses: [{ id: 5, title: '数据与计算' }],
    classes: [],
    subjects: []
  })
  analyticsMocks.getStratificationOverview.mockResolvedValue({
    scope: { class_group_ids: [3], course: { id: 5, title: '数据与计算' } },
    counts: { total: 1, A: 1, B: 0, C: 0, unassigned: 0, pending: 0 },
    class_distribution: [],
    rows: [{
      id: 7,
      student: row.student,
      class_group: row.class_group,
      current_layer: 'A',
      current_layer_label: '拓展挑战层',
      learning: null,
      latest_decision: row
    }]
  })
  analyticsMocks.getStratificationSuggestions.mockResolvedValue(rows)
  analyticsMocks.manuallyAdjustStratification.mockResolvedValue({ ...row, id: 92, current_layer: 'B' })

  const wrapper = mount(StratificationView, {
    attachTo: document.body,
    global: {
      components: { AppSelect: AppSelectStub },
      stubs: {
        AppShell: { template: '<main><slot /></main>' },
        NoticeLine: { props: ['message'], template: '<p>{{ message }}</p>' },
        MultiSelectActions: true
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

describe('teacher dynamic stratification P4 contract', () => {
  it('shows every target-level basis and carries it into a guarded manual adjustment', async () => {
    const wrapper = await mountView()
    await wrapper.get('button.assessment-row-review').trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('目标级学习依据（2 项）')
    expect(wrapper.text()).toContain('依据需求选择数据表示方式')
    expect(wrapper.text()).toContain('使用工具处理并解释数据')
    const reviewDialog = wrapper.get('[aria-labelledby="suggestion-review-title"]')
    expect(reviewDialog.element.contains(document.activeElement)).toBe(true)

    await wrapper.get('[aria-labelledby="suggestion-review-title"] .modal-actions .secondary-button').trigger('click')
    await wrapper.get('button.assessment-row-review.secondary').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('沿用所选记录中的目标级学习依据')

    const manualDialog = wrapper.get('[aria-labelledby="manual-layer-title"]')
    const selects = manualDialog.findAll('select')
    await selects[0].setValue('B')
    await selects[1].setValue('classroom_evidence')
    const submit = manualDialog.get('button[type="submit"]')
    await submit.trigger('click')
    await submit.trigger('click')
    await flushPromises()

    expect(analyticsMocks.manuallyAdjustStratification).toHaveBeenCalledTimes(1)
    expect(analyticsMocks.manuallyAdjustStratification).toHaveBeenCalledWith(expect.objectContaining({
      student: 7,
      course: 5,
      source_decision: 91,
      layer: 'B'
    }))
  })

  it('opens one confirmation flow for every pending suggestion in the current scope', async () => {
    const first = {
      ...suggestion(),
      status: 'pending' as const,
      status_label: '待教师确认',
      reviewed_by: '',
      reviewed_at: null
    }
    const second = {
      ...first,
      id: 92,
      student: { ...first.student, id: 8, username: 'student8', display_name: '第二名学生', student_no: 'S008' }
    }
    analyticsMocks.bulkReviewStratificationSuggestions.mockResolvedValue({
      updated_count: 2,
      ids: [91, 92],
      action: 'accept'
    })
    const wrapper = await mountView([first, second])
    const pendingTab = wrapper.findAll('.stratification-tabs button').find((button) => button.text().includes('待处理建议'))
    expect(pendingTab).toBeTruthy()
    await pendingTab!.trigger('click')
    await wrapper.get('[data-test="stratification-review-all"]').trigger('click')
    await nextTick()

    const dialog = wrapper.get('[aria-labelledby="batch-review-title"]')
    expect(dialog.text()).toContain('批量处理全部建议')
    expect(dialog.text()).toContain('当前筛选范围 2 条')
    expect(dialog.text()).toContain('不受表格分页影响')
    await dialog.get('button[type="submit"]').trigger('click')
    await flushPromises()

    expect(analyticsMocks.bulkReviewStratificationSuggestions).toHaveBeenCalledWith({
      ids: [91, 92],
      action: 'accept',
      reason_code: undefined,
      note: ''
    })
  })
})
