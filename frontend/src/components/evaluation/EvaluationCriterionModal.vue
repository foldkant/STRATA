<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import type { EvaluationEvidenceOwnership, EvaluationOptions, EvaluationCriterion, EvaluationPlanVersionOption } from '@/api/evaluation'
import { vModalFocus } from '@/directives/modalFocus'

const props = defineProps<{
  criterion: EvaluationCriterion | null
  options: EvaluationOptions
  planVersion: EvaluationPlanVersionOption | null
  suggestedCode: string
  aiDrafted?: boolean
}>()

const emit = defineEmits<{
  cancel: []
  save: [criterion: EvaluationCriterion]
}>()

const step = ref(1)
const error = ref('')
const submitted = ref(false)

function requestCancel() {
  if (!submitted.value) emit('cancel')
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function emptyCriterion(): EvaluationCriterion {
  return {
    code: props.suggestedCode,
    dimension: 'subject_practice',
    title: '',
    evaluation_target: '',
    evaluation_sources: [],
    learning_goal_codes: [],
    evaluation_task_codes: [],
    evidence_ownership: 'individual',
    material_types: [],
    expected_performance: '',
    skip_condition: '',
    support_options: [],
    common_problems: [],
    level_descriptions: { '1': '', '2': '', '3': '', '4': '', '5': '' },
    scoring_examples: [
      { level: 2, title: '', example_description: '', file_reference: '' },
      { level: 4, title: '', example_description: '', file_reference: '' }
    ],
    follow_up_suggestion: ''
  }
}

const materialLabelByValue = new Map(props.options.material_types.map((item) => [item.value, item.label]))

function readableEvaluationSources(values: string[]) {
  return values.map((value) => materialLabelByValue.get(value) || value)
}

const form = reactive<EvaluationCriterion>({
  ...emptyCriterion(),
  ...cloneJson(props.criterion || {} as EvaluationCriterion),
  learning_goal_codes: [...(props.criterion?.learning_goal_codes || [])],
  evaluation_task_codes: [...(props.criterion?.evaluation_task_codes || [])],
  evaluation_sources: readableEvaluationSources(props.criterion?.evaluation_sources || []),
  material_types: [...(props.criterion?.material_types || [])]
})
const title = computed(() => {
  if (props.aiDrafted && props.criterion) return '审阅 AI 起草的评价指标'
  return props.criterion ? '编辑评价指标' : '手工补充评价指标'
})
const introduction = computed(() => (
  props.aiDrafted && props.criterion
    ? 'AI 已起草评价材料、具体表现、星级说明和评分示例，请结合本班教学实际逐项核对。'
    : '这是一项手工补充指标，需要依次设置评价材料、具体表现、星级说明和评分示例。'
))
const selectedTasks = computed(() => (props.planVersion?.evaluation_tasks || []).filter((task) => (
  form.evaluation_task_codes.includes(task.code)
)))

const allowedOwnershipValues = computed(() => {
  const allValues = props.options.evidence_ownerships.map((item) => item.value)
  if (!selectedTasks.value.length) return new Set(allValues)
  const compatible = {
    individual: new Set(['individual']),
    group: new Set(['group']),
    both: new Set(['individual', 'group', 'both'])
  } as const
  return selectedTasks.value.reduce<Set<string>>((allowed, task) => {
    const taskAllowed = compatible[task.evidence_ownership as keyof typeof compatible] || new Set<string>()
    return new Set([...allowed].filter((value) => taskAllowed.has(value)))
  }, new Set(allValues))
})

const allowedOwnershipOptions = computed(() => props.options.evidence_ownerships.filter((item) => (
  allowedOwnershipValues.value.has(item.value)
)))

const allowedMaterialValues = computed(() => {
  if (!selectedTasks.value.length) {
    return new Set(props.options.material_types.map((item) => item.value))
  }
  return new Set(selectedTasks.value.flatMap((task) => task.material_types))
})

const allowedMaterialOptions = computed(() => props.options.material_types.filter((item) => (
  allowedMaterialValues.value.has(item.value)
)))

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLTextAreaElement).value
}

function addExample() {
  form.scoring_examples.push({ level: 3, title: '', example_description: '', file_reference: '' })
}

function toggleReference(values: string[], value: string, checked: boolean) {
  const next = checked ? Array.from(new Set([...values, value])) : values.filter((item) => item !== value)
  values.splice(0, values.length, ...next)
}

function toggleTaskReference(value: string, checked: boolean) {
  toggleReference(form.evaluation_task_codes, value, checked)
  form.material_types = form.material_types.filter((item) => allowedMaterialValues.value.has(item))
  const allowedGoalCodes = new Set(selectedTasks.value.flatMap((task) => task.goal_codes))
  form.learning_goal_codes = form.learning_goal_codes.filter((item) => allowedGoalCodes.has(item))
  if (!allowedOwnershipValues.value.has(form.evidence_ownership) && allowedOwnershipOptions.value.length) {
    form.evidence_ownership = allowedOwnershipOptions.value[0].value as EvaluationEvidenceOwnership
  }
}

function validateCurrentStep() {
  error.value = ''
  if (step.value === 1) {
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(form.code.trim())) error.value = '条目代码必须以字母开头，只能包含字母、数字、下划线或连字符。'
    else if (form.title.trim().length < 2) error.value = '请填写条目名称。'
    else if (form.evaluation_target.trim().length < 4) error.value = '请明确评价对象。'
    else if (!form.evaluation_sources.length) error.value = '至少填写一种材料来源。'
    else if (!form.learning_goal_codes.length) error.value = '评价指标必须关联至少一条学习目标。'
    else if (!form.evaluation_task_codes.length) error.value = '评价指标必须关联至少一个评价任务。'
    else if (selectedTasks.value.some((task) => !task.goal_codes.some((code) => form.learning_goal_codes.includes(code)))) error.value = '每个所选评价任务都必须与本指标至少共享一条学习目标。'
    else if (form.learning_goal_codes.some((code) => !selectedTasks.value.some((task) => task.goal_codes.includes(code)))) error.value = '评价指标只能关联所选评价任务覆盖的学习目标。'
    else if (!allowedOwnershipOptions.value.length) error.value = '所选评价任务没有共同的材料归属，请拆分为不同评价指标。'
    else if (!allowedOwnershipValues.value.has(form.evidence_ownership)) error.value = '评价材料归属与所选评价任务不一致。'
    else if (!form.material_types.length) error.value = '至少选择一种评价材料类型。'
    else if (form.material_types.some((item) => !allowedMaterialValues.value.has(item))) error.value = '评价材料类型与所选评价任务不一致。'
    else if (selectedTasks.value.some((task) => !task.material_types.some((item) => form.material_types.includes(item)))) error.value = '所选材料必须分别覆盖每个评价任务可形成的材料类型。'
    else if (form.expected_performance.trim().length < 8) error.value = '具体表现至少 8 个字符。'
  } else if (step.value === 2) {
    if (form.skip_condition.trim().length < 8) error.value = '请明确哪些情况下暂不评价。'
    else if (!form.common_problems.length) error.value = '至少填写一个常见问题。'
    else if (Object.values(form.level_descriptions).some((item) => item.trim().length < 8)) error.value = '1-5 星都必须填写完整的表现说明。'
    else if (new Set(Object.values(form.level_descriptions).map((item) => item.trim())).size !== 5) error.value = '五个星级说明必须各不相同。'
  } else {
    if (form.scoring_examples.length < 2) error.value = '至少需要两个评分示例。'
    else if (form.scoring_examples.some((item) => !item.title.trim() || item.example_description.trim().length < 8)) error.value = '每个评分示例都要填写名称和说明。'
    else if (new Set(form.scoring_examples.map((item) => Number(item.level))).size < 2) error.value = '评分示例至少覆盖两个星级。'
    else if (form.follow_up_suggestion.trim().length < 8) error.value = '请填写后续教学建议。'
  }
  return !error.value
}

function nextStep() {
  if (!validateCurrentStep()) return
  step.value = Math.min(3, step.value + 1)
}

function submit() {
  if (submitted.value) return
  if (!validateCurrentStep()) return
  submitted.value = true
  emit('save', {
    ...cloneJson(form),
    code: form.code.trim(),
    title: form.title.trim(),
    evaluation_target: form.evaluation_target.trim(),
    expected_performance: form.expected_performance.trim(),
    skip_condition: form.skip_condition.trim(),
    level_descriptions: Object.fromEntries(Object.entries(form.level_descriptions).map(([key, value]) => [key, value.trim()])),
    scoring_examples: form.scoring_examples.map((item) => ({
      level: Number(item.level),
      title: item.title.trim(),
      example_description: item.example_description.trim(),
      file_reference: item.file_reference.trim()
    })),
    follow_up_suggestion: form.follow_up_suggestion.trim()
  })
}
</script>

<template>
  <div class="modal-backdrop evaluation-editor-backdrop" @click.self="requestCancel">
    <section v-modal-focus="requestCancel" class="entity-modal compact-modal evaluation-editor criterion-editor" role="dialog" aria-modal="true" aria-labelledby="criterion-editor-title">
      <header class="modal-header">
        <div>
          <h2 id="criterion-editor-title">{{ title }}</h2>
          <p>{{ introduction }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="返回评价标准" :disabled="submitted" @click="requestCancel">×</button>
      </header>

      <nav class="evaluation-stepper" aria-label="评价指标编辑步骤">
        <button type="button" :class="{ active: step === 1 }" @click="step = 1"><span>1</span>评价内容</button>
        <button type="button" :class="{ active: step === 2 }" @click="step = 2"><span>2</span>星级说明</button>
        <button type="button" :class="{ active: step === 3 }" @click="step = 3"><span>3</span>评分示例</button>
      </nav>

      <div class="evaluation-editor-body">
        <p v-if="error" class="evaluation-inline-error" role="alert">{{ error }}</p>

        <section v-if="step === 1" class="evaluation-form-grid">
          <fieldset class="criterion-link-field">
            <legend>对应学习目标<b>*</b></legend>
            <label v-for="goal in planVersion?.learning_goals || []" :key="goal.code"><input type="checkbox" :disabled="Boolean(selectedTasks.length) && !selectedTasks.some((task) => task.goal_codes.includes(goal.code))" :checked="form.learning_goal_codes.includes(goal.code)" @change="toggleReference(form.learning_goal_codes, goal.code, ($event.target as HTMLInputElement).checked)" />{{ goal.title }}</label>
          </fieldset>
          <fieldset class="criterion-link-field">
            <legend>对应评价任务<b>*</b></legend>
            <label v-for="task in planVersion?.evaluation_tasks || []" :key="task.code"><input type="checkbox" :checked="form.evaluation_task_codes.includes(task.code)" @change="toggleTaskReference(task.code, ($event.target as HTMLInputElement).checked)" />{{ task.title }}</label>
          </fieldset>
          <label>
            <span>评价材料归属<b>*</b></span>
            <AppSelect v-model="form.evidence_ownership"><option v-for="item in allowedOwnershipOptions" :key="item.value" :value="item.value">{{ item.label }}</option></AppSelect>
            <small v-if="form.evidence_ownership === 'both'">个人评价材料与小组评价材料分别记录，小组材料不替代个人材料。</small>
          </label>
          <fieldset class="criterion-link-field">
            <legend>评价材料类型<b>*</b></legend>
            <label v-for="item in allowedMaterialOptions" :key="item.value"><input v-model="form.material_types" type="checkbox" :value="item.value" />{{ item.label }}</label>
            <small v-if="form.evaluation_task_codes.length">可为不同任务分别选择相容材料；所选材料需覆盖每个关联任务。</small>
          </fieldset>
          <label>
            <span>评价方面<b>*</b></span>
            <AppSelect v-model="form.dimension">
              <option v-for="item in options.dimensions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </AppSelect>
          </label>
          <label class="span-2">
            <span>指标名称<b>*</b></span>
            <input v-model.trim="form.title" data-modal-initial-focus maxlength="160" placeholder="例如 表达方案的选择与论证" />
          </label>
          <label class="span-2">
            <span>评价对象<b>*</b></span>
            <input v-model.trim="form.evaluation_target" maxlength="300" placeholder="明确评什么作品、过程、策略或学科实践" />
          </label>
          <label>
            <span>材料来源<b>*</b></span>
            <textarea :value="form.evaluation_sources.join('\n')" rows="5" placeholder="每行一种材料，例如学生作品、回答或操作记录" @input="form.evaluation_sources = lines(inputValue($event))" />
          </label>
          <label>
            <span>具体表现<b>*</b></span>
            <textarea v-model.trim="form.expected_performance" rows="5" placeholder="写清楚实际可以看见、听见或检查到的学生表现" />
          </label>
        </section>

        <section v-else-if="step === 2" class="criterion-anchor-layout">
          <div class="evaluation-form-grid">
            <label class="span-2">
              <span>暂不评价条件<b>*</b></span>
              <textarea v-model.trim="form.skip_condition" rows="3" placeholder="说明哪些情况下缺少材料，暂时不评价该指标" />
            </label>
            <label>
              <span>可用帮助</span>
              <textarea :value="form.support_options.join('\n')" rows="4" placeholder="每行一种允许使用的工具或帮助，没有可留空" @input="form.support_options = lines(inputValue($event))" />
            </label>
            <label>
              <span>常见问题<b>*</b></span>
              <textarea :value="form.common_problems.join('\n')" rows="4" placeholder="每行一个常见问题或容易误判的情况" @input="form.common_problems = lines(inputValue($event))" />
            </label>
          </div>
          <div class="criterion-anchor-list">
            <label v-for="level in [5, 4, 3, 2, 1]" :key="level">
              <span><strong>{{ level }} 星</strong>表现说明<b>*</b></span>
              <textarea v-model.trim="form.level_descriptions[String(level)]" rows="2" :placeholder="`${level} 星时可观察到的具体表现`" />
            </label>
          </div>
        </section>

        <section v-else class="criterion-example-layout">
          <header>
            <div><strong>评分示例</strong><small>至少两个，并覆盖两个不同星级，帮助教师统一判断。</small></div>
            <button class="secondary-button mini" type="button" @click="addExample">新增示例</button>
          </header>
          <div v-for="(example, index) in form.scoring_examples" :key="index" class="criterion-example-row">
            <label>
              <span>星级<b>*</b></span>
              <AppSelect v-model.number="example.level">
                <option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level">{{ level }} 星</option>
              </AppSelect>
            </label>
            <label>
              <span>示例名称<b>*</b></span>
              <input v-model.trim="example.title" maxlength="160" placeholder="示例名称" />
            </label>
            <label class="span-2">
              <span>示例说明<b>*</b></span>
              <textarea v-model.trim="example.example_description" rows="3" placeholder="说明该示例为什么对应这一星级" />
            </label>
            <label class="span-2">
              <span>材料引用</span>
              <input v-model.trim="example.file_reference" maxlength="500" placeholder="内部材料编号或路径，可后补" />
            </label>
            <button v-if="form.scoring_examples.length > 2" type="button" class="evaluation-remove" @click="form.scoring_examples.splice(index, 1)">删除样例</button>
          </div>
          <label class="criterion-action-field">
            <span>后续教学建议<b>*</b></span>
            <textarea v-model.trim="form.follow_up_suggestion" rows="4" placeholder="该条目证据不足或表现较弱时，教师下一步采取什么反馈与学习支持" />
          </label>
        </section>
      </div>

      <footer class="modal-actions evaluation-modal-actions">
        <span>出勤、积分和在线时长不能直接作为学科评价指标。</span>
        <button class="secondary-button" type="button" :disabled="submitted" @click="requestCancel">返回评价标准</button>
        <button v-if="step > 1" class="secondary-button" type="button" @click="step -= 1">上一步</button>
        <button v-if="step < 3" class="primary-button" type="button" @click="nextStep">下一步</button>
        <button v-else class="primary-button" type="button" :disabled="submitted" @click="submit">{{ submitted ? '保存中' : '保存指标' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.evaluation-editor-backdrop {
  z-index: 1300;
}

.criterion-editor {
  width: min(980px, 100%);
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.criterion-anchor-layout,
.criterion-example-layout,
.criterion-anchor-list {
  display: grid;
  gap: 16px;
}

.criterion-link-field {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  color: var(--muted);
  font-size: 12px;
}

.criterion-link-field legend {
  padding: 0 4px;
  color: var(--text);
  font-weight: 600;
}

.criterion-link-field label {
  display: flex;
  align-items: center;
  gap: 7px;
}

.criterion-link-field input {
  width: 18px;
  min-height: 18px;
}

.criterion-anchor-list {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.criterion-anchor-list label,
.criterion-action-field,
.criterion-example-row label {
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
}

.criterion-anchor-list label > span {
  display: flex;
  align-items: center;
  gap: 8px;
}

.criterion-anchor-list strong {
  min-width: 46px;
  color: #a16207;
}

.criterion-anchor-list b,
.criterion-action-field b,
.criterion-example-row b {
  color: var(--danger);
}

.criterion-anchor-list textarea,
.criterion-action-field textarea,
.criterion-example-row input,
.criterion-example-row select,
.criterion-example-row textarea {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff;
  color: var(--text);
  resize: vertical;
}

.criterion-example-layout > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.criterion-example-layout > header div {
  display: grid;
  gap: 4px;
}

.criterion-example-layout > header small {
  color: var(--muted);
}

.criterion-example-row {
  position: relative;
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 14px;
  background: #fbfdff;
}

.criterion-example-row .span-2 {
  grid-column: 1 / -1;
}

.criterion-example-row > .evaluation-remove {
  position: absolute;
  top: 8px;
  right: 8px;
}

@media (max-width: 640px) {
  .criterion-example-row {
    grid-template-columns: 1fr;
  }

  .criterion-example-row .span-2 {
    grid-column: auto;
  }
}
</style>
