<script setup lang="ts">
import { computed, useId } from 'vue'

const props = withDefaults(defineProps<{
  id?: string
  label: string
  hint?: string
  accept?: string
  file?: File | null
  files?: File[]
  currentName?: string
  currentDetail?: string
  required?: boolean
  optionalLabel?: string
  multiple?: boolean
  disabled?: boolean
  busy?: boolean
  chooseText?: string
  replaceText?: string
  busyText?: string
  statusLabel?: string
  error?: string
  compact?: boolean
}>(), {
  id: '',
  hint: '',
  accept: '',
  file: null,
  files: () => [],
  currentName: '',
  currentDetail: '',
  required: false,
  optionalLabel: '',
  multiple: false,
  disabled: false,
  busy: false,
  chooseText: '选择文件',
  replaceText: '重新选择',
  busyText: '上传中...',
  statusLabel: '',
  error: '',
  compact: false
})

const emit = defineEmits<{
  select: [files: File[]]
}>()

const generatedId = useId()
const inputId = computed(() => props.id || `file-picker-${generatedId.replace(/[^A-Za-z0-9_-]/g, '')}`)
const hintId = computed(() => `${inputId.value}-hint`)
const errorId = computed(() => `${inputId.value}-error`)
const selectedFiles = computed(() => props.files.length ? props.files : props.file ? [props.file] : [])
const hasSelection = computed(() => selectedFiles.value.length > 0 || Boolean(props.currentName))

const selectedName = computed(() => {
  if (!selectedFiles.value.length) return props.currentName
  const names = selectedFiles.value.slice(0, 2).map((file) => file.name)
  const suffix = selectedFiles.value.length > names.length ? ` 等 ${selectedFiles.value.length} 个文件` : ''
  return `${names.join('、')}${suffix}`
})

const selectedDetail = computed(() => {
  if (!selectedFiles.value.length) return props.currentDetail
  const totalSize = selectedFiles.value.reduce((total, file) => total + file.size, 0)
  return selectedFiles.value.length > 1
    ? `共 ${selectedFiles.value.length} 个文件，合计 ${formatFileSize(totalSize)}`
    : formatFileSize(totalSize)
})

const selectionStatus = computed(() => {
  if (props.statusLabel) return props.statusLabel
  if (selectedFiles.value.length > 1) return `已选择 ${selectedFiles.value.length} 个`
  return selectedFiles.value.length ? '已选择' : '当前文件'
})

const buttonText = computed(() => {
  if (props.busy) return props.busyText
  return hasSelection.value ? props.replaceText : props.chooseText
})

const describedBy = computed(() => {
  const ids: string[] = []
  if (props.hint) ids.push(hintId.value)
  if (props.error) ids.push(errorId.value)
  return ids.join(' ') || undefined
})

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(size >= 100 * 1024 * 1024 ? 0 : 1)} MB`
}

function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length) emit('select', files)
  input.value = ''
}
</script>

<template>
  <div
    class="app-file-picker"
    :class="{
      compact,
      'has-selection': hasSelection,
      'has-error': error,
      'is-disabled': disabled || busy
    }"
  >
    <div class="app-file-picker-control">
      <div class="app-file-picker-copy">
        <span class="app-file-picker-label">
          {{ label }}
          <b v-if="required" aria-hidden="true">*</b>
          <em v-else-if="optionalLabel">{{ optionalLabel }}</em>
        </span>
        <small v-if="hint" :id="hintId">{{ hint }}</small>
      </div>

      <label class="app-file-picker-button" :for="inputId" :aria-disabled="disabled || busy">
        {{ buttonText }}
        <input
          :id="inputId"
          class="app-file-picker-input"
          type="file"
          :accept="accept || undefined"
          :multiple="multiple"
          :disabled="disabled || busy"
          :aria-describedby="describedBy"
          @change="chooseFiles"
        />
      </label>
    </div>

    <div v-if="hasSelection" class="app-file-picker-selection" aria-live="polite">
      <span>{{ selectionStatus }}</span>
      <div>
        <strong>{{ selectedName }}</strong>
        <small v-if="selectedDetail">{{ selectedDetail }}</small>
      </div>
    </div>

    <small v-if="error" :id="errorId" class="app-file-picker-error" role="alert">{{ error }}</small>
  </div>
</template>

<style scoped>
.app-file-picker {
  min-width: 0;
  display: grid;
  gap: 8px;
}

.app-file-picker-control {
  min-width: 0;
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px dashed #b8c7d9;
  border-radius: 8px;
  background: #f8fafc;
  transition: border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease;
}

.app-file-picker.compact .app-file-picker-control {
  min-height: 64px;
  padding: 10px 12px;
}

.app-file-picker.has-selection .app-file-picker-control {
  border-color: #7db1ef;
  background: #f3f8ff;
}

.app-file-picker.has-error .app-file-picker-control {
  border-color: #dc2626;
  background: #fff7f7;
}

.app-file-picker.is-disabled .app-file-picker-control {
  border-style: solid;
  background: #f1f5f9;
  opacity: 0.72;
}

.app-file-picker-copy {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.app-file-picker-label {
  color: #334155;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.45;
}

.app-file-picker-label b {
  margin-left: 2px;
  color: #dc2626;
}

.app-file-picker-label em {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  margin-left: 5px;
  padding: 0 6px;
  border: 1px solid #d8e1ec;
  border-radius: 4px;
  background: #fff;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  font-weight: 600;
  vertical-align: middle;
}

.app-file-picker-copy small {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.app-file-picker-button {
  position: relative;
  flex: 0 0 auto;
  min-width: 112px;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 14px;
  border: 1px solid #91a8c2;
  border-radius: 6px;
  background: #fff;
  color: var(--primary-dark, #1d4f91);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  user-select: none;
  transition: border-color 180ms ease, background-color 180ms ease, color 180ms ease, box-shadow 180ms ease;
}

@media (hover: hover) {
  .app-file-picker-button:hover {
    border-color: var(--primary, #2563eb);
    background: #eaf3ff;
  }
}

.app-file-picker-button:active {
  background: #dbeafe;
}

.app-file-picker-button:focus-within {
  border-color: var(--primary, #2563eb);
  box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.16);
}

.app-file-picker-button[aria-disabled="true"] {
  cursor: not-allowed;
}

.app-file-picker-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: pointer;
}

.app-file-picker-input:disabled {
  cursor: not-allowed;
}

.app-file-picker-selection {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 9px;
  padding: 9px 11px;
  border: 1px solid #d8e8fb;
  border-radius: 6px;
  background: #f8fbff;
}

.app-file-picker-selection > span {
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  padding: 0 7px;
  border-radius: 4px;
  background: #dbeafe;
  color: #1d4f91;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.app-file-picker-selection > div {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.app-file-picker-selection strong,
.app-file-picker-selection small {
  overflow-wrap: anywhere;
}

.app-file-picker-selection strong {
  color: #334155;
  font-size: 13px;
  line-height: 1.45;
}

.app-file-picker-selection small {
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.app-file-picker-error {
  color: #b91c1c;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
}

@media (max-width: 560px) {
  .app-file-picker-control {
    align-items: stretch;
    flex-direction: column;
    gap: 10px;
  }

  .app-file-picker-button {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-file-picker-control,
  .app-file-picker-button {
    transition: none;
  }
}
</style>
