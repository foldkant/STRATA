export const studentNavItems = [
  { label: '首页', path: '/student' },
  { label: '课程', path: '/student/courses' },
  { label: '资源', path: '/student/resources' },
  { label: '测试', path: '/student/assessments' },
  { label: '档案', path: '/student/profile' },
  { label: '反馈', path: '/student/feedback' }
]

export function studentNav(activePath: string) {
  return studentNavItems.map((item) => ({
    ...item,
    active: item.path === '/student' ? activePath === item.path : activePath === item.path || activePath.startsWith(`${item.path}/`)
  }))
}
