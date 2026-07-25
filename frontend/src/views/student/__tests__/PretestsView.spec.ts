import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PretestsView from '../PretestsView.vue'

const apiMocks = vi.hoisted(() => ({
  getStudentPretestPaper: vi.fn(),
  getStudentSubjectPretests: vi.fn(),
  submitStudentPretestPaper: vi.fn()
}))

const routerMocks = vi.hoisted(() => ({
  back: vi.fn(),
  push: vi.fn()
}))

vi.mock('@/api/student', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/student')>(),
  ...apiMocks
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { subjectId: '2' } }),
  useRouter: () => routerMocks
}))

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

const subject = { id: 2, name: '信息科技', code: 'IT' }

function scheduledPaper() {
  return {
    administration_id: 31,
    batch_code: 'IT-2026-SCHEDULED',
    title: '七年级信息科技学习起点诊断',
    purpose: 'entry_diagnostic',
    purpose_label: '学习起点诊断',
    opportunity_status: 'offered',
    availability_status: 'scheduled',
    submission_allowed: false,
    open_at: '2026-09-01T00:00:00+08:00',
    close_at: '2026-09-07T00:00:00+08:00',
    completion: {
      submission: 'pending',
      scoring: 'not_started',
      course_access: 'deferred',
      exception: ''
    },
    subject
  }
}

function openPaper() {
  return {
    administration_id: 32,
    batch_code: 'IT-2026-OPEN',
    title: '七年级信息科技学习起点诊断',
    purpose: 'entry_diagnostic',
    purpose_label: '学习起点诊断',
    opportunity_status: 'offered',
    availability_status: 'open',
    submission_allowed: true,
    subject,
    kind: 'literacy',
    kind_label: '学科学习诊断',
    version: 1,
    introduction: '了解数据表示学习起点。',
    published_version: { id: 9, version_no: 1, content_hash: 'a'.repeat(64) },
    questions: [{
      id: 7,
      paper: 4,
      stem: '哪一种表示适合比较数量？',
      question_type: 'single',
      question_type_label: '单选',
      options: [{ label: 'A', text: '柱状图' }, { label: 'B', text: '散点图' }],
      score: 2,
      dimension: '数据表示',
      learning_target_code: 'IT-DATA-01',
      learning_target_name: '选择合适的数据表示方式',
      material_requirements: [],
      attachment_policy: { enabled: false, allowed_extensions: [], max_files: 1, max_file_mb: 1 },
      sort_order: 1,
      is_required: true
    }]
  }
}

let wrapper: VueWrapper | null = null

function mountView() {
  wrapper = mount(PretestsView, {
    global: {
      components: { AppSelect: AppSelectStub },
      stubs: {
        StudentShell: { template: '<main><slot name="actions" /><slot /></main>' },
        NoticeLine: { props: ['message'], template: '<p class="notice-stub">{{ message }}</p>' }
      }
    }
  })
  return wrapper
}

beforeEach(() => {
  Object.values(apiMocks).forEach((mock) => mock.mockReset())
  Object.values(routerMocks).forEach((mock) => mock.mockReset())
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('student learning-entry diagnostic P3 contract', () => {
  it('renders a scheduled administration without exposing task controls or undefined version data', async () => {
    const row = scheduledPaper()
    apiMocks.getStudentSubjectPretests.mockResolvedValue({
      subject,
      pretest_status: {
        required: false,
        completed: false,
        assigned: true,
        status: 'scheduled',
        course_access: 'eligible',
        missing: []
      },
      papers: [row]
    })
    apiMocks.getStudentPretestPaper.mockResolvedValue(row)

    const view = mountView()
    await flushPromises()

    expect(view.text()).toContain('已有诊断实施安排，当前尚未开放')
    expect(view.text()).toContain('IT-2026-SCHEDULED')
    expect(view.text()).not.toContain('诊断版本 vundefined')
    expect(view.find('.diagnostic-opportunity').exists()).toBe(false)
    expect(view.get('.student-primary-action').attributes('disabled')).toBeDefined()
  })

  it('prevents duplicate submission while the first immutable request is pending', async () => {
    const row = openPaper()
    apiMocks.getStudentSubjectPretests.mockResolvedValue({
      subject,
      pretest_status: {
        required: true,
        completed: false,
        assigned: true,
        status: 'action_required',
        course_access: 'deferred',
        missing: [{ administration_id: 32 }]
      },
      papers: [row]
    })
    apiMocks.getStudentPretestPaper.mockResolvedValue(row)
    apiMocks.submitStudentPretestPaper.mockReturnValue(new Promise(() => undefined))

    const view = mountView()
    await flushPromises()
    await view.get('input[type="radio"][value="A"]').setValue()
    const submit = view.findAll('button').find((button) => button.text() === '提交诊断材料')!
    await submit.trigger('click')
    await submit.trigger('click')

    expect(apiMocks.submitStudentPretestPaper).toHaveBeenCalledTimes(1)
    expect(submit.attributes('disabled')).toBeDefined()
  })
})
