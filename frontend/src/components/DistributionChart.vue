<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  rows: Array<{ label: string; count: number }>
}>()

const total = computed(() => props.rows.reduce((sum, item) => sum + item.count, 0))

function width(count: number) {
  if (!total.value) return '0%'
  return `${Math.max((count / total.value) * 100, count ? 6 : 0)}%`
}
</script>

<template>
  <article class="chart-card">
    <header>
      <h3>{{ title }}</h3>
      <span>{{ total }}</span>
    </header>
    <div class="distribution-list">
      <div v-for="item in rows" :key="item.label" class="distribution-row">
        <div class="distribution-meta">
          <span>{{ item.label }}</span>
          <strong>{{ item.count }}</strong>
        </div>
        <div class="distribution-track">
          <i :style="{ width: width(item.count) }" />
        </div>
      </div>
    </div>
  </article>
</template>
