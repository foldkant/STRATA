<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  getStudentOnboarding,
  getStudentOnboardingClasses,
  getStudentRequiredPretests,
  saveStudentClass,
  saveStudentPassword,
  type StudentDashboard,
  type StudentRequiredPretest
} from '@/api/student'
import type { ClassGroupRow } from '@/api/management'
import NoticeLine from '@/components/NoticeLine.vue'
import StudentShell from '@/layouts/StudentShell.vue'
import { studentNav } from './nav'

const router = useRouter()
const data = ref<StudentDashboard | null>(null)
const classes = ref<ClassGroupRow[]>([])
const pretestRows = ref<StudentRequiredPretest[]>([])
const selectedClass = ref('')
const password = ref('')
const passwordConfirm = ref('')
const notice = ref('')
const success = ref('')
const errors = ref<FieldErrors>({})
const loading = ref(false)
const savingPassword = ref(false)
const savingClass = ref(false)
const navItems = studentNav('/student')

const profile = computed(() => data.value?.profile || null)
const hasPassword = computed(() => Boolean(profile.value?.password_updated_at))
const hasClass = computed(() => Boolean(profile.value?.class_group))
const incompletePretests = computed(() => pretestRows.value.filter((item) => item.pretest_status.required && !item.pretest_status.completed))
const hasRequiredPretests = computed(() => pretestRows.value.some((item) => item.pretest_status.required))
const pretestsDone = computed(() => hasRequiredPretests.value && incompletePretests.value.length === 0)

const steps = computed(() => [
  { label: '修改密码', done: hasPassword.value },
  { label: '选择班级', done: hasClass.value },
  { label: '完成前测', done: pretestsDone.value || !hasRequiredPretests.value }
])

function classLabel(row: ClassGroupRow) {
  return `${row.grade ? `${row.grade} ` : ''}${row.name}`
}

function fieldError(name: string) {
  return errors.value[name]?.[0] || ''
}

async function loadPage() {
  loading.value = true
  notice.value = ''
  try {
    const [dashboard, classRows, requiredRows] = await Promise.all([
      getStudentOnboarding(),
      getStudentOnboardingClasses(),
      getStudentRequiredPretests()
    ])
    data.value = dashboard
    classes.value = classRows
    pretestRows.value = requiredRows
    selectedClass.value = dashboard.profile.class_group ? String(dashboard.profile.class_group.id) : ''
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '首次使用信息加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitPassword() {
  errors.value = {}
  notice.value = ''
  success.value = ''
  if (password.value.length < 6 || password.value.length > 32 || /\s/.test(password.value)) {
    errors.value = { password: ['密码需为 6-32 位，不能包含空格。'] }
    return
  }
  if (password.value !== passwordConfirm.value) {
    errors.value = { password_confirm: ['两次输入的密码不一致。'] }
    return
  }
  savingPassword.value = true
  try {
    const updatedProfile = await saveStudentPassword(password.value)
    if (data.value) data.value.profile = updatedProfile
    password.value = ''
    passwordConfirm.value = ''
    success.value = '密码已更新。'
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = '密码更新失败。'
    }
  } finally {
    savingPassword.value = false
  }
}

async function submitClass() {
  errors.value = {}
  notice.value = ''
  success.value = ''
  if (!selectedClass.value) {
    errors.value = { class_group: ['请选择班级。'] }
    return
  }
  savingClass.value = true
  try {
    const updatedProfile = await saveStudentClass(selectedClass.value)
    if (data.value) data.value.profile = updatedProfile
    success.value = '班级已选择。'
    await loadPage()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = '班级保存失败。'
    }
  } finally {
    savingClass.value = false
  }
}

onMounted(loadPage)
</script>

<template>
  <StudentShell title="首次使用" subtitle="完成基础设置后进入课程学习" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <NoticeLine v-if="success" :message="success" tone="success" />

    <section v-if="loading || !data" class="student-panel">
      <p class="empty">正在加载首次使用流程</p>
    </section>

    <template v-else>
      <section class="student-onboarding-steps">
        <article v-for="(step, index) in steps" :key="step.label" :class="{ done: step.done }">
          <em>{{ index + 1 }}</em>
          <span>{{ step.label }}</span>
          <strong>{{ step.done ? '已完成' : '待完成' }}</strong>
        </article>
      </section>

      <section class="student-onboarding-grid">
        <article class="student-panel student-form-panel">
          <header>
            <h2>修改密码</h2>
            <p>学生密码允许使用课堂便捷密码，但首次登录必须自己修改一次。</p>
          </header>
          <label>
            <span>新密码</span>
            <input v-model="password" type="password" autocomplete="new-password" placeholder="6-32 位，不能包含空格" />
            <small v-if="fieldError('password')" class="field-error">{{ fieldError('password') }}</small>
          </label>
          <label>
            <span>确认密码</span>
            <input v-model="passwordConfirm" type="password" autocomplete="new-password" placeholder="再次输入新密码" />
            <small v-if="fieldError('password_confirm')" class="field-error">{{ fieldError('password_confirm') }}</small>
          </label>
          <button class="student-primary-action" type="button" :disabled="savingPassword" @click="submitPassword">
            保存密码
          </button>
        </article>

        <article class="student-panel student-form-panel">
          <header>
            <h2>选择班级</h2>
            <p>如果学号还没有确定，可以先选班级，学号后续由学校管理员批量更新。</p>
          </header>
          <label>
            <span>我的班级</span>
            <select v-model="selectedClass">
              <option value="">请选择班级</option>
              <option v-for="row in classes" :key="row.id" :value="String(row.id)">{{ classLabel(row) }}</option>
            </select>
            <small v-if="fieldError('class_group')" class="field-error">{{ fieldError('class_group') }}</small>
          </label>
          <button class="student-primary-action" type="button" :disabled="savingClass" @click="submitClass">保存班级</button>
        </article>

        <article class="student-panel student-form-panel span-2">
          <header>
            <h2>学科前测</h2>
            <p>进入某个学科课程前，需要完成该学科当前发布的素养测试和学习态度问卷。</p>
          </header>
          <div class="student-pretest-summary">
            <RouterLink
              v-for="row in pretestRows"
              :key="row.subject.id"
              :to="`/student/pretests/${row.subject.id}`"
              :class="{ done: row.pretest_status.completed, warn: row.pretest_status.required && !row.pretest_status.completed }"
            >
              <strong>{{ row.subject.name }}</strong>
              <span v-if="row.pretest_status.required && !row.pretest_status.completed">
                待完成 {{ row.pretest_status.missing.length }} 套
              </span>
              <span v-else-if="row.pretest_status.required">已完成</span>
              <span v-else>暂无发布前测</span>
            </RouterLink>
            <p v-if="!pretestRows.length" class="empty">当前学校暂无启用学科。</p>
          </div>
          <footer>
            <button class="student-ghost-button" type="button" @click="router.push('/student')">进入首页</button>
          </footer>
        </article>
      </section>
    </template>
  </StudentShell>
</template>
