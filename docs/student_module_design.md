# 学生端功能与界面设计

## 定位

学生端不是后台管理系统。

学生进入平台后的主要任务是：

- 今天上课时跟随教师的课堂节奏。
- 课后进入课程和课时继续学习。
- 查看资源、完成题目、提交任务和作品。
- 完成学科前测、测试、项目、自评和互评。
- 查看自己的学习档案、反馈和教师公告。
- 在需要时向教师提交留言反馈。

学生端不做：

- 大量表格式管理页。
- 学校级或班级级数据大屏。
- 复杂的筛选、批量操作和后台配置。
- 暴露模型分层推理细节。
- 让学生直接看到“你被 AI 分到了哪一层”的后台解释。

学生端应该更像“课堂学习空间”和“课程阅读器”，而不是管理员后台。

## 设计原则

### 1. 课堂优先

学生登录后最重要的是知道“现在该做什么”：

- 当前是否有正在进行的课堂。
- 当前教师开启了哪个课时环节。
- 是否需要签到、答题、提交作品或反馈未懂。
- 未完成的前测、任务、测试和项目。

首页第一屏不要做数据大屏，应突出当前课堂、待完成事项和最近课程。

### 2. 学习过程优先

教师端课时设计出来的是一份学习过程。学生端不重新组织内容，而是按这份学习过程学习。

```text
课程
  -> 课时
      -> 环节
          -> 资源预览
          -> 题目作答
          -> 任务提交
          -> 作品上传
          -> 讨论反馈
          -> 学习日志
```

学生端和教师端必须同步开发：

- 教师端新增课时环节，学生端要能展示环节。
- 教师端上传资源，学生端要能预览或下载资源。
- 教师端配置课堂题，学生端要能作答并提交。
- 教师端发布作品上传，学生端要能上传作品。
- 教师端开启课堂活动，学生端要能实时收到并进入。
- 教师端关闭活动，学生端要停止提交或进入结果反馈。

### 3. 少导航，强引导

学生端可以使用顶部导航或底部快捷入口，不建议使用管理员/教师那种长侧边栏。

推荐结构：

```text
顶部：品牌 / 当前班级 / 当前课堂状态 / 个人入口
主区：当前任务、课程、课时学习
底部或轻导航：课程、课堂、任务、档案、消息
```

PC 机房场景优先保证 1366x768 和 1440 宽度体验。  
学生端可以有纵向滚动，但课时学习页的核心区域要稳定，不要因为资源、题目、按钮高度变化导致页面跳动。

### 4. 高中课堂风格

不要做儿童化、游戏化过重或营销式页面。

建议风格：

- 主题：清爽、专注、现代课堂。
- 主色：延续 STRATA 蓝色，学生端可增加青绿色作为学习进度色。
- 强调色：橙色只用于“现在要做”“待提交”“截止提醒”。
- 背景：浅蓝灰或白色，不使用夸张渐变和装饰图形。
- 卡片：只用于课程、任务、资源、消息等实体项，圆角不超过 8px。
- 字体：使用系统中文字体，保证离线部署。
- 图标：后续统一使用 lucide 或本地 SVG 图标，不使用 emoji。

## 旧 WWW 学生端迁移对应

旧学生端页面：

```text
student/index.php                 -> 学生首页 / 当前课堂入口
student/course.php                -> 我的课程
student/course-info.php           -> 课程详情
student/lesson.php                -> 课时学习工作台
student/resource.php              -> 资源列表
student/resource-content.php      -> 资源预览 / 资源详情
student/student-test.php          -> 测试作答
student/taskCompletion.php        -> 课堂题结果 / 作答反馈
student/my-project.php            -> 项目提交
student/mutual-evaluation.php     -> 互评
student/my-study-file.php         -> 学习档案
student/first-login.php           -> 首次使用流程
student/questionnaire.php         -> 素养前测
student/questionnaire2.php        -> 学习态度问卷
```

新版不应逐页翻译旧 PHP。  
旧页面提供业务参考，新版按“首次使用 -> 首页 -> 课程 -> 课时学习过程 -> 课堂同步 -> 作品/测试/档案”的方式重组。

## 信息架构

第一阶段建议路由：

```text
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

路由职责：

- `/student`：学生首页，显示当前课堂、待完成事项、最近课程和公告。
- `/student/onboarding`：首次使用流程，改密码、选班级、完成前测。
- `/student/pretests/:subjectId`：学科前测，两套题：素养测试和学习态度问卷。
- `/student/courses`：我的课程。
- `/student/courses/:courseId`：课程详情，课时目录和课程说明。
- `/student/lessons/:lessonId/workspace`：课时学习工作台，学生端核心页面。
- `/student/classroom/:sessionId`：实时课堂模式，跟随教师控制。
- `/student/resources`：我的资源，可作为资源历史和收藏入口。
- `/student/tasks`：待完成任务、测试和作品提交。
- `/student/projects`：项目式学习入口，项目阶段、日志、甘特图和评价后续接入。
- `/student/profile`：我的学习档案。
- `/student/notices`：公告。
- `/student/feedback`：给教师留言反馈。

## 首次使用流程

学生账号可能由学校管理员提前发放。新生刚入学时可能没有学号，也可能尚未分班。

首次使用必须支持：

1. 修改初始密码。
2. 选择本校启用班级。
3. 完成当前学科前测。
4. 进入正式学习平台。

已有数据字段：

- `StudentProfile.is_first_use`
- `StudentProfile.onboarding_status`
- `StudentProfile.password_updated_at`
- `StudentProfile.class_selected_at`
- `StudentProfile.pretest_completed_at`

流程建议：

```text
登录
  -> 判断 role=student
  -> 判断 is_first_login 或 is_first_use
  -> 进入 /student/onboarding
      第一步：修改密码
      第二步：选择班级
      第三步：选择要进入的学科并完成前测
  -> 更新 onboarding_status
  -> 完成后进入 /student
```

密码规则：

- 学生允许低安全课堂密码，例如 `123456`。
- 首次登录必须修改密码。
- 教师重置学生密码后，学生下次登录再次要求改密。
- 学生密码规则与管理员/超管不同，不能套强密码规则。

选班规则：

- 只显示本校启用班级。
- 已毕业或停用班级不可选。
- 若学校管理员后续通过学号批量匹配更新，不影响学生已选班级。
- 学号可为空，由学校管理员后续导入更新。

前测规则：

- 学科前测按学科区分。
- 学生进入某学科课程前，必须完成该学科当前发布的两类前测：
  - 素养测试 `literacy`
  - 学习态度问卷 `attitude`
- 未完成该学科前测时，学生可看到课程卡片，但点击进入时先跳转前测。
- 前测提交后写入 `PretestSubmission`，同时写入 `LearningEvent.answer_submit` 或后续扩展的 `pretest_submit`。

## 学生首页

学生首页不是后台首页。第一屏应回答三件事：

- 现在是否有课堂正在进行。
- 我还有什么必须完成。
- 我最近继续学哪个课程。

推荐布局：

```text
顶部学习状态条
  - 姓名 / 班级 / 当前课堂状态 / 退出

主区域
  - 当前课堂卡片
  - 待完成事项
  - 我的课程
  - 最近公告

辅助区域
  - 最近学习记录
  - 我的学习进度
```

首页模块：

- 当前课堂：课程、课时、教师、班级、课堂状态、进入按钮。
- 待完成：未完成前测、课堂任务、测试、项目互评、作品修改。
- 最近课程：课程封面、课程名、学科、教师、最近课时。
- 公告通知：教师发布给本班的公告。
- 学习提醒：例如“上次学习到第 3 个环节”。

不建议首页展示：

- 全班排名大榜。
- 复杂图表。
- 模型置信度。
- 后台指标。

## 我的课程

课程列表面向学生，应以卡片为主。

课程卡片字段：

- 课程封面。
- 课程名称。
- 学科。
- 任课教师。
- 已发布课时数。
- 最近学习进度。
- 当前状态：可学习、需前测、未发布、已结束。

封面规则：

- 教师上传课程封面时显示封面。
- 未上传封面时使用系统生成默认课程封面：蓝色主题 + 课程名称。
- 默认封面必须本地生成或 CSS 渲染，不依赖外网图片。

课程可见规则：

- 学生只能看到自己班级绑定的已发布课程。
- 课程所属班级必须包含学生当前班级。
- 课程所属学校必须是学生所在学校。
- 课程未发布时不可见。
- 课程所属学科未启用时不可进入。

## 课程详情

课程详情用于进入课时，不承担后台编辑。

页面结构：

```text
课程封面 / 课程名称 / 学科 / 教师
课程简介
课时目录
项目式学习区或任务驱动学习区
课程公告
```

课时目录字段：

- 课时名称。
- 发布状态。
- 学习进度：未开始、学习中、已完成。
- 环节数量。
- 最近学习时间。
- 进入课时按钮。

任务驱动课程：

- 重点展示课时目录和当前任务。
- 学生进入课时学习工作台。

项目式学习课程：

- 重点展示项目主题、阶段、里程碑、日志和作品提交。
- 后续进入项目工作台，而不是普通课时列表。

## 课时学习工作台

这是学生端最重要的页面。

推荐桌面布局：

```text
顶部状态栏
  课程 / 课时 / 课堂状态 / 学习进度 / 返回

左侧资源预览区
  当前资源、课件、视频、PDF、文档或素材包

右侧本环节任务区
  顶部横向环节切换条
  当前环节说明
  作答 / 提交 / 反馈区域

底部或右下角
  上一步 / 下一步 / 保存草稿 / 提交
```

移动或窄屏布局：

```text
顶部状态栏
Tab：资源 / 任务
资源预览区
当前环节作答区
底部固定操作按钮
```

左侧资源预览：

- 图片：原生预览。
- 视频：原生播放器，记录播放进度和停留时长。
- 音频：原生播放器。
- PDF：PDF.js 或 ONLYOFFICE PDF 预览。
- Word/PPT/Excel：优先 ONLYOFFICE，无 ONLYOFFICE 时转 PDF 或下载。
- TXT/MD/代码：平台内文本预览。
- 压缩包：展示文件清单，不默认解压内部文件给学生。

右侧本环节任务区：

- 顶部保留横向环节切换，不占用大块纵向空间。
- 当前环节的题目、任务、作品提交、讨论和反馈必须与左侧资源预览同时出现。
- 例如左侧播放视频或预览 PPT，右侧同屏显示本环节单选题、多选题、填空题、主观题或作品提交入口。
- 不再把“资源学习”和“题目作答”做成两个割裂页面；它们属于同一个课时环节的左右两侧。

环节状态：

- 未开始。
- 当前进行中。
- 已完成。
- 需修改。
- 已关闭。

学生操作：

- 打开资源。
- 播放视频。
- 查看课件。
- 回答题目。
- 保存草稿。
- 提交答案。
- 上传作品。
- 发送未懂反馈。
- 提交学习反思。
- 查看教师反馈。

数据采集：

- 进入课时写入 `lesson_enter`。
- 进入环节写入 `step_enter`。
- 打开资源写入 `resource_view`。
- 视频播放、暂停、完成写入资源行为 metadata。
- 作答提交写入 `answer_submit`。
- 作品提交写入 `task_submit` 或 `project_submit`。
- 未懂反馈写入 `question_ask` 或后续 `confusion_mark`。
- 离开页面时记录停留时长。

## 实时课堂模式

课堂模式由教师端 `ClassroomSession` 和 WebSocket 驱动。

学生端应支持：

- 自动发现当前班级正在进行的课堂。
- 教师开始课堂后，首页和顶部状态条出现“进入课堂”。
- 教师未开始课堂时，学生不能通过课堂入口或直接 URL 进入课堂。
- 教师开启某个环节后，学生端自动切换到对应环节。
- 教师未投放环节时，学生课堂页只显示等待状态，不展示课时资源和题目。
- 默认所有课时都需要课堂教学启用。未创建课堂场次、未开始课堂或未投放环节时，学生不能从普通课时学习入口绕过课堂控制查看资源和题目。
- 课堂启用分层模式时，学生端只接收后端按本人当前层级过滤后的题目，不展示其他层级题目和分值。
- 分层课堂只标注“分层课堂”或“已按层级匹配”，不向学生展示模型解释、其他层级任务或分层后台原因。
- 教师统一打开资源时，学生端打开对应资源预览。
- 教师发起签到，学生端显示签到按钮。
- 教师发起抢答，学生端显示抢答入口。
- 教师发起即时题，学生端显示作答区。
- 教师关闭活动后，学生端不再允许提交。
- 教师广播消息，学生端顶部或侧栏显示。

WebSocket 房间：

```text
class:{class_id}
lesson:{lesson_id}
user:{user_id}
control:{class_id}
```

学生端接收事件：

- `session_started`
- `session_finished`
- `step_opened`
- `step_closed`
- `resource_opened`
- `activity_opened`
- `activity_closed`
- `sign_in_opened`
- `quick_answer_opened`
- `broadcast_sent`
- `control_command`

学生端回执：

- `client_ready`
- `resource_open_ack`
- `step_seen`
- `answer_submitted`
- `task_submitted`
- `sign_in_submitted`
- `confusion_marked`

远程控制边界：

- 只做浏览器内控制。
- 不控制学生电脑系统。
- 不读取学生本地文件。
- 不强行上传学生本地内容。
- 所有控制命令必须可审计。

## 题目作答

第一阶段题型：

- 单选。
- 多选。
- 判断。
- 填空。
- 简答。
- 文件上传题。
- 5 级李克特量表。

交互规则：

- 题目作答区应清晰、稳定。
- 客观题选中后有明确状态。
- 多选题必须提示可多选。
- 填空和简答支持自动保存草稿。
- 文件上传显示文件名、大小、上传状态。
- 提交前进行本地校验。
- 提交后展示“已提交”，如果教师允许修改才显示“修改提交”。
- 教师关闭活动后，学生只能查看结果或反馈。

结果反馈：

- 客观题可在教师允许后显示正确/错误。
- 主观题显示“待批改”“已批改”。
- 课堂即时题可显示班级统计，但不要造成学生公开羞辱。
- 自己的答案、得分和教师反馈必须可查。

## 任务、测试与作品提交

学生任务中心聚合：

- 待完成课堂任务。
- 待完成课后任务。
- 待完成测试。
- 待提交项目作品。
- 待互评项目。
- 需修改的作品。

列表字段：

- 标题。
- 来源课程。
- 课时。
- 教师。
- 截止时间。
- 状态。
- 操作按钮。

状态：

- 未开始。
- 进行中。
- 已提交。
- 待批改。
- 已批改。
- 需修改。
- 已截止。

作品上传规则：

- 限制文件大小和类型。
- 上传完成后显示版本记录。
- 支持再次提交时保留历史版本。
- 教师反馈后，学生可按要求修改并重新提交。
- 作品提交写入学习事件和学习日志。

## 项目式学习

项目式学习不是普通任务列表。

学生项目工作台后续应包含：

- 项目背景和驱动问题。
- 阶段和里程碑。
- 甘特图计划。
- 小组成员和分工。
- 个人项目日志。
- 小组项目日志。
- 阶段成果提交。
- 最终作品提交。
- 自评。
- 互评。
- 教师评价。
- 量规得分。

第一阶段可以先做：

- 项目详情。
- 项目作品提交。
- 自评/互评入口。
- 项目日志占位。

后续再做：

- 甘特图。
- 小组协作。
- 阶段成果。
- 评价量规完整闭环。

项目学习事件：

- `project_enter`
- `project_log_create`
- `project_milestone_update`
- `project_submit`
- `self_evaluation_submit`
- `peer_evaluation_submit`

## 学习档案

学生学习档案面向学生自己，不是教师分析后台。

展示内容：

- 基础信息：姓名、账号、班级、学号。
- 我的课程进度。
- 近期完成事项。
- 学科前测完成情况。
- 测试记录。
- 任务提交记录。
- 项目作品记录。
- 教师反馈。
- 自评互评记录。
- 学习日志。

不展示或弱化：

- AI 模型置信度。
- 全班排名。
- 复杂风险标签。
- 教师内部干预记录。

可以展示：

- 我的学习进度。
- 我的任务完成情况。
- 我的作品修改历史。
- 我的反思记录。
- 教师给我的反馈。

## 公告与留言反馈

公告：

- 只显示学生所在班级可见的已发布公告。
- 置顶公告优先显示。
- 课程内公告和首页公告可共用数据。

留言反馈：

- 学生选择反馈类型：
  - 学习问题。
  - 账号问题。
  - 资源问题。
  - 建议反馈。
  - 其他。
- 学生选择关联教师。
- 默认只能选择任课教师。
- 教师回复后学生端可查看回复。
- 已关闭反馈只读。

## 权限边界

学生只能访问：

- 自己的账号信息。
- 自己所在学校和班级。
- 自己班级已发布课程。
- 自己班级可见公告。
- 自己的前测、作答、提交、学习事件和学习档案。
- 自己参与的小组项目数据。

学生不能访问：

- 其他学生账号。
- 其他班级课程。
- 教师备课备注。
- 教师端资源管理页。
- 管理员数据。
- AI 模型版本、训练任务和分层建议后台数据。

学生端 API 必须从登录用户推导学生身份、学校和班级，不能信任请求体传入的 `student_id`、`school_id` 或 `class_id`。

## API 设计草案

学生端 API 前缀：

```text
/api/v1/student/
```

当前用户状态：

```text
GET /api/v1/student/me/
```

返回：

- 用户信息。
- 学生档案。
- 班级。
- 是否首次使用。
- onboarding 状态。
- 当前是否有正在进行的课堂。

首次使用：

```text
GET /api/v1/student/onboarding/
POST /api/v1/student/onboarding/password/
POST /api/v1/student/onboarding/class/
GET /api/v1/student/onboarding/classes/
```

学科前测：

```text
GET /api/v1/student/pretests/required/
GET /api/v1/student/pretests/:subjectId/
GET /api/v1/student/pretests/papers/:paperId/
POST /api/v1/student/pretests/papers/:paperId/submit/
```

课程：

```text
GET /api/v1/student/courses/
GET /api/v1/student/courses/:courseId/
GET /api/v1/student/courses/:courseId/lessons/
```

课时学习：

```text
GET /api/v1/student/lessons/:lessonId/workspace/
POST /api/v1/student/lessons/:lessonId/enter/
POST /api/v1/student/lesson-steps/:stepId/enter/
POST /api/v1/student/lesson-steps/:stepId/complete/
POST /api/v1/student/lesson-steps/:stepId/answer/
POST /api/v1/student/lesson-steps/:stepId/upload/
POST /api/v1/student/lesson-steps/:stepId/reflection/
```

资源：

```text
GET /api/v1/student/resources/
GET /api/v1/student/resources/:resourceId/
POST /api/v1/student/resources/:resourceId/view/
POST /api/v1/student/resources/:resourceId/progress/
```

实时课堂：

```text
GET /api/v1/student/classroom/current/
GET /api/v1/student/classroom/:sessionId/
POST /api/v1/student/classroom/:sessionId/sign-in/
POST /api/v1/student/classroom/activities/:activityId/submit/
POST /api/v1/student/classroom/activities/:activityId/confusion/
```

任务与测试：

```text
GET /api/v1/student/tasks/
GET /api/v1/student/tasks/:taskId/
POST /api/v1/student/tasks/:taskId/submit/
GET /api/v1/student/tests/
GET /api/v1/student/tests/:testId/
POST /api/v1/student/tests/:testId/submit/
```

项目：

```text
GET /api/v1/student/projects/
GET /api/v1/student/projects/:projectId/
GET /api/v1/student/projects/:projectId/logs/
POST /api/v1/student/projects/:projectId/logs/
POST /api/v1/student/projects/:projectId/submit/
POST /api/v1/student/projects/:projectId/self-evaluation/
POST /api/v1/student/projects/:projectId/peer-evaluation/
```

学习档案：

```text
GET /api/v1/student/profile/
GET /api/v1/student/profile/events/
GET /api/v1/student/profile/submissions/
GET /api/v1/student/profile/logs/
```

公告与反馈：

```text
GET /api/v1/student/notices/
GET /api/v1/student/feedback/
POST /api/v1/student/feedback/
GET /api/v1/student/feedback/:id/
```

## 数据模型扩展建议

已有模型可直接使用：

- `User`
- `StudentProfile`
- `ClassGroup`
- `Subject`
- `Course`
- `CourseClass`
- `Lesson`
- `LessonStep`
- `ClassroomSession`
- `ClassroomActivity`
- `Resource`
- `PretestPaper`
- `PretestQuestion`
- `PretestSubmission`
- `Notice`
- `Feedback`
- `LearningEvent`

建议新增：

### StudentLessonProgress

记录学生课时学习进度。

字段：

- `student`
- `course`
- `lesson`
- `class_group`
- `status`
- `current_step`
- `completed_step_count`
- `total_step_count`
- `started_at`
- `last_seen_at`
- `completed_at`

### StudentStepProgress

记录学生在课时环节上的进度。

字段：

- `student`
- `lesson`
- `step`
- `status`
- `attempt_count`
- `duration_ms`
- `started_at`
- `submitted_at`
- `completed_at`

### LessonStepSubmission

保存学生在环节中的作答或提交。

字段：

- `student`
- `class_group`
- `lesson`
- `step`
- `answers`
- `content`
- `attachment`
- `score`
- `feedback`
- `status`
- `submitted_at`
- `graded_at`

### ClassroomActivitySubmission

保存课堂活动提交。

字段：

- `session`
- `activity`
- `student`
- `class_group`
- `answers`
- `content`
- `attachment`
- `score`
- `status`
- `submitted_at`

### StudentLearningLog

学生学习日志。

字段：

- `student`
- `class_group`
- `course`
- `lesson`
- `step`
- `project`
- `log_type`
- `content`
- `source`
- `related_events`
- `created_at`

### StudentResourceProgress

资源学习进度。

字段：

- `student`
- `resource`
- `course`
- `lesson`
- `step`
- `view_count`
- `duration_ms`
- `progress`
- `last_position`
- `completed_at`

说明：

- 如果不想一开始新增太多表，第一版可以先全部写 `LearningEvent`。
- 当需要展示“继续学习”“资源进度”“环节完成状态”时，再新增进度表。

## 学习行为采集

学生端是行为数据采集的主要来源。必须从第一版开始埋点。

事件建议：

- `login`
- `page_view`
- `course_enter`
- `lesson_enter`
- `step_enter`
- `step_complete`
- `resource_view`
- `resource_progress`
- `resource_complete`
- `answer_submit`
- `answer_update`
- `task_submit`
- `file_upload`
- `project_submit`
- `pretest_submit`
- `sign_in`
- `quick_answer`
- `confusion_mark`
- `chat_message`
- `question_ask`
- `reflection_submit`

每条事件至少包含：

- `actor`
- `class_group`
- `course`
- `lesson`
- `event_type`
- `object_type`
- `object_id`
- `duration_ms`
- `score`
- `metadata`
- `occurred_at`

前端采集策略：

- 页面进入立即记录 `page_view`。
- 课时进入记录 `lesson_enter`。
- 环节切换记录 `step_enter`。
- 离开环节或页面时上报停留时长。
- 资源预览每隔固定时间上报进度，避免只记录打开不记录学习过程。
- 作答、提交、上传、反馈类事件即时上报。
- 网络断开时允许本地短暂缓存，恢复后补发。

## 前端组件建议

学生端不要直接复用后台的 `ManagementPage`。

建议新增：

- `StudentShell`：学生端整体布局。
- `LearningTopBar`：课程、课时、课堂状态条。
- `CurrentClassroomCard`：当前课堂入口。
- `TodoListPanel`：待完成事项。
- `CourseCard`：课程卡片。
- `LessonTimeline`：课时环节流程。
- `ResourceViewer`：资源预览。
- `QuestionBlock`：题目作答。
- `UploadBlock`：作品上传。
- `ReflectionBlock`：学习反思。
- `ClassroomLiveBanner`：课堂实时提醒。
- `SubmissionStatus`：提交状态。
- `StudentNoticeList`：公告。
- `FeedbackForm`：留言反馈。
- `OnboardingStepper`：首次使用步骤。
- `PretestRunner`：前测答题器。

可复用后台组件：

- `NoticeLine`
- `StatusBadge`
- API client
- 认证 store

不建议复用：

- `AppShell` 侧边栏后台布局。
- `ManagementPage` 表格页。
- 批量选择和批量删除 hooks。

## 私有化与离线约束

学生端必须离线可运行：

- 不使用 CDN。
- 不加载公网字体。
- 不调用外部图片。
- PDF.js、图标、预览组件都应打包到本地。
- ONLYOFFICE 是可选增强，不是学生端必需条件。
- 无 ONLYOFFICE 时，Office 文档通过转 PDF、文本预览或下载兜底。
- 视频、音频、图片走本地媒体文件。
- AI 学习单如果依赖教师 DeepSeek Key，无 Key 或无外网时不影响普通学习过程。

## 开发顺序

### 阶段 A：学生端骨架

1. 新增 `StudentShell`。
2. 新增学生路由。
3. 新增 `/api/v1/student/me/`。
4. 实现 `/student` 首页第一版。
5. 实现学生端登录后跳转和首次使用拦截。

### 阶段 B：首次使用和学科前测

1. 实现改密。
2. 实现选班级。
3. 实现前测必做检查。
4. 实现素养测试和学习态度问卷作答。
5. 提交后写入 `PretestSubmission` 和 `LearningEvent`。

### 阶段 C：课程与课时学习

1. 实现我的课程。
2. 实现课程详情。
3. 实现课时工作台。
4. 读取 `LessonStep`。
5. 显示资源名称、活动名称和学生说明。
6. 写入 `lesson_enter`、`step_enter`、`resource_view`。

### 阶段 D：资源预览

1. 图片、视频、音频原生预览。
2. PDF.js 内置预览。
3. 文本和 Markdown 安全预览。
4. Office 文档接 ONLYOFFICE 或转 PDF 后备。
5. 压缩包文件清单预览。

### 阶段 E：课堂同步

1. 学生端当前课堂 API。
2. WebSocket 接入班级房间。
3. 接收教师开启/关闭活动。
4. 签到、抢答、即时题第一版。
5. 学生提交后教师端可看到状态。

### 阶段 F：任务、测试、项目和档案

1. 任务中心。
2. 测试作答。
3. 作品上传。
4. 项目提交、自评互评。
5. 学习档案。
6. 留言反馈。

## 与教师端同步开发清单

教师端完成以下功能时，学生端必须同时有对应能力：

| 教师端 | 学生端 |
| --- | --- |
| 创建课程并绑定班级 | 学生课程列表可见 |
| 上传课程封面 | 学生课程卡片显示封面 |
| 创建课时 | 学生课程详情显示课时 |
| 创建课时环节 | 学生课时工作台显示环节 |
| 上传资源并加入环节 | 学生资源预览或下载 |
| 创建课堂场次 | 学生首页显示当前课堂 |
| 开始课堂 | 学生进入课堂模式 |
| 开启活动 | 学生端显示作答/签到/提交 |
| 关闭活动 | 学生端停止提交 |
| 发布公告 | 学生端公告可见 |
| 回复留言 | 学生端可查看回复 |
| 批改提交 | 学生端可查看反馈 |

这个同步清单后续应作为开发验收标准。

## 第一版验收标准

学生端第一版做到：

- 学生登录后进入学生首页，不再显示“工作台建设中”。
- 首次使用学生必须改密、选班并完成学科前测。
- 学生能看到自己班级已发布课程。
- 学生能进入课程详情和课时学习工作台。
- 课时学习工作台能显示课时环节、学生说明、资源和活动占位。
- 学生进入课时、切换环节、查看资源会写入学习事件。
- 学生能看到教师发布给本班的公告。
- 学生能向任课教师提交留言反馈。
- 页面风格与管理员/教师后台区分明显，更适合课堂学习。

## 当前开发进度

2026-07-04 已完成第一批学生端开发：

- Vue 路由已接入 `/student`、首次使用、学科前测、课程、课程详情、课时学习、课堂入口、公告和留言反馈。
- 学生端使用独立 `StudentShell`，不复用管理员/教师后台侧边栏。
- 课时学习工作台采用左侧资源预览、右侧本环节任务的结构。一个环节可以同时包含视频、PPT、PDF、题目、任务和提交入口，学生不需要在资源页和作答页之间来回跳。
- 进入课时、进入环节、提交作答、标记完成已接入学生端学习行为 API。
- 前测学生端序列化不返回标准答案，避免学生通过接口看到答案。
- 后端已限制直接访问课时和环节：若课程所属学科前测未完成，API 返回 403。
- 任务、项目、学习档案暂为学生端样式占位页，后续接提交、日志、互评和档案数据。
