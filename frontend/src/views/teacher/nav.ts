import {
  IconAdjustmentsHorizontal,
  IconBooks,
  IconChecklist,
  IconClipboardCheck,
  IconFiles,
  IconLayoutDashboard,
  IconLibrary,
  IconListDetails,
  IconMessage,
  IconPresentation,
  IconRobot,
  IconSpeakerphone,
  IconUsers
} from '@tabler/icons-vue'

export const teacherNavItems = [
  { label: '首页', path: '/teacher', group: '', icon: IconLayoutDashboard },
  { label: '课程与课时', path: '/teacher/courses', group: '备课', icon: IconBooks },
  { label: '评价方案库', path: '/teacher/evaluations', group: '备课', icon: IconClipboardCheck },
  { label: '课堂实施', path: '/teacher/classroom', group: '上课', icon: IconPresentation },
  { label: '作业与测试', path: '/teacher/assessments', group: '评价任务', icon: IconChecklist },
  { label: '题库', path: '/teacher/question-bank', group: '评价任务', icon: IconListDetails },
  { label: '学生学习情况', path: '/teacher/students', group: '学习支持', icon: IconUsers },
  { label: '内容与支持建议', path: '/teacher/stratification', group: '学习支持', icon: IconAdjustmentsHorizontal },
  { label: '教学资源', path: '/teacher/resources', group: '资源', icon: IconLibrary },
  { label: '协作文档', path: '/teacher/documents', group: '资源', icon: IconFiles },
  { label: '公告', path: '/teacher/notices', group: '沟通与设置', icon: IconSpeakerphone },
  { label: '学生留言', path: '/teacher/feedback', group: '沟通与设置', icon: IconMessage },
  { label: '个人 AI 设置', path: '/teacher/ai', group: '沟通与设置', icon: IconRobot }
]

export function teacherNav(activePath: string) {
  return teacherNavItems.map((item) => ({
    ...item,
    active: item.path === '/teacher' ? activePath === item.path : item.path === activePath || activePath.startsWith(`${item.path}/`)
  }))
}
