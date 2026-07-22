<script setup lang="ts">
import { ref } from 'vue'
import { ApiError } from '@/api/client'
import { reviewCurriculumStandardVersion, type CurriculumStandardVersion } from '@/api/curriculumStandards'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{ version: CurriculumStandardVersion }>()

const emit = defineEmits<{
  close: []
  saved: [row: CurriculumStandardVersion, approved: boolean]
}>()

const note = ref(props.version.review_note || '')
const saving = ref(false)
const notice = ref('')

async function review(approved: boolean) {
  if (!approved && note.value.trim().length < 4) {
    notice.value = '退回修改时，请填写具体的复核意见。'
    return
  }
  saving.value = true
  notice.value = ''
  try {
    const row = await reviewCurriculumStandardVersion(props.version.id, approved, note.value.trim())
    emit('saved', row, approved)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准复核结果保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section v-curriculum-modal-focus="() => emit('close')" class="entity-modal curriculum-review-modal" role="dialog" aria-modal="true" aria-labelledby="curriculum-review-title">
      <header class="modal-header">
        <div>
          <h2 id="curriculum-review-title">复核课程标准版本</h2>
          <p>{{ version.title }} · {{ version.version_label }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
      </header>

      <div class="modal-body curriculum-review-body">
        <aside>
          请对照 PDF 原文检查结构化文本、课程标准内容条目、原文页码和文件校验信息。复核通过不代表直接发布，仍需单独确认发布。
        </aside>
        <label>
          <span>复核意见</span>
          <textarea v-model="note" rows="8" placeholder="记录核验范围、发现的问题或通过依据；退回修改时必须填写。" />
        </label>
        <p v-if="notice" role="alert">{{ notice }}</p>
      </div>

      <footer class="modal-actions curriculum-review-actions">
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button class="danger-outline-button" type="button" :disabled="saving" @click="review(false)">退回修改</button>
        <button class="primary-button" type="button" :disabled="saving" @click="review(true)">{{ saving ? '保存中' : '复核通过' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.curriculum-review-modal {
  width: min(720px, 100%);
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-review-body {
  display: grid;
  gap: 14px;
}

.curriculum-review-body aside {
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  padding: 11px 13px;
  background: #eff6ff;
  color: #1e40af;
  line-height: 1.6;
}

.curriculum-review-body label {
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-review-body textarea {
  width: 100%;
  min-height: 150px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 11px 12px;
  background: #fff;
  color: var(--text);
  resize: vertical;
}

.curriculum-review-body p {
  margin: 0;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 9px 11px;
  background: #fef2f2;
  color: #991b1b;
}

.danger-outline-button {
  min-height: 42px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 0 14px;
  background: #fff;
  color: #b42318;
  cursor: pointer;
}
</style>
