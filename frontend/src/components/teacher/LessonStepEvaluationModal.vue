<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import {
  deleteLessonStepEvaluationBinding,
  getEvaluationOptions,
  getEvaluationStandard,
  getLessonStepEvaluationBinding,
  publishEvaluationPlan,
  publishEvaluationStandard,
  reviewEvaluationPlan,
  reviewEvaluationStandard,
  saveLessonStepEvaluationBinding,
  type EvaluationOptions,
  type EvaluationPlanRow,
  type EvaluationStandardRow,
  type LessonStepEvaluationBinding,
  type LessonStepEvaluationCriterion,
  type LessonStepEvaluationStandardOption,
  type LessonStepEvaluationUseBoundary
} from '@/api/evaluation'
import { vModalFocus } from '@/directives/modalFocus'
import EvaluationAIDraftWizard from '@/components/evaluation/EvaluationAIDraftWizard.vue'
import EvaluationPlanEditorModal from '@/components/evaluation/EvaluationPlanEditorModal.vue'
import EvaluationStandardEditorModal from '@/components/evaluation/EvaluationStandardEditorModal.vue'

const props = withDefaults(defineProps<{
  open: boolean
  embedded?: boolean
  lessonStepId: number | null
  lessonStepTitle: string
  lessonTitle: string
  courseId: number | null
  courseTitle: string
  gradeOrStage?: string
  courseContent?: string
  returnPath?: string
}>(), {
  embedded: false
})

const emit = defineEmits<{
  close: []
  saved: [binding: LessonStepEvaluationBinding | null]
}>()

const loading = ref(false)
const notice = ref('')
const binding = ref<LessonStepEvaluationBinding | null>(null)
const standards = ref<LessonStepEvaluationStandardOption[]>([])
const useBoundaries = ref<LessonStepEvaluationUseBoundary[]>([])
const selectedStandardId = ref<number | null>(null)
const enableSelf = ref(false)
const enablePeer = ref(false)
const enableTeacher = ref(true)
const aiDraftWizardOpen = ref(false)
const aiOptionsLoading = ref(false)
const aiOptions = ref<EvaluationOptions | null>(null)
const planEditorOpen = ref(false)
const standardEditorOpen = ref(false)
const authoringBusy = ref(false)
const authoringPlan = ref<EvaluationPlanRow | null>(null)
const authoringStandard = ref<EvaluationStandardRow | null>(null)
const authoringOrigin = ref<'manual' | 'ai' | null>(null)
const authoringPlanVersionId = ref<number | null>(null)
const authoringCompleted = ref(false)

const fallbackUseBoundaries: LessonStepEvaluationUseBoundary[] = [
  {
    code: 'classroom_feedback',
    label: '课堂反馈',
    status: 'available',
    status_label: '绑定后可用',
    description: '用于学生自评、小组互评、教师评价和后续教学反馈。'
  },
  {
    code: 'learning_state_update',
    label: '学习情况更新',
    status: 'requires_review',
    status_label: '需另行审查',
    description: '只有目标对应、个人归属、材料质量、评价标准和评分质量均符合要求的材料，才可作为候选依据。'
  },
  {
    code: 'research_and_model',
    label: '后续教学安排',
    status: 'not_direct',
    status_label: '需教师再确认',
    description: '课堂星级和小组结果不会直接决定学生后续学习内容、支持方式或分组；教师需查看具体材料。'
  }
]

const selectedStandard = computed(() => (
  standards.value.find((item) => item.id === selectedStandardId.value) || null
))
const locked = computed(() => Boolean(binding.value?.locked))
const lessonContextLabel = computed(() => [props.lessonTitle, props.lessonStepTitle].filter(Boolean).join(' · '))
const initialContentScope = computed(() => {
  const content = props.courseContent?.trim()
  return content ? [content.slice(0, 1000)] : []
})
const authoringStep = computed(() => {
  if (authoringCompleted.value) return 4
  if (authoringStandard.value) return 3
  if (authoringPlanVersionId.value) return 2
  return authoringPlan.value ? 1 : 0
})
const evaluationManagementRoute = computed(() => ({
  path: '/teacher/evaluations',
  query: {
    ...(props.courseId ? { course: String(props.courseId) } : {}),
    ...(props.returnPath ? { return: props.returnPath } : {}),
    source: 'lesson'
  }
}))
const canSave = computed(() => Boolean(
  selectedStandardId.value
  && (enableSelf.value || enablePeer.value || enableTeacher.value)
  && !locked.value
  && !loading.value
))
const isAuthoring = computed(() => Boolean(authoringPlan.value && !authoringCompleted.value))
const isEmpty = computed(() => !loading.value && !standards.value.length && !isAuthoring.value)
const workflowStep = computed(() => {
  if (binding.value || authoringCompleted.value) return 3
  if (selectedStandardId.value || authoringPlanVersionId.value) return 2
  return 1
})
const footerTitle = computed(() => {
  if (locked.value) return '当前评价安排已锁定'
  if (isAuthoring.value) {
    if (!authoringPlanVersionId.value) return '下一步：复核评价方案'
    if (!authoringStandard.value) return '下一步：设置评价指标与表现水平'
    return '下一步：由教师确认发布并绑定'
  }
  if (selectedStandard.value) return binding.value ? '调整本环节评价安排' : '绑定到当前教学环节'
  return '先为本环节建立评价方案'
})
const footerHint = computed(() => {
  if (locked.value) return '该版本已经用于课堂；如需调整，请复制教学环节后使用新版本。'
  if (isAuthoring.value) return '草稿不会自动进入课堂，完成教师复核并绑定后才可使用。'
  if (selectedStandard.value) {
    if (!enableSelf.value && !enablePeer.value && !enableTeacher.value) return '请至少选择一种课堂评价方式。'
    return '保存后固定本次使用的评价版本，课堂首次使用后不可修改。'
  }
  return '当前课程暂无可绑定版本，可选择手工设计或 AI 辅助起草。'
})
const authoringPrimaryLabel = computed(() => {
  if (authoringBusy.value) return '正在处理...'
  if (!authoringPlanVersionId.value) return '完成方案复核，继续设置评价指标'
  if (!authoringStandard.value) return '设置评价指标与表现水平'
  return '教师确认发布并绑定本环节'
})

function criterionCoreCompetencies(criterion: LessonStepEvaluationCriterion) {
  const labels = (criterion.curriculum_alignment?.core_competencies || []).flatMap((item) => (
    item.elements?.length ? item.elements : [item.title]
  ))
  return Array.from(new Set(labels.filter(Boolean)))
}

function curriculumPageLabel(start: number, end: number) {
  return start === end ? `第 ${start} 页` : `第 ${start}—${end} 页`
}

async function runAuthoringPrimaryAction() {
  if (!authoringPlanVersionId.value) {
    await continueToCriteria()
    return
  }
  if (!authoringStandard.value) {
    await openAuthoringStandard()
    return
  }
  await publishAndBindAuthoring()
}

function syncBinding(row: LessonStepEvaluationBinding | null) {
  binding.value = row
  selectedStandardId.value = row?.standard_version || standards.value[0]?.id || null
  enableSelf.value = Boolean(row?.enable_self)
  enablePeer.value = Boolean(row?.enable_peer)
  enableTeacher.value = row ? Boolean(row.enable_teacher) : true
}

async function loadBinding() {
  if (!props.lessonStepId) return
  loading.value = true
  notice.value = ''
  try {
    const row = await getLessonStepEvaluationBinding(props.lessonStepId)
    standards.value = row.standards
    useBoundaries.value = row.use_boundaries?.length ? row.use_boundaries : fallbackUseBoundaries
    syncBinding(row.binding)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价标准加载失败。'
  } finally {
    loading.value = false
  }
}

async function openAiDraft() {
  if (aiOptionsLoading.value || !props.courseId) return
  aiOptionsLoading.value = true
  notice.value = ''
  try {
    aiOptions.value = aiOptions.value || await getEvaluationOptions()
    aiDraftWizardOpen.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : 'AI 辅助起草所需课程信息加载失败。'
  } finally {
    aiOptionsLoading.value = false
  }
}

async function openManualDraft() {
  if (aiOptionsLoading.value || !props.courseId || locked.value) return
  aiOptionsLoading.value = true
  notice.value = ''
  try {
    aiOptions.value = aiOptions.value || await getEvaluationOptions()
    authoringPlan.value = null
    authoringStandard.value = null
    authoringOrigin.value = 'manual'
    authoringPlanVersionId.value = null
    authoringCompleted.value = false
    planEditorOpen.value = true
  } catch (error) {
    notice.value = evaluationActionError(error, '新建评价方案所需课程信息加载失败。')
  } finally {
    aiOptionsLoading.value = false
  }
}

function evaluationActionError(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback
  const detail = Object.values(error.errors || {}).flat().find(Boolean)
  return detail ? `${error.message} ${detail}` : error.message
}

function handlePlanDraftSaved(plan: EvaluationPlanRow) {
  const retainedAiStandard = authoringOrigin.value === 'ai' ? authoringStandard.value : null
  planEditorOpen.value = false
  authoringPlan.value = plan
  authoringStandard.value = retainedAiStandard
  authoringPlanVersionId.value = null
  authoringCompleted.value = false
  notice.value = retainedAiStandard
    ? `评价方案修改已保存，AI 起草的 ${retainedAiStandard.criterion_count ?? retainedAiStandard.criteria?.length ?? 0} 项评价指标仍保留。下一步请根据修改后的方案逐项核对。`
    : '评价方案草稿已保存到评价方案库，但尚未绑定当前环节。请完成教师复核，再继续设置评价指标与表现水平。'
}

function handleAiDraftSaved(plan: EvaluationPlanRow, standard: EvaluationStandardRow) {
  aiDraftWizardOpen.value = false
  authoringPlan.value = plan
  authoringStandard.value = standard
  authoringOrigin.value = 'ai'
  authoringPlanVersionId.value = null
  authoringCompleted.value = false
  notice.value = 'AI 已保存评价方案和评价标准草稿。草稿尚未进入课堂，请在本页完成教师复核和绑定。'
}

async function continueToCriteria() {
  if (!authoringPlan.value || authoringBusy.value) return
  authoringBusy.value = true
  notice.value = ''
  try {
    await reviewEvaluationPlan(authoringPlan.value.id)
    const publishedPlan = await publishEvaluationPlan(authoringPlan.value.id)
    const versionId = publishedPlan.latest_version?.id
    if (!versionId) throw new Error('评价方案版本没有生成。')
    authoringPlan.value = publishedPlan
    authoringPlanVersionId.value = versionId
    aiOptions.value = await getEvaluationOptions()
    if (authoringStandard.value) {
      authoringStandard.value = await getEvaluationStandard(authoringStandard.value.id)
    }
    standardEditorOpen.value = true
    notice.value = '评价方案已由教师复核并形成版本。请继续检查评价指标、表现水平和评分示例。'
  } catch (error) {
    notice.value = evaluationActionError(error, '评价方案复核未完成，请检查必填内容后重试。')
  } finally {
    authoringBusy.value = false
  }
}

function handleStandardDraftSaved(standard: EvaluationStandardRow) {
  standardEditorOpen.value = false
  authoringStandard.value = standard
  authoringCompleted.value = false
  notice.value = '评价指标与表现水平草稿已保存。确认评价方式后，可以由教师复核、发布并绑定当前环节。'
}

async function openAuthoringStandard() {
  if (!authoringPlanVersionId.value || authoringBusy.value) return
  authoringBusy.value = true
  notice.value = ''
  try {
    aiOptions.value = await getEvaluationOptions()
    if (authoringStandard.value) {
      authoringStandard.value = await getEvaluationStandard(authoringStandard.value.id)
    }
    standardEditorOpen.value = true
  } catch (error) {
    notice.value = evaluationActionError(error, '评价指标草稿加载失败。')
  } finally {
    authoringBusy.value = false
  }
}

async function publishAndBindAuthoring() {
  if (!props.lessonStepId || !authoringStandard.value || authoringBusy.value) return
  if (!enableSelf.value && !enablePeer.value && !enableTeacher.value) {
    notice.value = '至少选择一种课堂评价方式。'
    return
  }
  authoringBusy.value = true
  notice.value = ''
  try {
    await reviewEvaluationStandard(authoringStandard.value.id)
    const publishedStandard = await publishEvaluationStandard(authoringStandard.value.id)
    const versionId = publishedStandard.latest_version?.id
    if (!versionId) throw new Error('评价标准版本没有生成。')
    const row = await saveLessonStepEvaluationBinding(props.lessonStepId, {
      standard_version: versionId,
      enable_self: enableSelf.value,
      enable_peer: enablePeer.value,
      enable_teacher: enableTeacher.value
    })
    await loadBinding()
    authoringCompleted.value = true
    authoringStandard.value = publishedStandard
    notice.value = '绑定成功：评价方案已固定到当前环节，可以在课堂中使用。'
    emit('saved', row)
  } catch (error) {
    notice.value = evaluationActionError(error, '评价标准复核或绑定未完成，请检查评价指标后重试。')
  } finally {
    authoringBusy.value = false
  }
}

async function saveBinding() {
  if (!props.lessonStepId || !selectedStandardId.value) return
  if (!enableSelf.value && !enablePeer.value && !enableTeacher.value) {
    notice.value = '至少选择一种评价方式。'
    return
  }
  loading.value = true
  try {
    const row = await saveLessonStepEvaluationBinding(props.lessonStepId, {
      standard_version: selectedStandardId.value,
      enable_self: enableSelf.value,
      enable_peer: enablePeer.value,
      enable_teacher: enableTeacher.value
    })
    binding.value = row
    notice.value = '绑定成功：当前评价版本已固定到本环节。'
    emit('saved', row)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价标准保存失败。'
  } finally {
    loading.value = false
  }
}

async function clearBinding() {
  if (!props.lessonStepId || !binding.value || locked.value) return
  loading.value = true
  try {
    await deleteLessonStepEvaluationBinding(props.lessonStepId)
    syncBinding(null)
    notice.value = '已取消当前环节的评价标准。'
    emit('saved', null)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '取消绑定失败。'
  } finally {
    loading.value = false
  }
}

function close() {
  if (loading.value || authoringBusy.value) return
  aiDraftWizardOpen.value = false
  planEditorOpen.value = false
  standardEditorOpen.value = false
  emit('close')
}

watch(
  () => [props.open, props.lessonStepId],
  async ([open]) => {
    if (open && props.lessonStepId) {
      authoringPlan.value = null
      authoringStandard.value = null
      authoringOrigin.value = null
      authoringPlanVersionId.value = null
      authoringCompleted.value = false
      await loadBinding()
    }
  },
  { immediate: true }
)
</script>

<template>
  <Teleport to="body" :disabled="embedded">
    <div
      v-if="open && lessonStepId"
      :class="embedded ? 'step-evaluation-inline-host' : 'modal-backdrop'"
      role="presentation"
      @click.self="embedded ? undefined : close()"
    >
      <section
        v-modal-focus="embedded ? false : close"
        class="entity-modal step-evaluation-modal"
        :role="embedded ? 'region' : 'dialog'"
        :aria-modal="embedded ? undefined : 'true'"
        aria-labelledby="step-evaluation-title"
      >
        <header class="modal-header">
          <div>
            <span class="step-evaluation-eyebrow">课时设计中的评价</span>
            <h2 id="step-evaluation-title">为当前环节安排评价</h2>
            <p>{{ courseTitle }} · {{ lessonTitle }} · {{ lessonStepTitle }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" :disabled="loading" @click="close">×</button>
        </header>

        <p v-if="notice" class="notice-line" role="status">{{ notice }}</p>
        <p v-if="locked" class="step-evaluation-lock" role="status">
          该版本已用于课堂，当前绑定已锁定。后续调整请复制环节后选择新版本。
        </p>

        <ol class="step-evaluation-workflow" aria-label="本环节评价安排流程">
          <li :class="{ active: workflowStep === 1, complete: workflowStep > 1 }">
            <span>1</span><div><strong>评价方案</strong><small>新建或选择可用版本</small></div>
          </li>
          <li :class="{ active: workflowStep === 2, complete: workflowStep > 2 }">
            <span>2</span><div><strong>评价方式</strong><small>确定自评、互评或教师评价</small></div>
          </li>
          <li :class="{ active: workflowStep === 3 }">
            <span>3</span><div><strong>教师确认绑定</strong><small>固定本环节使用的版本</small></div>
          </li>
        </ol>

        <div class="step-evaluation-body" :class="{ 'is-empty': isEmpty, 'is-authoring': isAuthoring }">
          <section v-if="isEmpty" class="step-evaluation-empty" aria-labelledby="standard-selector-title">
            <span class="step-empty-eyebrow">第 1 步 · 评价方案</span>
            <h3 id="standard-selector-title">本课程还没有可绑定的评价版本</h3>
            <p>可在当前课时手工设计，也可由 AI 依据已复核的课程标准和本环节内容辅助起草。AI 结果仅作为草稿，仍需教师逐项复核。</p>
            <div class="step-empty-choice-summary" aria-label="两种新建方式说明">
              <article>
                <strong>手工设计</strong>
                <span>适合教师已有明确的学习目标、评价任务和评价标准。</span>
              </article>
              <article>
                <strong>AI 辅助起草</strong>
                <span>先建议适合的评价方式，再形成可修改的评价方案初稿。</span>
              </article>
            </div>
            <RouterLink class="step-library-link" :to="evaluationManagementRoute" @click="close">查看评价方案库</RouterLink>
            <details class="step-usage-disclosure">
              <summary>了解评价材料的后续使用范围</summary>
              <p>绑定版本只用于组织本环节课堂评价，不会自动改变学生后续的学习内容、支持方式或分组安排。</p>
              <ul>
                <li v-for="item in (useBoundaries.length ? useBoundaries : fallbackUseBoundaries)" :key="item.code">
                  <strong>{{ item.label }}：{{ item.status_label }}</strong>
                  <span>{{ item.description }}</span>
                </li>
              </ul>
            </details>
          </section>

          <section v-else-if="isAuthoring && authoringPlan" class="step-authoring-view" aria-labelledby="step-authoring-progress-title">
            <section class="step-authoring-progress">
              <header>
                <div>
                  <span>当前课时的新建进度</span>
                  <strong id="step-authoring-progress-title">{{ authoringPlan.title }}</strong>
                </div>
                <em>第 {{ Math.max(authoringStep, 1) }} 步</em>
              </header>
              <ol>
                <li :class="{ complete: authoringStep >= 1 }"><span>1</span><small>评价方案草稿</small></li>
                <li :class="{ complete: authoringStep >= 2 }"><span>2</span><small>教师复核方案</small></li>
                <li :class="{ complete: authoringStep >= 3 }"><span>3</span><small>评价指标与表现水平</small></li>
                <li :class="{ complete: authoringStep >= 4 }"><span>4</span><small>发布并绑定环节</small></li>
              </ol>
              <p v-if="!authoringPlanVersionId">请核对课程标准依据、学习目标、学习活动和评价任务，再继续设置评价指标。</p>
              <p v-else-if="!authoringStandard">评价方案版本已经形成，请继续设置评价指标、1—5 星表现说明、评分示例和暂不评价条件。</p>
              <p v-else>请检查评价指标及个人/小组评价材料归属，然后由教师发布并绑定本环节。</p>
            </section>

            <fieldset class="step-evaluation-types" :disabled="locked">
              <legend>本环节采用哪些评价方式</legend>
              <div>
                <label><input v-model="enableSelf" type="checkbox" />学生自评</label>
                <label><input v-model="enablePeer" type="checkbox" />小组互评</label>
                <label><input v-model="enableTeacher" type="checkbox" />教师评价</label>
              </div>
              <small>至少选择一种；发布并绑定时将采用这里的设置。</small>
            </fieldset>

            <details class="step-usage-disclosure">
              <summary>了解评价材料的后续使用范围</summary>
              <p>课堂评价材料是否用于更新学习情况，需要另行进行材料审查。</p>
            </details>
          </section>

          <template v-else>
            <section class="step-standard-selector" aria-labelledby="standard-selector-title">
              <header>
                <div>
                  <span>第 1 步 · 评价方案</span>
                  <strong id="standard-selector-title">选择本环节使用的评价版本</strong>
                </div>
                <div class="step-standard-header-actions">
                  <button class="secondary-button mini" type="button" :disabled="aiOptionsLoading || !courseId || locked" data-test="lesson-manual-draft" @click="openManualDraft">手工新建</button>
                  <button class="secondary-button mini" type="button" :disabled="aiOptionsLoading || !courseId || locked" data-test="lesson-ai-draft" @click="openAiDraft">
                    {{ aiOptionsLoading ? '加载中' : 'AI 辅助起草' }}
                  </button>
                </div>
              </header>

              <div class="step-standard-list">
                <label
                  v-for="item in standards"
                  :key="item.id"
                  :class="{ active: selectedStandardId === item.id }"
                >
                  <input v-model="selectedStandardId" type="radio" :value="item.id" :disabled="locked" />
                  <span>
                    <strong>{{ item.title }}</strong>
                    <small>版本 {{ item.version_no }} · {{ item.criterion_count }} 项评价指标 · {{ item.review_status_label }}</small>
                  </span>
                </label>
              </div>
              <RouterLink class="step-library-link" :to="evaluationManagementRoute" @click="close">查看评价方案库</RouterLink>

              <fieldset class="step-evaluation-types" :disabled="locked">
                <legend>第 2 步 · 本环节采用哪些评价方式</legend>
                <div>
                  <label><input v-model="enableSelf" type="checkbox" />学生自评</label>
                  <label><input v-model="enablePeer" type="checkbox" />小组互评</label>
                  <label><input v-model="enableTeacher" type="checkbox" />教师评价</label>
                </div>
                <small>至少选择一种评价方式。</small>
              </fieldset>
            </section>

            <section class="step-standard-preview" aria-labelledby="standard-preview-title">
              <header>
                <div>
                  <span>评价内容预览</span>
                  <strong id="standard-preview-title">{{ selectedStandard?.title || '请选择评价方案' }}</strong>
                </div>
                <small v-if="selectedStandard">课堂首次使用后冻结此版本</small>
              </header>

              <div v-if="selectedStandard" class="step-criterion-list">
                <article v-for="criterion in selectedStandard.criteria" :key="criterion.id">
                  <div class="step-criterion-alignment">
                    <section>
                      <span>左 · 课标依据</span>
                      <strong>核心素养与学习目标</strong>
                      <ul v-if="criterionCoreCompetencies(criterion).length">
                        <li v-for="label in criterionCoreCompetencies(criterion)" :key="label">{{ label }}</li>
                      </ul>
                      <p v-else>尚未显示核心素养要素。</p>
                      <small v-for="goal in criterion.curriculum_alignment?.learning_goals || []" :key="goal.code">{{ goal.code }} · {{ goal.title }}</small>
                    </section>
                    <section>
                      <span>中 · 评价指标</span>
                      <strong>{{ criterion.code }} · {{ criterion.title }}</strong>
                      <p>{{ criterion.expected_performance }}</p>
                      <small>{{ criterion.dimension_label }} · {{ criterion.evaluation_sources.join('、') }}</small>
                    </section>
                    <section>
                      <span>右 · 学业质量参照</span>
                      <strong>课堂表现水平 1—5</strong>
                      <template v-if="criterion.curriculum_alignment?.academic_quality?.length">
                        <small v-for="item in criterion.curriculum_alignment.academic_quality" :key="item.node_id">
                          {{ item.title }} · {{ curriculumPageLabel(item.page_start, item.page_end) }}
                        </small>
                      </template>
                      <small v-else>尚未显示可追溯的学业质量条目。</small>
                      <p>{{ criterion.curriculum_alignment?.quality_mapping_note || '课堂表现水平不直接等同于课程标准中的学业质量等级。' }}</p>
                    </section>
                  </div>
                  <details open>
                    <summary>对照 1—5 星可观察表现</summary>
                    <ol>
                      <li v-for="(description, index) in criterion.level_descriptions" :key="index">
                        <strong>{{ index + 1 }} 星</strong>
                        <span>{{ description }}</span>
                      </li>
                    </ol>
                    <p v-if="criterion.skip_condition" class="criterion-skip">暂不评价：{{ criterion.skip_condition }}</p>
                  </details>
                </article>
              </div>
              <p v-else class="empty">选择左侧评价版本后查看评价指标、预期表现和星级说明。</p>

              <details class="step-usage-disclosure">
                <summary>评价材料的后续使用范围</summary>
                <p>绑定版本不等于评价材料会自动改变学生后续的学习内容、支持方式或分组安排。</p>
                <ul>
                  <li v-for="item in (useBoundaries.length ? useBoundaries : fallbackUseBoundaries)" :key="item.code">
                    <strong>{{ item.label }}：{{ item.status_label }}</strong>
                    <span>{{ item.description }}</span>
                  </li>
                </ul>
              </details>
            </section>
          </template>
        </div>

        <footer class="modal-actions step-evaluation-actions">
          <div class="step-footer-context" role="status">
            <strong>{{ footerTitle }}</strong>
            <span>{{ footerHint }}</span>
          </div>
          <div class="step-footer-buttons">
            <button v-if="binding && !isAuthoring" class="text-danger-button" type="button" :disabled="loading || locked" @click="clearBinding">取消绑定</button>
            <button class="secondary-button" type="button" :disabled="loading || authoringBusy" @click="close">关闭</button>

            <template v-if="isEmpty">
              <button class="secondary-button" type="button" :disabled="aiOptionsLoading || !courseId" data-test="lesson-ai-draft" @click="openAiDraft">
                {{ aiOptionsLoading ? '加载中...' : 'AI 辅助起草' }}
              </button>
              <button class="primary-button" type="button" :disabled="aiOptionsLoading || !courseId" data-test="lesson-manual-draft" @click="openManualDraft">手工新建评价方案</button>
            </template>

            <template v-else-if="isAuthoring">
              <button
                class="secondary-button"
                type="button"
                :disabled="authoringBusy"
                :data-test="authoringPlanVersionId ? 'authoring-edit-standard' : 'authoring-edit-plan'"
                @click="authoringPlanVersionId ? openAuthoringStandard() : (planEditorOpen = true)"
              >
                {{ authoringPlanVersionId ? '检查或修改评价指标' : '返回修改评价方案' }}
              </button>
              <button
                class="primary-button"
                type="button"
                :disabled="authoringBusy"
                :data-test="!authoringPlanVersionId ? 'authoring-continue' : (authoringStandard ? 'authoring-publish-bind' : 'authoring-edit-standard')"
                @click="runAuthoringPrimaryAction"
              >
                {{ authoringPrimaryLabel }}
              </button>
            </template>

            <button v-else class="primary-button" type="button" :disabled="!canSave" @click="saveBinding">
              {{ loading ? '正在绑定...' : '确认绑定到本环节' }}
            </button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>

  <EvaluationAIDraftWizard
    v-if="aiDraftWizardOpen && aiOptions"
    :options="aiOptions"
    :initial-course-id="courseId"
    :initial-grade-or-stage="gradeOrStage"
    :initial-unit-title="`${lessonTitle} · ${lessonStepTitle}`"
    :initial-course-content="courseContent"
    initial-content-source-label="当前课时与本环节"
    initial-evaluation-purpose="formative"
    @close="aiDraftWizardOpen = false"
    @saved="handleAiDraftSaved"
  />

  <EvaluationPlanEditorModal
    v-if="planEditorOpen && aiOptions"
    :draft="authoringPlan"
    :options="aiOptions"
    :initial-course-id="courseId"
    :initial-title="`${lessonTitle} · ${lessonStepTitle}评价方案`"
    :initial-target-students="gradeOrStage || courseTitle"
    :initial-content-scope="initialContentScope"
    :context-label="lessonContextLabel"
    lock-course
    @close="planEditorOpen = false"
    @saved="handlePlanDraftSaved"
  />

  <EvaluationStandardEditorModal
    v-if="standardEditorOpen && aiOptions && authoringPlanVersionId"
    :draft="authoringStandard"
    :options="aiOptions"
    :initial-plan-version-id="authoringPlanVersionId"
    :context-label="lessonContextLabel"
    :assisted-by-ai="authoringOrigin === 'ai'"
    @close="standardEditorOpen = false"
    @saved="handleStandardDraftSaved"
  />
</template>

<style scoped>
.step-evaluation-modal {
  width: min(1080px, calc(100vw - 32px));
  height: min(760px, calc(100dvh - 32px));
  max-height: calc(100dvh - 32px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.step-evaluation-inline-host {
  width: 100%;
}

.step-evaluation-inline-host .step-evaluation-modal {
  width: 100%;
  height: auto;
  max-height: none;
  border: 1px solid var(--line);
  border-radius: 16px;
  box-shadow: none;
}

.step-evaluation-inline-host .step-evaluation-body {
  min-height: 520px;
  overflow: visible;
}

.step-evaluation-modal > .modal-header,
.step-evaluation-modal > .notice-line,
.step-evaluation-modal > .step-evaluation-lock,
.step-evaluation-modal > .step-evaluation-workflow,
.step-evaluation-modal > .step-evaluation-actions {
  flex: 0 0 auto;
}

.step-evaluation-eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--primary);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .06em;
}

.step-evaluation-lock {
  margin: 0;
  padding: 10px 24px;
  border-block: 1px solid #fed7aa;
  color: #9a3412;
  background: #fff7ed;
  font-size: 13px;
}

.step-evaluation-body {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(300px, .9fr) minmax(0, 1.5fr);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.step-evaluation-body.is-empty,
.step-evaluation-body.is-authoring {
  display: block;
}

.step-evaluation-workflow {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 12px 24px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  list-style: none;
}

.step-evaluation-workflow li {
  position: relative;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding-right: 16px;
}

.step-evaluation-workflow li:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 50%;
  right: 8px;
  width: 28px;
  height: 1px;
  background: var(--line);
}

.step-evaluation-workflow li > span {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 50%;
  color: var(--muted);
  background: #f8fafc;
  font-size: 12px;
  font-weight: 800;
}

.step-evaluation-workflow li.active > span {
  border-color: var(--primary);
  color: #fff;
  background: var(--primary);
}

.step-evaluation-workflow li.complete > span {
  border-color: #86efac;
  color: #166534;
  background: #dcfce7;
}

.step-evaluation-workflow li.complete strong {
  color: #166534;
}

.step-evaluation-workflow li div {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.step-evaluation-workflow small {
  color: var(--muted);
  line-height: 1.35;
}

.step-standard-selector,
.step-standard-preview {
  min-width: 0;
  padding: 20px 24px;
  overflow: visible;
}

.step-standard-selector {
  border-right: 1px solid var(--line);
  background: #f8fafc;
}

.step-standard-selector > header,
.step-standard-preview > header,
.step-criterion-list article > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.step-standard-selector > header > div:first-child,
.step-standard-preview > header > div,
.step-criterion-list article > header div {
  display: grid;
  gap: 4px;
}

.step-standard-header-actions {
  flex: 0 0 auto;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.step-library-link {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  padding: 0 4px;
  color: var(--primary-dark);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}

.step-library-link:hover,
.step-library-link:focus-visible {
  text-decoration: underline;
}

.step-standard-selector > header span,
.step-standard-preview > header span,
.step-criterion-list article > header span {
  color: var(--muted);
  font-size: 12px;
}

.step-standard-list {
  display: grid;
  gap: 8px;
  margin-top: 16px;
}

.step-standard-list label {
  min-height: 56px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  cursor: pointer;
}

.step-standard-list label.active {
  border-color: var(--primary);
  box-shadow: inset 3px 0 0 var(--primary);
}

.step-standard-list input {
  margin-top: 4px;
}

.step-standard-list span {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.step-standard-list strong,
.step-standard-list small {
  overflow-wrap: anywhere;
}

.step-standard-list small {
  color: var(--muted);
}

.step-standard-list em {
  width: fit-content;
  padding: 2px 7px;
  border-radius: 999px;
  color: #166534;
  background: #dcfce7;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}

.step-evaluation-types {
  display: grid;
  gap: 10px;
  margin: 20px 0 0;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.step-evaluation-types legend {
  padding: 0 6px;
  font-weight: 700;
}

.step-evaluation-types > div {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.step-evaluation-types label {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #f8fafc;
  cursor: pointer;
}

.step-evaluation-types input {
  width: 18px;
  height: 18px;
  min-height: 18px;
}

.step-evaluation-types small {
  color: var(--muted);
}

.step-standard-preview > header {
  margin-bottom: 16px;
}

.step-standard-preview > header > small {
  color: var(--muted);
  text-align: right;
}

.step-usage-disclosure {
  margin-top: 20px;
  border-top: 1px solid var(--line);
  padding-top: 12px;
  color: #475569;
}

.step-usage-disclosure summary {
  min-height: 44px;
  display: flex;
  align-items: center;
  width: fit-content;
  color: var(--primary-dark);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.step-usage-disclosure p {
  margin: 4px 0 0;
  line-height: 1.6;
}

.step-usage-disclosure ul {
  display: grid;
  gap: 8px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.step-usage-disclosure li {
  display: grid;
  gap: 2px;
  padding-left: 12px;
  border-left: 3px solid #cbd5ce;
  font-size: 12px;
  line-height: 1.55;
}

.step-criterion-list {
  display: grid;
  gap: 12px;
}

.step-criterion-list article {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}

.step-criterion-alignment {
  display: grid;
  grid-template-columns: minmax(0, .95fr) minmax(0, 1.35fr) minmax(0, 1fr);
  border: 1px solid var(--line);
  border-radius: 7px;
  overflow: hidden;
}

.step-criterion-alignment > section {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 7px;
  padding: 12px;
  border-right: 1px solid var(--line);
}

.step-criterion-alignment > section:first-child { background: #f4f7f4; }
.step-criterion-alignment > section:last-child { border-right: 0; background: #fcfcfd; }
.step-criterion-alignment span { color: var(--primary); font-size: 12px; font-weight: 800; }
.step-criterion-alignment p { margin: 0; color: #475569; line-height: 1.55; }
.step-criterion-alignment small { color: #64748b; line-height: 1.45; }
.step-criterion-alignment strong,
.step-criterion-alignment p,
.step-criterion-alignment small { overflow-wrap: anywhere; }
.step-criterion-alignment section:last-child p { color: #7c2d12; font-size: 12px; }
.step-criterion-alignment ul { display: flex; flex-wrap: wrap; gap: 5px; margin: 0; padding: 0; list-style: none; }
.step-criterion-list .step-criterion-alignment li { display: inline-flex; grid-template-columns: none; border: 1px solid #c5d6cc; border-radius: 999px; padding: 3px 7px; color: #315f50; background: #eef5f1; font-size: 12px; }

.step-criterion-list article > header small {
  max-width: 42%;
  color: var(--muted);
  text-align: right;
  overflow-wrap: anywhere;
}

.step-criterion-list article > p {
  margin: 12px 0;
  color: #334a43;
  line-height: 1.65;
}

.step-criterion-list details {
  border-top: 1px solid var(--line);
  padding-top: 10px;
}

.step-criterion-list summary {
  min-height: 40px;
  display: flex;
  align-items: center;
  color: var(--primary-dark);
  font-weight: 700;
  cursor: pointer;
}

.step-criterion-list ol {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.step-criterion-list li {
  display: grid;
  align-content: start;
  gap: 6px;
  border: 1px solid #d7e0da;
  border-radius: 6px;
  padding: 9px;
  background: #f8fafc;
  color: #334a43;
  line-height: 1.55;
}

.criterion-skip {
  margin: 12px 0 0;
  padding: 10px 12px;
  color: #92400e;
  background: #fffbeb;
  border-left: 3px solid #f59e0b;
}

.step-evaluation-empty {
  width: min(760px, calc(100% - 48px));
  display: grid;
  gap: 10px;
  margin: 28px auto;
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text);
  background: var(--surface);
}

.step-empty-eyebrow {
  color: var(--primary);
  font-size: 12px;
  font-weight: 800;
}

.step-evaluation-empty h3,
.step-evaluation-empty p {
  margin: 0;
}

.step-evaluation-empty p {
  color: #475569;
  line-height: 1.7;
}

.step-empty-choice-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 8px;
}

.step-empty-choice-summary article {
  display: grid;
  gap: 5px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f8fafc;
}

.step-empty-choice-summary span {
  color: #64748b;
  font-size: 13px;
  line-height: 1.55;
}

.step-evaluation-empty > .step-library-link {
  justify-self: start;
  margin-top: 2px;
}

.step-authoring-view {
  width: min(820px, calc(100% - 48px));
  margin: 24px auto;
}

.step-authoring-progress {
  display: grid;
  gap: 12px;
  padding: 18px;
  border: 1px solid #b8cdc4;
  border-radius: 8px;
  background: #eef5f1;
}

.step-authoring-progress > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.step-authoring-progress > header div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.step-authoring-progress > header span {
  color: #475569;
  font-size: 12px;
}

.step-authoring-progress > header strong {
  overflow-wrap: anywhere;
}

.step-authoring-progress > header em {
  flex: 0 0 auto;
  padding: 3px 8px;
  border-radius: 999px;
  color: #315f50;
  background: #e4ede8;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.step-authoring-progress > ol {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.step-authoring-progress > ol li {
  min-width: 0;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  color: #64748b;
}

.step-authoring-progress > ol li > span {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border: 1px solid #94a3b8;
  border-radius: 50%;
  background: #fff;
  font-size: 11px;
  font-weight: 800;
}

.step-authoring-progress > ol li.complete {
  color: #17483f;
  font-weight: 700;
}

.step-authoring-progress > ol li.complete > span {
  border-color: #17483f;
  color: #fff;
  background: #17483f;
}

.step-authoring-progress > p {
  margin: 0;
  color: #334a43;
  font-size: 12px;
  line-height: 1.6;
}

.step-evaluation-actions {
  min-height: 78px;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-top: 1px solid var(--line);
  background: var(--surface);
  box-shadow: 0 -6px 18px rgba(15, 23, 42, .06);
}

.step-footer-context {
  min-width: 0;
  display: grid;
  gap: 3px;
  margin-right: auto;
}

.step-footer-context strong {
  font-size: 13px;
}

.step-footer-context span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.step-footer-buttons {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.step-footer-buttons button {
  min-height: 44px;
}

@media (max-width: 820px) {
  .modal-backdrop {
    padding: 8px;
  }

  .step-evaluation-modal {
    width: 100%;
    height: calc(100dvh - 16px);
    max-height: calc(100dvh - 16px);
  }

  .step-evaluation-body {
    display: block;
    overflow-y: auto;
  }

  .step-evaluation-workflow {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    padding: 12px 16px;
  }

  .step-evaluation-workflow li::after {
    display: none;
  }

  .step-evaluation-workflow li {
    align-items: flex-start;
    padding: 0;
  }

  .step-evaluation-workflow li > span {
    width: 24px;
    height: 24px;
    flex-basis: 24px;
  }

  .step-evaluation-workflow small {
    display: none;
  }

  .step-standard-selector,
  .step-standard-preview {
    overflow: visible;
    padding: 16px;
  }

  .step-standard-selector {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .step-criterion-list article > header {
    display: grid;
  }

  .step-criterion-alignment {
    grid-template-columns: 1fr;
  }

  .step-criterion-alignment > section {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .step-criterion-alignment > section:last-child {
    border-bottom: 0;
  }

  .step-standard-selector > header,
  .step-standard-preview > header {
    display: grid;
  }

  .step-standard-header-actions {
    justify-content: stretch;
  }

  .step-standard-header-actions > * {
    flex: 1 1 auto;
  }

  .step-library-link {
    justify-content: center;
  }

  .step-evaluation-empty,
  .step-authoring-view {
    width: auto;
    margin: 16px;
  }

  .step-evaluation-empty {
    padding: 20px;
  }

  .step-empty-choice-summary {
    grid-template-columns: 1fr;
  }

  .step-authoring-progress > ol {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .step-criterion-list article > header small {
    max-width: none;
    text-align: left;
  }

  .step-evaluation-actions {
    display: grid;
    grid-template-columns: 1fr;
    gap: 10px;
    padding: 12px 16px;
  }

  .step-footer-buttons {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .step-footer-buttons .primary-button {
    grid-column: 1 / -1;
  }
}

@media (min-width: 521px) and (max-width: 820px) {
  .step-evaluation-actions {
    display: flex;
    gap: 14px;
  }

  .step-footer-buttons {
    width: auto;
    display: flex;
  }

  .step-footer-buttons .primary-button {
    grid-column: auto;
  }
}
</style>
