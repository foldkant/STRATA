export const superAdminNavItems = [
  { label: '数据总览', path: '/super-admin' },
  { label: '学校管理', path: '/super-admin/schools' },
  { label: '学校管理员', path: '/super-admin/school-admins' },
  { label: '课程标准', path: '/super-admin/curriculum-standards' },
  { label: '跨校数据采集', path: '/super-admin/collection' },
  { label: '跨校分析', path: '/super-admin/analysis' },
  { label: '系统健康', path: '/super-admin/health' }
]

export function superAdminNav(activePath: string) {
  return superAdminNavItems.map((item) => ({
    ...item,
    active: item.path === '/super-admin'
      ? activePath === '/super-admin'
      : activePath.startsWith(item.path)
  }))
}
