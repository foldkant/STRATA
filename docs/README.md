# STRATA 文档导航

本目录记录 STRATA 数智教学系统的业务规则、技术架构、接口契约和私有化部署要求。实现新功能时应同步更新对应专题文档、`api_contract.md` 和 `data_model.md`，不能只修改代码。

## 总体架构

- [前端架构](frontend_architecture.md)：Vue 3 工程、路由、组件复用、UI/UX 和响应式约束。
- [API 契约](api_contract.md)：认证、管理端、教师端、学生端和实时课堂接口。
- [数据模型](data_model.md)：核心实体、关系、状态约束和学习事件。
- [私有化部署](private_deployment.md)：PostgreSQL、Redis、ASGI、Celery、离线依赖和服务启动。
- [安装与离线同步规划](setup_and_offline_sync_plan.md)：后续 setup 安装器、端口检测和学校数据同步方向。

## 角色与业务模块

- [超级管理员设计](admin_module_design.md)：平台级学校、学校管理员、跨校数据和健康管理。
- [学校管理员设计](school_admin_module_design.md)：教师、学生、班级、任课关系和学科前测。
- [教师端设计](teacher_module_design.md)：课程、课堂、学生、资源、公告、反馈、评价、AI 和分层能力。
- [学生端设计](student_module_design.md)：学生首页、首次使用、课程学习、课堂、测试和学习档案。

## 教学核心能力

- [课时设计与课堂教学重构](teacher_lesson_classroom_redesign.md)：备课、学习过程、资源、题目、课堂控制、小组合作和评价。
- [AI 学习网页](lesson_workspace_ai_design.md)：教师生成受控学习任务网页、版本、表单采集和安全沙箱。
- [测试与共享题库](assessment_module_design.md)：共享题库、AI 出题、组卷、随机顺序、测试运行和主观题批阅。
- [课堂实名文字聊天](classroom_chat_design.md)：全班、师生私聊、小组聊天、本地言论判断、撤回和扣分反馈。
- [ONLYOFFICE 集成](onlyoffice_integration.md)：文档预览、编辑、JWT、协作和无 ONLYOFFICE 降级方案。

## 品牌与界面

- [品牌素材清单](brand_assets_needed.md)：后续需要提供的 Logo、图标和默认课程图片。

## 当前实现边界

已经完成正式页面或主要业务闭环：

- 超级管理员学校和学校管理员管理。
- 学校管理员教师、学生、班级、任课和学科前测。
- 教师课程、课时设计、课堂控制、资源、公告、反馈、共享题库和测试。
- 学生课程、实时课堂、作答、测试和学习档案。
- ONLYOFFICE、AI 学习网页、小组协作、课堂评价和课堂实名聊天第一版。

仍需继续开发或生产化：

- 跨学校数据包采集、校验和统一分析。
- 全局基础模型、班级校准模型和夜间训练闭环。
- PostgreSQL/Redis 正式安装器、HTTPS、本地证书和自动端口选择。
- 备份恢复、监控告警、审计导出和学校版本升级工具。
- 大型前端包的路由级拆包和性能优化。

## 文档维护规则

1. 页面或交互变化更新角色模块文档和前端架构。
2. API 变化更新 `api_contract.md`。
3. 表、字段、状态和数据生命周期变化更新 `data_model.md`。
4. 服务、端口、环境变量和离线依赖变化更新 `private_deployment.md`。
5. 涉及学生行为和 AI 特征时，明确哪些是特征、哪些是教师确认标签、哪些数据禁止发送到外部服务。
6. UI 修改完成后执行桌面和移动端审查，临时截图检查后删除，并在文档记录结果。
