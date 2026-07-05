<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  deleteTeacherResource,
  getTeacherResources,
  uploadTeacherResource,
  type ResourceRow
} from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/resources')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const query = ref('')
const rows = ref<ResourceRow[]>([])
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const errors = ref<FieldErrors>({})
const selectedPreviewId = ref<number | null>(null)

const form = reactive({
  title: '',
  content: '',
  is_pinned: false
})

const allowedExt = new Set([
  'jpg',
  'jpeg',
  'png',
  'webp',
  'gif',
  'mp4',
  'webm',
  'mov',
  'mp3',
  'wav',
  'pdf',
  'doc',
  'docx',
  'ppt',
  'pptx',
  'xls',
  'xlsx',
  'csv',
  'txt',
  'md',
  'zip',
  'rar',
  '7z'
])

const selectedPreviewResource = computed(() => {
  if (!rows.value.length) return null
  return rows.value.find((item) => item.id === selectedPreviewId.value) || rows.value[0]
})

function formatFileSize(size: number) {
  if (!size) return '无附件'
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(size >= 100 * 1024 * 1024 ? 0 : 1)} MB`
}

function formatDate(value: string) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function isOfficeResource(item: ResourceRow) {
  return ['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'].includes((item.file_ext || '').toLowerCase())
}

function resetForm() {
  form.title = ''
  form.content = ''
  form.is_pinned = false
  selectedFile.value = null
  errors.value = {}
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  errors.value = {}
  selectedFile.value = file
  if (!file) return

  const cleanExt = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() || '' : ''
  if (!allowedExt.has(cleanExt)) {
    errors.value = { attachment: ['暂不支持该资源格式。'] }
    selectedFile.value = null
    input.value = ''
    return
  }
  if (file.size > 512 * 1024 * 1024) {
    errors.value = { attachment: ['资源文件不能超过 512MB。'] }
    selectedFile.value = null
    input.value = ''
    return
  }
  if (!form.title.trim()) {
    form.title = file.name.replace(/\.[^.]+$/, '').slice(0, 128)
  }
}

async function loadRows() {
  loading.value = true
  try {
    const result = await getTeacherResources({ q: query.value, page_size: 50 })
    rows.value = result.results
    if (!rows.value.some((item) => item.id === selectedPreviewId.value)) {
      selectedPreviewId.value = rows.value[0]?.id || null
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源列表加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitResource() {
  if (!selectedFile.value) {
    errors.value = { attachment: ['请选择要上传的资源文件。'] }
    return
  }
  const title = form.title.trim()
  if (!/^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\._\-\s]{2,128}$/.test(title)) {
    errors.value = { title: ['资源标题需为 2-128 位，可包含中文、字母、数字、下划线和常用标点。'] }
    return
  }

  saving.value = true
  try {
    const saved = await uploadTeacherResource({
      title,
      content: form.content.trim(),
      file: selectedFile.value,
      is_pinned: form.is_pinned
    })
    rows.value = [saved, ...rows.value.filter((item) => item.id !== saved.id)]
    selectedPreviewId.value = saved.id
    notice.value = '资源已上传。'
    resetForm()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = '资源上传失败。'
    }
  } finally {
    saving.value = false
  }
}

async function removeResource(row: ResourceRow) {
  const confirmed = window.confirm(`确认删除资源“${row.title}”？`)
  if (!confirmed) return
  try {
    await deleteTeacherResource(row.id)
    rows.value = rows.value.filter((item) => item.id !== row.id)
    if (selectedPreviewId.value === row.id) {
      selectedPreviewId.value = rows.value[0]?.id || null
    }
    notice.value = '资源已删除。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源删除失败。'
  }
}

onMounted(loadRows)
</script>

<template>
  <AppShell title="资源管理" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section class="resource-management-layout">
      <aside class="resource-upload-card">
        <header>
          <h2>上传资源</h2>
          <p>用于课程、课时和课堂活动。第一版保存到教师个人资源库。</p>
        </header>
        <form class="resource-upload-form" @submit.prevent="submitResource">
          <label>
            <span>资源标题 <b>*</b></span>
            <input v-model.trim="form.title" maxlength="128" placeholder="例如 数据采集课件" />
            <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
          </label>
          <label>
            <span>资源说明</span>
            <textarea v-model.trim="form.content" rows="4" maxlength="1000" placeholder="资源用途、课堂提示或学生阅读要求。"></textarea>
            <small v-if="errors.content" class="field-error">{{ errors.content[0] }}</small>
          </label>
          <label>
            <span>本地文件 <b>*</b></span>
            <input
              ref="fileInput"
              type="file"
              accept=".jpg,.jpeg,.png,.webp,.gif,.mp4,.webm,.mov,.mp3,.wav,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.txt,.md,.zip,.rar,.7z"
              @change="onFileChange"
            />
            <small v-if="selectedFile">{{ selectedFile.name }} · {{ formatFileSize(selectedFile.size) }}</small>
            <small v-if="errors.attachment" class="field-error">{{ errors.attachment[0] }}</small>
          </label>
          <label class="check-row">
            <input v-model="form.is_pinned" type="checkbox" />
            <span>置顶显示</span>
          </label>
          <div class="resource-upload-actions">
            <button class="primary-button" type="submit" :disabled="saving">{{ saving ? '上传中' : '上传资源' }}</button>
            <button class="secondary-button" type="button" @click="resetForm">清空</button>
          </div>
        </form>
      </aside>

      <main class="resource-library-card">
        <div class="panel-heading split">
          <div>
            <h2>我的资源</h2>
            <p>图片、视频、课件、PDF、表格和素材包都走本地存储，后续接入 ONLYOFFICE 和 PDF.js 预览。</p>
          </div>
          <div class="heading-actions">
            <input v-model.trim="query" class="resource-search-input" placeholder="搜索标题、说明或文件名" @keyup.enter="loadRows" />
            <button class="secondary-button" type="button" :disabled="loading" @click="loadRows">
              {{ loading ? '刷新中' : '查询' }}
            </button>
          </div>
        </div>

        <div class="resource-library-workspace">
          <ResourcePreview :resource="selectedPreviewResource" office-mode="edit" />

          <div class="resource-grid inline-preview-list">
            <article v-for="item in rows" :key="item.id" class="resource-card">
              <header>
                <span>{{ item.file_ext ? item.file_ext.toUpperCase() : '资源' }}</span>
                <strong>{{ item.title }}</strong>
              </header>
              <p>{{ item.content || '暂无说明。' }}</p>
              <dl class="resource-meta">
                <div>
                  <dt>文件</dt>
                  <dd>{{ item.attachment_name || '无附件' }}</dd>
                </div>
                <div>
                  <dt>大小</dt>
                  <dd>{{ formatFileSize(item.attachment_size) }}</dd>
                </div>
                <div>
                  <dt>更新</dt>
                  <dd>{{ formatDate(item.updated_at) }}</dd>
                </div>
              </dl>
              <footer>
                <button class="primary-button" type="button" @click="selectedPreviewId = item.id">网页内预览</button>
                <RouterLink v-if="isOfficeResource(item)" class="secondary-button" :to="`/teacher/documents?resource=${item.id}`">
                  文档工作区
                </RouterLink>
                <a v-if="item.attachment_url" class="secondary-button" :href="item.attachment_url" download>下载</a>
                <button class="secondary-button danger" type="button" @click="removeResource(item)">删除</button>
              </footer>
            </article>
            <p v-if="!loading && !rows.length" class="empty">暂无资源。先上传一个课件、PDF、视频或素材包。</p>
          </div>
        </div>
      </main>
    </section>
  </AppShell>
</template>
