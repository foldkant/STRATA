<script setup lang="ts">
import type {
  ClassroomGroupCollaborationPayload,
  ClassroomGroupCollaborationRow,
  ClassroomGroupRow,
  GroupingCandidate,
  GroupingCandidateAssignment,
  GroupingCandidateRun
} from '@/api/teacher'
import OnlyOfficeEditor from '@/components/OnlyOfficeEditor.vue'

type GroupingStrategyOption = {
  value: string
  label: string
  description: string
}

defineProps<{
  open: boolean
  loading: boolean
  sessionTitle: string
  classLabel: string
  collaboration: ClassroomGroupCollaborationRow | null
  strategyOptions: readonly GroupingStrategyOption[]
  groupingRun: GroupingCandidateRun | null
  selectedCandidate: GroupingCandidate | null
  fallbackMessage: string
  collaborationStatusText: string
  groups: ClassroomGroupRow[]
}>()

const form = defineModel<ClassroomGroupCollaborationPayload>('form', { required: true })
const candidateKey = defineModel<string>('candidateKey', { required: true })
const groupingDraft = defineModel<GroupingCandidateAssignment[]>('groupingDraft', { required: true })
const groupingLocks = defineModel<Record<number, boolean>>('groupingLocks', { required: true })
const groupingNote = defineModel<string>('groupingNote', { required: true })
const activeDocument = defineModel<ClassroomGroupRow | null>('activeDocument', { required: true })

const emit = defineEmits<{
  close: []
  save: [regenerate: boolean]
  closeCollaboration: []
  selectCandidate: [key: string]
  dragStart: [studentId: number]
  dragEnd: []
  drop: [groupNo: number]
  setStudentGroup: [studentId: number, event: Event]
  confirm: []
  refresh: []
}>()

function groupMembersText(group: ClassroomGroupRow) {
  return group.members.map((member) => member.display_name || member.username).join('、') || '暂无成员'
}

function groupStorageStyle(group: ClassroomGroupRow, collaboration: ClassroomGroupCollaborationRow | null) {
  const quota = Number(collaboration?.storage_quota_mb || 0) * 1024 * 1024
  const percent = quota ? Math.min(100, Math.round((group.used_storage_bytes / quota) * 100)) : 0
  return { width: `${percent}%` }
}

function formatFileSize(size: number) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function currentStudentGroup(studentId: number) {
  return groupingDraft.value.find((group) => group.members.some((member) => member.student_id === studentId))?.group_no || 1
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" role="presentation" @click.self="emit('close')">
    <section class="entity-modal group-collaboration-modal" role="dialog" aria-modal="true" aria-labelledby="group-collaboration-title" :aria-busy="loading">
      <header class="modal-header">
        <div><h2 id="group-collaboration-title">小组分组合作</h2><p>{{ sessionTitle }} · {{ classLabel }}</p></div>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="group-collaboration-body">
        <section class="group-collaboration-settings">
          <label><span>每组人数</span><input v-model.number="form.group_size" type="number" min="2" max="12" /></label>
          <label>
            <span>分组方式</span>
            <AppSelect v-model="form.grouping_strategy" aria-label="分组方式">
              <option v-for="item in strategyOptions" :key="item.value" :value="item.value" :title="item.description">{{ item.label }}</option>
            </AppSelect>
          </label>
          <label><span>协作文档</span><AppSelect v-model="form.document_type"><option value="docx">Word 文档</option><option value="pptx">PPT 演示</option><option value="xlsx">Excel 表格</option></AppSelect></label>
          <label><span>小组空间</span><div class="group-storage-input"><input v-model.number="form.storage_quota_mb" type="number" min="10" max="2048" aria-label="小组空间容量" /><span>MB</span></div></label>
          <label class="group-collaboration-check"><input v-model="form.allow_onlyoffice_edit" type="checkbox" /><span>允许学生在线协作编辑</span></label>
          <label class="group-collaboration-check"><input v-model="form.allow_student_upload" type="checkbox" /><span>允许学生上传小组共享文件</span></label>
          <div class="group-collaboration-actions">
            <button class="primary-button" type="button" :disabled="loading" @click="emit('save', false)">{{ collaboration ? '保存设置' : '开启小组合作' }}</button>
            <button class="secondary-button" type="button" :disabled="loading || !collaboration" @click="emit('save', true)">{{ groupingRun ? '重新计算' : '生成分组候选' }}</button>
            <button v-if="collaboration?.status === 'open'" class="secondary-button danger" type="button" :disabled="loading" @click="emit('closeCollaboration')">关闭合作</button>
          </div>
        </section>

        <section v-if="groupingRun" class="grouping-candidate-workspace">
          <header class="grouping-candidate-header"><div><span>{{ groupingRun.status_label }}</span><strong>选择并调整分组方案</strong></div><small>锁定的学生在重新计算时保持当前小组</small></header>
          <p v-if="fallbackMessage" class="grouping-fallback-message" role="status">{{ fallbackMessage }}</p>
          <div class="grouping-candidate-tabs" role="tablist" aria-label="分组候选">
            <button v-for="candidate in groupingRun.candidates" :key="candidate.key" type="button" role="tab" :class="{ active: candidateKey === candidate.key }" :aria-selected="candidateKey === candidate.key" @click="emit('selectCandidate', candidate.key)">
              <strong>{{ candidate.label }}</strong><span>{{ candidate.assignments.length }} 组 · 人数差 {{ candidate.fairness.group_size_gap }}</span>
            </button>
          </div>

          <div v-if="selectedCandidate" class="grouping-plan-editor">
            <article v-for="group in groupingDraft" :key="group.group_no" class="grouping-draft-group" @dragover.prevent @drop="emit('drop', group.group_no)">
              <header><strong>第{{ group.group_no }}组</strong><span>{{ group.members.length }} 人</span></header>
              <div class="grouping-draft-members">
                <div v-for="member in group.members" :key="member.student_id" class="grouping-draft-member" :class="{ locked: groupingLocks[member.student_id] }" :draggable="!groupingLocks[member.student_id]" @dragstart="emit('dragStart', member.student_id)" @dragend="emit('dragEnd')">
                  <div><strong>{{ member.display_name || member.username }}</strong><small>{{ member.student_no || member.username }}</small></div>
                  <label><span class="sr-only">调整小组</span><AppSelect :value="currentStudentGroup(member.student_id)" :disabled="groupingLocks[member.student_id]" @change="emit('setStudentGroup', member.student_id, $event)"><option v-for="target in groupingDraft" :key="target.group_no" :value="target.group_no">第{{ target.group_no }}组</option></AppSelect></label>
                  <label><span class="sr-only">调整角色</span><AppSelect v-model="member.role"><option value="coordinator">协调</option><option value="recorder">记录</option><option value="resource">资源</option><option value="presenter">展示</option><option value="verifier">核验</option><option value="member">成员</option></AppSelect></label>
                  <label class="grouping-lock-toggle"><input v-model="groupingLocks[member.student_id]" type="checkbox" /><span>锁定</span></label>
                </div>
              </div>
            </article>
          </div>

          <div class="grouping-confirm-row"><label><span>调整说明</span><input v-model="groupingNote" maxlength="500" placeholder="可选，记录本次人工调整原因" /></label><button class="primary-button" type="button" :disabled="loading || !selectedCandidate" @click="emit('confirm')">确认启用</button></div>
        </section>

        <section class="group-collaboration-list">
          <header><div><span>{{ collaborationStatusText }}</span><strong>分组与共享空间</strong></div><button class="secondary-button mini" type="button" :disabled="loading" @click="emit('refresh')">刷新</button></header>
          <div v-if="groups.length" class="group-card-grid">
            <article v-for="group in groups" :key="group.id" class="group-card">
              <header><div><span>{{ group.members.length }} 名成员</span><strong>{{ group.name }}</strong></div><button class="primary-button mini" type="button" @click="activeDocument = group">打开协作文档</button></header>
              <p>{{ groupMembersText(group) }}</p>
              <div class="group-member-chips"><span v-for="member in group.members" :key="member.id" :class="{ leader: member.role === 'leader' }">{{ member.display_name || member.username }}{{ member.role === 'leader' ? ' · 组长' : '' }}</span></div>
              <div class="group-storage-line"><div><strong>{{ group.used_storage_mb }}MB</strong><span>/ {{ collaboration?.storage_quota_mb || 0 }}MB</span></div><i><em :style="groupStorageStyle(group, collaboration)"></em></i></div>
              <div class="group-file-list"><strong>共享文件 {{ group.file_count }}</strong><a v-for="file in group.files.slice(0, 4)" :key="file.id" :href="file.attachment_url" download>{{ file.attachment_name }} · {{ formatFileSize(file.file_size) }}</a><span v-if="!group.files.length">暂无上传文件</span></div>
            </article>
          </div>
          <p v-else class="empty">保存设置后系统会按当前班级学生生成默认分组。</p>
        </section>
      </div>
      <footer class="modal-actions"><span>学生只看到小组、角色和任务，不显示内部判断依据。</span><button class="primary-button" type="button" @click="emit('close')">完成</button></footer>
    </section>
  </div>

  <div v-if="activeDocument" class="modal-backdrop group-document-backdrop" role="presentation" @click.self="activeDocument = null">
    <section class="entity-modal group-document-modal" role="dialog" aria-modal="true" aria-labelledby="group-document-title">
      <header class="modal-header"><div><h2 id="group-document-title">{{ activeDocument.name }}协作文档</h2><p>{{ activeDocument.document.attachment_name }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="activeDocument = null">×</button></header>
      <div class="group-document-editor"><OnlyOfficeEditor :group-id="activeDocument.id" mode="edit" /></div>
    </section>
  </div>
</template>
