<script setup lang="ts" generic="T extends { id: number }">
import { nextTick, onMounted, onUpdated, ref } from 'vue'

withDefaults(defineProps<{
  title: string
  description: string
  total: number
  page: number
  pageSize: number
  rows: T[]
  loading?: boolean
  query: string
  status?: string
  statusOptions?: Array<{ label: string; value: string }>
  primaryLabel?: string
  bulkLabel?: string
  showExport?: boolean
  showTemplate?: boolean
  showImport?: boolean
}>(), {
  showExport: true,
  showTemplate: true,
  showImport: true
})
const tableWrap = ref<HTMLElement | null>(null)

const emit = defineEmits<{
  search: [payload: { q: string; status: string }]
  reset: []
  create: []
  export: []
  template: []
  import: []
  bulk: []
  page: [page: number]
  'update:query': [value: string]
  'update:status': [value: string]
}>()

function labelMobileCells() {
  const table = tableWrap.value?.querySelector('table')
  if (!table) return
  const labels = Array.from(table.querySelectorAll('thead th')).map(
    (cell) => cell.textContent?.trim() || '内容'
  )
  table.querySelectorAll('tbody tr').forEach((row) => {
    Array.from(row.children).forEach((cell, index) => {
      if (!(cell instanceof HTMLTableCellElement) || cell.classList.contains('empty')) return
      if (!cell.dataset.label) cell.dataset.label = labels[index] || '内容'
    })
  })
}

function scheduleMobileLabels() {
  void nextTick(labelMobileCells)
}

onMounted(scheduleMobileLabels)
onUpdated(scheduleMobileLabels)
</script>

<template>
  <section class="management-panel">
    <div class="panel-heading split">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </div>
      <div class="heading-actions">
        <button v-if="showExport !== false" class="secondary-button" type="button" @click="emit('export')">导出表格</button>
        <button v-if="showTemplate !== false" class="secondary-button" type="button" @click="emit('template')">下载导入模板</button>
        <button v-if="showImport !== false" class="secondary-button" type="button" @click="emit('import')">批量导入</button>
        <slot name="actions-extra" />
        <button v-if="bulkLabel" class="secondary-button" type="button" @click="emit('bulk')">{{ bulkLabel }}</button>
        <button v-if="primaryLabel" class="primary-button" type="button" @click="emit('create')">{{ primaryLabel }}</button>
      </div>
    </div>

    <form class="toolbar" @submit.prevent="emit('search', { q: query, status: status || '' })">
      <label>
        <span>关键词</span>
        <input
          :value="query"
          placeholder="输入账号、姓名或编号"
          @input="emit('update:query', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <label v-if="statusOptions?.length">
        <span>状态</span>
        <AppSelect :value="status" @change="emit('update:status', ($event.target as HTMLSelectElement).value)">
          <option v-for="item in statusOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </AppSelect>
      </label>
      <button class="primary-button" type="submit">查询</button>
      <button class="secondary-button" type="button" @click="emit('reset')">重置</button>
      <div class="toolbar-actions">
        <slot name="toolbar-actions" />
      </div>
    </form>

    <slot name="bulk-actions" />

    <div ref="tableWrap" class="table-wrap management-table">
      <table>
        <slot name="head" />
        <tbody>
          <tr v-if="loading">
            <td class="empty" colspan="12">正在加载</td>
          </tr>
          <template v-else-if="rows.length">
            <slot name="rows" :rows="rows" />
          </template>
          <tr v-else>
            <td class="empty" colspan="12">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="pager">
      <span>共 {{ total }} 条</span>
      <div>
        <button class="secondary-button" type="button" :disabled="page <= 1 || loading" @click="emit('page', page - 1)">上一页</button>
        <strong>{{ page }}</strong>
        <button
          class="secondary-button"
          type="button"
          :disabled="page * pageSize >= total || loading"
          @click="emit('page', page + 1)"
        >
          下一页
        </button>
      </div>
    </footer>
  </section>
</template>
