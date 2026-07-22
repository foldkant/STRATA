<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  getCurriculumReferenceOptions,
  type CurriculumNode,
  type CurriculumNodeType,
  type CurriculumReferenceStandard,
  type CurriculumSchoolStage
} from '@/api/curriculumStandards'
import { buildCurriculumReferenceNode } from './curriculumReference'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{
  selected: CurriculumNode[]
  subjectCode?: string
  subjectName?: string
  schoolStage?: CurriculumSchoolStage | ''
}>()

const emit = defineEmits<{
  close: []
  apply: [nodes: CurriculumNode[]]
}>()

const standards = ref<CurriculumReferenceStandard[]>([])
const selectedStandardId = ref<number | ''>('')
const selectedIds = ref<number[]>(props.selected.map((node) => node.id))
const query = ref('')
const nodeType = ref<CurriculumNodeType | ''>('')
const loading = ref(false)
const notice = ref('')

const currentStandard = computed(() => standards.value.find((item) => item.id === selectedStandardId.value) || null)
const currentVersion = computed(() => currentStandard.value?.current_version || null)
const availableNodes = computed(() => {
  const search = query.value.trim().toLocaleLowerCase('zh-CN')
  return (currentVersion.value?.nodes || []).filter((node) => {
    if (nodeType.value && node.node_type !== nodeType.value) return false
    if (!search) return true
    return `${node.code} ${node.title} ${node.content}`.toLocaleLowerCase('zh-CN').includes(search)
  })
})
const selectedNodes = computed(() => {
  const selectedMap = new Map<number, CurriculumNode>()
  props.selected.forEach((node) => selectedMap.set(node.id, node))
  standards.value.forEach((standard) => {
    const versionNodes = standard.current_version.nodes || []
    versionNodes.forEach((node) => {
      selectedMap.set(node.id, buildCurriculumReferenceNode(node, standard))
    })
  })
  return selectedIds.value.map((id) => selectedMap.get(id)).filter((node): node is CurriculumNode => Boolean(node))
})
const selectedTypes = computed(() => new Set(selectedNodes.value.map((node) => node.node_type)))

function nodeTypeLabel(value: CurriculumNodeType) {
  return {
    core_competency: '核心素养',
    course_objective: '课程目标',
    course_content: '课程内容',
    academic_quality: '学业质量'
  }[value]
}

function stageLabel(value: CurriculumSchoolStage) {
  return value === 'k1_k9' ? '义务教育（K1—K9）' : '普通高中（K10—K12）'
}

function pageLabel(node: CurriculumNode) {
  if (!node.source_page_start) return '原文页码未标注'
  if (!node.source_page_end || node.source_page_end === node.source_page_start) return `第 ${node.source_page_start} 页`
  return `第 ${node.source_page_start}—${node.source_page_end} 页`
}

function toggleNode(id: number, checked: boolean) {
  selectedIds.value = checked
    ? Array.from(new Set([...selectedIds.value, id]))
    : selectedIds.value.filter((item) => item !== id)
}

function changeStandard(event: Event) {
  const nextId = Number((event.target as HTMLSelectElement).value)
  if (nextId === selectedStandardId.value) return
  if (selectedIds.value.length) {
    selectedIds.value = []
    notice.value = '已切换课程标准版本，原选择已清空，避免在同一评价方案中混用版本。'
  }
  selectedStandardId.value = nextId
  query.value = ''
  nodeType.value = ''
}

async function load() {
  loading.value = true
  notice.value = ''
  try {
    const result = await getCurriculumReferenceOptions({
      subject_code: props.subjectCode,
      subject_name: props.subjectName,
      school_stage: props.schoolStage || ''
    })
    standards.value = result.standards
    const selectedVersionId = props.selected[0]?.version_id || props.selected[0]?.version
    const matched = standards.value.find((item) => item.current_version.id === selectedVersionId)
    selectedStandardId.value = matched?.id || standards.value[0]?.id || ''

    if (matched) {
      const available = new Set((matched.current_version.nodes || []).map((node) => node.id))
      selectedIds.value = selectedIds.value.filter((id) => available.has(id))
    } else if (props.selected.length) {
      selectedIds.value = []
      notice.value = '原评价方案引用的是历史课程标准版本。历史依据仍可在方案中查看；如需修订引用，请重新选择当前使用版本。'
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准引用加载失败。'
  } finally {
    loading.value = false
  }
}

function apply() {
  emit('apply', selectedNodes.value)
}

onMounted(load)
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop curriculum-reference-backdrop" @click.self="emit('close')">
      <section v-curriculum-modal-focus="() => emit('close')" class="entity-modal curriculum-reference-picker" role="dialog" aria-modal="true" aria-labelledby="curriculum-reference-title">
        <header class="modal-header">
          <div>
            <h2 id="curriculum-reference-title">选择课程标准依据</h2>
            <p>从已发布版本中选择课程标准原文内容条目；课程标准只读，引用会随评价方案版本保留。</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
        </header>

        <div class="curriculum-reference-body">
          <p v-if="notice" class="curriculum-reference-notice" role="status">{{ notice }}</p>

          <section class="curriculum-reference-context">
            <label>
              <span>课程标准版本</span>
              <select :value="selectedStandardId" :disabled="loading || !standards.length" @change="changeStandard">
                <option v-if="!standards.length" value="">暂无可用版本</option>
                <option v-for="standard in standards" :key="standard.id" :value="standard.id">
                  {{ standard.title }} · {{ standard.current_version.version_label }}
                </option>
              </select>
            </label>
            <div v-if="currentStandard" class="curriculum-reference-version">
              <span>当前选择</span>
              <strong>{{ currentStandard.subject_name }} · {{ stageLabel(currentStandard.school_stage) }}</strong>
              <small>
                {{ currentStandard.current_version.version_label }}
                · {{ currentStandard.current_version.publication_year || '年份未标注' }}
                · 校验值 {{ currentStandard.current_version.content_hash?.slice(0, 12) || '未提供' }}
              </small>
              <div>
                <a v-if="currentStandard.current_version.pdf_url" :href="currentStandard.current_version.pdf_url" target="_blank" rel="noopener">查看 PDF 原文</a>
                <a v-if="currentStandard.current_version.source_url" :href="currentStandard.current_version.source_url" target="_blank" rel="noopener">查看权威来源</a>
              </div>
            </div>
          </section>

          <section class="curriculum-reference-coverage" aria-label="已选课程标准内容">
            <div v-for="type in ['core_competency', 'course_objective', 'course_content', 'academic_quality'] as CurriculumNodeType[]" :key="type" :class="{ selected: selectedTypes.has(type) }">
              <span aria-hidden="true">{{ selectedTypes.has(type) ? '✓' : '—' }}</span>
              <strong>{{ nodeTypeLabel(type) }}</strong>
            </div>
            <p>四类内容相互联系，并非固定的单向层级；请按本次课程内容和评价用途选择相关原文。</p>
          </section>

          <div class="curriculum-reference-toolbar">
            <label>
              <span>检索原文</span>
              <input v-model="query" placeholder="条目代码、标题或原文内容" />
            </label>
            <label>
              <span>条目类型</span>
              <AppSelect v-model="nodeType">
                <option value="">全部类型</option>
                <option value="core_competency">核心素养</option>
                <option value="course_objective">课程目标</option>
                <option value="course_content">课程内容</option>
                <option value="academic_quality">学业质量</option>
              </AppSelect>
            </label>
          </div>

          <div class="curriculum-reference-list" :aria-busy="loading">
            <p v-if="loading" class="curriculum-reference-empty">正在加载课程标准内容条目</p>
            <p v-else-if="!standards.length" class="curriculum-reference-empty">没有与当前课程匹配的已发布课程标准，请联系超级管理员完成发布。</p>
            <p v-else-if="!availableNodes.length" class="curriculum-reference-empty">没有符合筛选条件的内容条目</p>
            <article v-for="node in availableNodes" v-else :key="node.id" :class="{ selected: selectedIds.includes(node.id) }">
              <label>
                <input
                  type="checkbox"
                  :checked="selectedIds.includes(node.id)"
                  @change="toggleNode(node.id, ($event.target as HTMLInputElement).checked)"
                />
                <span>
                  <em>{{ nodeTypeLabel(node.node_type) }}</em>
                  <strong>{{ node.code }} · {{ node.title }}</strong>
                  <small>{{ pageLabel(node) }} · {{ currentVersion?.version_label }}</small>
                </span>
              </label>
              <details>
                <summary>查看课程标准原文</summary>
                <p>{{ node.content }}</p>
              </details>
            </article>
          </div>
        </div>

        <footer class="modal-actions curriculum-reference-actions">
          <span>已选择 {{ selectedIds.length }} 个内容条目</span>
          <button v-if="selectedIds.length" class="secondary-button" type="button" @click="selectedIds = []">清空选择</button>
          <button class="secondary-button" type="button" @click="emit('close')">取消</button>
          <button class="primary-button" type="button" :disabled="loading" @click="apply">确认引用</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.curriculum-reference-backdrop {
  z-index: 1200;
}

.curriculum-reference-picker {
  width: min(1040px, 100%);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-reference-body {
  min-height: 0;
  overflow: auto;
  padding: 18px 20px;
}

.curriculum-reference-notice {
  margin: 0 0 14px;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  padding: 9px 11px;
  background: #eff6ff;
  color: #1e40af;
  line-height: 1.5;
}

.curriculum-reference-context {
  display: grid;
  grid-template-columns: minmax(250px, .8fr) minmax(0, 1.2fr);
  gap: 14px;
}

.curriculum-reference-context > label,
.curriculum-reference-toolbar label {
  display: grid;
  align-content: start;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-reference-context select,
.curriculum-reference-toolbar input,
.curriculum-reference-toolbar select {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 9px 11px;
  background: #fff;
  color: var(--text);
}

.curriculum-reference-version {
  display: grid;
  gap: 4px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 11px 13px;
  background: #fbfdff;
}

.curriculum-reference-version > span,
.curriculum-reference-version small {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-reference-version > div {
  display: flex;
  gap: 14px;
  margin-top: 3px;
}

.curriculum-reference-version a {
  color: var(--primary);
  font-size: 13px;
}

.curriculum-reference-coverage {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  background: #f8fafc;
}

.curriculum-reference-coverage > div {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 8px 10px;
  color: var(--muted);
  background: #fff;
}

.curriculum-reference-coverage > div.selected {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}

.curriculum-reference-coverage p {
  grid-column: 1 / -1;
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.curriculum-reference-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 12px;
  margin-top: 16px;
}

.curriculum-reference-list {
  display: grid;
  gap: 9px;
  margin-top: 12px;
}

.curriculum-reference-list article {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}

.curriculum-reference-list article.selected {
  border-color: #93c5fd;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, .08);
}

.curriculum-reference-list article > label {
  min-height: 64px;
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 11px 13px;
  cursor: pointer;
}

.curriculum-reference-list input {
  width: 19px;
  height: 19px;
  margin-top: 2px;
}

.curriculum-reference-list label > span {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.curriculum-reference-list em {
  width: fit-content;
  border-radius: 999px;
  padding: 2px 7px;
  background: #e8f1ff;
  color: var(--primary-dark);
  font-size: 11px;
  font-style: normal;
}

.curriculum-reference-list small {
  color: var(--muted);
}

.curriculum-reference-list details {
  border-top: 1px solid var(--line);
}

.curriculum-reference-list summary {
  min-height: 42px;
  display: flex;
  align-items: center;
  padding: 7px 13px;
  color: var(--primary);
  cursor: pointer;
}

.curriculum-reference-list details p {
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.curriculum-reference-empty {
  min-height: 160px;
  display: grid;
  place-items: center;
  margin: 0;
  border: 1px dashed var(--line);
  border-radius: 6px;
  padding: 20px;
  color: var(--muted);
  text-align: center;
}

.curriculum-reference-actions > span {
  margin-right: auto;
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 700px) {
  .curriculum-reference-context,
  .curriculum-reference-toolbar,
  .curriculum-reference-coverage {
    grid-template-columns: 1fr;
  }

  .curriculum-reference-coverage p {
    grid-column: auto;
  }

  .curriculum-reference-actions {
    flex-wrap: wrap;
  }

  .curriculum-reference-actions > span {
    width: 100%;
  }
}
</style>
