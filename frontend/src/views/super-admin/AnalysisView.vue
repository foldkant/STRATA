<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getCrossSchoolAnalysis, type CrossSchoolAnalysis } from '@/api/superAdmin'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { barOption, governanceChartTheme, lineOption, pieOption, total } from '@/utils/chartOptions'
import { superAdminNav } from './nav'

const navItems = superAdminNav('/super-admin/analysis')
const data = ref<CrossSchoolAnalysis | null>(null)
const includeTestData = ref(false)
const loading = ref(false)
const notice = ref('')

const emptyRows: Array<{ label: string; count: number }> = []
const charts = computed(() => data.value?.charts)
const exportUrl = computed(() => `/api/v1/super-admin/analysis/export/${includeTestData.value ? '?include_test_data=1' : ''}`)
const eventTrendOption = computed(() => lineOption([
  { name: '学习活动记录', rows: charts.value?.event_series_30d || emptyRows }
], governanceChartTheme))
const schoolStudentsOption = computed(() => barOption(charts.value?.school_students || emptyRows, true, governanceChartTheme))
const schoolActivityOption = computed(() => barOption(charts.value?.school_activity || emptyRows, true, governanceChartTheme))
const activeRateOption = computed(() => barOption(charts.value?.school_active_rate || emptyRows, true, governanceChartTheme))
const eventTypeOption = computed(() => barOption(charts.value?.event_types || emptyRows, true, governanceChartTheme))
const collectionStatusOption = computed(() => pieOption(charts.value?.collection_status || emptyRows, governanceChartTheme))
const trainingStatusOption = computed(() => pieOption(charts.value?.training_status || emptyRows, governanceChartTheme))

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

async function load() {
  loading.value = true
  try {
    data.value = await getCrossSchoolAnalysis(includeTestData.value)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '校际数据概览加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell title="校际数据概览" eyebrow="超级管理员" :nav-items="navItems" shell-variant="super-admin" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <header class="console-page-heading">
      <div>
        <h2>校际数据概览</h2>
        <p>查看各校账号、班级、课程和学习活动记录，帮助判断数据是否完整。这里的数据不用于学校质量评价或排名。</p>
      </div>
      <div class="heading-actions">
        <label class="switch-control analysis-scope-toggle">
          <input v-model="includeTestData" type="checkbox" @change="load" />
          <span>包含测试数据</span>
        </label>
        <a class="secondary-button" :href="exportUrl">导出表格</a>
        <button class="primary-button" type="button" :disabled="loading" @click="load">{{ loading ? '更新中' : '更新数据' }}</button>
      </div>
    </header>

    <section v-if="!data" class="panel"><p class="empty">{{ loading ? '正在加载' : '暂无数据' }}</p></section>
    <template v-else>
      <div class="analysis-scope-note" :class="{ test: includeTestData }">
        <strong>{{ includeTestData ? '正式数据 + 测试数据' : '仅正式学校数据' }}</strong>
        <span>正式学校 {{ data.scope.formal_schools }} 所，测试学校 {{ data.scope.test_schools }} 所。</span>
      </div>

      <MetricGrid :metrics="data.metrics" />

      <section class="chart-grid cross-analysis-main-grid">
        <EChartPanel
          title="近 30 天学习活动记录"
          subtitle="当前范围内各校每日形成的记录数量"
          :total="total(charts?.event_series_30d || emptyRows)"
          :option="eventTrendOption"
          wide
          tall
        />
        <EChartPanel
          title="各校学生人数"
          subtitle="用于理解不同学校记录数量的差异"
          :total="total(charts?.school_students || emptyRows)"
          :option="schoolStudentsOption"
          tall
        />
      </section>

      <section class="chart-grid cross-analysis-comparison-grid">
        <EChartPanel
          title="学生人均学习活动记录"
          subtitle="近 30 天记录数量除以学生人数"
          :option="schoolActivityOption"
        />
        <EChartPanel
          title="近 7 天参与学习学生比例"
          subtitle="形成过学习活动记录的学生占比（%）"
          :option="activeRateOption"
        />
      </section>

      <section class="chart-grid cross-analysis-distribution-grid">
        <EChartPanel title="近 30 天学习活动类型" :total="total(charts?.event_types || emptyRows)" :option="eventTypeOption" />
        <EChartPanel title="学校数据接收状态" :total="total(charts?.collection_status || emptyRows)" :option="collectionStatusOption" />
        <EChartPanel title="学习情况分析任务状态" :total="total(charts?.training_status || emptyRows)" :option="trainingStatusOption" />
      </section>

      <section class="panel list-panel">
        <div class="panel-heading">
          <h2>各校数据明细</h2>
          <p>人均记录和参与学生比例帮助理解学校人数差异，不能作为学校教学质量评价依据。测试数据会单独标明。</p>
        </div>
        <div class="table-wrap">
          <table class="cross-school-table">
            <thead>
              <tr>
                <th>学校</th><th>教师</th><th>学生</th><th>班级</th><th>课程</th><th>近30天记录</th><th>人均记录</th><th>近7天参与率</th><th>数据接收次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in data.schools" :key="row.id">
                <td>
                  <strong>{{ row.name }}</strong>
                  <small class="table-subline">{{ row.code }}<span v-if="row.is_test_data" class="test-data-label">测试数据</span></small>
                </td>
                <td>{{ row.teacher_count }}</td>
                <td>{{ row.student_count }}</td>
                <td>{{ row.class_count }}</td>
                <td>{{ row.course_count }}</td>
                <td>{{ row.events_30d }}</td>
                <td>{{ row.events_per_student_30d }}</td>
                <td>{{ row.active_rate_7d }}%</td>
                <td>{{ row.collection_count }}</td>
              </tr>
              <tr v-if="!data.schools.length"><td colspan="9" class="empty">当前范围暂无学校数据</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel list-panel">
        <div class="panel-heading split">
          <div>
            <h2>最近接收的数据</h2>
            <p>这些记录说明数据来自哪所学校以及何时上传，不作为学校的数据备份文件。</p>
          </div>
          <RouterLink class="text-link" to="/super-admin/collection">查看数据接收记录</RouterLink>
        </div>
        <div class="table-wrap compact">
          <table>
            <thead><tr><th>批次</th><th>学校</th><th>版本</th><th>状态</th><th>上传时间</th></tr></thead>
            <tbody>
              <tr v-for="row in data.recent_collections" :key="row.id">
                <td>{{ row.batch_code }}</td>
                <td>{{ row.source_school?.name || row.source_school_code || '未识别' }}</td>
                <td>{{ row.source_system_version || '-' }}</td>
                <td><span class="status-pill" :class="`status-${row.status}`">{{ row.status_label }}</span></td>
                <td>{{ formatDate(row.uploaded_at) }}</td>
              </tr>
              <tr v-if="!data.recent_collections.length"><td colspan="5" class="empty">暂无数据接收记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </AppShell>
</template>
