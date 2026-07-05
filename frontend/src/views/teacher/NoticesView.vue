<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  archiveTeacherNotice,
  createTeacherNotice,
  deleteTeacherNotice,
  getTeacherClasses,
  getTeacherNotices,
  publishTeacherNotice,
  updateTeacherNotice,
  type NoticePayload,
  type NoticeRow
} from '@/api/teacher'
import type { ClassGroupRow, PageResult } from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/notices')
const rows = ref<PageResult<NoticeRow>>({ count: 0, page: 1, page_size: 20, results: [] })
const classes = ref<ClassGroupRow[]>([])
const loading = ref(false)
const saving = ref(false)
const noticeMessage = ref('')
const query = ref('')
const status = ref('')
const classFilter = ref('')
const modalOpen = ref(false)
const editing = ref<NoticeRow | null>(null)
const fieldErrors = ref<FieldErrors>({})
const confirmOpen = ref(false)
const confirmLoading = ref(false)
const pendingAction = ref<{ type: 'publish' | 'archive' | 'delete'; row: NoticeRow } | null>(null)

const form = reactive<NoticePayload>({
  title: '',
  content: '',
  status: 'draft',
  is_pinned: false,
  target_classes: []
})

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' },
  { label: '归档', value: 'archived' }
]

const summary = computed(() => {
  const published = rows.value.results.filter((item) => item.status === 'published').length
  const drafts = rows.value.results.filter((item) => item.status === 'draft').length
  const pinned = rows.value.results.filter((item) => item.is_pinned).length
  return [
    { label: '公告总数', value: rows.value.count, sub: '符合当前筛选' },
    { label: '本页发布', value: published, sub: '学生可见' },
    { label: '本页草稿', value: drafts, sub: '未发布' },
    { label: '本页置顶', value: pinned, sub: '优先显示' }
  ]
})

async function load(page = 1) {
  loading.value = true
  try {
    rows.value = await getTeacherNotices({
      page,
      q: query.value,
      status: status.value,
      class: classFilter.value
    })
  } catch (error) {
    noticeMessage.value = error instanceof ApiError ? error.message : '公告加载失败。'
  } finally {
    loading.value = false
  }
}

function resetForm() {
  editing.value = null
  fieldErrors.value = {}
  form.title = ''
  form.content = ''
  form.status = 'draft'
  form.is_pinned = false
  form.target_classes = []
}

function openCreate() {
  resetForm()
  modalOpen.value = true
}

function openEdit(row: NoticeRow) {
  editing.value = row
  fieldErrors.value = {}
  form.title = row.title
  form.content = row.content
  form.status = row.status
  form.is_pinned = row.is_pinned
  form.target_classes = row.target_classes.map((item) => item.id)
  modalOpen.value = true
}

function toggleClass(id: number, checked: boolean) {
  const next = new Set(form.target_classes.map((item) => Number(item)))
  if (checked) next.add(id)
  else next.delete(id)
  form.target_classes = Array.from(next)
}

function validateForm() {
  const errors: FieldErrors = {}
  if (!/^([\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]){2,128}$/.test(form.title.trim())) {
    errors.title = ['标题需为 2-128 位，可包含中文、字母、数字和常用标点。']
  }
  if (form.content.trim().length < 2 || form.content.trim().length > 5000) {
    errors.content = ['内容需为 2-5000 个字符。']
  }
  if (!form.target_classes.length) {
    errors.target_classes = ['请选择公告接收班级。']
  }
  fieldErrors.value = errors
  return Object.keys(errors).length === 0
}

async function saveNotice() {
  if (!validateForm()) return
  saving.value = true
  try {
    const payload = { ...form, title: form.title.trim(), content: form.content.trim() }
    const saved = editing.value
      ? await updateTeacherNotice(editing.value.id, payload)
      : await createTeacherNotice(payload)
    rows.value.results = editing.value
      ? rows.value.results.map((item) => (item.id === saved.id ? saved : item))
      : [saved, ...rows.value.results]
    if (!editing.value) rows.value.count += 1
    noticeMessage.value = editing.value ? '公告已更新。' : '公告已创建。'
    modalOpen.value = false
  } catch (error) {
    if (error instanceof ApiError) {
      noticeMessage.value = error.message
      fieldErrors.value = error.errors
    } else {
      noticeMessage.value = '公告保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function ask(type: 'publish' | 'archive' | 'delete', row: NoticeRow) {
  pendingAction.value = { type, row }
  confirmOpen.value = true
}

async function confirmAction() {
  if (!pendingAction.value) return
  confirmLoading.value = true
  try {
    const { type, row } = pendingAction.value
    if (type === 'publish') {
      const updated = await publishTeacherNotice(row.id)
      rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
      noticeMessage.value = '公告已发布。'
    } else if (type === 'archive') {
      const updated = await archiveTeacherNotice(row.id)
      rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
      noticeMessage.value = '公告已归档。'
    } else {
      await deleteTeacherNotice(row.id)
      rows.value.results = rows.value.results.filter((item) => item.id !== row.id)
      rows.value.count -= 1
      noticeMessage.value = '公告已删除。'
    }
    confirmOpen.value = false
  } catch (error) {
    noticeMessage.value = error instanceof ApiError ? error.message : '操作失败。'
  } finally {
    confirmLoading.value = false
  }
}

function resetFilters() {
  query.value = ''
  status.value = ''
  classFilter.value = ''
  load(1)
}

onMounted(async () => {
  await Promise.all([getTeacherClasses().then((items) => (classes.value = items)), load(1)])
})
</script>

<template>
  <AppShell title="公告通知" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="noticeMessage" :message="noticeMessage" />

    <section class="metric-grid teacher-student-summary" aria-label="公告概况">
      <article v-for="item in summary" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </article>
    </section>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="公告通知"
      description="面向本人任教班级发布课堂通知、课程提醒和学习安排。"
      :total="rows.count"
      :page="rows.page"
      :page-size="rows.page_size"
      :rows="rows.results"
      :loading="loading"
      :status-options="statusOptions"
      :show-export="false"
      :show-template="false"
      :show-import="false"
      primary-label="新增公告"
      @create="openCreate"
      @search="load(1)"
      @reset="resetFilters"
      @page="load"
    >
      <template #toolbar-actions>
        <label>
          <span>接收班级</span>
          <select v-model="classFilter" @change="load(1)">
            <option value="">全部班级</option>
            <option v-for="item in classes" :key="item.id" :value="item.id">
              {{ item.grade ? `${item.grade} ` : '' }}{{ item.name }}
            </option>
          </select>
        </label>
      </template>

      <template #head>
        <thead>
          <tr>
            <th>标题</th>
            <th>接收班级</th>
            <th>状态</th>
            <th>置顶</th>
            <th>发布时间</th>
            <th>更新时间</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>

      <template #rows="{ rows: tableRows }">
        <tr v-for="item in tableRows" :key="item.id">
          <td>{{ item.title }}</td>
          <td>
            <div class="class-chip-list notice-class-list">
              <span v-for="classGroup in item.target_classes" :key="classGroup.id" class="class-chip">
                {{ classGroup.grade ? `${classGroup.grade} ` : '' }}{{ classGroup.name }}
              </span>
            </div>
          </td>
          <td><span class="status-pill" :class="`status-${item.status}`">{{ item.status_label }}</span></td>
          <td>{{ item.is_pinned ? '是' : '否' }}</td>
          <td>{{ item.published_at ? new Date(item.published_at).toLocaleString() : '-' }}</td>
          <td>{{ new Date(item.updated_at).toLocaleString() }}</td>
          <td>
            <div class="row-actions">
              <button type="button" @click="openEdit(item)">编辑</button>
              <button v-if="item.status !== 'published'" type="button" @click="ask('publish', item)">发布</button>
              <button v-if="item.status === 'published'" type="button" @click="ask('archive', item)">归档</button>
              <button class="danger-link" type="button" @click="ask('delete', item)">删除</button>
            </div>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <Teleport to="body">
      <div v-if="modalOpen" class="modal-backdrop" role="presentation" @click.self="modalOpen = false">
        <section class="entity-modal compact-modal notice-editor-modal" role="dialog" aria-modal="true" aria-labelledby="notice-editor-title">
          <header class="modal-header">
            <div>
              <h2 id="notice-editor-title">{{ editing ? '编辑公告' : '新增公告' }}</h2>
              <p>公告只会发送给选择的任教班级。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="modalOpen = false">×</button>
          </header>
          <div class="notice-editor-body">
            <label class="span-2">
              <span>标题 <b>*</b></span>
              <input v-model.trim="form.title" maxlength="128" placeholder="例如：本周项目任务提交提醒" />
              <small v-if="fieldErrors.title" class="field-error">{{ fieldErrors.title[0] }}</small>
            </label>
            <label>
              <span>状态</span>
              <select v-model="form.status">
                <option value="draft">草稿</option>
                <option value="published">已发布</option>
                <option value="archived">归档</option>
              </select>
            </label>
            <label class="check-row notice-check-row">
              <input v-model="form.is_pinned" type="checkbox" />
              <em>置顶显示</em>
            </label>
            <label class="span-2">
              <span>内容 <b>*</b></span>
              <textarea v-model.trim="form.content" maxlength="5000" placeholder="填写公告内容"></textarea>
              <small v-if="fieldErrors.content" class="field-error">{{ fieldErrors.content[0] }}</small>
            </label>
            <div class="span-2 question-config-panel">
              <div class="class-check-header">
                <span>接收班级 <b>*</b></span>
                <small>已选 {{ form.target_classes.length }} 个</small>
              </div>
              <div class="class-checkbox-grid">
                <label v-for="item in classes" :key="item.id" class="class-check-item">
                  <input
                    type="checkbox"
                    :checked="form.target_classes.map(Number).includes(item.id)"
                    @change="toggleClass(item.id, ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ item.grade ? `${item.grade} ` : '' }}{{ item.name }}</span>
                  <small>{{ item.student_count }} 名学生</small>
                </label>
              </div>
              <small v-if="fieldErrors.target_classes" class="field-error">{{ fieldErrors.target_classes[0] }}</small>
            </div>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="modalOpen = false">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="saveNotice">
              {{ saving ? '保存中' : '保存公告' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="confirmOpen"
      title="确认操作"
      :message="pendingAction?.type === 'publish'
        ? '确定发布该公告？发布后学生端可见。'
        : pendingAction?.type === 'archive'
          ? '确定归档该公告？归档后学生端不再作为有效公告展示。'
          : '确定删除该公告？已发布公告需要先归档后才能删除。'"
      :danger="pendingAction?.type === 'delete'"
      :confirm-label="pendingAction?.type === 'delete' ? '确认删除' : '确认'"
      :loading="confirmLoading"
      @close="confirmOpen = false"
      @confirm="confirmAction"
    />
  </AppShell>
</template>
