import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'
import SuperAdminDashboard from '@/views/super-admin/DashboardView.vue'
import SchoolsView from '@/views/super-admin/SchoolsView.vue'
import SchoolAdminsView from '@/views/super-admin/SchoolAdminsView.vue'
import SchoolAdminDashboard from '@/views/school-admin/DashboardView.vue'
import TeachersView from '@/views/school-admin/TeachersView.vue'
import StudentsView from '@/views/school-admin/StudentsView.vue'
import ClassesView from '@/views/school-admin/ClassesView.vue'
import TeachingView from '@/views/school-admin/TeachingView.vue'
import PretestsView from '@/views/school-admin/PretestsView.vue'
import TeacherDashboard from '@/views/teacher/DashboardView.vue'
import TeacherCoursesView from '@/views/teacher/CoursesView.vue'
import TeacherClassroomView from '@/views/teacher/ClassroomView.vue'
import TeacherClassroomConsoleView from '@/views/teacher/ClassroomConsoleView.vue'
import TeacherDocumentsView from '@/views/teacher/DocumentsView.vue'
import TeacherAIProviderView from '@/views/teacher/AIProviderView.vue'
import TeacherLessonDesignerView from '@/views/teacher/LessonDesignerView.vue'
import TeacherStudentsView from '@/views/teacher/StudentsView.vue'
import TeacherNoticesView from '@/views/teacher/NoticesView.vue'
import TeacherFeedbackView from '@/views/teacher/FeedbackView.vue'
import TeacherResourcesView from '@/views/teacher/ResourcesView.vue'
import TeacherModulePlaceholder from '@/views/teacher/ModulePlaceholderView.vue'
import StudentDashboard from '@/views/student/DashboardView.vue'
import StudentCoursesView from '@/views/student/CoursesView.vue'
import StudentCourseDetailView from '@/views/student/CourseDetailView.vue'
import StudentLessonWorkspaceView from '@/views/student/LessonWorkspaceView.vue'
import StudentClassroomView from '@/views/student/ClassroomView.vue'
import StudentOnboardingView from '@/views/student/OnboardingView.vue'
import StudentPretestsView from '@/views/student/PretestsView.vue'
import StudentNoticesView from '@/views/student/NoticesView.vue'
import StudentFeedbackView from '@/views/student/FeedbackView.vue'
import StudentModulePlaceholder from '@/views/student/ModulePlaceholderView.vue'
import PlaceholderView from '@/views/PlaceholderView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/login' },
  { path: '/login', component: LoginView, meta: { public: true } },
  { path: '/super-admin', component: SuperAdminDashboard, meta: { role: 'super_admin' } },
  { path: '/super-admin/schools', component: SchoolsView, meta: { role: 'super_admin' } },
  { path: '/super-admin/school-admins', component: SchoolAdminsView, meta: { role: 'super_admin' } },
  { path: '/super-admin/collection', component: PlaceholderView, meta: { role: 'super_admin', title: '跨校数据采集' } },
  { path: '/super-admin/analysis', component: PlaceholderView, meta: { role: 'super_admin', title: '跨校分析' } },
  { path: '/super-admin/health', component: PlaceholderView, meta: { role: 'super_admin', title: '系统健康' } },
  { path: '/school-admin', component: SchoolAdminDashboard, meta: { role: 'school_admin' } },
  { path: '/school-admin/teachers', component: TeachersView, meta: { role: 'school_admin' } },
  { path: '/school-admin/students', component: StudentsView, meta: { role: 'school_admin' } },
  { path: '/school-admin/classes', component: ClassesView, meta: { role: 'school_admin' } },
  { path: '/school-admin/teaching', component: TeachingView, meta: { role: 'school_admin' } },
  { path: '/school-admin/pretests', component: PretestsView, meta: { role: 'school_admin' } },
  { path: '/school-admin/models', component: PlaceholderView, meta: { role: 'school_admin', title: '模型与训练' } },
  { path: '/teacher', component: TeacherDashboard, meta: { role: 'teacher' } },
  { path: '/teacher/courses', component: TeacherCoursesView, meta: { role: 'teacher' } },
  { path: '/teacher/lessons/:lessonId/design', component: TeacherLessonDesignerView, meta: { role: 'teacher' } },
  { path: '/teacher/classroom', component: TeacherClassroomView, meta: { role: 'teacher' } },
  { path: '/teacher/classroom/:sessionId', component: TeacherClassroomConsoleView, meta: { role: 'teacher' } },
  {
    path: '/teacher/tasks',
    component: TeacherModulePlaceholder,
    meta: { role: 'teacher', title: '任务与测试', description: '维护课堂任务、随堂测试、作业批改和学习过程反馈。' }
  },
  {
    path: '/teacher/projects',
    component: TeacherModulePlaceholder,
    meta: { role: 'teacher', title: '项目学习', description: '管理项目任务、作品提交、自评互评和教师评价。' }
  },
  { path: '/teacher/students', component: TeacherStudentsView, meta: { role: 'teacher' } },
  {
    path: '/teacher/question-bank',
    component: TeacherModulePlaceholder,
    meta: { role: 'teacher', title: '题库资源', description: '教师可维护个人题库，并使用学校公共题库组卷。' }
  },
  {
    path: '/teacher/documents',
    component: TeacherDocumentsView,
    meta: { role: 'teacher' }
  },
  {
    path: '/teacher/ai',
    component: TeacherAIProviderView,
    meta: { role: 'teacher' }
  },
  {
    path: '/teacher/resources',
    component: TeacherResourcesView,
    meta: { role: 'teacher' }
  },
  {
    path: '/teacher/stratification',
    component: TeacherModulePlaceholder,
    meta: { role: 'teacher', title: '分层调节', description: '查看 AI 分层建议、原因和置信度，由教师确认后生效。' }
  },
  {
    path: '/teacher/notices',
    component: TeacherNoticesView,
    meta: { role: 'teacher' }
  },
  {
    path: '/teacher/feedback',
    component: TeacherFeedbackView,
    meta: { role: 'teacher' }
  },
  { path: '/student', component: StudentDashboard, meta: { role: 'student' } },
  { path: '/student/onboarding', component: StudentOnboardingView, meta: { role: 'student' } },
  { path: '/student/pretests/:subjectId', component: StudentPretestsView, meta: { role: 'student' } },
  { path: '/student/courses', component: StudentCoursesView, meta: { role: 'student' } },
  { path: '/student/courses/:courseId', component: StudentCourseDetailView, meta: { role: 'student' } },
  { path: '/student/lessons/:lessonId/workspace', component: StudentLessonWorkspaceView, meta: { role: 'student' } },
  { path: '/student/classroom/:sessionId', component: StudentClassroomView, meta: { role: 'student' } },
  {
    path: '/student/tasks',
    component: StudentModulePlaceholder,
    meta: { role: 'student', title: '任务', description: '汇总课堂题、课后任务、测试和作品提交。' }
  },
  {
    path: '/student/projects',
    component: StudentModulePlaceholder,
    meta: { role: 'student', title: '项目', description: '展示项目阶段、作品提交、学习日志、自评和互评。' }
  },
  {
    path: '/student/profile',
    component: StudentModulePlaceholder,
    meta: { role: 'student', title: '学习档案', description: '查看课程进度、提交记录、前测结果和教师反馈。' }
  },
  { path: '/student/notices', component: StudentNoticesView, meta: { role: 'student' } },
  { path: '/student/feedback', component: StudentFeedbackView, meta: { role: 'student' } }
]

export const router = createRouter({
  history: createWebHistory('/app/'),
  routes
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.load()
  }
  if (to.meta.public) {
    return auth.isAuthenticated ? auth.homePath : true
  }
  if (!auth.isAuthenticated) {
    return '/login'
  }
  const requiredRole = to.meta.role
  if (requiredRole && auth.user?.role !== requiredRole) {
    return auth.homePath
  }
  return true
})
