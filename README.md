# STRATA数智教学系统

STRATA 是面向中学课堂的过程性评价与分层教学平台。系统采用学校局域网私有化部署，正式业务由 Vue 3 前端和 Django ASGI 后端承载，支持课程备课、课堂控制、过程数据采集、学科前测、测试题库、小组协作、AI 学习网页、实名课堂聊天和后续班级模型训练。

核心业务不依赖云服务器或公网服务。ONLYOFFICE、DeepSeek 和模型训练均为可选增强能力，未启用时不影响普通教学、作答、评价和数据留存。

## 当前状态

当前为 2.0 重构开发版，已经从旧 PHP/MySQL 项目迁移到前后端分离架构。

已实现的主要模块：

- 超级管理员：数据总览、学校管理、学校管理员管理。
- 学校管理员：教师管理、学生管理、班级管理、任课关系、学科前测、评价管理、跨校资源审核和学习数据检查。
- 教师：工作台、任教学生、课程与课时设计、课堂教学、公告、反馈、教学资源中心、AI 接入、共享题库和测试管理。
- 学生：首页、课程学习、教学资源中心、实时课堂、课堂作答、测试、公告、反馈和个人学习档案。
- 课堂能力：签到、随机点名、抢答、倒计时、课堂广播、小组合作、星级评价、附件提交与批阅、AI 学习网页、实名文字聊天。
- 课堂聊天：全班、师生私聊、小组三类范围，本地不良言论判断，教师放行、警告、撤回和确认扣分。
- 文档能力：ONLYOFFICE 在线预览与协作，未安装时保留本地预览和下载降级路线。
- 数据能力：35 个严格事件类型、不可修改的新版学习事件、批量防重复接收、新旧记录兼容写入、历史记录转换、学生学习任务关联、评分版本、课堂积分流水，以及七项学习数据检查指标和夜间自动检查。

当前开发校最近完整 7 日数据检查已通过，旧事件未转换比例为 0%。评价管理已迁移到学校管理员端；正式学校试用、题目质量管理、学生特征和分层建议仍按开发计划继续推进。跨学校数据采集、统一分析和夜间班级模型训练仍在后续开发范围内。

## 技术架构

```text
Vue 3 + TypeScript + Vite
        |
        | REST / WebSocket
        v
Django 5.2 LTS + DRF + Channels
        |
        +-- PostgreSQL（正式）/ SQLite（本机开发）
        +-- Redis（WebSocket、Celery）
        +-- Celery worker + Celery beat
        +-- 本地文件存储，后续可切换 MinIO
        +-- ONLYOFFICE Document Server（可选）
        +-- 教师个人 DeepSeek API（可选）
```

技术基线：

- Python 3.12
- Django 5.2 LTS
- Django REST Framework
- Django Channels + channels-redis
- Celery + django-celery-beat
- PostgreSQL 16/17
- Vue 3 + TypeScript + Pinia + Vue Router
- ECharts
- Uvicorn ASGI

所有前端依赖、图表、样式和业务资源均本地打包，不使用 CDN 或公网字体。

## 目录结构

```text
accounts/           用户与四类角色
school/             学校、班级、学生档案、任课关系
courses/            学科、课程、课时、课堂、小组、评价、AI 学习网页
learning/           行为事件、前测、测试、作品、公告、反馈
learning_analytics/ 学习记录检查、评价版本、隐性分层与后续分析服务
realtime/           课堂聊天模型、过滤规则、WebSocket 消费者
aiops/              教师 AI 配置、模型版本和训练任务底座
api/                DRF 接口、业务服务、序列化和测试
frontend/           Vue 3 正式前端源码
static/frontend/    Vue 生产构建产物
scripts/            本机、局域网、离线安装和任务进程脚本
docs/               架构、业务、API、部署和设计文档
storage/            本地数据库、媒体、模型和运行数据，不提交 Git
```

## 快速启动

### 1. 安装依赖

已有虚拟环境时直接使用 `.venv`。新环境或离线学校服务器执行：

```powershell
.\scripts\install_offline.ps1
```

联网开发机重新准备离线 wheel 包：

```powershell
.\scripts\make_wheelhouse.ps1
```

### 2. 初始化数据库

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py sync_learning_event_schemas
```

本机开发默认使用 `storage/dev.sqlite3`。正式学校部署应切换 PostgreSQL：

```powershell
.\scripts\switch_to_postgres.ps1
```

### 3. 构建前端

```powershell
cd frontend
npm.cmd install
npm.cmd run build
cd ..
```

构建产物写入 `static/frontend/`，Django 直接提供正式 Vue 页面。

### 4. 启动 ASGI 服务

本机：

```powershell
.\scripts\run_dev.ps1 -Port 8010
```

局域网前台运行：

```powershell
.\scripts\run_lan.ps1 -Port 8010
```

局域网后台运行：

```powershell
.\scripts\start_lan_background.ps1 -Port 8010
```

也可以通过环境变量指定端口：

```powershell
$env:STRATA_PORT = "8010"
.\scripts\run_asgi.ps1
```

课堂聊天使用 WebSocket，必须通过 Uvicorn/ASGI 启动，不能使用普通 WSGI 服务代替。

访问地址：

```text
http://127.0.0.1:8010
http://<学校服务器局域网IP>:8010
```

健康检查：

```text
http://127.0.0.1:8010/api/health/
```

## 环境配置

复制 `.env.example` 为 `.env` 后修改。不要把真实密钥、数据库密码或教师 API Key 提交到 Git。

本机单进程开发可以使用：

```env
DATABASE_ENGINE=sqlite
CHANNEL_LAYER_BACKEND=memory
```

学校正式部署至少应设置：

```env
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<随机长密钥>
LEARNING_EVENT_QUARANTINE_KEY=<Fernet 密钥>
LEARNING_EVENT_QUARANTINE_RETENTION_DAYS=7
LEARNING_EVENT_WRITE_MODE=dual_required
DATABASE_ENGINE=postgresql
DATABASE_NAME=xlzxedu
DATABASE_HOST=127.0.0.1
DATABASE_PORT=5432
DATABASE_USER=xlzxedu
DATABASE_PASSWORD=<数据库密码>
CHANNEL_LAYER_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

生产环境还需要配置局域网域名或服务器 IP、HTTPS、Cookie 安全选项、备份目录和 Redis 访问控制。

## 后台任务

Celery worker：

```powershell
.\scripts\run_celery_worker.ps1
```

Celery beat：

```powershell
.\scripts\run_celery_beat.ps1
```

Celery 当前用于每日 01:30 学习数据检查，后续再接特征汇总、班级模型训练、数据导出和学校数据同步任务。

升级或夜间检查可核对新旧学习记录：

```powershell
.\.venv\Scripts\python.exe manage.py reconcile_learning_event_writes --check
```

学校管理员数据检查页面：

```text
http://127.0.0.1:8010/app/school-admin/data-quality
```

检查指标、判断标准和下一阶段条件见 [学习数据检查](docs/data_quality_pipeline.md)。

## 模拟数据

平台无真实纵向样本时，可以在独立模拟学校中生成可复现数据，用于验证 M2/M3 工程，不进入正式运营统计：

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_learning_data `
  --school-code SIM-RESEARCH `
  --seed 20260719 `
  --classes 4 `
  --students-per-class 30 `
  --weeks 8 `
  --end-date 2026-07-18
```

先加 `--dry-run` 可只查看规模估算。相同配置重复执行不会重复造数。完整隔离规则和研究使用边界见[模拟数据开发与研究说明](docs/synthetic_data_research_track.md)。

也可以使用 `--mode school_overlay --school-code <现有学校代码> --teacher-username <教师账号>` 在现有学校中生成带 `SIM` 前缀的界面测试数据。完成后使用 `purge_synthetic_learning_data` 并同时提供 `run_id` 和完整 `dataset_key` 整批清理；正式检查报告不会读取这些测试事件。

## ONLYOFFICE

ONLYOFFICE 是可选组件，用于 Word、PPT、Excel 的网页预览、编辑和小组协作。配置项：

```env
ONLYOFFICE_DOCUMENT_SERVER_URL=http://127.0.0.1
ONLYOFFICE_JWT_SECRET=<与 Document Server 一致的密钥>
```

详细检测、JWT 和降级方案见 [ONLYOFFICE 集成文档](docs/onlyoffice_integration.md)。

## AI 使用边界

- 教师可以配置自己的 DeepSeek API，用于备课、生成题目、评价项和受控学习网页。
- AI 输出先作为教师可修改草稿，不直接发布给学生。
- 学生聊天内容默认只在学校本地处理，不发送给外部 AI。
- AI 学习网页运行在受控 iframe 中，表单回答通过平台接口采集。
- 学生分层、扣分和模型上线必须保留教师确认，不由模型自动决定。

## 验证命令

后端：

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test api.tests
```

前端：

```powershell
cd frontend
npm.cmd run build
```

提交前还应执行：

```powershell
git diff --check
```

## 文档

完整文档导航见 [docs/README.md](docs/README.md)。重点入口：

- [前端架构](docs/frontend_architecture.md)
- [API 契约](docs/api_contract.md)
- [数据模型](docs/data_model.md)
- [私有化部署](docs/private_deployment.md)
- [教师模块](docs/teacher_module_design.md)
- [学生模块](docs/student_module_design.md)
- [课时与课堂重构](docs/teacher_lesson_classroom_redesign.md)
- [测试与共享题库](docs/assessment_module_design.md)
- [课堂实名聊天](docs/classroom_chat_design.md)
- [教学资源中心](docs/resource_center_design.md)
- [AI 隐性动态分层设计报告](docs/student_behavior_ai_stratification_design.md)
- [AI 隐性动态分层开发路线图](docs/student_behavior_ai_stratification_development_roadmap.md)
- [学生评价、积分与奖章设计](docs/student_evaluation_incentive_design.md)

## 安全原则

- 角色只保留超级管理员、学校管理员、教师和学生。
- 管理员和超级管理员必须使用高强度密码；学生可使用便于课堂使用的低强度初始密码，并在首次使用流程中修改。
- 账号、班级和学校删除前必须先停用或归档。
- 所有接口必须在服务端校验学校、班级、任课关系和数据所有权。
- 学生不能看到内部风险标签、模型置信度或教师干预记录。
- `.env`、数据库、媒体文件、模型产物、日志和学校备份包不得提交 Git。
