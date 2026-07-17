<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  generateTeacherLearningPage,
  getTeacherLearningPageResponses,
  getTeacherLearningPages,
  reviseTeacherLearningPage,
  type LearningPage,
  type LearningPageGenerationMode,
  type LearningPageResponseSummary
} from '@/api/learningPages'
import type { ResourceBinding } from '@/api/teacher'
import LearningPageFrame from '@/components/LearningPageFrame.vue'
import LearningPageStatsModal from '@/components/teacher/LearningPageStatsModal.vue'

const props = defineProps<{
  lessonId: number
  lessonTitle: string
  activeStepId: number | null
  resourceItems: Array<ResourceBinding | string>
}>()

const emit = defineEmits<{
  addResource: [resource: ResourceBinding]
  updateResource: [resource: ResourceBinding]
}>()

const router = useRouter()
const pages = ref<LearningPage[]>([])
const selectedPageId = ref<number | null>(null)
const loading = ref(false)
const generating = ref(false)
const revising = ref(false)
const direction = ref('')
const revisionDirection = ref('')
const generationMode = ref<LearningPageGenerationMode>('auto')
const revisionMode = ref<LearningPageGenerationMode>('auto')
const notice = ref('')
const error = ref('')
const statsOpen = ref(false)
const statsLoading = ref(false)
const stats = ref<LearningPageResponseSummary | null>(null)

const selectedPage = computed(() => pages.value.find((item) => item.id === selectedPageId.value) || pages.value[0] || null)
const pageInStep = computed(() => {
  if (!selectedPage.value) return false
  return props.resourceItems.some((item) => typeof item !== 'string' && Number(item.learning_page_id || 0) === selectedPage.value?.id)
})

async function loadPages() {
  loading.value = true
  error.value = ''
  try {
    pages.value = await getTeacherLearningPages(props.lessonId)
    if (!selectedPageId.value || !pages.value.some((item) => item.id === selectedPageId.value)) {
      selectedPageId.value = pages.value[0]?.id || null
    }
  } catch (loadError) {
    error.value = loadError instanceof ApiError ? loadError.message : '学习网页加载失败。'
  } finally {
    loading.value = false
  }
}

async function generatePage() {
  const requirement = direction.value.trim()
  if (requirement.length < 4) {
    error.value = '请填写清晰的网页生成要求。'
    return
  }
  generating.value = true
  error.value = ''
  notice.value = ''
  try {
    const page = await generateTeacherLearningPage(props.lessonId, requirement, generationMode.value)
    pages.value = [page, ...pages.value]
    selectedPageId.value = page.id
    direction.value = ''
    notice.value = `已生成《${page.title}》。`
  } catch (generateError) {
    error.value = generateError instanceof ApiError ? generateError.message : 'AI 学习网页生成失败。'
  } finally {
    generating.value = false
  }
}

async function revisePage() {
  if (!selectedPage.value) return
  const requirement = revisionDirection.value.trim()
  if (requirement.length < 4) {
    error.value = '请填写本次修改要求。'
    return
  }
  revising.value = true
  error.value = ''
  notice.value = ''
  try {
    const page = await reviseTeacherLearningPage(selectedPage.value.id, requirement, revisionMode.value)
    pages.value = pages.value.map((item) => item.id === page.id ? page : item)
    if (pageInStep.value) {
      emit('updateResource', learningPageResource(page))
    }
    revisionDirection.value = ''
    notice.value = `已更新至 v${page.revision_no}。`
  } catch (reviseError) {
    error.value = reviseError instanceof ApiError ? reviseError.message : 'AI 修改失败。'
  } finally {
    revising.value = false
  }
}

function learningPageResource(page: LearningPage): ResourceBinding {
  return {
    id: `learning-page-${page.id}`,
    learning_page_id: page.id,
    revision_no: page.revision_no,
    title: page.title,
    attachment_url: '',
    attachment_name: '',
    file_ext: '',
    kind: 'learning_page'
  }
}

function addToStep() {
  if (!selectedPage.value || !props.activeStepId || pageInStep.value) return
  emit('addResource', learningPageResource(selectedPage.value))
  notice.value = '已加入当前环节，请保存环节内容。'
}

async function openStats() {
  if (!selectedPage.value) return
  statsOpen.value = true
  statsLoading.value = true
  error.value = ''
  try {
    stats.value = await getTeacherLearningPageResponses(selectedPage.value.id)
  } catch (statsError) {
    error.value = statsError instanceof ApiError ? statsError.message : '表单统计加载失败。'
  } finally {
    statsLoading.value = false
  }
}

function openPageTab() {
  if (!selectedPage.value) return
  const href = router.resolve(`/learning-pages/${selectedPage.value.id}`).href
  window.open(href, '_blank', 'noopener,noreferrer')
}

watch(() => props.lessonId, loadPages)
onMounted(loadPages)
</script>

<template>
  <section class="learning-page-studio">
    <div class="learning-page-studio-toolbar">
      <div>
        <strong>AI 学习网页</strong>
        <span>{{ pages.length }} 个网页</span>
      </div>
      <a href="/app/teacher/ai" target="_blank" rel="noopener">AI 接入</a>
    </div>

    <p v-if="error" class="learning-page-studio-message error">{{ error }}</p>
    <p v-if="notice" class="learning-page-studio-message success">{{ notice }}</p>

    <div class="learning-page-mode-field">
      <span>生成方式</span>
      <div class="learning-page-mode-switch" role="group" aria-label="学习网页生成方式">
        <button type="button" :class="{ active: generationMode === 'auto' }" @click="generationMode = 'auto'">智能选择</button>
        <button type="button" :class="{ active: generationMode === 'interactive' }" @click="generationMode = 'interactive'">自由交互动画</button>
        <button type="button" :class="{ active: generationMode === 'structured' }" @click="generationMode = 'structured'">受控演示</button>
      </div>
      <small v-if="generationMode === 'interactive'">生成自包含 HTML、CSS 与 JavaScript，可用于 Canvas、SVG、模拟实验和可播放动画。</small>
      <small v-else-if="generationMode === 'structured'">使用平台固定动画组件，适合流程、时间线、柱状对比和二进制演示。</small>
      <small v-else>要求中出现动画、交互或模拟时自动生成自由交互动画，其他内容使用受控组件。</small>
    </div>

    <label class="learning-page-direction">
      <span>生成要求</span>
      <textarea
        v-model.trim="direction"
        rows="5"
        maxlength="3000"
        placeholder="例如：制作一份数据编码学习任务单，包含任务情境、可播放的二进制编码过程动画、两道选择题和学习反思表单。"
      ></textarea>
      <button class="primary-button" type="button" :disabled="generating || direction.trim().length < 4" @click="generatePage">
        {{ generating ? 'AI 生成中...' : '生成学习网页' }}
      </button>
    </label>

    <div v-if="pages.length" class="learning-page-tabs">
      <button
        v-for="page in pages"
        :key="page.id"
        type="button"
        :class="{ active: selectedPage?.id === page.id }"
        @click="selectedPageId = page.id"
      >
        <strong>{{ page.title }}</strong>
        <span>v{{ page.revision_no }} · {{ page.form_count }} 个表单</span>
      </button>
    </div>

    <section v-if="selectedPage" class="learning-page-selected">
      <header>
        <div>
          <span>v{{ selectedPage.revision_no }} · {{ selectedPage.block_count }} 个区块 · {{ selectedPage.response_count }} 次提交</span>
          <strong>{{ selectedPage.title }}</strong>
        </div>
        <div>
          <button class="secondary-button mini" type="button" @click="openPageTab">新标签页预览</button>
          <button class="secondary-button mini" type="button" @click="openStats">表单统计</button>
          <button
            class="primary-button mini"
            type="button"
            :disabled="!activeStepId || pageInStep"
            @click="addToStep"
          >
            {{ pageInStep ? '已在当前环节' : activeStepId ? '加入当前环节' : '请先选择环节' }}
          </button>
        </div>
      </header>

      <div class="learning-page-studio-preview">
        <LearningPageFrame :page="selectedPage" />
      </div>

      <div class="learning-page-mode-field revision-mode-field">
        <span>本次修改方式</span>
        <div class="learning-page-mode-switch" role="group" aria-label="学习网页修改方式">
          <button type="button" :class="{ active: revisionMode === 'auto' }" @click="revisionMode = 'auto'">智能选择</button>
          <button type="button" :class="{ active: revisionMode === 'interactive' }" @click="revisionMode = 'interactive'">自由交互动画</button>
          <button type="button" :class="{ active: revisionMode === 'structured' }" @click="revisionMode = 'structured'">受控演示</button>
        </div>
      </div>

      <label class="learning-page-revision">
        <span>继续修改</span>
        <textarea
          v-model.trim="revisionDirection"
          rows="3"
          maxlength="3000"
          placeholder="例如：保留现有表单，把操作步骤改成可播放的流程动画，并增加一张编码位数柱状对比动画。"
        ></textarea>
        <button class="secondary-button" type="button" :disabled="revising || revisionDirection.trim().length < 4" @click="revisePage">
          {{ revising ? 'AI 修改中...' : '按要求修改' }}
        </button>
      </label>
    </section>

    <p v-else-if="loading" class="empty">正在加载学习网页...</p>
    <p v-else class="empty">还没有学习网页，填写要求后生成。</p>

    <LearningPageStatsModal
      :open="statsOpen"
      :loading="statsLoading"
      :stats="stats"
      :fallback-title="selectedPage?.title"
      @close="statsOpen = false"
      @refresh="openStats"
    />
  </section>
</template>
