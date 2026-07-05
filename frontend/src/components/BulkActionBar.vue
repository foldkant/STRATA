<script setup lang="ts">
defineProps<{
  selectedCount: number
  totalOnPage: number
  loading?: boolean
  disableLabel?: string
  deleteLabel?: string
  extraLabel?: string
  extraDanger?: boolean
  showDisable?: boolean
  showDelete?: boolean
}>()

const emit = defineEmits<{
  clear: []
  disable: []
  delete: []
  extra: []
}>()
</script>

<template>
  <div v-if="selectedCount" class="bulk-action-bar" aria-live="polite">
    <div>
      <strong>已选 {{ selectedCount }} 条</strong>
      <span>当前页共 {{ totalOnPage }} 条</span>
    </div>
    <div class="bulk-action-buttons">
      <button class="secondary-button" type="button" :disabled="loading" @click="emit('clear')">清空选择</button>
      <button v-if="showDisable !== false" class="secondary-button" type="button" :disabled="loading" @click="emit('disable')">
        {{ disableLabel || '批量停用' }}
      </button>
      <button
        v-if="extraLabel"
        class="secondary-button"
        :class="{ danger: extraDanger }"
        type="button"
        :disabled="loading"
        @click="emit('extra')"
      >
        {{ extraLabel }}
      </button>
      <button v-if="showDelete !== false" class="secondary-button danger" type="button" :disabled="loading" @click="emit('delete')">
        {{ deleteLabel || '批量删除' }}
      </button>
    </div>
  </div>
</template>
