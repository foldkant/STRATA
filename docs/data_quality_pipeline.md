# STRATA 学习数据检查

> 版本：`data-check-v2`  
> 更新日期：2026-07-19  
> 状态：后端、夜间任务和学校管理员页面已经完成；开发校最近完整 7 日检查已通过。

补充：`SIM-01` 模拟学校可以单独生成检查报告，用于验证程序是否可运行，但不进入正式学校夜间任务，也不能改变真实学校的检查结果。详见[模拟数据开发说明](synthetic_data_research_track.md)。

校内测试数据使用独立 `synthetic_run` 标记。正式 API、XLSX、手动检查和夜间任务只读取未标记的正式数据；模拟批次只读取自己的记录，两者不能相互混合。

## 1. 目标与边界

数据检查回答“当前学校的学习记录是否完整、能否继续后续分析”，不评价学生能力。检查问题只影响后续分析是否继续，禁止转化为学生扣分、素养分或分层结果。

学校管理员只能查看本校汇总报告、问题和运行记录。学生端和教师端没有入口；A/B/C 学习安排、个体风险和分组依据不进入本页面或导出文件。

## 2. 七项指标

| 指标 | 分子 | 分母 | 提醒/不通过标准 |
| --- | --- | --- | --- |
| 重复事件率 | 接收结果为 duplicate 的次数 | 有效、重复、拒绝接收尝试 | `>5% / >10%` |
| 无效事件率 | 拒绝事实与拒绝计数的较大值 | 有效、重复、拒绝接收尝试 | `>2% / >5%` |
| 迟到事件率 | 带 24 小时或 7 天迟到标记的事件 | 时间范围内新版事件 | `>10% / >25%` |
| 旧事件未转换比例 | 数据库中标记为未转换的旧事件 | 时间范围内新版事件 | `>5% / >15%` |
| 学习任务关联率 | 已关联学习任务的事件 | 需要关联任务的事件 | `<98% / <90%` |
| 客户端离线率 | 显式 `client.offline` 事件 | 学生 Web 事件 | `>10% / >25%` |
| 新旧记录差异率 | 缺失新版记录、转换差异和未关联旧记录 | 可核对旧记录总数 | `>0 / >0` |

没有学习记录时直接产生红色 `no_events` 问题。没有需要关联任务的事件时，任务关联率按 100% 处理，避免把“不适用”误判成问题。

手动 7 日和夜间窗口都按学校时区的完整自然日计算，不把尚未闭合的当天与日级接收计数混合。当前实现使用 `Asia/Shanghai`。

## 3. 数据模型

- `EventIngestionDailyCounter`：学校 × 日期 × 来源的有效、重复、拒绝、迟到、离线及错误分类计数。
- `AnalyticsPipelineRun`：学校级自动检查记录，保存时间范围、代码版本、触发方式、状态和重试关系。
- `AnalyticsTaskRun`：保存 `collect_learning_data`、`compare_old_new_records`、`save_data_check_report` 三个执行阶段。
- `DataQualityReport`：不可直接修改的检查报告，使用 `checks_passed`、`receive_attempt_count`、`rejected_event_count`、`unconverted_old_event_count`、`unlinked_old_event_count` 等直观字段。
- 七项比例字段为 `duplicate_rate`、`invalid_event_rate`、`late_event_rate`、`unconverted_old_event_rate`、`learning_task_link_rate`、`client_offline_rate`、`old_new_event_difference_rate`。
- 检查规则版本和来源校验码分别保存为 `check_version`、`source_checksum`。
- `thresholds`、`counts`、`issues` 和运行摘要中的历史键由迁移 `0017` 统一转换，不保留两套当前字段。

同一学校、同一窗口的定时运行有数据库条件唯一约束。夜间多校调度复用已存在运行，并隔离单校入队失败，不让一所学校中断其他学校。

## 4. 自动检查状态

```text
pending -> running -> succeeded
                  -> blocked
                  -> failed -> retry(attempt_no + 1)
```

- `succeeded`：报告为绿色或黄色，可以继续后续流程。
- `blocked`：数据库状态码，界面显示“检查未通过”，后续分析暂停。
- `failed`：代码、数据库或任务执行失败；保留错误代码和信息。
- `retry`：生成新运行并通过 `retry_of` 指向失败运行，不覆盖原报告和任务记录。

后续夜间分析必须先调用 `require_quality_checks(school=...)`。缺少报告或最新检查未通过时停止执行。

## 5. API 与页面

- `GET /api/v1/school-admin/analytics/quality/`：当前报告、最近 30 份报告和最近 20 次运行。
- `POST /api/v1/school-admin/analytics/quality/run/`：提交最近 1-365 个完整日的手动检查；同校已有等待/运行任务时返回 409。
- `GET /api/v1/school-admin/analytics/quality/export/`：导出本校 XLSX，包含“检查报告、检查指标、待处理问题、自动检查记录、执行阶段”五张表。
- Vue 路由：`/app/school-admin/data-quality`。

页面展示当前检查结果、七项指标、趋势、问题清单、数据核对和可展开运行记录。运行中每 3 秒刷新，结束后自动停止。

## 6. 夜间任务

Celery Beat 每天 `01:30` 触发：

```text
learning_analytics.tasks.run_nightly_data_quality
```

任务对每个启用学校检查前一完整自然日，并向 Redis 队列提交学校级检查任务。Windows 私有部署使用 `solo` worker；Beat 与 worker 必须作为独立服务运行。

## 7. 验收证据

- SQLite：全量 114 项测试通过。
- PostgreSQL 17.10：全量 114 项测试通过。
- 数据库审计：当前检查报告表没有旧列名，历史 `thresholds/counts/issues/summary/metrics` 中没有旧 JSON 键，执行阶段只保存 `collect_learning_data`、`compare_old_new_records`、`save_data_check_report`。
- PostgreSQL 17.10：完整迁移和全量测试通过。
- Redis/Memurai：`56379` 实例协议和任务队列验证通过。
- 真实 Celery：三阶段任务成功写入 PostgreSQL；红色报告正确产生 `blocked`。
- 真实重试：失败运行保留 `IntegrityError`，60 秒后生成 `attempt_no=2` 的独立 retry 运行并完成三阶段任务。
- Vue：`vue-tsc --noEmit` 与 Vite 生产构建通过。
- UI/UX：Chrome 150 在 `1440x900` 和 `390x844` 下无页面级横向溢出、无控制台异常；运行记录表仅在自身容器滚动。
- 页面交互：从按钮提交任务后，运行记录由 1 条变 2 条，轮询结束后按钮恢复，第二期报告显示 ECharts 趋势。

临时截图仅用于审查，完成后删除，不进入 Git。

## 8. 当前结果与进入下一阶段的条件

开发校原有 6 条旧测试事件无法转换，已按用户确认从新旧事件表中成对删除。重新检查结果为：10 条正式事件、旧事件未转换比例 0%、新旧记录差异 0%，报告为绿色。

进入评价与题目开发前必须满足：

1. 连续约定观察窗口内有真实教学事件，不能只用迁移样例。
2. 旧事件只允许通过明确规则转换；不能确定含义的记录继续隔离，测试垃圾数据可在确认后成对清理。
3. 最新报告无红色问题，且 新旧记录差异率为 0。
4. SQLite/PostgreSQL 测试、Ruff、迁移检查和 Vue 构建继续通过。
5. 建立新的 Git 基线后，才开始正式评价试用、题目质量管理和后续学生特征开发。

## 9. 回滚点

- DATA-03 前：`baseline/data01c-complete-20260719`
- DATA-03A 后端：`baseline/data03a-quality-backend-20260719`
- DATA-03B 页面与部署：`baseline/data03b-quality-dashboard-20260719`
