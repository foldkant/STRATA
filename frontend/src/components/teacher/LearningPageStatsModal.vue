<script setup lang="ts">
import { computed } from 'vue'
import type { LearningPageResponseSummary } from '@/api/learningPages'
import { barOption } from '@/utils/chartOptions'
import EChartPanel from '@/components/EChartPanel.vue'

const props = defineProps<{
  open: boolean
  loading: boolean
  stats: LearningPageResponseSummary | null
  fallbackTitle?: string
}>()

const emit = defineEmits<{
  close: []
  refresh: []
}>()

const isClassroomScope = computed(() => Boolean(props.stats?.scope))
const completionRate = computed(() => Number(props.stats?.summary.completion_rate || 0))
const completionStyle = computed(() => ({ width: `${Math.min(Math.max(completionRate.value, 0), 100)}%` }))
const summaryCards = computed(() => {
  const summary = props.stats?.summary
  if (!summary) return []
  if (isClassroomScope.value) {
    return [
      { label: '班级人数', value: summary.class_student_count || 0 },
      { label: '已完成', value: summary.completed_student_count || 0 },
      { label: '进行中', value: summary.started_student_count || 0 },
      { label: '未开始', value: summary.pending_student_count || 0 },
    ]
  }
  return [
    { label: '提交学生', value: summary.student_count },
    { label: '提交次数', value: summary.submission_count },
    { label: '表单数量', value: summary.form_count },
  ]
})

function formatDate(value: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function studentStatusClass(status: string) {
  if (status === 'completed') return 'status-active'
  if (status === 'started') return 'status-draft'
  return 'status-disabled'
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" role="presentation" @click.self="emit('close')">
      <section class="entity-modal learning-page-stats-modal" role="dialog" aria-modal="true" aria-labelledby="learning-page-stats-title">
        <header class="modal-header">
          <div>
            <h2 id="learning-page-stats-title">AI 学习任务单完成情况</h2>
            <p>
              {{ stats?.page.title || fallbackTitle || '学习任务单' }}
              <template v-if="stats?.scope"> · {{ stats.scope.class_group.name }} · {{ stats.scope.classroom_session.title }}</template>
            </p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>

        <div v-if="loading && !stats" class="learning-page-stats-body"><p class="empty">正在加载完成情况...</p></div>
        <div v-else-if="stats" class="learning-page-stats-body">
          <div class="learning-page-stat-summary" :class="{ classroom: isClassroomScope }">
            <article v-for="item in summaryCards" :key="item.label">
              <strong>{{ item.value }}</strong>
              <span>{{ item.label }}</span>
            </article>
          </div>

          <section v-if="isClassroomScope" class="learning-page-classroom-progress">
            <header>
              <div><strong>课堂完成率</strong><span>{{ stats.summary.completed_student_count || 0 }}/{{ stats.summary.class_student_count || 0 }} 人</span></div>
              <b>{{ completionRate }}%</b>
            </header>
            <div><span :style="completionStyle"></span></div>
          </section>

          <section v-if="isClassroomScope" class="learning-page-student-progress">
            <header><strong>学生进度</strong><span>{{ stats.students?.length || 0 }} 人</span></header>
            <div class="question-progress-table-wrap">
              <table>
                <thead><tr><th>学生</th><th>状态</th><th>已交表单</th><th>提交次数</th><th>最近提交</th></tr></thead>
                <tbody>
                  <tr v-for="row in stats.students || []" :key="row.student.id">
                    <td><strong>{{ row.student.display_name || row.student.username }}</strong><small>{{ row.student_no || row.student.username }}</small></td>
                    <td><span class="status-pill" :class="studentStatusClass(row.status)">{{ row.status_label }}</span></td>
                    <td>{{ row.submitted_form_count }}/{{ row.form_count }}</td>
                    <td>{{ row.submission_count }}</td>
                    <td>{{ formatDate(row.last_submitted_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-for="form in stats.forms" :key="form.form_id" class="learning-page-form-stats">
            <header><div><strong>{{ form.title }}</strong><span>{{ form.student_count }} 人 · {{ form.submission_count }} 次</span></div></header>
            <div class="learning-page-field-stats-grid">
              <article v-for="field in form.fields" :key="field.id" class="learning-page-field-stat">
                <header><strong>{{ field.label }}</strong><span>{{ field.stats.answered }} 份回答</span></header>
                <EChartPanel
                  v-if="field.stats.options"
                  :title="field.label"
                  :total="field.stats.answered"
                  :option="barOption(field.stats.options, true)"
                />
                <div v-else-if="field.type === 'number'" class="learning-page-number-stats">
                  <span>平均 <strong>{{ field.stats.average ?? '-' }}</strong></span>
                  <span>最小 <strong>{{ field.stats.min ?? '-' }}</strong></span>
                  <span>最大 <strong>{{ field.stats.max ?? '-' }}</strong></span>
                </div>
                <div v-else class="learning-page-text-responses">
                  <p v-for="item in field.stats.recent || []" :key="`${item.student}-${item.submitted_at}`">
                    <strong>{{ item.student }}</strong><span>{{ item.value }}</span><small>{{ formatDate(item.submitted_at) }}</small>
                  </p>
                  <p v-if="!(field.stats.recent || []).length" class="empty">暂无回答</p>
                </div>
              </article>
            </div>
          </section>
        </div>
        <div v-else class="learning-page-stats-body"><p class="empty">暂无统计数据。</p></div>

        <footer class="modal-actions learning-page-stats-actions">
          <button class="secondary-button" type="button" :disabled="loading" @click="emit('refresh')">{{ loading ? '刷新中...' : '刷新' }}</button>
          <button class="primary-button" type="button" @click="emit('close')">关闭</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
