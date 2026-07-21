<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { CountSlice, SeriesPoint } from '@/api/dashboards'
import { getTeacherDashboard, type TeacherDashboard } from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import { barOption, lineOption, pieOption, total } from '@/utils/chartOptions'
import { teacherNav } from './nav'

const emptyRows: SeriesPoint[] = []
const emptySlices: CountSlice[] = []
const data = ref<TeacherDashboard | null>(null)
const navItems = teacherNav('/teacher')

const charts = computed(() => ({
  event_series: data.value?.charts.event_series || emptyRows,
  login_series: data.value?.charts.login_series || emptyRows,
  active_students_7d: data.value?.charts.active_students_7d || emptyRows,
  class_students: data.value?.charts.class_students || emptyRows,
  class_activity: data.value?.charts.class_activity || emptyRows,
  student_layers: data.value?.charts.student_layers || emptySlices,
  event_types: data.value?.charts.event_types || emptySlices,
  decision_status: data.value?.charts.decision_status || emptySlices,
  training_status: data.value?.charts.training_status || emptySlices
}))

onMounted(async () => {
  data.value = await getTeacherDashboard()
})

const trendOption = computed(() =>
  lineOption([
    { name: '学习事件', rows: charts.value.event_series },
    { name: '活跃学生', rows: charts.value.active_students_7d },
    { name: '登录', rows: charts.value.login_series }
  ])
)
const classActivityOption = computed(() => barOption(charts.value.class_activity, true))
const classStudentsOption = computed(() => barOption(charts.value.class_students, true))
const layerOption = computed(() => pieOption(charts.value.student_layers))
const eventTypeOption = computed(() => barOption(charts.value.event_types, true))

const quickLinks = [
  { label: '进入课程备课', path: '/teacher/courses', detail: '维护本人课程、课时和学习资源。' },
  { label: '进入课堂教学', path: '/teacher/classroom', detail: '按课时学习过程发起课堂、签到和互动。' },
  { label: '协作文档', path: '/teacher/documents', detail: '管理教案、课件、任务单和小组文档。' },
  { label: 'AI接入', path: '/teacher/ai', detail: '配置 DeepSeek Key，用于后续辅助备课和资源生成。' },
  { label: '查看学生账户', path: '/teacher/students', detail: '查询任教班级学生并重置课堂密码。' },
  { label: '处理分层建议', path: '/teacher/stratification?view=pending', detail: '查看层级建议和学习支持提醒。' }
]
</script>

<template>
  <AppShell title="教师首页" eyebrow="教师工作台" :nav-items="navItems">
    <section v-if="!data" class="panel"><p class="empty">正在加载</p></section>
    <template v-else>
      <MetricGrid :metrics="data.metrics" />

      <section class="chart-grid teacher-dashboard-hero-grid">
        <EChartPanel
          title="近 7 天班级学习趋势"
          subtitle="仅统计本人任教班级内的学习过程数据"
          :total="total(charts.event_series)"
          :option="trendOption"
          wide
          tall
        />
        <EChartPanel
          title="班级活跃度"
          subtitle="按班级汇总近 7 天事件"
          :total="total(charts.class_activity)"
          :option="classActivityOption"
          tall
        />
      </section>

      <section class="chart-grid teacher-dashboard-grid">
        <EChartPanel title="任教班级人数" :total="total(charts.class_students)" :option="classStudentsOption" />
        <EChartPanel title="学生分层" :total="total(charts.student_layers)" :option="layerOption" />
        <EChartPanel title="行为类型" :total="total(charts.event_types)" :option="eventTypeOption" />
      </section>

      <section class="screen-grid teacher-work-grid">
        <article class="panel">
          <div class="panel-heading">
            <h2>待处理</h2>
            <p>仅显示本人课程中需要处理的事项。</p>
          </div>
          <div class="status-stack">
            <RouterLink
              v-for="row in data.todo_rows"
              :key="row.label"
              :to="row.path"
              class="status-line status-line-link"
              :class="row.level"
            >
              <span>{{ row.label }}</span>
              <strong>{{ row.count }}</strong>
            </RouterLink>
          </div>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <h2>快捷入口</h2>
            <p>教师端后续业务会按这些入口逐步展开。</p>
          </div>
          <div class="quick-action-grid">
            <RouterLink v-for="item in quickLinks" :key="item.path" :to="item.path" class="quick-action">
              <strong>{{ item.label }}</strong>
              <span>{{ item.detail }}</span>
            </RouterLink>
          </div>
        </article>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <h2>任教班级</h2>
          <p>班级由学校管理员设置；教师端仅展示和开展教学业务。</p>
        </div>
        <div class="table-wrap compact">
          <table>
            <thead>
              <tr><th>年级</th><th>班级</th><th>学生数</th><th>近 7 天事件</th><th>状态</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in data.class_rows" :key="item.id">
                <td>{{ item.grade || '-' }}</td>
                <td>{{ item.name }}</td>
                <td>{{ item.student_count }}</td>
                <td>{{ item.event_count }}</td>
                <td>{{ item.status_label }}</td>
              </tr>
              <tr v-if="!data.class_rows.length"><td colspan="5" class="empty">暂无任教班级</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </AppShell>
</template>
