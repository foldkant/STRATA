<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import { getTeacherStudentLearningProfile } from '@/api/teacher'
import type { StudentArchive } from '@/api/student'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

type ArchiveSection = 'overview' | 'courses' | 'assessments' | 'feedback'

const route = useRoute()
const data = ref<StudentArchive | null>(null)
const loading = ref(false)
const notice = ref('')
const selectedSubject = ref('')
const activeSection = ref<ArchiveSection>('overview')
const navItems = teacherNav('/teacher/students')

const studentId = computed(() => Number(route.params.studentId))
const className = computed(() => {
  const group = data.value?.student.class_group
  return group ? `${group.grade ? `${group.grade} ` : ''}${group.name}` : '未分班'
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
  if (!Number.isInteger(studentId.value) || studentId.value <= 0) {
    notice.value = '学生编号不正确，请返回学生列表重新选择。'
    data.value = null
    return
  }
  loading.value = true
  notice.value = ''
  try {
    data.value = await getTeacherStudentLearningProfile(studentId.value, selectedSubject.value)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学生学习档案加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(studentId, () => {
  selectedSubject.value = ''
  activeSection.value = 'overview'
  load()
})
</script>

<template>
  <AppShell title="学生学习档案" eyebrow="学生学习情况" :nav-items="navItems" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <header class="teacher-archive-toolbar">
      <RouterLink class="secondary-button" to="/teacher/students">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
        返回学生列表
      </RouterLink>
      <label class="student-archive-subject-filter">
        <span>查看学科</span>
        <AppSelect v-model="selectedSubject" :disabled="loading || !data" @change="load">
          <option value="">全部任教学科</option>
          <option v-for="item in data?.subjects || []" :key="item.id" :value="item.id">{{ item.name }}</option>
        </AppSelect>
      </label>
    </header>

    <section v-if="loading && !data" class="panel teacher-archive-loading">
      <p class="empty">正在整理该生学习档案</p>
    </section>

    <template v-else-if="data">
      <section class="student-archive-identity teacher-archive-identity">
        <div class="student-archive-avatar" aria-hidden="true">{{ studentInitial }}</div>
        <div class="student-archive-person">
          <span>{{ data.student.school?.name || '学校' }}</span>
          <h2>{{ data.student.display_name }}</h2>
          <p>{{ className }} · 账号 {{ data.student.username }} · 学号 {{ data.student.student_no || '待补充' }}</p>
        </div>
        <div class="student-archive-latest">
          <span>最近学习</span>
          <strong>{{ formatDate(data.metrics.last_activity_at, true) }}</strong>
          <small>仅显示本人任教学科课程相关记录</small>
        </div>
      </section>

      <section class="student-archive-metrics" aria-label="该生学习概览">
        <article><span>课程</span><strong>{{ data.metrics.course_count }}</strong><small>本人任教课程</small></article>
        <article><span>活跃天数</span><strong>{{ data.metrics.active_day_count }}</strong><small>有学习记录</small></article>
        <article><span>学习记录</span><strong>{{ data.metrics.learning_event_count }}</strong><small>过程记录</small></article>
        <article><span>完成测试</span><strong>{{ data.metrics.completed_test_count }}</strong><small>已完成评分</small></article>
        <article><span>提交作品</span><strong>{{ data.metrics.work_count }}</strong><small>课堂作品</small></article>
      </section>

      <nav class="student-archive-tabs" aria-label="学生学习档案内容">
        <button type="button" :aria-current="activeSection === 'overview' ? 'page' : undefined" :class="{ active: activeSection === 'overview' }" @click="activeSection = 'overview'">学习概览</button>
        <button type="button" :aria-current="activeSection === 'courses' ? 'page' : undefined" :class="{ active: activeSection === 'courses' }" @click="activeSection = 'courses'">课程学习</button>
        <button type="button" :aria-current="activeSection === 'assessments' ? 'page' : undefined" :class="{ active: activeSection === 'assessments' }" @click="activeSection = 'assessments'">测试与作品</button>
        <button type="button" :aria-current="activeSection === 'feedback' ? 'page' : undefined" :class="{ active: activeSection === 'feedback' }" @click="activeSection = 'feedback'">评价与轨迹</button>
      </nav>

      <div v-if="activeSection === 'overview'" class="student-archive-two-column">
        <section class="student-archive-section">
          <header><div><h2>学习活动分布</h2><p>本人任教学科课程中的学习活动记录</p></div></header>
          <div class="student-archive-distribution">
            <article v-for="item in data.event_distribution" :key="item.event_type">
              <div><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
              <i><em :style="{ width: `${item.percent}%` }"></em></i>
            </article>
            <p v-if="!data.event_distribution.length" class="empty">当前范围暂无学习活动记录。</p>
          </div>
        </section>

        <section class="student-archive-section">
          <header><div><h2>最近学习</h2><p>最近 8 条课程学习与提交记录</p></div></header>
          <div class="student-archive-timeline">
            <article v-for="item in data.recent_events.slice(0, 5)" :key="item.id">
              <i></i>
              <time>{{ formatDate(item.occurred_at, true) }}</time>
              <div><strong>{{ item.label }}</strong><span>{{ item.course?.title || '课程学习' }}<template v-if="item.lesson"> · {{ item.lesson.title }}</template></span></div>
            </article>
            <p v-if="!data.recent_events.length" class="empty">当前范围暂无学习轨迹。</p>
            <button
              v-if="data.recent_events.length > 5"
              class="teacher-archive-more"
              type="button"
              @click="activeSection = 'feedback'"
            >
              查看完整学习轨迹
            </button>
          </div>
        </section>
      </div>

      <section v-if="activeSection === 'courses'" class="student-archive-section">
        <header><div><h2>课程学习</h2><p>本人任教课程中的课时进入与学习环节完成情况</p></div></header>
        <div class="student-archive-course-list">
          <article v-for="course in data.courses" :key="course.id" class="teacher-archive-course">
            <div>
              <span>{{ course.subject?.name || '未设置学科' }}</span>
              <strong>{{ course.title }}</strong>
              <small>最近学习 {{ formatDate(course.last_activity_at, true) }}</small>
            </div>
            <div class="student-archive-course-progress">
              <span><b>{{ course.completed_step_count }}</b> / {{ course.step_count }} 个环节</span>
              <i><em :style="{ width: `${course.progress_percent}%` }"></em></i>
              <small>进入 {{ course.visited_lesson_count }} / {{ course.lesson_count }} 个课时</small>
            </div>
          </article>
          <p v-if="!data.courses.length" class="empty">当前学科暂无本人任教课程记录。</p>
        </div>
      </section>

      <div v-if="activeSection === 'assessments'" class="student-archive-two-column">
        <section class="student-archive-section">
          <header><div><h2>测试记录</h2><p>本人布置的测试及其评分情况</p></div></header>
          <div class="student-archive-test-list">
            <article v-for="item in data.tests" :key="item.id">
              <div><span>{{ item.subject.name }} · {{ item.status_label }}</span><strong>{{ item.title }}</strong><small>{{ formatDate(item.submitted_at || item.started_at, true) }}</small></div>
              <div><strong>{{ scoreText(item.total_score) }}<small> / {{ scoreText(item.total_possible) }}</small></strong><span>客观 {{ scoreText(item.objective_score) }} · 主观 {{ scoreText(item.subjective_score) }}</span></div>
            </article>
            <p v-if="!data.tests.length" class="empty">当前范围暂无测试记录。</p>
          </div>
          <div v-if="data.pretests.length" class="student-archive-pretests">
            <strong>学科前测</strong>
            <span v-for="item in data.pretests" :key="item.id">{{ item.subject.name }} · {{ item.kind_label }} · {{ item.kind === 'attitude' ? '已完成' : `${scoreText(item.score)} 分` }}</span>
          </div>
        </section>

        <section class="student-archive-section">
          <header><div><h2>作品与任务</h2><p>课堂作品提交与教师反馈</p></div></header>
          <div class="student-archive-work-list">
            <article v-for="item in data.works" :key="item.id">
              <div><span>{{ item.subject?.name || '课程' }} · {{ item.status_label }}</span><strong>{{ item.question_stem || item.attachment_name }}</strong><small>{{ item.course_title }} · {{ item.lesson_title }} · {{ formatDate(item.updated_at, true) }}</small><p v-if="item.feedback">教师反馈：{{ item.feedback }}</p></div>
              <div><strong v-if="item.score !== null">{{ scoreText(item.score) }} 分</strong><a :href="item.attachment_url" target="_blank" rel="noopener">查看作品</a></div>
            </article>
            <p v-if="!data.works.length" class="empty">当前范围暂无作品记录。</p>
          </div>
        </section>
      </div>

      <div v-if="activeSection === 'feedback'" class="student-archive-two-column">
        <section class="student-archive-section">
          <header><div><h2>评价记录</h2><p>与本人任教课程相关的自评、互评和教师评价</p></div></header>
          <div class="student-archive-evaluation-list">
            <article v-for="item in data.evaluations" :key="item.id">
              <div><span>{{ item.evaluation_type_label }} · {{ item.course.title }}</span><strong>{{ item.evaluator_label }}</strong></div>
              <div v-if="item.average_rating !== null" class="student-archive-stars" :aria-label="`${item.average_rating} 星`"><span v-for="star in 5" :key="star" :class="{ active: star <= Math.round(item.average_rating || 0) }">★</span><small>{{ item.average_rating }}</small></div>
              <p v-if="item.comment">{{ item.comment }}</p>
              <small>{{ formatDate(item.updated_at, true) }}</small>
            </article>
            <p v-if="!data.evaluations.length" class="empty">当前范围暂无评价记录。</p>
          </div>
        </section>

        <section class="student-archive-section">
          <header><div><h2>学习轨迹</h2><p>按时间查看本人任教学科课程中的过程记录</p></div></header>
          <div class="student-archive-timeline">
            <article v-for="item in data.recent_events" :key="item.id">
              <i></i>
              <time>{{ formatDate(item.occurred_at, true) }}</time>
              <div><strong>{{ item.label }}</strong><span>{{ item.course?.title || '课程学习' }}<template v-if="item.lesson"> · {{ item.lesson.title }}</template></span></div>
            </article>
            <p v-if="!data.recent_events.length" class="empty">当前范围暂无学习轨迹。</p>
          </div>
        </section>
      </div>
    </template>
  </AppShell>
</template>

<style scoped>
.teacher-archive-toolbar {
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.teacher-archive-toolbar > a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.teacher-archive-toolbar svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.teacher-archive-loading {
  min-height: 260px;
  display: grid;
  place-items: center;
}

.teacher-archive-identity {
  margin-top: 0;
}

.student-archive-latest small {
  max-width: 240px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.teacher-archive-course {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 0.55fr);
  align-items: center;
  gap: 24px;
  border-top: 1px solid var(--line);
  padding: 18px 0;
}

.teacher-archive-course:first-child {
  border-top: 0;
}

.teacher-archive-course > div:first-child {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.teacher-archive-course span,
.teacher-archive-course small {
  color: var(--muted);
  font-size: 13px;
}

.teacher-archive-course strong {
  color: var(--ink);
  font-size: 16px;
}

.teacher-archive-more {
  min-height: 44px;
  justify-self: start;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--primary);
  font-weight: 700;
  cursor: pointer;
}

.teacher-archive-more:hover {
  color: var(--primary-dark);
}

@media (max-width: 720px) {
  .teacher-archive-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .teacher-archive-toolbar > a {
    align-self: flex-start;
  }

  .teacher-archive-toolbar .student-archive-subject-filter {
    width: 100%;
  }

  .teacher-archive-course {
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
  }
}
</style>
