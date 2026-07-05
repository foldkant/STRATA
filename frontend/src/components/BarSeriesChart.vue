<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  rows: Array<{ label: string; count: number }>
}>()

const maxValue = computed(() => Math.max(...props.rows.map((item) => item.count), 1))

function height(count: number) {
  return `${Math.max((count / maxValue.value) * 100, count ? 8 : 0)}%`
}
</script>

<template>
  <article class="chart-card chart-card-wide">
    <header>
      <h3>{{ title }}</h3>
      <span>{{ rows.reduce((sum, item) => sum + item.count, 0) }}</span>
    </header>
    <div class="bar-series">
      <div v-for="item in rows" :key="item.label" class="bar-item">
        <div class="bar-track">
          <i :style="{ height: height(item.count) }" />
        </div>
        <span>{{ item.label }}</span>
        <strong>{{ item.count }}</strong>
      </div>
    </div>
  </article>
</template>
