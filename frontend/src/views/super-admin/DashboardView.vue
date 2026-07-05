<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getSuperAdminDashboard, type CountSlice, type SeriesPoint, type SuperAdminDashboard } from '@/api/dashboards'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import { barOption, lineOption, pieOption, total } from '@/utils/chartOptions'

type SuperAdminCharts = NonNullable<SuperAdminDashboard['charts']>

const emptyRows: SeriesPoint[] = []
const emptySlices: CountSlice[] = []
const data = ref<SuperAdminDashboard | null>(null)
const navItems = [
  { label: '数据总览', path: '/super-admin', active: true },
  { label: '学校管理', path: '/super-admin/schools' },
  { label: '学校管理员', path: '/super-admin/school-admins' },
  { label: '跨校数据采集', path: '/super-admin/collection' },
  { label: '跨校分析', path: '/super-admin/analysis' },
  { label: '系统健康', path: '/super-admin/health' }
]

const charts = computed<Partial<SuperAdminCharts>>(() => ({
  school_status: emptySlices,
  import_status: emptySlices,
  account_roles: emptySlices,
  learning_events_7d: emptyRows,
  training_jobs_7d: emptyRows,
  school_students: emptyRows,
  school_classes: emptyRows,
  ...(data.value?.charts || {})
}))

onMounted(async () => {
  data.value = await getSuperAdminDashboard()
})

const schoolStatusOption = computed(() => pieOption(charts.value.school_status || emptySlices))
const accountRoleOption = computed(() => pieOption(charts.value.account_roles || emptySlices))
const importStatusOption = computed(() => pieOption(charts.value.import_status || emptySlices))
const trendOption = computed(() =>
  lineOption([
    { name: '学习事件', rows: charts.value.learning_events_7d || emptyRows },
    { name: '训练任务', rows: charts.value.training_jobs_7d || emptyRows }
  ])
)
const schoolStudentsOption = computed(() => barOption(charts.value.school_students || emptyRows, true))
const schoolClassesOption = computed(() => barOption(charts.value.school_classes || emptyRows, true))
</script>

<template>
  <AppShell title="数据总览" eyebrow="超级管理员" :nav-items="navItems">
    <section v-if="!data" class="panel"><p class="empty">正在加载</p></section>
    <template v-else>
      <MetricGrid :metrics="data.metrics" />
      <section class="chart-grid dashboard-distribution-grid">
        <EChartPanel title="学校状态" :total="total(charts.school_status || emptySlices)" :option="schoolStatusOption" />
        <EChartPanel title="账号结构" :total="total(charts.account_roles || emptySlices)" :option="accountRoleOption" />
        <EChartPanel title="采集状态" :total="total(charts.import_status || emptySlices)" :option="importStatusOption" />
      </section>
      <section class="chart-grid super-dashboard-trend-grid">
        <EChartPanel
          title="近 7 天平台趋势"
          subtitle="学习事件与训练任务"
          :total="total(charts.learning_events_7d || emptyRows) + total(charts.training_jobs_7d || emptyRows)"
          :option="trendOption"
          wide
          tall
        />
        <EChartPanel
          title="学校学生规模"
          subtitle="按学生档案数排序"
          :total="total(charts.school_students || emptyRows)"
          :option="schoolStudentsOption"
          tall
        />
        <EChartPanel
          title="学校班级规模"
          subtitle="按同一学校顺序展示"
          :total="total(charts.school_classes || emptyRows)"
          :option="schoolClassesOption"
          tall
        />
      </section>
      <section class="screen-grid dashboard-bottom-grid">
        <article class="panel">
          <div class="panel-heading">
            <h2>运行状态</h2>
            <p>跨校采集、训练与分层待处理。</p>
          </div>
          <div class="status-stack">
            <div v-for="(value, key) in data.status" :key="key" class="status-line">
              <span>{{ key }}</span>
              <strong>{{ value }}</strong>
            </div>
          </div>
        </article>
        <article class="panel panel-large">
          <div class="panel-heading">
            <h2>最近采集</h2>
            <p>学校数据采集包记录。</p>
          </div>
          <div class="table-wrap compact">
            <table>
              <thead>
                <tr><th>批次</th><th>学校编号</th><th>版本</th><th>状态</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in data.recent_imports" :key="String(item.id)">
                  <td>{{ item.batch_code }}</td>
                  <td>{{ item.source_school_code || '-' }}</td>
                  <td>{{ item.source_system_version || '-' }}</td>
                  <td>{{ item.status_label }}</td>
                </tr>
                <tr v-if="!data.recent_imports.length"><td colspan="4" class="empty">暂无采集记录</td></tr>
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
