<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import { getTeacherResources, type ResourceRow } from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import OnlyOfficeEditor from '@/components/OnlyOfficeEditor.vue'
import { teacherNav } from './nav'

const route = useRoute()
const navItems = teacherNav('/teacher/documents')
const loading = ref(false)
const notice = ref('')
const query = ref('')
const rows = ref<ResourceRow[]>([])
const activeResourceId = ref<number | null>(null)
const mode = ref<'view' | 'edit'>('edit')

const officeExts = new Set(['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'])
const documents = computed(() =>
  rows.value.filter((item) => officeExts.has((item.file_ext || '').toLowerCase()))
)
const activeDocument = computed(() => documents.value.find((item) => item.id === activeResourceId.value) || documents.value[0] || null)

function formatFileSize(size: number) {
  if (!size) return '无附件'
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(size >= 100 * 1024 * 1024 ? 0 : 1)} MB`
}

function formatDate(value: string) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { hour12: false })
}

function documentType(row: ResourceRow) {
  const ext = (row.file_ext || '').toLowerCase()
  if (['ppt', 'pptx'].includes(ext)) return 'PPT'
  if (['xls', 'xlsx'].includes(ext)) return 'Excel'
  return 'Word'
}

async function loadRows() {
  loading.value = true
  notice.value = ''
  try {
    const result = await getTeacherResources({ q: query.value, page_size: 100 })
    rows.value = result.results
    const routeId = Number(route.query.resource || 0)
    const preferred = result.results.find((item) => item.id === routeId && officeExts.has(item.file_ext))
    const firstOffice = result.results.find((item) => officeExts.has(item.file_ext))
    activeResourceId.value = preferred?.id || firstOffice?.id || null
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '协作文档加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(loadRows)
</script>

<template>
  <AppShell title="协作文档" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <section class="document-workspace-shell">
      <header class="document-workspace-header">
        <div>
          <h2>ONLYOFFICE 文档工作区</h2>
          <p>从教师资源库读取 Word、PPT、Excel。教师可编辑自己的资源，学生端按课时引用只读预览。</p>
        </div>
        <div class="heading-actions">
          <RouterLink class="secondary-button" to="/teacher/resources">上传资源</RouterLink>
          <button class="secondary-button" type="button" :disabled="loading" @click="loadRows">
            {{ loading ? '刷新中' : '刷新' }}
          </button>
        </div>
      </header>

      <div class="document-workspace-grid">
        <section class="document-list-pane">
          <div class="document-filter-bar">
            <label>
              <span>关键词</span>
              <input v-model.trim="query" placeholder="搜索文档名称" @keyup.enter="loadRows" />
            </label>
            <label>
              <span>打开方式</span>
              <select v-model="mode">
                <option value="edit">编辑</option>
                <option value="view">只读预览</option>
              </select>
            </label>
          </div>

          <div class="document-table-list">
            <button
              v-for="doc in documents"
              :key="doc.id"
              class="document-row-card"
              :class="{ active: doc.id === activeResourceId }"
              type="button"
              @click="activeResourceId = doc.id"
            >
              <span class="document-file-type">{{ documentType(doc) }}</span>
              <span>
                <strong>{{ doc.title }}</strong>
                <small>{{ doc.attachment_name }} · {{ formatFileSize(doc.attachment_size) }}</small>
              </span>
              <i>{{ formatDate(doc.updated_at) }}</i>
            </button>
            <p v-if="!loading && !documents.length" class="empty">
              暂无可编辑 Office 文档。请先到资源管理上传 docx、pptx 或 xlsx。
            </p>
          </div>
        </section>

        <section class="document-detail-pane">
          <header>
            <div>
              <p v-if="activeDocument">{{ documentType(activeDocument) }} · {{ activeDocument.attachment_name }}</p>
              <h2>{{ activeDocument?.title || '未选择文档' }}</h2>
            </div>
            <div class="row-actions">
              <button type="button" :class="{ active: mode === 'edit' }" @click="mode = 'edit'">编辑</button>
              <button type="button" :class="{ active: mode === 'view' }" @click="mode = 'view'">预览</button>
              <a v-if="activeDocument?.attachment_url" :href="activeDocument.attachment_url" target="_blank" rel="noreferrer">下载</a>
            </div>
          </header>

          <OnlyOfficeEditor v-if="activeDocument" :key="`${activeDocument.id}-${mode}`" :resource-id="activeDocument.id" :mode="mode" />
          <div v-else class="onlyoffice-placeholder">
            <strong>没有可编辑文档</strong>
            <p>上传 PPT、Word 或 Excel 后，这里会显示 ONLYOFFICE 编辑器。</p>
          </div>

          <div class="document-meta-grid">
            <article>
              <span>当前权限</span>
              <strong>{{ mode === 'edit' ? '教师编辑' : '只读预览' }}</strong>
              <small>学生端从课时进入时默认只读。</small>
            </article>
            <article>
              <span>保存方式</span>
              <strong>本地回调保存</strong>
              <small>ONLYOFFICE 保存后写回教师资源文件。</small>
            </article>
            <article>
              <span>课堂用途</span>
              <strong>课件预览 / 任务单编辑</strong>
              <small>在课时设计中加入资源后，学生端可预览。</small>
            </article>
          </div>
        </section>
      </div>
    </section>
  </AppShell>
</template>
