<script setup lang="ts">
import type { FieldErrors } from '@/api/client'
import type { FormField } from '@/types/forms'

defineProps<{
  open: boolean
  title: string
  submitLabel: string
  fields: FormField[]
  model: Record<string, string | number | boolean>
  errors?: FieldErrors
  loading?: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: []
  'update:model': [value: Record<string, string | number | boolean>]
}>()

function setValue(model: Record<string, string | number | boolean>, name: string, value: string | number | boolean) {
  emit('update:model', { ...model, [name]: value })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" role="presentation" @click.self="emit('close')">
      <form class="entity-modal" role="dialog" aria-modal="true" @submit.prevent="emit('submit')">
        <header class="modal-header">
          <h2>{{ title }}</h2>
          <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>

        <div class="form-grid">
          <label v-for="field in fields" :key="field.name" :class="{ 'span-2': field.type === 'textarea' }">
            <span>{{ field.label }}<b v-if="field.required">*</b></span>

            <select
              v-if="field.type === 'select'"
              :value="String(model[field.name] ?? '')"
              :required="field.required"
              @change="setValue(model, field.name, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="option in field.options || []" :key="String(option.value)" :value="String(option.value)">
                {{ option.label }}
              </option>
            </select>

            <textarea
              v-else-if="field.type === 'textarea'"
              :value="String(model[field.name] ?? '')"
              :maxlength="field.maxlength"
              :placeholder="field.placeholder"
              @input="setValue(model, field.name, ($event.target as HTMLTextAreaElement).value)"
            />

            <span v-else-if="field.type === 'checkbox'" class="check-row">
              <input
                type="checkbox"
                :checked="Boolean(model[field.name])"
                @change="setValue(model, field.name, ($event.target as HTMLInputElement).checked)"
              />
              <em>启用</em>
            </span>

            <input
              v-else
              :type="field.type || 'text'"
              :value="model[field.name]"
              :required="field.required"
              :pattern="field.pattern"
              :maxlength="field.maxlength"
              :placeholder="field.placeholder"
              :autocomplete="field.autocomplete"
              @input="setValue(model, field.name, ($event.target as HTMLInputElement).value)"
            />

            <small v-if="field.helper">{{ field.helper }}</small>
            <strong v-if="errors?.[field.name]?.length" class="field-error">{{ errors[field.name][0] }}</strong>
          </label>
        </div>

        <footer class="modal-actions">
          <button class="secondary-button" type="button" :disabled="loading" @click="emit('close')">取消</button>
          <button class="primary-button" type="submit" :disabled="loading">
            {{ loading ? '保存中' : submitLabel }}
          </button>
        </footer>
      </form>
    </div>
  </Teleport>
</template>
