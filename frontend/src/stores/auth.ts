import { defineStore } from 'pinia'
import { getCsrf, login, logout, me, type CurrentUser } from '@/api/auth'
import { homePathForRole } from '@/domain/access'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as CurrentUser | null,
    loaded: false
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.user),
    homePath: (state) => homePathForRole(state.user?.role)
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
