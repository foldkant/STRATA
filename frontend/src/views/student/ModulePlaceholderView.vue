<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const route = useRoute()
const title = computed(() => String(route.meta.title || '学习模块'))
const description = computed(() => String(route.meta.description || '该模块会接入课程、课时和学习记录。'))
const navItems = computed(() => studentNav(route.path))
</script>

<template>
  <StudentShell :title="title" subtitle="学习空间" :nav-items="navItems">
    <section class="student-panel student-module-placeholder">
      <header>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </header>
      <div class="student-module-grid">
        <article>
          <strong>课程同步</strong>
          <span>内容会从教师发布的课程、课时、任务和项目中汇总。</span>
        </article>
        <article>
          <strong>学习记录</strong>
          <span>学生查看、作答和提交会写入学习行为事件。</span>
        </article>
      </div>
    </section>
  </StudentShell>
</template>
