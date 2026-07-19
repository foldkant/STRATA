# 安装向导与离线同步规划

## 部署原则

STRATA 面向成员校本地私有化部署，不默认部署到云服务器。

每所学校本地运行完整系统：

- Django / Vue 前后端。
- PostgreSQL。
- Redis。
- Celery 定时任务。
- 本地文件存储或 MinIO。
- 可选 ONLYOFFICE。

中心侧不直接接管学校在线系统。学校可在夜间定时同步资源数据，或导出数据包交由中心统一分析。

## setup 后续要做的事

安装向导后续需要完成：

1. 检测 Python、PostgreSQL、Redis。
2. 检测端口占用，自动选择或提示设置 STRATA 服务端口。
3. 检测 ONLYOFFICE 是否已安装。
4. 可选安装根目录的 `onlyoffice-documentserver.exe`。
5. 检测 ONLYOFFICE JWT 状态，并把当前学校主机的 Document Server 地址和 JWT 密钥同步到 `.env`。
6. 安装失败时继续完成主系统，只关闭协作能力。
7. 生成 `.env`，分别生成 Django、AI 配置和学习事件隔离密钥，不复用教师外部 API 密钥。
8. 初始化数据库并执行 `sync_learning_event_schemas`。
9. 创建超级管理员和学校管理员。
10. 注册隔离事件到期清理任务。
11. 注册 Windows 服务或生成启动脚本。
12. 输出局域网访问地址。

## 端口处理

不能固定假设 `8000` 可用。

检测顺序：

```text
8000 -> 8010 -> 8080 -> 用户指定端口
```

如果 ONLYOFFICE 或其他服务占用了端口，setup 应提示：

- 当前占用服务。
- 当前占用进程。
- 推荐 STRATA 使用的新端口。

## ONLYOFFICE 可选能力

ONLYOFFICE 用于：

- Word / PPT / Excel / PDF 预览。
- 在线编辑。
- 多人协作。
- 小组文档和学生作品批注。

但它不是必装项。

检测不到 ONLYOFFICE 时：

- 教师端不显示“协作编辑”主操作。
- 文档工作区显示“协作服务未启用”。
- 课时设计仍可上传和引用资源。
- 学生端仍可查看可预览资源或下载原文件。

已提供检测命令：

```powershell
.\.venv\Scripts\python.exe manage.py sync_onlyoffice_config --write-env
```

换学校、换服务器、重新安装 ONLYOFFICE 或修改 Document Server 访问地址后，都应重新运行该命令。命令会读取 ONLYOFFICE `config/local.json`，判断是否启用浏览器 JWT，并更新 `ONLYOFFICE_DOCUMENT_SERVER_URL`、`ONLYOFFICE_JWT_SECRET`。密钥只写入 `.env`，不在控制台明文展示。

## 备用预览

无 ONLYOFFICE 时必须保留：

| 类型 | 方案 |
| --- | --- |
| PDF | PDF.js |
| 图片 | 浏览器原生 |
| 视频 / 音频 | 浏览器原生 |
| TXT / MD / 代码 | 后端转义展示 |
| Word / PPT / Excel | LibreOffice headless 转 PDF |
| Excel | openpyxl 生成表格预览 |
| 压缩包 | 文件清单 + 下载 |

转换失败时显示：

```text
该文件暂时无法预览，可下载后查看。
```

## 夜间同步方向

成员校可配置夜间任务：

- 导出学习事件增量。
- 导出学生特征快照。
- 导出模型训练摘要。
- 导出资源元数据。
- 导出必要的匿名化统计数据。

跨校教学资源应使用 `Resource.public_id` 作为稳定编号。资源包需要包含来源学校、资源版本、共享状态、文件清单和 SHA256；学生项目的过程材料只在教师实际上传时进入资源包，不要求每个项目都有日志、甘特图或阶段成果。

同步方式第一阶段建议用“压缩包导出 / 导入”，不是强依赖联网 API。

后续如果学校允许内网到中心连通，再增加定时上传。

## 管理界面提示

学校管理员或超级管理员应能看到：

- STRATA 服务端口。
- PostgreSQL 状态。
- Redis 状态。
- Celery beat 状态。
- ONLYOFFICE 状态。
- 可用预览能力。
- 最近一次夜间同步结果。
