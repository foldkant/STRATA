<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import { getLearningPage, submitLearningPageForm, trackLearningPageBlock, type LearningPage, type LearningPageBlock } from '@/api/learningPages'
import LearningPageFrame from './LearningPageFrame.vue'
import OnlyOfficeEditor from './OnlyOfficeEditor.vue'

type PreviewResource = {
  id?: number | string
  title?: string
  content?: string
  attachment_url?: string
  attachment_name?: string
  file_ext?: string
  external_url?: string
  resource_type?: string
  kind?: string
  learning_page_id?: number | string
  revision_no?: number
}

const props = defineProps<{
  resource: PreviewResource | null
  officeMode?: 'view' | 'edit'
  closable?: boolean
  contentOnly?: boolean
  learningPageInteractive?: boolean
}>()

const emit = defineEmits<{
  close: []
  'resource-opened': [payload: {
    resourceId: number | string
    presentation: 'embedded' | 'popout' | 'external' | 'download' | 'unknown'
  }]
  'video-progress': [payload: {
    resourceId: number | string
    positionSeconds: number
    mediaSeconds: number
    playbackRate: number
    durationMs: number
  }]
}>()

const router = useRouter()
const learningPage = shallowRef<LearningPage | null>(null)
const learningPageLoading = ref(false)
const learningPageError = ref('')
const learningPageFrame = ref<InstanceType<typeof LearningPageFrame> | null>(null)
const videoElement = ref<HTMLVideoElement | null>(null)
let learningPageLoadToken = 0
let lastVideoReportAt = 0
let lastVideoPosition = 0

const knownExts = new Set([
  'png',
  'jpg',
  'jpeg',
  'webp',
  'gif',
  'bmp',
  'mp4',
  'webm',
  'ogg',
  'mov',
  'mp3',
  'wav',
  'm4a',
  'pdf',
  'doc',
  'docx',
  'ppt',
  'pptx',
  'xls',
  'xlsx',
  'zip',
  'rar',
  '7z'
])

function normalizeExt(value?: string) {
  const text = decodeURIComponent(value || '').toLowerCase().trim()
  const matches = [...text.matchAll(/\.?([a-z0-9]{1,8})(?=[^a-z0-9]*$)/g)]
  const candidate = matches.length ? matches[matches.length - 1][1] : text.replace(/^[.]+/, '').replace(/[^a-z0-9].*$/, '')
  return knownExts.has(candidate) ? candidate : ''
}

function detectExt() {
  const candidates = [
    props.resource?.file_ext,
    props.resource?.attachment_name,
    props.resource?.attachment_url?.split('?', 1)[0].split('#', 1)[0],
    props.resource?.title,
  ]
  for (const candidate of candidates) {
    const value = normalizeExt(candidate)
    if (value) return value
  }
  return ''
}

const title = computed(() => props.resource?.title || props.resource?.attachment_name || '未选择资源')
const url = computed(() => props.resource?.attachment_url || '')
const externalUrl = computed(() => props.resource?.external_url || '')
const ext = computed(detectExt)

const kind = computed(() => {
  if (props.resource?.kind === 'learning_page') return 'learning_page'
  if (props.resource?.resource_type === 'link') return 'link'
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(ext.value)) return 'image'
  if (['mp4', 'webm', 'ogg', 'mov'].includes(ext.value)) return 'video'
  if (['mp3', 'wav', 'm4a'].includes(ext.value)) return 'audio'
  if (ext.value === 'pdf') return 'pdf'
  if (['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'].includes(ext.value)) return 'office'
  if (['zip', 'rar', '7z'].includes(ext.value)) return 'archive'
  return 'resource'
})

const canEmbed = computed(() => Boolean(url.value && (url.value.startsWith('/') || /^https?:\/\//.test(url.value))))
const canUseOnlyOffice = computed(() => kind.value === 'office' && Boolean(props.resource?.id))
const learningPageId = computed(() => Number(props.resource?.learning_page_id || 0))
const learningPageRevision = computed(() => Number(props.resource?.revision_no || 0))
const learningPageKey = computed(() => {
  if (kind.value !== 'learning_page' || !learningPageId.value) return ''
  return `${learningPageId.value}:${learningPageRevision.value}`
})

const previewKey = computed(() => {
  if (!props.resource) return ''
  return [
    props.resource.kind || '',
    props.resource.id || '',
    props.resource.attachment_url || '',
    props.resource.external_url || '',
    props.resource.revision_no || '',
  ].join(':')
})

function trackableResourceId() {
  if (!props.resource || kind.value === 'learning_page') return null
  const value = props.resource.id
  return typeof value === 'number' || (typeof value === 'string' && /^\d+$/.test(value)) ? value : null
}

function emitResourceOpened(
  presentation: 'embedded' | 'popout' | 'external' | 'download' | 'unknown' = 'embedded'
) {
  const resourceId = trackableResourceId()
  if (resourceId === null) return
  emit('resource-opened', { resourceId, presentation })
}

function resetVideoTracking() {
  lastVideoReportAt = 0
  lastVideoPosition = 0
}

function startVideoTracking(event: Event) {
  const video = event.currentTarget as HTMLVideoElement
  lastVideoReportAt = performance.now()
  lastVideoPosition = Math.max(video.currentTime || 0, 0)
}

function reportVideoProgress(force = false) {
  const video = videoElement.value
  const resourceId = trackableResourceId()
  if (!video || resourceId === null) return
  const positionSeconds = Number(video.currentTime)
  const mediaSeconds = Number(video.duration)
  const playbackRate = Number(video.playbackRate || 1)
  if (!Number.isFinite(positionSeconds) || positionSeconds <= 0) return
  if (!Number.isFinite(mediaSeconds) || mediaSeconds <= 0) return
  const now = performance.now()
  if (!lastVideoReportAt) {
    lastVideoReportAt = now
    lastVideoPosition = positionSeconds
    return
  }
  const wallDurationMs = Math.max(now - lastVideoReportAt, 0)
  if (!force && wallDurationMs < 10_000) return
  const mediaDurationMs = Math.max(positionSeconds - lastVideoPosition, 0) * 1000 / Math.max(playbackRate, 0.25)
  emit('video-progress', {
    resourceId,
    positionSeconds,
    mediaSeconds,
    playbackRate,
    durationMs: Math.round(Math.min(wallDurationMs, mediaDurationMs, 600_000))
  })
  lastVideoReportAt = now
  lastVideoPosition = positionSeconds
}

async function loadLearningPage() {
  const loadToken = ++learningPageLoadToken
  learningPageError.value = ''
  if (!learningPageKey.value) {
    learningPage.value = null
    learningPageLoading.value = false
    return
  }
  learningPageLoading.value = true
  try {
    const page = await getLearningPage(learningPageId.value, 'embedded')
    if (loadToken === learningPageLoadToken) {
      learningPage.value = page
    }
  } catch (error) {
    if (loadToken === learningPageLoadToken) {
      learningPageError.value = error instanceof ApiError ? error.message : '学习网页加载失败。'
    }
  } finally {
    if (loadToken === learningPageLoadToken) {
      learningPageLoading.value = false
    }
  }
}

async function submitLearningPage(payload: { formId: string; answers: Record<string, unknown> }) {
  if (!learningPage.value || !props.learningPageInteractive) return
  try {
    await submitLearningPageForm(learningPage.value.id, payload.formId, payload.answers)
    learningPageFrame.value?.notifyResult(payload.formId, true, '提交成功')
  } catch (error) {
    const message = error instanceof ApiError ? error.message : '提交失败，请重试。'
    learningPageFrame.value?.notifyResult(payload.formId, false, message)
  }
}

async function trackLearningBlock(payload: { blockId: string; blockType: LearningPageBlock['type']; visibleMs: number; visibilityRatio: number }) {
  if (!learningPage.value || !props.learningPageInteractive) return
  try {
    await trackLearningPageBlock(learningPage.value.id, payload)
  } catch {
    // 行为采集失败不能中断学生当前的学习内容。
  }
}

function openLearningPageTab() {
  if (!learningPage.value) return
  const href = router.resolve(`/learning-pages/${learningPage.value.id}`).href
  window.open(href, '_blank', 'noopener,noreferrer')
}

watch(learningPageKey, loadLearningPage, { immediate: true })
watch(previewKey, (value) => {
  resetVideoTracking()
  if (value) emitResourceOpened('embedded')
}, { immediate: true, flush: 'post' })
onBeforeUnmount(() => reportVideoProgress(true))
</script>

<template>
  <section class="resource-preview-panel" :class="[`resource-preview-${kind}`, { 'resource-preview-content-only': contentOnly }]">
    <header v-if="!contentOnly">
      <div>
        <span>{{ kind.toUpperCase() }}</span>
        <h3>{{ title }}</h3>
        <p>{{ resource?.attachment_name || resource?.content || '网页内预览' }}</p>
      </div>
      <div class="resource-preview-actions">
        <a v-if="url" :href="url" download>下载</a>
        <a v-if="externalUrl" :href="externalUrl" target="_blank" rel="noopener noreferrer">打开链接</a>
        <button v-if="closable" type="button" @click="emit('close')">关闭</button>
      </div>
    </header>

    <div class="resource-preview-body" :class="`resource-preview-body-${kind}`">
      <div v-if="kind === 'learning_page'" class="learning-page-preview-shell">
        <button
          v-if="learningPage"
          class="learning-page-popout-button"
          type="button"
          title="在新标签页打开"
          aria-label="在新标签页打开学习网页"
          @click="openLearningPageTab"
        >
          新标签页打开
        </button>
        <p v-if="learningPageLoading && !learningPage" class="resource-preview-loading">正在加载学习网页...</p>
        <p v-else-if="learningPageError && !learningPage" class="resource-preview-error">{{ learningPageError }}</p>
        <LearningPageFrame
          v-else-if="learningPage"
          ref="learningPageFrame"
          :page="learningPage"
          :interactive="Boolean(learningPageInteractive)"
          @submit="submitLearningPage"
          @block-viewed="trackLearningBlock"
        />
      </div>
      <img v-else-if="kind === 'image' && canEmbed" :src="url" :alt="title" />
      <video
        v-else-if="kind === 'video' && canEmbed"
        ref="videoElement"
        :src="url"
        controls
        @play="startVideoTracking"
        @timeupdate="reportVideoProgress(false)"
        @pause="reportVideoProgress(true)"
        @ended="reportVideoProgress(true)"
      />
      <audio v-else-if="kind === 'audio' && canEmbed" :src="url" controls />
      <iframe v-else-if="kind === 'pdf' && canEmbed" :src="url" title="PDF 预览"></iframe>
      <OnlyOfficeEditor
        v-else-if="canUseOnlyOffice"
        :resource-id="resource!.id!"
        :mode="officeMode || 'view'"
      />
      <div v-else-if="kind === 'link'" class="resource-preview-empty resource-preview-link-card">
        <strong>{{ title }}</strong>
        <p>{{ resource?.content || '该资源需要联网访问外部链接。' }}</p>
        <a :href="externalUrl" target="_blank" rel="noopener noreferrer">在新标签页打开</a>
      </div>
      <div v-else class="resource-preview-empty">
        <strong>{{ title }}</strong>
        <p v-if="!resource">当前没有选择可预览资源。</p>
        <p v-if="kind === 'office'">该 Office 文件缺少资源编号，需从资源库重新加入课时后才能网页内预览。</p>
        <p v-else-if="kind === 'archive'">压缩包暂不在网页中直接展开，可下载后使用；后续会接文件清单预览。</p>
        <p v-else-if="resource">{{ resource.content || '该资源暂不支持网页内预览。' }}</p>
      </div>
    </div>

  </section>
</template>
