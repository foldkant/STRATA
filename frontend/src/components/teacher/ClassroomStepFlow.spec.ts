import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ClassroomStepFlow from './ClassroomStepFlow.vue'
import type { LessonStepRow } from '@/api/teacher'

const steps = [
  {
    id: 11,
    title: '观察编码现象',
    step_type_label: '学习任务',
    estimated_minutes: 8,
    target_layer_label: '全体'
  },
  {
    id: 12,
    title: '比较编码方案',
    step_type_label: '操作实践',
    estimated_minutes: 12,
    target_layer_label: '全体'
  }
] as LessonStepRow[]

describe('ClassroomStepFlow', () => {
  it('announces the selected and currently delivered learning step', async () => {
    const wrapper = mount(ClassroomStepFlow, {
      props: {
        steps,
        selectedStepId: 12,
        currentStepId: 11,
        currentStepStatus: 'open',
        stepStatusText: '已投放'
      }
    })

    const buttons = wrapper.findAll('button')
    expect(buttons[0].attributes('aria-label')).toContain('已投放')
    expect(buttons[0].text()).toContain('已投放')
    expect(buttons[1].attributes('aria-pressed')).toBe('true')
    expect(buttons[1].text()).toContain('待投放')

    await buttons[0].trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual([steps[0]])
  })

  it('shows a recoverable empty state when no lesson step is configured', () => {
    const wrapper = mount(ClassroomStepFlow, {
      props: {
        steps: [],
        selectedStepId: null,
        currentStepId: null,
        currentStepStatus: 'idle',
        stepStatusText: '未投放'
      }
    })

    expect(wrapper.text()).toContain('课时还没有已配置的学习环节')
  })
})
