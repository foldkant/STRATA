<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  saveBlueprint,
  type BlueprintPayload,
  type BlueprintRow,
  type MeasurementOptions
} from '@/api/measurement'

const props = defineProps<{
  draft: BlueprintRow | null
  options: MeasurementOptions
}>()

const emit = defineEmits<{
  close: []
  saved: [row: BlueprintRow]
}>()

const step = ref(1)
const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

const form = reactive<BlueprintPayload>({
  course: props.draft?.course?.id || props.options.courses[0]?.id || '',
  title: props.draft?.title || '',
  task_version: props.draft?.task_version || '1.0',
  target_population: props.draft?.target_population || '',
  course_goal: props.draft?.course_goal || '',
  claims: cloneJson(props.draft?.claims || []),
  evidence_rules: cloneJson(props.draft?.evidence_rules || []),
  task_specifications: cloneJson(props.draft?.task_specifications || []),
  content_coverage: [...(props.draft?.content_coverage || [])],
  cognitive_complexity: [...(props.draft?.cognitive_complexity || [])],
  allowed_supports: [...(props.draft?.allowed_supports || [])],
  scoring_model: {
    approach: props.draft?.scoring_model?.approach || '分析式量规逐项判断',
    decision_rule: props.draft?.scoring_model?.decision_rule || ''
  },
  next_formative_action: props.draft?.next_formative_action || ''
})

const modalTitle = computed(() => props.draft ? '编辑任务蓝图' : '新建任务蓝图')
const courseLocked = computed(() => Boolean(props.draft?.latest_version))

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLTextAreaElement).value
}

function addClaim() {
  form.claims.push({ code: `C${form.claims.length + 1}`, title: '', description: '' })
}

function addEvidence() {
  form.evidence_rules.push({ code: `E${form.evidence_rules.length + 1}`, claim_codes: [], description: '', source_types: [] })
}

function addTask() {
  form.task_specifications.push({ code: `T${form.task_specifications.length + 1}`, title: '', evidence_codes: [], description: '' })
}

function toggleReference(values: string[], code: string, checked: boolean) {
  const next = checked ? Array.from(new Set([...values, code])) : values.filter((item) => item !== code)
  values.splice(0, values.length, ...next)
}

function validateStep() {
  const next: FieldErrors = {}
  if (step.value === 1) {
    if (!form.course) next.course = ['请选择课程。']
    if (form.title.trim().length < 2) next.title = ['蓝图名称至少 2 个字符。']
    if (!form.task_version.trim()) next.task_version = ['请填写任务版本。']
    if (!form.target_population.trim()) next.target_population = ['请描述目标学生总体。']
    if (form.course_goal.trim().length < 8) next.course_goal = ['课程目标至少 8 个字符。']
  }
  if (step.value === 2) {
    if (!form.claims.length) next.claims = ['至少添加一条学习主张。']
    if (!form.evidence_rules.length) next.evidence_rules = ['至少添加一条证据规则。']
    if (!form.task_specifications.length) next.task_specifications = ['至少添加一个任务规格。']
  }
  if (step.value === 3) {
    if (!form.content_coverage.length) next.content_coverage = ['至少填写一项内容覆盖。']
    if (!form.cognitive_complexity.length) next.cognitive_complexity = ['至少选择一种认知复杂度。']
    if (form.scoring_model.decision_rule.trim().length < 8) next.scoring_model = ['请填写证据解释规则。']
    if (form.next_formative_action.trim().length < 8) next.next_formative_action = ['请填写下一步形成性行动。']
  }
  errors.value = next
  return !Object.keys(next).length
}

function nextStep() {
  if (!validateStep()) return
  step.value = Math.min(3, step.value + 1)
}

async function save() {
  if (!validateStep()) return
  saving.value = true
  notice.value = ''
  errors.value = {}
  try {
    const row = await saveBlueprint({
      ...form,
      title: form.title.trim(),
      task_version: form.task_version.trim(),
      target_population: form.target_population.trim(),
      course_goal: form.course_goal.trim(),
      claims: form.claims.map((item) => ({
        code: item.code.trim(),
        title: item.title.trim(),
        description: item.description.trim()
      })),
      evidence_rules: form.evidence_rules.map((item) => ({
        code: item.code.trim(),
        claim_codes: item.claim_codes,
        description: item.description.trim(),
        source_types: item.source_types
      })),
      task_specifications: form.task_specifications.map((item) => ({
        code: item.code.trim(),
        title: item.title.trim(),
        evidence_codes: item.evidence_codes,
        description: item.description.trim()
      })),
      scoring_model: {
        approach: form.scoring_model.approach.trim(),
        decision_rule: form.scoring_model.decision_rule.trim()
      },
      next_formative_action: form.next_formative_action.trim()
    }, props.draft?.id)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '蓝图草案保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section class="entity-modal compact-modal measurement-editor" role="dialog" aria-modal="true" :aria-labelledby="`blueprint-editor-${draft?.id || 'new'}`">
      <header class="modal-header">
        <div>
          <h2 :id="`blueprint-editor-${draft?.id || 'new'}`">{{ modalTitle }}</h2>
          <p>Claim → Evidence → Task → Scoring → Use</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <nav class="measurement-stepper" aria-label="蓝图编辑步骤">
        <button type="button" :class="{ active: step === 1 }" @click="step = 1"><span>1</span>范围与目标</button>
        <button type="button" :class="{ active: step === 2 }" @click="step = 2"><span>2</span>证据链</button>
        <button type="button" :class="{ active: step === 3 }" @click="step = 3"><span>3</span>评分与使用</button>
      </nav>

      <div class="measurement-editor-body">
        <p v-if="notice" class="measurement-inline-error" role="alert">{{ notice }}</p>

        <section v-if="step === 1" class="measurement-form-grid">
          <label>
            <span>课程<b>*</b></span>
            <select v-model="form.course" :disabled="courseLocked">
              <option value="" disabled>请选择课程</option>
              <option v-for="course in options.courses" :key="course.id" :value="course.id">
                {{ course.subject.name }} · {{ course.title }}
              </option>
            </select>
            <small v-if="courseLocked">已发布版本后，范围不能更换。</small>
            <small v-if="errors.course" class="field-error">{{ errors.course[0] }}</small>
          </label>
          <label>
            <span>任务版本<b>*</b></span>
            <input v-model.trim="form.task_version" maxlength="64" placeholder="例如 1.0" />
            <small v-if="errors.task_version" class="field-error">{{ errors.task_version[0] }}</small>
          </label>
          <label class="span-2">
            <span>蓝图名称<b>*</b></span>
            <input v-model.trim="form.title" maxlength="160" placeholder="例如 数据表达与解释任务蓝图" />
            <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
          </label>
          <label class="span-2">
            <span>目标学生总体<b>*</b></span>
            <input v-model.trim="form.target_population" maxlength="300" placeholder="年级、学习单元与适用边界" />
            <small v-if="errors.target_population" class="field-error">{{ errors.target_population[0] }}</small>
          </label>
          <label class="span-2">
            <span>学科或课程目标<b>*</b></span>
            <textarea v-model.trim="form.course_goal" rows="4" placeholder="描述任务要支持解释的学习目标，不写出勤、积分或服从性指标。" />
            <small v-if="errors.course_goal" class="field-error">{{ errors.course_goal[0] }}</small>
          </label>
        </section>

        <section v-else-if="step === 2" class="measurement-chain-layout">
          <div class="measurement-chain-section">
            <header><div><strong>学习主张</strong><small>学生应当知道、理解或能够完成什么</small></div><button class="secondary-button mini" type="button" @click="addClaim">新增主张</button></header>
            <p v-if="errors.claims" class="field-error">{{ errors.claims[0] }}</p>
            <div v-for="(claim, index) in form.claims" :key="index" class="measurement-chain-row claim-row">
              <input v-model.trim="claim.code" maxlength="32" aria-label="主张代码" placeholder="C1" />
              <input v-model.trim="claim.title" maxlength="160" aria-label="主张名称" placeholder="主张名称" />
              <textarea v-model.trim="claim.description" rows="2" aria-label="主张说明" placeholder="可解释、可观察的学习主张" />
              <button type="button" class="measurement-remove" @click="form.claims.splice(index, 1)">删除</button>
            </div>
          </div>

          <div class="measurement-chain-section">
            <header><div><strong>证据规则</strong><small>哪些证据可以支持哪些主张</small></div><button class="secondary-button mini" type="button" @click="addEvidence">新增证据</button></header>
            <p v-if="errors.evidence_rules" class="field-error">{{ errors.evidence_rules[0] }}</p>
            <div v-for="(evidence, index) in form.evidence_rules" :key="index" class="measurement-chain-row evidence-row">
              <input v-model.trim="evidence.code" maxlength="32" aria-label="证据代码" placeholder="E1" />
              <div class="measurement-reference-list">
                <span>关联主张</span>
                <label v-for="claim in form.claims" :key="claim.code">
                  <input type="checkbox" :checked="evidence.claim_codes.includes(claim.code)" @change="toggleReference(evidence.claim_codes, claim.code, ($event.target as HTMLInputElement).checked)" />
                  {{ claim.code || '未命名' }}
                </label>
              </div>
              <textarea v-model.trim="evidence.description" rows="2" aria-label="证据说明" placeholder="证据如何支持判断" />
              <textarea :value="evidence.source_types.join('\n')" rows="2" aria-label="证据来源" placeholder="每行一个来源，例如 学生作品" @input="evidence.source_types = lines(inputValue($event))" />
              <button type="button" class="measurement-remove" @click="form.evidence_rules.splice(index, 1)">删除</button>
            </div>
          </div>

          <div class="measurement-chain-section">
            <header><div><strong>任务规格</strong><small>通过什么任务产生所需证据</small></div><button class="secondary-button mini" type="button" @click="addTask">新增任务</button></header>
            <p v-if="errors.task_specifications" class="field-error">{{ errors.task_specifications[0] }}</p>
            <div v-for="(task, index) in form.task_specifications" :key="index" class="measurement-chain-row task-row">
              <input v-model.trim="task.code" maxlength="32" aria-label="任务代码" placeholder="T1" />
              <input v-model.trim="task.title" maxlength="160" aria-label="任务名称" placeholder="任务名称" />
              <div class="measurement-reference-list">
                <span>关联证据</span>
                <label v-for="evidence in form.evidence_rules" :key="evidence.code">
                  <input type="checkbox" :checked="task.evidence_codes.includes(evidence.code)" @change="toggleReference(task.evidence_codes, evidence.code, ($event.target as HTMLInputElement).checked)" />
                  {{ evidence.code || '未命名' }}
                </label>
              </div>
              <textarea v-model.trim="task.description" rows="2" aria-label="任务说明" placeholder="任务条件、产出和边界" />
              <button type="button" class="measurement-remove" @click="form.task_specifications.splice(index, 1)">删除</button>
            </div>
          </div>
        </section>

        <section v-else class="measurement-form-grid">
          <label>
            <span>内容覆盖<b>*</b></span>
            <textarea :value="form.content_coverage.join('\n')" rows="5" placeholder="每行一个内容范围" @input="form.content_coverage = lines(inputValue($event))" />
            <small v-if="errors.content_coverage" class="field-error">{{ errors.content_coverage[0] }}</small>
          </label>
          <fieldset class="measurement-check-field">
            <legend>认知复杂度<b>*</b></legend>
            <label v-for="item in options.cognitive_complexities" :key="item.value">
              <input v-model="form.cognitive_complexity" type="checkbox" :value="item.value" />
              {{ item.label }}
            </label>
            <small v-if="errors.cognitive_complexity" class="field-error">{{ errors.cognitive_complexity[0] }}</small>
          </fieldset>
          <label>
            <span>允许支持</span>
            <textarea :value="form.allowed_supports.join('\n')" rows="5" placeholder="每行一种允许的支架、工具或帮助；没有可留空" @input="form.allowed_supports = lines(inputValue($event))" />
          </label>
          <label>
            <span>评分方式<b>*</b></span>
            <input v-model.trim="form.scoring_model.approach" maxlength="160" placeholder="例如 分析式量规逐项判断" />
          </label>
          <label class="span-2">
            <span>证据解释规则<b>*</b></span>
            <textarea v-model.trim="form.scoring_model.decision_rule" rows="4" placeholder="说明如何由证据形成判断；没有观察机会时必须记录 NOT_ASSESSED。" />
            <small v-if="errors.scoring_model" class="field-error">{{ errors.scoring_model[0] }}</small>
          </label>
          <label class="span-2">
            <span>下一步形成性行动<b>*</b></span>
            <textarea v-model.trim="form.next_formative_action" rows="4" placeholder="说明评价结果如何转化为反馈、练习或支持。" />
            <small v-if="errors.next_formative_action" class="field-error">{{ errors.next_formative_action[0] }}</small>
          </label>
        </section>
      </div>

      <footer class="modal-actions measurement-modal-actions">
        <span>教师草案固定为“本地形成性”，发布后版本不可修改。</span>
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button v-if="step > 1" class="secondary-button" type="button" @click="step -= 1">上一步</button>
        <button v-if="step < 3" class="primary-button" type="button" @click="nextStep">下一步</button>
        <button v-else class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存草案' }}</button>
      </footer>
    </section>
  </div>
</template>

<style>
.measurement-editor {
  width: min(1080px, 100%);
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}

.measurement-editor .modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.measurement-stepper {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-bottom: 1px solid var(--line);
  background: #f8fafc;
}

.measurement-stepper button {
  min-height: 52px;
  border: 0;
  border-right: 1px solid var(--line);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.measurement-stepper button:last-child {
  border-right: 0;
}

.measurement-stepper button.active {
  background: #fff;
  color: var(--primary);
  font-weight: 700;
}

.measurement-stepper span {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  margin-right: 8px;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-variant-numeric: tabular-nums;
}

.measurement-editor-body {
  min-height: 0;
  overflow: auto;
  padding: 20px 22px;
}

.measurement-inline-error {
  margin: 0 0 14px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fef2f2;
  color: #991b1b;
}

.measurement-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.measurement-form-grid > label,
.measurement-check-field {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 7px;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.measurement-form-grid .span-2 {
  grid-column: 1 / -1;
}

.measurement-form-grid input,
.measurement-form-grid select,
.measurement-form-grid textarea,
.measurement-chain-row input,
.measurement-chain-row textarea {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  padding: 10px 12px;
  resize: vertical;
}

.measurement-form-grid b,
.measurement-check-field b {
  margin-left: 2px;
  color: var(--danger);
}

.measurement-form-grid small {
  line-height: 1.5;
}

.measurement-check-field {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px;
}

.measurement-check-field legend {
  padding: 0 4px;
  color: var(--text);
  font-weight: 600;
}

.measurement-check-field label {
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.measurement-check-field input,
.measurement-reference-list input {
  width: 18px;
  height: 18px;
  min-height: 18px;
}

.measurement-chain-layout,
.measurement-chain-section {
  display: grid;
  gap: 14px;
}

.measurement-chain-section + .measurement-chain-section {
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.measurement-chain-section > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.measurement-chain-section > header div {
  display: grid;
  gap: 3px;
}

.measurement-chain-section > header small {
  color: var(--muted);
}

.measurement-chain-row {
  position: relative;
  display: grid;
  grid-template-columns: 92px minmax(150px, .65fr) minmax(240px, 1.35fr) auto;
  align-items: start;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-left: 4px solid #3b82f6;
  border-radius: 6px;
  background: #fbfdff;
}

.evidence-row {
  grid-template-columns: 92px minmax(170px, .7fr) minmax(220px, 1fr) minmax(180px, .8fr) auto;
  border-left-color: #0f9f6e;
}

.task-row {
  grid-template-columns: 92px minmax(140px, .55fr) minmax(170px, .65fr) minmax(230px, 1fr) auto;
  border-left-color: #d97706;
}

.measurement-reference-list {
  min-height: 44px;
  display: flex;
  flex-wrap: wrap;
  align-content: center;
  gap: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  background: #fff;
}

.measurement-reference-list > span {
  width: 100%;
  color: var(--muted);
  font-size: 12px;
}

.measurement-reference-list label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
}

.measurement-remove {
  min-height: 44px;
  border: 0;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
}

.measurement-modal-actions {
  align-items: center;
}

.measurement-modal-actions > span {
  margin-right: auto;
  color: var(--muted);
  font-size: 12px;
}

@media (max-width: 900px) {
  .measurement-chain-row,
  .evidence-row,
  .task-row {
    grid-template-columns: 90px minmax(0, 1fr);
  }

  .measurement-chain-row textarea,
  .measurement-reference-list {
    grid-column: 1 / -1;
  }
}

@media (max-width: 640px) {
  .modal-backdrop {
    padding: 0;
  }

  .measurement-editor {
    width: 100%;
    max-height: 100dvh;
    border-radius: 0;
  }

  .measurement-stepper button {
    padding: 6px;
    font-size: 12px;
  }

  .measurement-stepper span {
    display: none;
  }

  .measurement-form-grid,
  .measurement-chain-row,
  .evidence-row,
  .task-row {
    grid-template-columns: 1fr;
  }

  .measurement-form-grid .span-2,
  .measurement-chain-row textarea,
  .measurement-reference-list {
    grid-column: auto;
  }

  .measurement-modal-actions {
    flex-wrap: wrap;
  }

  .measurement-modal-actions > span {
    width: 100%;
  }
}
</style>
