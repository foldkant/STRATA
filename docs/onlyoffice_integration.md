# ONLYOFFICE 集成验证

## 产品定位

ONLYOFFICE 是 STRATA 的增强能力，不是系统启动硬依赖。

各成员校以离线本地部署为主，不能假设每台学习电脑或每所学校服务器都能安装 ONLYOFFICE。因此正式方案必须支持：

- 检测到 ONLYOFFICE：启用 Office 在线预览、编辑和协作。
- 未检测到 ONLYOFFICE：禁用协作编辑，但平台课程、课堂、资源、题目和学生学习过程仍可正常使用。
- 安装失败或端口冲突：给出明确诊断和降级方案，不阻断系统运行。

根目录当前已有离线安装包：

```text
E:\newproject\onlyoffice-documentserver.exe
```

后续 setup 安装程序需要把它作为可选组件处理。

## 当前验证结果

本机已安装 ONLYOFFICE Docs Community Edition，Windows 服务运行正常：

- `DsConverterSvc`
- `DsDocServiceSvc`
- `DsProxySvc`
- `DsExampleSvc`

Document Server 地址：

```text
http://192.168.11.165/
```

API 脚本可访问：

```text
http://192.168.11.165/web-apps/apps/api/documents/api.js
```

欢迎页显示为 ONLYOFFICE Docs Community Edition。

注意：本机 `8000` 端口被 ONLYOFFICE `docservice` 占用，因此 Django 验证服务临时跑在 `8010`。

## 部署检测与降级

正式启动流程需要先做能力检测：

1. 检测 ONLYOFFICE 服务是否存在，例如 Windows 服务 `DsDocServiceSvc`。
2. 检测 Document Server 地址是否可访问。
3. 检测 API 脚本：

```text
/web-apps/apps/api/documents/api.js
```

4. 检测端口占用。ONLYOFFICE 可能占用 `80`、`8000` 或安装时配置的其他端口；Django/ASGI 需要自动避开或让 setup 提示用户选择端口。
5. 将检测结果写入系统配置，例如 `ONLYOFFICE_ENABLED=true/false`、`ONLYOFFICE_DOCUMENT_SERVER_URL`。

降级规则：

- `ONLYOFFICE_ENABLED=true`：Office 文件优先用 ONLYOFFICE 预览/编辑；有权限时支持协作。
- `ONLYOFFICE_ENABLED=false`：Office 文件不显示“协作编辑”，只提供预览或下载。
- 转换失败：显示“无法预览，可下载原文件”，不影响课堂继续。

JWT 配置：

- 如果 ONLYOFFICE `config/local.json` 中启用了 `services.CoAuthoring.token.enable.browser`，STRATA 必须在 `.env` 中配置同一个 `ONLYOFFICE_JWT_SECRET`。
- Django 会用 HS256 给编辑器配置生成 `config.token`；没有这个 token 会出现“文档安全令牌的格式不正确”。
- 各学校 setup 程序后续需要检测 ONLYOFFICE JWT 状态，并自动写入或提示填写该密钥。

## 无 ONLYOFFICE 的备用预览方案

没有 ONLYOFFICE 时，平台仍要支持基础资源使用：

| 文件类型 | 备用方案 |
| --- | --- |
| PDF | 内置 PDF.js 离线预览 |
| 图片 | 浏览器原生预览 |
| 视频 / 音频 | 浏览器原生播放 |
| TXT / MD / 代码 | 后端转义后前端展示 |
| Word / PPT / Excel | LibreOffice headless 转 PDF 后预览 |
| Excel | 可选用 openpyxl 生成前几页表格预览 |
| ZIP / RAR / 7z | 展示文件清单，允许下载，不默认解压公开 |

备用预览不提供多人协作编辑。

## 后续 setup 要记录的事项

后续安装向导需要支持：

- 检测 Python、PostgreSQL、Redis、Django 服务端口。
- 检测 ONLYOFFICE 是否已安装。
- 如果未安装，提示可选安装 `onlyoffice-documentserver.exe`。
- 如果安装失败，继续完成 STRATA 主系统安装。
- 如果端口被占用，允许调整 STRATA 端口或 ONLYOFFICE 地址。
- 生成 `.env` 中的 `APP_PORT`、`ONLYOFFICE_ENABLED`、`ONLYOFFICE_DOCUMENT_SERVER_URL`。
- 安装完成后提供检测页，展示“协作编辑可用 / 不可用”和降级预览能力。

## 验证页面

已新增临时验证入口：

```text
http://192.168.11.165:8010/onlyoffice-test/
```

模拟两个 STRATA 用户：

```text
http://192.168.11.165:8010/onlyoffice-test/?user=teacher1&name=教师一
http://192.168.11.165:8010/onlyoffice-test/?user=teacher2&name=教师二
```

验证结果：

- 两个用户使用同一个 `document.key`。
- 两个用户传入不同 `editorConfig.user.id` 和 `editorConfig.user.name`。
- ONLYOFFICE 编辑器 iframe 能正常生成。
- Django 的保存回调接口能接收 `status=2`，下载文档并保存版本。

这说明不用 Nextcloud 也可以接入。STRATA 可以自己管理账户、权限、文件和协作关系，ONLYOFFICE 只负责文档预览、编辑和协同。

## 接入架构

```text
Vue 前端
  -> 请求 Django 获取 ONLYOFFICE 编辑配置
  -> 加载 Document Server 的 api.js
  -> 创建 DocsAPI.DocEditor

Django 后端
  -> 管理 STRATA 用户、班级、课程、文件权限
  -> 生成 document.url、callbackUrl、permissions、user
  -> 接收 ONLYOFFICE 保存回调
  -> 保存新版本
  -> 写入 LearningEvent

ONLYOFFICE Docs
  -> 文档预览
  -> 在线编辑
  -> 多人协作
  -> 回调保存
```

## 自有账户协作原则

同一个协作会话的关键是：

```text
document.key 相同
document.url 指向同一份文档
editorConfig.user.id 不同
editorConfig.user.name 不同
```

权限由 STRATA 控制：

```text
permissions.edit      是否可编辑
permissions.comment   是否可评论
permissions.download  是否可下载
permissions.print     是否可打印
```

## 后续正式开发建议

1. 新建正式文档模型，例如 `DocumentAsset`、`DocumentVersion`、`DocumentPermission`。
2. 文件不要直接暴露真实路径，使用带权限校验的下载接口。
3. `document.key` 应绑定具体版本；新版本或副本使用新 key。
4. 教师协同备课使用同一 key。
5. 学生小组协作每组一份副本，每组一个 key。
6. 学生个人作业每人一份副本，每人一个 key。
7. 已发布课件默认只读，可禁止下载/打印。
8. 保存回调中写入版本记录和学习行为事件。
9. 编辑器配置和保存回调均启用 JWT；未配置密钥时不得接受保存回调。

## 当前业务接入状态

2026-07-04 已从验证页推进到业务页面：

- 教师资源库中的 `doc/docx/ppt/pptx/xls/xlsx` 可以在 `/teacher/documents` 中打开。
- 教师资源库、课时设计器、课堂控制台和学生课时学习页统一使用网页内嵌资源预览，不再把“预览”作为跳转新窗口的主流程。
- 教师本人资源默认支持编辑模式。
- 学生端从课时学习页打开 Office 资源时使用只读预览模式。
- 课时设计器从教师资源库加入资源时，会保存资源 ID、URL、文件名和扩展名。
- 课堂控制台已经读取真实课时资源，当前可用于教师端预览。

当前仍是过渡实现：

- Office 文件仍使用 `Resource` 模型承载，没有单独 `DocumentAsset` 和版本表。
- 普通教师资源仍未建立统一 `DocumentAsset/DocumentVersion`；小组协作文档已使用 `ClassroomGroupDocumentVersion` 保存不可变版本、SHA-256、大小、回调状态、key 和已验证编辑者 ID。
- 小组协作回调已校验 HS256 JWT、签名字段、文档 key、下载来源和大小；相同内容的重复回调不会重复生成版本或行为事件。
- `group.document.saved` 只表示小组文档发生变化。即使回调包含编辑者 ID，也不能据此推断每位学生的实际贡献量。
- 生产私有化部署时，资源下载接口需要改为带权限校验的临时 URL，不能长期公开媒体目录。
