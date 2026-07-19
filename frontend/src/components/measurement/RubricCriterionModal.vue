<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import type { MeasurementOptions, RubricCriterion } from '@/api/measurement'

const props = defineProps<{
  criterion: RubricCriterion | null
  options: MeasurementOptions
}>()

const emit = defineEmits<{
  cancel: []
  save: [criterion: RubricCriterion]
}>()

const step = ref(1)
const error = ref('')

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function emptyCriterion(): RubricCriterion {
  return {
    code: '',
    module: 'D',
    title: '',
    evaluation_object: '',
    evidence_sources: [],
    observable_evidence: '',
    not_assessed_condition: '',
    allowed_supports: [],
    counter_examples: [],
    anchors: { '1': '', '2': '', '3': '', '4': '', '5': '' },
    anchor_examples: [
      { level: 2, title: '', evidence_summary: '', artifact_reference: '' },
      { level: 4, title: '', evidence_summary: '', artifact_reference: '' }
    ],
    next_formative_action: ''
  }
}

const form = reactive<RubricCriterion>(cloneJson(props.criterion || emptyCriterion()))
const title = computed(() => props.criterion ? '编辑量规条目' : '新增量规条目')

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLTextAreaElement).value
}

function addExample() {
  form.anchor_examples.push({ level: 3, title: '', evidence_summary: '', artifact_reference: '' })
}

function validateCurrentStep() {
  error.value = ''
  if (step.value === 1) {
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(form.code.trim())) error.value = '条目代码必须以字母开头，只能包含字母、数字、下划线或连字符。'
    else if (form.title.trim().length < 2) error.value = '请填写条目名称。'
    else if (form.evaluation_object.trim().length < 4) error.value = '请明确评价对象。'
    else if (!form.evidence_sources.length) error.value = '至少填写一种证据来源。'
    else if (form.observable_evidence.trim().length < 8) error.value = '可观察证据至少 8 个字符。'
  } else if (step.value === 2) {
    if (form.not_assessed_condition.trim().length < 8) error.value = '请明确何时记录 NOT_ASSESSED。'
    else if (!form.counter_examples.length) error.value = '至少填写一个反例。'
    else if (Object.values(form.anchors).some((item) => item.trim().length < 8)) error.value = '1-5 星都必须填写完整、可观察的文字锚点。'
    else if (new Set(Object.values(form.anchors).map((item) => item.trim())).size !== 5) error.value = '五个星级锚点必须各不相同。'
  } else {
    if (form.anchor_examples.length < 2) error.value = '至少需要两份锚定样例。'
    else if (form.anchor_examples.some((item) => !item.title.trim() || item.evidence_summary.trim().length < 8)) error.value = '每份锚定样例都要填写名称和证据说明。'
    else if (new Set(form.anchor_examples.map((item) => Number(item.level))).size < 2) error.value = '锚定样例至少覆盖两个星级。'
    else if (form.next_formative_action.trim().length < 8) error.value = '请填写下一步形成性行动。'
  }
  return !error.value
}

function nextStep() {
  if (!validateCurrentStep()) return
  step.value = Math.min(3, step.value + 1)
}

function submit() {
  if (!validateCurrentStep()) return
  emit('save', {
    ...cloneJson(form),
    code: form.code.trim(),
    title: form.title.trim(),
    evaluation_object: form.evaluation_object.trim(),
    observable_evidence: form.observable_evidence.trim(),
    not_assessed_condition: form.not_assessed_condition.trim(),
    anchors: Object.fromEntries(Object.entries(form.anchors).map(([key, value]) => [key, value.trim()])),
    anchor_examples: form.anchor_examples.map((item) => ({
      level: Number(item.level),
      title: item.title.trim(),
      evidence_summary: item.evidence_summary.trim(),
      artifact_reference: item.artifact_reference.trim()
    })),
    next_formative_action: form.next_formative_action.trim()
  })
}
</script>

<template>
  <div class="modal-backdrop">
    <section class="entity-modal compact-modal measurement-editor criterion-editor" role="dialog" aria-modal="true" aria-labelledby="criterion-editor-title">
      <header class="modal-header">
        <div>
          <h2 id="criterion-editor-title">{{ title }}</h2>
          <p>每个条目独立保存可观察证据、NOT_ASSESSED 条件和五级锚点。</p>
        </div>
        <button class="icon-button" type="button" aria-label="返回量规" @click="emit('cancel')">×</button>
      </header>

      <nav class="measurement-stepper" aria-label="量规条目编辑步骤">
        <button type="button" :class="{ active: step === 1 }" @click="step = 1"><span>1</span>评价证据</button>
        <button type="button" :class="{ active: step === 2 }" @click="step = 2"><span>2</span>星级锚点</button>
        <button type="button" :class="{ active: step === 3 }" @click="step = 3"><span>3</span>锚定样例</button>
      </nav>

      <div class="measurement-editor-body">
        <p v-if="error" class="measurement-inline-error" role="alert">{{ error }}</p>

        <section v-if="step === 1" class="measurement-form-grid">
          <label>
            <span>条目代码<b>*</b></span>
            <input v-model.trim="form.code" maxlength="32" placeholder="例如 D1" />
          </label>
          <label>
            <span>量规模块<b>*</b></span>
            <select v-model="form.module">
              <option v-for="item in options.rubric_modules" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="span-2">
            <span>条目名称<b>*</b></span>
            <input v-model.trim="form.title" maxlength="160" placeholder="例如 表达方案的选择与论证" />
          </label>
          <label class="span-2">
            <span>评价对象<b>*</b></span>
            <input v-model.trim="form.evaluation_object" maxlength="300" placeholder="明确评什么作品、过程、策略或学科实践" />
          </label>
          <label>
            <span>证据来源<b>*</b></span>
            <textarea :value="form.evidence_sources.join('\n')" rows="5" placeholder="每行一种证据来源" @input="form.evidence_sources = lines(inputValue($event))" />
          </label>
          <label>
            <span>可观察证据<b>*</b></span>
            <textarea v-model.trim="form.observable_evidence" rows="5" placeholder="写清楚实际可以看见、听见或检查到的证据" />
          </label>
        </section>

        <section v-else-if="step === 2" class="criterion-anchor-layout">
          <div class="measurement-form-grid">
            <label class="span-2">
              <span>不可观察条件<b>*</b></span>
              <textarea v-model.trim="form.not_assessed_condition" rows="3" placeholder="说明何时记录 NOT_ASSESSED，而不是给 0 分或 1 星" />
            </label>
            <label>
              <span>允许支持</span>
              <textarea :value="form.allowed_supports.join('\n')" rows="4" placeholder="每行一种允许支持；没有可留空" @input="form.allowed_supports = lines(inputValue($event))" />
            </label>
            <label>
              <span>反例<b>*</b></span>
              <textarea :value="form.counter_examples.join('\n')" rows="4" placeholder="每行一个容易误判的反例" @input="form.counter_examples = lines(inputValue($event))" />
            </label>
          </div>
          <div class="criterion-anchor-list">
            <label v-for="level in [5, 4, 3, 2, 1]" :key="level">
              <span><strong>{{ level }} 星</strong>完整文字锚点<b>*</b></span>
              <textarea v-model.trim="form.anchors[String(level)]" rows="2" :placeholder="`${level} 星时可观察到的具体表现`" />
            </label>
          </div>
        </section>

        <section v-else class="criterion-example-layout">
          <header>
            <div><strong>锚定样例</strong><small>至少两份，并覆盖两个不同星级。样例可先登记引用，后续再进入共同锚测。</small></div>
            <button class="secondary-button mini" type="button" @click="addExample">新增样例</button>
          </header>
          <div v-for="(example, index) in form.anchor_examples" :key="index" class="criterion-example-row">
            <label>
              <span>星级<b>*</b></span>
              <select v-model.number="example.level">
                <option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level">{{ level }} 星</option>
              </select>
            </label>
            <label>
              <span>样例名称<b>*</b></span>
              <input v-model.trim="example.title" maxlength="160" placeholder="样例名称" />
            </label>
            <label class="span-2">
              <span>证据说明<b>*</b></span>
              <textarea v-model.trim="example.evidence_summary" rows="3" placeholder="说明该样例为什么对应这一星级" />
            </label>
            <label class="span-2">
              <span>材料引用</span>
              <input v-model.trim="example.artifact_reference" maxlength="500" placeholder="内部材料编号或路径，可后补" />
            </label>
            <button v-if="form.anchor_examples.length > 2" type="button" class="measurement-remove" @click="form.anchor_examples.splice(index, 1)">删除样例</button>
          </div>
          <label class="criterion-action-field">
            <span>下一步形成性行动<b>*</b></span>
            <textarea v-model.trim="form.next_formative_action" rows="4" placeholder="该条目证据不足或表现较弱时，教师下一步采取什么反馈与学习支持" />
          </label>
        </section>
      </div>

      <footer class="modal-actions measurement-modal-actions">
        <span>出勤、按时率、完成率、积分、在线时长和服从性不能进入量规。</span>
        <button class="secondary-button" type="button" @click="emit('cancel')">返回量规</button>
        <button v-if="step > 1" class="secondary-button" type="button" @click="step -= 1">上一步</button>
        <button v-if="step < 3" class="primary-button" type="button" @click="nextStep">下一步</button>
        <button v-else class="primary-button" type="button" @click="submit">保存条目</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
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

.criterion-example-row > .measurement-remove {
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
