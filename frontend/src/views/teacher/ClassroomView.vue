<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  closeClassroomActivity,
  createClassroomActivity,
  createClassroomSession,
  deleteClassroomActivity,
  deleteClassroomSession,
  finishClassroomSession,
  getClassroomActivities,
  getClassroomSession,
  getClassroomSessions,
  getTeacherCourseOptions,
  openClassroomActivity,
  restartClassroomSession,
  startClassroomSession,
  updateClassroomActivity,
  updateClassroomSession,
  type ClassroomActivityPayload,
  type ClassroomActivityRow,
  type ClassroomSessionPayload,
  type ClassroomSessionRow,
  type CourseRow,
  type LessonRow,
  type TeacherCourseOptions
} from '@/api/teacher'
import type { ClassGroupRow, PageResult } from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

type SessionAction = 'start' | 'restart' | 'finish' | 'delete'
type ActivityAction = 'open' | 'close' | 'delete'

const navItems = teacherNav('/teacher/classroom')
const rows = ref<PageResult<ClassroomSessionRow>>({ count: 0, page: 1, page_size: 20, results: [] })
const options = ref<TeacherCourseOptions>({ subjects: [], classes: [], courses: [], activity_types: [] })
const activities = ref<ClassroomActivityRow[]>([])
const loading = ref(false)
const saving = ref(false)
const activityLoading = ref(false)
const notice = ref('')
const query = ref('')
const status = ref('')
const classFilter = ref('')
const courseFilter = ref('')
const sessionModalOpen = ref(false)
const activeSessionOpen = ref(false)
const activityEditorOpen = ref(false)
const editingSession = ref<ClassroomSessionRow | null>(null)
const activeSession = ref<ClassroomSessionRow | null>(null)
const editingActivity = ref<ClassroomActivityRow | null>(null)
const sessionErrors = ref<FieldErrors>({})
const activityErrors = ref<FieldErrors>({})
const confirmOpen = ref(false)
const confirmLoading = ref(false)
const pendingSessionAction = ref<{ type: SessionAction; row: ClassroomSessionRow } | null>(null)
const activityConfirmOpen = ref(false)
const activityConfirmLoading = ref(false)
const pendingActivityAction = ref<{ type: ActivityAction; row: ClassroomActivityRow } | null>(null)

const sessionForm = reactive<ClassroomSessionPayload>({
  course: '',
  lesson: '',
  class_group: '',
  title: '',
  is_layered: false
})

const activityForm = reactive<ClassroomActivityPayload>({
  activity_type: 'question',
  title: '',
  content: ''
})

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '未开始', value: 'draft' },
  { label: '进行中', value: 'running' },
  { label: '已结束', value: 'finished' }
]

const courseOptions = computed<CourseRow[]>(() => options.value.courses || [])
const classOptions = computed<ClassGroupRow[]>(() => options.value.classes || [])
const activityTypeOptions = computed(() => options.value.activity_types || [])
const selectedCourse = computed(() => courseOptions.value.find((item) => String(item.id) === String(sessionForm.course)) || null)
const lessonOptions = computed<LessonRow[]>(() => selectedCourse.value?.lessons || [])
const courseClassOptions = computed<ClassGroupRow[]>(() => selectedCourse.value?.target_classes || [])
const summary = computed(() => {
  const running = rows.value.results.filter((item) => item.status === 'running').length
  const draft = rows.value.results.filter((item) => item.status === 'draft').length
  const finished = rows.value.results.filter((item) => item.status === 'finished').length
  const openActivities = rows.value.results.reduce((total, item) => total + item.open_activity_count, 0)
  return [
    { label: '课堂总数', value: rows.value.count, sub: '符合当前筛选' },
    { label: '本页进行中', value: running, sub: '正在上课' },
    { label: '本页未开始', value: draft, sub: '待启动' },
    { label: '已结束/活动', value: finished, sub: `${openActivities} 个活动进行中` }
  ]
})

async function loadOptions() {
  options.value = await getTeacherCourseOptions()
}

async function load(page = 1) {
  loading.value = true
  try {
    rows.value = await getClassroomSessions({
      page,
      q: query.value,
      status: status.value,
      class: classFilter.value,
      course: courseFilter.value
    })
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂加载失败。'
  } finally {
    loading.value = false
  }
}

function classLabel(item: ClassGroupRow | null) {
  if (!item) return '-'
  return `${item.grade ? `${item.grade} ` : ''}${item.name}`
}

function lessonLabel(item: LessonRow | null) {
  return item ? item.title : '未选择课时'
}

function resetSessionForm() {
  editingSession.value = null
  sessionErrors.value = {}
  sessionForm.course = courseOptions.value[0]?.id || ''
  sessionForm.lesson = courseOptions.value[0]?.lessons?.[0]?.id || ''
  sessionForm.class_group = courseOptions.value[0]?.target_classes?.[0]?.id || ''
  sessionForm.title = ''
  sessionForm.is_layered = false
}

function openCreateSession() {
  resetSessionForm()
  sessionModalOpen.value = true
}

function openEditSession(row: ClassroomSessionRow) {
  editingSession.value = row
  sessionErrors.value = {}
  sessionForm.course = row.course?.id || ''
  sessionForm.lesson = row.lesson?.id || ''
  sessionForm.class_group = row.class_group?.id || ''
  sessionForm.title = row.title
  sessionForm.is_layered = row.is_layered
  sessionModalOpen.value = true
}

function syncCourseDefaults() {
  const course = selectedCourse.value
  if (!course) {
    sessionForm.lesson = ''
    sessionForm.class_group = ''
    return
  }
  if (!course.lessons?.some((item) => String(item.id) === String(sessionForm.lesson))) {
    sessionForm.lesson = course.lessons?.[0]?.id || ''
  }
  if (!course.target_classes.some((item) => String(item.id) === String(sessionForm.class_group))) {
    sessionForm.class_group = course.target_classes[0]?.id || ''
  }
}

function validateSessionForm() {
  const errors: FieldErrors = {}
  if (!sessionForm.course) errors.course = ['请选择课程。']
  if (!sessionForm.class_group) errors.class_group = ['请选择班级。']
  if (sessionForm.title && !/^([\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]){2,128}$/.test(sessionForm.title.trim())) {
    errors.title = ['课堂标题需为 2-128 位，可包含中文、字母、数字和常用标点。']
  }
  sessionErrors.value = errors
  return Object.keys(errors).length === 0
}

async function saveSession() {
  if (!validateSessionForm()) return
  saving.value = true
  try {
    const payload: ClassroomSessionPayload = {
      course: sessionForm.course,
      lesson: sessionForm.lesson,
      class_group: sessionForm.class_group,
      title: sessionForm.title.trim(),
      is_layered: sessionForm.is_layered
    }
    const saved = editingSession.value
      ? await updateClassroomSession(editingSession.value.id, payload)
      : await createClassroomSession(payload)
    rows.value.results = editingSession.value
      ? rows.value.results.map((item) => (item.id === saved.id ? saved : item))
      : [saved, ...rows.value.results]
    if (!editingSession.value) rows.value.count += 1
    notice.value = editingSession.value ? '课堂已更新。' : '课堂已创建。'
    sessionModalOpen.value = false
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      sessionErrors.value = error.errors
    } else {
      notice.value = '课堂保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function askSession(type: SessionAction, row: ClassroomSessionRow) {
  pendingSessionAction.value = { type, row }
  confirmOpen.value = true
}

async function confirmSessionAction() {
  if (!pendingSessionAction.value) return
  confirmLoading.value = true
  try {
    const { type, row } = pendingSessionAction.value
    if (type === 'start') {
      const updated = await startClassroomSession(row.id)
      updateSessionRow(updated)
      notice.value = '课堂已开始。'
    } else if (type === 'restart') {
      const updated = await restartClassroomSession(row.id)
      updateSessionRow(updated)
      notice.value = '课堂已重新开始。'
    } else if (type === 'finish') {
      const updated = await finishClassroomSession(row.id)
      updateSessionRow(updated)
      notice.value = '课堂已结束。'
      if (activeSession.value?.id === updated.id) {
        activeSession.value = await getClassroomSession(updated.id)
        activities.value = activeSession.value.activities || []
      }
    } else {
      await deleteClassroomSession(row.id)
      rows.value.results = rows.value.results.filter((item) => item.id !== row.id)
      rows.value.count -= 1
      notice.value = '课堂已删除。'
    }
    confirmOpen.value = false
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂操作失败。'
  } finally {
    confirmLoading.value = false
  }
}

function updateSessionRow(updated: ClassroomSessionRow) {
  rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? { ...item, ...updated } : item))
  if (activeSession.value?.id === updated.id) {
    activeSession.value = { ...activeSession.value, ...updated }
  }
}

async function openSession(row: ClassroomSessionRow) {
  activeSessionOpen.value = true
  activityLoading.value = true
  try {
    const session = await getClassroomSession(row.id)
    activeSession.value = session
    activities.value = session.activities || []
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂详情加载失败。'
  } finally {
    activityLoading.value = false
  }
}

function resetActivityForm() {
  editingActivity.value = null
  activityErrors.value = {}
  activityForm.activity_type = activityTypeOptions.value[0]?.value || 'question'
  activityForm.title = ''
  activityForm.content = ''
}

function openCreateActivity() {
  resetActivityForm()
  activityEditorOpen.value = true
}

function openEditActivity(row: ClassroomActivityRow) {
  editingActivity.value = row
  activityErrors.value = {}
  activityForm.activity_type = row.activity_type
  activityForm.title = row.title
  activityForm.content = row.content
  activityEditorOpen.value = true
}

function validateActivityForm() {
  const errors: FieldErrors = {}
  if (!activityForm.activity_type) errors.activity_type = ['请选择活动类型。']
  if (!/^([\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]){2,128}$/.test(activityForm.title.trim())) {
    errors.title = ['活动标题需为 2-128 位，可包含中文、字母、数字和常用标点。']
  }
  if (activityForm.content.trim().length > 5000) {
    errors.content = ['活动内容不能超过 5000 个字符。']
  }
  activityErrors.value = errors
  return Object.keys(errors).length === 0
}

async function saveActivity() {
  if (!activeSession.value || !validateActivityForm()) return
  saving.value = true
  try {
    const payload: ClassroomActivityPayload = {
      activity_type: activityForm.activity_type,
      title: activityForm.title.trim(),
      content: activityForm.content.trim()
    }
    const saved = editingActivity.value
      ? await updateClassroomActivity(editingActivity.value.id, payload)
      : await createClassroomActivity(activeSession.value.id, payload)
    activities.value = editingActivity.value
      ? activities.value.map((item) => (item.id === saved.id ? saved : item))
      : [saved, ...activities.value]
    activeSession.value.activity_count = editingActivity.value ? activeSession.value.activity_count : activeSession.value.activity_count + 1
    updateSessionRow({ ...activeSession.value, activities: undefined })
    notice.value = editingActivity.value ? '课堂活动已更新。' : '课堂活动已创建。'
    activityEditorOpen.value = false
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      activityErrors.value = error.errors
    } else {
      notice.value = '课堂活动保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function askActivity(type: ActivityAction, row: ClassroomActivityRow) {
  pendingActivityAction.value = { type, row }
  activityConfirmOpen.value = true
}

async function confirmActivityAction() {
  if (!pendingActivityAction.value || !activeSession.value) return
  activityConfirmLoading.value = true
  try {
    const { type, row } = pendingActivityAction.value
    if (type === 'open') {
      const updated = await openClassroomActivity(row.id)
      activities.value = activities.value.map((item) => (item.id === updated.id ? updated : item))
      activeSession.value.open_activity_count += row.status === 'open' ? 0 : 1
      updateSessionRow({ ...activeSession.value, activities: undefined })
      notice.value = '课堂活动已开启。'
    } else if (type === 'close') {
      const updated = await closeClassroomActivity(row.id)
      activities.value = activities.value.map((item) => (item.id === updated.id ? updated : item))
      activeSession.value.open_activity_count = Math.max(0, activeSession.value.open_activity_count - (row.status === 'open' ? 1 : 0))
      updateSessionRow({ ...activeSession.value, activities: undefined })
      notice.value = '课堂活动已关闭。'
    } else {
      await deleteClassroomActivity(row.id)
      activities.value = activities.value.filter((item) => item.id !== row.id)
      activeSession.value.activity_count = Math.max(0, activeSession.value.activity_count - 1)
      activeSession.value.open_activity_count = Math.max(0, activeSession.value.open_activity_count - (row.status === 'open' ? 1 : 0))
      updateSessionRow({ ...activeSession.value, activities: undefined })
      notice.value = '课堂活动已删除。'
    }
    activityConfirmOpen.value = false
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '活动操作失败。'
  } finally {
    activityConfirmLoading.value = false
  }
}

function resetFilters() {
  query.value = ''
  status.value = ''
  classFilter.value = ''
  courseFilter.value = ''
  load(1)
}

function sessionActionMessage() {
  if (pendingSessionAction.value?.type === 'delete') return '只有未开始课堂可以删除；进行中或已结束课堂会保留课堂记录。'
  if (pendingSessionAction.value?.type === 'restart') return '重新开始会清空当前投放环节，学生进入课堂后等待教师重新投放。'
  if (pendingSessionAction.value?.type === 'finish') return '结束课堂会同步关闭所有进行中的课堂活动。'
  return '确认开始该课堂？开始后可以开启签到、抢答、即时题等活动。'
}

function activityActionMessage() {
  if (pendingActivityAction.value?.type === 'delete') return '进行中的课堂活动需要先关闭后再删除。'
  if (pendingActivityAction.value?.type === 'close') return '确认关闭该课堂活动？'
  return '确认开启该课堂活动？开启后学生端后续会通过实时通道收到活动状态。'
}

onMounted(async () => {
  await loadOptions()
  await load(1)
})
</script>

<template>
  <AppShell title="课堂教学" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section class="metric-grid teacher-student-summary" aria-label="课堂概况">
      <article v-for="item in summary" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </article>
    </section>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="课堂教学"
      description="选择课程、课时和任教班级创建课堂。正式课堂会进入控制台，按课时学习过程逐环节投放。"
      :total="rows.count"
      :page="rows.page"
      :page-size="rows.page_size"
      :rows="rows.results"
      :loading="loading"
      :status-options="statusOptions"
      :show-export="false"
      :show-template="false"
      :show-import="false"
      primary-label="新建课堂"
      @create="openCreateSession"
      @search="load(1)"
      @reset="resetFilters"
      @page="load"
    >
      <template #toolbar-actions>
        <label>
          <span>课程</span>
          <select v-model="courseFilter" @change="load(1)">
            <option value="">全部课程</option>
            <option v-for="item in courseOptions" :key="item.id" :value="item.id">{{ item.title }}</option>
          </select>
        </label>
        <label>
          <span>班级</span>
          <select v-model="classFilter" @change="load(1)">
            <option value="">全部班级</option>
            <option v-for="item in classOptions" :key="item.id" :value="item.id">{{ classLabel(item) }}</option>
          </select>
        </label>
      </template>

      <template #head>
        <thead>
          <tr>
            <th>课堂</th>
            <th>课程</th>
            <th>课时</th>
            <th>班级</th>
            <th>状态</th>
            <th>模式</th>
            <th>活动</th>
            <th>创建时间</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>

      <template #rows="{ rows: tableRows }">
        <tr v-for="item in tableRows" :key="item.id">
          <td><strong>{{ item.title }}</strong></td>
          <td>{{ item.course?.title || '-' }}</td>
          <td>{{ lessonLabel(item.lesson) }}</td>
          <td>{{ classLabel(item.class_group) }}</td>
          <td><span class="status-pill" :class="`status-${item.status}`">{{ item.status_label }}</span></td>
          <td><span class="status-pill" :class="item.is_layered ? 'status-running' : 'status-draft'">{{ item.is_layered ? '分层' : '普通' }}</span></td>
          <td>{{ item.activity_count }} 个 / {{ item.open_activity_count }} 进行中</td>
          <td>{{ new Date(item.created_at).toLocaleString() }}</td>
          <td>
            <div class="row-actions">
              <RouterLink :to="`/teacher/classroom/${item.id}`">进入课堂</RouterLink>
              <button type="button" @click="openSession(item)">活动</button>
              <button type="button" :disabled="item.status !== 'draft'" @click="openEditSession(item)">编辑</button>
              <button v-if="item.status === 'draft'" type="button" @click="askSession('start', item)">开始</button>
              <button v-if="item.status === 'finished'" type="button" @click="askSession('restart', item)">重新开始</button>
              <button v-if="item.status === 'running'" type="button" @click="askSession('finish', item)">结束</button>
              <button class="danger-link" type="button" :disabled="item.status !== 'draft'" @click="askSession('delete', item)">删除</button>
            </div>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <Teleport to="body">
      <div v-if="sessionModalOpen" class="modal-backdrop" role="presentation" @click.self="sessionModalOpen = false">
        <form class="entity-modal compact-modal course-editor-modal" role="dialog" aria-modal="true" @submit.prevent="saveSession">
          <header class="modal-header">
            <div>
              <h2>{{ editingSession ? '编辑课堂' : '新建课堂' }}</h2>
              <p>只能选择本人课程已绑定的任教班级。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="sessionModalOpen = false">×</button>
          </header>
          <div class="notice-editor-body">
            <label>
              <span>课程 <b>*</b></span>
              <select v-model="sessionForm.course" @change="syncCourseDefaults">
                <option value="">请选择课程</option>
                <option v-for="item in courseOptions" :key="item.id" :value="item.id">{{ item.title }}</option>
              </select>
              <small v-if="sessionErrors.course" class="field-error">{{ sessionErrors.course[0] }}</small>
            </label>
            <label>
              <span>课时</span>
              <select v-model="sessionForm.lesson">
                <option value="">不指定课时</option>
                <option v-for="item in lessonOptions" :key="item.id" :value="item.id">{{ item.title }}</option>
              </select>
              <small v-if="sessionErrors.lesson" class="field-error">{{ sessionErrors.lesson[0] }}</small>
            </label>
            <label>
              <span>班级 <b>*</b></span>
              <select v-model="sessionForm.class_group">
                <option value="">请选择班级</option>
                <option v-for="item in courseClassOptions" :key="item.id" :value="item.id">{{ classLabel(item) }}</option>
              </select>
              <small v-if="sessionErrors.class_group" class="field-error">{{ sessionErrors.class_group[0] }}</small>
            </label>
            <label>
              <span>课堂标题</span>
              <input v-model.trim="sessionForm.title" maxlength="128" placeholder="不填时按课程和班级自动生成" />
              <small v-if="sessionErrors.title" class="field-error">{{ sessionErrors.title[0] }}</small>
            </label>
            <label class="settings-check-row span-2">
              <input v-model="sessionForm.is_layered" type="checkbox" />
              <span>启用分层教学模式，学生端按 A/B/C 层级接收适用题目和分值。</span>
            </label>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="sessionModalOpen = false">取消</button>
            <button class="primary-button" type="submit" :disabled="saving">{{ saving ? '保存中' : '保存课堂' }}</button>
          </footer>
        </form>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="activeSessionOpen && activeSession" class="modal-backdrop" role="presentation" @click.self="activeSessionOpen = false">
        <section class="entity-modal compact-modal classroom-activity-modal" role="dialog" aria-modal="true">
          <header class="modal-header">
            <div>
              <h2>课堂活动</h2>
              <p>{{ activeSession.title }} · {{ classLabel(activeSession.class_group) }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="activeSessionOpen = false">×</button>
          </header>
          <div class="classroom-activity-body">
            <section class="classroom-state-strip">
              <span class="status-pill" :class="`status-${activeSession.status}`">{{ activeSession.status_label }}</span>
              <strong>{{ activeSession.course?.title }}</strong>
              <small>{{ lessonLabel(activeSession.lesson) }}</small>
              <div class="row-actions">
                <button v-if="activeSession.status === 'draft'" type="button" @click="askSession('start', activeSession)">开始课堂</button>
                <button v-if="activeSession.status === 'finished'" type="button" @click="askSession('restart', activeSession)">重新开始</button>
                <button v-if="activeSession.status === 'running'" type="button" @click="askSession('finish', activeSession)">结束课堂</button>
              </div>
            </section>
            <div class="class-check-header">
              <span>共 {{ activities.length }} 个活动</span>
              <button class="primary-button" type="button" :disabled="activeSession.status === 'finished'" @click="openCreateActivity">
                新增活动
              </button>
            </div>
            <div v-if="activityLoading" class="empty">正在加载</div>
            <div v-else-if="activities.length" class="activity-list">
              <article v-for="item in activities" :key="item.id" class="activity-item">
                <header>
                  <div>
                    <strong>{{ item.title }}</strong>
                    <span>{{ item.activity_type_label }} · {{ item.content || '暂无活动说明' }}</span>
                  </div>
                  <span class="status-pill" :class="`status-${item.status}`">{{ item.status_label }}</span>
                </header>
                <footer>
                  <small>{{ new Date(item.created_at).toLocaleString() }}</small>
                  <div class="row-actions">
                    <button type="button" :disabled="item.status === 'open' || activeSession.status === 'finished'" @click="openEditActivity(item)">编辑</button>
                    <button v-if="item.status !== 'open'" type="button" :disabled="activeSession.status !== 'running'" @click="askActivity('open', item)">开启</button>
                    <button v-else type="button" @click="askActivity('close', item)">关闭</button>
                    <button class="danger-link" type="button" :disabled="item.status === 'open'" @click="askActivity('delete', item)">删除</button>
                  </div>
                </footer>
              </article>
            </div>
            <p v-else class="empty">暂无课堂活动</p>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" @click="activeSessionOpen = false">关闭</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="activityEditorOpen" class="modal-backdrop" role="presentation" @click.self="activityEditorOpen = false">
        <form class="entity-modal compact-modal lesson-editor-modal" role="dialog" aria-modal="true" @submit.prevent="saveActivity">
          <header class="modal-header">
            <div>
              <h2>{{ editingActivity ? '编辑活动' : '新增活动' }}</h2>
              <p>{{ activeSession?.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="activityEditorOpen = false">×</button>
          </header>
          <div class="notice-editor-body">
            <label>
              <span>活动类型 <b>*</b></span>
              <select v-model="activityForm.activity_type">
                <option v-for="item in activityTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
              <small v-if="activityErrors.activity_type" class="field-error">{{ activityErrors.activity_type[0] }}</small>
            </label>
            <label>
              <span>活动标题 <b>*</b></span>
              <input v-model.trim="activityForm.title" maxlength="128" />
              <small v-if="activityErrors.title" class="field-error">{{ activityErrors.title[0] }}</small>
            </label>
            <label class="span-2">
              <span>活动说明</span>
              <textarea v-model.trim="activityForm.content" maxlength="5000" placeholder="填写活动题干、讨论要求或任务说明"></textarea>
              <small v-if="activityErrors.content" class="field-error">{{ activityErrors.content[0] }}</small>
            </label>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="activityEditorOpen = false">取消</button>
            <button class="primary-button" type="submit" :disabled="saving">{{ saving ? '保存中' : '保存活动' }}</button>
          </footer>
        </form>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="confirmOpen"
      title="确认课堂操作"
      :message="sessionActionMessage()"
      confirm-label="确认"
      :loading="confirmLoading"
      @close="confirmOpen = false"
      @confirm="confirmSessionAction"
    />

    <ConfirmDialog
      :open="activityConfirmOpen"
      title="确认活动操作"
      :message="activityActionMessage()"
      confirm-label="确认"
      :loading="activityConfirmLoading"
      @close="activityConfirmOpen = false"
      @confirm="confirmActivityAction"
    />
  </AppShell>
</template>
