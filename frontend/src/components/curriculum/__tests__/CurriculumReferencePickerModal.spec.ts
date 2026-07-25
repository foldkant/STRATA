import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import type { CurriculumReferenceStandard } from '@/api/curriculumStandards'
import CurriculumReferencePickerModal from '../CurriculumReferencePickerModal.vue'

const getCurriculumReferenceOptionsMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/curriculumStandards', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/curriculumStandards')>(),
  getCurriculumReferenceOptions: getCurriculumReferenceOptionsMock
}))

const AppSelectStub = defineComponent({
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue', 'change'],
  template: `
    <select
      :value="modelValue"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.value); $emit('change', $event)"
    >
      <slot />
    </select>
  `
})

function highSchoolStandard(): CurriculumReferenceStandard {
  return {
    id: 12,
    title: '普通高中信息技术课程标准（2025年版）',
    document_type: 'subject_standard',
    school_stage: 'k10_k12',
    subject_code: 'IT',
    subject_name: '信息技术',
    current_version: {
      id: 25,
      title: '普通高中信息技术课程标准（2025年版）',
      version_label: '2025年版',
      publication_year: 2025,
      effective_year: 2025,
      issued_by: '中华人民共和国教育部',
      source_url: 'https://example.edu.cn/high-school-it-2025',
      pdf_url: '/api/v1/curriculum-standard-versions/25/pdf/',
      pdf_page_count: 120,
      extraction_engine: 'pymupdf',
      extraction_engine_version: '1',
      extraction_config: {},
      extracted_at: '2026-07-22T08:00:00+08:00',
      content_hash: 'high-school-it-2025-hash',
      status: 'published',
      status_label: '当前使用',
      replaces_version: null,
      nodes: [{
        id: 251,
        node_type: 'core_competency',
        code: 'IT-HS-CC-01',
        title: '信息意识',
        content: '能够敏锐感觉到信息的变化，主动获取并合理使用信息。',
        parent: null,
        source_page_start: 8,
        source_page_end: 8,
        sort_order: 1
      }]
    }
  }
}

beforeEach(() => {
  getCurriculumReferenceOptionsMock.mockReset()
  getCurriculumReferenceOptionsMock.mockResolvedValue({
    standards: [highSchoolStandard()]
  })
  document.body.innerHTML = ''
})

describe('CurriculumReferencePickerModal', () => {
  it('requires a school stage before loading and requests only the selected high-school stage', async () => {
    const wrapper = mount(CurriculumReferencePickerModal, {
      props: {
        selected: [],
        subjectCode: 'IT',
        subjectName: '信息技术',
        schoolStage: ''
      },
      attachTo: document.body,
      global: {
        components: { AppSelect: AppSelectStub },
        stubs: { Teleport: true }
      }
    })
    await flushPromises()

    expect(getCurriculumReferenceOptionsMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('课程尚未设置学段，本次必须明确选择')

    const stageSelect = wrapper.findAll('select')[0]
    await stageSelect.setValue('k10_k12')
    await flushPromises()

    expect(getCurriculumReferenceOptionsMock).toHaveBeenCalledTimes(1)
    expect(getCurriculumReferenceOptionsMock).toHaveBeenCalledWith({
      subject_code: 'IT',
      subject_name: '信息技术',
      school_stage: 'k10_k12'
    })
    expect(wrapper.text()).toContain('普通高中信息技术课程标准（2025年版）')
    expect(wrapper.text()).toContain('普通高中（K10—K12）')
    expect(wrapper.text()).toContain('IT-HS-CC-01 · 信息意识')

    wrapper.unmount()
  })
})
