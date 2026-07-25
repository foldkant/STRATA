import {
  IconActivityHeartbeat,
  IconBook2,
  IconBuildingCommunity,
  IconChartHistogram,
  IconDatabaseImport,
  IconLayoutDashboard,
  IconUserShield
} from '@tabler/icons-vue'

export const superAdminNavItems = [
  { label: '首页', path: '/super-admin', group: '', icon: IconLayoutDashboard },
  { label: '学校信息', path: '/super-admin/schools', group: '学校管理', icon: IconBuildingCommunity },
  { label: '学校管理员', path: '/super-admin/school-admins', group: '学校管理', icon: IconUserShield },
  { label: '课程标准', path: '/super-admin/curriculum-standards', group: '课程与评价', icon: IconBook2 },
  { label: '学校数据接收', path: '/super-admin/collection', group: '数据与分析', icon: IconDatabaseImport },
  { label: '校际数据概览', path: '/super-admin/analysis', group: '数据与分析', icon: IconChartHistogram },
  { label: '系统检查', path: '/super-admin/health', group: '系统保障', icon: IconActivityHeartbeat }
]

export function superAdminNav(activePath: string) {
  return superAdminNavItems.map((item) => ({
    ...item,
    active: item.path === '/super-admin'
      ? activePath === '/super-admin'
      : activePath.startsWith(item.path)
  }))
}
