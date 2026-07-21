# 前端架构设计

## 动态分层与分组页面（2026-07-20）

- 学校管理员在“分层分析”的“层级标准”页签维护按学科/课程版本化的标准，不把研究参数堆入教师日常页面。
- 教师 `/teacher/stratification` 必须选择单一课程，使用“当前分层、待处理建议、学习依据、处理记录”四个视图；学生端没有层级页面。
- 教师课堂的小组合作使用固定头部、内部滚动正文和固定底部操作区。候选卡、拖动和选择移动共享同一份草稿状态。
- `ClassroomChatDock` 除聊天消息外向父页面转发课堂实时事件；教师和学生收到 `grouping.updated` 后刷新当前计划。
- Playwright 已复查 `375x812`、`768x900`、`1440x900`：分层页无页面级横向溢出；分组弹窗完整位于视口内，正文可滚动且底部操作始终可见。临时截图已删除。

教师端与学生端的四轮响应式、性能和可访问性审查记录见 [ui_ux_audit.md](ui_ux_audit.md)。所有角色页面使用路由级动态导入；重型图表、评价弹窗和 AI 学习网页组件继续使用组件级异步加载，避免进入登录首包。

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
      AppSelect.vue
      ClassChipList.vue
      ConfirmDialog.vue
      EntityFormModal.vue
      ManagementPage.vue
      MetricGrid.vue
      MultiSelectActions.vue
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

## 共享下拉控件

- 正式业务页面统一使用全局注册的 `AppSelect.vue`，不在各页面重复实现下拉菜单。
- 控件兼容 `v-model`、`v-model.number`、禁用项、必填校验和原有 `change` 事件；支持方向键、Enter、Space、Home、End、Escape 和点击外部关闭。
- 展开菜单使用 `Teleport` 放到页面根层，并根据可用空间自动向上或向下展开，避免被弹窗、表格和局部滚动容器裁切。
- 选项可通过 `title` 或 `data-description` 提供简短说明；鼠标悬停和键盘聚焦时使用同一说明区域，不依赖浏览器原生 `option` 提示。
- `AppSelect` 内部保留一个不可见的原生 `select`，只用于浏览器表单校验和字段提交兼容。该内部元素不得替换为 `AppSelect`，否则会形成组件递归并导致页面无法挂载。
- AI 学习网页运行在独立沙箱 iframe 中，不能直接挂载 Vue 组件；其中由系统生成的表单控件继续使用沙箱自身样式和校验逻辑。

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
/school-admin/resource-reviews
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
- `/super-admin/collection`
- `/super-admin/analysis`
- `/super-admin/health`
- `/school-admin`
- `/school-admin/teachers`
- `/school-admin/students`
- `/school-admin/classes`
- `/school-admin/teaching`
- `/school-admin/pretests`
- `/school-admin/resource-reviews`
- `/teacher`
- `/teacher/students`
- `/teacher/notices`
- `/teacher/feedback`
- `/teacher/courses`
- `/teacher/classroom`
- `/teacher/resources`
- `/student/resources`

超级管理员上述六个路由均已接入真实 API。跨校采集、跨校分析和系统健康不再使用 `PlaceholderView`；严重故障与最近操作日志收敛在系统健康页面的独立页签中，避免继续扩大侧栏。

超级管理员页面菜单统一由 `views/super-admin/nav.ts` 生成，页面不得各自复制菜单数组。采集包上传复用 `FilePicker`，图表继续复用 `EChartPanel` 与 `chartOptions`；操作日志动作名称由 `utils/auditLabels.ts` 统一转换为用户可读文字，同时保留内部动作编码供排查。

教师端路由设计详见 `docs/teacher_module_design.md`。当前教师端已经完成“工作台、学生管理、公告通知、留言反馈、课程管理、课堂活动”第一版。后续继续扩展题库、资源、测试、项目、学生档案画像和分层建议。

课程与课堂的下一版以 `docs/lesson_workspace_ai_design.md` 为准：教师进入课时后按环节组织资源、题目、任务、作品上传和 AI 生成学习单；学生端采用左侧资源预览、右侧本环节任务的结构，同一环节内可以边看视频/PPT边完成选择题或提交任务。当前 `/teacher/classroom` 第一版仅作为数据模型和接口基础，不作为最终课堂 UI 方向。

AI 隐性分层按 `docs/student_behavior_ai_stratification_development_roadmap.md` 开发。学生前端不建立分层页面，也不接收 `current_layer/target_layer/layer_scores/is_layered/layer_hint/grouping_strategy` 等内部字段；题目和资源必须由服务端解析后只返回本人实际投放内容。教师分层工作台在独立 `features/stratification` 领域中建设，不与学生 DTO 复用。

动态分组按 `docs/dynamic_grouping_ten_round_validation.md` 建立独立 `features/grouping` 领域。教师端处理任务策略、候选组、锁定成员、角色和确认；学生端只接收已生效的中性组名、本人组员、角色、聊天、文档和共享空间，不接收策略代码、目标权重、准备度或其他学生证据。

学生端路由设计详见 `docs/student_module_design.md`。学生端不使用后台侧边栏布局，核心是首次使用、学科前测、课程学习、课时学习工作台、实时课堂同步、任务作品提交、学习档案和留言反馈。

资源中心采用共享卡片、详情预览弹窗和独立编辑弹窗。教师编辑弹窗内部滚动、底部操作固定；学生端资源卡片在桌面双列、窄屏单列。三端共享 `ResourcePreview`，不重复实现 Office、PDF、图片和音视频预览逻辑。

## 复用策略

避免臃肿的原则：

- 一个后台 Shell，按角色传入菜单。
- 一个指标卡组件，超管和校管共用。
- 一个状态徽标组件，所有列表共用。
- `ManagementPage` 统一封装查询、分页、导出/模板/导入入口和表格外壳。
- `EntityFormModal` 统一封装新增、编辑、重置密码表单和字段错误展示。
- `ConfirmDialog` 统一封装停用、启用、删除确认。
- `MultiSelectActions` 统一显示多选数量、全选和全不选；测试、公告、资源、课程和任课关系中的班级多选不得单独复制按钮逻辑。
- `ClassChipList` 统一展示班级标签，表格默认只显示前三个，其余以 `+N` 汇总，避免班级数量较多时撑宽表格。
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

前端发布必须保留上一稳定版本的哈希资源。Vite 的 `emptyOutDir` 固定为 `false`，不能在覆盖部署时先清空 `static/frontend/assets`。`/app/...` 的入口 HTML 使用禁止缓存响应；登录成功后执行整页加载，以免已经打开的旧标签页继续请求被删除的分包文件。学校服务器确认所有终端完成升级后，才可按发布批次清理更早资源。

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

## 受控学习网页

- `LearningPageFrame.vue` 根据后端白名单 schema 生成 `srcdoc`，所有文本逐字段 HTML 转义，不使用 `v-html`。
- iframe 使用 `sandbox="allow-scripts"`，不授予 `allow-same-origin`、弹窗、下载、摄像头、麦克风或顶层导航权限。
- iframe CSP 禁止网络连接、外部资源、原生表单提交、对象和子 iframe；仅带固定 nonce 的 STRATA 表单桥接脚本可运行。提交按钮必须使用 `type="button"`，由固定脚本直接校验和收集字段，再通过 `postMessage` 通知 Vue 父页面，不能依赖沙箱会提前拦截的原生 `submit` 事件。
- 父页面只接受 `event.source === iframe.contentWindow` 且消息类型、页面编号和数据结构正确的提交，再由 Vue API 客户端携带登录态和 CSRF 写入 Django。
- 教师和学生点击“新标签页打开”后进入独立深链接 `/app/learning-pages/:pageId`；教师预览不启用提交，学生页面启用提交。
- 禁止使用 Teleport 全屏弹层再次挂载同一个 `LearningPageFrame`。课堂内预览和独立页面分别只保留一个 iframe，避免 `srcdoc`、表单监听和消息通道重复初始化造成闪烁。
- 独立页面采用“固定顶栏 + `minmax(0, 1fr)` 内容区”，加载、错误和 iframe 共用稳定的视口尺寸，异步加载不得改变页面高度。
- 新标签页入口和返回/重试按钮的可点击高度不低于 44px，必须有 `focus-visible` 状态，并遵守 `prefers-reduced-motion`。
- 课堂轮询只能更新课堂状态，不得按资源对象引用重载学习网页。`ResourcePreview` 以“页面编号 + 版本号”为稳定键；键未变化时保留当前 iframe、表单内容和提交状态。
- 普通动画优先使用受控 `visualization` 区块；流程、时间线、柱状对比和二进制动画由 `LearningPageFrame` 固定模板渲染。
- 复杂动画可使用 `interactive` 区块提供自包含 HTML/CSS/JavaScript。它必须运行在学习网页 iframe 内的第二层 `sandbox="allow-scripts"` iframe 中，不继承登录态、不能访问外层表单桥、不能联网或导航主页面；外层只提供“重新运行”。
- 教师端生成区使用 `智能选择 / 自由交互动画 / 受控演示` 分段控件；创建与继续修改分别保存本次选择，不依赖教师记忆特定提示词。
- 自由动画 iframe 内置运行错误提示，脚本异常会在动画区域显示原因。系统“减少动态效果”仅阻止受控动画自动播放和循环，用户主动点击播放仍然生效。

### 2026-07-11 UI/UX 审查记录

- 学习网页属于主要学习任务，不使用覆盖课堂的模态框，改用可复制、可刷新、可恢复的独立路由。
- 全屏页不加载教师或学生工作台侧栏，内容优先占满可用视口；原课堂标签页保持资源位置和作答上下文不变。
- 页面加载时预留完整内容区并显示轻量进度状态，失败时在原位置给出原因和重试操作，避免空白页和布局跳动。
- 375、768、1024、1440 宽度均不得出现横向滚动；窄屏顶栏压缩辅助信息，但保留标题与返回操作。

## 课堂聊天共用组件

教师和学生课堂页统一使用 `frontend/src/components/ClassroomChatDock.vue`，不分别复制聊天业务组件。角色差异由 `role` 属性和后端权限数据控制：

- 共用房间标签、实名消息、首字头像、输入区、未读数和 WebSocket 重连。
- 教师增加聊天开关、学生/小组选择和言论审核。
- 学生只渲染后端返回为已开启的房间。
- REST API 封装集中在 `frontend/src/api/chat.ts`。
- 桌面端使用右侧抽屉，移动端使用全宽抽屉；课堂资源和任务布局不因聊天消息数量增长而拉伸。

2026-07-17 使用 UI/UX 审查流程检查 1440x900 和 375x812：抽屉均无横向溢出，消息区独立滚动，移动端输入区保持可见；临时截图在审查后删除。

## 学校数据检查页面

- 路由：`/school-admin/data-quality`，页面按路由动态导入。
- API 与类型集中在 `frontend/src/api/analytics.ts`，不复制通用请求、CSRF 或错误处理。
- 复用 `AppShell`、`NoticeLine` 和 `EChartPanel`；页面只实现检查指标卡、问题列表和执行阶段。
- 当前报告和七项判断标准使用文字、数字和颜色共同表达；图表下方的运行记录与指标卡提供非图形信息兜底。
- 有 `pending/running` 任务时每 3 秒刷新，任务结束后停止，不建立永久轮询。
- 运行记录表在窄屏仅在 `.table-wrap` 内横向滚动，根页面禁止横向滚动。
- 通用 `.workspace` 必须声明 `grid-template-columns: minmax(0, 1fr)`，`.topbar/.content` 必须 `min-width: 0`，防止任意宽表撑开整个后台。
- 学生端和教师端不新增平台数据检查入口。

2026-07-19 使用 UI/UX 审查流程检查 `1440x900` 和 `390x844`：根页面横向溢出均为 0，七项卡片无文本越界，桌面趋势图容器稳定，手机操作按钮完整可见；页面提交真实 Celery 任务后运行记录由 1 条变 2 条且无控制台异常。临时截图审查后删除。

## 教师评价标准页面

- 路由：`/teacher/evaluations`，API 与类型集中在 `frontend/src/api/evaluation.ts`。
- 页面复用 `AppShell`、`NoticeLine` 和 `ConfirmDialog`；评价方案、评价标准和评价指标分别拆为组件，避免把完整编辑逻辑堆入主页面。
- 评价方案与评价指标使用三步弹窗，标题和底部操作固定，表单正文独立滚动；评价标准弹窗只管理总体信息和指标列表，进入指标编辑时隐藏上一层弹窗。
- 桌面使用紧凑表格；小于 640px 时转为纵向信息块，不产生页面级横向滚动。
- 所有字段有可见标签，必填星号使用危险色；异步保存和发布均提供禁用状态、成功或字段错误反馈。

页面必须在 `390x844`、`768x900` 和 `1440x900` 检查无横向溢出、弹窗操作栏可见、字段错误靠近输入项。临时截图审查后删除。

评价页面不再与课程列表共用旧 `CourseEvaluationModal`。课程列表不提供课程级评价编辑；课时设计器只显示已发布标准选择和自评、互评、师评开关；课堂控制台只显示开启、执行和查看。

## 页面反馈规则

- 页面级异步操作结果复用 `NoticeLine floating`，由 `App.vue` 的全局反馈区域统一承载；不得在每个页面复制定位、动画和关闭样式。
- 成功和普通信息自动消失，警告和错误由用户关闭；页面必须监听 `dismiss` 并清空对应状态，保证相同操作可重复反馈。
- 持久说明、数据环境提示和表单字段错误使用普通内联模式，放在相关内容附近，不进入全局反馈区域。
- 多条反馈由全局区域纵向排列；移动端宽度限制在视口内，不遮挡页面宽度或制造横向滚动。
- 长页面的本页页签和高频操作可以使用局部停靠工具栏，但必须使用实色背景、明确边界和响应式换行，不能让正文透出或覆盖控件。

## 共同题与学习情况页面

- 学校管理员题库审核页增加“共同题集合”，按学科发布、归档和导出，不与教师个人题目编辑混在同一弹窗。
- 教师题库和组卷页显示普通题、共同题、分层题及适用范围；选择共同题集合后自动加入必备共同题。
- 测试成绩逐题卡显示答对率、难度、区分度和选项分布。样本不足时显示“数据不足”，不显示 `null%`、0% 进度条或推断性结论。
- 教师 `/teacher/stratification` 默认显示“当前分层”，并拆分为“当前分层 / 待处理建议 / 学习依据 / 处理记录”四个明确视图。
- 当前过渡页面显示测试期 A/B/C/未分层人数、学生名单、近 30 日完成率/得分率和最新建议；支持班级、课程、层级、关键词筛选及 XLSX 导出。当前 MODEL-03 分组只验收完成支持流程，正式页面将按内容建议、完成支持、成长趋势和数据状态拆分。
- 待处理建议只显示当前待办；处理记录按学生和课程去重，只显示最新记录，旧版本不在主列表重复堆叠。
- 教师审核支持采纳、保持、调整和暂缓。采纳或调整后当前名单立即刷新；学生端不建立层级页面。
- 1440px 使用紧凑表格，1024px 以下转为双列信息块，620px 以下转为单列；页面不得产生横向溢出，按钮保持至少 44px 可点击高度。
