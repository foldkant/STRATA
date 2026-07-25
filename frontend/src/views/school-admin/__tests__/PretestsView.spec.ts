import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PretestsView from '../PretestsView.vue'

const apiMocks = vi.hoisted(() => ({
  getSubjects: vi.fn(),
  getPretestPapers: vi.fn(),
  getPendingPretestMaterials: vi.fn(),
  getDiagnosticAdministrations: vi.fn(),
  reviewPretestMaterial: vi.fn()
}))

vi.mock('@/api/management', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/management')>(),
  ...apiMocks
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

const material = {
  material_id: 'material-1',
  student: { id: 8, username: 'student8', display_name: '学生甲' },
  class_group: { id: 3, name: '七年级1班', grade: '七年级' },
  subject: { id: 2, name: '信息科技' },
  learning_target_code: 'IT-DATA-01',
  material_type: 'operation',
  material_type_label: '操作记录',
  material_status: 'pending_review',
  material_status_label: '等待评价',
  question_id: '7',
  question_type: 'operation',
  answer: '完成数据导入并说明检查过程。',
  process_explanation: '完成数据导入并说明检查过程。',
  attachments: [],
  material_requirements: ['操作过程说明'],
  score_max: 10,
  recorded_at: '2026-07-22T08:00:00+08:00'
}

let wrapper: VueWrapper | null = null

async function mountView() {
  apiMocks.getSubjects.mockResolvedValue([
    { id: 2, name: '信息科技', code: 'IT', is_active: true, pretest_count: 1 }
  ])
  apiMocks.getPretestPapers.mockResolvedValue({ count: 0, page: 1, page_size: 20, results: [] })
  apiMocks.getPendingPretestMaterials.mockResolvedValue([material])
  apiMocks.getDiagnosticAdministrations.mockResolvedValue([])
  wrapper = mount(PretestsView, {
    attachTo: document.body,
    global: {
      components: { AppSelect: AppSelectStub },
      stubs: {
        AppShell: { template: '<main><slot /></main>' },
        NoticeLine: { props: ['message'], template: '<p class="notice-stub">{{ message }}</p>' },
        ManagementPage: true,
        EntityFormModal: true,
        ConfirmDialog: true,
        Teleport: true
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

describe('school administrator diagnostic material review P3 contract', () => {
  it('keeps the published maximum score read-only and prevents duplicate review writes', async () => {
    apiMocks.reviewPretestMaterial.mockReturnValue(new Promise(() => undefined))
    const view = await mountView()
    const open = view.findAll('button').find((button) => button.text() === '查看待评价材料')!
    await open.trigger('click')
    await flushPromises()
    await view.get('.pretest-material-review-body aside button').trigger('click')

    const inputs = view.findAll('.material-score-grid input')
    expect(inputs[1].attributes('readonly')).toBeDefined()
    expect((inputs[1].element as HTMLInputElement).value).toBe('10')
    await inputs[0].setValue('8')
    const submit = view.findAll('.pretest-material-review-body button').find((button) => button.text() === '保存评价')!
    await submit.trigger('click')
    await submit.trigger('click')
    await nextTick()

    expect(apiMocks.reviewPretestMaterial).toHaveBeenCalledTimes(1)
    expect(apiMocks.reviewPretestMaterial).toHaveBeenCalledWith('material-1', {
      score: 8,
      feedback: ''
    })
    const pendingSubmit = view.findAll('.pretest-material-review-body button').find((button) => button.text() === '保存中')!
    expect(pendingSubmit.attributes('disabled')).toBeDefined()
  })
})
