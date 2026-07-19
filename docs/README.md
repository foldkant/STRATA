# STRATA 文档导航

本目录记录 STRATA 数智教学系统的业务规则、技术架构、接口契约和私有化部署要求。实现新功能时应同步更新对应专题文档、`api_contract.md` 和 `data_model.md`，不能只修改代码。

## 总体架构

- [前端架构](frontend_architecture.md)：Vue 3 工程、路由、组件复用、UI/UX 和响应式约束。
- [教师端与学生端 UI/UX 四轮审查](ui_ux_audit.md)：多视口页面、弹窗、性能和可访问性审查结果。
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

- [学生行为分析与 AI 隐性动态分层设计报告](student_behavior_ai_stratification_design.md)：汇总 30 轮科学审查，规定研究级事件、过程性评价量规、特征、计划结局、教师可见/学生隐性的内容带、班级校准模型、夜间流水线和论文研究设计。
- [学生行为分析与 AI 隐性动态分层开发路线图](student_behavior_ai_stratification_development_roadmap.md)：把设计报告落实为 M0-M8 工程里程碑、模块边界、迁移顺序、前后端交付、夜间 DAG、阶段闸门和首批开发任务。
- [学生行为分析工程进度审计](implementation_progress_audit.md)：按 Git、迁移、测试和真实组件运行证据记录已完成、进行中和未开始工作，并固定 DATA-01C、DATA-03、M2、M3 的进入顺序。
- [数据质量流水线与闸门](data_quality_pipeline.md)：定义七项质量指标、完整日窗口、流水线/重试状态、本校 API、夜间任务、学校看板和 M2 进入条件。
- [学习事件 V1 写入点与 V2 迁移清单](learning_event_write_inventory.md)：盘点测试、课堂、资源、评价、聊天和小组业务的现有事件写入入口、语义问题与双写验收要求。
- [学生评价、积分与奖章设计](student_evaluation_incentive_design.md)：规定成绩、五星量规、核心素养证据、课堂积分/奖章和 AI 内部建议的隔离、可见性与实施顺序。
- [行为、特征与量规五轮科学审查](student_behavior_ai_stratification_five_round_review.md)：五轮文献复审发现、方案修正和仍需实证的风险。
- [动态分层第 6-10 轮科学审查](student_behavior_ai_stratification_review_rounds_06_10.md)：预测估计量、抽样、证据中心测量、特征迁移和决策效用。
- [动态分层第 11-15 轮科学审查](student_behavior_ai_stratification_review_rounds_11_15.md)：因果干预、人机协同、隐私安全、可复现性和反证停用。
- [动态分层第 16-20 轮科学审查](student_behavior_ai_stratification_review_rounds_16_20.md)：科学主张、纵向测量、观察过程、结局契约、AI 题目效度和预测偏倚。
- [动态分层第 21-25 轮科学审查](student_behavior_ai_stratification_review_rounds_21_25.md)：跨校迁移、多层公平、解释稳定性、教师容量和观察性策略边界。
- [动态分层第 26-30 轮科学审查](student_behavior_ai_stratification_review_rounds_26_30.md)：实施忠实度、分析单位、隐私自主性、生产验证和证据成熟度。
- [课时设计与课堂教学重构](teacher_lesson_classroom_redesign.md)：备课、学习过程、资源、题目、课堂控制、小组合作和评价。
- [AI 学习网页](lesson_workspace_ai_design.md)：教师生成受控学习任务网页、版本、表单采集和安全沙箱。
- [测试与共享题库](assessment_module_design.md)：共享题库、AI 出题、组卷、随机顺序、测试运行和主观题批阅。
- [课堂实名文字聊天](classroom_chat_design.md)：全班、师生私聊、小组聊天、本地言论判断、撤回和扣分反馈。
- [ONLYOFFICE 集成](onlyoffice_integration.md)：文档预览、编辑、JWT、协作和无 ONLYOFFICE 降级方案。
- [教学资源中心](resource_center_design.md)：课外资源、学生项目、班级/校内/跨校共享、审核与行为采集。

## 品牌与界面

- [品牌素材清单](brand_assets_needed.md)：后续需要提供的 Logo、图标和默认课程图片。

## 当前实现边界

已经完成正式页面或主要业务闭环：

- 超级管理员学校和学校管理员管理。
- 学校管理员教师、学生、班级、任课和学科前测。
- 教师课程、课时设计、课堂控制、资源中心、公告、反馈、共享题库和测试。
- 学生课程、资源中心、实时课堂、作答、测试和学习档案。
- ONLYOFFICE、AI 学习网页、小组协作、课堂评价和课堂实名聊天第一版。
- 学习事件 V2、确定性历史回填、数据质量闸门、夜间质量任务和学校管理员数据质量看板。

仍需继续开发或生产化：

- 跨学校数据包采集、校验和统一分析。
- 全局基础模型、班级校准模型和夜间训练闭环。
- M2 研究级量规和题目生命周期；必须先解除当前学校数据质量红色阻断。
- PostgreSQL/Redis 正式安装器、HTTPS、本地证书和自动端口选择。
- 备份恢复、监控告警、审计导出和学校版本升级工具。
- 大型前端包的路由级拆包和性能优化。

## 文档维护规则

1. 页面或交互变化更新角色模块文档和前端架构。
2. API 变化更新 `api_contract.md`。
3. 表、字段、状态和数据生命周期变化更新 `data_model.md`。
4. 服务、端口、环境变量和离线依赖变化更新 `private_deployment.md`。
5. 涉及学生行为和 AI 特征时，明确哪些是预测特征、哪些是学生结局、哪些是教师决策观测，以及哪些数据禁止发送到外部服务。
6. UI 修改完成后执行桌面和移动端审查，临时截图检查后删除，并在文档记录结果。
