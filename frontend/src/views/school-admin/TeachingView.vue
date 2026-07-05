<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  bulkSaveTeachingAssignments,
  getTeachingAssignments,
  getTeachingOptions,
  type ClassGroupRow,
  type PageResult,
  type TeachingTeacherRow,
  type TeachingOptions
} from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'

const navItems = [
  { label: '管理首页', path: '/school-admin' },
  { label: '教师管理', path: '/school-admin/teachers' },
  { label: '学生管理', path: '/school-admin/students' },
  { label: '班级管理', path: '/school-admin/classes' },
  { label: '任课关系', path: '/school-admin/teaching' },
  { label: '学科与学科前测', path: '/school-admin/pretests' },
  { label: '模型与训练', path: '/school-admin/models' }
]

const rows = ref<TeachingTeacherRow[]>([])
const options = ref<TeachingOptions>({ classes: [], teachers: [] })
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const query = ref('')
const status = ref('')
const classId = ref('')
const teacherId = ref('')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const batchOpen = ref(false)
const batchTeacherId = ref('')
const batchTeacherName = ref('')
const batchClassIds = ref<number[]>([])
const batchErrors = ref<FieldErrors>({})

const activeClasses = computed(() =>
  options.value.classes.filter((item) => item.status === 'active')
)

const selectedClassIdSet = computed(() => new Set(batchClassIds.value))

const allClassesSelected = computed(
  () => activeClasses.value.length > 0 && activeClasses.value.every((item) => selectedClassIdSet.value.has(item.id))
)

const partialClassesSelected = computed(
  () => batchClassIds.value.length > 0 && !allClassesSelected.value
)

function setRows(data: PageResult<TeachingTeacherRow>) {
  rows.value = data.results
  total.value = data.count
  page.value = data.page
  pageSize.value = data.page_size
}

async function loadOptions() {
  options.value = await getTeachingOptions()
}

async function load() {
  loading.value = true
  try {
    setRows(
      await getTeachingAssignments({
        q: query.value,
        class: classId.value,
        teacher: teacherId.value,
        page: page.value,
        page_size: pageSize.value
      })
    )
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  query.value = ''
  status.value = ''
  classId.value = ''
  teacherId.value = ''
  page.value = 1
  load()
}

function download(url: string) {
  window.location.href = url
}

function teachingExportUrl() {
  const params = new URLSearchParams()
  if (query.value) params.set('q', query.value)
  if (classId.value) params.set('class', classId.value)
  if (teacherId.value) params.set('teacher', teacherId.value)
  const raw = params.toString()
  return `/api/v1/school-admin/teaching/export/${raw ? `?${raw}` : ''}`
}

function classLabel(item: ClassGroupRow) {
  return `${item.grade ? `${item.grade} ` : ''}${item.name}`.trim()
}

function openBatch(row: TeachingTeacherRow) {
  batchErrors.value = {}
  batchTeacherId.value = String(row.teacher.id)
  batchTeacherName.value = row.teacher.display_name || row.teacher.username
  batchClassIds.value = row.classes.map((item) => item.id)
  batchOpen.value = true
}

function toggleClass(id: number, checked: boolean) {
  if (checked) {
    if (!batchClassIds.value.includes(id)) {
      batchClassIds.value = [...batchClassIds.value, id]
    }
    return
  }
  batchClassIds.value = batchClassIds.value.filter((item) => item !== id)
}

function toggleAllClasses(checked: boolean) {
  batchClassIds.value = checked ? activeClasses.value.map((item) => item.id) : []
}

function batchError(field: string) {
  return batchErrors.value[field]?.[0] || ''
}

async function submitBatch() {
  saving.value = true
  notice.value = ''
  batchErrors.value = {}
  try {
    const result = await bulkSaveTeachingAssignments({
      teacher: batchTeacherId.value,
      class_groups: batchClassIds.value
    })
    notice.value = `任教班级已保存：新增 ${result.created_count} 个，保留 ${result.updated_count} 个，移除 ${result.deleted_count} 个。`
    batchOpen.value = false
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      batchErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '任教班级保存失败。'
    }
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadOptions()
  await load()
})
</script>

<template>
  <AppShell title="任课关系" eyebrow="学校管理员" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <div class="extra-filter">
      <label>
        <span>班级</span>
        <select v-model="classId" @change="page = 1; load()">
          <option value="">全部班级</option>
          <option v-for="item in options.classes" :key="item.id" :value="String(item.id)">
            {{ classLabel(item) }}
          </option>
        </select>
      </label>
      <label>
        <span>教师</span>
        <select v-model="teacherId" @change="page = 1; load()">
          <option value="">全部教师</option>
          <option v-for="item in options.teachers" :key="item.id" :value="String(item.id)">
            {{ item.display_name || item.username }}
          </option>
        </select>
      </label>
    </div>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="任课关系"
      description="维护教师与任教班级的对应关系。课程归属后续由课程模块处理。"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :rows="rows"
      :loading="loading"
      :show-template="false"
      :show-import="false"
      @search="page = 1; load()"
      @reset="resetFilters"
      @page="page = $event; load()"
      @export="download(teachingExportUrl())"
    >
      <template #head>
        <thead>
          <tr>
            <th>教师</th>
            <th>登录账号</th>
            <th>任教班级</th>
            <th>班级数</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>
      <template #rows="{ rows: tableRows }">
        <tr v-for="row in tableRows" :key="row.id">
          <td>{{ row.teacher.display_name || '-' }}</td>
          <td>{{ row.teacher.username }}</td>
          <td>
            <div v-if="row.classes.length" class="class-chip-list">
              <span v-for="item in row.classes" :key="item.id" class="class-chip">{{ classLabel(item) }}</span>
            </div>
            <span v-else class="muted-text">未设置任教班级</span>
          </td>
          <td>{{ row.class_count }}</td>
          <td class="row-actions">
            <button type="button" @click="openBatch(row)">批量设置</button>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <Teleport to="body">
      <div v-if="batchOpen" class="modal-backdrop" role="presentation" @click.self="batchOpen = false">
        <section class="entity-modal compact-modal" role="dialog" aria-modal="true" aria-labelledby="teaching-batch-title">
          <header class="modal-header">
            <div>
              <h2 id="teaching-batch-title">设置任教班级</h2>
              <p>{{ batchTeacherName }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="batchOpen = false">×</button>
          </header>

          <div class="batch-modal-body">
            <div class="class-check-header">
              <label class="check-row">
                <input
                  type="checkbox"
                  :checked="allClassesSelected"
                  :indeterminate.prop="partialClassesSelected"
                  @change="toggleAllClasses(($event.target as HTMLInputElement).checked)"
                />
                <em>全选启用班级</em>
              </label>
              <span>已选 {{ batchClassIds.length }} 个班级</span>
            </div>
            <p v-if="batchError('class_groups')" class="field-error">{{ batchError('class_groups') }}</p>
            <p v-if="batchError('teacher')" class="field-error">{{ batchError('teacher') }}</p>

            <div class="class-checkbox-grid">
              <label v-for="item in activeClasses" :key="item.id" class="class-check-item">
                <input
                  type="checkbox"
                  :checked="selectedClassIdSet.has(item.id)"
                  @change="toggleClass(item.id, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ classLabel(item) }}</span>
                <small>{{ item.student_count }} 名学生</small>
              </label>
              <span v-if="!activeClasses.length" class="muted-text">暂无启用班级</span>
            </div>
          </div>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="batchOpen = false">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="submitBatch">
              {{ saving ? '保存中' : '保存任教班级' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>
  </AppShell>
</template>
