# 页面与功能截图索引

共保存 100 张全页面截图、46 张主要功能流程截图和 12 张角色总览图。页面截图同时覆盖 1440×1000 桌面端与 390×844 手机端。学校管理员“教育实验”按要求完全排除。

## 总览图

|角色|桌面端|手机端|主要功能流程|
|---|---|---|---|
|超级管理员|[总览](contact-sheets/super-admin--desktop.jpg)|[总览](contact-sheets/super-admin--mobile.jpg)|[总览](contact-sheets/super-admin--workflows.jpg)|
|学校管理员|[总览](contact-sheets/school-admin--desktop.jpg)|[总览](contact-sheets/school-admin--mobile.jpg)|[总览](contact-sheets/school-admin--workflows.jpg)|
|教师|[总览](contact-sheets/teacher--desktop.jpg)|[总览](contact-sheets/teacher--mobile.jpg)|[总览](contact-sheets/teacher--workflows.jpg)|
|学生|[总览](contact-sheets/student--desktop.jpg)|[总览](contact-sheets/student--mobile.jpg)|[总览](contact-sheets/student--workflows.jpg)|

## 超级管理员：7 个页面

|页面|路由|桌面|手机|基线记录|
|---|---|---|---|---|
|数据总览|`/app/super-admin`|[桌面](screenshots/super-admin/dashboard--desktop.png)|[手机](screenshots/super-admin/dashboard--mobile.png)|页面较长；操作事件仍显示技术代码|
|学校管理|`/app/super-admin/schools`|[桌面](screenshots/super-admin/schools--desktop.png)|[手机](screenshots/super-admin/schools--mobile.png)|表格操作触控区偏小|
|学校管理员|`/app/super-admin/school-admins`|[桌面](screenshots/super-admin/school-admins--desktop.png)|[手机](screenshots/super-admin/school-admins--mobile.png)|表格操作触控区偏小|
|课程标准|`/app/super-admin/curriculum-standards`|[桌面](screenshots/super-admin/curriculum-standards--desktop.png)|[手机](screenshots/super-admin/curriculum-standards--mobile.png)|目录、详情、后台任务分区已经建立|
|跨校数据采集|`/app/super-admin/collection`|[桌面](screenshots/super-admin/collection--desktop.png)|[手机](screenshots/super-admin/collection--mobile.png)|基线可用|
|跨校分析|`/app/super-admin/analysis`|[桌面](screenshots/super-admin/analysis--desktop.png)|[手机](screenshots/super-admin/analysis--mobile.png)|手机端信息较长|
|系统健康|`/app/super-admin/health`|[桌面](screenshots/super-admin/health--desktop.png)|[手机](screenshots/super-admin/health--mobile.png)|基线可用|

主要功能流程：

- [新增学校](workflow-screenshots/super-admin/schools-create.png)
- [学校批量导入入口](workflow-screenshots/super-admin/schools-import.png)
- [新增学校管理员](workflow-screenshots/super-admin/school-admin-create.png)
- [学校管理员批量导入入口](workflow-screenshots/super-admin/school-admin-import.png)
- [登记课程标准](workflow-screenshots/super-admin/curriculum-register.png)
- [课程标准详情](workflow-screenshots/super-admin/curriculum-detail.png)
- [课程标准后台任务](workflow-screenshots/super-admin/curriculum-tasks.png)

## 学校管理员：10 个页面

|页面|路由|桌面|手机|基线记录|
|---|---|---|---|---|
|管理首页|`/app/school-admin`|[桌面](screenshots/school-admin/dashboard--desktop.png)|[手机](screenshots/school-admin/dashboard--mobile.png)|手机端全页约 5385px，需折叠次要内容|
|教师管理|`/app/school-admin/teachers`|[桌面](screenshots/school-admin/teachers--desktop.png)|[手机](screenshots/school-admin/teachers--mobile.png)|手机表格只适合查看部分字段|
|学生管理|`/app/school-admin/students`|[桌面](screenshots/school-admin/students--desktop.png)|[手机](screenshots/school-admin/students--mobile.png)|密集表格与小操作控件|
|班级管理|`/app/school-admin/classes`|[桌面](screenshots/school-admin/classes--desktop.png)|[手机](screenshots/school-admin/classes--mobile.png)|密集表格与小操作控件|
|任课关系|`/app/school-admin/teaching`|[桌面](screenshots/school-admin/teaching--desktop.png)|[手机](screenshots/school-admin/teaching--mobile.png)|班级标签过多，手机端阅读成本高|
|学科与学习起点诊断|`/app/school-admin/pretests`|[桌面](screenshots/school-admin/pretests--desktop.png)|[手机](screenshots/school-admin/pretests--mobile.png)|术语基本符合教育表达|
|资源审核|`/app/school-admin/resource-reviews`|[桌面](screenshots/school-admin/resource-reviews--desktop.png)|[手机](screenshots/school-admin/resource-reviews--mobile.png)|搜索框缺少可访问标签|
|题库审核|`/app/school-admin/question-reviews`|[桌面](screenshots/school-admin/question-reviews--desktop.png)|[手机](screenshots/school-admin/question-reviews--mobile.png)|空状态可用|
|数据检查|`/app/school-admin/data-quality`|[桌面](screenshots/school-admin/data-quality--desktop.png)|[手机](screenshots/school-admin/data-quality--mobile.png)|手机端信息较长|
|学习情况分析|`/app/school-admin/models`|[桌面](screenshots/school-admin/analysis-preparation--desktop.png)|[手机](screenshots/school-admin/analysis-preparation--mobile.png)|模型工程术语过多|

主要功能流程：

- [新增教师](workflow-screenshots/school-admin/teacher-create.png)
- [批量导入教师](workflow-screenshots/school-admin/teacher-import.png)
- [新增学生](workflow-screenshots/school-admin/student-create.png)
- [批量导入学生](workflow-screenshots/school-admin/student-import.png)
- [新增班级](workflow-screenshots/school-admin/class-create.png)
- [批量新增班级](workflow-screenshots/school-admin/class-bulk-create.png)
- [批量升班](workflow-screenshots/school-admin/class-promote.png)
- [设置任教班级](workflow-screenshots/school-admin/teaching-bulk-set.png)
- [新增学科](workflow-screenshots/school-admin/pretest-subject-create.png)
- [新建学习起点诊断版本](workflow-screenshots/school-admin/pretest-paper-create.png)
- [诊断实施批次](workflow-screenshots/school-admin/pretest-administrations.png)
- [诊断材料评价](workflow-screenshots/school-admin/pretest-evidence-review.png)
- [数据检查详情](workflow-screenshots/school-admin/data-quality-detail.png)
- [分析数据准备](workflow-screenshots/school-admin/analysis-data-preparation.png)
- [学习内容层级标准](workflow-screenshots/school-admin/analysis-level-standard.png)
- [详细检查](workflow-screenshots/school-admin/analysis-detailed-check.png)

## 教师：17 个页面

|页面|路由|桌面|手机|基线记录|
|---|---|---|---|---|
|教师首页|`/app/teacher`|[桌面](screenshots/teacher/dashboard--desktop.png)|[手机](screenshots/teacher/dashboard--mobile.png)|13 个并列导航入口|
|课程备课|`/app/teacher/courses`|[桌面](screenshots/teacher/courses--desktop.png)|[手机](screenshots/teacher/courses--mobile.png)|表格操作密集|
|课时设计|`/app/teacher/lessons/86/design`|[桌面](screenshots/teacher/lesson-design-86--desktop.png)|[手机](screenshots/teacher/lesson-design-86--mobile.png)|手机端约 4094px；50 个小控件|
|课堂列表|`/app/teacher/classroom`|[桌面](screenshots/teacher/classroom-list--desktop.png)|[手机](screenshots/teacher/classroom-list--mobile.png)|41 个禁用操作没有原因|
|课堂控制台|`/app/teacher/classroom/3`|[桌面](screenshots/teacher/classroom-console-3--desktop.png)|[手机](screenshots/teacher/classroom-console-3--mobile.png)|功能集中但首屏信息密度高|
|学生管理|`/app/teacher/students`|[桌面](screenshots/teacher/students--desktop.png)|[手机](screenshots/teacher/students--mobile.png)|班级筛选项过多|
|测试管理|`/app/teacher/assessments`|[桌面](screenshots/teacher/assessments--desktop.png)|[手机](screenshots/teacher/assessments--mobile.png)|基线可用|
|题库管理|`/app/teacher/question-bank`|[桌面](screenshots/teacher/question-bank--desktop.png)|[手机](screenshots/teacher/question-bank--mobile.png)|操作与筛选较多|
|评价方案库|`/app/teacher/evaluations`|[桌面](screenshots/teacher/evaluations--desktop.png)|[手机](screenshots/teacher/evaluations--mobile.png)|用途说明已区分课时设计与方案库|
|资源中心|`/app/teacher/resources`|[桌面](screenshots/teacher/resources--desktop.png)|[手机](screenshots/teacher/resources--mobile.png)|多个主操作并列|
|协作文档|`/app/teacher/documents`|[桌面](screenshots/teacher/documents--desktop.png)|[手机](screenshots/teacher/documents--mobile.png)|手机端编辑器操作空间有限|
|AI 接入|`/app/teacher/ai`|[桌面](screenshots/teacher/ai-provider--desktop.png)|[手机](screenshots/teacher/ai-provider--mobile.png)|应移入个人设置|
|学习内容层级与学习支持|`/app/teacher/stratification`|[桌面](screenshots/teacher/stratification--desktop.png)|[手机](screenshots/teacher/stratification--mobile.png)|教育术语较合理|
|公告通知|`/app/teacher/notices`|[桌面](screenshots/teacher/notices--desktop.png)|[手机](screenshots/teacher/notices--mobile.png)|基线可用|
|留言反馈|`/app/teacher/feedback`|[桌面](screenshots/teacher/feedback--desktop.png)|[手机](screenshots/teacher/feedback--mobile.png)|基线可用|
|项目学习|`/app/teacher/projects`|[桌面](screenshots/teacher/projects-placeholder--desktop.png)|[手机](screenshots/teacher/projects-placeholder--mobile.png)|占位页|
|学习网页|`/app/learning-pages/2`|[桌面](screenshots/teacher/learning-page-2--desktop.png)|[手机](screenshots/teacher/learning-page-2--mobile.png)|教师预览可打开|

主要功能流程：

- [新增课程](workflow-screenshots/teacher/course-create.png)
- [新增课时环节](workflow-screenshots/teacher/lesson-step-create.png)
- [课时环节评价入口](workflow-screenshots/teacher/lesson-evaluation.png)
- [课时内手工新建评价](workflow-screenshots/teacher/lesson-evaluation-manual.png)
- [课时内 AI 辅助评价](workflow-screenshots/teacher/lesson-evaluation-ai.png)
- [新建课堂](workflow-screenshots/teacher/classroom-create.png)
- [课堂签到](workflow-screenshots/teacher/classroom-attendance.png)
- [随机点名](workflow-screenshots/teacher/classroom-random-pick.png)
- [课堂倒计时](workflow-screenshots/teacher/classroom-timer.png)
- [课堂广播](workflow-screenshots/teacher/classroom-broadcast.png)
- [课堂小组合作](workflow-screenshots/teacher/classroom-grouping.png)
- [课堂评价情况](workflow-screenshots/teacher/classroom-evaluation.png)
- [新建测试](workflow-screenshots/teacher/assessment-create.png)
- [新增题目](workflow-screenshots/teacher/question-create.png)
- [AI 批量出题](workflow-screenshots/teacher/question-ai-batch.png)
- [题库批量导入](workflow-screenshots/teacher/question-import.png)
- [新建可复用评价方案](workflow-screenshots/teacher/evaluation-create.png)
- [方案库 AI 辅助评价](workflow-screenshots/teacher/evaluation-ai.png)
- [新增资源](workflow-screenshots/teacher/resource-create.png)
- [新增学生项目](workflow-screenshots/teacher/student-project-create.png)
- [新增公告](workflow-screenshots/teacher/notice-create.png)

## 学生：16 个页面

|页面|路由|桌面|手机|基线记录|
|---|---|---|---|---|
|学习首页|`/app/student`|[桌面](screenshots/student/dashboard--desktop.png)|[手机](screenshots/student/dashboard--mobile.png)|手机端约 2485px，当前任务仍较清晰|
|首次使用|`/app/student/onboarding`|[桌面](screenshots/student/onboarding--desktop.png)|[手机](screenshots/student/onboarding--mobile.png)|基线可用|
|信息科技学习起点诊断|`/app/student/pretests/1`|[桌面](screenshots/student/pretest-subject-1--desktop.png)|[手机](screenshots/student/pretest-subject-1--mobile.png)|测试学生暂无可完成诊断版本|
|我的课程|`/app/student/courses`|[桌面](screenshots/student/courses--desktop.png)|[手机](screenshots/student/courses--mobile.png)|卡片清晰|
|课程详情|`/app/student/courses/3`|[桌面](screenshots/student/course-3--desktop.png)|[手机](screenshots/student/course-3--mobile.png)|课堂接管状态有说明|
|课时学习|`/app/student/lessons/3/workspace`|[桌面](screenshots/student/lesson-workspace-3--desktop.png)|[手机](screenshots/student/lesson-workspace-3--mobile.png)|403 后仍显示加载状态|
|课堂学习|`/app/student/classroom/3`|[桌面](screenshots/student/classroom-3--desktop.png)|[手机](screenshots/student/classroom-3--mobile.png)|资源 2 预览 404；文件说明缺少标签|
|测试列表|`/app/student/assessments`|[桌面](screenshots/student/assessments--desktop.png)|[手机](screenshots/student/assessments--mobile.png)|基线可用|
|测试结果|`/app/student/assessments/3`|[桌面](screenshots/student/assessment-3--desktop.png)|[手机](screenshots/student/assessment-3--mobile.png)|完成状态清晰|
|资源中心|`/app/student/resources`|[桌面](screenshots/student/resources--desktop.png)|[手机](screenshots/student/resources--mobile.png)|当前无可查看资源|
|学习档案|`/app/student/profile`|[桌面](screenshots/student/profile--desktop.png)|[手机](screenshots/student/profile--mobile.png)|手机全页约 7295px，需分区折叠|
|公告通知|`/app/student/notices`|[桌面](screenshots/student/notices--desktop.png)|[手机](screenshots/student/notices--mobile.png)|基线可用|
|留言反馈|`/app/student/feedback`|[桌面](screenshots/student/feedback--desktop.png)|[手机](screenshots/student/feedback--mobile.png)|基线可用|
|任务|`/app/student/tasks`|[桌面](screenshots/student/tasks-placeholder--desktop.png)|[手机](screenshots/student/tasks-placeholder--mobile.png)|占位页|
|项目|`/app/student/projects`|[桌面](screenshots/student/projects-placeholder--desktop.png)|[手机](screenshots/student/projects-placeholder--mobile.png)|占位页|
|学习网页|`/app/learning-pages/2`|[桌面](screenshots/student/learning-page-2--desktop.png)|[手机](screenshots/student/learning-page-2--mobile.png)|未投放时返回 403，页面有说明|

主要功能流程：

- [课堂聊天](workflow-screenshots/student/classroom-chat.png)
- [课堂自评](workflow-screenshots/student/classroom-evaluation.png)

## 自动检查摘要

- 50 个角色—页面场景。
- 100 张全页面截图。
- 46 个主要非破坏性操作入口均能打开。
- 3 个页面场景产生 4xx 记录，其中 1 个为真实资源授权缺陷，2 个为未投放或课堂接管状态的恢复体验问题。
- 2 个页面存在可见表单字段缺少可访问标签。
- 2 个页面存在标题层级跳跃。
- 37 个页面至少有一个小于推荐触控面积的可见控件。
- 未发现整页横向溢出；后台表格在手机端仍主要依赖内部横向滚动或压缩列宽。
