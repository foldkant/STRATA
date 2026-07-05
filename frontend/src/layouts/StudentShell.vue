<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

defineProps<{
  title: string
  subtitle?: string
  navItems: Array<{ label: string; path: string; active?: boolean }>
}>()

const auth = useAuthStore()
const router = useRouter()

async function signOut() {
  await auth.signOut()
  router.push('/login')
}
</script>

<template>
  <div class="student-shell">
    <header class="student-topbar">
      <RouterLink class="student-brand" to="/student">
        <span class="student-brand-mark">S</span>
        <span>
          <strong>STRATA</strong>
          <small>数智教学系统</small>
        </span>
      </RouterLink>
      <nav class="student-nav">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" :class="{ active: item.active }">
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="student-user">
        <span>{{ auth.user?.display_name || auth.user?.username }}</span>
        <button class="student-ghost-button" type="button" @click="signOut">退出</button>
      </div>
    </header>

    <main class="student-main">
      <section class="student-page-heading">
        <div>
          <p>{{ subtitle || '学习空间' }}</p>
          <h1>{{ title }}</h1>
        </div>
        <slot name="actions" />
      </section>
      <slot />
    </main>
  </div>
</template>
