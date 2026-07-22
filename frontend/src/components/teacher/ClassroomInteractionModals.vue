<script setup lang="ts">
import type {
  AttendanceStatus,
  ClassroomActivityRow,
  ClassroomAttendancePayload,
  ClassroomAttendanceRow,
  QuickAnswerPayload,
  QuickAnswerRow,
  RandomPickPayload,
  RandomPickPreviewPayload,
  RandomPickStudentRow
} from '@/api/teacher'

type AttendanceFilter = AttendanceStatus | 'all'
type AttendanceAction = { status: Exclude<AttendanceStatus, 'not_signed'>; label: string }

defineProps<{
  sessionTitle: string
  classLabel: string
  attendanceOpen: boolean
  attendanceLoading: boolean
  attendanceActivity: ClassroomActivityRow | null
  attendanceData: ClassroomAttendancePayload | null
  attendanceFilter: AttendanceFilter
  attendanceRows: ClassroomAttendanceRow[]
  attendanceActions: AttendanceAction[]
  quickAnswerOpen: boolean
  quickAnswerLoading: boolean
  quickAnswerActivity: ClassroomActivityRow | null
  quickAnswerData: QuickAnswerPayload | null
  randomPickOpen: boolean
  randomPickLoading: boolean
  randomPickActivity: ClassroomActivityRow | null
  randomPickData: RandomPickPayload | RandomPickPreviewPayload | null
  randomPickAnimating: boolean
  randomPickStudents: RandomPickStudentRow[]
  randomPickCurrentStudentId: number | null
  randomPickPickedStudent: RandomPickStudentRow | null
  randomPickDisplayStudent: RandomPickStudentRow | null
}>()

const emit = defineEmits<{
  'update:attendanceFilter': [value: AttendanceFilter]
  closeAttendance: []
  refreshAttendance: [activity: ClassroomActivityRow]
  closeActivity: [activity: ClassroomActivityRow]
  markAttendance: [row: ClassroomAttendanceRow, status: Exclude<AttendanceStatus, 'not_signed'>]
  closeQuickAnswer: []
  scoreQuickAnswer: [row: QuickAnswerRow, action: 'plus' | 'minus']
  closeRandomPick: []
  startRandomPick: []
  scoreRandomPick: [action: 'plus' | 'minus']
}>()

const attendanceFilters: Array<{ value: AttendanceFilter; label: string; summaryKey: keyof ClassroomAttendancePayload['summary'] }> = [
  { value: 'all', label: '全部', summaryKey: 'total' },
  { value: 'signed', label: '已签到', summaryKey: 'signed' },
  { value: 'late', label: '迟到', summaryKey: 'late' },
  { value: 'leave', label: '请假', summaryKey: 'leave' },
  { value: 'absent', label: '缺勤', summaryKey: 'absent' },
  { value: 'not_signed', label: '未签到', summaryKey: 'not_signed' }
]

const quickAnswerScoreActions = [
  { action: 'plus', label: '加分' },
  { action: 'minus', label: '减分' }
] as const

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

function attendanceStatusClass(status: AttendanceStatus) {
  if (status === 'signed') return 'status-active'
  if (status === 'late') return 'status-warning'
  if (status === 'leave') return 'status-locked'
  if (status === 'absent') return 'status-closed'
  return 'status-disabled'
}

function quickAnswerScoreClass(row: QuickAnswerRow) {
  if (row.score_action === 'plus') return 'status-active'
  if (row.score_action === 'minus') return 'status-closed'
  return 'status-disabled'
}

function scoreText(row: Pick<QuickAnswerRow | RandomPickStudentRow, 'score'>) {
  if (row.score === null || row.score === undefined) return '未评分'
  return row.score > 0 ? `+${row.score}` : String(row.score)
}

function randomPickScoreClass(row: RandomPickStudentRow | null) {
  if (!row || row.score === null || row.score === undefined) return 'status-disabled'
  if (row.score_action === 'plus' || row.score > 0) return 'status-active'
  if (row.score_action === 'minus' || row.score < 0) return 'status-closed'
  return 'status-disabled'
}
</script>

<template>
  <div v-if="attendanceOpen && attendanceActivity" class="modal-backdrop" role="presentation" @click.self="emit('closeAttendance')">
    <section class="entity-modal attendance-modal" role="dialog" aria-modal="true" aria-labelledby="attendance-title" :aria-busy="attendanceLoading">
      <header class="modal-header">
        <div>
          <h2 id="attendance-title">课堂签到</h2>
          <p>{{ sessionTitle }} · {{ classLabel }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('closeAttendance')">×</button>
      </header>

      <div class="attendance-summary-grid">
        <button
          v-for="item in attendanceFilters"
          :key="item.value"
          type="button"
          :class="{ active: attendanceFilter === item.value }"
          :aria-pressed="attendanceFilter === item.value"
          @click="emit('update:attendanceFilter', item.value)"
        >
          <strong>{{ attendanceData?.summary[item.summaryKey] || 0 }}</strong>
          <span>{{ item.label }}</span>
        </button>
      </div>

      <div class="attendance-toolbar">
        <span>{{ attendanceActivity.status_label }} · {{ formatDateTime(attendanceActivity.opened_at) }}</span>
        <div>
          <button class="secondary-button mini" type="button" :disabled="attendanceLoading" @click="emit('refreshAttendance', attendanceActivity)">刷新名单</button>
          <button class="secondary-button mini" type="button" :disabled="attendanceLoading" @click="emit('closeActivity', attendanceActivity); emit('closeAttendance')">关闭签到</button>
        </div>
      </div>

      <div class="attendance-table-wrap">
        <table>
          <thead><tr><th>学生</th><th>账号</th><th>学号</th><th>层级</th><th>状态</th><th>时间/备注</th><th>手工标记</th></tr></thead>
          <tbody>
            <tr v-for="row in attendanceRows" :key="row.student_id">
              <td>{{ row.display_name }}</td><td>{{ row.username }}</td><td>{{ row.student_no || '-' }}</td>
              <td>{{ row.current_layer ? `${row.current_layer} ${row.current_layer_label}` : '-' }}</td>
              <td><span class="status-pill" :class="attendanceStatusClass(row.status)">{{ row.status_label }}</span></td>
              <td><span class="attendance-note">{{ row.occurred_at ? formatDateTime(row.occurred_at) : '-' }}<template v-if="row.note"> · {{ row.note }}</template></span></td>
              <td>
                <div class="attendance-actions">
                  <button v-for="item in attendanceActions" :key="`${row.student_id}-${item.status}`" type="button" :disabled="attendanceLoading" @click="emit('markAttendance', row, item.status)">{{ item.label }}</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="attendanceLoading" class="empty">正在加载签到信息...</p>
        <p v-else-if="!attendanceRows.length" class="empty">当前筛选下没有学生。</p>
      </div>
    </section>
  </div>

  <div v-if="quickAnswerOpen && quickAnswerActivity" class="modal-backdrop" role="presentation" @click.self="emit('closeQuickAnswer')">
    <section class="entity-modal attendance-modal quick-answer-modal" role="dialog" aria-modal="true" aria-labelledby="quick-answer-title" :aria-busy="quickAnswerLoading">
      <header class="modal-header">
        <div><h2 id="quick-answer-title">课堂抢答</h2><p>{{ sessionTitle }} · {{ classLabel }}</p></div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('closeQuickAnswer')">×</button>
      </header>
      <div class="attendance-summary-grid quick-answer-summary-grid">
        <button type="button" class="active" tabindex="-1"><strong>{{ quickAnswerData?.summary.total || 0 }}</strong><span>抢答人数</span></button>
        <button type="button" tabindex="-1"><strong>{{ quickAnswerData?.summary.scored || 0 }}</strong><span>已评分</span></button>
        <button type="button" tabindex="-1"><strong>+{{ quickAnswerData?.score_defaults.plus ?? 2 }}</strong><span>默认加分</span></button>
        <button type="button" tabindex="-1"><strong>{{ quickAnswerData?.score_defaults.minus ?? -1 }}</strong><span>默认减分</span></button>
      </div>
      <div class="attendance-toolbar">
        <span>{{ quickAnswerActivity.status_label }} · {{ formatDateTime(quickAnswerActivity.opened_at) }}</span>
        <div><span class="live-refresh-indicator">自动更新中</span><button class="secondary-button mini" type="button" :disabled="quickAnswerLoading" @click="emit('closeActivity', quickAnswerActivity); emit('closeQuickAnswer')">关闭抢答</button></div>
      </div>
      <div class="attendance-table-wrap">
        <table>
          <thead><tr><th>顺序</th><th>学生</th><th>账号</th><th>学号</th><th>层级</th><th>抢答时间</th><th>得分</th><th>评分</th></tr></thead>
          <tbody>
            <tr v-for="row in quickAnswerData?.rows || []" :key="row.event_id">
              <td><span class="quick-rank-badge">{{ row.rank }}</span></td><td>{{ row.display_name }}</td><td>{{ row.username }}</td><td>{{ row.student_no || '-' }}</td>
              <td>{{ row.current_layer ? `${row.current_layer} ${row.current_layer_label}` : '-' }}</td><td>{{ formatDateTime(row.responded_at) }}</td>
              <td><span class="status-pill" :class="quickAnswerScoreClass(row)">{{ scoreText(row) }}</span></td>
              <td><div class="attendance-actions quick-answer-actions"><button v-for="item in quickAnswerScoreActions" :key="`${row.student_id}-${item.action}`" type="button" :class="item.action === 'minus' ? 'danger-action' : ''" :disabled="quickAnswerLoading" @click="emit('scoreQuickAnswer', row, item.action)">{{ item.label }}</button></div></td>
            </tr>
          </tbody>
        </table>
        <p v-if="quickAnswerLoading" class="empty">正在加载抢答结果...</p><p v-else-if="!(quickAnswerData?.rows || []).length" class="empty">抢答已开启，等待学生响应。</p>
      </div>
    </section>
  </div>

  <div v-if="randomPickOpen" class="modal-backdrop" role="presentation" @click.self="emit('closeRandomPick')">
    <section class="entity-modal attendance-modal random-pick-modal" role="dialog" aria-modal="true" aria-labelledby="random-pick-title" :aria-busy="randomPickLoading">
      <header class="modal-header"><div><h2 id="random-pick-title">随机点名</h2><p>{{ sessionTitle }} · {{ classLabel }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="emit('closeRandomPick')">×</button></header>
      <div class="random-pick-layout">
        <section class="random-pick-draw-panel">
          <div class="random-pick-spotlight" :class="{ rolling: randomPickAnimating, picked: Boolean(randomPickPickedStudent) }" aria-live="polite">
            <span>{{ randomPickAnimating ? '正在抽取' : randomPickPickedStudent ? '已抽中' : '准备点名' }}</span>
            <strong>{{ randomPickDisplayStudent?.display_name || randomPickDisplayStudent?.username || '点击随机抽取' }}</strong>
            <small>默认加分 +{{ randomPickData?.score_defaults.plus ?? 2 }} · 默认减分 {{ randomPickData?.score_defaults.minus ?? -1 }}</small>
          </div>
          <button class="primary-button random-pick-main-button" type="button" :disabled="randomPickLoading || randomPickAnimating || Boolean(randomPickActivity) || !randomPickStudents.length" @click="emit('startRandomPick')">{{ randomPickActivity ? '已投放给学生' : randomPickAnimating ? '抽取中...' : '随机抽取' }}</button>
          <button v-if="randomPickActivity" class="secondary-button" type="button" :disabled="randomPickLoading" @click="emit('closeActivity', randomPickActivity)">关闭点名</button>
        </section>
        <section class="random-pick-list-panel">
          <div class="class-check-header"><span>共 {{ randomPickStudents.length }} 名学生</span><span v-if="randomPickLoading">正在同步...</span></div>
          <div class="random-pick-student-grid">
            <span v-for="row in randomPickStudents" :key="row.student_id" class="random-pick-student-chip" :class="{ rolling: randomPickCurrentStudentId === row.student_id && randomPickAnimating, picked: randomPickPickedStudent?.student_id === row.student_id }">
              <strong>{{ row.display_name || row.username }}</strong><small>{{ row.student_no || row.username }}{{ row.current_layer ? ` · ${row.current_layer}` : '' }}</small>
            </span>
          </div>
          <p v-if="!randomPickLoading && !randomPickStudents.length" class="empty">当前班级没有可点名学生。</p>
        </section>
        <section v-if="randomPickPickedStudent" class="random-pick-score-panel">
          <header><div><span>评分</span><strong>{{ randomPickPickedStudent.display_name || randomPickPickedStudent.username }}</strong></div><span class="status-pill" :class="randomPickScoreClass(randomPickPickedStudent)">{{ scoreText(randomPickPickedStudent) }}</span></header>
          <p>教师评分后，学生端会收到一次性弹窗反馈。</p>
          <div class="attendance-actions random-pick-score-actions"><button type="button" :disabled="randomPickLoading || !randomPickActivity" @click="emit('scoreRandomPick', 'plus')">加分 +{{ randomPickData?.score_defaults.plus ?? 2 }}</button><button class="danger-action" type="button" :disabled="randomPickLoading || !randomPickActivity" @click="emit('scoreRandomPick', 'minus')">减分 {{ randomPickData?.score_defaults.minus ?? -1 }}</button></div>
        </section>
      </div>
    </section>
  </div>
</template>
