<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'
import { teacherNav } from './nav'

const route = useRoute()
const title = computed(() => String(route.meta.title || '教师模块'))
const description = computed(() => String(route.meta.description || '该模块会按教师真实教学流程继续开发。'))
const navItems = computed(() => teacherNav(route.path))
</script>

<template>
  <AppShell :title="title" eyebrow="教师工作台" :nav-items="navItems">
    <section class="panel teacher-placeholder">
      <div class="panel-heading">
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </div>
      <div class="teacher-placeholder-grid">
        <article>
          <strong>当前阶段</strong>
          <span>页面骨架已接入教师端导航，后续会逐步连接 API 和业务数据。</span>
        </article>
        <article>
          <strong>权限边界</strong>
          <span>教师仅处理本人课程、资源、课堂活动和任教班级内学生数据。</span>
        </article>
        <article>
          <strong>数据采集</strong>
          <span>后续操作会统一写入学习行为事件，用于过程性评价和动态分层。</span>
        </article>
      </div>
    </section>
  </AppShell>
</template>
