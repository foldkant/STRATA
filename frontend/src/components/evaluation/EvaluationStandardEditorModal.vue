<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  saveEvaluationStandard,
  type EvaluationPlanRow,
  type EvaluationOptions,
  type EvaluationCriterion,
  type EvaluationStandardPayload,
  type EvaluationStandardRow
} from '@/api/evaluation'
import EvaluationCriterionModal from './EvaluationCriterionModal.vue'

const props = defineProps<{
  draft: EvaluationStandardRow | null
  options: EvaluationOptions
  plans: EvaluationPlanRow[]
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

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

const form = reactive<EvaluationStandardPayload>({
  plan: props.draft?.plan.id || props.plans[0]?.id || '',
  title: props.draft?.title || '',
  evaluation_target: props.draft?.evaluation_target || '',
  criteria: cloneJson(props.draft?.criteria || [])
})

const modalTitle = computed(() => props.draft ? '编辑评价标准' : '新建评价标准')
const planLocked = computed(() => Boolean(props.draft?.latest_version))
const selectedCriterion = computed(() => criterionIndex.value === null ? null : form.criteria[criterionIndex.value] || null)

function dimensionLabel(value: string) {
  return props.options.dimensions.find((item) => item.value === value)?.label || value
}

function openCriterion(index: number | null = null) {
  criterionIndex.value = index
  criterionOpen.value = true
}

function saveCriterion(criterion: EvaluationCriterion) {
  if (criterionIndex.value === null) form.criteria.push(criterion)
  else form.criteria.splice(criterionIndex.value, 1, criterion)
  criterionOpen.value = false
  criterionIndex.value = null
}

function closeCriterion() {
  criterionOpen.value = false
  criterionIndex.value = null
}

function validate() {
  const next: FieldErrors = {}
  if (!form.plan) next.plan = ['请选择评价方案。']
  if (form.title.trim().length < 2) next.title = ['评价标准名称至少 2 个字符。']
  if (form.evaluation_target.trim().length < 4) next.evaluation_target = ['请明确评价对象。']
  errors.value = next
  return !Object.keys(next).length
}

async function save() {
  if (!validate()) return
  saving.value = true
  notice.value = ''
  try {
    const row = await saveEvaluationStandard({
      plan: form.plan,
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
    @cancel="closeCriterion"
    @save="saveCriterion"
  />

  <div v-else class="modal-backdrop" @click.self="emit('close')">
    <section class="entity-modal compact-modal evaluation-editor standard-editor" role="dialog" aria-modal="true" :aria-labelledby="`standard-editor-${draft?.id || 'new'}`">
      <header class="modal-header">
        <div>
          <h2 :id="`standard-editor-${draft?.id || 'new'}`">{{ modalTitle }}</h2>
          <p>按指标设置 1-5 星表现说明，没有可评价材料时暂不评价。</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="evaluation-editor-body standard-editor-body">
        <p v-if="notice" class="evaluation-inline-error" role="alert">{{ notice }}</p>

        <section class="evaluation-form-grid standard-basics">
          <label>
            <span>评价方案<b>*</b></span>
            <AppSelect v-model="form.plan" :disabled="planLocked">
              <option value="" disabled>请选择评价方案</option>
              <option v-for="plan in plans" :key="plan.id" :value="plan.id">
                {{ plan.course?.title || plan.subject.name }} · {{ plan.title }}
              </option>
            </AppSelect>
            <small v-if="planLocked">已发布版本后不能更换评价方案。</small>
            <small v-if="errors.plan" class="field-error">{{ errors.plan[0] }}</small>
          </label>
          <label>
            <span>评价标准名称<b>*</b></span>
            <input v-model.trim="form.title" maxlength="160" placeholder="例如 数据表达五星评价标准" />
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
              <strong>评价指标</strong>
              <small>选择需要评价的方面，并为每项填写具体表现和星级说明。</small>
            </div>
            <button class="primary-button" type="button" @click="openCriterion()">新增指标</button>
          </header>
          <p v-if="errors.criteria" class="field-error">{{ errors.criteria[0] }}</p>
          <p v-if="!form.criteria.length" class="standard-empty">尚未添加评价指标。可以先保存，发布前需补齐指标、星级说明和评分示例。</p>
          <div v-else class="standard-criterion-list">
            <article v-for="(criterion, index) in form.criteria" :key="`${criterion.code}-${index}`">
              <div class="standard-criterion-order">{{ index + 1 }}</div>
              <div class="standard-criterion-main">
                <span>{{ dimensionLabel(criterion.dimension) }} · {{ criterion.code }}</span>
                <strong>{{ criterion.title }}</strong>
                <small>{{ criterion.evaluation_target }}</small>
              </div>
              <div class="standard-criterion-meta">
                <span>5 个星级说明</span>
                <span>{{ criterion.scoring_examples.length }} 个评分示例</span>
              </div>
              <div class="standard-criterion-actions">
                <button type="button" @click="openCriterion(index)">编辑</button>
                <button type="button" class="danger" @click="form.criteria.splice(index, 1)">删除</button>
              </div>
            </article>
          </div>
        </section>
      </div>

      <footer class="modal-actions evaluation-modal-actions">
        <span>发布后保留历史版本，修改内容会生成新版本。</span>
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存草案' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
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
  border: 1px dashed #b8c6d8;
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
  background: #fbfdff;
}

.standard-criterion-order {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #e8f1ff;
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
