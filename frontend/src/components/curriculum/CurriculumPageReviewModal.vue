<script setup lang="ts">
import { IconChecklist, IconEdit, IconLockCheck } from '@tabler/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  getCurriculumStandardPages,
  reviewCurriculumStandardPages,
  saveCurriculumStandardPage,
  type CurriculumPageQualityStatus,
  type CurriculumPageReviewStatus,
  type CurriculumStandardPage,
  type CurriculumStandardVersion
} from '@/api/curriculumStandards'
import CurriculumConfirmDialog from './CurriculumConfirmDialog.vue'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{ version: CurriculumStandardVersion }>()

const emit = defineEmits<{
  close: []
  changed: []
  reviewed: [version: CurriculumStandardVersion]
}>()

const pages = ref<CurriculumStandardPage[]>([])
const query = ref('')
const qualityStatus = ref<CurriculumPageQualityStatus | ''>('')
const reviewStatus = ref<CurriculumPageReviewStatus | ''>('')
const selectedIds = ref<number[]>([])
const editingPage = ref<CurriculumStandardPage | null>(null)
const editedText = ref('')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const confirmAll = ref(false)

const metrics = computed(() => ({
  total: props.version.page_count ?? pages.value.length,
  reviewed: Math.max((props.version.page_count || pages.value.length) - (props.version.unreviewed_page_count || 0), 0),
  needsReview: props.version.unreviewed_page_count || 0,
  attention: (props.version.page_quality_counts?.empty || 0)
    + (props.version.page_quality_counts?.low_confidence || 0)
    + (props.version.page_quality_counts?.failed || 0)
}))
const selectablePages = computed(() => pages.value.filter((page) => page.review_status !== 'reviewed' && page.quality_status !== 'failed'))

function qualityClass(page: CurriculumStandardPage) {
  return `quality-${page.quality_status}`
}

function confidenceLabel(page: CurriculumStandardPage) {
  if (page.mean_confidence === null) return ''
  return `平均置信度 ${(page.mean_confidence * 100).toFixed(1)}%`
}

function togglePage(id: number, checked: boolean) {
  selectedIds.value = checked
    ? Array.from(new Set([...selectedIds.value, id]))
    : selectedIds.value.filter((item) => item !== id)
}

function toggleVisible(checked: boolean) {
  const visible = selectablePages.value.map((page) => page.id)
  selectedIds.value = checked
    ? Array.from(new Set([...selectedIds.value, ...visible]))
    : selectedIds.value.filter((id) => !visible.includes(id))
}

async function load() {
  loading.value = true
  notice.value = ''
  try {
    const result = await getCurriculumStandardPages(props.version.id, {
      q: query.value.trim(),
      quality_status: qualityStatus.value,
      review_status: reviewStatus.value
    })
    pages.value = result.pages
    const available = new Set(result.pages.map((page) => page.id))
    selectedIds.value = selectedIds.value.filter((id) => available.has(id))
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '逐页文本加载失败。'
  } finally {
    loading.value = false
  }
}

function openEdit(page: CurriculumStandardPage) {
  editingPage.value = page
  editedText.value = page.text
  notice.value = ''
}

async function savePage() {
  if (!editingPage.value) return
  saving.value = true
  notice.value = ''
  try {
    const row = await saveCurriculumStandardPage(editingPage.value.id, editedText.value)
    const index = pages.value.findIndex((page) => page.id === row.id)
    if (index >= 0) pages.value[index] = row
    editingPage.value = null
    emit('changed')
    notice.value = `第 ${row.page_number} 页文本已保存，请重新核对。`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '逐页文本保存失败。'
  } finally {
    saving.value = false
  }
}

async function confirmPages(all: boolean) {
  if (!all && !selectedIds.value.length) {
    notice.value = '请先选择已经核对的页面。'
    return
  }
  saving.value = true
  notice.value = ''
  try {
    const result = await reviewCurriculumStandardPages(props.version.id, all ? undefined : selectedIds.value)
    selectedIds.value = []
    confirmAll.value = false
    emit('reviewed', result.version)
    await load()
    notice.value = `已确认 ${result.reviewed_page_count} 页文本。`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '逐页文本复核结果保存失败。'
    confirmAll.value = false
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="modal-backdrop curriculum-page-backdrop" @click.self="emit('close')">
    <section v-curriculum-modal-focus="() => emit('close')" class="entity-modal curriculum-page-modal" role="dialog" aria-modal="true" aria-labelledby="curriculum-page-title">
      <header class="modal-header">
        <div>
          <h2 id="curriculum-page-title">逐页原文核对</h2>
          <p>{{ version.title }} · {{ version.version_label }} · 共 {{ metrics.total }} 页</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
      </header>

      <div class="curriculum-page-body">
        <p v-if="notice" class="curriculum-page-notice" role="status">{{ notice }}</p>

        <section class="curriculum-page-summary" aria-label="逐页文本处理概况">
          <article><span>总页数</span><strong>{{ metrics.total }}</strong></article>
          <article><span>已复核</span><strong>{{ metrics.reviewed }}</strong></article>
          <article><span>待复核</span><strong>{{ metrics.needsReview }}</strong></article>
          <article :class="{ attention: metrics.attention }"><span>需关注</span><strong>{{ metrics.attention }}</strong></article>
        </section>

        <aside v-if="version.status === 'draft'" class="curriculum-page-guidance draft">
          <IconEdit aria-hidden="true" />
          <div>
            <strong>当前为草稿版本</strong>
            <p>请逐页对照 PDF 原文核对文字和页码。若已依据该页建立课程标准内容条目，请先核对条目与原文的一致性，再修订页级文本。</p>
          </div>
        </aside>
        <aside v-else-if="version.status === 'review_pending'" class="curriculum-page-guidance review">
          <IconChecklist aria-hidden="true" />
          <div>
            <strong>当前版本正在复核</strong>
            <p>请逐页对照 PDF 原文核对文字、页码和处理提示。处理失败页不能确认，应退回草稿修订；全部页面确认后方可登记版本复核结果。</p>
          </div>
        </aside>
        <aside v-else class="curriculum-page-guidance">
          <IconLockCheck aria-hidden="true" />
          <div>
            <strong>当前版本已发布</strong>
            <p>原文与逐页核对记录保持不变。您可以查看各页复核情况；如需调整，请新增版本并重新完成核对与复核。</p>
          </div>
        </aside>

        <form class="curriculum-page-toolbar" @submit.prevent="load">
          <label><span>检索原文</span><input v-model="query" placeholder="输入页内文字" /></label>
          <label>
            <span>处理质量</span>
            <AppSelect v-model="qualityStatus">
              <option value="">全部</option>
              <option value="complete">文本完整</option>
              <option value="empty">未识别到文字</option>
              <option value="low_confidence">识别置信度较低</option>
              <option value="failed">处理失败</option>
            </AppSelect>
          </label>
          <label>
            <span>复核状态</span>
            <AppSelect v-model="reviewStatus">
              <option value="">全部</option>
              <option value="needs_review">待复核</option>
              <option value="reviewed">已复核</option>
            </AppSelect>
          </label>
          <button class="secondary-button" type="submit" :disabled="loading">筛选</button>
        </form>

        <div v-if="version.status === 'review_pending' && pages.length" class="curriculum-page-select-all">
          <label>
            <input
              type="checkbox"
              :checked="selectablePages.length > 0 && selectablePages.every((page) => selectedIds.includes(page.id))"
              @change="toggleVisible(($event.target as HTMLInputElement).checked)"
            />
            选择当前结果中可确认的待复核页
          </label>
          <span>已选 {{ selectedIds.length }} 页</span>
        </div>

        <div class="curriculum-page-list" :aria-busy="loading">
          <p v-if="loading" class="curriculum-page-empty">正在加载逐页文本</p>
          <p v-else-if="!pages.length" class="curriculum-page-empty">没有符合筛选条件的页面</p>
          <article v-for="page in pages" v-else :key="page.id" :class="[qualityClass(page), { selected: selectedIds.includes(page.id) }]">
            <header>
              <label v-if="version.status === 'review_pending' && page.review_status !== 'reviewed' && page.quality_status !== 'failed'">
                <input type="checkbox" :checked="selectedIds.includes(page.id)" @change="togglePage(page.id, ($event.target as HTMLInputElement).checked)" />
                <span class="sr-only">选择第 {{ page.page_number }} 页</span>
              </label>
              <div>
                <strong>第 {{ page.page_number }} 页</strong>
                <span>{{ page.extraction_method_label }}<template v-if="confidenceLabel(page)"> · {{ confidenceLabel(page) }}</template></span>
              </div>
              <div class="curriculum-page-statuses">
                <em :class="qualityClass(page)">{{ page.quality_status_label }}</em>
                <em :class="`review-${page.review_status}`">{{ page.review_status_label }}</em>
              </div>
              <button v-if="version.status === 'draft'" type="button" @click="openEdit(page)">修订文本</button>
            </header>
            <p v-if="page.quality_message" class="curriculum-page-quality-message">{{ page.quality_message }}</p>
            <pre>{{ page.text || '本页未识别到文字。请对照 PDF 原文核对。' }}</pre>
            <footer>
              <span>{{ page.char_count.toLocaleString('zh-CN') }} 字符 · 文本校验信息 {{ page.content_hash.slice(0, 12) }}</span>
              <span v-if="page.reviewed_at">{{ page.reviewed_by || '复核人未记录' }} · {{ new Date(page.reviewed_at).toLocaleString('zh-CN') }}</span>
            </footer>
          </article>
        </div>
      </div>

      <footer class="modal-actions curriculum-page-actions">
        <span v-if="version.status === 'review_pending'">逐页确认只表示文本与 PDF 已核对，不代表版本已经发布。</span>
        <button class="secondary-button" type="button" @click="emit('close')">关闭</button>
        <button v-if="version.status === 'review_pending'" class="secondary-button" type="button" :disabled="saving || !selectedIds.length" @click="confirmPages(false)">确认所选页</button>
        <button v-if="version.status === 'review_pending'" class="primary-button" type="button" :disabled="saving || !metrics.needsReview" @click="confirmAll = true">确认全部页</button>
      </footer>

      <div v-if="editingPage" class="curriculum-page-edit-layer" @click.self="editingPage = null">
        <section v-curriculum-modal-focus="() => { editingPage = null }" role="dialog" aria-modal="true" aria-labelledby="curriculum-page-edit-title">
          <header>
            <div><h3 id="curriculum-page-edit-title">修订第 {{ editingPage.page_number }} 页文本</h3><p>请对照 PDF 原文修订，不得补写 PDF 中不存在的内容。</p></div>
            <button type="button" aria-label="关闭" data-modal-initial-focus @click="editingPage = null">×</button>
          </header>
          <label class="curriculum-page-text-field" for="curriculum-page-edit-text">
            <span>第 {{ editingPage.page_number }} 页文本</span>
            <textarea id="curriculum-page-edit-text" v-model="editedText" rows="20" />
          </label>
          <footer>
            <button class="secondary-button" type="button" @click="editingPage = null">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="savePage">{{ saving ? '保存中' : '保存页级文本' }}</button>
          </footer>
        </section>
      </div>

      <CurriculumConfirmDialog
        :open="confirmAll"
        title="确认全部逐页文本"
        :message="`确认本版本全部 ${metrics.total} 页均已对照 PDF 原文核对。处理失败页仍会阻止版本复核通过。`"
        confirm-label="确认全部页"
        :loading="saving"
        @close="confirmAll = false"
        @confirm="confirmPages(true)"
      />
    </section>
  </div>
</template>

<style scoped>
.curriculum-page-backdrop {
  z-index: 1250;
}

.curriculum-page-modal {
  position: relative;
  width: min(1120px, 100%);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-page-body {
  min-height: 0;
  overflow: auto;
  padding: 18px 20px;
}

.curriculum-page-notice {
  margin: 0 0 12px;
  border: 1px solid var(--governance-line, var(--line));
  border-left: 3px solid var(--governance-success, var(--primary));
  border-radius: 3px;
  padding: 10px 12px;
  background: var(--success-bg);
  color: var(--success-text);
  line-height: 1.55;
}

.curriculum-page-guidance {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 10px;
  margin: 0 0 14px;
  border: 1px solid var(--governance-line, var(--line));
  border-left: 3px solid var(--governance-ink-soft, var(--primary));
  border-radius: 3px;
  padding: 12px 14px;
  background: var(--governance-fog, color-mix(in srgb, var(--primary) 7%, #fff));
  color: var(--text);
}

.curriculum-page-guidance.review {
  border-color: var(--governance-warning-line, #dbc79b);
  border-left-color: var(--governance-warning, #9a6328);
  background: var(--governance-warning-soft, #faf4e8);
}

.curriculum-page-guidance.draft {
  border-left-color: var(--governance-cinnabar, var(--primary));
}

.curriculum-page-guidance > svg {
  width: 19px;
  height: 19px;
  margin-top: 1px;
  color: var(--governance-ink-soft, var(--primary));
  stroke-width: 1.8;
}

.curriculum-page-guidance.review > svg {
  color: var(--governance-warning, #9a6328);
}

.curriculum-page-guidance.draft > svg {
  color: var(--governance-cinnabar, var(--primary));
}

.curriculum-page-guidance strong {
  display: block;
  color: var(--primary-dark);
  font-size: 14px;
  line-height: 1.5;
}

.curriculum-page-guidance p {
  margin: 3px 0 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.65;
}

.curriculum-page-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 12px;
  border: 1px solid var(--line);
  border-radius: 3px;
  overflow: hidden;
}

.curriculum-page-summary article {
  display: grid;
  gap: 3px;
  padding: 10px 13px;
  border-right: 1px solid var(--line);
}

.curriculum-page-summary article:last-child {
  border-right: 0;
}

.curriculum-page-summary span {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-page-summary strong {
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.curriculum-page-summary .attention {
  background: #fff7ed;
  color: #9a3412;
}

.curriculum-page-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 190px 160px auto;
  align-items: end;
  gap: 10px;
}

.curriculum-page-toolbar label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-page-toolbar input,
.curriculum-page-toolbar select {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 8px 10px;
  background: #fff;
  color: var(--text);
}

.curriculum-page-select-all {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 9px 12px;
  background: color-mix(in srgb, var(--primary) 3%, #fff);
  color: var(--muted);
}

.curriculum-page-select-all label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.curriculum-page-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.curriculum-page-list > article {
  border: 1px solid var(--line);
  border-left: 4px solid color-mix(in srgb, var(--primary) 42%, var(--line));
  border-radius: 3px;
  background: #fff;
}

.curriculum-page-list > article.quality-low_confidence,
.curriculum-page-list > article.quality-empty {
  border-left-color: #d97706;
}

.curriculum-page-list > article.quality-failed {
  border-left-color: #dc2626;
}

.curriculum-page-list > article.selected {
  border-color: color-mix(in srgb, var(--primary) 48%, var(--line));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 12%, transparent);
}

.curriculum-page-list article > header {
  min-height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
}

.curriculum-page-list article > header > div:first-of-type {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.curriculum-page-list article > header span {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-page-list article > header > button {
  min-height: 40px;
  margin-left: auto;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
}

.curriculum-page-statuses {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-left: auto;
}

.curriculum-page-statuses em {
  border-radius: 999px;
  padding: 3px 8px;
  background: color-mix(in srgb, var(--primary) 5%, #fff);
  color: var(--muted);
  font-size: 11px;
  font-style: normal;
}

.curriculum-page-statuses .quality-low_confidence,
.curriculum-page-statuses .quality-empty {
  background: #fff4dd;
  color: #9a4f08;
}

.curriculum-page-statuses .quality-failed {
  background: #fef2f2;
  color: #b42318;
}

.curriculum-page-statuses .review-reviewed {
  background: #e8f7ef;
  color: #166534;
}

.curriculum-page-quality-message {
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 8px 12px;
  background: #fff7ed;
  color: #9a3412;
}

.curriculum-page-list pre {
  max-height: 260px;
  overflow: auto;
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 13px;
  background: color-mix(in srgb, var(--primary) 2%, #fff);
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.curriculum-page-list article > footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid var(--line);
  padding: 7px 12px;
  color: var(--muted);
  font-size: 11px;
}

.curriculum-page-empty {
  min-height: 180px;
  display: grid;
  place-items: center;
  margin: 0;
  border: 1px dashed var(--line);
  border-radius: 3px;
  color: var(--muted);
}

.curriculum-page-actions > span {
  margin-right: auto;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-page-edit-layer {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(18, 42, 37, .58);
}

.curriculum-page-edit-layer > section {
  width: min(820px, 100%);
  max-height: 90%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  border-radius: 4px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(12, 36, 31, .28);
}

.curriculum-page-edit-layer header,
.curriculum-page-edit-layer footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
}

.curriculum-page-edit-layer h3,
.curriculum-page-edit-layer p {
  margin: 0;
}

.curriculum-page-edit-layer p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-page-edit-layer header > button {
  min-width: 44px;
  min-height: 44px;
  border: 0;
  background: transparent;
  font-size: 24px;
  cursor: pointer;
}

.curriculum-page-text-field {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 6px;
  margin: 0 16px;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-page-edit-layer textarea {
  min-height: 0;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 12px;
  resize: none;
}

.curriculum-page-edit-layer footer {
  justify-content: flex-end;
}

@media (max-width: 720px) {
  .curriculum-page-summary,
  .curriculum-page-toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .curriculum-page-summary article:nth-child(2) {
    border-right: 0;
  }

  .curriculum-page-summary article:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }

  .curriculum-page-list article > header,
  .curriculum-page-list article > footer {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .curriculum-page-statuses {
    width: 100%;
    margin-left: 29px;
  }

  .curriculum-page-list article > header > button {
    margin-left: 29px;
  }

  .curriculum-page-actions {
    flex-wrap: wrap;
  }

  .curriculum-page-actions > span {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .curriculum-page-summary,
  .curriculum-page-toolbar {
    grid-template-columns: 1fr;
  }

  .curriculum-page-summary article,
  .curriculum-page-summary article:nth-child(2) {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .curriculum-page-summary article:last-child {
    border-bottom: 0;
  }
}
</style>
