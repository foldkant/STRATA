import { apiRequest, queryString, toJsonBody } from './client'

export type ChatRole = 'teacher' | 'student'
export type ChatRoomType = 'whole_class' | 'teacher_private' | 'group'
export type ChatModerationStatus = 'visible' | 'pending' | 'removed'
export type ChatSeverity = 'none' | 'mild' | 'moderate' | 'severe'
export type ChatReviewAction = 'none' | 'allow' | 'warn' | 'remove' | 'deduct'

export type ChatUser = {
  id: number
  username: string
  display_name: string
  role: string
  role_label: string
  student_no?: string
  avatar: {
    initial: string
    color: string
  }
}

export type ChatGroup = {
  id: number
  name: string
  group_no: number
  members: ChatUser[]
}

export type ChatTarget = ChatUser | { id: number; name: string; group_no: number } | null

export type ChatMessage = {
  id: number
  thread_id: number
  room_type: ChatRoomType
  target: ChatTarget
  sender: ChatUser
  content: string
  is_mine: boolean
  moderation_status: ChatModerationStatus
  moderation_status_label: string
  severity: ChatSeverity
  severity_label: string
  moderation_categories?: string[]
  matched_rules?: string[]
  review_action: ChatReviewAction
  review_action_label: string
  review_note: string
  deduction_points: number
  reviewed_by?: ChatUser | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
}

export type ChatThread = {
  id: number
  room_type: ChatRoomType
  room_type_label: string
  target: ChatTarget
  unread_count: number
  last_message: ChatMessage | null
  updated_at: string
}

export type ChatContext = {
  session: {
    id: number
    title: string
    status: 'draft' | 'running' | 'finished'
    status_label: string
  }
  me: ChatUser
  teacher: ChatUser
  settings: {
    whole_class_enabled: boolean
    teacher_private_enabled: boolean
    group_chat_enabled: boolean
  }
  enabled: Record<ChatRoomType, boolean>
  group_chat_available: boolean
  threads: ChatThread[]
  pending_moderation_count: number
  students?: ChatUser[]
  groups?: ChatGroup[]
  my_group?: ChatGroup | null
  moderation_feedbacks?: ChatModerationFeedback[]
}

export type ChatMessagesPayload = {
  thread: ChatThread | null
  messages: ChatMessage[]
  has_more: boolean
}

export type ChatModerationPayload = {
  count: number
  results: ChatMessage[]
}

export type ChatSettingsPayload = ChatContext['settings']

export type ChatModerationFeedback = {
  id: number
  action: 'warn' | 'remove' | 'deduct'
  action_label: string
  severity: ChatSeverity
  severity_label: string
  deduction_points: number
  note: string
  reviewed_at: string
}

function basePath(role: ChatRole, sessionId: number) {
  return role === 'teacher'
    ? `/api/v1/teacher/classroom/sessions/${sessionId}/chat`
    : `/api/v1/student/classroom/${sessionId}/chat`
}

export function getChatContext(role: ChatRole, sessionId: number) {
  return apiRequest<ChatContext>(`${basePath(role, sessionId)}/`)
}

export function getChatMessages(role: ChatRole, sessionId: number, roomType: ChatRoomType, targetId?: number | null) {
  return apiRequest<ChatMessagesPayload>(
    `${basePath(role, sessionId)}/messages/${queryString({ room_type: roomType, target_id: targetId })}`
  )
}

export function sendChatMessage(
  role: ChatRole,
  sessionId: number,
  payload: { room_type: ChatRoomType; target_id?: number | null; content: string }
) {
  return apiRequest<ChatMessage>(`${basePath(role, sessionId)}/messages/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function markChatRead(
  role: ChatRole,
  sessionId: number,
  payload: { room_type: ChatRoomType; target_id?: number | null; message_id: number }
) {
  return apiRequest<{ thread_id: number | null; last_read_message_id: number | null }>(`${basePath(role, sessionId)}/read/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function acknowledgeChatModerationFeedback(sessionId: number, messageId: number) {
  return apiRequest<{ message_id: number; acknowledged: boolean }>(
    `/api/v1/student/classroom/${sessionId}/chat/moderation-feedback/${messageId}/ack/`,
    { method: 'POST' }
  )
}

export function updateTeacherChatSettings(sessionId: number, payload: ChatSettingsPayload) {
  return apiRequest<ChatContext>(`/api/v1/teacher/classroom/sessions/${sessionId}/chat/settings/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function getTeacherChatModeration(sessionId: number, status: 'pending' | 'reviewed' | 'all' = 'pending') {
  return apiRequest<ChatModerationPayload>(
    `/api/v1/teacher/classroom/sessions/${sessionId}/chat/moderation/${queryString({ status })}`
  )
}

export function moderateTeacherChatMessage(
  sessionId: number,
  messageId: number,
  payload: { action: Exclude<ChatReviewAction, 'none'>; points?: number; note?: string }
) {
  return apiRequest<ChatMessage>(`/api/v1/teacher/classroom/sessions/${sessionId}/chat/messages/${messageId}/moderate/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}
