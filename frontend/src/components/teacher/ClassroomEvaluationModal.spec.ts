import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import ClassroomEvaluationModal from './ClassroomEvaluationModal.vue'
import type { ClassroomEvaluationPayload } from '@/api/teacher'

const RouterLinkStub = defineComponent({
  props: { to: [String, Object] },
  template: '<a :href="String(to)"><slot /></a>'
})

function payload(): ClassroomEvaluationPayload {
  return {
    runtime_enabled: false,
    runtime_opened_at: null,
    config: {
      id: null,
      course: 3,
      session: 3,
      enable_self: false,
      enable_peer: false,
      enable_teacher: false,
      self_criteria: [],
      peer_criteria: [],
      teacher_criteria: [],
      opened_at: null,
      created_at: null,
      updated_at: null
    },
    summary: {
      self: { label: '自评', enabled: false, submitted: 0, total: 0, average: null, rated_item_count: 0, not_assessed_item_count: 0, unanswered_item_count: 0, total_item_count: 0, criteria: [] },
      peer: { label: '互评', enabled: false, submitted: 0, total: 0, average: null, rated_item_count: 0, not_assessed_item_count: 0, unanswered_item_count: 0, total_item_count: 0, criteria: [] },
      teacher: { label: '师评', enabled: false, submitted: 0, total: 0, average: null, rated_item_count: 0, not_assessed_item_count: 0, unanswered_item_count: 0, total_item_count: 0, criteria: [] }
    },
    students: [],
    recent_submissions: [],
    peer_available: false,
    availability: {
      can_enable: false,
      reason_code: 'current_step_unbound',
      reason: '当前环节“新课教授”尚未设置评价方案。',
      recovery: '可返回课时设计为本环节设置评价。',
      current_step: { id: 2, title: '新课教授' },
      current_binding: null,
      bound_steps: [{ id: 1, title: '导入', standard_version: 1, standard_title: '信息科技评价标准', version_no: 1 }]
    }
  }
}

describe('ClassroomEvaluationModal', () => {
  it('explains why evaluation cannot open and provides recoverable actions', async () => {
    const wrapper = mount(ClassroomEvaluationModal, {
      props: {
        open: true,
        sessionTitle: '信息科技课堂',
        classLabel: '测试班',
        loading: false,
        notice: '',
        lessonDesignPath: '/teacher/lessons/3/design',
        runtimeEnabled: false,
        enabledCount: 0,
        summaryItems: [],
        data: payload(),
        enableTeacher: false,
        selectedStudentId: null,
        selectedStudent: null,
        teacherCriteria: [],
        ratings: {},
        notAssessed: {},
        comment: ''
      },
      global: { stubs: { RouterLink: RouterLinkStub } }
    })

    expect(wrapper.text()).toContain('当前环节“新课教授”尚未设置评价方案')
    expect(wrapper.text()).toContain('已设置评价的环节')
    expect(wrapper.get('a').text()).toContain('为当前环节设置评价')
    expect(wrapper.findAll('button').find((button) => button.text() === '开启评价')?.attributes('disabled')).toBeDefined()

    await wrapper.findAll('button').find((button) => button.text().includes('定位到“导入”'))!.trigger('click')
    expect(wrapper.emitted('prepareStep')?.[0]).toEqual([1])
  })
})
