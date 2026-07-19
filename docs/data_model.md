# 底层数据模型

> AI 隐性动态分层的目标模型以 [设计报告](student_behavior_ai_stratification_design.md) 为科学与产品依据，以 [开发路线图](student_behavior_ai_stratification_development_roadmap.md) 为迁移顺序。本文中的现有字段用于描述当前实现，不得覆盖目标模型的用途和可见性约束。

## accounts

- `User`：统一用户表，角色为超级管理员、学校管理员、教师、学生。

## school

- `School`：学校。
- `ClassGroup`：班级，支持启用、停用、归档；毕业时设为归档。
- `ClassGroup.graduated_at`：班级毕业归档时间。
- `ClassGroup.graduated_by`：执行毕业归档的学校管理员。
- `StudentProfile`：学生档案扩展，保存班级、过渡期 `current_layer` 缓存、积分和首次使用状态。新生允许暂不选班级、暂不分层；正式隐性分层迁移到按学科/课程和有效期保存的 `StudentSubjectBand` 后，`current_layer` 逐步只读并删除。
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
- 签到活动开启后生成全班 `attendance` 学习机会。学生自助签到与教师考勤确认追加 `attendance.recorded`；状态修订引用前一事件，不覆盖历史。未响应保持未知并在课堂结束时撤回，不自动转为缺勤。
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
- `ProjectSubmission`：项目提交、自评、互评、师评和评价结果。
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
- `ClassroomGroupDocumentVersion` 保存小组协作文档的不可变版本号、文件副本、SHA-256、大小、来源、回调状态、文档 key 和经过 JWT 校验的编辑者 ID。编辑者列表只用于组级审计，不直接归因个人贡献。
- `ClassroomGroupFile` 使用 `public_id`、`analytics_attempt_id` 和 `version_no` 标识一次共享区提交；业务表保留文件名与描述，新版事件不复制这些正文信息。
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
- `StudentWorkAttachment`：学生课堂附件提交版本。除教学上下文、文件和批阅缓存外，包含唯一 `submission_id`、`upload_version` 和 `supersedes`；重新上传追加记录，不删除旧文件。
- `LessonStepAttempt`：学生一次课堂环节提交。使用唯一 `attempt_id` 和递增 `attempt_no`，保存课堂/环节上下文、正文、题目计数和客观题汇总。
- `LessonStepAttemptAnswer`：课堂提交的逐题业务答案，保存题目版本、题型、响应正文、自动评分和可选附件版本引用；分析事件只引用该业务记录，不复制答案正文。
- `ClassroomEvaluationConfig`：课程评价设置。与 `Course` 一对一，记录教师当前使用的自评、互评、师评三类 5 星评价项；保存后按内容生成评价版本。
- `ClassroomEvaluationConfigVersion`：不可修改的课程评价版本。保存课程内递增版本号、内容摘要、三类开关和评价项快照；相同内容不重复发布。课堂首次开启评价时把版本固定到 `ClassroomSession.evaluation_config_version`。
- `ClassroomEvaluationSubmission`：不可修改的评价提交版本。记录课程、可选课堂、班级、评价者、被评价者、小组、评价版本、逐项星级、逐项暂不评价原因和备注；修订生成新版本，不能覆盖或删除旧记录。同一指标不能同时评分和暂不评价。
- `TeacherNote`：建议新增，教师对任教班级学生的教学备注和干预记录。
- `StudentLearningLog`：建议新增，学生学习日志。由系统根据 `LearningEvent` 自动生成，也可由学生反思或教师补充。
- `ClassLearningLog`：建议新增，班级学习日志。记录课堂运行、任务推进、项目阶段、共性问题、教师干预和课后复盘。

学习日志与学习事件的关系：

- `LearningEvent` 是原始行为流水，记录“谁在什么时候做了什么”。
- `StudentLearningLog` 是学生维度的过程摘要，记录任务实践、项目推进、反思、修改和反馈。
- `ClassLearningLog` 是班级维度的过程摘要，记录班级整体进度、完成情况、共性问题和教师干预。
- 日志可以引用多个 `LearningEvent`，但不能替代 `LearningEvent`。
- AI 特征工程应优先使用 `LearningEvent` 做统计特征，同时使用学习日志提取阶段性、反思性和协作性特征。

课堂作答事实层：

- 环节投放按题目和适用带创建 `LearningOpportunity`；文件题使用 `task` 机会，其他题使用 `question` 机会。
- 学生每次提交追加 `LessonStepAttempt` 和逐题 `LessonStepAttemptAnswer`，不会覆盖上一版；教师完成情况读取当前课堂下最新尝试。
- 非文件题逐题写 `item.submitted@1.1`。客观题同时形成 `item.graded@1.1 final/automatic`，简答题先形成无分数 `pending`。
- 附件每次上传追加 `StudentWorkAttachment` 并写 `task.submitted`；教师首次批阅形成 `final`，复评形成 `revised`，评分事实通过 `supersedes` 保留历史。
- `LearningEventV2` 仅保存对象版本、机会 UUID、尝试 UUID 和统计契约，不保存答案正文、聊天原文或文件地址。
- 小组文档和共享区分别生成非必做 `document/task` 学习机会，并通过 `content.released@1.1.target_student_ids` 只投放给当前组员。
- 学生打开小组协作文档时通过统一服务兼容写入 `group.document.opened`；学生上传共享文件时按同一方式写入 `group.file.shared`。
- ONLYOFFICE 保存回调通过 JWT、文档 key、下载来源和大小校验后追加文档版本及 `group.document.saved`。该事件分析单位是 `group`，不能据此推断某位学生完成了多少内容。
- 协作关闭和课堂结束撤回未完成机会；有打开、保存或上传证据后禁止重新分组，防止删除成员关系和文件证据。
- 自评、互评、课堂师评和课程师评统一记录为 `evaluation.rating.submitted@1.1`；事件保存实际星级和结构化暂不评价原因代码，不复制评价备注正文。历史 `1.0` 定义继续保留，不覆盖原版本。
- 平均星级只使用实际评分项。汇总同时返回已评分、暂不评价、未回答和总指标数；提交人数与指标覆盖数分开显示。
- 自评事件的评价者和归属学生相同；师评及互评分别保留真实评价者，证据归属被评价学生。互评跨学生归属只能由已校验同组关系的服务端入口写入。
- 课堂评价星级、评价完成时间、评价者和被评价者关系可作为过程性评价和后续 AI 分层/分组特征；星级本身不直接作为分层 label。
- 课堂历史提交和附件版本底座已经建立；后续批量批阅与导出应读取业务提交表和成熟评分事实，不从事件 JSON 反解析答案。

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

- 当前 `StratificationDecision` 只是初版骨架；目标模型拆分为候选建议、教师决定观测和有效 `StudentSubjectBand`。
- 模型不能直接修改 `StudentProfile.current_layer` 或 `StudentSubjectBand`；教师确认后才生成新的有效内容带版本。
- 教师拒绝、保持、手动调整或延后建议必须写审计日志，且只允许查看本人任教班级。
- A/B/C、概率、排名和分组依据只向任课教师显示；学生接口只返回已分配的任务、资源和支持。
- 课堂题的 `target_layer`、`layer_scores` 和分层达成率是训练特征和评价上下文，不作为主要 label。
- 教师最终确认层级和采纳/拒绝记录属于弱监督、人机一致性与实施数据，不是学生能力或模型效果的主要真值。
- 主要预测结局来自预先计划的下一阶段掌握、必做任务完成、逾期和成长结果；动态分层是否有效需要单独的前瞻性干预研究。

## aiops

- `ModelVersion`：班级模型版本。
- `TrainingJob`：训练任务。

## learning_analytics

- `AnalyticsOperatingMode`：每校一条分析安全运行状态，状态为 `collect_only/shadow/teacher_review/active/suspended`；不能从仅采集直接跳到正式投放，暂停必须记录原因。
- `SensitiveInferenceAccessLog`：内容带、个体解释和分组依据的敏感访问审计。保存访问者角色、学校/班级作用域、用途、字段类别、导出标记、允许/拒绝和原因；创建后不可修改。
- `EventSchemaDefinition`：版本化事件模式登记表。保存事件名、模式版本、Pydantic 生成的 JSON Schema、上下文要求、允许来源、隐私类别、分析单位和 SHA-256；启用后不可覆盖，只能停用并发布新版本。
- `LearningEventV2`：新版不可变学习事件。分别保存执行人和记录归属学生、学校/班级/学科/课程/课时/课堂/环节上下文、对象与尝试/学习任务 UUID、客户端发生和服务端接收时间、载荷、隐私类别及记录状态。
- `LearningEventV2.idempotency_key`：服务端按学校、执行人、来源和客户端会话/序号计算的 SHA-256；与 `event_id` 共同防止离线重试重复写入。
- `LearningEventV2.event_fingerprint`：不包含服务器接收时间和事件 UUID 的规范化事实摘要。相同幂等键但指纹不同会拒绝为 `idempotency_conflict`。
- `LearningEventV2.legacy_event`：新版记录与旧业务 `LearningEvent` 的一对一追溯键。该字段名称属于内部兼容契约；新文档和界面统一称“旧记录”。新版记录使用教师作为操作人、学生作为记录归属对象时，允许与旧页面为兼容而保留学生 `actor` 的记录不同。
- `LearningEventV2.payload`：只允许注册表中的严格字段，未知字段拒绝，规范化后不得超过 16KB；答卷正文、聊天原文、作品内容和文件明细继续保留在业务表。
- `LearningEventV2.quality_status`：`received/schema_valid/context_valid/deduplicated/accepted/quarantined/legacy_unmapped`。批量服务在写入前完成模式、上下文和幂等检查；超过 24 小时/7 天及客户端时钟超前写入质量标记，不因离线乱序直接丢弃。
- `LearningEventV2.opportunity_id/opportunity_record`：迁移期同时保留旧 UUID 和新机会外键。新接受事件必须让两者指向同一条可验证机会；仅 `legacy_unmapped` 可暂时保留 UUID 而无外键，便于增量迁移而不破坏历史信封。
- `LearningOpportunity`：按学生展开的不可变学习机会分母，保存学校、班级、学科、课程、课时、课堂、环节、内容 ID/版本、必做标记、实际投放带、教学阶段和可用窗口。唯一约束为“学生 + 投放事件”，不能由提交结果反推。
- `LearningOpportunityTransitionFact`：机会状态的只增事实，支持 `assigned/released/exposed/started/submitted/graded/withdrawn/excused/unavailable`。撤回、豁免和不可用互斥；迟到但发生更早的离线证据追加保存，不覆盖旧时间。
- `AssessmentResultFact`：按学习机会和 `attempt_id` 保存不可变评分版本，成熟状态为 `pending/final/revised`。最终和修订评分必须有实际得分；修订必须引用同一次作答的既有成熟版本。当前成熟版本按最大 `grade_version` 派生，不通过修改旧行维护 `is_current`。
- `AssessmentResultFact` 只在同一 `attempt_id` 已存在 `submitted` 事实后生成。主观题 `pending` 可保留空得分，不计为 0；`item.graded` 事件、机会的 `graded` 状态与评分事实处于同一事务，失败时整体回滚。
- `ParticipationPointLedger`：课堂激励积分不可变流水。保存来源事件、学生、班级/课程/课堂、结构化原因、执行教师、增量、记账前后余额和冲正引用；同一来源事件只能生成一条，原流水不能编辑或删除。
- `ParticipationPointLedger` 单次增减绝对值不超过 100，普通扣分和冲正后余额不能低于 0；冲正值必须与原流水方向相反且绝对值相同，同一原流水只能冲正一次。
- `learning_analytics.services.participation_points.reconcile_participation_point_cache`：以第一笔流水的迁移期起始余额和全部增量重算 `StudentProfile.score`。旧字段只是显示缓存，不是学业成绩、核心素养或 AI 主模型特征。
- `learning_analytics.services.dual_write.record_learning_event`：统一服务端写入入口。`dual_required` 模式下新旧记录在同一数据库事务中创建并互相追溯，新版记录校验失败时旧记录同步回滚；`v1_only` 只保留旧业务写入，用于紧急回退。
- `learning_analytics.services.dual_write.record_classroom_point_adjustment`：统一计算“旧评分替换为新评分”产生的实际积分增量，锁定学生缓存后写入旧业务记录、新版记录和积分流水；重复相同评分不重复记账。
- `learning_analytics.services.dual_write.reconcile_v1_v2_events`：底层兼容函数，检查旧记录是否存在唯一新版映射，并验证事件 UUID 和事件名。自动检查保存的阶段名称统一为 `compare_old_new_records`。
- `LearningEventRejection`：无效或冲突事件的短期隔离审计。原始 JSON 信封使用 Fernet 加密，保存 SHA-256、错误码、可重放状态和保留期限；超过 64KB 时只加密保存摘要并标记不可重放。
- `learning_analytics.services.access_audit.teacher_has_class_scope`：按学校和有效任课关系判断教师是否可查看班级个体分析，单纯教师角色不足以授权。
- `sync_learning_event_schemas`：将代码中 35 个事件模式同步到本地数据库；生产启动检查使用 `--check`，发现同版本模式哈希不一致时阻断运行。
- `purge_expired_event_rejections`：删除超过本地保留期限的加密拒绝记录；正式环境后续由 Celery beat 定时调用。
- 当前 app 已完成隐私权限、学习记录、学习任务关联、评分积分、新旧记录兼容写入和学习数据检查。历史旧记录使用确定性 UUID 回填，不能明确转换的记录以内部状态 `legacy.unmapped` 隔离，界面统一显示“旧事件未转换”。评价管理和试用记录已经完成；学习情况汇总和模型训练尚未完成。

机会状态当前只支持立即投放：`content.released` 的发生时间即实际开放时间。未来定时任务必须先增加 `content.assigned`，到点后再追加 `released`；不能把未来计划时间提前记成已开放。

计划新增但尚未迁移：

- `BadgeDefinitionVersion/StudentBadgeAward`：版本化奖章规则、证据和撤销。
- `SubjectCompetencyFramework/StudentCompetencyEvidence`：学科核心素养框架及任务证据，不从点击量或积分直接推断。

首批登记事件：

- `content.released`
- `content.withdrawn`
- `session.heartbeat`
- `resource.opened`
- `video.progress`
- `document.progress`
- `group.document.opened`
- `group.document.saved`
- `group.file.shared`
- `attendance.recorded`
- `quick_answer.responded`
- `random_call.selected`
- `item.submitted`
- `item.graded`
- `task.submitted`
- `learning_page.opened`
- `learning_page.block_viewed`
- `learning_page.form_submitted`
- `evaluation.rating.submitted`
- `intervention.created`
- `client.offline`

`content.released` 当前保留四个不可覆盖版本：

- `1.0`：按班级和 `target_layers` 展开机会。
- `1.1`：在保留层级范围的同时允许服务端提交唯一 `target_student_ids`，用于小组成员等明确对象集合；请求中的学生必须全部是当前班级启用学生，否则整次投放失败。
- `1.2`：保持 `1.1` 的显式对象集合能力，并新增 `attendance` 内容类型。签到不得回写或覆盖既有 `1.0/1.1` 契约。
- `1.3`：保持 `1.2` 能力，并新增 `interaction` 内容类型。用于抢答等可选课堂互动机会，不修改既有签到契约。

签到事实补充：

- `LearningOpportunity.content_type=attendance` 表示学生实际获得一次签到机会，不与题目、成绩或积分混用。
- `attendance.recorded` 载荷仅保存 `attendance_status`、`recorded_by`、`revision_no` 和可选前序事件 UUID；教师备注留在业务兼容记录。
- 学生来源只允许本人 `signed`，教师来源可记录 `signed/late/leave/absent`。统一接收层拒绝学生伪造教师考勤状态。
- 课堂结束后，已有状态的机会保留 `submitted`，无状态机会追加 `withdrawn`。分析时必须把未知未响应与明确缺勤分开。

课堂互动事实补充：

- `LearningOpportunity.content_type=interaction` 当前用于抢答的非必做机会；未响应不能计作未完成必做任务。
- `quick_answer.responded` 仅保存服务端计算的首次响应排名和响应延迟，回答正文留在业务兼容记录；重复提交幂等。
- `random_call.selected` 保存教师操作下的选择方法、候选人数、选择序次和既往入选次数。它不创建学生学习机会，不代表学生作答、完成或掌握。

`item.submitted` 当前保留两个不可覆盖版本：

- `1.0`：要求提供经过客户端有效计时的 `response_time_ms`。
- `1.1`：允许 `response_time_ms` 缺失，用于旧测试模块只能证明提交、不能重建单题时长的场景。缺失时字段省略，不写 0 或整场测试时长。

测试事实补充：

- `TestAttempt.analytics_attempt_id`：新旧测试记录共同使用的稳定 UUID；迁移时逐行生成后再添加唯一约束。
- 测试开启后，每个目标班级和试题快照生成 `content.released`，题目版本为题干、选项、答案、解析、知识点和分值快照的 SHA-256。
- 每道题先写 `item.submitted`，再写 `item.graded`。客观题使用 `final/automatic`；主观题提交时使用无实际得分的 `pending`，教师完整批阅后写 `final/teacher`，复评分写 `revised/teacher`。
- 测试结束先提交仍在作答的答卷，再对尚未完成的机会追加 `withdrawn`；已经提交或评分的机会保留原事实。

## AI 学习网页

- `LearningWebPage`：教师在某门课程、某个课时中创建的受控学习网页，保存当前 JSON schema、当前版本和原始生成要求。
- `LearningWebPageVersion`：每次 AI 生成或修改后的不可变版本快照，用于追溯修改过程和后续回滚扩展。
- `LearningWebPageResponse`：学生对某个网页表单的提交，记录网页版本、表单编号、学生、班级、课时环节、课堂场次、结构化回答、尝试次数和唯一 `analytics_attempt_id`。
- `LessonStep.resource_items` 通过 `kind=learning_page`、`learning_page_id` 绑定网页，沿用现有资源顺序和课堂投放流程。
- `LearningWebPage.schema.blocks` 支持受控 `visualization` 区块，类型限定为 `process/timeline/bars/binary`；只保存结构化动画数据，不保存或执行 AI 生成的 HTML、CSS、JavaScript。
- `LearningWebPage.schema.blocks` 也支持 `interactive`，保存受长度限制的 `html/css/javascript/height`；代码只在无同源权限、无网络权限的嵌套沙箱中执行，不作为平台业务代码运行。
- 网页表单回答属于过程性学习行为，可聚合为参与度、选择分布、量表变化、反思文本和任务达成特征；不能直接作为分层 label。
- 网页随课堂环节投放时生成学生级 `learning_page` 机会；`opened` 记录打开方式，`block_viewed` 只记录受控区块 ID/类型、可见时长和比例，`form_submitted` 只引用业务响应及尝试 UUID。
- 页面正文、交互脚本和表单答案均不复制到 `LearningEventV2`。区块行为采集失败不得阻断学生继续浏览或提交。
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

## 教学资源中心

- `Resource.public_id`：跨校交换使用的稳定 UUID，不依赖各校数据库自增编号。
- `Resource.resource_type`：`file/article/link/student_project`。
- `Resource.visibility`：`private/classes/school/external`。
- `Resource.publish_status`：`published/pending/approved/rejected/archived`。资源中心不设草稿；个人、班级和校内资源保存即发布，跨校资源进入审核状态。
- `Resource.subject`、`grade_scope`、`tags`：资源检索和推荐元数据。
- `Resource.target_classes`：指定班级共享范围，只允许教师本人任教班级。
- `Resource.project_type`、`project_members`、`project_course`、比赛信息：学生项目展示元数据。
- `ResourceFile`：一个资源的补充文件。普通资源角色为 `supplement`，学生项目过程材料角色为 `process`。

学生项目的日志、甘特图和阶段成果通过 `ResourceFile(role=process)` 保存，全部为选填。学生浏览资源写入 `LearningEvent.resource_view`，`object_type=resource_center`。

## 学习数据检查

- `EventIngestionDailyCounter`：按学校、自然日和来源记录学习事件的接收、重复、拒绝、延迟与离线数量。历史转换记录不计入实时接收数量。
- `AnalyticsPipelineRun`：学校级自动检查任务。当前 `pipeline_type=data_quality`，触发方式为定时、手动或重试。
- `AnalyticsPipelineRun.retry_of/attempt_no`：追加式重试链。重试生成新运行，不覆盖失败运行；同校、同窗口的 scheduled 运行具有条件唯一约束。
- `AnalyticsTaskRun`：自动检查的执行阶段，保存状态、指标、错误和起止时间。
- `DataQualityReport`：一次检查最多生成一份不可修改的报告，保存七项检查指标、判断标准、来源数量和待处理问题。
- `DataQualityReport.checks_passed`：本次检查是否通过。
- `DataQualityReport.receive_attempt_count/rejected_event_count`：接收尝试数和拒绝记录数。
- `DataQualityReport.unconverted_old_event_count/unlinked_old_event_count`：未转换和未关联的旧记录数量。
- `DataQualityReport.unconverted_old_event_rate/learning_task_link_rate/old_new_event_difference_rate`：旧记录转换、学习任务关联和新旧记录核对结果。
- `DataQualityReport.check_version/source_checksum`：检查规则版本和来源校验码。

检查报告不可原地修改或直接删除；重新检查必须产生新运行和新报告。检查结果只控制后续分析是否继续，禁止写入学生能力特征、核心素养得分、积分或奖章。

## 模拟数据开发

- `School.is_synthetic`：区分正式运营学校与模拟数据学校，默认 `false`。
- `SyntheticDatasetRun`：保存 `isolated_school/school_overlay` 模式、生成器版本、数据集指纹、随机种子、窗口、配置、计数、状态、清理摘要和清单 SHA-256。
- `SyntheticStudentTruth`：保存模拟生成所需的连续隐藏潜变量；不进入正式特征、API 或学生档案。
- `LearningEventV2.synthetic_run`：模拟事件到生成批次的不可变来源关联。
- `AnalyticsPipelineRun.synthetic_run`、`DataQualityReport.synthetic_run`、`EventIngestionDailyCounter.synthetic_run`：隔离正式记录和指定测试批次。

正式夜间检查排除 `is_synthetic=true` 的模拟学校；正式学校检查报告始终排除已关联 `synthetic_run` 的测试事件和计数。模拟事件仍通过正式写入、任务关联和评分服务生成，以验证程序，详细边界见[模拟数据开发说明](synthetic_data_research_track.md)。

## 教师评价标准管理

- `EvaluationPlan`：教师为本人课程维护的评价方案，保存课程、适用学生、学习目标、评价依据、学习任务、评价内容、思维要求、可用帮助、评分规则和后续教学建议。
- `EvaluationPlanVersion`：已发布的评价方案版本。相同内容不重复发布，修改后生成下一版本。
- `EvaluationStandard`：教师为本人课程维护的评价标准，绑定评价方案并保存评价对象和评价指标。
- `EvaluationStandardVersion`：已发布的评价标准版本，必须绑定对应的评价方案版本。
- `EvaluationCriterionVersion`：单项评价指标，保存评价方面、材料来源、具体表现、暂不评价条件、可用帮助、常见问题、1-5 星表现说明和后续教学建议。
- `EvaluationScoringExample`：评价指标的评分示例，登记星级、示例说明和可选材料引用。
- `EvaluationTrialRecord`：评价试用与审核记录，绑定已发布评价标准版本，保存记录类型、日期、参与人数、状态、评分一致率、处理结论、问题和后续安排。
- `LessonStepEvaluationBinding`：一个课时环节选择一个已发布评价标准版本，并设置自评、互评和教师评价。绑定一旦被课堂使用即不可原地修改或删除。
- `ClassroomEvaluationStandardUse`：某次课堂首次开启评价时冻结环节、标准版本、评价方式和完整指标快照，后续切换环节或编辑工作稿不改变历史记录。
- `EvaluationSubmissionEvidence`：把课堂评价提交关联到同一课堂、同一环节、同一被评价学生的最新 `LessonStepAttempt` 和最新 `StudentWorkAttachment`。没有匹配材料时允许为空，不以低星代替缺失材料。
- `ClassroomEvaluationSubmission.not_assessed`：按评价指标 ID 保存原因代码和最多 200 字说明；原因是“其他”时说明必填。该字段与 `ratings` 互斥，平均值不读取暂不评价项。

实际表名和字段名已通过 `learning_analytics.0013-0015` 迁移到评价命名；迁移 `0018` 新增评价试用记录，迁移 `0019` 新增课时评价绑定和课堂证据链，`courses.0025` 新增暂不评价结构，`learning_analytics.0020` 修复旧事件登记哈希。已完成记录由 API 禁止修改和删除。完整约束见[教师评价标准管理](evaluation_management.md)。

旧随机点名 `ClassroomActivity.metadata.picked_student` 可能含历史层级字段。新写入不再保存层级；学生 DTO 使用 `sanitize_student_payload` 清理历史受限字段，教师端证据不变，最终 `StudentPrivacyJSONRenderer` 仍执行阻断复查。
