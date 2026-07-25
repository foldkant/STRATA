<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import type { CurriculumNode, CurriculumNodeType } from '@/api/curriculumStandards'
import {
  saveEvaluationPlan,
  type EvaluationPlanPayload,
  type EvaluationPlanRow,
  type EvaluationTask,
  type EvaluationOptions
} from '@/api/evaluation'
import CurriculumReferencePickerModal from '@/components/curriculum/CurriculumReferencePickerModal.vue'
import CurriculumReferenceTraceModal from '@/components/curriculum/CurriculumReferenceTraceModal.vue'
import { vModalFocus } from '@/directives/modalFocus'

const props = defineProps<{
  draft: EvaluationPlanRow | null
  options: EvaluationOptions
  initialCourseId?: number | null
  initialTitle?: string
  initialTargetStudents?: string
  initialContentScope?: string[]
  contextLabel?: string
  lockCourse?: boolean
}>()

const emit = defineEmits<{
  close: []
  saved: [row: EvaluationPlanRow]
}>()

const step = ref(1)
const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})
const referencePicker = ref(false)
const traceReferenceId = ref<number | null>(null)
const curriculumReferences = ref<CurriculumNode[]>(cloneJson(props.draft?.curriculum_references || []))

function requestClose() {
  if (!saving.value) emit('close')
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

const draftEvaluationTasks = cloneJson(props.draft?.evaluation_tasks || [])
const defaultTaskWeight = draftEvaluationTasks.length ? 100 / draftEvaluationTasks.length : 100

const form = reactive<EvaluationPlanPayload>({
  course: props.draft?.course?.id
    || props.options.courses.find((item) => item.id === Number(props.initialCourseId))?.id
    || props.options.courses[0]?.id
    || '',
  title: props.draft?.title || props.initialTitle?.trim() || '',
  content_version: props.draft?.content_version || '1.0',
  target_students: props.draft?.target_students || props.initialTargetStudents?.trim() || '',
  learning_goal: props.draft?.learning_goal || '',
  learning_goals: cloneJson(props.draft?.learning_goals || []).map((item) => ({
    ...item,
    curriculum_node_ids: item.curriculum_node_ids || props.draft?.curriculum_node_ids || props.draft?.curriculum_references?.map((reference) => reference.id) || []
  })),
  evaluation_basis: cloneJson(props.draft?.evaluation_basis || []),
  learning_activities: cloneJson(props.draft?.learning_activities || []),
  learning_tasks: cloneJson(props.draft?.learning_tasks || []),
  evaluation_tasks: draftEvaluationTasks.map((item) => ({
    ...item,
    component_modes: [...(item.component_modes || [])],
    weight: Number(item.weight || defaultTaskWeight)
  })),
  assessment_modes: Array.from(new Set(draftEvaluationTasks.map((item) => item.mode))),
  content_scope: [...(props.draft?.content_scope || props.initialContentScope || [])],
  thinking_requirements: [...(props.draft?.thinking_requirements || [])],
  support_options: [...(props.draft?.support_options || [])],
  scoring_rules: {
    approach: props.draft?.scoring_rules?.approach || '按评价指标分别判断',
    decision_rule: props.draft?.scoring_rules?.decision_rule || ''
  },
  follow_up_suggestion: props.draft?.follow_up_suggestion || '',
  curriculum_node_ids: [...(props.draft?.curriculum_node_ids || props.draft?.curriculum_references?.map((item) => item.id) || [])]
})

const modalTitle = computed(() => props.draft ? '编辑评价方案' : '新建评价方案')
const courseLocked = computed(() => Boolean(props.draft?.latest_version) || Boolean(props.lockCourse))
const selectedCourse = computed(() => props.options.courses.find((item) => item.id === Number(form.course)) || null)
const selectedReferenceTypes = computed(() => new Set(curriculumReferences.value.map((item) => item.node_type)))
const curriculumTypeOrder: CurriculumNodeType[] = ['core_competency', 'course_objective', 'course_content', 'academic_quality']
const atomicAssessmentOptions = computed(() => props.options.assessment_modes.filter((item) => item.value !== 'mixed'))
const derivedAssessmentModes = computed(() => Array.from(new Set(form.evaluation_tasks.map((item) => item.mode))))
const derivedAssessmentModeLabels = computed(() => derivedAssessmentModes.value.map((mode) => (
  props.options.assessment_modes.find((item) => item.value === mode)?.label || mode
)))

function curriculumTypeLabel(type: CurriculumNodeType) {
  return {
    core_competency: '核心素养',
    course_objective: '课程目标',
    course_content: '课程内容',
    academic_quality: '学业质量'
  }[type]
}

function curriculumPageLabel(reference: CurriculumNode) {
  if (!reference.source_page_start) return '原文页码未标注'
  if (!reference.source_page_end || reference.source_page_end === reference.source_page_start) return `第 ${reference.source_page_start} 页`
  return `第 ${reference.source_page_start}—${reference.source_page_end} 页`
}

function applyCurriculumReferences(references: CurriculumNode[]) {
  curriculumReferences.value = references
  form.curriculum_node_ids = references.map((item) => item.id)
  const available = new Set(form.curriculum_node_ids)
  for (const goal of form.learning_goals) {
    goal.curriculum_node_ids = goal.curriculum_node_ids.filter((id) => available.has(id))
  }
  referencePicker.value = false
}

function removeCurriculumReference(id: number) {
  curriculumReferences.value = curriculumReferences.value.filter((item) => item.id !== id)
  form.curriculum_node_ids = curriculumReferences.value.map((item) => item.id)
  for (const goal of form.learning_goals) {
    goal.curriculum_node_ids = goal.curriculum_node_ids.filter((item) => item !== id)
  }
}

watch(() => form.course, (next, previous) => {
  if (previous && next !== previous) {
    curriculumReferences.value = []
    form.curriculum_node_ids = []
    for (const goal of form.learning_goals) goal.curriculum_node_ids = []
  }
})

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLTextAreaElement).value
}

function nextCode(prefix: string, rows: Array<{ code: string }>) {
  const maximum = rows.reduce((current, row) => {
    const match = row.code.match(new RegExp(`^${prefix}(\\d+)$`, 'i'))
    return match ? Math.max(current, Number(match[1])) : current
  }, 0)
  return `${prefix}${maximum + 1}`
}

function addGoal() {
  form.learning_goals.push({
    code: nextCode('G', form.learning_goals),
    title: '',
    description: '',
    curriculum_node_ids: [...form.curriculum_node_ids]
  })
}

function addBasis() {
  form.evaluation_basis.push({ code: nextCode('B', form.evaluation_basis), goal_codes: [], description: '', source_types: [] })
}

function addActivity() {
  form.learning_activities.push({
    code: nextCode('A', form.learning_activities),
    title: '',
    goal_codes: [],
    description: ''
  })
}

function addEvaluationTask() {
  const mode: EvaluationTask['mode'] = 'project'
  form.evaluation_tasks.push({
    code: nextCode('E', form.evaluation_tasks),
    title: '',
    goal_codes: [],
    activity_codes: [],
    mode,
    component_modes: [],
    evidence_ownership: 'individual',
    material_types: ['artifact'],
    weight: 100,
    description: ''
  })
  rebalanceTaskWeights()
}

function prepareSimpleLessonDraft() {
  if (!form.learning_goals.length) {
    form.learning_goals.push({
      code: 'G1',
      title: form.learning_goal.replace(/[，。；\n].*$/, '').slice(0, 80) || '完成本环节学习任务',
      description: form.learning_goal,
      curriculum_node_ids: [...form.curriculum_node_ids]
    })
  }
  const goalCodes = form.learning_goals.map((item) => item.code)
  if (!form.learning_activities.length) {
    form.learning_activities.push({
      code: 'A1',
      title: `${props.contextLabel || form.title}学习活动`.slice(0, 160),
      goal_codes: [...goalCodes],
      description: form.content_scope[0]
        || '学生围绕本环节学习任务开展实践、交流方法并修改学习成果。'
    })
  }
  if (!form.evaluation_basis.length) {
    form.evaluation_basis.push({
      code: 'B1',
      goal_codes: [...goalCodes],
      description: '依据学生在本环节形成的作品、操作记录和个人说明，判断与学习目标对应的具体表现。',
      source_types: ['学生作品', '操作记录', '学生说明']
    })
  }
  if (!form.evaluation_tasks.length) {
    const isInformationTechnology = `${selectedCourse.value?.subject.name || ''}${selectedCourse.value?.subject.code || ''}`.includes('信息')
    const mode: EvaluationTask['mode'] = isInformationTechnology ? 'operation' : 'project'
    form.evaluation_tasks.push({
      code: 'E1',
      title: `${props.contextLabel || form.title}学习成果`.slice(0, 160),
      goal_codes: [...goalCodes],
      activity_codes: form.learning_activities.map((item) => item.code),
      mode,
      component_modes: [],
      evidence_ownership: 'individual',
      material_types: [mode === 'operation' ? 'operation' : 'artifact'],
      weight: 100,
      description: '学生完成本环节学习任务，并提交可检查的个人作品、操作记录或说明。'
    })
  }
  if (!form.content_scope.length) form.content_scope = [props.contextLabel || form.title]
  if (!form.thinking_requirements.length) form.thinking_requirements = ['understand', 'apply']
  if (form.scoring_rules.decision_rule.trim().length < 8) {
    form.scoring_rules.decision_rule = '依据学生实际形成的作品、操作记录和说明对照表现水平判断；材料不足、设备故障或未获得表现机会时暂不评价。'
  }
  if (form.follow_up_suggestion.trim().length < 8) {
    form.follow_up_suggestion = '根据学生具体表现提供针对性反馈，并安排补充说明、修改作品或迁移实践的学习机会。'
  }
}

function removeGoal(index: number) {
  const code = form.learning_goals[index]?.code
  if (!code) return
  form.evaluation_basis.forEach((item) => {
    item.goal_codes = item.goal_codes.filter((value) => value !== code)
  })
  form.learning_activities.forEach((item) => {
    item.goal_codes = item.goal_codes.filter((value) => value !== code)
  })
  form.evaluation_tasks.forEach((item) => {
    item.goal_codes = item.goal_codes.filter((value) => value !== code)
  })
  form.learning_goals.splice(index, 1)
}

function removeActivity(index: number) {
  const code = form.learning_activities[index]?.code
  if (!code) return
  form.evaluation_tasks.forEach((item) => {
    item.activity_codes = item.activity_codes.filter((value) => value !== code)
  })
  form.learning_activities.splice(index, 1)
}

function taskModeChanged(task: EvaluationTask) {
  if (task.mode !== 'mixed') task.component_modes = []
}

function rebalanceTaskWeights() {
  if (!form.evaluation_tasks.length) return
  const weight = Number((100 / form.evaluation_tasks.length).toFixed(2))
  form.evaluation_tasks.forEach((item, index) => {
    item.weight = index === form.evaluation_tasks.length - 1
      ? Number((100 - weight * (form.evaluation_tasks.length - 1)).toFixed(2))
      : weight
  })
}

function removeEvaluationTask(index: number) {
  form.evaluation_tasks.splice(index, 1)
  rebalanceTaskWeights()
}

function toggleReference<T extends string | number>(values: T[], code: T, checked: boolean) {
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
    if (!form.curriculum_node_ids.length) next.curriculum_node_ids = ['至少选择一条课程标准依据。']
  }
  if (step.value === 2) {
    if (!form.learning_goals.length) next.learning_goals = ['至少添加一条学习目标。']
    if (form.learning_goals.some((item) => !item.curriculum_node_ids.length)) next.learning_goals = ['每条学习目标都要关联课程标准依据。']
    if (!form.learning_activities.length) next.learning_activities = ['至少添加一个学习活动。']
    if (!form.evaluation_tasks.length) next.evaluation_tasks = ['至少添加一个评价任务。']
    if (form.evaluation_tasks.some((item) => item.mode === 'mixed' && new Set(item.component_modes).size < 2)) {
      next.evaluation_tasks = ['混合评价任务至少选择两种具体评价方式。']
    }
    const taskWeightTotal = form.evaluation_tasks.reduce((total, item) => total + Number(item.weight || 0), 0)
    if (form.evaluation_tasks.length && Math.abs(taskWeightTotal - 100) > 0.01) {
      next.evaluation_tasks = [`全部评价任务权重之和必须为 100%，当前为 ${taskWeightTotal.toFixed(2)}%。`]
    }
    if (!form.evaluation_basis.length) next.evaluation_basis = ['至少添加一条评价依据。']
  }
  if (step.value === 3) {
    if (!derivedAssessmentModes.value.length) next.assessment_modes = ['至少添加一个评价任务。']
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
  if (step.value === 1) prepareSimpleLessonDraft()
  step.value = Math.min(3, step.value + 1)
}

async function save() {
  if (saving.value) return
  const next: FieldErrors = {}
  if (!form.course) next.course = ['请选择课程。']
  if (form.title.trim().length < 2) next.title = ['方案名称至少 2 个字符。']
  errors.value = next
  if (Object.keys(next).length) {
    step.value = 1
    return
  }
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
        description: item.description.trim(),
        curriculum_node_ids: item.curriculum_node_ids
      })),
      evaluation_basis: form.evaluation_basis.map((item) => ({
        code: item.code.trim(),
        goal_codes: item.goal_codes,
        description: item.description.trim(),
        source_types: item.source_types
      })),
      learning_activities: form.learning_activities.map((item) => ({
        code: item.code.trim(),
        title: item.title.trim(),
        goal_codes: item.goal_codes,
        description: item.description.trim()
      })),
      learning_tasks: [],
      evaluation_tasks: form.evaluation_tasks.map((item) => ({
        ...item,
        code: item.code.trim(),
        title: item.title.trim(),
        component_modes: item.mode === 'mixed'
          ? Array.from(new Set(item.component_modes))
          : [],
        description: item.description.trim()
      })),
      assessment_modes: derivedAssessmentModes.value,
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
  <div class="modal-backdrop evaluation-editor-backdrop" @click.self="requestClose">
    <section v-modal-focus="requestClose" class="entity-modal compact-modal evaluation-editor" role="dialog" aria-modal="true" :aria-labelledby="`plan-editor-${draft?.id || 'new'}`">
      <header class="modal-header">
        <div>
          <h2 :id="`plan-editor-${draft?.id || 'new'}`">{{ modalTitle }}</h2>
          <p v-if="contextLabel">当前课时：{{ contextLabel }}</p>
          <p>建立课程标准依据、学习目标、学习活动与评价任务的对应关系，并设置评分规则</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="requestClose">×</button>
      </header>

      <nav class="evaluation-stepper" aria-label="评价方案编辑步骤">
        <button type="button" :class="{ active: step === 1 }" @click="step = 1"><span>1</span>课程内容与目标</button>
        <button type="button" :class="{ active: step === 2 }" @click="step = 2"><span>2</span>活动与评价任务</button>
        <button type="button" :class="{ active: step === 3 }" @click="step = 3"><span>3</span>材料与评分安排</button>
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
          <section class="curriculum-reference-field span-2" aria-labelledby="curriculum-reference-field-title">
            <header>
              <div>
                <strong id="curriculum-reference-field-title">课程标准依据</strong>
                <small>从超级管理员发布的课程标准中选择相关原文，作为本方案学习目标与评价设计的依据。</small>
              </div>
              <button class="secondary-button" type="button" :disabled="!selectedCourse" @click="referencePicker = true">
                {{ curriculumReferences.length ? '调整课程标准依据' : '选择课程标准依据' }}
              </button>
            </header>

            <div class="curriculum-reference-chain" aria-label="课程标准内容类型">
              <div v-for="type in curriculumTypeOrder" :key="type" :class="{ selected: selectedReferenceTypes.has(type) }">
                <span aria-hidden="true">{{ selectedReferenceTypes.has(type) ? '✓' : '—' }}</span>
                <strong>{{ curriculumTypeLabel(type) }}</strong>
              </div>
            </div>
            <p class="curriculum-reference-help">
              四类内容相互联系，不直接换算为分数。请选择与本次课程内容和评价用途相关的条目；学业质量用于提供阶段性表现参照。
            </p>

            <div v-if="curriculumReferences.length" class="selected-curriculum-references">
              <article v-for="reference in curriculumReferences" :key="reference.id">
                <div class="selected-reference-content">
                  <em>{{ curriculumTypeLabel(reference.node_type) }}</em>
                  <strong>{{ reference.code }} · {{ reference.title }}</strong>
                  <small>
                    {{ reference.standard_title || selectedCourse?.subject.name }}
                    · {{ reference.version_label || '版本待加载' }}
                    · {{ curriculumPageLabel(reference) }}
                  </small>
                </div>
                <div class="selected-reference-actions">
                  <button class="reference-trace-button" type="button" @click="traceReferenceId = reference.id">查看原文</button>
                  <button class="reference-remove-button" type="button" aria-label="移除课程标准依据" @click="removeCurriculumReference(reference.id)">移除</button>
                </div>
              </article>
            </div>
            <p v-else class="curriculum-reference-empty">
              尚未选择课程标准依据。草案可以先保存，但发布前应完成原文引用和适用范围复核。
            </p>
            <p v-if="errors.curriculum_node_ids" class="field-error" role="alert">{{ errors.curriculum_node_ids[0] }}</p>
          </section>
          <label class="span-2">
            <span>方案名称<b>*</b></span>
            <input v-model.trim="form.title" data-modal-initial-focus maxlength="160" placeholder="例如 数据表达与解释评价方案" />
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
            <div v-for="(goal, index) in form.learning_goals" :key="goal.code" class="evaluation-chain-row claim-row">
              <span class="evaluation-item-number">学习目标 {{ index + 1 }}</span>
              <input v-model.trim="goal.title" maxlength="160" aria-label="目标名称" placeholder="目标名称" />
              <textarea v-model.trim="goal.description" rows="2" aria-label="目标说明" placeholder="写清楚学生应达到的具体表现" />
              <div class="evaluation-reference-list">
                <span>对应课标依据</span>
                <label v-for="reference in curriculumReferences" :key="reference.id">
                  <input type="checkbox" :checked="goal.curriculum_node_ids.includes(reference.id)" @change="toggleReference(goal.curriculum_node_ids, reference.id, ($event.target as HTMLInputElement).checked)" />
                  {{ reference.code }} · {{ reference.title }}
                </label>
              </div>
              <button type="button" class="evaluation-remove" :aria-label="`删除学习目标 ${index + 1}`" @click="removeGoal(index)">删除</button>
            </div>
          </div>

          <div class="evaluation-chain-section">
            <header><div><strong>学习活动</strong><small>学生经历什么学习过程来达成目标</small></div><button class="secondary-button mini" type="button" @click="addActivity">新增活动</button></header>
            <p v-if="errors.learning_activities" class="field-error">{{ errors.learning_activities[0] }}</p>
            <div v-for="(activity, index) in form.learning_activities" :key="activity.code" class="evaluation-chain-row task-row">
              <span class="evaluation-item-number">学习活动 {{ index + 1 }}</span>
              <input v-model.trim="activity.title" maxlength="160" aria-label="活动名称" placeholder="学习活动名称" />
              <div class="evaluation-reference-list">
                <span>关联学习目标</span>
                <label v-for="goal in form.learning_goals" :key="goal.code">
                  <input type="checkbox" :checked="activity.goal_codes.includes(goal.code)" @change="toggleReference(activity.goal_codes, goal.code, ($event.target as HTMLInputElement).checked)" />
                  {{ goal.title || `学习目标 ${form.learning_goals.indexOf(goal) + 1}` }}
                </label>
              </div>
              <textarea v-model.trim="activity.description" rows="2" aria-label="活动说明" placeholder="说明学习过程、资源和学生参与方式" />
              <button type="button" class="evaluation-remove" :aria-label="`删除学习活动 ${index + 1}`" @click="removeActivity(index)">删除</button>
            </div>
          </div>

          <div class="evaluation-chain-section">
            <header><div><strong>评价依据</strong><small>根据哪些作品、答案或表现进行判断</small></div><button class="secondary-button mini" type="button" @click="addBasis">新增依据</button></header>
            <p v-if="errors.evaluation_basis" class="field-error">{{ errors.evaluation_basis[0] }}</p>
            <div v-for="(evidence, index) in form.evaluation_basis" :key="evidence.code" class="evaluation-chain-row evidence-row">
              <span class="evaluation-item-number">评价依据 {{ index + 1 }}</span>
              <div class="evaluation-reference-list">
                <span>关联目标</span>
                <label v-for="goal in form.learning_goals" :key="goal.code">
                  <input type="checkbox" :checked="evidence.goal_codes.includes(goal.code)" @change="toggleReference(evidence.goal_codes, goal.code, ($event.target as HTMLInputElement).checked)" />
                  {{ goal.title || `学习目标 ${form.learning_goals.indexOf(goal) + 1}` }}
                </label>
              </div>
              <textarea v-model.trim="evidence.description" rows="2" aria-label="依据说明" placeholder="说明如何据此判断学生表现" />
              <textarea :value="evidence.source_types.join('\n')" rows="2" aria-label="材料来源" placeholder="每行一种材料，例如学生作品" @input="evidence.source_types = lines(inputValue($event))" />
              <button type="button" class="evaluation-remove" :aria-label="`删除评价依据 ${index + 1}`" @click="form.evaluation_basis.splice(index, 1)">删除</button>
            </div>
          </div>

          <div class="evaluation-chain-section">
            <header><div><strong>评价任务</strong><small>通过测试、操作、项目、作品或答辩收集评价材料</small></div><button class="secondary-button mini" type="button" @click="addEvaluationTask">新增评价任务</button></header>
            <p v-if="errors.evaluation_tasks" class="field-error">{{ errors.evaluation_tasks[0] }}</p>
            <div v-for="(task, index) in form.evaluation_tasks" :key="task.code" class="evaluation-chain-row task-row evaluation-task-row">
              <span class="evaluation-item-number">评价任务 {{ index + 1 }}</span>
              <input v-model.trim="task.title" maxlength="160" aria-label="评价任务名称" placeholder="评价任务名称" />
              <div class="evaluation-reference-list">
                <span>关联学习目标</span>
                <label v-for="goal in form.learning_goals" :key="goal.code">
                  <input type="checkbox" :checked="task.goal_codes.includes(goal.code)" @change="toggleReference(task.goal_codes, goal.code, ($event.target as HTMLInputElement).checked)" />
                  {{ goal.title || `学习目标 ${form.learning_goals.indexOf(goal) + 1}` }}
                </label>
              </div>
              <div class="evaluation-reference-list">
                <span>关联学习活动</span>
                <label v-for="activity in form.learning_activities" :key="activity.code">
                  <input type="checkbox" :checked="task.activity_codes.includes(activity.code)" @change="toggleReference(task.activity_codes, activity.code, ($event.target as HTMLInputElement).checked)" />
                  {{ activity.title || `学习活动 ${form.learning_activities.indexOf(activity) + 1}` }}
                </label>
              </div>
              <label><span>评价方式</span><AppSelect v-model="task.mode" @change="taskModeChanged(task)"><option v-for="item in options.assessment_modes" :key="item.value" :value="item.value">{{ item.label }}</option></AppSelect></label>
              <fieldset v-if="task.mode === 'mixed'" class="evaluation-material-types">
                <legend>混合评价包含的具体方式<b>*</b></legend>
                <label v-for="item in atomicAssessmentOptions" :key="item.value"><input v-model="task.component_modes" type="checkbox" :value="item.value" />{{ item.label }}</label>
                <small>至少选择两种非“混合评价”的具体方式。</small>
              </fieldset>
              <label><span>材料归属</span><AppSelect v-model="task.evidence_ownership"><option v-for="item in options.evidence_ownerships" :key="item.value" :value="item.value">{{ item.label }}</option></AppSelect></label>
              <label><span>任务权重（%）</span><input v-model.number="task.weight" type="number" min="0.01" max="100" step="0.01" /></label>
              <fieldset class="evaluation-material-types"><legend>评价材料</legend><label v-for="item in options.material_types" :key="item.value"><input v-model="task.material_types" type="checkbox" :value="item.value" />{{ item.label }}</label></fieldset>
              <textarea v-model.trim="task.description" rows="2" aria-label="评价任务说明" placeholder="说明情境、产出、操作要求、答辩或测试条件" />
              <button type="button" class="evaluation-remove" @click="removeEvaluationTask(index)">删除</button>
            </div>
          </div>
        </section>

        <section v-else class="evaluation-form-grid">
          <section class="evaluation-mode-summary span-2" aria-labelledby="evaluation-mode-summary-title">
            <strong id="evaluation-mode-summary-title">本方案使用的评价方式</strong>
            <p v-if="derivedAssessmentModeLabels.length">{{ derivedAssessmentModeLabels.join('、') }}</p>
            <p v-else>尚未添加评价任务。</p>
            <small>由各评价任务的方式自动汇总，不能在方案层级另行修改。</small>
            <small v-if="errors.assessment_modes" class="field-error">{{ errors.assessment_modes[0] }}</small>
          </section>
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
        <button class="secondary-button" type="button" :disabled="saving" @click="requestClose">取消</button>
        <button v-if="step > 1" class="secondary-button" type="button" @click="step -= 1">上一步</button>
        <button v-if="step < 3" class="primary-button" type="button" :disabled="saving" @click="nextStep">下一步</button>
        <button :class="step < 3 ? 'secondary-button' : 'primary-button'" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存草案' }}</button>
      </footer>
    </section>
    <CurriculumReferencePickerModal
      v-if="referencePicker"
      :selected="curriculumReferences"
      :subject-code="selectedCourse?.subject.code"
      :subject-name="selectedCourse?.subject.name"
      :school-stage="selectedCourse?.school_stage || ''"
      @close="referencePicker = false"
      @apply="applyCurriculumReferences"
    />
    <CurriculumReferenceTraceModal
      v-if="traceReferenceId !== null"
      :node-id="traceReferenceId"
      @close="traceReferenceId = null"
    />
  </div>
</template>

<style>
.evaluation-editor-backdrop {
  z-index: 1300;
}

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

.evaluation-mode-summary {
  display: grid;
  gap: 6px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px;
  background: #f8fafc;
}

.evaluation-mode-summary p {
  margin: 0;
  color: var(--text);
}

.evaluation-mode-summary small {
  color: var(--muted);
}

.evaluation-form-grid .span-2 {
  grid-column: 1 / -1;
}

.evaluation-form-grid input,
.evaluation-form-grid select,
.evaluation-form-grid textarea,
.evaluation-chain-row input,
.evaluation-chain-row select,
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
  border-left: 4px solid #17483f;
  border-radius: 6px;
  background: #fafbf8;
}

.evaluation-item-number {
  min-height: 44px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  background: #e8f1ec;
  color: #315f50;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
}

.evidence-row {
  grid-template-columns: 92px minmax(170px, .7fr) minmax(220px, 1fr) minmax(180px, .8fr) auto;
  border-left-color: #0f9f6e;
}

.task-row {
  grid-template-columns: 92px minmax(140px, .55fr) minmax(170px, .65fr) minmax(230px, 1fr) auto;
  border-left-color: #d97706;
}

.evaluation-task-row {
  grid-template-columns: 92px minmax(180px, 1fr) minmax(180px, .7fr) minmax(180px, .7fr);
}

.evaluation-task-row > .evaluation-reference-list,
.evaluation-task-row > textarea {
  grid-column: span 2;
}

.evaluation-task-row > label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.evaluation-material-types {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  background: #fff;
}

.evaluation-material-types legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
}

.evaluation-material-types label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
}

.evaluation-material-types input {
  width: 18px;
  min-height: 18px;
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

.curriculum-reference-field {
  min-width: 0;
  display: grid;
  gap: 12px;
  border: 1px solid #c5d6cc;
  border-radius: 7px;
  padding: 14px;
  background: #f4f7f4;
}

.curriculum-reference-field > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.curriculum-reference-field > header > div {
  display: grid;
  gap: 4px;
}

.curriculum-reference-field > header small {
  color: var(--muted);
  line-height: 1.5;
}

.curriculum-reference-chain {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.curriculum-reference-chain > div {
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  background: #fff;
  color: var(--muted);
}

.curriculum-reference-chain > div.selected {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}

.curriculum-reference-help,
.curriculum-reference-empty {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}

.curriculum-reference-empty {
  border: 1px dashed #b8c9bf;
  border-radius: 6px;
  padding: 12px;
  text-align: center;
}

.selected-curriculum-references {
  display: grid;
  gap: 8px;
}

.selected-curriculum-references article {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff;
}

.selected-curriculum-references .selected-reference-content {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.selected-curriculum-references em {
  width: fit-content;
  border-radius: 999px;
  padding: 2px 7px;
  background: #e4ede8;
  color: var(--primary-dark);
  font-size: 11px;
  font-style: normal;
}

.selected-curriculum-references small {
  color: var(--muted);
  line-height: 1.45;
}

.selected-curriculum-references .selected-reference-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

.selected-curriculum-references .selected-reference-actions button {
  min-width: 44px;
  min-height: 44px;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.selected-curriculum-references .reference-trace-button {
  color: var(--primary-dark);
  font-weight: 600;
}

.selected-curriculum-references .reference-remove-button {
  color: var(--danger);
}

@media (max-width: 900px) {
  .evaluation-chain-row,
  .evidence-row,
  .task-row {
    grid-template-columns: 90px minmax(0, 1fr);
  }

  .evaluation-task-row > .evaluation-reference-list,
  .evaluation-task-row > textarea {
    grid-column: 1 / -1;
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

  .evaluation-task-row > .evaluation-reference-list,
  .evaluation-task-row > textarea {
    grid-column: auto;
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

  .curriculum-reference-field > header {
    align-items: stretch;
    flex-direction: column;
  }

  .curriculum-reference-chain {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .selected-curriculum-references article {
    align-items: flex-start;
    flex-direction: column;
  }

  .selected-curriculum-references .selected-reference-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
