import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import AppSelect from '@/components/AppSelect.vue'
import type { CurriculumStandard, CurriculumStandardVersion } from '@/api/curriculumStandards'
import CurriculumStandardsView from '../CurriculumStandardsView.vue'

const { getStandards, getStandard, getVersion, setStandardActive } = vi.hoisted(() => ({
  getStandards: vi.fn(),
  getStandard: vi.fn(),
  getVersion: vi.fn(),
  setStandardActive: vi.fn()
}))

vi.mock('@/api/curriculumStandards', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/curriculumStandards')>()
  return {
    ...original,
    getCurriculumStandards: getStandards,
    getCurriculumStandard: getStandard,
    getCurriculumStandardVersion: getVersion,
    setCurriculumStandardActive: setStandardActive
  }
})

let wrapper: VueWrapper | null = null

function version(id = 1): CurriculumStandardVersion {
  return {
    id,
    standard: 1,
    title: '义务教育信息科技课程标准（2022年版）',
    official_title: '义务教育信息科技课程标准（2022年版）',
    version_label: '2022年版',
    publication_year: 2022,
    effective_year: 2022,
    issued_by: '中华人民共和国教育部',
    source_url: 'https://example.edu/source',
    pdf_url: '/standard.pdf',
    pdf_page_count: 74,
    structured_text: '信息科技课程标准正文。'.repeat(180),
    structured_markdown_url: '/standard.md',
    structured_json_url: '/standard.json',
    structured_jsonl_url: '/standard.jsonl',
    extraction_status: 'completed',
    extraction_status_label: '处理完成',
    extraction_message: '逐页文本处理完成。',
    extraction_engine: 'test',
    extraction_engine_version: '1',
    extraction_config: {},
    extracted_at: '2026-07-22T08:00:00+08:00',
    content_hash: 'content-hash',
    pdf_sha256: 'pdf-hash',
    status: 'draft',
    status_label: '草稿',
    replaces_version: null,
    page_count: 74,
    unreviewed_page_count: 0,
    page_quality_counts: { complete: 74, failed: 0, low_confidence: 0 },
    nodes: Array.from({ length: 18 }, (_, index) => ({
      id: index + 1,
      node_type: 'core_competency' as const,
      code: `CS-${index + 1}`,
      title: `核心素养条目 ${index + 1}`,
      content: `条目原文 ${index + 1}`,
      parent: null,
      source_page_start: index + 1,
      source_page_end: index + 1,
      sort_order: index + 1
    }))
  }
}

function standard(id: number): CurriculumStandard {
  const currentVersion = version(id)
  return {
    id,
    title: `课程标准 ${String(id).padStart(2, '0')}`,
    document_type: 'subject_standard',
    school_stage: id % 2 ? 'k1_k9' : 'k10_k12',
    subject_code: `SUB-${id}`,
    subject_name: id === 1 ? '信息科技' : `学科 ${id}`,
    current_version: currentVersion,
    versions: [currentVersion],
    is_active: true,
    audit_logs: [{
      id: 1,
      version: null,
      action: 'standard_created',
      actor: 'superadmin',
      detail: { subject_code: `SUB-${id}` },
      created_at: '2026-07-22T08:00:00+08:00'
    }],
    created_at: '2026-07-22T08:00:00+08:00',
    updated_at: '2026-07-22T08:00:00+08:00'
  }
}

function mountView() {
  const ConfirmDialogStub = defineComponent({
    name: 'CurriculumConfirmDialog',
    props: {
      open: Boolean,
      title: String,
      loading: Boolean
    },
    emits: ['close', 'confirm'],
    template: `
      <section v-if="open" data-test="confirm-dialog">
        <strong>{{ title }}</strong>
        <button type="button" :disabled="loading" @click="$emit('confirm')">确认</button>
      </section>
    `
  })

  wrapper = mount(CurriculumStandardsView, {
    global: {
      components: { AppSelect },
      stubs: {
        AppShell: { template: '<main><slot /></main>' },
        NoticeLine: true,
        CurriculumConfirmDialog: ConfirmDialogStub,
        CurriculumNodeEditorModal: true,
        CurriculumPageReviewModal: true,
        CurriculumReviewModal: true,
        CurriculumStandardEditorModal: true,
        CurriculumVersionEditorModal: true,
        CurriculumVersionCompareModal: true,
        CurriculumProcessingTaskCenter: { template: '<div data-test="task-center">任务中心</div>' }
      }
    }
  })
  return wrapper
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('curriculum standards management layout', () => {
  it('passes the selected school stage into the catalogue query', async () => {
    getStandards.mockResolvedValue({ standards: [] })

    const view = mountView()
    await flushPromises()

    const stageSelect = view.findAllComponents(AppSelect)[0]
    stageSelect.vm.$emit('update:modelValue', 'k10_k12')
    await view.get('.curriculum-toolbar').trigger('submit')
    await flushPromises()

    expect(getStandards).toHaveBeenLastCalledWith(expect.objectContaining({
      school_stage: 'k10_k12'
    }))
  })

  it('bounds the catalogue and keeps task management in a separate top-level tab', async () => {
    const standards = Array.from({ length: 18 }, (_, index) => standard(index + 1))
    getStandards.mockResolvedValue({ standards })

    const view = mountView()
    await flushPromises()

    expect(view.findAll('.curriculum-list > button')).toHaveLength(8)
    expect(view.text()).toContain('第 1—8 项，共 18 项')
    expect(view.find('#curriculum-standards-tab').attributes('aria-selected')).toBe('true')
    expect(view.find('#curriculum-tasks-panel').exists()).toBe(false)

    const paginationButtons = view.findAll('.curriculum-list-pagination button')
    await paginationButtons[1]?.trigger('click')
    expect(view.text()).toContain('第 9—16 项，共 18 项')
    expect(view.findAll('.curriculum-list > button')).toHaveLength(8)

    await view.get('#curriculum-standards-tab').trigger('keydown', { key: 'ArrowRight' })
    expect(view.find('[data-test="task-center"]').exists()).toBe(true)
    expect(view.find('#curriculum-standards-panel').exists()).toBe(false)
    expect(view.get('#curriculum-tasks-tab').attributes('tabindex')).toBe('0')
  })

  it('paginates content nodes and limits structured text to a short preview', async () => {
    const selected = standard(1)
    const selectedVersion = version(1)
    getStandards.mockResolvedValue({ standards: [selected] })
    getStandard.mockResolvedValue(selected)
    getVersion.mockResolvedValue(selectedVersion)

    const view = mountView()
    await flushPromises()
    await view.get('.curriculum-list > button').trigger('click')
    await flushPromises()

    expect(view.findAll('.curriculum-node-card')).toHaveLength(8)
    expect(view.text()).toContain('第 1 / 3 页')
    expect(view.findAll('.curriculum-node-type-tabs [role="tab"]')).toHaveLength(4)

    await view.get('#curriculum-detail-tab-text').trigger('click')
    const preview = view.get('.curriculum-text-area pre').text()
    expect(preview).toContain('当前为摘要预览')
    expect(preview.length).toBeLessThan(selectedVersion.structured_text!.length)
    expect(view.text()).toContain('当前仅显示前 1,200 个字符')
    expect(view.find('.curriculum-text-toggle').exists()).toBe(false)
    expect(view.get('a[href="/standard.json"]').text()).toBe('下载 JSON')
  })

  it('shows the audit timeline and disables a standard only after confirmation', async () => {
    let selected = standard(1)
    const statusUpdate = { finish: () => undefined }
    getStandards.mockImplementation(async () => ({ standards: [selected] }))
    getStandard.mockImplementation(async () => selected)
    getVersion.mockResolvedValue(version(1))
    setStandardActive.mockImplementation((_id: number, isActive: boolean) => new Promise<CurriculumStandard>((resolve) => {
      statusUpdate.finish = () => {
        selected = {
          ...selected,
          is_active: isActive,
          audit_logs: [
            {
              id: 2,
              version: null,
              action: 'standard_updated',
              actor: 'superadmin',
              detail: { before: { is_active: true }, after: { is_active: isActive } },
              created_at: '2026-07-22T09:00:00+08:00'
            },
            ...(selected.audit_logs || [])
          ]
        }
        resolve(selected)
      }
    }))

    const view = mountView()
    await flushPromises()
    await view.get('.curriculum-list > button').trigger('click')
    await flushPromises()

    await view.get('#curriculum-detail-tab-audit').trigger('click')
    expect(view.text()).toContain('创建课程标准主档')
    expect(view.text()).toContain('操作人：superadmin')
    expect(view.text()).toContain('课程标准主档')

    const disableButton = view.findAll('button').find((button) => button.text() === '停用主档')
    expect(disableButton).toBeDefined()
    await disableButton!.trigger('click')
    expect(view.get('[data-test="confirm-dialog"]').text()).toContain('停用课程标准主档')

    await view.get('[data-test="confirm-dialog"] button').trigger('click')
    expect(view.get('[data-test="confirm-dialog"] button').attributes()).toHaveProperty('disabled')
    statusUpdate.finish()
    await flushPromises()

    expect(setStandardActive).toHaveBeenCalledWith(1, false)
    expect(view.text()).toContain('已停用')
    expect(view.findAll('button').some((button) => button.text() === '启用主档')).toBe(true)
  })
})
