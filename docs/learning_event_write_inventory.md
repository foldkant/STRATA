# 学习事件 V1 写入点与 V2 迁移清单

> 盘点日期：2026-07-18。  
> 用途：为 `LearningEvent` 到 `LearningEventV2` 的统一双写、对账和回滚提供完整入口清单。  
> 当前状态：`DATA-01C` 已完成；生产写入全部收口到统一双写服务，历史回填和全库对账已通过。

## 1. 当前写入结构

现有代码有两类写入方式：

1. 学生课程、课时和课堂活动仍主要通过 [`api.views._write_student_event`](../api/views.py) 写入；课堂题目、附件、AI 学习网页、环节内普通资源和小组协作已迁移到统一服务。
2. `api/` 生产代码已无分散的 `LearningEvent.objects.create()`；静态测试会阻止直写重新出现。

迁移时统一调用后续 `learning_analytics.services.event_ingestion.record_learning_event()`。视图不得自行分别创建 V1/V2 两条记录。

## 2. 直接写入点

| 优先级 | 业务事实 | 当前入口 | 当前 V1 含义 | V2 目标 |
| --- | --- | --- | --- | --- |
| P0 | 测试最终提交 | [`api/assessment_views.py`](../api/assessment_views.py#L1087) | `answer_submit/test_assessment` | **已迁移**：逐题 `item.submitted@1.1`、`item.graded` 和结果事实 |
| P0 | 课堂环节作答 | [`api/views.py`](../api/views.py) | 旧版 `_write_student_event(answer_submit)` | **已迁移**：`LessonStepAttempt/Answer` 保存正文与版本，逐题双写 `item.submitted@1.1` 和自动/待评事实 |
| P0 | 课堂附件上传与批阅 | [`api/views.py`](../api/views.py) | 旧版覆盖附件并写 `attachment_score` | **已迁移**：上传追加 `StudentWorkAttachment` 版本，写 `task.submitted`；教师评分追加 `item.graded final/revised` |
| P1 | 课堂环节普通资源 | [`api/views.py`](../api/views.py) | 仅随页面预览，没有课堂机会分母 | **已迁移**：按格式投放 `resource/video/document` 机会，写 `resource.opened`、`video.progress`；真实页码可得时写 `document.progress` |
| P1 | 资源中心查看 | [`api/views.py`](../api/views.py#L2218) | `resource_view/resource_center` | 保留为课堂外自主浏览；需先设计独立推荐/指派语义，再决定是否生成机会分母 |
| P1 | 小组文档打开/保存 | [`api/views.py`](../api/views.py) | 曾直接写 `resource_view/group_document` 并覆盖原文件 | **已迁移**：组员定向文档机会、`group.document.opened`、JWT 回调校验、不可变版本和组级 `group.document.saved` |
| P1 | AI 学习网页浏览/提交 | [`api/views.py`](../api/views.py) | 旧版复制表单答案到事件 JSON | **已迁移**：`opened/block_viewed/form_submitted`，答案只留 `LearningWebPageResponse` |
| P2 | 随机点名选择与加减分 | [`api/views.py`](../api/views.py) | `teacher_intervention` 且 `actor` 为学生 | **已迁移**：服务端 `random_call.selected` 只记录教师选择事实；加减分进入 `ParticipationPointLedger`，不生成学生完成机会 |
| P2 | 抢答响应与加减分 | [`api/views.py`](../api/views.py) | `page_view/teacher_intervention` | **已迁移**：可选 `interaction` 机会、服务端排名的 `quick_answer.responded`、积分流水及冲正；回答正文只留 V1 业务元数据 |
| P2 | 签到与人工考勤 | [`api/views.py`](../api/views.py) | 曾直接追加 `page_view` 且无机会分母 | **已迁移**：全班 `attendance` 机会和追加式 `attendance.recorded`，学生仅能自助签到，迟到/请假/缺勤由教师确认 |
| P2 | 课堂活动开关 | [`api/services.py`](../api/services.py#L4287) | `teacher_intervention` | 内容/活动 `released/withdrawn` 与课堂控制事实 |
| P3 | 课堂师评 | [`api/views.py`](../api/views.py) | 曾原地覆盖 `teacher_intervention/classroom_evaluation` | **已迁移**：冻结课堂量规版本，追加提交版本并双写 `rubric.rating.submitted` |
| P3 | 课程级师评 | [`api/views.py`](../api/views.py) | 曾原地覆盖 `teacher_intervention/course_evaluation` | **已迁移**：按课程、班级和量规版本创建机会，评价归属目标学生 |
| P3 | 学生自评/互评 | [`api/views.py`](../api/views.py) | 曾通过 `_write_student_event(answer_submit)` 覆盖旧提交 | **已迁移**：自评归本人；互评保留评价者并归属被评价学生，普通客户端不能伪造跨学生目标 |
| P4 | 聊天消息 | [`api/chat_views.py`](../api/chat_views.py#L407) | `chat_message` | 只写参与事实，不复制聊天原文 |
| P4 | 聊天审核/扣分 | [`api/chat_views.py`](../api/chat_views.py#L606) | `teacher_intervention` | 审核事实 + 积分流水，保留教师决策与冲正 |
| P4 | 学生确认审核反馈 | [`api/chat_views.py`](../api/chat_views.py#L728) | `page_view` | `intervention.acknowledged` |
| P4 | 小组共享文件 | [`api/views.py`](../api/views.py) | 曾通过 `_write_student_event(task_submit)` 写文件名 | **已迁移**：组员定向可选任务机会和 `group.file.shared`；V2 只保存文件 UUID、版本、格式和大小 |

## 3. 通过学生事件辅助函数写入的入口

[`api.views._write_student_event`](../api/views.py#L5667) 当前被以下流程调用：

- 学生进入课时、进入环节和完成环节。
- 学生抢答已通过专用服务迁移；随机点名不存在学生提交响应，只保留服务端选择事实。
- 学生完成前测及其他课程学习行为。

旧 `_write_student_event` 过渡函数已经删除；课时、环节、前测、课堂互动和反馈确认使用具名领域服务。

## 4. 已发现的语义问题

- 部分教师加减分把学生保存为 `actor`，无法区分“教师执行动作”和“证据归属学生”。V2 必须分别写 `actor` 与 `target_student`。
- 多种业务依靠 `metadata.action` 区分，事件名过粗；V2 按登记后的点分事件名拆分。
- 旧课堂作答曾把答案和附件复制进事件 JSON；现已迁移到业务提交表，V2 只保存业务引用、题目版本、机会和尝试 UUID。
- 未提交、未评分和未获得投放机会容易被解释为 0；必须在 `DATA-02A/B` 建立机会和最终评分事实后才计算比率。
- 课堂积分直接覆盖 `StudentProfile.score`，缺少冲正流水；迁移后以不可变积分台账重算缓存。
- 客户端离线、迟到和网络故障尚未记录，现有“零行为”不能直接解释为低参与。

## 5. 迁移验收

1. 每个入口先生成稳定 `event_id`，统一服务在同一事务内完成 V1/V2 双写。
2. 对账按业务事实和语义映射进行，不只比较总行数。
3. 主观题未完成评分前不得生成最终 0 分事实。
4. 结果事件必须关联明确学习机会；覆盖不足时只报告质量问题。
5. 双写失败要整体回滚或进入明确重试队列，不能静默丢弃任一版本。
6. 停止 V1 写入前保留回滚开关，并完成重复、乱序、离线和迟到回放测试。

## 6. DATA-01C 当前进度

已迁移：

- 随机点名和抢答评分：旧页面继续读取 V1，V2 明确记录教师 `actor` 与学生 `target_student`，实际余额变化进入不可变积分流水。
- 聊天放行、警告、撤回和扣分：审核状态、V1/V2 干预与积分流水处于同一事务；积分不足时不提交审核结果。
- 已提供 `dual_required/v1_only` 回滚模式和 `reconcile_learning_event_writes --check` 对账命令。
- 测试开启、关闭、学生主动/自动交卷、客观题自动评分、主观题待评/最终评分/复评；关闭时区分完成机会与撤回机会。
- 课堂环节投放按题目和适用带生成学生级机会；文件题作为任务机会，其他题作为题目机会。
- 课堂提交使用不可变 `LessonStepAttempt` 和逐题答案版本；客观题自动形成 `final`，简答题先形成 `pending`。
- 附件重新上传不再删除旧文件，而是追加上传版本和 `supersedes`；批阅及复评追加 `final/revised` 评分事实。
- 同一机会允许按不同尝试追加 `submitted/graded` 状态，投放、呈现和开始状态仍保留最早证据去重。
- AI 学习网页随课堂环节创建页面版本机会；打开、受控区块可见时长和表单提交均已双写。V2 仅保存区块/表单 ID、版本、时长和业务响应引用，不保存页面正文或学生答案。
- 课堂普通资源按真实 `Resource` 和投放时版本生成机会。资源切换记录 `resource.opened`，视频约每 10 秒及暂停/结束记录 `video.progress`；PDF/Office 无真实页码时不伪造文档进度。
- 纯资源环节不再自动创建无法完成的通用任务机会，避免扩大必做任务分母。
- 课程评价配置发布为不可变量规版本，课堂首次开启后冻结版本；自评、互评、师评修订均追加 `submission_version/supersedes`，不覆盖旧记录。
- 五星评价写入 `rubric.rating.submitted`，评论正文只留业务表。关闭评价和结束课堂撤回未完成机会，已提交评价不撤回。
- 小组协作按当前组员使用 `content.released@1.1.target_student_ids` 定向生成文档和共享区机会，不扩展到全班其他学生。
- 学生打开协作文档写 `group.document.opened`；上传共享文件写 `group.file.shared`，文件名、描述、地址和正文不进入 V2。
- ONLYOFFICE 回调必须通过 HS256 JWT、文档 key、文档服务器来源和大小校验。真实变化追加 `ClassroomGroupDocumentVersion` 与组级 `group.document.saved`；回调只能证明组文档变化，不能推断个人贡献。
- 小组已有打开、保存或上传证据后禁止重新分组，关闭协作或结束课堂只撤回未完成机会，不删除历史文件和版本。
- 教师开启签到时使用 `content.released@1.2` 为全班生成必做 `attendance` 机会。学生自助签到和教师考勤修订统一写 `attendance.recorded`，通过 `revision_no/supersedes_event_id` 保留状态变化。
- 学生事件入口只能记录本人 `signed/student`；迟到、请假、缺勤和教师来源必须经过任课教师业务接口。考勤备注只留 V1 业务记录，不复制到 V2。
- 课堂结束时，有考勤状态的机会保留为已提交；未响应机会追加 `withdrawn`，不自动生成缺勤事件。已开启或已有记录的课堂活动禁止物理删除。
- 教师开启抢答时使用 `content.released@1.3` 为在籍学生生成非必做 `interaction` 机会。首次响应写 `quick_answer.responded`，排名和相对开启时间的延迟由服务端在活动行锁内计算；重复响应幂等，关闭活动或课堂时只撤回未响应机会。
- 抢答正文只留在 V1 业务兼容元数据，V2 不复制原文。随机点名写服务端来源的 `random_call.selected`，保存选择方法、候选人数和序次；该事实不生成学生机会，也不视为学生参与、完成或能力证据。

最终迁移：资源中心自主浏览使用 `resource.center.opened` 且不生成机会分母；普通课时过程、聊天、干预确认和课堂控制使用独立事件模式。开发库回填 606 条 V1：7 条原已双写、179 条确定映射、420 条 `legacy.unmapped`、0 条拒绝；重跑 606 条全部幂等命中。
