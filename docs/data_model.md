# 底层数据模型

## accounts

- `User`：统一用户表，角色为超级管理员、学校管理员、教师、学生。

## school

- `School`：学校。
- `ClassGroup`：班级，支持启用、停用、归档；毕业时设为归档。
- `ClassGroup.graduated_at`：班级毕业归档时间。
- `ClassGroup.graduated_by`：执行毕业归档的学校管理员。
- `StudentProfile`：学生档案扩展，保存班级、当前分层、分组、积分和首次使用状态。新生允许暂不选班级、暂不分层。
- `StudentProfile.student_no`：学号，可为空。新生账号先发放，学号后续通过批量导入按登录账号匹配更新；非空学号在班级内唯一。
- `TeachingAssignment`：任课关系，只维护本校教师与任教班级的对应关系；课程、公有课/私有课后续由课程模块单独处理。

班级毕业规则：

- 毕业不删除班级和学生档案。
- 毕业后班级状态为 `archived`。
- 毕业会停用该班所有学生账号。
- 历史学习行为、分层记录、模型版本和训练任务继续保留。

学生首次使用字段：

- `is_first_use`：是否仍处于首次使用流程。
- `onboarding_status`：`new`、`password_updated`、`class_selected`、`pretest_completed`、`active`。
- `password_updated_at`：学生首次改密时间。
- `class_selected_at`：学生首次选班时间。
- `pretest_completed_at`：学生完成素养题和态度问卷前测的时间。

## courses

- `Subject`：学科。每个学校独立维护学科，字段包括 `school`、`name`、`code`、`is_active`。课程和前测都挂到学科下。
- `Course`：课程，支持 PBL/TBL。
- `Course.subject`：课程所属学科，可为空。后续学生进入某学科课程前，需要检查该学科前测完成状态。
- `CourseClass`：课程与班级关系。教师把自己的课程发布给哪些任教班级，学生端后续按班级看到课程。
- `Lesson`：课时。
- `Activity`：课堂活动。
- `ClassroomSession`：课堂场次，字段包括学校、教师、课程、课时、班级、状态、当前投放环节、环节投放状态、提交锁定状态、开始时间和结束时间。
- `ClassroomSession.is_layered`：历史兼容字段，业务上不再作为教师可配置开关。接口中的 `is_layered` 表示当前投放环节是否含分层题，由 `LessonStep.question_items` 自动计算。
- `ClassroomActivity`：课堂场次下的活动和控制指令，当前支持签到、随机点名、抢答、倒计时、课堂广播、即时题、讨论、课堂任务和未懂反馈。
- `ClassroomActivity.metadata`：课堂指令结构化参数，例如 `command`、倒计时秒数、随机点名学生、广播已读统计等。
- `Resource`：平台资源。
- `ClassroomGroupCollaboration`：课堂小组合作配置。按课堂场次一对一保存是否开启、分组策略、每组人数、协作文档类型、共享空间配额、是否允许学生上传和是否允许在线编辑。
- `ClassroomGroup`：某次课堂小组。保存组号、组名、层级提示、组长、该组协作文档文件、文档类型和文档版本。
- `ClassroomGroupMember`：课堂小组成员。一个学生在同一次小组合作中只能属于一个小组，角色为组长或成员。
- `ClassroomGroupFile`：小组共享文件。用于学生小组交流网盘，保存上传者、原始文件名、格式、大小、说明和文件路径。

教师端后续建议扩展：

- `Question`：统一题目表，支持教师个人题库、学校公共题库和公共题审核。
- `Assessment`：测试或作业发布单。
- `AssessmentItem`：测试题目明细。
- `AssessmentSubmission`：学生测试作答和批改结果。
- `LearningTask`：课堂任务或课后任务。
- `TaskSubmission`：任务提交和教师反馈。
- `ProjectWork`：项目式学习任务，支持 A/B/C 层适配。
- `ProjectMilestone`：项目阶段和里程碑，用于项目式学习的进度管理。
- `ProjectGanttItem`：项目甘特图条目，记录阶段起止时间、负责人、依赖关系和完成状态。
- `ProjectLog`：项目日志，支持学生个人日志、小组日志和教师过程记录。
- `ProjectSubmission`：项目提交、自评、互评、师评和量规评分。
- `Notice`：教师发布给任教班级的公告。

课程规则：

- 课程归创建教师所有。
- 课程所属学科必须属于教师所在学校。
- 课程发布给班级时，班级必须是教师任教班级。
- 课程发布前至少需要设置学科、绑定 1 个任教班级并创建 1 个课时。
- 已发布课程和课时删除前必须先停用。
- 已有学习事件或课堂记录的课程、课时、测试、任务和项目不做物理删除，只能停用、归档或复制新版本。
- 课堂场次只有 `draft` 未开始状态可以删除；进行中和已结束课堂必须保留过程记录。
- 同一课时不再额外区分普通课堂和分层课堂。教师只要在当前环节题目中设置 `target_layer` 或 `use_layer_scores`，学生端就会按学生当前层级自动过滤题目和适配分值。
- 小组合作不作为课时环节内容保存，而是某次课堂场次的运行能力。教师可在课堂控制台开启，学生只在课堂进行中看到自己所在小组。
- 评价项配置不作为课堂运行态保存，而是备课阶段的课程级设置。入口放在课时设计页，教师选择性开启自评、互评和师评；课堂中只调用已保存配置。单次课堂是否开放评价保存为 `ClassroomSession.evaluation_enabled`，默认关闭，重新开始课堂也重置为关闭；评价结果只记录 1-5 星，不记录百分制分数。
- 小组分组第一版采用默认分组：按 A/B/C 层级优先组内同层，未分层学生均衡补齐；随机分组可选；`ai_layer` 策略已预留，当前仍回退到同层优先规则。
- 小组协作文档按组生成一份独立 Word/PPT/Excel 文件。STRATA 负责账号和权限，ONLYOFFICE 负责在线编辑；无 ONLYOFFICE 时仍保留文件下载和共享文件上传能力。
- 小组共享空间按组限制容量，第一版由教师设置 MB 配额，上传文件只允许 Office、PDF、压缩包、图片、音视频和常见文本格式。
- `LessonStep.question_items` 第一版保存在 JSON 中，题目可包含 `target_layer`、`use_layer_scores` 和 `layer_scores`，用于学生端自动分层过滤和分值适配。
- `target_layer` 支持 `all`、`A`、`B`、`C`、`A/B`、`B/C`、`A/B/C`；第一版不支持 `A/C`。
- `layer_scores` 初始值应由基础分 `score` 自动填充，教师可修改；后续 AI 只提供建议分值，不直接写入。
- 后续新增正式提交表时，应保存学生作答时的 `student_layer_snapshot`、`target_layer_snapshot`、`layer_scores_snapshot`、`max_score_for_layer` 和 `score_rate`。
- 课堂活动进行中不能删除，必须先关闭。
- 任务驱动学习和项目式学习都必须写入学习行为事件和学习日志。
- 任务驱动学习日志重点记录课时任务过程、资源学习、作答、作品提交、修改和教师反馈。
- 项目式学习日志重点记录阶段推进、里程碑、甘特图进度、协作分工、成果迭代和评价反思。

## learning

- `LearningEvent`：统一学习行为事件表，是 AI 特征工程的数据源。
- `StudentFeatureSnapshot`：夜间聚合后的学生特征快照。
- `StratificationDecision`：AI 分层建议与教师确认记录。
- `PretestPaper`：学科前测套卷。按学校、学科、前测类型和版本管理。
- `PretestQuestion`：前测题目。支持单选、多选、量表和简答。
- `PretestSubmission`：学生前测作答记录。后续学生端提交前测时写入。
- `StudentWorkAttachment`：学生课堂附件提交。字段包括学校、班级、课程、课时、环节、课堂场次、学生、题目 ID、题干快照、文件、原始文件名、格式、大小、教师评分、教师反馈和批阅人。
- `ClassroomEvaluationConfig`：课程评价配置。与 `Course` 一对一，记录自评、互评、师评三类 5 星评价项；旧的类型开关只作兼容字段，实际判断以是否存在评价项为准。
- `ClassroomEvaluationSubmission`：评价提交。记录课程、可选课堂场次、班级、评价类型、评价者、被评价者、小组、各评价项星级和备注。课堂提交按同一课堂唯一；课程级师评按同一课程、同一评价者、同一被评价者唯一。
- `TeacherNote`：建议新增，教师对任教班级学生的教学备注和干预记录。
- `StudentLearningLog`：建议新增，学生学习日志。由系统根据 `LearningEvent` 自动生成，也可由学生反思或教师补充。
- `ClassLearningLog`：建议新增，班级学习日志。记录课堂运行、任务推进、项目阶段、共性问题、教师干预和课后复盘。

学习日志与学习事件的关系：

- `LearningEvent` 是原始行为流水，记录“谁在什么时候做了什么”。
- `StudentLearningLog` 是学生维度的过程摘要，记录任务实践、项目推进、反思、修改和反馈。
- `ClassLearningLog` 是班级维度的过程摘要，记录班级整体进度、完成情况、共性问题和教师干预。
- 日志可以引用多个 `LearningEvent`，但不能替代 `LearningEvent`。
- AI 特征工程应优先使用 `LearningEvent` 做统计特征，同时使用学习日志提取阶段性、反思性和协作性特征。

课堂作答事件第一版：

- 学生在课堂页提交当前环节题目或任务文字时，写入 `LearningEvent.event_type=answer_submit`。
- `object_type=lesson_step`，`object_id` 为 `LessonStep.id`。
- `metadata.action=lesson_step_answer`，`metadata.classroom_session` 记录本次课堂场次。
- `metadata.answer` 保存结构化作答：课堂题为 `{ questions: { question_id: value }, text: string }`，纯任务文字为字符串；附件提交题的 `value` 保存附件编号、文件名、地址、格式和大小。
- `metadata.answered_count`、`question_count`、`required_count`、`auto_score`、`auto_score_max`、`correct_count` 用于教师端实时完成情况和后续特征聚合。
- 附件提交文件进入 `StudentWorkAttachment`，教师评分和反馈也保存在该表；教师评分会额外写入 `LearningEvent.event_type=teacher_intervention`。
- 学生打开小组协作文档时写入 `LearningEvent.event_type=resource_view`，`metadata.action=group_document_open`。
- 学生上传小组共享文件时写入 `LearningEvent.event_type=task_submit`，`metadata.action=group_file_upload`。
- 学生提交课堂自评时写入 `LearningEvent.event_type=answer_submit`，`metadata.action=self_evaluation_submit`。
- 学生提交课堂互评时写入 `LearningEvent.event_type=answer_submit`，`metadata.action=peer_evaluation_submit`。
- 教师提交课堂师评时写入 `LearningEvent.event_type=teacher_intervention`，`metadata.action=teacher_evaluation_submit`。
- 教师提交课程级师评时写入 `LearningEvent.event_type=teacher_intervention`，`metadata.action=course_teacher_evaluation_submit`。
- 课堂评价星级、评价完成时间、评价者和被评价者关系可作为过程性评价和后续 AI 分层/分组特征；星级本身不直接作为分层 label。
- 正式批阅、历史答案查询和导出后续可新增 `LessonStepSubmission` 或同类表，`LearningEvent` 继续作为原始行为事件。

前测套卷规则：

- 前测类型固定为 `literacy` 素养测试和 `attitude` 学习态度问卷。
- 一个学科可以有多个历史版本。
- 同一学校、同一学科、同一类型只允许一套当前发布版本；发布新版本时旧发布版本自动归档。
- 已发布且已有学生作答的套卷和题目不做物理删除，只能归档或复制新版本。
- 学生进入某学科正式学习前，必须完成该学科当前发布的素养测试和学习态度问卷。

教师端学习事件建议补充：

- `sign_in`：签到。
- `random_call`：随机点名。
- `quick_answer`：抢答。
- `confusion_mark`：未懂反馈。
- `activity_opened`：课堂活动开启。
- `activity_closed`：课堂活动关闭。
- `control_command`：浏览器内课堂控制指令。

分层建议规则：

- AI 训练任务只生成 `StratificationDecision`。
- 模型不能直接修改 `StudentProfile.current_layer`。
- 教师采纳建议后才更新学生当前层级。
- 教师拒绝建议或手动调整层级必须写审计日志。
- 课堂题的 `target_layer`、`layer_scores` 和分层达成率是训练特征和评价上下文，不作为主要 label。
- 主要 label 应来自教师最终确认的层级、教师采纳/拒绝 AI 建议记录，以及下一阶段表现标签。

## aiops

- `ModelVersion`：班级模型版本。
- `TrainingJob`：训练任务。

## AI 学习网页

- `LearningWebPage`：教师在某门课程、某个课时中创建的受控学习网页，保存当前 JSON schema、当前版本和原始生成要求。
- `LearningWebPageVersion`：每次 AI 生成或修改后的不可变版本快照，用于追溯修改过程和后续回滚扩展。
- `LearningWebPageResponse`：学生对某个网页表单的提交，记录网页版本、表单编号、学生、班级、课时环节、课堂场次、结构化回答和尝试次数。
- `LessonStep.resource_items` 通过 `kind=learning_page`、`learning_page_id` 绑定网页，沿用现有资源顺序和课堂投放流程。
- `LearningWebPage.schema.blocks` 支持受控 `visualization` 区块，类型限定为 `process/timeline/bars/binary`；只保存结构化动画数据，不保存或执行 AI 生成的 HTML、CSS、JavaScript。
- `LearningWebPage.schema.blocks` 也支持 `interactive`，保存受长度限制的 `html/css/javascript/height`；代码只在无同源权限、无网络权限的嵌套沙箱中执行，不作为平台业务代码运行。
- 网页表单回答属于过程性学习行为，可聚合为参与度、选择分布、量表变化、反思文本和任务达成特征；不能直接作为分层 label。
## 测试与题库

- `QuestionBankItem`：学校共享题目。记录创建教师、学科、题型、选项、答案、解析、难度、知识点、默认分值、状态和使用次数。
- `TestAssessment`：教师创建的测试，关联学科、可选课程和多个任教班级，包含时长、时间窗口、运行状态和成绩显示策略。
- `TestAssessmentQuestion`：试卷题目快照。保留题库来源但不依赖来源内容，历史试卷不受题库修改影响。
- `TestAttempt`：学生唯一答卷，记录答题、提交、评分状态和客观/主观/总分。
- `TestAttemptAnswer`：逐题答案、自动得分、人工得分、正确状态和教师评语。

## realtime 课堂聊天

- `ClassroomChatConfig`：一节课堂一个聊天配置，保存全班聊天、师生私聊、小组聊天三个开关，默认全部关闭。
- `ClassroomChatThread`：课堂内的聊天线程。全班每课堂唯一，私聊按课堂和学生唯一，小组聊天按课堂小组唯一。
- `ClassroomChatMessage`：实名纯文本消息，保存发送者、原文、内容指纹、审核状态、严重度、命中规则、教师处理、扣分值及审核时间。
- `ClassroomChatReadState`：用户在线程中的最后已读消息，用于计算未读数。

消息状态为 `visible`、`pending`、`removed`。`removed` 消息只对教师返回，任何学生都不能再读取原文。聊天消息写入 `LearningEvent.chat_message`，教师审核写入 `LearningEvent.teacher_intervention`；学生确认警告、撤回或扣分反馈时写入 `LearningEvent.page_view` 和 `metadata.action=classroom_chat_moderation_feedback_ack`。原文只保存在聊天消息表，不复制到学习事件元数据。
