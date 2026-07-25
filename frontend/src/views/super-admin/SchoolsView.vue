<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  bulkDeleteSchools,
  bulkDisableSchools,
  createSchool,
  deleteSchool,
  getSchools,
  updateSchool,
  type PageResult,
  type SchoolPayload,
  type SchoolRow
} from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import BulkActionBar from '@/components/BulkActionBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EntityFormModal from '@/components/EntityFormModal.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { useBulkDisableDelete } from '@/composables/useBulkDisableDelete'
import { usePageSelection } from '@/composables/usePageSelection'
import type { FormField } from '@/types/forms'
import { superAdminNav } from './nav'

const navItems = superAdminNav('/super-admin/schools')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '启用', value: 'active' },
  { label: '停用', value: 'disabled' },
  { label: '归档', value: 'archived' }
]

const schoolFields: FormField[] = [
  {
    name: 'name',
    label: '学校名称',
    required: true,
    maxlength: 80,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9（）()·\\-\\s]{2,80}$',
    placeholder: '例如：小榄中学'
  },
  {
    name: 'code',
    label: '学校编号',
    required: true,
    maxlength: 32,
    pattern: '^[A-Z0-9][A-Z0-9_-]{1,31}$',
    placeholder: '例如：XLZX'
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
  },
  {
    name: 'contact_name',
    label: '联系人',
    maxlength: 24,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z·\\s]{2,24}$',
    placeholder: '例如：张老师'
  },
  {
    name: 'contact_phone',
    label: '联系电话',
    type: 'tel',
    maxlength: 24,
    pattern: '^(\\+?86[- ]?)?(1[3-9]\\d{9}|0\\d{2,3}[- ]?\\d{7,8})$',
    placeholder: '手机号或固定电话'
  },
  { name: 'address', label: '学校地址', maxlength: 255, placeholder: '学校所在地' },
  { name: 'note', label: '备注', type: 'textarea', placeholder: '内部维护备注，可为空' }
]

const rows = ref<SchoolRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const query = ref('')
const status = ref('')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const formOpen = ref(false)
const editing = ref<SchoolRow | null>(null)
const formErrors = ref<FieldErrors>({})
const formModel = ref<Record<string, string | number | boolean>>(emptySchool())
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

const formTitle = computed(() => (editing.value ? '编辑学校' : '新增学校'))

function emptySchool() {
  return {
    name: '',
    code: '',
    status: 'active',
    contact_name: '',
    contact_phone: '',
    address: '',
    note: ''
  }
}

function toPayload(model: Record<string, string | number | boolean>): SchoolPayload {
  return {
    name: String(model.name || '').trim(),
    code: String(model.code || '').trim().toUpperCase(),
    status: String(model.status || 'active'),
    contact_name: String(model.contact_name || '').trim(),
    contact_phone: String(model.contact_phone || '').trim(),
    address: String(model.address || '').trim(),
    note: String(model.note || '').trim()
  }
}

function setRows(data: PageResult<SchoolRow>) {
  rows.value = data.results
  total.value = data.count
  page.value = data.page
  pageSize.value = data.page_size
  selectedIds.value = selectedIds.value.filter((id) => data.results.some((row) => row.id === id))
}

async function load() {
  loading.value = true
  try {
    setRows(await getSchools({ q: query.value, status: status.value, page: page.value, page_size: pageSize.value }))
  } finally {
    loading.value = false
  }
}

function createRow() {
  editing.value = null
  formErrors.value = {}
  formModel.value = emptySchool()
  formOpen.value = true
}

function editRow(row: SchoolRow) {
  editing.value = row
  formErrors.value = {}
  formModel.value = {
    name: row.name,
    code: row.code,
    status: row.status,
    contact_name: row.contact_name,
    contact_phone: row.contact_phone,
    address: row.address,
    note: row.note
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
      await updateSchool(editing.value.id, payload)
      notice.value = '学校信息已更新。'
    } else {
      await createSchool(payload)
      notice.value = '学校已创建。'
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

function switchStatus(row: SchoolRow, nextStatus: 'active' | 'disabled' | 'archived') {
  const label = nextStatus === 'active' ? '启用' : nextStatus === 'disabled' ? '停用' : '归档'
  ask(`${label}学校`, `确认将 ${row.name} 设置为${label}状态？`, async () => {
    await updateSchool(row.id, {
      name: row.name,
      code: row.code,
      status: nextStatus,
      contact_name: row.contact_name,
      contact_phone: row.contact_phone,
      address: row.address,
      note: row.note
    })
    notice.value = `学校已${label}。`
  })
}

function removeRow(row: SchoolRow) {
  if (row.status === 'active') {
    notice.value = '请先将学校停用或归档，再执行删除。'
    return
  }
  ask('删除学校', `确认删除 ${row.name}？如果学校已有班级、账号或教学记录，系统将保留学校档案。`, async () => {
    await deleteSchool(row.id)
    notice.value = '学校已删除。'
  }, true)
}

const { disableSelected: bulkDisableSelected, deleteSelected: bulkDeleteSelected } = useBulkDisableDelete({
  entityLabel: '学校',
  selectedIds,
  selectedRows,
  selectedCount,
  notice,
  ask,
  clearSelection,
  isActive: (row) => row.status === 'active',
  bulkDisable: bulkDisableSchools,
  bulkDelete: bulkDeleteSchools,
  deleteMessage: '确认删除所选的停用或归档学校？如果学校已有班级、账号或教学记录，系统将保留学校档案。'
})

function download(url: string) {
  window.location.href = url
}

function showImportNotice() {
  notice.value = '批量导入功能尚未开放，请暂时使用“新增学校”逐项登记。'
}

onMounted(load)
</script>

<template>
  <AppShell title="学校信息" eyebrow="超级管理员" :nav-items="navItems" shell-variant="super-admin">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="学校信息"
      description="登记使用平台的学校、联系人和当前使用状态。停用或归档学校不会影响已经形成的教学记录。"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :rows="rows"
      :loading="loading"
      :status-options="statusOptions"
      primary-label="新增学校"
      @create="createRow"
      @search="page = 1; load()"
      @reset="query = ''; status = ''; page = 1; load()"
      @page="page = $event; load()"
      @export="download('/ops/super-admin/schools/export/')"
      @template="download('/ops/super-admin/schools/template/')"
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
                aria-label="选择当前页学校"
                :checked="allPageSelected"
                :indeterminate.prop="partiallyPageSelected"
                @change="togglePage(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>学校编号</th>
            <th>学校名称</th>
            <th>联系人</th>
            <th>联系电话</th>
            <th>班级</th>
            <th>账号</th>
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
              :aria-label="`选择学校 ${row.name}`"
              :checked="selectedIdSet.has(row.id)"
              @change="toggleRow(row.id, ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td>{{ row.code }}</td>
          <td>{{ row.name }}</td>
          <td>{{ row.contact_name || '-' }}</td>
          <td>{{ row.contact_phone || '-' }}</td>
          <td>{{ row.class_count }}</td>
          <td>{{ row.user_count }}</td>
          <td>
            <span class="status-pill" :class="`status-${row.status}`">{{ row.status_label }}</span>
          </td>
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
      :title="formTitle"
      :fields="schoolFields"
      :errors="formErrors"
      :loading="saving"
      submit-label="保存"
      @close="formOpen = false"
      @submit="submitForm"
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
