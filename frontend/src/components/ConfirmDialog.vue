<script setup lang="ts">
import { vModalFocus } from '@/directives/modalFocus'

const props = defineProps<{
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

function requestClose() {
  if (!props.loading) emit('close')
}

</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" role="presentation" @click.self="requestClose">
      <section v-modal-focus="requestClose" class="confirm-dialog" role="dialog" aria-modal="true" :aria-labelledby="`${title}-title`">
        <h2 :id="`${title}-title`">{{ title }}</h2>
        <p>{{ message }}</p>
        <div class="modal-actions">
          <button class="secondary-button" type="button" data-modal-initial-focus :disabled="loading" @click="requestClose">取消</button>
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
