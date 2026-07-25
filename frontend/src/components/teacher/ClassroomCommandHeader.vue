<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { ClassroomCommandPayload, ClassroomSessionRow } from '@/api/teacher'

defineProps<{
  session: ClassroomSessionRow
  currentStepTitle: string
  stepStatusText: string
  classLabel: string
  saving: boolean
  loading: boolean
  controls: {
    canStart: boolean
    canFinish: boolean
    canRestart: boolean
  }
  commands: ReadonlyArray<{ command: ClassroomCommandPayload['command']; label: string }>
  groupEnabled: boolean
  groupStatusText: string
  evaluationEnabled: boolean
}>()

const emit = defineEmits<{
  refresh: []
  start: []
  finish: []
  restart: []
  command: [value: ClassroomCommandPayload['command']]
  openGroup: []
  openEvaluation: []
}>()
</script>

<template>
  <header class="classroom-console-top classroom-control-header">
    <div>
      <p>{{ session.course?.title || '未绑定课程' }} · {{ session.lesson?.title || '未绑定课时' }} · {{ classLabel }}</p>
      <h2>{{ session.title }}</h2>
      <span>
        当前环节：{{ currentStepTitle || '未投放' }} · {{ stepStatusText }}
        <template v-if="session.submission_locked"> · 提交已锁定</template>
      </span>
    </div>
    <div class="lesson-designer-actions">
      <RouterLink class="secondary-button" to="/teacher/classroom">课堂列表</RouterLink>
      <RouterLink v-if="session.lesson" class="secondary-button" :to="`/teacher/lessons/${session.lesson.id}/design`">课时设计</RouterLink>
      <button class="secondary-button" type="button" :disabled="loading" @click="emit('refresh')">刷新状态</button>
      <button v-if="controls.canStart" class="primary-button" type="button" :disabled="saving" @click="emit('start')">开始课堂</button>
      <button v-if="controls.canFinish" class="primary-button danger" type="button" :disabled="saving" @click="emit('finish')">结束课堂</button>
      <button v-if="controls.canRestart" class="primary-button" type="button" :disabled="saving" @click="emit('restart')">重新开始</button>
    </div>
  </header>

  <section class="classroom-control-strip classroom-command-strip classroom-command-strip-top" aria-label="课堂快捷操作">
    <button
      v-for="item in commands"
      :key="item.command"
      type="button"
      :disabled="saving || session.status !== 'running'"
      @click="emit('command', item.command)"
    >
      {{ item.label }}
    </button>
    <button
      type="button"
      :class="{ active: groupEnabled }"
      :disabled="saving || session.status === 'finished'"
      @click="emit('openGroup')"
    >
      小组合作
      <small v-if="groupStatusText">{{ groupStatusText }}</small>
    </button>
    <button
      type="button"
      :class="{ active: evaluationEnabled }"
      :disabled="saving || session.status === 'finished'"
      @click="emit('openEvaluation')"
    >
      评价情况
      <small v-if="evaluationEnabled">已开放</small>
    </button>
  </section>
</template>
