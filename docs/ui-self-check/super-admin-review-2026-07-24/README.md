# 超级管理员端视觉与操作复核

日期：2026-07-24

## 复核范围

- 首页
- 学校信息
- 学校管理员
- 课程标准
- 学校数据接收
- 校际数据概览
- 系统检查
- 课程标准登记窗口
- 课程标准逐页原文核对窗口
- 1440px 桌面端与 390px 手机端

## 本轮修正

1. 课程标准逐页核对提示改为“当前状态—核对要求—后续操作”的表达，不再使用旧版蓝色通知条。
2. 课程标准选中状态、键盘焦点、运行状态和 AI 辅助读取文本说明统一为黛青、朱砂和纸张感视觉。
3. 学校信息与学校管理员的页首操作在桌面端保持一行，在手机端改为两列，减少纵向占用。
4. 学校数据文件选择器改为继承当前角色主题，不再固定使用蓝色边框和蓝色选中状态。
5. 超级管理员弹窗统一遮罩、边框、圆角、标题字体和键盘焦点反馈。
6. 保留正常、提醒、失败等语义颜色，不用颜色作为唯一状态依据。

## 浏览器复核结果

- 七个入口均可正常加载。
- 未发现前端运行错误或 500 响应。
- 桌面端与手机端均未发现页面级横向溢出。
- 未发现外部字体、图片、图标或脚本请求。
- 课程标准已发布版本的逐页核对窗口可正常打开，并显示新的只读说明。

## 截图

桌面端：

- [首页](desktop-1440/dashboard.png)
- [学校信息](desktop-1440/schools.png)
- [学校管理员](desktop-1440/school-admins.png)
- [课程标准](desktop-1440/curriculum-standards.png)
- [学校数据接收](desktop-1440/collection.png)
- [校际数据概览](desktop-1440/analysis.png)
- [系统检查](desktop-1440/health.png)
- [逐页原文核对](desktop-1440/curriculum-page-review.png)
- [登记课程标准](desktop-1440/curriculum-standard-editor.png)

手机端：

- [首页](mobile-390/dashboard.png)
- [学校信息](mobile-390/schools.png)
- [学校管理员](mobile-390/school-admins.png)
- [课程标准](mobile-390/curriculum-standards.png)
- [学校数据接收](mobile-390/collection.png)
- [校际数据概览](mobile-390/analysis.png)
- [系统检查](mobile-390/health.png)
