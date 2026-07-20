<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  layer?: string | null
  label?: string
  compact?: boolean
}>(), {
  layer: '',
  label: '',
  compact: false
})

const normalizedLayer = computed(() => ['A', 'B', 'C'].includes(String(props.layer)) ? String(props.layer) : '')
const fallbackLabel = computed(() => ({
  A: '拓展挑战层',
  B: '核心发展层',
  C: '基础提升层'
}[normalizedLayer.value] || '未分层'))
</script>

<template>
  <span class="layer-badge" :class="[`layer-${normalizedLayer || 'unassigned'}`, { compact }]">
    <strong>{{ normalizedLayer || '-' }}</strong>
    <small v-if="!compact">{{ label || fallbackLabel }}</small>
  </span>
</template>

<style scoped>
.layer-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  background: #f8fafc;
  padding: 4px 9px;
  color: #475569;
  white-space: nowrap;
}

.layer-badge strong {
  display: grid;
  place-items: center;
  width: 23px;
  height: 23px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #334155;
  font-size: 13px;
  line-height: 1;
}

.layer-badge small {
  font-size: 12px;
  font-weight: 700;
}

.layer-A { border-color: #99d5cb; background: #effaf7; color: #0f6258; }
.layer-A strong { background: #0f766e; color: #fff; }
.layer-B { border-color: #a9c9f2; background: #f0f6ff; color: #174f91; }
.layer-B strong { background: #2563a9; color: #fff; }
.layer-C { border-color: #e5c38e; background: #fff8e9; color: #7c4a0e; }
.layer-C strong { background: #b7791f; color: #fff; }

.layer-badge.compact {
  min-width: 34px;
  min-height: 30px;
  justify-content: center;
  padding: 3px;
}
</style>
