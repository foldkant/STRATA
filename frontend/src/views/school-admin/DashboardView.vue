<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getSchoolAdminDashboard, type CountSlice, type SchoolAdminDashboard, type SeriesPoint } from '@/api/dashboards'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { barOption, lineOption, pieOption, stackedBarOption, total } from '@/utils/chartOptions'
import { schoolAdminNav } from './nav'

type SchoolAdminCharts = NonNullable<SchoolAdminDashboard['charts']>

const emptyRows: SeriesPoint[] = []
const emptySlices: CountSlice[] = []
const data = ref<SchoolAdminDashboard | null>(null)
const loading = ref(false)
const notice = ref('')
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
  pretest_completion: emptySlices,
  training_status: emptySlices,
  active_students_7d: emptyRows
}))
const charts = computed<Partial<SchoolAdminCharts>>(() => ({ ...fallbackCharts.value, ...(data.value?.charts || {}) }))
const recentClasses = computed(() => data.value?.recent_classes || [])
const statusRows = computed(() => data.value?.status_rows || [])
const attentionRows = computed(() => statusRows.value.filter((row) => row.count > 0))

async function load() {
  loading.value = true
  try {
    data.value = await getSchoolAdminDashboard()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '管理首页加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)

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
const accountRoleOption = computed(() => pieOption(charts.value.account_roles || emptySlices))
const pretestCompletionOption = computed(() => pieOption(charts.value.pretest_completion || emptySlices))
const pretestOption = computed(() => pieOption(charts.value.pretest_status || emptySlices))
const trainingOption = computed(() => pieOption(charts.value.training_status || emptySlices))
</script>

<template>
  <AppShell title="管理首页" eyebrow="学校管理员" :nav-items="navItems" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <header class="console-page-heading">
      <div>
        <h2>{{ data?.school.name || '学校运行概况' }}</h2>
        <p>查看本校账号、班级、课程与近期学习活动。</p>
      </div>
      <button class="secondary-button" type="button" :disabled="loading" @click="load">{{ loading ? '更新中' : '更新数据' }}</button>
    </header>
    <section v-if="!data" class="panel"><p class="empty">{{ loading ? '正在加载' : '暂无数据' }}</p></section>
    <template v-else>
      <MetricGrid :metrics="data.metrics" />

      <section class="dashboard-section-heading"><div><h2>学习运行</h2><p>近 7 天平台使用和学生入门进度。</p></div></section>
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

      <section class="dashboard-section-heading"><div><h2>班级与任课</h2><p>班级规模、任课覆盖和近期学习活动。</p></div></section>
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

      <section class="dashboard-section-heading"><div><h2>学生与账号</h2><p>账号启用、学生分层和首次前测完成情况。</p></div></section>
      <section class="chart-grid school-dashboard-four-grid">
        <EChartPanel title="账号角色" :total="total(charts.account_roles || emptySlices)" :option="accountRoleOption" />
        <EChartPanel title="账号状态" :total="total(charts.account_status || emptySlices)" :option="accountStatusOption" />
        <EChartPanel title="学生分层" :total="total(charts.student_layers || emptySlices)" :option="studentLayerOption" />
        <EChartPanel title="首次前测完成情况" :total="total(charts.pretest_completion || emptySlices)" :option="pretestCompletionOption" />
      </section>

      <section class="dashboard-section-heading"><div><h2>内容与后台任务</h2><p>学习行为结构、任课负载、前测套卷和训练任务。</p></div></section>
      <section class="chart-grid school-dashboard-four-grid">
        <EChartPanel title="近 7 天行为类型" :total="total(charts.event_types || emptySlices)" :option="eventTypeOption" />
        <EChartPanel title="教师任课负载" :total="total(charts.teacher_load || emptyRows)" :option="teacherLoadOption" />
        <EChartPanel title="前测套卷状态" :total="total(charts.pretest_status || emptySlices)" :option="pretestOption" />
        <EChartPanel title="训练任务状态" :total="total(charts.training_status || emptySlices)" :option="trainingOption" />
      </section>

      <section class="screen-grid dashboard-bottom-grid">
        <article class="panel">
          <div class="panel-heading">
            <h2>管理提醒</h2>
            <p>只显示需要跟进的事项，正常停用和归档不会计入。</p>
          </div>
          <div class="status-stack">
            <RouterLink
              v-for="row in attentionRows"
              :key="row.label"
              class="status-line status-line-link"
              :class="row.level"
              :to="row.path"
            >
              <span><b>{{ row.label }}</b><small>{{ row.detail }}</small></span>
              <strong>{{ row.count }}</strong>
            </RouterLink>
            <div v-if="!attentionRows.length" class="dashboard-clear-state">
              <strong>当前没有需要跟进的事项</strong>
              <span>账号、审核、训练与导出状态正常。</span>
            </div>
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
