export const teacherNavItems = [
  { label: '教师首页', path: '/teacher' },
  { label: '课程备课', path: '/teacher/courses' },
  { label: '课堂教学', path: '/teacher/classroom' },
  { label: '学生管理', path: '/teacher/students' },
  { label: '测试管理', path: '/teacher/assessments' },
  { label: '题库管理', path: '/teacher/question-bank' },
  { label: '资源中心', path: '/teacher/resources' },
  { label: '协作文档', path: '/teacher/documents' },
  { label: 'AI接入', path: '/teacher/ai' },
  { label: '分层调节', path: '/teacher/stratification' },
  { label: '公告通知', path: '/teacher/notices' },
  { label: '留言反馈', path: '/teacher/feedback' }
]

export function teacherNav(activePath: string) {
  return teacherNavItems.map((item) => ({
    ...item,
    active: item.path === '/teacher' ? activePath === item.path : item.path === activePath || activePath.startsWith(`${item.path}/`)
  }))
}
