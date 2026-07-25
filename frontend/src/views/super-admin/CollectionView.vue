<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  deleteCollectionBatch,
  getCollectionBatch,
  getCollectionBatches,
  uploadCollectionBatch,
  type CollectionBatch
} from '@/api/superAdmin'
import AppShell from '@/layouts/AppShell.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import FilePicker from '@/components/FilePicker.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { superAdminNav } from './nav'

const navItems = superAdminNav('/super-admin/collection')
const rows = ref<CollectionBatch[]>([])
const statusCounts = ref<Array<{ label: string; value: string; count: number }>>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const query = ref('')
const status = ref('')
const loading = ref(false)
const uploading = ref(false)
const selectedFile = ref<File | null>(null)
const notice = ref('')
const fileError = ref('')
const detail = ref<CollectionBatch | null>(null)
const detailLoading = ref(false)
const deleteTarget = ref<CollectionBatch | null>(null)
const deleting = ref(false)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const metrics = computed(() => statusCounts.value.map((item) => ({
  label: statusLabel(item.value, item.label),
  value: item.count,
  sub: item.value === 'failed' ? '需要处理' : '数据接收批次'
})))
const exportUrl = computed(() => {
  const search = new URLSearchParams()
  if (query.value.trim()) search.set('q', query.value.trim())
  if (status.value) search.set('status', status.value)
  return `/api/v1/super-admin/collection/export/${search.size ? `?${search}` : ''}`
})

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function formatSize(value?: number) {
  if (!value) return '0 B'
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function statusClass(value: CollectionBatch['status']) {
  return `status-${value}`
}

function statusLabel(value: string, fallback = '') {
  const labels: Record<string, string> = {
    uploaded: '待检查',
    validated: '检查完成',
    imported: '接收完成',
    failed: '检查未通过'
  }
  return labels[value] || fallback || value
}

async function load(resetPage = false) {
  if (resetPage) page.value = 1
  loading.value = true
  try {
    const result = await getCollectionBatches({
      q: query.value.trim(),
      status: status.value,
      page: page.value,
      page_size: pageSize.value
    })
    rows.value = result.results
    total.value = result.count
    pageSize.value = result.page_size
    statusCounts.value = result.status_counts
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学校数据接收记录加载失败。'
  } finally {
    loading.value = false
  }
}

function selectPackage(files: File[]) {
  const file = files[0] || null
  selectedFile.value = file
  fileError.value = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) fileError.value = '请上传 ZIP 格式的学校数据文件。'
  else if (file.size > 1024 * 1024 * 1024) fileError.value = '学校数据文件不能超过 1GB。'
}

async function upload() {
  if (!selectedFile.value) {
    fileError.value = '请选择 ZIP 格式的学校数据文件。'
    return
  }
  if (fileError.value) return
  uploading.value = true
  try {
    const result = await uploadCollectionBatch(selectedFile.value)
    selectedFile.value = null
    notice.value = result.status === 'failed'
      ? '数据文件已登记，但完整性检查未通过，请查看详情。'
      : '数据文件已上传并通过基础检查。'
    await load(true)
    await openDetail(result)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      fileError.value = error.errors.package_file?.[0] || ''
    } else {
      notice.value = '数据文件上传失败。'
    }
  } finally {
    uploading.value = false
  }
}

async function openDetail(row: CollectionBatch) {
  detailLoading.value = true
  detail.value = row
  try {
    detail.value = await getCollectionBatch(row.id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '数据接收详情加载失败。'
  } finally {
    detailLoading.value = false
  }
}

async function removeBatch() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteCollectionBatch(deleteTarget.value.id)
    if (detail.value?.id === deleteTarget.value.id) detail.value = null
    deleteTarget.value = null
    notice.value = '数据接收记录已删除。'
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '数据接收记录删除失败。'
  } finally {
    deleting.value = false
  }
}

function resetFilters() {
  query.value = ''
  status.value = ''
  load(true)
}

function changePage(delta: number) {
  page.value = Math.min(Math.max(page.value + delta, 1), pageCount.value)
  load()
}

onMounted(() => load())
</script>

<template>
  <AppShell title="学校数据接收" eyebrow="超级管理员" :nav-items="navItems" shell-variant="super-admin" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <header class="console-page-heading">
      <div>
        <h2>学校数据接收</h2>
        <p>接收各校导出的数据文件，检查学校来源、系统版本和文件完整性，确认后再用于校际数据汇总。</p>
      </div>
      <a class="secondary-button" :href="exportUrl">导出记录</a>
    </header>

    <MetricGrid v-if="metrics.length" class="metric-grid-four" :metrics="metrics" />

    <section class="panel collection-upload-panel">
      <div class="panel-heading split compact-heading">
        <div>
          <h2>上传学校数据文件</h2>
          <p>通过检查只说明文件来源清楚、内容完整，尚未加入校际数据统计。</p>
        </div>
        <button class="primary-button" type="button" :disabled="uploading" @click="upload">
          {{ uploading ? '正在检查' : '上传并检查' }}
        </button>
      </div>
      <FilePicker
        label="学校数据文件"
        hint="请上传不超过 1GB 的 ZIP 压缩包，文件内需包含数据说明文件（manifest.json）。"
        accept=".zip,application/zip,application/x-zip-compressed"
        :file="selectedFile"
        :busy="uploading"
        :error="fileError"
        required
        @select="selectPackage"
      />
    </section>

    <section class="panel list-panel collection-list-panel">
      <div class="panel-heading">
        <h2>数据接收记录</h2>
        <p>查看学校来源、上传时间、处理状态和文件完整性检查结果。</p>
      </div>
      <form class="toolbar" @submit.prevent="load(true)">
        <label>
          <span>关键词</span>
          <input v-model="query" placeholder="批次、学校编号、学校或版本" />
        </label>
        <label>
          <span>状态</span>
          <AppSelect v-model="status">
            <option value="">全部状态</option>
            <option value="uploaded">待检查</option>
            <option value="validated">检查完成</option>
            <option value="imported">接收完成</option>
            <option value="failed">检查未通过</option>
          </AppSelect>
        </label>
        <button class="primary-button" type="submit" :disabled="loading">查询</button>
        <button class="secondary-button" type="button" @click="resetFilters">重置</button>
      </form>

      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>批次</th><th>学校</th><th>版本</th><th>状态</th><th>提交人</th><th>提交时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td><button class="table-link button-link" type="button" @click="openDetail(row)">{{ row.batch_code }}</button></td>
              <td>
                <strong>{{ row.source_school?.name || row.source_school_code || '未识别' }}</strong>
                <small class="table-subline">{{ row.source_school_code || '-' }}</small>
              </td>
              <td>{{ row.source_system_version || '-' }}</td>
              <td><span class="status-pill" :class="statusClass(row.status)">{{ statusLabel(row.status, row.status_label) }}</span></td>
              <td>{{ row.uploaded_by || '-' }}</td>
              <td>{{ formatDate(row.uploaded_at) }}</td>
              <td class="row-actions">
                <button type="button" @click="openDetail(row)">详情</button>
                <button class="danger-link" type="button" :disabled="row.status === 'imported'" @click="deleteTarget = row">删除</button>
              </td>
            </tr>
            <tr v-if="!rows.length"><td colspan="7" class="empty">{{ loading ? '正在加载' : '暂无数据接收记录' }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>共 {{ total }} 条，第 {{ page }} / {{ pageCount }} 页</span>
        <div>
          <button type="button" :disabled="page <= 1 || loading" @click="changePage(-1)">上一页</button>
          <button type="button" :disabled="page >= pageCount || loading" @click="changePage(1)">下一页</button>
        </div>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="detail" class="modal-backdrop" role="presentation" @click.self="detail = null">
        <section class="entity-modal collection-detail-modal" role="dialog" aria-modal="true" aria-labelledby="collection-detail-title">
          <header class="modal-header">
            <div>
              <h2 id="collection-detail-title">数据接收详情</h2>
              <p>{{ detail.batch_code }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="detail = null">×</button>
          </header>
          <div class="collection-detail-body">
            <p v-if="detailLoading" class="empty">正在加载</p>
            <template v-else>
              <dl class="detail-grid">
                <div><dt>状态</dt><dd><span class="status-pill" :class="statusClass(detail.status)">{{ statusLabel(detail.status, detail.status_label) }}</span></dd></div>
                <div><dt>来源学校</dt><dd>{{ detail.source_school?.name || '未匹配学校档案' }}</dd></div>
                <div><dt>学校编号</dt><dd>{{ detail.source_school_code || '-' }}</dd></div>
                <div><dt>系统版本</dt><dd>{{ detail.source_system_version || '-' }}</dd></div>
                <div><dt>上传时间</dt><dd>{{ formatDate(detail.uploaded_at) }}</dd></div>
                <div><dt>压缩包文件名</dt><dd>{{ detail.package_name || '-' }}</dd></div>
                <div><dt>包含文件</dt><dd>{{ detail.validation.file_count ?? 0 }} 个</dd></div>
                <div><dt>解压后总大小</dt><dd>{{ formatSize(detail.validation.uncompressed_size) }}</dd></div>
              </dl>
              <section v-if="detail.validation.errors?.length" class="validation-message validation-error">
                <strong>未通过检查</strong>
                <p v-for="item in detail.validation.errors" :key="item">{{ item }}</p>
              </section>
              <section v-if="detail.validation.warnings?.length" class="validation-message validation-warning">
                <strong>需要留意</strong>
                <p v-for="item in detail.validation.warnings" :key="item">{{ item }}</p>
              </section>
              <div class="checksum-line"><span>文件校验信息（SHA-256）</span><code>{{ detail.checksum || '-' }}</code></div>
              <details class="manifest-details">
                <summary>查看数据说明文件（manifest.json）</summary>
                <pre>{{ JSON.stringify(detail.manifest || {}, null, 2) }}</pre>
              </details>
            </template>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" @click="detail = null">关闭</button>
            <button v-if="detail.status !== 'imported'" class="danger-button" type="button" @click="deleteTarget = detail">删除记录</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="Boolean(deleteTarget)"
      title="删除数据接收记录"
      :message="`确认删除 ${deleteTarget?.batch_code || ''} 及其上传文件？该操作不会删除学校业务数据。`"
      confirm-label="确认删除"
      danger
      :loading="deleting"
      @close="deleteTarget = null"
      @confirm="removeBatch"
    />
  </AppShell>
</template>
