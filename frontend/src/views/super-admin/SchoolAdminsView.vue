<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  bulkDeleteSchoolAdmins,
  bulkDisableSchoolAdmins,
  createSchoolAdmin,
  deleteSchoolAdmin,
  getSchoolAdmins,
  getSchools,
  resetSchoolAdminPassword,
  setSchoolAdminActive,
  updateSchoolAdmin,
  type AccountPayload,
  type AccountRow,
  type PageResult,
  type SchoolRow
} from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import BulkActionBar from '@/components/BulkActionBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EntityFormModal from '@/components/EntityFormModal.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useBulkDisableDelete } from '@/composables/useBulkDisableDelete'
import { usePageSelection } from '@/composables/usePageSelection'
import type { FormField } from '@/types/forms'
import { superAdminNav } from './nav'

type FormModel = Record<string, string | number | boolean>

const navItems = superAdminNav('/super-admin/school-admins')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '启用', value: 'active' },
  { label: '停用', value: 'disabled' }
]

const rows = ref<AccountRow[]>([])
const schools = ref<SchoolRow[]>([])
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
const formErrors = ref<FieldErrors>({})
const resetErrors = ref<FieldErrors>({})
const formModel = ref<FormModel>(emptyAccount())
const resetModel = ref<FormModel>({ password: '' })
const confirmOpen = ref(false)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmDanger = ref(false)
const confirmAction = ref<null | (() => Promise<void>)>(null)

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

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

const schoolOptions = computed(() => {
  const options = schools.value.map((school) => ({ label: `${school.name}（${school.code}）`, value: school.id }))
  return options.length ? options : [{ label: '请先新增学校', value: '' }]
})

const accountFields = computed<FormField[]>(() => {
  const base: FormField[] = [
    {
      name: 'school',
      label: '所属学校',
      type: 'select',
      required: true,
      options: schoolOptions.value
    },
    {
      name: 'username',
      label: '登录账号',
      required: true,
      maxlength: 32,
      pattern: '^[A-Za-z][A-Za-z0-9_]{4,31}$',
      placeholder: '例如：schooladmin1',
      helper: '5-32 位，以字母开头，可包含字母、数字和下划线'
    },
    {
      name: 'display_name',
      label: '姓名',
      required: true,
      maxlength: 24,
      pattern: '^[\\u4e00-\\u9fa5A-Za-z·\\s]{2,24}$',
      placeholder: '例如：学校管理员'
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
    base.splice(4, 0, {
      name: 'password',
      label: '初始密码',
      type: 'password',
      required: true,
      maxlength: 32,
      pattern: '^(?=.*[A-Za-z])(?=.*\\d)[A-Za-z\\d@#$%^&*_.!+\\-]{8,32}$',
      autocomplete: 'new-password',
      helper: '8-32 位，至少包含字母和数字；管理员不能使用 123456'
    })
  }
  return base
})

const resetFields: FormField[] = [
  {
    name: 'password',
    label: '新密码',
    type: 'password',
    required: true,
    maxlength: 32,
    pattern: '^(?=.*[A-Za-z])(?=.*\\d)[A-Za-z\\d@#$%^&*_.!+\\-]{8,32}$',
    autocomplete: 'new-password',
    helper: '8-32 位，至少包含字母和数字；管理员不能使用 123456'
  }
]

const formTitle = computed(() => (editing.value ? '编辑学校管理员' : '新增学校管理员'))

function emptyAccount(): FormModel {
  return {
    school: '',
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
    school: typeof model.school === 'boolean' ? '' : model.school,
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
    setRows(await getSchoolAdmins({ q: query.value, status: status.value, page: page.value, page_size: pageSize.value }))
  } finally {
    loading.value = false
  }
}

async function loadSchools() {
  const data = await getSchools({ page_size: 100 })
  schools.value = data.results
}

function createRow() {
  editing.value = null
  formErrors.value = {}
  const model = emptyAccount()
  const firstSchool = schoolOptions.value[0]?.value
  model.school = typeof firstSchool === 'boolean' ? '' : firstSchool || ''
  formModel.value = model
  formOpen.value = true
}

function editRow(row: AccountRow) {
  editing.value = row
  formErrors.value = {}
  formModel.value = {
    school: row.school?.id || '',
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
      await updateSchoolAdmin(editing.value.id, payload)
      notice.value = '学校管理员已更新。'
    } else {
      await createSchoolAdmin(payload)
      notice.value = '学校管理员已创建。'
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
  ask(next ? '启用账号' : '停用账号', `确认${next ? '启用' : '停用'} ${row.username}？`, async () => {
    await setSchoolAdminActive(row.id, next)
    notice.value = '账号状态已更新。'
  })
}

function removeRow(row: AccountRow) {
  if (row.is_active) {
    notice.value = '请先停用账号，再执行删除。'
    return
  }
  ask('删除账号', `确认删除 ${row.username}？如果该账号已有管理记录，系统将保留停用状态。`, async () => {
    await deleteSchoolAdmin(row.id)
    notice.value = '学校管理员已删除。'
  }, true)
}

const { disableSelected: bulkDisableSelected, deleteSelected: bulkDeleteSelected } = useBulkDisableDelete({
  entityLabel: '学校管理员',
  selectedIds,
  selectedRows,
  selectedCount,
  notice,
  ask,
  clearSelection,
  isActive: (row) => row.is_active,
  bulkDisable: bulkDisableSchoolAdmins,
  bulkDelete: bulkDeleteSchoolAdmins,
  deleteMessage: '确认删除已选已停用学校管理员？已有业务数据时系统会保留停用状态。'
})

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
    await resetSchoolAdminPassword(editing.value.id, String(resetModel.value.password || ''))
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

function showImportNotice() {
  notice.value = '批量导入功能尚未开放，请暂时使用“新增管理员”逐项登记。'
}

onMounted(async () => {
  await loadSchools()
  await load()
})
</script>

<template>
  <AppShell title="学校管理员" eyebrow="超级管理员" :nav-items="navItems" shell-variant="super-admin">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="学校管理员"
      description="为每所学校设置负责本校账号、班级和教学安排的管理员。停用账号后，已有管理记录仍会保留。"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :rows="rows"
      :loading="loading"
      :status-options="statusOptions"
      primary-label="新增管理员"
      @create="createRow"
      @search="page = 1; load()"
      @reset="query = ''; status = ''; page = 1; load()"
      @page="page = $event; load()"
      @export="download('/ops/super-admin/school-admins/export/')"
      @template="download('/ops/super-admin/school-admins/template/')"
      @import="showImportNotice"
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
                aria-label="选择当前页学校管理员"
                :checked="allPageSelected"
                :indeterminate.prop="partiallyPageSelected"
                @change="togglePage(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>登录账号</th>
            <th>姓名</th>
            <th>所属学校</th>
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
              :aria-label="`选择管理员 ${row.username}`"
              :checked="selectedIdSet.has(row.id)"
              @change="toggleRow(row.id, ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td>{{ row.username }}</td>
          <td>{{ row.display_name || '-' }}</td>
          <td>{{ row.school ? `${row.school.name}（${row.school.code}）` : '-' }}</td>
          <td>{{ row.phone || '-' }}</td>
          <td><StatusBadge :active="row.is_active" /></td>
          <td>{{ row.is_first_login ? '是' : '否' }}</td>
          <td>{{ formatDate(row.last_login) }}</td>
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
      title="重置管理员密码"
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
  </AppShell>
</template>
