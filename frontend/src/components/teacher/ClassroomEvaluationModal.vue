<script setup lang="ts">
import type {
  ClassroomEvaluationCriterion,
  ClassroomEvaluationPayload,
  ClassroomEvaluationStudentRow,
  ClassroomEvaluationSummaryItem,
  ClassroomEvaluationType
} from '@/api/teacher'
import EvaluationRatingInput from '@/components/evaluation/EvaluationRatingInput.vue'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'

export type EvaluationSummaryRow = {
  type: ClassroomEvaluationType
  label: string
  summary: ClassroomEvaluationSummaryItem | null
  criteria: ClassroomEvaluationCriterion[]
}

defineProps<{
  open: boolean
  sessionTitle: string
  classLabel: string
  loading: boolean
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

const emit = defineEmits<{
  close: []
  refresh: []
  toggleRuntime: [enabled: boolean]
  selectStudent: [studentId: number]
  rating: [criterionId: string, value: number]
  notAssessed: [criterionId: string, value: EvaluationNotAssessedEntry | null]
  'update:comment': [value: string]
  submit: []
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
          <header class="evaluation-section-head">
            <div>
              <span>完成情况</span>
              <strong>按 5 星评价统计</strong>
            </div>
            <button class="secondary-button mini" type="button" :disabled="loading" @click="emit('refresh')">刷新</button>
          </header>
          <div class="evaluation-runtime-switch-card" :class="{ active: runtimeEnabled }">
            <div>
              <span>{{ runtimeEnabled ? '课堂评价已开启' : '课堂评价未开启' }}</span>
              <strong>{{ runtimeEnabled ? `${enabledCount} 类评价已开放` : '默认关闭' }}</strong>
            </div>
            <button
              class="primary-button mini"
              type="button"
              :class="{ danger: runtimeEnabled }"
              :disabled="loading"
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

          <div class="runtime-evaluation-criteria-list">
            <section v-for="item in summaryItems" :key="`criteria-${item.type}`">
              <header>
                <strong>{{ item.label }}评价项</strong>
                <span>{{ item.criteria.length }} 项</span>
              </header>
              <article v-for="criterion in item.criteria" :key="criterion.id">
                <strong>{{ criterion.title }}</strong>
                <small>{{ criterion.description || '未填写观察说明。' }}</small>
              </article>
              <p v-if="!item.criteria.length" class="empty">未在课时设计中设置{{ item.label }}评价项。</p>
            </section>
          </div>
        </section>

        <section class="teacher-evaluation-panel">
          <header class="evaluation-section-head">
            <div>
              <span>师评</span>
              <strong>选择学生后填写星级或暂不评价</strong>
            </div>
          </header>
          <div class="teacher-evaluation-layout">
            <div class="teacher-evaluation-student-list">
              <button
                v-for="row in data?.students || []"
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
              <p v-if="!(data?.students || []).length" class="empty">当前班级暂无学生。</p>
            </div>

            <div class="teacher-evaluation-form">
              <p v-if="!enableTeacher" class="evaluation-warning">师评未在课时设计中开启，课堂内不能填写师评。</p>
              <template v-if="selectedStudent">
                <div class="teacher-evaluation-target">
                  <strong>{{ selectedStudent.student.display_name || selectedStudent.student.username }}</strong>
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
                  <p v-if="!teacherCriteria.length" class="empty">请先回到课时设计设置师评评价项。</p>
                </div>
                <label class="evaluation-comment-box">
                  <span>师评备注</span>
                  <textarea
                    :value="comment"
                    maxlength="1000"
                    rows="3"
                    placeholder="可选，记录课堂观察或后续辅导建议。"
                    @input="emit('update:comment', ($event.target as HTMLTextAreaElement).value)"
                  ></textarea>
                </label>
              </template>
            </div>
          </div>
        </section>
      </div>

      <footer class="modal-actions evaluation-modal-actions">
        <span>评价内容在课时设计中维护；没有足够材料时选择暂不评价。</span>
        <button class="secondary-button" type="button" :disabled="loading" @click="emit('close')">关闭</button>
        <button class="primary-button" type="button" :disabled="loading || !selectedStudent || !enableTeacher" @click="emit('submit')">
          保存师评
        </button>
      </footer>
    </section>
  </div>
</template>
