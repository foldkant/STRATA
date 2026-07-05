<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  getStudentPretestPaper,
  getStudentSubjectPretests,
  submitStudentPretestPaper,
  type StudentPretestPaper,
  type StudentPretestQuestion,
  type StudentSubjectPretests
} from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const route = useRoute()
const router = useRouter()
const subjectId = computed(() => Number(route.params.subjectId || 0))
const data = ref<StudentSubjectPretests | null>(null)
const paper = ref<StudentPretestPaper | null>(null)
const answers = ref<Record<string, unknown>>({})
const errors = ref<FieldErrors>({})
const notice = ref('')
const success = ref('')
const loading = ref(false)
const submitting = ref(false)
const navItems = studentNav('/student/courses')

const likertOptions = [
  { label: '1', text: '非常不同意' },
  { label: '2', text: '不同意' },
  { label: '3', text: '一般' },
  { label: '4', text: '同意' },
  { label: '5', text: '非常同意' }
]

const activePaperId = computed(() => paper.value?.id || null)
const questions = computed(() => paper.value?.questions || [])

function optionLabel(option: string | { label?: string; text?: string }, index: number) {
  if (typeof option === 'string') return String.fromCharCode(65 + index)
  return option.label || String.fromCharCode(65 + index)
}

function optionText(option: string | { label?: string; text?: string }) {
  return typeof option === 'string' ? option : option.text || option.label || ''
}

function optionValue(option: string | { label?: string; text?: string }, index: number) {
  if (typeof option === 'string') return option
  return option.label || String(index + 1)
}

function questionOptions(question: StudentPretestQuestion) {
  if (question.question_type === 'scale') return likertOptions
  return question.options.length ? question.options : []
}

function isChecked(question: StudentPretestQuestion, value: string) {
  const current = answers.value[String(question.id)]
  return Array.isArray(current) && current.map(String).includes(value)
}

function answerText(question: StudentPretestQuestion) {
  const current = answers.value[String(question.id)]
  return typeof current === 'string' ? current : ''
}

function setTextAnswer(question: StudentPretestQuestion, value: string) {
  answers.value = { ...answers.value, [String(question.id)]: value }
}

function toggleMultiple(question: StudentPretestQuestion, value: string, checked: boolean) {
  const key = String(question.id)
  const current = Array.isArray(answers.value[key]) ? answers.value[key].map(String) : []
  if (checked && !current.includes(value)) {
    answers.value = { ...answers.value, [key]: [...current, value] }
    return
  }
  answers.value = { ...answers.value, [key]: current.filter((item) => item !== value) }
}

function fieldError(questionId: number) {
  return errors.value[String(questionId)]?.[0] || ''
}

function localValidate() {
  const nextErrors: FieldErrors = {}
  questions.value.forEach((question) => {
    const value = answers.value[String(question.id)]
    const empty = value === undefined || value === '' || (Array.isArray(value) && value.length === 0)
    if (question.is_required && empty) {
      nextErrors[String(question.id)] = ['该题必答。']
    }
  })
  errors.value = nextErrors
  return Object.keys(nextErrors).length === 0
}

async function loadPaper(id: number) {
  paper.value = null
  answers.value = {}
  errors.value = {}
  notice.value = ''
  try {
    paper.value = await getStudentPretestPaper(id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '前测题目加载失败。'
  }
}

async function loadPage() {
  loading.value = true
  notice.value = ''
  success.value = ''
  try {
    data.value = await getStudentSubjectPretests(subjectId.value)
    const firstMissingId = data.value.pretest_status.missing[0]?.paper_id
    const fallbackId = data.value.papers[0]?.id
    if (firstMissingId || fallbackId) {
      await loadPaper(firstMissingId || fallbackId)
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学科前测加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitPaper() {
  if (!paper.value || !localValidate()) return
  submitting.value = true
  notice.value = ''
  success.value = ''
  try {
    await submitStudentPretestPaper(paper.value.id, answers.value)
    success.value = '前测已提交。'
    await loadPage()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = '前测提交失败。'
    }
  } finally {
    submitting.value = false
  }
}

onMounted(loadPage)
</script>

<template>
  <StudentShell
    :title="data?.subject.name ? `${data.subject.name}前测` : '学科前测'"
    subtitle="素养测试与学习态度问卷"
    :nav-items="navItems"
  >
    <template #actions>
      <button class="student-ghost-button" type="button" @click="router.back()">返回</button>
    </template>

    <NoticeLine v-if="notice" :message="notice" />
    <NoticeLine v-if="success" :message="success" tone="success" />
    <section v-if="loading || !data" class="student-panel">
      <p class="empty">正在加载前测</p>
    </section>

    <section v-else class="student-pretest-layout">
      <aside class="student-panel student-pretest-side">
        <header>
          <h2>{{ data.subject.name }}</h2>
          <p v-if="data.pretest_status.completed">该学科前测已完成。</p>
          <p v-else-if="data.pretest_status.required">请完成下列前测后进入课程。</p>
          <p v-else>当前学科暂无已发布前测。</p>
        </header>
        <button
          v-for="item in data.papers"
          :key="item.id"
          type="button"
          :class="{ active: activePaperId === item.id }"
          @click="loadPaper(item.id)"
        >
          <span>{{ item.kind_label }}</span>
          <strong>{{ item.title }}</strong>
          <small>{{ item.question_count }} 题 · v{{ item.version }}</small>
        </button>
      </aside>

      <article class="student-panel student-pretest-paper">
        <template v-if="paper">
          <header>
            <span>{{ paper.kind_label }}</span>
            <h2>{{ paper.title }}</h2>
            <p>{{ paper.introduction || '请按实际情况完成作答。' }}</p>
          </header>

          <div class="student-question-list">
            <section v-for="(question, index) in questions" :key="question.id" class="student-question-card">
              <header>
                <span>第 {{ index + 1 }} 题</span>
                <small>{{ question.question_type_label }}{{ question.is_required ? ' · 必答' : '' }}</small>
              </header>
              <h3>{{ question.stem }}</h3>
              <p v-if="question.dimension">维度：{{ question.dimension }}</p>

              <div v-if="question.question_type === 'single'" class="student-option-list">
                <label v-for="(option, optionIndex) in questionOptions(question)" :key="optionValue(option, optionIndex)">
                  <input
                    v-model="answers[String(question.id)]"
                    type="radio"
                    :name="`question-${question.id}`"
                    :value="optionValue(option, optionIndex)"
                  />
                  <span>{{ optionLabel(option, optionIndex) }}. {{ optionText(option) }}</span>
                </label>
              </div>

              <div v-else-if="question.question_type === 'multiple'" class="student-option-list">
                <label v-for="(option, optionIndex) in questionOptions(question)" :key="optionValue(option, optionIndex)">
                  <input
                    type="checkbox"
                    :checked="isChecked(question, optionValue(option, optionIndex))"
                    @change="toggleMultiple(question, optionValue(option, optionIndex), ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ optionLabel(option, optionIndex) }}. {{ optionText(option) }}</span>
                </label>
              </div>

              <div v-else-if="question.question_type === 'scale'" class="student-scale-list">
                <label v-for="option in likertOptions" :key="option.label">
                  <input v-model="answers[String(question.id)]" type="radio" :name="`question-${question.id}`" :value="option.label" />
                  <span>{{ option.text }}</span>
                </label>
              </div>

              <label v-else class="student-answer-box">
                <span>我的回答</span>
                <textarea
                  :value="answerText(question)"
                  rows="4"
                  placeholder="请输入你的回答"
                  @input="setTextAnswer(question, ($event.target as HTMLTextAreaElement).value)"
                ></textarea>
              </label>

              <small v-if="fieldError(question.id)" class="field-error">{{ fieldError(question.id) }}</small>
            </section>
          </div>

          <footer class="student-pretest-actions">
            <button class="student-ghost-button" type="button" @click="router.push('/student/courses')">稍后返回课程</button>
            <button class="student-primary-action" type="button" :disabled="submitting || !questions.length" @click="submitPaper">
              提交当前前测
            </button>
          </footer>
        </template>
        <p v-else class="empty">暂无可作答的前测。</p>
      </article>
    </section>
  </StudentShell>
</template>
