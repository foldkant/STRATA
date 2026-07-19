<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getSchoolAdminDashboard, type CountSlice, type SchoolAdminDashboard, type SeriesPoint } from '@/api/dashboards'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import { barOption, lineOption, pieOption, stackedBarOption, total } from '@/utils/chartOptions'
import { schoolAdminNav } from './nav'

type SchoolAdminCharts = NonNullable<SchoolAdminDashboard['charts']>

const emptyRows: SeriesPoint[] = []
const emptySlices: CountSlice[] = []
const data = ref<SchoolAdminDashboard | null>(null)
const navItems = schoolAdminNav('/school-admin')

const fallbackCharts = computed<Partial<SchoolAdminCharts>>(() => ({
  login_series: data.value?.login_series || emptyRows,
  event_series: data.value?.event_series || emptyRows,
  account_roles: emptySlices,
  account_status: emptySlices,
  student_onboarding: emptySlices,
  student_class_status: emptySlices,
  student_layers: emptySlices,
  class_status: emptySlices,
  class_students: emptyRows,
  class_teachers: emptyRows,
  class_activity: emptyRows,
  teacher_load: emptyRows,
  event_types: emptySlices,
  pretest_status: emptySlices,
  training_status: emptySlices,
  active_students_7d: emptyRows
}))
const charts = computed<Partial<SchoolAdminCharts>>(() => ({ ...fallbackCharts.value, ...(data.value?.charts || {}) }))
const recentClasses = computed(() => data.value?.recent_classes || [])
const statusRows = computed(() => data.value?.status_rows || [])

onMounted(async () => {
  data.value = await getSchoolAdminDashboard()
})

const behaviorTrendOption = computed(() =>
  lineOption([
    { name: '学习事件', rows: charts.value.event_series || emptyRows },
    { name: '活跃学生', rows: charts.value.active_students_7d || emptyRows },
    { name: '登录', rows: charts.value.login_series || emptyRows }
  ])
)
const onboardingOption = computed(() => pieOption(charts.value.student_onboarding || emptySlices))
const classStatusOption = computed(() => pieOption(charts.value.student_class_status || emptySlices))
const studentLayerOption = computed(() => pieOption(charts.value.student_layers || emptySlices))
const classLoadOption = computed(() =>
  stackedBarOption([
    { name: '学生', rows: charts.value.class_students || emptyRows },
    { name: '教师', rows: charts.value.class_teachers || emptyRows }
  ])
)
const classActivityOption = computed(() => barOption(charts.value.class_activity || emptyRows, true))
const eventTypeOption = computed(() => barOption(charts.value.event_types || emptySlices, true))
const teacherLoadOption = computed(() => barOption(charts.value.teacher_load || emptyRows, true))
const accountStatusOption = computed(() => pieOption(charts.value.account_status || emptySlices))
const pretestOption = computed(() => pieOption(charts.value.pretest_status || emptySlices))
const trainingOption = computed(() => pieOption(charts.value.training_status || emptySlices))
</script>

<template>
  <AppShell title="管理首页" eyebrow="学校管理员" :nav-items="navItems">
    <section v-if="!data" class="panel"><p class="empty">正在加载</p></section>
    <template v-else>
      <MetricGrid :metrics="data.metrics" />

      <section class="chart-grid school-dashboard-hero-grid">
        <EChartPanel
          title="近 7 天学习趋势"
          subtitle="学习事件、活跃学生和登录变化"
          :total="total(charts.event_series || emptyRows)"
          :option="behaviorTrendOption"
          wide
          tall
        />
        <EChartPanel
          title="学生入门状态"
          subtitle="首次使用、改密、选班和前测进度"
          :total="total(charts.student_onboarding || emptySlices)"
          :option="onboardingOption"
          tall
        />
        <EChartPanel
          title="学生分班状态"
          subtitle="新生可先建账号，后续再选班或批量匹配"
          :total="total(charts.student_class_status || emptySlices)"
          :option="classStatusOption"
          tall
        />
      </section>

      <section class="chart-grid school-dashboard-work-grid">
        <EChartPanel
          title="班级规模"
          subtitle="各班学生数与任课教师数"
          :total="total(charts.class_students || emptyRows)"
          :option="classLoadOption"
          wide
        />
        <EChartPanel
          title="近 7 天班级行为"
          subtitle="按班级汇总学习过程事件"
          :total="total(charts.class_activity || emptyRows)"
          :option="classActivityOption"
          wide
        />
      </section>

      <section class="chart-grid school-dashboard-grid">
        <EChartPanel title="行为类型" :total="total(charts.event_types || emptySlices)" :option="eventTypeOption" />
        <EChartPanel title="教师任课负载" :total="total(charts.teacher_load || emptyRows)" :option="teacherLoadOption" />
        <EChartPanel title="学生分层" :total="total(charts.student_layers || emptySlices)" :option="studentLayerOption" />
      </section>

      <section class="chart-grid school-dashboard-grid">
        <EChartPanel title="账号状态" :total="total(charts.account_status || emptySlices)" :option="accountStatusOption" />
        <EChartPanel title="学科前测状态" :total="total(charts.pretest_status || emptySlices)" :option="pretestOption" />
        <EChartPanel title="训练任务状态" :total="total(charts.training_status || emptySlices)" :option="trainingOption" />
      </section>

      <section class="screen-grid dashboard-bottom-grid">
        <article class="panel">
          <div class="panel-heading">
            <h2>待处理</h2>
            <p>{{ data.school.name }} 的账号、前测、训练与导出状态。</p>
          </div>
          <div class="status-stack">
            <div v-for="row in statusRows" :key="row.label" class="status-line" :class="row.level">
              <span>{{ row.label }}</span>
              <strong>{{ row.count }}</strong>
            </div>
            <p v-if="!statusRows.length" class="empty">暂无待处理项</p>
          </div>
        </article>
        <article class="panel panel-large">
          <div class="panel-heading">
            <h2>班级概况</h2>
            <p>当前学校的班级、学生与任课教师数量。</p>
          </div>
          <div class="table-wrap compact">
            <table>
              <thead>
                <tr><th>年级</th><th>班级</th><th>学生</th><th>教师</th><th>状态</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in recentClasses" :key="String(item.id)">
                  <td>{{ item.grade || '-' }}</td>
                  <td>{{ item.name }}</td>
                  <td>{{ item.student_count }}</td>
                  <td>{{ item.teacher_count }}</td>
                  <td>{{ item.status_label }}</td>
                </tr>
                <tr v-if="!recentClasses.length"><td colspan="5" class="empty">暂无班级</td></tr>
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
