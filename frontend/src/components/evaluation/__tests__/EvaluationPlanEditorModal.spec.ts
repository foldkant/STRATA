import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import AppSelect from '@/components/AppSelect.vue'
import type { EvaluationOptions, EvaluationPlanRow } from '@/api/evaluation'
import EvaluationPlanEditorModal from '../EvaluationPlanEditorModal.vue'

let wrapper: VueWrapper | null = null

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
    }],
    scopes: [],
    review_statuses: [],
    dimensions: [],
    thinking_requirements: [],
    standard_versions: [],
    trial_types: [],
    trial_statuses: [],
    trial_conclusions: []
  }
}

function draft(): EvaluationPlanRow {
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
    review_status: 'draft',
    review_status_label: '草稿',
    latest_version: null,
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
    updated_at: '2026-07-22T08:00:00+08:00'
  }
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('EvaluationPlanEditorModal curriculum references', () => {
  it('opens the original-text trace from a selected curriculum reference', async () => {
    wrapper = mount(EvaluationPlanEditorModal, {
      props: { draft: draft(), options: options() },
      global: {
        components: { AppSelect },
        stubs: {
          CurriculumReferencePickerModal: true,
          CurriculumReferenceTraceModal: TraceModalStub
        }
      }
    })

    const traceButton = wrapper.findAll('button').find((button) => button.text() === '查看原文')
    expect(traceButton).toBeDefined()
    await traceButton!.trigger('click')

    expect(wrapper.get('[data-test="reference-trace"]').text()).toBe('37')
  })
})
