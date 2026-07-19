<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import {
  deleteLessonStepEvaluationBinding,
  getLessonStepEvaluationBinding,
  saveLessonStepEvaluationBinding,
  type LessonStepEvaluationBinding,
  type LessonStepEvaluationStandardOption
} from '@/api/evaluation'

const props = defineProps<{
  open: boolean
  lessonStepId: number | null
  lessonStepTitle: string
  courseTitle: string
}>()

const emit = defineEmits<{
  close: []
  saved: [binding: LessonStepEvaluationBinding | null]
}>()

const loading = ref(false)
const notice = ref('')
const binding = ref<LessonStepEvaluationBinding | null>(null)
const standards = ref<LessonStepEvaluationStandardOption[]>([])
const selectedStandardId = ref<number | null>(null)
const enableSelf = ref(false)
const enablePeer = ref(false)
const enableTeacher = ref(true)

const selectedStandard = computed(() => (
  standards.value.find((item) => item.id === selectedStandardId.value) || null
))
const locked = computed(() => Boolean(binding.value?.locked))
const canSave = computed(() => Boolean(
  selectedStandardId.value
  && (enableSelf.value || enablePeer.value || enableTeacher.value)
  && !locked.value
  && !loading.value
))

function syncBinding(row: LessonStepEvaluationBinding | null) {
  binding.value = row
  selectedStandardId.value = row?.standard_version || standards.value[0]?.id || null
  enableSelf.value = Boolean(row?.enable_self)
  enablePeer.value = Boolean(row?.enable_peer)
  enableTeacher.value = row ? Boolean(row.enable_teacher) : true
}

async function loadBinding() {
  if (!props.lessonStepId) return
  loading.value = true
  notice.value = ''
  try {
    const row = await getLessonStepEvaluationBinding(props.lessonStepId)
    standards.value = row.standards
    syncBinding(row.binding)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价标准加载失败。'
  } finally {
    loading.value = false
  }
}

async function saveBinding() {
  if (!props.lessonStepId || !selectedStandardId.value) return
  if (!enableSelf.value && !enablePeer.value && !enableTeacher.value) {
    notice.value = '至少选择一种评价方式。'
    return
  }
  loading.value = true
  try {
    const row = await saveLessonStepEvaluationBinding(props.lessonStepId, {
      standard_version: selectedStandardId.value,
      enable_self: enableSelf.value,
      enable_peer: enablePeer.value,
      enable_teacher: enableTeacher.value
    })
    binding.value = row
    notice.value = '当前环节已绑定评价标准。'
    emit('saved', row)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价标准保存失败。'
  } finally {
    loading.value = false
  }
}

async function clearBinding() {
  if (!props.lessonStepId || !binding.value || locked.value) return
  loading.value = true
  try {
    await deleteLessonStepEvaluationBinding(props.lessonStepId)
    syncBinding(null)
    notice.value = '已取消当前环节的评价标准。'
    emit('saved', null)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '取消绑定失败。'
  } finally {
    loading.value = false
  }
}

function close() {
  emit('close')
}

watch(
  () => [props.open, props.lessonStepId],
  async ([open]) => {
    if (open && props.lessonStepId) await loadBinding()
  },
  { immediate: true }
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open && lessonStepId" class="modal-backdrop" role="presentation" @click.self="close">
      <section class="entity-modal step-evaluation-modal" role="dialog" aria-modal="true" aria-labelledby="step-evaluation-title">
        <header class="modal-header">
          <div>
            <h2 id="step-evaluation-title">环节评价</h2>
            <p>{{ courseTitle }} · {{ lessonStepTitle }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" :disabled="loading" @click="close">×</button>
        </header>

        <p v-if="notice" class="notice-line" role="status">{{ notice }}</p>
        <p v-if="locked" class="step-evaluation-lock" role="status">
          该版本已用于课堂，当前绑定已锁定。后续调整请复制环节后选择新版本。
        </p>

        <div class="step-evaluation-body">
          <section class="step-standard-selector" aria-labelledby="standard-selector-title">
            <header>
              <div>
                <span>已发布标准</span>
                <strong id="standard-selector-title">选择本环节使用的版本</strong>
              </div>
              <RouterLink class="secondary-button mini" to="/teacher/evaluations" @click="close">管理标准</RouterLink>
            </header>

            <div v-if="standards.length" class="step-standard-list">
              <label
                v-for="item in standards"
                :key="item.id"
                :class="{ active: selectedStandardId === item.id }"
              >
                <input v-model="selectedStandardId" type="radio" :value="item.id" :disabled="locked" />
                <span>
                  <strong>{{ item.title }}</strong>
                  <small>版本 {{ item.version_no }} · {{ item.criterion_count }} 项 · {{ item.review_status_label }}</small>
                </span>
              </label>
            </div>
            <div v-else-if="!loading" class="step-evaluation-empty">
              <strong>本课程还没有已发布的评价标准</strong>
              <span>先到评价标准库完成标准并发布版本，再返回当前环节选择。</span>
            </div>

            <fieldset class="step-evaluation-types" :disabled="locked || !selectedStandard">
              <legend>评价方式</legend>
              <label><input v-model="enableSelf" type="checkbox" />学生自评</label>
              <label><input v-model="enablePeer" type="checkbox" />小组互评</label>
              <label><input v-model="enableTeacher" type="checkbox" />教师评价</label>
            </fieldset>
          </section>

          <section class="step-standard-preview" aria-labelledby="standard-preview-title">
            <header>
              <span>标准预览</span>
              <strong id="standard-preview-title">{{ selectedStandard?.title || '请选择评价标准' }}</strong>
            </header>
            <div v-if="selectedStandard" class="step-criterion-list">
              <article v-for="criterion in selectedStandard.criteria" :key="criterion.id">
                <header>
                  <div>
                    <span>{{ criterion.code }} · {{ criterion.dimension_label }}</span>
                    <strong>{{ criterion.title }}</strong>
                  </div>
                  <small>{{ criterion.evaluation_sources.join('、') }}</small>
                </header>
                <p>{{ criterion.expected_performance }}</p>
                <details>
                  <summary>查看 1-5 星说明</summary>
                  <ol>
                    <li v-for="(description, index) in criterion.level_descriptions" :key="index">
                      <strong>{{ index + 1 }} 星</strong>
                      <span>{{ description }}</span>
                    </li>
                  </ol>
                  <p v-if="criterion.skip_condition" class="criterion-skip">不评价：{{ criterion.skip_condition }}</p>
                </details>
              </article>
            </div>
            <p v-else class="empty">选择左侧标准后查看评价指标和星级说明。</p>
          </section>
        </div>

        <footer class="modal-actions step-evaluation-actions">
          <button class="secondary-button" type="button" :disabled="loading" @click="close">关闭</button>
          <button v-if="binding" class="text-danger-button" type="button" :disabled="loading || locked" @click="clearBinding">取消绑定</button>
          <button class="primary-button" type="button" :disabled="!canSave" @click="saveBinding">
            {{ loading ? '保存中...' : '保存当前环节' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.step-evaluation-modal {
  width: min(1120px, calc(100vw - 32px));
  max-height: min(820px, calc(100dvh - 32px));
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}

.step-evaluation-lock {
  margin: 0;
  padding: 10px 24px;
  border-block: 1px solid #fed7aa;
  color: #9a3412;
  background: #fff7ed;
  font-size: 13px;
}

.step-evaluation-body {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(260px, 0.8fr) minmax(0, 1.7fr);
  overflow: hidden;
}

.step-standard-selector,
.step-standard-preview {
  min-width: 0;
  padding: 20px 24px;
  overflow-y: auto;
}

.step-standard-selector {
  border-right: 1px solid var(--line);
  background: #f8fafc;
}

.step-standard-selector > header,
.step-standard-preview > header,
.step-criterion-list article > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.step-standard-selector > header div,
.step-standard-preview > header,
.step-criterion-list article > header div {
  display: grid;
  gap: 4px;
}

.step-standard-selector > header span,
.step-standard-preview > header span,
.step-criterion-list article > header span {
  color: var(--muted);
  font-size: 12px;
}

.step-standard-list {
  display: grid;
  gap: 8px;
  margin-top: 16px;
}

.step-standard-list label {
  min-height: 56px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  cursor: pointer;
}

.step-standard-list label.active {
  border-color: var(--primary);
  box-shadow: inset 3px 0 0 var(--primary);
}

.step-standard-list input {
  margin-top: 4px;
}

.step-standard-list span {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.step-standard-list strong,
.step-standard-list small {
  overflow-wrap: anywhere;
}

.step-standard-list small {
  color: var(--muted);
}

.step-evaluation-types {
  display: grid;
  gap: 8px;
  margin: 20px 0 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}

.step-evaluation-types legend {
  padding: 0 6px;
  font-weight: 700;
}

.step-evaluation-types label {
  min-height: 40px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.step-standard-preview > header {
  margin-bottom: 16px;
}

.step-criterion-list {
  display: grid;
  gap: 12px;
}

.step-criterion-list article {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}

.step-criterion-list article > header small {
  max-width: 42%;
  color: var(--muted);
  text-align: right;
  overflow-wrap: anywhere;
}

.step-criterion-list article > p {
  margin: 12px 0;
  color: #334155;
  line-height: 1.65;
}

.step-criterion-list details {
  border-top: 1px solid var(--line);
  padding-top: 10px;
}

.step-criterion-list summary {
  min-height: 40px;
  display: flex;
  align-items: center;
  color: var(--primary-dark);
  font-weight: 700;
  cursor: pointer;
}

.step-criterion-list ol {
  display: grid;
  gap: 8px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.step-criterion-list li {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 10px;
  color: #334155;
  line-height: 1.55;
}

.criterion-skip {
  margin: 12px 0 0;
  padding: 10px 12px;
  color: #92400e;
  background: #fffbeb;
  border-left: 3px solid #f59e0b;
}

.step-evaluation-empty {
  display: grid;
  gap: 6px;
  margin-top: 16px;
  padding: 16px;
  border: 1px dashed var(--line);
  color: var(--muted);
  background: var(--surface);
}

.step-evaluation-actions {
  border-top: 1px solid var(--line);
  background: var(--surface);
}

@media (max-width: 760px) {
  .modal-backdrop {
    padding: 8px;
  }

  .step-evaluation-modal {
    width: 100%;
    max-height: calc(100dvh - 16px);
  }

  .step-evaluation-body {
    display: block;
    overflow-y: auto;
  }

  .step-standard-selector,
  .step-standard-preview {
    overflow: visible;
    padding: 16px;
  }

  .step-standard-selector {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .step-criterion-list article > header {
    display: grid;
  }

  .step-criterion-list article > header small {
    max-width: none;
    text-align: left;
  }

  .step-evaluation-actions {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
