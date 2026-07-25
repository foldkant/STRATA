import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import type { CurriculumNodeTrace } from '@/api/curriculumStandards'
import CurriculumReferenceTraceModal from '../CurriculumReferenceTraceModal.vue'

const { getNodeReference } = vi.hoisted(() => ({
  getNodeReference: vi.fn()
}))

vi.mock('@/api/curriculumStandards', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/curriculumStandards')>()
  return {
    ...original,
    getCurriculumNodeReference: getNodeReference
  }
})

let wrapper: VueWrapper | null = null

function traceNode(): CurriculumNodeTrace {
  return {
    id: 37,
    node_type: 'core_competency',
    code: 'IT-K9-01',
    title: '信息意识',
    content: '能够根据解决问题的需要，自觉、主动地寻求恰当方式获取与处理信息。',
    parent: null,
    source_page_start: 12,
    source_page_end: 14,
    source_paragraph: '第二部分 课程目标',
    sort_order: 1,
    content_hash: 'node-content-hash',
    source_pages: [
      {
        id: 114,
        page_number: 14,
        text: 'PDF 第十四页真实文本：学业质量相关说明。',
        char_count: 22,
        extraction_method: 'ocr',
        extraction_method_label: 'OCR 识别',
        mean_confidence: 0.97,
        quality_status: 'complete',
        quality_status_label: '完整',
        quality_message: '',
        review_status: 'reviewed',
        review_status_label: '已复核',
        reviewed_by: 'superadmin',
        reviewed_at: '2026-07-22T08:00:00+08:00',
        content_hash: 'page-14-content-hash'
      },
      {
        id: 112,
        page_number: 12,
        text: 'PDF 第十二页真实文本：课程目标原始页内容。',
        char_count: 23,
        extraction_method: 'embedded_text',
        extraction_method_label: '内嵌文本',
        mean_confidence: null,
        quality_status: 'complete',
        quality_status_label: '完整',
        quality_message: '',
        review_status: 'reviewed',
        review_status_label: '已复核',
        reviewed_by: 'superadmin',
        reviewed_at: '2026-07-22T08:00:00+08:00',
        content_hash: 'page-12-content-hash'
      },
      {
        id: 113,
        page_number: 13,
        text: 'PDF 第十三页真实文本：核心素养展开说明。',
        char_count: 22,
        extraction_method: 'embedded_text',
        extraction_method_label: '内嵌文本',
        mean_confidence: null,
        quality_status: 'complete',
        quality_status_label: '完整',
        quality_message: '',
        review_status: 'reviewed',
        review_status_label: '已复核',
        reviewed_by: 'superadmin',
        reviewed_at: '2026-07-22T08:00:00+08:00',
        content_hash: 'page-13-content-hash'
      }
    ],
    curriculum_standard: {
      id: 4,
      title: '义务教育信息科技课程标准（2022年版）',
      record_title: '义务教育信息科技课程标准',
      document_type: 'subject_standard',
      school_stage: 'k1_k9',
      school_stage_label: '义务教育（K1—K9）',
      subject_code: 'IT',
      subject_name: '信息科技'
    },
    curriculum_version: {
      id: 8,
      version_label: '2022年版',
      publication_year: 2022,
      issued_by: '中华人民共和国教育部',
      source_url: 'https://www.moe.gov.cn/example.html',
      status: 'published',
      status_label: '当前使用',
      content_hash: 'version-content-hash',
      pdf_sha256: 'pdf-sha256',
      pdf_size_bytes: 4096,
      pdf_url: '/api/v1/curriculum-standard-versions/8/pdf/'
    }
  }
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('CurriculumReferenceTraceModal', () => {
  it('loads the authoritative trace and links directly to the cited PDF page', async () => {
    getNodeReference.mockResolvedValue(traceNode())

    wrapper = mount(CurriculumReferenceTraceModal, {
      props: { nodeId: 37 },
      attachTo: document.body,
      global: {
        stubs: { Teleport: true }
      }
    })
    await flushPromises()

    expect(getNodeReference).toHaveBeenCalledWith(37)
    expect(wrapper.text()).toContain('义务教育信息科技课程标准（2022年版）')
    expect(wrapper.text()).toContain('2022年版')
    expect(wrapper.text()).toContain('第 12—14 页')
    expect(wrapper.text()).toContain('能够根据解决问题的需要')

    const pdfLink = wrapper.get<HTMLAnchorElement>('a.primary-button')
    expect(pdfLink.attributes('href')).toBe('/api/v1/curriculum-standard-versions/8/pdf/#page=12')
    expect(pdfLink.text()).toContain('打开 PDF 第 12 页')

    const sourceLink = wrapper.get<HTMLAnchorElement>('a.secondary-button')
    expect(sourceLink.attributes('href')).toBe('https://www.moe.gov.cn/example.html')
  })

  it('renders the structured item separately from real source_pages text and checksums', async () => {
    getNodeReference.mockResolvedValue(traceNode())

    wrapper = mount(CurriculumReferenceTraceModal, {
      props: { nodeId: 37 },
      global: {
        stubs: { Teleport: true }
      }
    })
    await flushPromises()

    const item = wrapper.get('.curriculum-trace-item')
    expect(item.text()).toContain('评价所引用的内容条目')
    expect(item.text()).toContain('请结合 PDF 原文核对')
    expect(item.text()).toContain('能够根据解决问题的需要')
    expect(item.text()).toContain('node-content-hash')
    expect(item.text()).not.toContain('PDF 第十二页真实文本')

    const pages = wrapper.findAll('.curriculum-trace-page')
    expect(pages).toHaveLength(3)
    expect(pages.map((page) => page.get('strong').text())).toEqual([
      'PDF 第 12 页',
      'PDF 第 13 页',
      'PDF 第 14 页'
    ])
    expect(pages[0].text()).toContain('PDF 第十二页真实文本')
    expect(pages[0].text()).toContain('page-12-content-hash')
    expect(pages[1].text()).toContain('PDF 第十三页真实文本')
    expect(pages[2].text()).toContain('page-14-content-hash')

    const pageLinks = wrapper.findAll<HTMLAnchorElement>('.curriculum-trace-page-link')
    expect(pageLinks.map((link) => link.attributes('href'))).toEqual([
      '/api/v1/curriculum-standard-versions/8/pdf/#page=12',
      '/api/v1/curriculum-standard-versions/8/pdf/#page=13',
      '/api/v1/curriculum-standard-versions/8/pdf/#page=14'
    ])
  })
})
