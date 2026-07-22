<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  compareCurriculumStandardVersions,
  type CurriculumStandard,
  type CurriculumVersionComparison,
  type CurriculumVersionComparisonItem
} from '@/api/curriculumStandards'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{ standard: CurriculumStandard }>()
const emit = defineEmits<{ close: [] }>()

const versions = computed(() => props.standard.versions || [])
const fromId = ref<number | ''>(versions.value[1]?.id || versions.value[0]?.id || '')
const toId = ref<number | ''>(props.standard.current_version?.id || versions.value[0]?.id || '')
const result = ref<CurriculumVersionComparison | null>(null)
const changeType = ref<'changed' | 'added' | 'removed' | 'modified' | 'unchanged'>('changed')
const loading = ref(false)
const notice = ref('')

const displayedItems = computed(() => {
  if (!result.value) return []
  if (changeType.value === 'changed') return result.value.content_items.filter((item) => item.change_type !== 'unchanged')
  return result.value.content_items.filter((item) => item.change_type === changeType.value)
})

function pageLabel(item: CurriculumVersionComparisonItem | null) {
  if (!item) return '-'
  return item.source_page_start === item.source_page_end
    ? `第 ${item.source_page_start} 页`
    : `第 ${item.source_page_start}—${item.source_page_end} 页`
}

function changeLabel(value: 'added' | 'removed' | 'modified' | 'unchanged') {
  return { added: '新增', removed: '删除', modified: '修改', unchanged: '未变化' }[value]
}

function metadataLabel(value: string) {
  return {
    version_label: '版本标识',
    publication_year: '发布年份',
    effective_year: '实施年份',
    issued_by: '发布机构',
    source_url: '权威来源网址',
    pdf_sha256: 'PDF 校验值',
    structured_text_sha256: '结构化文本校验值',
    content_hash: '版本内容校验值'
  }[value] || value
}

function displayValue(value: string | number | null) {
  if (value === null || value === '') return '未填写'
  const text = String(value)
  return text.length > 28 ? `${text.slice(0, 28)}…` : text
}

async function compare() {
  if (!fromId.value || !toId.value || fromId.value === toId.value) {
    notice.value = '请选择同一课程标准下两个不同版本。'
    return
  }
  loading.value = true
  notice.value = ''
  try {
    result.value = await compareCurriculumStandardVersions(Number(fromId.value), Number(toId.value))
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准版本比较失败。'
    result.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (versions.value.length >= 2) compare()
})
</script>

<template>
  <div class="modal-backdrop curriculum-compare-backdrop" @click.self="emit('close')">
    <section v-curriculum-modal-focus="() => emit('close')" class="entity-modal curriculum-compare-modal" role="dialog" aria-modal="true" aria-labelledby="curriculum-compare-title">
      <header class="modal-header">
        <div>
          <h2 id="curriculum-compare-title">课程标准版本比较</h2>
          <p>{{ standard.title }} · 比较元数据、文件校验值、内容条目和原文位置</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
      </header>

      <div class="curriculum-compare-body">
        <p v-if="notice" class="curriculum-compare-notice" role="alert">{{ notice }}</p>
        <p v-if="versions.length < 2" class="curriculum-compare-empty">至少需要两个课程标准版本才能比较。</p>
        <template v-else>
          <form class="curriculum-compare-controls" @submit.prevent="compare">
            <label>
              <span>原版本</span>
              <AppSelect v-model="fromId">
                <option v-for="version in versions" :key="version.id" :value="version.id">{{ version.version_label }} · {{ version.status_label }}</option>
              </AppSelect>
            </label>
            <span aria-hidden="true">→</span>
            <label>
              <span>目标版本</span>
              <AppSelect v-model="toId">
                <option v-for="version in versions" :key="version.id" :value="version.id">{{ version.version_label }} · {{ version.status_label }}</option>
              </AppSelect>
            </label>
            <button class="primary-button" type="submit" :disabled="loading">{{ loading ? '比较中' : '开始比较' }}</button>
          </form>

          <div v-if="result" class="curriculum-compare-results">
            <section class="curriculum-compare-summary" aria-label="内容条目变化概况">
              <article class="added"><span>新增</span><strong>{{ result.content_item_counts.added }}</strong></article>
              <article class="removed"><span>删除</span><strong>{{ result.content_item_counts.removed }}</strong></article>
              <article class="modified"><span>修改</span><strong>{{ result.content_item_counts.modified }}</strong></article>
              <article><span>未变化</span><strong>{{ result.content_item_counts.unchanged }}</strong></article>
            </section>

            <section class="curriculum-metadata-changes">
              <header><strong>基本信息与文件校验变化</strong><small>校验值变化说明文件或结构化内容发生变化，需要结合内容条目逐项复核。</small></header>
              <p v-if="!result.metadata_changes.length" class="curriculum-compare-empty compact">基本信息和文件校验值没有变化。</p>
              <table v-else>
                <thead><tr><th>项目</th><th>原版本</th><th>目标版本</th></tr></thead>
                <tbody>
                  <tr v-for="item in result.metadata_changes" :key="item.field">
                    <th>{{ metadataLabel(item.field) }}</th>
                    <td :title="String(item.before ?? '')">{{ displayValue(item.before) }}</td>
                    <td :title="String(item.after ?? '')">{{ displayValue(item.after) }}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section class="curriculum-item-changes">
              <header>
                <div><strong>课程标准内容条目变化</strong><small>按稳定条目代码比较标题、内容校验值和原文位置。</small></div>
                <AppSelect v-model="changeType" aria-label="筛选变化类型">
                  <option value="changed">仅显示发生变化</option>
                  <option value="added">新增</option>
                  <option value="removed">删除</option>
                  <option value="modified">修改</option>
                  <option value="unchanged">未变化</option>
                </AppSelect>
              </header>
              <p v-if="!displayedItems.length" class="curriculum-compare-empty compact">该类型没有内容条目。</p>
              <article v-for="item in displayedItems" v-else :key="item.code" :class="`change-${item.change_type}`">
                <header>
                  <span>{{ changeLabel(item.change_type) }}</span>
                  <strong>{{ item.code }} · {{ item.after?.title || item.before?.title }}</strong>
                </header>
                <div>
                  <section>
                    <span>{{ result.from_version.version_label }}</span>
                    <strong>{{ item.before?.title || '该版本中不存在' }}</strong>
                    <small>{{ pageLabel(item.before) }}<template v-if="item.before?.source_paragraph"> · {{ item.before.source_paragraph }}</template></small>
                    <code v-if="item.before">{{ item.before.content_hash.slice(0, 16) }}</code>
                  </section>
                  <section>
                    <span>{{ result.to_version.version_label }}</span>
                    <strong>{{ item.after?.title || '该版本中不存在' }}</strong>
                    <small>{{ pageLabel(item.after) }}<template v-if="item.after?.source_paragraph"> · {{ item.after.source_paragraph }}</template></small>
                    <code v-if="item.after">{{ item.after.content_hash.slice(0, 16) }}</code>
                  </section>
                </div>
              </article>
            </section>
          </div>
        </template>
      </div>

      <footer class="modal-actions"><button class="secondary-button" type="button" @click="emit('close')">关闭</button></footer>
    </section>
  </div>
</template>

<style scoped>
.curriculum-compare-backdrop {
  z-index: 1250;
}

.curriculum-compare-modal {
  width: min(1080px, 100%);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-compare-body {
  min-height: 0;
  overflow: auto;
  padding: 18px 20px 24px;
}

.curriculum-compare-notice {
  margin: 0 0 12px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fef2f2;
  color: #991b1b;
}

.curriculum-compare-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto;
  align-items: end;
  gap: 12px;
}

.curriculum-compare-controls > label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-compare-controls select {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 9px 11px;
  background: #fff;
  color: var(--text);
}

.curriculum-compare-controls > span {
  min-height: 44px;
  display: grid;
  place-items: center;
  color: var(--muted);
}

.curriculum-compare-results {
  display: grid;
  gap: 16px;
  margin-top: 16px;
}

.curriculum-compare-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}

.curriculum-compare-summary article {
  display: grid;
  gap: 3px;
  padding: 11px 14px;
  border-right: 1px solid var(--line);
}

.curriculum-compare-summary article:last-child {
  border-right: 0;
}

.curriculum-compare-summary span {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-compare-summary strong {
  font-size: 21px;
  font-variant-numeric: tabular-nums;
}

.curriculum-compare-summary .added {
  background: #f0fdf4;
  color: #166534;
}

.curriculum-compare-summary .removed {
  background: #fef2f2;
  color: #b42318;
}

.curriculum-compare-summary .modified {
  background: #fff7ed;
  color: #9a3412;
}

.curriculum-metadata-changes,
.curriculum-item-changes {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}

.curriculum-metadata-changes > header,
.curriculum-item-changes > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--line);
  padding: 12px 14px;
  background: #f8fafc;
}

.curriculum-metadata-changes > header,
.curriculum-item-changes > header > div {
  display: grid;
  gap: 3px;
}

.curriculum-metadata-changes header small,
.curriculum-item-changes header small {
  color: var(--muted);
}

.curriculum-metadata-changes table {
  min-width: 680px;
}

.curriculum-metadata-changes {
  overflow: auto;
}

.curriculum-metadata-changes th,
.curriculum-metadata-changes td {
  white-space: normal;
  overflow-wrap: anywhere;
}

.curriculum-item-changes > header select {
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 7px 9px;
  background: #fff;
}

.curriculum-item-changes > article {
  border-left: 4px solid #94a3b8;
  border-bottom: 1px solid var(--line);
}

.curriculum-item-changes > article:last-child {
  border-bottom: 0;
}

.curriculum-item-changes > article.change-added {
  border-left-color: #16a34a;
}

.curriculum-item-changes > article.change-removed {
  border-left-color: #dc2626;
}

.curriculum-item-changes > article.change-modified {
  border-left-color: #d97706;
}

.curriculum-item-changes > article > header {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
}

.curriculum-item-changes > article > header span {
  border-radius: 999px;
  padding: 2px 7px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
}

.curriculum-item-changes > article > div {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px solid var(--line);
}

.curriculum-item-changes > article section {
  min-width: 0;
  display: grid;
  gap: 5px;
  padding: 11px 12px;
}

.curriculum-item-changes strong,
.curriculum-compare-modal h2,
.curriculum-compare-modal p {
  overflow-wrap: anywhere;
}

.curriculum-item-changes > article section + section {
  border-left: 1px solid var(--line);
}

.curriculum-item-changes section > span,
.curriculum-item-changes section small,
.curriculum-item-changes code {
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.curriculum-compare-empty {
  min-height: 180px;
  display: grid;
  place-items: center;
  margin: 0;
  border: 1px dashed var(--line);
  border-radius: 6px;
  color: var(--muted);
}

.curriculum-compare-empty.compact {
  min-height: 90px;
  border: 0;
  border-radius: 0;
}

@media (max-width: 700px) {
  .curriculum-compare-controls {
    grid-template-columns: 1fr;
  }

  .curriculum-compare-controls > span {
    min-height: auto;
    transform: rotate(90deg);
  }

  .curriculum-compare-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .curriculum-compare-summary article:nth-child(2) {
    border-right: 0;
  }

  .curriculum-compare-summary article:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }

  .curriculum-item-changes > header {
    align-items: stretch;
    flex-direction: column;
  }

  .curriculum-item-changes > article > div {
    grid-template-columns: 1fr;
  }

  .curriculum-item-changes > article section + section {
    border-top: 1px solid var(--line);
    border-left: 0;
  }
}
</style>
