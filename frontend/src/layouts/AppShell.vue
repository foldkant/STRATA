<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, type Component } from 'vue'
import { useRouter } from 'vue-router'
import {
  IconChalkboardTeacher,
  IconLogout,
  IconMenu2,
  IconSchool,
  IconShieldLock
} from '@tabler/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useRouteMenu } from '@/composables/useRouteMenu'

type NavItem = {
  label: string
  path: string
  active?: boolean
  group?: string
  icon?: Component
}

const props = defineProps<{
  title: string
  eyebrow: string
  navItems: NavItem[]
  naturalScroll?: boolean
  shellVariant?: 'default' | 'teacher' | 'super-admin' | 'school-admin'
}>()

const auth = useAuthStore()
const router = useRouter()
const { isOpen: mobileNavOpen, close: closeMobileNav, toggle: toggleMobileNav } = useRouteMenu()
const currentUserName = computed(() => auth.user?.display_name || auth.user?.username || '当前用户')
const currentUserInitial = computed(() => currentUserName.value.trim().slice(0, 1).toUpperCase())
const isSuperAdminShell = computed(() => props.shellVariant === 'super-admin')
const isSchoolAdminShell = computed(() => props.shellVariant === 'school-admin')
const isInstitutionalShell = computed(() => isSuperAdminShell.value || isSchoolAdminShell.value)
const isTeacherShell = computed(
  () => props.shellVariant === 'teacher' || (!props.shellVariant && auth.user?.role === 'teacher')
)
const isRefinedShell = computed(() => isInstitutionalShell.value || isTeacherShell.value)
const navGroups = computed(() => {
  const groups: Array<{ label: string; items: NavItem[] }> = []
  props.navItems.forEach((item) => {
    const label = item.group || ''
    const current = groups[groups.length - 1]
    if (!current || current.label !== label) {
      groups.push({ label, items: [item] })
    } else {
      current.items.push(item)
    }
  })
  return groups
})

onMounted(() => {
  if (isInstitutionalShell.value) document.body.classList.add('super-admin-theme-active')
  if (isSchoolAdminShell.value) document.body.classList.add('school-admin-theme-active')
})

onBeforeUnmount(() => {
  document.body.classList.remove('super-admin-theme-active')
  document.body.classList.remove('school-admin-theme-active')
})

async function signOut() {
  await auth.signOut()
  router.push('/login')
}
</script>

<template>
  <div
    class="app-shell"
    :class="{
      'app-shell-natural': naturalScroll,
      'app-shell-teacher': isTeacherShell,
      'app-shell-super-admin': isInstitutionalShell,
      'app-shell-school-admin': isSchoolAdminShell
    }"
  >
    <a class="skip-link" href="#app-main-content">跳到主要内容</a>
    <button
      v-if="mobileNavOpen"
      class="shell-nav-backdrop"
      type="button"
      aria-label="关闭导航"
      @click="closeMobileNav"
    />
    <aside id="app-shell-navigation" class="sidebar" :class="{ open: mobileNavOpen }">
      <RouterLink class="brand" :to="auth.homePath">
        <span class="brand-mark" aria-hidden="true">{{ isSuperAdminShell ? '教' : isSchoolAdminShell ? '校' : isTeacherShell ? '师' : '2.0' }}</span>
        <span>
          <strong>STRATA</strong>
          <small>{{ isSuperAdminShell ? '课程标准与平台管理' : isSchoolAdminShell ? '学校教学管理' : isTeacherShell ? '教学设计与课堂实施' : '数智教学系统' }}</small>
        </span>
      </RouterLink>
      <nav class="nav-list" aria-label="主要导航">
        <template
          v-for="group in navGroups"
          :key="group.label || 'main'"
        >
          <div v-if="!group.label" class="nav-group nav-group-standalone">
            <RouterLink
              v-for="item in group.items"
              :key="item.path"
              :to="item.path"
              :class="{ active: item.active }"
              @click="closeMobileNav"
            >
              <component v-if="item.icon" :is="item.icon" class="nav-item-icon" aria-hidden="true" />
              {{ item.label }}
            </RouterLink>
          </div>
          <details
            v-else
            class="nav-group"
            :class="{ 'has-active': group.items.some((item) => item.active) }"
            :open="isInstitutionalShell || group.label === '当前任务' || group.items.some((item) => item.active)"
          >
            <summary class="nav-group-label">
              <span>{{ group.label }}</span>
              <i aria-hidden="true"></i>
            </summary>
            <RouterLink
              v-for="item in group.items"
              :key="item.path"
              :to="item.path"
              :class="{ active: item.active }"
              @click="closeMobileNav"
            >
              <component v-if="item.icon" :is="item.icon" class="nav-item-icon" aria-hidden="true" />
              {{ item.label }}
            </RouterLink>
          </details>
        </template>
      </nav>
      <div class="sidebar-footer" aria-label="当前登录用户">
        <span class="sidebar-avatar" aria-hidden="true">{{ currentUserInitial }}</span>
        <span class="sidebar-identity">
          <small>{{ auth.user?.role_label || '当前用户' }}</small>
          <strong :title="currentUserName">{{ currentUserName }}</strong>
        </span>
      </div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p>
            <IconShieldLock v-if="isSuperAdminShell" aria-hidden="true" />
            <IconSchool v-else-if="isSchoolAdminShell" aria-hidden="true" />
            <IconChalkboardTeacher v-else-if="isTeacherShell" aria-hidden="true" />
            {{ eyebrow }}
          </p>
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
            <IconMenu2 v-if="isRefinedShell" aria-hidden="true" />
            导航
          </button>
          <template v-if="isRefinedShell">
            <span class="topbar-user-avatar" aria-hidden="true">{{ currentUserInitial }}</span>
            <span class="topbar-user-copy">
              <small>{{ auth.user?.role_label }}</small>
              <strong>{{ currentUserName }}</strong>
            </span>
          </template>
          <span v-else>{{ auth.user?.role_label }}</span>
          <button class="secondary-button" type="button" @click="signOut">
            <IconLogout v-if="isInstitutionalShell" aria-hidden="true" />
            退出
          </button>
        </div>
      </header>
      <main id="app-main-content" class="content" tabindex="-1">
        <slot />
      </main>
    </section>
  </div>
</template>
