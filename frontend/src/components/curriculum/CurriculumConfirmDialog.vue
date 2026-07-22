<script setup lang="ts">
import { useId } from 'vue'
import { vCurriculumModalFocus } from './curriculumModalFocus'

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

const dialogId = `curriculum-confirm-${useId().replace(/:/g, '')}`
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop curriculum-confirm-backdrop" role="presentation" @click.self="emit('close')">
      <section
        v-curriculum-modal-focus="() => emit('close')"
        class="confirm-dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`${dialogId}-title`"
        :aria-describedby="`${dialogId}-description`"
      >
        <h2 :id="`${dialogId}-title`">{{ title }}</h2>
        <p :id="`${dialogId}-description`">{{ message }}</p>
        <div class="modal-actions">
          <button class="secondary-button" type="button" :disabled="loading" data-modal-initial-focus @click="emit('close')">取消</button>
          <button
            class="primary-button"
            :class="{ danger }"
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

<style scoped>
.curriculum-confirm-backdrop {
  z-index: 1400;
}
</style>
