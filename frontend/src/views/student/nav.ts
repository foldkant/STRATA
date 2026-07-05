export const studentNavItems = [
  { label: '首页', path: '/student' },
  { label: '课程', path: '/student/courses' },
  { label: '任务', path: '/student/tasks' },
  { label: '项目', path: '/student/projects' },
  { label: '档案', path: '/student/profile' },
  { label: '消息', path: '/student/notices' },
  { label: '反馈', path: '/student/feedback' }
]

export function studentNav(activePath: string) {
  return studentNavItems.map((item) => ({
    ...item,
    active: item.path === '/student' ? activePath === item.path : activePath === item.path || activePath.startsWith(`${item.path}/`)
  }))
}
