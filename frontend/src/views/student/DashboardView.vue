<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getStudentDashboard, type StudentDashboard, type StudentCourse } from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const data = ref<StudentDashboard | null>(null)
const notice = ref('')
const navItems = studentNav('/student')

const className = computed(() => {
  const classGroup = data.value?.profile.class_group
  if (!classGroup) return '未选择班级'
  return `${classGroup.grade ? `${classGroup.grade} ` : ''}${classGroup.name}`
})

function courseInitial(course: StudentCourse) {
  return course.title.slice(0, 6)
}

function formatDate(value: string | null) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

onMounted(async () => {
  try {
    data.value = await getStudentDashboard()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学生首页加载失败。'
  }
})
</script>

<template>
  <StudentShell title="学习首页" :subtitle="className" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="!data" class="student-panel"><p class="empty">正在加载学习空间</p></section>

    <template v-else>
      <section class="student-home-announcements">
        <header>
          <div><span>公告通知</span><strong>班级与课程动态</strong></div>
          <RouterLink to="/student/notices">全部公告</RouterLink>
        </header>
        <div v-if="data.notice_rows.length" class="student-home-announcement-list">
          <article v-for="item in data.notice_rows.slice(0, 3)" :key="item.id">
            <div><b v-if="item.is_pinned">置顶</b><strong>{{ item.title }}</strong></div>
            <p>{{ item.content }}</p>
            <small>{{ item.teacher.display_name }} · {{ formatDate(item.published_at || item.created_at) }}</small>
          </article>
        </div>
        <p v-else class="empty">暂无新公告。</p>
      </section>

      <section class="student-hero-grid">
        <article class="student-live-card" :class="{ active: data.current_classroom }">
          <span>{{ data.current_classroom ? '课堂进行中' : '当前没有进行中的课堂' }}</span>
          <strong>{{ data.current_classroom?.title || '按课程继续学习' }}</strong>
          <p v-if="data.current_classroom">
            {{ data.current_classroom.course?.title }} · {{ data.current_classroom.lesson?.title || '未指定课时' }}
          </p>
          <p v-else>可以从最近课程进入课时学习，或等待教师开启课堂。</p>
          <RouterLink
            v-if="data.current_classroom"
            class="student-primary-action"
            :to="`/student/classroom/${data.current_classroom.id}`"
            target="_blank"
            rel="noopener"
          >
            进入课堂
          </RouterLink>
          <RouterLink v-else class="student-primary-action" to="/student/courses">查看课程</RouterLink>
        </article>

        <article class="student-panel student-todo-card">
          <header>
            <h2>待完成</h2>
            <RouterLink to="/student/tasks">全部</RouterLink>
          </header>
          <div class="student-todo-list">
            <RouterLink v-for="item in data.todo_rows" :key="`${item.label}-${item.path}`" :to="item.path" :class="item.level">
              <strong>{{ item.label }}</strong>
              <span>{{ item.detail }}</span>
            </RouterLink>
            <p v-if="!data.todo_rows.length" class="empty">暂无必须处理的事项。</p>
          </div>
        </article>
      </section>

      <section class="student-metric-strip">
        <article v-for="item in data.metrics" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.sub }}</small>
        </article>
      </section>

      <section class="student-section">
        <header>
          <div>
            <h2>最近课程</h2>
            <p>继续上次的学习，或进入新的课时。</p>
          </div>
          <RouterLink to="/student/courses">全部课程</RouterLink>
        </header>
        <div class="student-course-grid">
          <RouterLink v-for="course in data.course_rows" :key="course.id" class="student-course-card" :to="`/student/courses/${course.id}`">
            <img v-if="course.cover_url" :src="course.cover_url" :alt="course.title" />
            <div v-else class="student-course-cover"><strong>{{ courseInitial(course) }}</strong></div>
            <div>
              <span>{{ course.subject?.name || '未设置学科' }}</span>
              <h3>{{ course.title }}</h3>
              <p>{{ course.teacher.display_name }} · {{ course.lesson_count }} 个课时</p>
            </div>
            <small v-if="course.pretest_status.required && !course.pretest_status.completed">需完成前测</small>
            <small v-else>可学习</small>
          </RouterLink>
          <p v-if="!data.course_rows.length" class="empty">当前班级暂无已发布课程。</p>
        </div>
      </section>

    </template>
  </StudentShell>
</template>
