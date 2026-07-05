# API 契约

## 基本约定

API 前缀：

```text
/api/v1/
```

响应格式：

```json
{
  "data": {},
  "message": ""
}
```

列表响应：

```json
{
  "data": {
    "count": 0,
    "page": 1,
    "page_size": 20,
    "results": []
  },
  "message": ""
}
```

错误响应：

```json
{
  "data": null,
  "message": "错误说明",
  "errors": {
    "field": ["字段错误"]
  }
}
```

## 认证

使用 Django Session Cookie。

### 获取 CSRF

```text
GET /api/v1/auth/csrf/
```

返回：

```json
{
  "data": {"csrf_token": "..."},
  "message": "ok"
}
```

### 登录

```text
POST /api/v1/auth/login/
```

请求：

```json
{
  "username": "schooladmin1",
  "password": "Strata2026"
}
```

返回：

```json
{
  "data": {
    "id": 1,
    "username": "schooladmin1",
    "display_name": "学校管理员",
    "role": "school_admin",
    "school": {"id": 1, "name": "小榄中学", "code": "XLZX"}
  },
  "message": "登录成功"
}
```

### 当前用户

```text
GET /api/v1/auth/me/
```

### 退出

```text
POST /api/v1/auth/logout/
```

## 超级管理员

### 数据总览

```text
GET /api/v1/super-admin/dashboard/
```

返回：

- 学校数。
- 学校管理员数。
- 教师数。
- 学生档案数。
- 班级数。
- 学习行为事件数。
- 近期采集。
- 近期日志。

### 学校列表

```text
GET /api/v1/super-admin/schools/?q=&status=&page=1
```

### 新增学校

```text
POST /api/v1/super-admin/schools/
```

### 学校详情、编辑、删除

```text
GET /api/v1/super-admin/schools/{id}/
PATCH /api/v1/super-admin/schools/{id}/
DELETE /api/v1/super-admin/schools/{id}/
```

删除规则：

- 学校必须先停用或归档。
- 已有关联班级、账号、采集记录或导出记录时不做物理删除。

### 学校批量操作

```text
POST /api/v1/super-admin/schools/bulk-disable/
POST /api/v1/super-admin/schools/bulk-delete/
```

请求：

```json
{"ids": [1, 2]}
```

规则：

- 批量删除前如果包含启用学校，前端先执行批量停用，并提示用户重新勾选后再删除。
- 已有关联数据的学校不物理删除，保持停用或归档状态。

### 学校管理员列表

```text
GET /api/v1/super-admin/school-admins/?q=&school=&status=&page=1
POST /api/v1/super-admin/school-admins/
GET /api/v1/super-admin/school-admins/{id}/
PATCH /api/v1/super-admin/school-admins/{id}/
DELETE /api/v1/super-admin/school-admins/{id}/
POST /api/v1/super-admin/school-admins/{id}/active/
POST /api/v1/super-admin/school-admins/{id}/reset-password/
```

账号规则：

- 删除必须先停用。
- 若有关联业务数据，API 返回 400 并提示保留停用状态。
- 学校管理员使用强密码规则：8-32 位，至少包含字母和数字。

### 学校管理员批量操作

```text
POST /api/v1/super-admin/school-admins/bulk-disable/
POST /api/v1/super-admin/school-admins/bulk-delete/
```

规则：

- 请求体为 `{"ids": [1, 2]}`。
- 删除必须先停用。
- 如果批量删除包含启用账号，前端先执行批量停用，用户重新选择后再删除。

## 学校管理员

### 管理首页

```text
GET /api/v1/school-admin/dashboard/
```

返回：

- 教师数。
- 学生数。
- 班级数。
- 课程数。
- 今日行为事件数。
- 待处理事项。
- 近 7 天登录趋势。
- 近 7 天学习事件趋势。

### 教师列表

```text
GET /api/v1/school-admin/teachers/?q=&status=&page=1
POST /api/v1/school-admin/teachers/
POST /api/v1/school-admin/teachers/bulk-disable/
POST /api/v1/school-admin/teachers/bulk-delete/
GET /api/v1/school-admin/teachers/{id}/
PATCH /api/v1/school-admin/teachers/{id}/
DELETE /api/v1/school-admin/teachers/{id}/
POST /api/v1/school-admin/teachers/{id}/active/
POST /api/v1/school-admin/teachers/{id}/reset-password/
```

教师账号规则：

- 教师属于教学账号，密码允许 6-32 位课堂简易密码，例如 `123456`。
- 删除必须先停用。
- 若有关联课程、资源、学习行为、任课关系等业务数据，API 返回 400 并提示保留停用状态。
- 批量删除请求体为 `{"ids": [1, 2]}`。
- 批量删除前如果包含启用账号，API 返回 400；前端应先执行批量停用，再让用户重新选择后删除。

### 学生列表

```text
GET /api/v1/school-admin/students/?q=&class=&page=1
POST /api/v1/school-admin/students/
POST /api/v1/school-admin/students/bulk-disable/
POST /api/v1/school-admin/students/bulk-delete/
GET /api/v1/school-admin/students/{id}/
PATCH /api/v1/school-admin/students/{id}/
DELETE /api/v1/school-admin/students/{id}/
POST /api/v1/school-admin/students/{id}/active/
POST /api/v1/school-admin/students/{id}/reset-password/
```

学生账号规则：

- 学生属于教学账号，密码允许 6-32 位课堂简易密码，例如 `123456`。
- 学生创建时可以暂不选择班级，`class_group` 可为空。
- 学生创建时不默认分层，`current_layer` 可为空。
- 学生档案需要标记首次使用状态，默认 `is_first_use=true`、`onboarding_status=new`。
- 学生首次登录后必须修改密码、选择本校启用班级、完成素养题和态度问卷前测。
- 未完成前测的学生不能进入正式学习平台，只能进入首次使用流程。
- 新生可先不填写学号。
- 学号后续通过批量导入按登录账号匹配更新。
- 已填写学号后，学号在班级内唯一；空学号不参与唯一约束。
- 删除必须先停用。
- 若已有学习行为、特征快照或分层记录，API 返回 400 并提示保留停用状态。
- 批量删除请求体为 `{"ids": [1, 2]}`。
- 批量删除前如果包含启用账号，API 返回 400；前端应先执行批量停用，再让用户重新选择后删除。

### 班级列表

```text
GET /api/v1/school-admin/classes/?q=&status=&page=1
POST /api/v1/school-admin/classes/
POST /api/v1/school-admin/classes/bulk-create/
POST /api/v1/school-admin/classes/bulk-disable/
POST /api/v1/school-admin/classes/bulk-delete/
POST /api/v1/school-admin/classes/graduate/
POST /api/v1/school-admin/classes/promote/
GET /api/v1/school-admin/classes/{id}/
PATCH /api/v1/school-admin/classes/{id}/
DELETE /api/v1/school-admin/classes/{id}/
```

班级规则：

- 班级名称在本校内唯一。
- 批量新增班级按 `{年级}{班号}班` 自动命名。
- 批量新增请求字段：`grade`、`entry_year`、`class_count`、`start_no`、`status`。
- 批量新增如果遇到同名班级，整批拒绝创建。
- 批量升班请求字段：`from_grade`、`to_grade`。
- 批量升班会更新班级年级和名称，例如 `高一1班` 更新为 `高二1班`。
- 批量升班如果遇到目标班级重名，整批拒绝更新。
- 班级支持 `active`、`disabled`、`archived`。
- 删除必须先停用或归档。
- 若已有学生、学习行为、特征快照、分层记录、模型版本或训练任务，API 返回 400 并提示保留停用或归档状态。
- 批量删除请求体为 `{"ids": [1, 2]}`。
- 批量删除前如果包含启用班级，API 返回 400；前端应先执行批量停用，再让用户重新选择后删除。
- 批量毕业请求体为 `{"ids": [1, 2]}`，会将班级设为 `archived`，写入毕业时间和操作者，并停用班内所有学生账号。

### 任课关系

```text
GET /api/v1/school-admin/teaching/options/
GET /api/v1/school-admin/teaching/?q=&class=&teacher=&page=1
POST /api/v1/school-admin/teaching/
GET /api/v1/school-admin/teaching/{id}/
PATCH /api/v1/school-admin/teaching/{id}/
DELETE /api/v1/school-admin/teaching/{id}/
POST /api/v1/school-admin/teaching/bulk-save/
GET /api/v1/school-admin/teaching/export/
```

任课关系规则：

- 任课关系只表达“教师任教哪些班级”，不绑定课程、角色或状态。
- 列表按教师聚合返回，每个教师行包含 `classes` 任教班级数组。
- 批量保存请求体为 `{"teacher": 1, "class_groups": [1, 2]}`。
- 批量保存采用覆盖式设置：传入的班级列表就是该教师保存后的任教班级；取消勾选的班级会移除任教关系。
- 同一学校内，同一教师和同一班级只能存在一条任教关系。

### 学科与学科前测

学科：

```text
GET /api/v1/school-admin/subjects/?q=&status=
POST /api/v1/school-admin/subjects/
GET /api/v1/school-admin/subjects/{id}/
PATCH /api/v1/school-admin/subjects/{id}/
DELETE /api/v1/school-admin/subjects/{id}/
```

前测套卷：

```text
GET /api/v1/school-admin/pretests/?q=&subject=&kind=&status=&page=1
POST /api/v1/school-admin/pretests/
GET /api/v1/school-admin/pretests/{id}/
PATCH /api/v1/school-admin/pretests/{id}/
DELETE /api/v1/school-admin/pretests/{id}/
POST /api/v1/school-admin/pretests/{id}/publish/
POST /api/v1/school-admin/pretests/{id}/archive/
```

题目：

```text
GET /api/v1/school-admin/pretests/{paper_id}/questions/
POST /api/v1/school-admin/pretests/{paper_id}/questions/
PATCH /api/v1/school-admin/pretests/{paper_id}/questions/{id}/
DELETE /api/v1/school-admin/pretests/{paper_id}/questions/{id}/
```

规则：

- 学科属于本校，学校管理员不能传入其他学校范围。
- 前测类型为 `literacy` 和 `attitude`。
- 学生进入某学科正式学习前，需要完成该学科当前发布的两类前测。
- 同一学科同一类型发布新版本时，旧发布版本自动归档。
- 已有作答记录的套卷和题目不物理删除。

## 权限规则

## 教师

教师 API 前缀：

```text
/api/v1/teacher/
```

权限边界：

- 教师只能访问自己创建的课程、课时、资源、题目、任务。
- 教师只能访问学校管理员分配给自己的任教班级。
- 教师只能查看任教班级内学生的学习数据。
- 教师可以查询任教班级学生账号，并将学生密码重置为固定课堂默认密码 `123456`。
- 教师不能新增、编辑、停用、删除学生账号，也不能修改学生姓名、学号、班级、层级和状态。
- 教师不能通过请求体或 URL 传入其他学校、其他教师或非任教班级数据。

### 教师首页

```text
GET /api/v1/teacher/dashboard/
```

返回：

- 任教班级数。
- 我的课程数。
- 今日课堂活动数。
- 待批改任务数。
- 待确认分层建议数。
- 近 7 天任教班级学习事件趋势。
- 任教班级活跃度对比。
- 今日课堂列表。
- 待处理列表。

### 我的课程

```text
GET /api/v1/teacher/course-options/
GET /api/v1/teacher/courses/?q=&subject=&status=&page=1
POST /api/v1/teacher/courses/
GET /api/v1/teacher/courses/{id}/
PATCH /api/v1/teacher/courses/{id}/
DELETE /api/v1/teacher/courses/{id}/
POST /api/v1/teacher/courses/{id}/publish/
POST /api/v1/teacher/courses/{id}/archive/
POST /api/v1/teacher/courses/{id}/classes/
```

规则：

- 课程属于创建教师。
- 课程所属学科必须为本校启用学科。
- 发布到班级时，班级必须是教师任教班级。
- 第一版课程状态使用 `is_active` 映射：`draft` 为未发布，`published` 为已发布。
- 发布课程前需要选择学科、至少绑定 1 个任教班级、至少创建 1 个课时。
- 已发布课程不能直接删除，必须先停用。
- 已有学习事件或课堂记录的课程不能物理删除，只能停用保留。

### 课时

```text
GET /api/v1/teacher/courses/{course_id}/lessons/
POST /api/v1/teacher/courses/{course_id}/lessons/
GET /api/v1/teacher/lessons/{id}/
PATCH /api/v1/teacher/lessons/{id}/
DELETE /api/v1/teacher/lessons/{id}/
POST /api/v1/teacher/lessons/{id}/publish/
POST /api/v1/teacher/lessons/{id}/archive/
```

规则：

- 课时必须属于教师自己的课程。
- 第一版课时状态使用 `is_active` 映射：`draft` 为未发布，`published` 为已发布。
- 已发布课时不能直接删除，必须先停用。
- 已有学习事件或课堂记录的课时不能物理删除。

### 课时设计环节

```text
GET /api/v1/teacher/lessons/{lesson_id}/steps/
POST /api/v1/teacher/lessons/{lesson_id}/steps/
POST /api/v1/teacher/lessons/{lesson_id}/steps/reorder/
GET /api/v1/teacher/lesson-steps/{id}/
PATCH /api/v1/teacher/lesson-steps/{id}/
DELETE /api/v1/teacher/lesson-steps/{id}/
```

第一版已实现 `LessonStep`，用于保存课时学习过程中的可排序环节。

字段：

- `title`：环节标题。
- `step_type`：`intro`、`resource`、`question`、`task`、`upload`、`discussion`、`evaluation`、`reflection`、`ai_worksheet`、`document`。
- `student_instruction`：学生可见说明。
- `teacher_note`：教师备课备注。
- `sort_order`：排序。
- `is_required`：是否必做。
- `estimated_minutes`：预计时长。
- `target_layer`：`all`、`A`、`B`、`C`、`A/B`、`B/C`、`A/B/C`。
- `status`：`draft` 或 `ready`。
- `resource_items`：第一版资源名称数组，后续替换为真实资源绑定。
- `activity_items`：第一版活动/任务名称数组，主要用于任务、讨论、作品提交等轻量占位。
- `question_items`：课堂题结构化 JSON 数组，支持 `single`、`multiple`、`judge`、`blank`、`text`。
- `ai_prompt`：AI 学习单生成目标草稿。
- `collect_student_log`、`collect_class_log`：是否写入学生/班级学习日志。

`question_items` 题目字段：

- `id`：题目临时 ID。
- `question_type`：`single`、`multiple`、`judge`、`blank`、`text`。
- `stem`、`options`、`answer`、`analysis`。
- `score`：基础分值。
- `target_layer`：`all`、`A`、`B`、`C`、`A/B`、`B/C`、`A/B/C`。
- `use_layer_scores`：是否启用分层分值。
- `layer_scores`：`{"A": 2, "B": 2, "C": 1}`。
- `is_required`、`sort_order`。

规则：

- 教师只能操作自己课程下的课时环节。
- 排序接口只接收当前课时内的环节 `ids`，后端统一重写 `sort_order`。
- 第一版不直接让 AI 发布内容，AI 目标只作为草稿保存。
- 课时设计页面左侧上下文只显示学科、课程和当前课时，不展示课程绑定的所有任教班级；班级发布范围在课程管理中维护。
- 当前第一版已接入教师资源库上传，上传资源后可把资源显示名加入 `resource_items`；后续再升级为 `LessonStepResource` 关系表。
- 教师端保存 `question_items` 时包含参考答案和解析；学生端读取课时工作台时只返回题干、题型、选项、分值和必答状态，不返回答案。
- 课堂未启用分层模式时，学生端返回当前环节全部题目。
- 课堂启用分层模式时，学生端按学生 `StudentProfile.current_layer` 过滤 `question_items`；`target_layer=all` 对所有学生可见；启用 `use_layer_scores` 时学生端 `score` 返回该学生层级分值。
- `A/B` 和 `B/C` 是正式支持的相邻层级组合；第一版不开放 `A/C`。
- 新建题目基础分按题型给初始值：选择/判断 2 分，填空 3 分，简答 5 分。
- 新建题目开启分层分值时，前端先按 `target_layer` 给 `layer_scores.A/B/C` 初始建议值；无法判断时三层都等于基础分。
- AI 分值建议只能返回建议值，不能直接覆盖教师已保存的 `layer_scores`。
- 学生提交课堂题仍走 `POST /api/v1/student/lesson-steps/{id}/answer/`，提交内容写入 `LearningEvent.answer_submit`；后续可升级为正式 `LessonStepSubmission`。

### 教师 AI 接入

```text
GET /api/v1/teacher/ai-provider/
PATCH /api/v1/teacher/ai-provider/
POST /api/v1/teacher/ai-provider/test/
```

### AI 生成分层题草稿

```text
POST /api/v1/teacher/lesson-steps/ai-generate-questions/
```

请求：

```json
{
  "direction": "围绕数据采集流程，分别设计拓展题、核心题、基础支架题和相邻层级共用题。",
  "question_type": "single",
  "count": 1,
  "subject_name": "信息科技",
  "lesson_title": "数据采集",
  "step_title": "任务分析",
  "student_instruction": "阅读材料并完成问题。",
  "requirement": "选项要包含常见误区。"
}
```

响应：

```json
{
  "groups": [
    {
      "target_layer": "A",
      "target_layer_label": "A",
      "questions": [],
      "score_defaults": {"base_score": 2, "layer_scores": {"A": 3, "B": 2, "C": 2}}
    }
  ],
  "questions": [
    {
      "id": "q_xxx",
      "question_type": "single",
      "stem": "题干",
      "options": ["A", "B", "C", "D"],
      "answer": ["A"],
      "score": 2,
      "target_layer": "B/C",
      "use_layer_scores": true,
      "layer_scores": {"A": 2, "B": 2, "C": 1.5},
      "analysis": "解析",
      "is_required": true,
      "sort_order": 10,
      "ai_generated": true,
      "ai_score_note": "AI 建议分值，教师确认后才写入环节。"
    }
  ],
  "score_defaults": {
    "base_score": 2,
    "groups": {
      "A": {"base_score": 2, "layer_scores": {"A": 3, "B": 2, "C": 2}},
      "B": {"base_score": 2, "layer_scores": {"A": 2, "B": 2, "C": 2}},
      "C": {"base_score": 2, "layer_scores": {"A": 2, "B": 2, "C": 1.5}},
      "A/B": {"base_score": 2, "layer_scores": {"A": 2.5, "B": 2, "C": 2}},
      "B/C": {"base_score": 2, "layer_scores": {"A": 2, "B": 2, "C": 1.5}}
    },
    "note": "系统按 A、B、C、A/B、B/C 同时给题目和分值建议；后续接入分层模型后，只作为建议，必须由教师确认。"
  }
}
```

规则：

- 仅教师可用，且只使用该教师在 `AI 接入` 中保存的 DeepSeek API Key。
- 教师只提交一个出题方向；系统必须同时生成 `A`、`B`、`C`、`A/B`、`B/C` 五组题目。
- 后端要求模型返回 JSON，并二次校验题型、层级、选项、答案和分值。
- 接口只返回草稿，不直接写入 `LessonStep.question_items`。
- 教师端必须经过“直接加入”或“编辑后加入”才会写入当前环节。
- 无外网或未配置 Key 时，返回可恢复错误，不影响手动出题。

规则：

- 第一版默认支持 DeepSeek。
- 每位教师维护自己的 API Key。
- API Key 加密保存，接口只返回是否已配置和尾号，不返回完整 Key。
- 无外网或未配置 Key 时，只禁用 AI 辅助备课，不影响课程、课堂、资源和评价等本地功能。
- AI 生成内容只能作为草稿，后续发布到课时前必须由教师确认。

### 课堂教学

```text
GET /api/v1/teacher/classroom/options/
GET /api/v1/teacher/classroom/sessions/?q=&class=&course=&status=&page=1
POST /api/v1/teacher/classroom/sessions/
GET /api/v1/teacher/classroom/sessions/{id}/
PATCH /api/v1/teacher/classroom/sessions/{id}/
DELETE /api/v1/teacher/classroom/sessions/{id}/
POST /api/v1/teacher/classroom/sessions/{id}/start/
POST /api/v1/teacher/classroom/sessions/{id}/restart/
POST /api/v1/teacher/classroom/sessions/{id}/finish/
POST /api/v1/teacher/classroom/sessions/{id}/step/open/
POST /api/v1/teacher/classroom/sessions/{id}/step/lock/
POST /api/v1/teacher/classroom/sessions/{id}/step/close/
GET /api/v1/teacher/classroom/sessions/{id}/activities/
POST /api/v1/teacher/classroom/sessions/{id}/activities/
GET /api/v1/teacher/classroom/activities/{id}/
PATCH /api/v1/teacher/classroom/activities/{id}/
DELETE /api/v1/teacher/classroom/activities/{id}/
POST /api/v1/teacher/classroom/activities/{id}/open/
POST /api/v1/teacher/classroom/activities/{id}/close/
```

规则：

- 课堂场次必须选择教师自己的课程、该课程课时和该课程已绑定的任教班级。
- 课堂状态为 `draft`、`running`、`finished`。
- 只有 `draft` 未开始课堂可以删除。
- 已结束课堂可以通过 `restart` 重新开始，重新开始会清空当前投放环节，学生端等待教师重新投放。
- 开始和结束课堂会写入 `LearningEvent.teacher_intervention`。
- 结束课堂会自动关闭进行中的课堂活动。
- `ClassroomSession` 记录当前投放环节：`current_step`、`current_step_status`、`submission_locked`、`current_step_started_at`、`current_step_closed_at`。
- `ClassroomSession.is_layered` 表示本次课堂是否启用分层教学模式。创建/编辑课堂时可传入 `is_layered: true/false`。
- `step/open` 只允许投放当前课堂绑定课时下已配置的 `LessonStep`，课堂未开始时前端会先调用开始课堂。
- `step/lock` 锁定当前环节提交，`step/close` 关闭当前环节并保持提交锁定。
- 课堂活动状态为 `draft`、`open`、`closed`。
- 开启和关闭课堂活动会写入 `LearningEvent.teacher_intervention`。
- 当前第一版已完成课堂场次、当前环节投放、锁定提交、关闭环节和活动开关；学生端实时 WebSocket 推送和 submissions 后续实现。

### 测试、任务、项目

测试：

```text
GET /api/v1/teacher/assessments/?q=&class=&course=&status=&page=1
POST /api/v1/teacher/assessments/
GET /api/v1/teacher/assessments/{id}/
PATCH /api/v1/teacher/assessments/{id}/
DELETE /api/v1/teacher/assessments/{id}/
POST /api/v1/teacher/assessments/{id}/publish/
POST /api/v1/teacher/assessments/{id}/close/
GET /api/v1/teacher/assessments/{id}/submissions/
POST /api/v1/teacher/assessments/{id}/grade/
GET /api/v1/teacher/assessments/{id}/export/
```

任务：

```text
GET /api/v1/teacher/tasks/?q=&class=&course=&status=&page=1
POST /api/v1/teacher/tasks/
GET /api/v1/teacher/tasks/{id}/
PATCH /api/v1/teacher/tasks/{id}/
DELETE /api/v1/teacher/tasks/{id}/
POST /api/v1/teacher/tasks/{id}/publish/
POST /api/v1/teacher/tasks/{id}/close/
GET /api/v1/teacher/tasks/{id}/submissions/
POST /api/v1/teacher/tasks/{id}/grade/
GET /api/v1/teacher/tasks/{id}/export/
```

项目评价后续使用：

```text
GET /api/v1/teacher/projects/
POST /api/v1/teacher/projects/
GET /api/v1/teacher/projects/{id}/
PATCH /api/v1/teacher/projects/{id}/
GET /api/v1/teacher/projects/{id}/milestones/
POST /api/v1/teacher/projects/{id}/milestones/
PATCH /api/v1/teacher/projects/{id}/milestones/{milestone_id}/
GET /api/v1/teacher/projects/{id}/gantt/
PATCH /api/v1/teacher/projects/{id}/gantt/
GET /api/v1/teacher/projects/{id}/logs/
POST /api/v1/teacher/projects/{id}/logs/
GET /api/v1/teacher/projects/{id}/submissions/
POST /api/v1/teacher/projects/{id}/grade/
GET /api/v1/teacher/projects/{id}/export/
```

学习日志后续使用：

```text
GET /api/v1/teacher/classes/{class_id}/learning-logs/?course=&lesson=&project=&page=1
POST /api/v1/teacher/classes/{class_id}/learning-logs/
GET /api/v1/teacher/students/{student_id}/learning-logs/?course=&lesson=&project=&page=1
POST /api/v1/teacher/students/{student_id}/learning-logs/
GET /api/v1/student/learning-logs/?course=&lesson=&project=&page=1
POST /api/v1/student/learning-logs/
```

规则：

- 学习日志不替代 `LearningEvent`，只作为班级和学生过程记录。
- 系统可根据学习行为自动生成日志，教师和学生可补充反思或备注。
- 教师只能查看和补充本人任教班级内的班级日志和学生日志。
- 项目日志、甘特图和里程碑属于项目式学习；任务驱动学习优先记录课时任务过程日志。

### 学生档案

```text
GET /api/v1/teacher/students/?q=&class=&layer=&risk=&page=1
GET /api/v1/teacher/students/{student_id}/profile/
GET /api/v1/teacher/students/{student_id}/events/
GET /api/v1/teacher/students/{student_id}/assessments/
GET /api/v1/teacher/students/{student_id}/projects/
POST /api/v1/teacher/students/{student_id}/notes/
POST /api/v1/teacher/students/{student_id}/reset-password/
GET /api/v1/teacher/students/export/
```

教师学生账号协助规则：

- 教师只能查看和备注任教班级学生，不能修改学生账号基础信息。
- 教师可在任教班级学生列表中查询学生登录账号。
- 教师可将任教班级学生密码重置为 `123456`。
- 重置接口不接收自定义密码字段。
- 重置后学生 `is_first_login=true`，下次登录需要改密。
- 重置操作必须写入审计日志。

### 题库与资源

题库：

```text
GET /api/v1/teacher/questions/?q=&subject=&type=&visibility=&page=1
POST /api/v1/teacher/questions/
GET /api/v1/teacher/questions/{id}/
PATCH /api/v1/teacher/questions/{id}/
DELETE /api/v1/teacher/questions/{id}/
POST /api/v1/teacher/questions/{id}/submit-public/
GET /api/v1/teacher/questions/template/
POST /api/v1/teacher/questions/import/
GET /api/v1/teacher/questions/export/
```

资源：

```text
GET /api/v1/teacher/resources/?q=&page=1
POST /api/v1/teacher/resources/
GET /api/v1/teacher/resources/{id}/
PATCH /api/v1/teacher/resources/{id}/
DELETE /api/v1/teacher/resources/{id}/
GET /api/v1/teacher/resources/export/
```

当前第一版已实现资源列表、上传、详情、编辑和删除 API，前端已实现教师资源管理页和课时设计右侧上传面板。

上传字段：

- `title`：资源标题，2-128 位。
- `content`：资源说明，可空。
- `attachment`：本地文件。
- `is_pinned`：是否置顶。

支持格式：

- 图片：`jpg`、`jpeg`、`png`、`webp`、`gif`。
- 音视频：`mp4`、`webm`、`mov`、`mp3`、`wav`。
- 文档：`pdf`、`doc`、`docx`、`ppt`、`pptx`、`xls`、`xlsx`。
- 数据与文本：`csv`、`txt`、`md`。
- 素材包：`zip`、`rar`、`7z`。

规则：

- 资源属于上传教师本人。
- 文件保存到本地私有化部署存储，不依赖外部云服务。
- 单个资源第一版限制为 512MB。
- 资源预览和 ONLYOFFICE/PDF.js 转换后续继续接入；当前可打开或下载原文件。

### 分层建议

```text
GET /api/v1/teacher/stratification/?class=&status=&page=1
GET /api/v1/teacher/stratification/{id}/
POST /api/v1/teacher/stratification/{id}/accept/
POST /api/v1/teacher/stratification/{id}/reject/
POST /api/v1/teacher/stratification/bulk-accept/
POST /api/v1/teacher/stratification/bulk-reject/
POST /api/v1/teacher/stratification/manual-adjust/
```

AI 分层建议必须教师确认后才生效。拒绝建议和手动调整都要写入审计日志。

### 公告

```text
GET /api/v1/teacher/notices/?q=&class=&status=&page=1
POST /api/v1/teacher/notices/
GET /api/v1/teacher/notices/{id}/
PATCH /api/v1/teacher/notices/{id}/
DELETE /api/v1/teacher/notices/{id}/
POST /api/v1/teacher/notices/{id}/publish/
POST /api/v1/teacher/notices/{id}/revoke/
```

教师公告只能发布给任教班级。

## 学生

学生 API 前缀：

```text
/api/v1/student/
```

设计详见 `docs/student_module_design.md`。

权限边界：

- 学生只能访问自己的账号、档案、前测、作答、提交、学习事件和学习档案。
- 学生只能访问自己当前班级已发布课程、课时、资源、公告和课堂。
- 学生端 API 必须从登录用户推导学校、班级和学生身份，不能信任请求体中的 `student_id`、`school_id` 或 `class_id`。
- 学生不能访问教师备课备注、教师管理资源、其他学生数据、管理员数据、模型训练任务和分层建议后台数据。

### 当前学生

```text
GET /api/v1/student/me/
```

返回：

- 用户信息。
- 学生档案。
- 班级。
- 首次使用状态。
- 当前课堂状态。

### 首次使用

```text
GET /api/v1/student/onboarding/
GET /api/v1/student/onboarding/classes/
POST /api/v1/student/onboarding/password/
POST /api/v1/student/onboarding/class/
```

规则：

- 学生首次登录必须修改密码。
- 学生允许课堂简易密码，例如 `123456`。
- 新生可在首次使用时选择本校启用班级。
- 新生学号可为空，后续由学校管理员批量导入匹配更新。

### 学科前测

```text
GET /api/v1/student/pretests/required/
GET /api/v1/student/pretests/{subject_id}/
GET /api/v1/student/pretests/papers/{paper_id}/
POST /api/v1/student/pretests/papers/{paper_id}/submit/
```

规则：

- 学生进入某学科课程前，必须完成该学科当前发布的素养测试和学习态度问卷。
- 学生只能提交自己未完成的当前发布前测。
- 提交写入 `PretestSubmission` 和学习行为事件。

### 课程与课时

```text
GET /api/v1/student/courses/
GET /api/v1/student/courses/{course_id}/
GET /api/v1/student/courses/{course_id}/lessons/
GET /api/v1/student/lessons/{lesson_id}/workspace/
POST /api/v1/student/lessons/{lesson_id}/enter/
POST /api/v1/student/lesson-steps/{step_id}/enter/
POST /api/v1/student/lesson-steps/{step_id}/complete/
POST /api/v1/student/lesson-steps/{step_id}/answer/
POST /api/v1/student/lesson-steps/{step_id}/upload/
POST /api/v1/student/lesson-steps/{step_id}/reflection/
```

规则：

- 学生只能看到自己班级绑定的已发布课程。
- 课时必须属于学生可见课程。
- 课时学习工作台读取教师端 `LessonStep` 学习过程。
- 学生端会读取 `question_items` 并按题型渲染作答控件；参考答案不会下发给学生端。
- 进入课程、课时、环节、查看资源、提交答案和上传作品都要写入 `LearningEvent`。

### 资源

```text
GET /api/v1/student/resources/
GET /api/v1/student/resources/{resource_id}/
POST /api/v1/student/resources/{resource_id}/view/
POST /api/v1/student/resources/{resource_id}/progress/
```

规则：

- 学生只能查看被课程、课时或教师发布到自己班级的资源。
- 资源预览优先本地预览能力；无预览能力时提供下载。
- 资源查看、停留、播放进度和完成状态进入学习行为事件。

### 实时课堂

```text
GET /api/v1/student/classroom/current/
GET /api/v1/student/classroom/{session_id}/
POST /api/v1/student/classroom/{session_id}/sign-in/
POST /api/v1/student/classroom/activities/{activity_id}/submit/
POST /api/v1/student/classroom/activities/{activity_id}/confusion/
```

规则：

- 学生只能进入自己班级的进行中课堂。
- 未开始、已结束或非本班课堂，`GET /student/classroom/{session_id}/` 不返回课堂内容。
- 课堂进行中但教师尚未投放环节时，接口可返回课堂基础状态，但 `current_step` 为空，学生端显示等待。
- 只有教师投放当前环节后，学生端才展示该环节资源、题目和任务。
- 如果课堂 `is_layered=true`，学生端 `current_step.question_items` 已由后端按学生当前层级过滤；学生端不能自行请求其他层级题目。
- 如果题目启用分层分值，学生端收到的 `score` 已是该学生层级对应分值。
- 默认所有课时由课堂教学启用控制。未给学生所在班级创建课堂场次、未开始课堂、已结束课堂，普通课时工作台 `/student/lessons/{lesson_id}/workspace/` 都不返回课时内容。
- 学生必须等待教师创建课堂、开始课堂并投放环节后，才能从课堂入口查看该环节资源和题目。
- 教师开启活动后，学生端通过 WebSocket 收到状态。
- 教师关闭活动后，学生端不能继续提交。
- 签到、抢答、即时题、未懂反馈和课堂任务都要写入学习事件。

### 任务、测试、项目

```text
GET /api/v1/student/tasks/
GET /api/v1/student/tasks/{task_id}/
POST /api/v1/student/tasks/{task_id}/submit/
GET /api/v1/student/tests/
GET /api/v1/student/tests/{test_id}/
POST /api/v1/student/tests/{test_id}/submit/
GET /api/v1/student/projects/
GET /api/v1/student/projects/{project_id}/
POST /api/v1/student/projects/{project_id}/logs/
POST /api/v1/student/projects/{project_id}/submit/
POST /api/v1/student/projects/{project_id}/self-evaluation/
POST /api/v1/student/projects/{project_id}/peer-evaluation/
```

规则：

- 第一阶段可先实现任务和作品提交，测试和项目评价后续补齐。
- 项目式学习要保留个人日志、小组协作、阶段成果、自评互评和教师评价。

### 学习档案、公告和留言

```text
GET /api/v1/student/profile/
GET /api/v1/student/profile/events/
GET /api/v1/student/profile/submissions/
GET /api/v1/student/profile/logs/
GET /api/v1/student/notices/
GET /api/v1/student/feedback/
POST /api/v1/student/feedback/
GET /api/v1/student/feedback/{id}/
```

规则：

- 学习档案只展示学生自己的学习记录、提交记录、教师反馈和学习日志。
- 学生公告只显示自己班级可见的已发布公告。
- 学生留言默认只能发给自己的任课教师。

角色：

- `super_admin`
- `school_admin`
- `teacher`
- `student`

学校管理员 API 必须从登录用户获取学校范围。  
不能信任 URL 或请求体传入的 `school_id`。

## XLSX 导入导出

导入导出继续由 Django 完成。

Vue 只负责：

- 上传文件。
- 下载模板。
- 下载导出结果。
- 展示导入错误。

下载类接口可以直接返回文件流，不强制使用 JSON 包装。

## WebSocket

WebSocket 路径：

```text
/ws/classes/{class_id}/
```

后续扩展：

- `class:{class_id}` 课堂广播。
- `lesson:{lesson_id}` 课时状态。
- `group:{group_id}` 小组协作。
- `user:{user_id}` 个人通知。
- `control:{class_id}` 教师控制指令。

WebSocket 必须校验登录态和班级权限。
