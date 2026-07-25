<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRouter } from 'vue-router'
import {
  IconBell,
  IconLogout,
  IconMessageCircle
} from '@tabler/icons-vue'
import { useAuthStore } from '@/stores/auth'

defineProps<{
  title: string
  subtitle?: string
  navItems: Array<{ label: string; path: string; active?: boolean; icon?: Component }>
}>()

const auth = useAuthStore()
const router = useRouter()
const brandLogoUrl = '/static/brand/brand-logo.png?v=202607251130'
const currentUserName = computed(() => auth.user?.display_name || auth.user?.username || '同学')
const currentUserInitial = computed(() => currentUserName.value.trim().slice(0, 1).toUpperCase())

async function signOut() {
  await auth.signOut()
  router.push('/login')
}
</script>

<template>
  <div class="student-shell">
    <a class="skip-link" href="#student-main-content">跳到主要内容</a>
    <header class="student-topbar">
      <RouterLink class="student-brand" to="/student" aria-label="返回学生学习首页">
        <img
          class="student-brand-mark"
          :src="brandLogoUrl"
          alt=""
          width="891"
          height="891"
          aria-hidden="true"
        />
        <span>
          <strong>STRATA</strong>
          <small>学生学习空间</small>
        </span>
      </RouterLink>
      <nav id="student-navigation" class="student-nav" aria-label="学生学习导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="{ active: item.active }"
        >
          <component v-if="item.icon" :is="item.icon" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="student-user" aria-label="通知与账号">
        <RouterLink class="student-tool-link" to="/student/notices" aria-label="查看通知">
          <IconBell aria-hidden="true" />
          <span>通知</span>
        </RouterLink>
        <RouterLink class="student-tool-link" to="/student/feedback" aria-label="留言反馈">
          <IconMessageCircle aria-hidden="true" />
          <span>留言</span>
        </RouterLink>
        <span class="student-user-avatar" aria-hidden="true">{{ currentUserInitial }}</span>
        <span class="student-user-copy">
          <small>学生</small>
          <strong :title="currentUserName">{{ currentUserName }}</strong>
        </span>
        <button class="student-signout" type="button" aria-label="退出登录" @click="signOut">
          <IconLogout aria-hidden="true" />
          <span>退出</span>
        </button>
      </div>
    </header>

    <main id="student-main-content" class="student-main" tabindex="-1">
      <section class="student-page-heading">
        <div class="student-page-heading-copy">
          <p><span aria-hidden="true"></span>{{ subtitle || '学习空间' }}</p>
          <h1>{{ title }}</h1>
        </div>
        <div v-if="$slots.actions" class="student-page-actions">
          <slot name="actions" />
        </div>
      </section>
      <slot />
    </main>
  </div>
</template>
