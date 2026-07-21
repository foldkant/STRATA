<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getSuperAdminDashboard, type CountSlice, type SeriesPoint, type SuperAdminDashboard } from '@/api/dashboards'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { barOption, lineOption, pieOption, total } from '@/utils/chartOptions'
import { auditActionLabel } from '@/utils/auditLabels'
import { superAdminNav } from './nav'

type SuperAdminCharts = NonNullable<SuperAdminDashboard['charts']>

const emptyRows: SeriesPoint[] = []
const emptySlices: CountSlice[] = []
const data = ref<SuperAdminDashboard | null>(null)
const loading = ref(false)
const notice = ref('')
const navItems = superAdminNav('/super-admin')

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

async function load() {
  loading.value = true
  try {
    data.value = await getSuperAdminDashboard()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '数据总览加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const schoolStatusOption = computed(() => pieOption(charts.value.school_status || emptySlices))
const accountRoleOption = computed(() => pieOption(charts.value.account_roles || emptySlices))
const importStatusOption = computed(() => pieOption(charts.value.import_status || emptySlices))
const learningTrendOption = computed(() => lineOption([
  { name: '学习行为', rows: charts.value.learning_events_7d || emptyRows }
]))
const trainingTrendOption = computed(() => lineOption([
  { name: '训练任务', rows: charts.value.training_jobs_7d || emptyRows }
]))
const schoolStudentsOption = computed(() => barOption(charts.value.school_students || emptyRows, true))
const schoolClassesOption = computed(() => barOption(charts.value.school_classes || emptyRows, true))
</script>

<template>
  <AppShell title="数据总览" eyebrow="超级管理员" :nav-items="navItems" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <header class="console-page-heading">
      <div>
        <h2>平台运行总览</h2>
        <p>查看学校规模、数据采集、学习行为和训练任务。</p>
      </div>
      <button class="secondary-button" type="button" :disabled="loading" @click="load">{{ loading ? '更新中' : '更新数据' }}</button>
    </header>
    <section v-if="!data" class="panel"><p class="empty">{{ loading ? '正在加载' : '暂无数据' }}</p></section>
    <template v-else>
      <MetricGrid :metrics="data.metrics" />
      <section class="dashboard-section-heading"><div><h2>平台构成</h2><p>学校、账号与跨校采集状态。</p></div></section>
      <section class="chart-grid dashboard-distribution-grid">
        <EChartPanel title="学校状态" :total="total(charts.school_status || emptySlices)" :option="schoolStatusOption" />
        <EChartPanel title="账号结构" :total="total(charts.account_roles || emptySlices)" :option="accountRoleOption" />
        <EChartPanel title="采集状态" :total="total(charts.import_status || emptySlices)" :option="importStatusOption" />
      </section>
      <section class="dashboard-section-heading"><div><h2>近 7 天运行</h2><p>学习行为与训练任务分别展示，避免数量级相互遮挡。</p></div></section>
      <section class="chart-grid super-dashboard-week-grid">
        <EChartPanel
          title="近 7 天学习行为"
          subtitle="各学校学习过程记录"
          :total="total(charts.learning_events_7d || emptyRows)"
          :option="learningTrendOption"
          tall
        />
        <EChartPanel
          title="近 7 天训练任务"
          subtitle="模型训练任务创建数量"
          :total="total(charts.training_jobs_7d || emptyRows)"
          :option="trainingTrendOption"
          tall
        />
      </section>
      <section class="dashboard-section-heading"><div><h2>学校规模</h2><p>按学生档案和班级数量查看学校分布。</p></div></section>
      <section class="chart-grid super-dashboard-week-grid">
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
            <h2>运行提醒</h2>
            <p>仅列出需要跟进的采集、训练与分层事项。</p>
          </div>
          <div class="status-stack">
            <RouterLink
              v-for="row in data.status_rows.filter((item) => item.count > 0)"
              :key="row.label"
              class="status-line status-line-link"
              :class="row.level"
              :to="row.path"
            ><span>{{ row.label }}</span><strong>{{ row.count }}</strong></RouterLink>
            <div v-if="!data.status_rows.some((item) => item.count > 0)" class="dashboard-clear-state">
              <strong>当前没有需要跟进的事项</strong>
              <span>采集、训练与分层状态正常。</span>
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
      <section class="panel list-panel dashboard-log-panel">
        <div class="panel-heading split">
          <div><h2>最近操作</h2><p>超级管理员与学校管理操作记录。</p></div>
          <RouterLink class="text-link" to="/super-admin/health">查看系统健康</RouterLink>
        </div>
        <div class="table-wrap compact">
          <table>
            <thead><tr><th>时间</th><th>操作</th><th>操作者</th></tr></thead>
            <tbody>
              <tr v-for="item in data.recent_logs" :key="String(item.id)">
                <td>{{ item.created_at ? new Date(String(item.created_at)).toLocaleString('zh-CN') : '-' }}</td>
                <td><strong>{{ auditActionLabel(String(item.action || '')) }}</strong><small class="table-subline">{{ item.action }}</small></td>
                <td>{{ item.actor || '系统' }}</td>
              </tr>
              <tr v-if="!data.recent_logs.length"><td colspan="3" class="empty">暂无操作记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </AppShell>
</template>
