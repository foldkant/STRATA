<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  IconArrowUpRight,
  IconBook2,
  IconBuildingCommunity,
  IconDatabaseImport,
  IconRefresh
} from '@tabler/icons-vue'
import { ApiError } from '@/api/client'
import { getSuperAdminDashboard, type CountSlice, type SeriesPoint, type SuperAdminDashboard } from '@/api/dashboards'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { barOption, governanceChartTheme, lineOption, pieOption, total } from '@/utils/chartOptions'
import { auditActionLabel } from '@/utils/auditLabels'
import { superAdminNav } from './nav'

type SuperAdminCharts = NonNullable<SuperAdminDashboard['charts']>

const emptyRows: SeriesPoint[] = []
const emptySlices: CountSlice[] = []
const data = ref<SuperAdminDashboard | null>(null)
const loading = ref(false)
const notice = ref('')
const updatedAt = ref('')
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
    updatedAt.value = new Date().toLocaleString('zh-CN', {
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '数据总览加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const schoolStatusOption = computed(() => pieOption(charts.value.school_status || emptySlices, governanceChartTheme))
const accountRoleOption = computed(() => pieOption(charts.value.account_roles || emptySlices, governanceChartTheme))
const importStatusOption = computed(() => pieOption(charts.value.import_status || emptySlices, governanceChartTheme))
const learningTrendOption = computed(() => lineOption([
  { name: '学习活动记录', rows: charts.value.learning_events_7d || emptyRows }
], governanceChartTheme))
const trainingTrendOption = computed(() => lineOption([
  { name: '学习情况分析', rows: charts.value.training_jobs_7d || emptyRows }
], governanceChartTheme))
const schoolStudentsOption = computed(() => barOption(charts.value.school_students || emptyRows, true, governanceChartTheme))
const schoolClassesOption = computed(() => barOption(charts.value.school_classes || emptyRows, true, governanceChartTheme))
const focusItems = computed(() => data.value?.status_rows.filter((item) => item.count > 0) || [])
const focusTotal = computed(() => focusItems.value.reduce((sum, item) => sum + item.count, 0))
</script>

<template>
  <AppShell title="首页" eyebrow="超级管理员" :nav-items="navItems" shell-variant="super-admin" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <header class="super-admin-page-heading">
      <div>
        <span>平台工作概况</span>
        <h2>先看需要处理的事项，再了解学校使用情况。</h2>
        <p>这里汇总课程标准、学校账号、教学活动记录和系统检查结果。</p>
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
      <section class="governance-home-grid" aria-label="平台待处理事项和常用工作">
        <article class="governance-priority">
          <header>
            <div>
              <span>待处理事项</span>
              <strong>{{ focusTotal }}</strong>
            </div>
            <p>{{ focusItems.length ? '请进入相应页面查看并处理' : '当前没有需要处理的事项' }}</p>
          </header>
          <div v-if="focusItems.length" class="governance-priority-list">
            <RouterLink
              v-for="row in focusItems"
              :key="row.label"
              :to="row.path"
              :class="row.level"
            >
              <span>{{ row.label }}</span>
              <strong>{{ row.count }}</strong>
              <IconArrowUpRight aria-hidden="true" />
            </RouterLink>
          </div>
          <div v-else class="governance-stable-state">
            <strong>当前各项工作正常</strong>
            <span>课程标准处理、学校数据接收和学习情况分析任务均可正常使用。</span>
          </div>
        </article>

        <nav class="governance-shortcuts" aria-label="常用工作入口">
          <header>
            <h3>常用工作</h3>
            <span>直接进入相应页面</span>
          </header>
          <RouterLink to="/super-admin/curriculum-standards">
            <IconBook2 aria-hidden="true" />
            <span><strong>课程标准</strong><small>核对原文、复核内容和发布版本</small></span>
            <IconArrowUpRight aria-hidden="true" />
          </RouterLink>
          <RouterLink to="/super-admin/schools">
            <IconBuildingCommunity aria-hidden="true" />
            <span><strong>学校信息</strong><small>登记学校并管理使用状态</small></span>
            <IconArrowUpRight aria-hidden="true" />
          </RouterLink>
          <RouterLink to="/super-admin/collection">
            <IconDatabaseImport aria-hidden="true" />
            <span><strong>学校数据接收</strong><small>接收并检查各校上传的数据文件</small></span>
            <IconArrowUpRight aria-hidden="true" />
          </RouterLink>
        </nav>
      </section>

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>平台基本情况</h2><p>显示正式学校、账号和学习活动记录，不包含测试学校。</p></div>
      </section>
      <MetricGrid :metrics="data.metrics" />

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>学校与账号</h2><p>了解账号构成、学校使用状态和学校数据接收情况。</p></div>
      </section>
      <section class="chart-grid governance-composition-grid">
        <EChartPanel title="账号结构" :total="total(charts.account_roles || emptySlices)" :option="accountRoleOption" />
        <EChartPanel title="学校状态" :total="total(charts.school_status || emptySlices)" :option="schoolStatusOption" />
        <EChartPanel title="学校数据接收状态" :total="total(charts.import_status || emptySlices)" :option="importStatusOption" />
      </section>

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>近 7 天教学数据</h2><p>查看学习活动记录和学习情况分析任务的变化。</p></div>
      </section>
      <section class="chart-grid governance-trend-grid">
        <EChartPanel
          title="近 7 天学习活动记录"
          subtitle="各学校保存的学习过程记录数量"
          :total="total(charts.learning_events_7d || emptyRows)"
          :option="learningTrendOption"
          tall
        />
        <EChartPanel
          title="近 7 天学习情况分析"
          subtitle="学校发起的学习情况分析任务数量"
          :total="total(charts.training_jobs_7d || emptyRows)"
          :option="trainingTrendOption"
          tall
        />
      </section>

      <section class="dashboard-section-heading super-admin-section-heading">
        <div><h2>各校学生与班级</h2><p>分别查看各学校已建档学生和班级数量。</p></div>
      </section>
      <section class="chart-grid governance-scale-grid">
        <EChartPanel
          title="各校学生人数"
          subtitle="按已建档学生人数排序"
          :total="total(charts.school_students || emptyRows)"
          :option="schoolStudentsOption"
          tall
        />
        <EChartPanel
          title="各校班级数量"
          subtitle="与学生人数使用相同的学校顺序"
          :total="total(charts.school_classes || emptyRows)"
          :option="schoolClassesOption"
          tall
        />
      </section>

      <section class="screen-grid governance-record-grid">
        <article class="panel panel-large">
          <div class="panel-heading">
            <h2>最近接收的数据</h2>
            <p>各学校近期上传的数据文件。</p>
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
                <tr v-if="!data.recent_imports.length"><td colspan="4" class="empty">暂无数据接收记录</td></tr>
              </tbody>
            </table>
          </div>
        </article>
        <article class="panel panel-large dashboard-log-panel">
          <div class="panel-heading split">
            <div><h2>最近操作</h2><p>超级管理员和学校管理员最近完成的管理操作。</p></div>
            <RouterLink class="text-link" to="/super-admin/health">查看系统检查</RouterLink>
          </div>
          <div class="table-wrap compact">
            <table>
              <thead><tr><th>时间</th><th>操作</th><th>操作者</th></tr></thead>
              <tbody>
                <tr v-for="item in data.recent_logs" :key="String(item.id)">
                  <td>{{ item.created_at ? new Date(String(item.created_at)).toLocaleString('zh-CN') : '-' }}</td>
                  <td><strong>{{ auditActionLabel(String(item.action || '')) }}</strong></td>
                  <td>{{ item.actor || '系统' }}</td>
                </tr>
                <tr v-if="!data.recent_logs.length"><td colspan="3" class="empty">暂无操作记录</td></tr>
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
