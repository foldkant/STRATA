<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  saveEvaluationPlan,
  type EvaluationPlanPayload,
  type EvaluationPlanRow,
  type EvaluationOptions
} from '@/api/evaluation'

const props = defineProps<{
  draft: EvaluationPlanRow | null
  options: EvaluationOptions
}>()

const emit = defineEmits<{
  close: []
  saved: [row: EvaluationPlanRow]
}>()

const step = ref(1)
const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

const form = reactive<EvaluationPlanPayload>({
  course: props.draft?.course?.id || props.options.courses[0]?.id || '',
  title: props.draft?.title || '',
  content_version: props.draft?.content_version || '1.0',
  target_students: props.draft?.target_students || '',
  learning_goal: props.draft?.learning_goal || '',
  learning_goals: cloneJson(props.draft?.learning_goals || []),
  evaluation_basis: cloneJson(props.draft?.evaluation_basis || []),
  learning_tasks: cloneJson(props.draft?.learning_tasks || []),
  content_scope: [...(props.draft?.content_scope || [])],
  thinking_requirements: [...(props.draft?.thinking_requirements || [])],
  support_options: [...(props.draft?.support_options || [])],
  scoring_rules: {
    approach: props.draft?.scoring_rules?.approach || '按评价指标分别判断',
    decision_rule: props.draft?.scoring_rules?.decision_rule || ''
  },
  follow_up_suggestion: props.draft?.follow_up_suggestion || ''
})

const modalTitle = computed(() => props.draft ? '编辑评价方案' : '新建评价方案')
const courseLocked = computed(() => Boolean(props.draft?.latest_version))

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLTextAreaElement).value
}

function addGoal() {
  form.learning_goals.push({ code: `G${form.learning_goals.length + 1}`, title: '', description: '' })
}

function addBasis() {
  form.evaluation_basis.push({ code: `B${form.evaluation_basis.length + 1}`, goal_codes: [], description: '', source_types: [] })
}

function addTask() {
  form.learning_tasks.push({ code: `T${form.learning_tasks.length + 1}`, title: '', basis_codes: [], description: '' })
}

function toggleReference(values: string[], code: string, checked: boolean) {
  const next = checked ? Array.from(new Set([...values, code])) : values.filter((item) => item !== code)
  values.splice(0, values.length, ...next)
}

function validateStep() {
  const next: FieldErrors = {}
  if (step.value === 1) {
    if (!form.course) next.course = ['请选择课程。']
    if (form.title.trim().length < 2) next.title = ['方案名称至少 2 个字符。']
    if (!form.content_version.trim()) next.content_version = ['请填写适用内容版本。']
    if (!form.target_students.trim()) next.target_students = ['请描述适用学生。']
    if (form.learning_goal.trim().length < 8) next.learning_goal = ['学习目标至少 8 个字符。']
  }
  if (step.value === 2) {
    if (!form.learning_goals.length) next.learning_goals = ['至少添加一条学习目标。']
    if (!form.evaluation_basis.length) next.evaluation_basis = ['至少添加一条评价依据。']
    if (!form.learning_tasks.length) next.learning_tasks = ['至少添加一个学习任务。']
  }
  if (step.value === 3) {
    if (!form.content_scope.length) next.content_scope = ['至少填写一项评价内容。']
    if (!form.thinking_requirements.length) next.thinking_requirements = ['至少选择一种思维要求。']
    if (form.scoring_rules.decision_rule.trim().length < 8) next.scoring_rules = ['请填写评分判定说明。']
    if (form.follow_up_suggestion.trim().length < 8) next.follow_up_suggestion = ['请填写后续教学建议。']
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
    const row = await saveEvaluationPlan({
      ...form,
      title: form.title.trim(),
      content_version: form.content_version.trim(),
      target_students: form.target_students.trim(),
      learning_goal: form.learning_goal.trim(),
      learning_goals: form.learning_goals.map((item) => ({
        code: item.code.trim(),
        title: item.title.trim(),
        description: item.description.trim()
      })),
      evaluation_basis: form.evaluation_basis.map((item) => ({
        code: item.code.trim(),
        goal_codes: item.goal_codes,
        description: item.description.trim(),
        source_types: item.source_types
      })),
      learning_tasks: form.learning_tasks.map((item) => ({
        code: item.code.trim(),
        title: item.title.trim(),
        basis_codes: item.basis_codes,
        description: item.description.trim()
      })),
      scoring_rules: {
        approach: form.scoring_rules.approach.trim(),
        decision_rule: form.scoring_rules.decision_rule.trim()
      },
      follow_up_suggestion: form.follow_up_suggestion.trim()
    }, props.draft?.id)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '评价方案保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section class="entity-modal compact-modal evaluation-editor" role="dialog" aria-modal="true" :aria-labelledby="`plan-editor-${draft?.id || 'new'}`">
      <header class="modal-header">
        <div>
          <h2 :id="`plan-editor-${draft?.id || 'new'}`">{{ modalTitle }}</h2>
          <p>学习目标、评价依据、学习任务和评分规则</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <nav class="evaluation-stepper" aria-label="评价方案编辑步骤">
        <button type="button" :class="{ active: step === 1 }" @click="step = 1"><span>1</span>范围与目标</button>
        <button type="button" :class="{ active: step === 2 }" @click="step = 2"><span>2</span>依据与任务</button>
        <button type="button" :class="{ active: step === 3 }" @click="step = 3"><span>3</span>评分设置</button>
      </nav>

      <div class="evaluation-editor-body">
        <p v-if="notice" class="evaluation-inline-error" role="alert">{{ notice }}</p>

        <section v-if="step === 1" class="evaluation-form-grid">
          <label>
            <span>课程<b>*</b></span>
            <AppSelect v-model="form.course" :disabled="courseLocked">
              <option value="" disabled>请选择课程</option>
              <option v-for="course in options.courses" :key="course.id" :value="course.id">
                {{ course.subject.name }} · {{ course.title }}
              </option>
            </AppSelect>
            <small v-if="courseLocked">已发布版本后，范围不能更换。</small>
            <small v-if="errors.course" class="field-error">{{ errors.course[0] }}</small>
          </label>
          <label>
            <span>内容版本<b>*</b></span>
            <input v-model.trim="form.content_version" maxlength="64" placeholder="例如 1.0" />
            <small v-if="errors.content_version" class="field-error">{{ errors.content_version[0] }}</small>
          </label>
          <label class="span-2">
            <span>方案名称<b>*</b></span>
            <input v-model.trim="form.title" maxlength="160" placeholder="例如 数据表达与解释评价方案" />
            <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
          </label>
          <label class="span-2">
            <span>适用学生<b>*</b></span>
            <input v-model.trim="form.target_students" maxlength="300" placeholder="年级、学习单元与适用边界" />
            <small v-if="errors.target_students" class="field-error">{{ errors.target_students[0] }}</small>
          </label>
          <label class="span-2">
            <span>总体学习目标<b>*</b></span>
            <textarea v-model.trim="form.learning_goal" rows="4" placeholder="说明课程或任务希望学生达到的学习目标。" />
            <small v-if="errors.learning_goal" class="field-error">{{ errors.learning_goal[0] }}</small>
          </label>
        </section>

        <section v-else-if="step === 2" class="evaluation-chain-layout">
          <div class="evaluation-chain-section">
            <header><div><strong>学习目标</strong><small>学生应当知道、理解或能够完成什么</small></div><button class="secondary-button mini" type="button" @click="addGoal">新增目标</button></header>
            <p v-if="errors.learning_goals" class="field-error">{{ errors.learning_goals[0] }}</p>
            <div v-for="(goal, index) in form.learning_goals" :key="index" class="evaluation-chain-row claim-row">
              <input v-model.trim="goal.code" maxlength="32" aria-label="目标代码" placeholder="G1" />
              <input v-model.trim="goal.title" maxlength="160" aria-label="目标名称" placeholder="目标名称" />
              <textarea v-model.trim="goal.description" rows="2" aria-label="目标说明" placeholder="写清楚学生应达到的具体表现" />
              <button type="button" class="evaluation-remove" @click="form.learning_goals.splice(index, 1)">删除</button>
            </div>
          </div>

          <div class="evaluation-chain-section">
            <header><div><strong>评价依据</strong><small>根据哪些作品、答案或表现进行判断</small></div><button class="secondary-button mini" type="button" @click="addBasis">新增依据</button></header>
            <p v-if="errors.evaluation_basis" class="field-error">{{ errors.evaluation_basis[0] }}</p>
            <div v-for="(evidence, index) in form.evaluation_basis" :key="index" class="evaluation-chain-row evidence-row">
              <input v-model.trim="evidence.code" maxlength="32" aria-label="依据代码" placeholder="B1" />
              <div class="evaluation-reference-list">
                <span>关联目标</span>
                <label v-for="goal in form.learning_goals" :key="goal.code">
                  <input type="checkbox" :checked="evidence.goal_codes.includes(goal.code)" @change="toggleReference(evidence.goal_codes, goal.code, ($event.target as HTMLInputElement).checked)" />
                  {{ goal.code || '未命名' }}
                </label>
              </div>
              <textarea v-model.trim="evidence.description" rows="2" aria-label="依据说明" placeholder="说明如何据此判断学生表现" />
              <textarea :value="evidence.source_types.join('\n')" rows="2" aria-label="材料来源" placeholder="每行一种材料，例如学生作品" @input="evidence.source_types = lines(inputValue($event))" />
              <button type="button" class="evaluation-remove" @click="form.evaluation_basis.splice(index, 1)">删除</button>
            </div>
          </div>

          <div class="evaluation-chain-section">
            <header><div><strong>学习任务</strong><small>学生通过什么任务展示学习结果</small></div><button class="secondary-button mini" type="button" @click="addTask">新增任务</button></header>
            <p v-if="errors.learning_tasks" class="field-error">{{ errors.learning_tasks[0] }}</p>
            <div v-for="(task, index) in form.learning_tasks" :key="index" class="evaluation-chain-row task-row">
              <input v-model.trim="task.code" maxlength="32" aria-label="任务代码" placeholder="T1" />
              <input v-model.trim="task.title" maxlength="160" aria-label="任务名称" placeholder="任务名称" />
              <div class="evaluation-reference-list">
                <span>关联依据</span>
                <label v-for="evidence in form.evaluation_basis" :key="evidence.code">
                  <input type="checkbox" :checked="task.basis_codes.includes(evidence.code)" @change="toggleReference(task.basis_codes, evidence.code, ($event.target as HTMLInputElement).checked)" />
                  {{ evidence.code || '未命名' }}
                </label>
              </div>
              <textarea v-model.trim="task.description" rows="2" aria-label="任务说明" placeholder="任务条件、产出和边界" />
              <button type="button" class="evaluation-remove" @click="form.learning_tasks.splice(index, 1)">删除</button>
            </div>
          </div>
        </section>

        <section v-else class="evaluation-form-grid">
          <label>
            <span>评价内容<b>*</b></span>
            <textarea :value="form.content_scope.join('\n')" rows="5" placeholder="每行一项评价内容" @input="form.content_scope = lines(inputValue($event))" />
            <small v-if="errors.content_scope" class="field-error">{{ errors.content_scope[0] }}</small>
          </label>
          <fieldset class="evaluation-check-field">
            <legend>思维要求<b>*</b></legend>
            <label v-for="item in options.thinking_requirements" :key="item.value">
              <input v-model="form.thinking_requirements" type="checkbox" :value="item.value" />
              {{ item.label }}
            </label>
            <small v-if="errors.thinking_requirements" class="field-error">{{ errors.thinking_requirements[0] }}</small>
          </fieldset>
          <label>
            <span>可用帮助</span>
            <textarea :value="form.support_options.join('\n')" rows="5" placeholder="每行一种允许使用的工具或帮助，没有可留空" @input="form.support_options = lines(inputValue($event))" />
          </label>
          <label>
            <span>评分方式<b>*</b></span>
            <input v-model.trim="form.scoring_rules.approach" maxlength="160" placeholder="例如 按评价指标分别判断" />
          </label>
          <label class="span-2">
            <span>评分判定说明<b>*</b></span>
            <textarea v-model.trim="form.scoring_rules.decision_rule" rows="4" placeholder="说明如何根据学生表现确定星级；没有可评价材料时暂不评价。" />
            <small v-if="errors.scoring_rules" class="field-error">{{ errors.scoring_rules[0] }}</small>
          </label>
          <label class="span-2">
            <span>后续教学建议<b>*</b></span>
            <textarea v-model.trim="form.follow_up_suggestion" rows="4" placeholder="说明评价结果如何转化为反馈、练习或支持。" />
            <small v-if="errors.follow_up_suggestion" class="field-error">{{ errors.follow_up_suggestion[0] }}</small>
          </label>
        </section>
      </div>

      <footer class="modal-actions evaluation-modal-actions">
        <span>发布后保留历史版本，后续修改会生成新版本。</span>
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button v-if="step > 1" class="secondary-button" type="button" @click="step -= 1">上一步</button>
        <button v-if="step < 3" class="primary-button" type="button" @click="nextStep">下一步</button>
        <button v-else class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存草案' }}</button>
      </footer>
    </section>
  </div>
</template>

<style>
.evaluation-editor {
  width: min(1080px, 100%);
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}

.evaluation-editor .modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.evaluation-stepper {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-bottom: 1px solid var(--line);
  background: #f8fafc;
}

.evaluation-stepper button {
  min-height: 52px;
  border: 0;
  border-right: 1px solid var(--line);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.evaluation-stepper button:last-child {
  border-right: 0;
}

.evaluation-stepper button.active {
  background: #fff;
  color: var(--primary);
  font-weight: 700;
}

.evaluation-stepper span {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  margin-right: 8px;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-variant-numeric: tabular-nums;
}

.evaluation-editor-body {
  min-height: 0;
  overflow: auto;
  padding: 20px 22px;
}

.evaluation-inline-error {
  margin: 0 0 14px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fef2f2;
  color: #991b1b;
}

.evaluation-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.evaluation-form-grid > label,
.evaluation-check-field {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 7px;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.evaluation-form-grid .span-2 {
  grid-column: 1 / -1;
}

.evaluation-form-grid input,
.evaluation-form-grid select,
.evaluation-form-grid textarea,
.evaluation-chain-row input,
.evaluation-chain-row textarea {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  padding: 10px 12px;
  resize: vertical;
}

.evaluation-form-grid b,
.evaluation-check-field b {
  margin-left: 2px;
  color: var(--danger);
}

.evaluation-form-grid small {
  line-height: 1.5;
}

.evaluation-check-field {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px;
}

.evaluation-check-field legend {
  padding: 0 4px;
  color: var(--text);
  font-weight: 600;
}

.evaluation-check-field label {
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.evaluation-check-field input,
.evaluation-reference-list input {
  width: 18px;
  height: 18px;
  min-height: 18px;
}

.evaluation-chain-layout,
.evaluation-chain-section {
  display: grid;
  gap: 14px;
}

.evaluation-chain-section + .evaluation-chain-section {
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.evaluation-chain-section > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.evaluation-chain-section > header div {
  display: grid;
  gap: 3px;
}

.evaluation-chain-section > header small {
  color: var(--muted);
}

.evaluation-chain-row {
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

.evaluation-reference-list {
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

.evaluation-reference-list > span {
  width: 100%;
  color: var(--muted);
  font-size: 12px;
}

.evaluation-reference-list label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
}

.evaluation-remove {
  min-height: 44px;
  border: 0;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
}

.evaluation-modal-actions {
  align-items: center;
}

.evaluation-modal-actions > span {
  margin-right: auto;
  color: var(--muted);
  font-size: 12px;
}

@media (max-width: 900px) {
  .evaluation-chain-row,
  .evidence-row,
  .task-row {
    grid-template-columns: 90px minmax(0, 1fr);
  }

  .evaluation-chain-row textarea,
  .evaluation-reference-list {
    grid-column: 1 / -1;
  }
}

@media (max-width: 640px) {
  .modal-backdrop {
    padding: 0;
  }

  .evaluation-editor {
    width: 100%;
    max-height: 100dvh;
    border-radius: 0;
  }

  .evaluation-stepper button {
    padding: 6px;
    font-size: 12px;
  }

  .evaluation-stepper span {
    display: none;
  }

  .evaluation-form-grid,
  .evaluation-chain-row,
  .evidence-row,
  .task-row {
    grid-template-columns: 1fr;
  }

  .evaluation-form-grid .span-2,
  .evaluation-chain-row textarea,
  .evaluation-reference-list {
    grid-column: auto;
  }

  .evaluation-modal-actions {
    flex-wrap: wrap;
  }

  .evaluation-modal-actions > span {
    width: 100%;
  }
}
</style>
