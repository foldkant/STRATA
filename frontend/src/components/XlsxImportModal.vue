<script setup lang="ts">
import { ref, watch } from 'vue'
import FilePicker from './FilePicker.vue'

const props = defineProps<{
  open: boolean
  title: string
  loading?: boolean
  errors?: string[]
}>()

const emit = defineEmits<{
  close: []
  submit: [file: File]
}>()

const file = ref<File | null>(null)

function chooseFile(files: File[]) {
  file.value = files[0] || null
}

function submit() {
  if (!file.value) return
  emit('submit', file.value)
}

watch(() => props.open, (open) => {
  if (open) file.value = null
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" role="presentation" @click.self="emit('close')">
      <section class="confirm-dialog import-dialog" role="dialog" aria-modal="true" :aria-labelledby="`${title}-title`">
        <h2 :id="`${title}-title`">{{ title }}</h2>
        <p>请选择按模板填写的 xlsx 文件。导入会按登录账号新增或更新已有数据。</p>
        <FilePicker
          class="import-file-picker"
          label="Excel 文件"
          hint="仅支持按系统模板填写的 .xlsx 文件。"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          :file="file"
          :required="true"
          :disabled="loading"
          @select="chooseFile"
        />
        <div v-if="errors?.length" class="import-errors" role="alert">
          <strong>导入校验失败</strong>
          <ul>
            <li v-for="item in errors" :key="item">{{ item }}</li>
          </ul>
        </div>
        <div class="modal-actions">
          <button class="secondary-button" type="button" :disabled="loading" @click="emit('close')">取消</button>
          <button class="primary-button" type="button" :disabled="loading || !file" @click="submit">
            {{ loading ? '导入中' : '开始导入' }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
