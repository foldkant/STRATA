<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  closeClassroomStep,
  finishClassroomSession,
  getClassroomSession,
  getTeacherLessonSteps,
  lockClassroomStep,
  openClassroomStep,
  restartClassroomSession,
  startClassroomSession,
  type ClassroomSessionRow,
  type LessonStepQuestion,
  type LessonStepRow,
  type ResourceBinding
} from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import { teacherNav } from './nav'

const route = useRoute()
const sessionId = computed(() => Number(route.params.sessionId || 0))
const navItems = teacherNav('/teacher/classroom')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const session = ref<ClassroomSessionRow | null>(null)
const steps = ref<LessonStepRow[]>([])
const selectedStepId = ref<number | null>(null)
const selectedResourceIndex = ref(0)

const selectedStep = computed(() => steps.value.find((item) => item.id === selectedStepId.value) || steps.value[0] || null)
const currentStep = computed(() => {
  const currentId = session.value?.current_step?.id
  return currentId ? steps.value.find((item) => item.id === currentId) || null : null
})
const activeResources = computed(() => selectedStep.value?.resource_items || [])
const activeQuestions = computed(() => selectedStep.value?.question_items || [])
const activeActivities = computed(() => selectedStep.value?.activity_items || [])
const selectedResource = computed<ResourceBinding | null>(() => {
  if (!activeResources.value.length) return null
  return activeResources.value[Math.min(selectedResourceIndex.value, activeResources.value.length - 1)] || null
})
const selectedStepIndex = computed(() => steps.value.findIndex((item) => item.id === selectedStep.value?.id))
const currentStepIndex = computed(() => steps.value.findIndex((item) => item.id === currentStep.value?.id))
const isCurrentSelected = computed(() => Boolean(selectedStep.value && currentStep.value?.id === selectedStep.value.id))
const canControlStep = computed(() => Boolean(session.value && selectedStep.value && session.value.status !== 'finished'))
const stepStatusText = computed(() => session.value?.current_step_status_label || '未投放')

const classroomStats = computed(() => [
  { label: '班级人数', value: session.value?.class_group?.student_count ?? 0 },
  { label: '学习环节', value: steps.value.length },
  { label: '当前资源', value: activeResources.value.length },
  { label: '当前题目', value: activeQuestions.value.length }
])

function classLabel() {
  const item = session.value?.class_group
  if (!item) return '-'
  return `${item.grade ? `${item.grade} ` : ''}${item.name}`
}

function resourceTitle(resource: ResourceBinding | null) {
  if (!resource) return ''
  return resource.title || resource.attachment_name || '未命名资源'
}

function statusClass(status: string) {
  if (status === 'running' || status === 'open') return 'status-running'
  if (status === 'locked') return 'status-locked'
  if (status === 'finished' || status === 'closed') return 'status-closed'
  return 'status-draft'
}

function stepBadgeClass(step: LessonStepRow) {
  if (currentStep.value?.id !== step.id) return 'status-draft'
  return statusClass(session.value?.current_step_status || 'idle')
}

function stepRunLabel(step: LessonStepRow) {
  if (currentStep.value?.id !== step.id) return '待投放'
  return stepStatusText.value
}

function questionAnswerSummary(question: LessonStepQuestion) {
  if (!question.answer?.length) return '未设置'
  return question.answer.join('、')
}

function scoreNumber(value: number | string | undefined | null, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function questionScoreSummary(question: LessonStepQuestion) {
  const baseScore = scoreNumber(question.score)
  if (!question.use_layer_scores) return `${baseScore} 分`
  const scores = question.layer_scores || { A: question.score, B: question.score, C: question.score }
  return `A:${scoreNumber(scores.A, baseScore)} / B:${scoreNumber(scores.B, baseScore)} / C:${scoreNumber(scores.C, baseScore)}`
}

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : '-'
}

function syncSelectedStep() {
  const currentId = session.value?.current_step?.id
  selectedStepId.value = currentId && steps.value.some((item) => item.id === currentId)
    ? currentId
    : steps.value[0]?.id || null
  selectedResourceIndex.value = 0
}

async function loadPage() {
  loading.value = true
  notice.value = ''
  try {
    const row = await getClassroomSession(sessionId.value)
    session.value = row
    if (row.lesson?.id) {
      steps.value = await getTeacherLessonSteps(row.lesson.id)
    } else {
      steps.value = []
    }
    syncSelectedStep()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂控制台加载失败。'
  } finally {
    loading.value = false
  }
}

async function startSession() {
  if (!session.value) return null
  saving.value = true
  try {
    session.value = await startClassroomSession(session.value.id)
    notice.value = '课堂已开始。'
    return session.value
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂开始失败。'
    return null
  } finally {
    saving.value = false
  }
}

async function finishSession() {
  if (!session.value) return
  const confirmed = window.confirm('确认结束当前课堂？结束后当前环节会关闭，学生端不再继续提交。')
  if (!confirmed) return
  saving.value = true
  try {
    session.value = await finishClassroomSession(session.value.id)
    notice.value = '课堂已结束。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂结束失败。'
  } finally {
    saving.value = false
  }
}

async function restartSession() {
  if (!session.value) return
  const confirmed = window.confirm('确认重新开始当前课堂？当前投放环节会清空，学生端进入课堂后会等待教师重新投放。')
  if (!confirmed) return
  saving.value = true
  try {
    session.value = await restartClassroomSession(session.value.id)
    selectedStepId.value = steps.value[0]?.id || null
    selectedResourceIndex.value = 0
    notice.value = '课堂已重新开始，请选择环节并投放。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂重新开始失败。'
  } finally {
    saving.value = false
  }
}

async function publishSelectedStep() {
  if (!session.value || !selectedStep.value) return
  saving.value = true
  notice.value = ''
  try {
    let activeSession = session.value
    if (activeSession.status === 'draft') {
      activeSession = await startClassroomSession(activeSession.id)
    }
    session.value = await openClassroomStep(activeSession.id, selectedStep.value.id)
    notice.value = `已投放环节：${selectedStep.value.title}`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '环节投放失败。'
  } finally {
    saving.value = false
  }
}

async function lockCurrentStep() {
  if (!session.value) return
  saving.value = true
  try {
    session.value = await lockClassroomStep(session.value.id)
    notice.value = '当前环节已锁定提交。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '锁定提交失败。'
  } finally {
    saving.value = false
  }
}

async function closeCurrentStep() {
  if (!session.value) return
  saving.value = true
  try {
    session.value = await closeClassroomStep(session.value.id)
    notice.value = '当前环节已关闭。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '关闭环节失败。'
  } finally {
    saving.value = false
  }
}

async function publishNextStep() {
  if (!steps.value.length) return
  const baseIndex = currentStepIndex.value >= 0 ? currentStepIndex.value : selectedStepIndex.value
  const next = steps.value[Math.min(baseIndex + 1, steps.value.length - 1)]
  if (!next) return
  selectStep(next)
  await publishSelectedStep()
}

function selectStep(step: LessonStepRow) {
  selectedStepId.value = step.id
  selectedResourceIndex.value = 0
}

onMounted(loadPage)
</script>

<template>
  <AppShell title="课堂控制台" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="loading || !session" class="panel">
      <p class="empty">正在加载课堂控制台</p>
    </section>

    <section v-else class="classroom-console-shell">
      <header class="classroom-console-top classroom-control-header">
        <div>
          <p>{{ session.course?.title || '未绑定课程' }} · {{ session.lesson?.title || '未绑定课时' }} · {{ classLabel() }}</p>
          <h2>{{ session.title }}</h2>
          <span>
            当前环节：{{ currentStep?.title || '未投放' }} · {{ stepStatusText }}
            <template v-if="session.submission_locked"> · 提交已锁定</template>
          </span>
        </div>
        <div class="classroom-live-meta">
          <span class="status-pill" :class="statusClass(session.status)">{{ session.status_label }}</span>
          <span class="status-pill" :class="statusClass(session.current_step_status)">{{ session.current_step_status_label }}</span>
          <span class="status-pill" :class="session.is_layered ? 'status-running' : 'status-draft'">{{ session.is_layered ? '分层课堂' : '普通课堂' }}</span>
          <RouterLink v-if="session.lesson" class="secondary-button" :to="`/teacher/lessons/${session.lesson.id}/design`">
            课时设计
          </RouterLink>
          <button v-if="session.status === 'draft'" class="primary-button" type="button" :disabled="saving" @click="startSession">
            开始课堂
          </button>
          <button v-if="session.status === 'running'" class="primary-button danger" type="button" :disabled="saving" @click="finishSession">
            结束课堂
          </button>
          <button v-if="session.status === 'finished'" class="primary-button" type="button" :disabled="saving" @click="restartSession">
            重新开始
          </button>
        </div>
      </header>

      <div class="classroom-console-grid classroom-control-grid">
        <aside class="console-pane classroom-step-flow">
          <div class="console-pane-header">
            <div>
              <strong>学习过程</strong>
              <span>{{ steps.length }} 个环节</span>
            </div>
          </div>
          <div class="classroom-step-list">
            <button
              v-for="(step, index) in steps"
              :key="step.id"
              class="classroom-step-run"
              :class="{ active: step.id === selectedStepId, live: currentStep?.id === step.id }"
              type="button"
              @click="selectStep(step)"
            >
              <em>{{ index + 1 }}</em>
              <span>
                <strong>{{ step.title }}</strong>
                <small>{{ step.step_type_label }} · {{ step.estimated_minutes }} 分钟 · {{ step.target_layer_label }}</small>
              </span>
              <i :class="stepBadgeClass(step)">{{ stepRunLabel(step) }}</i>
            </button>
            <p v-if="!steps.length" class="empty">该课堂未指定课时，或课时还没有保存已配置环节。</p>
          </div>
        </aside>

        <main class="console-pane current-step-console classroom-stage-pane">
          <div class="console-pane-header">
            <div>
              <strong>{{ selectedStep?.title || '未选择环节' }}</strong>
              <span>
                {{ selectedStep?.step_type_label || '课堂环节' }}
                <template v-if="selectedStepIndex >= 0"> · 第 {{ selectedStepIndex + 1 }} 个环节</template>
              </span>
            </div>
            <div class="classroom-primary-controls">
              <button
                class="primary-button"
                type="button"
                :disabled="saving || !canControlStep"
                @click="publishSelectedStep"
              >
                {{ session.status === 'draft' ? '开始并投放' : isCurrentSelected ? '重新投放' : '投放此环节' }}
              </button>
              <button
                class="secondary-button"
                type="button"
                :disabled="saving || session.current_step_status !== 'open'"
                @click="lockCurrentStep"
              >
                锁定提交
              </button>
              <button
                class="secondary-button"
                type="button"
                :disabled="saving || !session.current_step || session.current_step_status === 'closed'"
                @click="closeCurrentStep"
              >
                关闭环节
              </button>
              <button
                class="secondary-button"
                type="button"
                :disabled="saving || session.status === 'finished' || !steps.length || currentStepIndex >= steps.length - 1"
                @click="publishNextStep"
              >
                下一环节
              </button>
            </div>
          </div>

          <section class="classroom-stage-grid">
            <article class="live-preview-area classroom-resource-stage">
              <header>
                <span>资源预览</span>
                <strong>{{ resourceTitle(selectedResource) || '暂无资源' }}</strong>
              </header>

              <div v-if="activeResources.length > 1" class="student-resource-tabs">
                <button
                  v-for="(resource, index) in activeResources"
                  :key="`${resource.id || resource.title}-${index}`"
                  type="button"
                  :class="{ active: selectedResourceIndex === index }"
                  @click="selectedResourceIndex = index"
                >
                  {{ resourceTitle(resource) }}
                </button>
              </div>

              <div class="classroom-resource-preview">
                <ResourcePreview :resource="selectedResource" office-mode="view" />
              </div>
            </article>

            <aside class="classroom-step-task-panel">
              <header>
                <span>本环节任务</span>
                <strong>{{ activeQuestions.length }} 道题 · {{ activeActivities.length }} 个活动</strong>
              </header>
              <p class="student-instruction">
                {{ selectedStep?.student_instruction || '教师暂未填写学生可见说明。' }}
              </p>

              <div v-if="activeQuestions.length" class="classroom-question-list">
                <article v-for="(question, index) in activeQuestions" :key="question.id">
                  <span>
                    {{ question.question_type_label }} · 面向 {{ question.target_layer_label || '全体' }} ·
                    {{ questionScoreSummary(question) }} · {{ question.is_required ? '必答' : '选答' }}
                  </span>
                  <strong>{{ index + 1 }}. {{ question.stem }}</strong>
                  <small v-if="question.options.length">选项：{{ question.options.join(' / ') }}</small>
                  <small>参考答案：{{ questionAnswerSummary(question) }}</small>
                </article>
              </div>
              <p v-else class="empty">当前环节没有课堂题。</p>

              <div v-if="activeActivities.length" class="classroom-activity-tags">
                <span v-for="activity in activeActivities" :key="activity">{{ activity }}</span>
              </div>
            </aside>
          </section>

          <section class="classroom-control-strip classroom-command-strip">
            <button type="button" disabled>签到</button>
            <button type="button" disabled>随机点名</button>
            <button type="button" disabled>抢答</button>
            <button type="button" disabled>倒计时</button>
            <button type="button" disabled>课堂广播</button>
            <button type="button" disabled>统一打开资源</button>
            <button type="button" disabled>收回答案</button>
          </section>
        </main>

        <aside class="console-pane student-live-pane classroom-live-pane">
          <div class="console-pane-header">
            <div>
              <strong>课堂状态</strong>
              <span>当前为本地轮询前的控制台状态</span>
            </div>
          </div>
          <div class="student-state-summary">
            <div v-for="item in classroomStats" :key="item.label">
              <strong>{{ item.value }}</strong>
              <span>{{ item.label }}</span>
            </div>
          </div>
          <div class="live-message-list classroom-run-log">
            <strong>运行信息</strong>
            <p><span>课堂</span>{{ session.status_label }}，开始时间：{{ formatDateTime(session.started_at) }}</p>
            <p><span>环节</span>{{ currentStep?.title || '未投放' }}，状态：{{ session.current_step_status_label }}</p>
            <p><span>提交</span>{{ session.submission_locked ? '已锁定' : '允许提交' }}</p>
            <p><span>分层</span>{{ session.is_layered ? '已启用，学生端按层级过滤题目和分值' : '未启用，学生端显示当前环节全部题目' }}</p>
            <p><span>说明</span>投放状态已写入课堂 Session。WebSocket 接入后，学生端会按这里的当前环节实时同步。</p>
          </div>
        </aside>
      </div>
    </section>
  </AppShell>
</template>
