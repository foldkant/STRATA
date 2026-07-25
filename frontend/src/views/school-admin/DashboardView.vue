<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  IconArrowUpRight,
  IconBuildingCommunity,
  IconClipboardCheck,
  IconRefresh,
  IconUsersGroup,
  IconUsersPlus
} from '@tabler/icons-vue'
import { ApiError } from '@/api/client'
import { getSchoolAdminDashboard, type CountSlice, type SchoolAdminDashboard, type SeriesPoint } from '@/api/dashboards'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { barOption, governanceChartTheme, lineOption, pieOption, stackedBarOption, total } from '@/utils/chartOptions'
import { schoolAdminNav } from './nav'

type SchoolAdminCharts = NonNullable<SchoolAdminDashboard['charts']>

const emptyRows: SeriesPoint[] = []
const emptySlices: CountSlice[] = []
const data = ref<SchoolAdminDashboard | null>(null)
const loading = ref(false)
const notice = ref('')
const updatedAt = ref('')
const navItems = schoolAdminNav('/school-admin')

const fallbackCharts = computed<Partial<SchoolAdminCharts>>(() => ({
  login_series: data.value?.login_series || emptyRows,
  event_series: data.value?.event_series || emptyRows,
  account_roles: emptySlices,
  account_status: emptySlices,
  student_onboarding: emptySlices,
  student_class_status: emptySlices,
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
const attentionTotal = computed(() => attentionRows.value.reduce((sum, row) => sum + row.count, 0))

async function load() {
  loading.value = true
  try {
    data.value = await getSchoolAdminDashboard()
    updatedAt.value = new Date().toLocaleString('zh-CN', {
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
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
  ], governanceChartTheme)
)
const onboardingOption = computed(() => pieOption(charts.value.student_onboarding || emptySlices, governanceChartTheme))
const classStatusOption = computed(() => pieOption(charts.value.student_class_status || emptySlices, governanceChartTheme))
const classLoadOption = computed(() =>
  stackedBarOption([
    { name: '学生', rows: charts.value.class_students || emptyRows },
    { name: '教师', rows: charts.value.class_teachers || emptyRows }
  ], governanceChartTheme)
)
const classActivityOption = computed(() => barOption(charts.value.class_activity || emptyRows, true, governanceChartTheme))
const eventTypeOption = computed(() => barOption(charts.value.event_types || emptySlices, true, governanceChartTheme))
const teacherLoadOption = computed(() => barOption(charts.value.teacher_load || emptyRows, true, governanceChartTheme))
const accountStatusOption = computed(() => pieOption(charts.value.account_status || emptySlices, governanceChartTheme))
const accountRoleOption = computed(() => pieOption(charts.value.account_roles || emptySlices, governanceChartTheme))
const pretestCompletionOption = computed(() => pieOption(charts.value.pretest_completion || emptySlices, governanceChartTheme))
const pretestOption = computed(() => pieOption(charts.value.pretest_status || emptySlices, governanceChartTheme))
const trainingOption = computed(() => pieOption(charts.value.training_status || emptySlices, governanceChartTheme))
</script>

<template>
  <AppShell title="首页" eyebrow="学校教学管理" :nav-items="navItems" shell-variant="school-admin" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <header class="super-admin-page-heading school-admin-page-heading">
      <div>
        <span>学校教学概况</span>
        <h2>{{ data?.school.name || '本校教学工作' }}</h2>
        <p>先查看需要处理的事项，再了解班级、师生和近期学习情况。</p>
      </div>
      <div class="super-admin-heading-actions">
        <small v-if="updatedAt">更新于 {{ updatedAt }}</small>
        <button class="secondary-button" type="button" :disabled="loading" @click="load">
          <IconRefresh aria-hidden="true" />
          {{ loading ? '正在更新' : '更新数据' }}
        </button>
      </div>
    </header>
    <section v-if="!data" class="panel"><p class="empty">{{ loading ? '正在加载' : '暂无数据' }}</p></section>
    <template v-else>
      <section class="school-home-grid" aria-label="待处理事项和常用工作">
        <article class="school-priority">
          <header>
            <div>
              <span>需要处理</span>
              <strong>{{ attentionTotal }}</strong>
            </div>
            <p>{{ attentionRows.length ? '请进入相应页面核对并处理' : '当前没有需要处理的事项' }}</p>
          </header>
          <div v-if="attentionRows.length" class="school-priority-list">
            <RouterLink
              v-for="row in attentionRows"
              :key="row.label"
              :to="row.path"
              :class="row.level"
            >
              <span><strong>{{ row.label }}</strong><small>{{ row.detail }}</small></span>
              <b>{{ row.count }}</b>
              <IconArrowUpRight aria-hidden="true" />
            </RouterLink>
          </div>
          <div v-else class="governance-stable-state">
            <strong>当前各项工作正常</strong>
            <span>师生账号、学习起点诊断、资源审核和学习情况分析均无待处理事项。</span>
          </div>
        </article>

        <nav class="school-shortcuts" aria-label="常用工作入口">
          <header>
            <h3>常用工作</h3>
            <span>直接进入相应页面</span>
          </header>
          <div>
            <RouterLink to="/school-admin/classes">
              <IconBuildingCommunity aria-hidden="true" />
              <span><strong>班级管理</strong><small>维护年级与班级信息</small></span>
              <IconArrowUpRight aria-hidden="true" />
            </RouterLink>
            <RouterLink to="/school-admin/teaching">
              <IconUsersPlus aria-hidden="true" />
              <span><strong>任课关系</strong><small>安排教师任教班级</small></span>
              <IconArrowUpRight aria-hidden="true" />
            </RouterLink>
            <RouterLink to="/school-admin/pretests">
              <IconClipboardCheck aria-hidden="true" />
              <span><strong>学习起点诊断</strong><small>准备诊断任务与实施批次</small></span>
              <IconArrowUpRight aria-hidden="true" />
            </RouterLink>
            <RouterLink to="/school-admin/models">
              <IconUsersGroup aria-hidden="true" />
              <span><strong>学习情况与支持建议</strong><small>查看材料并准备教学支持</small></span>
              <IconArrowUpRight aria-hidden="true" />
            </RouterLink>
          </div>
        </nav>
      </section>

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>学校基本情况</h2><p>显示本校已经建立的师生账号、班级、课程和近期学习记录。</p></div>
      </section>
      <MetricGrid :metrics="data.metrics" />

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>近期学习情况</h2><p>了解学生近期参与学习及完成学习起点诊断的情况。</p></div>
        <small>手机端可横向滑动查看</small>
      </section>
      <section class="chart-grid school-dashboard-hero-grid school-chart-row">
        <EChartPanel
          title="近 7 天学习参与情况"
          subtitle="学习活动记录、活跃学生和登录情况"
          :total="total(charts.event_series || emptyRows)"
          :option="behaviorTrendOption"
          wide
          tall
        />
        <EChartPanel
          title="新生使用准备"
          subtitle="查看首次登录、账号设置、分班和诊断完成情况"
          :total="total(charts.student_onboarding || emptySlices)"
          :option="onboardingOption"
          tall
        />
        <EChartPanel
          title="学习起点诊断完成情况"
          subtitle="缺失材料、设备问题或未获得机会不计为低水平"
          :total="total(charts.pretest_completion || emptySlices)"
          :option="pretestCompletionOption"
          tall
        />
      </section>

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>班级与任课</h2><p>查看各班学生人数、任课安排和近期学习活动。</p></div>
        <small>手机端可横向滑动查看</small>
      </section>
      <section class="chart-grid school-dashboard-work-grid school-chart-row">
        <EChartPanel
          title="各班师生人数"
          subtitle="各班学生人数与任课教师人数"
          :total="total(charts.class_students || emptyRows)"
          :option="classLoadOption"
          wide
        />
        <EChartPanel
          title="近 7 天班级学习记录"
          subtitle="按班级汇总近期学习活动记录"
          :total="total(charts.class_activity || emptyRows)"
          :option="classActivityOption"
          wide
        />
        <EChartPanel
          title="教师任课班级数"
          subtitle="查看教师承担的任教班级数量"
          :total="total(charts.teacher_load || emptyRows)"
          :option="teacherLoadOption"
          wide
        />
      </section>

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>学生与账号</h2><p>核对学生分班、账号启用和师生账号构成。</p></div>
        <small>手机端可横向滑动查看</small>
      </section>
      <section class="chart-grid school-dashboard-four-grid school-chart-row">
        <EChartPanel title="学生分班情况" :total="total(charts.student_class_status || emptySlices)" :option="classStatusOption" />
        <EChartPanel title="账号角色" :total="total(charts.account_roles || emptySlices)" :option="accountRoleOption" />
        <EChartPanel title="账号状态" :total="total(charts.account_status || emptySlices)" :option="accountStatusOption" />
      </section>

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>诊断与学习情况分析</h2><p>查看学习活动记录、学习起点诊断版本和学习情况分析任务。</p></div>
        <small>手机端可横向滑动查看</small>
      </section>
      <section class="chart-grid school-dashboard-four-grid school-chart-row">
        <EChartPanel title="近 7 天学习活动类型" :total="total(charts.event_types || emptySlices)" :option="eventTypeOption" />
        <EChartPanel title="学习起点诊断版本状态" :total="total(charts.pretest_status || emptySlices)" :option="pretestOption" />
        <EChartPanel title="学习情况分析任务" :total="total(charts.training_status || emptySlices)" :option="trainingOption" />
      </section>

      <section class="school-class-overview">
        <article class="panel panel-large">
          <div class="panel-heading split">
            <div><h2>班级概况</h2><p>查看本校各班学生人数、任课教师人数和使用状态。</p></div>
            <RouterLink class="text-link" to="/school-admin/classes">
              查看全部班级
              <IconArrowUpRight aria-hidden="true" />
            </RouterLink>
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
