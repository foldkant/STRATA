# STRATA 术语规范

本规范用于界面、API、数据库、代码和开发文档。新增功能不得重新引入已经停用的旧名称。

## 平台统一名称

| 统一名称 | 代码与数据库名称 | 含义 |
| --- | --- | --- |
| 评价标准管理 | `evaluation` | 教师维护本人课程的评价方案、标准和版本 |
| 评价方案 | `EvaluationPlan` | 学习目标、评价依据、学习任务和评分规则 |
| 评价方案版本 | `EvaluationPlanVersion` | 已发布、不可直接修改的方案版本 |
| 评价标准 | `EvaluationStandard` | 一组可用于课程和任务的评价指标 |
| 评价标准版本 | `EvaluationStandardVersion` | 已发布、不可直接修改的标准版本 |
| 评价指标 | `EvaluationCriterionVersion` | 单项评价内容 |
| 评价方面 | `dimension` | 任务质量、学习方法、自我管理、合作、学科实践或规范责任 |
| 具体表现 | `expected_performance` | 教师实际可以检查的学生表现 |
| 暂不评价条件 | `skip_condition` | 缺少足够材料时不评价该项 |
| 星级说明 | `level_descriptions` | 1-5 星分别对应的具体表现 |
| 评分示例 | `EvaluationScoringExample` | 帮助教师统一判断的示例 |
| 评价试用记录 | `EvaluationTrialRecord` | 内容审核、课堂试用、评分培训和评分一致性检查记录 |
| AI 辅助起草评价 | `EvaluationAIDraftSession` | 教师以课程标准和课程内容为依据，请 AI 提供可编辑评价初稿的过程；不得简称“自动评价” |
| 评价方式建议 | `mode_suggestion` | AI 根据学习目标、课程内容和评价用途提出的测试、操作、项目、作品、答辩或混合评价建议，须由教师确认 |
| AI 评价初稿 | `draft_payload` | 尚未经过教师专业复核的学习目标、评价任务、评价依据、评价指标、表现水平和后续教学建议 |
| 教师处理记录 | `teacher_revision` | 教师对 AI 初稿逐项采纳、修改、删除或恢复的可追溯记录 |
| 自动检查结果 | `validation_report` | 对课标引用、目标与任务对应关系、个人/小组材料归属及必填内容进行的工程检查；不代替教师专业判断 |
| 评价版本 | `evaluation_version` | 课堂评价提交所使用的版本 |
| 评价提交事件 | `evaluation.rating.submitted` | 自评、互评或师评的逐项星级记录 |
| 课程标准管理 | `curriculum_standards` | 超级管理员管理权威课程方案、学科课程标准及其历史版本 |
| 课程标准 | `CurriculumStandard` | 同一学段、文件类型和学科下各历史版本的管理主记录 |
| 课程标准版本 | `CurriculumStandardVersion` | 保存原始 PDF、来源、可检索文本、文件校验值和状态的不可变发布版本 |
| 逐页可检索文本 | `CurriculumStandardPage` | 按 PDF 页码保存的文本、提取方式、处理质量和复核状态；不得简称“AI 文本” |
| 课程标准内容条目 | `CurriculumStandardNode` | 经复核的核心素养、课程目标、课程内容或学业质量原文条目；普通界面不简称“节点” |
| 原文位置 | `source_page_start` / `source_page_end` / `source_paragraph` | 课程标准内容条目对应的 PDF 页码、章节或段落位置 |
| 当前使用版本 | `CurriculumStandard.current_version` | 新建评价方案默认引用的已发布版本；历史评价仍保留原版本 |
| 恢复为当前使用版本 | `restore_version` | 将一个历史已发布版本重新设为当前使用版本；不删除或改写其他版本 |
| 信息科技 | 义务教育学科显示名称 | 用于 K1—K9；引用《义务教育信息科技课程标准》时不得改称“信息技术” |
| 信息技术 / 信息科技 | 普通高中信息学科的版本化正式名称 | 2020 年修订版沿用“信息技术”，2025 年修订版 PDF 正式题名使用“信息科技”；引用时必须保留所引用版本的正式题名，检索可使用同一学科别名 |
| 分层建议 | `StratificationDecision` | 面向任课教师的学习内容安排候选，必须由教师审核后生效 |
| 学习内容层级 | `StudentSubjectBand` | 某学科或课程在限定有效期内的内部教学内容安排，不是学生能力身份 |
| 学习内容层级标准 | `ContentBandPolicyVersion` | 生成学习内容层级建议所使用的版本化标准、边界与拒绝规则 |
| 分组候选方案 | `GroupingCandidateRun` | 针对具体课堂任务和约束生成、供教师比较调整的候选结果 |
| 分组计划 | `GroupingPlanVersion` | 教师针对具体任务确认的成员与角色安排，不是永久学生群体 |
| 学习数据检查 | `DataQualityReport` | 学校管理员检查学习记录是否完整、可转换并关联到学习任务 |
| 检查是否通过 | `checks_passed` | 当前报告能否继续后续分析 |
| 接收尝试数 | `receive_attempt_count` | 有效、重复和拒绝接收记录的合计 |
| 拒绝记录数 | `rejected_event_count` | 因格式或上下文错误未被接收的记录数量 |
| 旧事件未转换数 | `unconverted_old_event_count` | 不能按明确规则转换的旧记录数量 |
| 未关联旧记录数 | `unlinked_old_event_count` | 尚未建立新版对应记录的旧记录数量 |
| 学习任务关联率 | `learning_task_link_rate` | 需要关联任务的记录中已正确关联的比例 |
| 新旧记录差异率 | `old_new_event_difference_rate` | 新旧记录核对后存在差异的比例 |
| 检查版本 | `check_version` | 本次检查使用的规则版本 |
| 来源校验码 | `source_checksum` | 用于确认检查来源数据未被替换的校验值 |
| 新版学习事件 | `LearningEventV2` | 当前学习行为记录模型；文档正文不简称为“V2 事件” |
| 旧记录追溯关系 | `LearningEventV2.legacy_event` | 内部兼容字段；界面和普通文档不使用“legacy”作为栏目名 |
| 旧事件未转换 | `legacy.unmapped` / `legacy_unmapped` | 内部兼容事件名和状态值；界面、API 标签和导出统一显示“旧事件未转换” |
| 自动检查记录 | `AnalyticsPipelineRun` | 保存定时、手动和重试检查；数据库状态 `blocked` 显示为“检查未通过” |
| 自动检查阶段 | `AnalyticsTaskRun` | 当前阶段代码为 `collect_learning_data`、`compare_old_new_records`、`save_data_check_report` |
| 分析时间点 | `DecisionPoint` | 固定班级、课程、学生范围和当时数据的时间 `T0`；界面不使用 landmark |
| 当时可用数据 | `operational_available` | 行为发生和服务器接收都不晚于分析时间点的数据 |
| 事后完整数据 | `reconstructed_complete` | 只用于补传影响检查的事后视图，不用于报告实际模型效果 |
| 学习指标 | `FeatureDefinition` | 保存计算规则、窗口、分子、分母、缺失原因和版本的学习事实 |
| 学生特征快照 | `StudentFeatureSnapshot` | 某学生在分析时间点的多窗口学习指标记录；普通界面简称“学习记录快照” |
| 未来结果 | `OutcomeObservation` | 分析时间点之后预先指定的完成或逾期结果；未观察到时不记为 0 |
| 数据版本 | `TrainingDatasetVersion` | 固定指标、未来结果、分组和来源摘要的匿名数据清单 |
| 测试数据批次 | `TestDataBatch` | 保存历史或手工测试数据的唯一用途、来源、精确对象清单和清单校验值；不替代现有合成数据批次 |
| 测试数据对象标记 | `TestDataObjectMarker` | 按应用、模型和主键登记到测试数据批次的审计记录；误标时只撤销生效状态并保留原登记、撤销人、时间和原因 |
| 数据用途 | `TestDataBatch.purpose` | 开发测试、验收测试、迁移验证或研究沙盒；任一用途都不能自动升级为正式教学、正式统计或正式研究 |

## 角色用语

- 学校管理员：账号与班级管理、学习数据检查、分层运行汇总。
- 教师：课程备课、评价标准、课时设计、课堂教学、测试、学生管理、分层建议。
- 学生：课程学习、实时课堂、测试、资源和学习档案。
- 超级管理员：学校管理、课程标准管理、跨校数据采集、跨校分析和系统健康。

## 教育语义边界

- 课程标准原文不能直接生成学生得分、学习内容层级或分组计划。
- AI 辅助起草评价只能生成教师可编辑初稿；未经教师逐项复核、试用和发布，不得进入课堂、评分、动态分层或动态分组。
- “AI 建议评价方式”必须使用“测试、操作、项目、作品、答辩、混合评价”等教育领域表达，不使用“任务策略路由”“测量管线”等工程术语作为教师界面栏目。
- 学科名称随学段和版本使用正式题名：义务教育 2022 年版称“信息科技”；普通高中 2020 年修订版称“信息技术”，2025 年修订版正式题名称“信息科技”。档案检索可以归一到同一学科身份，但不得据此改写历史版本题名。
- 评价结果、学习状态、学习内容层级和分组计划是不同对象；不得在界面、接口或导出中互相替代命名。
- “动态分层”是业务领域名称；教师操作统一称“分层建议”或“学习内容层级建议”，不得向学生显示 A/B/C 或内部判断依据。
- 分组只服务具体任务和阶段。内容层级可以作为受限参考之一，但不能直接复制为同层组或异层组。
- 评价材料不足时称“暂不评价”；学习证据不足时称“暂不建议”或“需要补充学习材料”，不得统一写成低表现。
- 课程标准的技术对象 `CurriculumStandardNode` 在普通界面称“课程标准内容条目”；“节点”只用于代码和开发文档。
- 标题中的 `test`、`SIM`、数字或“测试”字样不能单独证明对象属于测试数据；历史或手工测试对象必须登记到明确的测试数据批次。合成数据继续使用 `SyntheticDatasetRun`，不得建立第二套同义批次真值源。

## 停用名称

以下名称不得出现在新的界面、API、模型、字段或当前功能说明中：

- 测量设计
- 任务蓝图
- 学习主张
- 证据规则
- 任务规格
- 认知复杂度
- 五星量规
- 量规条目
- 锚点、锚定样例
- `NOT_ASSESSED`
- `local_formative`、`school_common`、`research_linked`
- `AssessmentBlueprint*`、`Rubric*`、`MeasurementUse`
- `rubric_version`、`rubric.rating.submitted`
- `gate_passed`、`ingestion_attempt_count`、`rejection_count`
- `legacy_unmapped_count`、`unlinked_legacy_count`
- `semantic_missing_rate`、`opportunity_coverage_rate`、`v1_v2_difference_rate`
- `methodology_version`、`source_fingerprint`
- 数据闸门、语义缺失率、机会关联覆盖率、V1/V2 差异率

历史迁移文件和 Git 标签可以保留旧名称，因为它们记录已经发生的数据库和版本演进；当前模型、表、字段、接口和文档必须使用统一名称。

## 兼容名称

以下代码名称暂时保留以避免破坏已部署学校、历史数据或已有客户端，但不得扩散成新的菜单、字段或文档标题：

- API 路径 `/api/v1/school-admin/analytics/quality/`：路径保持兼容，页面和接口说明称“学习数据检查”。
- `AnalyticsPipelineRun.PipelineType.DATA_QUALITY` 及数据库值 `data_quality`：内部枚举保持兼容，显示名称为“数据检查”。
- `DataQualityReport`、`EventIngestionDailyCounter`、`require_quality_checks`、`run_nightly_data_quality`：现有类名和函数名暂时保留；正文分别称“检查报告、学习事件每日接收记录、确认检查通过、执行夜间学习数据检查”。
- 文件 `learning_analytics/services/quality.py`、文档文件 `data_quality_pipeline.md` 和前端路由 `/app/school-admin/data-quality`：路径暂时保持兼容，页面标题、导航和正文统一使用“学习数据检查”。
- `LearningEventV2`、`backfill_learning_event_v2`、`reconcile_v1_v2_events`：真实类名、命令或底层函数可以原样出现在代码引用中，正文分别称“新版学习事件、历史旧记录回填、新旧记录核对”。
- `LEARNING_EVENT_WRITE_MODE=v1_only`：紧急回滚配置值保持不变，文档解释为“只写旧业务记录”。

旧名称只能出现在迁移映射、历史 Git 标签、停用名称清单和说明旧名称已被移除的审查记录中。

## 研究文档

论文设计中可以使用效度、测量误差、评分一致性、评分锚点、IRT、DIF 和数据质量等必要学术概念，但首次出现时必须用一句中文解释，并与平台按钮、菜单和数据库名称分开。例如，研究文档可讨论“数据质量”，当前产品模块仍统一称“学习数据检查”；研究文档可讨论“评分锚点”，平台字段和表单仍统一称“星级表现说明”。研究术语不能直接成为普通教师或学生界面的栏目名称，也不能反向成为新的数据库表名、字段名、接口名或开发任务名。

## 文档同步范围

每次调整统一名称时，至少检查以下文件：

- 根目录 `README.md` 和 `docs/README.md`。
- `api_contract.md`、`data_model.md`、`private_deployment.md`。
- 对应角色设计文档和专题设计文档。
- 开发路线图、进度审计、模拟数据说明和历史审查结论。

迁移文件、历史 Git 标签和必须保持兼容的代码路径可以保留旧名称，但必须在附近注明当前中文名称。除停用名称清单和历史变更说明外，文档正文不得继续使用已经停用的旧名称。
