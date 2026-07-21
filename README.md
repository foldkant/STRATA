# STRATA数智教学系统

STRATA 2.0 是一套面向中学课堂的教学平台。它把备课、课堂活动、学生作答、过程评价和课后查看放在同一个系统里，学校可以部署在自己的服务器和局域网中，不必把学生数据放到云端。

平台仍在持续开发和试用。当前重点不是替代教师，而是让教师更方便地组织课堂，并把原本分散的学习过程记录下来，为后续教学调整提供依据。

## 老师可以用它做什么

- 建立课程和课时，按教学过程依次加入课件、视频、资源、题目、任务和作品提交。
- 在课堂中逐环节投放内容，学生只有在教师开始课堂并投放环节后才能进入。
- 使用签到、随机点名、抢答、倒计时、课堂广播和实名文字聊天。
- 开启小组合作，安排组员、协作文档和小组共享文件。每组共享空间默认 20MB，教师可以调整。
- 建立个人题目，也可以使用学校共享题库组卷和安排测试。
- 制定评价标准，在课堂收尾时按需要开放学生自评、小组互评和教师评价。
- 查看学生作答、附件、测试、评价和近期学习情况。
- 查看系统给出的教学关注建议和隐性分层建议。学生看不到内部层级，是否采用始终由教师决定。
- 选填自己的 DeepSeek API，用于生成备课草稿、题目、评价内容和受控学习网页。

## 一节课的大致流程

1. 在“课程备课”中建立课程，并选择任教班级。
2. 新建课时，按实际教学顺序加入资源、题目和任务。
3. 在“课堂教学”中选择课程、课时和班级，新建本次课堂。
4. 开始课堂后，在独立课堂控制台逐个投放学习环节。
5. 根据教学需要开启签到、互动、小组合作、聊天或评价。
6. 课堂结束后查看学生完成情况、作答结果和过程记录。

课堂绑定的是“课时”，不是固定的第几周。系统不限制课程只能有 8 个课时；新建课堂时可以搜索课时名称或序号。开发库中出现的“第 n 周学习任务”只是模拟数据的课时名称，不是正式学校必须填写的周次字段。

## 不同账户看到什么

### 超级管理员

用于维护多所学校的基础信息、学校管理员账户、数据采集、跨校汇总和运行状态。跨校数据只在明确导入学校数据包后处理，不要求成员校连接公共云服务器。

### 学校管理员

负责本校教师、学生、班级、任课关系和学科前测，也可以查看学校学习数据检查、模型训练记录和候选版本。学校管理员不代替教师给学生做课堂评价。

### 教师

负责课程、课时、课堂、题库、测试、评价标准、公告、资源和本人任教班级的学生。教师可以重置所教学生的课堂密码，也可以确认或调整系统给出的教学建议。

### 学生

学生端以学习和上课为主，不使用管理后台式界面。学生完成首次登录、选择班级和学科前测后，可以进入课程、课堂、测试、资源和个人学习档案。

## 学习记录与分层

平台会记录与教学有关的过程事实，例如：

- 是否进入资源、阅读或观看到什么进度。
- 题目是否作答、是否正确、用了多长时间。
- 任务和附件是否按时提交，教师如何评价。
- 签到、抢答、点名、小组协作和课堂互动情况。
- 自评、互评、教师评价和测试结果。

这些记录用于生成日、7 日、30 日和单元学习情况，也用于后续模型比较。系统不会因为一次答错、一次缺勤或一次教师扣分就自动改变学生层级。

目前开发库使用模拟数据验证训练、发布和回滚流程。模拟结果只能说明程序可以运行，不能直接证明教学效果。正式使用前仍需经过真实学校试用、隐私审查和教学研究验证。

## 私有化与离线运行

- Django、Vue、ECharts 和系统业务资源全部本地提供，不使用 CDN 或公网字体。
- SQLite 可用于单机开发；学校正式部署建议使用 PostgreSQL。
- Redis 用于 WebSocket 和后台任务。
- ONLYOFFICE 是可选组件。安装后可以预览和协作编辑 Word、PPT、Excel；没有安装时仍保留普通课堂、文件下载和其他学习功能。
- DeepSeek 是教师自愿接入的可选能力。未填写 API Key 时，普通备课、上课、作答和评价不受影响。

## 当前已经完成的主要页面

- 超级管理员：总览、学校、学校管理员、数据采集、跨校分析、运行检查。
- 学校管理员：首页、教师、学生、班级、任课关系、学科前测、内容审核、学习数据检查、分层分析与模型记录。
- 教师：工作台、课程备课、课时设计、课堂教学、学生、题库、测试、评价标准、资源、公告、留言、AI 接入和分层建议。
- 学生：首页、课程、实时课堂、资源、测试、公告、留言和学习档案。

## 开发与运行

### 基础版本

- Python 3.12
- Django 5.2 LTS
- Vue 3 + TypeScript + Vite
- PostgreSQL 16/17（正式部署）
- Redis + Celery + Django Channels
- ECharts

### 第一次安装

已有离线依赖包时：

```powershell
.\scripts\install_offline.ps1
```

初始化数据库：

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py sync_learning_event_schemas
.\.venv\Scripts\python.exe manage.py sync_analysis_definitions
```

### 构建前端

开发机修改 Vue 源码后执行：

```powershell
cd frontend
npm.cmd install
npm.cmd run build
cd ..
```

构建结果写入 `static/frontend/`。已经包含构建结果的学校安装包不需要在每台学习电脑上安装 Node.js。

### 启动系统

本机使用：

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

访问地址：

```text
http://127.0.0.1:8010
http://<学校服务器局域网IP>:8010
```

课堂聊天使用 WebSocket，正式运行应使用项目提供的 ASGI 启动脚本。

### PostgreSQL 与后台任务

切换 PostgreSQL：

```powershell
.\scripts\switch_to_postgres.ps1
```

启动 Celery：

```powershell
.\scripts\run_celery_worker.ps1
.\scripts\run_celery_beat.ps1
```

后台任务负责学习记录检查、学习情况汇总和夜间模型候选更新。候选结果仍需教师确认，不会自动改变学生安排。

## 模拟数据说明

没有真实纵向数据时，可以生成可清理的模拟数据检查完整流程：

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_learning_data `
  --school-code SIM-RESEARCH `
  --seed 20260719 `
  --classes 4 `
  --students-per-class 30 `
  --weeks 12 `
  --end-date 2026-07-18
```

`--weeks` 支持 1 到 52，这只是模拟数据跨度，不是正式课程的课时上限。先加 `--dry-run` 可以只查看预计数据量。清理方式和隔离规则见[模拟数据说明](docs/synthetic_data_research_track.md)。

## ONLYOFFICE

环境配置示例：

```env
ONLYOFFICE_DOCUMENT_SERVER_URL=http://127.0.0.1
ONLYOFFICE_JWT_SECRET=<与 Document Server 一致的密钥>
```

学校服务器地址、端口或密钥变化后，需要重新运行检测。详细说明见[ONLYOFFICE 集成文档](docs/onlyoffice_integration.md)。

## 提交前检查

后端：

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

前端：

```powershell
cd frontend
npm.cmd run build
```

代码格式：

```powershell
git diff --check
```

## 目录说明

```text
accounts/           登录账户与权限
school/             学校、班级、学生档案和任课关系
courses/            学科、课程、课时、课堂、小组、评价和学习网页
learning/           学习记录、前测、测试、作品、公告和留言
learning_analytics/ 学习情况汇总、数据检查、分层与模型服务
realtime/           课堂聊天、过滤规则和 WebSocket
aiops/              教师 AI 配置、模型版本和训练任务
api/                前后端接口
frontend/           Vue 正式前端源码
static/frontend/    Vue 构建结果
scripts/            安装、启动和维护脚本
docs/               架构、业务、部署和研究设计文档
storage/            本地数据库、媒体、模型和运行数据
```

## 使用边界

- 学校数据、数据库、媒体文件、模型文件、日志和备份包不提交到 Git。
- 超级管理员和学校管理员必须使用高强度密码。
- 学生可以使用便于课堂登录的初始密码，并在首次使用流程中修改。
- 学校、班级和账户删除前必须先停用或归档。
- 学生不能看到内部层级、风险标签、模型置信度和教师干预记录。
- AI 生成的题目、评价和学习网页必须经过教师确认后才能发布。

## 进一步文档

完整索引见 [docs/README.md](docs/README.md)。常用入口：

- [私有化部署](docs/private_deployment.md)
- [教师端设计](docs/teacher_module_design.md)
- [学生端设计](docs/student_module_design.md)
- [课时与课堂设计](docs/teacher_lesson_classroom_redesign.md)
- [测试与共享题库](docs/assessment_module_design.md)
- [课堂实名聊天](docs/classroom_chat_design.md)
- [教学资源中心](docs/resource_center_design.md)
- [学习数据检查](docs/data_quality_pipeline.md)
- [动态分层设计报告](docs/student_behavior_ai_stratification_design.md)
- [模型发布与回滚](docs/model_release_operations.md)
- [学校试用方案](docs/school_pilot_protocol.md)
