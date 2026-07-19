<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import { getStudentResources, recordStudentResourceView } from '@/api/student'
import type { ResourceRow } from '@/api/teacher'
import StudentShell from '@/layouts/StudentShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import { studentNav } from './nav'

const navItems = studentNav('/student/resources')
const loading = ref(false)
const notice = ref('')
const query = ref('')
const scope = ref<'all' | 'school' | 'external' | 'projects'>('all')
const rows = ref<ResourceRow[]>([])
const previewRow = ref<ResourceRow | null>(null)
const viewedIds = new Set<number>()

const scopeTabs = [
  { value: 'all', label: '全部资源' },
  { value: 'school', label: '校内资源' },
  { value: 'external', label: '跨校资源' },
  { value: 'projects', label: '学生项目' }
] as const

function resourceInitial(item: ResourceRow) {
  return item.title.slice(0, 4)
}

function formatDate(value: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleDateString('zh-CN')
}

async function loadRows() {
  loading.value = true
  try {
    const result = await getStudentResources({ q: query.value, scope: scope.value, page_size: 60 })
    rows.value = result.results
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源加载失败。'
  } finally {
    loading.value = false
  }
}

async function openResource(item: ResourceRow) {
  previewRow.value = item
  if (viewedIds.has(item.id)) return
  viewedIds.add(item.id)
  try {
    const updated = await recordStudentResourceView(item.id)
    const index = rows.value.findIndex((row) => row.id === item.id)
    if (index >= 0) rows.value[index] = updated
    previewRow.value = updated
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源浏览记录提交失败。'
  }
}

watch(scope, loadRows)
onMounted(loadRows)
</script>

<template>
  <StudentShell title="资源中心" subtitle="课外拓展与优秀项目" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section class="student-resource-center-head">
      <div class="resource-scope-tabs student-resource-tabs">
        <button
          v-for="tab in scopeTabs"
          :key="tab.value"
          type="button"
          :class="{ active: scope === tab.value }"
          @click="scope = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>
      <div class="student-resource-search">
        <input v-model.trim="query" aria-label="搜索资源" placeholder="搜索资源、项目成员或标签" @keyup.enter="loadRows" />
        <button type="button" :disabled="loading" @click="loadRows">{{ loading ? '查询中' : '查询' }}</button>
      </div>
    </section>

    <section class="student-resource-center-grid">
      <article v-for="item in rows" :key="item.id" class="student-resource-card">
        <button class="student-resource-cover" type="button" @click="openResource(item)">
          <img v-if="item.cover_url" :src="item.cover_url" :alt="`${item.title}封面`" />
          <span v-else>{{ resourceInitial(item) }}</span>
          <small>{{ item.resource_type_label }}</small>
        </button>
        <div>
          <span class="student-resource-source">{{ item.school?.name || '本校' }} · {{ item.owner.display_name }}</span>
          <h2>{{ item.title }}</h2>
          <p>{{ item.content || item.external_url || item.attachment_name || '暂无资源说明。' }}</p>
          <div class="resource-card-tags">
            <span>{{ item.category_label }}</span>
            <span v-if="item.subject">{{ item.subject.name }}</span>
            <span v-for="tag in item.tags.slice(0, 2)" :key="tag">{{ tag }}</span>
          </div>
          <p v-if="item.resource_type === 'student_project'" class="student-project-members">
            {{ item.project_type_label }} · {{ item.project_members.join('、') }}
          </p>
          <footer>
            <span>{{ formatDate(item.published_at || item.updated_at) }} · {{ item.view_count }} 次浏览</span>
            <button type="button" @click="openResource(item)">查看资源</button>
          </footer>
        </div>
      </article>
      <p v-if="!loading && !rows.length" class="empty">当前没有可查看的资源。</p>
    </section>

    <div v-if="previewRow" class="modal-backdrop" role="presentation" @click.self="previewRow = null">
      <section class="entity-modal student-resource-detail-modal" role="dialog" aria-modal="true" aria-labelledby="student-resource-title">
        <header class="modal-header">
          <div>
            <h2 id="student-resource-title">{{ previewRow.title }}</h2>
            <p>{{ previewRow.school?.name }} · {{ previewRow.owner.display_name }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="previewRow = null">×</button>
        </header>
        <div class="resource-detail-body student-resource-detail-body">
          <ResourcePreview :resource="previewRow" office-mode="view" />
          <aside>
            <h3>资源说明</h3>
            <p>{{ previewRow.content || '暂无补充说明。' }}</p>
            <p v-if="previewRow.resource_type === 'student_project'">
              <strong>项目成员：</strong>{{ previewRow.project_members.join('、') }}
            </p>
            <p v-if="previewRow.competition_name">
              {{ previewRow.competition_name }} {{ previewRow.competition_year || '' }} {{ previewRow.award_level }}
            </p>
            <section v-if="previewRow.extra_files.length">
              <strong>{{ previewRow.resource_type === 'student_project' ? '项目过程材料' : '补充附件' }}</strong>
              <a v-for="file in previewRow.extra_files" :key="file.id" :href="file.file_url" download>{{ file.name }}</a>
            </section>
          </aside>
        </div>
      </section>
    </div>
  </StudentShell>
</template>
