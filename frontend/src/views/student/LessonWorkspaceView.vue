<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  completeStudentLessonStep,
  enterStudentLesson,
  enterStudentLessonStep,
  getStudentLessonWorkspace,
  submitStudentStepAnswer,
  type StudentLessonQuestion,
  type StudentLessonStep,
  type StudentLessonWorkspace,
  type StudentResourceBinding
} from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const route = useRoute()
const router = useRouter()
const lessonId = computed(() => Number(route.params.lessonId || 0))
const workspace = ref<StudentLessonWorkspace | null>(null)
const selectedStepId = ref<number | null>(null)
const selectedResourceIndex = ref(0)
const completedStepIds = ref<number[]>([])
const answerDrafts = ref<Record<string, string>>({})
const questionAnswerDrafts = ref<Record<string, Record<string, string | string[]>>>({})
const notice = ref('')
const success = ref('')
const loading = ref(false)
const saving = ref(false)
const stepStartedAt = ref(Date.now())
const navItems = studentNav('/student/courses')

const selectedStep = computed(() => {
  if (!workspace.value) return null
  return workspace.value.steps.find((step) => step.id === selectedStepId.value) || workspace.value.steps[0] || null
})

const selectedStepIndex = computed(() => {
  if (!workspace.value || !selectedStep.value) return -1
  return workspace.value.steps.findIndex((step) => step.id === selectedStep.value?.id)
})

const stepCount = computed(() => workspace.value?.steps.length || 0)

const progressText = computed(() => {
  if (!stepCount.value) return '暂无环节'
  return `${completedStepIds.value.length}/${stepCount.value} 已完成`
})

const activeResources = computed(() => selectedStep.value?.resource_items || [])
const activeActivities = computed(() => selectedStep.value?.activity_items || [])
const activeQuestions = computed(() => selectedStep.value?.question_items || [])

const selectedResource = computed(() => {
  const items = activeResources.value
  if (!items.length) return null
  return items[Math.min(selectedResourceIndex.value, items.length - 1)] || null
})

const answerDraft = computed({
  get() {
    const id = selectedStep.value?.id
    return id ? answerDrafts.value[String(id)] || '' : ''
  },
  set(value: string) {
    const id = selectedStep.value?.id
    if (!id) return
    answerDrafts.value = { ...answerDrafts.value, [String(id)]: value }
  }
})

function stepTypeNeedsAnswer(step: StudentLessonStep | null) {
  if (!step) return false
  return Boolean(step.question_items?.length) || ['question', 'task', 'discussion', 'reflection', 'evaluation', 'ai_worksheet'].includes(step.step_type)
}

function stepTypeNeedsUpload(step: StudentLessonStep | null) {
  return step?.step_type === 'upload' || step?.step_type === 'document'
}

function isCompleted(stepId: number) {
  return completedStepIds.value.includes(stepId)
}

function resourceTitle(resource: StudentResourceBinding) {
  return resource.title || resource.attachment_name || '未命名资源'
}

function questionAnswer(question: StudentLessonQuestion) {
  const stepId = selectedStep.value?.id
  if (!stepId) return question.question_type === 'multiple' ? [] : ''
  const value = questionAnswerDrafts.value[String(stepId)]?.[question.id]
  if (question.question_type === 'multiple') return Array.isArray(value) ? value : []
  return typeof value === 'string' ? value : ''
}

function setQuestionAnswer(question: StudentLessonQuestion, value: string | string[]) {
  const stepId = selectedStep.value?.id
  if (!stepId) return
  questionAnswerDrafts.value = {
    ...questionAnswerDrafts.value,
    [String(stepId)]: {
      ...(questionAnswerDrafts.value[String(stepId)] || {}),
      [question.id]: value
    }
  }
}

function toggleMultipleAnswer(question: StudentLessonQuestion, value: string, checked: boolean) {
  const current = questionAnswer(question)
  const items = Array.isArray(current) ? current : []
  setQuestionAnswer(question, checked ? Array.from(new Set([...items, value])) : items.filter((item) => item !== value))
}

function optionChecked(question: StudentLessonQuestion, value: string) {
  const current = questionAnswer(question)
  return Array.isArray(current) ? current.includes(value) : current === value
}

function validateQuestionAnswers() {
  if (!activeQuestions.value.length) return true
  for (const question of activeQuestions.value) {
    if (!question.is_required) continue
    const value = questionAnswer(question)
    const empty = Array.isArray(value) ? value.length === 0 : !String(value || '').trim()
    if (empty) {
      notice.value = `请完成必答题：${question.stem}`
      return false
    }
  }
  return true
}

async function selectStep(step: StudentLessonStep) {
  selectedStepId.value = step.id
  selectedResourceIndex.value = 0
  stepStartedAt.value = Date.now()
  try {
    await enterStudentLessonStep(step.id)
  } catch {
    // 埋点失败不阻断课堂学习。
  }
}

async function moveStep(offset: number) {
  if (!workspace.value || !workspace.value.steps.length) return
  const nextIndex = Math.min(Math.max(selectedStepIndex.value + offset, 0), workspace.value.steps.length - 1)
  await selectStep(workspace.value.steps[nextIndex])
}

async function markComplete() {
  if (!selectedStep.value) return
  saving.value = true
  notice.value = ''
  success.value = ''
  try {
    await completeStudentLessonStep(selectedStep.value.id, Date.now() - stepStartedAt.value)
    if (!completedStepIds.value.includes(selectedStep.value.id)) {
      completedStepIds.value = [...completedStepIds.value, selectedStep.value.id]
    }
    success.value = '已记录当前环节完成。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '完成状态提交失败。'
  } finally {
    saving.value = false
  }
}

async function submitAnswer() {
  if (!selectedStep.value) return
  if (!validateQuestionAnswers()) return
  const hasStructuredQuestions = activeQuestions.value.length > 0
  const answer = hasStructuredQuestions
    ? {
        questions: questionAnswerDrafts.value[String(selectedStep.value.id)] || {},
        text: answerDraft.value.trim()
      }
    : answerDraft.value.trim()
  if (!hasStructuredQuestions && !answer) {
    notice.value = '请先填写内容后再提交。'
    return
  }
  saving.value = true
  notice.value = ''
  success.value = ''
  try {
    await submitStudentStepAnswer(selectedStep.value.id, answer)
    success.value = '答案已提交。'
    await markComplete()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '答案提交失败。'
  } finally {
    saving.value = false
  }
}

async function loadWorkspace() {
  loading.value = true
  notice.value = ''
  try {
    workspace.value = await getStudentLessonWorkspace(lessonId.value)
    if (workspace.value.steps.length) {
      await selectStep(workspace.value.steps[0])
    }
    await enterStudentLesson(lessonId.value)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课时学习页加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(loadWorkspace)
</script>

<template>
  <StudentShell
    :title="workspace?.lesson.title || '课时学习'"
    :subtitle="workspace ? `${workspace.course.title} · ${progressText}` : '课时学习'"
    :nav-items="navItems"
  >
    <template #actions>
      <button class="student-ghost-button" type="button" @click="router.back()">返回</button>
    </template>

    <NoticeLine v-if="notice" :message="notice" />
    <NoticeLine v-if="success" :message="success" tone="success" />
    <section v-if="loading || !workspace" class="student-panel">
      <p class="empty">正在加载课时内容</p>
    </section>

    <section v-else class="student-workspace-grid">
      <article class="student-resource-pane">
        <header>
          <div>
            <span>资源预览</span>
            <h2>{{ selectedStep?.title || '学习资源' }}</h2>
          </div>
          <small>{{ selectedStep?.step_type_label }}</small>
        </header>

        <div v-if="activeResources.length" class="student-resource-tabs">
            <button
            v-for="(resource, index) in activeResources"
            :key="`${resourceTitle(resource)}-${index}`"
            type="button"
            :class="{ active: selectedResourceIndex === index }"
            @click="selectedResourceIndex = index"
          >
            {{ resourceTitle(resource) || `资源 ${index + 1}` }}
          </button>
        </div>

        <div class="student-preview-stage">
          <ResourcePreview :resource="selectedResource" office-mode="view" />
        </div>
      </article>

      <aside class="student-step-pane">
        <div class="student-step-list">
          <button
            v-for="(step, index) in workspace.steps"
            :key="step.id"
            type="button"
            class="student-step-item"
            :class="{ active: selectedStep?.id === step.id, complete: isCompleted(step.id) }"
            @click="selectStep(step)"
          >
            <em>{{ index + 1 }}</em>
            <span>
              <strong>{{ step.title }}</strong>
              <small>{{ step.step_type_label }} · {{ step.estimated_minutes }} 分钟</small>
            </span>
            <i>{{ isCompleted(step.id) ? '完成' : step.is_required ? '必做' : '选做' }}</i>
          </button>
          <p v-if="!workspace.steps.length" class="empty">当前课时暂无已配置环节。</p>
        </div>

        <section v-if="selectedStep" class="student-step-detail">
          <header>
            <div>
              <span>本环节任务</span>
              <h2>{{ selectedStep.title }}</h2>
            </div>
            <small>{{ selectedStep.step_type_label }} · {{ selectedStep.estimated_minutes }} 分钟</small>
          </header>
          <p class="student-instruction">
            {{ selectedStep.student_instruction || '教师暂未填写学生可见说明。' }}
          </p>

          <div v-if="activeActivities.length" class="student-activity-list">
            <strong>活动</strong>
            <span v-for="(activity, index) in activeActivities" :key="`${activity}-${index}`">{{ activity }}</span>
          </div>

          <div v-if="activeQuestions.length" class="student-lesson-question-list">
            <section v-for="(question, index) in activeQuestions" :key="question.id" class="student-lesson-question-card">
              <header>
                <span>{{ question.question_type_label }}{{ question.is_required ? ' · 必答' : ' · 选答' }}</span>
                <small>{{ question.score }} 分</small>
              </header>
              <h3>{{ index + 1 }}. {{ question.stem }}</h3>

              <div v-if="question.question_type === 'single' || question.question_type === 'judge'" class="student-option-list">
                <label v-for="option in question.options" :key="`${question.id}-${option}`">
                  <input
                    type="radio"
                    :name="`lesson-question-${selectedStep.id}-${question.id}`"
                    :checked="optionChecked(question, option)"
                    @change="setQuestionAnswer(question, option)"
                  />
                  <span>{{ option }}</span>
                </label>
              </div>

              <div v-else-if="question.question_type === 'multiple'" class="student-option-list">
                <label v-for="option in question.options" :key="`${question.id}-${option}`">
                  <input
                    type="checkbox"
                    :checked="optionChecked(question, option)"
                    @change="toggleMultipleAnswer(question, option, ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ option }}</span>
                </label>
              </div>

              <label v-else-if="question.question_type === 'blank'" class="student-answer-box inline-answer">
                <span>我的答案</span>
                <input
                  :value="String(questionAnswer(question) || '')"
                  placeholder="填写答案"
                  @input="setQuestionAnswer(question, ($event.target as HTMLInputElement).value)"
                />
              </label>

              <label v-else class="student-answer-box">
                <span>我的答案</span>
                <textarea
                  :value="String(questionAnswer(question) || '')"
                  rows="5"
                  placeholder="填写你的分析、说明或反思"
                  @input="setQuestionAnswer(question, ($event.target as HTMLTextAreaElement).value)"
                ></textarea>
              </label>
            </section>
          </div>

          <label v-if="stepTypeNeedsAnswer(selectedStep) && !activeQuestions.length" class="student-answer-box">
            <span>我的作答</span>
            <textarea v-model="answerDraft" rows="6" placeholder="在这里填写答案、讨论内容或学习反思"></textarea>
          </label>

          <div v-if="stepTypeNeedsUpload(selectedStep)" class="student-upload-placeholder">
            <strong>作品提交</strong>
            <p>文件上传接口会在任务/作品提交模块接入。当前可以先按教师要求完成本环节。</p>
          </div>

          <footer class="student-workspace-actions">
            <button class="student-ghost-button" type="button" :disabled="selectedStepIndex <= 0" @click="moveStep(-1)">
              上一步
            </button>
            <button
              v-if="stepTypeNeedsAnswer(selectedStep)"
              class="student-primary-action"
              type="button"
              :disabled="saving"
              @click="submitAnswer"
            >
              提交作答
            </button>
            <button v-else class="student-primary-action" type="button" :disabled="saving" @click="markComplete">
              标记完成
            </button>
            <button
              class="student-ghost-button"
              type="button"
              :disabled="selectedStepIndex >= workspace.steps.length - 1"
              @click="moveStep(1)"
            >
              下一步
            </button>
          </footer>
        </section>
      </aside>
    </section>
  </StudentShell>
</template>
