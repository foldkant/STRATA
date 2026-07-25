import {
  IconBooks,
  IconClipboardCheck,
  IconHome2,
  IconLibrary,
  IconUserCircle
} from '@tabler/icons-vue'

export const studentNavItems = [
  { label: '首页', path: '/student', icon: IconHome2 },
  { label: '课程学习', path: '/student/courses', icon: IconBooks },
  { label: '测试任务', path: '/student/assessments', icon: IconClipboardCheck },
  { label: '学习资源', path: '/student/resources', icon: IconLibrary },
  { label: '学习档案', path: '/student/profile', icon: IconUserCircle }
]

export function studentNav(activePath: string) {
  return studentNavItems.map((item) => ({
    ...item,
    active: item.path === '/student' ? activePath === item.path : activePath === item.path || activePath.startsWith(`${item.path}/`)
  }))
}
