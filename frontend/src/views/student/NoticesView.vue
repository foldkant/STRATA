<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getStudentNotices, type StudentNotice } from '@/api/student'
import type { PageResult } from '@/api/management'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const rows = ref<StudentNotice[]>([])
const page = ref<PageResult<StudentNotice> | null>(null)
const query = ref('')
const notice = ref('')
const loading = ref(false)
const navItems = studentNav('/student/notices')

const filteredRows = computed(() => {
  const value = query.value.trim().toLowerCase()
  if (!value) return rows.value
  return rows.value.filter((item) => `${item.title} ${item.content} ${item.teacher.display_name}`.toLowerCase().includes(value))
})

function formatDate(value: string | null) {
  if (!value) return '未设置时间'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function loadRows() {
  loading.value = true
  notice.value = ''
  try {
    page.value = await getStudentNotices({ page_size: 50 })
    rows.value = page.value.results
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '公告加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(loadRows)
</script>

<template>
  <StudentShell title="公告通知" subtitle="任课教师发布给本班的通知" :nav-items="navItems">
    <template #actions>
      <input v-model.trim="query" class="student-search-input" aria-label="搜索公告" placeholder="搜索公告" />
    </template>

    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <section v-if="loading" class="student-panel">
      <p class="empty">正在加载公告</p>
    </section>
    <section v-else class="student-notice-page">
      <article v-for="item in filteredRows" :key="item.id" class="student-notice-card">
        <header>
          <span v-if="item.is_pinned">置顶</span>
          <h2>{{ item.title }}</h2>
          <small>{{ item.teacher.display_name }} · {{ formatDate(item.published_at || item.created_at) }}</small>
        </header>
        <p>{{ item.content }}</p>
      </article>
      <p v-if="!filteredRows.length" class="empty">暂无公告。</p>
    </section>
  </StudentShell>
</template>
