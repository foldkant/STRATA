import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import EvaluationRatingInput from './EvaluationRatingInput.vue'

const AppSelectStub = defineComponent({
  props: { value: String },
  template: '<select :value="value"><slot /></select>'
})

describe('EvaluationRatingInput', () => {
  it('shows curriculum foundation, criterion and quality reference as three distinct columns', () => {
    const wrapper = mount(EvaluationRatingInput, {
      props: {
        criterion: {
          id: 'c1',
          title: '数据表示方法判断与说明',
          description: '能根据数据特点选择方法并说明理由。',
          level_descriptions: ['需要支持', '初步完成', '基本达成', '较好达成', '拓展迁移'],
          curriculum_alignment: {
            learning_goals: [{ code: 'G1', title: '依据任务需要处理数据', description: '选择方法并说明理由。' }],
            core_competencies: [{ node_id: 1, title: '核心素养', elements: ['信息意识', '计算思维'], page_start: 7, page_end: 9 }],
            academic_quality: [{ node_id: 2, title: '学业质量', level_labels: ['水平 1', '水平 2', '水平 3'], page_start: 40, page_end: 44 }],
            quality_mapping_status: 'reference_only',
            quality_mapping_note: '课堂表现水平不直接等同于课标学业质量等级。'
          }
        }
      },
      global: { components: { AppSelect: AppSelectStub } }
    })

    expect(wrapper.text()).toContain('左 · 课标依据')
    expect(wrapper.text()).toContain('信息意识')
    expect(wrapper.text()).toContain('中 · 评价指标')
    expect(wrapper.text()).toContain('右 · 表现水平')
    expect(wrapper.text()).toContain('学业质量 · 第 40—44 页')
    expect(wrapper.text()).toContain('不直接等同')
    expect(wrapper.findAll('.evaluation-level-matrix li')).toHaveLength(5)
  })
})
