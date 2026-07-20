# MODEL-02/03 工程验收报告

> 验收日期：2026-07-20  
> 数据性质：可删除模拟数据，仅用于工程验证

## 1. 数据批次

| 学校 | 模式 | run_id | dataset_key | 学生 | 班级 | 周数 | 事件 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 中山市小榄中学 | school_overlay | `b2461705-ff84-4c9e-a45c-3211d16226f2` | `aee9ee8519994b86cf7467626983f413b42f24796a55183c42259876e53e9e0e` | 96 | 4 | 8 | 3774 |
| STRATA跨校测试学校 | isolated_school | `1cdcc47f-d4b8-4634-af9c-91c4b1514e7f` | `93bfa5ccd0b16bea34400092cb4a4e1acc5da55463c5da94a313e21c3f1cfafc` | 96 | 4 | 8 | 3636 |

生成器版本为 `synthetic-v2`。3,072 个学习机会均为必做任务并包含明确截止时间。两校初始学习数据检查均通过。

## 2. 时间点与冻结版本

每校建立 24 个时间点，即 4 个班 × 6 个历史周。分析前先生成截至时间点的数据检查，再冻结学习指标；随后生成结果截止日检查并冻结未来 7 日结果。

最终使用的数据版本：

| 学校 | 数据版本 ID | 版本键 | 记录数 | 已观察 | 输入指标键 | 状态 |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| 中山市小榄中学 | 11 | `e16ad06ea293545291c9637b2db8254ac92f3da148ee23d2` | 576 | 576 | 19 | 可比较 |
| STRATA跨校测试学校 | 12 | `cf7b71cac5807c0f4c7f2bb5e76d3acd8277c8e1a1d2ed9a` | 576 | 576 | 19 | 可比较 |

冻结生成版本为 `training-dataset-v3`，标准学科键为 `information_technology`。模型输入使用带时间窗的真实键；审计字段未进入主模型。

## 3. 模型运行

| 学校 | LONG-01 | MODEL-01 | MODEL-02 | MODEL-03 | 最佳结构化模型 | 候选 |
| --- | --- | --- | --- | --- | --- | ---: |
| 中山市小榄中学 | completed | shadow_only | shadow_only | candidate | CatBoost | 96 |
| STRATA跨校测试学校 | completed | shadow_only | shadow_only | candidate | CatBoost | 96 |

MODEL-02 的五项防误判检查均通过。CatBoost 与 LightGBM 在 V-A、V-B、V-C 和 V-D 均达到 100% 预测覆盖；V-E 因没有第二套可比较测量版本，正确显示“暂不适用”。

跨校 V-D 每校只使用另一学校最新兼容的 576 条记录，未重复计入历史数据版本。模型性能数值仅用于验证计算和页面，不得解释为真实学生效果。

## 4. 班级校准

每校保存：

- 一份完整冻结数据训练的 CatBoost 全局模型。
- 4 组班级残差收缩参数。
- 全局修正值和 A/B/C 阈值。
- 特征重要性。
- 模型文件路径和 SHA-256。
- 96 条教师待确认候选。

两份模型文件重新计算 SHA-256 后与数据库记录一致。旧的待处理模型候选已标记为“已由新版替代”；教师页面只把最新 96 条计入当前模型待办。

## 5. API 与 XLSX

学校管理员接口验收：

- `/api/v1/school-admin/analytics/preparation/?include_test_data=1` 返回 24 个时间点、576 个可用快照和 576 条已观察结果。
- `/api/v1/school-admin/analytics/models/?include_test_data=1` 返回 LONG-01、MODEL-01/02 和 MODEL-03 记录。
- 数据版本 XLSX 包含 577 行匿名数据，不包含账号、姓名或学号。
- 模型 XLSX 包含 8 个工作表：模型卡、模型比较、重复测量、防误判检查、稳定性、班级差异、班级校准、班级参数。

教师接口只返回任教范围。当前小榄中学有 96 条 MODEL-03 候选和 2 条真实测试学生透明规则建议待处理；旧模型候选及被替代的透明规则进入只读历史。学生接口不返回这些记录。

## 6. 环境演练

- SQLite：8 项新增专项测试通过。
- PostgreSQL 17.10：在全新 `strata_model_validation` 库执行全部迁移至 `learning_analytics.0027`，并通过同一组 8 项测试。
- Redis 兼容服务：`PING`、Celery broker `/1`、结果后端 `/2` 均通过。
- Django Channels：显式使用 `RedisChannelLayer` 完成发送和接收。
- Celery 5.5.3：Windows `solo` worker 收到真实任务 `320c955e-7369-4f8f-a5ae-d27120dd5ecc`，两校均返回 `completed/candidate`。

本机 Redis 验收使用 Memurai Developer 便携包，仅用于开发测试，其许可禁止生产使用。学校正式部署必须使用可生产授权的 Redis 7.x、Linux/WSL Redis，或经单独兼容性验收的开源 Redis 协议服务。

## 7. 清理

小榄中学测试批次：

```powershell
.\.venv\Scripts\python.exe manage.py purge_synthetic_learning_data `
  --run-id b2461705-ff84-4c9e-a45c-3211d16226f2 `
  --confirm-key aee9ee8519994b86cf7467626983f413b42f24796a55183c42259876e53e9e0e
```

跨校测试学校：

```powershell
.\.venv\Scripts\python.exe manage.py purge_synthetic_learning_data `
  --run-id 1cdcc47f-d4b8-4634-af9c-91c4b1514e7f `
  --confirm-key 93bfa5ccd0b16bea34400092cb4a4e1acc5da55463c5da94a313e21c3f1cfafc
```

清理服务已验证可删除时间点、结果版本、冻结数据、模型比较、班级校准、教师候选、模型文件、学生、班级、课程和事件。执行前仍应备份数据库。

## 8. 结论边界

本次验收确认：从行为事件到教师审核候选的工程流程可以运行、重跑、导出和清理。它不确认模型在真实学生上的准确性、公平性、稳定性或教学效果。正式试用仍需真实纵向数据、伦理与隐私审查、预注册分析方案和教师监督。
