<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  message: string
  tone?: 'success' | 'warning' | 'error' | 'info'
}>()

const inferredTone = computed(() => {
  if (props.tone) return props.tone
  if (/失败|错误|拒绝|不能|不存在|不正确/.test(props.message)) return 'error'
  if (/请先|停用|归档|待|下一步|上传/.test(props.message)) return 'warning'
  if (/已|成功|完成|创建|更新|删除|重置|启用/.test(props.message)) return 'success'
  return 'info'
})
</script>

<template>
  <p class="notice-line" :class="`notice-${inferredTone}`" role="status">{{ message }}</p>
</template>
