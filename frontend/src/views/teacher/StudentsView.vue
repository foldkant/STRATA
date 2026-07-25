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
  class: ''
})
const confirmOpen = ref(false)
const confirmLoading = ref(false)
const selectedStudent = ref<StudentRow | null>(null)
const detailStudent = ref<StudentRow | null>(null)
const classListExpanded = ref(false)
const resetMode = ref<'single' | 'bulk'>('single')
const CLASS_PREVIEW_LIMIT = 6
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
  const pretestCompleted = rows.value.results.filter((item) => item.pretest_completed_at).length
  return [
    { label: '当前结果', value: rows.value.count, sub: '符合筛选条件' },
    { label: '本页启用', value: active, sub: '可重置密码' },
    { label: '首次登录', value: firstLogin, sub: '仍需改密' },
    { label: '本页已完成起点诊断', value: pretestCompleted, sub: '分学科形成学习情况' }
  ]
})
const selectedClassLabel = computed(() => {
  if (!filters.class) return '全部班级'
  const current = classes.value.find((item) => String(item.id) === filters.class)
  return current ? `${current.grade ? `${current.grade} ` : ''}${current.name}` : '全部班级'
})
const hiddenClassCount = computed(() => Math.max(classes.value.length - CLASS_PREVIEW_LIMIT, 0))
const visibleClasses = computed(() => {
  if (classListExpanded.value || classes.value.length <= CLASS_PREVIEW_LIMIT) {
    return classes.value
  }

  const preview = classes.value.slice(0, CLASS_PREVIEW_LIMIT)
  const selected = classes.value.find((item) => String(item.id) === filters.class)
  if (!selected || preview.some((item) => item.id === selected.id)) {
    return preview
  }
  return [...preview.slice(0, CLASS_PREVIEW_LIMIT - 1), selected]
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
      class: filters.class
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
  classListExpanded.value = false
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
  classListExpanded.value = false
  load(1)
}

onMounted(async () => {
  await Promise.all([loadOptions(), load(1)])
})
</script>

<template>
  <AppShell title="学生学习情况" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <section class="metric-grid teacher-student-summary" aria-label="学生管理概况">
      <article v-for="item in summary" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </article>
    </section>

    <section class="panel teacher-class-strip" aria-labelledby="teacher-class-strip-title">
      <header class="teacher-class-strip-header">
        <div>
          <h2 id="teacher-class-strip-title">任教班级</h2>
          <p>{{ classes.length }} 个班级 · 当前查看：{{ selectedClassLabel }}</p>
        </div>
      </header>
      <div class="teacher-class-strip-content">
        <p>选择班级后，下方学生名单和学习档案入口将同步筛选。</p>
        <div id="teacher-class-list" class="class-chip-list">
          <button class="class-filter-chip" :class="{ active: !filters.class }" type="button" @click="selectClass('')">
            全部班级
          </button>
          <button
            v-for="item in visibleClasses"
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
        <button
          v-if="hiddenClassCount"
          class="teacher-class-more"
          :class="{ expanded: classListExpanded }"
          type="button"
          aria-controls="teacher-class-list"
          :aria-expanded="classListExpanded"
          @click="classListExpanded = !classListExpanded"
        >
          {{ classListExpanded ? '收起更多班级' : `展开更多班级（还有 ${hiddenClassCount} 个）` }}
          <i aria-hidden="true"></i>
        </button>
      </div>
    </section>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="学生名单"
      description="查找本人任教班级内的学生，并进入每名学生的学习档案。"
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
          <td>{{ item.onboarding_status_label }}</td>
          <td><StatusBadge :active="item.is_active" /></td>
          <td>{{ item.is_first_login ? '是' : '否' }}</td>
          <td>{{ item.last_login ? new Date(item.last_login).toLocaleString() : '-' }}</td>
          <td>
            <div class="row-actions">
              <RouterLink :to="`/teacher/students/${item.id}/profile`">查看学习档案</RouterLink>
              <button type="button" @click="detailStudent = item">账号信息</button>
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
              <h2 id="student-detail-title">学生账号信息</h2>
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
              <div><dt>小组号</dt><dd>{{ detailStudent.current_group_no || '-' }}</dd></div>
              <div><dt>积分</dt><dd>{{ detailStudent.score }}</dd></div>
              <div><dt>入门状态</dt><dd>{{ detailStudent.onboarding_status_label }}</dd></div>
              <div><dt>学习起点诊断完成</dt><dd>{{ detailStudent.pretest_completed_at ? new Date(detailStudent.pretest_completed_at).toLocaleString() : '-' }}</dd></div>
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

<style scoped>
.teacher-class-strip {
  display: grid;
  gap: 12px;
}

.teacher-class-strip-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.teacher-class-strip-header h2 {
  margin: 0;
  color: var(--ink);
  font-size: 18px;
}

.teacher-class-strip-header p,
.teacher-class-strip-content > p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.teacher-class-strip-content {
  display: grid;
  justify-items: start;
  gap: 12px;
  min-width: 0;
}

.teacher-class-strip-content > p {
  margin: 0;
}

.teacher-class-more {
  min-height: 44px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  padding: 0 10px;
  margin-left: -10px;
  cursor: pointer;
  transition: background-color 160ms ease-out;
}

.teacher-class-more:hover {
  background: #eef4f0;
}

.teacher-class-more:focus-visible {
  outline: 3px solid rgba(23, 72, 63, 0.2);
  outline-offset: 2px;
}

.teacher-class-more i {
  width: 9px;
  height: 9px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(45deg);
  transition: transform 180ms ease-out;
}

.teacher-class-more.expanded i {
  transform: rotate(225deg);
}

.class-filter-chip {
  min-height: 44px;
}

@media (max-width: 640px) {
  .teacher-class-strip {
    padding: 16px;
  }

  .teacher-class-strip-header {
    align-items: flex-start;
  }

  .class-chip-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .class-filter-chip {
    min-width: 0;
    justify-content: space-between;
  }

  .teacher-class-more {
    width: 100%;
    justify-content: center;
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .teacher-class-more,
  .teacher-class-more i {
    transition: none;
  }
}
</style>
