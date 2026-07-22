<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  saveCurriculumStandard,
  type CurriculumDocumentType,
  type CurriculumSchoolStage,
  type CurriculumStandard,
  type CurriculumStandardPayload
} from '@/api/curriculumStandards'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{ draft: CurriculumStandard | null }>()

const emit = defineEmits<{
  close: []
  saved: [row: CurriculumStandard]
}>()

const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})
const form = reactive<CurriculumStandardPayload>({
  title: props.draft?.title || '',
  document_type: props.draft?.document_type || 'subject_standard',
  school_stage: props.draft?.school_stage || 'k1_k9',
  subject_code: props.draft?.subject_code || '',
  subject_name: props.draft?.subject_name || ''
})

function validate() {
  const next: FieldErrors = {}
  if (form.title.trim().length < 4) next.title = ['请填写完整的课程标准名称。']
  if (form.document_type === 'subject_standard' && !form.subject_code.trim()) next.subject_code = ['请填写学科代码。']
  if (form.document_type === 'subject_standard' && !form.subject_name.trim()) next.subject_name = ['请填写学科名称。']
  errors.value = next
  return Object.keys(next).length === 0
}

async function save() {
  if (!validate()) return
  saving.value = true
  notice.value = ''
  try {
    const row = await saveCurriculumStandard({
      ...form,
      title: form.title.trim(),
      subject_code: form.subject_code.trim(),
      subject_name: form.subject_name.trim()
    }, props.draft?.id)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '课程标准元数据保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section v-curriculum-modal-focus="() => emit('close')" class="entity-modal curriculum-standard-editor" role="dialog" aria-modal="true" aria-labelledby="curriculum-standard-editor-title">
      <header class="modal-header">
        <div>
          <h2 id="curriculum-standard-editor-title">{{ draft ? '编辑课程标准元数据' : '登记课程标准' }}</h2>
          <p>登记文件身份和适用范围；正式内容通过不可变版本管理。</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
      </header>

      <div class="modal-body curriculum-standard-form">
        <p v-if="notice" class="curriculum-form-error" role="alert">{{ notice }}</p>
        <label class="span-2">
          <span>课程标准名称<b>*</b></span>
          <input v-model.trim="form.title" maxlength="200" placeholder="例如 义务教育信息科技课程标准（2022年版）" />
          <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
        </label>
        <label>
          <span>文件类型<b>*</b></span>
          <AppSelect v-model="form.document_type">
            <option value="subject_standard">学科课程标准</option>
            <option value="curriculum_plan">课程方案</option>
          </AppSelect>
        </label>
        <label>
          <span>学段<b>*</b></span>
          <AppSelect v-model="form.school_stage">
            <option value="k1_k9">义务教育（K1—K9）</option>
            <option value="k10_k12">普通高中（K10—K12）</option>
          </AppSelect>
        </label>
        <label>
          <span>学科代码<b v-if="form.document_type === 'subject_standard'">*</b></span>
          <input v-model.trim="form.subject_code" maxlength="64" placeholder="例如 information_technology" />
          <small>代码用于课程和评价方案的稳定关联，保存后不建议随意更改。</small>
          <small v-if="errors.subject_code" class="field-error">{{ errors.subject_code[0] }}</small>
        </label>
        <label>
          <span>学科名称<b v-if="form.document_type === 'subject_standard'">*</b></span>
          <input v-model.trim="form.subject_name" maxlength="100" placeholder="例如 信息科技" />
          <small v-if="errors.subject_name" class="field-error">{{ errors.subject_name[0] }}</small>
        </label>
      </div>

      <footer class="modal-actions">
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.curriculum-standard-editor {
  width: min(760px, 100%);
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-standard-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.curriculum-standard-form label {
  min-width: 0;
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-standard-form .span-2,
.curriculum-form-error {
  grid-column: 1 / -1;
}

.curriculum-standard-form input,
.curriculum-standard-form select {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff;
  color: var(--text);
}

.curriculum-standard-form b {
  margin-left: 2px;
  color: var(--danger);
}

.curriculum-standard-form small {
  line-height: 1.5;
}

.curriculum-form-error {
  margin: 0;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fef2f2;
  color: #991b1b;
}

@media (max-width: 640px) {
  .curriculum-standard-form {
    grid-template-columns: 1fr;
  }

  .curriculum-standard-form .span-2,
  .curriculum-form-error {
    grid-column: auto;
  }
}
</style>
