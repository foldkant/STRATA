<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import { getStudentClassroom, type StudentClassroom, type StudentResourceBinding } from '@/api/student'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const route = useRoute()
const router = useRouter()
const classroomId = computed(() => Number(route.params.sessionId || 0))
const classroom = ref<StudentClassroom | null>(null)
const selectedResourceIndex = ref(0)
const notice = ref('')
const loading = ref(false)
const navItems = studentNav('/student')

const currentStep = computed(() => classroom.value?.current_step || null)
const currentResources = computed(() => currentStep.value?.resource_items || [])
const currentQuestions = computed(() => currentStep.value?.question_items || [])
const selectedResource = computed<StudentResourceBinding | null>(() => {
  if (!currentResources.value.length) return null
  return currentResources.value[Math.min(selectedResourceIndex.value, currentResources.value.length - 1)] || null
})

function formatDate(value: string | null) {
  if (!value) return '未开始'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function resourceTitle(resource: StudentResourceBinding | null) {
  if (!resource) return ''
  return resource.title || resource.attachment_name || '未命名资源'
}

async function loadPage() {
  loading.value = true
  notice.value = ''
  try {
    classroom.value = await getStudentClassroom(classroomId.value)
    selectedResourceIndex.value = 0
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂信息加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(loadPage)
</script>

<template>
  <StudentShell title="课堂学习" subtitle="跟随教师课堂节奏" :nav-items="navItems">
    <template #actions>
      <button class="student-ghost-button" type="button" @click="router.back()">返回</button>
    </template>

    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="loading" class="student-panel">
      <p class="empty">正在加载课堂</p>
    </section>

    <section v-else-if="!classroom" class="student-panel">
      <p class="empty">课堂尚未开放，请等待教师开始课堂。</p>
    </section>

    <section v-else class="student-classroom-panel live-classroom-workspace">
      <article class="live-classroom-head">
        <div>
          <span>{{ classroom.status_label }} · {{ classroom.current_step_status_label }}{{ classroom.is_layered ? ' · 分层课堂' : '' }}</span>
          <strong>{{ classroom.title }}</strong>
        </div>
        <p>
          {{ classroom.teacher.display_name }} · {{ classroom.course?.title || '未绑定课程' }} ·
          {{ classroom.lesson?.title || '未指定课时' }}
        </p>
        <small>开始时间：{{ formatDate(classroom.started_at) }}</small>
      </article>

      <article v-if="!currentStep" class="student-panel student-classroom-note">
        <h2>等待教师投放环节</h2>
        <p>课堂已经开始，但教师还没有投放学习环节。请保持当前页面，后续会接入实时同步自动刷新。</p>
      </article>

      <section v-else class="student-workspace-grid student-classroom-step-grid">
        <article class="student-resource-pane">
          <header>
            <div>
              <span>当前资源</span>
              <h2>{{ currentStep.title }}</h2>
            </div>
            <small>{{ currentStep.step_type_label }} · {{ currentStep.estimated_minutes }} 分钟</small>
          </header>

          <div v-if="currentResources.length > 1" class="student-resource-tabs">
            <button
              v-for="(resource, index) in currentResources"
              :key="`${resource.id || resource.title}-${index}`"
              type="button"
              :class="{ active: selectedResourceIndex === index }"
              @click="selectedResourceIndex = index"
            >
              {{ resourceTitle(resource) }}
            </button>
          </div>

          <div class="student-preview-stage">
            <ResourcePreview :resource="selectedResource" office-mode="view" />
          </div>
        </article>

        <aside class="student-step-pane">
          <section class="student-step-detail">
            <header>
              <div>
                <span>本环节任务</span>
                <h2>{{ currentStep.title }}</h2>
              </div>
              <small>
                {{ classroom.current_step_status_label }}{{ classroom.submission_locked ? ' · 提交已锁定' : '' }}{{ classroom.is_layered ? ' · 已按层级匹配' : '' }}
              </small>
            </header>
            <p class="student-instruction">
              {{ currentStep.student_instruction || '教师暂未填写学生可见说明。' }}
            </p>

            <div v-if="currentQuestions.length" class="student-lesson-question-list">
              <section v-for="(question, index) in currentQuestions" :key="question.id" class="student-lesson-question-card">
                <header>
                  <span>{{ question.question_type_label }}{{ question.is_required ? ' · 必答' : ' · 选答' }}</span>
                  <small>{{ question.score }} 分</small>
                </header>
                <h3>{{ index + 1 }}. {{ question.stem }}</h3>
                <div v-if="question.options.length" class="student-option-list readonly-options">
                  <label v-for="option in question.options" :key="`${question.id}-${option}`">
                    <input disabled type="radio" />
                    <span>{{ option }}</span>
                  </label>
                </div>
              </section>
            </div>
            <p v-else class="empty">当前环节没有课堂题。</p>
          </section>
        </aside>
      </section>
    </section>
  </StudentShell>
</template>
