import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  getTeacherDashboard: vi.fn()
}))

vi.mock('@/api/teacher', () => apiMocks)
vi.mock('@/layouts/AppShell.vue', () => ({
  default: defineComponent({
    props: ['title', 'eyebrow', 'navItems'],
    template: '<main :data-shell-title="title"><slot /></main>'
  })
}))
vi.mock('@/components/EChartPanel.vue', () => ({
  default: defineComponent({
    props: ['title'],
    template: '<article class="chart-stub">{{ title }}</article>'
  })
}))

import DashboardView from '../DashboardView.vue'
import { teacherNavItems } from '../nav'

const RouterLinkStub = defineComponent({
  props: ['to'],
  template: '<a :href="to"><slot /></a>'
})

describe('Teacher dashboard information hierarchy', () => {
  beforeEach(() => {
    apiMocks.getTeacherDashboard.mockReset()
    apiMocks.getTeacherDashboard.mockResolvedValue({
      school: { id: 1, name: '测试学校', code: '001' },
      metrics: [
        { label: '任教班级', value: 3, sub: '学校已分配' },
        { label: '学生', value: 96, sub: '任教范围内' },
        { label: '课程', value: 4, sub: '本人课程' },
        { label: '资源', value: 12, sub: '本人上传' },
        { label: '今日学习记录', value: 25, sub: '任教范围内' },
        { label: '待确认教学安排', value: 8, sub: '学习内容与支持建议' }
      ],
      charts: {
        event_series: [],
        login_series: [],
        active_students_7d: [],
        class_students: [],
        class_activity: [],
        event_types: [],
        decision_status: [],
        training_status: []
      },
      class_rows: [{ id: 1, name: '高一1班', grade: '高一', student_count: 32, event_count: 10, status_label: '启用' }],
      todo_rows: [{ label: '待确认学习支持安排', count: 8, level: 'warn', path: '/teacher/stratification' }]
    })
  })

  it('uses a direct home entry, compact shortcuts and a complete teaching overview', async () => {
    expect(teacherNavItems[0]).toMatchObject({ label: '首页', path: '/teacher', group: '' })

    const wrapper = mount(DashboardView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub
        }
      }
    })
    await flushPromises()

    expect(wrapper.get('main').attributes('data-shell-title')).toBe('首页')
    expect(wrapper.findAll('.teacher-home-shortcut')).toHaveLength(6)
    expect(wrapper.findAll('.teacher-home-shortcut strong').map((item) => item.text())).toEqual([
      '课程与课时',
      '课堂教学',
      '作业与测试',
      '评价方案',
      '学生学习情况',
      '教学资源'
    ])
    expect(wrapper.findAll('.teacher-home-metrics article')).toHaveLength(4)
    expect(wrapper.findAll('.chart-stub')).toHaveLength(4)
    expect(wrapper.text()).toContain('教学概况')
    expect(wrapper.text()).toContain('班级学习活动')
    expect(wrapper.text()).toContain('学生分布')
    expect(wrapper.text()).not.toContain('今天先做什么')
    expect(wrapper.text()).not.toContain('待处理')
    expect(wrapper.text()).not.toContain('任教班级')
  })
})
