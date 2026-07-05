<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  bulkDeleteClasses,
  bulkDisableClasses,
  bulkCreateClasses,
  createClass,
  deleteClass,
  getClasses,
  graduateClasses,
  promoteClasses,
  updateClass,
  type ClassGroupBulkPayload,
  type ClassGroupPayload,
  type ClassGroupRow,
  type PageResult
} from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import BulkActionBar from '@/components/BulkActionBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EntityFormModal from '@/components/EntityFormModal.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { usePageSelection } from '@/composables/usePageSelection'
import type { FormField } from '@/types/forms'

type FormModel = Record<string, string | number | boolean>

const navItems = [
  { label: '管理首页', path: '/school-admin' },
  { label: '教师管理', path: '/school-admin/teachers' },
  { label: '学生管理', path: '/school-admin/students' },
  { label: '班级管理', path: '/school-admin/classes' },
  { label: '任课关系', path: '/school-admin/teaching' },
  { label: '学科与学科前测', path: '/school-admin/pretests' },
  { label: '模型与训练', path: '/school-admin/models' }
]

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '启用', value: 'active' },
  { label: '停用', value: 'disabled' },
  { label: '归档', value: 'archived' }
]

const classFields: FormField[] = [
  {
    name: 'name',
    label: '班级名称',
    required: true,
    maxlength: 64,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9（）()·\\-\\s]{1,64}$',
    placeholder: '例如：高一1班'
  },
  {
    name: 'grade',
    label: '年级',
    maxlength: 32,
    placeholder: '例如：高一'
  },
  {
    name: 'entry_year',
    label: '入学年份',
    type: 'number',
    placeholder: '例如：2026'
  },
  {
    name: 'status',
    label: '状态',
    type: 'select',
    required: true,
    options: [
      { label: '启用', value: 'active' },
      { label: '停用', value: 'disabled' },
      { label: '归档', value: 'archived' }
    ]
  }
]

const bulkClassFields: FormField[] = [
  {
    name: 'grade',
    label: '年级',
    required: true,
    maxlength: 32,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9届级年高初小\\s\\-]{1,32}$',
    placeholder: '例如：高一',
    helper: '将生成“高一1班、高一2班……”这样的班级名称。'
  },
  {
    name: 'entry_year',
    label: '入学年份',
    type: 'number',
    required: true,
    placeholder: '例如：2026'
  },
  {
    name: 'class_count',
    label: '班级数量',
    type: 'number',
    required: true,
    placeholder: '例如：12',
    helper: '一次最多创建 80 个班级。'
  },
  {
    name: 'start_no',
    label: '起始班号',
    type: 'number',
    required: true,
    placeholder: '默认 1'
  },
  {
    name: 'status',
    label: '状态',
    type: 'select',
    required: true,
    options: [
      { label: '启用', value: 'active' },
      { label: '停用', value: 'disabled' },
      { label: '归档', value: 'archived' }
    ]
  }
]

const promoteFields: FormField[] = [
  {
    name: 'from_grade',
    label: '原年级',
    required: true,
    maxlength: 32,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9届级年高初小\\s\\-]{1,32}$',
    placeholder: '例如：高一'
  },
  {
    name: 'to_grade',
    label: '目标年级',
    required: true,
    maxlength: 32,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9届级年高初小\\s\\-]{1,32}$',
    placeholder: '例如：高二',
    helper: '会将“高一1班”更新为“高二1班”，并保留入学年份。'
  }
]

const rows = ref<ClassGroupRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const query = ref('')
const status = ref('')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const editing = ref<ClassGroupRow | null>(null)
const formOpen = ref(false)
const bulkOpen = ref(false)
const promoteOpen = ref(false)
const formErrors = ref<FieldErrors>({})
const bulkErrors = ref<FieldErrors>({})
const promoteErrors = ref<FieldErrors>({})
const formModel = ref<FormModel>(emptyClass())
const bulkModel = ref<FormModel>(emptyBulkClass())
const promoteModel = ref<FormModel>(emptyPromote())
const confirmOpen = ref(false)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmDanger = ref(false)
const confirmAction = ref<null | (() => Promise<void>)>(null)
const {
  selectedIds,
  selectedIdSet,
  selectedRows,
  selectedCount,
  allPageSelected,
  partiallyPageSelected,
  toggleRow,
  togglePage,
  clearSelection
} = usePageSelection(rows)

function emptyClass(): FormModel {
  return {
    name: '',
    grade: '',
    entry_year: '',
    status: 'active'
  }
}

function emptyBulkClass(): FormModel {
  const year = new Date().getFullYear()
  return {
    grade: '高一',
    entry_year: year,
    class_count: 12,
    start_no: 1,
    status: 'active'
  }
}

function emptyPromote(): FormModel {
  return {
    from_grade: '高一',
    to_grade: '高二'
  }
}

function setRows(data: PageResult<ClassGroupRow>) {
  rows.value = data.results
  total.value = data.count
  page.value = data.page
  pageSize.value = data.page_size
  selectedIds.value = selectedIds.value.filter((id) => data.results.some((row) => row.id === id))
}

function toPayload(model: FormModel): ClassGroupPayload {
  return {
    name: String(model.name || '').trim(),
    grade: String(model.grade || '').trim(),
    entry_year: model.entry_year ? String(model.entry_year).trim() : '',
    status: String(model.status || 'active')
  }
}

function toBulkPayload(model: FormModel): ClassGroupBulkPayload {
  return {
    grade: String(model.grade || '').trim(),
    entry_year: typeof model.entry_year === 'boolean' ? '' : model.entry_year || '',
    class_count: typeof model.class_count === 'boolean' ? '' : model.class_count || '',
    start_no: typeof model.start_no === 'boolean' ? 1 : model.start_no || 1,
    status: String(model.status || 'active')
  }
}

function toPromotePayload(model: FormModel) {
  return {
    from_grade: String(model.from_grade || '').trim(),
    to_grade: String(model.to_grade || '').trim()
  }
}

async function load() {
  loading.value = true
  try {
    setRows(await getClasses({ q: query.value, status: status.value, page: page.value, page_size: pageSize.value }))
  } finally {
    loading.value = false
  }
}

function createRow() {
  editing.value = null
  formErrors.value = {}
  formModel.value = emptyClass()
  formOpen.value = true
}

function openBulkCreate() {
  bulkErrors.value = {}
  bulkModel.value = emptyBulkClass()
  bulkOpen.value = true
}

function openPromote() {
  promoteErrors.value = {}
  promoteModel.value = emptyPromote()
  promoteOpen.value = true
}

function editRow(row: ClassGroupRow) {
  editing.value = row
  formErrors.value = {}
  formModel.value = {
    name: row.name,
    grade: row.grade,
    entry_year: row.entry_year || '',
    status: row.status
  }
  formOpen.value = true
}

async function submitForm() {
  saving.value = true
  notice.value = ''
  formErrors.value = {}
  try {
    const payload = toPayload(formModel.value)
    if (editing.value) {
      await updateClass(editing.value.id, payload)
      notice.value = '班级已更新。'
    } else {
      await createClass(payload)
      notice.value = '班级已创建。'
    }
    formOpen.value = false
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      formErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '保存失败。'
    }
  } finally {
    saving.value = false
  }
}

async function submitBulkForm() {
  saving.value = true
  notice.value = ''
  bulkErrors.value = {}
  try {
    const result = await bulkCreateClasses(toBulkPayload(bulkModel.value))
    notice.value = `已批量新增 ${result.created_count} 个班级。`
    bulkOpen.value = false
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      bulkErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '批量新增失败。'
    }
  } finally {
    saving.value = false
  }
}

async function submitPromoteForm() {
  saving.value = true
  notice.value = ''
  promoteErrors.value = {}
  try {
    const result = await promoteClasses(toPromotePayload(promoteModel.value))
    notice.value = `已完成升班，更新 ${result.promoted_count} 个班级。`
    promoteOpen.value = false
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      promoteErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '升班失败。'
    }
  } finally {
    saving.value = false
  }
}

function ask(title: string, message: string, action: () => Promise<void>, danger = false) {
  confirmTitle.value = title
  confirmMessage.value = message
  confirmAction.value = action
  confirmDanger.value = danger
  confirmOpen.value = true
}

async function runConfirm() {
  if (!confirmAction.value) return
  saving.value = true
  notice.value = ''
  try {
    await confirmAction.value()
    confirmOpen.value = false
    await load()
  } catch (exc) {
    notice.value = exc instanceof ApiError ? exc.message : '操作失败。'
  } finally {
    saving.value = false
  }
}

function switchStatus(row: ClassGroupRow, nextStatus: 'active' | 'disabled' | 'archived') {
  const label = nextStatus === 'active' ? '启用' : nextStatus === 'disabled' ? '停用' : '归档'
  ask(`${label}班级`, `确认将 ${row.name} 设置为${label}状态？`, async () => {
    await updateClass(row.id, {
      name: row.name,
      grade: row.grade,
      entry_year: row.entry_year || '',
      status: nextStatus
    })
    notice.value = `班级已${label}。`
  })
}

function removeRow(row: ClassGroupRow) {
  if (row.status === 'active') {
    notice.value = '请先将班级停用或归档，再执行删除。'
    return
  }
  ask('删除班级', `确认删除 ${row.name}？已有学生、学习行为或模型数据时系统会拒绝物理删除。`, async () => {
    await deleteClass(row.id)
    notice.value = '班级已删除。'
  }, true)
}

function bulkDisableSelected() {
  if (!selectedCount.value) {
    notice.value = '请先选择班级。'
    return
  }
  ask('批量停用班级', `确认停用已选 ${selectedCount.value} 个班级？已归档班级会保持归档状态。`, async () => {
    const result = await bulkDisableClasses(selectedIds.value)
    notice.value = result.updated_count ? `已停用 ${result.updated_count} 个班级。` : '所选班级无需停用。'
    clearSelection()
  })
}

function bulkDeleteSelected() {
  if (!selectedCount.value) {
    notice.value = '请先选择班级。'
    return
  }
  const activeRows = selectedRows.value.filter((row) => row.status === 'active')
  if (activeRows.length) {
    ask(
      '先停用班级',
      `已选班级中有 ${activeRows.length} 个仍处于启用状态。确认后系统只执行批量停用；停用完成后请重新勾选并再次删除。`,
      async () => {
        const result = await bulkDisableClasses(selectedIds.value)
        notice.value = result.updated_count ? `已停用 ${result.updated_count} 个班级，请重新勾选后删除。` : '所选班级无需停用。'
        clearSelection()
      },
      true
    )
    return
  }
  ask('批量删除班级', `确认删除已选 ${selectedCount.value} 个非启用班级？已有学生、学习行为或模型数据时系统会保留当前状态。`, async () => {
    const result = await bulkDeleteClasses(selectedIds.value)
    notice.value = result.message || `已删除 ${result.deleted_count || 0} 个班级。`
    clearSelection()
  }, true)
}

function bulkGraduateSelected() {
  if (!selectedCount.value) {
    notice.value = '请先选择班级。'
    return
  }
  const studentCount = selectedRows.value.reduce((sum, row) => sum + row.student_count, 0)
  ask(
    '批量毕业归档',
    `确认将已选 ${selectedCount.value} 个班级设为毕业归档？系统会同时停用这些班级下的学生账号，涉及当前列表统计 ${studentCount} 名学生。`,
    async () => {
      const result = await graduateClasses(selectedIds.value)
      notice.value = `已毕业归档 ${result.graduated_count || 0} 个班级，并停用 ${result.disabled_students || 0} 个学生账号。`
      clearSelection()
    },
    true
  )
}

function download(url: string) {
  window.location.href = url
}

onMounted(load)
</script>

<template>
  <AppShell title="班级管理" eyebrow="学校管理员" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="班级管理"
      description="维护本校年级、班级和学生归属。删除班级前必须先停用或归档。"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :rows="rows"
      :loading="loading"
      :status-options="statusOptions"
      primary-label="新增班级"
      bulk-label="批量新增班级"
      :show-template="false"
      :show-import="false"
      @create="createRow"
      @bulk="openBulkCreate"
      @search="page = 1; load()"
      @reset="query = ''; status = ''; page = 1; load()"
      @page="page = $event; load()"
      @export="download('/school-admin/classes/export/')"
    >
      <template #bulk-actions>
        <BulkActionBar
          :selected-count="selectedCount"
          :total-on-page="rows.length"
          :loading="saving"
          extra-label="批量毕业"
          extra-danger
          @clear="clearSelection"
          @disable="bulkDisableSelected"
          @extra="bulkGraduateSelected"
          @delete="bulkDeleteSelected"
        />
      </template>
      <template #actions-extra>
        <button class="secondary-button" type="button" @click="openPromote">批量升班</button>
      </template>
      <template #head>
        <thead>
          <tr>
            <th class="select-col">
              <input
                type="checkbox"
                aria-label="选择当前页班级"
                :checked="allPageSelected"
                :indeterminate.prop="partiallyPageSelected"
                @change="togglePage(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>年级</th>
            <th>班级</th>
            <th>入学年份</th>
            <th>学生</th>
            <th>教师</th>
            <th>状态</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>
      <template #rows="{ rows: tableRows }">
        <tr v-for="row in tableRows" :key="row.id">
          <td class="select-col">
            <input
              type="checkbox"
              :aria-label="`选择班级 ${row.name}`"
              :checked="selectedIdSet.has(row.id)"
              @change="toggleRow(row.id, ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td>{{ row.grade || '-' }}</td>
          <td>{{ row.name }}</td>
          <td>{{ row.entry_year || '-' }}</td>
          <td>{{ row.student_count }}</td>
          <td>{{ row.teacher_count }}</td>
          <td><span class="status-pill" :class="`status-${row.status}`">{{ row.status_label }}</span></td>
          <td class="row-actions">
            <button type="button" @click="editRow(row)">编辑</button>
            <button v-if="row.status !== 'active'" type="button" @click="switchStatus(row, 'active')">启用</button>
            <button v-if="row.status === 'active'" type="button" @click="switchStatus(row, 'disabled')">停用</button>
            <button v-if="row.status !== 'archived'" type="button" @click="switchStatus(row, 'archived')">归档</button>
            <button type="button" class="danger-link" @click="removeRow(row)">删除</button>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <EntityFormModal
      v-model:model="formModel"
      :open="formOpen"
      :title="editing ? '编辑班级' : '新增班级'"
      :fields="classFields"
      :errors="formErrors"
      :loading="saving"
      submit-label="保存"
      @close="formOpen = false"
      @submit="submitForm"
    />

    <EntityFormModal
      v-model:model="bulkModel"
      :open="bulkOpen"
      title="批量新增班级"
      :fields="bulkClassFields"
      :errors="bulkErrors"
      :loading="saving"
      submit-label="生成班级"
      @close="bulkOpen = false"
      @submit="submitBulkForm"
    />

    <EntityFormModal
      v-model:model="promoteModel"
      :open="promoteOpen"
      title="批量升班"
      :fields="promoteFields"
      :errors="promoteErrors"
      :loading="saving"
      submit-label="确认升班"
      @close="promoteOpen = false"
      @submit="submitPromoteForm"
    />

    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :message="confirmMessage"
      :danger="confirmDanger"
      :loading="saving"
      confirm-label="确认"
      @close="confirmOpen = false"
      @confirm="runConfirm"
    />
  </AppShell>
</template>
