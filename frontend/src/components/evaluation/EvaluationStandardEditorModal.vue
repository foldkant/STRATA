<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  saveEvaluationStandard,
  type EvaluationOptions,
  type EvaluationCriterion,
  type EvaluationStandardPayload,
  type EvaluationStandardRow
} from '@/api/evaluation'
import EvaluationCriterionModal from './EvaluationCriterionModal.vue'
import { vModalFocus } from '@/directives/modalFocus'

const props = defineProps<{
  draft: EvaluationStandardRow | null
  options: EvaluationOptions
  initialPlanVersionId?: number | null
  contextLabel?: string
  assistedByAi?: boolean
}>()

const emit = defineEmits<{
  close: []
  saved: [row: EvaluationStandardRow]
}>()

const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})
const criterionIndex = ref<number | null>(null)
const criterionOpen = ref(false)
const aiCriterionCodes = ref(new Set(
  props.assistedByAi ? (props.draft?.criteria || []).map((item) => item.code) : []
))

function requestClose() {
  if (!saving.value) emit('close')
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

const form = reactive<EvaluationStandardPayload>({
  plan_version: props.draft?.plan_version?.review_status === 'reviewed'
    ? props.draft.plan_version.id
    : props.options.plan_versions.find((item) => (
      item.review_status === 'reviewed'
      && item.source_plan_id === props.draft?.plan.id
    ))?.id
      || props.options.plan_versions.find((item) => (
      item.review_status === 'reviewed'
      && item.id === Number(props.initialPlanVersionId)
    ))?.id
      || props.options.plan_versions.find((item) => item.review_status === 'reviewed')?.id
      || '',
  title: props.draft?.title || '',
  evaluation_target: props.draft?.evaluation_target || '',
  criteria: cloneJson(props.draft?.criteria || [])
})

const modalTitle = computed(() => {
  if (props.assistedByAi && props.draft) return '审阅 AI 起草的评价标准'
  return props.draft ? '编辑评价标准' : '新建评价标准'
})
const planLocked = computed(() => Boolean(props.draft?.latest_version))
const planSelectionLocked = computed(() => planLocked.value || form.criteria.length > 0)
const selectedCriterion = computed(() => criterionIndex.value === null ? null : form.criteria[criterionIndex.value] || null)
const selectedCriterionIsAiDraft = computed(() => Boolean(
  selectedCriterion.value && aiCriterionCodes.value.has(selectedCriterion.value.code)
))
const reviewedPlanVersions = computed(() => props.options.plan_versions.filter((item) => item.review_status === 'reviewed'))
const selectedPlanVersion = computed(() => reviewedPlanVersions.value.find((item) => item.id === Number(form.plan_version)) || null)
const suggestedCriterionCode = computed(() => {
  const maximum = form.criteria.reduce((current, criterion) => {
    const match = criterion.code.match(/^D(\d+)$/i)
    return match ? Math.max(current, Number(match[1])) : current
  }, 0)
  return `D${maximum + 1}`
})

function dimensionLabel(value: string) {
  return props.options.dimensions.find((item) => item.value === value)?.label || value
}

function openCriterion(index: number | null = null) {
  criterionIndex.value = index
  criterionOpen.value = true
}

function saveCriterion(criterion: EvaluationCriterion) {
  if (criterionIndex.value === null) form.criteria.push(criterion)
  else {
    const previousCode = form.criteria[criterionIndex.value]?.code
    if (previousCode && aiCriterionCodes.value.has(previousCode)) {
      aiCriterionCodes.value.delete(previousCode)
      aiCriterionCodes.value.add(criterion.code)
    }
    form.criteria.splice(criterionIndex.value, 1, criterion)
  }
  criterionOpen.value = false
  criterionIndex.value = null
}

function removeCriterion(index: number) {
  const code = form.criteria[index]?.code
  if (code) aiCriterionCodes.value.delete(code)
  form.criteria.splice(index, 1)
}

function closeCriterion() {
  criterionOpen.value = false
  criterionIndex.value = null
}

function validate() {
  const next: FieldErrors = {}
  if (!form.plan_version) next.plan_version = ['请选择已复核并发布的评价方案版本。']
  if (form.title.trim().length < 2) next.title = ['评价标准名称至少 2 个字符。']
  errors.value = next
  return !Object.keys(next).length
}

async function save() {
  if (saving.value) return
  if (!validate()) return
  saving.value = true
  notice.value = ''
  try {
    const row = await saveEvaluationStandard({
      plan_version: form.plan_version,
      title: form.title.trim(),
      evaluation_target: form.evaluation_target.trim(),
      criteria: cloneJson(form.criteria)
    }, props.draft?.id)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '评价标准保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <EvaluationCriterionModal
    v-if="criterionOpen"
    :criterion="selectedCriterion"
    :options="options"
    :plan-version="selectedPlanVersion"
    :suggested-code="suggestedCriterionCode"
    :ai-drafted="selectedCriterionIsAiDraft"
    @cancel="closeCriterion"
    @save="saveCriterion"
  />

  <div v-else class="modal-backdrop evaluation-editor-backdrop" @click.self="requestClose">
    <section v-modal-focus="requestClose" class="entity-modal compact-modal evaluation-editor standard-editor" role="dialog" aria-modal="true" :aria-labelledby="`standard-editor-${draft?.id || 'new'}`">
      <header class="modal-header">
        <div>
          <h2 :id="`standard-editor-${draft?.id || 'new'}`">{{ modalTitle }}</h2>
          <p v-if="contextLabel">当前课时：{{ contextLabel }}</p>
          <p>按指标设置 1-5 星表现说明，没有可评价材料时暂不评价。</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="requestClose">×</button>
      </header>

      <div class="evaluation-editor-body standard-editor-body">
        <p v-if="notice" class="evaluation-inline-error" role="alert">{{ notice }}</p>

        <aside v-if="assistedByAi && form.criteria.length" class="ai-standard-review-note" role="status">
          <strong>AI 已起草 {{ form.criteria.length }} 项评价指标</strong>
          <span>指标名称、评价材料、具体表现、1—5 星说明和评分示例均已形成初稿。请逐项审阅修改，无需重新新增。</span>
        </aside>

        <section class="evaluation-form-grid standard-basics">
          <label>
            <span>评价方案版本<b>*</b></span>
            <AppSelect v-model="form.plan_version" :disabled="planSelectionLocked">
              <option value="" disabled>请选择已复核并发布的评价方案版本</option>
              <option v-for="version in reviewedPlanVersions" :key="version.id" :value="version.id">
                {{ version.course?.title || version.subject.name }} · {{ version.title }} · v{{ version.version_no }} · {{ version.content_hash.slice(0, 8) }}
              </option>
            </AppSelect>
            <small v-if="planLocked">评价标准发布后不能更换所依据的方案版本。</small>
            <small v-else-if="form.criteria.length">已有评价指标；如需更换方案版本，请先删除当前指标。</small>
            <small v-else>仅列出已经复核并发布的方案版本；保存后可追溯到该版本内容。</small>
            <small v-if="errors.plan_version" class="field-error">{{ errors.plan_version[0] }}</small>
          </label>
          <label>
            <span>评价标准名称<b>*</b></span>
            <input v-model.trim="form.title" data-modal-initial-focus maxlength="160" placeholder="例如 数据表达五星评价标准" />
            <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
          </label>
          <label class="span-2">
            <span>总体评价对象<b>*</b></span>
            <input v-model.trim="form.evaluation_target" maxlength="300" placeholder="例如 学生作品、解释文本与修订过程" />
            <small v-if="errors.evaluation_target" class="field-error">{{ errors.evaluation_target[0] }}</small>
          </label>
        </section>

        <section class="standard-criterion-section">
          <header>
            <div>
              <strong>{{ assistedByAi && form.criteria.length ? `AI 起草的评价指标（${form.criteria.length} 项）` : '评价指标' }}</strong>
              <small>{{ assistedByAi && form.criteria.length ? '逐项审阅后保存；如确有遗漏，再手工补充。' : '选择需要评价的方面，并为每项填写具体表现和星级说明。' }}</small>
            </div>
            <button class="secondary-button" type="button" @click="openCriterion()">手工补充指标</button>
          </header>
          <p v-if="errors.criteria" class="field-error">{{ errors.criteria[0] }}</p>
          <p v-if="!form.criteria.length" class="standard-empty">
            {{ assistedByAi ? '本次 AI 草稿中没有可用的评价指标，请返回 AI 辅助起草重新生成，或手工补充后再保存。' : '尚未添加评价指标。可以先保存，发布前需补齐指标、星级说明和评分示例。' }}
          </p>
          <div v-else class="standard-criterion-list">
            <article v-for="(criterion, index) in form.criteria" :key="criterion.code">
              <div class="standard-criterion-order">{{ index + 1 }}</div>
              <div class="standard-criterion-main">
                <span>{{ dimensionLabel(criterion.dimension) }} · {{ criterion.code }}</span>
                <strong>{{ criterion.title }} <em v-if="aiCriterionCodes.has(criterion.code)">AI 初稿 · 待教师审阅</em></strong>
                <small>{{ criterion.evaluation_target }}</small>
              </div>
              <div class="standard-criterion-meta">
                <span>5 个星级说明</span>
                <span>{{ criterion.scoring_examples.length }} 个评分示例</span>
              </div>
              <div class="standard-criterion-actions">
                <button type="button" @click="openCriterion(index)">{{ aiCriterionCodes.has(criterion.code) ? '审阅' : '编辑' }}</button>
                <button type="button" class="danger" @click="removeCriterion(index)">删除</button>
              </div>
            </article>
          </div>
        </section>
      </div>

      <footer class="modal-actions evaluation-modal-actions">
        <span>发布后保留历史版本，修改内容会生成新版本。</span>
        <button class="secondary-button" type="button" :disabled="saving" @click="requestClose">取消</button>
        <button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存草案' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.evaluation-editor-backdrop {
  z-index: 1300;
}

.standard-editor {
  width: min(1040px, 100%);
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.standard-editor-body {
  display: grid;
  gap: 22px;
}

.standard-basics {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}

.ai-standard-review-note {
  display: grid;
  gap: 4px;
  border: 1px solid #c5d6cc;
  border-left: 4px solid var(--primary);
  border-radius: 6px;
  padding: 12px 14px;
  color: #315f50;
  background: #eef5f1;
}

.ai-standard-review-note span {
  font-size: 13px;
  line-height: 1.6;
}

.standard-criterion-section,
.standard-criterion-list {
  display: grid;
  gap: 12px;
}

.standard-criterion-section > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.standard-criterion-section > header div {
  display: grid;
  gap: 4px;
}

.standard-criterion-section > header small {
  max-width: 720px;
  color: var(--muted);
  line-height: 1.5;
}

.standard-empty {
  margin: 0;
  border: 1px dashed #b8c9bf;
  border-radius: 6px;
  padding: 24px;
  color: var(--muted);
  text-align: center;
}

.standard-criterion-list article {
  min-width: 0;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px 14px;
  background: #fafbf8;
}

.standard-criterion-order {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #e5ede8;
  color: var(--primary-dark);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.standard-criterion-main {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.standard-criterion-main span,
.standard-criterion-main small,
.standard-criterion-meta {
  color: var(--muted);
  font-size: 12px;
}

.standard-criterion-main strong,
.standard-criterion-main small {
  overflow-wrap: anywhere;
}

.standard-criterion-main em {
  display: inline-block;
  margin-left: 6px;
  border-radius: 999px;
  padding: 2px 7px;
  color: #315f50;
  background: #e4ede8;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  white-space: nowrap;
}

.standard-criterion-meta {
  display: flex;
  gap: 8px;
}

.standard-criterion-meta span {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 8px;
  background: #fff;
  white-space: nowrap;
}

.standard-criterion-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.standard-criterion-actions button {
  min-height: 40px;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
}

.standard-criterion-actions .danger {
  color: var(--danger);
}

@media (max-width: 760px) {
  .standard-criterion-section > header {
    align-items: stretch;
    flex-direction: column;
  }

  .standard-criterion-list article {
    grid-template-columns: 40px minmax(0, 1fr);
  }

  .standard-criterion-meta,
  .standard-criterion-actions {
    grid-column: 2;
  }
}
</style>
