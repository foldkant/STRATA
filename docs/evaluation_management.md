# EVAL-01A 学校评价管理

> 实现日期：2026-07-19  
> 当前状态：数据库、API、学校管理员页面和版本管理已完成；正式学校试用与专家审核尚未开始。

## 1. 功能定位

评价管理由学校管理员维护，用于统一本校课程的评价要求。教师不再维护学校级方案，只在课程和课堂中选用已发布内容、完成评分并查看任教学生结果。

平台统一使用以下名称：

```text
评价方案 -> 学习目标 -> 评价依据 -> 学习任务 -> 评分规则
评价标准 -> 评价指标 -> 星级说明 -> 评分示例
```

## 2. 数据对象

- `EvaluationPlan`：可编辑的评价方案。
- `EvaluationPlanVersion`：已发布的评价方案版本。
- `EvaluationStandard`：可编辑的评价标准。
- `EvaluationStandardVersion`：已发布的评价标准版本。
- `EvaluationCriterionVersion`：评价标准中的单项指标。
- `EvaluationScoringExample`：帮助统一评分判断的示例。

实际数据库表、字段、Python 类、API 和前端类型均使用上述名称。历史迁移文件保留旧名称，只用于记录数据库升级过程。

## 3. 评价方案

评价方案绑定本校课程，包含：

- 方案名称和适用内容版本。
- 适用学生和总体学习目标。
- 具体学习目标。
- 每个目标对应的评价依据。
- 产生评价材料的学习任务。
- 评价内容、思维要求和可用帮助。
- 评分方式、判定说明和后续教学建议。

方案可以先保存未完成内容。发布前系统检查目标、依据和任务之间的关联，避免出现没有评价依据的目标或没有学习任务的依据。

## 4. 评价标准

评价标准必须绑定一个评价方案，包含多个评价指标。每个指标保存：

- 评价方面和评价对象。
- 材料来源与应观察到的具体表现。
- 暂不评价条件。
- 可用帮助和常见问题。
- 1-5 星的具体表现说明。
- 至少两个、覆盖不同星级的评分示例。
- 后续教学建议。

没有足够材料时使用“暂不评价”，不能用 0 分或 1 星代替。出勤、签到、积分、在线时长等运行数据不能直接作为学科评价指标。

## 5. 版本规则

- 编辑内容保存为当前工作版本。
- 发布后生成不可修改的历史版本。
- 相同内容重复发布不会生成重复版本。
- 修改后再次发布会生成下一版本。
- 已发布版本不能删除，保证历史评分可以追溯。

## 6. 权限

- 学校管理员：查看和维护本校全部评价方案、评价标准及其版本。
- 教师：不能访问学校管理员评价管理 API；后续只读取学校发布内容并用于本人课程。
- 学生：不能访问评价管理页面，只在学习任务中看到教师公开的评价要求和本人结果。
- 超级管理员：不直接编辑成员校评价内容。

所有学校管理员请求都从登录账号取得学校范围，不接受客户端传入学校 ID。

## 7. 页面与接口

页面：

```text
/app/school-admin/evaluations
```

接口：

```text
GET      /api/v1/school-admin/evaluations/options/
GET|POST /api/v1/school-admin/evaluations/plans/
GET|PATCH /api/v1/school-admin/evaluations/plans/{id}/
POST     /api/v1/school-admin/evaluations/plans/{id}/publish/
GET|POST /api/v1/school-admin/evaluations/standards/
GET|PATCH /api/v1/school-admin/evaluations/standards/{id}/
POST     /api/v1/school-admin/evaluations/standards/{id}/publish/
```

## 8. 数据迁移

迁移 `learning_analytics.0013-0015` 已完成：

- 重命名评价领域的数据库表和字段。
- 把旧 JSON 键转换为 `learning_goals`、`evaluation_basis`、`learning_tasks`、`dimension`、`level_descriptions` 和 `scoring_examples`。
- 把课堂评价字段改为 `evaluation_version`。
- 把评价提交事件改为 `evaluation.rating.submitted`。
- 保留原有 1 个方案、1 个标准、5 个指标和 10 个评分示例。

SQLite 升级前备份位于 `storage/dev.before-evaluation-rename.sqlite3`。

## 9. 后续开发

1. 学校管理员审核、启用和停用评价版本。
2. 教师在课程或课时中选择已发布评价标准。
3. 题库题目与评价目标关联。
4. 评分一致性检查和试用记录。
5. 在正式数据满足要求后，再进入学生特征和分层建议开发。
