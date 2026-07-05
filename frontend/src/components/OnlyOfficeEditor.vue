<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import { getResourceOfficeConfig, type OnlyOfficePayload } from '@/api/office'
import NoticeLine from './NoticeLine.vue'

declare global {
  interface Window {
    DocsAPI?: {
      DocEditor: new (elementId: string, config: Record<string, unknown>) => { destroyEditor?: () => void }
    }
  }
}

const props = defineProps<{
  resourceId: number | string
  mode?: 'view' | 'edit'
}>()

const containerId = `onlyoffice-${Math.random().toString(36).slice(2)}`
const loading = ref(false)
const notice = ref('')
let editor: { destroyEditor?: () => void } | null = null

function destroyEditor() {
  if (editor?.destroyEditor) {
    editor.destroyEditor()
  }
  editor = null
}

function loadScript(serverUrl: string) {
  const scriptUrl = `${serverUrl.replace(/\/$/, '')}/web-apps/apps/api/documents/api.js`
  const existing = document.querySelector<HTMLScriptElement>(`script[data-onlyoffice-api="${scriptUrl}"]`)
  if (existing && window.DocsAPI) {
    return Promise.resolve()
  }
  return new Promise<void>((resolve, reject) => {
    const script = existing || document.createElement('script')
    script.dataset.onlyofficeApi = scriptUrl
    script.src = scriptUrl
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('ONLYOFFICE API 加载失败。'))
    if (!existing) {
      document.head.appendChild(script)
    }
  })
}

async function openEditor() {
  if (!props.resourceId) return
  loading.value = true
  notice.value = ''
  destroyEditor()
  try {
    const payload: OnlyOfficePayload = await getResourceOfficeConfig(props.resourceId, props.mode || 'view')
    await loadScript(payload.server_url)
    if (!window.DocsAPI) {
      throw new Error('ONLYOFFICE API 不可用。')
    }
    editor = new window.DocsAPI.DocEditor(containerId, payload.config)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : error instanceof Error ? error.message : '文档编辑器打开失败。'
  } finally {
    loading.value = false
  }
}

watch(() => [props.resourceId, props.mode] as const, openEditor, { immediate: true })
onBeforeUnmount(destroyEditor)
</script>

<template>
  <div class="onlyoffice-editor-shell">
    <NoticeLine v-if="notice" :message="notice" />
    <p v-if="loading" class="onlyoffice-loading">正在加载 ONLYOFFICE 编辑器</p>
    <div :id="containerId" class="onlyoffice-editor-frame"></div>
  </div>
</template>
