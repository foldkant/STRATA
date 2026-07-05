<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import { getStudentCourse, type StudentCourse, type StudentLesson } from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId || 0))
const course = ref<StudentCourse | null>(null)
const notice = ref('')
const loading = ref(false)
const navItems = studentNav('/student/courses')

function courseInitial() {
  return course.value?.title.slice(0, 8) || '课程'
}

function pretestPath() {
  return course.value?.pretest_status.required && !course.value.pretest_status.completed && course.value.subject
    ? `/student/pretests/${course.value.subject.id}`
    : ''
}

function lessonTarget(lesson: StudentLesson) {
  const requiredPretestPath = pretestPath()
  if (requiredPretestPath) return requiredPretestPath
  if (lesson.classroom_session) {
    return lesson.classroom_session.status === 'running' ? `/student/classroom/${lesson.classroom_session.id}` : ''
  }
  return ''
}

function lessonStatusLabel(lesson: StudentLesson) {
  if (lesson.classroom_session) {
    if (lesson.classroom_session.status === 'running') {
      return lesson.classroom_session.current_step_status === 'idle'
        ? '课堂已启用，等待投放'
        : `课堂进行中 · ${lesson.classroom_session.current_step_status_label}`
    }
    if (lesson.classroom_session.status === 'finished') return '课堂已结束'
    return '等待教师启用课堂'
  }
  return '等待教师创建课堂'
}

onMounted(async () => {
  loading.value = true
  try {
    course.value = await getStudentCourse(courseId.value)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程详情加载失败。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <StudentShell title="课程详情" subtitle="课程学习" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="loading || !course" class="student-panel"><p class="empty">正在加载课程详情</p></section>

    <template v-else>
      <section class="student-course-hero">
        <img v-if="course.cover_url" :src="course.cover_url" :alt="course.title" />
        <div v-else class="student-course-cover hero"><strong>{{ courseInitial() }}</strong></div>
        <div>
          <span>{{ course.subject?.name || '未设置学科' }} · {{ course.teaching_model_label }}</span>
          <h2>{{ course.title }}</h2>
          <p>{{ course.introduction || '暂无课程简介。' }}</p>
          <div class="student-course-meta">
            <small>任课教师：{{ course.teacher.display_name }}</small>
            <small>{{ course.lesson_count }} 个课时</small>
            <small>{{ course.step_count }} 个学习环节</small>
          </div>
          <RouterLink
            v-if="course.pretest_status.required && !course.pretest_status.completed && course.subject"
            class="student-primary-action"
            :to="`/student/pretests/${course.subject.id}`"
          >
            完成学科前测
          </RouterLink>
        </div>
      </section>

      <section class="student-section">
        <header>
          <div>
            <h2>课时目录</h2>
            <p>按教师设计的学习过程进入课时。</p>
          </div>
        </header>
        <div class="student-lesson-list">
          <RouterLink
            v-for="lesson in (course.lessons || []).filter((item) => lessonTarget(item))"
            :key="lesson.id"
            class="student-lesson-row"
            :to="lessonTarget(lesson)"
          >
            <em>{{ lesson.sort_order || lesson.id }}</em>
            <span>
              <strong>{{ lesson.title }}</strong>
              <small>{{ lesson.content || '进入课时查看学习资源、活动和任务。' }}</small>
            </span>
            <i>{{ lessonStatusLabel(lesson) }}</i>
          </RouterLink>
          <button
            v-for="lesson in (course.lessons || []).filter((item) => !lessonTarget(item))"
            :key="`locked-${lesson.id}`"
            class="student-lesson-row disabled"
            type="button"
            disabled
          >
            <em>{{ lesson.sort_order || lesson.id }}</em>
            <span>
              <strong>{{ lesson.title }}</strong>
              <small>{{ lesson.content || '该课时由课堂教学控制。' }}</small>
            </span>
            <i>{{ lessonStatusLabel(lesson) }}</i>
          </button>
          <p v-if="!(course.lessons || []).length" class="empty">课程暂未发布课时。</p>
        </div>
      </section>
    </template>
  </StudentShell>
</template>
