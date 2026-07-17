<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import { getLearningPage, submitLearningPageForm, type LearningPage } from '@/api/learningPages'
import LearningPageFrame from '@/components/LearningPageFrame.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const pageId = computed(() => Number(route.params.pageId || 0))
const page = shallowRef<LearningPage | null>(null)
const frame = ref<InstanceType<typeof LearningPageFrame> | null>(null)
const loading = ref(true)
const error = ref('')
const interactive = computed(() => auth.user?.role === 'student')
const roleLabel = computed(() => interactive.value ? '学生作答' : '教师预览')

async function loadPage() {
  loading.value = true
  error.value = ''
  page.value = null
  if (!Number.isInteger(pageId.value) || pageId.value <= 0) {
    error.value = '学习网页地址无效。'
    loading.value = false
    return
  }
  try {
    page.value = await getLearningPage(pageId.value)
    document.title = `${page.value.title} - STRATA数智教学系统`
  } catch (loadError) {
    error.value = loadError instanceof ApiError ? loadError.message : '学习网页加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitForm(payload: { formId: string; answers: Record<string, unknown> }) {
  if (!page.value || !interactive.value) return
  try {
    await submitLearningPageForm(page.value.id, payload.formId, payload.answers)
    frame.value?.notifyResult(payload.formId, true, '提交成功')
  } catch (submitError) {
    const message = submitError instanceof ApiError ? submitError.message : '提交失败，请重试。'
    frame.value?.notifyResult(payload.formId, false, message)
  }
}

function closePage() {
  window.close()
  window.setTimeout(() => {
    if (!window.closed) router.back()
  }, 120)
}

onMounted(loadPage)
</script>

<template>
  <main class="learning-page-standalone">
    <header class="learning-page-standalone-header">
      <div>
        <span>STRATA · {{ roleLabel }}</span>
        <strong>{{ page?.title || '学习网页' }}</strong>
        <small v-if="page">v{{ page.revision_no }}</small>
      </div>
      <button type="button" @click="closePage">关闭</button>
    </header>

    <section v-if="loading" class="learning-page-standalone-state" aria-live="polite">
      <div class="learning-page-loading-bar" aria-hidden="true"></div>
      <strong>正在加载学习网页</strong>
    </section>
    <section v-else-if="error" class="learning-page-standalone-state error" role="alert">
      <strong>{{ error }}</strong>
      <button type="button" @click="loadPage">重新加载</button>
    </section>
    <LearningPageFrame
      v-else-if="page"
      ref="frame"
      :page="page"
      :interactive="interactive"
      @submit="submitForm"
    />
  </main>
</template>
