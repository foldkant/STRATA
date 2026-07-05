<script setup lang="ts">
import AppShell from '@/layouts/AppShell.vue'
</script>

<template>
  <AppShell
    :title="String($route.meta.title || '工作台')"
    eyebrow="模块建设中"
    :nav-items="[{ label: String($route.meta.title || '工作台'), path: $route.path, active: true }]"
  >
    <section class="panel">
      <div class="panel-heading">
        <h2>模块建设中</h2>
        <p>该角色的 Vue 工作台会按 API 优先的方式继续迁移。</p>
      </div>
    </section>
  </AppShell>
</template>
