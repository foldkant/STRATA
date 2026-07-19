<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import {
  generateCourseEvaluationCriteria,
  getCourseEvaluation,
  saveCourseEvaluation,
  submitCourseTeacherEvaluation,
  type ClassroomEvaluationConfigPayload,
  type ClassroomEvaluationCriterion,
  type ClassroomEvaluationPayload,
  type ClassroomEvaluationStudentRow,
  type ClassroomEvaluationType,
  type CourseRow
} from '@/api/teacher'
import EvaluationRatingInput from '@/components/evaluation/EvaluationRatingInput.vue'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'

const props = defineProps<{
  open: boolean
  course: CourseRow | null
}>()

const emit = defineEmits<{
  close: []
}>()

const loading = ref(false)
const aiLoading = ref(false)
const notice = ref('')
const evaluationData = ref<ClassroomEvaluationPayload | null>(null)
const selectedClassGroupId = ref<number | ''>('')
const selectedTeacherEvalStudentId = ref<number | null>(null)
const teacherEvaluationRatings = ref<Record<string, number>>({})
const teacherEvaluationNotAssessed = ref<Record<string, EvaluationNotAssessedEntry>>({})
const teacherEvaluationComment = ref('')
const aiDirection = ref('')
const aiTypes = ref<ClassroomEvaluationType[]>(['self', 'peer', 'teacher'])
const evaluationForm = ref<ClassroomEvaluationConfigPayload>({
  enable_self: false,
  enable_peer: false,
  enable_teacher: false,
  self_criteria: [],
  peer_criteria: [],
  teacher_criteria: []
})

const evaluationTypeOptions: Array<{
  type: ClassroomEvaluationType
  label: string
  criteriaKey: keyof ClassroomEvaluationConfigPayload
  enabledKey: keyof ClassroomEvaluationConfigPayload
}> = [
  { type: 'self', label: '自评', criteriaKey: 'self_criteria', enabledKey: 'enable_self' },
  { type: 'peer', label: '互评', criteriaKey: 'peer_criteria', enabledKey: 'enable_peer' },
  { type: 'teacher', label: '师评', criteriaKey: 'teacher_criteria', enabledKey: 'enable_teacher' }
]

const selectedTeacherEvalStudent = computed(() => {
  const studentId = selectedTeacherEvalStudentId.value
  return evaluationData.value?.students.find((item) => item.student.id === studentId) || null
})
const teacherEvaluationCriteria = computed(() => evaluationForm.value.teacher_criteria)
const evaluationSummaryItems = computed(() => evaluationTypeOptions.map((item) => ({
  ...item,
  summary: evaluationData.value?.summary?.[item.type] || null,
  criteria: evaluationCriteria(item.type)
})))
const evaluationEnabledCount = computed(() => evaluationTypeOptions.filter((item) => Boolean(evaluationForm.value[item.enabledKey])).length)

function syncForm(row: ClassroomEvaluationPayload | null) {
  const config = row?.config
  evaluationForm.value = {
    enable_self: Boolean(config?.enable_self),
    enable_peer: Boolean(config?.enable_peer),
    enable_teacher: Boolean(config?.enable_teacher),
    self_criteria: config?.self_criteria || [],
    peer_criteria: config?.peer_criteria || [],
    teacher_criteria: config?.teacher_criteria || []
  }
}

async function loadEvaluation() {
  if (!props.course) return
  loading.value = true
  try {
    const row = await getCourseEvaluation(props.course.id, selectedClassGroupId.value)
    evaluationData.value = row
    syncForm(row)
    if (row.selected_class_group) {
      selectedClassGroupId.value = row.selected_class_group.id
    }
    if (!selectedTeacherEvalStudentId.value && row.students.length) {
      selectedTeacherEvalStudentId.value = row.students[0].student.id
    }
    syncTeacherEvaluationDraft()
    notice.value = ''
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程评价加载失败。'
  } finally {
    loading.value = false
  }
}

function evaluationCriteria(type: ClassroomEvaluationType) {
  const option = evaluationTypeOptions.find((item) => item.type === type)
  if (!option) return []
  return evaluationForm.value[option.criteriaKey] as ClassroomEvaluationCriterion[]
}

function setEvaluationCriteria(type: ClassroomEvaluationType, rows: ClassroomEvaluationCriterion[]) {
  const option = evaluationTypeOptions.find((item) => item.type === type)
  if (!option) return
  evaluationForm.value = {
    ...evaluationForm.value,
    [option.criteriaKey]: rows
  }
}

function evaluationEnabled(type: ClassroomEvaluationType) {
  const option = evaluationTypeOptions.find((item) => item.type === type)
  return option ? Boolean(evaluationForm.value[option.enabledKey]) : false
}

function toggleEvaluation(type: ClassroomEvaluationType, checked: boolean) {
  const option = evaluationTypeOptions.find((item) => item.type === type)
  if (!option) return
  evaluationForm.value = {
    ...evaluationForm.value,
    [option.enabledKey]: checked
  }
  if (checked && !evaluationCriteria(type).length) {
    addEvaluationCriterion(type)
  }
}

function defaultEvaluationCriterion(type: ClassroomEvaluationType): ClassroomEvaluationCriterion {
  const label = evaluationTypeOptions.find((item) => item.type === type)?.label || '评价'
  const count = evaluationCriteria(type).length + 1
  return {
    id: `${type}_${Date.now()}_${count}`,
    title: `${label}维度${count}`,
    description: '',
    sort_order: count * 10
  }
}

function addEvaluationCriterion(type: ClassroomEvaluationType) {
  setEvaluationCriteria(type, [...evaluationCriteria(type), defaultEvaluationCriterion(type)])
}

function updateEvaluationCriterion(type: ClassroomEvaluationType, index: number, field: keyof ClassroomEvaluationCriterion, value: string | number) {
  const rows = evaluationCriteria(type).map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item)
  setEvaluationCriteria(type, rows)
}

function removeEvaluationCriterion(type: ClassroomEvaluationType, index: number) {
  setEvaluationCriteria(type, evaluationCriteria(type).filter((_, itemIndex) => itemIndex !== index))
}

async function saveConfig() {
  if (!props.course) return
  loading.value = true
  try {
    const row = await saveCourseEvaluation(props.course.id, {
      ...evaluationForm.value,
      class_group: selectedClassGroupId.value
    })
    evaluationData.value = row
    syncForm(row)
    notice.value = '课程评价设置已保存。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程评价设置保存失败。'
  } finally {
    loading.value = false
  }
}

async function generateCriteria() {
  if (!props.course) return
  if (!aiTypes.value.length) {
    notice.value = '请选择要生成的评价类型。'
    return
  }
  aiLoading.value = true
  try {
    const result = await generateCourseEvaluationCriteria(props.course.id, {
      types: aiTypes.value,
      direction: aiDirection.value.trim()
    })
    for (const type of aiTypes.value) {
      const rows = result[type]
      if (rows?.length) {
        setEvaluationCriteria(type, rows)
        toggleEvaluation(type, true)
      }
    }
    notice.value = 'AI 已生成评价项草稿，请确认后保存。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : 'AI 生成评价项失败。'
  } finally {
    aiLoading.value = false
  }
}

function syncTeacherEvaluationDraft(row: ClassroomEvaluationStudentRow | null = selectedTeacherEvalStudent.value) {
  const ratings = row?.teacher_submission?.ratings || {}
  teacherEvaluationRatings.value = { ...ratings }
  teacherEvaluationNotAssessed.value = row?.teacher_submission?.not_assessed
    ? { ...row.teacher_submission.not_assessed }
    : {}
  teacherEvaluationComment.value = row?.teacher_submission?.comment || ''
}

function selectTeacherEvalStudent(studentId: number) {
  selectedTeacherEvalStudentId.value = studentId
  syncTeacherEvaluationDraft(evaluationData.value?.students.find((item) => item.student.id === studentId) || null)
}

function setTeacherRating(criterionId: string, value: number) {
  const notAssessed = { ...teacherEvaluationNotAssessed.value }
  delete notAssessed[criterionId]
  teacherEvaluationNotAssessed.value = notAssessed
  teacherEvaluationRatings.value = {
    ...teacherEvaluationRatings.value,
    [criterionId]: value
  }
}

function setTeacherNotAssessed(criterionId: string, value: EvaluationNotAssessedEntry | null) {
  const ratings = { ...teacherEvaluationRatings.value }
  const notAssessed = { ...teacherEvaluationNotAssessed.value }
  if (value) {
    delete ratings[criterionId]
    notAssessed[criterionId] = value
  } else {
    delete notAssessed[criterionId]
  }
  teacherEvaluationRatings.value = ratings
  teacherEvaluationNotAssessed.value = notAssessed
}

async function submitTeacherEvaluation() {
  if (!props.course || !selectedTeacherEvalStudent.value) return
  if (!evaluationForm.value.enable_teacher) {
    notice.value = '请先开启师评并保存评价设置。'
    return
  }
  const missing = teacherEvaluationCriteria.value.find((item) => (
    !teacherEvaluationRatings.value[item.id] && !teacherEvaluationNotAssessed.value[item.id]
  ))
  if (missing) {
    notice.value = `请为“${missing.title}”选择星级或暂不评价。`
    return
  }
  const missingOtherNote = teacherEvaluationCriteria.value.find((item) => {
    const skipped = teacherEvaluationNotAssessed.value[item.id]
    return skipped?.reason === 'other' && !skipped.note.trim()
  })
  if (missingOtherNote) {
    notice.value = `请填写“${missingOtherNote.title}”暂不评价的具体说明。`
    return
  }
  loading.value = true
  try {
    const row = await submitCourseTeacherEvaluation(props.course.id, {
      class_group: selectedClassGroupId.value,
      target: selectedTeacherEvalStudent.value.student.id,
      ratings: teacherEvaluationRatings.value,
      not_assessed: teacherEvaluationNotAssessed.value,
      comment: teacherEvaluationComment.value.trim()
    })
    evaluationData.value = row
    syncForm(row)
    syncTeacherEvaluationDraft()
    notice.value = '师评已保存。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '师评保存失败。'
  } finally {
    loading.value = false
  }
}

function close() {
  emit('close')
}

watch(
  () => [props.open, props.course?.id],
  async ([open]) => {
    if (open && props.course) {
      selectedClassGroupId.value = ''
      selectedTeacherEvalStudentId.value = null
      teacherEvaluationRatings.value = {}
      teacherEvaluationNotAssessed.value = {}
      teacherEvaluationComment.value = ''
      await loadEvaluation()
    }
  },
  { immediate: true }
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open && course" class="modal-backdrop classroom-evaluation-backdrop" role="presentation" @click.self="close">
      <section class="entity-modal classroom-evaluation-modal course-evaluation-modal" role="dialog" aria-modal="true" aria-labelledby="course-evaluation-title">
        <header class="modal-header">
          <div>
            <h2 id="course-evaluation-title">课程评价</h2>
            <p>{{ course.title }} · 评价设置归课程，课堂与课程均可查看结果。</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" :disabled="loading" @click="close">×</button>
        </header>

        <p class="notice-line course-evaluation-notice" :class="{ empty: !notice }" role="status">{{ notice || ' ' }}</p>

        <div class="course-evaluation-toolbar">
          <label>
            <span>评价班级</span>
            <select v-model="selectedClassGroupId" :disabled="loading" @change="loadEvaluation">
              <option v-for="item in evaluationData?.class_options || []" :key="item.id" :value="item.id">
                {{ item.grade ? `${item.grade} ` : '' }}{{ item.name }}
              </option>
            </select>
          </label>
          <strong>{{ evaluationEnabledCount }} 类评价已开启</strong>
        </div>

        <div class="classroom-evaluation-body">
          <section class="evaluation-config-panel">
            <header class="evaluation-section-head">
              <div>
                <span>课程评价设置</span>
                <strong>自评、互评、师评</strong>
              </div>
              <div class="evaluation-section-actions">
                <RouterLink class="secondary-button mini" to="/teacher/evaluations" @click="close">评价标准库</RouterLink>
                <button class="secondary-button mini" type="button" :disabled="loading" @click="loadEvaluation">刷新</button>
              </div>
            </header>

            <div class="evaluation-ai-panel">
              <span>AI 生成草稿</span>
              <strong>基于课程目标生成评价项</strong>
              <textarea v-model="aiDirection" maxlength="1000" placeholder="填写评价方向，例如：围绕任务完成质量、合作过程、作品表达等"></textarea>
              <div class="evaluation-ai-actions">
                <label v-for="item in evaluationTypeOptions" :key="item.type">
                  <input v-model="aiTypes" type="checkbox" :value="item.type" />
                  {{ item.label }}
                </label>
                <button class="primary-button mini" type="button" :disabled="aiLoading" @click="generateCriteria">
                  {{ aiLoading ? '生成中...' : 'AI 生成草稿' }}
                </button>
              </div>
            </div>

            <section v-for="item in evaluationTypeOptions" :key="item.type" class="evaluation-type-editor">
              <header>
                <label class="evaluation-toggle">
                  <input
                    type="checkbox"
                    :checked="evaluationEnabled(item.type)"
                    @change="toggleEvaluation(item.type, ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ item.label }}</span>
                </label>
                <button class="secondary-button mini" type="button" @click="addEvaluationCriterion(item.type)">新增评价项</button>
              </header>
              <p v-if="item.type === 'peer'" class="evaluation-warning">互评项保存在课程中，只有课堂开启小组合作后学生端才会出现互评。</p>
              <div class="evaluation-criteria-list">
                <article v-for="(criterion, index) in evaluationCriteria(item.type)" :key="criterion.id">
                  <input
                    :value="criterion.title"
                    maxlength="80"
                    placeholder="评价项"
                    @input="updateEvaluationCriterion(item.type, index, 'title', ($event.target as HTMLInputElement).value)"
                  />
                  <textarea
                    :value="criterion.description"
                    maxlength="300"
                    placeholder="5星观察说明"
                    @input="updateEvaluationCriterion(item.type, index, 'description', ($event.target as HTMLTextAreaElement).value)"
                  ></textarea>
                  <button class="text-danger-button" type="button" @click="removeEvaluationCriterion(item.type, index)">删除</button>
                </article>
                <p v-if="!evaluationCriteria(item.type).length" class="empty">暂无评价项。</p>
              </div>
            </section>
          </section>

          <aside class="evaluation-results-panel">
            <section class="evaluation-summary-panel">
              <header class="evaluation-section-head">
                <div>
                  <span>评价情况</span>
                  <strong>{{ evaluationData?.selected_class_group?.name || '未选择班级' }}</strong>
                </div>
              </header>
              <div class="evaluation-summary-grid">
                <article v-for="item in evaluationSummaryItems" :key="item.type">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.summary?.submitted || 0 }}/{{ item.summary?.total || 0 }}</strong>
                  <small>
                    已评分 {{ item.summary?.rated_item_count || 0 }}/{{ item.summary?.total_item_count || 0 }} 项
                    <template v-if="item.summary?.not_assessed_item_count"> · 暂不评价 {{ item.summary.not_assessed_item_count }} 项</template>
                    · {{ item.summary?.average ? `${item.summary.average} 星` : '暂无平均' }}
                  </small>
                </article>
              </div>
            </section>

            <section class="teacher-evaluation-panel">
              <header class="evaluation-section-head">
                <div>
                  <span>课程师评</span>
                  <strong>填写星级或暂不评价</strong>
                </div>
              </header>

              <div class="teacher-evaluation-layout">
                <div class="teacher-evaluation-student-list">
                  <button
                    v-for="row in evaluationData?.students || []"
                    :key="row.student.id"
                    type="button"
                    :class="{ active: selectedTeacherEvalStudentId === row.student.id }"
                    @click="selectTeacherEvalStudent(row.student.id)"
                  >
                    <strong>{{ row.student.display_name || row.student.username }}</strong>
                    <small>{{ row.profile?.student_no || row.student.username }}</small>
                  </button>
                  <p v-if="!(evaluationData?.students || []).length" class="empty">当前班级暂无学生。</p>
                </div>

                <div class="teacher-evaluation-form">
                  <p v-if="!evaluationForm.enable_teacher" class="evaluation-warning">开启师评并保存后，才能给学生填写师评。</p>
                  <template v-if="selectedTeacherEvalStudent">
                    <div class="teacher-evaluation-target">
                      <span>评价对象</span>
                      <strong>{{ selectedTeacherEvalStudent.student.display_name || selectedTeacherEvalStudent.student.username }}</strong>
                    </div>
                    <div class="evaluation-star-list">
                      <EvaluationRatingInput
                        v-for="criterion in teacherEvaluationCriteria"
                        :key="criterion.id"
                        :criterion="criterion"
                        :rating="teacherEvaluationRatings[criterion.id] || 0"
                        :not-assessed="teacherEvaluationNotAssessed[criterion.id] || null"
                        :disabled="loading"
                        @rating="setTeacherRating"
                        @not-assessed="setTeacherNotAssessed"
                      />
                      <p v-if="!teacherEvaluationCriteria.length" class="empty">暂无师评评价项。</p>
                    </div>
                    <label class="evaluation-comment-box">
                      <span>评价备注</span>
                      <textarea v-model="teacherEvaluationComment" maxlength="1000" placeholder="可填写简短过程性反馈"></textarea>
                    </label>
                  </template>
                  <p v-else class="empty">请选择学生。</p>
                </div>
              </div>
            </section>
          </aside>
        </div>

        <footer class="modal-actions evaluation-modal-actions">
          <button class="secondary-button" type="button" :disabled="loading" @click="close">关闭</button>
          <button class="secondary-button" type="button" :disabled="loading || !selectedTeacherEvalStudent" @click="submitTeacherEvaluation">保存师评</button>
          <button class="primary-button" type="button" :disabled="loading" @click="saveConfig">
            {{ loading ? '保存中...' : '保存评价设置' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
