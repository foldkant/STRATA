<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  getTeacherAIProvider,
  saveTeacherAIProvider,
  testTeacherAIProvider,
  type TeacherAIProviderPayload,
  type TeacherAIProviderRow
} from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/ai')
const provider = ref<TeacherAIProviderRow | null>(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const notice = ref('')
const errors = ref<FieldErrors>({})

const form = reactive({
  provider: 'deepseek',
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-v4-flash',
  api_key: '',
  is_enabled: false
})

const statusRows = computed(() => [
  {
    label: '接入状态',
    value: provider.value?.is_enabled ? '已启用' : '未启用',
    tone: provider.value?.is_enabled ? 'ok' : 'warn'
  },
  {
    label: '密钥状态',
    value: provider.value?.has_api_key ? `已保存，尾号 ${provider.value.api_key_hint}` : '未保存',
    tone: provider.value?.has_api_key ? 'ok' : 'warn'
  },
  {
    label: '最近测试',
    value: provider.value?.last_tested_at ? new Date(provider.value.last_tested_at).toLocaleString() : '未测试',
    tone: provider.value?.last_error ? 'failed' : 'ok'
  }
])

function syncForm(row: TeacherAIProviderRow) {
  provider.value = row
  form.provider = row.provider
  form.base_url = row.base_url || 'https://api.deepseek.com'
  form.model = row.model || 'deepseek-v4-flash'
  form.api_key = ''
  form.is_enabled = row.is_enabled
}

function payload(extra: Partial<TeacherAIProviderPayload> = {}): TeacherAIProviderPayload {
  return {
    provider: form.provider,
    base_url: form.base_url.trim(),
    model: form.model.trim(),
    api_key: form.api_key.trim() || undefined,
    is_enabled: form.is_enabled,
    ...extra
  }
}

async function load() {
  loading.value = true
  try {
    syncForm(await getTeacherAIProvider())
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : 'AI 接入配置加载失败。'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  notice.value = ''
  errors.value = {}
  try {
    syncForm(await saveTeacherAIProvider(payload()))
    notice.value = 'AI 接入配置已保存。'
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else {
      notice.value = 'AI 接入配置保存失败。'
    }
  } finally {
    saving.value = false
  }
}

async function clearKey() {
  saving.value = true
  notice.value = ''
  errors.value = {}
  try {
    form.api_key = ''
    form.is_enabled = false
    syncForm(await saveTeacherAIProvider(payload({ clear_api_key: true, is_enabled: false })))
    notice.value = 'API Key 已清除，AI 接入已停用。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : 'API Key 清除失败。'
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  notice.value = ''
  errors.value = {}
  try {
    syncForm(await testTeacherAIProvider())
    notice.value = 'AI 接入测试通过。'
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
      await load()
    } else {
      notice.value = 'AI 接入测试失败。'
    }
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell title="AI接入" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section v-if="loading" class="panel">
      <p class="empty">正在加载</p>
    </section>

    <template v-else>
      <section class="ai-provider-hero">
        <article v-for="item in statusRows" :key="item.label" class="ai-provider-status" :class="item.tone">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </section>

      <section class="screen-grid ai-provider-layout">
        <form class="panel ai-provider-form" @submit.prevent="save">
          <div class="panel-heading">
            <h2>DeepSeek 接入</h2>
            <p>教师填写自己的 API Key。未配置或测试失败时，只影响 AI 辅助功能，平台其他功能可照常使用。</p>
          </div>

          <div class="ai-provider-fields">
            <label>
              <span>服务商</span>
              <select v-model="form.provider">
                <option value="deepseek">DeepSeek</option>
              </select>
              <small v-if="errors.provider" class="field-error">{{ errors.provider[0] }}</small>
            </label>

            <label>
              <span>接口地址</span>
              <input v-model.trim="form.base_url" autocomplete="off" placeholder="https://api.deepseek.com" />
              <small v-if="errors.base_url" class="field-error">{{ errors.base_url[0] }}</small>
            </label>

            <label>
              <span>模型</span>
              <input v-model.trim="form.model" autocomplete="off" placeholder="deepseek-v4-flash" />
              <small v-if="errors.model" class="field-error">{{ errors.model[0] }}</small>
            </label>

            <label>
              <span>API Key</span>
              <input
                v-model.trim="form.api_key"
                type="password"
                autocomplete="new-password"
                :placeholder="provider?.has_api_key ? `已保存，尾号 ${provider.api_key_hint}；不填则保持不变` : '粘贴教师自己的 API Key'"
              />
              <small v-if="errors.api_key" class="field-error">{{ errors.api_key[0] }}</small>
            </label>

            <label class="ai-enable-row">
              <input v-model="form.is_enabled" type="checkbox" />
              <span>启用教师 AI 辅助</span>
            </label>
          </div>

          <footer class="ai-provider-actions">
            <button class="secondary-button danger" type="button" :disabled="saving || testing || !provider?.has_api_key" @click="clearKey">
              清除 Key
            </button>
            <button class="secondary-button" type="button" :disabled="saving || testing || !provider?.has_api_key" @click="testConnection">
              {{ testing ? '测试中' : '测试连接' }}
            </button>
            <button class="primary-button" type="submit" :disabled="saving || testing">
              {{ saving ? '保存中' : '保存配置' }}
            </button>
          </footer>
        </form>

        <aside class="panel ai-provider-notes">
          <div class="panel-heading">
            <h2>使用边界</h2>
            <p>AI 接入先服务教师备课，不直接面向学生自动发布内容。</p>
          </div>
          <div class="ai-rule-list">
            <article>
              <strong>教师确认</strong>
              <span>生成的题目、任务单、网页学习单必须由教师确认后才能进入课时。</span>
            </article>
            <article>
              <strong>结构化生成</strong>
              <span>后续生成网页学习单时，只允许输出平台定义的 DSL，不允许任意脚本。</span>
            </article>
            <article>
              <strong>私有化优先</strong>
              <span>学校本地部署无外网时，AI 按不可用处理，课程、课堂、资源和评价仍可正常运行。</span>
            </article>
          </div>
          <p v-if="provider?.last_error" class="ai-provider-error" role="status">{{ provider.last_error }}</p>
        </aside>
      </section>
    </template>
  </AppShell>
</template>
