# 教师课时设计与课堂管理重构方案

## 核心结论

教师端后续要围绕“课时学习过程”重构。

一节课不是一个简单 `Lesson.content`，也不是一堆独立课堂活动，而是由多个学习片段组成：

```text
课程
  -> 课时
      -> 学习片段
          -> 资源 / 课件 / 视频 / 协作文档
          -> 题目 / 讨论 / 任务 / 作品上传
          -> 学生作答与行为数据
```

同一份课时学习过程服务四个场景：

```text
教师备课：制作片段、上传资源、配置题目、生成任务单。
学生学习：按片段浏览资源、完成活动、提交作品。
课堂授课：教师控制片段开启、收题、查看完成状态。
课后复盘：查看学习行为、提交质量、评价和分层建议。
```

因此后续不再把“课堂活动”做成主界面的后台列表。课堂活动只是课时学习过程在某次课堂中的运行状态。

课程教学模式需要影响备课入口：

- 任务驱动学习：以课时学习过程为核心，围绕每节课的资源、题目、实践任务、作品提交和即时反馈组织。
- 项目式学习：以项目工作流为核心，围绕项目背景、驱动问题、阶段任务、里程碑、甘特图、小组协作、项目日志和量规评价组织。
- 两种模式共用资源、题库、提交、评价和 `LearningEvent`，但教师看到的设计器和学生看到的学习路径应不同。
- 两种模式都必须产出班级学习日志和学生学习日志，作为过程性评价和 AI 分层特征的数据来源。

## 导航调整

教师端建议调整为：

```text
教师首页
课程备课
课堂教学
学生管理
任务批改
题库资源
协作文档
分层调节
公告通知
留言反馈
```

说明：

- `课程备课`：管理课程、课时、学习片段、资源绑定、题目和任务单。
- `课堂教学`：选择班级和课时，运行已备好的学习过程。
- `协作文档`：接入 ONLYOFFICE，用于教案、课件、任务单、小组文档和学生作品协作。
- `题库资源`：个人题库和资源库，供课时片段引用。

## 课程备课

### 页面目标

教师备课的重点是快速制作学生能看到的一节课，而不是填写一张后台表。

课程备课页分为三级：

```text
课程列表
  -> 课程详情
      -> 课时设计
```

### 课程列表

保留当前第一版课程管理能力：

- 新增课程。
- 编辑课程。
- 发布 / 停用。
- 绑定任教班级。
- 管理课时。

但“课时”入口应改为“设计课时”，进入课时设计。

### 课时设计布局

建议使用三栏布局：

```text
左侧：课程与课时目录
中间：学习片段编辑区
右侧：资源库 / 题库 / AI 助手 / 属性设置 / 学生预览
```

左侧：

- 当前课程。
- 课时列表。
- 当前课时下的片段目录。
- 支持新增课时、新增片段、片段拖拽排序。

中间：

- 当前片段编辑。
- 学生可见说明。
- 教师备课备注。
- 资源和活动的组合。
- 题目、任务、讨论、作品上传配置。

右侧：

- 资源库：上传或选择资源。
- 题库：选择个人题或公共题。
- ONLYOFFICE：创建或选择协作文档。
- AI 助手：生成任务单、问题、评价量规。
- 属性设置：必做、时长、目标层级、发布状态。
- 学生预览：查看学生实际看到的效果。

## 学习片段类型

建议第一阶段支持这些片段类型：

| 类型 | 用途 |
| --- | --- |
| 导入 | 情境、问题、图片、短视频 |
| 资源学习 | PPT、Word、PDF、视频、网页任务单 |
| 课堂题 | 单选、多选、判断、填空、主观题 |
| 任务实践 | 任务说明、素材包、作品上传 |
| 讨论反馈 | 讨论区、提问、未懂反馈 |
| 展示评价 | 自评、互评、教师评价、量规 |
| 小结反思 | 反思题、出口卡、学习记录 |
| AI 学习单 | AI 生成的结构化网页任务单 |
| 协作文档 | ONLYOFFICE 文档、表格、演示 |

每个片段公共字段：

- 片段标题。
- 片段类型。
- 学生可见说明。
- 教师备注。
- 排序。
- 是否必做。
- 预计时长。
- 目标层级：全体 / A / B / C。
- 环节不再向教师暴露“草稿 / 已配置”状态。一个环节只要保存，就属于当前课时学习过程；是否让学生看到，由课程、课时发布状态和课堂投放状态决定。

## 资源与文档

### 普通资源

资源包括：

- 图片。
- 视频。
- 音频。
- PDF。
- Word。
- PPT。
- Excel。
- 压缩包。
- 文本 / 代码。

后续资源模型需要扩展：

- 文件类型。
- 原始文件名。
- 文件大小。
- MIME。
- SHA256。
- 预览状态。
- 所属学科。
- 可见范围。

### ONLYOFFICE 文档

ONLYOFFICE 用于更完整的 Office 文档预览、编辑和协作。

适合场景：

- 教师协同备课教案。
- 教师共同编辑课件。
- AI 生成任务单后转成文档继续编辑。
- 小组协作文档。
- 学生个人作品文档。
- 教师批注学生作品。

STRATA 管账号和权限，ONLYOFFICE 只负责文档编辑。

文档打开时由 Django 生成配置：

```text
document.url
document.key
document.permissions
editorConfig.user.id
editorConfig.user.name
editorConfig.callbackUrl
```

协作规则：

- 同一份文档：同一个 `document.key`。
- 不同用户：不同 `editorConfig.user.id`。
- 小组协作：每个小组一份文档副本，一个 key。
- 个人作业：每个学生一份文档副本，一个 key。
- 新版本或复制文档：生成新 key。

### 文档权限

教师备课文档：

- 创建教师可编辑。
- 协作教师可编辑或评论。
- 学生默认不可见。

课时资源文档：

- 教师可编辑。
- 学生可只读查看。
- 是否允许下载、打印由教师设置。

学生作品文档：

- 学生本人或小组成员可编辑。
- 教师可查看、评论、批注。
- 其他学生是否可见由课堂活动设置。

## AI 学习单

AI 生成网页学习单不能直接发布任意 HTML/JS。

平台采用结构化 DSL：

```json
{
  "title": "数据可视化任务单",
  "blocks": [
    {"type": "markdown", "content": "阅读材料并完成任务。"},
    {"type": "single_choice", "id": "q1", "stem": "下列哪项属于数据清洗？", "options": []},
    {"type": "textarea", "id": "q2", "label": "写出你的分析过程"},
    {"type": "file_upload", "id": "work", "label": "上传作品"}
  ]
}
```

教师流程：

```text
输入教学目标 / 素材 / 学生层级
  -> AI 生成学习单草稿
  -> 后端校验 DSL
  -> Vue 白名单组件预览
  -> 教师修改确认
  -> 发布到课时片段
```

禁止：

- 任意 `<script>`。
- 任意 iframe 外链。
- 任意远程资源。
- 任意提交到外站。
- 任意读取 Cookie、本地存储。

## 课堂教学

### 页面目标

课堂教学不是备课页，也不是活动管理表。

课堂教学是把已备好的课时学习过程在某个班级中运行起来。

### 课堂入口

入口包括：

- 教师首页“进入课堂”。
- 课程备课页“进入课堂”。
- 课时设计“预设课堂”。

进入课堂前选择：

- 课程。
- 课时。
- 班级。
- 是否使用已有课堂场次。

### 课堂控制台布局

建议布局：

```text
顶部：课程 / 课时 / 班级 / 状态 / 计时器 / 开始或结束课堂
左侧：课时片段流程
中间：当前片段控制与预览
右侧：学生状态 / 提交情况 / 消息反馈
底部：课堂工具条
```

左侧片段流程：

- 展示已备好的所有片段。
- 显示片段状态：未开启、进行中、已关闭。
- 支持开启当前片段、关闭片段、切换下一片段。

中间当前片段：

- 展示资源或活动内容。
- 支持投放到学生端。
- 支持收题、锁定、解锁。
- 支持广播资源。

右侧学生状态：

- 在线 / 离线。
- 当前片段进入状态。
- 已完成 / 未完成。
- 提交数量。
- 未懂反馈。
- 提问消息。

底部工具：

- 签到。
- 随机点名。
- 抢答。
- 倒计时。
- 课堂广播。
- 统一打开资源。
- 锁定提交。
- 收回答案。

## 学生学习页

学生学习页使用同一份课时学习过程，但是浏览和作答模式。

布局可以采用：

```text
左侧：资源预览
右侧：本环节任务、题目、任务、提交入口
```

学生端的主要区域不再把“片段流程”作为右侧主体。环节切换可以放在顶部横条或轻量导航中，右侧主体必须服务当前环节作答和提交；左侧资源与右侧任务同时出现。

学生端行为必须写入 `LearningEvent`：

- 进入课时。
- 进入片段。
- 打开资源。
- 资源停留时长。
- 答题。
- 修改答案。
- 提交任务。
- 上传作品。
- 打开协作文档。
- 保存协作文档。
- 提问和反馈。

同时要沉淀学习日志：

- 学生学习日志：按学生记录进入片段、任务实践、作品保存、作品提交、反思、教师反馈和自我修正。
- 班级学习日志：按班级记录课堂运行、片段开启关闭、共性问题、教师干预、完成率变化和课后复盘。
- 学习日志可以由系统根据 `LearningEvent` 自动生成，也允许教师补充备注；不能只依赖学生手写。
- 任务驱动学习的日志重点是课时任务完成过程。
- 项目式学习的日志重点是项目阶段推进、协作贡献、里程碑完成和成果迭代。

## 数据模型规划

保留现有模型：

- `Course`
- `CourseClass`
- `Lesson`
- `ClassroomSession`
- `ClassroomActivity`
- `Resource`
- `LearningEvent`

新增模型建议：

### StudentLearningLog

学生学习日志。它不是原始点击流水，而是面向教师复盘、学生反思和 AI 特征聚合的结构化过程记录。

字段：

- `student`
- `class_group`
- `course`
- `lesson`
- `lesson_step`
- `project`
- `log_type`
- `content`
- `source`：系统生成 / 学生填写 / 教师补充。
- `event_refs`
- `created_at`

### ClassLearningLog

班级学习日志。用于记录某个班级在一节课、一个任务或一个项目阶段中的整体过程。

字段：

- `class_group`
- `course`
- `lesson`
- `classroom_session`
- `project`
- `log_type`
- `summary`
- `metrics`
- `teacher_note`
- `created_by`
- `created_at`

### LessonStep

课时学习片段。

字段：

- `lesson`
- `title`
- `step_type`
- `student_instruction`
- `teacher_note`
- `sort_order`
- `is_required`
- `estimated_minutes`
- `target_layer`
- `status`
- `created_by`

### LessonStepResource

片段绑定资源。

字段：

- `step`
- `resource`
- `sort_order`
- `display_mode`

### LessonStepQuestion

片段内题目。第一阶段可先独立存，后续再接统一题库。

字段：

- `step`
- `question_type`
- `stem`
- `options`
- `answer`
- `score`
- `analysis`
- `sort_order`

### LessonStepSubmission

学生片段作答或任务提交。

字段：

- `step`
- `student`
- `class_group`
- `answers`
- `attachment`
- `score`
- `status`
- `submitted_at`
- `graded_at`

### DocumentAsset

ONLYOFFICE 文档资产。

字段：

- `school`
- `owner`
- `title`
- `file_type`
- `current_version`
- `document_key`
- `permission_scope`
- `created_at`
- `updated_at`

### DocumentVersion

文档版本。

字段：

- `asset`
- `version`
- `file`
- `sha256`
- `size`
- `saved_by`
- `saved_at`

### DocumentPermission

文档权限。

字段：

- `asset`
- `user`
- `class_group`
- `permission`
- `can_edit`
- `can_comment`
- `can_download`
- `can_print`

### AIWorksheet

AI 生成学习单。

字段：

- `teacher`
- `lesson`
- `step`
- `title`
- `prompt`
- `schema_json`
- `status`
- `published_at`

## 课堂模型调整

现有 `ClassroomSession` 保留，表示某次课堂。

后续扩展：

- `lesson` 必选。
- `class_group` 必选。
- 记录当前片段。

现有 `ClassroomActivity` 不再作为独立内容来源，而是表示某个片段在课堂中的运行状态。

建议增加：

- `lesson_step`
- `started_by`
- `metadata`

后续也可以拆为 `ClassroomStepRun`：

```text
ClassroomSession
  -> ClassroomStepRun
      -> step
      -> status
      -> opened_at
      -> closed_at
```

这样比把所有课堂片段都塞进 `ClassroomActivity` 更清晰。

## API 规划

课时设计：

```text
GET  /api/v1/teacher/courses/{course_id}/lesson-workspace/
GET  /api/v1/teacher/lessons/{lesson_id}/workspace/
POST /api/v1/teacher/lessons/{lesson_id}/steps/
PATCH /api/v1/teacher/lesson-steps/{step_id}/
DELETE /api/v1/teacher/lesson-steps/{step_id}/
POST /api/v1/teacher/lesson-steps/{step_id}/resources/
DELETE /api/v1/teacher/lesson-step-resources/{id}/
POST /api/v1/teacher/lesson-steps/{step_id}/questions/
PATCH /api/v1/teacher/lesson-step-questions/{id}/
DELETE /api/v1/teacher/lesson-step-questions/{id}/
POST /api/v1/teacher/lesson-steps/reorder/
POST /api/v1/teacher/lessons/{lesson_id}/publish/
```

ONLYOFFICE：

```text
GET  /api/v1/teacher/documents/
POST /api/v1/teacher/documents/
GET  /api/v1/teacher/documents/{id}/editor-config/
GET  /api/v1/documents/{id}/download/
POST /api/v1/documents/{id}/callback/
POST /api/v1/teacher/documents/{id}/copy/
POST /api/v1/teacher/documents/{id}/permissions/
```

课堂教学：

```text
GET  /api/v1/teacher/classroom/sessions/
POST /api/v1/teacher/classroom/sessions/
GET  /api/v1/teacher/classroom/sessions/{id}/console/
POST /api/v1/teacher/classroom/sessions/{id}/start/
POST /api/v1/teacher/classroom/sessions/{id}/finish/
POST /api/v1/teacher/classroom/sessions/{id}/steps/{step_id}/open/
POST /api/v1/teacher/classroom/sessions/{id}/steps/{step_id}/close/
GET  /api/v1/teacher/classroom/sessions/{id}/students/
GET  /api/v1/teacher/classroom/sessions/{id}/submissions/
POST /api/v1/teacher/classroom/sessions/{id}/broadcast/
```

## 前端页面规划

### 课程备课列表

路径：

```text
/teacher/courses
```

保留课程 CRUD。

新增动作：

- `设计课时`
- `进入课堂`
- `学生预览`

### 课时设计

路径：

```text
/teacher/lessons/:lessonId/design
```

核心区域：

- 课时片段目录。
- 当前片段编辑器。
- 资源和题目侧栏。
- 学生预览抽屉。

### 课堂控制台

路径：

```text
/teacher/classroom/:sessionId
```

核心区域：

- 课堂状态条。
- 片段流程控制。
- 当前片段投放。
- 学生实时状态。
- 课堂工具条。

### 协作文档

路径：

```text
/teacher/documents
/teacher/documents/:documentId
```

用途：

- 管理本人文档。
- 发起协同备课。
- 创建小组协作文档。
- 查看保存版本。

## 第一阶段开发顺序

建议不要直接重做大课堂页面，先做课时学习过程底座。

1. 新增 `LessonStep`、`LessonStepResource`、`LessonStepQuestion`。
2. 实现 `/teacher/lessons/:lessonId/design` 课时设计第一版。
3. 资源先只支持上传和绑定，不先做复杂预览。
4. 接入 ONLYOFFICE `DocumentAsset`，支持教师创建和打开文档。
5. 在片段中绑定 ONLYOFFICE 文档。
6. 做学生预览模式。
7. 再重构课堂控制台，让课堂运行已设计好的片段。
8. 最后接 WebSocket、学生实时作答和行为采集。

## 当前第一版如何处理

当前已经实现的：

- `/teacher/courses`
- `/teacher/classroom`
- `ClassroomSession`
- `ClassroomActivity`
- `LessonStep` 第一版模型
- `/teacher/lessons/:lessonId/design` 课时设计第一版
- 前端骨架页 `/teacher/classroom/:sessionId`
- 前端骨架页 `/teacher/documents`

先保留，不急着删除。

后续调整：

- `/teacher/courses` 已增加“课时设计”方向入口，具体课时可进入课时设计页。
- `/teacher/classroom` 先保留为课堂记录列表，列表中可进入课堂控制台骨架。
- `/teacher/classroom/:sessionId` 作为真正课堂控制台方向，当前只做静态结构演示。
- `/teacher/documents` 作为 ONLYOFFICE 协作文档工作区方向，当前只做静态结构演示。
- 旧 `ClassroomActivity` 后续逐步降级为兼容层或迁移到 `ClassroomStepRun`。

当前第一版边界：

- 已新增正式 `LessonStep` 数据库模型。
- 已实现课时环节 CRUD 和排序。
- 资源、题目、文档和活动暂以名称数组保存，后续再接真实资源库、题库、ONLYOFFICE 文档和任务提交模型。
- 不接真实资源预览、学生提交和 WebSocket。
- AI 只保存生成目标，不直接调用模型生成或发布学习单。

## 2026-07-04 修正版状态

前一版的主要问题是资源、课时、课堂和学生端没有闭合：

- `/teacher/documents` 是静态演示数据。
- `/teacher/classroom/:sessionId` 是静态演示数据。
- `LessonStep.resource_items` 只保存资源名称字符串。
- 学生端只能看到资源名称，拿不到真实资源 URL 和资源 ID。
- PPT、Word、Excel 因此无法进入 ONLYOFFICE 预览或编辑。

现在主线调整为：

```text
教师上传真实资源
  -> 课时设计中从资源库加入资源
  -> LessonStep.resource_items 保存资源对象
  -> 教师课堂控制台读取真实课时环节
  -> 学生课时页读取同一份环节和资源
  -> Office 文档走 ONLYOFFICE，PDF/图片/视频走本地预览
```

已经落地：

- `/teacher/documents` 改为真实教师资源库 Office 工作区。
- 教师可对本人上传的 Word、PPT、Excel 资源使用 ONLYOFFICE 编辑。
- `/teacher/resources` 增加网页内嵌预览区，图片、视频、音频、PDF 和 Office 资源都在当前页面预览，Office 文件可进入文档工作区。
- `/teacher/lessons/:lessonId/design` 从资源库加入资源时保存 `id/title/attachment_url/attachment_name/file_ext`。
- `/teacher/lessons/:lessonId/design` 右侧预览页签可直接查看当前环节资源，备课时不用离开课时设计器。
- `/teacher/classroom/:sessionId` 改为读取真实课堂、课时环节和资源。
- `/student/lessons/:lessonId/workspace` 改为读取资源对象；学生在课时页面左侧直接预览资源，Office 文件只读预览。

仍需继续：

- 新增 `LessonStepResource` 正式绑定表，替代 JSON。
- 新增课堂投放状态，例如 `ClassroomStepRun`，记录教师当前开启的环节。
- 接 WebSocket，让学生端自动切换教师投放的环节和资源。
- 资源打开、Office 预览、视频进度、PDF 停留时长写入更细学习事件。
- ONLYOFFICE 回调加入签名、版本表和权限审计。
- 无 ONLYOFFICE 时接 LibreOffice 转 PDF 和 PDF.js 离线预览。

## 2026-07-04 教师端界面重整结论

这次确认教师端必须按“备课”和“上课”分清职责。

### 职责边界

```text
课程备课 / 课时设计
  -> 制作课时学习过程
  -> 上传和绑定资源
  -> 配置题目、任务、作品提交入口
  -> 写学生说明和教师备注
  -> 做学生视图大屏预览

课堂教学 / 课堂控制台
  -> 选择课程、课时、班级创建课堂场次
  -> 开始 / 结束课堂
  -> 投放当前环节
  -> 锁定提交、收题、关闭环节
  -> 查看在线、完成、提问和提交状态
```

备课页不能承担课堂运行控制，否则教师会分不清“我是在设计课，还是正在上课”。课堂控制台也不能重新创建一套独立内容，否则会和课时学习过程重复。

### 课时设计页调整

- 左侧只放课时学习过程目录，不再放大块课程信息卡。
- 中间按主次拆开：上方是当前环节内容和“保存当前环节”，下方是名称、类型、时长、层级、日志和 AI 目标等环节设置。
- 右侧只放备课工具：资源、题目、协作文档、AI。
- 学生预览和 Office/PPT 预览改为独立大屏弹层。
- 环节级“草稿 / 已配置”不再出现在教师界面。
- 保存环节时仍向后端写入兼容字段 `status=ready`，但它只是旧接口兼容，不作为教师操作概念。
- “保存内容”和“保存环节”合并为“保存当前环节”。这个动作一次性保存环节设置、资源、题目、活动和 AI 目标，避免教师误以为有两个不同保存范围。

### 课堂题第一版

课堂题先落在 `LessonStep.question_items` JSON 字段中，跑通师生闭环后再升级为正式 `LessonStepQuestion` 表。

支持题型：

- 单选。
- 多选。
- 判断。
- 填空。
- 简答。

教师端保存内容：

- 题型。
- 题干。
- 选项。
- 参考答案。
- 分值。
- 是否必答。
- 解析 / 评分说明。
- 排序。

学生端只读取：

- 题型。
- 题干。
- 选项。
- 分值。
- 是否必答。

学生端不返回参考答案和解析。学生提交后走 `student/lesson-steps/{id}/answer/`，第一版写入 `LearningEvent.answer_submit`。后续再新增 `LessonStepSubmission`，用于保存每道题作答、自动判分、教师批阅和课堂统计。

### 课堂教学页调整

课堂控制台读取课时学习过程，并显示课堂运行态：

- 当前环节。
- 待投放环节。
- 当前资源预览。
- 投放、锁定提交、结束当前环节。

第一版暂不新增完整 `ClassroomStepRun` 表，先把当前投放状态落在 `ClassroomSession`：

- `current_step`
- `current_step_status`: `idle` / `open` / `locked` / `closed`
- `submission_locked`
- `current_step_started_at`
- `current_step_closed_at`

课堂控制台已接入真实动作：开始课堂、投放当前环节、锁定提交、关闭环节、结束课堂。后续接 WebSocket 时，学生端订阅这些课堂运行态即可。注意不要把运行态写回 `LessonStep.status`，`LessonStep` 仍只表示备课内容结构。

### 后续模型方向

建议新增：

```text
ClassroomStepRun
  -> classroom_session
  -> lesson_step
  -> status: pending / open / locked / closed
  -> opened_at
  -> locked_at
  -> closed_at
  -> opened_by
```

这样同一个课时可以在不同班级、不同日期多次上课，而每次课堂的投放状态互不影响。

## 2026-07-05 课时设计与分层课堂修正版

当前课时设计页以“三栏备课工作台”为准：

```text
左侧：学习过程
  - 显示当前课时环节
  - 新增环节、编辑环节均通过弹窗完成
  - 环节顺序在主页面用上移 / 下移调整

中间：当前环节内容
  - 上方显示资源顺序
  - 下方显示题目顺序
  - 资源和题目都可以独立上移 / 下移
  - 这里是学生端当前环节实际会看到的内容编排

右侧：资源库 / 题库 / 文档 / AI
  - 上传资源按钮打开上传弹窗
  - 新增课堂题按钮打开题目编辑弹窗
  - 下方列表用于把资源或题目加入当前环节
```

不再把环节名称、时长、层级、备注等设置长期铺在主页面中。环节基础信息放入“编辑环节”弹窗；高级设置放入“高级设置”弹窗。主页面必须优先服务资源、课件、视频、题目和任务的编排。

右侧题库第一版不是独立题库表，而是“本课时题库”：

- 汇总当前课时所有环节已有题目。
- 当前环节题目可直接编辑。
- 其他环节题目可复制加入当前环节。
- 后续再升级为教师个人题库和学校公共题库。

### 分层课堂

课堂是否分层由 `ClassroomSession.is_layered` 控制：

- 普通课堂：学生端显示当前投放环节的全部题目。
- 分层课堂：学生端按 `StudentProfile.current_layer` 过滤题目。

题目级分层字段暂存于 `LessonStep.question_items`：

```json
{
  "target_layer": "A/B",
  "use_layer_scores": true,
  "layer_scores": {"A": 3, "B": 2, "C": 1}
}
```

规则：

- `target_layer=all` 对所有学生可见。
- `target_layer=A`、`B`、`C` 只对单一层级学生可见。
- `target_layer=A/B` 同时对 A、B 层学生可见，适合核心题加拓展要求。
- `target_layer=B/C` 同时对 B、C 层学生可见，适合基础巩固和支架题。
- `target_layer=A/B/C` 等价于全体分层记录，主要用于需要保留分层分值的全体题。
- 默认不提供 `A/C` 这种跨层组合，避免跳过 B 层导致教学目标解释困难；确有需要时后续再做自定义层级组合。
- `use_layer_scores=true` 时，学生端返回的 `score` 是该学生层级对应分值。
- 教师端始终看到完整题目和完整分值设置。
- 学生端不展示其他层级题目、其他层级分值或 AI 分层解释。

### 分层分值与 AI 训练

分层分值不应一开始由系统强行决定。建议第一版采用安全默认：

- 题目基础分 `score` 按题型给初始值：选择/判断默认 2 分，填空默认 3 分，简答默认 5 分。
- 开启 `use_layer_scores` 时，系统先按 `target_layer` 给 A/B/C 建议分值：A 层或 A/B 题可略高，C 层或 B/C 题可略低；无法判断时三层都等于基础分。
- 教师可以手动修改 A、B、C 分值。
- 后续 AI 可以给“建议分值”，但必须由教师确认后写入题目。
- AI 生成分层专属题时，返回的是题目草稿和分值建议；教师可以直接加入、逐题编辑后加入，或丢弃。

分层分值在 AI 训练中的定位：

- `target_layer`、`use_layer_scores`、`layer_scores` 是题目设计上下文和特征，不直接作为核心 label。
- 学生在分层题上的作答结果、达成率、耗时、重试、放弃、教师讲评和后续表现可以作为训练特征。
- 训练时应保存学生作答时的层级快照、题目层级配置快照和该层级满分，避免后续教师改题导致历史数据解释错误。
- 模型分层的核心 label 应优先使用“教师最终确认的层级”或“教师采纳/拒绝 AI 建议后的结果”，而不是题目分值本身。
- 分值可以参与生成 `future_performance_label`、达成率特征和难度适配特征，但不能让模型简单学习“老师给 A 高分所以学生应是 A”这种泄漏关系。

### AI 生成分层专属题

教师端“题目”工具中提供 `AI 生成分层题`：

1. 教师先在 `AI 接入` 中填写并启用自己的 DeepSeek API Key。
2. 在课时设计器中填写出题方向、题型、适用层级、数量和补充要求。
3. 后端调用教师自己的 DeepSeek 接口，要求返回平台定义的 JSON 题目结构。
4. 后端清洗题型、选项、答案、层级和分值，丢弃不合格题目。
5. 前端只展示草稿，教师确认后才加入当前环节。

支持的层级目标：

- `A`：拓展题。
- `B`：核心题。
- `C`：支架题。
- `A/B`：核心加拓展。
- `B/C`：基础巩固和支架。
- `A/B/C`：全体可见，但保留分层分值记录。

AI 生成题目不能绕过教师确认，也不能直接写入学生端。没有外网、没有 Key 或 Key 不可用时，只禁用 AI 生成按钮对应能力，不影响手动出题、资源预览和课堂教学。
