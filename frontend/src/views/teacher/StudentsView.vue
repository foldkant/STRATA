<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  bulkResetTeacherStudentPasswords,
  getTeacherClasses,
  getTeacherStudents,
  resetTeacherStudentPassword,
} from '@/api/teacher'
import type { ClassGroupRow, PageResult, StudentRow } from '@/api/management'
import { usePageSelection } from '@/composables/usePageSelection'
import AppShell from '@/layouts/AppShell.vue'
import BulkActionBar from '@/components/BulkActionBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/students')
const rows = ref<PageResult<StudentRow>>({ count: 0, page: 1, page_size: 20, results: [] })
const classes = ref<ClassGroupRow[]>([])
const loading = ref(false)
const notice = ref('')
const query = ref('')
const status = ref('')
const filters = reactive({
  class: '',
  layer: ''
})
const confirmOpen = ref(false)
const confirmLoading = ref(false)
const selectedStudent = ref<StudentRow | null>(null)
const detailStudent = ref<StudentRow | null>(null)
const resetMode = ref<'single' | 'bulk'>('single')
const tableRows = computed(() => rows.value.results)
const selectableRows = computed(() => rows.value.results.filter((item) => item.is_active))
const {
  selectedIds,
  selectedIdSet,
  selectedCount,
  allPageSelected,
  toggleRow,
  togglePage,
  clearSelection
} = usePageSelection(selectableRows)

const summary = computed(() => {
  const active = rows.value.results.filter((item) => item.is_active).length
  const firstLogin = rows.value.results.filter((item) => item.is_first_login).length
  const unlayered = rows.value.results.filter((item) => !item.current_layer).length
  return [
    { label: '当前结果', value: rows.value.count, sub: '符合筛选条件' },
    { label: '本页启用', value: active, sub: '可重置密码' },
    { label: '首次登录', value: firstLogin, sub: '仍需改密' },
    { label: '本页未分层', value: unlayered, sub: '等待分层建议' }
  ]
})

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '启用', value: 'active' },
  { label: '停用', value: 'disabled' }
]

async function load(page = 1) {
  loading.value = true
  try {
    rows.value = await getTeacherStudents({
      page,
      q: query.value,
      status: status.value,
      class: filters.class,
      layer: filters.layer
    })
    selectedIds.value = selectedIds.value.filter((id) => rows.value.results.some((item) => item.id === id))
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学生数据加载失败。'
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  classes.value = await getTeacherClasses()
}

function resetFilters() {
  query.value = ''
  status.value = ''
  filters.class = ''
  filters.layer = ''
  load(1)
}

function openReset(row: StudentRow) {
  detailStudent.value = null
  selectedStudent.value = row
  resetMode.value = 'single'
  confirmOpen.value = true
}

function openBulkReset() {
  if (!selectedCount.value) {
    notice.value = '请先选择学生。'
    return
  }
  resetMode.value = 'bulk'
  selectedStudent.value = null
  confirmOpen.value = true
}

async function confirmReset() {
  confirmLoading.value = true
  try {
    if (resetMode.value === 'bulk') {
      const result = await bulkResetTeacherStudentPasswords(selectedIds.value)
      const updatedMap = new Map(result.results.map((item) => [item.id, item]))
      rows.value.results = rows.value.results.map((item) => updatedMap.get(item.id) || item)
      notice.value = `已将 ${result.updated_count} 个学生密码重置为 123456。`
      clearSelection()
    } else if (selectedStudent.value) {
      const updated = await resetTeacherStudentPassword(selectedStudent.value.id)
      rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
      notice.value = `${updated.display_name || updated.username} 的密码已重置为 123456。`
    }
    confirmOpen.value = false
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '密码重置失败。'
  } finally {
    confirmLoading.value = false
  }
}

function selectClass(classId: number | '') {
  filters.class = classId === '' ? '' : String(classId)
  load(1)
}

onMounted(async () => {
  await Promise.all([loadOptions(), load(1)])
})
</script>

<template>
  <AppShell title="学生管理" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <section class="metric-grid teacher-student-summary" aria-label="学生管理概况">
      <article v-for="item in summary" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </article>
    </section>

    <section class="panel teacher-class-strip">
      <div class="panel-heading split">
        <div>
          <h2>任教班级</h2>
          <p>点击班级快速筛选学生；班级范围由学校管理员配置。</p>
        </div>
      </div>
      <div class="class-chip-list">
        <button class="class-filter-chip" :class="{ active: !filters.class }" type="button" @click="selectClass('')">
          全部班级
        </button>
        <button
          v-for="item in classes"
          :key="item.id"
          class="class-filter-chip"
          :class="{ active: filters.class === String(item.id) }"
          type="button"
          @click="selectClass(item.id)"
        >
          {{ item.grade ? `${item.grade} ` : '' }}{{ item.name }}
          <span>{{ item.student_count }}</span>
        </button>
      </div>
    </section>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="学生管理"
      description="查询本人任教班级内的学生账号；课堂需要时可将学生密码重置为 123456。"
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
      <template #bulk-actions>
        <BulkActionBar
          :selected-count="selectedCount"
          :total-on-page="rows.results.length"
          :loading="loading || confirmLoading"
          disable-label="批量重置为 123456"
          :show-delete="false"
          @clear="clearSelection"
          @disable="openBulkReset"
        />
      </template>

      <template #toolbar-actions>
        <label>
          <span>任教班级</span>
          <AppSelect v-model="filters.class" @change="load(1)">
            <option value="">全部班级</option>
            <option v-for="item in classes" :key="item.id" :value="item.id">
              {{ item.grade ? `${item.grade} ` : '' }}{{ item.name }}
            </option>
          </AppSelect>
        </label>
        <label>
          <span>分层</span>
          <AppSelect v-model="filters.layer" @change="load(1)">
            <option value="">全部分层</option>
            <option value="A">A 拓展挑战层</option>
            <option value="B">B 核心发展层</option>
            <option value="C">C 基础提升层</option>
            <option value="unassigned">未分层</option>
          </AppSelect>
        </label>
      </template>

      <template #head>
        <thead>
          <tr>
            <th class="select-col">
              <input
                type="checkbox"
                :checked="allPageSelected"
                :disabled="!rows.results.length"
                aria-label="选择当前页"
                @change="togglePage(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>账号</th>
            <th>姓名</th>
            <th>学号</th>
            <th>班级</th>
            <th>分层</th>
            <th>入门状态</th>
            <th>账号状态</th>
            <th>首次登录</th>
            <th>最近登录</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>

      <template #rows="{ rows: tableRows }">
        <tr v-for="item in tableRows" :key="item.id">
          <td class="select-col">
            <input
              type="checkbox"
              :checked="selectedIdSet.has(item.id)"
              :disabled="!item.is_active"
              :aria-label="`选择 ${item.display_name || item.username}`"
              @change="toggleRow(item.id, ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td>{{ item.username }}</td>
          <td>{{ item.display_name || '-' }}</td>
          <td>{{ item.student_no || '-' }}</td>
          <td>
            <span v-if="item.class_group">
              {{ item.class_group.grade ? `${item.class_group.grade} ` : '' }}{{ item.class_group.name }}
            </span>
            <span v-else class="muted-text">未分班</span>
          </td>
          <td>{{ item.current_layer_label || '未分层' }}</td>
          <td>{{ item.onboarding_status_label }}</td>
          <td><StatusBadge :active="item.is_active" /></td>
          <td>{{ item.is_first_login ? '是' : '否' }}</td>
          <td>{{ item.last_login ? new Date(item.last_login).toLocaleString() : '-' }}</td>
          <td>
            <div class="row-actions">
              <button type="button" @click="detailStudent = item">查看</button>
              <button type="button" :disabled="!item.is_active" @click="openReset(item)">重置为 123456</button>
            </div>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <ConfirmDialog
      :open="confirmOpen"
      title="重置学生密码"
      :message="resetMode === 'bulk'
        ? `确定将已选 ${selectedCount} 个学生的密码统一重置为 123456？学生下次登录后会被标记为首次登录。`
        : `确定将 ${selectedStudent?.display_name || selectedStudent?.username || '该学生'} 的密码重置为 123456？学生下次登录后会被标记为首次登录。`"
      confirm-label="确认重置"
      :loading="confirmLoading"
      @close="confirmOpen = false"
      @confirm="confirmReset"
    />

    <Teleport to="body">
      <div v-if="detailStudent" class="modal-backdrop" role="presentation" @click.self="detailStudent = null">
        <section class="entity-modal compact-modal student-detail-modal" role="dialog" aria-modal="true" aria-labelledby="student-detail-title">
          <header class="modal-header">
            <div>
              <h2 id="student-detail-title">学生详情</h2>
              <p>{{ detailStudent.display_name || detailStudent.username }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="detailStudent = null">×</button>
          </header>
          <div class="student-detail-body">
            <dl>
              <div><dt>登录账号</dt><dd>{{ detailStudent.username }}</dd></div>
              <div><dt>姓名</dt><dd>{{ detailStudent.display_name || '-' }}</dd></div>
              <div><dt>学号</dt><dd>{{ detailStudent.student_no || '-' }}</dd></div>
              <div><dt>联系电话</dt><dd>{{ detailStudent.phone || '-' }}</dd></div>
              <div>
                <dt>班级</dt>
                <dd>
                  <span v-if="detailStudent.class_group">
                    {{ detailStudent.class_group.grade ? `${detailStudent.class_group.grade} ` : '' }}{{ detailStudent.class_group.name }}
                  </span>
                  <span v-else>-</span>
                </dd>
              </div>
              <div><dt>当前分层</dt><dd>{{ detailStudent.current_layer_label || '未分层' }}</dd></div>
              <div><dt>小组号</dt><dd>{{ detailStudent.current_group_no || '-' }}</dd></div>
              <div><dt>积分</dt><dd>{{ detailStudent.score }}</dd></div>
              <div><dt>入门状态</dt><dd>{{ detailStudent.onboarding_status_label }}</dd></div>
              <div><dt>前测完成</dt><dd>{{ detailStudent.pretest_completed_at ? new Date(detailStudent.pretest_completed_at).toLocaleString() : '-' }}</dd></div>
              <div><dt>账号状态</dt><dd>{{ detailStudent.is_active ? '启用' : '停用' }}</dd></div>
              <div><dt>最近登录</dt><dd>{{ detailStudent.last_login ? new Date(detailStudent.last_login).toLocaleString() : '-' }}</dd></div>
            </dl>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" @click="detailStudent = null">关闭</button>
            <button
              class="primary-button"
              type="button"
              :disabled="!detailStudent.is_active"
              @click="openReset(detailStudent)"
            >
              重置为 123456
            </button>
          </footer>
        </section>
      </div>
    </Teleport>
  </AppShell>
</template>
