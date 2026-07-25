<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  ClassroomGroupCollaborationPayload,
  ClassroomGroupCollaborationRow,
  ClassroomGroupRow,
  GroupingCandidate,
  GroupingCandidateAssignment,
  GroupingCandidateRun,
  GroupingDecisionPayload,
  GroupingDecisionPoint,
  GroupingPlanVersion,
  GroupingRole
} from '@/api/teacher'
import OnlyOfficeEditor from '@/components/OnlyOfficeEditor.vue'
import { vModalFocus } from '@/directives/modalFocus'

type GroupingStrategyOption = {
  value: string
  label: string
  description: string
}

type GroupingStudentOption = {
  student_id: number
  username: string
  display_name: string
  student_no: string
}

const props = defineProps<{
  open: boolean
  loading: boolean
  sessionTitle: string
  classLabel: string
  statusMessage: string
  draftSaved: boolean
  collaboration: ClassroomGroupCollaborationRow | null
  strategyOptions: readonly GroupingStrategyOption[]
  students: GroupingStudentOption[]
  decision: GroupingDecisionPoint | null
  groupingRun: GroupingCandidateRun | null
  selectedCandidate: GroupingCandidate | null
  plan: GroupingPlanVersion | null
  fallbackMessage: string
  collaborationStatusText: string
  groups: ClassroomGroupRow[]
}>()

const form = defineModel<ClassroomGroupCollaborationPayload>('form', { required: true })
const decisionForm = defineModel<GroupingDecisionPayload>('decisionForm', { required: true })
const candidateKey = defineModel<string>('candidateKey', { required: true })
const groupingDraft = defineModel<GroupingCandidateAssignment[]>('groupingDraft', { required: true })
const groupingLocks = defineModel<Record<number, boolean>>('groupingLocks', { required: true })
const groupingNote = defineModel<string>('groupingNote', { required: true })
const activeDocument = defineModel<ClassroomGroupRow | null>('activeDocument', { required: true })

const emit = defineEmits<{
  close: []
  saveDraft: []
  saveDecision: []
  generateCandidates: []
  confirmReview: []
  activate: []
  notifyStudents: []
  restartWorkflow: []
  closeCollaboration: []
  selectCandidate: [key: string]
  dragStart: [studentId: number]
  dragEnd: []
  drop: [groupNo: number]
  setStudentGroup: [studentId: number, event: Event]
  refresh: []
}>()

const separationLeft = ref<number | null>(null)
const separationRight = ref<number | null>(null)

const taskPurposeOptions = [
  { value: 'targeted_support', label: '针对性学习支持' },
  { value: 'peer_explanation', label: '同伴讲解与互助' },
  { value: 'open_problem', label: '开放性问题解决' },
  { value: 'project_learning', label: '项目学习' },
  { value: 'low_risk_baseline', label: '低风险基线活动' }
] as const

const roleOptions: Array<{ value: GroupingRole; label: string }> = [
  { value: 'coordinator', label: '协调员' },
  { value: 'recorder', label: '记录员' },
  { value: 'resource', label: '资源管理员' },
  { value: 'presenter', label: '汇报员' },
  { value: 'verifier', label: '核验员' },
  { value: 'leader', label: '组长' },
  { value: 'member', label: '组员' }
]

const opportunityOptions = computed(() => [
  { value: 'collaboration', label: '参与小组协作', disabled: false },
  { value: 'document_edit', label: '参与协作文档编辑', disabled: !form.value.allow_onlyoffice_edit },
  { value: 'file_share', label: '参与资源分享', disabled: !form.value.allow_student_upload },
  { value: 'presentation', label: '参与成果表达', disabled: false },
  { value: 'peer_explanation', label: '参与同伴讲解', disabled: false }
])

const resourceText = computed({
  get: () => decisionForm.value.resource_requirements.join('\n'),
  set: (value: string) => {
    decisionForm.value = {
      ...decisionForm.value,
      resource_requirements: value
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean)
    }
  }
})

const candidateCount = computed(() => props.groupingRun?.candidate_count ?? props.groupingRun?.candidates.length ?? 0)
const hasComparableCandidates = computed(() => candidateCount.value >= 2 && (props.groupingRun?.candidates.length || 0) >= 2)
const selectedCandidatePassed = computed(() => props.selectedCandidate?.constraint_status !== 'blocked')
const roleCountWithinGroupSize = computed(() => decisionForm.value.role_requirements.length <= Number(form.value.group_size || 0))
const decisionValid = computed(() => Boolean(
  decisionForm.value.task_purpose
    && decisionForm.value.task_stage.trim()
    && decisionForm.value.role_requirements.length
    && roleCountWithinGroupSize.value
    && decisionForm.value.resource_requirements.length
    && decisionForm.value.opportunity_requirements.required_for_every_student.length
    && decisionForm.value.stability_until
))

const workflowStep = computed(() => {
  if (!props.draftSaved) return 1
  if (!props.decision) return 2
  if (!hasComparableCandidates.value) return 3
  if (!props.plan) return 4
  if (props.plan.status === 'reviewed') return 5
  return 6
})

const workflowComplete = computed(() => Boolean(props.plan?.notified_at))
const reviewedPlanNeedsLoading = computed(() => Boolean(
  !props.plan
    && props.groupingRun?.selected_candidate_key
    && ['reviewed', 'active', 'notified', 'confirmed'].includes(props.decision?.status || '')
))

const workflowSteps = computed(() => [
  { number: 1, label: '保存合作设置', complete: props.draftSaved },
  { number: 2, label: '确定分组任务', complete: Boolean(props.decision) },
  { number: 3, label: '生成候选方案', complete: hasComparableCandidates.value },
  { number: 4, label: '教师复核方案', complete: Boolean(props.plan) },
  { number: 5, label: '启用分组方案', complete: Boolean(props.plan && props.plan.status !== 'reviewed') },
  { number: 6, label: '通知学生', complete: workflowComplete.value }
])

const purposeLabel = computed(() => (
  taskPurposeOptions.find((item) => item.value === props.decision?.task_purpose)?.label
    || props.decision?.task_purpose_label
    || '未确定'
))

const selectedRoleOptions = computed(() => roleOptions.filter((item) => decisionForm.value.role_requirements.includes(item.value)))

watch(
  () => [form.value.allow_onlyoffice_edit, form.value.allow_student_upload] as const,
  ([allowEdit, allowUpload]) => {
    const disabledValues = new Set<string>()
    if (!allowEdit) disabledValues.add('document_edit')
    if (!allowUpload) disabledValues.add('file_share')
    if (!disabledValues.size) return
    decisionForm.value = {
      ...decisionForm.value,
      opportunity_requirements: {
        ...decisionForm.value.opportunity_requirements,
        required_for_every_student: decisionForm.value.opportunity_requirements.required_for_every_student
          .filter((item) => !disabledValues.has(item))
      }
    }
  }
)

function closeModal() {
  if (!props.loading) emit('close')
}

function closeActiveDocument() {
  activeDocument.value = null
}

function toggleRole(role: GroupingRole, checked: boolean) {
  const roles = checked
    ? [...new Set([...decisionForm.value.role_requirements, role])]
    : decisionForm.value.role_requirements.filter((item) => item !== role)
  const requiredGroupRoles = decisionForm.value.opportunity_requirements.required_group_roles
    .filter((item) => roles.includes(item))
  decisionForm.value = {
    ...decisionForm.value,
    role_requirements: roles,
    opportunity_requirements: {
      ...decisionForm.value.opportunity_requirements,
      required_group_roles: requiredGroupRoles
    }
  }
}

function toggleRequiredGroupRole(role: GroupingRole, checked: boolean) {
  const current = decisionForm.value.opportunity_requirements.required_group_roles
  decisionForm.value = {
    ...decisionForm.value,
    opportunity_requirements: {
      ...decisionForm.value.opportunity_requirements,
      required_group_roles: checked
        ? [...new Set([...current, role])]
        : current.filter((item) => item !== role)
    }
  }
}

function toggleOpportunity(value: string, checked: boolean) {
  const current = decisionForm.value.opportunity_requirements.required_for_every_student
  decisionForm.value = {
    ...decisionForm.value,
    opportunity_requirements: {
      ...decisionForm.value.opportunity_requirements,
      required_for_every_student: checked
        ? [...new Set([...current, value])]
        : current.filter((item) => item !== value)
    }
  }
}

function addSeparationPair() {
  const left = Number(separationLeft.value)
  const right = Number(separationRight.value)
  if (!left || !right || left === right) return
  const pair = [Math.min(left, right), Math.max(left, right)]
  const pairs = decisionForm.value.safety_constraints.prohibited_pairs
  if (!pairs.some((item) => item[0] === pair[0] && item[1] === pair[1])) {
    decisionForm.value = {
      ...decisionForm.value,
      safety_constraints: {
        ...decisionForm.value.safety_constraints,
        prohibited_pairs: [...pairs, pair]
      }
    }
  }
  separationLeft.value = null
  separationRight.value = null
}

function removeSeparationPair(index: number) {
  decisionForm.value = {
    ...decisionForm.value,
    safety_constraints: {
      ...decisionForm.value.safety_constraints,
      prohibited_pairs: decisionForm.value.safety_constraints.prohibited_pairs.filter((_, itemIndex) => itemIndex !== index)
    }
  }
}

function studentLabel(studentId: number) {
  const student = props.students.find((item) => item.student_id === studentId)
  return student ? `${student.display_name || student.username}（${student.student_no || student.username}）` : `学生 ${studentId}`
}

function groupMembersText(group: ClassroomGroupRow) {
  return group.members.map((member) => member.display_name || member.username).join('、') || '暂无成员'
}

function groupStorageStyle(group: ClassroomGroupRow, collaboration: ClassroomGroupCollaborationRow | null) {
  const quota = Number(collaboration?.storage_quota_mb || 0) * 1024 * 1024
  const percent = quota ? Math.min(100, Math.round((group.used_storage_bytes / quota) * 100)) : 0
  return { width: `${percent}%` }
}

function formatFileSize(size: number) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function currentStudentGroup(studentId: number) {
  return groupingDraft.value.find((group) => group.members.some((member) => member.student_id === studentId))?.group_no || 1
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" role="presentation" @click.self="closeModal">
    <section
      v-modal-focus="closeModal"
      class="entity-modal group-collaboration-modal grouping-workflow-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="group-collaboration-title"
      aria-describedby="group-collaboration-description"
      :aria-busy="loading"
    >
      <header class="modal-header grouping-workflow-heading">
        <div>
          <h2 id="group-collaboration-title">课堂小组合作</h2>
          <p id="group-collaboration-description">{{ sessionTitle }} · {{ classLabel }} · 按步骤完成分组决策</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" :disabled="loading" @click="closeModal">×</button>
      </header>

      <div class="group-collaboration-body grouping-workflow-body">
        <aside class="grouping-principle-note" role="note">
          <strong>教师作出最终决定</strong>
          <span>系统不会默认自动分组。候选方案只供教师比较和调整，完成复核后仍需分别“启用方案”和“通知学生”。</span>
        </aside>
        <p v-if="statusMessage" class="grouping-workflow-status" role="status" aria-live="polite">{{ statusMessage }}</p>

        <nav class="grouping-stepper" aria-label="分组工作流程">
          <ol>
            <li
              v-for="step in workflowSteps"
              :key="step.number"
              :class="{ current: workflowStep === step.number, complete: step.complete }"
              :aria-current="workflowStep === step.number ? 'step' : undefined"
            >
              <span aria-hidden="true">{{ step.complete ? '✓' : step.number }}</span>
              <strong>{{ step.label }}</strong>
            </li>
          </ol>
        </nav>

        <p class="sr-only" aria-live="polite">当前步骤：{{ workflowSteps[workflowStep - 1]?.label }}</p>

        <section v-if="workflowStep === 1" class="workflow-panel" data-step="1" aria-labelledby="grouping-step-1-title">
          <header>
            <span>步骤 1 / 6</span>
            <h3 id="grouping-step-1-title">保存小组合作设置草稿</h3>
            <p>这些设置仅保存为草稿，不会生成、启用或通知任何分组。</p>
          </header>
          <div class="group-collaboration-settings workflow-fields">
            <label><span>每组人数</span><input v-model.number="form.group_size" type="number" min="2" max="12" required /></label>
            <label>
              <span>候选生成方式</span>
              <AppSelect v-model="form.grouping_strategy" aria-label="候选生成方式">
                <option v-for="item in strategyOptions" :key="item.value" :value="item.value" :title="item.description">{{ item.label }}</option>
              </AppSelect>
              <small>只影响候选方案，不会自动启用。</small>
            </label>
            <label><span>协作文档</span><AppSelect v-model="form.document_type" aria-label="协作文档类型"><option value="docx">Word 文档</option><option value="pptx">PPT 演示</option><option value="xlsx">Excel 表格</option></AppSelect></label>
            <label><span>小组空间</span><div class="group-storage-input"><input v-model.number="form.storage_quota_mb" type="number" min="10" max="2048" aria-label="小组空间容量" /><span>MB</span></div></label>
            <label class="group-collaboration-check"><input v-model="form.allow_onlyoffice_edit" type="checkbox" /><span>允许学生在线协作编辑</span></label>
            <label class="group-collaboration-check"><input v-model="form.allow_student_upload" type="checkbox" /><span>允许学生上传小组共享文件</span></label>
          </div>
          <div class="workflow-primary-action">
            <button class="primary-button" data-action="save-draft" type="button" :disabled="loading" @click="emit('saveDraft')">
              {{ loading ? '保存中…' : '保存合作设置草稿' }}
            </button>
          </div>
        </section>

        <section v-else-if="workflowStep === 2" class="workflow-panel" data-step="2" aria-labelledby="grouping-step-2-title">
          <header>
            <span>步骤 2 / 6</span>
            <h3 id="grouping-step-2-title">确定本次分组任务</h3>
            <p>先明确学习任务及教育约束，再生成候选方案。生成候选后，本次任务定义将不再修改。</p>
          </header>

          <div class="decision-grid">
            <label class="workflow-field">
              <span>学习任务目的</span>
              <AppSelect v-model="decisionForm.task_purpose" aria-label="学习任务目的" required>
                <option v-for="item in taskPurposeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </AppSelect>
            </label>
            <label class="workflow-field">
              <span>学习阶段</span>
              <input v-model.trim="decisionForm.task_stage" maxlength="120" placeholder="例如：项目方案形成、作品调试、成果交流" required />
            </label>
            <label class="workflow-field workflow-field-wide">
              <span>可用学习资源（每行一项）</span>
              <textarea v-model="resourceText" rows="3" maxlength="1200" placeholder="例如：项目任务单&#10;信息科技教材第 3 单元&#10;共享素材库" required></textarea>
            </label>
            <label class="workflow-field">
              <span>小组稳定期结束时间</span>
              <input v-model="decisionForm.stability_until" type="datetime-local" required />
              <small>稳定期内，已启用方案不会被新方案替换。</small>
            </label>
          </div>

          <fieldset class="decision-fieldset">
            <legend>小组角色</legend>
            <p>确定本次任务需要的角色；角色数量不能超过每组人数。</p>
            <div class="choice-grid">
              <label v-for="role in roleOptions" :key="role.value">
                <input
                  type="checkbox"
                  :checked="decisionForm.role_requirements.includes(role.value)"
                  @change="toggleRole(role.value, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ role.label }}</span>
              </label>
            </div>
            <p v-if="!roleCountWithinGroupSize" class="field-error" role="alert">角色数量不能超过每组 {{ form.group_size }} 人。</p>
          </fieldset>

          <fieldset class="decision-fieldset">
            <legend>学生安全约束</legend>
            <p>如有需要分开安排的学生，请明确记录；没有时保持为空，即表示本次已确认无此类约束。</p>
            <div v-if="students.length" class="separation-editor">
              <AppSelect v-model.number="separationLeft" aria-label="需要分开的第一名学生">
                <option v-for="student in students" :key="student.student_id" :value="student.student_id">{{ student.display_name || student.username }} · {{ student.student_no || student.username }}</option>
              </AppSelect>
              <span>与</span>
              <AppSelect v-model.number="separationRight" aria-label="需要分开的第二名学生">
                <option v-for="student in students" :key="student.student_id" :value="student.student_id">{{ student.display_name || student.username }} · {{ student.student_no || student.username }}</option>
              </AppSelect>
              <button class="secondary-button mini" type="button" :disabled="!separationLeft || !separationRight || separationLeft === separationRight" @click="addSeparationPair">添加约束</button>
            </div>
            <p v-else class="field-hint">学生名单暂未加载；可以先刷新，或确认本次无需设置学生分开约束。</p>
            <ul v-if="decisionForm.safety_constraints.prohibited_pairs.length" class="constraint-list">
              <li v-for="(pair, index) in decisionForm.safety_constraints.prohibited_pairs" :key="`${pair[0]}-${pair[1]}`">
                <span>{{ studentLabel(pair[0]) }} 与 {{ studentLabel(pair[1]) }}</span>
                <button type="button" aria-label="删除该学生分开约束" @click="removeSeparationPair(index)">删除</button>
              </li>
            </ul>
            <p v-else class="constraint-empty">当前确认：无需设置学生分开约束。</p>
          </fieldset>

          <fieldset class="decision-fieldset">
            <legend>学习机会要求</legend>
            <p>明确每组必须承担的角色，以及每名学生在本次任务中应获得的参与机会。</p>
            <strong class="fieldset-subtitle">每组必设角色</strong>
            <div class="choice-grid">
              <label v-for="role in selectedRoleOptions" :key="role.value">
                <input
                  type="checkbox"
                  :checked="decisionForm.opportunity_requirements.required_group_roles.includes(role.value)"
                  @change="toggleRequiredGroupRole(role.value, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ role.label }}</span>
              </label>
            </div>
            <strong class="fieldset-subtitle">每名学生应获得的机会</strong>
            <div class="choice-grid">
              <label v-for="item in opportunityOptions" :key="item.value" :class="{ disabled: item.disabled }">
                <input
                  type="checkbox"
                  :disabled="item.disabled"
                  :checked="decisionForm.opportunity_requirements.required_for_every_student.includes(item.value)"
                  @change="toggleOpportunity(item.value, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ item.label }}</span>
              </label>
            </div>
          </fieldset>

          <div class="workflow-primary-action">
            <button class="primary-button" data-action="save-decision" type="button" :disabled="loading || !decisionValid" @click="emit('saveDecision')">
              {{ loading ? '保存中…' : '保存本次分组任务' }}
            </button>
          </div>
        </section>

        <section v-else-if="workflowStep === 3" class="workflow-panel" data-step="3" aria-labelledby="grouping-step-3-title">
          <header>
            <span>步骤 3 / 6</span>
            <h3 id="grouping-step-3-title">生成可比较的候选方案</h3>
            <p>系统将生成至少两套候选方案供教师比较，不会默认选定或自动启用任何方案。</p>
          </header>
          <dl class="decision-summary">
            <div><dt>任务目的</dt><dd>{{ purposeLabel }}</dd></div>
            <div><dt>学习阶段</dt><dd>{{ decision?.task_stage }}</dd></div>
            <div><dt>小组角色</dt><dd>{{ decision?.role_requirements.map((role) => roleOptions.find((item) => item.value === role)?.label || role).join('、') }}</dd></div>
            <div><dt>学习资源</dt><dd>{{ decision?.resource_requirements.join('、') || '无' }}</dd></div>
            <div><dt>稳定期至</dt><dd>{{ decision?.stability_until ? new Date(decision.stability_until).toLocaleString() : '未设置' }}</dd></div>
          </dl>
          <p v-if="fallbackMessage" class="grouping-fallback-message" role="status">{{ fallbackMessage }}</p>
          <div class="workflow-primary-action">
            <button class="primary-button" data-action="generate" type="button" :disabled="loading" @click="emit('generateCandidates')">
              {{ loading ? '生成中…' : '生成至少两套候选方案' }}
            </button>
          </div>
        </section>

        <section v-else-if="workflowStep === 4" class="workflow-panel" data-step="4" aria-labelledby="grouping-step-4-title">
          <header>
            <span>步骤 4 / 6</span>
            <h3 id="grouping-step-4-title">比较、调整并完成教师复核</h3>
            <p>复核只保存教师决定，不会启用分组，也不会通知学生。</p>
          </header>
          <p class="privacy-note" role="note">候选依据仅供教师内部判断。学生端不呈现学习准备情况、系统形成的内部建议或其他个人学习依据。</p>
          <div class="grouping-candidate-workspace">
            <header class="grouping-candidate-header">
              <div><span>{{ groupingRun?.status_label }}</span><strong>{{ candidateCount }} 套候选方案</strong></div>
              <small>可使用下拉框调整小组和角色；“编辑时固定”可防止本次误移动。</small>
            </header>
            <div class="grouping-candidate-tabs" role="tablist" aria-label="分组候选方案">
              <button
                v-for="candidate in groupingRun?.candidates"
                :key="candidate.key"
                type="button"
                role="tab"
                :class="{ active: candidateKey === candidate.key, blocked: candidate.constraint_status === 'blocked' }"
                :aria-selected="candidateKey === candidate.key"
                @click="emit('selectCandidate', candidate.key)"
              >
                <strong>{{ candidate.label }}</strong>
                <span>{{ candidate.assignments.length }} 组 · 人数差 {{ candidate.fairness.group_size_gap }} · {{ candidate.constraint_status === 'blocked' ? '需重新生成' : '可复核' }}</span>
              </button>
            </div>

            <p v-if="selectedCandidate?.constraint_status === 'blocked'" class="field-error" role="alert">该候选未通过完整性检查，请选择其他候选或重新准备分组任务。</p>
            <div v-if="selectedCandidate" class="grouping-plan-editor">
              <article v-for="group in groupingDraft" :key="group.group_no" class="grouping-draft-group" @dragover.prevent @drop="emit('drop', group.group_no)">
                <header><strong>第{{ group.group_no }}组</strong><span>{{ group.members.length }} 人</span></header>
                <div class="grouping-draft-members">
                  <div
                    v-for="member in group.members"
                    :key="member.student_id"
                    class="grouping-draft-member"
                    :class="{ locked: groupingLocks[member.student_id] }"
                    :draggable="!groupingLocks[member.student_id]"
                    @dragstart="emit('dragStart', member.student_id)"
                    @dragend="emit('dragEnd')"
                  >
                    <div><strong>{{ member.display_name || member.username }}</strong><small>{{ member.student_no || member.username }}</small></div>
                    <label><span class="sr-only">调整 {{ member.display_name || member.username }} 所在小组</span><AppSelect :value="currentStudentGroup(member.student_id)" :disabled="groupingLocks[member.student_id]" @change="emit('setStudentGroup', member.student_id, $event)"><option v-for="target in groupingDraft" :key="target.group_no" :value="target.group_no">第{{ target.group_no }}组</option></AppSelect></label>
                    <label><span class="sr-only">调整 {{ member.display_name || member.username }} 的小组角色</span><AppSelect v-model="member.role"><option v-for="role in roleOptions" :key="role.value" :value="role.value">{{ role.label }}</option></AppSelect></label>
                    <label class="grouping-lock-toggle"><input v-model="groupingLocks[member.student_id]" type="checkbox" :disabled="member.locked" /><span>{{ member.locked ? '固定约束' : '编辑时固定' }}</span></label>
                  </div>
                </div>
              </article>
            </div>
          </div>

          <div class="grouping-confirm-row">
            <label><span>教师调整说明</span><input v-model="groupingNote" maxlength="500" placeholder="可选，记录本次人工调整的教育考虑" /></label>
            <button class="primary-button" data-action="confirm-review" type="button" :disabled="loading || !selectedCandidate || !selectedCandidatePassed" @click="emit('confirmReview')">
              {{ loading ? '保存中…' : reviewedPlanNeedsLoading ? '载入已复核方案状态' : '完成教师复核（不启用）' }}
            </button>
          </div>
        </section>

        <section v-else-if="workflowStep === 5" class="workflow-panel" data-step="5" aria-labelledby="grouping-step-5-title">
          <header>
            <span>步骤 5 / 6</span>
            <h3 id="grouping-step-5-title">明确启用已复核方案</h3>
            <p>方案已完成教师复核，但尚未在课堂中生效。</p>
          </header>
          <div class="activation-card">
            <strong>第 {{ plan?.plan_version }} 版分组方案</strong>
            <span>{{ plan?.assignments.length || 0 }} 个小组 · {{ plan?.assignments.reduce((sum, group) => sum + group.members.length, 0) || 0 }} 名学生</span>
            <p>启用后，课堂将切换到该方案；此操作不会自动发送学生通知。</p>
          </div>
          <div class="workflow-primary-action">
            <button class="primary-button" data-action="activate" type="button" :disabled="loading" @click="emit('activate')">
              {{ loading ? '启用中…' : '启用已复核方案' }}
            </button>
          </div>
        </section>

        <section v-else class="workflow-panel" data-step="6" aria-labelledby="grouping-step-6-title">
          <header>
            <span>步骤 6 / 6</span>
            <h3 id="grouping-step-6-title">{{ workflowComplete ? '分组流程已完成' : '通知学生查看分组' }}</h3>
            <p>{{ workflowComplete ? '方案已启用，学生通知也已发送。' : '方案已经启用；请另行发送通知，提醒学生查看小组、角色和学习任务。' }}</p>
          </header>
          <div class="activation-card" :class="{ complete: workflowComplete }">
            <strong>{{ workflowComplete ? '已通知学生' : '已启用，尚未通知' }}</strong>
            <span>学生端呈现小组、角色和学习任务，不呈现教师内部判断依据。</span>
          </div>
          <div class="workflow-primary-action">
            <button v-if="!workflowComplete" class="primary-button" data-action="notify" type="button" :disabled="loading" @click="emit('notifyStudents')">
              {{ loading ? '发送中…' : '发送分组通知' }}
            </button>
            <button v-else class="secondary-button" data-action="restart" type="button" :disabled="loading" @click="emit('restartWorkflow')">准备新的分组任务</button>
          </div>
        </section>

        <section class="group-collaboration-list" aria-labelledby="active-group-list-title">
          <header>
            <div><span>{{ collaborationStatusText }}</span><strong id="active-group-list-title">当前已启用的小组与共享空间</strong></div>
            <div class="active-group-actions">
              <button v-if="collaboration && decision && workflowStep !== 2 && !workflowComplete" class="secondary-button mini" type="button" :disabled="loading" @click="emit('restartWorkflow')">重新准备分组任务</button>
              <button class="secondary-button mini" type="button" :disabled="loading" @click="emit('refresh')">刷新</button>
              <button v-if="collaboration?.status === 'open'" class="secondary-button mini danger" type="button" :disabled="loading" @click="emit('closeCollaboration')">关闭合作</button>
            </div>
          </header>
          <div v-if="groups.length" class="group-card-grid">
            <article v-for="group in groups" :key="group.id" class="group-card">
              <header><div><span>{{ group.members.length }} 名成员</span><strong>{{ group.name }}</strong></div><button class="primary-button mini" type="button" @click="activeDocument = group">打开协作文档</button></header>
              <p>{{ groupMembersText(group) }}</p>
              <div class="group-member-chips"><span v-for="member in group.members" :key="member.id" :class="{ leader: member.role === 'leader' }">{{ member.display_name || member.username }}{{ member.role === 'leader' ? ' · 组长' : '' }}</span></div>
              <div class="group-storage-line"><div><strong>{{ group.used_storage_mb }}MB</strong><span>/ {{ collaboration?.storage_quota_mb || 0 }}MB</span></div><i><em :style="groupStorageStyle(group, collaboration)"></em></i></div>
              <div class="group-file-list"><strong>共享文件 {{ group.file_count }}</strong><a v-for="file in group.files.slice(0, 4)" :key="file.id" :href="file.attachment_url" download>{{ file.attachment_name }} · {{ formatFileSize(file.file_size) }}</a><span v-if="!group.files.length">暂无上传文件</span></div>
            </article>
          </div>
          <p v-else class="empty">尚无已启用分组。系统不会仅因保存设置而自动分组。</p>
        </section>
      </div>

      <footer class="modal-actions grouping-workflow-footer">
        <span>所有候选与调整均由教师复核；学生不查看内部判断依据。</span>
        <button class="primary-button" type="button" :disabled="loading" @click="closeModal">完成</button>
      </footer>
    </section>
  </div>

  <div v-if="activeDocument" class="modal-backdrop group-document-backdrop" role="presentation" @click.self="closeActiveDocument">
    <section v-modal-focus="closeActiveDocument" class="entity-modal group-document-modal" role="dialog" aria-modal="true" aria-labelledby="group-document-title">
      <header class="modal-header"><div><h2 id="group-document-title">{{ activeDocument.name }}协作文档</h2><p>{{ activeDocument.document.attachment_name }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="closeActiveDocument">×</button></header>
      <div class="group-document-editor"><OnlyOfficeEditor :group-id="activeDocument.id" mode="edit" /></div>
    </section>
  </div>
</template>

<style scoped>
.grouping-workflow-modal {
  width: min(1180px, calc(100vw - 32px));
  max-height: calc(100vh - 32px);
}

.grouping-workflow-heading p {
  margin-top: 4px;
}

.grouping-workflow-body {
  display: grid;
  gap: 18px;
  overflow-y: auto;
  padding: 20px;
}

.grouping-principle-note,
.privacy-note {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border: 1px solid #c5d6cc;
  border-radius: 12px;
  color: #315f50;
  background: #f4f7f4;
}

.grouping-principle-note span,
.privacy-note {
  line-height: 1.6;
}

.grouping-workflow-status {
  margin: 0;
  padding: 11px 13px;
  border: 1px solid #d6ded8;
  border-radius: 10px;
  color: #3e6a61;
  background: #f7f8f4;
}

.grouping-stepper {
  overflow-x: auto;
  padding-bottom: 2px;
}

.grouping-stepper ol {
  display: grid;
  grid-template-columns: repeat(6, minmax(132px, 1fr));
  gap: 8px;
  min-width: 820px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.grouping-stepper li {
  display: flex;
  gap: 8px;
  align-items: center;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid #d6ded8;
  border-radius: 10px;
  color: #687a73;
  background: #f7f8f4;
}

.grouping-stepper li > span {
  display: grid;
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 50%;
  color: #526a61;
  background: #e8eeea;
}

.grouping-stepper li.current {
  border-color: #78978c;
  color: #17483f;
  background: #edf4f0;
}

.grouping-stepper li.current > span {
  color: #fff;
  background: #17483f;
}

.grouping-stepper li.complete > span {
  color: #fff;
  background: #18865b;
}

.workflow-panel {
  display: grid;
  gap: 18px;
  padding: 20px;
  border: 1px solid #d6ded8;
  border-radius: 14px;
  background: #fff;
}

.workflow-panel > header > span {
  color: #17483f;
  font-size: 13px;
  font-weight: 700;
}

.workflow-panel > header h3 {
  margin: 5px 0;
  color: #263832;
  font-size: 21px;
}

.workflow-panel > header p {
  margin: 0;
  color: #687a73;
  line-height: 1.6;
}

.workflow-fields,
.decision-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.workflow-field,
.workflow-fields label {
  display: grid;
  gap: 7px;
}

.workflow-field > span,
.workflow-fields label > span,
.grouping-confirm-row label > span {
  color: #334a43;
  font-weight: 700;
}

.workflow-field input,
.workflow-field textarea,
.grouping-confirm-row input {
  width: 100%;
  min-height: 44px;
  padding: 10px 12px;
  border: 1px solid #cbd5ce;
  border-radius: 9px;
  color: #263832;
  background: #fff;
}

.workflow-field textarea {
  min-height: 96px;
  resize: vertical;
}

.workflow-field-wide {
  grid-column: 1 / -1;
}

.workflow-field small,
.workflow-fields small,
.field-hint {
  color: #687a73;
  line-height: 1.5;
}

.decision-fieldset {
  display: grid;
  gap: 12px;
  min-width: 0;
  margin: 0;
  padding: 16px;
  border: 1px solid #d6ded8;
  border-radius: 12px;
}

.decision-fieldset legend {
  padding: 0 6px;
  color: #334a43;
  font-weight: 800;
}

.decision-fieldset > p {
  margin: 0;
  color: #687a73;
  line-height: 1.55;
}

.choice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}

.choice-grid label {
  display: flex;
  gap: 8px;
  align-items: center;
  min-height: 42px;
  padding: 8px 10px;
  border: 1px solid #d6ded8;
  border-radius: 9px;
  color: #334a43;
  background: #fafbf8;
}

.choice-grid label.disabled {
  opacity: .55;
}

.choice-grid input {
  width: 18px;
  height: 18px;
}

.fieldset-subtitle {
  color: #334a43;
  font-size: 14px;
}

.separation-editor {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto minmax(180px, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.constraint-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.constraint-list li {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 9px 11px;
  border-radius: 9px;
  color: #5b3131;
  background: #fff4f2;
}

.constraint-list button {
  border: 0;
  color: #a43131;
  background: transparent;
  cursor: pointer;
}

.constraint-empty {
  padding: 9px 11px;
  border-radius: 9px;
  color: #315f4c !important;
  background: #effaf5;
}

.field-error {
  margin: 0;
  padding: 10px 12px;
  border-radius: 9px;
  color: #9f2929 !important;
  background: #fff0f0;
}

.workflow-primary-action {
  display: flex;
  justify-content: flex-end;
}

.workflow-primary-action button {
  min-height: 44px;
  min-width: 190px;
}

.decision-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.decision-summary div {
  display: grid;
  gap: 5px;
  padding: 12px;
  border-radius: 10px;
  background: #f7f8f4;
}

.decision-summary dt {
  color: #687a73;
  font-size: 13px;
}

.decision-summary dd {
  margin: 0;
  color: #334a43;
  line-height: 1.5;
}

.privacy-note {
  margin: 0;
}

.grouping-candidate-tabs button.blocked {
  border-color: #e9b5b5;
  background: #fff8f8;
}

.grouping-confirm-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: end;
}

.grouping-confirm-row label {
  display: grid;
  gap: 7px;
}

.grouping-confirm-row button {
  min-height: 44px;
}

.activation-card {
  display: grid;
  gap: 8px;
  padding: 18px;
  border: 1px solid #c5d6cc;
  border-radius: 12px;
  color: #315f50;
  background: #f4f7f4;
}

.activation-card.complete {
  border-color: #b8dfcf;
  color: #285b48;
  background: #f0faf6;
}

.activation-card strong {
  font-size: 18px;
}

.activation-card p {
  margin: 3px 0 0;
  line-height: 1.55;
}

.active-group-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.grouping-workflow-footer {
  justify-content: space-between;
}

@media (max-width: 760px) {
  .grouping-workflow-modal {
    width: calc(100vw - 16px);
    max-height: calc(100vh - 16px);
  }

  .grouping-workflow-body,
  .workflow-panel {
    padding: 14px;
  }

  .workflow-fields,
  .decision-grid,
  .decision-summary,
  .grouping-confirm-row {
    grid-template-columns: 1fr;
  }

  .separation-editor {
    grid-template-columns: 1fr;
  }

  .separation-editor > span {
    text-align: center;
  }

  .workflow-primary-action button,
  .grouping-confirm-row button {
    width: 100%;
  }

  .grouping-workflow-footer {
    align-items: stretch;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
