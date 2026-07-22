import type { CurriculumNode, CurriculumReferenceStandard } from '@/api/curriculumStandards'

export function buildCurriculumReferenceNode(
  node: CurriculumNode,
  standard: CurriculumReferenceStandard
): CurriculumNode {
  return {
    ...node,
    version_id: standard.current_version.id,
    version_label: standard.current_version.version_label,
    standard_id: standard.id,
    standard_title: standard.current_version.title,
    subject_code: standard.subject_code,
    subject_name: standard.subject_name,
    school_stage: standard.school_stage,
    source_url: standard.current_version.source_url,
    pdf_url: standard.current_version.pdf_url,
    curriculum_version_hash: standard.current_version.content_hash
  }
}
