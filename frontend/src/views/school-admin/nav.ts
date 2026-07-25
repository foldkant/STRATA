import {
  IconBook2,
  IconBuildingCommunity,
  IconChartDots3,
  IconChecklist,
  IconClipboardCheck,
  IconFlask2,
  IconLayoutDashboard,
  IconSchool,
  IconUser,
  IconUsersGroup,
  IconUsersPlus
} from '@tabler/icons-vue'

export const schoolAdminNavItems = [
  { label: '首页', path: '/school-admin', group: '', icon: IconLayoutDashboard },
  { label: '班级管理', path: '/school-admin/classes', group: '教学组织', icon: IconBuildingCommunity },
  { label: '教师管理', path: '/school-admin/teachers', group: '教学组织', icon: IconSchool },
  { label: '学生管理', path: '/school-admin/students', group: '教学组织', icon: IconUser },
  { label: '任课关系', path: '/school-admin/teaching', group: '教学组织', icon: IconUsersPlus },
  { label: '学习起点诊断', path: '/school-admin/pretests', group: '诊断与评价', icon: IconClipboardCheck },
  { label: '资源审核', path: '/school-admin/resource-reviews', group: '诊断与评价', icon: IconBook2 },
  { label: '题库审核', path: '/school-admin/question-reviews', group: '诊断与评价', icon: IconChecklist },
  { label: '数据检查', path: '/school-admin/data-quality', group: '学习支持', icon: IconChartDots3 },
  { label: '学习情况与支持建议', path: '/school-admin/models', group: '学习支持', icon: IconUsersGroup },
  { label: '教育实验', path: '/school-admin/research', group: '教育研究', icon: IconFlask2 }
]

export function schoolAdminNav(activePath: string) {
  return schoolAdminNavItems.map((item) => ({
    ...item,
    active: item.path === '/school-admin'
      ? activePath === item.path
      : activePath === item.path || activePath.startsWith(`${item.path}/`)
  }))
}
