# STRATA 模拟数据开发与研究说明

## 共同掌握夜间任务验收（2026-07-20）

`seed_mastery_pipeline_acceptance` 只为模拟学校生成带 `[TEST]` 前缀的共同题测试、答卷和可清理掌握候选。默认拒绝正式学校，必须提供 `--confirmation TEST-DATA-ONLY`；`--clear` 按测试标题清除测试场次、掌握结果和候选。该数据只验证共同测量、层级迁移保护和 Celery 夜间任务，不能用于效度、公平性、跨校或教学效果结论。

> 工作包：`SIM-01`  
> 版本：`synthetic-v2`  
> 状态：生成、分析、模型比较、班级校准和整批清理验证完成，2026-07-20。

## 1. 目的与边界

平台尚无足以支持评价验证和模型研究的真实纵向数据。模拟数据用于提前验证事件、学习任务、评分、数据检查、特征和模型自动流程的工程正确性，不用于证明真实学生上的预测性能或教学效果。

固定采用双轨制：

- 正式学校继续使用真实数据检查报告。模拟数据不能替换、稀释或改变正式学校结果。
- 模拟数据使用独立模拟学校、生成批次和模拟参考值，只允许推进评价、题目、学习情况汇总以及后续模型恢复测试。
- 模拟数据得到的准确率、AUC、分层迁移率和干预效果不得写成平台实证结果。
- 正式试点前必须重新完成正式学习数据检查、评价标准、共同测试、样本量和伦理治理验收。

## 2. 隔离机制

支持两种模式：

- `isolated_school`：创建 `is_synthetic=true` 的独立研究学校，适合大规模数据和算法开发。
- `school_overlay`：把带 `SIM-批次` 前缀的班级、课程和学生放入现有学校，用于现有管理员、教师和学生界面的实测。

- `School.is_synthetic=true` 标识模拟学校。
- `SyntheticDatasetRun` 保存生成版本、随机种子、时间窗口、完整配置、计数和清单 SHA-256。
- `LearningEventV2.synthetic_run` 把每条模拟新版记录追溯到唯一生成批次。
- 旧业务兼容记录的 `metadata.synthetic=true`，并保存批次、生成器版本和数据集校验码。
- `SyntheticStudentTruth` 保存生成模拟数据所需的先验掌握、投入、自我调节、反应速度、成长率和班级效应。这些模拟参考值禁止进入正式特征、学生接口和运营页面。
- `AnalyticsPipelineRun`、`DataQualityReport` 和 `EventIngestionDailyCounter` 均可关联生成批次。正式学校报告固定读取 `synthetic_run IS NULL`，叠加数据只进入对应批次报告。
- 独立模拟学校不进入夜间正式任务、超级管理员学校列表和运营总览。
- 独立模拟账号使用不可登录密码。校内叠加学生使用平台允许的课堂测试密码 `123456`，用户名和班级均带 `SIM` 批次前缀，清理后失效。
- `synthetic-v2` 为每个必做学习机会生成明确截止时间，以便真实计算未来完成和逾期结果；没有截止时间的任务不能伪造为 0 次逾期。

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

生成过程调用正式 `record_learning_event()`，同时产生新旧记录、学习任务关联、状态变化、评分记录和接收计数，不绕过生产接口直接批量插表。

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

生成并立即运行独立检查报告：

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_learning_data `
  --school-code SIM-RESEARCH `
  --school-name "STRATA 模拟数据学校" `
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

清理按检查报告、评分、状态记录、学习任务、事件、课程、班级和账号的依赖顺序执行；保留目标学校和校内测试所使用的真实教师账号。

模型训练只会生成候选建议，不会自动给学生写入层级。为了验收教师建议、课堂分层投放和按层分组，测试批次可以显式执行一次“发布并模拟教师采纳”：

```powershell
.\.venv\Scripts\python.exe manage.py complete_synthetic_stratification `
  --calibration-id <MODEL-03 候选记录 ID> `
  --actor-username <超级管理员或本校管理员账号> `
  --confirm-key <64 位 dataset_key>
```

该命令只接受已成功生成的 `SyntheticDatasetRun`，并逐一核对候选学生是否属于该批次。正式数据版本、其他学校管理员、错误批次指纹和非候选模型都会被拒绝。执行后：

- 发布该测试候选，教师端可以查看对应建议。
- 将建议标记为测试环境中的模拟教师采纳，并写入测试学生的过渡期 `current_layer` 缓存。
- 返回每个测试班的 A/B/C 数量，可直接验收学生管理、教师学生列表、分层题投放和课堂分组。
- 重复执行不会重复产生发布记录或重复修改已验收学生。
- 清理合成批次时，测试学生、层级缓存和候选审核记录一并删除。

这一步只用于工程验收，不代表模型建议被真实教师接受，也不能作为模型有效性、教师接受度或教学效果的研究结果。

参数上限为 24 个班、每班 60 人、52 周。大规模压力数据应使用专用 PostgreSQL 研究库，不在学校正式库中生成。

## 5. 当前开发库证据

开发库批次 `a948d4cd-df91-4be3-9dd2-5a0fda8fd4e6`：

- 4 个班、120 名学生、8 周。
- 8 个课时、32 节课堂。
- 4,529 条新版事件、1,920 个学习任务关联。
- 593 次题目提交和 593 个最终评分事实。
- 120 条模拟参考值。
- 检查报告为绿色，无待处理问题。
- 旧事件未转换比例为 0，新旧记录差异率为 0。
- 相同配置重跑返回 `reused=true`，事件数和清单指纹不变。

小榄中学校内叠加批次 `a68fec53-0903-475d-ac40-93336d9e06d2`：

- 归属教师 `foldkant`，2 个模拟班、24 名模拟学生、4 周。
- 477 条新版事件、192 个学习任务关联，批次检查报告通过。
- 正式学校原有 6 条旧测试事件已确认清理；重新检查为 10 条正式事件、旧事件未转换比例 0%，报告为绿色。
- 已完成一次整批清理和同配置重建演练，学校、真实教师和正式报告均保留。
- 示例学生：`sim_b94bb297_c01s001`，测试密码 `123456`。

开发数据库位于 Git 忽略目录，以上 UUID 只作为本机验收证据，不是安装后必须存在的固定数据。

## 6. 进入后续阶段的规则

模拟数据流程通过后可开始评价管理的数据库、API、版本管理和测试实现，但仍需区分：

- 模拟数据工程通过：说明数据约定、重算和错误处理可运行。
- 专家内容审查通过：说明评价标准和题目具有初步内容效度。
- 真实试评通过：才允许估计评分一致性、题目参数和共同测量质量。
- 真实学习结果达到约定样本量后，才允许比较候选模型。

评价与题目流程完成后才能建设正式学习情况汇总和结果记录。在这些工作完成前，不增加真实模型训练入口。
