<script setup lang="ts">
defineProps<{ active: boolean }>()
</script>

<template>
  <span class="status-pill" :class="active ? 'status-active' : 'status-disabled'">
    {{ active ? '启用' : '停用' }}
  </span>
</template>
