<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import { getResourceReviews, reviewResource } from '@/api/management'
import type { ResourceRow } from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import { schoolAdminNav } from './nav'

const navItems = schoolAdminNav('/school-admin/resource-reviews')
const loading = ref(false)
const notice = ref('')
const query = ref('')
const status = ref('pending')
const rows = ref<ResourceRow[]>([])
const previewRow = ref<ResourceRow | null>(null)
const rejectRow = ref<ResourceRow | null>(null)
const rejectNote = ref('')
const reviewingId = ref<number | null>(null)

const statusTabs = [
  { value: 'pending', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已退回' },
  { value: '', label: '全部' }
]

async function loadRows() {
  loading.value = true
  try {
    const result = await getResourceReviews({ q: query.value, status: status.value, page_size: 60 })
    rows.value = result.results
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源审核列表加载失败。'
  } finally {
    loading.value = false
  }
}

async function approve(item: ResourceRow) {
  if (!window.confirm(`确认允许“${item.title}”进入跨校资源库？`)) return
  reviewingId.value = item.id
  try {
    await reviewResource(item.id, 'approve')
    notice.value = '资源已通过审核。'
    await loadRows()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源审核失败。'
  } finally {
    reviewingId.value = null
  }
}

function openReject(item: ResourceRow) {
  rejectRow.value = item
  rejectNote.value = ''
}

async function submitReject() {
  if (!rejectRow.value) return
  if (!rejectNote.value.trim()) {
    notice.value = '退回时需要填写原因。'
    return
  }
  reviewingId.value = rejectRow.value.id
  try {
    await reviewResource(rejectRow.value.id, 'reject', rejectNote.value.trim())
    notice.value = '资源已退回教师修改。'
    rejectRow.value = null
    rejectNote.value = ''
    await loadRows()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源审核失败。'
  } finally {
    reviewingId.value = null
  }
}

watch(status, loadRows)
onMounted(loadRows)
</script>

<template>
  <AppShell title="资源审核" eyebrow="学校管理员" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section class="resource-review-head">
      <div>
        <h2>跨校资源审核</h2>
        <p>检查教师提交资源的内容、来源和学生项目信息，通过后才进入跨校资源库。</p>
      </div>
      <div class="resource-review-search">
        <input v-model.trim="query" placeholder="搜索标题或教师" @keyup.enter="loadRows" />
        <button class="secondary-button" type="button" :disabled="loading" @click="loadRows">查询</button>
      </div>
    </section>

    <div class="resource-scope-tabs resource-review-tabs">
      <button
        v-for="tab in statusTabs"
        :key="tab.value || 'all'"
        type="button"
        :class="{ active: status === tab.value }"
        @click="status = tab.value"
      >
        {{ tab.label }}
      </button>
    </div>

    <section class="resource-review-list">
      <article v-for="item in rows" :key="item.id">
        <div class="resource-review-summary">
          <span>{{ item.resource_type_label }}</span>
          <div>
            <strong>{{ item.title }}</strong>
            <p>{{ item.content || item.attachment_name || item.external_url || '暂无说明。' }}</p>
          </div>
        </div>
        <dl>
          <div><dt>提交教师</dt><dd>{{ item.owner.display_name }}</dd></div>
          <div><dt>分类学科</dt><dd>{{ item.category_label }} · {{ item.subject?.name || '不限学科' }}</dd></div>
          <div><dt>学生项目</dt><dd>{{ item.project_members.length ? item.project_members.join('、') : '否' }}</dd></div>
          <div><dt>状态</dt><dd>{{ item.publish_status_label }}</dd></div>
        </dl>
        <p v-if="item.review_note" class="resource-review-note">审核说明：{{ item.review_note }}</p>
        <footer>
          <button class="secondary-button" type="button" @click="previewRow = item">预览</button>
          <button
            v-if="item.publish_status === 'pending'"
            class="primary-button"
            type="button"
            :disabled="reviewingId === item.id"
            @click="approve(item)"
          >
            通过
          </button>
          <button
            v-if="item.publish_status === 'pending'"
            class="secondary-button danger"
            type="button"
            :disabled="reviewingId === item.id"
            @click="openReject(item)"
          >
            退回
          </button>
        </footer>
      </article>
      <p v-if="!loading && !rows.length" class="empty">当前没有符合条件的跨校资源。</p>
    </section>

    <div v-if="previewRow" class="modal-backdrop" role="presentation" @click.self="previewRow = null">
      <section class="entity-modal resource-detail-modal" role="dialog" aria-modal="true" aria-labelledby="review-preview-title">
        <header class="modal-header">
          <div><h2 id="review-preview-title">{{ previewRow.title }}</h2><p>{{ previewRow.owner.display_name }}</p></div>
          <button class="icon-button" type="button" aria-label="关闭" @click="previewRow = null">×</button>
        </header>
        <div class="resource-detail-body">
          <ResourcePreview :resource="previewRow" office-mode="view" />
          <aside>
            <h3>审核信息</h3>
            <p>{{ previewRow.content || '暂无补充说明。' }}</p>
            <p v-if="previewRow.project_members.length"><strong>项目成员：</strong>{{ previewRow.project_members.join('、') }}</p>
            <a v-for="file in previewRow.extra_files" :key="file.id" :href="file.file_url" download>{{ file.name }}</a>
          </aside>
        </div>
      </section>
    </div>

    <div v-if="rejectRow" class="modal-backdrop" role="presentation" @click.self="rejectRow = null">
      <section class="entity-modal compact-modal" role="dialog" aria-modal="true" aria-labelledby="resource-reject-title">
        <header class="modal-header">
          <div><h2 id="resource-reject-title">退回资源</h2><p>{{ rejectRow.title }}</p></div>
          <button class="icon-button" type="button" aria-label="关闭" @click="rejectRow = null">×</button>
        </header>
        <div class="resource-reject-body">
          <label><span>退回原因 <b>*</b></span><textarea v-model.trim="rejectNote" rows="5" maxlength="500"></textarea></label>
        </div>
        <footer class="modal-actions">
          <button class="secondary-button" type="button" @click="rejectRow = null">取消</button>
          <button class="primary-button" type="button" :disabled="reviewingId === rejectRow.id" @click="submitReject">确认退回</button>
        </footer>
      </section>
    </div>
  </AppShell>
</template>
