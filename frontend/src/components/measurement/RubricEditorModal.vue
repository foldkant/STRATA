<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  saveRubric,
  type BlueprintRow,
  type MeasurementOptions,
  type RubricCriterion,
  type RubricPayload,
  type RubricRow
} from '@/api/measurement'
import RubricCriterionModal from './RubricCriterionModal.vue'

const props = defineProps<{
  draft: RubricRow | null
  options: MeasurementOptions
  blueprints: BlueprintRow[]
}>()

const emit = defineEmits<{
  close: []
  saved: [row: RubricRow]
}>()

const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})
const criterionIndex = ref<number | null>(null)
const criterionOpen = ref(false)

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

const form = reactive<RubricPayload>({
  blueprint: props.draft?.blueprint.id || props.blueprints[0]?.id || '',
  title: props.draft?.title || '',
  evaluation_object: props.draft?.evaluation_object || '',
  criteria: cloneJson(props.draft?.criteria || [])
})

const modalTitle = computed(() => props.draft ? '编辑量规草案' : '新建量规草案')
const blueprintLocked = computed(() => Boolean(props.draft?.latest_version))
const selectedCriterion = computed(() => criterionIndex.value === null ? null : form.criteria[criterionIndex.value] || null)

function moduleLabel(value: string) {
  return props.options.rubric_modules.find((item) => item.value === value)?.label || value
}

function openCriterion(index: number | null = null) {
  criterionIndex.value = index
  criterionOpen.value = true
}

function saveCriterion(criterion: RubricCriterion) {
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
  if (!form.blueprint) next.blueprint = ['请选择任务蓝图。']
  if (form.title.trim().length < 2) next.title = ['量规名称至少 2 个字符。']
  if (form.evaluation_object.trim().length < 4) next.evaluation_object = ['请明确量规评价对象。']
  errors.value = next
  return !Object.keys(next).length
}

async function save() {
  if (!validate()) return
  saving.value = true
  notice.value = ''
  try {
    const row = await saveRubric({
      blueprint: form.blueprint,
      title: form.title.trim(),
      evaluation_object: form.evaluation_object.trim(),
      criteria: cloneJson(form.criteria)
    }, props.draft?.id)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '量规草案保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <RubricCriterionModal
    v-if="criterionOpen"
    :criterion="selectedCriterion"
    :options="options"
    @cancel="closeCriterion"
    @save="saveCriterion"
  />

  <div v-else class="modal-backdrop" @click.self="emit('close')">
    <section class="entity-modal compact-modal measurement-editor rubric-editor" role="dialog" aria-modal="true" :aria-labelledby="`rubric-editor-${draft?.id || 'new'}`">
      <header class="modal-header">
        <div>
          <h2 :id="`rubric-editor-${draft?.id || 'new'}`">{{ modalTitle }}</h2>
          <p>五星用于逐项形成性判断；没有观察机会时记录 NOT_ASSESSED。</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="measurement-editor-body rubric-editor-body">
        <p v-if="notice" class="measurement-inline-error" role="alert">{{ notice }}</p>

        <section class="measurement-form-grid rubric-basics">
          <label>
            <span>任务蓝图<b>*</b></span>
            <select v-model="form.blueprint" :disabled="blueprintLocked">
              <option value="" disabled>请选择任务蓝图</option>
              <option v-for="blueprint in blueprints" :key="blueprint.id" :value="blueprint.id">
                {{ blueprint.course?.title || blueprint.subject.name }} · {{ blueprint.title }}
              </option>
            </select>
            <small v-if="blueprintLocked">已发布版本后不能更换蓝图。</small>
            <small v-if="errors.blueprint" class="field-error">{{ errors.blueprint[0] }}</small>
          </label>
          <label>
            <span>量规名称<b>*</b></span>
            <input v-model.trim="form.title" maxlength="160" placeholder="例如 数据表达形成性量规" />
            <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
          </label>
          <label class="span-2">
            <span>总体评价对象<b>*</b></span>
            <input v-model.trim="form.evaluation_object" maxlength="300" placeholder="例如 学生作品、解释文本与修订过程" />
            <small v-if="errors.evaluation_object" class="field-error">{{ errors.evaluation_object[0] }}</small>
          </label>
        </section>

        <section class="rubric-criterion-section">
          <header>
            <div>
              <strong>量规条目</strong>
              <small>从 P/S/R/C/D/E 模块选择真正需要观察的方面，不把出勤、积分或在线时长写入量规。</small>
            </div>
            <button class="primary-button" type="button" @click="openCriterion()">新增条目</button>
          </header>
          <p v-if="errors.criteria" class="field-error">{{ errors.criteria[0] }}</p>
          <p v-if="!form.criteria.length" class="rubric-empty">尚未添加量规条目。可以先保存空草案，但发布前必须补齐条目和锚定样例。</p>
          <div v-else class="rubric-criterion-list">
            <article v-for="(criterion, index) in form.criteria" :key="`${criterion.code}-${index}`">
              <div class="rubric-criterion-order">{{ index + 1 }}</div>
              <div class="rubric-criterion-main">
                <span>{{ moduleLabel(criterion.module) }} · {{ criterion.code }}</span>
                <strong>{{ criterion.title }}</strong>
                <small>{{ criterion.evaluation_object }}</small>
              </div>
              <div class="rubric-criterion-meta">
                <span>5 级锚点</span>
                <span>{{ criterion.anchor_examples.length }} 份样例</span>
              </div>
              <div class="rubric-criterion-actions">
                <button type="button" @click="openCriterion(index)">编辑</button>
                <button type="button" class="danger" @click="form.criteria.splice(index, 1)">删除</button>
              </div>
            </article>
          </div>
        </section>
      </div>

      <footer class="modal-actions measurement-modal-actions">
        <span>教师创建的量规只能用于本地形成性评价。</span>
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存草案' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.rubric-editor {
  width: min(1040px, 100%);
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.rubric-editor-body {
  display: grid;
  gap: 22px;
}

.rubric-basics {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}

.rubric-criterion-section,
.rubric-criterion-list {
  display: grid;
  gap: 12px;
}

.rubric-criterion-section > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.rubric-criterion-section > header div {
  display: grid;
  gap: 4px;
}

.rubric-criterion-section > header small {
  max-width: 720px;
  color: var(--muted);
  line-height: 1.5;
}

.rubric-empty {
  margin: 0;
  border: 1px dashed #b8c6d8;
  border-radius: 6px;
  padding: 24px;
  color: var(--muted);
  text-align: center;
}

.rubric-criterion-list article {
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

.rubric-criterion-order {
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

.rubric-criterion-main {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.rubric-criterion-main span,
.rubric-criterion-main small,
.rubric-criterion-meta {
  color: var(--muted);
  font-size: 12px;
}

.rubric-criterion-main strong,
.rubric-criterion-main small {
  overflow-wrap: anywhere;
}

.rubric-criterion-meta {
  display: flex;
  gap: 8px;
}

.rubric-criterion-meta span {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 8px;
  background: #fff;
  white-space: nowrap;
}

.rubric-criterion-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.rubric-criterion-actions button {
  min-height: 40px;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
}

.rubric-criterion-actions .danger {
  color: var(--danger);
}

@media (max-width: 760px) {
  .rubric-criterion-section > header {
    align-items: stretch;
    flex-direction: column;
  }

  .rubric-criterion-list article {
    grid-template-columns: 40px minmax(0, 1fr);
  }

  .rubric-criterion-meta,
  .rubric-criterion-actions {
    grid-column: 2;
  }
}
</style>
