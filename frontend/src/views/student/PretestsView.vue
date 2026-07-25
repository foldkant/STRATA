<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  getStudentPretestPaper,
  getStudentSubjectPretests,
  submitStudentPretestPaper,
  type StudentPretestPaper,
  type StudentPretestQuestion,
  type StudentSubjectPretests
} from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

type OpportunityStatus = 'observed' | 'missing' | 'device_issue'
type TargetResult = {
  learning_target_code?: string
  learning_target_name?: string
  evidence_status?: string
  estimate?: number | null
  uncertainty?: number | null
}

const route = useRoute()
const router = useRouter()
const subjectId = computed(() => Number(route.params.subjectId || 0))
const data = ref<StudentSubjectPretests | null>(null)
const paper = ref<StudentPretestPaper | null>(null)
const answers = ref<Record<string, unknown>>({})
const errors = ref<FieldErrors>({})
const notice = ref('')
const success = ref('')
const loading = ref(false)
const submitting = ref(false)
const opportunityStatus = ref<OpportunityStatus>('observed')
const taskStatuses = ref<Record<string, OpportunityStatus>>({})
const attachments = ref<Record<string, File[]>>({})
const submittedTargets = ref<TargetResult[]>([])
const idempotencyKey = ref('')
const navItems = studentNav('/student/courses')

const likertOptions = [
  { label: '1', text: '非常不同意' },
  { label: '2', text: '不同意' },
  { label: '3', text: '一般' },
  { label: '4', text: '同意' },
  { label: '5', text: '非常同意' }
]

const activeAdministrationId = computed(() => paper.value?.administration_id || null)
const questions = computed(() => paper.value?.questions || [])
const canSubmit = computed(() => paper.value?.submission_allowed === true)
const canAnswer = computed(() => canSubmit.value && opportunityStatus.value === 'observed')

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `diagnostic-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

const opportunityOptions: Array<{ value: OpportunityStatus; label: string; help: string }> = [
  { value: 'observed', label: '可以正常完成', help: '正常完成本次学习起点诊断任务。' },
  { value: 'missing', label: '所需材料缺失', help: '本次材料不完整，系统不会据此判定为低水平。' },
  { value: 'device_issue', label: '设备或网络问题', help: '设备条件影响完成，系统不会把缺失作答记为 0 分。' }
]

function optionLabel(option: string | { label?: string; text?: string }, index: number) {
  if (typeof option === 'string') return String.fromCharCode(65 + index)
  return option.label || String.fromCharCode(65 + index)
}

function optionText(option: string | { label?: string; text?: string }) {
  return typeof option === 'string' ? option : option.text || option.label || ''
}

function optionValue(option: string | { label?: string; text?: string }, index: number) {
  if (typeof option === 'string') return option
  return option.label || String(index + 1)
}

function questionOptions(question: StudentPretestQuestion) {
  if (question.question_type === 'scale') return question.options.length ? question.options : likertOptions
  return question.options.length ? question.options : []
}

function isMaterialTask(question: StudentPretestQuestion) {
  return ['performance', 'operation', 'short_project'].includes(question.question_type)
}

function taskAttachments(question: StudentPretestQuestion) {
  return attachments.value[String(question.id)] || []
}

function attachmentAccept(question: StudentPretestQuestion) {
  return question.attachment_policy.allowed_extensions.map((item) => `.${item}`).join(',')
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function setAttachments(question: StudentPretestQuestion, event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  const policy = question.attachment_policy
  const key = String(question.id)
  const nextErrors = { ...errors.value }
  delete nextErrors[key]
  if (files.length > policy.max_files) {
    nextErrors[key] = [`每项任务最多上传 ${policy.max_files} 个附件。`]
  } else {
    const allowed = new Set(policy.allowed_extensions.map((item) => item.toLowerCase()))
    const invalid = files.find((file) => {
      const extension = file.name.split('.').pop()?.toLowerCase() || ''
      return !allowed.has(extension) || file.size <= 0 || file.size > policy.max_file_mb * 1024 * 1024
    })
    if (invalid) {
      nextErrors[key] = [`附件“${invalid.name}”的格式或大小不符合要求。`]
    } else {
      attachments.value = { ...attachments.value, [key]: files }
    }
  }
  errors.value = nextErrors
  input.value = ''
}

function removeAttachment(question: StudentPretestQuestion, index: number) {
  const key = String(question.id)
  attachments.value = {
    ...attachments.value,
    [key]: taskAttachments(question).filter((_, fileIndex) => fileIndex !== index)
  }
}

function isChecked(question: StudentPretestQuestion, value: string) {
  const current = answers.value[String(question.id)]
  return Array.isArray(current) && current.map(String).includes(value)
}

function answerText(question: StudentPretestQuestion) {
  const current = answers.value[String(question.id)]
  return typeof current === 'string' ? current : ''
}

function setTextAnswer(question: StudentPretestQuestion, value: string) {
  answers.value = { ...answers.value, [String(question.id)]: value }
}

function toggleMultiple(question: StudentPretestQuestion, value: string, checked: boolean) {
  const key = String(question.id)
  const current = Array.isArray(answers.value[key]) ? answers.value[key].map(String) : []
  if (checked && !current.includes(value)) {
    answers.value = { ...answers.value, [key]: [...current, value] }
    return
  }
  answers.value = { ...answers.value, [key]: current.filter((item) => item !== value) }
}

function fieldError(questionId: number) {
  return errors.value[String(questionId)]?.[0] || ''
}

function canAnswerTask(question: StudentPretestQuestion) {
  return canAnswer.value && (taskStatuses.value[String(question.id)] || 'observed') === 'observed'
}

function localValidate() {
  if (!canAnswer.value) {
    errors.value = {}
    return true
  }
  const nextErrors: FieldErrors = {}
  questions.value.forEach((question) => {
    if (!canAnswerTask(question)) return
    const value = answers.value[String(question.id)]
    const empty = (
      (value === undefined || value === '' || (Array.isArray(value) && value.length === 0))
      && taskAttachments(question).length === 0
    )
    if (question.is_required && empty) {
      nextErrors[String(question.id)] = ['该题必答。']
    }
  })
  errors.value = nextErrors
  return Object.keys(nextErrors).length === 0
}

async function loadPaper(id: number) {
  paper.value = null
  answers.value = {}
  taskStatuses.value = {}
  attachments.value = {}
  opportunityStatus.value = 'observed'
  submittedTargets.value = []
  errors.value = {}
  notice.value = ''
  idempotencyKey.value = newIdempotencyKey()
  try {
    paper.value = await getStudentPretestPaper(id)
    taskStatuses.value = Object.fromEntries(
      (paper.value.questions || []).map((question) => [String(question.id), 'observed' as OpportunityStatus])
    )
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习起点诊断任务加载失败。'
  }
}

async function loadPage() {
  loading.value = true
  notice.value = ''
  success.value = ''
  try {
    data.value = await getStudentSubjectPretests(subjectId.value)
    const firstMissingId = data.value.pretest_status.missing[0]?.administration_id
    const fallbackId = data.value.papers[0]?.administration_id
    if (firstMissingId || fallbackId) {
      await loadPaper(firstMissingId || fallbackId)
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习起点诊断加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitPaper() {
  if (submitting.value || !paper.value?.published_version || !localValidate()) return
  submitting.value = true
  notice.value = ''
  success.value = ''
  try {
    const result = await submitStudentPretestPaper(
      paper.value.administration_id,
      paper.value.published_version,
      answers.value,
      opportunityStatus.value,
      taskStatuses.value,
      Object.fromEntries(
        Object.entries(attachments.value).filter(([questionId]) => (
          opportunityStatus.value === 'observed'
          && (taskStatuses.value[questionId] || 'observed') === 'observed'
        ))
      ),
      idempotencyKey.value
    )
    const resultTargets = result.target_results as TargetResult[]
    const resultMessage = canAnswer.value
      ? '学习起点诊断材料已提交。主观任务将在教师复核后形成学习目标层面的判断。'
      : '情况已记录。本次不会按 0 分处理，也不会据此作出低水平判断。'
    await loadPage()
    submittedTargets.value = resultTargets
    success.value = resultMessage
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = '学习起点诊断材料提交失败。'
    }
  } finally {
    submitting.value = false
  }
}

onMounted(loadPage)
</script>

<template>
  <StudentShell
    :title="data?.subject.name ? `${data.subject.name}学习起点诊断（前测）` : '学习起点诊断（前测）'"
    subtitle="了解各学习目标的起始情况，为后续学习支持与任务安排提供依据"
    :nav-items="navItems"
  >
    <template #actions>
      <button class="student-ghost-button" type="button" @click="router.back()">返回</button>
    </template>

    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <NoticeLine v-if="success" :message="success" tone="success" floating @dismiss="success = ''" />
    <section v-if="submittedTargets.length" class="student-panel diagnostic-result" aria-live="polite">
      <header>
        <h2>学习目标材料状态</h2>
        <p>这里只呈现材料是否可用于判断；等待教师评价的任务不会提前生成水平结论。</p>
      </header>
      <div>
        <article v-for="target in submittedTargets" :key="target.learning_target_code || target.learning_target_name">
          <strong>{{ target.learning_target_code }}{{ target.learning_target_name ? ` · ${target.learning_target_name}` : '' }}</strong>
          <span>{{ target.evidence_status === 'available' ? '材料可用' : target.evidence_status === 'pending_review' ? '等待教师评价' : target.evidence_status === 'not_observed' ? '未形成观察' : '材料不足' }}</span>
        </article>
      </div>
    </section>
    <section v-if="loading || !data" class="student-panel">
      <p class="empty">正在加载学习起点诊断</p>
    </section>

    <section v-else class="student-pretest-layout">
      <aside class="student-panel student-pretest-side">
        <header>
          <h2>{{ data.subject.name }}</h2>
          <p v-if="data.pretest_status.status === 'completed'">当前实施批次的学习起点诊断已完成。</p>
          <p v-else-if="data.pretest_status.status === 'action_required'">请完成当前已经开放的诊断任务。</p>
          <p v-else-if="data.pretest_status.status === 'scheduled'">已有诊断实施安排，当前尚未开放。</p>
          <p v-else-if="data.pretest_status.status === 'exempt'">当前实施批次无需提交，且不会据此形成低水平判断。</p>
          <p v-else-if="data.pretest_status.assigned">当前没有需要处理的诊断任务。</p>
          <p v-else>当前学科暂无学习起点诊断实施安排。</p>
        </header>
        <button
          v-for="item in data.papers"
          :key="item.administration_id"
          type="button"
          :class="{ active: activeAdministrationId === item.administration_id }"
          @click="loadPaper(item.administration_id)"
        >
          <span>{{ item.purpose_label || item.kind_label }}</span>
          <strong>{{ item.title }}</strong>
          <small v-if="item.availability_status === 'open'">{{ item.question_count || 0 }} 项任务 · v{{ item.version }} · {{ item.batch_code }}</small>
          <small v-else>{{ item.availability_status === 'scheduled' ? '尚未开放' : '已经关闭' }} · {{ item.batch_code }}</small>
        </button>
      </aside>

      <article class="student-panel student-pretest-paper">
        <template v-if="paper">
          <header>
            <span>{{ paper.purpose_label || paper.kind_label }}</span>
            <h2>{{ paper.title }}</h2>
            <p>{{ paper.introduction || '请按实际情况完成。诊断结果用于了解学习起点，不依据一次诊断结果对学生作固定判断。' }}</p>
            <small>实施批次：{{ paper.batch_code }}<template v-if="paper.version"> · 诊断版本 v{{ paper.version }}</template></small>
          </header>

          <p v-if="!canSubmit" class="diagnostic-exception-note" role="status">
            {{ paper.opportunity_status === 'not_offered' ? '本班级未获得本次评价机会，无需提交；该情况不会记为低水平。' : paper.availability_status === 'scheduled' ? '本批次尚未开放，请在开放时间内完成。' : '本批次已经关闭，当前不能继续提交。' }}
          </p>

          <section v-if="canSubmit" class="diagnostic-opportunity" aria-labelledby="opportunity-title">
            <header>
              <strong id="opportunity-title">本次完成条件</strong>
              <small>如遇材料、设备或实践机会问题，请如实记录；这些情况不会被视为低水平。</small>
            </header>
            <div>
              <label v-for="option in opportunityOptions" :key="option.value" :class="{ active: opportunityStatus === option.value }">
                <input v-model="opportunityStatus" type="radio" name="opportunity-status" :value="option.value" />
                <span><strong>{{ option.label }}</strong><small>{{ option.help }}</small></span>
              </label>
            </div>
          </section>

          <p v-if="canSubmit && !canAnswer" class="diagnostic-exception-note" role="status">
            你可以直接提交本次情况，无需填写下列任务。教师将根据后续获得的有效材料再作判断。
          </p>

          <div class="student-question-list" :class="{ disabled: !canAnswer }">
            <section v-for="(question, index) in questions" :key="question.id" class="student-question-card">
              <header>
                <span>第 {{ index + 1 }} 项</span>
                <small>{{ question.question_type_label }}{{ question.is_required ? ' · 必答' : '' }}</small>
              </header>
              <h3>{{ question.stem }}</h3>
              <div v-if="question.learning_target_code || question.learning_target_name" class="diagnostic-target">
                <strong>对应学习目标</strong>
                <span>{{ question.learning_target_code }}{{ question.learning_target_name ? ` · ${question.learning_target_name}` : '' }}</span>
              </div>
              <label v-if="canAnswer" class="diagnostic-task-status">
                <span>本项材料状态</span>
                <AppSelect v-model="taskStatuses[String(question.id)]">
                  <option value="observed">可以正常完成</option>
                  <option value="missing">所需材料缺失</option>
                  <option value="device_issue">设备或网络问题</option>
                </AppSelect>
                <small v-if="!canAnswerTask(question)">本项不会进入得分分母，也不会按低水平处理。</small>
              </label>
              <p v-if="question.dimension">观察维度：{{ question.dimension }}</p>
              <ul v-if="question.material_requirements.length" class="diagnostic-materials">
                <li v-for="item in question.material_requirements" :key="item">{{ item }}</li>
              </ul>

              <div v-if="question.question_type === 'single'" class="student-option-list">
                <label v-for="(option, optionIndex) in questionOptions(question)" :key="optionValue(option, optionIndex)">
                  <input
                    v-model="answers[String(question.id)]"
                    type="radio"
                    :name="`question-${question.id}`"
                    :value="optionValue(option, optionIndex)"
                    :disabled="!canAnswerTask(question)"
                  />
                  <span>{{ optionLabel(option, optionIndex) }}. {{ optionText(option) }}</span>
                </label>
              </div>

              <div v-else-if="question.question_type === 'multiple'" class="student-option-list">
                <label v-for="(option, optionIndex) in questionOptions(question)" :key="optionValue(option, optionIndex)">
                  <input
                    type="checkbox"
                    :checked="isChecked(question, optionValue(option, optionIndex))"
                    :disabled="!canAnswerTask(question)"
                    @change="toggleMultiple(question, optionValue(option, optionIndex), ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ optionLabel(option, optionIndex) }}. {{ optionText(option) }}</span>
                </label>
              </div>

              <div v-else-if="question.question_type === 'scale'" class="student-scale-list">
                <label v-for="option in likertOptions" :key="option.label">
                  <input v-model="answers[String(question.id)]" type="radio" :name="`question-${question.id}`" :value="option.label" :disabled="!canAnswerTask(question)" />
                  <span>{{ option.text }}</span>
                </label>
              </div>

              <label v-else class="student-answer-box">
                <span>{{ ['performance', 'operation', 'short_project'].includes(question.question_type) ? '完成过程、结果与材料说明' : '我的回答' }}</span>
                <textarea
                  :value="answerText(question)"
                  :disabled="!canAnswerTask(question)"
                  :rows="['performance', 'operation', 'short_project'].includes(question.question_type) ? 7 : 4"
                  :placeholder="['performance', 'operation', 'short_project'].includes(question.question_type) ? '请说明完成过程、关键操作、结果以及相关作品或材料的位置' : '请输入你的回答'"
                  @input="setTextAnswer(question, ($event.target as HTMLTextAreaElement).value)"
                ></textarea>
              </label>

              <section
                v-if="isMaterialTask(question) && question.attachment_policy.enabled"
                class="diagnostic-attachments"
                :aria-labelledby="`attachment-title-${question.id}`"
              >
                <header>
                  <div>
                    <strong :id="`attachment-title-${question.id}`">作品与操作材料</strong>
                    <small>
                      最多 {{ question.attachment_policy.max_files }} 个，单个不超过
                      {{ question.attachment_policy.max_file_mb }} MB；允许
                      {{ question.attachment_policy.allowed_extensions.join('、').toUpperCase() }}
                    </small>
                  </div>
                  <label class="diagnostic-file-button" :class="{ disabled: !canAnswerTask(question) }">
                    <span>选择附件</span>
                    <input
                      type="file"
                      multiple
                      :accept="attachmentAccept(question)"
                      :disabled="!canAnswerTask(question)"
                      :aria-describedby="`attachment-help-${question.id}`"
                      @change="setAttachments(question, $event)"
                    />
                  </label>
                </header>
                <p :id="`attachment-help-${question.id}`">
                  可上传截图、文档、数据表或演示文稿。附件和上方过程说明会作为同一项学习材料提交。
                </p>
                <ul v-if="taskAttachments(question).length">
                  <li v-for="(file, fileIndex) in taskAttachments(question)" :key="`${file.name}-${file.size}-${fileIndex}`">
                    <span><strong>{{ file.name }}</strong><small>{{ formatFileSize(file.size) }}</small></span>
                    <button type="button" :disabled="!canAnswerTask(question)" @click="removeAttachment(question, fileIndex)">移除</button>
                  </li>
                </ul>
                <small v-else class="diagnostic-attachment-empty">尚未选择附件；也可以只提交充分的过程说明。</small>
              </section>

              <small v-if="fieldError(question.id)" class="field-error">{{ fieldError(question.id) }}</small>
            </section>
          </div>

          <footer class="student-pretest-actions">
            <button class="student-ghost-button" type="button" @click="router.push('/student/courses')">稍后返回课程</button>
            <button class="student-primary-action" type="button" :disabled="submitting || !questions.length || !canSubmit" @click="submitPaper">
              {{ canAnswer ? '提交诊断材料' : '提交情况记录' }}
            </button>
          </footer>
        </template>
        <p v-else class="empty">暂无可完成的学习起点诊断。</p>
      </article>
    </section>
  </StudentShell>
</template>

<style scoped>
.diagnostic-opportunity,
.diagnostic-opportunity > header,
.diagnostic-opportunity > div,
.diagnostic-opportunity label,
.diagnostic-opportunity label span {
  display: grid;
}

.diagnostic-result,
.diagnostic-result > header,
.diagnostic-result > div,
.diagnostic-result article {
  display: grid;
  gap: 8px;
}

.diagnostic-result > header h2,
.diagnostic-result > header p {
  margin: 0;
}

.diagnostic-result > header p {
  color: #475569;
}

.diagnostic-result > div {
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
}

.diagnostic-result article {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  padding: 10px;
}

.diagnostic-result article span {
  border-radius: 999px;
  background: #eef2ff;
  color: #3730a3;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 700;
}

.diagnostic-opportunity {
  gap: 12px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
  padding: 14px;
}

.diagnostic-opportunity > header {
  gap: 4px;
}

.diagnostic-opportunity > header small,
.diagnostic-opportunity label small {
  color: #475569;
  line-height: 1.45;
}

.diagnostic-opportunity > div {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.diagnostic-opportunity label {
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 9px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #fff;
  padding: 10px;
  cursor: pointer;
}

.diagnostic-opportunity label.active {
  border-color: #2563eb;
  box-shadow: 0 0 0 1px #2563eb;
}

.diagnostic-opportunity label span {
  gap: 3px;
}

.diagnostic-opportunity input {
  width: 18px;
  height: 18px;
  accent-color: #2563eb;
}

.diagnostic-exception-note {
  margin: 0;
  border-left: 4px solid #d97706;
  background: #fffbeb;
  color: #78350f;
  padding: 10px 12px;
}

.student-question-list.disabled {
  opacity: 0.66;
}

.diagnostic-target {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.diagnostic-target strong {
  border-radius: 999px;
  background: #e0e7ff;
  color: #3730a3;
  padding: 3px 8px;
  font-size: 12px;
}

.diagnostic-materials {
  margin: 0;
  padding-left: 20px;
  color: #475569;
}

.diagnostic-task-status {
  display: grid;
  grid-template-columns: minmax(120px, auto) minmax(180px, 320px);
  align-items: center;
  gap: 8px 12px;
  border-top: 1px dashed #cbd5e1;
  padding-top: 10px;
}

.diagnostic-task-status > span {
  color: #334155;
  font-weight: 700;
}

.diagnostic-task-status small {
  grid-column: 1 / -1;
  color: #92400e;
}

.diagnostic-attachments {
  display: grid;
  gap: 10px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px;
}

.diagnostic-attachments > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.diagnostic-attachments > header > div,
.diagnostic-attachments li span {
  display: grid;
  gap: 3px;
}

.diagnostic-attachments small,
.diagnostic-attachments > p {
  color: #475569;
  line-height: 1.5;
}

.diagnostic-attachments > p {
  margin: 0;
}

.diagnostic-file-button {
  position: relative;
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  border: 1px solid #2563eb;
  border-radius: 8px;
  background: #fff;
  color: #1d4ed8;
  padding: 0 14px;
  cursor: pointer;
  font-weight: 700;
}

.diagnostic-file-button:focus-within {
  outline: 3px solid rgba(37, 99, 235, 0.3);
  outline-offset: 2px;
}

.diagnostic-file-button.disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.diagnostic-file-button input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.diagnostic-attachments ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.diagnostic-attachments li {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px dashed #cbd5e1;
  padding-top: 8px;
}

.diagnostic-attachments li span,
.diagnostic-attachments li strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.diagnostic-attachments li button {
  min-height: 44px;
  border: 0;
  background: transparent;
  color: #b91c1c;
  padding: 0 10px;
  cursor: pointer;
  font-weight: 700;
}

.diagnostic-attachments li button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.diagnostic-attachment-empty {
  border-top: 1px dashed #cbd5e1;
  padding-top: 8px;
}

@media (max-width: 760px) {
  .diagnostic-opportunity > div {
    grid-template-columns: 1fr;
  }
  .diagnostic-task-status {
    grid-template-columns: 1fr;
  }
  .diagnostic-attachments > header {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
