<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{
  message: string
  tone?: 'success' | 'warning' | 'error' | 'info'
  floating?: boolean
  duration?: number
}>()

const emit = defineEmits<{
  dismiss: []
}>()

const visible = ref(true)
let hideTimer: number | null = null

const inferredTone = computed(() => {
  if (props.tone) return props.tone
  if (/失败|错误|拒绝|不能|不存在|不正确/.test(props.message)) return 'error'
  if (/请先|停用|归档|待|下一步|上传/.test(props.message)) return 'warning'
  if (/已|成功|完成|创建|更新|删除|重置|启用/.test(props.message)) return 'success'
  return 'info'
})

const liveRole = computed(() =>
  inferredTone.value === 'error' || inferredTone.value === 'warning' ? 'alert' : 'status'
)

function clearHideTimer() {
  if (hideTimer !== null) {
    window.clearTimeout(hideTimer)
    hideTimer = null
  }
}

function dismiss() {
  clearHideTimer()
  visible.value = false
  emit('dismiss')
}

function showNotice() {
  clearHideTimer()
  visible.value = true
  if (!props.floating || props.duration === 0) return
  if (inferredTone.value === 'success' || inferredTone.value === 'info') {
    hideTimer = window.setTimeout(dismiss, props.duration ?? 5000)
  }
}

watch(
  () => [props.message, props.tone, props.floating, props.duration],
  showNotice,
  { immediate: true }
)

onBeforeUnmount(clearHideTimer)
</script>

<template>
  <Teleport v-if="floating" to="#global-notice-area">
    <Transition name="notice-toast">
      <div
        v-if="visible"
        class="notice-line notice-line-floating"
        :class="`notice-${inferredTone}`"
        :role="liveRole"
      >
        <span>{{ message }}</span>
        <button class="notice-dismiss" type="button" aria-label="关闭提示" @click="dismiss">×</button>
      </div>
    </Transition>
  </Teleport>
  <p v-else class="notice-line" :class="`notice-${inferredTone}`" :role="liveRole">{{ message }}</p>
</template>
