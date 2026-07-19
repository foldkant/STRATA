<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useRouteMenu } from '@/composables/useRouteMenu'

defineProps<{
  title: string
  eyebrow: string
  navItems: Array<{ label: string; path: string; active?: boolean }>
  naturalScroll?: boolean
}>()

const auth = useAuthStore()
const router = useRouter()
const { isOpen: mobileNavOpen, close: closeMobileNav, toggle: toggleMobileNav } = useRouteMenu()

async function signOut() {
  await auth.signOut()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell-natural': naturalScroll }">
    <a class="skip-link" href="#app-main-content">跳到主要内容</a>
    <button
      v-if="mobileNavOpen"
      class="shell-nav-backdrop"
      type="button"
      aria-label="关闭导航"
      @click="closeMobileNav"
    />
    <aside id="app-shell-navigation" class="sidebar" :class="{ open: mobileNavOpen }">
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
          @click="closeMobileNav"
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
          <button
            class="secondary-button shell-nav-toggle"
            type="button"
            aria-controls="app-shell-navigation"
            :aria-expanded="mobileNavOpen"
            @click="toggleMobileNav"
          >
            导航
          </button>
          <span>{{ auth.user?.role_label }}</span>
          <button class="secondary-button" type="button" @click="signOut">退出</button>
        </div>
      </header>
      <main id="app-main-content" class="content" tabindex="-1">
        <slot />
      </main>
    </section>
  </div>
</template>
