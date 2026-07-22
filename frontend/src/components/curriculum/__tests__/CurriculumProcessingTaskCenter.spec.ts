import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import AppSelect from '@/components/AppSelect.vue'
import type {
  CurriculumProcessingJob,
  CurriculumProcessingJobsIndex,
  CurriculumStandardVersion
} from '@/api/curriculumStandards'
import CurriculumProcessingTaskCenter from '../CurriculumProcessingTaskCenter.vue'

const { getJobs, createJob, cancelJob, retryJob } = vi.hoisted(() => ({
  getJobs: vi.fn(),
  createJob: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn()
}))

vi.mock('@/api/curriculumStandards', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/curriculumStandards')>()
  return {
    ...original,
    getCurriculumProcessingJobs: getJobs,
    createCurriculumProcessingJob: createJob,
    cancelCurriculumProcessingJob: cancelJob,
    retryCurriculumProcessingJob: retryJob
  }
})

let wrapper: VueWrapper | null = null

const statuses: CurriculumProcessingJobsIndex['statuses'] = [
  { value: 'queued', label: '等待中' },
  { value: 'running', label: '运行中' },
  { value: 'succeeded', label: '已成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelling', label: '取消中' },
  { value: 'cancelled', label: '已取消' }
]

function job(id: number, status: CurriculumProcessingJob['status']): CurriculumProcessingJob {
  return {
    id,
    version: id,
    version_label: '2022年版',
    standard: id,
    standard_title: `课程标准 ${id}`,
    subject_name: id === 1 ? '信息科技' : `学科 ${id}`,
    task_type: 'pdf_text_extraction',
    mode: 'ocr',
    priority: 'low',
    status,
    status_label: statuses.find((item) => item.value === status)?.label || status,
    stage: status === 'running' ? 'extracting' : status,
    stage_label: status === 'running' ? '逐页识别' : '等待后台处理',
    progress_current: status === 'running' ? 8 : status === 'succeeded' ? 74 : 0,
    progress_total: 74,
    progress_percent: status === 'running' ? 11 : status === 'succeeded' ? 100 : 0,
    resource_limit: { worker_concurrency: 1, cpu_cores: 2 },
    requested_by: 1,
    created_by_display: 'superadmin',
    celery_task_id: `task-${id}`,
    retry_of: null,
    retry_count: 0,
    can_retry: status === 'failed' || status === 'cancelled',
    can_cancel: status === 'queued' || status === 'running',
    error_code: status === 'failed' ? 'OCR_FAILED' : '',
    error_message: status === 'failed' ? '第 3 页识别失败。' : '',
    result_summary: {},
    created_at: '2026-07-22T08:00:00+08:00',
    started_at: status === 'queued' ? null : '2026-07-22T08:01:00+08:00',
    finished_at: status === 'succeeded' || status === 'failed' ? '2026-07-22T08:03:00+08:00' : null,
    updated_at: '2026-07-22T08:02:00+08:00'
  }
}

function index(jobs: CurriculumProcessingJob[]): CurriculumProcessingJobsIndex {
  const count = (status: CurriculumProcessingJob['status']) => jobs.filter((item) => item.status === status).length
  return {
    jobs,
    summary: {
      total: jobs.length,
      queued: count('queued'),
      running: count('running'),
      succeeded: count('succeeded'),
      failed: count('failed'),
      cancelling: count('cancelling'),
      cancelled: count('cancelled'),
      active: jobs.filter((item) => ['queued', 'running', 'cancelling'].includes(item.status)).length
    },
    statuses,
    modes: [
      { value: 'auto', label: '自动选择文本提取方式' },
      { value: 'ocr', label: '逐页 OCR 识别' }
    ],
    priorities: [
      { value: 'low', label: '低优先级（后台慢速）' },
      { value: 'normal', label: '普通优先级' },
      { value: 'high', label: '高优先级' }
    ]
  }
}

function selectedVersion(): CurriculumStandardVersion {
  return {
    id: 1,
    title: '义务教育信息科技课程标准（2022年版）',
    official_title: '义务教育信息科技课程标准（2022年版）',
    version_label: '2022年版',
    publication_year: 2022,
    effective_year: 2022,
    issued_by: '中华人民共和国教育部',
    source_url: 'https://example.edu/source',
    pdf_url: '/standard.pdf',
    pdf_page_count: 74,
    extraction_engine: '',
    extraction_engine_version: '',
    extraction_config: {},
    extracted_at: null,
    content_hash: 'hash',
    status: 'draft',
    status_label: '草稿',
    replaces_version: null
  }
}

function mountCenter(version: CurriculumStandardVersion | null = selectedVersion()) {
  wrapper = mount(CurriculumProcessingTaskCenter, {
    props: { selectedVersion: version },
    global: { components: { AppSelect } }
  })
  return wrapper
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.clearAllMocks()
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('curriculum processing task center', () => {
  it('keeps the default overview bounded while preserving textual status, progress and recovery actions', async () => {
    const rows = Array.from({ length: 16 }, (_, offset) => {
      if (offset === 0) return job(1, 'running')
      if (offset === 1) return job(2, 'failed')
      return job(offset + 1, 'queued')
    })
    getJobs.mockResolvedValue(index(rows))

    const view = mountCenter()
    await flushPromises()

    expect(view.findAll('.task-card')).toHaveLength(5)
    expect(view.text()).toContain('概览显示 5 项：4 个活动任务、1 条最近记录')
    expect(view.text()).toContain('运行中')
    expect(view.text()).toContain('失败')
    expect(view.text()).toContain('第 3 页识别失败。')
    expect(view.text()).toContain('重新排队')
    expect(view.text()).toContain('取消任务')
    expect(view.find('progress').attributes('aria-label')).toContain('处理进度')
    expect(view.findAll('.task-details')).toHaveLength(5)
    expect(view.find('.task-details').attributes()).not.toHaveProperty('open')

    await view.get('[data-task-scope="active"]').trigger('click')
    expect(view.findAll('.task-card')).toHaveLength(6)
    expect(view.text()).toContain('显示前 6 项，共 15 项')
    expect(view.text()).toContain('查看更多（还有 9 项）')

    await view.get('[data-action="show-more"]').trigger('click')
    expect(view.findAll('.task-card')).toHaveLength(12)
    expect(view.text()).toContain('收起到前 6 项')
  })

  it('shows only recent history by default and reveals older records in fixed-size batches', async () => {
    const rows = Array.from({ length: 16 }, (_, offset) => (
      job(offset + 1, offset % 4 === 0 ? 'failed' : 'succeeded')
    ))
    getJobs.mockResolvedValue(index(rows))

    const view = mountCenter()
    await flushPromises()

    expect(view.findAll('.task-card')).toHaveLength(2)
    expect(view.text()).toContain('0 个活动任务、2 条最近记录')
    expect(view.text()).toContain('查看全部历史记录（16）')

    await view.get('[data-task-scope="history"]').trigger('click')
    expect(view.findAll('.task-card')).toHaveLength(6)
    expect(view.text()).toContain('查看更多（还有 10 项）')
  })

  it('polls only while an active task exists and clears the pending timer on unmount', async () => {
    vi.useFakeTimers()
    getJobs
      .mockResolvedValueOnce(index([job(1, 'running')]))
      .mockResolvedValueOnce(index([job(1, 'succeeded')]))

    const view = mountCenter()
    await flushPromises()
    expect(getJobs).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()
    expect(getJobs).toHaveBeenCalledTimes(2)
    expect(view.text()).toContain('当前没有运行中的任务')

    await vi.advanceTimersByTimeAsync(10000)
    expect(getJobs).toHaveBeenCalledTimes(2)

    getJobs.mockResolvedValueOnce(index([job(2, 'queued')]))
    await view.get('.task-center-heading button').trigger('click')
    await flushPromises()
    expect(getJobs).toHaveBeenCalledTimes(3)

    view.unmount()
    wrapper = null
    await vi.advanceTimersByTimeAsync(10000)
    expect(getJobs).toHaveBeenCalledTimes(3)
  })

  it('creates one low-priority background task for the selected version and prevents active duplicates', async () => {
    const queued = job(1, 'queued')
    getJobs.mockResolvedValueOnce(index([])).mockResolvedValueOnce(index([queued]))
    createJob.mockResolvedValue(queued)

    const view = mountCenter()
    await flushPromises()
    await view.get('.task-create-form').trigger('submit')
    await flushPromises()

    expect(createJob).toHaveBeenCalledWith(1, { mode: 'auto', priority: 'low' })
    expect(view.text()).toContain('已加入后台处理队列')
    const submit = view.get<HTMLButtonElement>('.task-create-form > button')
    expect(submit.attributes()).toHaveProperty('disabled')
    expect(submit.text()).toContain('该版本已排队')
  })
})
