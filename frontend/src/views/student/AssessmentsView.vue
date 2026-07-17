<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getStudentAssessments, type TestAssessment } from '@/api/assessments'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const navItems = studentNav('/student/assessments')
const rows = ref<TestAssessment[]>([])
const loading = ref(false)
const notice = ref('')
const filter = ref<'all' | 'available' | 'finished'>('all')

const visibleRows = computed(() => rows.value.filter((item) => {
  if (filter.value === 'available') return item.available && (!item.attempt || item.attempt.status === 'in_progress')
  if (filter.value === 'finished') return item.attempt && item.attempt.status !== 'in_progress'
  return true
}))

const summary = computed(() => ({
  available: rows.value.filter((item) => item.available && (!item.attempt || item.attempt.status === 'in_progress')).length,
  inProgress: rows.value.filter((item) => Boolean(item.attempt?.id) && item.attempt?.status === 'in_progress').length,
  finished: rows.value.filter((item) => item.attempt && item.attempt.status !== 'in_progress').length
}))

function statusText(item: TestAssessment) {
  if (item.attempt?.status === 'graded') return '已完成'
  if (item.attempt?.status === 'submitted') return '待教师评分'
  if (item.attempt?.status === 'in_progress') return '继续作答'
  if (item.available) return '开始测试'
  if (item.status === 'published') return '等待教师开启'
  return item.status_label
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '教师手动控制'
}

async function load() {
  loading.value = true
  try { rows.value = await getStudentAssessments() }
  catch (error) { notice.value = error instanceof ApiError ? error.message : '测试列表加载失败。' }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <StudentShell title="测试" subtitle="课程检测与阶段测试" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <section class="student-test-summary">
      <article><span>可作答</span><strong>{{ summary.available }}</strong></article>
      <article><span>进行中</span><strong>{{ summary.inProgress }}</strong></article>
      <article><span>已完成</span><strong>{{ summary.finished }}</strong></article>
    </section>
    <div class="student-test-filter" role="tablist" aria-label="测试筛选">
      <button type="button" :class="{ active: filter === 'all' }" @click="filter = 'all'">全部</button>
      <button type="button" :class="{ active: filter === 'available' }" @click="filter = 'available'">待完成</button>
      <button type="button" :class="{ active: filter === 'finished' }" @click="filter = 'finished'">已完成</button>
    </div>
    <section class="student-test-grid">
      <article v-for="item in visibleRows" :key="item.id" class="student-test-card" :class="{ available: item.available, finished: item.attempt && item.attempt.status !== 'in_progress' }">
        <header><span>{{ item.subject.name }}</span><b>{{ item.status_label }}</b></header>
        <h2>{{ item.title }}</h2>
        <p>{{ item.instruction || '请在规定时间内独立完成测试。' }}</p>
        <dl><div><dt>试卷</dt><dd>{{ item.question_count }} 题 · {{ item.total_score }} 分</dd></div><div><dt>时长</dt><dd>{{ item.duration_minutes }} 分钟</dd></div><div><dt>教师</dt><dd>{{ item.teacher.display_name }}</dd></div><div><dt>截止</dt><dd>{{ formatDate(item.end_at) }}</dd></div></dl>
        <footer>
          <span v-if="item.attempt?.status === 'graded' && item.show_score_after_submit">得分 {{ item.attempt.total_score }} / {{ item.total_score }}</span>
          <span v-else>{{ statusText(item) }}</span>
          <RouterLink v-if="item.available || item.attempt" :to="`/student/assessments/${item.id}`">{{ statusText(item) }}</RouterLink>
          <button v-else type="button" disabled>{{ statusText(item) }}</button>
        </footer>
      </article>
      <p v-if="!loading && !visibleRows.length" class="empty">当前没有符合条件的测试。</p>
    </section>
  </StudentShell>
</template>
