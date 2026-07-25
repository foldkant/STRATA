<script setup lang="ts">
import type { LessonStepRow } from '@/api/teacher'

const props = defineProps<{
  steps: LessonStepRow[]
  selectedStepId: number | null
  currentStepId: number | null
  currentStepStatus: string
  stepStatusText: string
}>()

const emit = defineEmits<{
  select: [step: LessonStepRow]
}>()

function statusClass() {
  if (props.currentStepStatus === 'open') return 'status-running'
  if (props.currentStepStatus === 'locked') return 'status-locked'
  if (props.currentStepStatus === 'closed') return 'status-closed'
  return 'status-draft'
}

function stepBadgeClass(step: LessonStepRow) {
  return props.currentStepId === step.id ? statusClass() : 'status-draft'
}

function stepRunLabel(step: LessonStepRow) {
  return props.currentStepId === step.id ? props.stepStatusText : '待投放'
}
</script>

<template>
  <aside class="console-pane classroom-step-flow">
    <div class="console-pane-header">
      <div>
        <strong>学习过程</strong>
        <span>{{ steps.length }} 个环节</span>
      </div>
    </div>
    <div class="classroom-step-list">
      <button
        v-for="(step, index) in steps"
        :key="step.id"
        class="classroom-step-run"
        :class="{ active: step.id === selectedStepId, live: currentStepId === step.id }"
        type="button"
        :aria-pressed="step.id === selectedStepId"
        :aria-label="`第 ${index + 1} 环节：${step.title}，${stepRunLabel(step)}`"
        @click="emit('select', step)"
      >
        <em>{{ index + 1 }}</em>
        <span>
          <strong>{{ step.title }}</strong>
          <small>{{ step.step_type_label }} · {{ step.estimated_minutes }} 分钟 · {{ step.target_layer_label }}</small>
        </span>
        <i :class="stepBadgeClass(step)">{{ stepRunLabel(step) }}</i>
      </button>
      <p v-if="!steps.length" class="empty">该课堂尚未指定课时，或课时还没有已配置的学习环节。</p>
    </div>
  </aside>
</template>
