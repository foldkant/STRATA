<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

defineProps<{
  title: string
  eyebrow: string
  navItems: Array<{ label: string; path: string; active?: boolean }>
  naturalScroll?: boolean
}>()

const auth = useAuthStore()
const router = useRouter()

async function signOut() {
  await auth.signOut()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell-natural': naturalScroll }">
    <aside class="sidebar">
      <RouterLink class="brand" to="/">
        <span class="brand-mark">2.0</span>
        <span>
          <strong>STRATA</strong>
          <small>数智教学系统</small>
        </span>
      </RouterLink>
      <nav class="nav-list">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="{ active: item.active }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <strong>{{ auth.user?.display_name || auth.user?.username }}</strong>
      </div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p>{{ eyebrow }}</p>
          <h1>{{ title }}</h1>
        </div>
        <div class="user-box">
          <span>{{ auth.user?.role_label }}</span>
          <button class="secondary-button" type="button" @click="signOut">退出</button>
        </div>
      </header>
      <main class="content">
        <slot />
      </main>
    </section>
  </div>
</template>
