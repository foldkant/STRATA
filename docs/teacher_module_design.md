# 教师端功能与界面设计

## 定位

教师端是日常教学工作台，不是学校运营后台。

教师负责：

- 管理自己任教班级可见的课程、课时、资源和任务。
- 组织课堂活动、签到、即时问答和作答。
- 批改测试、项目和课堂任务。
- 查看本班学生学习档案、行为数据和分层建议。
- 查询任教班级学生账号，并将学生密码重置为课堂默认密码 `123456`。
- 对 AI 分层建议进行确认、拒绝或人工调整。
- 维护个人题库，并按权限提交公共题。

教师不负责：

- 创建学校、学校管理员、教师和学生账号。
- 管理班级基础档案和任课关系。
- 发布学校级前测。
- 管理跨校数据采集。
- 修改全局模型训练策略。
- 编辑学生姓名、学号、班级、状态、分层等基础档案。
- 删除、停用或批量导入学生账号。

## 权限边界

教师所有数据必须限制在：

- 自己创建的课程、资源、题目、任务。
- 学校管理员分配给自己的任教班级。
- 任教班级内学生的学习数据。

查询边界：

- `request.user.role = teacher`
- `course.teacher_id = request.user.id`
- `class_group.teaching_assignments.teacher_id = request.user.id`
- 学生档案只能来自教师任教班级。
- 学习事件只能来自教师任教班级、自己课程或自己课时。
- 学生账号查询和密码重置只能作用于教师任教班级学生。
- 教师只能将学生密码重置为固定课堂默认密码 `123456`，不能自定义学生密码。

教师不能通过 URL 参数访问其他教师课程或非任教班级数据。

## 信息架构

教师端建议使用统一左侧导航：

```text
教师首页
我的课程
课堂教学
任务与测试
项目评价
学生档案
题库资源
分层建议
消息公告
```

第一阶段路由：

```text
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
```

## 1. 教师首页

教师首页是工作台，不做夸张大屏。  
它应显示今天要处理什么、哪些班级有风险、哪些任务需要批改。

指标：

- 任教班级数。
- 我的课程数。
- 今日课堂活动数。
- 待批改任务数。
- 待确认分层建议数。
- 近 7 天活跃学生数。

图表：

- 近 7 天任教班级学习事件趋势。
- 任教班级活跃度对比。
- 待批改任务类型分布。
- 分层建议状态：待确认、已采纳、已拒绝。

列表：

- 今日课堂：课程、班级、课时、进入课堂按钮。
- 待处理：未批改测试、未批改项目、未确认分层、低参与学生。
- 最近动态：学生提交、提问、互评、自评、系统预警。

页面动作：

- 进入课堂。
- 新建课程。
- 批改任务。
- 查看分层建议。

## 2. 我的课程

旧 WWW 对应：

- `teacher/course.php`
- `teacher/add-course.php`
- `teacher/project-course-info.php`
- `teacher/task-course-info.php`
- `teacher/add-lesson.php`
- `teacher/edit-lesson.php`

新版课程是教师组织教学内容的主入口。

最新调整详见 `docs/teacher_lesson_classroom_redesign.md` 和 `docs/lesson_workspace_ai_design.md`。后续不应继续把“课堂活动”做成独立后台列表，而应重构为“课时学习过程”：教师在课时设计中按片段制作资源、课件、题目、任务、协作文档和 AI 学习单；学生按同一份学习过程学习；课堂教学负责运行和控制这份学习过程。

字段：

- 课程名称。
- 所属学科。
- 教学模式：项目式学习、任务驱动学习。
- 封面。
- 课程简介。
- 状态：草稿、已发布、停用。
- 课时数。
- 关联班级数。
- 最近更新时间。

教学模式设计：

当前代码中 `pbl` 和 `tbl` 已作为课程字段保存，但第一版还没有在课时、任务和项目流程上真正分化。后续设计原则是“底层能力统一，教学组织方式分化”。

- 任务驱动学习：适合常规课时教学，以“课时 -> 学习片段 -> 任务实践 -> 提交反馈”为主线。
- 项目式学习：适合跨课时、跨周期综合项目，以“项目 -> 阶段 -> 里程碑 -> 小组协作 -> 成果迭代 -> 量规评价”为主线。
- 两种模式都必须写入学习行为事件和学习日志，不能只记录最终成绩或最终作品。
- 新增课程时，教学模式不应只是下拉框，后续应改成带说明的模式卡片，让教师明确选择后的备课结构差异。

功能：

- 新增课程。
- 编辑课程。
- 发布、停用。
- 删除草稿课程。
- 管理课程课时。
- 为课程绑定任教班级。

规则：

- 教师只能管理自己创建的课程。
- 课程所属学科必须来自本校启用学科。
- 学生进入课程前，如果课程绑定学科，必须完成该学科当前发布的素养测试和态度问卷。
- 课程发布前至少需要设置学科、绑定 1 个任教班级并创建 1 个课时。
- 已发布课程不能直接删除，必须先停用。
- 已有学习事件或课堂记录的课程不能物理删除，只能停用保留。
- 公有课/私有课后续在课程字段中扩展：
  - 私有课：仅创建教师可编辑。
  - 公有课：学校审核后本校教师可复制引用。

当前第一版已实现：

- `/teacher/courses` 课程列表、查询、学科筛选和状态筛选。
- 课程新增、编辑、发布、停用、删除。
- 课程绑定本人任教班级。
- 课时列表、新增、编辑、发布、停用、删除。
- `/teacher/lessons/:lessonId/design` 课时设计第一版，已读取真实课程和课时信息，并支持课时环节新增、编辑、删除、上移下移和保存。
- `LessonStep` 已落库，第一版保存资源绑定数组、活动名称数组、结构化课堂题 `question_items`、AI 生成目标、日志采集开关和学生预览结构。
- `/teacher/ai` 教师 AI 接入配置，第一版支持保存、清除和测试 DeepSeek Key。
- `/teacher/resources` 资源管理第一版，支持上传、查询、打开和删除本人资源。
- 课时设计右侧资源页签已接入教师资源库，支持直接上传课件、视频、PDF、Office 文档、文本和素材包，并把上传资源加入当前环节。
- 课时设计页面采用三栏结构：左侧“学习过程”只负责环节选择、上移下移和弹窗编辑；中间只展示当前环节的资源顺序和题目顺序；右侧作为资源库、题库、文档和 AI 工具入口。
- 新增和编辑环节必须通过弹窗完成，主页面不再放大块环节基础表单。
- 右侧“本课时题库”第一版汇总当前课时各环节的已保存题目，可复制加入当前环节；后续升级为教师个人题库和学校公共题库。
- 课堂题支持题目级分层字段：`target_layer`、`use_layer_scores`、`layer_scores`。课堂不再单独设置分层开关，当前投放环节只要含分层题，学生端就按学生当前 A/B/C 层级过滤题目并返回对应分值。
- 课堂题新增 `file` 附件提交题型。教师可设置允许格式和大小上限，学生课堂页上传后，教师在对应题目的完成情况弹窗中预览、下载、评分和反馈。
- 课时设计左侧上下文卡片只显示学科、课程和当前课时，不展示课程绑定的所有任教班级；课程发布班级仍在课程管理中设置。
- 后端 API 会校验课程教师归属、学科学校范围和班级任课权限。

后续重构方向：

- 将 `LessonStep.resource_items`、`LessonStep.question_items` 和 `LessonStep.activity_items` 从 JSON 过渡方案升级为真实资源、题库、任务和提交模型绑定。
- 每个片段可绑定资源、平台题目、作品上传、任务单、ONLYOFFICE 协作文档或 AI 生成学习单。
- 课程管理页增加“课时设计”，不再只维护课时标题和说明。
- 教师备课模式采用“左侧课程/课时/片段目录，中间片段编辑，右侧资源库/题库/AI/属性/预览”的结构。
- 学生预览模式采用“左侧资源预览，右侧本环节任务和作答”的结构。资源、题目、任务和作品提交都挂在同一个课时环节下，学生端同屏完成。
- 任务驱动课程默认进入课时学习过程设计。
- 项目式学习课程默认进入项目设计器，项目设计器需要支持阶段、里程碑、甘特图、项目日志和评价量规。
- 每个班级、每个学生在两类课程中都要形成学习日志，供教师复盘、学生反思和 AI 特征聚合使用。

## 3. 课程详情与课时

课程详情承载课程结构和教学进度。

布局：

- 顶部课程摘要。
- 左侧课时列表。
- 右侧当前课时内容、活动、资源、任务和数据。

课时字段：

- 课时名称。
- 排序。
- 内容说明。
- 状态：草稿、已发布、停用。
- 关联活动数。
- 关联资源数。
- 学生完成率。

课时功能：

- 新增课时。
- 编辑课时。
- 发布、停用。
- 进入课堂模式。

规则：

- 课时必须属于教师自己的课程。
- 课时发布后学生端可见。
- 已发布课时不能直接删除，必须先停用。
- 已有学习事件或课堂记录的课时不能物理删除。

## 4. 课堂教学

旧 WWW 对应：

- `teacher/lesson.php`
- `teacher/sign.php`
- `teacher/active1.php` 到 `active4.php`
- `teacher/lesson-active-task.php`
- `teacher/taskCompletion.php`

新版课堂教学是实时教学控制台。

课堂教学不再承担课程内容设计。课程内容设计应在课时设计中完成；课堂教学只表示某个班级在某个时间运行这节课，并控制当前片段的开启、关闭、收集和反馈。

课堂分层由当前投放环节的题目自动决定：

- 当前环节没有分层题：学生端显示当前投放环节下的全部题目。
- 当前环节存在 `target_layer != all` 或 `use_layer_scores=true` 的题目：学生端只显示题目 `target_layer` 匹配自己当前层级的题目；若题目启用 `use_layer_scores`，分值按 `layer_scores.A/B/C` 返回。

教师不需要在课堂场次中额外勾选分层模式。是否自动分层只跟当前投放环节的题目设置有关。

分层题目设计规则：

- 支持 `all`、`A`、`B`、`C`、`A/B`、`B/C`、`A/B/C`。
- `A/B` 和 `B/C` 都必须保留，方便教师设置相邻层级共用题。
- 第一版不提供 `A/C`，避免跨层组合造成教学解释困难。
- 题目开启分层分值时，`A/B/C` 初始分值默认等于基础分，教师再按需要修改。
- 后续 AI 可以给分层分值建议，但不能自动改题，必须由教师确认。
- 分层分值是题目难度和评价设计的上下文，也会成为 AI 特征；模型核心 label 应使用教师最终确认的学生层级或教师对 AI 分层建议的采纳结果。

课堂入口：

- 从课程课时进入。
- 从教师首页“今日课堂”进入。

课堂控制台页面区域：

- 顶部：课程、课时、班级、课堂状态、计时器、开始或结束课堂。
- 左侧：课时片段流程，显示未开启、进行中、已关闭。
- 中间：当前片段控制与资源/活动预览。
- 右侧：学生状态、提交情况、未懂反馈和实时消息。
- 底部：签到、随机点名、抢答、倒计时、课堂广播、锁定提交等工具。

课堂工具：

- 开始课堂。
- 结束课堂。
- 开启签到。
- 随机点名。
- 发布抢答。
- 发布讨论。
- 发布即时题。
- 发布课堂任务。
- 收回答案暂不做独立课堂指令，需要时由“锁定提交/关闭环节”承担。
- 锁定提交。
- 广播资源。
- 课堂倒计时。
- 浏览器内远程控制。

课堂活动类型：

- 签到。
- 随机点名。
- 抢答。
- 单题作答。
- 多题作答。
- 简答提交。
- 小组讨论。
- 课堂任务提交。
- 未懂反馈。
- 教师干预记录。

数据采集：

每个课堂动作都写入 `LearningEvent`：

- `lesson_enter`
- `answer_submit`
- `task_submit`
- `chat_message`
- `question_ask`
- `question_answer`
- `teacher_intervention`

扩展事件建议：

- `sign_in`
- `random_call`
- `quick_answer`
- `confusion_mark`
- `control_command`
- `activity_opened`
- `activity_closed`

WebSocket 房间：

- `class:{class_id}`：班级课堂广播。
- `lesson:{lesson_id}`：课时活动状态。
- `user:{user_id}`：个人提醒。
- `control:{class_id}`：教师控制指令。

远程控制范围：

- 统一打开指定课时、活动、资源。
- 锁定或解锁提交。
- 课堂倒计时。
- 收回答案暂不做独立入口，避免和环节锁定、关闭逻辑重复。
- 学生端状态回传。

不做系统级远程控制。第一阶段只做浏览器内控制。

当前第一版已实现：

- `/teacher/classroom` 课堂场次列表、查询、课程筛选、班级筛选和状态筛选。
- 创建课堂时选择本人课程、课时和课程已绑定的任教班级。
- 课堂开始、结束和删除。
- 课堂下新增、编辑、开启、关闭、删除活动。
- 活动类型包括签到、抢答、即时题、讨论、课堂任务、未懂反馈和课堂广播。
- 开始课堂、结束课堂、开启活动和关闭活动写入 `LearningEvent.teacher_intervention`。
- 结束课堂会自动关闭所有进行中的活动。

当前第一版未实现：

- 学生端实时作答和提交。
- WebSocket 推送课堂状态。
- 活动作答 submissions。
- 浏览器内远程控制命令下发。

后续重构方向：

- `ClassroomSession` 保留为一次上课记录。
- 推荐新增 `ClassroomStepRun`，表示某个 `LessonStep` 在本次课堂中的运行状态。
- 也可以先让 `ClassroomActivity` 增加可选 `lesson_step` 字段作为兼容过渡。
- 教师课堂主界面改为“课堂状态条 + 片段流程控制 + 当前片段投放 + 学生实时状态”。
- 平台题、学习任务单、作品上传、ONLYOFFICE 协作文档和讨论都作为学习片段，而不是散落在多个独立页面。

## 5. 任务与测试

旧 WWW 对应：

- `teacher/student-test.php`
- `teacher/edit-test.php`
- `teacher/exam-resource.php`
- `teacher/taskCompletion/*.php`

新版拆成“测试”和“任务”，但共享题目、发布、批改和统计能力。

### 测试管理

字段：

- 测试名称。
- 所属课程、课时。
- 适用班级。
- 题目数量。
- 总分。
- 开始时间。
- 截止时间。
- 状态：草稿、已发布、已结束。
- 提交人数。
- 平均分。

功能：

- 新增测试。
- 从个人题库选题。
- 从公共题库选题。
- 导入题目。
- 设置题目分值。
- 发布到班级。
- 收卷。
- 批改主观题。
- 查看统计。
- 导出成绩 XLSX。

### 课堂任务

字段：

- 任务名称。
- 所属课程、课时。
- 适用班级。
- 层级适配：A/B/C 或全体。
- 提交方式：文本、附件、链接、截图。
- 截止时间。
- 状态。

功能：

- 新建任务。
- 发布任务。
- 按层级发布不同任务。
- 查看提交情况。
- 批改和反馈。
- 导出提交统计。

规则：

- 测试和任务必须属于教师任教班级。
- 发布后写入学习事件。
- 学生提交过程写入行为数据。
- 任务驱动学习中，学生进入任务、查看资源、开始实践、保存草稿、提交作品、修改提交和教师反馈都要形成学生学习日志。
- 按班级运行任务时，系统要形成班级学习日志，例如任务发布时间、参与人数、完成率、集中错误、教师干预和课堂反馈。
- 已有提交记录的测试和任务不能物理删除，只能归档。

## 6. 项目评价

旧 WWW 对应：

- `teacher/edit-project.php`
- `teacher/evaluate-project.php`
- `teacher/student-project.php`

新版项目评价服务于项目式学习和过程性评价。

项目字段：

- 项目主题。
- 背景。
- 目标。
- 重难点。
- 项目内容。
- 课时安排。
- 项目阶段。
- 里程碑。
- 甘特图计划。
- 适用课程。
- 适用班级。
- 层级：A/B/C 或全体。
- 状态。

评价量规：

- 信息意识。
- 计算思维。
- 数字化学习与创新。
- 信息社会责任。

评价来源：

- 学生自评。
- 同伴互评。
- 教师评价。
- 系统过程数据。

功能：

- 新建项目。
- 按 A/B/C 层设置不同项目。
- 设置项目阶段、里程碑和时间计划。
- 查看项目甘特图。
- 记录学生个人项目日志。
- 记录小组项目日志。
- 引用学校评价模板。
- 编辑评价量规。
- 查看学生提交。
- 查看阶段成果和最终成果。
- 批量评分。
- 单个学生详细评价。
- 查看自评/互评/师评差异。
- 查看项目进度、日志完整度和协作贡献。
- 导出项目评价表。

规则：

- 项目评价不只看最终文件，要结合过程行为。
- 项目式学习必须保留过程日志，包括需求分析、资料查找、方案设计、作品制作、调试修改、反思总结和小组协作记录。
- 甘特图不是只做展示图，而要与项目阶段、里程碑、截止时间和完成状态关联。
- 学生个人日志用于记录个人学习过程，小组日志用于记录分工、讨论、决策和阶段成果。
- 班级项目日志用于记录教师发布、阶段推进、全班共性问题、集中展示、教师讲评和项目复盘。
- 教师评分后写入学习档案。
- 评价差异过大时进入待关注列表。

## 7. 学生档案

旧 WWW 对应：

- `teacher/student-file.php`
- `teacher/class.php`

教师端学生档案只显示自己任教班级内学生。

列表字段：

- 学生姓名。
- 账号。
- 账号状态。
- 首次登录状态。
- 学号。
- 班级。
- 当前层级。
- 当前小组。
- 近 7 天活跃度。
- 任务完成率。
- 测试平均分。
- 项目评价。
- 前测状态。
- 风险标签。

功能：

- 按班级筛选。
- 按层级筛选。
- 按风险标签筛选。
- 查询学生账号。
- 将任教班级学生密码重置为 `123456`。
- 查看学生画像。
- 查看学习事件时间线。
- 查看课程学习记录。
- 查看测试记录。
- 查看项目记录。
- 查看自评互评记录。
- 添加教师干预记录。
- 导出任教班级学生学习概况。

学生画像：

- 基础信息。
- 学科前测结果。
- 分层变化记录。
- 学习行为趋势。
- 任务完成情况。
- 测试表现。
- 项目表现。
- 核心素养雷达图。
- 教师干预记录。

规则：

- 教师不能修改学生账号基础信息。
- 教师不能新增、编辑、停用、删除学生账号。
- 教师不能修改学生姓名、学号、班级、层级、账号状态。
- 教师可以查询任教班级学生账号，用于机房上课和学生忘记账号时协助登录。
- 教师可以把任教班级学生密码重置为固定课堂默认密码 `123456`。
- 教师重置学生密码后，该学生应标记为首次登录或要求下次登录改密。
- 教师不能自定义学生密码，避免教师长期持有学生私密密码。
- 教师重置学生密码必须写审计日志，记录教师、学生、班级、时间和来源 IP。
- 教师可以添加教学备注和干预记录。
- 教学备注默认仅教师本人可见；学校管理员可审计。

## 8. 题库资源

旧 WWW 对应：

- `teacher/exam-resource.php`
- `teacher/resource.php`
- `teacher/add-resource.php`
- `teacher/resource-content.php`

新版拆成“题库”和“资源”，但放在同一导航组。

### 个人题库

题型：

- 单选。
- 多选。
- 判断。
- 填空。
- 简答。
- 操作题。
- 量表题。

字段：

- 题干。
- 题型。
- 学科。
- 知识点。
- 难度。
- 分值。
- 选项。
- 答案。
- 解析。
- 标签。
- 可见范围：个人、提交公共题。

功能：

- 新增题目。
- 编辑题目。
- 批量导入。
- 下载模板。
- 导出个人题库。
- 提交为公共题。
- 查看使用记录。

规则：

- 教师可管理个人题库。
- 学校公共题库由学校管理员审核。
- 教师没有公共题审核权限，除非学校管理员授予。

### 我的资源

资源类型：

- 文本。
- 附件。
- 链接。
- 图片。
- 视频。
- 代码包。

功能：

- 新增资源。
- 编辑资源。
- 上传附件。
- 绑定课程或课时。
- 发布给班级。
- 查看资源访问数据。
- 导出资源清单。

规则：

- 所有上传走本地文件存储或后续 MinIO，不依赖外网。
- 资源打开、下载、停留时长写入学习行为事件。
- 当前第一版已经完成资源上传、列表、打开和删除。
- 当前资源绑定到课时环节时仍以显示名写入 `LessonStep.resource_items`；后续应新增资源绑定表，保存真实资源 ID、展示方式、排序和是否必读。
- 资源管理是教师个人资源库；学校公共资源库、审核、共享和复制引用后续再做。

## 9. 分层建议

旧 WWW 对应：

- `teacher/updateFenceng.php`
- `teacher/_edit-fenceng.php`

新版分层建议必须是可解释、可审计、教师确认后生效。

列表字段：

- 学生。
- 班级。
- 当前层级。
- 建议层级。
- 置信度。
- 风险标签。
- 建议原因。
- 模型版本。
- 状态：待确认、已采纳、已拒绝。
- 创建时间。

功能：

- 查看本班待确认建议。
- 单个采纳。
- 单个拒绝。
- 批量采纳。
- 批量拒绝。
- 手动调整学生层级。
- 查看分层变化历史。
- 查看模型解释。

规则：

- AI 模型不直接修改学生层级。
- 教师采纳后才写入学生当前层级。
- 拒绝必须填写或选择原因。
- 手动调整必须写审计日志。
- 分层结果不直接公开给学生，学生端只看到适配后的任务和资源。

## 10. 消息公告

旧 WWW 对应：

- `teacher/notice.php`
- `msg/` 实时消息服务。

新版公告分两类：

- 教师给任教班级发布的班级公告。
- 课堂实时消息。

公告字段：

- 标题。
- 内容。
- 接收班级。
- 状态。
- 发布时间。
- 阅读人数。

功能：

- 新建公告。
- 编辑公告。
- 发布公告。
- 撤回公告。
- 查看阅读情况。

实时消息：

- 学生提问。
- 教师回复。
- 课堂广播。
- 系统提醒。

规则：

- 公告只发给教师任教班级。
- 实时问答使用 WebSocket，离线历史写数据库。

## 11. 教师端数据大屏边界

教师端允许有首页看板，但不做学校级大屏。

首页图表应该服务教学动作：

- 哪个班今天要上课。
- 哪些学生需要关注。
- 哪些任务待批改。
- 哪些分层建议待确认。
- 哪些课堂活动参与度低。

不展示：

- 全校账号结构。
- 全校采集状态。
- 跨学校分析。
- 系统健康底层指标。

## 12. XLSX 导入导出

教师端支持：

- 个人题库导入、导出、模板下载。
- 测试成绩导出。
- 任务提交统计导出。
- 项目评价导出。
- 任教班级学生学习概况导出。
- 资源清单导出。

教师端不支持：

- 批量导入学生账号。
- 批量导入教师账号。
- 批量导入班级。
- 导出学校灾备包。

## 13. 数据模型扩展

已有模型：

- `Course`
- `CourseClass`
- `Lesson`
- `Activity`
- `ClassroomSession`
- `ClassroomActivity`
- `Resource`
- `LearningEvent`
- `StratificationDecision`
- `TeachingAssignment`

已实现：

### CourseClass

课程与班级关系。

字段：

- `course`
- `class_group`
- `created_by`
- `created_at`

用途：

- 教师把课程发布给哪些任教班级。
- 学生端按班级看到课程。

### ClassroomSession

课堂场次。

字段：

- `school`
- `teacher`
- `course`
- `lesson`
- `class_group`
- `title`
- `status`
- `is_layered`：历史兼容字段，前端不再提交；接口返回时表示当前投放环节是否含分层题。
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

状态：

- `draft`：未开始。
- `running`：进行中。
- `finished`：已结束。

### ClassroomActivity

课堂活动。

字段：

- `session`
- `activity_type`
- `title`
- `content`
- `status`
- `opened_at`
- `closed_at`
- `created_at`
- `updated_at`

活动类型：

- `sign_in`
- `quick_answer`
- `question`
- `discussion`
- `task`
- `confusion`
- `broadcast`

待扩展：

### Question

统一题目表。

字段：

- `school`
- `owner`
- `subject`
- `question_type`
- `stem`
- `options`
- `answer`
- `analysis`
- `score`
- `difficulty`
- `knowledge_points`
- `tags`
- `visibility`
- `review_status`
- `created_at`

用途：

- 教师个人题库。
- 学校公共题库。
- 测试、课堂活动、前测的题目来源。

### Assessment

测试或作业发布单。

字段：

- `teacher`
- `course`
- `lesson`
- `title`
- `assessment_type`
- `status`
- `start_at`
- `end_at`
- `total_score`
- `created_at`

### AssessmentItem

测试题目明细。

字段：

- `assessment`
- `question`
- `sort_order`
- `score`

### AssessmentSubmission

学生测试作答。

字段：

- `assessment`
- `student`
- `class_group`
- `answers`
- `score`
- `objective_score`
- `subjective_score`
- `status`
- `submitted_at`
- `graded_at`

### LearningTask

课堂任务或课后任务。

字段：

- `teacher`
- `course`
- `lesson`
- `title`
- `content`
- `target_layer`
- `submission_type`
- `status`
- `deadline`

### TaskSubmission

任务提交。

字段：

- `task`
- `student`
- `content`
- `attachment`
- `score`
- `feedback`
- `status`
- `submitted_at`
- `graded_at`

### ProjectWork

项目任务。

字段：

- `teacher`
- `course`
- `class_group`
- `target_layer`
- `title`
- `background`
- `objective`
- `content`
- `rubric`
- `status`

### ProjectSubmission

项目提交和评分。

字段：

- `project`
- `student`
- `attachment`
- `self_review`
- `peer_review_score`
- `teacher_score`
- `rubric_scores`
- `feedback`
- `status`

### TeacherNote

教师教学备注和干预记录。

字段：

- `teacher`
- `student`
- `class_group`
- `note_type`
- `content`
- `visibility`
- `created_at`

### Notice

班级公告。

字段：

- `teacher`
- `title`
- `content`
- `target_classes`
- `status`
- `published_at`

## 14. API 设计

前缀：

```text
/api/v1/teacher/
```

首页：

```text
GET /api/v1/teacher/dashboard/
```

课程：

```text
GET /api/v1/teacher/course-options/
GET /api/v1/teacher/courses/?q=&subject=&status=&page=1
POST /api/v1/teacher/courses/
GET /api/v1/teacher/courses/{id}/
PATCH /api/v1/teacher/courses/{id}/
DELETE /api/v1/teacher/courses/{id}/
POST /api/v1/teacher/courses/{id}/publish/
POST /api/v1/teacher/courses/{id}/archive/
POST /api/v1/teacher/courses/{id}/classes/
```

课时：

```text
GET /api/v1/teacher/courses/{course_id}/lessons/
POST /api/v1/teacher/courses/{course_id}/lessons/
GET /api/v1/teacher/lessons/{id}/
PATCH /api/v1/teacher/lessons/{id}/
DELETE /api/v1/teacher/lessons/{id}/
POST /api/v1/teacher/lessons/{id}/publish/
POST /api/v1/teacher/lessons/{id}/archive/
```

课堂：

```text
GET /api/v1/teacher/classroom/options/
GET /api/v1/teacher/classroom/sessions/?q=&class=&course=&status=&page=1
POST /api/v1/teacher/classroom/sessions/
GET /api/v1/teacher/classroom/sessions/{id}/
PATCH /api/v1/teacher/classroom/sessions/{id}/
DELETE /api/v1/teacher/classroom/sessions/{id}/
POST /api/v1/teacher/classroom/sessions/{id}/start/
POST /api/v1/teacher/classroom/sessions/{id}/finish/
GET /api/v1/teacher/classroom/sessions/{id}/activities/
POST /api/v1/teacher/classroom/sessions/{id}/activities/
GET /api/v1/teacher/classroom/activities/{id}/
PATCH /api/v1/teacher/classroom/activities/{id}/
DELETE /api/v1/teacher/classroom/activities/{id}/
POST /api/v1/teacher/classroom/activities/{id}/open/
POST /api/v1/teacher/classroom/activities/{id}/close/
```

测试：

```text
GET /api/v1/teacher/assessments/?q=&class=&course=&status=&page=1
POST /api/v1/teacher/assessments/
GET /api/v1/teacher/assessments/{id}/
PATCH /api/v1/teacher/assessments/{id}/
DELETE /api/v1/teacher/assessments/{id}/
POST /api/v1/teacher/assessments/{id}/publish/
POST /api/v1/teacher/assessments/{id}/close/
GET /api/v1/teacher/assessments/{id}/submissions/
POST /api/v1/teacher/assessments/{id}/grade/
GET /api/v1/teacher/assessments/{id}/export/
```

任务：

```text
GET /api/v1/teacher/tasks/?q=&class=&course=&status=&page=1
POST /api/v1/teacher/tasks/
GET /api/v1/teacher/tasks/{id}/
PATCH /api/v1/teacher/tasks/{id}/
DELETE /api/v1/teacher/tasks/{id}/
POST /api/v1/teacher/tasks/{id}/publish/
POST /api/v1/teacher/tasks/{id}/close/
GET /api/v1/teacher/tasks/{id}/submissions/
POST /api/v1/teacher/tasks/{id}/grade/
GET /api/v1/teacher/tasks/{id}/export/
```

学生档案：

```text
GET /api/v1/teacher/students/?q=&class=&layer=&risk=&page=1
GET /api/v1/teacher/students/{student_id}/profile/
GET /api/v1/teacher/students/{student_id}/events/
GET /api/v1/teacher/students/{student_id}/assessments/
GET /api/v1/teacher/students/{student_id}/projects/
POST /api/v1/teacher/students/{student_id}/notes/
POST /api/v1/teacher/students/{student_id}/reset-password/
GET /api/v1/teacher/students/export/
```

教师重置学生密码规则：

- 只能重置任教班级内学生。
- 固定重置为 `123456`。
- 不接收自定义密码字段。
- 重置后学生 `is_first_login=true`。
- 操作写入审计日志。

题库：

```text
GET /api/v1/teacher/questions/?q=&subject=&type=&visibility=&page=1
POST /api/v1/teacher/questions/
GET /api/v1/teacher/questions/{id}/
PATCH /api/v1/teacher/questions/{id}/
DELETE /api/v1/teacher/questions/{id}/
POST /api/v1/teacher/questions/{id}/submit-public/
GET /api/v1/teacher/questions/template/
POST /api/v1/teacher/questions/import/
GET /api/v1/teacher/questions/export/
```

资源：

```text
GET /api/v1/teacher/resources/?q=&page=1
POST /api/v1/teacher/resources/
GET /api/v1/teacher/resources/{id}/
PATCH /api/v1/teacher/resources/{id}/
DELETE /api/v1/teacher/resources/{id}/
GET /api/v1/teacher/resources/export/
```

分层建议：

```text
GET /api/v1/teacher/stratification/?class=&status=&page=1
GET /api/v1/teacher/stratification/{id}/
POST /api/v1/teacher/stratification/{id}/accept/
POST /api/v1/teacher/stratification/{id}/reject/
POST /api/v1/teacher/stratification/bulk-accept/
POST /api/v1/teacher/stratification/bulk-reject/
POST /api/v1/teacher/stratification/manual-adjust/
```

公告：

```text
GET /api/v1/teacher/notices/?q=&class=&status=&page=1
POST /api/v1/teacher/notices/
GET /api/v1/teacher/notices/{id}/
PATCH /api/v1/teacher/notices/{id}/
DELETE /api/v1/teacher/notices/{id}/
POST /api/v1/teacher/notices/{id}/publish/
POST /api/v1/teacher/notices/{id}/revoke/
```

## 15. 前端页面设计

复用现有组件：

- `AppShell`
- `MetricGrid`
- `EChartPanel`
- `ManagementPage`
- `EntityFormModal`
- `ConfirmDialog`
- `StatusBadge`
- `NoticeLine`
- `XlsxImportModal`

新增组件建议：

- `CourseCard`
- `LessonList`
- `ClassSelector`
- `QuestionEditor`
- `RubricEditor`
- `StudentProfilePanel`
- `ClassroomToolbar`
- `LiveStudentGrid`
- `SubmissionReviewPanel`
- `LayerDecisionPanel`

交互规则：

- 表格页都支持查询、筛选、分页。
- 有批量数据的页面支持导出 XLSX。
- 删除必须先停用或归档，已有业务数据不物理删除。
- 教师端高频操作按钮要靠近列表顶部或当前卡片，不藏在复杂菜单里。
- 课堂页内容区可以滚动，顶部课堂状态栏固定。
- 弹窗内的列表区域滚动，底部保存按钮固定。
- 图表容器使用固定高度，避免 ECharts resize 循环。

## 16. 第一阶段开发顺序

### 阶段 A：教师端骨架

1. 新增教师端 API 权限类 `IsTeacher`。
2. 新增 `/api/v1/teacher/dashboard/`。
3. Vue 新增教师端 `AppShell` 菜单。
4. 实现 `/teacher` 首页。

### 阶段 B：课程与课时

1. 补课程序列化和教师课程 API。
2. 实现课程列表。
3. 实现课程新增/编辑/发布/停用。
4. 实现课程详情和课时列表。
5. 实现课时新增/编辑/发布。

状态：已完成第一版。

### 阶段 C：资源与题库

1. 实现我的资源 API 和页面。
2. 新增题目模型和个人题库 API。
3. 实现题库列表、题目编辑器、导入导出。

### 阶段 D：课堂与任务

1. 新增课堂会话和课堂活动模型。
2. 实现课堂页基础 UI。
3. 接 WebSocket 房间。
4. 实现签到、即时题、课堂任务。

状态：课堂会话和活动开关第一版已完成；WebSocket、学生端作答和任务提交待继续。

### 阶段 E：评价与分层

1. 实现测试和任务发布。
2. 实现提交批改。
3. 实现项目评价。
4. 实现分层建议确认。
5. 实现学生档案画像。

## 17. 与旧 WWW 的迁移对应

```text
teacher/course.php                  -> /teacher/courses
teacher/add-course.php              -> /teacher/courses 新增弹窗或独立页
teacher/project-course-info.php     -> /teacher/courses/:id
teacher/task-course-info.php        -> /teacher/courses/:id
teacher/add-lesson.php              -> /teacher/courses/:id/lessons
teacher/lesson.php                  -> /teacher/lessons/:id
teacher/sign.php                    -> /teacher/classroom
teacher/active1.php - active4.php   -> /teacher/classroom 活动类型
teacher/taskCompletion.php          -> /teacher/tasks/:id/submissions
teacher/student-test.php            -> /teacher/tests
teacher/exam-resource.php           -> /teacher/question-bank
teacher/resource.php                -> /teacher/resources
teacher/notice.php                  -> /teacher/notices
teacher/student-file.php            -> /teacher/students
teacher/edit-project.php            -> /teacher/projects
teacher/evaluate-project.php        -> /teacher/projects/:id/evaluation
teacher/updateFenceng.php           -> /teacher/stratification
```

## 18. 课程评价与课堂评价补充

2026-07-10 已补充课程评价能力，并在课堂控制台调用：

- 自评、互评、师评均由教师在课程中选择性开启。
- 评价项由教师设计，评价方式固定为 1-5 星，不使用分数、权重或百分制。
- 互评项可先在课程中设计；只有课堂开启小组合作后，学生端才显示互评入口。
- 教师在课时设计页设置评价内容，可使用自己配置的 DeepSeek API 生成评价项草稿，草稿必须确认保存后才对学生生效。
- 教师可在课时设计页按班级查看三类评价完成数量和平均星级，并填写课程级师评。
- 每次新建课堂默认不对学生开放评价；教师可在课堂控制台“评价情况”中按收尾节奏开启或关闭本课堂评价可见性，并填写绑定本次课堂的师评；课堂控制台不再提供评价项编辑和 AI 生成入口。
- 评价结果写入评价提交表，并同步写入 `LearningEvent`，作为过程性评价和 AI 分层/分组特征来源。

## 19. AI 学习网页

- 教师在课时设计“AI”页签填写生成方向，使用自己的 DeepSeek API 生成受控学习网页。
- 一个课时可以保存多个网页；教师可选择网页并多轮填写修改要求，每次修改保存独立版本。
- 网页可包含任务情境、说明、列表、步骤、卡片、表格、代码和多个表单。
- 教师可网页内预览、在独立新标签页预览、加入当前学习环节，并在保存环节后随课堂投放给学生。
- 教师可查看每个表单的提交学生、提交次数、选择分布、数值统计和文本回答。
- AI 不能生成或执行任意脚本；平台只执行自身固定渲染器和表单消息桥。
- 教师要求“生成动画/可视化”时，DeepSeek 应优先输出受控 `visualization`：流程演示用 `process`，阶段变化用 `timeline`，数值比较用 `bars`，字符编码过程用 `binary`；该模式不使用 AI 自定义脚本。
- 固定动画无法表达的模拟实验、Canvas 或 SVG 交互可生成 `interactive` 自定义动画；平台允许自包含 HTML/CSS/JavaScript，但在独立嵌套沙箱中运行且禁止联网。学生答案采集仍必须另配平台表单。
- AI 学习网页生成和继续修改都提供三种模式。自由交互动画模式要求 DeepSeek 真实生成可执行 JavaScript，必须包含播放控件和画面变化；后端会拒绝仅用静态步骤或受控可视化冒充自由动画的结果。
- 新标签页使用 `/app/learning-pages/:pageId` 深链接，只挂载一个只读 iframe；不再以全屏弹层叠加第二个 iframe，避免重复渲染和闪烁。
- 课堂控制台“本环节任务”直接列出本环节 AI 学习任务单，并提供“查看完成情况”；弹窗默认限定当前课堂场次和当前班级，显示完成率、已完成/进行中/未开始学生、表单提交明细和字段图表。
- 课时设计中的“表单统计”保留为跨课堂历史汇总入口，课堂教学中的统计不得混入其他班级或其他场次数据。
## 测试管理与共享题库

教师端已将原“任务与测试”和“题库资源”占位页替换为正式模块：

- 题库管理默认展示学校共享题库，可切换到我的题目。
- 同校教师共享查看和组卷，编辑权限仍归题目创建者。
- 测试管理采用“基本信息 -> 共享题库组卷”两步窗口，保存按钮固定在窗口底部。
- 发布后试卷锁定，教师开启后学生才能作答；教师结束测试会自动收卷。
- 成绩窗口提供应考、提交、待评分、平均分和逐题正确率；答卷窗口支持人工评分和评语。
- 题库新增 AI 批量出题入口，使用教师自己的 DeepSeek API。AI 只生成可编辑草稿，教师确认后才批量进入学校共享题库；确认接口复用手工题目校验，不允许 AI 绕过答案与选项约束。

完整规则见 `docs/assessment_module_design.md`。

## 课堂实名文字聊天

- 教师在课堂控制台通过右侧聊天抽屉分别开启全班、师生私聊和小组聊天。
- 教师端私聊按学生切换，小组聊天可进入任意当前课堂小组。
- 教师端提供待审核言论队列，可放行、警告、撤回或确认扣分。
- 警告、撤回和扣分都会使原消息从所有学生聊天记录中消失；教师端保留审计原文。
- 系统只给出轻微 1 分、一般 3 分、严重 5 分的建议值，不自动扣分。
- 课堂结束后聊天自动关闭，历史消息和审核记录保留。

完整规则见 `docs/classroom_chat_design.md`。
