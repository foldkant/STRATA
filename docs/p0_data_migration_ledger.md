# P0 数据迁移执行台账

> 台账编号：`P0-MIGRATION-20260722-v1`  
> 核对日期：2026-07-22  
> 规则：只记录实际文件、数据库查询、dry-run 或测试结果；未在开发库执行的步骤明确写“待执行”。

## 1. 台账字段

每一项迁移至少记录：源范围、源数量、目标范围、目标数量、迁移批次或来源标记、校验结果、异常、备份、回滚方法和执行状态。只写“脚本存在”不能代替实际迁移记录。

## 2. 数据库保护基线

| 用途 | 文件 | 创建时间 | 字节数 | SHA-256 | 完整性 |
| --- | --- | --- | ---: | --- | --- |
| 旧评价配置迁移前 | `storage/backups/dev-before-evaluation-migration-20260721-221407.sqlite3` | 2026-07-21 22:14:07 | 93,810,688 | `f1cacffff0e50a88d0fe5c8f3f1aa3b717b6f042b8eaa9ccb0a366cc96227ec0` | `PRAGMA quick_check = ok` |
| P0—P1 本轮前 | `storage/cleanup_backups/dev-before-p0-p1-20260722-084350.sqlite3` | 2026-07-22 08:43:50 | 93,810,688 | `0ee6f1f2c6af4ca1779c5a2c42ffa7b4cdc14d9cd9f620872df599b159fb2e6a` | `PRAGMA quick_check = ok` |
| 课程标准后台队列迁移前 | `storage/cleanup_backups/dev-before-curriculum-queue-20260722-104511.sqlite3` | 2026-07-22 10:45:11 | 110,886,912 | `d38d8f64ede4e32f7ae5ae2259897d780472876ba64e8252d9a3fbb935e38c95` | `PRAGMA quick_check = ok` |
| P0—P1 最终迁移前 | `storage/cleanup_backups/dev-before-p0-p1-final-20260722-120728.sqlite3` | 2026-07-22 12:07:28 | 111,587,328 | `781cbbb46369d7b30d995debca35a6b983493401a8b87c5178bc96245a93c513` | `PRAGMA quick_check = ok` |

备份文件位于 Git 忽略目录，只是本机恢复源；正式部署还必须复制到受控的独立存储并验证读取权限和保留期限。

## 3. 已执行迁移

### 3.1 旧课堂评价配置迁移

| 字段 | 实际记录 |
| --- | --- |
| 源备份 | `dev-before-evaluation-migration-20260721-221407.sqlite3` |
| 源对象 | `ClassroomEvaluationConfig=1`、`ClassroomEvaluationConfigVersion=1`、`ClassroomEvaluationSubmission=1` |
| 迁移命令 | `migrate_legacy_evaluation_standards`；命令支持 `--dry-run`，删除旧数据要求 `--confirm DELETE_LEGACY_EVALUATION_DATA` |
| 当前目标对象 | `EvaluationPlan id=2`、`EvaluationStandard id=2` |
| 来源标记 | `legacy-evaluation-config-1-v1` |
| 目标状态 | 方案和标准均为 `draft`；标准含 11 个评价指标，不冒充已发布内容 |
| 当前旧对象 | 配置 0、配置版本 0、旧提交 0 |
| 自动化验证 | `test_legacy_evaluation_migration.py` 覆盖 dry-run 不落库、删除显式确认和迁移结果 |
| 回滚 | 必须停服后恢复上述迁移前整库备份；当前命令没有已提交删除后的反向数据迁移 |
| 结论 | 已执行，但历史教师文本仍须教师复核；`legacy-*` 是来源标记，不是测试数据批次 |

### 3.2 课程标准数据库结构和受控登记

| 字段 | 实际记录 |
| --- | --- |
| 已应用开发库迁移 | `curriculum_standards.0001`—`0004`；最终迁移后全库共 140 条已应用迁移 |
| 登记结果 | 38 个课程标准档案、48 个历史版本；文件重复登记保持幂等 |
| 内容处理 | 逐页记录、内容条目和检索片段按版本保存；最终核对时 33 个版本已完成文本处理、15 个扫描版本由低优先级独立后台队列逐个处理 |
| 检索索引 | 33 个版本索引、4,389 个可追溯检索片段；发布版本严格审计为 2 个版本、0 错误、0 警告 |
| 状态边界 | 信息科技的义务教育 2022 版与普通高中 2025 修订版已按开发环境治理豁免发布并设为当前使用；豁免有明确留痕，不等同于独立学科专家复核。其余版本保持草稿 |
| 回滚 | 数据结构回退前必须停 Web 和专用 worker；优先恢复队列迁移前备份，不在活动任务运行中执行反向迁移 |

本节只记录课程标准数据迁移范围；课程标准处理和复核的详细验收由 `p0_p1_curriculum_governance_acceptance.md` 记录。

## 4. 测试数据批次迁移

### 4.1 已有合成数据批次

开发库只读查询得到 6 个 `SyntheticDatasetRun`：4 个已清理、2 个生成成功。仍在使用的两个批次为：

| 批次 ID | 模式 | 学校范围 | 生成版本 | 状态 | 清单 SHA-256 |
| ---: | --- | --- | --- | --- | --- |
| 5 | `school_overlay` | 正式学校中的受控测试叠加 | `synthetic-v2` | `succeeded` | `3cfab566023fbe169784dfcc0ab991db3b055f8514d64fa90a5f51d8606fac9f` |
| 6 | `isolated_school` | 独立合成测试学校 | `synthetic-v2` | `succeeded` | `e0faf6304dde23fbc32dfe22dea894948ed0f9774fbd161a7e9016870f37f34e` |

合成数据继续由 `SyntheticDatasetRun` 和相关 `synthetic_run` 外键管理，不重复登记为手工批次。

### 4.2 新增的历史/手工测试数据结构

| 项目 | 状态 |
| --- | --- |
| 迁移文件 | `learning_analytics/migrations/0032_testdatabatch_testdataobjectmarker.py` 已生成 |
| 模型 | `TestDataBatch`、`TestDataObjectMarker` 已实现不可变批次和精确对象标记；误标通过撤销状态、撤销人、时间和原因留痕，不删除原登记 |
| 管理命令 | `register_test_data_batch` 已实现超级管理员限制、模型白名单、显式主键、dry-run、确认、幂等和冲突拒绝；`revoke_test_data_marker` 提供受控误标纠正 |
| 正式查询 helper | `exclude_explicit_test_data_objects` 排除仍生效的直接对象标记；`assert_no_explicit_test_data_objects` 在正式范围含测试根对象时阻断 |
| 自动化测试 | 批次治理专项 7/7 通过；与旧评价迁移合计 10/10。隔离内存测试库覆盖登记、幂等、白名单、权限、直接查询排除/阻断和保留审计记录的撤销 |
| 备份副本验证 | 在恢复副本上成功应用 `0032`，两张表均存在，`PRAGMA quick_check=ok`，`manage.py check` 为 0 个问题 |
| 开发库应用 | **已完成**；先取消活动任务、停止专用 worker 与 Web，再建立最终迁移前备份；`learning_analytics.0032` 应用成功，最终全库共 140 条迁移 |

开发库迁移严格在课程标准后台任务安全停写、备份校验完成后执行；迁移完成并核对后，Web 与单并发低优先级 worker 才重新启动。

### 4.3 当前历史/手工对象逐项核对

开发库共有 6 个课程对象。P0 不按名称自动归类，逐项记录如下：

| 对象 | 当前证据 | P0 分类决定 | 后续动作 |
| --- | --- | --- | --- |
| `courses.Course:1`，名称显示为乱码 | 学科为空、来源无法仅凭当前行确认 | 未分类 | 核对创建来源和关联课堂；确认前不删除、不登记测试批次 |
| `courses.Course:3`，“数据与计算” | 正式学校课程，关联迁移后的评价草稿 | 保持现状 | 不因开发库环境自动标为测试数据 |
| `courses.Course:4`，“test” | 用户已明确授权可直接修改现有测试数据，且对象名称和验收用途一致 | 手工测试对象 | 已正式登记为批次 `TEST-MANUAL-COURSE-4-20260722`，禁止进入正式统计、训练或科研结论 |
| `courses.Course:14`，“数据与计算（SIM-AEE9EE85）” | 对应合成批次 5 | 合成数据 | 继续使用 `SyntheticDatasetRun`，不重复登记 |
| `courses.Course:15`，“数据与计算（SIM-93BFA5CC）” | 所属合成学校并对应合成批次 6 | 合成数据 | 继续使用 `SyntheticDatasetRun`，不重复登记 |
| `courses.Course:16`，“111” | 名称可疑但没有足够来源证据 | 未分类 | 负责人核对后再决定；禁止按短标题自动标记 |

评价方案 `id=2` 的 `legacy-evaluation-config-1-v1` 只证明它来源于旧评价配置，不能证明它属于测试批次，因此当前不登记为测试数据。

### 4.4 对课程 4 的 dry-run 与正式登记

执行命令：

```powershell
python manage.py register_test_data_batch `
  --batch-code TEST-MANUAL-COURSE-4-20260722 `
  --purpose acceptance_testing `
  --source-kind historical_manual `
  --description "课程 4 标题明确为 test；仅用于界面和迁移验收，不得进入正式统计、模型训练或科研结论。" `
  --target courses.Course:4 `
  --actor superadmin `
  --dry-run
```

真实结果：

```text
target_count=1
target=courses.course:4
object_label=test
manifest_hash=92505de37c556175d6568be3b710c77195d125dc304bb2ab78e2d2f576554988
database_write=0
```

完成安全停写、最终备份、`0032` 迁移和重复 dry-run 核对后，使用相同参数追加 `--confirm REGISTER_TEST_DATA` 正式登记。实际结果如下：

```text
首次正式登记结果 = CREATED
重复正式登记结果 = UNCHANGED
TestDataBatch(TEST-MANUAL-COURSE-4-20260722) = 1
TestDataObjectMarker(courses.course:4, is_active=true) = 1
manifest_hash = 92505de37c556175d6568be3b710c77195d125dc304bb2ab78e2d2f576554988
```

课程 1 和课程 16 仍因来源证据不足保持未分类；没有按名称猜测或删除。

### 4.5 正式训练与统计污染审计

2026-07-22 对开发库进行了只读审计：

| 检查 | 结果 |
| --- | --- |
| `DecisionPoint` 总数 | 49 |
| `TrainingDatasetVersion` 总数 | 6 |
| `TrainingDatasetRow` 总数 | 3,456 |
| 冻结数据版本范围 | 6/6 均有 `synthetic_run_id`，属于明确合成批次；正式范围数据版本为 0 |
| 课程 4 的分析时间点 | 0 |
| 课程 16 的分析时间点 | 0 |
| 乱码课程 1 的分析时间点 | 0 |

在本次快照中，没有发现课程 1、4、16 已进入现有分析时间点或冻结训练数据版本；现有 6 个数据版本均来自合成批次。因此本次审计未发现已发生的手工测试课程污染，但这只是当前开发库快照，不是永久保证。

标记传播边界必须明确：登记 `courses.Course:4` 只会让课程根对象的统一 helper 排除或阻断该课程，不会自动给课堂、作答、评价材料、学习事件、特征快照或训练数据行逐条加标记。正式分析入口必须先通过 `DecisionPoint.course` 或等价来源把范围解析回课程根对象，执行 `assert_no_explicit_test_data_objects`；无法解析来源时必须拒绝进入正式用途，不能假定“没有直接标记就是正式数据”。当前 helper 和测试已经就绪，所有正式训练/统计入口的统一接线属于后续强制门，在接线完成前不得把手工批次用于任何正式分析。

## 5. 已完成迁移步骤

主任务已在后台任务安全边界依次执行：

```powershell
python manage.py showmigrations learning_analytics
python manage.py migrate --plan
python manage.py migrate learning_analytics 0032 --noinput
python manage.py register_test_data_batch <与 4.4 相同参数> --dry-run
python manage.py register_test_data_batch <与 4.4 相同参数> --confirm REGISTER_TEST_DATA
```

执行后查询结果：

```text
django_migrations 中 learning_analytics.0032 = 1
TestDataBatch(TEST-MANUAL-COURSE-4-20260722) = 1
TestDataObjectMarker(courses.course:4) = 1
manifest_hash = 92505de37c556175d6568be3b710c77195d125dc304bb2ab78e2d2f576554988
重复执行命令结果 = UNCHANGED
```

迁移后的 `manage.py check`、`makemigrations --check --dry-run` 和 `PRAGMA quick_check` 均通过；联合后端回归 88/88 通过。没有待执行的 P0 数据库迁移。

## 6. 迁移验收和停止条件

每次迁移均须满足：

1. 迁移前备份通过 SHA-256 和 `PRAGMA quick_check`；
2. 活动写入已经停止，课程标准任务状态已记录；
3. `migrate --plan` 只包含已审查迁移；
4. 迁移后 `manage.py check`、迁移专项测试和数据库完整性检查通过；
5. 源数量、目标数量、对象主键和清单哈希与台账一致；
6. 重复执行不新增重复对象；
7. 任一数量不符、写锁、完整性失败、未知迁移或清单变化都立即停止，不继续登记或删除数据；
8. 回滚按 `p0_rollback_runbook.md` 执行，并在本台账追加实际恢复结果。
