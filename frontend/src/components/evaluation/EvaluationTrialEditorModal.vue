<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  saveEvaluationTrial,
  type EvaluationOptions,
  type EvaluationTrialPayload,
  type EvaluationTrialRow
} from '@/api/evaluation'

const props = defineProps<{
  draft: EvaluationTrialRow | null
  options: EvaluationOptions
}>()

const emit = defineEmits<{
  close: []
  saved: [row: EvaluationTrialRow]
}>()

const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})

function dateText(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const form = reactive<EvaluationTrialPayload>({
  standard_version: props.draft?.standard_version.id || props.options.standard_versions[0]?.id || '',
  record_type: props.draft?.record_type || props.options.trial_types[0]?.value || 'content_review',
  title: props.draft?.title || '',
  status: props.draft?.status || 'planned',
  activity_date: props.draft?.activity_date || dateText(new Date()),
  participant_count: props.draft?.participant_count || 0,
  agreement_rate: props.draft?.agreement_rate ?? null,
  conclusion: props.draft?.conclusion || 'pending',
  summary: props.draft?.summary || '',
  issues: [...(props.draft?.issues || [])],
  action_items: [...(props.draft?.action_items || [])]
})

const locked = computed(() => props.draft?.status === 'completed')
const modalTitle = computed(() => locked.value ? '查看试用记录' : props.draft ? '编辑试用记录' : '新增试用记录')
const isScoringCheck = computed(() => form.record_type === 'scoring_check')
const isCompleted = computed(() => form.status === 'completed')

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLTextAreaElement).value
}

function validate() {
  const next: FieldErrors = {}
  if (!form.standard_version) next.standard_version = ['请选择已发布的评价标准。']
  if (form.title.trim().length < 2) next.title = ['记录名称至少 2 个字符。']
  if (!form.activity_date) next.activity_date = ['请选择日期。']
  if (form.participant_count < 0) next.participant_count = ['参与人数不能小于 0。']
  if (isCompleted.value) {
    if (form.participant_count < 1) next.participant_count = ['已完成记录至少需要 1 名参与者。']
    if (form.summary.trim().length < 4) next.summary = ['请填写本次结果说明。']
    if (form.conclusion === 'pending') next.conclusion = ['请选择处理结论。']
    if (isScoringCheck.value && (form.agreement_rate === null || form.agreement_rate === '')) {
      next.agreement_rate = ['请填写评分一致率。']
    }
  }
  const agreement = Number(form.agreement_rate)
  if (isScoringCheck.value && form.agreement_rate !== null && form.agreement_rate !== '' && (agreement < 0 || agreement > 100)) {
    next.agreement_rate = ['评分一致率应在 0-100 之间。']
  }
  errors.value = next
  return !Object.keys(next).length
}

async function save() {
  if (locked.value) return
  if (!validate()) return
  saving.value = true
  notice.value = ''
  errors.value = {}
  try {
    const row = await saveEvaluationTrial({
      ...form,
      title: form.title.trim(),
      agreement_rate: isScoringCheck.value && form.agreement_rate !== '' ? form.agreement_rate : null,
      conclusion: isCompleted.value ? form.conclusion : 'pending',
      summary: form.summary.trim(),
      issues: form.issues.map((item) => item.trim()).filter(Boolean),
      action_items: form.action_items.map((item) => item.trim()).filter(Boolean)
    }, props.draft?.id)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '评价试用记录保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section class="entity-modal compact-modal trial-editor" role="dialog" aria-modal="true" :aria-labelledby="`trial-editor-${draft?.id || 'new'}`">
      <header class="modal-header">
        <div>
          <h2 :id="`trial-editor-${draft?.id || 'new'}`">{{ modalTitle }}</h2>
          <p>记录审核、课堂试用和评分检查结果</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="trial-editor-body">
        <p v-if="notice" class="trial-inline-error" role="alert">{{ notice }}</p>

        <div class="trial-form-grid">
          <label class="span-2">
            <span>评价标准版本<b>*</b></span>
            <AppSelect v-model="form.standard_version" :disabled="locked">
              <option value="" disabled>请选择已发布评价标准</option>
              <option v-for="version in options.standard_versions" :key="version.id" :value="version.id">
                {{ version.subject.name }} · {{ version.title }} v{{ version.version_no }}
              </option>
            </AppSelect>
            <small v-if="errors.standard_version" class="field-error">{{ errors.standard_version[0] }}</small>
          </label>

          <label>
            <span>记录类型<b>*</b></span>
            <AppSelect v-model="form.record_type" :disabled="locked">
              <option v-for="item in options.trial_types" :key="item.value" :value="item.value">{{ item.label }}</option>
            </AppSelect>
          </label>
          <label>
            <span>日期<b>*</b></span>
            <input v-model="form.activity_date" type="date" :disabled="locked" />
            <small v-if="errors.activity_date" class="field-error">{{ errors.activity_date[0] }}</small>
          </label>

          <label class="span-2">
            <span>记录名称<b>*</b></span>
            <input v-model.trim="form.title" maxlength="160" placeholder="例如 高一数据表达课堂试用" :disabled="locked" />
            <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
          </label>

          <label>
            <span>当前状态<b>*</b></span>
            <AppSelect v-model="form.status" :disabled="locked">
              <option v-for="item in options.trial_statuses" :key="item.value" :value="item.value">{{ item.label }}</option>
            </AppSelect>
          </label>
          <label>
            <span>参与人数<b v-if="isCompleted">*</b></span>
            <input v-model.number="form.participant_count" type="number" min="0" max="9999" :disabled="locked" />
            <small v-if="errors.participant_count" class="field-error">{{ errors.participant_count[0] }}</small>
          </label>

          <label v-if="isScoringCheck">
            <span>评分一致率<b v-if="isCompleted">*</b></span>
            <div class="trial-rate-input">
              <input v-model="form.agreement_rate" type="number" min="0" max="100" step="0.01" placeholder="0-100" :disabled="locked" />
              <span>%</span>
            </div>
            <small v-if="errors.agreement_rate" class="field-error">{{ errors.agreement_rate[0] }}</small>
          </label>
          <label :class="{ 'span-2': !isScoringCheck }">
            <span>处理结论<b v-if="isCompleted">*</b></span>
            <AppSelect v-model="form.conclusion" :disabled="locked || !isCompleted">
              <option v-for="item in options.trial_conclusions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </AppSelect>
            <small v-if="!isCompleted">完成后再选择结论。</small>
            <small v-if="errors.conclusion" class="field-error">{{ errors.conclusion[0] }}</small>
          </label>

          <label class="span-2">
            <span>结果说明<b v-if="isCompleted">*</b></span>
            <textarea v-model.trim="form.summary" rows="4" placeholder="记录本次审核、试用或评分检查的主要结果。" :disabled="locked" />
            <small v-if="errors.summary" class="field-error">{{ errors.summary[0] }}</small>
          </label>
          <label>
            <span>发现的问题</span>
            <textarea :value="form.issues.join('\n')" rows="5" placeholder="每行一个问题" :disabled="locked" @input="form.issues = lines(inputValue($event))" />
            <small v-if="errors.issues" class="field-error">{{ errors.issues[0] }}</small>
          </label>
          <label>
            <span>后续处理</span>
            <textarea :value="form.action_items.join('\n')" rows="5" placeholder="每行一项处理安排" :disabled="locked" @input="form.action_items = lines(inputValue($event))" />
            <small v-if="errors.action_items" class="field-error">{{ errors.action_items[0] }}</small>
          </label>
        </div>
      </div>

      <footer class="modal-actions trial-editor-actions">
        <button class="secondary-button" type="button" :disabled="saving" @click="emit('close')">{{ locked ? '关闭' : '取消' }}</button>
        <button v-if="!locked" class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存记录' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.trial-editor {
  width: min(760px, calc(100vw - 32px));
  max-height: min(820px, calc(100dvh - 32px));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.trial-editor-body {
  min-height: 0;
  overflow-y: auto;
  padding: 20px;
}

.trial-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.trial-form-grid label {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 7px;
}

.trial-form-grid label > span {
  color: var(--ink);
  font-size: 14px;
  font-weight: 600;
}

.trial-form-grid b {
  margin-left: 3px;
  color: var(--danger, #c62828);
}

.trial-form-grid input,
.trial-form-grid select,
.trial-form-grid textarea {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff;
  color: var(--ink);
  font: inherit;
}

.trial-form-grid textarea {
  min-height: 104px;
  resize: vertical;
  line-height: 1.55;
}

.trial-form-grid input:focus,
.trial-form-grid select:focus,
.trial-form-grid textarea:focus {
  border-color: var(--primary);
  outline: 3px solid rgba(37, 99, 235, .12);
}

.trial-form-grid select:disabled {
  background: #f1f5f9;
  color: var(--muted);
}

.trial-form-grid small {
  color: var(--muted);
  line-height: 1.45;
}

.trial-form-grid .field-error,
.trial-inline-error {
  color: #b42318;
}

.trial-inline-error {
  margin: 0 0 16px;
  border: 1px solid #f5b7b1;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff1f0;
}

.span-2 {
  grid-column: 1 / -1;
}

.trial-rate-input {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 42px;
}

.trial-rate-input input {
  border-radius: 6px 0 0 6px;
}

.trial-rate-input > span {
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-left: 0;
  border-radius: 0 6px 6px 0;
  background: #f8fafc;
  color: var(--muted);
}

.trial-editor-actions {
  border-top: 1px solid var(--line);
  background: #fff;
}

@media (max-width: 640px) {
  .trial-editor {
    width: 100vw;
    max-height: 100dvh;
    min-height: 100dvh;
    border-radius: 0;
  }

  .trial-form-grid {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: auto;
  }
}
</style>
