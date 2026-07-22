<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  createCurriculumNode,
  saveCurriculumNode,
  type CurriculumNode,
  type CurriculumNodePayload,
  type CurriculumStandardVersion
} from '@/api/curriculumStandards'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{
  version: CurriculumStandardVersion
  draft: CurriculumNode | null
}>()

const emit = defineEmits<{
  close: []
  saved: [row: CurriculumNode]
}>()

const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})
const form = reactive<CurriculumNodePayload>({
  node_type: props.draft?.node_type || 'course_content',
  code: props.draft?.code || '',
  title: props.draft?.title || '',
  content: props.draft?.content || '',
  parent: props.draft?.parent || null,
  source_page_start: props.draft?.source_page_start || 1,
  source_page_end: props.draft?.source_page_end || 1,
  source_paragraph: props.draft?.source_paragraph || '',
  sort_order: props.draft?.sort_order ?? props.version.nodes?.length ?? 0
})

function validate() {
  const next: FieldErrors = {}
  if (!form.code.trim()) next.code = ['请填写条目代码。']
  if (!form.title.trim()) next.title = ['请填写条目标题。']
  if (form.content.trim().length < 4) next.content = ['请填写可核验的课程标准原文。']
  if (!form.source_page_start) next.source_page_start = ['请填写原文起始页码。']
  if (!form.source_page_end) next.source_page_end = ['请填写原文结束页码。']
  if (form.source_page_start && form.source_page_end && form.source_page_end < form.source_page_start) {
    next.source_page_end = ['结束页码不能早于起始页码。']
  }
  errors.value = next
  return Object.keys(next).length === 0
}

async function save() {
  if (!validate()) return
  saving.value = true
  notice.value = ''
  try {
    const payload: CurriculumNodePayload = {
      ...form,
      code: form.code.trim(),
      title: form.title.trim(),
      content: form.content.trim()
    }
    const row = props.draft
      ? await saveCurriculumNode(props.draft.id, payload)
      : await createCurriculumNode(props.version.id, payload)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '课程标准内容条目保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section v-curriculum-modal-focus="() => emit('close')" class="entity-modal curriculum-node-editor" role="dialog" aria-modal="true" aria-labelledby="curriculum-node-editor-title">
      <header class="modal-header">
        <div>
          <h2 id="curriculum-node-editor-title">{{ draft ? '编辑课程标准内容条目' : '新增课程标准内容条目' }}</h2>
          <p>{{ version.version_label }} · 仅草稿版本可编辑</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
      </header>

      <div class="modal-body curriculum-node-form">
        <p v-if="notice" class="curriculum-form-error" role="alert">{{ notice }}</p>
        <label>
          <span>条目类型<b>*</b></span>
          <AppSelect v-model="form.node_type">
            <option value="core_competency">核心素养</option>
            <option value="course_objective">课程目标</option>
            <option value="course_content">课程内容</option>
            <option value="academic_quality">学业质量</option>
          </AppSelect>
        </label>
        <label>
          <span>条目代码<b>*</b></span>
          <input v-model.trim="form.code" maxlength="80" placeholder="例如 CC-1" />
          <small v-if="errors.code" class="field-error">{{ errors.code[0] }}</small>
        </label>
        <label class="span-2">
          <span>条目标题<b>*</b></span>
          <input v-model.trim="form.title" maxlength="240" />
          <small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small>
        </label>
        <label>
          <span>上级条目</span>
          <AppSelect v-model="form.parent">
            <option :value="null">无上级条目</option>
            <option v-for="node in (version.nodes || []).filter((item) => item.id !== draft?.id)" :key="node.id" :value="node.id">
              {{ node.code }} · {{ node.title }}
            </option>
          </AppSelect>
          <small>课程标准四类内容不一定构成固定单一路径，只按原文层级设置上级条目。</small>
        </label>
        <label>
          <span>排序序号</span>
          <input v-model.number="form.sort_order" type="number" min="0" />
        </label>
        <label>
          <span>原文起始页码</span>
          <input v-model.number="form.source_page_start" type="number" min="1" />
          <small v-if="errors.source_page_start" class="field-error">{{ errors.source_page_start[0] }}</small>
        </label>
        <label>
          <span>原文结束页码</span>
          <input v-model.number="form.source_page_end" type="number" min="1" />
          <small v-if="errors.source_page_end" class="field-error">{{ errors.source_page_end[0] }}</small>
        </label>
        <label class="span-2">
          <span>原文位置说明</span>
          <input v-model.trim="form.source_paragraph" maxlength="240" placeholder="例如 第三章 第2节" />
        </label>
        <label class="span-2">
          <span>课程标准原文<b>*</b></span>
          <textarea v-model="form.content" rows="9" placeholder="保留与 PDF 一致的原文内容。" />
          <small v-if="errors.content" class="field-error">{{ errors.content[0] }}</small>
        </label>
      </div>

      <footer class="modal-actions">
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存条目' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.curriculum-node-editor {
  width: min(860px, 100%);
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-node-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.curriculum-node-form label {
  min-width: 0;
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-node-form .span-2,
.curriculum-form-error {
  grid-column: 1 / -1;
}

.curriculum-node-form input,
.curriculum-node-form select,
.curriculum-node-form textarea {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff;
  color: var(--text);
  resize: vertical;
}

.curriculum-node-form b {
  margin-left: 2px;
  color: var(--danger);
}

.curriculum-node-form small {
  line-height: 1.5;
}

.curriculum-form-error {
  margin: 0;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fef2f2;
  color: #991b1b;
}

@media (max-width: 640px) {
  .curriculum-node-form {
    grid-template-columns: 1fr;
  }

  .curriculum-node-form .span-2,
  .curriculum-form-error {
    grid-column: auto;
  }
}
</style>
