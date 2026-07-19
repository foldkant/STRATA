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

## 研究文档

论文设计中可以使用效度、测量误差、评分一致性、IRT、DIF 等必要学术概念，但首次出现时必须用一句中文解释，并与平台按钮、菜单和数据库名称分开。研究术语不能直接成为普通教师或学生界面的栏目名称。
