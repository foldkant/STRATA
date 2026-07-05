# 前端架构设计

## 定位

新版前端使用 Vue3 承接主要业务界面。  
Django 模板只保留为早期调试页和后端兜底页面，不再继续扩展正式业务功能。

## 技术栈

- Vue3
- TypeScript
- Vite
- Vue Router
- Pinia
- 原生 CSS 变量和轻量组件

第一阶段不引入大型 UI 组件库。  
原因是后台样式已经确定，先用少量通用组件沉淀表格、指标卡、布局、表单和确认交互，避免每个角色重复开发。

## 目录结构

```text
frontend/
  index.html
  package.json
  src/
    api/
      client.ts
      auth.ts
      dashboards.ts
      management.ts
    components/
      ConfirmDialog.vue
      EntityFormModal.vue
      ManagementPage.vue
      MetricGrid.vue
      StatusBadge.vue
    layouts/
      AppShell.vue
    router/
      index.ts
    stores/
      auth.ts
    views/
      LoginView.vue
      super-admin/
        DashboardView.vue
        SchoolsView.vue
        SchoolAdminsView.vue
      school-admin/
        DashboardView.vue
        TeachersView.vue
        StudentsView.vue
        ClassesView.vue
        TeachingView.vue
        PretestsView.vue
      teacher/
        DashboardView.vue
        CoursesView.vue
        CourseDetailView.vue
        ClassroomView.vue
        TasksView.vue
        TestsView.vue
        ProjectsView.vue
        StudentsView.vue
        QuestionBankView.vue
        ResourcesView.vue
        StratificationView.vue
        NoticesView.vue
    composables/
      usePageSelection.ts
      useBulkDisableDelete.ts
    types/
      forms.ts
    styles/
      main.css
    App.vue
    main.ts
```

## 前后端边界

Vue 负责：

- 登录页。
- 路由和角色跳转。
- 超级管理员、学校管理员、教师、学生工作台。
- 表格、表单、弹窗、确认提示。
- WebSocket 实时课堂交互。

Django 负责：

- 数据模型。
- 权限校验。
- Session 登录态。
- DRF API。
- XLSX 导入导出。
- WebSocket 后端。
- Celery 任务。
- AI 训练和模型版本。

## 认证方式

第一阶段采用同域 `Session Cookie + CSRF`。

原因：

- 私有化部署中前后端可以同源发布。
- 不需要额外维护 JWT 刷新逻辑。
- WebSocket 可以复用 Django 登录态。
- 更适合学校机房和局域网部署。

Vue 登录流程：

1. 调用 `GET /api/v1/auth/csrf/` 获取 CSRF Cookie。
2. 调用 `POST /api/v1/auth/login/` 登录。
3. 调用 `GET /api/v1/auth/me/` 获取当前用户和角色。
4. 前端根据角色跳转：
   - `super_admin` -> `/super-admin`
   - `school_admin` -> `/school-admin`
   - `teacher` -> `/teacher`
   - `student` -> `/student`

## API 客户端

所有 API 请求统一走 `src/api/client.ts`。

统一处理：

- `credentials: "include"`。
- CSRF 请求头。
- JSON 序列化。
- 401 跳转登录。
- 403 显示无权限。
- 422/400 表单错误映射。

不在页面里直接写 `fetch`。

## 路由设计

```text
/login
/super-admin
/super-admin/schools
/super-admin/school-admins
/super-admin/collection
/super-admin/analysis
/super-admin/health
/school-admin
/school-admin/teachers
/school-admin/students
/school-admin/classes
/school-admin/teaching
/school-admin/pretests
/teacher
/teacher/courses
/teacher/courses/:courseId
/teacher/courses/:courseId/lessons
/teacher/lessons/:lessonId
/teacher/classroom
/teacher/tasks
/teacher/tests
/teacher/projects
/teacher/students
/teacher/question-bank
/teacher/resources
/teacher/stratification
/teacher/notices
/student
/student/onboarding
/student/pretests/:subjectId
/student/courses
/student/courses/:courseId
/student/lessons/:lessonId/workspace
/student/classroom/:sessionId
/student/resources
/student/tasks
/student/projects
/student/profile
/student/notices
/student/feedback
```

当前已实现：

- `/login`
- `/super-admin`
- `/super-admin/schools`
- `/super-admin/school-admins`
- `/school-admin`
- `/school-admin/teachers`
- `/school-admin/students`
- `/school-admin/classes`
- `/school-admin/teaching`
- `/school-admin/pretests`
- `/teacher`
- `/teacher/students`
- `/teacher/notices`
- `/teacher/feedback`
- `/teacher/courses`
- `/teacher/classroom`

其它路由后续接 API 时补页面。

教师端路由设计详见 `docs/teacher_module_design.md`。当前教师端已经完成“工作台、学生管理、公告通知、留言反馈、课程管理、课堂活动”第一版。后续继续扩展题库、资源、测试、项目、学生档案画像和分层建议。

课程与课堂的下一版以 `docs/lesson_workspace_ai_design.md` 为准：教师进入课时后按环节组织资源、题目、任务、作品上传和 AI 生成学习单；学生端采用左侧资源预览、右侧本环节任务的结构，同一环节内可以边看视频/PPT边完成选择题或提交任务。当前 `/teacher/classroom` 第一版仅作为数据模型和接口基础，不作为最终课堂 UI 方向。

学生端路由设计详见 `docs/student_module_design.md`。学生端不使用后台侧边栏布局，核心是首次使用、学科前测、课程学习、课时学习工作台、实时课堂同步、任务作品提交、学习档案和留言反馈。

## 复用策略

避免臃肿的原则：

- 一个后台 Shell，按角色传入菜单。
- 一个指标卡组件，超管和校管共用。
- 一个状态徽标组件，所有列表共用。
- `ManagementPage` 统一封装查询、分页、导出/模板/导入入口和表格外壳。
- `EntityFormModal` 统一封装新增、编辑、重置密码表单和字段错误展示。
- `ConfirmDialog` 统一封装停用、启用、删除确认。
- `usePageSelection` 统一处理当前页多选、全选和选择清空。
- `useBulkDisableDelete` 统一处理“批量删除前必须先停用”的交互逻辑。
- API 层按资源分组，不按页面复制。

批量删除统一交互：

- 选中项为空时提示先选择。
- 点击批量删除时，如果有启用账号、启用学校或启用班级，只执行批量停用。
- 停用完成后清空选择，提示用户重新勾选再删除。
- 第二次删除只对已停用或归档数据执行物理删除。
- 有业务关联的数据由后端拒绝物理删除，并保持停用或归档状态。

## 部署方式

开发环境：

```text
Vite dev server -> /api 代理到 Django
Django -> API / WebSocket / 文件
```

生产或学校内网环境：

```text
Vue build -> static/frontend
Django 或 Nginx 提供静态文件
Django 提供 /api/v1/ 和 /ws/
```

所有前端依赖必须可离线安装。  
后续需要准备 npm 离线缓存或内网包目录。

## Django 模板迁移策略

- 已有 Django 模板暂时保留，作为调试和回退入口。
- 新功能优先做 API + Vue，不再新增正式 Django 模板页面。
- 已完成的 Django 业务逻辑迁移为 service/API。
- Vue 页面稳定后，隐藏 `/ops/`、`/school-admin/` 模板入口，只保留 `/admin/` 给部署维护人员。

当前状态：

- `/app/...` 是正式前端入口。
- `/ops/super-admin/`、`/ops/super-admin/schools/`、`/ops/super-admin/school-admins/` 等旧页面入口已重定向到 Vue。
- Vue 仍使用部分 Django 文件流接口下载 XLSX 模板和导出文件，因此这些接口暂不删除。
- 新增正式业务页面必须先做 API，再做 Vue，不再扩展 Django 模板。

## TypeScript 路径

`tsconfig.json` 不再使用已弃用的 `baseUrl`。  
路径别名写为：

```json
"paths": {
  "@/*": ["./src/*"]
}
```
