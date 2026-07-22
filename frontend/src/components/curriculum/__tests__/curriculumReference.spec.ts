import { describe, expect, it } from 'vitest'
import type { CurriculumNode, CurriculumReferenceStandard } from '@/api/curriculumStandards'
import { buildCurriculumReferenceNode } from '../curriculumReference'

describe('curriculum reference metadata', () => {
  it('keeps the content item hash and records the curriculum version hash separately', () => {
    const node = {
      id: 7,
      node_type: 'course_content',
      code: 'CC-1',
      title: '信息意识内容要求',
      content: '课程标准原文',
      parent: null,
      source_page_start: 12,
      source_page_end: 12,
      sort_order: 0,
      content_hash: 'node-content-hash'
    } satisfies CurriculumNode
    const standard = {
      id: 2,
      title: '信息科技课程标准主档',
      document_type: 'subject_standard',
      school_stage: 'k1_k9',
      subject_code: 'information_technology',
      subject_name: '信息科技',
      current_version: {
        id: 9,
        title: '义务教育信息科技课程标准（2022年版）',
        version_label: '2022年版',
        publication_year: 2022,
        effective_year: 2022,
        issued_by: '中华人民共和国教育部',
        source_url: 'https://example.edu/source',
        pdf_url: 'https://example.edu/standard.pdf',
        structured_text: '',
        content_hash: 'curriculum-version-hash',
        status: 'published',
        status_label: '已发布',
        replaces_version: null,
        nodes: [node]
      }
    } as CurriculumReferenceStandard

    const result = buildCurriculumReferenceNode(node, standard)

    expect(result.content_hash).toBe('node-content-hash')
    expect(result.curriculum_version_hash).toBe('curriculum-version-hash')
    expect(result.standard_title).toBe('义务教育信息科技课程标准（2022年版）')
    expect(node).not.toHaveProperty('curriculum_version_hash')
  })
})
