# 修复后全角色截图索引

复验日期：2026-07-24  
视口：1440×900、768×1024、390×844  
范围：超级管理员、学校管理员、教师、学生。学校管理员“教育实验”模块明确排除。

## 数量与浏览器检查

|视口|超级管理员|学校管理员|教师|学生|平台未处理异常/500|
|---|---:|---:|---:|---:|---:|
|桌面 1440|7|10|15|12|0|
|平板 768|7|10|15|12|0|
|手机 390|7|10|15|12|0|
|合计|21|30|45|36|0|

共 132 张原始全页截图、12 张角色汇总图。每个原始截图目录内的 `browser-findings.json` 记录页面异常和服务端 500：平台自身未处理异常与服务端 500 均为 0；学生平板课堂记录到 1 次校内 OnlyOffice 9.4 的外部 `ColorPaletteExt.js` 异常，自动化同时确认页面已显示“重新加载/下载原文件”恢复路径。

## 汇总图

|角色|桌面|平板|手机|
|---|---|---|---|
|超级管理员|[查看](verification-contact-sheets/desktop-1440--superAdmin.jpg)|[查看](verification-contact-sheets/tablet-768--superAdmin.jpg)|[查看](verification-contact-sheets/mobile-390--superAdmin.jpg)|
|学校管理员|[查看](verification-contact-sheets/desktop-1440--schoolAdmin.jpg)|[查看](verification-contact-sheets/tablet-768--schoolAdmin.jpg)|[查看](verification-contact-sheets/mobile-390--schoolAdmin.jpg)|
|教师|[查看](verification-contact-sheets/desktop-1440--teacher.jpg)|[查看](verification-contact-sheets/tablet-768--teacher.jpg)|[查看](verification-contact-sheets/mobile-390--teacher.jpg)|
|学生|[查看](verification-contact-sheets/desktop-1440--student.jpg)|[查看](verification-contact-sheets/tablet-768--student.jpg)|[查看](verification-contact-sheets/mobile-390--student.jpg)|

## 原始截图目录

- 桌面：`verification-screenshots/desktop-1440/{superAdmin,schoolAdmin,teacher,student}/`
- 平板：`verification-screenshots/tablet-768/{superAdmin,schoolAdmin,teacher,student}/`
- 手机：`verification-screenshots/mobile-390/{superAdmin,schoolAdmin,teacher,student}/`

截图覆盖登录后的角色首页、人员与教学组织、课程与课时、课堂实施、作业与测试、评价方案、学生学习情况、内容与支持建议、资源、课程标准、后台任务、公告与反馈等当前正式入口。

## 关键复验截图

- [教师手机课堂控制与环节任务](verification-screenshots/mobile-390/teacher/teacher-classroom-3.png)
- [教师桌面课时设计](verification-screenshots/desktop-1440/teacher/teacher-lessons-3-design.png)
- [教师手机评价方案](verification-screenshots/mobile-390/teacher/teacher-evaluations.png)
- [学生手机课堂](verification-screenshots/mobile-390/student/student-classroom-3.png)
- [超级管理员桌面课程标准](verification-screenshots/desktop-1440/superAdmin/super-admin-curriculum-standards.png)
- [学校管理员手机数据质量](verification-screenshots/mobile-390/schoolAdmin/school-admin-data-quality.png)

截图只能证明页面和工程流程在当前数据下可访问，不替代真实用户可用性研究、教学效果验证或正式教育实验。
