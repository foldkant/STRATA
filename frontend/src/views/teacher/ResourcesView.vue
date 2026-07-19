<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  deleteTeacherResource,
  deleteTeacherResourceFile,
  getTeacherCourseOptions,
  getTeacherResources,
  updateTeacherResource,
  uploadTeacherResource,
  type ResourcePayload,
  type ResourceRow,
  type TeacherCourseOptions
} from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import FilePicker from '@/components/FilePicker.vue'
import MultiSelectActions from '@/components/MultiSelectActions.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/resources')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const query = ref('')
const scope = ref<'mine' | 'school' | 'external' | 'projects'>('mine')
const categoryFilter = ref('')
const subjectFilter = ref('')
const rows = ref<ResourceRow[]>([])
const options = ref<TeacherCourseOptions>({ subjects: [], classes: [], courses: [], activity_types: [] })
const editorOpen = ref(false)
const previewRow = ref<ResourceRow | null>(null)
const editingId = ref<number | null>(null)
const selectedFile = ref<File | null>(null)
const selectedCover = ref<File | null>(null)
const extraFiles = ref<File[]>([])
const errors = ref<FieldErrors>({})

const form = reactive({
  title: '',
  content: '',
  resource_type: 'file' as ResourceRow['resource_type'],
  category: 'courseware',
  visibility: 'private' as ResourceRow['visibility'],
  subject: '',
  class_ids: [] as number[],
  grade_scope: '',
  tags_text: '',
  external_url: '',
  project_type: 'group' as 'individual' | 'group',
  project_members_text: '',
  project_course: '',
  competition_name: '',
  competition_year: '',
  award_level: '',
  is_pinned: false
})

const scopeTabs = [
  { value: 'mine', label: '我的资源' },
  { value: 'school', label: '校内资源' },
  { value: 'external', label: '跨校资源' },
  { value: 'projects', label: '学生项目' }
] as const

const resourceTypes = [
  { value: 'file', label: '文件资源', description: '课件、视频、压缩包等' },
  { value: 'article', label: '图文内容', description: '课外阅读、方法和案例' },
  { value: 'link', label: '外部链接', description: '需要联网访问的资源' },
  { value: 'student_project', label: '学生项目', description: '个人或小组项目成果' }
] as const

const categories = [
  { value: 'courseware', label: '课件素材' },
  { value: 'extracurricular', label: '课外拓展' },
  { value: 'competition', label: '竞赛资源' },
  { value: 'project', label: '学生项目' },
  { value: 'reference', label: '参考资料' },
  { value: 'toolkit', label: '工具素材' },
  { value: 'other', label: '其他' }
]

const visibilityOptions = [
  { value: 'private', label: '仅自己', description: '只在个人资源库和课时设计中使用' },
  { value: 'classes', label: '指定班级', description: '仅向本人任教的指定班级开放' },
  { value: 'school', label: '本校共享', description: '本校师生可以浏览和使用' },
  { value: 'external', label: '跨校共享', description: '提交学校管理员审核后进入跨校资源库' }
] as const

const currentEditingRow = computed(() => rows.value.find((item) => item.id === editingId.value) || null)
const modalTitle = computed(() => editingId.value ? '编辑资源' : form.resource_type === 'student_project' ? '新增学生项目' : '新增资源')

function splitTextList(value: string) {
  return value
    .split(/[，,、\n]/)
    .map((item) => item.trim())
    .filter((item, index, values) => Boolean(item) && values.indexOf(item) === index)
}

function formatFileSize(size: number) {
  if (!size) return '无附件'
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(size >= 100 * 1024 * 1024 ? 0 : 1)} MB`
}

function formatDate(value: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleDateString('zh-CN')
}

function resourceInitial(item: ResourceRow) {
  return item.title.slice(0, 4)
}

function resetForm() {
  editingId.value = null
  form.title = ''
  form.content = ''
  form.resource_type = 'file'
  form.category = 'courseware'
  form.visibility = 'private'
  form.subject = ''
  form.class_ids = []
  form.grade_scope = ''
  form.tags_text = ''
  form.external_url = ''
  form.project_type = 'group'
  form.project_members_text = ''
  form.project_course = ''
  form.competition_name = ''
  form.competition_year = ''
  form.award_level = ''
  form.is_pinned = false
  selectedFile.value = null
  selectedCover.value = null
  extraFiles.value = []
  errors.value = {}
}

function openCreate(type: ResourceRow['resource_type'] = 'file') {
  resetForm()
  form.resource_type = type
  if (type === 'student_project') form.category = 'project'
  editorOpen.value = true
}

function openEdit(item: ResourceRow) {
  resetForm()
  editingId.value = item.id
  form.title = item.title
  form.content = item.content
  form.resource_type = item.resource_type
  form.category = item.category
  form.visibility = item.visibility
  form.subject = item.subject ? String(item.subject.id) : ''
  form.class_ids = item.target_classes.map((classGroup) => classGroup.id)
  form.grade_scope = item.grade_scope
  form.tags_text = item.tags.join('，')
  form.external_url = item.external_url
  form.project_type = item.project_type === 'individual' ? 'individual' : 'group'
  form.project_members_text = item.project_members.join('，')
  form.project_course = item.project_course
  form.competition_name = item.competition_name
  form.competition_year = item.competition_year ? String(item.competition_year) : ''
  form.award_level = item.award_level
  form.is_pinned = item.is_pinned
  editorOpen.value = true
}

function closeEditor() {
  if (saving.value) return
  editorOpen.value = false
  resetForm()
}

function onFileChange(files: File[], target: 'main' | 'cover' | 'extra') {
  if (target === 'main') selectedFile.value = files[0] || null
  if (target === 'cover') selectedCover.value = files[0] || null
  if (target === 'extra') extraFiles.value = files
  errors.value = {}
  if (target === 'main' && selectedFile.value && !form.title.trim()) {
    form.title = selectedFile.value.name.replace(/\.[^.]+$/, '').slice(0, 128)
  }
}

function validateForm() {
  const nextErrors: FieldErrors = {}
  if (form.title.trim().length < 2) nextErrors.title = ['资源标题至少填写 2 个字符。']
  if (form.resource_type === 'file' && !selectedFile.value && !currentEditingRow.value?.attachment_url) {
    nextErrors.attachment = ['文件资源需要上传主文件。']
  }
  if (form.resource_type === 'article' && !form.content.trim()) nextErrors.content = ['请填写图文正文。']
  if (form.resource_type === 'link' && !/^https?:\/\//i.test(form.external_url.trim())) {
    nextErrors.external_url = ['请输入以 http:// 或 https:// 开头的链接。']
  }
  if (form.resource_type === 'student_project' && !splitTextList(form.project_members_text).length) {
    nextErrors.project_members = ['请至少填写一名项目成员。']
  }
  if (form.visibility === 'classes' && !form.class_ids.length) nextErrors.class_ids = ['请至少选择一个任教班级。']
  errors.value = nextErrors
  return !Object.keys(nextErrors).length
}

function buildPayload(): ResourcePayload {
  return {
    title: form.title.trim(),
    content: form.content.trim(),
    resource_type: form.resource_type,
    category: form.resource_type === 'student_project' ? 'project' : form.category,
    visibility: form.visibility,
    subject: form.subject,
    class_ids: form.class_ids,
    grade_scope: form.grade_scope.trim(),
    tags: splitTextList(form.tags_text),
    external_url: form.external_url.trim(),
    project_type: form.resource_type === 'student_project' ? form.project_type : '',
    project_members: form.resource_type === 'student_project' ? splitTextList(form.project_members_text) : [],
    project_course: form.project_course.trim(),
    competition_name: form.competition_name.trim(),
    competition_year: form.competition_year,
    award_level: form.award_level.trim(),
    is_pinned: form.is_pinned,
    file: selectedFile.value,
    cover: selectedCover.value,
    extra_files: extraFiles.value
  }
}

async function loadRows() {
  loading.value = true
  try {
    const result = await getTeacherResources({
      q: query.value,
      scope: scope.value,
      category: categoryFilter.value,
      subject: subjectFilter.value,
      page_size: 60
    })
    rows.value = result.results
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源列表加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitResource() {
  if (!validateForm()) return
  saving.value = true
  try {
    const saved = editingId.value
      ? await updateTeacherResource(editingId.value, buildPayload())
      : await uploadTeacherResource(buildPayload())
    notice.value = saved.visibility === 'external' ? '资源已提交跨校共享审核。' : '资源已保存。'
    editorOpen.value = false
    resetForm()
    await loadRows()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = '资源保存失败。'
    }
  } finally {
    saving.value = false
  }
}

async function removeResource(item: ResourceRow) {
  if (!item.is_owner) return
  if (!window.confirm(`确认删除资源“${item.title}”？`)) return
  try {
    await deleteTeacherResource(item.id)
    notice.value = '资源已删除。'
    if (previewRow.value?.id === item.id) previewRow.value = null
    await loadRows()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源删除失败。'
  }
}

async function removeExtraFile(fileId: number) {
  if (!editingId.value || !window.confirm('确认删除这份补充材料？')) return
  try {
    await deleteTeacherResourceFile(editingId.value, fileId)
    const row = currentEditingRow.value
    if (row) row.extra_files = row.extra_files.filter((item) => item.id !== fileId)
    notice.value = '补充材料已删除。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '附件删除失败。'
  }
}

watch(scope, loadRows)

onMounted(async () => {
  try {
    options.value = await getTeacherCourseOptions()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源筛选项加载失败。'
  }
  await loadRows()
})
</script>

<template>
  <AppShell title="资源中心" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section class="resource-center-head">
      <div>
        <h2>教学资源中心</h2>
        <p>管理备课资源、课外拓展材料和学生项目，并按班级、校内或跨校范围发布。</p>
      </div>
      <div class="resource-center-head-actions">
        <button class="secondary-button" type="button" @click="openCreate('student_project')">新增学生项目</button>
        <button class="primary-button" type="button" @click="openCreate()">新增资源</button>
      </div>
    </section>

    <section class="resource-center-toolbar">
      <div class="resource-scope-tabs" role="tablist" aria-label="资源范围">
        <button
          v-for="tab in scopeTabs"
          :key="tab.value"
          type="button"
          :class="{ active: scope === tab.value }"
          @click="scope = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>
      <div class="resource-filter-row">
        <input v-model.trim="query" aria-label="搜索资源" placeholder="搜索标题、成员、标签或说明" @keyup.enter="loadRows" />
        <select v-model="subjectFilter" aria-label="按学科筛选" @change="loadRows">
          <option value="">全部学科</option>
          <option v-for="subject in options.subjects" :key="subject.id" :value="subject.id">{{ subject.name }}</option>
        </select>
        <select v-model="categoryFilter" aria-label="按分类筛选" @change="loadRows">
          <option value="">全部分类</option>
          <option v-for="item in categories" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <button class="secondary-button" type="button" :disabled="loading" @click="loadRows">
          {{ loading ? '查询中' : '查询' }}
        </button>
      </div>
    </section>

    <section class="resource-center-grid" :aria-busy="loading">
      <article v-for="item in rows" :key="item.id" class="resource-center-card">
        <button class="resource-cover-button" type="button" @click="previewRow = item">
          <img v-if="item.cover_url" :src="item.cover_url" :alt="`${item.title}封面`" />
          <span v-else class="resource-cover-placeholder">{{ resourceInitial(item) }}</span>
          <small>{{ item.resource_type_label }}</small>
        </button>
        <div class="resource-center-card-body">
          <div class="resource-card-title-row">
            <strong>{{ item.title }}</strong>
            <span class="resource-status-chip" :class="`status-${item.publish_status}`">{{ item.publish_status_label }}</span>
          </div>
          <p>{{ item.content || item.external_url || item.attachment_name || '暂无内容说明。' }}</p>
          <div class="resource-card-tags">
            <span>{{ item.category_label }}</span>
            <span v-if="item.subject">{{ item.subject.name }}</span>
            <span v-if="item.grade_scope">{{ item.grade_scope }}</span>
            <span v-for="tag in item.tags.slice(0, 3)" :key="tag">{{ tag }}</span>
          </div>
          <dl class="resource-card-meta">
            <div><dt>来源</dt><dd>{{ item.school?.name || '本校' }} · {{ item.owner.display_name }}</dd></div>
            <div><dt>范围</dt><dd>{{ item.visibility_label }}</dd></div>
            <div><dt>更新</dt><dd>{{ formatDate(item.updated_at) }}</dd></div>
          </dl>
          <p v-if="item.resource_type === 'student_project'" class="resource-project-members">
            {{ item.project_type_label }} · {{ item.project_members.join('、') }}
          </p>
          <p v-if="item.publish_status === 'rejected' && item.review_note" class="resource-review-note">
            退回原因：{{ item.review_note }}
          </p>
        </div>
        <footer class="resource-center-card-actions">
          <button class="primary-button" type="button" @click="previewRow = item">预览</button>
          <a v-if="item.external_url" class="secondary-button" :href="item.external_url" target="_blank" rel="noopener noreferrer">打开链接</a>
          <a v-else-if="item.attachment_url" class="secondary-button" :href="item.attachment_url" download>下载</a>
          <button v-if="item.is_owner" class="secondary-button" type="button" @click="openEdit(item)">编辑</button>
          <button v-if="item.is_owner" class="secondary-button danger" type="button" @click="removeResource(item)">删除</button>
        </footer>
      </article>
      <p v-if="!loading && !rows.length" class="empty resource-center-empty">
        当前范围暂无资源。
      </p>
    </section>

    <div v-if="editorOpen" class="modal-backdrop" role="presentation" @click.self="closeEditor">
      <section class="entity-modal resource-editor-modal" role="dialog" aria-modal="true" aria-labelledby="resource-editor-title">
        <header class="modal-header">
          <div>
            <h2 id="resource-editor-title">{{ modalTitle }}</h2>
            <p>项目过程材料、比赛信息和封面均为选填。</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="closeEditor">×</button>
        </header>

        <div class="resource-editor-body">
          <fieldset class="resource-type-picker">
            <legend>资源类型</legend>
            <label v-for="item in resourceTypes" :key="item.value" :class="{ active: form.resource_type === item.value }">
              <input v-model="form.resource_type" type="radio" :value="item.value" @change="item.value === 'student_project' && (form.category = 'project')" />
              <strong>{{ item.label }}</strong>
              <small>{{ item.description }}</small>
            </label>
          </fieldset>

          <div class="resource-form-grid">
            <label class="span-2">
              <span>资源标题 <b>*</b></span>
              <input v-model.trim="form.title" maxlength="128" placeholder="例如 信息学竞赛作品展示" />
              <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
            </label>
            <label>
              <span>资源分类 <b>*</b></span>
              <select v-model="form.category" :disabled="form.resource_type === 'student_project'">
                <option v-for="item in categories" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label>
              <span>所属学科</span>
              <select v-model="form.subject">
                <option value="">不限定学科</option>
                <option v-for="subject in options.subjects" :key="subject.id" :value="subject.id">{{ subject.name }}</option>
              </select>
            </label>
            <label>
              <span>适用年级</span>
              <input v-model.trim="form.grade_scope" maxlength="128" placeholder="例如 高一、高二" />
            </label>
            <label>
              <span>标签</span>
              <input v-model.trim="form.tags_text" maxlength="300" placeholder="使用逗号分隔，最多 12 个" />
            </label>

            <label v-if="form.resource_type !== 'link'" class="span-2">
              <span>{{ form.resource_type === 'article' ? '图文正文' : form.resource_type === 'student_project' ? '项目简介' : '资源说明' }}</span>
              <textarea v-model.trim="form.content" rows="5" maxlength="5000" placeholder="填写资源用途、阅读说明或项目介绍。"></textarea>
              <small v-if="errors.content" class="field-error">{{ errors.content[0] }}</small>
            </label>
            <label v-if="form.resource_type === 'link' || form.resource_type === 'student_project'" class="span-2">
              <span>外部链接{{ form.resource_type === 'link' ? ' *' : '（选填）' }}</span>
              <input v-model.trim="form.external_url" maxlength="500" placeholder="https://" />
              <small v-if="errors.external_url" class="field-error">{{ errors.external_url[0] }}</small>
            </label>

            <template v-if="form.resource_type === 'student_project'">
              <label>
                <span>项目形式 <b>*</b></span>
                <select v-model="form.project_type">
                  <option value="individual">个人项目</option>
                  <option value="group">小组项目</option>
                </select>
              </label>
              <label>
                <span>所属课程</span>
                <input v-model.trim="form.project_course" maxlength="128" placeholder="例如 数据与计算" />
              </label>
              <label class="span-2">
                <span>项目成员 <b>*</b></span>
                <input v-model.trim="form.project_members_text" maxlength="1000" placeholder="使用逗号分隔学生姓名" />
                <small v-if="errors.project_members" class="field-error">{{ errors.project_members[0] }}</small>
              </label>
              <label>
                <span>比赛名称</span>
                <input v-model.trim="form.competition_name" maxlength="128" placeholder="选填" />
              </label>
              <label>
                <span>比赛年份</span>
                <input v-model.trim="form.competition_year" inputmode="numeric" maxlength="4" placeholder="选填" />
              </label>
              <label class="span-2">
                <span>获奖等级</span>
                <input v-model.trim="form.award_level" maxlength="128" placeholder="例如 市级一等奖，选填" />
              </label>
            </template>

            <FilePicker
              v-if="form.resource_type === 'file' || form.resource_type === 'student_project'"
              class="span-2"
              :label="form.resource_type === 'student_project' ? '项目成果文件' : '主文件'"
              :hint="form.resource_type === 'student_project' ? '支持作品、演示文稿、视频或压缩包等项目成果。' : '支持课件、视频、图片、压缩包等常用教学文件。'"
              :file="selectedFile"
              :current-name="currentEditingRow?.attachment_name || ''"
              current-detail="未选择新文件时，保存后继续使用原文件。"
              :required="form.resource_type === 'file' && !currentEditingRow?.attachment_url"
              :optional-label="form.resource_type === 'student_project' ? '选填' : ''"
              :disabled="saving"
              :error="errors.attachment?.[0] || ''"
              :replace-text="currentEditingRow?.attachment_url && !selectedFile ? '替换文件' : '重新选择'"
              @select="onFileChange($event, 'main')"
            />

            <FilePicker
              label="资源封面"
              hint="支持 JPG、PNG、WebP，建议使用横版图片。"
              accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
              optional-label="选填"
              choose-text="选择图片"
              replace-text="更换图片"
              :file="selectedCover"
              :current-name="currentEditingRow?.cover_url ? '已上传封面图片' : ''"
              current-detail="未选择新图片时，保存后继续使用原封面。"
              :disabled="saving"
              :error="errors.cover?.[0] || ''"
              @select="onFileChange($event, 'cover')"
            />

            <FilePicker
              :label="form.resource_type === 'student_project' ? '项目过程材料' : '补充附件'"
              :hint="form.resource_type === 'student_project' ? '可上传日志、甘特图和阶段成果，支持多选。' : '可补充讲义、素材或说明文件，支持多选。'"
              optional-label="选填"
              choose-text="选择多个文件"
              :files="extraFiles"
              :multiple="true"
              :disabled="saving"
              :error="errors.extra_files?.[0] || ''"
              @select="onFileChange($event, 'extra')"
            />
          </div>

          <section v-if="currentEditingRow?.extra_files.length" class="resource-existing-files">
            <header><strong>已有补充材料</strong><small>{{ currentEditingRow.extra_files.length }} 个</small></header>
            <article v-for="file in currentEditingRow.extra_files" :key="file.id">
              <a :href="file.file_url" download>{{ file.name }}</a>
              <span>{{ file.role_label }} · {{ formatFileSize(file.file_size) }}</span>
              <button type="button" @click="removeExtraFile(file.id)">删除</button>
            </article>
          </section>

          <fieldset class="resource-visibility-picker">
            <legend>发布范围</legend>
            <label v-for="item in visibilityOptions" :key="item.value" :class="{ active: form.visibility === item.value }">
              <input v-model="form.visibility" type="radio" :value="item.value" />
              <strong>{{ item.label }}</strong>
              <small>{{ item.description }}</small>
            </label>
          </fieldset>

          <section v-if="form.visibility === 'classes'" class="resource-class-picker">
            <header>
              <strong>选择任教班级</strong>
              <MultiSelectActions
                :selected-count="form.class_ids.length"
                :total-count="options.classes.length"
                @select-all="form.class_ids = options.classes.map((item) => item.id)"
                @clear="form.class_ids = []"
              />
            </header>
            <div>
              <label v-for="classGroup in options.classes" :key="classGroup.id">
                <input v-model="form.class_ids" type="checkbox" :value="classGroup.id" />
                <span>{{ classGroup.grade }} {{ classGroup.name }}</span>
              </label>
            </div>
            <small v-if="errors.class_ids" class="field-error">{{ errors.class_ids[0] }}</small>
          </section>

          <label class="check-row resource-pin-row">
            <input v-model="form.is_pinned" type="checkbox" />
            <span>在我的资源中置顶</span>
          </label>
        </div>

        <footer class="modal-actions resource-editor-actions">
          <button class="secondary-button" type="button" :disabled="saving" @click="closeEditor">取消</button>
          <button class="primary-button" type="button" :disabled="saving" @click="submitResource">
            {{ saving ? '保存中' : form.visibility === 'external' ? '提交审核' : '保存资源' }}
          </button>
        </footer>
      </section>
    </div>

    <div v-if="previewRow" class="modal-backdrop" role="presentation" @click.self="previewRow = null">
      <section class="entity-modal resource-detail-modal" role="dialog" aria-modal="true" aria-labelledby="resource-preview-title">
        <header class="modal-header">
          <div>
            <h2 id="resource-preview-title">{{ previewRow.title }}</h2>
            <p>{{ previewRow.school?.name }} · {{ previewRow.owner.display_name }} · {{ previewRow.visibility_label }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="previewRow = null">×</button>
        </header>
        <div class="resource-detail-body">
          <ResourcePreview :resource="previewRow" :office-mode="previewRow.is_owner ? 'edit' : 'view'" />
          <aside>
            <h3>资源信息</h3>
            <p>{{ previewRow.content || '暂无补充说明。' }}</p>
            <dl>
              <div><dt>分类</dt><dd>{{ previewRow.category_label }}</dd></div>
              <div><dt>学科</dt><dd>{{ previewRow.subject?.name || '不限' }}</dd></div>
              <div><dt>适用</dt><dd>{{ previewRow.grade_scope || '不限' }}</dd></div>
              <div><dt>浏览</dt><dd>{{ previewRow.view_count }}</dd></div>
            </dl>
            <section v-if="previewRow.resource_type === 'student_project'">
              <strong>项目成员</strong>
              <p>{{ previewRow.project_members.join('、') }}</p>
              <p v-if="previewRow.competition_name">{{ previewRow.competition_name }} {{ previewRow.competition_year || '' }} {{ previewRow.award_level }}</p>
            </section>
            <section v-if="previewRow.extra_files.length">
              <strong>{{ previewRow.resource_type === 'student_project' ? '项目过程材料' : '补充附件' }}</strong>
              <a v-for="file in previewRow.extra_files" :key="file.id" :href="file.file_url" download>{{ file.name }}</a>
            </section>
          </aside>
        </div>
      </section>
    </div>
  </AppShell>
</template>
