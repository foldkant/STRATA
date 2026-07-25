import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import AppShell from './AppShell.vue'
import { useAuthStore } from '@/stores/auth'

async function mountShell(navItems: Array<{ label: string; path: string; active?: boolean; group?: string }>) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1,
    username: 'teacher',
    display_name: '测试教师',
    role: 'teacher',
    role_label: '教师',
    school: null,
    is_active: true,
    is_first_login: false
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', component: defineComponent({ template: '<div />' }) }]
  })
  await router.push('/teacher/courses')
  await router.isReady()
  return mount(AppShell, {
    props: { title: '工作台', eyebrow: '教师', navItems },
    slots: { default: '<p>主要内容</p>' },
    global: { plugins: [pinia, router] }
  })
}

describe('AppShell navigation', () => {
  it('renders ungrouped navigation as direct first-level links instead of browser details', async () => {
    const wrapper = await mountShell([
      { label: '首页', path: '/student' },
      { label: '课程', path: '/student/courses', active: true }
    ])

    const group = wrapper.get('.nav-group-standalone')
    expect(wrapper.find('details.nav-group').exists()).toBe(false)
    expect(group.findAll('a')).toHaveLength(2)
  })

  it('keeps the teacher home page as a direct first-level entry', async () => {
    const wrapper = await mountShell([
      { label: '首页', path: '/teacher', group: '', active: true },
      { label: '课程与课时', path: '/teacher/courses', group: '备课' }
    ])

    const home = wrapper.get('.nav-group-standalone a')
    expect(home.text()).toBe('首页')
    expect(home.classes()).toContain('active')
    expect(wrapper.findAll('details.nav-group')).toHaveLength(1)
    expect(wrapper.get('details.nav-group summary').text()).toBe('备课')
  })

  it('presents the current user as a compact identity block in the sidebar', async () => {
    const wrapper = await mountShell([{ label: '首页', path: '/teacher', group: '', active: true }])

    expect(wrapper.get('.sidebar-footer').attributes('aria-label')).toBe('当前登录用户')
    expect(wrapper.get('.sidebar-avatar').text()).toBe('测')
    expect(wrapper.get('.sidebar-identity small').text()).toBe('教师')
    expect(wrapper.get('.sidebar-identity strong').text()).toBe('测试教师')
  })

  it('uses progressive disclosure while keeping the current task and active group open', async () => {
    const wrapper = await mountShell([
      { label: '今日工作', path: '/teacher', group: '当前任务' },
      { label: '课程与课时', path: '/teacher/courses', group: '备课', active: true },
      { label: '课堂实施', path: '/teacher/classroom', group: '上课' }
    ])

    const groups = wrapper.findAll('details.nav-group')
    expect(groups).toHaveLength(3)
    expect(groups[0].attributes()).toHaveProperty('open')
    expect(groups[1].attributes()).toHaveProperty('open')
    expect(groups[2].attributes()).not.toHaveProperty('open')
    expect(groups.map((group) => group.get('summary').text())).toEqual(['当前任务', '备课', '上课'])
  })
})
