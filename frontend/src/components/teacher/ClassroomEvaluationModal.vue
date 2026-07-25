<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  ClassroomEvaluationCriterion,
  ClassroomEvaluationPayload,
  ClassroomEvaluationStudentRow,
  ClassroomEvaluationSummaryItem,
  ClassroomEvaluationType
} from '@/api/teacher'
import EvaluationRatingInput from '@/components/evaluation/EvaluationRatingInput.vue'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'
import '@/styles/teacher-classroom-evaluation.css'

export type EvaluationSummaryRow = {
  type: ClassroomEvaluationType
  label: string
  summary: ClassroomEvaluationSummaryItem | null
  criteria: ClassroomEvaluationCriterion[]
}

const props = defineProps<{
  open: boolean
  sessionTitle: string
  classLabel: string
  loading: boolean
  notice?: string
  lessonDesignPath?: string
  runtimeEnabled: boolean
  enabledCount: number
  summaryItems: EvaluationSummaryRow[]
  data: ClassroomEvaluationPayload | null
  enableTeacher: boolean
  selectedStudentId: number | null
  selectedStudent: ClassroomEvaluationStudentRow | null
  teacherCriteria: ClassroomEvaluationCriterion[]
  ratings: Record<string, number>
  notAssessed: Record<string, EvaluationNotAssessedEntry>
  comment: string
}>()

const studentQuery = ref('')
const teacherReady = computed(() => props.enableTeacher && props.teacherCriteria.length > 0)
const filteredStudents = computed(() => {
  const keyword = studentQuery.value.trim().toLocaleLowerCase()
  const students = props.data?.students || []
  if (!keyword) return students
  return students.filter((row) => (
    [
      row.student.display_name,
      row.student.username,
      row.profile?.student_no
    ]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase().includes(keyword))
  ))
})

watch(() => props.open, (open) => {
  if (open) studentQuery.value = ''
})

const emit = defineEmits<{
  close: []
  refresh: []
  toggleRuntime: [enabled: boolean]
  selectStudent: [studentId: number]
  rating: [criterionId: string, value: number]
  notAssessed: [criterionId: string, value: EvaluationNotAssessedEntry | null]
  'update:comment': [value: string]
  submit: []
  prepareStep: [stepId: number]
}>()

function ratingAverageText(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : `${Number(value).toFixed(1)} 星`
}

function forwardRating(criterionId: string, value: number) {
  emit('rating', criterionId, value)
}

function forwardNotAssessed(criterionId: string, value: EvaluationNotAssessedEntry | null) {
  emit('notAssessed', criterionId, value)
}
</script>

<template>
  <div v-if="open" class="modal-backdrop classroom-evaluation-backdrop" role="presentation" @click.self="emit('close')">
    <section
      class="entity-modal classroom-evaluation-modal runtime-evaluation-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="classroom-evaluation-title"
      :aria-busy="loading"
    >
      <header class="modal-header">
        <div>
          <h2 id="classroom-evaluation-title">课堂评价情况</h2>
          <p>{{ sessionTitle }} · {{ classLabel }} · 评价内容来自课时设计</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" :disabled="loading" @click="emit('close')">×</button>
      </header>

      <div class="classroom-evaluation-body runtime-evaluation-body">
        <section class="evaluation-summary-panel runtime-evaluation-overview">
          <header class="evaluation-section-head runtime-evaluation-section-head">
            <div>
              <span>课堂评价进度</span>
              <strong>查看开启状态与完成情况</strong>
            </div>
            <button class="secondary-button mini" type="button" :disabled="loading" @click="emit('refresh')">刷新</button>
          </header>
          <p v-if="notice" class="classroom-evaluation-notice" role="alert">{{ notice }}</p>
          <section
            v-if="!runtimeEnabled && data?.availability && !data.availability.can_enable"
            class="evaluation-availability-card"
            role="alert"
          >
            <div>
              <span>当前不能开启</span>
              <strong>{{ data.availability.reason }}</strong>
              <p>{{ data.availability.recovery }}</p>
            </div>
            <dl>
              <div><dt>当前课堂环节</dt><dd>{{ data.availability.current_step?.title || '尚未投放' }}</dd></div>
              <div><dt>已设置评价的环节</dt><dd>{{ data.availability.bound_steps.map((item) => item.title).join('、') || '暂无' }}</dd></div>
            </dl>
            <div class="evaluation-recovery-actions">
              <RouterLink v-if="lessonDesignPath" class="primary-button mini" :to="lessonDesignPath">为当前环节设置评价</RouterLink>
              <button
                v-if="data.availability.reason_code === 'current_step_unbound' && data.availability.bound_steps.length"
                class="secondary-button mini"
                type="button"
                @click="emit('prepareStep', data.availability!.bound_steps[0].id)"
              >
                定位到“{{ data.availability.bound_steps[0].title }}”环节
              </button>
            </div>
          </section>
          <div class="evaluation-runtime-switch-card" :class="{ active: runtimeEnabled }">
            <div>
              <span>{{ runtimeEnabled ? '课堂评价已开启' : '课堂评价未开启' }}</span>
              <strong>{{ runtimeEnabled ? `${enabledCount} 类评价已开放` : '默认关闭' }}</strong>
            </div>
            <button
              class="primary-button mini"
              type="button"
              :class="{ danger: runtimeEnabled }"
              :disabled="loading || (!runtimeEnabled && data?.availability && !data.availability.can_enable)"
              :aria-pressed="runtimeEnabled"
              @click="emit('toggleRuntime', !runtimeEnabled)"
            >
              {{ runtimeEnabled ? '关闭评价' : '开启评价' }}
            </button>
          </div>
          <div class="evaluation-summary-grid">
            <article v-for="item in summaryItems" :key="item.type">
              <span>{{ item.label }}{{ item.summary?.enabled ? ' · 已配置' : ' · 未配置' }}</span>
              <strong>{{ item.summary?.submitted || 0 }}/{{ item.summary?.total || 0 }}</strong>
              <small>
                已评分 {{ item.summary?.rated_item_count || 0 }}/{{ item.summary?.total_item_count || 0 }} 项
                <template v-if="item.summary?.not_assessed_item_count"> · 暂不评价 {{ item.summary.not_assessed_item_count }} 项</template>
                · 平均 {{ ratingAverageText(item.summary?.average) }}
              </small>
            </article>
          </div>

          <div class="runtime-evaluation-criteria-list" aria-label="本环节评价项">
            <details v-for="item in summaryItems" :key="`criteria-${item.type}`" :open="Boolean(item.criteria.length)">
              <summary>
                <strong>{{ item.label }}评价项</strong>
                <span>{{ item.criteria.length }} 项</span>
              </summary>
              <div class="runtime-evaluation-criteria-content">
                <article v-for="criterion in item.criteria" :key="criterion.id">
                  <strong>{{ criterion.title }}</strong>
                  <small>{{ criterion.description || '未填写观察说明。' }}</small>
                </article>
                <p v-if="!item.criteria.length" class="empty">未在课时设计中设置{{ item.label }}评价项。</p>
              </div>
            </details>
          </div>
        </section>

        <section class="teacher-evaluation-panel">
          <header class="evaluation-section-head teacher-evaluation-panel-head">
            <div>
              <span>教师评价</span>
              <strong>{{ teacherReady ? '选择学生并记录课堂表现' : '本环节尚未设置教师评价' }}</strong>
            </div>
            <small v-if="teacherReady">{{ filteredStudents.length }} 名学生</small>
          </header>

          <section v-if="!teacherReady" class="teacher-evaluation-setup">
            <div>
              <span>需要先完成课时设计</span>
              <strong>为当前教学环节设置教师评价项</strong>
              <p>评价项确定后，课堂中才会显示学生名单、表现水平和课堂观察记录。</p>
            </div>
            <RouterLink v-if="lessonDesignPath" class="primary-button" :to="lessonDesignPath">前往课时设计</RouterLink>
          </section>

          <div v-else class="teacher-evaluation-layout">
            <aside class="teacher-evaluation-student-column" aria-label="学生名单">
              <label class="teacher-evaluation-student-search">
                <span>查找学生</span>
                <input v-model="studentQuery" type="search" placeholder="输入姓名或学号" autocomplete="off" />
              </label>
              <div class="teacher-evaluation-student-list">
                <button
                  v-for="row in filteredStudents"
                  :key="row.student.id"
                  type="button"
                  :class="{ active: selectedStudentId === row.student.id }"
                  :aria-pressed="selectedStudentId === row.student.id"
                  @click="emit('selectStudent', row.student.id)"
                >
                  <strong>{{ row.student.display_name || row.student.username }}</strong>
                  <span>
                    {{ row.profile?.student_no || row.student.username }}
                    <template v-if="row.peer_submission_count"> · 互评 {{ row.peer_submission_count }}</template>
                    <template v-if="row.teacher_submission"> · 已师评</template>
                  </span>
                </button>
                <p v-if="!filteredStudents.length" class="empty">
                  {{ (data?.students || []).length ? '没有找到符合条件的学生。' : '当前班级暂无学生。' }}
                </p>
              </div>
            </aside>

            <div class="teacher-evaluation-form">
              <template v-if="selectedStudent">
                <div class="teacher-evaluation-target">
                  <div>
                    <span>当前评价学生</span>
                    <strong>{{ selectedStudent.student.display_name || selectedStudent.student.username }}</strong>
                  </div>
                  <span>
                    自评：{{ selectedStudent.self_submission ? '已提交' : '未提交' }} ·
                    互评平均：{{ ratingAverageText(selectedStudent.peer_average) }}
                  </span>
                </div>
                <div class="evaluation-star-list">
                  <EvaluationRatingInput
                    v-for="criterion in teacherCriteria"
                    :key="criterion.id"
                    :criterion="criterion"
                    :rating="ratings[criterion.id] || 0"
                    :not-assessed="notAssessed[criterion.id] || null"
                    :disabled="loading"
                    @rating="forwardRating"
                    @not-assessed="forwardNotAssessed"
                  />
                </div>
                <label class="evaluation-comment-box">
                  <span>课堂观察记录</span>
                  <textarea
                    :value="comment"
                    maxlength="1000"
                    rows="3"
                    placeholder="可选，记录学生的具体表现或后续教学建议。"
                    @input="emit('update:comment', ($event.target as HTMLTextAreaElement).value)"
                  ></textarea>
                </label>
              </template>
              <section v-else class="teacher-evaluation-empty">
                <strong>请先从左侧选择一名学生</strong>
                <p>选择后可查看对应评价项，并记录本次课堂中的可观察表现。</p>
              </section>
            </div>
          </div>
        </section>
      </div>

      <footer class="modal-actions evaluation-modal-actions">
        <span>评价内容在课时设计中维护；材料不足时请选择“暂不评价”。</span>
        <button class="secondary-button" type="button" :disabled="loading" @click="emit('close')">关闭</button>
        <button class="primary-button" type="button" :disabled="loading || !selectedStudent || !teacherReady" @click="emit('submit')">
          保存师评
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.classroom-evaluation-notice {
  margin: 0;
  border-left: 4px solid #dc2626;
  padding: 10px 12px;
  background: #fff1f2;
  color: #9f1239;
  line-height: 1.55;
}

.evaluation-availability-card {
  display: grid;
  gap: 12px;
  border: 1px solid #fbbf24;
  border-radius: 8px;
  padding: 14px;
  background: #fffbeb;
}

.evaluation-availability-card > div:first-child {
  display: grid;
  gap: 4px;
}

.evaluation-availability-card > div:first-child > span {
  color: #b45309;
  font-size: 12px;
  font-weight: 800;
}

.evaluation-availability-card p {
  margin: 0;
  color: #78350f;
  line-height: 1.55;
}

.evaluation-availability-card dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.evaluation-availability-card dl div {
  display: grid;
  gap: 3px;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 9px 10px;
  background: #fff;
}

.evaluation-availability-card dt {
  color: #92400e;
  font-size: 12px;
}

.evaluation-availability-card dd {
  margin: 0;
  font-weight: 700;
}

.evaluation-recovery-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.evaluation-recovery-actions a {
  text-decoration: none;
}

@media (max-width: 760px) {
  .evaluation-availability-card dl {
    grid-template-columns: 1fr;
  }

  .evaluation-recovery-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
