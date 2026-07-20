<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import {
  acknowledgeChatModerationFeedback,
  getChatContext,
  getChatMessages,
  getTeacherChatModeration,
  markChatRead,
  moderateTeacherChatMessage,
  sendChatMessage,
  updateTeacherChatSettings,
  type ChatContext,
  type ChatMessage,
  type ChatModerationFeedback,
  type ChatReviewAction,
  type ChatRole,
  type ChatRoomType,
  type ChatSettingsPayload
} from '@/api/chat'

const props = defineProps<{
  sessionId: number
  role: ChatRole
  running: boolean
}>()

const emit = defineEmits<{
  classroomEvent: [payload: { type?: string; [key: string]: unknown }]
}>()

type ChatView = ChatRoomType | 'moderation'

const drawerOpen = ref(false)
const settingsOpen = ref(false)
const activeView = ref<ChatView>('whole_class')
const context = ref<ChatContext | null>(null)
const messages = ref<ChatMessage[]>([])
const moderationRows = ref<ChatMessage[]>([])
const selectedStudentId = ref<number | null>(null)
const selectedGroupId = ref<number | null>(null)
const draft = ref('')
const loading = ref(false)
const sending = ref(false)
const settingsSaving = ref(false)
const notice = ref('')
const noticeTone = ref<'info' | 'success' | 'warning' | 'danger'>('info')
const settingsDraft = ref<ChatSettingsPayload>({
  whole_class_enabled: false,
  teacher_private_enabled: false,
  group_chat_enabled: false
})
const messageList = ref<HTMLElement | null>(null)
const socketState = ref<'connecting' | 'online' | 'offline'>('connecting')
const reviewMessage = ref<ChatMessage | null>(null)
const reviewAction = ref<Exclude<ChatReviewAction, 'none'>>('allow')
const reviewPoints = ref(1)
const reviewNote = ref('')
const moderationFilter = ref<'pending' | 'reviewed'>('pending')
const activeModerationFeedback = ref<ChatModerationFeedback | null>(null)
const feedbackAcknowledging = ref(false)

let socket: WebSocket | null = null
let reconnectHandle: number | null = null
let pollingHandle: number | null = null
let refreshDebounceHandle: number | null = null
let disposed = false
const markedRead = new Map<number, number>()

const isTeacher = computed(() => props.role === 'teacher')
const studentOptions = computed(() => context.value?.students || [])
const groupOptions = computed(() => context.value?.groups || [])
const enabled = computed(() => context.value?.enabled || {
  whole_class: false,
  teacher_private: false,
  group: false
})
const studentHasChat = computed(() => Object.values(enabled.value).some(Boolean))
const showLauncher = computed(() => props.running && (isTeacher.value || studentHasChat.value))
const activeRoom = computed<ChatRoomType | null>(() => activeView.value === 'moderation' ? null : activeView.value)
const activeTargetId = computed(() => {
  if (activeView.value === 'teacher_private') {
    return isTeacher.value ? selectedStudentId.value : null
  }
  if (activeView.value === 'group') {
    return isTeacher.value ? selectedGroupId.value : context.value?.my_group?.id || null
  }
  return null
})
const currentRoomEnabled = computed(() => activeRoom.value ? Boolean(enabled.value[activeRoom.value]) : false)
const canCompose = computed(() => {
  if (!props.running || !activeRoom.value || !currentRoomEnabled.value) return false
  if (activeRoom.value === 'teacher_private' && isTeacher.value) return Boolean(selectedStudentId.value)
  if (activeRoom.value === 'group') return Boolean(activeTargetId.value)
  return true
})
const totalUnread = computed(() => {
  const messageUnread = (context.value?.threads || []).reduce((sum, thread) => sum + thread.unread_count, 0)
  return messageUnread + (isTeacher.value ? Number(context.value?.pending_moderation_count || 0) : 0)
})
const conversationTitle = computed(() => {
  if (activeView.value === 'whole_class') return '全班聊天'
  if (activeView.value === 'moderation') return '言论审核'
  if (activeView.value === 'teacher_private') {
    if (!isTeacher.value) return `与${context.value?.teacher.display_name || '老师'}聊天`
    return studentOptions.value.find((item) => item.id === selectedStudentId.value)?.display_name || '选择学生'
  }
  if (!isTeacher.value) return context.value?.my_group?.name || '我的小组'
  return groupOptions.value.find((item) => item.id === selectedGroupId.value)?.name || '选择小组'
})
const connectionLabel = computed(() => ({
  connecting: '连接中',
  online: '实时连接',
  offline: '轮询同步'
})[socketState.value])
const moderationFeedbackText = computed(() => {
  const feedback = activeModerationFeedback.value
  if (!feedback) return ''
  if (feedback.action === 'deduct') return `教师已撤回你的一条消息，并确认扣除 ${feedback.deduction_points} 分。`
  if (feedback.action === 'warn') return '教师已警告并撤回你的一条消息。'
  return '教师已撤回你的一条消息。'
})

function targetIdOf(message: ChatMessage) {
  return message.target && 'id' in message.target ? Number(message.target.id) : null
}

function roomUnread(roomType: ChatRoomType) {
  return (context.value?.threads || [])
    .filter((thread) => thread.room_type === roomType)
    .reduce((sum, thread) => sum + thread.unread_count, 0)
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function setNotice(message: string, tone: typeof noticeTone.value = 'info') {
  notice.value = message
  noticeTone.value = tone
}

function syncSettingsDraft(data: ChatContext) {
  settingsDraft.value = { ...data.settings }
}

function chooseStudentAndGroup() {
  if (!selectedStudentId.value || !studentOptions.value.some((item) => item.id === selectedStudentId.value)) {
    selectedStudentId.value = studentOptions.value[0]?.id || null
  }
  if (!selectedGroupId.value || !groupOptions.value.some((item) => item.id === selectedGroupId.value)) {
    selectedGroupId.value = groupOptions.value[0]?.id || null
  }
}

function chooseStudentDefaultRoom() {
  if (isTeacher.value || activeView.value === 'moderation' || enabled.value[activeView.value]) return
  const first = (['whole_class', 'teacher_private', 'group'] as ChatRoomType[]).find((room) => enabled.value[room])
  if (first) activeView.value = first
}

function syncModerationFeedback(data: ChatContext) {
  if (isTeacher.value || activeModerationFeedback.value) return
  activeModerationFeedback.value = data.moderation_feedbacks?.[0] || null
}

async function loadContext(silent = false) {
  if (!props.sessionId || !props.running) return
  try {
    const data = await getChatContext(props.role, props.sessionId)
    context.value = data
    syncSettingsDraft(data)
    chooseStudentAndGroup()
    chooseStudentDefaultRoom()
    syncModerationFeedback(data)
  } catch (error) {
    if (!silent) setNotice(error instanceof ApiError ? error.message : '聊天信息加载失败。', 'danger')
  }
}

async function markCurrentRead() {
  const last = messages.value[messages.value.length - 1]
  if (!last || !activeRoom.value || markedRead.get(last.thread_id) === last.id) return
  markedRead.set(last.thread_id, last.id)
  try {
    await markChatRead(props.role, props.sessionId, {
      room_type: activeRoom.value,
      target_id: activeTargetId.value,
      message_id: last.id
    })
  } catch {
    markedRead.delete(last.thread_id)
  }
}

async function scrollToLatest() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

async function loadMessages(silent = false) {
  if (!activeRoom.value || !props.running) return
  if ((activeRoom.value === 'teacher_private' && isTeacher.value && !selectedStudentId.value)
    || (activeRoom.value === 'group' && !activeTargetId.value)) {
    messages.value = []
    return
  }
  if (!silent) loading.value = true
  try {
    const previousById = new Map(messages.value.map((message) => [message.id, message]))
    const data = await getChatMessages(props.role, props.sessionId, activeRoom.value, activeTargetId.value)
    messages.value = data.messages
    if (!isTeacher.value) {
      const newlyAllowed = data.messages.find((message) => {
        const previous = previousById.get(message.id)
        return message.is_mine
          && previous?.moderation_status === 'pending'
          && message.moderation_status === 'visible'
          && message.review_action === 'allow'
      })
      if (newlyAllowed) {
        setNotice('教师已审核并放行你的消息。', 'success')
      }
    }
    await markCurrentRead()
    if (!silent) await scrollToLatest()
  } catch (error) {
    if (!silent) setNotice(error instanceof ApiError ? error.message : '聊天记录加载失败。', 'danger')
  } finally {
    loading.value = false
  }
}

async function loadModeration(silent = false) {
  if (!isTeacher.value) return
  if (!silent) loading.value = true
  try {
    const data = await getTeacherChatModeration(props.sessionId, moderationFilter.value)
    moderationRows.value = data.results
  } catch (error) {
    if (!silent) setNotice(error instanceof ApiError ? error.message : '审核队列加载失败。', 'danger')
  } finally {
    loading.value = false
  }
}

async function refreshActive(silent = true) {
  await loadContext(silent)
  if (!drawerOpen.value) return
  if (activeView.value === 'moderation') await loadModeration(silent)
  else await loadMessages(silent)
}

function scheduleRefresh() {
  if (refreshDebounceHandle !== null) window.clearTimeout(refreshDebounceHandle)
  refreshDebounceHandle = window.setTimeout(() => {
    refreshActive(true)
  }, 120)
}

function connectSocket() {
  if (disposed || !props.running || !props.sessionId) return
  if (socket) socket.close()
  socketState.value = 'connecting'
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  socket = new WebSocket(`${protocol}//${window.location.host}/ws/classrooms/${props.sessionId}/chat/`)
  socket.onopen = () => {
    socketState.value = 'online'
  }
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as { type?: string; [key: string]: unknown }
      if (payload.type?.startsWith('chat.')) scheduleRefresh()
      else emit('classroomEvent', payload)
    } catch {
      // Ignore malformed realtime frames; REST polling remains available.
    }
  }
  socket.onerror = () => {
    socketState.value = 'offline'
  }
  socket.onclose = () => {
    socket = null
    socketState.value = 'offline'
    if (!disposed && props.running) {
      reconnectHandle = window.setTimeout(connectSocket, 3000)
    }
  }
}

async function openDrawer() {
  drawerOpen.value = true
  notice.value = ''
  await refreshActive(false)
}

function closeDrawer() {
  drawerOpen.value = false
  settingsOpen.value = false
}

async function selectView(view: ChatView) {
  activeView.value = view
  draft.value = ''
  notice.value = ''
  if (view === 'moderation') await loadModeration()
  else await loadMessages()
}

async function sendMessage() {
  const content = draft.value.trim()
  if (!content || !activeRoom.value || !canCompose.value || sending.value) return
  sending.value = true
  try {
    const message = await sendChatMessage(props.role, props.sessionId, {
      room_type: activeRoom.value,
      target_id: activeTargetId.value,
      content
    })
    draft.value = ''
    if (message.moderation_status === 'pending') {
      setNotice('消息包含需要确认的表达，已提交教师审核。', 'warning')
    }
    await refreshActive(false)
  } catch (error) {
    setNotice(error instanceof ApiError ? error.message : '消息发送失败。', 'danger')
  } finally {
    sending.value = false
  }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  sendMessage()
}

async function saveSettings() {
  if (!isTeacher.value || settingsSaving.value) return
  settingsSaving.value = true
  try {
    const data = await updateTeacherChatSettings(props.sessionId, settingsDraft.value)
    context.value = data
    syncSettingsDraft(data)
    settingsOpen.value = false
    setNotice('聊天权限已更新。', 'success')
    chooseStudentAndGroup()
    await loadMessages(true)
  } catch (error) {
    setNotice(error instanceof ApiError ? error.message : '聊天权限保存失败。', 'danger')
  } finally {
    settingsSaving.value = false
  }
}

function defaultPoints(message: ChatMessage) {
  if (message.severity === 'severe') return 5
  if (message.severity === 'moderate') return 3
  return 1
}

function openReview(message: ChatMessage, action: Exclude<ChatReviewAction, 'none'> = 'allow') {
  reviewMessage.value = message
  reviewAction.value = action
  reviewPoints.value = defaultPoints(message)
  reviewNote.value = ''
}

function closeReview() {
  reviewMessage.value = null
  reviewNote.value = ''
}

async function submitReview() {
  const message = reviewMessage.value
  if (!message || settingsSaving.value) return
  settingsSaving.value = true
  try {
    await moderateTeacherChatMessage(props.sessionId, message.id, {
      action: reviewAction.value,
      points: reviewAction.value === 'deduct' ? Number(reviewPoints.value) : undefined,
      note: reviewNote.value.trim()
    })
    closeReview()
    setNotice('言论处理结果已记录。', 'success')
    await refreshActive(false)
  } catch (error) {
    setNotice(error instanceof ApiError ? error.message : '言论处理失败。', 'danger')
  } finally {
    settingsSaving.value = false
  }
}

async function acknowledgeModerationFeedback() {
  const feedback = activeModerationFeedback.value
  if (!feedback || feedbackAcknowledging.value) return
  feedbackAcknowledging.value = true
  try {
    await acknowledgeChatModerationFeedback(props.sessionId, feedback.id)
    if (context.value?.moderation_feedbacks) {
      context.value.moderation_feedbacks = context.value.moderation_feedbacks.filter((item) => item.id !== feedback.id)
    }
    activeModerationFeedback.value = null
    syncModerationFeedback(context.value as ChatContext)
  } catch (error) {
    setNotice(error instanceof ApiError ? error.message : '处理反馈确认失败。', 'danger')
  } finally {
    feedbackAcknowledging.value = false
  }
}

watch([selectedStudentId, selectedGroupId], () => {
  if (drawerOpen.value && activeView.value !== 'moderation') loadMessages()
})

watch(() => props.running, (running) => {
  if (running) {
    loadContext()
    connectSocket()
  } else {
    drawerOpen.value = false
    socket?.close()
  }
})

onMounted(async () => {
  await loadContext()
  connectSocket()
  pollingHandle = window.setInterval(() => refreshActive(true), 5000)
})

onBeforeUnmount(() => {
  disposed = true
  socket?.close()
  if (reconnectHandle !== null) window.clearTimeout(reconnectHandle)
  if (pollingHandle !== null) window.clearInterval(pollingHandle)
  if (refreshDebounceHandle !== null) window.clearTimeout(refreshDebounceHandle)
})
</script>

<template>
  <button
    v-if="showLauncher"
    class="classroom-chat-launcher"
    type="button"
    :aria-expanded="drawerOpen"
    aria-controls="classroom-chat-drawer"
    @click="openDrawer"
  >
    <span class="chat-launcher-mark" aria-hidden="true"></span>
    <span>课堂聊天</span>
    <strong v-if="totalUnread">{{ totalUnread > 99 ? '99+' : totalUnread }}</strong>
  </button>

  <section
    v-if="activeModerationFeedback"
    class="chat-student-feedback"
    :class="activeModerationFeedback.action"
    role="alertdialog"
    aria-modal="false"
    aria-labelledby="chat-feedback-title"
  >
    <header>
      <div><span>课堂聊天提醒</span><strong id="chat-feedback-title">{{ activeModerationFeedback.action_label }}</strong></div>
    </header>
    <p>{{ moderationFeedbackText }}</p>
    <small v-if="activeModerationFeedback.note">教师说明：{{ activeModerationFeedback.note }}</small>
    <footer>
      <button type="button" :disabled="feedbackAcknowledging" @click="acknowledgeModerationFeedback">
        {{ feedbackAcknowledging ? '确认中...' : '知道了' }}
      </button>
    </footer>
  </section>

  <div v-if="drawerOpen" class="classroom-chat-scrim" role="presentation" @click="closeDrawer"></div>
  <aside
    id="classroom-chat-drawer"
    class="classroom-chat-drawer"
    :class="{ open: drawerOpen }"
    :aria-hidden="!drawerOpen"
  >
    <header class="chat-drawer-header">
      <div>
        <span>课堂实名交流</span>
        <strong>{{ conversationTitle }}</strong>
      </div>
      <div class="chat-header-actions">
        <span class="chat-connection" :class="socketState"><i></i>{{ connectionLabel }}</span>
        <button v-if="isTeacher" type="button" aria-label="聊天设置" title="聊天设置" @click="settingsOpen = !settingsOpen">设置</button>
        <button type="button" aria-label="关闭聊天" title="关闭" @click="closeDrawer">×</button>
      </div>
    </header>

    <section v-if="settingsOpen && isTeacher" class="chat-settings-panel">
      <header><strong>聊天权限</strong><span>每节课堂默认关闭</span></header>
      <label>
        <input v-model="settingsDraft.whole_class_enabled" type="checkbox" />
        <span><strong>全班聊天</strong><small>开启后全班师生均可发言</small></span>
      </label>
      <label>
        <input v-model="settingsDraft.teacher_private_enabled" type="checkbox" />
        <span><strong>与老师聊天</strong><small>学生只能与教师一对一交流</small></span>
      </label>
      <label :class="{ disabled: !context?.group_chat_available }">
        <input v-model="settingsDraft.group_chat_enabled" type="checkbox" :disabled="!context?.group_chat_available" />
        <span><strong>小组聊天</strong><small>{{ context?.group_chat_available ? '按当前课堂分组交流' : '请先开启课堂分组' }}</small></span>
      </label>
      <div class="chat-settings-actions">
        <button type="button" @click="settingsOpen = false">取消</button>
        <button class="primary" type="button" :disabled="settingsSaving" @click="saveSettings">{{ settingsSaving ? '保存中...' : '保存权限' }}</button>
      </div>
    </section>

    <nav class="chat-room-tabs" aria-label="聊天范围">
      <button
        v-if="isTeacher || enabled.whole_class"
        type="button"
        :class="{ active: activeView === 'whole_class' }"
        @click="selectView('whole_class')"
      >
        全班<small v-if="roomUnread('whole_class')">{{ roomUnread('whole_class') }}</small>
      </button>
      <button
        v-if="isTeacher || enabled.teacher_private"
        type="button"
        :class="{ active: activeView === 'teacher_private' }"
        @click="selectView('teacher_private')"
      >
        {{ isTeacher ? '私聊' : '老师' }}<small v-if="roomUnread('teacher_private')">{{ roomUnread('teacher_private') }}</small>
      </button>
      <button
        v-if="isTeacher || enabled.group"
        type="button"
        :class="{ active: activeView === 'group' }"
        @click="selectView('group')"
      >
        小组<small v-if="roomUnread('group')">{{ roomUnread('group') }}</small>
      </button>
      <button
        v-if="isTeacher"
        type="button"
        :class="{ active: activeView === 'moderation' }"
        @click="selectView('moderation')"
      >
        审核<small v-if="context?.pending_moderation_count">{{ context.pending_moderation_count }}</small>
      </button>
    </nav>

    <div v-if="notice" class="chat-inline-notice" :class="noticeTone" role="status">
      <span>{{ notice }}</span><button type="button" aria-label="关闭提示" @click="notice = ''">×</button>
    </div>

    <section v-if="activeView === 'teacher_private' && isTeacher" class="chat-target-selector">
      <label for="chat-student-select">私聊学生</label>
      <select id="chat-student-select" v-model.number="selectedStudentId">
        <option v-for="student in studentOptions" :key="student.id" :value="student.id">
          {{ student.display_name }}{{ student.student_no ? ` · ${student.student_no}` : '' }}
        </option>
      </select>
    </section>
    <section v-if="activeView === 'group' && isTeacher" class="chat-target-selector">
      <label for="chat-group-select">进入小组</label>
      <select id="chat-group-select" v-model.number="selectedGroupId">
        <option v-for="group in groupOptions" :key="group.id" :value="group.id">{{ group.name }} · {{ group.members.length }} 人</option>
      </select>
    </section>

    <template v-if="activeView !== 'moderation'">
      <div ref="messageList" class="chat-message-list" aria-live="polite">
        <p v-if="loading" class="chat-empty">正在加载聊天记录...</p>
        <p v-else-if="!messages.length" class="chat-empty">
          {{ currentRoomEnabled ? '暂无消息' : '该聊天方式尚未开启' }}
        </p>
        <article
          v-for="message in messages"
          :key="message.id"
          class="chat-message-row"
          :class="{ mine: message.is_mine, pending: message.moderation_status === 'pending', removed: message.moderation_status === 'removed' }"
        >
          <span class="chat-avatar" :style="{ backgroundColor: message.sender.avatar.color }">{{ message.sender.avatar.initial }}</span>
          <div class="chat-message-content">
            <header>
              <strong>{{ message.sender.display_name }}</strong>
              <small v-if="message.sender.role === 'teacher'">教师</small>
              <time>{{ formatTime(message.created_at) }}</time>
            </header>
            <p>{{ message.content }}</p>
            <footer v-if="message.moderation_status !== 'visible' || message.review_action !== 'none'">
              <span>{{ message.moderation_status_label }}</span>
              <span v-if="message.review_action === 'deduct'">扣除 {{ message.deduction_points }} 分</span>
              <span v-else-if="message.review_action !== 'none'">{{ message.review_action_label }}</span>
              <span v-if="message.review_note">{{ message.review_note }}</span>
            </footer>
            <button
              v-if="isTeacher && message.sender.role === 'student' && message.review_action === 'none'"
              class="chat-review-link"
              type="button"
              @click="openReview(message, message.moderation_status === 'pending' ? 'allow' : 'remove')"
            >
              {{ message.moderation_status === 'pending' ? '审核消息' : '处理消息' }}
            </button>
          </div>
        </article>
      </div>

      <footer class="chat-composer">
        <div v-if="!currentRoomEnabled" class="chat-compose-disabled">教师尚未开启{{ conversationTitle }}</div>
        <div v-else-if="!canCompose" class="chat-compose-disabled">当前没有可用聊天对象</div>
        <template v-else>
          <textarea
            v-model="draft"
            rows="2"
            maxlength="500"
            :placeholder="`发送到${conversationTitle}`"
            aria-label="聊天内容"
            @keydown="handleComposerKeydown"
          ></textarea>
          <div><small>{{ draft.length }}/500 · Enter 发送，Shift+Enter 换行</small><button type="button" :disabled="sending || !draft.trim()" @click="sendMessage">{{ sending ? '发送中...' : '发送' }}</button></div>
        </template>
      </footer>
    </template>

    <section v-else class="chat-moderation-view">
      <div class="chat-moderation-filter">
        <button type="button" :class="{ active: moderationFilter === 'pending' }" @click="moderationFilter = 'pending'; loadModeration()">待审核</button>
        <button type="button" :class="{ active: moderationFilter === 'reviewed' }" @click="moderationFilter = 'reviewed'; loadModeration()">已处理</button>
      </div>
      <div class="chat-moderation-list">
        <p v-if="loading" class="chat-empty">正在加载审核记录...</p>
        <p v-else-if="!moderationRows.length" class="chat-empty">当前没有{{ moderationFilter === 'pending' ? '待审核' : '已处理' }}言论</p>
        <article v-for="message in moderationRows" :key="message.id" class="chat-moderation-card">
          <header>
            <span class="chat-avatar" :style="{ backgroundColor: message.sender.avatar.color }">{{ message.sender.avatar.initial }}</span>
            <div><strong>{{ message.sender.display_name }}</strong><small>{{ message.severity_label }} · {{ formatDateTime(message.created_at) }}</small></div>
            <b :class="message.severity">{{ message.severity_label }}</b>
          </header>
          <p>{{ message.content }}</p>
          <div v-if="message.matched_rules?.length" class="chat-rule-tags"><span v-for="rule in message.matched_rules" :key="rule">{{ rule }}</span></div>
          <footer>
            <span v-if="message.review_action !== 'none'">{{ message.review_action_label }}{{ message.deduction_points ? ` · ${message.deduction_points} 分` : '' }}</span>
            <button v-else type="button" @click="openReview(message)">处理</button>
          </footer>
        </article>
      </div>
    </section>
  </aside>

  <div v-if="reviewMessage" class="chat-review-backdrop" role="presentation" @click.self="closeReview">
    <section class="chat-review-dialog" role="dialog" aria-modal="true" aria-labelledby="chat-review-title">
      <header><div><span>实名言论审核</span><strong id="chat-review-title">{{ reviewMessage.sender.display_name }}</strong></div><button type="button" aria-label="关闭" @click="closeReview">×</button></header>
      <blockquote>{{ reviewMessage.content }}</blockquote>
      <div v-if="reviewMessage.matched_rules?.length" class="chat-rule-tags"><span v-for="rule in reviewMessage.matched_rules" :key="rule">{{ rule }}</span></div>
      <fieldset>
        <legend>处理方式</legend>
        <label><input v-model="reviewAction" type="radio" value="allow" />放行</label>
        <label><input v-model="reviewAction" type="radio" value="warn" />警告</label>
        <label><input v-model="reviewAction" type="radio" value="remove" />撤回</label>
        <label><input v-model="reviewAction" type="radio" value="deduct" />扣分</label>
      </fieldset>
      <label v-if="reviewAction === 'deduct'" class="chat-review-field"><span>扣分分值</span><input v-model.number="reviewPoints" type="number" min="0.5" max="100" step="0.5" /></label>
      <label class="chat-review-field"><span>处理说明</span><textarea v-model="reviewNote" rows="3" maxlength="255" placeholder="可选，学生能够看到该说明"></textarea></label>
      <footer><button type="button" @click="closeReview">取消</button><button class="primary" type="button" :disabled="settingsSaving" @click="submitReview">{{ settingsSaving ? '处理中...' : '确认处理' }}</button></footer>
    </section>
  </div>
</template>

<style scoped>
.classroom-chat-launcher{position:fixed;right:22px;bottom:22px;z-index:80;display:flex;align-items:center;gap:9px;min-height:44px;padding:0 14px;border:1px solid #155eef;border-radius:6px;background:#155eef;color:#fff;font:600 14px/1 inherit;box-shadow:0 10px 26px rgba(15,45,90,.2);cursor:pointer}.classroom-chat-launcher:hover{background:#1049bd}.classroom-chat-launcher:focus-visible,.classroom-chat-drawer button:focus-visible,.classroom-chat-drawer select:focus-visible,.classroom-chat-drawer textarea:focus-visible,.chat-review-dialog button:focus-visible,.chat-review-dialog input:focus-visible,.chat-review-dialog textarea:focus-visible{outline:3px solid rgba(37,99,235,.25);outline-offset:2px}.classroom-chat-launcher strong{display:grid;place-items:center;min-width:21px;height:21px;padding:0 5px;border-radius:11px;background:#fff;color:#b42318;font-size:11px}.chat-launcher-mark{position:relative;width:18px;height:14px;border:2px solid currentColor;border-radius:4px}.chat-launcher-mark:after{content:"";position:absolute;left:2px;bottom:-5px;width:6px;height:6px;border-left:2px solid currentColor;transform:skewY(-35deg)}
.chat-student-feedback{position:fixed;top:18px;right:18px;z-index:108;width:min(360px,calc(100vw - 36px));padding:16px;border:1px solid #f0b84b;border-left:4px solid #d97706;border-radius:6px;background:#fff;box-shadow:0 16px 42px rgba(15,23,42,.22)}.chat-student-feedback.deduct{border-color:#f1a6a0;border-left-color:#d92d20}.chat-student-feedback.remove{border-color:#a8c7fa;border-left-color:#2563eb}.chat-student-feedback header div{display:grid;gap:2px}.chat-student-feedback header span{color:#667085;font-size:12px}.chat-student-feedback header strong{color:#172b4d;font-size:17px}.chat-student-feedback p{margin:12px 0 6px;color:#1d2939;font-size:14px;line-height:1.6}.chat-student-feedback>small{display:block;color:#667085;font-size:12px;line-height:1.5}.chat-student-feedback footer{display:flex;justify-content:flex-end;margin-top:14px}.chat-student-feedback button{min-width:82px;height:38px;border:1px solid #155eef;border-radius:5px;background:#155eef;color:#fff;font-weight:600;cursor:pointer}.chat-student-feedback button:disabled{opacity:.5;cursor:not-allowed}
.classroom-chat-scrim{position:fixed;inset:0;z-index:88;background:rgba(15,23,42,.34)}.classroom-chat-drawer{position:fixed;top:0;right:0;bottom:0;z-index:90;display:grid;grid-template-rows:auto auto auto auto minmax(0,1fr);width:min(430px,100vw);background:#f7f9fc;border-left:1px solid #d9e1ec;box-shadow:-16px 0 40px rgba(15,23,42,.16);transform:translateX(102%);transition:transform .2s ease;pointer-events:none}.classroom-chat-drawer.open{transform:translateX(0);pointer-events:auto}.chat-drawer-header{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:68px;padding:12px 16px;background:#fff;border-bottom:1px solid #e3e8ef}.chat-drawer-header>div:first-child{display:grid;gap:3px;min-width:0}.chat-drawer-header span{font-size:12px;color:#667085}.chat-drawer-header strong{overflow:hidden;color:#172b4d;font-size:17px;text-overflow:ellipsis;white-space:nowrap}.chat-header-actions{display:flex;align-items:center;gap:6px}.chat-header-actions button{min-width:36px;height:36px;padding:0 9px;border:1px solid #d6deea;border-radius:5px;background:#fff;color:#344054;cursor:pointer}.chat-header-actions button:last-child{font-size:22px}.chat-connection{display:flex;align-items:center;gap:5px;white-space:nowrap}.chat-connection i{width:7px;height:7px;border-radius:50%;background:#f59e0b}.chat-connection.online i{background:#16a34a}.chat-connection.offline i{background:#94a3b8}
.chat-settings-panel{display:grid;gap:8px;padding:12px 16px;background:#fff;border-bottom:1px solid #dbe3ee}.chat-settings-panel>header{display:flex;justify-content:space-between;align-items:center}.chat-settings-panel>header strong{font-size:14px;color:#1d2939}.chat-settings-panel>header span{font-size:12px;color:#667085}.chat-settings-panel>label{display:flex;align-items:flex-start;gap:10px;padding:9px 10px;border:1px solid #e1e7ef;border-radius:5px;cursor:pointer}.chat-settings-panel>label.disabled{opacity:.55;cursor:not-allowed}.chat-settings-panel input[type=checkbox]{width:17px;height:17px;margin:2px 0 0;accent-color:#155eef}.chat-settings-panel label span{display:grid;gap:2px}.chat-settings-panel label strong{font-size:13px;color:#26364d}.chat-settings-panel label small{font-size:12px;color:#667085}.chat-settings-actions{display:flex;justify-content:flex-end;gap:8px}.chat-settings-actions button,.chat-review-dialog footer button{min-height:36px;padding:0 14px;border:1px solid #ccd5e1;border-radius:5px;background:#fff;color:#344054;cursor:pointer}.chat-settings-actions button.primary,.chat-review-dialog footer button.primary{border-color:#155eef;background:#155eef;color:#fff}
.chat-room-tabs{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;background:#fff;border-bottom:1px solid #e0e6ef}.chat-room-tabs button{position:relative;display:flex;align-items:center;justify-content:center;gap:5px;min-width:0;min-height:44px;border:0;border-bottom:2px solid transparent;background:transparent;color:#667085;font-weight:600;cursor:pointer}.chat-room-tabs button.active{border-bottom-color:#155eef;color:#155eef}.chat-room-tabs small{display:grid;place-items:center;min-width:18px;height:18px;padding:0 4px;border-radius:9px;background:#d92d20;color:#fff;font-size:10px}.chat-inline-notice{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:9px 12px;border-bottom:1px solid #f3d59d;background:#fffaeb;color:#8a4b08;font-size:12px}.chat-inline-notice.success{border-color:#b7e4c7;background:#ecfdf3;color:#067647}.chat-inline-notice.danger{border-color:#fecaca;background:#fef3f2;color:#b42318}.chat-inline-notice button{border:0;background:transparent;color:inherit;font-size:18px;cursor:pointer}.chat-target-selector{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:10px;padding:9px 12px;background:#f0f4f9;border-bottom:1px solid #dfe6ef}.chat-target-selector label{font-size:12px;font-weight:600;color:#475467}.chat-target-selector select{min-width:0;height:36px;padding:0 30px 0 10px;border:1px solid #cbd5e1;border-radius:5px;background:#fff;color:#1d2939}
.chat-message-list{min-height:0;overflow-y:auto;padding:16px 14px 20px;scroll-behavior:smooth}.chat-empty{display:grid;place-items:center;min-height:140px;margin:0;color:#98a2b3;font-size:13px;text-align:center}.chat-message-row{display:flex;align-items:flex-start;gap:9px;margin-bottom:16px}.chat-message-row.mine{flex-direction:row-reverse}.chat-avatar{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border-radius:50%;color:#fff;font-size:13px;font-weight:700}.chat-message-content{display:grid;justify-items:start;max-width:78%;min-width:0}.chat-message-row.mine .chat-message-content{justify-items:end}.chat-message-content header{display:flex;align-items:center;gap:6px;min-width:0;margin:0 3px 5px}.chat-message-content header strong{overflow:hidden;color:#344054;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.chat-message-content header small{padding:1px 5px;border-radius:3px;background:#e8f0ff;color:#155eef;font-size:10px}.chat-message-content header time{color:#98a2b3;font-size:10px}.chat-message-content>p{max-width:100%;margin:0;padding:9px 11px;border:1px solid #dfe6ef;border-radius:5px;background:#fff;color:#1f2937;font-size:14px;line-height:1.55;overflow-wrap:anywhere;white-space:pre-wrap}.chat-message-row.mine .chat-message-content>p{border-color:#b9d0ff;background:#eaf2ff}.chat-message-row.pending .chat-message-content>p{border-color:#f0c36a;background:#fffaeb}.chat-message-row.removed .chat-message-content>p{border-style:dashed;background:#f2f4f7;color:#667085}.chat-message-content>footer{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:5px;margin-top:5px;color:#b54708;font-size:10px}.chat-message-content>footer span{padding:2px 5px;border-radius:3px;background:#fff3d6}.chat-review-link{margin-top:5px;padding:3px 0;border:0;background:transparent;color:#155eef;font-size:11px;cursor:pointer}.chat-composer{padding:10px 12px calc(10px + env(safe-area-inset-bottom));background:#fff;border-top:1px solid #dbe3ee}.chat-composer textarea{display:block;width:100%;min-height:64px;max-height:130px;resize:vertical;padding:9px 10px;border:1px solid #cbd5e1;border-radius:5px;background:#fff;color:#1d2939;font:14px/1.5 inherit}.chat-composer>div:not(.chat-compose-disabled){display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:7px}.chat-composer small{color:#98a2b3;font-size:10px}.chat-composer button{min-width:68px;height:36px;border:1px solid #155eef;border-radius:5px;background:#155eef;color:#fff;font-weight:600;cursor:pointer}.chat-composer button:disabled{opacity:.45;cursor:not-allowed}.chat-compose-disabled{display:grid;place-items:center;min-height:48px;color:#667085;font-size:13px}
.chat-moderation-view{min-height:0;overflow:hidden;display:grid;grid-template-rows:auto minmax(0,1fr)}.chat-moderation-filter{display:flex;gap:6px;padding:9px 12px;border-bottom:1px solid #dfe6ef}.chat-moderation-filter button{min-height:34px;padding:0 12px;border:1px solid #d5dde8;border-radius:5px;background:#fff;color:#475467;cursor:pointer}.chat-moderation-filter button.active{border-color:#155eef;background:#edf4ff;color:#155eef}.chat-moderation-list{overflow-y:auto;padding:12px}.chat-moderation-card{margin-bottom:10px;padding:12px;border:1px solid #e1e6ee;border-left:3px solid #f59e0b;border-radius:5px;background:#fff}.chat-moderation-card>header{display:flex;align-items:center;gap:9px}.chat-moderation-card header div{display:grid;flex:1;gap:2px}.chat-moderation-card header strong{font-size:13px;color:#26364d}.chat-moderation-card header small{font-size:10px;color:#98a2b3}.chat-moderation-card header b{padding:3px 6px;border-radius:3px;background:#fff4e5;color:#b54708;font-size:10px}.chat-moderation-card header b.severe{background:#fef3f2;color:#b42318}.chat-moderation-card header b.mild{background:#f2f4f7;color:#475467}.chat-moderation-card>p{margin:10px 0;color:#1f2937;font-size:14px;line-height:1.5;overflow-wrap:anywhere}.chat-rule-tags{display:flex;flex-wrap:wrap;gap:5px}.chat-rule-tags span{padding:3px 6px;border:1px solid #f2c7c3;border-radius:3px;background:#fff7f6;color:#a83a31;font-size:10px}.chat-moderation-card>footer{display:flex;justify-content:flex-end;margin-top:10px}.chat-moderation-card>footer span{color:#667085;font-size:11px}.chat-moderation-card>footer button{min-height:32px;padding:0 12px;border:1px solid #155eef;border-radius:5px;background:#fff;color:#155eef;cursor:pointer}
.chat-review-backdrop{position:fixed;inset:0;z-index:110;display:grid;place-items:center;padding:20px;background:rgba(15,23,42,.5)}.chat-review-dialog{width:min(480px,100%);max-height:min(680px,calc(100dvh - 40px));overflow-y:auto;padding:18px;border-radius:6px;background:#fff;box-shadow:0 18px 60px rgba(15,23,42,.26)}.chat-review-dialog>header{display:flex;align-items:center;justify-content:space-between}.chat-review-dialog header div{display:grid;gap:3px}.chat-review-dialog header span{font-size:12px;color:#667085}.chat-review-dialog header strong{font-size:18px;color:#172b4d}.chat-review-dialog header button{width:36px;height:36px;border:1px solid #d6deea;border-radius:5px;background:#fff;color:#475467;font-size:22px;cursor:pointer}.chat-review-dialog blockquote{margin:16px 0 10px;padding:12px;border-left:3px solid #f59e0b;background:#fffaeb;color:#344054;font-size:14px;line-height:1.6;overflow-wrap:anywhere}.chat-review-dialog fieldset{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:16px 0;padding:0;border:0}.chat-review-dialog legend{margin-bottom:7px;color:#344054;font-size:12px;font-weight:600}.chat-review-dialog fieldset label{display:flex;align-items:center;justify-content:center;gap:5px;min-height:38px;border:1px solid #d7dee8;border-radius:5px;color:#344054;font-size:13px;cursor:pointer}.chat-review-dialog fieldset input{accent-color:#155eef}.chat-review-field{display:grid;gap:6px;margin-top:12px}.chat-review-field span{color:#344054;font-size:12px;font-weight:600}.chat-review-field input,.chat-review-field textarea{width:100%;min-height:40px;padding:8px 9px;border:1px solid #cbd5e1;border-radius:5px;background:#fff;color:#1d2939;font:14px/1.5 inherit}.chat-review-field textarea{resize:vertical}.chat-review-dialog>footer{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
.classroom-chat-drawer{display:flex;flex-direction:column}.chat-message-list{flex:1}.chat-composer{flex:0 0 auto}.chat-moderation-view{flex:1}.chat-composer small,.chat-message-content header time,.chat-moderation-card header small,.chat-rule-tags span{font-size:11px}
@media(max-width:600px){.classroom-chat-launcher{right:12px;bottom:12px}.chat-student-feedback{top:12px;right:12px;width:calc(100vw - 24px)}.classroom-chat-drawer{width:100vw}.classroom-chat-scrim{display:none}.chat-connection{display:none}.chat-message-content{max-width:82%}.chat-review-backdrop{padding:0}.chat-review-dialog{align-self:end;width:100%;max-height:88dvh;border-radius:6px 6px 0 0}.chat-review-dialog fieldset{grid-template-columns:repeat(2,1fr)}}
@media(prefers-reduced-motion:reduce){.classroom-chat-drawer{transition:none}.chat-message-list{scroll-behavior:auto}}
</style>
