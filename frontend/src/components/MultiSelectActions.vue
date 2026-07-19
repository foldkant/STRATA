<script setup lang="ts">
withDefaults(defineProps<{
  selectedCount: number
  totalCount: number
  itemLabel?: string
}>(), {
  itemLabel: '班级'
})

const emit = defineEmits<{
  (event: 'select-all'): void
  (event: 'clear'): void
}>()
</script>

<template>
  <div class="multi-select-actions" role="group" :aria-label="`${itemLabel}批量选择`">
    <span>已选 {{ selectedCount }} / {{ totalCount }} 个{{ itemLabel }}</span>
    <div>
      <button type="button" :disabled="totalCount === 0 || selectedCount >= totalCount" @click="emit('select-all')">全选</button>
      <button type="button" :disabled="selectedCount === 0" @click="emit('clear')">全不选</button>
    </div>
  </div>
</template>
