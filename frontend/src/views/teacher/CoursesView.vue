<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  archiveTeacherCourse,
  archiveTeacherLesson,
  createTeacherCourse,
  createTeacherLesson,
  deleteTeacherCourseCover,
  deleteTeacherCourse,
  deleteTeacherLesson,
  getTeacherCourseOptions,
  getTeacherCourses,
  getTeacherLessons,
  publishTeacherCourse,
  publishTeacherLesson,
  saveTeacherCourseClasses,
  updateTeacherCourse,
  updateTeacherLesson,
  uploadTeacherCourseCover,
  type CoursePayload,
  type CourseRow,
  type LessonPayload,
  type LessonRow,
  type TeacherCourseOptions
} from '@/api/teacher'
import type { ClassGroupRow, PageResult, SubjectRow } from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

type PendingCourseAction = 'publish' | 'archive' | 'delete'
type PendingLessonAction = 'publish' | 'archive' | 'delete'

const navItems = teacherNav('/teacher/courses')
const rows = ref<PageResult<CourseRow>>({ count: 0, page: 1, page_size: 20, results: [] })
const options = ref<TeacherCourseOptions>({ subjects: [], classes: [], courses: [], activity_types: [] })
const loading = ref(false)
const saving = ref(false)
const lessonLoading = ref(false)
const notice = ref('')
const query = ref('')
const status = ref('')
const subjectFilter = ref('')
const courseModalOpen = ref(false)
const classModalOpen = ref(false)
const lessonModalOpen = ref(false)
const lessonEditorOpen = ref(false)
const courseErrors = ref<FieldErrors>({})
const lessonErrors = ref<FieldErrors>({})
const editingCourse = ref<CourseRow | null>(null)
const activeCourse = ref<CourseRow | null>(null)
const selectedCoverFile = ref<File | null>(null)
const coverPreviewUrl = ref('')
const removeCoverAfterSave = ref(false)
const lessons = ref<LessonRow[]>([])
const editingLesson = ref<LessonRow | null>(null)
const selectedClassIds = ref<number[]>([])
const confirmOpen = ref(false)
const confirmLoading = ref(false)
const pendingCourseAction = ref<{ type: PendingCourseAction; row: CourseRow } | null>(null)
const lessonConfirmOpen = ref(false)
const lessonConfirmLoading = ref(false)
const pendingLessonAction = ref<{ type: PendingLessonAction; row: LessonRow } | null>(null)

const courseForm = reactive<CoursePayload>({
  subject: '',
  title: '',
  introduction: '',
  teaching_model: 'pbl',
  status: 'draft',
  class_groups: []
})

const lessonForm = reactive<LessonPayload>({
  title: '',
  content: '',
  sort_order: '',
  status: 'draft'
})

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' }
]

const subjectOptions = computed<SubjectRow[]>(() => options.value.subjects || [])
const classOptions = computed<ClassGroupRow[]>(() => options.value.classes || [])
const summary = computed(() => {
  const published = rows.value.results.filter((item) => item.is_active).length
  const draft = rows.value.results.filter((item) => !item.is_active).length
  const lessonCount = rows.value.results.reduce((total, item) => total + item.lesson_count, 0)
  const classCount = rows.value.results.reduce((total, item) => total + item.class_count, 0)
  return [
    { label: '课程总数', value: rows.value.count, sub: '符合当前筛选' },
    { label: '本页发布', value: published, sub: '学生可见' },
    { label: '本页草稿', value: draft, sub: '待完善' },
    { label: '本页课时', value: lessonCount, sub: `${classCount} 个班级绑定` }
  ]
})

async function loadOptions() {
  options.value = await getTeacherCourseOptions()
}

async function load(page = 1) {
  loading.value = true
  try {
    rows.value = await getTeacherCourses({
      page,
      q: query.value,
      status: status.value,
      subject: subjectFilter.value
    })
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程加载失败。'
  } finally {
    loading.value = false
  }
}

function resetCourseForm() {
  editingCourse.value = null
  courseErrors.value = {}
  selectedCoverFile.value = null
  coverPreviewUrl.value = ''
  removeCoverAfterSave.value = false
  courseForm.subject = subjectOptions.value[0]?.id || ''
  courseForm.title = ''
  courseForm.introduction = ''
  courseForm.teaching_model = 'pbl'
  courseForm.status = 'draft'
  courseForm.class_groups = []
}

function openCreateCourse() {
  resetCourseForm()
  courseModalOpen.value = true
}

function openEditCourse(row: CourseRow) {
  editingCourse.value = row
  courseErrors.value = {}
  selectedCoverFile.value = null
  coverPreviewUrl.value = row.cover_url || ''
  removeCoverAfterSave.value = false
  courseForm.subject = row.subject?.id || ''
  courseForm.title = row.title
  courseForm.introduction = row.introduction
  courseForm.teaching_model = row.teaching_model
  courseForm.status = row.status
  courseForm.class_groups = row.target_classes.map((item) => item.id)
  courseModalOpen.value = true
}

function onCourseCoverChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const errors: FieldErrors = { ...courseErrors.value }
  delete errors.cover
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    errors.cover = ['封面仅支持 JPG、PNG、WEBP 图片。']
    courseErrors.value = errors
    input.value = ''
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    errors.cover = ['封面不能超过 5MB。']
    courseErrors.value = errors
    input.value = ''
    return
  }
  if (coverPreviewUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(coverPreviewUrl.value)
  }
  selectedCoverFile.value = file
  coverPreviewUrl.value = URL.createObjectURL(file)
  removeCoverAfterSave.value = false
  courseErrors.value = errors
}

function removeCourseCover() {
  if (coverPreviewUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(coverPreviewUrl.value)
  }
  selectedCoverFile.value = null
  coverPreviewUrl.value = ''
  removeCoverAfterSave.value = Boolean(editingCourse.value?.cover_url)
}

function validateCourseForm() {
  const errors: FieldErrors = {}
  if (!/^([\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]){2,128}$/.test(courseForm.title.trim())) {
    errors.title = ['课程名称需为 2-128 位，可包含中文、字母、数字和常用标点。']
  }
  if (!courseForm.subject) {
    errors.subject = ['请选择学科。']
  }
  if (courseForm.introduction.trim().length > 5000) {
    errors.introduction = ['课程简介不能超过 5000 个字符。']
  }
  courseErrors.value = errors
  return Object.keys(errors).length === 0
}

async function saveCourse() {
  if (!validateCourseForm()) return
  saving.value = true
  try {
    const payload: CoursePayload = {
      ...courseForm,
      title: courseForm.title.trim(),
      introduction: courseForm.introduction.trim()
    }
    let saved = editingCourse.value
      ? await updateTeacherCourse(editingCourse.value.id, payload)
      : await createTeacherCourse(payload)
    if (selectedCoverFile.value) {
      saved = await uploadTeacherCourseCover(saved.id, selectedCoverFile.value)
    } else if (removeCoverAfterSave.value && saved.cover_url) {
      saved = await deleteTeacherCourseCover(saved.id)
    }
    rows.value.results = editingCourse.value
      ? rows.value.results.map((item) => (item.id === saved.id ? saved : item))
      : [saved, ...rows.value.results]
    if (!editingCourse.value) rows.value.count += 1
    notice.value = editingCourse.value ? '课程已更新。' : '课程已创建。'
    courseModalOpen.value = false
    selectedCoverFile.value = null
    coverPreviewUrl.value = ''
    removeCoverAfterSave.value = false
    await loadOptions()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      courseErrors.value = error.errors
    } else {
      notice.value = '课程保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function askCourse(type: PendingCourseAction, row: CourseRow) {
  pendingCourseAction.value = { type, row }
  confirmOpen.value = true
}

async function confirmCourseAction() {
  if (!pendingCourseAction.value) return
  confirmLoading.value = true
  try {
    const { type, row } = pendingCourseAction.value
    if (type === 'publish') {
      const updated = await publishTeacherCourse(row.id)
      rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
      notice.value = '课程已发布。'
    } else if (type === 'archive') {
      const updated = await archiveTeacherCourse(row.id)
      rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
      notice.value = '课程已停用。'
    } else {
      await deleteTeacherCourse(row.id)
      rows.value.results = rows.value.results.filter((item) => item.id !== row.id)
      rows.value.count -= 1
      notice.value = '课程已删除。'
    }
    await loadOptions()
    confirmOpen.value = false
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '操作失败。'
  } finally {
    confirmLoading.value = false
  }
}

function openClassManager(row: CourseRow) {
  activeCourse.value = row
  selectedClassIds.value = row.target_classes.map((item) => item.id)
  courseErrors.value = {}
  classModalOpen.value = true
}

function toggleClass(id: number, checked: boolean) {
  const next = new Set(selectedClassIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedClassIds.value = Array.from(next)
}

function selectAllClasses() {
  selectedClassIds.value = classOptions.value.map((item) => item.id)
}

async function saveClassScope() {
  if (!activeCourse.value) return
  saving.value = true
  try {
    const updated = await saveTeacherCourseClasses(activeCourse.value.id, selectedClassIds.value)
    rows.value.results = rows.value.results.map((item) => (item.id === updated.id ? updated : item))
    activeCourse.value = updated
    notice.value = '课程班级范围已更新。'
    classModalOpen.value = false
    await loadOptions()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      courseErrors.value = error.errors
    } else {
      notice.value = '班级范围保存失败。'
    }
  } finally {
    saving.value = false
  }
}

async function openLessons(row: CourseRow) {
  activeCourse.value = row
  lessonModalOpen.value = true
  lessonLoading.value = true
  lessonErrors.value = {}
  try {
    lessons.value = await getTeacherLessons(row.id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课时加载失败。'
  } finally {
    lessonLoading.value = false
  }
}

function resetLessonForm() {
  editingLesson.value = null
  lessonErrors.value = {}
  lessonForm.title = ''
  lessonForm.content = ''
  lessonForm.sort_order = lessons.value.length ? Math.max(...lessons.value.map((item) => item.sort_order)) + 10 : 10
  lessonForm.status = 'draft'
}

function openCreateLesson() {
  resetLessonForm()
  lessonEditorOpen.value = true
}

function openEditLesson(row: LessonRow) {
  editingLesson.value = row
  lessonErrors.value = {}
  lessonForm.title = row.title
  lessonForm.content = row.content
  lessonForm.sort_order = row.sort_order
  lessonForm.status = row.status
  lessonEditorOpen.value = true
}

function validateLessonForm() {
  const errors: FieldErrors = {}
  if (!/^([\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]){2,128}$/.test(lessonForm.title.trim())) {
    errors.title = ['课时名称需为 2-128 位，可包含中文、字母、数字和常用标点。']
  }
  if (lessonForm.content.trim().length > 5000) {
    errors.content = ['课时内容不能超过 5000 个字符。']
  }
  const order = Number(lessonForm.sort_order)
  if (!Number.isInteger(order) || order < 0 || order > 9999) {
    errors.sort_order = ['排序需为 0-9999 的整数。']
  }
  lessonErrors.value = errors
  return Object.keys(errors).length === 0
}

async function saveLesson() {
  if (!activeCourse.value || !validateLessonForm()) return
  saving.value = true
  try {
    const payload: LessonPayload = {
      title: lessonForm.title.trim(),
      content: lessonForm.content.trim(),
      sort_order: lessonForm.sort_order,
      status: lessonForm.status
    }
    const saved = editingLesson.value
      ? await updateTeacherLesson(editingLesson.value.id, payload)
      : await createTeacherLesson(activeCourse.value.id, payload)
    lessons.value = editingLesson.value
      ? lessons.value.map((item) => (item.id === saved.id ? saved : item))
      : [...lessons.value, saved].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
    notice.value = editingLesson.value ? '课时已更新。' : '课时已创建。'
    lessonEditorOpen.value = false
    await load(rows.value.page)
    await loadOptions()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      lessonErrors.value = error.errors
    } else {
      notice.value = '课时保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function askLesson(type: PendingLessonAction, row: LessonRow) {
  pendingLessonAction.value = { type, row }
  lessonConfirmOpen.value = true
}

async function confirmLessonAction() {
  if (!pendingLessonAction.value) return
  lessonConfirmLoading.value = true
  try {
    const { type, row } = pendingLessonAction.value
    if (type === 'publish') {
      const updated = await publishTeacherLesson(row.id)
      lessons.value = lessons.value.map((item) => (item.id === updated.id ? updated : item))
      notice.value = '课时已发布。'
    } else if (type === 'archive') {
      const updated = await archiveTeacherLesson(row.id)
      lessons.value = lessons.value.map((item) => (item.id === updated.id ? updated : item))
      notice.value = '课时已停用。'
    } else {
      await deleteTeacherLesson(row.id)
      lessons.value = lessons.value.filter((item) => item.id !== row.id)
      notice.value = '课时已删除。'
    }
    await load(rows.value.page)
    await loadOptions()
    lessonConfirmOpen.value = false
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课时操作失败。'
  } finally {
    lessonConfirmLoading.value = false
  }
}

function resetFilters() {
  query.value = ''
  status.value = ''
  subjectFilter.value = ''
  load(1)
}

function classLabel(item: ClassGroupRow) {
  return `${item.grade ? `${item.grade} ` : ''}${item.name}`
}

function subjectLabel(item: SubjectRow | null) {
  return item ? `${item.name} / ${item.code}` : '未设置'
}

onMounted(async () => {
  await loadOptions()
  await load(1)
})
</script>

<template>
  <AppShell title="课程备课" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section class="metric-grid teacher-student-summary" aria-label="课程概况">
      <article v-for="item in summary" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </article>
    </section>

    <ManagementPage
      v-model:query="query"
      v-model:status="status"
      title="课程备课"
      description="维护本人课程、课时和可见班级。下一阶段课时会按学习片段组织资源、题目、任务和协作文档。"
      :total="rows.count"
      :page="rows.page"
      :page-size="rows.page_size"
      :rows="rows.results"
      :loading="loading"
      :status-options="statusOptions"
      :show-export="false"
      :show-template="false"
      :show-import="false"
      primary-label="新增课程"
      @create="openCreateCourse"
      @search="load(1)"
      @reset="resetFilters"
      @page="load"
    >
      <template #toolbar-actions>
        <label>
          <span>学科</span>
          <select v-model="subjectFilter" @change="load(1)">
            <option value="">全部学科</option>
            <option v-for="item in subjectOptions" :key="item.id" :value="item.id">
              {{ item.name }}
            </option>
          </select>
        </label>
      </template>

      <template #head>
        <thead>
          <tr>
            <th>封面</th>
            <th>课程</th>
            <th>学科</th>
            <th>模式</th>
            <th>状态</th>
            <th>课时</th>
            <th>班级</th>
            <th>更新时间</th>
            <th class="actions-col">操作</th>
          </tr>
        </thead>
      </template>

      <template #rows="{ rows: tableRows }">
        <tr v-for="item in tableRows" :key="item.id">
          <td>
            <div class="course-cover-thumb">
              <img v-if="item.cover_url" :src="item.cover_url" :alt="`${item.title}封面`" />
              <div v-else class="course-cover-default">
                <strong>{{ item.title }}</strong>
              </div>
            </div>
          </td>
          <td>
            <strong>{{ item.title }}</strong>
            <p class="table-subtitle">{{ item.introduction || '暂无课程简介' }}</p>
          </td>
          <td>{{ subjectLabel(item.subject) }}</td>
          <td>{{ item.teaching_model_label }}</td>
          <td><span class="status-pill" :class="item.is_active ? 'status-published' : 'status-draft'">{{ item.status_label }}</span></td>
          <td>{{ item.lesson_count }}</td>
          <td>
            <div class="class-chip-list notice-class-list">
              <span v-for="classItem in item.target_classes.slice(0, 3)" :key="classItem.id" class="class-chip">
                {{ classLabel(classItem) }}
              </span>
              <span v-if="item.target_classes.length > 3" class="class-chip">+{{ item.target_classes.length - 3 }}</span>
              <span v-if="!item.target_classes.length" class="muted-text">未绑定</span>
            </div>
          </td>
          <td>{{ new Date(item.updated_at).toLocaleString() }}</td>
          <td>
            <div class="row-actions">
              <button type="button" @click="openEditCourse(item)">编辑</button>
              <button type="button" @click="openClassManager(item)">班级</button>
              <button type="button" @click="openLessons(item)">课时设计</button>
              <button v-if="!item.is_active" type="button" @click="askCourse('publish', item)">发布</button>
              <button v-else type="button" @click="askCourse('archive', item)">停用</button>
              <button class="danger-link" type="button" @click="askCourse('delete', item)">删除</button>
            </div>
          </td>
        </tr>
      </template>
    </ManagementPage>

    <Teleport to="body">
      <div v-if="courseModalOpen" class="modal-backdrop" role="presentation" @click.self="courseModalOpen = false">
        <form class="entity-modal compact-modal course-editor-modal" role="dialog" aria-modal="true" @submit.prevent="saveCourse">
          <header class="modal-header">
            <div>
              <h2>{{ editingCourse ? '编辑课程' : '新增课程' }}</h2>
              <p>课程属于教师本人，发布后学生端按绑定班级可见。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="courseModalOpen = false">×</button>
          </header>
          <div class="notice-editor-body">
            <label>
              <span>课程名称 <b>*</b></span>
              <input v-model.trim="courseForm.title" maxlength="128" />
              <small v-if="courseErrors.title" class="field-error">{{ courseErrors.title[0] }}</small>
            </label>
            <label>
              <span>学科 <b>*</b></span>
              <select v-model="courseForm.subject">
                <option value="">请选择学科</option>
                <option v-for="item in subjectOptions" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
              <small v-if="courseErrors.subject" class="field-error">{{ courseErrors.subject[0] }}</small>
            </label>
            <label>
              <span>教学模式</span>
              <select v-model="courseForm.teaching_model">
                <option value="pbl">项目式学习</option>
                <option value="tbl">任务驱动学习</option>
              </select>
            </label>
            <label>
              <span>状态</span>
              <select v-model="courseForm.status">
                <option value="draft">草稿</option>
                <option value="published">已发布</option>
              </select>
            </label>
            <label class="span-2">
              <span>课程简介</span>
              <textarea v-model.trim="courseForm.introduction" maxlength="5000" placeholder="填写课程目标、内容范围或课堂说明"></textarea>
              <small v-if="courseErrors.introduction" class="field-error">{{ courseErrors.introduction[0] }}</small>
            </label>
            <div class="span-2 course-cover-editor">
              <div class="course-cover-preview">
                <img v-if="coverPreviewUrl" :src="coverPreviewUrl" alt="课程封面预览" />
                <div v-else class="course-cover-default large">
                  <strong>{{ courseForm.title || '课程名称' }}</strong>
                </div>
              </div>
              <div class="course-cover-controls">
                <span>课程封面</span>
                <p>推荐 16:9 图片，支持 JPG、PNG、WEBP，最大 5MB。未上传时系统会使用蓝色默认封面。</p>
                <input type="file" accept="image/jpeg,image/png,image/webp" @change="onCourseCoverChange" />
                <small v-if="courseErrors.cover" class="field-error">{{ courseErrors.cover[0] }}</small>
                <div class="row-actions">
                  <button type="button" @click="removeCourseCover">使用默认封面</button>
                </div>
              </div>
            </div>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="courseModalOpen = false">取消</button>
            <button class="primary-button" type="submit" :disabled="saving">{{ saving ? '保存中' : '保存课程' }}</button>
          </footer>
        </form>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="classModalOpen && activeCourse" class="modal-backdrop" role="presentation" @click.self="classModalOpen = false">
        <section class="entity-modal compact-modal class-scope-modal" role="dialog" aria-modal="true">
          <header class="modal-header">
            <div>
              <h2>设置可见班级</h2>
              <p>{{ activeCourse.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="classModalOpen = false">×</button>
          </header>
          <div class="batch-modal-body">
            <div class="class-check-header">
              <span>已选择 {{ selectedClassIds.length }} 个班级</span>
              <div class="row-actions">
                <button type="button" @click="selectAllClasses">全选</button>
                <button type="button" @click="selectedClassIds = []">清空</button>
              </div>
            </div>
            <small v-if="courseErrors.class_groups" class="field-error">{{ courseErrors.class_groups[0] }}</small>
            <div class="class-checkbox-grid">
              <label v-for="item in classOptions" :key="item.id" class="class-check-item">
                <input
                  type="checkbox"
                  :checked="selectedClassIds.includes(item.id)"
                  @change="toggleClass(item.id, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ classLabel(item) }}</span>
                <small>{{ item.student_count }} 名学生</small>
              </label>
            </div>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="classModalOpen = false">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="saveClassScope">
              {{ saving ? '保存中' : '保存班级范围' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="lessonModalOpen && activeCourse" class="modal-backdrop" role="presentation" @click.self="lessonModalOpen = false">
        <section class="entity-modal compact-modal lesson-manager-modal" role="dialog" aria-modal="true">
          <header class="modal-header">
            <div>
              <h2>课时管理</h2>
              <p>{{ activeCourse.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="lessonModalOpen = false">×</button>
          </header>
          <div class="batch-modal-body">
            <div class="class-check-header">
              <span>共 {{ lessons.length }} 个课时</span>
              <button class="primary-button" type="button" @click="openCreateLesson">新增课时</button>
            </div>
            <div v-if="lessonLoading" class="empty">正在加载</div>
            <div v-else-if="lessons.length" class="lesson-list">
              <article v-for="item in lessons" :key="item.id" class="lesson-item">
                <header>
                  <div>
                    <strong>{{ item.sort_order }}. {{ item.title }}</strong>
                    <span>{{ item.content || '暂无课时说明' }}</span>
                  </div>
                  <span class="status-pill" :class="item.is_active ? 'status-published' : 'status-draft'">{{ item.status_label }}</span>
                </header>
                <footer>
                  <small>课堂 {{ item.session_count }} · 活动 {{ item.activity_count }}</small>
                  <div class="row-actions">
                    <button type="button" @click="openEditLesson(item)">编辑</button>
                    <RouterLink :to="`/teacher/lessons/${item.id}/design`">设计课时</RouterLink>
                    <button v-if="!item.is_active" type="button" @click="askLesson('publish', item)">发布</button>
                    <button v-else type="button" @click="askLesson('archive', item)">停用</button>
                    <button class="danger-link" type="button" @click="askLesson('delete', item)">删除</button>
                  </div>
                </footer>
              </article>
            </div>
            <p v-else class="empty">暂无课时</p>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" @click="lessonModalOpen = false">关闭</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="lessonEditorOpen" class="modal-backdrop" role="presentation" @click.self="lessonEditorOpen = false">
        <form class="entity-modal compact-modal lesson-editor-modal" role="dialog" aria-modal="true" @submit.prevent="saveLesson">
          <header class="modal-header">
            <div>
              <h2>{{ editingLesson ? '编辑课时' : '新增课时' }}</h2>
              <p>{{ activeCourse?.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="lessonEditorOpen = false">×</button>
          </header>
          <div class="notice-editor-body">
            <label>
              <span>课时名称 <b>*</b></span>
              <input v-model.trim="lessonForm.title" maxlength="128" />
              <small v-if="lessonErrors.title" class="field-error">{{ lessonErrors.title[0] }}</small>
            </label>
            <label>
              <span>排序</span>
              <input v-model="lessonForm.sort_order" type="number" min="0" max="9999" />
              <small v-if="lessonErrors.sort_order" class="field-error">{{ lessonErrors.sort_order[0] }}</small>
            </label>
            <label>
              <span>状态</span>
              <select v-model="lessonForm.status">
                <option value="draft">草稿</option>
                <option value="published">已发布</option>
              </select>
            </label>
            <label class="span-2">
              <span>课时内容</span>
              <textarea v-model.trim="lessonForm.content" maxlength="5000" placeholder="填写本课时的教学内容或活动说明"></textarea>
              <small v-if="lessonErrors.content" class="field-error">{{ lessonErrors.content[0] }}</small>
            </label>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="lessonEditorOpen = false">取消</button>
            <button class="primary-button" type="submit" :disabled="saving">{{ saving ? '保存中' : '保存课时' }}</button>
          </footer>
        </form>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="confirmOpen"
      title="确认操作"
      :message="pendingCourseAction?.type === 'delete' ? '删除前请确认课程已停用，且没有课堂或学习行为记录。' : '确认执行该课程操作？'"
      confirm-label="确认"
      :loading="confirmLoading"
      @close="confirmOpen = false"
      @confirm="confirmCourseAction"
    />

    <ConfirmDialog
      :open="lessonConfirmOpen"
      title="确认课时操作"
      :message="pendingLessonAction?.type === 'delete' ? '删除前请确认课时已停用，且没有课堂或学习行为记录。' : '确认执行该课时操作？'"
      confirm-label="确认"
      :loading="lessonConfirmLoading"
      @close="lessonConfirmOpen = false"
      @confirm="confirmLessonAction"
    />
  </AppShell>
</template>
