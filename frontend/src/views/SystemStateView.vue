<script setup lang="ts">
import { computed } from 'vue'
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconHome,
  IconRefresh
} from '@tabler/icons-vue'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  status: '404' | '500'
}>()

const auth = useAuthStore()
const logoUrl = '/static/brand/brand-logo.png?v=202607242349'
const isNotFound = computed(() => props.status === '404')
const destinationLabel = computed(() => auth.isAuthenticated ? '返回工作台' : '返回首页')

function reloadPage() {
  window.location.reload()
}
</script>

<template>
  <main class="public-page public-state-page">
    <section class="public-state-shell" :aria-labelledby="`state-title-${status}`">
      <a class="public-brand public-state-brand" href="/">
        <img :src="logoUrl" alt="" />
        <span>
          <strong>STRATA</strong>
          <small>数智教学系统</small>
        </span>
      </a>

      <div class="public-state-code" aria-hidden="true">{{ status }}</div>
      <div class="public-state-content">
        <IconAlertTriangle aria-hidden="true" />
        <span>{{ isNotFound ? '没有找到这个页面' : '页面暂时无法打开' }}</span>
        <h1 :id="`state-title-${status}`">
          {{ isNotFound ? '请检查页面地址，或返回平台继续使用。' : '请稍后重试，已经填写的内容请暂时保留。' }}
        </h1>
        <p v-if="isNotFound">这个地址可能已经更改、被删除，或者您没有从正确的入口进入。</p>
        <p v-else>平台服务可能正在恢复。如果多次重试仍无法打开，请记录发生时间并联系平台管理员。</p>
        <div class="public-state-actions">
          <RouterLink v-if="auth.isAuthenticated" class="public-primary-action" :to="auth.homePath">
            <IconHome aria-hidden="true" />
            {{ destinationLabel }}
          </RouterLink>
          <a v-else class="public-primary-action" href="/">
            <IconHome aria-hidden="true" />
            {{ destinationLabel }}
          </a>
          <button v-if="!isNotFound" class="public-secondary-action" type="button" @click="reloadPage">
            <IconRefresh aria-hidden="true" />
            重新加载
          </button>
          <RouterLink v-else class="public-secondary-action" to="/login">
            <IconArrowLeft aria-hidden="true" />
            前往登录
          </RouterLink>
        </div>
      </div>
    </section>
  </main>
</template>
