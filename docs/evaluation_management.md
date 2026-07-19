# STRATA 教师评价标准管理

> 实现日期：2026-07-19  
> 当前状态：教师评价方案、评价标准、版本管理、试用记录和课时环节绑定已经完成；课堂开启评价时会冻结所选版本，并把评价提交关联到本环节作答与学生作品。正式课堂试用结论尚未形成。

## 1. 功能定位

评价标准由教师围绕本人课程制定和维护。教师负责明确学习目标、评价依据、学习任务、评价指标和星级说明，并在课程或课堂中使用已发布版本完成自评、互评和师评。学校管理员不制定评价标准，也不直接评价学生，只查看学校层面的汇总和运行情况。

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
- `EvaluationTrialRecord`：内容审核、课堂试用、评分培训和评分一致性检查记录。
- `LessonStepEvaluationBinding`：课时环节选择的已发布标准版本，以及本环节启用的自评、互评和教师评价。
- `ClassroomEvaluationStandardUse`：课堂首次开启评价时形成的不可修改快照。
- `EvaluationSubmissionEvidence`：评价提交与同一课堂、同一环节、同一学生最新作答和最新作品的关联。

实际数据库表、字段、Python 类、API 和前端类型均使用上述名称。历史迁移文件保留旧名称，只用于记录数据库升级过程。

## 3. 评价方案

评价方案绑定教师本人的课程，包含：

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
- 已经投入课堂的课时绑定不能原地修改或删除；需要调整时复制环节并选择新版本，避免改写历史课堂。

## 6. 权限

- 教师：查看和维护本人课程的评价方案、评价标准、版本和试用记录；不能读取其他教师课程的内容。
- 学校管理员：不进入评价标准编辑页面，不直接修改教师评价内容；后续只查看不含学生个体敏感信息的学校汇总。
- 学生：不能访问评价管理页面，只在学习任务中看到教师公开的评价要求和本人结果。
- 超级管理员：不直接编辑成员校评价内容。

所有教师请求都从登录账号取得学校和本人课程范围，不接受客户端传入学校 ID、教师 ID 或越权课程。

## 7. 页面与接口

页面：

```text
/app/teacher/evaluations
```

接口：

```text
GET      /api/v1/teacher/evaluations/options/
GET|POST /api/v1/teacher/evaluations/plans/
GET|PATCH /api/v1/teacher/evaluations/plans/{id}/
POST     /api/v1/teacher/evaluations/plans/{id}/publish/
GET|POST /api/v1/teacher/evaluations/standards/
GET|PATCH /api/v1/teacher/evaluations/standards/{id}/
POST     /api/v1/teacher/evaluations/standards/{id}/publish/
GET|POST /api/v1/teacher/evaluations/trials/
GET|PATCH|DELETE /api/v1/teacher/evaluations/trials/{id}/
GET      /api/v1/teacher/evaluations/trials/export/
GET|PATCH|DELETE /api/v1/teacher/evaluations/lesson-steps/{step_id}/binding/
```

页面包含“评价方案、评价标准、试用记录”三个页签。试用记录支持 XLSX 导出。

## 8. 试用记录

试用记录必须绑定已发布评价标准，包含：

- 内容审核、课堂试用、评分培训或评分一致性检查。
- 记录名称、日期、参与人数和当前状态。
- 评分一致性检查可填写 0-100 的一致率。
- 完成后的处理结论：可使用、需要修改或暂不使用。
- 结果说明、发现的问题和后续处理。

待进行和进行中的记录可以编辑或删除。已完成记录只能查看和导出，不能修改或删除；需要更正时新增补充记录。

## 9. 数据迁移

迁移 `learning_analytics.0013-0015` 已完成：

- 重命名评价领域的数据库表和字段。
- 把旧 JSON 键转换为 `learning_goals`、`evaluation_basis`、`learning_tasks`、`dimension`、`level_descriptions` 和 `scoring_examples`。
- 把课堂评价字段改为 `evaluation_version`。
- 把评价提交事件改为 `evaluation.rating.submitted`。
- 保留原有 1 个方案、1 个标准、5 个指标和 10 个评分示例。
- 迁移 `learning_analytics.0018` 新增评价试用记录表、学校/日期索引和评分一致率范围约束。
- 迁移 `learning_analytics.0019` 新增课时绑定、课堂标准快照和评价证据关联。

SQLite 升级前备份位于 `storage/dev.before-evaluation-rename.sqlite3`。

## 10. 测试数据

当前小榄中学已生成 4 条带“测试-”前缀的记录，用于检查页面和导出：

```powershell
.\.venv\Scripts\python.exe manage.py seed_evaluation_trial_records --school-code 001 --username <教师账号>
```

清理测试记录：

```powershell
.\.venv\Scripts\python.exe manage.py seed_evaluation_trial_records --school-code 001 --purge
```

测试记录不能作为正式评价结论。

## 11. 后续开发

1. 为题库题目增加审核、试用、启用和停用状态。
2. 建立共同测试和不同版本结果比较。
3. 使用正式课堂数据补充真实试用记录。
4. 前述流程稳定后，再进入学生学习情况汇总和分层建议开发。
