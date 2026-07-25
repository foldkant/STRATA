<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import { getSystemHealth, type SystemHealth } from '@/api/superAdmin'
import AppShell from '@/layouts/AppShell.vue'
import MetricGrid from '@/components/MetricGrid.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { auditActionLabel } from '@/utils/auditLabels'
import { superAdminNav } from './nav'

const navItems = superAdminNav('/super-admin/health')
const data = ref<SystemHealth | null>(null)
const loading = ref(false)
const notice = ref('')
const activeSection = ref<'checks' | 'incidents' | 'logs'>('checks')

const overallStatus = computed(() => {
  if (!data.value) return { label: '检查中', level: 'warn' }
  if (data.value.checks.some((item) => item.level === 'failed')) return { label: '发现异常', level: 'failed' }
  if (data.value.checks.some((item) => item.level === 'warn')) return { label: '有提醒', level: 'warn' }
  return { label: '运行正常', level: 'ok' }
})

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function detailText(value: Record<string, unknown>) {
  const entries = Object.entries(value || {}).slice(0, 4)
  if (!entries.length) return '-'
  return entries.map(([key, item]) => `${key}: ${String(item)}`).join('；')
}

async function load() {
  loading.value = true
  try {
    data.value = await getSystemHealth()
    notice.value = '系统检查结果已更新。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '系统检查未完成，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load().then(() => { notice.value = '' })
})
</script>

<template>
  <AppShell title="系统检查" eyebrow="超级管理员" :nav-items="navItems" shell-variant="super-admin" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <header class="console-page-heading">
      <div>
        <h2>平台服务检查</h2>
        <p>检查登录、课堂互动、文档预览、教学文件保存、课程标准处理和 AI 辅助功能是否正常。</p>
      </div>
      <div class="heading-actions">
        <span class="health-overall-status" :class="overallStatus.level">{{ overallStatus.label }}</span>
        <a class="secondary-button" href="/api/v1/super-admin/health/export/">导出检查结果</a>
        <button class="primary-button" type="button" :disabled="loading" @click="load">{{ loading ? '检查中' : '重新检查' }}</button>
      </div>
    </header>

    <section v-if="!data" class="panel"><p class="empty">正在执行系统检查</p></section>
    <template v-else>
      <MetricGrid :metrics="data.metrics" />

      <nav class="console-section-tabs" aria-label="系统检查内容">
        <button type="button" :class="{ active: activeSection === 'checks' }" @click="activeSection = 'checks'">功能检查</button>
        <button type="button" :class="{ active: activeSection === 'incidents' }" @click="activeSection = 'incidents'">
          需要处理 <span v-if="data.incidents.length">{{ data.incidents.length }}</span>
        </button>
        <button type="button" :class="{ active: activeSection === 'logs' }" @click="activeSection = 'logs'">最近操作</button>
      </nav>

      <section v-if="activeSection === 'checks'" class="panel health-check-panel">
        <div class="panel-heading split">
          <div>
            <h2>功能检查</h2>
            <p>检查时间：{{ formatDate(data.checked_at) }}</p>
          </div>
          <span class="muted-text">“有提醒”表示需要留意，但相关功能仍可能正常使用</span>
        </div>
        <div class="health-check-grid">
          <article v-for="check in data.checks" :key="check.key" class="health-check-row" :class="check.level">
            <div class="health-check-indicator" aria-hidden="true" />
            <div>
              <strong>{{ check.name }}</strong>
              <p>{{ check.detail }}</p>
            </div>
            <span>{{ check.status }}</span>
          </article>
        </div>
      </section>

      <section v-else-if="activeSection === 'incidents'" class="panel list-panel">
        <div class="panel-heading">
          <h2>需要处理的问题</h2>
          <p>集中显示学校数据检查、课程标准处理和学习情况分析中未完成的任务，便于继续处理。</p>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>问题类型</th><th>学校</th><th>相关内容</th><th>说明</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in data.incidents" :key="row.id">
                <td>{{ formatDate(row.time) }}</td>
                <td><span class="status-pill status-failed">{{ row.type }}</span></td>
                <td>{{ row.school }}</td>
                <td>{{ row.target }}</td>
                <td class="table-long-text">{{ row.detail }}</td>
                <td><RouterLink v-if="row.path" class="table-link" :to="row.path">查看</RouterLink><span v-else>-</span></td>
              </tr>
              <tr v-if="!data.incidents.length"><td colspan="6" class="empty">当前没有需要处理的问题</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-else class="panel list-panel">
        <div class="panel-heading split">
          <div>
            <h2>最近操作</h2>
            <p>记录谁在什么时间对哪所学校或哪项内容进行了操作，便于核对和查找问题。</p>
          </div>
          <a class="secondary-button" href="/ops/super-admin/audit-logs/export/">导出操作记录</a>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>操作</th><th>操作者</th><th>学校</th><th>相关内容</th><th>来源地址</th><th>详情</th></tr></thead>
            <tbody>
              <tr v-for="row in data.audit_logs" :key="row.id">
                <td>{{ formatDate(row.created_at) }}</td>
                <td><strong>{{ auditActionLabel(row.action) }}</strong></td>
                <td>{{ row.actor }}</td>
                <td>{{ row.school }}</td>
                <td>{{ row.target }}</td>
                <td>{{ row.ip_address }}</td>
                <td class="table-long-text">{{ detailText(row.detail) }}</td>
              </tr>
              <tr v-if="!data.audit_logs.length"><td colspan="7" class="empty">暂无操作日志</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </AppShell>
</template>
