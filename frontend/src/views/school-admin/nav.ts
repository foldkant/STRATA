export const schoolAdminNavItems = [
  { label: '管理首页', path: '/school-admin' },
  { label: '教师管理', path: '/school-admin/teachers' },
  { label: '学生管理', path: '/school-admin/students' },
  { label: '班级管理', path: '/school-admin/classes' },
  { label: '任课关系', path: '/school-admin/teaching' },
  { label: '学科与学科前测', path: '/school-admin/pretests' },
  { label: '资源审核', path: '/school-admin/resource-reviews' },
  { label: '数据质量', path: '/school-admin/data-quality' },
  { label: '模型与训练', path: '/school-admin/models' }
]

export function schoolAdminNav(activePath: string) {
  return schoolAdminNavItems.map((item) => ({
    ...item,
    active: item.path === '/school-admin'
      ? activePath === item.path
      : activePath === item.path || activePath.startsWith(`${item.path}/`)
  }))
}
