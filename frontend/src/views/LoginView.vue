<script setup lang="ts">
import { ref } from 'vue'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)
const logoUrl = '/static/brand/brand-logo.png'

async function submit() {
  error.value = ''
  submitting.value = true
  try {
    await auth.signIn(username.value, password.value)
    window.location.assign(`/app${auth.homePath}`)
  } catch (exc) {
    error.value = exc instanceof ApiError ? exc.message : '登录失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel" aria-labelledby="login-title">
      <a class="login-brand" href="/">
        <img :src="logoUrl" alt="" />
        <span>STRATA数智教学系统</span>
      </a>

      <div class="login-heading">
        <h1 id="login-title">账号登录</h1>
      </div>

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>

      <form class="login-form" @submit.prevent="submit">
        <label>
          <span>账号</span>
          <input v-model.trim="username" autocomplete="username" required autofocus />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>
        <button class="primary-button wide" type="submit" :disabled="submitting">
          {{ submitting ? '登录中' : '登录' }}
        </button>
      </form>
      <a class="text-link" href="/">返回首页</a>
    </section>
  </main>
</template>
