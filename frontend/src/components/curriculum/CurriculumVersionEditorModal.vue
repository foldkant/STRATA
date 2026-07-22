<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  createCurriculumStandardVersion,
  saveCurriculumStandardVersion,
  type CurriculumStandard,
  type CurriculumStandardVersion,
  type CurriculumVersionPayload
} from '@/api/curriculumStandards'
import { vCurriculumModalFocus } from './curriculumModalFocus'

const props = defineProps<{
  standard: CurriculumStandard
  draft?: CurriculumStandardVersion | null
  replaces?: CurriculumStandardVersion | null
}>()

const emit = defineEmits<{
  close: []
  saved: [row: CurriculumStandardVersion]
}>()

const saving = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})
const selectedFile = ref<File | null>(null)
const form = reactive<CurriculumVersionPayload>({
  version_label: props.draft?.version_label || '',
  publication_year: props.draft?.publication_year || new Date().getFullYear(),
  effective_year: props.draft?.effective_year || new Date().getFullYear(),
  issued_by: props.draft?.issued_by || '中华人民共和国教育部',
  official_title: props.draft?.official_title || props.draft?.title || '',
  source_url: props.draft?.source_url || '',
  source_note: props.draft?.source_note || '',
  structured_text: props.draft?.structured_text || '',
  pdf_file: null,
  replaces_version: props.replaces?.id || props.draft?.replaces_version || null
})

const modalTitle = computed(() => {
  if (props.draft) return '编辑课程标准草稿版本'
  if (props.replaces) return '新增取代版本'
  return '新增课程标准版本'
})

function fileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] || null
  form.pdf_file = selectedFile.value
  errors.value.pdf_file = []
}

function validate() {
  const next: FieldErrors = {}
  if (!form.version_label.trim()) next.version_label = ['请填写正式版本标识。']
  if (!form.official_title.trim()) next.official_title = ['请按照原文填写正式名称。']
  if (!form.publication_year) next.publication_year = ['请填写发布年份。']
  if (!form.issued_by.trim()) next.issued_by = ['请填写发布机构。']
  if (!props.draft && !selectedFile.value) next.pdf_file = ['请上传 PDF 原文。']
  if (selectedFile.value && selectedFile.value.type !== 'application/pdf' && !selectedFile.value.name.toLowerCase().endsWith('.pdf')) {
    next.pdf_file = ['仅支持 PDF 原文文件。']
  }
  errors.value = next
  return Object.keys(next).length === 0
}

async function save() {
  if (!validate()) return
  saving.value = true
  notice.value = ''
  try {
    const payload: CurriculumVersionPayload = {
      ...form,
      version_label: form.version_label.trim(),
      issued_by: form.issued_by.trim(),
      official_title: form.official_title.trim(),
      source_url: form.source_url.trim(),
      source_note: form.source_note.trim(),
      structured_text: props.draft && (form.structured_text || '').trim() === (props.draft.structured_text || '').trim()
        ? undefined
        : (form.structured_text || '').trim(),
      pdf_file: selectedFile.value
    }
    const row = props.draft
      ? await saveCurriculumStandardVersion(props.draft.id, payload)
      : await createCurriculumStandardVersion(props.standard.id, payload)
    emit('saved', row)
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '课程标准版本保存失败。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section v-curriculum-modal-focus="() => emit('close')" class="entity-modal curriculum-version-editor" role="dialog" aria-modal="true" aria-labelledby="curriculum-version-editor-title">
      <header class="modal-header">
        <div>
          <h2 id="curriculum-version-editor-title">{{ modalTitle }}</h2>
          <p>{{ standard.title }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="关闭" data-modal-initial-focus @click="emit('close')">×</button>
      </header>

      <div class="modal-body curriculum-version-form">
        <p v-if="notice" class="curriculum-form-error" role="alert">{{ notice }}</p>
        <aside v-if="replaces" class="replacement-notice">
          新版本将取代“{{ replaces.version_label }}”成为当前使用版本。原版本及已有评价引用会完整保留。
        </aside>
        <label>
          <span>版本标识<b>*</b></span>
          <input v-model.trim="form.version_label" maxlength="80" placeholder="例如 2022年版" />
          <small v-if="errors.version_label" class="field-error">{{ errors.version_label[0] }}</small>
        </label>
        <label class="span-2">
          <span>正式名称<b>*</b></span>
          <input v-model="form.official_title" maxlength="240" placeholder="请按课程标准原文封面填写，不使用简称" />
          <small>正式名称将原样用于课程标准引用，不会根据学科名称自动改写。</small>
          <small v-if="errors.official_title" class="field-error">{{ errors.official_title[0] }}</small>
        </label>
        <label>
          <span>发布机构<b>*</b></span>
          <input v-model.trim="form.issued_by" maxlength="160" />
          <small v-if="errors.issued_by" class="field-error">{{ errors.issued_by[0] }}</small>
        </label>
        <label>
          <span>发布年份<b>*</b></span>
          <input v-model.number="form.publication_year" type="number" min="1900" max="2100" />
          <small v-if="errors.publication_year" class="field-error">{{ errors.publication_year[0] }}</small>
        </label>
        <label>
          <span>实施年份</span>
          <input v-model.number="form.effective_year" type="number" min="1900" max="2100" />
        </label>
        <label class="span-2">
          <span>权威来源网址</span>
          <input v-model.trim="form.source_url" type="url" maxlength="500" placeholder="教育行政部门发布页面" />
        </label>
        <label class="span-2">
          <span>来源说明</span>
          <textarea v-model="form.source_note" rows="3" placeholder="例如：教育部发布页面、文件来源和版本核验说明" />
          <small>用于记录文件来源及核验依据，便于后续更新与追溯。</small>
        </label>
        <label v-if="!draft" class="span-2">
          <span>PDF 原文<b>*</b></span>
          <input type="file" accept=".pdf,application/pdf" @change="fileSelected" />
          <small>保留原始 PDF，供页码核验和历史追溯。系统先登记文件并提取内嵌文字；扫描件将显示为“待文字识别”，由受控后台或离线任务处理后再逐页复核。PDF 保存后不可在同一版本中替换。</small>
          <small v-if="errors.pdf_file" class="field-error">{{ errors.pdf_file[0] }}</small>
        </label>
        <aside v-else class="span-2 pdf-locked-notice">
          PDF 原文已保存并计算校验值。若原文文件有变化，请新增课程标准版本，不能在当前版本中覆盖。
        </aside>
        <label class="span-2">
          <span>结构化文本</span>
          <textarea v-model="form.structured_text" rows="11" placeholder="多页 PDF 请按实际页序保留完整的 # PDF 第 N 页 标记；单页 PDF 可直接填写经校对的文本。" />
          <small>多页 PDF 的人工文本必须保留完整的“# PDF 第 N 页”页标记，并与 PDF 实际页数一致；无页标记的纯文本仅允许用于单页 PDF。结构化文本用于检索和辅助阅读，不替代 PDF 原文。</small>
        </label>
      </div>

      <footer class="modal-actions">
        <span>草稿可继续校对；发布后通过新增版本修订。</span>
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存草稿' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.curriculum-version-editor {
  width: min(900px, 100%);
}

.modal-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-version-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.curriculum-version-form label {
  min-width: 0;
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
}

.curriculum-version-form .span-2,
.curriculum-form-error,
.replacement-notice {
  grid-column: 1 / -1;
}

.pdf-locked-notice {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  background: #f8fafc;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.55;
}

.curriculum-version-form input,
.curriculum-version-form textarea {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff;
  color: var(--text);
  resize: vertical;
}

.curriculum-version-form input[type='file'] {
  padding: 7px;
}

.curriculum-version-form b {
  margin-left: 2px;
  color: var(--danger);
}

.curriculum-version-form small {
  line-height: 1.5;
}

.curriculum-form-error,
.replacement-notice {
  margin: 0;
  border-radius: 6px;
  padding: 10px 12px;
  line-height: 1.55;
}

.curriculum-form-error {
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #991b1b;
}

.replacement-notice {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1e40af;
}

.modal-actions > span {
  margin-right: auto;
  color: var(--muted);
  font-size: 12px;
}

@media (max-width: 640px) {
  .curriculum-version-form {
    grid-template-columns: 1fr;
  }

  .curriculum-version-form .span-2,
  .curriculum-form-error,
  .replacement-notice {
    grid-column: auto;
  }

  .modal-actions {
    flex-wrap: wrap;
  }

  .modal-actions > span {
    width: 100%;
  }
}
</style>
