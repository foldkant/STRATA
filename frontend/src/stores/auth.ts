import { defineStore } from 'pinia'
import { getCsrf, login, logout, me, type CurrentUser } from '@/api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as CurrentUser | null,
    loaded: false
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.user),
    homePath: (state) => {
      if (state.user?.role === 'super_admin') return '/super-admin'
      if (state.user?.role === 'school_admin') return '/school-admin'
      if (state.user?.role === 'teacher') return '/teacher'
      if (state.user?.role === 'student') return '/student'
      return '/login'
    }
  },
  actions: {
    async load() {
      try {
        this.user = await me()
      } catch {
        this.user = null
      } finally {
        this.loaded = true
      }
    },
    async signIn(username: string, password: string) {
      await getCsrf()
      this.user = await login(username, password)
      this.loaded = true
    },
    async signOut() {
      await logout()
      this.user = null
      this.loaded = true
    }
  }
})
