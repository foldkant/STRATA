<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  getStudentAssessment,
  saveStudentAssessmentAnswer,
  startStudentAssessment,
  submitStudentAssessment,
  type AssessmentQuestion,
  type StudentAssessmentWorkspace
} from '@/api/assessments'

const route = useRoute()
const router = useRouter()
const assessmentId = computed(() => Number(route.params.assessmentId || 0))
const data = ref<StudentAssessmentWorkspace | null>(null)
const loading = ref(true)
const starting = ref(false)
const submitting = ref(false)
const notice = ref('')
const answers = ref<Record<string, string[]>>({})
const activeIndex = ref(0)
const savingIds = ref(new Set<number>())
const savedIds = ref(new Set<number>())
const secondsLeft = ref(0)
let timer = 0

const assessment = computed(() => data.value?.assessment || null)
const attempt = computed(() => data.value?.attempt || null)
const questions = computed(() => data.value?.questions || [])
const started = computed(() => Boolean(attempt.value))
const finished = computed(() => Boolean(attempt.value && attempt.value.status !== 'in_progress'))
const activeQuestion = computed(() => questions.value[activeIndex.value] || null)
const answeredCount = computed(() => questions.value.filter((item) => (answers.value[String(item.id)] || []).some((value) => value.trim())).length)
const timeText = computed(() => {
  const minutes = Math.floor(Math.max(secondsLeft.value, 0) / 60)
  const seconds = Math.max(secondsLeft.value, 0) % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})

function initializeWorkspace(payload: StudentAssessmentWorkspace) {
  data.value = payload
  answers.value = {}
  Object.entries(payload.answers || {}).forEach(([key, value]) => { answers.value[key] = Array.isArray(value) ? value.map(String) : [] })
  if (payload.deadline) secondsLeft.value = Math.max(0, Math.floor((new Date(payload.deadline).getTime() - Date.now()) / 1000))
  setupTimer()
}

function setupTimer() {
  window.clearInterval(timer)
  if (!attempt.value || finished.value) return
  timer = window.setInterval(async () => {
    secondsLeft.value = Math.max(0, secondsLeft.value - 1)
    if (secondsLeft.value === 0) {
      window.clearInterval(timer)
      await submit(false)
    }
  }, 1000)
}

function questionAnswer(question: AssessmentQuestion) {
  return answers.value[String(question.id)] || []
}

function isAnswered(question: AssessmentQuestion) {
  return questionAnswer(question).some((item) => item.trim())
}

async function persist(question: AssessmentQuestion, value: string[]) {
  if (!attempt.value || finished.value) return
  savingIds.value = new Set([...savingIds.value, question.id])
  try {
    await saveStudentAssessmentAnswer(assessmentId.value, question.id, value)
    savedIds.value = new Set([...savedIds.value, question.id])
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '答案保存失败，请重试。'
  } finally {
    const next = new Set(savingIds.value)
    next.delete(question.id)
    savingIds.value = next
  }
}

function setSingle(question: AssessmentQuestion, value: string) {
  answers.value = { ...answers.value, [String(question.id)]: [value] }
  persist(question, [value])
}

function toggleMultiple(question: AssessmentQuestion, value: string, checked: boolean) {
  const current = questionAnswer(question)
  const next = checked ? Array.from(new Set([...current, value])) : current.filter((item) => item !== value)
  answers.value = { ...answers.value, [String(question.id)]: next }
  persist(question, next)
}

function setText(question: AssessmentQuestion, value: string) {
  answers.value = { ...answers.value, [String(question.id)]: [value] }
}

function blurText(question: AssessmentQuestion) {
  persist(question, questionAnswer(question))
}

async function start() {
  starting.value = true
  notice.value = ''
  try {
    await startStudentAssessment(assessmentId.value)
    initializeWorkspace(await getStudentAssessment(assessmentId.value))
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '测试开始失败。'
  } finally { starting.value = false }
}

async function submit(confirmFirst = true) {
  if (confirmFirst && !window.confirm(`已完成 ${answeredCount.value} / ${questions.value.length} 题，确认交卷？交卷后不能修改。`)) return
  submitting.value = true
  try {
    const result = await submitStudentAssessment(assessmentId.value)
    if (data.value) data.value.attempt = result
    window.clearInterval(timer)
    notice.value = '测试已提交。'
    initializeWorkspace(await getStudentAssessment(assessmentId.value))
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '交卷失败。'
  } finally { submitting.value = false }
}

async function load() {
  loading.value = true
  try { initializeWorkspace(await getStudentAssessment(assessmentId.value)) }
  catch (error) { notice.value = error instanceof ApiError ? error.message : '测试加载失败。' }
  finally { loading.value = false }
}

onMounted(load)
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="student-assessment-shell">
    <header class="student-assessment-topbar">
      <div><button type="button" @click="router.push('/student/assessments')">返回</button><span>STRATA 测试</span></div>
      <strong>{{ assessment?.title || '测试' }}</strong>
      <div v-if="started && !finished" class="student-test-timer" :class="{ urgent: secondsLeft < 300 }"><span>剩余时间</span><b>{{ timeText }}</b></div>
      <span v-else>{{ assessment?.status_label || '' }}</span>
    </header>

    <main v-if="loading" class="student-assessment-loading"><p>正在加载测试</p></main>
    <main v-else-if="!data || !assessment" class="student-assessment-loading"><p>{{ notice || '测试不存在。' }}</p></main>
    <main v-else-if="!started" class="student-assessment-intro">
      <section><span>{{ assessment.subject.name }}</span><h1>{{ assessment.title }}</h1><p>{{ assessment.instruction || '请在规定时间内独立完成测试。' }}</p><dl><div><dt>题目</dt><dd>{{ assessment.question_count }} 题</dd></div><div><dt>总分</dt><dd>{{ assessment.total_score }} 分</dd></div><div><dt>时长</dt><dd>{{ assessment.duration_minutes }} 分钟</dd></div><div><dt>班级</dt><dd>{{ assessment.target_classes.map((item) => item.name).join('、') }}</dd></div></dl><p v-if="notice" class="student-assessment-notice">{{ notice }}</p><button type="button" :disabled="starting || !assessment.available" @click="start">{{ starting ? '正在进入' : assessment.available ? '开始测试' : '测试暂未开放' }}</button></section>
    </main>

    <main v-else class="student-assessment-workspace">
      <aside class="student-question-nav"><header><strong>答题卡</strong><span>{{ answeredCount }} / {{ questions.length }}</span></header><div><button v-for="(item, index) in questions" :key="item.id" type="button" :class="{ active: activeIndex === index, answered: isAnswered(item) }" @click="activeIndex = index">{{ index + 1 }}</button></div><footer><i></i><span>已作答</span><i></i><span>未作答</span></footer></aside>

      <section v-if="finished" class="student-assessment-finished"><span>已交卷</span><h1>{{ assessment.title }}</h1><p>{{ attempt?.status === 'submitted' ? '答卷已提交，主观题等待教师评分。' : '测试已完成。' }}</p><strong v-if="data.result">{{ data.result.score }} / {{ data.result.total_score }} 分</strong><button type="button" @click="router.push('/student/assessments')">返回测试列表</button></section>

      <section v-else-if="activeQuestion" class="student-assessment-question-stage">
        <header><div><span>第 {{ activeIndex + 1 }} 题 · {{ activeQuestion.question_type_label }}</span><small>{{ activeQuestion.knowledge_point || '课程测试' }}</small></div><b>{{ activeQuestion.score }} 分</b></header>
        <h2>{{ activeQuestion.stem }}</h2>
        <div v-if="['single', 'judge'].includes(activeQuestion.question_type)" class="student-assessment-options"><label v-for="(option, index) in activeQuestion.options" :key="option"><input type="radio" :name="`question-${activeQuestion.id}`" :checked="questionAnswer(activeQuestion)[0] === option" @change="setSingle(activeQuestion, option)" /><span><b>{{ String.fromCharCode(65 + index) }}</b>{{ option }}</span></label></div>
        <div v-else-if="activeQuestion.question_type === 'multiple'" class="student-assessment-options"><label v-for="(option, index) in activeQuestion.options" :key="option"><input type="checkbox" :checked="questionAnswer(activeQuestion).includes(option)" @change="toggleMultiple(activeQuestion, option, ($event.target as HTMLInputElement).checked)" /><span><b>{{ String.fromCharCode(65 + index) }}</b>{{ option }}</span></label></div>
        <label v-else class="student-assessment-text-answer"><span>{{ activeQuestion.question_type === 'blank' ? '填写答案' : '我的回答' }}</span><textarea :value="questionAnswer(activeQuestion)[0] || ''" :rows="activeQuestion.question_type === 'blank' ? 3 : 9" maxlength="5000" placeholder="请输入答案" @input="setText(activeQuestion, ($event.target as HTMLTextAreaElement).value)" @blur="blurText(activeQuestion)"></textarea></label>
        <footer><div><span v-if="savingIds.has(activeQuestion.id)">正在保存</span><span v-else-if="savedIds.has(activeQuestion.id) || isAnswered(activeQuestion)">答案已保存</span></div><div><button type="button" :disabled="activeIndex === 0" @click="activeIndex--">上一题</button><button v-if="activeIndex < questions.length - 1" type="button" @click="activeIndex++">下一题</button><button v-else class="submit" type="button" :disabled="submitting" @click="submit(true)">交卷</button></div></footer>
      </section>
    </main>
  </div>
</template>
