# STRATA 数据质量流水线与闸门

> 版本：`data-quality-v1`  
> 更新日期：2026-07-19  
> 状态：`DATA-03A/B` 工程实现完成；开发校当前数据闸门为红色，M2 尚未进入。

## 1. 目标与边界

数据质量层回答“当前学校的事件事实是否足以进入后续测量、特征和模型流程”，不评价学生能力。质量问题只影响分析资格、置信度和流水线状态，禁止转化为学生扣分、素养分或分层标签。

学校管理员只能查看本校聚合报告、问题和运行记录。学生端没有入口；教师端不显示平台级摄取错误。A/B/C 内容带、风险概率、模型理由和分组策略不进入本页面或导出文件。

## 2. 七项指标

| 指标 | 分子 | 分母 | 关注/阻断阈值 |
| --- | --- | --- | --- |
| 重复事件率 | 摄取结果为 duplicate 的次数 | 有效、重复、拒绝摄取尝试 | `>5% / >10%` |
| 无效事件率 | 拒绝事实与拒绝计数的较大值 | 有效、重复、拒绝摄取尝试 | `>2% / >5%` |
| 迟到事件率 | 带 24 小时或 7 天迟到标记的事件 | 窗口内 V2 事件 | `>10% / >25%` |
| 语义缺失率 | `legacy.unmapped` 事件 | 窗口内 V2 事件 | `>5% / >15%` |
| 机会关联覆盖率 | 已关联学习机会的应关联事件 | 注册表要求机会的事件 | `<98% / <90%` |
| 客户端离线率 | 显式 `client.offline` 事件 | 学生 Web 事件 | `>10% / >25%` |
| V1/V2 差异率 | 缺失 V2、映射差异和未关联 V1 | 可对账 V1 总数 | `>0 / >0` |

没有事件时直接产生红色 `no_events` 问题。没有机会型事件时机会覆盖率按 100% 处理，避免用“不适用”制造假阻断。

手动 7 日和夜间窗口都按学校时区的完整自然日计算，不把尚未闭合的当天与日级摄取计数混合。当前实现使用 `Asia/Shanghai`。

## 3. 数据模型

- `EventIngestionDailyCounter`：学校 × 日期 × 来源的有效、重复、拒绝、迟到、离线及错误分类计数。
- `AnalyticsPipelineRun`：学校级流水线运行，记录窗口、方法版本、配置哈希、代码版本、触发方式、状态和重试链。
- `AnalyticsTaskRun`：`collect_event_quality`、`reconcile_v1_v2`、`publish_quality_report` 三阶段记录。
- `DataQualityReport`：不可原地修改的版本化报告，保存七项比率、阈值、计数、问题、来源指纹和闸门结果。

同一学校、同一窗口的定时运行有数据库条件唯一约束。夜间多校调度复用已存在运行，并隔离单校入队失败，不让一所学校中断其他学校。

## 4. 流水线状态

```text
pending -> running -> succeeded
                  -> blocked
                  -> failed -> retry(attempt_no + 1)
```

- `succeeded`：报告为绿色或黄色，质量闸门通过。
- `blocked`：报告为红色，后续分析必须停止。
- `failed`：代码、数据库或任务执行失败；保留错误代码和信息。
- `retry`：生成新运行并通过 `retry_of` 指向失败运行，不覆盖原报告和任务记录。

`require_quality_gate(school=...)` 是后续 M2/M3 夜间流程的强制入口。缺少报告或最新报告被阻断时抛出 `QualityGateError`。

## 5. API 与页面

- `GET /api/v1/school-admin/analytics/quality/`：当前报告、最近 30 份报告和最近 20 次运行。
- `POST /api/v1/school-admin/analytics/quality/run/`：提交最近 1-365 个完整日的手动检查；同校已有等待/运行任务时返回 409。
- `GET /api/v1/school-admin/analytics/quality/export/`：导出本校 XLSX，包含质量报告、指标、问题、流水线和任务阶段五张表。
- Vue 路由：`/app/school-admin/data-quality`。

页面展示当前闸门、七项指标与阈值、异常率趋势、完整性趋势、问题清单、对账计数和可展开运行记录。运行中每 3 秒刷新，结束后自动停止轮询。

## 6. 夜间任务

Celery Beat 每天 `01:30` 触发：

```text
learning_analytics.tasks.run_nightly_data_quality
```

任务对每个启用学校检查前一完整自然日，并向 Redis 队列投递学校级质量任务。Windows 私有部署使用 `solo` worker；Beat 与 worker 必须作为独立服务运行。

## 7. 验收证据

- SQLite：全量 101 项测试通过。
- PostgreSQL 17.10：迁移 `0009` 和全量 101 项测试通过。
- Redis/Memurai：`56379` 实例协议和任务队列验证通过。
- 真实 Celery：三阶段任务成功写入 PostgreSQL；红色报告正确产生 `blocked`。
- 真实重试：失败运行保留 `IntegrityError`，60 秒后生成 `attempt_no=2` 的独立 retry 运行并完成三阶段任务。
- Vue：`vue-tsc --noEmit` 与 Vite 生产构建通过。
- UI/UX：Chrome 150 在 `1440x900` 和 `390x844` 下无页面级横向溢出、无控制台异常；运行记录表仅在自身容器滚动。
- 页面交互：从按钮提交任务后，运行记录由 1 条变 2 条，轮询结束后按钮恢复，第二期报告显示 ECharts 趋势。

临时截图仅用于审查，完成后删除，不进入 Git。

## 8. 当前阻断与进入 M2 的条件

开发校最近完整 7 日共有 16 条 V2 事件，其中 6 条为 `legacy.unmapped`，语义缺失率 37.5%，高于 15% 阻断阈值。该结果说明闸门工作正常，不允许通过手工改状态或编造映射变绿。

进入 M2 前必须满足：

1. 连续约定观察窗口内有真实教学事件，不能只用迁移样例。
2. `legacy.unmapped` 只通过可证明的确定规则补映射；无法证明的历史继续隔离。
3. 最新报告无红色问题，且 V1/V2 差异率为 0。
4. SQLite/PostgreSQL 测试、Ruff、迁移检查和 Vue 构建继续通过。
5. 建立新的 Git 基线后，才开始研究级量规、题目生命周期与共同锚测。

## 9. 回滚点

- DATA-03 前：`baseline/data01c-complete-20260719`
- DATA-03A 后端：`baseline/data03a-quality-backend-20260719`
- DATA-03B 页面与部署：`baseline/data03b-quality-dashboard-20260719`
