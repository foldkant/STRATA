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
- `ClassroomSession`：课堂场次，字段包括学校、教师、课程、课时、班级、状态、是否启用分层课堂、当前投放环节、环节投放状态、提交锁定状态、开始时间和结束时间。
- `ClassroomSession.is_layered`：课堂级分层教学开关。为 `true` 时，学生端按 `StudentProfile.current_layer` 过滤当前环节题目并应用题目分层分值；为 `false` 时，学生端显示当前环节全部题目。
- `ClassroomActivity`：课堂场次下的活动，支持签到、抢答、即时题、讨论、课堂任务、未懂反馈和课堂广播。
- `Resource`：平台资源。

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
- 同一课时可以被普通课堂和分层课堂复用。是否分层由 `ClassroomSession.is_layered` 决定，不由课程或课时固定决定。
- `LessonStep.question_items` 第一版保存在 JSON 中，题目可包含 `target_layer`、`use_layer_scores` 和 `layer_scores`，用于课堂级分层模式下的学生端过滤和分值适配。
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
- `TeacherNote`：建议新增，教师对任教班级学生的教学备注和干预记录。
- `StudentLearningLog`：建议新增，学生学习日志。由系统根据 `LearningEvent` 自动生成，也可由学生反思或教师补充。
- `ClassLearningLog`：建议新增，班级学习日志。记录课堂运行、任务推进、项目阶段、共性问题、教师干预和课后复盘。

学习日志与学习事件的关系：

- `LearningEvent` 是原始行为流水，记录“谁在什么时候做了什么”。
- `StudentLearningLog` 是学生维度的过程摘要，记录任务实践、项目推进、反思、修改和反馈。
- `ClassLearningLog` 是班级维度的过程摘要，记录班级整体进度、完成情况、共性问题和教师干预。
- 日志可以引用多个 `LearningEvent`，但不能替代 `LearningEvent`。
- AI 特征工程应优先使用 `LearningEvent` 做统计特征，同时使用学习日志提取阶段性、反思性和协作性特征。

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
