<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getStudentArchive, type StudentArchive } from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const data = ref<StudentArchive | null>(null)
const loading = ref(false)
const notice = ref('')
const selectedSubject = ref('')
const navItems = studentNav('/student/profile')

const className = computed(() => {
  const group = data.value?.student.class_group
  return group ? `${group.grade ? `${group.grade} ` : ''}${group.name}` : '未选择班级'
})

const studentInitial = computed(() => (data.value?.student.display_name || '学').slice(0, 1))

function formatDate(value: string | null, includeTime = false) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', includeTime
    ? { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }
    : { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function scoreText(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

async function load() {
  loading.value = true
  notice.value = ''
  try {
    data.value = await getStudentArchive(selectedSubject.value)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习档案加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <StudentShell title="学习档案" :subtitle="className" :nav-items="navItems">
    <template #actions>
      <label class="student-archive-subject-filter">
        <span>学科</span>
        <select v-model="selectedSubject" :disabled="loading" @change="load">
          <option value="">全部学科</option>
          <option v-for="item in data?.subjects || []" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>
    </template>

    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="loading && !data" class="student-panel"><p class="empty">正在整理学习档案</p></section>

    <template v-else-if="data">
      <section class="student-archive-identity">
        <div class="student-archive-avatar" aria-hidden="true">{{ studentInitial }}</div>
        <div class="student-archive-person">
          <span>{{ data.student.school?.name || '学校' }}</span>
          <h2>{{ data.student.display_name }}</h2>
          <p>{{ className }} · 账号 {{ data.student.username }} · 学号 {{ data.student.student_no || '待补充' }}</p>
        </div>
        <div class="student-archive-latest">
          <span>最近学习</span>
          <strong>{{ formatDate(data.metrics.last_activity_at, true) }}</strong>
        </div>
      </section>

      <section class="student-archive-metrics" aria-label="学习概览">
        <article><span>课程</span><strong>{{ data.metrics.course_count }}</strong><small>当前可学习</small></article>
        <article><span>活跃天数</span><strong>{{ data.metrics.active_day_count }}</strong><small>累计有学习记录</small></article>
        <article><span>学习记录</span><strong>{{ data.metrics.learning_event_count }}</strong><small>已采集过程行为</small></article>
        <article><span>完成测试</span><strong>{{ data.metrics.completed_test_count }}</strong><small>已完成评分</small></article>
        <article><span>提交作品</span><strong>{{ data.metrics.work_count }}</strong><small>课堂附件作品</small></article>
      </section>

      <section class="student-archive-section">
        <header><div><h2>课程学习</h2><p>课时进入与学习环节完成情况</p></div></header>
        <div class="student-archive-course-list">
          <RouterLink v-for="course in data.courses" :key="course.id" :to="`/student/courses/${course.id}`">
            <div><span>{{ course.subject?.name || '未设置学科' }}</span><strong>{{ course.title }}</strong><small>{{ course.teacher.display_name }} · 最近 {{ formatDate(course.last_activity_at, true) }}</small></div>
            <div class="student-archive-course-progress"><span><b>{{ course.completed_step_count }}</b> / {{ course.step_count }} 个环节</span><i><em :style="{ width: `${course.progress_percent}%` }"></em></i><small>进入 {{ course.visited_lesson_count }} / {{ course.lesson_count }} 个课时</small></div>
          </RouterLink>
          <p v-if="!data.courses.length" class="empty">当前学科暂无课程学习记录。</p>
        </div>
      </section>

      <div class="student-archive-two-column">
        <section class="student-archive-section">
          <header><div><h2>测试记录</h2><p>测试成绩与批阅状态</p></div><RouterLink to="/student/assessments">进入测试</RouterLink></header>
          <div class="student-archive-test-list">
            <article v-for="item in data.tests" :key="item.id">
              <div><span>{{ item.subject.name }} · {{ item.status_label }}</span><strong>{{ item.title }}</strong><small>{{ formatDate(item.submitted_at || item.started_at, true) }}</small></div>
              <div><strong>{{ scoreText(item.total_score) }}<small> / {{ scoreText(item.total_possible) }}</small></strong><span>客观 {{ scoreText(item.objective_score) }} · 主观 {{ scoreText(item.subjective_score) }}</span></div>
            </article>
            <p v-if="!data.tests.length" class="empty">暂无测试记录。</p>
          </div>
          <div v-if="data.pretests.length" class="student-archive-pretests">
            <strong>学科前测</strong>
            <span v-for="item in data.pretests" :key="item.id">{{ item.subject.name }} · {{ item.kind_label }} · {{ item.kind === 'attitude' ? '已完成' : `${scoreText(item.score)} 分` }}</span>
          </div>
        </section>

        <section class="student-archive-section">
          <header><div><h2>课堂参与</h2><p>学习行为类型分布</p></div></header>
          <div class="student-archive-distribution">
            <article v-for="item in data.event_distribution" :key="item.event_type"><div><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div><i><em :style="{ width: `${item.percent}%` }"></em></i></article>
            <p v-if="!data.event_distribution.length" class="empty">暂无课堂参与记录。</p>
          </div>
        </section>
      </div>

      <div class="student-archive-two-column">
        <section class="student-archive-section">
          <header><div><h2>作品与任务</h2><p>课堂附件提交与教师反馈</p></div></header>
          <div class="student-archive-work-list">
            <article v-for="item in data.works" :key="item.id"><div><span>{{ item.subject?.name || '课程' }} · {{ item.status_label }}</span><strong>{{ item.question_stem || item.attachment_name }}</strong><small>{{ item.course_title }} · {{ item.lesson_title }} · {{ formatDate(item.updated_at, true) }}</small><p v-if="item.feedback">教师反馈：{{ item.feedback }}</p></div><div><strong v-if="item.score !== null">{{ scoreText(item.score) }} 分</strong><a :href="item.attachment_url" target="_blank" rel="noopener">查看作品</a></div></article>
            <p v-if="!data.works.length" class="empty">暂无附件作品记录。</p>
          </div>
        </section>

        <section class="student-archive-section">
          <header><div><h2>评价记录</h2><p>自评、互评与教师评价</p></div></header>
          <div class="student-archive-evaluation-list">
            <article v-for="item in data.evaluations" :key="item.id"><div><span>{{ item.evaluation_type_label }} · {{ item.course.title }}</span><strong>{{ item.evaluator_label }}</strong></div><div v-if="item.average_rating !== null" class="student-archive-stars" :aria-label="`${item.average_rating} 星`"><span v-for="star in 5" :key="star" :class="{ active: star <= Math.round(item.average_rating || 0) }">★</span><small>{{ item.average_rating }}</small></div><p v-if="item.comment">{{ item.comment }}</p><small>{{ formatDate(item.updated_at, true) }}</small></article>
            <p v-if="!data.evaluations.length" class="empty">暂无评价记录。</p>
          </div>
        </section>
      </div>

      <section class="student-archive-section">
        <header><div><h2>最近学习轨迹</h2><p>按时间记录课程学习与提交</p></div></header>
        <div class="student-archive-timeline">
          <article v-for="item in data.recent_events" :key="item.id"><i></i><time>{{ formatDate(item.occurred_at, true) }}</time><div><strong>{{ item.label }}</strong><span>{{ item.course?.title || '平台学习' }}<template v-if="item.lesson"> · {{ item.lesson.title }}</template></span></div></article>
          <p v-if="!data.recent_events.length" class="empty">暂无学习轨迹。</p>
        </div>
      </section>
    </template>
  </StudentShell>
</template>
