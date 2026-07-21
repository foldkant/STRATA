<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  bulkDeleteTeachers,
  bulkDisableTeachers,
  createTeacher,
  deleteTeacher,
  getTeachers,
  importTeachers,
  resetTeacherPassword,
  setTeacherActive,
  updateTeacher,
  type AccountPayload,
  type AccountRow,
  type PageResult
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

const navItems = schoolAdminNav('/school-admin/teachers')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '启用', value: 'active' },
  { label: '停用', value: 'disabled' }
]

const rows = ref<AccountRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const query = ref('')
const status = ref('')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const editing = ref<AccountRow | null>(null)
const formOpen = ref(false)
const resetOpen = ref(false)
const importOpen = ref(false)
const formErrors = ref<FieldErrors>({})
const resetErrors = ref<FieldErrors>({})
const importErrors = ref<string[]>([])
const formModel = ref<Record<string, string | number | boolean>>(emptyAccount())
const resetModel = ref<Record<string, string | number | boolean>>({ password: '' })
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

const accountFields = computed<FormField[]>(() => {
  const fields: FormField[] = [
    {
      name: 'username',
      label: '登录账号',
      required: true,
      maxlength: 32,
      pattern: '^[A-Za-z][A-Za-z0-9_]{4,31}$',
      placeholder: '例如：teacher1',
      helper: '5-32 位，以字母开头，可包含字母、数字和下划线'
    },
    {
      name: 'display_name',
      label: '姓名',
      required: true,
      maxlength: 24,
      pattern: '^[\\u4e00-\\u9fa5A-Za-z·\\s]{2,24}$',
      placeholder: '例如：张老师'
    },
    {
      name: 'phone',
      label: '联系电话',
      type: 'tel',
      maxlength: 24,
      pattern: '^(\\+?86[- ]?)?(1[3-9]\\d{9}|0\\d{2,3}[- ]?\\d{7,8})$',
      placeholder: '可为空'
    },
    { name: 'is_active', label: '账号状态', type: 'checkbox' }
  ]
  if (!editing.value) {
    fields.splice(3, 0, {
      name: 'password',
      label: '初始密码',
      type: 'password',
      required: true,
      maxlength: 32,
      pattern: '^[A-Za-z0-9@#$%^&*_.!+\\-]{6,32}$',
      autocomplete: 'new-password',
      helper: '6-32 位；教师允许使用 123456 这类课堂简易密码'
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
    helper: '6-32 位；教师允许使用 123456 这类课堂简易密码'
  }
]

const formTitle = computed(() => (editing.value ? '编辑教师' : '新增教师'))

function emptyAccount() {
  return {
    username: '',
    display_name: '',
    phone: '',
    password: '',
    is_active: true
  }
}

function setRows(data: PageResult<AccountRow>) {
  rows.value = data.results
  total.value = data.count
  page.value = data.page
  pageSize.value = data.page_size
  selectedIds.value = selectedIds.value.filter((id) => data.results.some((row) => row.id === id))
}

function toPayload(model: Record<string, string | number | boolean>): AccountPayload {
  const payload: AccountPayload = {
    username: String(model.username || '').trim(),
    display_name: String(model.display_name || '').trim(),
    phone: String(model.phone || '').trim(),
    is_active: Boolean(model.is_active)
  }
  if (model.password) {
    payload.password = String(model.password)
  }
  return payload
}

async function load() {
  loading.value = true
  try {
    setRows(await getTeachers({ q: query.value, status: status.value, page: page.value, page_size: pageSize.value }))
  } finally {
    loading.value = false
  }
}

function createRow() {
  editing.value = null
  formErrors.value = {}
  formModel.value = emptyAccount()
  formOpen.value = true
}

function editRow(row: AccountRow) {
  editing.value = row
  formErrors.value = {}
  formModel.value = {
    username: row.username,
    display_name: row.display_name,
    phone: row.phone,
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
      await updateTeacher(editing.value.id, payload)
      notice.value = '教师已更新。'
    } else {
      await createTeacher(payload)
      notice.value = '教师已创建。'
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

function toggleActive(row: AccountRow) {
  const next = !row.is_active
  ask(next ? '启用教师' : '停用教师', `确认${next ? '启用' : '停用'} ${row.username}？`, async () => {
    await setTeacherActive(row.id, next)
    notice.value = '教师状态已更新。'
  })
}

function removeRow(row: AccountRow) {
  if (row.is_active) {
    notice.value = '请先停用账号，再执行删除。'
    return
  }
  ask('删除教师', `确认删除 ${row.username}？已有课程、资源或学习数据时系统会拒绝物理删除。`, async () => {
    await deleteTeacher(row.id)
    notice.value = '教师已删除。'
  }, true)
}

function bulkDisableSelected() {
  if (!selectedCount.value) {
    notice.value = '请先选择教师。'
    return
  }
  ask('批量停用教师', `确认停用已选 ${selectedCount.value} 个教师账号？`, async () => {
    const result = await bulkDisableTeachers(selectedIds.value)
    notice.value = result.updated_count ? `已停用 ${result.updated_count} 个教师账号。` : '所选教师账号已是停用状态。'
    clearSelection()
  })
}

function bulkDeleteSelected() {
  if (!selectedCount.value) {
    notice.value = '请先选择教师。'
    return
  }
  const activeRows = selectedRows.value.filter((row) => row.is_active)
  if (activeRows.length) {
    ask(
      '先停用教师',
      `已选教师中有 ${activeRows.length} 个仍处于启用状态。确认后系统只执行批量停用；停用完成后请重新勾选并再次删除。`,
      async () => {
        const result = await bulkDisableTeachers(selectedIds.value)
        notice.value = result.updated_count ? `已停用 ${result.updated_count} 个教师账号，请重新勾选后删除。` : '所选教师账号已是停用状态。'
        clearSelection()
      },
      true
    )
    return
  }
  ask('批量删除教师', `确认删除已选 ${selectedCount.value} 个已停用教师？已有课程、资源或任课关系时系统会保留停用状态。`, async () => {
    const result = await bulkDeleteTeachers(selectedIds.value)
    notice.value = result.message || `已删除 ${result.deleted_count || 0} 个教师。`
    clearSelection()
  }, true)
}

function openReset(row: AccountRow) {
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
    await resetTeacherPassword(editing.value.id, String(resetModel.value.password || ''))
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

function download(url: string) {
  window.location.href = url
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
    const result = await importTeachers(file)
    notice.value = `教师批量导入完成：新增 ${result.created_count} 个，更新 ${result.updated_count} 个。`
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

onMounted(load)
</script>

<template>
  <AppShell title="教师管理" eyebrow="学校管理员" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="教师管理"
      description="维护本校教师账号。教师允许课堂简易密码；删除前必须先停用。"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :rows="rows"
      :loading="loading"
      :status-options="statusOptions"
      primary-label="新增教师"
      @create="createRow"
      @search="page = 1; load()"
      @reset="query = ''; status = ''; page = 1; load()"
      @page="page = $event; load()"
      @export="download(`/api/v1/school-admin/teachers/export/?q=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}`)"
      @template="download('/api/v1/school-admin/teachers/template/')"
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
                aria-label="选择当前页教师"
                :checked="allPageSelected"
                :indeterminate.prop="partiallyPageSelected"
                @change="togglePage(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>登录账号</th>
            <th>姓名</th>
            <th>联系电话</th>
            <th>状态</th>
            <th>首次登录</th>
            <th>最近登录</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>
      <template #rows="{ rows: tableRows }">
        <tr v-for="row in tableRows" :key="row.id">
          <td class="select-col">
            <input
              type="checkbox"
              :aria-label="`选择教师 ${row.username}`"
              :checked="selectedIdSet.has(row.id)"
              @change="toggleRow(row.id, ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td>{{ row.username }}</td>
          <td>{{ row.display_name || '-' }}</td>
          <td>{{ row.phone || '-' }}</td>
          <td><StatusBadge :active="row.is_active" /></td>
          <td>{{ row.is_first_login ? '是' : '否' }}</td>
          <td>{{ row.last_login || '-' }}</td>
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
      :title="formTitle"
      :fields="accountFields"
      :errors="formErrors"
      :loading="saving"
      submit-label="保存"
      @close="formOpen = false"
      @submit="submitForm"
    />

    <EntityFormModal
      v-model:model="resetModel"
      :open="resetOpen"
      title="重置教师密码"
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
      title="批量导入教师"
      :loading="saving"
      :errors="importErrors"
      @close="importOpen = false"
      @submit="submitImport"
    />
  </AppShell>
</template>
