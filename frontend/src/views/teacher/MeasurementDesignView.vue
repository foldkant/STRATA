<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  getBlueprint,
  getBlueprints,
  getMeasurementOptions,
  getRubric,
  getRubrics,
  publishBlueprint,
  publishRubric,
  type BlueprintRow,
  type MeasurementOptions,
  type RubricRow
} from '@/api/measurement'
import BlueprintEditorModal from '@/components/measurement/BlueprintEditorModal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import RubricEditorModal from '@/components/measurement/RubricEditorModal.vue'
import AppShell from '@/layouts/AppShell.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/measurement-design')
const activeTab = ref<'blueprints' | 'rubrics'>('blueprints')
const options = ref<MeasurementOptions | null>(null)
const blueprints = ref<BlueprintRow[]>([])
const rubrics = ref<RubricRow[]>([])
const loading = ref(false)
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')
const blueprintEditor = ref(false)
const rubricEditor = ref(false)
const editingBlueprint = ref<BlueprintRow | null>(null)
const editingRubric = ref<RubricRow | null>(null)
const publishing = ref(false)
const publishTarget = ref<{ type: 'blueprint' | 'rubric'; id: number; title: string } | null>(null)

const summary = computed(() => [
  { label: '任务蓝图', value: blueprints.value.length, detail: `${blueprints.value.filter((item) => item.latest_version).length} 个已有发布版本` },
  { label: '量规草案', value: rubrics.value.length, detail: `${rubrics.value.reduce((sum, item) => sum + item.criterion_count, 0)} 个评价条目` },
  { label: '试点课程', value: options.value?.courses.length || 0, detail: '仅显示本人课程' },
  { label: '当前用途', value: '本地形成性', detail: '教师不可升级为研究用途' }
])

function firstApiError(error: ApiError) {
  const first = Object.values(error.errors).flat()[0]
  return first || error.message
}

async function load() {
  loading.value = true
  try {
    const [optionRows, blueprintRows, rubricRows] = await Promise.all([
      getMeasurementOptions(),
      getBlueprints(),
      getRubrics()
    ])
    options.value = optionRows
    blueprints.value = blueprintRows
    rubrics.value = rubricRows
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '测量设计数据加载失败。'
    noticeTone.value = 'error'
  } finally {
    loading.value = false
  }
}

async function openBlueprint(row?: BlueprintRow) {
  notice.value = ''
  try {
    editingBlueprint.value = row ? await getBlueprint(row.id) : null
    blueprintEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '任务蓝图加载失败。'
    noticeTone.value = 'error'
  }
}

async function openRubric(row?: RubricRow) {
  notice.value = ''
  try {
    editingRubric.value = row ? await getRubric(row.id) : null
    rubricEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '量规草案加载失败。'
    noticeTone.value = 'error'
  }
}

async function saved(kind: 'blueprint' | 'rubric') {
  blueprintEditor.value = false
  rubricEditor.value = false
  editingBlueprint.value = null
  editingRubric.value = null
  notice.value = kind === 'blueprint' ? '任务蓝图草案已保存。' : '量规草案已保存。'
  noticeTone.value = 'success'
  await load()
}

function requestPublish(type: 'blueprint' | 'rubric', row: BlueprintRow | RubricRow) {
  publishTarget.value = { type, id: row.id, title: row.title }
}

async function confirmPublish() {
  if (!publishTarget.value) return
  publishing.value = true
  const target = publishTarget.value
  try {
    if (target.type === 'blueprint') await publishBlueprint(target.id)
    else await publishRubric(target.id)
    notice.value = target.type === 'blueprint' ? '任务蓝图版本已发布。' : '量规版本已发布。'
    noticeTone.value = 'success'
    publishTarget.value = null
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? firstApiError(error) : '版本发布失败。'
    noticeTone.value = 'error'
    publishTarget.value = null
  } finally {
    publishing.value = false
  }
}

function versionLabel(row: BlueprintRow | RubricRow) {
  return row.latest_version ? `v${row.latest_version.version_no}` : '未发布'
}

onMounted(load)
</script>

<template>
  <AppShell title="测量设计" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" />

    <section class="measurement-summary" aria-label="测量设计概况">
      <article v-for="item in summary" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.detail }}</small>
      </article>
    </section>

    <section class="measurement-workspace">
      <header class="measurement-page-header">
        <div>
          <h2>{{ activeTab === 'blueprints' ? '任务蓝图' : '五星量规' }}</h2>
          <p v-if="activeTab === 'blueprints'">先定义学习主张、证据规则和任务规格，再冻结可追溯版本。</p>
          <p v-else>每个条目必须写明证据来源、不可观察条件、五级锚点和锚定样例。</p>
        </div>
        <button
          class="primary-button"
          type="button"
          :disabled="!options?.courses.length || (activeTab === 'rubrics' && !blueprints.length)"
          @click="activeTab === 'blueprints' ? openBlueprint() : openRubric()"
        >
          {{ activeTab === 'blueprints' ? '新建蓝图' : '新建量规' }}
        </button>
      </header>

      <div class="measurement-tabs" role="tablist" aria-label="测量设计类型">
        <button role="tab" type="button" :aria-selected="activeTab === 'blueprints'" :class="{ active: activeTab === 'blueprints' }" @click="activeTab = 'blueprints'">
          任务蓝图 <span>{{ blueprints.length }}</span>
        </button>
        <button role="tab" type="button" :aria-selected="activeTab === 'rubrics'" :class="{ active: activeTab === 'rubrics' }" @click="activeTab = 'rubrics'">
          五星量规 <span>{{ rubrics.length }}</span>
        </button>
      </div>

      <div v-if="loading" class="measurement-empty">正在加载</div>

      <div v-else-if="activeTab === 'blueprints'" class="measurement-table-wrap">
        <p v-if="!blueprints.length" class="measurement-empty">
          尚无任务蓝图。先选择一个本人课程，建立第一条 Claim → Evidence → Task 链。
        </p>
        <table v-else class="measurement-table">
          <thead><tr><th>蓝图</th><th>课程</th><th>证据链</th><th>用途</th><th>版本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in blueprints" :key="row.id">
              <td data-label="蓝图"><strong>{{ row.title }}</strong><small>任务版本 {{ row.task_version || '未填写' }}</small></td>
              <td data-label="课程"><strong>{{ row.course?.title || '未绑定课程' }}</strong><small>{{ row.subject.name }}</small></td>
              <td data-label="证据链"><span>{{ row.claim_count }} 主张</span><span>{{ row.evidence_count }} 证据</span><span>{{ row.task_count }} 任务</span></td>
              <td data-label="用途">{{ row.intended_use_label }}</td>
              <td data-label="版本"><span class="measurement-version" :class="{ published: row.latest_version }">{{ versionLabel(row) }}</span></td>
              <td data-label="操作">
                <div class="measurement-row-actions">
                  <button type="button" @click="openBlueprint(row)">编辑草案</button>
                  <button type="button" @click="requestPublish('blueprint', row)">发布版本</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else class="measurement-table-wrap">
        <p v-if="!rubrics.length" class="measurement-empty">
          尚无量规草案。量规必须绑定任务蓝图，发布前蓝图也必须已有发布版本。
        </p>
        <table v-else class="measurement-table">
          <thead><tr><th>量规</th><th>绑定蓝图</th><th>评价对象</th><th>条目</th><th>版本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in rubrics" :key="row.id">
              <td data-label="量规"><strong>{{ row.title }}</strong><small>{{ row.subject.name }} · {{ row.intended_use_label }}</small></td>
              <td data-label="绑定蓝图">{{ row.blueprint.title }}</td>
              <td data-label="评价对象" class="measurement-wrap-cell">{{ row.evaluation_object || '未填写' }}</td>
              <td data-label="条目">{{ row.criterion_count }} 项</td>
              <td data-label="版本"><span class="measurement-version" :class="{ published: row.latest_version }">{{ versionLabel(row) }}</span></td>
              <td data-label="操作">
                <div class="measurement-row-actions">
                  <button type="button" @click="openRubric(row)">编辑草案</button>
                  <button type="button" @click="requestPublish('rubric', row)">发布版本</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <BlueprintEditorModal
      v-if="blueprintEditor && options"
      :draft="editingBlueprint"
      :options="options"
      @close="blueprintEditor = false"
      @saved="saved('blueprint')"
    />
    <RubricEditorModal
      v-if="rubricEditor && options"
      :draft="editingRubric"
      :options="options"
      :blueprints="blueprints"
      @close="rubricEditor = false"
      @saved="saved('rubric')"
    />
    <ConfirmDialog
      :open="Boolean(publishTarget)"
      title="发布不可变版本"
      :message="`将“${publishTarget?.title || ''}”当前草案冻结为新版本。发布版本不能原地修改，后续调整会生成下一版本。`"
      confirm-label="确认发布"
      :loading="publishing"
      @close="publishTarget = null"
      @confirm="confirmPublish"
    />
  </AppShell>
</template>

<style scoped>
.measurement-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, .04);
}

.measurement-summary article {
  min-width: 0;
  min-height: 104px;
  display: grid;
  align-content: center;
  gap: 5px;
  padding: 16px 20px;
  border-right: 1px solid var(--line);
}

.measurement-summary article:last-child {
  border-right: 0;
}

.measurement-summary span,
.measurement-summary small {
  color: var(--muted);
}

.measurement-summary strong {
  font-size: 24px;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.measurement-workspace {
  min-width: 0;
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, .04);
}

.measurement-page-header {
  min-height: 86px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
}

.measurement-page-header h2,
.measurement-page-header p {
  margin: 0;
}

.measurement-page-header p {
  margin-top: 5px;
  color: var(--muted);
  line-height: 1.5;
}

.measurement-tabs {
  display: flex;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: #f8fafc;
}

.measurement-tabs button {
  min-height: 48px;
  border: 0;
  border-bottom: 3px solid transparent;
  padding: 0 18px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.measurement-tabs button.active {
  border-bottom-color: var(--primary);
  color: var(--primary-dark);
  font-weight: 700;
}

.measurement-tabs span {
  display: inline-grid;
  place-items: center;
  min-width: 22px;
  height: 22px;
  margin-left: 6px;
  border-radius: 999px;
  background: #e8f1ff;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.measurement-table-wrap {
  min-width: 0;
  overflow: auto;
}

.measurement-table {
  min-width: 900px;
}

.measurement-table th,
.measurement-table td {
  padding: 13px 16px;
  vertical-align: middle;
}

.measurement-table td:first-child,
.measurement-table td:nth-child(2) {
  white-space: normal;
}

.measurement-table td strong,
.measurement-table td small {
  display: block;
}

.measurement-table td small {
  margin-top: 4px;
  color: var(--muted);
  line-height: 1.4;
}

.measurement-table td:nth-child(3) > span {
  display: inline-block;
  margin: 2px 6px 2px 0;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 7px;
  color: var(--muted);
  font-size: 12px;
}

.measurement-wrap-cell {
  max-width: 320px;
  white-space: normal;
  line-height: 1.5;
}

.measurement-version {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  border-radius: 999px;
  padding: 0 9px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 12px;
}

.measurement-version.published {
  background: #e8f7ef;
  color: #166534;
}

.measurement-row-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.measurement-row-actions button {
  min-height: 40px;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  white-space: nowrap;
}

.measurement-row-actions button:hover {
  color: var(--primary-dark);
}

.measurement-empty {
  min-height: 220px;
  display: grid;
  place-items: center;
  margin: 0;
  padding: 24px;
  color: var(--muted);
  text-align: center;
}

@media (max-width: 1000px) {
  .measurement-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .measurement-summary article:nth-child(2) {
    border-right: 0;
  }

  .measurement-summary article:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }
}

@media (max-width: 640px) {
  .measurement-summary {
    grid-template-columns: 1fr;
  }

  .measurement-summary article,
  .measurement-summary article:nth-child(2) {
    min-height: 88px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .measurement-summary article:last-child {
    border-bottom: 0;
  }

  .measurement-page-header {
    align-items: stretch;
    flex-direction: column;
  }

  .measurement-tabs {
    padding: 0;
  }

  .measurement-tabs button {
    flex: 1;
    padding: 0 8px;
  }

  .measurement-table-wrap {
    overflow: visible;
    padding: 14px;
  }

  .measurement-table,
  .measurement-table tbody {
    min-width: 0;
    display: grid;
    gap: 12px;
  }

  .measurement-table thead {
    display: none;
  }

  .measurement-table tr {
    min-width: 0;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 14px;
    background: #fbfdff;
  }

  .measurement-table td {
    min-width: 0;
    display: grid;
    align-content: start;
    gap: 4px;
    border: 0;
    padding: 0;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .measurement-table td::before {
    content: attr(data-label);
    color: var(--muted);
    font-size: 12px;
    font-weight: 500;
  }

  .measurement-table td:first-child,
  .measurement-table td:last-child,
  .measurement-wrap-cell {
    grid-column: 1 / -1;
    max-width: none;
  }

  .measurement-table td:first-child {
    padding-bottom: 12px;
    border-bottom: 1px solid var(--line);
  }

  .measurement-row-actions {
    align-items: stretch;
  }

  .measurement-row-actions button {
    min-height: 44px;
    flex: 1;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: #fff;
  }
}
</style>
