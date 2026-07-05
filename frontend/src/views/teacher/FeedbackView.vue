<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  closeTeacherFeedback,
  getTeacherClasses,
  getTeacherFeedback,
  replyTeacherFeedback,
  type FeedbackRow
} from '@/api/teacher'
import type { ClassGroupRow, PageResult } from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/feedback')
const rows = ref<PageResult<FeedbackRow>>({ count: 0, page: 1, page_size: 20, results: [] })
const classes = ref<ClassGroupRow[]>([])
const loading = ref(false)
const saving = ref(false)
const noticeMessage = ref('')
const query = ref('')
const status = ref('')
const classFilter = ref('')
const categoryFilter = ref('')
const activeFeedback = ref<FeedbackRow | null>(null)
const replyContent = ref('')
const fieldErrors = ref<FieldErrors>({})
const closeConfirmOpen = ref(false)
const closeLoading = ref(false)

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '待回复', value: 'pending' },
  { label: '已回复', value: 'replied' },
  { label: '已关闭', value: 'closed' }
]

const categoryOptions = [
  { label: '全部分类', value: '' },
  { label: '学习问题', value: 'study' },
  { label: '账号问题', value: 'account' },
  { label: '资源问题', value: 'resource' },
  { label: '建议反馈', value: 'suggestion' },
  { label: '其他', value: 'other' }
]

const summary = computed(() => {
  const pending = rows.value.results.filter((item) => item.status === 'pending').length
  const replied = rows.value.results.filter((item) => item.status === 'replied').length
  const closed = rows.value.results.filter((item) => item.status === 'closed').length
  return [
    { label: '留言总数', value: rows.value.count, sub: '符合当前筛选' },
    { label: '本页待回复', value: pending, sub: '需要处理' },
    { label: '本页已回复', value: replied, sub: '等待学生查看' },
    { label: '本页关闭', value: closed, sub: '已结束' }
  ]
})

async function load(page = 1) {
  loading.value = true
  try {
    rows.value = await getTeacherFeedback({
      page,
      q: query.value,
      status: status.value,
      class: classFilter.value,
      category: categoryFilter.value
    })
  } catch (error) {
    noticeMessage.value = error instanceof ApiError ? error.message : '留言反馈加载失败。'
  } finally {
    loading.value = false
  }
}

function openFeedback(row: FeedbackRow) {
  activeFeedback.value = row
  replyContent.value = row.reply_content || ''
  fieldErrors.value = {}
}

async function saveReply() {
  if (!activeFeedback.value) return
  fieldErrors.value = {}
  if (replyContent.value.trim().length < 2 || replyContent.value.trim().length > 3000) {
    fieldErrors.value = { reply_content: ['回复内容需为 2-3000 个字符。'] }
    return
  }
  saving.value = true
  try {
    const updated = await replyTeacherFeedback(activeFeedback.value.id, replyContent.value.trim())
    rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
    activeFeedback.value = updated
    noticeMessage.value = '留言反馈已回复。'
  } catch (error) {
    if (error instanceof ApiError) {
      noticeMessage.value = error.message
      fieldErrors.value = error.errors
    } else {
      noticeMessage.value = '回复保存失败。'
    }
  } finally {
    saving.value = false
  }
}

async function confirmClose() {
  if (!activeFeedback.value) return
  closeLoading.value = true
  try {
    const updated = await closeTeacherFeedback(activeFeedback.value.id)
    rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
    activeFeedback.value = updated
    noticeMessage.value = '留言反馈已关闭。'
    closeConfirmOpen.value = false
  } catch (error) {
    noticeMessage.value = error instanceof ApiError ? error.message : '关闭失败。'
  } finally {
    closeLoading.value = false
  }
}

function resetFilters() {
  query.value = ''
  status.value = ''
  classFilter.value = ''
  categoryFilter.value = ''
  load(1)
}

onMounted(async () => {
  await Promise.all([getTeacherClasses().then((items) => (classes.value = items)), load(1)])
})
</script>

<template>
  <AppShell title="留言反馈" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="noticeMessage" :message="noticeMessage" />

    <section class="metric-grid teacher-student-summary" aria-label="留言反馈概况">
      <article v-for="item in summary" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </article>
    </section>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="留言反馈"
      description="查看任教班级学生提交的问题、建议和反馈，并进行回复处理。"
      :total="rows.count"
      :page="rows.page"
      :page-size="rows.page_size"
      :rows="rows.results"
      :loading="loading"
      :status-options="statusOptions"
      :show-export="false"
      :show-template="false"
      :show-import="false"
      @search="load(1)"
      @reset="resetFilters"
      @page="load"
    >
      <template #toolbar-actions>
        <label>
          <span>班级</span>
          <select v-model="classFilter" @change="load(1)">
            <option value="">全部班级</option>
            <option v-for="item in classes" :key="item.id" :value="item.id">
              {{ item.grade ? `${item.grade} ` : '' }}{{ item.name }}
            </option>
          </select>
        </label>
        <label>
          <span>分类</span>
          <select v-model="categoryFilter" @change="load(1)">
            <option v-for="item in categoryOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
      </template>

      <template #head>
        <thead>
          <tr>
            <th>标题</th>
            <th>学生</th>
            <th>班级</th>
            <th>分类</th>
            <th>状态</th>
            <th>提交时间</th>
            <th>回复时间</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>

      <template #rows="{ rows: tableRows }">
        <tr v-for="item in tableRows" :key="item.id">
          <td>{{ item.title }}</td>
          <td>{{ item.student.display_name || item.student.username }}</td>
          <td>{{ item.class_group.grade ? `${item.class_group.grade} ` : '' }}{{ item.class_group.name }}</td>
          <td>{{ item.category_label }}</td>
          <td><span class="status-pill" :class="`status-${item.status}`">{{ item.status_label }}</span></td>
          <td>{{ new Date(item.created_at).toLocaleString() }}</td>
          <td>{{ item.replied_at ? new Date(item.replied_at).toLocaleString() : '-' }}</td>
          <td>
            <div class="row-actions">
              <button type="button" @click="openFeedback(item)">查看/回复</button>
            </div>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <Teleport to="body">
      <div v-if="activeFeedback" class="modal-backdrop" role="presentation" @click.self="activeFeedback = null">
        <section class="entity-modal compact-modal feedback-modal" role="dialog" aria-modal="true" aria-labelledby="feedback-title">
          <header class="modal-header">
            <div>
              <h2 id="feedback-title">留言反馈</h2>
              <p>{{ activeFeedback.student.display_name || activeFeedback.student.username }} · {{ activeFeedback.category_label }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="activeFeedback = null">×</button>
          </header>
          <div class="feedback-body">
            <article class="feedback-content">
              <header>
                <strong>{{ activeFeedback.title }}</strong>
                <span class="status-pill" :class="`status-${activeFeedback.status}`">{{ activeFeedback.status_label }}</span>
              </header>
              <p>{{ activeFeedback.content }}</p>
              <small>
                {{ activeFeedback.class_group.grade ? `${activeFeedback.class_group.grade} ` : '' }}{{ activeFeedback.class_group.name }}
                · {{ new Date(activeFeedback.created_at).toLocaleString() }}
              </small>
            </article>
            <label class="reply-editor">
              <span>教师回复 <b>*</b></span>
              <textarea v-model.trim="replyContent" maxlength="3000" placeholder="填写给学生的回复"></textarea>
              <small v-if="fieldErrors.reply_content" class="field-error">{{ fieldErrors.reply_content[0] }}</small>
            </label>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="activeFeedback = null">关闭</button>
            <button
              class="secondary-button danger"
              type="button"
              :disabled="saving || activeFeedback.status === 'closed'"
              @click="closeConfirmOpen = true"
            >
              关闭反馈
            </button>
            <button class="primary-button" type="button" :disabled="saving || activeFeedback.status === 'closed'" @click="saveReply">
              {{ saving ? '保存中' : '保存回复' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="closeConfirmOpen"
      title="关闭反馈"
      message="确定关闭该留言反馈？关闭后教师端不再作为待处理事项展示。"
      confirm-label="确认关闭"
      :loading="closeLoading"
      @close="closeConfirmOpen = false"
      @confirm="confirmClose"
    />
  </AppShell>
</template>
