<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  getCurriculumNodeReference,
  type CurriculumNodeTrace,
  type CurriculumNodeType,
  type CurriculumSchoolStage
} from '@/api/curriculumStandards'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{
  nodeId: number
}>()

const emit = defineEmits<{
  close: []
}>()

const loading = ref(false)
const errorMessage = ref('')
const trace = ref<CurriculumNodeTrace | null>(null)

const sourcePages = computed(() => [...(trace.value?.source_pages || [])].sort((left, right) => (
  left.page_number - right.page_number
)))

const pdfPageUrl = computed(() => {
  return pdfUrlForPage(trace.value?.source_page_start)
})

function pdfUrlForPage(pageNumber?: number) {
  const pdfUrl = trace.value?.curriculum_version.pdf_url || ''
  if (!pdfUrl) return ''
  const baseUrl = pdfUrl.split('#')[0]
  return pageNumber
    ? `${baseUrl}#page=${pageNumber}`
    : baseUrl
}

function nodeTypeLabel(value: CurriculumNodeType) {
  return {
    core_competency: '核心素养',
    course_objective: '课程目标',
    course_content: '课程内容',
    academic_quality: '学业质量'
  }[value]
}

function stageLabel(value: CurriculumSchoolStage) {
  return value === 'k1_k9' ? '义务教育（K1—K9）' : '普通高中（K10—K12）'
}

function pageLabel(item: CurriculumNodeTrace) {
  if (!item.source_page_start) return '原文页码未标注'
  if (!item.source_page_end || item.source_page_end === item.source_page_start) {
    return `第 ${item.source_page_start} 页`
  }
  return `第 ${item.source_page_start}—${item.source_page_end} 页`
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    trace.value = await getCurriculumNodeReference(props.nodeId)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '课程标准原文追溯信息加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop curriculum-trace-backdrop" @click.self="emit('close')">
      <section
        v-curriculum-modal-focus="() => emit('close')"
        class="entity-modal curriculum-trace-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="curriculum-trace-title"
      >
        <header class="modal-header">
          <div>
            <h2 id="curriculum-trace-title">课程标准依据追溯</h2>
            <p>分别核对结构化内容条目、PDF 逐页原文及其课程标准版本。</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
        </header>

        <div class="curriculum-trace-body" :aria-busy="loading">
          <div v-if="loading" class="curriculum-trace-state" role="status">正在加载课程标准原文</div>
          <div v-else-if="errorMessage" class="curriculum-trace-state is-error" role="alert">
            <p>{{ errorMessage }}</p>
            <button class="secondary-button" type="button" @click="load">重新加载</button>
          </div>
          <template v-else-if="trace">
            <section class="curriculum-trace-summary" aria-label="课程标准版本信息">
              <span>{{ nodeTypeLabel(trace.node_type) }}</span>
              <h3>{{ trace.code }} · {{ trace.title }}</h3>
              <p>{{ trace.curriculum_standard.title }}</p>
              <dl>
                <div><dt>学科</dt><dd>{{ trace.curriculum_standard.subject_name }}</dd></div>
                <div><dt>学段</dt><dd>{{ trace.curriculum_standard.school_stage_label || stageLabel(trace.curriculum_standard.school_stage) }}</dd></div>
                <div><dt>版本</dt><dd>{{ trace.curriculum_version.version_label }}</dd></div>
                <div><dt>原文位置</dt><dd>{{ pageLabel(trace) }}</dd></div>
              </dl>
            </section>

            <section class="curriculum-trace-item" aria-labelledby="curriculum-trace-item-title">
              <header>
                <div>
                  <strong id="curriculum-trace-item-title">结构化内容条目</strong>
                  <small>供评价设计引用的结构化条目，不等同于 PDF 整页原文。</small>
                  <small v-if="trace.source_paragraph">段落标识：{{ trace.source_paragraph }}</small>
                </div>
                <span>{{ pageLabel(trace) }}</span>
              </header>
              <p>{{ trace.content }}</p>
              <footer>
                <span>内容条目校验值</span>
                <code>{{ trace.content_hash || '未提供' }}</code>
              </footer>
            </section>

            <section class="curriculum-trace-pages" aria-labelledby="curriculum-trace-pages-title">
              <header>
                <div>
                  <strong id="curriculum-trace-pages-title">PDF 逐页原文</strong>
                  <small>以下为该课程标准版本保存的逐页提取或 OCR 文本，PDF 文件是最终核验依据。</small>
                </div>
                <span>{{ sourcePages.length }} 页</span>
              </header>
              <div v-if="sourcePages.length" class="curriculum-trace-page-list">
                <article
                  v-for="page in sourcePages"
                  :key="page.id"
                  class="curriculum-trace-page"
                  :aria-labelledby="`curriculum-trace-page-${page.id}`"
                >
                  <header>
                    <div>
                      <strong :id="`curriculum-trace-page-${page.id}`">PDF 第 {{ page.page_number }} 页</strong>
                      <small>
                        {{ page.extraction_method_label }} · {{ page.quality_status_label }} · {{ page.review_status_label }}
                      </small>
                    </div>
                    <a
                      v-if="pdfUrlForPage(page.page_number)"
                      class="curriculum-trace-page-link"
                      :href="pdfUrlForPage(page.page_number)"
                      target="_blank"
                      rel="noopener"
                    >打开该页</a>
                  </header>
                  <pre>{{ page.text || '本页暂无可读取文本，请直接核验 PDF 原文件。' }}</pre>
                  <footer>
                    <span>{{ page.char_count.toLocaleString('zh-CN') }} 字符</span>
                    <span>逐页文本校验值</span>
                    <code>{{ page.content_hash || '未提供' }}</code>
                  </footer>
                </article>
              </div>
              <p v-else class="curriculum-trace-pages-empty">
                引用页范围内尚无逐页文本记录，请直接打开 PDF 原文件核验。
              </p>
            </section>

            <details class="curriculum-trace-verification">
              <summary>查看版本级校验信息</summary>
              <dl>
                <div><dt>课程标准版本校验值</dt><dd>{{ trace.curriculum_version.content_hash || '未提供' }}</dd></div>
                <div><dt>PDF 校验值</dt><dd>{{ trace.curriculum_version.pdf_sha256 || '未提供' }}</dd></div>
              </dl>
            </details>
          </template>
        </div>

        <footer class="modal-actions curriculum-trace-actions">
          <a
            v-if="trace?.curriculum_version.source_url"
            class="secondary-button"
            :href="trace.curriculum_version.source_url"
            target="_blank"
            rel="noopener"
          >查看权威来源</a>
          <a
            v-if="pdfPageUrl"
            class="primary-button"
            :href="pdfPageUrl"
            target="_blank"
            rel="noopener"
          >{{ trace?.source_page_start ? `打开 PDF 第 ${trace.source_page_start} 页` : '打开 PDF 原文' }}</a>
          <button class="secondary-button" type="button" @click="emit('close')">关闭</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.curriculum-trace-backdrop {
  z-index: 1450;
}

.curriculum-trace-modal {
  width: min(760px, 100%);
  max-height: min(780px, calc(100dvh - 32px));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.curriculum-trace-modal .modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-trace-body {
  min-height: 240px;
  overflow: auto;
  padding: 18px 20px;
  background: #f8fafc;
}

.curriculum-trace-state {
  min-height: 210px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 12px;
  color: var(--muted);
  text-align: center;
}

.curriculum-trace-state p {
  margin: 0;
}

.curriculum-trace-state.is-error {
  color: #b42318;
}

.curriculum-trace-summary,
.curriculum-trace-item,
.curriculum-trace-pages,
.curriculum-trace-verification {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}

.curriculum-trace-summary {
  padding: 16px;
}

.curriculum-trace-summary > span {
  display: inline-flex;
  border-radius: 999px;
  padding: 3px 8px;
  background: #e8f1ff;
  color: var(--primary-dark);
  font-size: 12px;
  font-weight: 700;
}

.curriculum-trace-summary h3 {
  margin: 10px 0 4px;
  font-size: 18px;
  line-height: 1.45;
}

.curriculum-trace-summary > p {
  margin: 0;
  color: var(--muted);
}

.curriculum-trace-summary dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
  margin: 14px 0 0;
}

.curriculum-trace-summary dl > div {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 8px;
}

.curriculum-trace-summary dt,
.curriculum-trace-summary dd {
  margin: 0;
}

.curriculum-trace-summary dt {
  color: var(--muted);
}

.curriculum-trace-item,
.curriculum-trace-pages {
  margin-top: 12px;
  overflow: hidden;
}

.curriculum-trace-item > header,
.curriculum-trace-pages > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--line);
  padding: 11px 14px;
  background: #fbfdff;
}

.curriculum-trace-item > header > div,
.curriculum-trace-pages > header > div {
  display: grid;
  gap: 2px;
}

.curriculum-trace-item small,
.curriculum-trace-item > header > span,
.curriculum-trace-pages small,
.curriculum-trace-pages > header > span {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-trace-item > p {
  margin: 0;
  padding: 16px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.curriculum-trace-item > footer {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  border-top: 1px solid var(--line);
  padding: 9px 14px;
  background: #fbfdff;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-trace-item code,
.curriculum-trace-page code {
  min-width: 0;
  color: #475569;
  overflow-wrap: anywhere;
}

.curriculum-trace-page-list {
  display: grid;
  gap: 10px;
  padding: 12px;
  background: #f8fafc;
}

.curriculum-trace-page {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: #fff;
}

.curriculum-trace-page > header {
  min-height: 54px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 12px;
}

.curriculum-trace-page > header > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.curriculum-trace-page-link {
  flex: 0 0 auto;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  color: var(--primary-dark);
  font-size: 12px;
  font-weight: 700;
}

.curriculum-trace-page pre {
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 14px;
  background: #fff;
  color: var(--text);
  font: inherit;
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.curriculum-trace-page > footer {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: 8px 12px;
  border-top: 1px solid var(--line);
  padding: 9px 12px;
  background: #fbfdff;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-trace-pages-empty {
  margin: 0;
  padding: 20px;
  color: #9a3412;
  text-align: center;
}

.curriculum-trace-verification {
  margin-top: 12px;
  padding: 0 14px;
}

.curriculum-trace-verification summary {
  min-height: 44px;
  display: flex;
  align-items: center;
  color: var(--primary-dark);
  cursor: pointer;
  font-weight: 600;
}

.curriculum-trace-verification dl {
  display: grid;
  gap: 8px;
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 12px 0 14px;
}

.curriculum-trace-verification dl > div {
  display: grid;
  grid-template-columns: 145px minmax(0, 1fr);
  gap: 10px;
}

.curriculum-trace-verification dt,
.curriculum-trace-verification dd {
  margin: 0;
}

.curriculum-trace-verification dt {
  color: var(--muted);
}

.curriculum-trace-verification dd {
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}

.curriculum-trace-actions {
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .curriculum-trace-backdrop {
    padding: 0;
  }

  .curriculum-trace-modal {
    width: 100%;
    max-height: 100dvh;
    border-radius: 0;
  }

  .curriculum-trace-summary dl {
    grid-template-columns: 1fr;
  }

  .curriculum-trace-item > header,
  .curriculum-trace-pages > header,
  .curriculum-trace-page > header {
    align-items: flex-start;
    flex-direction: column;
  }

  .curriculum-trace-item > footer,
  .curriculum-trace-page > footer {
    grid-template-columns: 1fr;
    gap: 3px;
  }

  .curriculum-trace-verification dl > div {
    grid-template-columns: 1fr;
    gap: 3px;
  }

  .curriculum-trace-actions > * {
    flex: 1 1 auto;
    justify-content: center;
  }
}
</style>
