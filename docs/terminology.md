# STRATA 术语规范

本规范用于界面、API、数据库、代码和开发文档。新增功能不得重新引入已经停用的旧名称。

## 平台统一名称

| 统一名称 | 代码与数据库名称 | 含义 |
| --- | --- | --- |
| 评价管理 | `evaluation` | 学校管理员维护本校评价内容 |
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
| 评价版本 | `evaluation_version` | 课堂评价提交所使用的版本 |
| 评价提交事件 | `evaluation.rating.submitted` | 自评、互评或师评的逐项星级记录 |
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

## 角色用语

- 学校管理员：评价管理、学习数据检查、分层分析。
- 教师：课程备课、课时设计、课堂教学、测试、学生管理、分层建议。
- 学生：课程学习、实时课堂、测试、资源和学习档案。
- 超级管理员：学校管理、跨校数据采集、跨校分析和系统健康。

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
