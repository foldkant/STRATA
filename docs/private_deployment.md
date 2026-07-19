# 私有化部署说明

本项目要求在离线局域网内可运行。推荐部署形态：

- 应用服务器：Windows Server 或 Linux
- Python：3.12.x
- 数据库：PostgreSQL 16/17
- 缓存与消息：Redis 7.x
- Web 后端：Django ASGI
- 后台任务：Celery worker + Celery beat
- 文件存储：本机目录起步，后期可换 MinIO

## 为什么选 Python 3.12

Python 3.12 对 Django、Celery、Channels、PostgreSQL 驱动、NumPy、pandas、scikit-learn 等生态兼容性更稳。Python 3.14 太新，离线部署时很多 AI 二进制包更容易缺 wheel。

## 服务端口建议

- Django/ASGI：8000 或安装向导自动选择的可用端口
- PostgreSQL：5432
- Redis：6379
- 前端静态服务：80 或 8080

注意：如果安装了 ONLYOFFICE Document Server，它可能占用 `80` 或 `8000` 等端口。STRATA 后续 setup 需要检测端口占用并允许调整，不应假设 `8000` 永远可用。

## Windows 局域网安装建议

当前机器没有 PostgreSQL、Redis、Docker，但存在 Chocolatey。联网准备机可用：

```powershell
choco install postgresql redis-64 -y
```

离线环境建议提前下载 PostgreSQL 和 Redis 安装包，放入内网软件库。安装完成后创建数据库：

```sql
CREATE USER xlzxedu WITH PASSWORD 'your-private-password';
CREATE DATABASE xlzxedu OWNER xlzxedu ENCODING 'UTF8';
```

也可以参考 `deploy/postgres_init.sql`，执行前必须替换默认密码。

PostgreSQL 安装并启动后，可执行：

```powershell
.\scripts\switch_to_postgres.ps1
```

该脚本会把 `.env` 从 SQLite 切换到 PostgreSQL 并执行 Django 迁移。

## Redis 用途

- Channels WebSocket channel layer
- Celery broker
- Celery result backend

建议生产环境 Redis 配置密码和局域网访问白名单。

## ONLYOFFICE 可选组件

ONLYOFFICE 只作为 Office 预览、在线编辑和多人协作的增强组件，不作为 STRATA 必装依赖。

本地根目录当前已有离线安装包：

```text
E:\newproject\onlyoffice-documentserver.exe
```

后续 setup 应按以下逻辑处理：

1. 先检测当前服务器是否已安装 ONLYOFFICE。
2. 检测 Document Server 地址和 `/web-apps/apps/api/documents/api.js`。
3. 检测端口占用，必要时调整 STRATA 端口或配置 ONLYOFFICE 地址。
4. 未安装时提示用户是否安装离线包。
5. 安装失败时继续完成 STRATA 主系统安装，仅关闭协作编辑能力。
6. 检测结果写入 `.env`：

```env
ONLYOFFICE_ENABLED=false
ONLYOFFICE_DOCUMENT_SERVER_URL=
```

当前已提供 Django 检测命令，后续 setup 安装器应直接调用它：

```powershell
.\.venv\Scripts\python.exe manage.py sync_onlyoffice_config --write-env
```

如果学校的 ONLYOFFICE 安装路径或访问地址不同：

```powershell
.\.venv\Scripts\python.exe manage.py sync_onlyoffice_config `
  --config "D:\Program Files\ONLYOFFICE\DocumentServer\config\local.json" `
  --server-url "http://192.168.1.10" `
  --write-env
```

该命令会检测 ONLYOFFICE 是否启用浏览器 JWT，并把 `ONLYOFFICE_DOCUMENT_SERVER_URL` 和 `ONLYOFFICE_JWT_SECRET` 写入 `.env`。JWT 密钥只写入配置文件，不在命令输出中明文显示。

没有 ONLYOFFICE 时，资源仍应支持降级预览：

- PDF：PDF.js 离线预览。
- 图片、音频、视频：浏览器原生预览。
- Word、PPT、Excel：优先使用 LibreOffice headless 转 PDF 预览；不能转换时允许下载。
- Excel：可选用 Python `openpyxl` 生成表格预览。
- 压缩包：显示文件清单，不默认解压到公开目录。

因此成员校即使无法安装 ONLYOFFICE，也能完成课程学习、课堂投放、资源查看和作答；只是不能使用多人协作编辑。

## 启动顺序

1. PostgreSQL
2. Redis
3. Django migration
4. ASGI Web 服务
5. Celery worker
6. Celery beat

## 学习事件隔离密钥

正式环境必须为无效事件的短期加密隔离配置独立 Fernet 密钥：

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将结果写入学校服务器本地 `.env`，不得提交 Git 或进入跨校研究包：

```env
LEARNING_EVENT_QUARANTINE_KEY=<Fernet 密钥>
LEARNING_EVENT_QUARANTINE_RETENTION_DAYS=7
LEARNING_EVENT_WRITE_MODE=dual_required
```

PostgreSQL 环境缺失或配置错误时，`manage.py check` 会阻断启动。本地 SQLite 可临时从 `DJANGO_SECRET_KEY` 派生，但不能作为正式部署配置。

数据库迁移后同步事件模式：

```powershell
.\.venv\Scripts\python.exe manage.py sync_learning_event_schemas
```

从旧版事件表升级时，先备份数据库并执行 dry-run，再正式回填和核对：

```powershell
.\.venv\Scripts\python.exe manage.py backfill_learning_event_v2 --dry-run --batch-size 500
.\.venv\Scripts\python.exe manage.py backfill_learning_event_v2 --batch-size 500
.\.venv\Scripts\python.exe manage.py reconcile_learning_event_writes --check
```

不能确定含义的旧记录必须保留为“未转换”状态，不得手工改成已接受记录，也不得据此补造学习任务关联。

清理超过保留期限的隔离事件：

```powershell
.\.venv\Scripts\python.exe manage.py purge_expired_event_rejections
```

开发命令：

```powershell
.\scripts\run_dev.ps1
```

Celery worker：

```powershell
.\.venv\Scripts\celery.exe -A config worker -l info --pool=solo
```

Celery beat：

```powershell
.\.venv\Scripts\celery.exe -A config beat -l info
```

## 课堂聊天部署补充

课堂实时聊天要求正式环境使用 Redis channel layer：

```env
CHANNEL_LAYER_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

开发机未安装 Redis 时可使用 `CHANNEL_LAYER_BACKEND=memory`，但只支持单个 ASGI 进程，不能用于学校正式多进程部署。

必须使用 ASGI 启动：

```powershell
.\scripts\run_asgi.ps1 -Port 8010
```

`run_dev.ps1`、`run_lan.ps1` 和 `start_lan_background.ps1` 已统一使用 Uvicorn。Waitress/WSGI 不支持 WebSocket，`run_waitress_lan.ps1` 现会转交 ASGI 启动脚本。

## 学习数据夜间检查

迁移到最新版本后，学校服务器包含学习记录接收数量、自动检查记录、执行阶段、检查报告和测试数据隔离字段。升级顺序：

```powershell
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Celery Beat 默认每天 01:30 检查前一完整自然日的学习数据。正式环境必须同时运行：

```powershell
.\scripts\run_celery_worker.ps1
.\scripts\run_celery_beat.ps1
```

Windows worker 使用 `--pool=solo`。Redis 数据库建议保持隔离：Channel Layer 使用 `/0`、Celery broker 使用 `/1`、结果使用 `/2`。

部署验收：

```powershell
.\.venv\Scripts\celery.exe -A config inspect ping --timeout=5
```

再由学校管理员访问 `/app/school-admin/data-quality` 手动检查最近完整 7 日。报告未通过不代表服务故障；应先查看待处理问题和 XLSX，不得直接修改报告状态。进入后续分析前，必须保存一份最新通过报告及对应检查记录。

便携验证实例可使用非默认端口，但 Web、worker 和 beat 的 `REDIS_URL/CELERY_*` 必须一致。当前工程验证使用 PostgreSQL `55432` 和 Redis 兼容服务 `56379`；这不是学校生产默认端口。

## 模拟数据部署边界

`generate_synthetic_learning_data` 主要用于开发机或独立测试数据库。学校正式库确需做界面验收时可使用 `school_overlay`，但必须先备份、指定真实任课教师，并记录返回的 `run_id` 和完整 `dataset_key`。正式检查报告会排除测试批次，其他普通业务统计在清理前可能显示带 `SIM` 前缀的测试班级和学生。

独立模拟账号使用不可登录密码；校内测试学生统一使用测试密码 `123456`，只能用于受控验收，不能作为正式账号分发。验收后执行 `purge_synthetic_learning_data --run-id ... --confirm-key ...` 整批清理。测试报告只能证明程序和自动检查可运行，不能覆盖本校正式检查报告，也不能作为模型上线依据。
