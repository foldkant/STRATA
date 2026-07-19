<script setup lang="ts">
import { computed } from 'vue'

type ClassChipItem = {
  id: number | string
  name: string
  grade?: string
}

const props = withDefaults(defineProps<{
  classes: ClassChipItem[]
  maxVisible?: number
  emptyLabel?: string
}>(), {
  maxVisible: 3,
  emptyLabel: '未设置'
})

const visibleClasses = computed(() => props.classes.slice(0, Math.max(props.maxVisible, 0)))
const remainingCount = computed(() => Math.max(props.classes.length - visibleClasses.value.length, 0))

function classLabel(item: ClassChipItem) {
  return `${item.grade ? `${item.grade} ` : ''}${item.name}`.trim()
}
</script>

<template>
  <div class="class-chip-list">
    <span v-for="item in visibleClasses" :key="item.id" class="class-chip">{{ classLabel(item) }}</span>
    <span v-if="remainingCount" class="class-chip class-chip-more" :title="`还有 ${remainingCount} 个班级`">+{{ remainingCount }}</span>
    <span v-if="!classes.length" class="muted-text">{{ emptyLabel }}</span>
  </div>
</template>
