# STRATA 数智教学系统

STRATA 2.0 是一套面向中学课堂的教学系统。老师可以在这里备课、组织课堂活动、布置测试和评价，学生可以在课堂中查看资源、作答、提交作品并参加小组学习。

系统可以部署在学校自己的服务器和局域网中。日常教学数据保存在校内，不要求学校把学生数据上传到公共云平台。AI 和在线文档都是可选能力，没有配置时也不影响普通备课和上课。

> 项目目前处于持续开发和学校试用阶段，部分研究功能仍需结合真实教学继续验证。

## 老师可以怎样使用

### 课前备课

- 建立课程和课时，并分配给自己的任教班级。
- 按实际教学顺序安排课件、视频、网页、题目、任务和作品提交。
- 从共享题库选题，也可以维护自己的题目并组成测试。
- 提前设置自评、互评和教师评价内容。
- 按需要使用自己的 DeepSeek API 辅助生成题目、评价内容和学习网页。

### 课堂教学

- 开始课堂后，按环节逐步向学生投放学习内容。
- 使用签到、随机点名、抢答、倒计时和课堂广播。
- 查看每道题的提交人数、作答结果和正确情况。
- 开启实名文字聊天，可分别使用全班聊天、师生私聊和小组聊天。
- 开启小组合作，为小组安排成员、协作文档和共享文件空间。
- 课堂结束前按需要开启学生自评、小组互评和教师评价。

### 课后查看

- 查看学生作答、附件、测试结果、课堂表现和评价记录。
- 查看日、近 7 日、近 30 日和单元学习情况。
- 查看系统给出的教学关注建议，并由老师决定是否采用。
- 查看隐性分层和分组建议。学生端不会显示内部层级。

## 一节课怎么走完

1. 老师在“课程备课”中建立课程并选择任教班级。
2. 新建课时，按课堂顺序加入资源、题目、任务和评价内容。
3. 到“课堂教学”中选择课时和班级，新建本次课堂。
4. 开始课堂，在独立的课堂控制台逐个投放学习环节。
5. 根据需要开启签到、互动、小组合作、聊天或评价。
6. 结束课堂，查看学生完成情况和课堂记录。

### 关于“第 n 周学习任务”

课堂实际绑定的是“课时”，不是固定周次。系统不限制一门课程只能有 8 周或 8 个课时。

当前开发数据中出现的“第 n 周学习任务”只是模拟出来的课时名称，不是老师必须填写的周次字段。新建课堂时可以按课时名称或序号搜索，因此一学期安排多少个课时都可以。

### 关于小组共享空间

每个小组的共享文件空间默认是 **20 MB**，界面会明确显示单位 `MB`。老师可按本节课的任务需要调整容量。这个空间主要用于课堂过程材料和小组成果，不建议当作长期网盘使用。

## 四类账户

系统对外只有超级管理员、学校管理员、教师和学生四类账户。

### 超级管理员

用于维护多所学校、学校管理员和系统运行情况，也可以导入成员校交付的数据包进行跨校汇总。成员校不需要持续连接一台公共云服务器。

### 学校管理员

负责本校的教师、学生、班级、任课关系和学科前测；查看本校数据是否完整，以及模型训练和发布情况。学校管理员不代替老师制定课堂评价或调整具体教学活动。

### 教师

负责本人任教班级的课程、课时、课堂、学生、题库、测试、评价标准、资源、公告和留言。老师可以确认、拒绝或人工调整系统给出的教学建议。

### 学生

学生端以课程学习和课堂参与为主，不使用管理后台式页面。新生首次登录后可以修改密码、选择班级并完成相应学科的前测，再进入后续学习。

## 学习记录有什么用

系统记录的是与教学有关的过程事实，例如：

- 学生是否打开资源、观看到什么进度。
- 是否作答、答案是否正确、作答用了多长时间。
- 是否按时提交任务和附件，老师给出了什么评价。
- 签到、抢答、点名、小组合作和课堂互动情况。
- 自评、互评、教师评价和测试结果。

这些记录用来帮助老师了解学生近期学习情况，并为后续分层和分组建议提供依据。系统不会因为一次答错、一次缺勤或一次扣分就自动改变学生层级，也不会绕过老师直接调整学生安排。

开发环境中的模拟数据只用于检查流程能否跑通，不能代替真实教学效果验证。正式研究仍需要真实学校试用、隐私审查和规范的研究设计。

## 私有化部署说明

- Django、Vue、ECharts 和页面资源都由本地服务器提供，不依赖 CDN 或公网字体。
- 开发和单机体验可以使用 SQLite；学校正式部署建议使用 PostgreSQL。
- Redis 用于实时课堂连接和后台任务。
- ONLYOFFICE 是可选组件。安装后可以在网页内预览或协作编辑 Word、PPT 和 Excel；没有安装时，其他课堂功能仍可使用。
- DeepSeek 是老师自愿配置的可选服务。没有填写 API Key 时，普通备课、上课、作答和评价不受影响。
- 学生电脑通过浏览器访问学校服务器，不需要逐台安装 Python、Node.js 或数据库。

## 当前主要功能

| 使用者 | 当前功能 |
| --- | --- |
| 超级管理员 | 学校管理、学校管理员、数据采集、跨校汇总、运行检查 |
| 学校管理员 | 教师、学生、班级、任课关系、学科前测、内容审核、学习数据检查、模型管理 |
| 教师 | 课程备课、课时设计、课堂教学、学生管理、题库、测试、评价、资源、公告、留言、AI 接入、分层建议 |
| 学生 | 首页、课程、实时课堂、资源、测试、公告、留言、学习档案 |

## 给开发和维护人员

### 技术组成

- Python 3.12
- Django 5.2 LTS + Django REST Framework
- Vue 3 + TypeScript + Vite
- PostgreSQL 16/17（学校正式部署建议）
- Redis + Celery + Django Channels
- ECharts

前后端已经分离：业务页面由 Vue 提供，Django 负责接口、权限、数据、后台任务和 WebSocket。

### 第一次安装

项目已经准备离线 Python 依赖包时，在 PowerShell 中执行：

```powershell
.\scripts\install_offline.ps1
```

初始化或更新数据库：

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py sync_learning_event_schemas
.\.venv\Scripts\python.exe manage.py sync_analysis_definitions
```

本地开发默认可以先使用 SQLite。学校正式部署前，再切换到 PostgreSQL 和 Redis。

### 启动系统

只在本机开发：

```powershell
.\scripts\run_dev.ps1 -Port 8010
```

让同一局域网的电脑访问：

```powershell
.\scripts\run_lan.ps1 -Port 8010
```

在服务器后台运行：

```powershell
.\scripts\start_lan_background.ps1 -Port 8010
```

启动后访问：

```text
http://127.0.0.1:8010
http://<学校服务器的局域网 IP>:8010
```

实时课堂和聊天使用 WebSocket。正式部署应使用项目提供的 ASGI 启动方式，而不是只运行 Django 开发服务器。

### 修改和构建前端

Vue 源码位于 `frontend/`。修改后执行：

```powershell
cd frontend
npm.cmd install
npm.cmd run build
cd ..
```

构建结果会写入 `static/frontend/`。只有开发机需要 Node.js，普通教师机和学生机不需要安装。

### PostgreSQL 和后台任务

切换数据库配置：

```powershell
.\scripts\switch_to_postgres.ps1
```

启动 Celery 后台任务：

```powershell
.\scripts\run_celery_worker.ps1
.\scripts\run_celery_beat.ps1
```

后台任务用于整理学习记录、生成学习情况汇总，以及在夜间准备新的模型候选版本。候选版本必须经过检查和发布，教学建议仍需老师确认。

### ONLYOFFICE

`.env` 配置示例：

```env
ONLYOFFICE_DOCUMENT_SERVER_URL=http://127.0.0.1
ONLYOFFICE_JWT_SECRET=<与 Document Server 一致的密钥>
```

学校服务器地址、端口或密钥改变后，需要重新检测文档服务。具体步骤见 [ONLYOFFICE 集成说明](docs/onlyoffice_integration.md)。

### 模拟一批测试数据

没有真实教学数据时，可以生成一批可清理的模拟数据，用来检查页面、统计和训练流程：

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_learning_data `
  --school-code SIM-RESEARCH `
  --seed 20260719 `
  --classes 4 `
  --students-per-class 30 `
  --weeks 12 `
  --end-date 2026-07-18
```

`--weeks` 支持 `1-52`，这里只表示模拟数据覆盖多少周，不是正式课程的课时上限。先加 `--dry-run` 可以只查看预计生成量。清理方法见 [模拟数据说明](docs/synthetic_data_research_track.md)。

## 项目目录

```text
accounts/           账户、登录和权限
school/             学校、班级、学生档案和任课关系
courses/            学科、课程、课时、课堂、小组和评价
learning/           学习记录、前测、测试、作品、公告和留言
learning_analytics/ 学习情况汇总、数据检查、分层和模型服务
realtime/           课堂聊天、消息规则和 WebSocket
aiops/              教师 AI 配置、模型版本和训练任务
api/                Django 接口
frontend/           Vue 前端源码
static/frontend/    已构建的前端文件
scripts/            安装、启动和维护脚本
docs/               业务、架构、部署和研究文档
storage/            本地数据库、媒体、模型和运行数据
```

## 提交代码前检查

检查 Django 配置和迁移：

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

检查前端构建：

```powershell
cd frontend
npm.cmd run build
```

检查 Git 差异：

```powershell
git diff --check
```

## 数据和账号边界

- 学校数据库、上传文件、模型文件、日志和备份包不提交到 Git。
- 超级管理员和学校管理员必须使用高强度密码。
- 学生可以使用便于课堂登录的初始密码，并在首次使用时修改。
- 学校、班级和账户必须先停用或归档，之后才能删除。
- 学生看不到内部层级、模型置信度和教师干预记录。
- AI 生成的题目、评价和学习网页必须经过老师确认后才能发布。

## 继续阅读

完整文档索引见 [docs/README.md](docs/README.md)。常用文档包括：

- [私有化部署](docs/private_deployment.md)
- [教师端功能设计](docs/teacher_module_design.md)
- [学生端功能设计](docs/student_module_design.md)
- [课时设计与课堂教学](docs/teacher_lesson_classroom_redesign.md)
- [测试与共享题库](docs/assessment_module_design.md)
- [课堂实名聊天](docs/classroom_chat_design.md)
- [教学资源中心](docs/resource_center_design.md)
- [学习数据检查](docs/data_quality_pipeline.md)
- [动态分层设计报告](docs/student_behavior_ai_stratification_design.md)
- [模型发布与回滚](docs/model_release_operations.md)
- [学校试用方案](docs/school_pilot_protocol.md)
