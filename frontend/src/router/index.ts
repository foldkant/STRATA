import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'

const SuperAdminDashboard = () => import('@/views/super-admin/DashboardView.vue')
const SchoolsView = () => import('@/views/super-admin/SchoolsView.vue')
const SchoolAdminsView = () => import('@/views/super-admin/SchoolAdminsView.vue')
const SchoolAdminDashboard = () => import('@/views/school-admin/DashboardView.vue')
const TeachersView = () => import('@/views/school-admin/TeachersView.vue')
const StudentsView = () => import('@/views/school-admin/StudentsView.vue')
const ClassesView = () => import('@/views/school-admin/ClassesView.vue')
const TeachingView = () => import('@/views/school-admin/TeachingView.vue')
const PretestsView = () => import('@/views/school-admin/PretestsView.vue')
const SchoolAdminResourceReviewsView = () => import('@/views/school-admin/ResourceReviewsView.vue')
const SchoolAdminQuestionReviewsView = () => import('@/views/school-admin/QuestionReviewsView.vue')
const SchoolAdminDataQualityView = () => import('@/views/school-admin/DataQualityView.vue')
const TeacherDashboard = () => import('@/views/teacher/DashboardView.vue')
const TeacherCoursesView = () => import('@/views/teacher/CoursesView.vue')
const TeacherClassroomView = () => import('@/views/teacher/ClassroomView.vue')
const TeacherClassroomConsoleView = () => import('@/views/teacher/ClassroomConsoleView.vue')
const TeacherDocumentsView = () => import('@/views/teacher/DocumentsView.vue')
const TeacherAIProviderView = () => import('@/views/teacher/AIProviderView.vue')
const TeacherLessonDesignerView = () => import('@/views/teacher/LessonDesignerView.vue')
const TeacherStudentsView = () => import('@/views/teacher/StudentsView.vue')
const TeacherNoticesView = () => import('@/views/teacher/NoticesView.vue')
const TeacherFeedbackView = () => import('@/views/teacher/FeedbackView.vue')
const TeacherResourcesView = () => import('@/views/teacher/ResourcesView.vue')
const TeacherQuestionBankView = () => import('@/views/teacher/QuestionBankView.vue')
const TeacherAssessmentsView = () => import('@/views/teacher/AssessmentsView.vue')
const TeacherEvaluationManagementView = () => import('@/views/teacher/EvaluationManagementView.vue')
const TeacherModulePlaceholder = () => import('@/views/teacher/ModulePlaceholderView.vue')
const StudentDashboard = () => import('@/views/student/DashboardView.vue')
const StudentCoursesView = () => import('@/views/student/CoursesView.vue')
const StudentCourseDetailView = () => import('@/views/student/CourseDetailView.vue')
const StudentLessonWorkspaceView = () => import('@/views/student/LessonWorkspaceView.vue')
const StudentClassroomView = () => import('@/views/student/ClassroomView.vue')
const StudentOnboardingView = () => import('@/views/student/OnboardingView.vue')
const StudentPretestsView = () => import('@/views/student/PretestsView.vue')
const StudentNoticesView = () => import('@/views/student/NoticesView.vue')
const StudentFeedbackView = () => import('@/views/student/FeedbackView.vue')
const StudentAssessmentsView = () => import('@/views/student/AssessmentsView.vue')
const StudentAssessmentWorkspaceView = () => import('@/views/student/AssessmentWorkspaceView.vue')
const StudentProfileView = () => import('@/views/student/ProfileView.vue')
const StudentResourcesView = () => import('@/views/student/ResourcesView.vue')
const StudentModulePlaceholder = () => import('@/views/student/ModulePlaceholderView.vue')
const PlaceholderView = () => import('@/views/PlaceholderView.vue')
const LearningPageView = () => import('@/views/LearningPageView.vue')

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/login' },
  { path: '/login', component: LoginView, meta: { public: true } },
  { path: '/learning-pages/:pageId', component: LearningPageView, meta: { roles: ['teacher', 'student'] } },
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
  { path: '/school-admin/resource-reviews', component: SchoolAdminResourceReviewsView, meta: { role: 'school_admin' } },
  { path: '/school-admin/question-reviews', component: SchoolAdminQuestionReviewsView, meta: { role: 'school_admin' } },
  { path: '/school-admin/data-quality', component: SchoolAdminDataQualityView, meta: { role: 'school_admin' } },
  { path: '/school-admin/evaluations', redirect: '/school-admin' },
  { path: '/school-admin/models', component: PlaceholderView, meta: { role: 'school_admin', title: '分层分析' } },
  { path: '/teacher', component: TeacherDashboard, meta: { role: 'teacher' } },
  { path: '/teacher/courses', component: TeacherCoursesView, meta: { role: 'teacher' } },
  { path: '/teacher/lessons/:lessonId/design', component: TeacherLessonDesignerView, meta: { role: 'teacher' } },
  { path: '/teacher/classroom', component: TeacherClassroomView, meta: { role: 'teacher' } },
  { path: '/teacher/classroom/:sessionId', component: TeacherClassroomConsoleView, meta: { role: 'teacher' } },
  { path: '/teacher/assessments', component: TeacherAssessmentsView, meta: { role: 'teacher' } },
  { path: '/teacher/evaluations', component: TeacherEvaluationManagementView, meta: { role: 'teacher' } },
  { path: '/teacher/tasks', redirect: '/teacher/assessments' },
  {
    path: '/teacher/projects',
    component: TeacherModulePlaceholder,
    meta: { role: 'teacher', title: '项目学习', description: '管理项目任务、作品提交、自评互评和教师评价。' }
  },
  { path: '/teacher/students', component: TeacherStudentsView, meta: { role: 'teacher' } },
  { path: '/teacher/question-bank', component: TeacherQuestionBankView, meta: { role: 'teacher' } },
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
    meta: { role: 'teacher', title: '分层建议', description: '查看学生学习安排建议和参考原因，由教师确认后生效。' }
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
  { path: '/student/resources', component: StudentResourcesView, meta: { role: 'student' } },
  { path: '/student/courses/:courseId', component: StudentCourseDetailView, meta: { role: 'student' } },
  { path: '/student/lessons/:lessonId/workspace', component: StudentLessonWorkspaceView, meta: { role: 'student' } },
  { path: '/student/classroom/:sessionId', component: StudentClassroomView, meta: { role: 'student' } },
  { path: '/student/assessments', component: StudentAssessmentsView, meta: { role: 'student' } },
  { path: '/student/assessments/:assessmentId', component: StudentAssessmentWorkspaceView, meta: { role: 'student' } },
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
    component: StudentProfileView,
    meta: { role: 'student', title: '学习档案' }
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
  const requiredRoles = Array.isArray(to.meta.roles) ? to.meta.roles.filter((role): role is string => typeof role === 'string') : []
  const currentRole = auth.user?.role
  if (requiredRoles.length && (!currentRole || !requiredRoles.includes(currentRole))) {
    return auth.homePath
  }
  return true
})
