<script setup lang="ts">
import { computed } from 'vue'
import OnlyOfficeEditor from './OnlyOfficeEditor.vue'

type PreviewResource = {
  id?: number | string
  title?: string
  content?: string
  attachment_url?: string
  attachment_name?: string
  file_ext?: string
}

const props = defineProps<{
  resource: PreviewResource | null
  officeMode?: 'view' | 'edit'
  closable?: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

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
const ext = computed(detectExt)

const kind = computed(() => {
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
</script>

<template>
  <section class="resource-preview-panel" :class="`resource-preview-${kind}`">
    <header>
      <div>
        <span>{{ kind.toUpperCase() }}</span>
        <h3>{{ title }}</h3>
        <p>{{ resource?.attachment_name || resource?.content || '网页内预览' }}</p>
      </div>
      <div class="resource-preview-actions">
        <a v-if="url" :href="url" download>下载</a>
        <button v-if="closable" type="button" @click="emit('close')">关闭</button>
      </div>
    </header>

    <div class="resource-preview-body" :class="`resource-preview-body-${kind}`">
      <img v-if="kind === 'image' && canEmbed" :src="url" :alt="title" />
      <video v-else-if="kind === 'video' && canEmbed" :src="url" controls />
      <audio v-else-if="kind === 'audio' && canEmbed" :src="url" controls />
      <iframe v-else-if="kind === 'pdf' && canEmbed" :src="url" title="PDF 预览"></iframe>
      <OnlyOfficeEditor
        v-else-if="canUseOnlyOffice"
        :resource-id="resource!.id!"
        :mode="officeMode || 'view'"
      />
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
