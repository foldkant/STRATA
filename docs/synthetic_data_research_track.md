# STRATA 合成数据研究轨道

> 工作包：`SIM-01`  
> 版本：`synthetic-v1`  
> 状态：工程实现与开发库验证完成，2026-07-19。

## 1. 目的与边界

平台尚无足以支持测量验证和模型研究的真实纵向数据。合成数据轨道用于提前验证事件、机会、评分、质量、特征和模型流水线的工程正确性，不用于证明真实学生上的预测性能或教学效果。

固定采用双轨制：

- 正式学校轨道继续使用真实数据质量报告。当前开发校仍为红色，不能以合成数据替换或稀释。
- 合成研究轨道使用独立模拟学校、生成批次和隐藏真值，只允许推进 M2/M3 工程以及后续模型恢复测试。
- 合成数据得到的准确率、AUC、分层迁移率和干预效果不得写成平台实证结果。
- 正式试点前必须重新完成真实数据质量、量规、共同测量、样本量和伦理治理验收。

## 2. 隔离机制

支持两种模式：

- `isolated_school`：创建 `is_synthetic=true` 的独立研究学校，适合大规模数据和算法开发。
- `school_overlay`：把带 `SIM-批次` 前缀的班级、课程和学生放入现有学校，用于现有管理员、教师和学生界面的实测。

- `School.is_synthetic=true` 标识合成研究学校。
- `SyntheticDatasetRun` 保存生成版本、随机种子、时间窗口、完整配置、计数和清单 SHA-256。
- `LearningEventV2.synthetic_run` 把每条模拟 V2 事实追溯到唯一生成批次。
- V1 兼容事件的 `metadata.synthetic=true`，并保存批次、生成器版本和数据集指纹。
- `SyntheticStudentTruth` 保存先验掌握、投入、自我调节、反应速度、成长率和班级效应。这些字段禁止进入正式特征、学生接口和运营页面。
- `AnalyticsPipelineRun`、`DataQualityReport` 和 `EventIngestionDailyCounter` 均可关联生成批次。正式学校报告固定读取 `synthetic_run IS NULL`，叠加数据只进入对应批次报告。
- 独立模拟学校不进入夜间正式任务、超级管理员学校列表和运营总览。
- 独立模拟账号使用不可登录密码。校内叠加学生使用平台允许的课堂测试密码 `123456`，用户名和班级均带 `SIM` 批次前缀，清理后失效。

同一配置产生固定 `dataset_key` 和确定性事件 UUID。重复执行直接复用既有成功批次，不重复写入。不同配置不能写入同一模拟学校代码。

## 3. 生成机制

`clean_baseline` 场景先为每名学生生成连续潜变量，再按周生成课程、课时、课堂和学习行为：

- 先验掌握、投入和自我调节来自有界分布，并保留班级随机效应。
- 周掌握状态由先验掌握、班级效应、个体成长率和小幅随机扰动共同决定。
- 资源查看概率由投入和自我调节决定。
- 题目提交概率由投入、自我调节和是否查看资源决定。
- 正确概率使用掌握状态、自我调节和资源曝光的 logistic 函数。
- 作答时长由反应速度和掌握状态决定，并加入有界噪声。
- 教师支持由未提交、错误和低投入概率触发，作为干预事实，不作为能力真值。

当前生成事件包括：

- `content.released`
- `lesson.entered`
- `session.heartbeat`
- `document.progress`
- `item.submitted`
- `item.graded`
- `lesson.step.completed`
- `intervention.created`

生成过程调用正式 `record_learning_event()`，同时产生 V1/V2、机会、状态转移、评分事实和摄取计数，不绕过生产契约直接批量插表。

## 4. 使用命令

只估算、不写数据库：

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_learning_data `
  --school-code SIM-RESEARCH `
  --classes 4 `
  --students-per-class 30 `
  --weeks 8 `
  --end-date 2026-07-18 `
  --dry-run
```

生成并立即运行独立质量报告：

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_learning_data `
  --school-code SIM-RESEARCH `
  --school-name "STRATA 合成研究学校" `
  --seed 20260719 `
  --classes 4 `
  --students-per-class 30 `
  --weeks 8 `
  --end-date 2026-07-18
```

在现有学校中叠加界面测试数据：

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_learning_data `
  --mode school_overlay `
  --school-code 001 `
  --school-name "中山市小榄中学" `
  --teacher-username foldkant `
  --seed 20260720 `
  --classes 2 `
  --students-per-class 12 `
  --weeks 4 `
  --end-date 2026-07-18
```

清理前预览：

```powershell
.\.venv\Scripts\python.exe manage.py purge_synthetic_learning_data `
  --run-id <run UUID> `
  --dry-run
```

正式清理必须同时提供完整数据集指纹：

```powershell
.\.venv\Scripts\python.exe manage.py purge_synthetic_learning_data `
  --run-id <run UUID> `
  --confirm-key <64 位 dataset_key>
```

清理按质量报告、评分、状态事实、机会、事件、课程、班级和账号的依赖顺序执行；保留目标学校和校内叠加所使用的真实教师账号。

参数上限为 24 个班、每班 60 人、52 周。大规模压力数据应使用专用 PostgreSQL 研究库，不在学校正式库中生成。

## 5. 当前开发库证据

开发库批次 `a948d4cd-df91-4be3-9dd2-5a0fda8fd4e6`：

- 4 个班、120 名学生、8 周。
- 8 个课时、32 节课堂。
- 4,529 条 V2 事件、1,920 个学习机会。
- 593 次题目提交和 593 个最终评分事实。
- 120 条隐藏真值。
- 质量报告为绿色，无质量问题。
- 语义缺失率为 0，V1/V2 差异率为 0。
- 相同配置重跑返回 `reused=true`，事件数和清单指纹不变。

小榄中学校内叠加批次 `a68fec53-0903-475d-ac40-93336d9e06d2`：

- 归属教师 `foldkant`，2 个模拟班、24 名模拟学生、4 周。
- 477 条 V2 事件、192 个学习机会，合成报告绿色。
- 正式学校报告仍为 16 条事件、语义缺失率 37.5% 的红色报告。
- 已完成一次整批清理和同配置重建演练，学校、真实教师和正式报告均保留。
- 示例学生：`sim_b94bb297_c01s001`，测试密码 `123456`。

开发数据库位于 Git 忽略目录，以上 UUID 只作为本机验收证据，不是安装后必须存在的固定数据。

## 6. 进入后续阶段的规则

合成轨道通过后可开始 `MEAS-01A` 的数据库、API、版本冻结和测试实现，但仍需区分：

- 合成工程通过：说明契约、重算和错误处理可运行。
- 专家内容审查通过：说明量规和题目具有初步内容效度。
- 真实试评通过：才允许估计评分一致性、题目参数和共同测量质量。
- 真实结局成熟：才允许执行 M5 候选模型比较。

M2 完成后才能建设 M3 冻结特征注册和结局合同。M3 完成前不增加真实模型训练入口。
