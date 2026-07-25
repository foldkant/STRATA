<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  bulkDeleteStudents,
  bulkDisableStudents,
  createStudent,
  deleteStudent,
  getClasses,
  getStudents,
  importStudents,
  resetStudentPassword,
  setStudentActive,
  updateStudent,
  type ClassGroupRow,
  type PageResult,
  type StudentPayload,
  type StudentRow
} from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import BulkActionBar from '@/components/BulkActionBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EntityFormModal from '@/components/EntityFormModal.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import XlsxImportModal from '@/components/XlsxImportModal.vue'
import { usePageSelection } from '@/composables/usePageSelection'
import type { FormField } from '@/types/forms'
import { schoolAdminNav } from './nav'

type FormModel = Record<string, string | number | boolean>

const navItems = schoolAdminNav('/school-admin/students')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '启用', value: 'active' },
  { label: '停用', value: 'disabled' }
]

const rows = ref<StudentRow[]>([])
const classes = ref<ClassGroupRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const query = ref('')
const status = ref('')
const classId = ref('')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const editing = ref<StudentRow | null>(null)
const formOpen = ref(false)
const resetOpen = ref(false)
const importOpen = ref(false)
const formErrors = ref<FieldErrors>({})
const resetErrors = ref<FieldErrors>({})
const importErrors = ref<string[]>([])
const formModel = ref<FormModel>(emptyStudent())
const resetModel = ref<FormModel>({ password: '' })
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

const classOptions = computed(() => {
  const options = classes.value.map((item) => ({
    label: `${item.grade ? `${item.grade} ` : ''}${item.name}`,
    value: item.id
  }))
  return [{ label: '暂不分配，学生首次使用时自选', value: '' }, ...options]
})

const studentFields = computed<FormField[]>(() => {
  const fields: FormField[] = [
    {
      name: 'class_group',
      label: '所属班级',
      type: 'select',
      options: classOptions.value,
      helper: '新生可以暂不分配班级，首次使用时由学生自选。'
    },
    {
      name: 'username',
      label: '登录账号',
      required: true,
      maxlength: 32,
      pattern: '^[A-Za-z][A-Za-z0-9_]{4,31}$',
      placeholder: '例如：student1',
      helper: '5-32 位，以字母开头，可包含字母、数字和下划线'
    },
    {
      name: 'display_name',
      label: '姓名',
      required: true,
      maxlength: 24,
      pattern: '^[\\u4e00-\\u9fa5A-Za-z·\\s]{2,24}$',
      placeholder: '例如：李同学'
    },
    {
      name: 'student_no',
      label: '学号',
      maxlength: 32,
      pattern: '^[A-Za-z0-9_-]{1,32}$',
      placeholder: '可后补，例如：20260101',
      helper: '新生入学时可以先为空，后续通过批量导入按账号匹配更新。'
    },
    {
      name: 'phone',
      label: '联系电话',
      type: 'tel',
      maxlength: 24,
      pattern: '^(\\+?86[- ]?)?(1[3-9]\\d{9}|0\\d{2,3}[- ]?\\d{7,8})$',
      placeholder: '可为空'
    },
    {
      name: 'current_group_no',
      label: '小组号',
      type: 'number',
      placeholder: '可为空'
    },
    {
      name: 'score',
      label: '积分',
      type: 'number',
      placeholder: '默认 0'
    },
    { name: 'is_active', label: '账号状态', type: 'checkbox' }
  ]
  if (!editing.value) {
    fields.splice(5, 0, {
      name: 'password',
      label: '初始密码',
      type: 'password',
      required: true,
      maxlength: 32,
      pattern: '^[A-Za-z0-9@#$%^&*_.!+\\-]{6,32}$',
      autocomplete: 'new-password',
      helper: '6-32 位；学生允许使用 123456 这类课堂简易密码'
    })
  }
  return fields
})

const resetFields: FormField[] = [
  {
    name: 'password',
    label: '新密码',
    type: 'password',
    required: true,
    maxlength: 32,
    pattern: '^[A-Za-z0-9@#$%^&*_.!+\\-]{6,32}$',
    autocomplete: 'new-password',
    helper: '6-32 位；学生允许使用 123456 这类课堂简易密码'
  }
]

function emptyStudent(): FormModel {
  return {
    class_group: '',
    username: '',
    display_name: '',
    student_no: '',
    phone: '',
    password: '',
    current_group_no: '',
    score: 0,
    is_active: true
  }
}

function setRows(data: PageResult<StudentRow>) {
  rows.value = data.results
  total.value = data.count
  page.value = data.page
  pageSize.value = data.page_size
  selectedIds.value = selectedIds.value.filter((id) => data.results.some((row) => row.id === id))
}

function toPayload(model: FormModel): StudentPayload {
  const payload: StudentPayload = {
    class_group: typeof model.class_group === 'boolean' ? '' : model.class_group,
    username: String(model.username || '').trim(),
    display_name: String(model.display_name || '').trim(),
    student_no: String(model.student_no || '').trim(),
    phone: String(model.phone || '').trim(),
    current_group_no: model.current_group_no ? String(model.current_group_no).trim() : '',
    score: typeof model.score === 'boolean' ? 0 : model.score || 0,
    is_active: Boolean(model.is_active)
  }
  if (model.password) {
    payload.password = String(model.password)
  }
  return payload
}

async function loadClasses() {
  const data = await getClasses({ page_size: 100 })
  classes.value = data.results
}

async function load() {
  loading.value = true
  try {
    setRows(
      await getStudents({
        q: query.value,
        status: status.value,
        class: classId.value,
        page: page.value,
        page_size: pageSize.value
      })
    )
  } finally {
    loading.value = false
  }
}

function createRow() {
  editing.value = null
  formErrors.value = {}
  const model = emptyStudent()
  formModel.value = model
  formOpen.value = true
}

function editRow(row: StudentRow) {
  editing.value = row
  formErrors.value = {}
  formModel.value = {
    class_group: row.class_group?.id || '',
    username: row.username,
    display_name: row.display_name,
    student_no: row.student_no,
    phone: row.phone,
    current_group_no: row.current_group_no || '',
    score: row.score,
    is_active: row.is_active
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
      await updateStudent(editing.value.id, payload)
      notice.value = '学生已更新。'
    } else {
      await createStudent(payload)
      notice.value = '学生已创建。'
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

function toggleActive(row: StudentRow) {
  const next = !row.is_active
  ask(next ? '启用学生' : '停用学生', `确认${next ? '启用' : '停用'} ${row.username}？`, async () => {
    await setStudentActive(row.id, next)
    notice.value = '学生状态已更新。'
  })
}

function removeRow(row: StudentRow) {
  if (row.is_active) {
    notice.value = '请先停用账号，再执行删除。'
    return
  }
  ask('删除学生', `确认删除 ${row.username}？已有学习行为或分层记录时系统会拒绝物理删除。`, async () => {
    await deleteStudent(row.id)
    notice.value = '学生已删除。'
  }, true)
}

function bulkDisableSelected() {
  if (!selectedCount.value) {
    notice.value = '请先选择学生。'
    return
  }
  ask('批量停用学生', `确认停用已选 ${selectedCount.value} 个学生账号？`, async () => {
    const result = await bulkDisableStudents(selectedIds.value)
    notice.value = result.updated_count ? `已停用 ${result.updated_count} 个学生账号。` : '所选学生账号已是停用状态。'
    clearSelection()
  })
}

function bulkDeleteSelected() {
  if (!selectedCount.value) {
    notice.value = '请先选择学生。'
    return
  }
  const activeRows = selectedRows.value.filter((row) => row.is_active)
  if (activeRows.length) {
    ask(
      '先停用学生',
      `已选学生中有 ${activeRows.length} 个仍处于启用状态。确认后系统只执行批量停用；停用完成后请重新勾选并再次删除。`,
      async () => {
        const result = await bulkDisableStudents(selectedIds.value)
        notice.value = result.updated_count ? `已停用 ${result.updated_count} 个学生账号，请重新勾选后删除。` : '所选学生账号已是停用状态。'
        clearSelection()
      },
      true
    )
    return
  }
  ask('批量删除学生', `确认删除已选 ${selectedCount.value} 个已停用学生？已有学习行为、特征快照或分层记录时系统会保留停用状态。`, async () => {
    const result = await bulkDeleteStudents(selectedIds.value)
    notice.value = result.message || `已删除 ${result.deleted_count || 0} 个学生。`
    clearSelection()
  }, true)
}

function openReset(row: StudentRow) {
  editing.value = row
  resetErrors.value = {}
  resetModel.value = { password: '' }
  resetOpen.value = true
}

async function submitReset() {
  if (!editing.value) return
  saving.value = true
  notice.value = ''
  resetErrors.value = {}
  try {
    await resetStudentPassword(editing.value.id, String(resetModel.value.password || ''))
    notice.value = '密码已重置。'
    resetOpen.value = false
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      resetErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '重置失败。'
    }
  } finally {
    saving.value = false
  }
}

function resetFilters() {
  query.value = ''
  status.value = ''
  classId.value = ''
  page.value = 1
  load()
}

function download(url: string) {
  window.location.href = url
}

function studentsExportUrl() {
  const params = new URLSearchParams()
  if (query.value) params.set('q', query.value)
  if (status.value) params.set('status', status.value)
  if (classId.value) params.set('class', classId.value)
  const raw = params.toString()
  return `/api/v1/school-admin/students/export/${raw ? `?${raw}` : ''}`
}

function openImport() {
  importErrors.value = []
  importOpen.value = true
}

async function submitImport(file: File) {
  saving.value = true
  notice.value = ''
  importErrors.value = []
  try {
    const result = await importStudents(file)
    notice.value = `学生批量导入完成：新增 ${result.created_count} 个，更新 ${result.updated_count} 个。`
    importOpen.value = false
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      importErrors.value = exc.errors.rows || exc.errors.file || [exc.message]
      notice.value = exc.message
    } else {
      notice.value = '导入失败。'
    }
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadClasses()
  await load()
})
</script>

<template>
  <AppShell title="学生管理" eyebrow="学校教学管理" :nav-items="navItems" shell-variant="school-admin">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <div class="extra-filter">
      <label>
        <span>班级</span>
        <AppSelect v-model="classId" @change="page = 1; load()">
          <option value="">全部班级</option>
          <option v-for="item in classes" :key="item.id" :value="String(item.id)">
            {{ item.grade ? `${item.grade} ` : '' }}{{ item.name }}
          </option>
        </AppSelect>
      </label>
    </div>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="学生管理"
      description="维护本校学生账号和班级信息。学生的学习情况由任课教师依据具体学科、课程和学习材料确认；删除账号前需先停用。"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :rows="rows"
      :loading="loading"
      :status-options="statusOptions"
      primary-label="新增学生"
      @create="createRow"
      @search="page = 1; load()"
      @reset="resetFilters"
      @page="page = $event; load()"
      @export="download(studentsExportUrl())"
      @template="download('/api/v1/school-admin/students/template/')"
      @import="openImport"
    >
      <template #bulk-actions>
        <BulkActionBar
          :selected-count="selectedCount"
          :total-on-page="rows.length"
          :loading="saving"
          @clear="clearSelection"
          @disable="bulkDisableSelected"
          @delete="bulkDeleteSelected"
        />
      </template>
      <template #head>
        <thead>
          <tr>
            <th class="select-col">
              <input
                type="checkbox"
                aria-label="选择当前页学生"
                :checked="allPageSelected"
                :indeterminate.prop="partiallyPageSelected"
                @change="togglePage(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>登录账号</th>
            <th>姓名</th>
            <th>学号</th>
            <th>班级</th>
            <th>使用状态</th>
            <th>小组</th>
            <th>积分</th>
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
              :aria-label="`选择学生 ${row.username}`"
              :checked="selectedIdSet.has(row.id)"
              @change="toggleRow(row.id, ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td>{{ row.username }}</td>
          <td>{{ row.display_name || '-' }}</td>
          <td>{{ row.student_no || '-' }}</td>
          <td>
            <template v-if="row.class_group">
              {{ row.class_group.grade ? `${row.class_group.grade} ` : '' }}{{ row.class_group.name }}
            </template>
            <span v-else class="muted-text">未选班级</span>
          </td>
          <td>
            <span
              class="status-pill"
              :class="row.onboarding_status === 'active' ? 'status-active' : 'status-warning'"
            >
              {{ row.onboarding_status_label || (row.is_first_use ? '首次使用' : '未完成') }}
            </span>
          </td>
          <td>{{ row.current_group_no || '-' }}</td>
          <td>{{ row.score }}</td>
          <td><StatusBadge :active="row.is_active" /></td>
          <td class="row-actions">
            <button type="button" @click="editRow(row)">编辑</button>
            <button type="button" @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</button>
            <button type="button" @click="openReset(row)">重置密码</button>
            <button type="button" class="danger-link" @click="removeRow(row)">删除</button>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <EntityFormModal
      v-model:model="formModel"
      :open="formOpen"
      :title="editing ? '编辑学生' : '新增学生'"
      :fields="studentFields"
      :errors="formErrors"
      :loading="saving"
      submit-label="保存"
      @close="formOpen = false"
      @submit="submitForm"
    />

    <EntityFormModal
      v-model:model="resetModel"
      :open="resetOpen"
      title="重置学生密码"
      :fields="resetFields"
      :errors="resetErrors"
      :loading="saving"
      submit-label="保存新密码"
      @close="resetOpen = false"
      @submit="submitReset"
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

    <XlsxImportModal
      :open="importOpen"
      title="批量导入学生"
      :loading="saving"
      :errors="importErrors"
      @close="importOpen = false"
      @submit="submitImport"
    />
  </AppShell>
</template>
