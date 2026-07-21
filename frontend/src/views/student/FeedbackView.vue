<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  createStudentFeedback,
  getStudentFeedback,
  getStudentMe,
  type StudentFeedback,
  type StudentFeedbackPayload,
  type StudentTeacher
} from '@/api/student'
import type { PageResult } from '@/api/management'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const rows = ref<StudentFeedback[]>([])
const page = ref<PageResult<StudentFeedback> | null>(null)
const teachers = ref<StudentTeacher[]>([])
const notice = ref('')
const success = ref('')
const errors = ref<FieldErrors>({})
const loading = ref(false)
const saving = ref(false)
const navItems = studentNav('/student/feedback')

const form = ref<StudentFeedbackPayload>({
  teacher: '',
  category: 'study',
  title: '',
  content: ''
})

const categories = [
  { label: '学习问题', value: 'study' },
  { label: '账号问题', value: 'account' },
  { label: '资源问题', value: 'resource' },
  { label: '建议反馈', value: 'suggestion' },
  { label: '其他', value: 'other' }
]

const hasTeacher = computed(() => teachers.value.length > 0)

function fieldError(name: string) {
  return errors.value[name]?.[0] || ''
}

function formatDate(value: string | null) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function statusTone(status: string) {
  if (status === 'replied') return 'success'
  if (status === 'closed') return 'muted'
  return 'warn'
}

function localValidate() {
  const nextErrors: FieldErrors = {}
  if (!form.value.teacher) nextErrors.teacher = ['请选择任课教师。']
  if (form.value.title.trim().length < 2) nextErrors.title = ['标题至少 2 个字符。']
  if (form.value.content.trim().length < 2) nextErrors.content = ['内容至少 2 个字符。']
  errors.value = nextErrors
  return Object.keys(nextErrors).length === 0
}

async function loadRows() {
  loading.value = true
  notice.value = ''
  try {
    const [me, feedbackPage] = await Promise.all([getStudentMe(), getStudentFeedback({ page_size: 50 })])
    teachers.value = me.teachers
    if (!form.value.teacher && me.teachers[0]) {
      form.value.teacher = me.teachers[0].id
    }
    page.value = feedbackPage
    rows.value = feedbackPage.results
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '留言反馈加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitFeedback() {
  if (!localValidate()) return
  saving.value = true
  notice.value = ''
  success.value = ''
  errors.value = {}
  try {
    await createStudentFeedback({
      teacher: form.value.teacher,
      category: form.value.category,
      title: form.value.title.trim(),
      content: form.value.content.trim()
    })
    success.value = '留言已提交。'
    form.value.title = ''
    form.value.content = ''
    await loadRows()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = '留言提交失败。'
    }
  } finally {
    saving.value = false
  }
}

onMounted(loadRows)
</script>

<template>
  <StudentShell title="留言反馈" subtitle="向任课教师提交问题或建议" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <NoticeLine v-if="success" :message="success" tone="success" floating @dismiss="success = ''" />

    <section class="student-feedback-layout">
      <article class="student-panel student-form-panel">
        <header>
          <h2>提交留言</h2>
          <p>教师回复后会在右侧列表中显示。</p>
        </header>
        <label>
          <span>任课教师</span>
          <AppSelect v-model="form.teacher" :disabled="!hasTeacher">
            <option value="">请选择教师</option>
            <option v-for="teacher in teachers" :key="teacher.id" :value="teacher.id">{{ teacher.display_name }}</option>
          </AppSelect>
          <small v-if="fieldError('teacher')" class="field-error">{{ fieldError('teacher') }}</small>
        </label>
        <label>
          <span>反馈类型</span>
          <AppSelect v-model="form.category">
            <option v-for="item in categories" :key="item.value" :value="item.value">{{ item.label }}</option>
          </AppSelect>
          <small v-if="fieldError('category')" class="field-error">{{ fieldError('category') }}</small>
        </label>
        <label>
          <span>标题</span>
          <input v-model.trim="form.title" maxlength="128" placeholder="简要描述问题" />
          <small v-if="fieldError('title')" class="field-error">{{ fieldError('title') }}</small>
        </label>
        <label>
          <span>内容</span>
          <textarea v-model.trim="form.content" rows="7" maxlength="3000" placeholder="写下你遇到的问题或建议"></textarea>
          <small v-if="fieldError('content')" class="field-error">{{ fieldError('content') }}</small>
        </label>
        <button class="student-primary-action" type="button" :disabled="saving || !hasTeacher" @click="submitFeedback">
          提交留言
        </button>
      </article>

      <article class="student-panel student-feedback-list">
        <header>
          <h2>我的留言</h2>
          <p>{{ page?.count || rows.length }} 条记录</p>
        </header>
        <p v-if="loading" class="empty">正在加载留言</p>
        <template v-else>
          <section v-for="item in rows" :key="item.id" class="student-feedback-card">
            <header>
              <span :class="statusTone(item.status)">{{ item.status_label }}</span>
              <strong>{{ item.title }}</strong>
              <small>{{ item.teacher.display_name }} · {{ item.category_label }} · {{ formatDate(item.created_at) }}</small>
            </header>
            <p>{{ item.content }}</p>
            <div v-if="item.reply_content" class="student-feedback-reply">
              <strong>教师回复</strong>
              <p>{{ item.reply_content }}</p>
              <small>{{ formatDate(item.replied_at) }}</small>
            </div>
          </section>
          <p v-if="!rows.length" class="empty">暂无留言记录。</p>
        </template>
      </article>
    </section>
  </StudentShell>
</template>
