<script setup lang="ts">
defineProps<{
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
}>()

const emit = defineEmits<{
  close: []
  confirm: []
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" role="presentation" @click.self="emit('close')">
      <section class="confirm-dialog" role="dialog" aria-modal="true" :aria-labelledby="`${title}-title`">
        <h2 :id="`${title}-title`">{{ title }}</h2>
        <p>{{ message }}</p>
        <div class="modal-actions">
          <button class="secondary-button" type="button" :disabled="loading" @click="emit('close')">取消</button>
          <button
            class="primary-button"
            :class="{ danger: danger }"
            type="button"
            :disabled="loading"
            @click="emit('confirm')"
          >
            {{ loading ? '处理中' : confirmLabel || '确认' }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
