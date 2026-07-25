<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import { getGroupOfficeConfig, getResourceOfficeConfig, type OnlyOfficePayload } from '@/api/office'
import NoticeLine from './NoticeLine.vue'

declare global {
  interface Window {
    DocsAPI?: {
      DocEditor: new (elementId: string, config: Record<string, unknown>) => { destroyEditor?: () => void }
    }
  }
}

const props = defineProps<{
  resourceId?: number | string
  groupId?: number | string
  mode?: 'view' | 'edit'
  fallbackUrl?: string
  fallbackTitle?: string
}>()

const containerId = `onlyoffice-${Math.random().toString(36).slice(2)}`
const loading = ref(false)
const notice = ref('')
const fallbackDocument = ref<{ url: string; title: string } | null>(null)
const previewReady = ref(false)
let editor: { destroyEditor?: () => void } | null = null
let onlyOfficeServerOrigin = ''
let readinessTimeout: ReturnType<typeof window.setTimeout> | null = null

function extractFallbackDocument(config: Record<string, unknown>) {
  const documentConfig = config.document as { url?: unknown; title?: unknown } | undefined
  const url = typeof documentConfig?.url === 'string' ? documentConfig.url : ''
  const title = typeof documentConfig?.title === 'string' ? documentConfig.title : '下载文档'
  return url ? { url, title } : null
}

function destroyEditor() {
  if (readinessTimeout !== null) {
    window.clearTimeout(readinessTimeout)
    readinessTimeout = null
  }
  try {
    editor?.destroyEditor?.()
  } catch {
    // The external editor may already be partially disposed after a runtime
    // failure. Clearing the local reference still allows the download fallback.
  }
  editor = null
  previewReady.value = false
}

function showPreviewFailure(message: string) {
  destroyEditor()
  notice.value = message
}

function handleOnlyOfficeRuntimeError(event: ErrorEvent) {
  const detail = `${event.filename || ''}\n${event.error?.stack || event.message || ''}`
  if (
    !onlyOfficeServerOrigin
    || !detail.includes(onlyOfficeServerOrigin)
    || !detail.includes('/web-apps/')
  ) {
    return
  }
  event.preventDefault()
  showPreviewFailure('文档预览服务本次加载失败。请重新加载；如仍无法打开，可先下载原文件继续学习。')
}

function loadScript(serverUrl: string) {
  const scriptUrl = `${serverUrl.replace(/\/$/, '')}/web-apps/apps/api/documents/api.js`
  const existing = document.querySelector<HTMLScriptElement>(`script[data-onlyoffice-api="${scriptUrl}"]`)
  if (existing && window.DocsAPI) {
    return Promise.resolve()
  }
  return new Promise<void>((resolve, reject) => {
    const script = existing || document.createElement('script')
    let finished = false
    const finish = (error?: Error) => {
      if (finished) return
      finished = true
      window.clearTimeout(timeoutHandle)
      if (error) reject(error)
      else resolve()
    }
    const timeoutHandle = window.setTimeout(
      () => finish(new Error('文档预览服务响应超时。')),
      8_000
    )
    script.dataset.onlyofficeApi = scriptUrl
    script.src = scriptUrl
    script.onload = () => finish()
    script.onerror = () => finish(new Error('文档预览服务加载失败。'))
    if (!existing) {
      document.head.appendChild(script)
    }
  })
}

async function openEditor() {
  if (!props.resourceId && !props.groupId) return
  loading.value = true
  notice.value = ''
  fallbackDocument.value = props.fallbackUrl
    ? {
        url: props.fallbackUrl,
        title: props.fallbackTitle || '下载文档'
      }
    : null
  destroyEditor()
  try {
    const payload: OnlyOfficePayload = props.groupId
      ? await getGroupOfficeConfig(props.groupId, props.mode || 'view')
      : await getResourceOfficeConfig(props.resourceId!, props.mode || 'view')
    onlyOfficeServerOrigin = new URL(payload.server_url, window.location.origin).origin
    fallbackDocument.value = extractFallbackDocument(payload.config) || fallbackDocument.value
    await loadScript(payload.server_url)
    if (!window.DocsAPI) {
      throw new Error('ONLYOFFICE API 不可用。')
    }
    const configuredEvents = (
      payload.config.events && typeof payload.config.events === 'object'
        ? payload.config.events
        : {}
    ) as Record<string, unknown>
    const configuredOnAppReady = typeof configuredEvents.onAppReady === 'function'
      ? configuredEvents.onAppReady as (...args: unknown[]) => void
      : null
    const configuredOnError = typeof configuredEvents.onError === 'function'
      ? configuredEvents.onError as (...args: unknown[]) => void
      : null
    const editorConfig = {
      ...payload.config,
      events: {
        ...configuredEvents,
        onAppReady: (...args: unknown[]) => {
          configuredOnAppReady?.(...args)
          previewReady.value = true
          if (readinessTimeout !== null) {
            window.clearTimeout(readinessTimeout)
            readinessTimeout = null
          }
        },
        onError: (...args: unknown[]) => {
          configuredOnError?.(...args)
          showPreviewFailure('文档预览服务报告加载失败。请重新加载；如仍无法打开，可先下载原文件继续学习。')
        }
      }
    }
    editor = new window.DocsAPI.DocEditor(containerId, editorConfig)
    if (!previewReady.value) {
      readinessTimeout = window.setTimeout(
        () => showPreviewFailure('文档预览服务未能按时准备完成。请重新加载；如仍无法打开，可先下载原文件继续学习。'),
        8_000
      )
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : error instanceof Error ? error.message : '文档编辑器打开失败。'
  } finally {
    loading.value = false
  }
}

watch(() => [props.resourceId, props.groupId, props.mode] as const, openEditor, { immediate: true })
onMounted(() => window.addEventListener('error', handleOnlyOfficeRuntimeError))
onBeforeUnmount(() => {
  window.removeEventListener('error', handleOnlyOfficeRuntimeError)
  destroyEditor()
})
</script>

<template>
  <div class="onlyoffice-editor-shell">
    <NoticeLine v-if="notice" :message="notice" />
    <p v-if="loading" class="onlyoffice-loading">正在加载 ONLYOFFICE 编辑器</p>
    <div v-if="!notice && !previewReady && fallbackDocument" class="onlyoffice-loading-recovery">
      <span>预览正在加载，您也可以先下载原文件。</span>
      <a :href="fallbackDocument.url" download>{{ fallbackDocument.title }}</a>
    </div>
    <div v-if="notice" class="onlyoffice-fallback" role="alert">
      <strong>文档预览暂不可用</strong>
      <p>可以重新加载；如仍无法打开，请先下载原文件继续学习。</p>
      <div>
        <button type="button" :disabled="loading" @click="openEditor">重新加载</button>
        <a v-if="fallbackDocument" :href="fallbackDocument.url" download>{{ fallbackDocument.title }}</a>
      </div>
    </div>
    <div :id="containerId" class="onlyoffice-editor-frame"></div>
  </div>
</template>
