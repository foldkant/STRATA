# P0 数据库、媒体与代码回滚手册

> 手册编号：`P0-ROLLBACK-20260722-v1`  
> 当前已演练范围：Windows 单机 SQLite 开发环境的备份复制、完整性检查、前向迁移和应用检查  
> 未演练范围：生产 PostgreSQL 恢复、正式媒体快照切换、学校生产服务编排。未演练不能写成已通过。

## 1. 回滚原则

1. 回滚前先停止新写入，不在 Web、Celery、课程标准 OCR 或定时任务仍写数据库时覆盖文件。
2. 数据库、媒体和代码必须恢复到相互匹配的同一发布基线；不能只恢复数据库却保留不兼容代码。
3. 永远先把失败现场复制到隔离位置，再恢复旧版本；不得用 `git reset --hard` 或直接删除当前数据库。
4. 先在副本验证哈希、数据库完整性和迁移计划，再切换正式路径。
5. 回滚后的历史课程标准版本、评价版本和审计记录不得因“恢复当前版本”而被物理删除。
6. 任一哈希不符、备份不可读、迁移计划包含未知操作或验证失败均停止切换并升级处理。

## 2. 回滚触发条件

- 数据库迁移失败或迁移后出现结构不一致；
- 课程标准后台任务留下无法由事务回滚的异常状态；
- 发布版本、权限或历史引用被错误改写；
- 测试数据进入正式统计、模型训练或研究数据版本；
- 新代码无法读取既有数据库或媒体；
- 出现数据丢失、越权、隐私外泄或无法解释的批量变更。

普通单任务失败优先使用任务级失败保护和显式重试；只有影响数据库、媒体或发布基线时才执行整套回滚。

## 3. 发布前必须准备的恢复包

每个可发布基线必须包含：

```text
release_id/
  database/
    database.sqlite3 或 PostgreSQL 自定义格式备份
    database.sha256
  media/
    curriculum_standards/...
    media-manifest.tsv
    media-manifest.sha256
  code/
    Git commit + tag，或不可变源码包
    requirements 锁定文件
    code-manifest.sha256
  metadata/
    p0_baseline_manifest.json
    migration-plan.txt
    test-results.txt
```

本轮最终代码以专用分支提交和本地 Git 标签固定，具体标识写入 `p0_baseline_manifest.json`。本地标签可恢复当前工作站源码；跨机器或生产恢复仍须把该标签推送到受控远端，或生成并校验不可变源码包。

## 4. SQLite 回滚步骤

### 4.1 停止写入并记录现场

1. 禁止新的管理写操作。
2. 查看课程标准专用 worker 状态：

```powershell
./scripts/get_curriculum_ocr_worker_status.ps1
```

3. 等待运行任务到达页级安全点。普通停止脚本在存在 `running/cancelling` 时应拒绝停止：

```powershell
./scripts/stop_curriculum_ocr_worker.ps1
```

4. 停止 Web、普通 Celery worker 和 beat。具体 PID 或 Windows 服务名必须从当次部署记录读取，不能模糊结束全部 Python 进程。
5. 保存失败现场数据库，不覆盖：

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item -LiteralPath "storage/dev.sqlite3" `
  -Destination "storage/cleanup_backups/dev-failed-$stamp.sqlite3"
Get-FileHash "storage/cleanup_backups/dev-failed-$stamp.sqlite3" -Algorithm SHA256
```

### 4.2 在隔离副本验证恢复源

```powershell
$backup = "storage/cleanup_backups/dev-before-curriculum-queue-20260722-104511.sqlite3"
$stagingDir = "tmp/p0_restore_validation"
$stagingDb = "$stagingDir/restored.sqlite3"
New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
Copy-Item -LiteralPath $backup -Destination $stagingDb -Force
Get-FileHash -LiteralPath $backup -Algorithm SHA256
Get-FileHash -LiteralPath $stagingDb -Algorithm SHA256
```

两个 SHA-256 必须完全一致。随后只读检查：

```powershell
$env:DRILL_DB = (Resolve-Path $stagingDb).Path
@'
import os, sqlite3
p = os.environ["DRILL_DB"]
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
print(con.execute("PRAGMA quick_check").fetchone()[0])
print(con.execute("SELECT COUNT(*) FROM django_migrations").fetchone()[0])
con.close()
'@ | ./.venv/Scripts/python.exe -
```

输出必须包含 `ok`。再把应用指向隔离副本，检查待应用迁移：

```powershell
$env:DATABASE_ENGINE = "sqlite"
$env:DATABASE_NAME = (Resolve-Path $stagingDb).Path
./.venv/Scripts/python.exe manage.py migrate --plan
./.venv/Scripts/python.exe manage.py check
```

未知迁移或系统检查失败时停止，不能切换正式数据库。

### 4.3 切换数据库

只有完成 4.1 和 4.2 后才能执行。先核对绝对路径均位于项目的 `storage` 目录，再使用同一 PowerShell 会话完成：

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$current = (Resolve-Path "storage/dev.sqlite3").Path
$quarantine = Join-Path (Split-Path $current) "dev-quarantine-$stamp.sqlite3"
$verified = (Resolve-Path "tmp/p0_restore_validation/restored.sqlite3").Path
Move-Item -LiteralPath $current -Destination $quarantine
Copy-Item -LiteralPath $verified -Destination $current
```

切换后重新设置 `DATABASE_NAME=storage/dev.sqlite3`，执行：

```powershell
./.venv/Scripts/python.exe manage.py showmigrations
./.venv/Scripts/python.exe manage.py migrate --plan
./.venv/Scripts/python.exe manage.py check
```

如恢复目标需要与当前代码共同运行，只能应用事先审查的前向迁移。不得为了让检查通过而临时生成迁移。

## 5. 课程标准媒体回滚

数据库中的课程标准版本保存文件路径和 SHA-256，因此媒体恢复必须与数据库基线一致。

### 5.1 创建非覆盖媒体快照

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$source = "storage/media/curriculum_standards/official"
$snapshot = "storage/media_backups/curriculum-standards-$stamp/official"
New-Item -ItemType Directory -Force -Path $snapshot | Out-Null
Copy-Item -Path (Join-Path $source "*") -Destination $snapshot -Recurse
```

生成按相对路径排序的 `路径 + 字节数 + SHA-256` 清单，并保存清单自身 SHA-256。发布后新增或替换 PDF 时必须建立新快照，不能覆盖旧快照。

### 5.2 验证并切换媒体

1. 把媒体快照复制到新的 staging 目录。
2. 重算文件数、总字节数和清单 SHA-256；必须与基线 manifest 一致。
3. 随机抽查并通过数据库记录核对每个课程标准版本的 `file_sha256`。
4. 停止 Web 和 worker 后，将当前媒体目录移动到隔离目录，再把 staging 目录移动到正式路径。
5. 不删除隔离目录，直到数据库、PDF 下载、Markdown/JSONL 导出和后台任务验证完成。

当前 P0 媒体基线为 70 个文件、498,750,733 字节，清单 SHA-256 为 `deccd6415fafe0bde17b495dcefd56a2f5eaa9eb3bacdbfc0743087fab2526e9`。其中包含 69 个 PDF/资产文件和 1 个说明文件；具体目录统计见 `p0_baseline_manifest.json`。

## 6. 代码回滚

### 6.1 有 Git 发布标签时

不要在当前脏工作区直接 checkout。使用独立工作树验证目标标签：

```powershell
git worktree add "tmp/p0-code-restore" "baseline/p0-p1-20260722"
git -C "tmp/p0-code-restore" status --short
```

核对依赖锁文件、基线 manifest 和源码哈希，在独立目录完成测试和构建，再由部署工具切换应用目录。原工作区保留，不执行 `git reset --hard`。

### 6.2 只有不可变源码包时

1. 验证源码包 SHA-256；
2. 解压到新的版本目录，不覆盖当前目录；
3. 按包内锁文件建立独立虚拟环境；
4. 把数据库和媒体指向匹配的恢复基线；
5. 完成系统检查、后端测试和前端构建后再切换服务入口。

当前 P0 工作区没有提交或标签，因此不能宣称已经具备代码字节级回滚。主任务建立提交/标签或源码包后，应把标识和哈希追加到基线 manifest。

## 7. 恢复后验收

最低检查顺序：

```powershell
./.venv/Scripts/python.exe manage.py check
./.venv/Scripts/python.exe manage.py showmigrations
./.venv/Scripts/python.exe manage.py test curriculum_standards
./.venv/Scripts/python.exe manage.py test learning_analytics.tests.test_legacy_evaluation_migration learning_analytics.tests.test_test_data_governance
```

随后人工核对：

- 超级管理员、学校管理员、教师、学生的课程标准权限；
- 一个课程标准 PDF、逐页文本、JSONL 和原文页码；
- 当前使用版本与历史版本引用没有被静默替换；
- 旧评价迁移草稿仍为草稿；
- 测试数据批次清单与台账一致；
- OCR 队列没有把恢复前的失联任务误判为已完成。

只有检查通过后才按“Web → 普通 worker/beat → 课程标准专用 worker”的顺序恢复服务。任一步失败均保持停服或只读状态，并保留失败现场。

## 8. PostgreSQL 生产恢复边界

正式学校 PostgreSQL 必须使用同版本 `pg_dump`/`pg_restore`，在隔离数据库先完成恢复和校验，再按发布流程切换连接。`--clean`、删除数据库或覆盖 schema 都属于破坏性操作，必须有单独审批、停服确认和第二人复核。本次仅完成 SQLite 演练，不能据此声称 PostgreSQL 恢复已经验证。

## 9. 2026-07-22 非破坏性恢复演练记录

| 项目 | 真实结果 |
| --- | --- |
| 恢复源 | `storage/cleanup_backups/dev-before-curriculum-queue-20260722-104511.sqlite3` |
| 源文件 | 110,886,912 字节；SHA-256 `d38d8f64ede4e32f7ae5ae2259897d780472876ba64e8252d9a3fbb935e38c95` |
| 隔离副本 | `tmp/p0_restore_drill/restored.sqlite3`；复制完成时字节数与 SHA-256 和源文件一致 |
| 复制后只读检查 | `PRAGMA quick_check=ok`；136 条已应用迁移；3 所学校、6 门课程、48 个课程标准版本 |
| 副本前向迁移 | 成功应用 `curriculum_standards.0002`、`0003`、`0004` 和 `learning_analytics.0032`；没有修改 `storage/dev.sqlite3` |
| 迁移后检查 | 140 条已应用迁移；测试批次表和对象标记表均存在；`is_active/revoked_at/revoked_by_id/revocation_reason` 撤销字段齐全；`PRAGMA quick_check=ok`；`manage.py check` 为 0 个问题 |
| 迁移后副本 | 111,116,288 字节；SHA-256 `e967f345ffcc95149f26585f5455a94319203f483bd6d2b58b677d8bdf0f3590` |
| 正式路径切换 | 未执行；本次是非破坏性副本演练 |
| 开发库写入 | 0；OCR worker 未停止、未重启、未改变任务 |

演练证明当前 SQLite 备份可复制、可读取，并能在隔离副本应用已审查迁移后通过完整性和 Django 系统检查。它不证明媒体切换、代码发布包、PostgreSQL 或生产服务编排已经演练。

## 10. 2026-07-22 P0—P1 开发库迁移记录

| 项目 | 真实结果 |
| --- | --- |
| 安全停写 | 先请求取消全部排队/运行中的旧课程标准任务，再停止专用 worker 和 Web；确认没有遗留写进程后执行备份 |
| 最终迁移前备份 | `storage/cleanup_backups/dev-before-p0-p1-final-20260722-120728.sqlite3` |
| 备份校验 | 111,587,328 字节；SHA-256 `781cbbb46369d7b30d995debca35a6b983493401a8b87c5178bc96245a93c513`；`PRAGMA quick_check=ok` |
| 已应用迁移 | `curriculum_standards.0004`、`learning_analytics.0032`；迁移后共 140 条已应用迁移 |
| 数据登记 | `TEST-MANUAL-COURSE-4-20260722` 首次正式登记为 `CREATED`，重复执行为 `UNCHANGED` |
| 迁移后检查 | `manage.py check` 为 0 个问题；`makemigrations --check --dry-run` 无待生成迁移；开发库 `PRAGMA quick_check=ok` |
| 服务恢复 | Web 在 8010 端口恢复并通过 `/api/health/`；课程标准 worker 以单并发、低优先级和 2 个逻辑处理器限制恢复 |

如需撤销本次 P0—P1 数据结构和正式登记，优先按第 5—7 节在隔离副本验证上述最终迁移前备份，再同时切换与其匹配的代码版本。不得在 worker 运行时直接反向迁移或覆盖 `storage/dev.sqlite3`。
