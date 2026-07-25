<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  IconBooks,
  IconChecklist,
  IconChevronRight,
  IconClipboardCheck,
  IconLibrary,
  IconPresentation,
  IconUsers
} from '@tabler/icons-vue'
import type { CountSlice, SeriesPoint } from '@/api/dashboards'
import { getTeacherDashboard, type TeacherDashboard } from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import { barOption, lineOption, teacherChartTheme, total } from '@/utils/chartOptions'
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
  event_types: data.value?.charts.event_types || emptySlices,
  decision_status: data.value?.charts.decision_status || emptySlices,
  training_status: data.value?.charts.training_status || emptySlices
}))

onMounted(async () => {
  data.value = await getTeacherDashboard()
})

const trendOption = computed(() =>
  lineOption([
    { name: '学习活动', rows: charts.value.event_series },
    { name: '参与学生', rows: charts.value.active_students_7d }
  ], teacherChartTheme)
)
const eventTypeOption = computed(() => barOption(charts.value.event_types, true, teacherChartTheme))
const classActivityOption = computed(() => barOption(charts.value.class_activity, true, teacherChartTheme))
const classStudentsOption = computed(() => barOption(charts.value.class_students, true, teacherChartTheme))

const quickLinks = [
  { category: '备课', label: '课程与课时', path: '/teacher/courses', icon: IconBooks },
  { category: '上课', label: '课堂教学', path: '/teacher/classroom', icon: IconPresentation },
  { category: '评价', label: '作业与测试', path: '/teacher/assessments', icon: IconChecklist },
  { category: '评价设计', label: '评价方案', path: '/teacher/evaluations', icon: IconClipboardCheck },
  { category: '学习支持', label: '学生学习情况', path: '/teacher/students', icon: IconUsers },
  { category: '资源', label: '教学资源', path: '/teacher/resources', icon: IconLibrary }
]

const overviewMetrics = computed(() => {
  const metricMap = new Map((data.value?.metrics || []).map((item) => [item.label, item.value]))
  return [
    { key: 'courses', label: '课程', value: metricMap.get('课程') || 0, hint: '本人创建与维护' },
    { key: 'students', label: '学生', value: metricMap.get('学生') || 0, hint: '任教范围内' },
    { key: 'resources', label: '教学资源', value: metricMap.get('资源') || 0, hint: '本人上传' },
    { key: 'activity', label: '今日学习活动', value: metricMap.get('今日学习记录') || 0, hint: '今天已形成记录' }
  ]
})
</script>

<template>
  <AppShell title="首页" eyebrow="教师工作台" :nav-items="navItems">
    <div class="teacher-home">
      <section v-if="!data" class="panel teacher-home-loading"><p class="empty">正在加载教师首页</p></section>
      <template v-else>
        <section class="teacher-home-shortcuts" aria-labelledby="teacher-shortcuts-title">
          <header>
            <h2 id="teacher-shortcuts-title">快捷入口</h2>
            <p>常用教学功能</p>
          </header>
          <nav class="teacher-home-shortcut-grid" aria-label="常用教学功能">
            <RouterLink
              v-for="item in quickLinks"
              :key="item.path"
              :to="item.path"
              class="teacher-home-shortcut"
            >
              <span class="teacher-home-shortcut-icon" aria-hidden="true">
                <component :is="item.icon" />
              </span>
              <span class="teacher-home-shortcut-copy">
                <small>{{ item.category }}</small>
                <strong>{{ item.label }}</strong>
              </span>
              <span class="teacher-home-shortcut-arrow" aria-hidden="true">
                <IconChevronRight />
              </span>
            </RouterLink>
          </nav>
        </section>

        <section class="teacher-home-overview" aria-labelledby="teacher-overview-title">
          <header class="teacher-home-heading teacher-home-overview-heading">
            <div>
              <h2 id="teacher-overview-title">教学概况</h2>
              <p>课程建设、学生参与和学习活动数据</p>
            </div>
            <RouterLink class="teacher-home-text-link" to="/teacher/students">
              查看学生学习情况
              <IconChevronRight aria-hidden="true" />
            </RouterLink>
          </header>

          <div class="teacher-home-metrics" aria-label="教学概况摘要">
            <article v-for="item in overviewMetrics" :key="item.key">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.hint }}</small>
            </article>
          </div>

          <section class="teacher-home-chart-grid" aria-label="教学数据图表">
            <EChartPanel
              title="近 7 天学习活动与参与学生"
              subtitle="按天汇总学习活动记录与参与学生人数"
              :total="total(charts.event_series)"
              :option="trendOption"
            />
            <EChartPanel
              title="学习活动类型"
              subtitle="近 7 天各类学习活动记录"
              :total="total(charts.event_types)"
              :option="eventTypeOption"
            />
            <EChartPanel
              title="班级学习活动"
              subtitle="近 7 天各班学习活动记录比较"
              :total="total(charts.class_activity)"
              :option="classActivityOption"
            />
            <EChartPanel
              title="学生分布"
              subtitle="本人任教范围内各班学生人数"
              :total="total(charts.class_students)"
              :option="classStudentsOption"
            />
          </section>
          <p class="teacher-home-data-note">
            以上数据用于了解教学实施与学生参与情况，不作为单一评价依据。
          </p>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.teacher-home {
  width: min(1240px, 100%);
  display: grid;
  gap: 24px;
  margin: 0 auto;
  padding-bottom: 44px;
}

.teacher-home-loading {
  min-height: 240px;
  display: grid;
  place-items: center;
}

.teacher-home-shortcuts {
  min-width: 0;
  display: grid;
  grid-template-columns: 128px minmax(0, 1fr);
  align-items: center;
  gap: 18px;
  border: 1px solid #d6ded8;
  border-radius: 12px;
  padding: 16px 18px;
  background: #fff;
}

.teacher-home-shortcuts > header {
  min-width: 0;
  border-right: 1px solid #dfe5e0;
  padding-right: 16px;
}

.teacher-home-shortcuts h2 {
  margin: 0;
  color: #0d352e;
  font-size: 18px;
}

.teacher-home-shortcuts header p {
  margin: 5px 0 0;
  color: #687a73;
  font-size: 12px;
}

.teacher-home-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
}

.teacher-home-heading > div {
  min-width: 0;
}

.teacher-home-heading h2 {
  margin: 0;
  color: #0d352e;
}

.teacher-home-heading h2 {
  font-size: 24px;
  line-height: 1.25;
}

.teacher-home-heading p {
  margin: 5px 0 0;
  color: #687a73;
  font-size: 13px;
  line-height: 1.55;
}

.teacher-home-shortcut-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
}

.teacher-home-shortcut {
  min-width: 0;
  min-height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid #dbe2dd;
  border-radius: 8px;
  padding: 10px 12px;
  background: #f7f8f4;
  transition: border-color 160ms ease-out, background-color 160ms ease-out, transform 160ms ease-out;
}

.teacher-home-shortcut:hover,
.teacher-home-shortcut:focus-visible {
  border-color: #8ba59b;
  background: #f1f5f1;
  transform: translateY(-1px);
}

.teacher-home-shortcut-copy {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 3px;
}

.teacher-home-shortcut-copy small {
  color: #687a73;
  font-size: 11px;
  font-weight: 700;
}

.teacher-home-shortcut-copy strong {
  color: #0d352e;
  font-size: 14px;
  line-height: 1.3;
}

.teacher-home-shortcut-arrow,
.teacher-home-text-link svg {
  display: inline-grid;
  place-items: center;
}

.teacher-home-shortcut-arrow {
  align-self: center;
  color: #83948d;
  flex: 0 0 auto;
}

.teacher-home-shortcut-arrow svg,
.teacher-home-text-link svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.teacher-home-overview {
  min-width: 0;
}

.teacher-home-text-link {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #17483f;
  font-size: 14px;
  font-weight: 800;
}

.teacher-home-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.teacher-home-metrics article {
  min-width: 0;
  min-height: 104px;
  display: grid;
  align-content: center;
  gap: 6px;
  border: 1px solid #d6ded8;
  border-radius: 9px;
  padding: 16px 18px;
  background: #fff;
}

.teacher-home-metrics span,
.teacher-home-metrics small {
  color: #687a73;
}

.teacher-home-metrics span {
  font-size: 13px;
  font-weight: 700;
}

.teacher-home-metrics strong {
  color: #0d352e;
  font-size: 30px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.teacher-home-metrics small {
  font-size: 12px;
}

.teacher-home-chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 14px;
}

.teacher-home-chart-grid :deep(.chart-card) {
  border-color: #d6ded8;
  border-radius: 9px;
  box-shadow: none;
}

 .teacher-home-data-note {
  margin: 12px 2px 0;
  color: #687a73;
  font-size: 12px;
  line-height: 1.55;
}

@media (max-width: 1100px) {
  .teacher-home-shortcuts {
    grid-template-columns: minmax(0, 1fr);
  }

  .teacher-home-shortcuts > header {
    display: flex;
    align-items: baseline;
    gap: 10px;
    border-right: 0;
    padding-right: 0;
  }

  .teacher-home-shortcut-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .teacher-home {
    gap: 18px;
    padding-bottom: 24px;
  }

  .teacher-home-shortcuts {
    border-radius: 10px;
    gap: 12px;
    padding: 15px;
  }

  .teacher-home-heading {
    display: grid;
    align-items: start;
    gap: 10px;
  }

  .teacher-home-heading h2 {
    font-size: 22px;
  }

  .teacher-home-shortcut-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .teacher-home-shortcut {
    min-height: 64px;
    padding: 9px 10px;
  }

  .teacher-home-shortcut-copy strong {
    font-size: 13px;
  }

  .teacher-home-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
    margin-top: 16px;
  }

  .teacher-home-metrics article {
    min-height: 98px;
    padding: 14px;
  }

  .teacher-home-chart-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
  }
}
</style>
