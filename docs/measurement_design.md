# MEAS-01A 任务蓝图与量规版本

> 实现日期：2026-07-19  
> 当前证据等级：合成工程轨道完成；真实内容效度、反应过程、评分一致性和跨校链接均未验证。

## 1. 目标与边界

`MEAS-01A` 建立研究级测量对象的工程底座，固定以下证据链：

```text
Claim -> Evidence -> Task -> Scoring -> Use
```

教师可以保存未完成草案，但只有满足发布校验后才能冻结不可变版本。教师自行创建的蓝图和量规用途固定为 `local_formative`，不能自行升级为 `school_common` 或 `research_linked`。

本阶段不完成以下工作：

- 不宣称量规已具有内容效度、结构效度或评分者一致性。
- 不把五星总数作为学生层级标签。
- 不训练分层模型，不进入 M3 特征工程。
- 不允许学生查看 A/B/C、风险概率、模型理由或内部策略。

## 2. 数据对象

- `AssessmentBlueprint`：可编辑任务蓝图草案。
- `AssessmentBlueprintVersion`：发布后的不可变蓝图版本，保存递增版本号和 SHA-256。
- `RubricDefinition`：可编辑量规草案，条目暂存为结构化 JSON。
- `RubricDefinitionVersion`：绑定已发布蓝图版本的不可变量规版本。
- `RubricCriterionVersion`：规范化量规条目，模块限定为 P/S/R/C/D/E。
- `RubricAnchorExample`：条目锚定样例，星级限定为 1-5。

发布版本和其条目、样例不能修改或删除。相同规范化内容重复发布不会产生重复版本；草案变化后再次发布生成下一版本。

## 3. 发布校验

蓝图发布必须满足：

- 绑定教师本人课程，并登记任务版本、目标学生总体和课程目标。
- 至少一条学习主张、证据规则和任务规格。
- 每条主张至少有证据规则，每条证据至少由一个任务触发。
- 登记内容覆盖、认知复杂度、允许支持、评分方式、证据解释规则和下一步形成性行动。

量规发布必须满足：

- 绑定已有发布版本的任务蓝图，且用途一致。
- 每个条目登记评价对象、证据来源、可观察证据、不可观察条件、允许支持、反例和下一步行动。
- 1-5 星分别具有完整且不同的文字锚点。
- 每个条目至少有两份锚定样例，并覆盖两个不同星级。
- 没有观察机会时使用 `NOT_ASSESSED`，不能写成 0 分或 1 星。
- 出勤、签到、按时率、完成率、积分、在线时长和服从性表达被发布校验拒绝。

## 4. 教师端

正式路由：`/app/teacher/measurement-design`

页面包含：

- 任务蓝图与五星量规两个标签。
- 蓝图三步编辑：范围与目标、证据链、评分与使用。
- 量规草案编辑和独立条目三步编辑：评价证据、星级锚点、锚定样例。
- 发布前确认，发布后显示版本号；编辑始终修改草案，不覆盖历史版本。

移动端列表使用纵向信息块，不依赖页面级横向滚动。长表单放在有固定标题和操作栏的弹窗中，正文区域独立滚动。

## 5. 试点工程数据

当前小榄中学合成叠加课程已创建首个工程版本：

- 教师：`foldkant`
- 课程：`数据与计算（SIM-B94BB297）`
- 蓝图：`数据表达与解释试点任务蓝图@v1`
- 量规：`数据表达与解释形成性量规@v1`
- 条目：P1、S1、R1、D1、E1，共 5 项、10 份锚定样例
- 验证状态：`unvalidated`

可重复执行：

```powershell
.\.venv\Scripts\python.exe manage.py seed_measurement_pilot --teacher foldkant --course-id 7
```

该命令相同内容幂等；内容变化时发布下一版本。数据只用于合成工程验证，不能作为真实学生测量结果或论文模型效果。

## 6. API

教师接口均按登录学校和创建教师隔离：

```text
GET  /api/v1/teacher/measurement/options/
GET|POST /api/v1/teacher/measurement/blueprints/
GET|PATCH /api/v1/teacher/measurement/blueprints/{id}/
POST /api/v1/teacher/measurement/blueprints/{id}/publish/
GET|POST /api/v1/teacher/measurement/rubrics/
GET|PATCH /api/v1/teacher/measurement/rubrics/{id}/
POST /api/v1/teacher/measurement/rubrics/{id}/publish/
```

## 7. 验证记录

- SQLite：111 项全量测试通过。
- PostgreSQL 17.10：111 项全量测试通过。
- Ruff、Django check、迁移一致性通过。
- Vue `vue-tsc --noEmit` 与 Vite 生产构建通过。
- UI/UX：自动检查 `320x740`、`390x844`、`768x900`、`1440x900`，页面横向溢出均为 0；蓝图、量规和条目弹窗无控制台错误。
- 临时截图在复查完成后删除，不进入仓库。

## 8. 下一工作包

继续 M2，不进入 M3：

1. `MEAS-01B`：内容专家审查、反应过程访谈、评分者培训与共同锚测记录契约。
2. `ITEM-01A`：题目 `draft -> reviewed -> pilot -> calibrated -> active -> retired/compromised` 生命周期。
3. `LINK-01A`：共同锚题、跨版本等值和量规评分一致性分析。
4. M2 测量闸门通过后，才开始 `FEAT-01A`。
