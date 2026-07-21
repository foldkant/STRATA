<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getStudentCourses, type StudentCourse } from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const rows = ref<StudentCourse[]>([])
const loading = ref(false)
const notice = ref('')
const query = ref('')
const navItems = studentNav('/student/courses')

const filteredRows = computed(() => {
  const value = query.value.trim().toLowerCase()
  if (!value) return rows.value
  return rows.value.filter((item) =>
    `${item.title} ${item.subject?.name || ''} ${item.teacher.display_name}`.toLowerCase().includes(value)
  )
})

function courseInitial(course: StudentCourse) {
  return course.title.slice(0, 8)
}

onMounted(async () => {
  loading.value = true
  try {
    rows.value = await getStudentCourses()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程加载失败。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <StudentShell title="我的课程" subtitle="按班级发布的学习内容" :nav-items="navItems">
    <template #actions>
      <input v-model.trim="query" class="student-search-input" aria-label="搜索课程" placeholder="搜索课程、学科或教师" />
    </template>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <section v-if="loading" class="student-panel"><p class="empty">正在加载课程</p></section>
    <section v-else class="student-course-grid wide">
      <RouterLink v-for="course in filteredRows" :key="course.id" class="student-course-card large" :to="`/student/courses/${course.id}`">
        <img v-if="course.cover_url" :src="course.cover_url" :alt="course.title" />
        <div v-else class="student-course-cover"><strong>{{ courseInitial(course) }}</strong></div>
        <div>
          <span>{{ course.subject?.name || '未设置学科' }} · {{ course.teaching_model_label }}</span>
          <h3>{{ course.title }}</h3>
          <p>{{ course.introduction || '暂无课程简介。' }}</p>
        </div>
        <footer>
          <small>{{ course.teacher.display_name }}</small>
          <small>{{ course.lesson_count }} 个课时</small>
          <small v-if="course.pretest_status.required && !course.pretest_status.completed">需前测</small>
          <small v-else>可学习</small>
        </footer>
      </RouterLink>
      <p v-if="!filteredRows.length" class="empty">暂无匹配课程。</p>
    </section>
  </StudentShell>
</template>
