import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

const teacherApi = vi.hoisted(() => ({
  createTeacherLessonStep: vi.fn(),
  deleteTeacherLessonStep: vi.fn(),
  generateTeacherLessonStepQuestions: vi.fn(),
  getTeacherCourse: vi.fn(),
  getTeacherLesson: vi.fn(),
  getTeacherLessonSteps: vi.fn(),
  getTeacherResources: vi.fn(),
  reorderTeacherLessonSteps: vi.fn(),
  updateTeacherLessonStep: vi.fn(),
  uploadTeacherResource: vi.fn()
}))

const evaluationApi = vi.hoisted(() => ({
  getLessonStepEvaluationBinding: vi.fn(),
  saveLessonStepEvaluationBinding: vi.fn()
}))

vi.mock('@/api/teacher', () => teacherApi)
vi.mock('@/api/evaluation', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/evaluation')>(),
  ...evaluationApi
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => ({ params: { lessonId: '86' }, fullPath: '/teacher/lessons/86/design' })
}))
vi.mock('@/layouts/AppShell.vue', () => ({
  default: defineComponent({ template: '<main><slot /></main>' })
}))
vi.mock('@/components/FilePicker.vue', () => ({
  default: defineComponent({ template: '<div />' })
}))
vi.mock('@/components/NoticeLine.vue', () => ({
  default: defineComponent({ props: ['message'], template: '<p class="notice-stub">{{ message }}</p>' })
}))
vi.mock('@/components/ResourcePreview.vue', () => ({
  default: defineComponent({ template: '<div />' })
}))
import LessonDesignerView from '@/views/teacher/LessonDesignerView.vue'

const step = {
  id: 165,
  lesson: 86,
  title: '导入',
  step_type: 'intro',
  step_type_label: '导入',
  student_instruction: '观察情境并提出问题',
  teacher_note: '',
  sort_order: 10,
  is_required: true,
  estimated_minutes: 10,
  target_layer: 'all',
  target_layer_label: '全体',
  status: 'ready',
  status_label: '就绪',
  resource_items: [],
  activity_items: [],
  question_items: [],
  ai_prompt: '',
  collect_student_log: true,
  collect_class_log: true,
  created_at: '2026-07-23T00:00:00+08:00',
  updated_at: '2026-07-23T00:00:00+08:00'
}

const criterion = {
  id: 1,
  code: 'ITEM-01',
  dimension: 'subject_practice',
  dimension_label: '学科实践',
  title: '说明核心素养内涵',
  evaluation_target: '学生口头陈述',
  evaluation_sources: ['口头陈述'],
  expected_performance: '能够联系生活实例说明核心素养内涵。',
  level_descriptions: ['尚未形成', '部分形成', '基本形成', '较好形成', '充分形成'],
  skip_condition: '未获得陈述机会时暂不评价。',
  support_options: [],
  common_problems: [],
  follow_up_suggestion: ''
}

const binding = {
  id: 9,
  lesson_step: 165,
  standard_version: 12,
  standard_title: '核心素养口头陈述评价标准',
  version_no: 1,
  enable_self: true,
  enable_peer: false,
  enable_teacher: true,
  locked: false,
  criteria: [criterion, { ...criterion, id: 2, code: 'ITEM-02', title: '联系生活实例' }],
  created_at: '2026-07-23T00:00:00+08:00',
  updated_at: '2026-07-23T00:00:00+08:00'
}

describe('LessonDesignerView evaluation binding status', () => {
  beforeEach(() => {
    Object.values(teacherApi).forEach((mock) => mock.mockReset())
    Object.values(evaluationApi).forEach((mock) => mock.mockReset())
    teacherApi.getTeacherLesson.mockResolvedValue({
      id: 86,
      course: 16,
      course_title: '政治',
      title: '111',
      content: '课程内容'
    })
    teacherApi.getTeacherCourse.mockResolvedValue({
      id: 16,
      title: '政治',
      teaching_model: 'task',
      subject: { id: 2, name: '思想政治' },
      target_classes: [{ id: 1, grade: '高一' }]
    })
    teacherApi.getTeacherLessonSteps.mockResolvedValue([step])
    teacherApi.getTeacherResources.mockResolvedValue({ results: [] })
    evaluationApi.getLessonStepEvaluationBinding.mockResolvedValue({
      binding,
      standards: [{
        id: 12,
        title: binding.standard_title,
        version_no: 1,
        review_status: 'reviewed',
        review_status_label: '已复核',
        criterion_count: 2,
        criteria: binding.criteria
      }],
      use_boundaries: []
    })
    evaluationApi.saveLessonStepEvaluationBinding.mockResolvedValue(binding)
  })

  it('shows the persisted binding on the active lesson step', async () => {
    const view = mount(LessonDesignerView, {
      global: {
        stubs: {
          AppSelect: true,
          RouterLink: defineComponent({ template: '<a><slot /></a>' }),
          Teleport: true
        }
      }
    })
    await flushPromises()

    await view.findAll('.designer-tabs button').find((button) => button.text() === '评价')!.trigger('click')
    await flushPromises()

    expect(evaluationApi.getLessonStepEvaluationBinding).toHaveBeenCalledWith(165)
    expect(view.text()).toContain('已绑定到本环节')
    expect(view.text()).toContain('核心素养口头陈述评价标准')
    expect(view.text()).toContain('版本 1')
    expect(view.text()).toContain('学生自评、教师评价')
    expect(view.text()).toContain('2 项')
  })

  it('updates the lesson page immediately after the modal confirms a binding', async () => {
    const view = mount(LessonDesignerView, {
      global: {
        stubs: {
          AppSelect: true,
          RouterLink: defineComponent({ template: '<a><slot /></a>' }),
          Teleport: true
        }
      }
    })
    await flushPromises()

    await view.findAll('.designer-tabs button').find((button) => button.text() === '评价')!.trigger('click')
    await flushPromises()
    await view.findAll('button').find((button) => button.text() === '查看或调整评价安排')!.trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(view.find('.step-evaluation-modal').exists()).toBe(true))
    await view.findAll('button').find((button) => button.text().includes('确认绑定到本环节'))!.trigger('click')
    await flushPromises()

    expect(evaluationApi.saveLessonStepEvaluationBinding).toHaveBeenCalledWith(165, {
      standard_version: 12,
      enable_self: true,
      enable_peer: false,
      enable_teacher: true
    })
    expect(view.find('.step-evaluation-modal').exists()).toBe(false)
    expect(view.get('.notice-stub').text()).toContain('已绑定评价方案')
    expect(view.text()).toContain('已绑定到本环节')
  })

  it('passes the complete lesson and current-step context to AI evaluation authoring', async () => {
    teacherApi.getTeacherLessonSteps.mockResolvedValue([{
      ...step,
      teacher_note: '引导学生比较不同表示方法',
      activity_items: ['整理数据', '制作图表'],
      resource_items: [{ id: 7, title: '数据表示案例', attachment_url: '', attachment_name: '', file_ext: '', kind: 'file' }],
      question_items: [{ id: 'q1', question_type: 'text', stem: '为什么选择这种表示方法？', options: [], answer: [], score: 2, target_layer: 'all', use_layer_scores: false, layer_scores: { A: 2, B: 2, C: 2 }, analysis: '', is_required: true, sort_order: 10 }]
    }])
    const EvaluationModalStub = defineComponent({
      props: { open: Boolean, courseContent: String },
      template: '<pre v-if="open" data-test="evaluation-context">{{ courseContent }}</pre>'
    })
    const view = mount(LessonDesignerView, {
      global: {
        stubs: {
          AppSelect: true,
          RouterLink: defineComponent({ template: '<a><slot /></a>' }),
          Teleport: true,
          LessonStepEvaluationModal: EvaluationModalStub
        }
      }
    })
    await flushPromises()

    await view.findAll('button').find((button) => button.text() === '环节评价')!.trigger('click')
    const content = view.get('[data-test="evaluation-context"]').text()
    expect(content).toContain('课时内容：课程内容')
    expect(content).toContain('教师教学提示：引导学生比较不同表示方法')
    expect(content).toContain('学习活动：整理数据；制作图表')
    expect(content).toContain('学习资源：数据表示案例')
    expect(content).toContain('课堂问题或任务：为什么选择这种表示方法？')
  })
})
