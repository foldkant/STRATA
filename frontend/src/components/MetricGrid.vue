<script setup lang="ts">
import type { Metric } from '@/api/dashboards'

defineProps<{ metrics: Metric[] }>()
</script>

<template>
  <section class="metric-grid" aria-label="关键指标">
    <article v-for="item in metrics" :key="item.label" class="metric-card">
      <span>{{ item.label }}</span>
      <strong>{{ item.value }}</strong>
      <small>{{ item.sub }}</small>
    </article>
  </section>
</template>
