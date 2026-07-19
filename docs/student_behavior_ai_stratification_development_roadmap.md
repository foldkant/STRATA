# STRATA 学生行为分析与 AI 隐性动态分层开发路线图

> 状态：工程执行基线。  
> 版本：1.0，2026-07-18。  
> 科学与产品依据：[AI 隐性动态分层设计报告](student_behavior_ai_stratification_design.md)。  
> 适用范围：Django/DRF、Vue 3、PostgreSQL、Redis、Celery、Channels 和学校离线私有化部署。

## 当前实施状态

| 工作项 | 状态 | 当前结果 |
| --- | --- | --- |
| `ARCH-01` analytics 领域骨架 | 基础完成 | 已创建 `learning_analytics` app、独立 `api/analytics/` 路由包和测试目录；前端教师工作台 feature 在 M4 建立 |
| `PRIV-01A` 学生字段泄漏审计 | 完成 | 已覆盖学生主要 REST、课堂 WebSocket、分层题、小组、互评、对象下载和原始媒体直链；后续每新增学生接口继续执行字段白名单测试 |
| `PRIV-01B` 任课权限和访问审计 | 基础完成 | 已建立安全运行状态、任课范围判断和不可变敏感推断访问日志；待 M4 教师分层接口接入 |
| `DATA-01A` 事件注册表与事件 V2 | 完成 | 已建立 25 个 Pydantic 严格事件模式、不可覆盖的 `EventSchemaDefinition`、不可变 `LearningEventV2`、同步命令、迁移和测试 |
| `DATA-01B` 批量接收与幂等 | 完成 | 已建立每批最多 200 条的 API、双重幂等、双时间戳、乱序/迟到标记、加密拒绝隔离、角色与跨校作用域测试 |
| `DATA-02A` 学习机会与撤回事实 | 完成 | 已建立学生级不可变机会分母、追加式状态事实、分层投放展开、机会归属/版本校验、撤回与离线早到证据测试 |
| `DATA-02B` 评分成熟状态与积分流水 | 完成 | 已建立不可变评分版本、待评/最终/修订成熟状态、同尝试校验、积分幂等/冲正/非负余额和旧分数缓存对账服务 |
| `DATA-01C` 统一写入与 V1/V2 双写 | 进行中 | 已建立事务双写、回滚和对账；课堂积分/聊天、测试、课堂题目/附件、AI 学习网页、课堂普通资源、五星评价、小组协作、签到、抢答及随机点名已接入 |
| `INCENTIVE-01` 积分奖章边界 | 积分底座完成 | 积分与成绩、量规、核心素养和 AI 建议分离；奖章仍在量规和证据框架完成后开发，不提前进入主模型 |
| M0 总体 | 工程闸门完成 | SQLite/PostgreSQL 全量测试、Redis/Channels、Celery worker/beat 和实际任务已验证；学校生产部署仍需完成密码、服务账号和备份恢复验收 |
| M1 总体 | 进行中 | `DATA-01A/01B/02A/02B` 完成，`DATA-01C` 已覆盖课堂积分、测试、题目/附件、AI 网页、课堂资源、五星评价、小组协作、签到、抢答和随机点名；下一步迁移其余课堂控制与普通学习入口 |

## 0. 路线总则

开发顺序固定为：

```text
架构与隐性安全基线
  -> 研究级事件、机会和结果事实
  -> 量规、题目与共同测量
  -> 特征、计划决策点和结局
  -> 教师可见/学生隐性的规则影子版
  -> 冻结数据上的离线模型实验
  -> 班级校准、签名发布和生产监测
  -> 校内前瞻性试点
  -> 跨校独立复验与统一分析
```

不允许跳过数据与测量阶段直接训练生产模型。当前开发库数据只能用于接口、迁移和回放测试，不能用于报告模型效果。任何里程碑只有在“代码、测试、文档、迁移、回滚和数据质量”同时完成后才能关闭。

路线中的 Sprint 只表示相对工程量，默认以一名熟悉项目的全职开发者配合学科教师、研究人员和学校 IT 为参考，不是交付承诺，也不能代替正式研究的样本量与时间设计。

## 1. 当前基线与差距

| 领域 | 当前状态 | 路线要求 |
| --- | --- | --- |
| 学习事件 | [learning/models.py](../learning/models.py) 中 `LearningEvent` 使用粗粒度类型和自由 `metadata` | 新增版本化事件信封、事件注册表、机会分母、幂等和迟到语义；旧表双写后逐步只读 |
| 特征 | `StudentFeatureSnapshot` 仅有窗口和自由 JSON | 增加特征定义、学科、`as_of`、分母、缺失码、质量状态和代码版本 |
| 分层建议 | `StratificationDecision` 只有单一置信度和接受/拒绝 | 拆分模型候选、教师决定和有效内容带；支持保持、调整、延后、不确定性和 `abstain` |
| 学生层级 | `StudentProfile.current_layer` 是全局单字段 | 迁移为按学生 × 学科 × 可选课程 × 有效期的 `StudentSubjectBand`；旧字段只作过渡缓存 |
| 训练 | [aiops/tasks.py](../aiops/tasks.py) 仍是成功占位任务 | 先建设事实与影子推理；真实数据成熟后才实现冻结实验、候选模型和部署任务 |
| 教师前端 | `/teacher/stratification` 仍使用占位页面 | 建设教师私有审核工作台、证据抽屉、迁移历史和投屏隐私模式 |
| 学生前端 | 没有分层页面，这是正确方向 | 保持无分层入口；现有学生 API 必须审计并剥离层级、概率、分组策略和候选变体 |
| API 组织 | `api/views.py`、`api/services.py` 已超过适合继续扩展的规模 | 新能力进入独立 `api/analytics/` 包和领域服务，不继续堆入旧大文件 |
| 正式运行环境 | 本机可用 SQLite；生产设计为 PostgreSQL、Redis、Celery | 从需要约束、并发和夜间任务的 M1 开始，正式试点只以 PostgreSQL/Redis 结果验收 |

当前代码中教师接口和共享序列化逻辑存在 `current_layer`、`target_layer`、`layer_scores` 等字段。M0 必须逐个审计所有学生响应，不能仅依据某个首页测试已经隐藏 `current_layer` 就认定课堂、课程、资源、WebSocket 和下载均安全。

## 2. 目标工程结构

### 2.1 Django 领域边界

新增 `learning_analytics` 应用，避免继续把前测、题库、测试、行为、特征和模型全部放在 `learning`：

```text
learning_analytics/
  models/
    events.py
    opportunities.py
    measurement.py
    features.py
    outcomes.py
    decisions.py
    governance.py
  services/
    event_ingestion.py
    opportunity_builder.py
    feature_builder.py
    outcome_builder.py
    decision_policy.py
    assignment_resolver.py
    access_audit.py
  tasks/
    quality.py
    snapshots.py
    inference.py
    monitoring.py
  schemas/
    registry.py
    payloads/
  tests/
```

保留现有 `learning` 业务模型，不做一次性大搬迁。`LearningEvent`、`StudentFeatureSnapshot` 和 `StratificationDecision` 作为 V1 兼容源，使用新增 V2 表双写、对账和渐进切换。`aiops` 只负责模型实验、版本、校准、签名、部署和监测，不负责课堂业务写入。

API 新增独立命名空间：

```text
api/analytics/
  urls.py
  permissions.py
  teacher_views.py
  student_views.py
  school_admin_views.py
  serializers/
```

教师与学生使用完全分离的 Serializer/DTO。禁止使用一个大序列化器再通过可选参数决定是否删除层级字段。

### 2.2 Vue 领域边界

```text
frontend/src/features/stratification/
  api/
  components/
  composables/
  types/
  views/teacher/
  views/school-admin/
  tests/
```

学生端不建立“我的层级”页面。学生课程、课堂和任务页面通过普通学习清单接口接收服务端已经解析好的内容；前端不接收全部变体后自行过滤。

### 2.3 数据流

```text
教学业务操作
  -> 统一事件发布服务
  -> LearningEventV2 + LearningOpportunity + 评分/积分/干预事实
  -> Celery 数据质量与计划快照
  -> FeatureSnapshot + OutcomeObservation
  -> aiops 冻结实验/推理
  -> StratificationDecisionCandidate
  -> 任课教师私有审核
  -> StudentSubjectBand
  -> AssignmentResolver
  -> 学生学习清单（无层级字段）
```

## 3. 里程碑总览

| 里程碑 | 参考工程量 | 主要结果 | 前置 | 结束后允许做什么 |
| --- | ---: | --- | --- | --- |
| M0 架构与隐性安全基线 | 1-2 Sprint | 新模块骨架、权限边界、学生字段泄漏审计、正式环境基线 | 无 | 安全地继续采集现有业务数据 |
| M1 研究级事实层 | 2-3 Sprint | 事件 V2、机会、评分/积分/干预事实、双写和质量报告 | M0 | 可靠描述“发生了什么、谁获得了什么机会” |
| M2 测量与题目层 | 2-3 Sprint | 评价蓝图、量规版本、AI 题生命周期、共同锚测 | M1 | 形成可验证的任务和测量数据 |
| M3 特征与结局层 | 2-3 Sprint | 计划决策点、特征注册、结局合同、夜间无模型 DAG | M1/M2 | 生成冻结、可重算的训练候选数据 |
| M4 隐性分层影子版 | 2-3 Sprint | V0 规则、教师工作台、学生隐性投放、管理员聚合 | M3 | 教师试用建议，但不自动改变学生内容带 |
| M5 离线模型实验 | 3-5 Sprint，且等待真实结局成熟 | M00-M06 比较、外层验证、模型卡和候选结论 | M3 数据闸门 | 选择是否存在优于透明基线的候选模型 |
| M6 生产模型闭环 | 2-4 Sprint | 班级校准、签名模型包、shadow/canary/champion、回滚 | M5 通过 | 小范围教师审核模式运行候选模型 |
| M7 校内前瞻性试点 | 至少覆盖完整教学单元，研究可覆盖一学期 | 教师培训、实施忠实度、决策效用和安全评估 | M4/M6 | 决定是否扩大校内范围和开展效果研究 |
| M8 跨校复验与统一分析 | 第二所及以上学校准备完成后 | 去标识研究包、独立外校验证、跨校异质性 | M7 | 支持受限的跨校主张和后续论文 |

## 4. M0：架构与隐性安全基线

### 开发任务

1. 建立 `learning_analytics` Django app、`api/analytics/` 包和前端 feature 目录，只搭骨架，不搬迁无关旧代码。
2. 建立 `AnalyticsOperatingMode` 安全状态：`collect_only`、`shadow`、`teacher_review`、`active`、`suspended`。这是模型安全状态机，不是面向用户的通用功能开关；默认 `collect_only`。
3. 审计所有学生 REST、WebSocket、HTML、下载和缓存响应中的 `current_layer`、`target_layer`、`target_layer_label`、`layer_scores`、`confidence`、分组策略和未分配内容变体。
4. 为学生接口增加响应 schema 测试；教师对象级权限必须验证实际任教关系，不能只验证角色是教师。
5. 约定新 analytics 代码不能继续加入 `api/views.py` 和 `api/services.py`；旧代码只在接入统一事件服务时做局部修改。
6. 准备正式试点 PostgreSQL/Redis 配置、备份、Celery worker/beat、时区和日志目录；SQLite 仅保留本机界面开发。
7. 冻结术语、数据目的、禁止采集项、隐性分层规则和文档优先级。

### 交付物

- 新应用与 URL 空骨架。
- 学生响应字段白名单和教师权限测试集。
- 当前事件写入点清单与 V2 映射表。
- 数据库迁移/回滚模板、ADR 和安全审查记录。
- 正式试点环境健康检查清单。

### M0 闸门

- 学生无法通过 API、URL 枚举、WebSocket、浏览器缓存或文件名获得层级和分组依据。
- 教师不能查看非本人任教班级的个体分层信息。
- 新 analytics 模块可在 SQLite 开发环境和 PostgreSQL 验证环境启动。
- 尚未新增任何自动分层或模型训练行为。

2026-07-19 工程验收已通过。验证证据、限制和后续固定顺序见[学生行为分析工程进度审计](implementation_progress_audit.md)。本机便携 PostgreSQL/Redis 只用于组件真实性验证，不替代学校生产部署安全验收。

## 5. M1：研究级事实层

### 当前实现

- `DATA-01A` 已完成：迁移 `learning_analytics.0002` 新增事件模式和事件 V2 表。
- `DATA-01B` 已完成：迁移 `learning_analytics.0003` 新增服务端幂等键、事件指纹和加密拒绝隔离表；批量 API 支持逐条 `accepted/duplicate/rejected`。
- `DATA-02A` 已完成：迁移 `learning_analytics.0004` 新增 `LearningOpportunity`、`LearningOpportunityTransitionFact` 和事件机会外键；投放、撤回与结果事件在同一事务内维护机会事实。
- `DATA-02B` 已完成：迁移 `learning_analytics.0005` 新增 `AssessmentResultFact` 和 `ParticipationPointLedger`；`item.graded` 已在同一事务内生成评分版本，待评分不作为最终 0 分，修订必须追加并引用既有成熟版本。
- 积分服务已统一单次增减上限、非负余额、来源事件幂等、反向冲正和 `StudentProfile.score` 缓存对账；抢答、随机点名和聊天扣分已通过统一服务接入，旧历史分数仍不能直接当作完整研究流水。
- 代码注册表当前包含设计报告核心载荷、`content.released@1.1/1.2/1.3`、`content.withdrawn@1.0`、`item.submitted@1.1`、AI 学习网页、课堂资源、小组协作、签到和课堂互动事件，共 25 个模式。既有 `content.released@1.0/1.1/1.2` 语义不覆盖，`1.3` 专门扩展非必做 `interaction` 机会类型。
- 已新增 `sync_learning_event_schemas`，同一个 `event_name + schema_version` 的语义哈希不一致时禁止覆盖。
- `DATA-01C` 首批新增迁移 `learning_analytics.0006`，以 `LearningEventV2.legacy_event` 建立一对一追溯。统一服务在同一事务内写入 V1/V2，任一失败整体回滚；`LEARNING_EVENT_WRITE_MODE=v1_only` 仅用于紧急业务回滚。
- `reconcile_learning_event_writes --check` 可按全平台或学校检查缺失与错误映射。尚未迁移的入口见 [学习事件 V1 写入点与 V2 迁移清单](learning_event_write_inventory.md)。
- 测试开启按班级和题目生成学生级机会；学生主动交卷使用 `student-web`，超时/教师结束触发的自动交卷使用 `server`。客观题生成 `final` 自动评分，主观题先生成空得分 `pending`，教师批阅及复评追加 `final/revised`。
- `TestAttempt.analytics_attempt_id` 使用三步数据迁移为已有和新答卷生成唯一 UUID。测试关闭先自动提交在途答卷，再撤回未完成机会；已有答卷的测试不能原地重开，必须复制为新轮次。
- 迁移 `learning.0008` 新增不可变追加式 `LessonStepAttempt`、`LessonStepAttemptAnswer`，并为 `StudentWorkAttachment` 增加提交 UUID、上传版本和前序版本引用。课堂答案正文和附件留在业务表，V2 不复制原文或文件地址。
- 教师投放课堂环节时按题目、适用带和题目版本生成学生级机会；文件题使用任务机会，其他题使用题目机会。关闭、替换环节或结束课堂时只撤回未提交机会。
- 客观课堂题在提交事务内生成 `final/automatic`，简答题和附件先生成无分数 `pending`；附件教师评分与复评追加 `final/revised`。同一机会的多次提交按尝试追加状态，不再被最早提交状态吞并。
- 迁移 `courses.0018` 为每次 `LearningWebPageResponse` 生成唯一分析尝试 UUID。页面随环节投放生成机会；区块可见只采集页面版本、区块 ID/类型、可见时长和比例，表单答案不进入 V2。
- 课时环节绑定的真实 `Resource` 会按文件格式生成 `resource/video/document` 机会，版本哈希绑定资源更新时间和环节内资源快照。`resource.opened` 只推进“已呈现”；视频实际播放后由节流 `video.progress` 推进“已开始”。
- PDF/Office 查看器无法提供可信页码时只记录打开，不伪造 `document.progress`；文档进度接口仅供能返回真实页码、页数和有效可见时长的本地查看器调用。资源中心的自由浏览不进入课堂机会分母。
- 迁移 `courses.0019-0022` 新增不可变 `ClassroomEvaluationConfigVersion`，并把课堂首次开启评价时的版本冻结到 `ClassroomSession.evaluation_config_version`。课程之后修改评价项只影响后续课堂。
- `ClassroomEvaluationSubmission` 改为追加式版本：每次修订生成新的提交 UUID、递增 `submission_version`、`supersedes` 和分析尝试 UUID。`rubric.rating.submitted` 只保存量规版本、评价项 ID 和 1-5 星，不复制评价备注。
- 课堂开启评价时按自评、互评、师评生成非必做任务机会；自评机会归本人，师评和互评机会归被评价学生。互评跨学生目标只允许经过已校验同组关系的服务端入口，学生批量事件 API 仍禁止替他人提交。
- 关闭评价或结束课堂会撤回未提交评价机会，已提交版本保留；课程级师评按课程、班级和量规版本建立独立机会。
- 迁移 `courses.0023` 为小组共享文件补充唯一 UUID、分析尝试 UUID 和版本号，并新增不可变 `ClassroomGroupDocumentVersion`。旧小组文档在迁移时保存基线快照，后续 ONLYOFFICE 有效保存追加 SHA-256 版本。
- 小组文档与共享区分别作为非必做 `document/task` 机会，通过 `content.released@1.1.target_student_ids` 只展开给当前组员。打开和上传是学生级事实；经 JWT 验证的保存仅写组级事实，不从编辑者列表推断个人贡献。
- 协作关闭、课堂结束和无行为重分组会撤回未完成机会；一旦已有打开、保存或上传记录，服务端阻止重分组，避免成员关系和文件证据被物理覆盖。
- 迁移 `learning_analytics.0007` 增加独立 `attendance` 机会类型。教师开启签到时按全班生成机会，学生本人只能提交 `signed/student`，教师可追加 `signed/late/leave/absent` 修订。
- `attendance.recorded` 使用 `revision_no` 和 `supersedes_event_id` 保留状态变化；备注不进入 V2。课堂结束时未响应机会撤回，但不自动标记缺勤，网络或设备问题不能被静默解释为负面行为。
- 迁移 `learning_analytics.0008` 增加独立 `interaction` 机会类型。抢答开启时为在籍学生生成非必做机会；首次响应写 `quick_answer.responded`，服务端在活动锁内生成排名和响应延迟，重复响应不追加事实。
- 关闭抢答或结束课堂时只撤回未响应机会。回答正文留在业务兼容层，不复制进 V2；`random_call.selected` 只记录教师选择事实和序次，不创建学生完成机会，也不能直接作为掌握度或投入特征。
- 目前 `content.released` 只表示立即开放。未来定时开放不能提前写成 `released`，必须在后续工作包增加 `content.assigned` 后再实现。
- `DATA-01C/03` 未完成前，V2 数据不得用于特征、分层建议或模型性能报告。

### 数据模型

第一批只增不改的模型：

- `EventSchemaDefinition`
- `LearningEventV2`
- `LearningOpportunity`
- `AssessmentResultFact`
- `ParticipationPointLedger`
- `TeacherInterventionFact`
- `DataQualityReport`
- `AnalyticsPipelineRun`
- `AnalyticsTaskRun`

事件至少包含 UUID、模式版本、学校/学生、学科/课程/课时/环节、对象版本、发生/接收时间、客户端会话与序号、分析单位、载荷和质量状态。服务端重建学校和权限作用域，不能信任客户端提交的 `school_id` 或角色。

### 写入改造顺序

1. 题目与测试最终作答、主观题最终评分。
2. 课堂资源、视频、Office 文档和 AI 学习网页。
3. 签到、抢答、点名、倒计时和教师加减分。
4. 自评、互评、师评和教师干预。
5. 小组文档、共享文件、聊天和项目阶段。
6. 登录与普通页面访问最后接入，避免低价值事件先淹没质量排查。

所有业务写入调用一个 `record_learning_event()` 领域服务。V1/V2 双写由该服务负责，视图不能直接复制两次 `objects.create()`。

### API 与任务

- `POST /api/v1/learning-events/batch/`：批量补传、逐条幂等结果。
- `GET /api/v1/school-admin/analytics/quality/`：本校事件覆盖、重复、迟到和错误。
- Celery：`validate_events`、`build_opportunities`、`finalize_result_facts`、`reconcile_v1_v2`、`publish_quality_report`。

### M1 闸门

- 设计报告中的黄金事件、离线乱序、迟到、机会分母、最终评分、评价归属和积分冲正测试通过。
- 每个结果都能追溯到投放机会、版本和最终状态；无机会不记失败，未评分不记 0 分。
- V1/V2 对账差异有明确原因和审计，不通过时保持双写且不进入 M3。
- 核心数据源机会覆盖率初始工程闸门达到报告规定的 0.95；不足时只显示质量问题。

## 6. M2：测量、量规与题目层

### 开发任务

1. 建立 `AssessmentBlueprintVersion`，保存课程目标、主张、证据、任务规格、认知复杂度、允许支持和验证用途。
2. 建立模块化 `RubricDefinitionVersion`、`RubricCriterionVersion`、锚点样例和证据引用；本地形成性、校级分析和研究链接用途隔离。
3. 自评、互评、师评保存逐项星级、目标对象、量规版本和证据，不只存总星数。
4. 题库增加 `draft -> reviewed -> pilot -> calibrated -> active -> retired/compromised` 生命周期，以及 AI 来源、审核、曝光、DIF 和漂移字段。
5. 每个拟用于研究的学科准备共同锚测或等值设计。A/B/C 专属题不能替代共同测量。
6. 教师端增加量规设计、题目验证状态和共同锚测管理；学生端仍只显示评价锚点和本人任务。

### M2 闸门

- 学科专家完成内容审查，反应过程和第一轮试评方案已执行或正式排期。
- 未达到 `calibrated/active` 的 AI 题无法进入共同锚测、主要研究结局或跨校链接。
- 五星评价逐项带可观察锚点，未启用项目保存 `NOT_ASSESSED` 而不是 0/1 星。
- 测量权重和预测权重在代码与数据中彻底分离。

## 7. M3：特征、计划决策点与结局层

### 数据模型

- `FeatureDefinition`
- `DecisionPointSnapshot`
- `StudentFeatureSnapshotV2`
- `OutcomeDefinitionVersion`
- `OutcomeObservation`
- `ConstructEvidenceMap`
- `ScientificClaimVersion`

### 开发任务

1. 实现报告注册的首批候选特征，所有特征保存公式、窗口、分母、缺失码、因果角色、证据等级和代码哈希。
2. 分开环节、课时、7 日、30 日、单元和学期窗口；不把每晚运行自动当作新研究样本。
3. 建立学生 × 学科 × 计划 `T0` 决策点，生成 `operational_available` 与 `reconstructed_complete` 两种不可互相覆盖的视图。
4. 生成未来掌握、必做完成、逾期和成长的分开结局，不直接生成 A/B/C 标签。
5. 实现学生内变化与学生间基线拆分、机会不足、竞争状态和 `UNOBSERVED`。
6. 建立无模型夜间 DAG，先验证事实、特征和结局可重复生成。

### 夜间 DAG V1

```text
close_event_watermark
  -> validate_events
  -> build_opportunities_and_facts
  -> publish_quality_report
  -> create_planned_decision_points
  -> build_feature_snapshots
  -> mature_outcomes
  -> reconcile_counts_and_hashes
```

每个任务必须幂等，输入水位和输出哈希写入运行表。任一关键任务失败时不发布部分新快照。

### M3 闸门

- 所有特征可按相同 `T0` 和代码版本重算，未来数据注入不会改变历史快照。
- F4 教师干预、设备和质量信息与 V1 主模型输入隔离。
- 结局带计划窗口、分子/分母、观察状态和证据引用。
- 至少完成一个学科、一个完整单元的端到端冻结数据演练。

## 8. M4：隐性动态分层影子版

### 后端

1. 建立 `StratificationDecisionCandidate`、`TeacherDecisionObservation`、`StudentSubjectBand`、`SupportInterventionDefinition/Episode` 和 `SensitiveInferenceAccessLog`。
2. 先实现透明 V0 规则，只从允许的掌握证据生成内容带候选；完成困难只生成支持处方，不自动降为 C。
3. `AssignmentResolver` 根据教师确认后的有效带解析资源、题目和支架；学生只获得已分配内容。
4. 学生访问其他变体返回 403/404，不能通过响应差异推断层级。
5. 学校管理员只获得满足小单元规则的聚合覆盖、迁移、质量和处理率。

### 教师前端

将当前占位路由替换为 `StratificationWorkbenchView`：

- 班级/学科/时间筛选。
- 当前带、建议带和边界状态。
- 证据质量、学习机会、支持/反对证据与不确定性。
- `接受`、`保持原层`、`调整`、`延后观察`。
- 学生内容预览、变化历史和支持处方。
- 默认隐私模式、投屏遮蔽和敏感导出确认。

### 学生前端

- 不增加分层导航或层级卡片。
- 课程、课堂、测试和资源继续使用原有学生体验。
- 学习清单、通知、WebSocket、路由和文件名不包含内部代码。
- 小组协作只显示当前组员，不显示同层/异层策略和能力型组名。

### 运行方式

初始只允许 `shadow`：教师看到候选和证据，但候选不自动改变学生内容。完成可用性和权限测试后进入 `teacher_review`，仍必须由教师确认。

### M4 闸门

- 隐性分层自动验收测试全部通过，包括学生响应、直接对象访问、WebSocket、教师跨班、分组、投屏和导出。
- 教师能正确解释规则建议，完成一条建议的时间和错误类型可记录。
- 学生核心课程机会不因 `abstain`、数据不足或访问问题而减少。
- 旧 `current_layer` 与 `StudentSubjectBand` 双读对账完成，新的个体投放只读取版本化有效带。

## 9. M5：冻结数据上的离线模型实验

### 启动前提

- M1-M3 数据闸门持续通过。
- 已积累真实、成熟、覆盖计划时间窗的结局。
- 学科测量版本冻结，研究协议、数据切分、主要指标和停止规则预注册。
- 有效样本量、学校/班级数量和不确定区间通过正式精度或功效分析，而不是使用“每班约 50 人”的经验判断。

### 实验顺序

1. M00：总体发生率和上一时点状态。
2. M01：透明专家规则。
3. M02：Elastic Net/序数模型。
4. M03：多层模型。
5. M04/M05：CatBoost 与 LightGBM。
6. M06：独立 IRT/BKT 掌握子模型。
7. 只有训练折外预测显示稳定增益时才比较组合模型。

实验使用同一冻结特征、结局和外层折。并行执行在读学生时间外推、新学生、新班级、新学校、新课程/时间验证，报告校准、区分、误差、不确定性、拒绝预测、公平、逐校结果和透明基线差异。

### 工程约束

- 实验代码进入 `aiops/experiments/`，不能直接由生产 Celery 任务调用。
- 不使用 pickle/joblib 作为学校导入模型包。
- scikit-learn、CatBoost、LightGBM、NumPy、pandas/Polars 和模型转换依赖先加入离线 wheelhouse 并在目标 Python 3.12 环境验证。
- MLflow 可在中心研究机作为可选实验目录，不作为每所学校运行依赖；正式来源仍是数据库注册、不可变产物、哈希和签名。
- 教师 DeepSeek 密钥不能用于学生预测、特征生成或模型解释。

### M5 闸门

- 候选模型在锁定外层验证中稳定优于透明基线，且校准、公平、解释稳定和拒绝预测满足预注册闸门。
- 学校身份或班级身份基线不能接近完整模型，否则限制迁移主张并重新审查特征。
- 标签置乱、未来数据、访问问题和点击操纵负对照全部通过。
- 未通过时保留 V0 规则或完全人工模式，不以“项目已经做了 AI”作为上线理由。

## 10. M6：生产模型、班级校准与夜间闭环

### 模型包

```text
manifest.json
feature_schema.json
outcome_contract.json
global_or_subject_model.onnx/json/txt
class_calibrator.json
policy_version.json
model_card.md
checksums.sha256
signature.ed25519
```

只允许白名单数据格式和经过审查的解析器。模型包不得包含可执行 Python 对象、pickle、joblib、脚本或宏。

### 运行频率

- 每晚：事实、质量、特征、推理和教师摘要。
- 每周：满足新成熟结局门槛时更新班级校准器。
- 每月/学期：中心端离线训练全局或学科候选模型。
- 每次更新：先 shadow、再 canary、最后才允许 champion；失败自动回滚。

### 状态迁移

```text
collect_only -> shadow -> teacher_review -> active
                      \-> suspended
active -> suspended -> shadow/reviewed rollback
```

`active` 也不允许模型直接改变学生内容带，只表示经过教师确认后的决定可以进入正式投放。数据覆盖、校准、公平、漂移、签名、版本兼容或安全任一失败时进入 `suspended`。

### M6 闸门

- 原子发布、重跑幂等、canary、签名验证和一键回滚演练通过。
- 班级样本不足时正确回退到学校-学科或全局版本，不从零训练复杂模型。
- 模型/校准器/策略/特征/测量版本可以完整追溯。
- 教师容量预算、建议积压和群体覆盖处于预注册可接受范围。

## 11. M7：校内前瞻性试点

### 建议范围

- 先选择一个学科、一个年级和一个边界清晰的教学单元。
- 影子期先于正式教师审核期。
- 先评价测量、预测和教师决策可用性，再单独设计分层教学效果研究。

### 必须记录

- 教师是否查看、理解、接受/修改/拒绝建议。
- 实际投放、学生曝光、使用、完成和退出。
- 教师耗时、额外负担、课堂偏离和支持资源不足。
- 学生资源机会、纠错、申诉和不良后果。
- 不同群体的测量、建议覆盖、教师处理和学习后果。

### M7 闸门

- 学校完成必要的伦理、知情、未成年人保护和数据治理程序。
- 教师通过数据素养与隐性沟通培训，能区分代理、预测和因果。
- 教师单独、模型单独和人机团队评价显示团队有真实净效用，而不是只提高接受率。
- 出现污名化、机会减少、严重不公平、数据用途扩张或教师不可承受负担时暂停扩大。

## 12. M8：跨校复验与统一分析

### 学校端

- 按批准模式导出去标识化、加密、签名的 Parquet 研究包。
- 默认不导出姓名、账号、聊天原文、答卷正文、作品文件、IP、设备指纹和个体可识别层级。
- 导出前执行小单元、稀有组合和字段白名单审查。

### 中心端

- 验签、解密、模式兼容和恶意文件隔离后导入。
- 各学校单独保留性能、校准、缺失和实施结果，不只报告平均值。
- 新学校先做独立 shadow 外测，不能查看结局后反复调参再称为外部验证。
- 超级管理员跨校界面只显示达到隐私门槛的聚合结果。

### M8 闸门

- 至少一所未参与开发的学校完成独立时间段验证。
- 测量、事件语义、课程和机会兼容性通过迁移评估。
- 跨校结论有明确学校、学科、年级、版本和时间边界。
- 不满足时限制模型包适用范围，不使用“普遍有效”或“精准分层”。

## 13. 数据库迁移与回滚顺序

1. **Additive**：只新增 V2 表、索引和约束，不修改旧表语义。
2. **Dual write**：统一事件服务同时写 V1/V2，失败时事务回滚或进入明确重试队列。
3. **Backfill**：只迁移能够确定语义的历史记录；不确定记录标记 `legacy_unmapped`。
4. **Reconcile**：按事件、机会、结果和积分分别对账，不能只比总行数。
5. **Read switch**：质量看板先读 V2，随后是特征、教师工作台和学生投放。
6. **Freeze legacy**：所有读写切换并稳定一个批准周期后，V1 改为只读。
7. **Remove**：只有备份、申诉、研究复现和保留要求均满足后才删除旧字段或表。

每批迁移必须提供反向迁移或明确的前向修复方案、预估锁表时间、备份点和 PostgreSQL 实测记录。正式学校数据库不使用一次迁移同时回填大量历史数据，批量回填由可恢复管理命令执行。

## 14. API 与界面交付矩阵

| 阶段 | 教师 | 学生 | 学校管理员 | 超级管理员 |
| --- | --- | --- | --- | --- |
| M0 | 权限审计，无新页面 | 字段泄漏修复 | 无 | 无 |
| M1 | 事件写入无感接入 | 离线批量补传 | 数据质量页 V1 | 无 |
| M2 | 量规/题目生命周期 | 任务锚点与评价 | 测量版本概况 | 无 |
| M3 | 特征质量调试页 | 无分层变化 | 机会/特征质量 | 无 |
| M4 | 分层审核工作台 V0 | 隐性学习清单 | 聚合运行概况 | 无 |
| M5 | 冻结案例可用性研究 | 无 | 研究状态摘要 | 模型实验目录，无个体数据 |
| M6 | 生产审核、历史和回滚状态 | 仍只有普通学习体验 | 模型运行质量 | 签名模型包状态 |
| M7 | 试点实施与负担反馈 | 纠错/申诉和支持反馈 | 试点监督 | 无 |
| M8 | 本校反馈报告 | 无新增层级信息 | 研究包导出 | 去标识跨校分析 |

## 15. 测试与发布门槛

### 每个 PR 必须执行

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check
.\.venv\Scripts\python.exe manage.py test learning_analytics aiops api.tests
Set-Location frontend
npm.cmd run build
```

在测试模块尚未拆分前保留 `api.tests`；analytics 覆盖增大后再按领域拆成测试包，不能继续把所有测试追加到单个 `api/tests.py`。

### 测试层级

- **Schema 单元测试**：事件、机会、特征、结局和模型包格式。
- **领域测试**：幂等、迟到、缺失、积分冲正、教师决定和有效期。
- **权限测试**：学生字段白名单、教师任课范围、管理员聚合、小单元抑制。
- **契约测试**：Vue TypeScript 类型与 DRF 响应 fixture 一致。
- **DAG 集成测试**：相同输入重复运行得到相同计数和哈希，失败无部分发布。
- **模型测试**：数据折、泄漏、置乱、校准、漂移、签名和回滚。
- **浏览器测试**：教师工作台隐私模式、学生页面无隐藏层级字段、不同视口无溢出。
- **目标硬件负载测试**：并发按学校实际班级数、学生数、课堂事件率和服务器规格制定，不复制云端假设。

## 16. 文档、Issue 与 PR 规则

1. 主设计报告定义科学和产品边界；本路线图定义实施顺序；`data_model.md` 和 `api_contract.md` 只记录已经确定或实现的契约。
2. Issue 使用工作包前缀，例如 `DATA-01`、`MEAS-01`、`UX-01`、`MODEL-01`。
3. 一个 PR 聚焦一个工作包或可独立回滚的子任务，不混入无关 UI 重构。
4. 数据库 PR 必须包含迁移、回滚/修复、索引说明、数据保留和真实 PostgreSQL 验证。
5. API PR 必须包含角色矩阵、对象级权限、错误契约和前端类型。
6. UI PR 必须完成桌面、小屏和课堂投屏检查；临时截图验证后删除，结果写入 UI/UX 审查文档。
7. 模型 PR 必须引用冻结协议、数据版本、外层折、模型卡和失败结果，不能只提交一个性能数字。
8. 每个里程碑结束更新主报告版本、路线图状态、API、数据模型、部署和用户角色文档。

## 17. 第一批开发任务顺序

建议下一阶段按以下顺序开工：

1. `ARCH-01`：创建 `learning_analytics` app、analytics API 包和测试目录。
2. `PRIV-01A`：扫描并测试全部学生响应中的层级、分值变体和分组策略泄漏。
3. `PRIV-01B`：教师任课对象权限和敏感推断访问日志骨架。
4. `DATA-01A`：事件注册表与 `LearningEventV2`。**已完成。**
5. `DATA-01B`：批量接收、幂等、客户端发生/服务端接收时间。**已完成。**
6. `DATA-02A`：学习机会与撤回事实。**已完成。**
7. `DATA-02B`：最终评分、主观题成熟状态和课堂积分流水。**已完成。**
8. `DATA-01C`：统一事件写入服务与 V1/V2 双写。**进行中，统一服务、课堂积分/聊天、测试、课堂题目/附件、AI 学习网页、课堂普通资源、五星评价、小组协作和签到已完成。**
9. `DATA-03A`：质量流水线、对账和本校质量 API。
10. `DATA-03B`：学校管理员质量页面与 Celery 夜间调度。
11. `MEAS-01A`：一个试点学科的任务蓝图和量规版本。
12. `FEAT-01A`：特征定义注册表和首个无模型快照。

完成前 10 项以前不开发真实模型训练按钮；完成 M3 前，教师分层页面只使用合成 fixture 做组件开发，不读取开发库生成伪 AI 结果。

## 18. 全局完成定义

一个“AI 隐性动态分层版本”只有同时满足以下条件才可称为完成：

- 数据事实、机会、测量、特征和计划结局可重算并通过质量闸门。
- 模型优于透明基线，具有校准、不确定性、适用范围和拒绝预测。
- 任课教师可以查看、解释、接受、保持、调整、延后和纠错。
- 学生端、接口、WebSocket、缓存、文件名和分组命名均不泄漏内部层级。
- 学生仍能获得共同核心目标、正常课程机会、数据用途说明和纠错申诉渠道。
- 班级专属通过全局/学科模型加班级校准实现，小班不从零重训复杂模型。
- 夜间任务幂等、无部分发布，模型包可验签、canary、回滚和停用。
- 公平审计覆盖测量、机会、观察、预测、教师处理和学习后果。
- 学校离线部署、备份恢复和跨校去标识研究包在目标硬件上验证。
- 产品与论文只使用当前证据等级允许的措辞，失败和退役记录同样保留。
