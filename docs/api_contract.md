# API 契约

> 本文只记录已经实现或已进入当前开发批次的接口。AI 隐性动态分层的未来接口、实施顺序和上线检查见 [开发路线图](student_behavior_ai_stratification_development_roadmap.md)；实现后再逐项合并到本文，不能把规划中的路由当作可用接口。

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

## 学生隐性分层响应契约

学生接口采用字段白名单。任何学生身份响应、WebSocket、浏览器缓存、下载文件名和通知不得包含：

- `current_layer`、`current_layer_label`、`current_group_no`
- `target_layer`、`target_layer_label`
- `layer_scores`、`use_layer_scores`、`is_layered`
- `layer_hint`、`grouping_strategy`、`grouping_strategy_label`
- 模型概率、置信度、排名、风险原因和其他内容变体

已完成的学生隐私与权限调整：

- `GET /api/v1/student/me/`：学生 profile 不返回当前层级和持久分组编号。
- `GET /api/v1/student/classroom/current/` 与 `GET /api/v1/student/classroom/{id}/`：服务端完成题目过滤，只返回已分配题目，不返回环节目标层、分层分值和“已匹配层级”标记。
- `GET /api/v1/student/classroom/{id}/group-collaboration/`：只返回本人当前小组、组员和协作所需配置；不返回分组策略、`layer_hint` 或组员层级。
- `GET /api/v1/student/classroom/{id}/evaluation/`：互评对象不返回层级，小组信息使用学生安全 DTO。
- 学生通过直接 ID 提交未分配题目时返回 404；不能依靠前端隐藏控制权限。
- 自动分组对学生统一显示“第 N 组”，聊天和 ONLYOFFICE 标题也使用中性组名。

教师接口继续返回其任教班级所需的内容带和分组依据。未来教师分层接口必须接入 `SensitiveInferenceAccessLog`；`api/analytics/` 当前只建立独立路由包，尚未开放公共 analytics 路由。

## 受保护文件访问

DEBUG 模式不再直接发布 `/media/`。课程封面、资源文件、学生作品和课堂小组文件统一通过对象级权限接口读取：

- `GET /api/v1/files/courses/{id}/cover/`
- `GET /api/v1/files/resources/{id}/attachment/`
- `GET /api/v1/files/resources/{id}/cover/`
- `GET /api/v1/files/resource-files/{id}/`
- `GET /api/v1/files/student-work/{id}/`
- `GET /api/v1/files/classroom-group-files/{id}/`
- `GET /api/v1/files/classroom-groups/{id}/document/`

学生只能读取本人课程、目标班级资源、本人作品和本人所在小组文件；教师只能读取本人课程/课堂和授权共享资源；学校管理员只能读取本校对象。无权限对象统一返回 404，避免通过编号枚举判断对象是否存在。

ONLYOFFICE 文档服务器无法使用浏览器 Session Cookie，因此资源附件和小组协作文档的编辑配置使用绑定对象 ID、文件版本和一小时时效的签名 URL。签名不能用于其他对象或其他文件版本；普通前端响应不返回永久媒体地址。

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
- 当前投放环节没有分层题时，学生端返回当前环节全部题目。
- 当前投放环节存在 `target_layer != all` 或 `use_layer_scores=true` 的题目时，学生端按学生 `StudentProfile.current_layer` 自动过滤 `question_items`；`target_layer=all` 对所有学生可见；启用 `use_layer_scores` 时学生端 `score` 返回该学生层级分值。
- `A/B` 和 `B/C` 是正式支持的相邻层级组合；第一版不开放 `A/C`。
- 新建题目基础分按题型给初始值：选择/判断 2 分，填空 3 分，简答 5 分。
- 新建题目开启分层分值时，前端先按 `target_layer` 给 `layer_scores.A/B/C` 初始建议值；无法判断时三层都等于基础分。
- AI 分值建议只能返回建议值，不能直接覆盖教师已保存的 `layer_scores`。
- 学生提交课堂题仍走 `POST /api/v1/student/lesson-steps/{id}/answer/`；正文写入版本化 `LessonStepAttempt/Answer`，每题通过统一服务兼容写入旧业务记录和新版事件，且不复制答案正文。

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
GET /api/v1/teacher/classroom/sessions/{id}/step-progress/
GET /api/v1/teacher/classroom/sessions/{id}/activities/
POST /api/v1/teacher/classroom/sessions/{id}/activities/
GET /api/v1/teacher/classroom/activities/{id}/
PATCH /api/v1/teacher/classroom/activities/{id}/
DELETE /api/v1/teacher/classroom/activities/{id}/
POST /api/v1/teacher/classroom/activities/{id}/open/
POST /api/v1/teacher/classroom/activities/{id}/close/
POST /api/v1/teacher/classroom/sessions/{id}/command/
GET /api/v1/teacher/classroom/sessions/{id}/attendance/{activity_id}/
POST /api/v1/teacher/classroom/sessions/{id}/attendance/{activity_id}/mark/
POST /api/v1/student/classroom/{id}/activities/{activity_id}/response/
```

规则：

- 课堂场次必须选择教师自己的课程、该课程课时和该课程已绑定的任教班级。
- 课堂状态为 `draft`、`running`、`finished`。
- 只有 `draft` 未开始课堂可以删除。
- 已结束课堂可以通过 `restart` 重新开始，重新开始会清空当前投放环节，学生端等待教师重新投放。
- 开始和结束课堂会写入 `LearningEvent.teacher_intervention`。
- 结束课堂会自动关闭进行中的课堂活动。
- `ClassroomSession` 记录当前投放环节：`current_step`、`current_step_status`、`submission_locked`、`current_step_started_at`、`current_step_closed_at`。
- `ClassroomSession.is_layered` 不再作为创建/编辑课堂参数。接口保留该字段用于兼容，含义为“当前投放环节是否含分层题”，由后端按当前环节题目自动计算。
- `step/open` 只允许投放当前课堂绑定课时下已配置的 `LessonStep`，课堂未开始时前端会先调用开始课堂；成功投放会按题目版本和适用带生成学生级学习机会。
- `step/lock` 锁定当前环节提交，`step/close` 关闭当前环节并保持提交锁定。
- `step-progress` 优先读取当前课堂和环节的最新 `LessonStepAttempt`，旧课堂记录才回退到本次投放后的 `LearningEvent.answer_submit`。
- `step-progress.rows` 每个学生一行，包含提交状态、提交时间、已答题数、客观题自动得分、每题作答摘要和未提交名单。
- 单选、多选、判断和设置了参考答案的填空题可以自动判分；简答和无参考答案题目返回“待批阅”，不做假自动得分。
- 课堂活动状态为 `draft`、`open`、`closed`。
- 开启和关闭课堂活动会写入 `LearningEvent.teacher_intervention`。
- `command=sign_in` 开启签到时使用 `content.released@1.2` 为当前班级启用学生生成必做 `attendance` 机会；重复请求同一开放活动不重复生成机会。
- 学生签到只允许写本人 `attendance_status=signed` 和 `recorded_by=student`。迟到、请假、缺勤及教师代签必须通过教师 `mark` 接口。
- 教师每次修改考勤都会追加 `attendance.recorded`，通过 `revision_no/supersedes_event_id` 关联前一状态；备注不进入新版事件。
- 关闭签到后学生不能继续提交，但教师可在课堂结束前核实状态。课堂结束后未响应机会撤回，不自动生成缺勤；已开启或已有记录的活动禁止物理删除。
- 当前已完成课堂场次、环节投放、锁定/关闭、学生版本化作答、附件版本上传、客观题自动评分、主观题待评和附件复评事实；课堂控制继续使用现有 WebSocket 推送。

### 课堂小组合作

教师端：

```text
GET /api/v1/teacher/classroom/sessions/{id}/group-collaboration/
POST /api/v1/teacher/classroom/sessions/{id}/group-collaboration/setup/
POST /api/v1/teacher/classroom/sessions/{id}/group-collaboration/close/
GET /api/v1/teacher/classroom/sessions/{id}/groups/{group_id}/files/
POST /api/v1/teacher/classroom/sessions/{id}/groups/{group_id}/files/
```

学生端：

```text
GET /api/v1/student/classroom/{session_id}/group-collaboration/
POST /api/v1/student/classroom/{session_id}/group-collaboration/files/
```

协作文档：

```text
GET /api/v1/classroom/groups/{group_id}/office-config/?mode=view
GET /api/v1/classroom/groups/{group_id}/office-config/?mode=edit
POST /api/v1/classroom/groups/{group_id}/office-callback/
```

`setup` 请求：

```json
{
  "group_size": 4,
  "grouping_strategy": "balanced_layer",
  "document_type": "docx",
  "storage_quota_mb": 100,
  "allow_student_upload": true,
  "allow_onlyoffice_edit": true,
  "regenerate": false
}
```

规则：

- 小组合作属于某次 `ClassroomSession` 的课堂运行能力，不写入课时设计环节。
- 教师只能为自己的课堂开启、关闭或重新分组。
- 已有分组时修改人数、策略或文档类型必须显式提交 `regenerate=true`；一旦已有文档打开、有效保存或共享文件，重新分组返回 `409`，避免历史证据丢失。
- 学生只有在课堂 `running`、小组合作 `open`、且自己属于该组时才能看到小组合作入口。
- 默认分组策略支持 `balanced_layer`、`same_layer`、`random`、`ai_layer`；`ai_layer` 第一版按同层优先规则执行，后续接分层模型。
- `group_size` 范围为 2-12，`storage_quota_mb` 范围为 10-2048。
- 每组自动生成一份协作文档，类型为 `docx`、`pptx` 或 `xlsx`。
- 有 ONLYOFFICE 时，同组学生打开同一个文档 `key` 协作编辑；教师可以打开任意小组文档。
- 无 ONLYOFFICE 或服务不可用时，平台仍保留小组成员、文件上传、文件下载和课堂其他功能，只禁用在线协作编辑体验。
- 学生只能上传到自己所在小组共享区；共享区按教师设置的容量配额校验。
- 共享文件响应包含不可猜测的 `public_id` 和递增 `version_no`；内部分析尝试 UUID 不返回给客户端。
- 教师端可查看所有小组成员、层级提示、组长、空间使用和共享文件。
- 学生端只返回自己的 `my_group`，不返回其他小组成员和文件。
- 每组的文档和共享区分别使用 `content.released@1.1.target_student_ids` 只向本组成员生成非必做 `document/task` 机会，不进入其他学生分母。
- 打开小组协作文档写 `group.document.opened`；上传共享文件写 `group.file.shared`。文件名、描述、地址和正文只保存在业务表，不进入新版事件。
- ONLYOFFICE 回调必须提供有效 HS256 JWT，且签名内的 `status/key/url/users/actions` 与请求一致。服务端同时校验文档 key、下载 URL 来源和文件大小。
- 有实际内容变化的回调追加 `ClassroomGroupDocumentVersion` 和组级 `group.document.saved`；相同 SHA-256 的重复回调不新增版本或事件。保存事实不自动归因到单个学生。
- 关闭小组合作或结束课堂会关闭入口并撤回未完成机会；已提交共享文件等完成事实保留。
- 后续 AI 分组应使用学生当前层级、近期学习行为、协作贡献、教师调整记录和小组任务完成质量作为特征，但模型建议必须可被教师确认或覆盖。

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
POST /api/v1/student/lesson-steps/{step_id}/attachments/
POST /api/v1/student/lesson-steps/{step_id}/reflection/
```

规则：

- 学生只能看到自己班级绑定的已发布课程。
- 课时必须属于学生可见课程。
- 课时学习工作台读取教师端 `LessonStep` 学习过程。
- 学生端会读取 `question_items` 并按题型渲染作答控件；参考答案不会下发给学生端。
- `question_items` 支持 `single`、`multiple`、`judge`、`blank`、`text`、`file`。
- `file` 附件提交题下发 `file_config.allowed_extensions` 和 `file_config.max_size_mb`，学生上传接口仍会在后端二次校验格式和大小。
- 进入课程、课时、环节和查看资源仍处于旧记录迁移阶段；课堂提交和附件上传已由统一服务在同一事务写入新旧记录。
- 学生上传附件会追加 `StudentWorkAttachment.upload_version`，不会覆盖或删除旧版本，并写 `task.submitted`；响应中的 `upload_version` 可用于教师端确认版本。
- 学生提交环节后返回 `attempt_id` 和 `attempt_no`。正文保存在 `LessonStepAttempt/Answer`；新版 `item.submitted` 事件仅保存题目版本、题型、尝试号及学习任务引用。

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
- 如果接口返回 `is_layered=true`，表示当前投放环节含分层题，学生端 `current_step.question_items` 已由后端按学生当前层级过滤；学生端不能自行请求其他层级题目。
- 如果题目启用分层分值，学生端收到的 `score` 已是该学生层级对应分值。
- 教师课堂控制统一使用 `POST /api/v1/teacher/classroom/sessions/{id}/command/`。`command` 当前支持 `sign_in`、`random_pick`、`quick_answer`、`timer`、`broadcast`。
- 教师查看当前环节完成情况使用 `GET /api/v1/teacher/classroom/sessions/{id}/step-progress/`，前端按题目 ID 展开对应题目的学生完成情况。
- 教师给学生附件提交评分使用 `POST /api/v1/teacher/classroom/sessions/{id}/attachments/{attachment_id}/score/`，请求体为 `{score, feedback}`；首次评分追加 `final`，后续修改追加 `revised`，旧评分事实不覆盖。
- 课堂指令写入 `ClassroomActivity`，结构化参数写入 `metadata`。学生课堂接口返回进行中的 `activities`，学生端据此展示签到、点名、抢答、倒计时和课堂广播。
- 课堂广播由教师输入文本内容，学生端收到后必须以弹窗展示，学生点击“知道了”后写入已读响应。
- `open_resource` 和 `collect_answers` 暂不开放按钮和接口，后续确有课堂流程需要时再重新设计。
- 默认所有课时由课堂教学启用控制。未给学生所在班级创建课堂场次、未开始课堂、已结束课堂，普通课时工作台 `/student/lessons/{lesson_id}/workspace/` 都不返回课时内容。
- 学生必须等待教师创建课堂、开始课堂并投放环节后，才能从课堂入口查看该环节资源和题目。
- 教师开启活动后，学生端通过 WebSocket 收到状态。
- 教师关闭活动后，学生端不能继续提交。
- 签到、抢答、即时题、未懂反馈和课堂任务都要写入学习事件。
- 抢答开启时服务端通过 `content.released@1.3` 生成非必做 `interaction` 机会；`quick_answer.responded` 的首次排名和响应延迟由服务端计算，客户端不能提交排名。
- 随机点名只写服务端来源的 `random_call.selected` 选择事实，不生成学生完成机会；当前前端抽取标记为 `client_draw`，不能宣称为服务端随机。

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
- 当前第一版使用 `GET /api/v1/student/profile/?subject={subject_id}` 聚合返回当前学生的基础档案、课程进度、学科前测、测试成绩、作品提交、评价记录、学习行为分布和最近学习轨迹。
- 档案接口不接受学生 ID，始终按当前会话学生查询；不返回当前分层、模型置信度、风险标签、积分排名或教师内部干预详情。后续个人积分和奖章使用独立接口，不混入核心素养或 AI 内容带。
- `subject` 可选，只能使用本校启用学科；筛选后课程、测试、前测、作品、评价和事件统计使用同一学科范围。
- `profile/events`、`profile/submissions`、`profile/logs` 保留为后续分页扩展；当前聚合接口返回最近 60 条轨迹和最近 50 条业务记录。
- 学生公告只显示自己班级可见的已发布公告。
- 学生留言默认只能发给自己的任课教师。

角色：

- `super_admin`
- `school_admin`
- `teacher`
- `student`

学校管理员 API 必须从登录用户获取学校范围。  
不能信任 URL 或请求体传入的 `school_id`。

## 新版学习事件批量接收

```text
POST /api/v1/learning-events/batch/
```

权限：仅已登录、已绑定学校的教师或学生。学校管理员和超级管理员不能通过客户端批量接口制造学习行为。

请求批次最多 200 条：

```json
{
  "batch_id": "5f9f0d5f-ff72-4a60-8ad5-7cfbd519973f",
  "sent_at": "2026-07-18T20:00:00+08:00",
  "events": [
    {
      "event_id": "59b7de87-9034-4a08-a5cf-b5797abde980",
      "event_name": "session.heartbeat",
      "schema_version": "1.0",
      "source": "student-web",
      "client_version": "2.0.0",
      "class_id": 3,
      "subject_id": 1,
      "client_session_id": "d112ea98-2ad7-42af-8e0a-b8689244cf11",
      "client_sequence": 18,
      "client_occurred_at": "2026-07-18T19:59:58+08:00",
      "payload": {
        "foreground": true,
        "idle_seconds": 2,
        "network_state": "online"
      }
    }
  ]
}
```

规则：

- 服务端根据登录会话重建 `actor/school/source`，请求体不得提交 `school_id`、`actor_id`、角色、记录状态或模型版本。
- 学生事件的 `target_student` 固定为本人；教师目标学生必须属于本人任教班级。
- `event_id` 和服务端生成的“客户端会话 + 序号”幂等键共同去重。
- 同一幂等键、同一事实返回 `duplicate`；同一幂等键对应不同内容返回 `idempotency_conflict`。
- 允许离线乱序补传。客户端发生时间保留原值，服务端接收时间由同一批次统一生成；迟到和时钟异常写入 `quality_errors`。
- 每条事件独立返回 `accepted/duplicate/rejected`，单条错误不阻断同批其他合法事件。
- 拒绝信封在校内使用独立 Fernet 密钥加密并短期保留，API 和 Django Admin 不返回明文。
- `content.released@1.0` 由教师端或服务端提交，必须包含班级、学科、不可变 `object_id/object_version`、`content_type`、`required` 和 `target_layers`；接受后按符合条件的在籍学生展开 `LearningOpportunity`。
- `content.released@1.1` 增加可选的唯一 `target_student_ids`，用于组员等显式对象集合；列表中的学生必须全部是当前班级启用学生且符合投放范围，否则整条事件拒绝。学生接口不返回该列表。
- `content.released@1.2` 保持 1.1 规则并新增 `attendance` 内容类型。既有 1.0/1.1 模式不可修改，旧事件仍按原哈希重放。
- `content.released@1.3` 保持 1.2 规则并新增 `interaction` 内容类型。既有 1.0/1.1/1.2 模式不可修改，旧事件仍按原哈希重放。
- `target_layers` 支持 `all`、`A`、`B`、`C`、`A/B`、`B/C` 和 `A/B/C`。层级只在服务端用于实际投放，学生响应不得返回目标层级或 `delivered_band`；尚无当前层级的学生只接收 `all` 内容。
- `content.withdrawn@1.0` 必须引用原 `release_event_id` 和结构化 `reason_code`；已提交或已评分的机会保留，其余机会追加 `withdrawn` 事实。
- `resource.opened`、`video.progress`、`document.progress`、`group.document.opened`、`group.file.shared`、`attendance.recorded`、`quick_answer.responded`、`item.submitted`、`item.graded`、`task.submitted` 和 `evaluation.rating.submitted` 必须提交真实 `opportunity_id`。随机 UUID、跨学生引用、内容版本不一致或机会终止后的事件按条拒绝。
- `quick_answer.responded` 只允许服务端写入，载荷仅保存首次响应排名和相对活动开启时间的延迟；学生回答正文不复制进新版事件。`random_call.selected` 也只允许服务端写入，记录教师选择事实，不要求学习任务关联、不生成提交状态。
- `resource.center.opened`、`lesson.entered`、`lesson.step.entered/completed`、`pretest.submitted`、`chat.message.sent`、`intervention.acknowledged`、`classroom.interaction.responded` 和 `classroom.control.executed` 由对应业务接口通过统一服务写入。资源中心自由浏览和班级级课堂控制不生成学习机会。
- `item.graded` 必须与同一机会、同一 `attempt_id` 的既有 `item.submitted` 对应。`pending` 只表示尚未形成成熟评分；首个成熟结果使用 `final`，后续修改必须使用 `revised` 并追加新版本。
- `AssessmentResultFact` 不通过该接口直接提交，由服务端在接受 `item.graded` 时同事务生成。重复 `final`、无提交先评分或修订缺少成熟前序版本会整条拒绝，事件和机会状态不会留下半成品。
- 当前仅支持立即开放。`content.released.available_from` 不能晚于事件发生时间；预定开放需等待后续 `content.assigned` 契约实现。

测试模块接入规则：

- 教师执行“开启测试”时，服务端按目标班级和题目快照生成 `content.released` 及学生机会；设置了未来 `start_at` 的测试不能提前开启。
- `TestAttempt.analytics_attempt_id` 是逐题提交和评分共用的 UUID，客户端不能自行替换。
- 旧测试页面没有可信单题计时，因此服务端使用 `item.submitted@1.1` 并省略 `response_time_ms`；不得填 0 或把整场测试时长当作单题时长。
- 学生主动交卷记录为 `student-web`；超时和教师结束触发的自动交卷记录为 `server`。
- 客观题自动形成 `final` 评分；主观题提交只形成 `pending`。教师必须完成全部待评主观题后才能形成 `final`，后续复评生成 `revised`。
- 测试结束会撤回未完成机会，但保留已经提交或评分的机会。已有答卷的已结束测试不能原地重新开启，教师应复制后创建新轮次。

课堂资源行为接口：

```text
POST /api/v1/student/classroom/{session_id}/resources/{resource_id}/opened/
POST /api/v1/student/classroom/{session_id}/resources/{resource_id}/video-progress/
POST /api/v1/student/classroom/{session_id}/resources/{resource_id}/document-progress/
```

- 三个接口只接受当前学生所在班级、进行中课堂、已投放且未关闭环节中的真实资源；服务端负责解析机会和对象版本，客户端不能提交或替换 `opportunity_id`。
- `opened` 请求体为 `{ "presentation": "embedded|popout|external|download|unknown" }`，写入 `resource.opened@1.0`。该事件只证明资源已呈现，不等同于完成、掌握或有效投入。
- `video-progress` 请求体包含 `position_seconds/media_seconds/playback_rate/duration_ms`。学生端约每 10 秒及暂停、结束时节流提交；服务端校验位置不超过媒体总时长。
- `document-progress` 请求体包含真实 `page/page_count/visible_seconds`。只有本地查看器能可靠返回这些值时才调用；浏览器 PDF iframe 和当前 ONLYOFFICE 接入无法可靠返回页码时只写 `resource.opened`，禁止用固定 `1/1` 伪造进度。
- 资源中心 `POST /student/resources/{id}/` 写入 `resource.center.opened`，表示课堂外自主浏览，不复用课堂机会。未来若建立推荐或教师指派，必须另建指派事实；当前不将自由浏览放入必做完成率分母。

历史旧记录回填命令：

```powershell
.\.venv\Scripts\python.exe manage.py backfill_learning_event_v2 --dry-run --batch-size 500
.\.venv\Scripts\python.exe manage.py backfill_learning_event_v2 --batch-size 500
.\.venv\Scripts\python.exe manage.py reconcile_learning_event_writes --check
```

命令支持 `--school`、`--before`、`--batch-size`、`--resume` 和 `--dry-run`。事件 UUID 由旧记录主键和转换版本确定生成；不能明确转换上下文或学习任务关联的旧记录写入内部兼容状态 `legacy.unmapped`，界面和导出统一显示“旧事件未转换”，且不创建学习任务关联、不进入后续学生分析。

响应包含批次计数和逐条结果：

```json
{
  "data": {
    "counts": {"accepted": 1, "duplicate": 0, "rejected": 0},
    "results": [
      {
        "index": 0,
        "event_id": "59b7de87-9034-4a08-a5cf-b5797abde980",
        "status": "accepted",
        "quality_errors": []
      }
    ]
  },
  "message": "事件批次已处理。"
}
```

接受结果可按事件类型额外返回 `opportunities_created`、`opportunities_withdrawn`、`opportunity_states_recorded`、`assessment_result_created`、`assessment_result_mature` 和 `assessment_result_version`；无关字段会省略，不保证全部同时出现。

课堂积分流水不开放通用客户端写入 API。抢答评分、随机点名评分和聊天审核扣分已在原有受权限控制的业务接口内同时写入新旧记录；客户端只能提交本次操作，不能提交余额、冲正引用或修改历史流水。重复设置相同评分不重复记账，替换评分只记录实际余额变化。

服务端新旧记录兼容写入模式由本地环境配置控制：

```env
LEARNING_EVENT_WRITE_MODE=dual_required
```

- `dual_required`：旧业务记录、新版记录和派生积分/评分记录必须在同一事务中成功，任一失败整体回滚。
- `v1_only`：紧急回滚模式，只保留旧 `LearningEvent` 业务写入；不得用于研究数据覆盖率声明。
- 客户端不能通过请求参数切换写入模式。

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

## 课程评价与课堂评价 API

评价项配置属于 `Course`，不属于单次 `ClassroomSession`，也不写入课时模板。自评、互评、师评均由教师在课程/课时设计阶段选择性开启，评价方式固定为 1-5 星，不使用分数、权重或百分制。单次课堂是否对学生开放评价属于 `ClassroomSession.evaluation_enabled` 运行状态，新建课堂默认关闭，重新开始课堂也重置为关闭。

课程端：

```text
GET /api/v1/teacher/courses/{id}/evaluation/?class_group={class_group_id}
PATCH /api/v1/teacher/courses/{id}/evaluation/
POST /api/v1/teacher/courses/{id}/evaluation/ai-generate/
POST /api/v1/teacher/courses/{id}/evaluation/teacher-submit/
```

教师端：

```text
GET /api/v1/teacher/classroom/sessions/{id}/evaluation/
PATCH /api/v1/teacher/classroom/sessions/{id}/evaluation/
POST /api/v1/teacher/classroom/sessions/{id}/evaluation/ai-generate/
POST /api/v1/teacher/classroom/sessions/{id}/evaluation/teacher-submit/
```

学生端：

```text
GET /api/v1/student/classroom/{id}/evaluation/
POST /api/v1/student/classroom/{id}/evaluation/submit/
```

规则：

- 课程端 `PATCH evaluation` 保存课程级 `enable_self`、`enable_peer`、`enable_teacher` 和三类 `criteria`。
- 每次保存课程评价配置按规范化内容计算 SHA-256；内容变化才发布新的 `ClassroomEvaluationConfigVersion`，相同内容不重复生成版本。
- 课堂端 `PATCH evaluation` 只接受 `evaluation_enabled`，用于开启或关闭本课堂评价可见性，不修改课程评价项配置；只有进行中课堂允许开启评价。
- 课堂第一次开启评价时冻结当前评价版本；之后修改课程评价项不会改变这节课堂。关闭后再次开启仍使用原冻结版本。
- 评价内容设置入口放在教师课时设计页；课堂控制台只调用已保存配置，不提供评价项编辑和 AI 生成。
- 学生端只有在 `ClassroomSession.evaluation_enabled=true` 时才显示课堂评价入口；课堂默认关闭评价，适合教师在课堂收尾时手动开启。
- 每类评价项最多 20 个；某类评价只要已有评价项，就视为该类可用于课堂开启。
- 互评项可以先在课程中设计；学生端只有在课堂开启小组分组合作并生成小组后才显示互评，且只允许评价同组成员，不能评价自己。
- 师评可在课程中按班级填写，也可在课堂控制台填写。课程师评不绑定具体课堂，课堂师评绑定当前 `ClassroomSession`。
- 自评、互评、师评每次修改都追加新的 `ClassroomEvaluationSubmission`，响应默认展示最新版本；历史版本通过 `submission_version/supersedes` 保留。
- 每个评价项必须二选一：在 `ratings` 中提交 1-5 星，或在 `not_assessed` 中提交原因。两者不能同时包含同一指标；原因 `other` 必须填写最多 200 字说明。
- 三类评价统一写入 `evaluation.rating.submitted@1.1`，并保留旧业务兼容记录。载荷只包含评价版本、评价项 ID、1-5 星、暂不评价原因代码和评价者角色；备注及暂不评价补充说明只保留在业务提交表。
- 历史 `evaluation.rating.submitted@1.0` 保持原字段和哈希，禁止覆盖。当前 `item.graded` 写入同样使用 `1.1`，历史评分事件继续保留在 `1.0`。
- 汇总中的平均星级排除暂不评价项，并返回 `rated_item_count`、`not_assessed_item_count`、`unanswered_item_count` 和 `total_item_count`。页面必须同时展示提交人数，不能只显示平均值。
- 自评机会归本人；师评和互评机会归被评价学生。互评 API 先校验同组关系，再由服务端可信来源写入；`POST /learning-events/batch/` 仍禁止学生直接指定其他目标学生。
- 开启评价生成非必做机会；关闭评价或结束课堂撤回未提交机会，已经提交的评价及版本链保留。
- `ai-generate` 使用教师自己的 DeepSeek 配置生成评价项草稿；草稿必须由教师确认保存后才对学生生效。课程端生成基于课程上下文，课堂端生成会额外参考当前课堂环节。

提交示例：

```json
{
  "evaluation_type": "self",
  "ratings": {
    "task_quality": 4
  },
  "not_assessed": {
    "collaboration": {
      "reason": "not_observed",
      "note": "本节课未安排小组活动。"
    }
  },
  "comment": "按本节课实际材料填写。"
}
```

## AI 学习网页 API

教师端：

```text
GET  /api/v1/teacher/lessons/{lesson_id}/learning-pages/
POST /api/v1/teacher/lessons/{lesson_id}/learning-pages/
GET/PATCH/DELETE /api/v1/teacher/learning-pages/{id}/
POST /api/v1/teacher/learning-pages/{id}/revise/
GET  /api/v1/teacher/learning-pages/{id}/responses/
GET  /api/v1/teacher/learning-pages/{id}/responses/?classroom_session={session_id}
```

师生预览与学生提交：

```text
GET  /api/v1/learning-pages/{id}/
POST /api/v1/student/learning-pages/{id}/blocks/viewed/
POST /api/v1/student/learning-pages/{id}/submit/
```

规则：

- DeepSeek 只返回平台定义的 JSON schema，不接收或保存 AI 生成的 HTML、CSS、JavaScript、外链和 iframe。
- 页面区块白名单为 `content`、`callout`、`list`、`steps`、`cards`、`table`、`code`、`visualization`、`interactive`、`form`。
- `visualization` 是受控动画区块，`visualization_type` 只能是 `process`、`timeline`、`bars`、`binary`；动画项只接受 `label`、`detail`、`code`、`value`、`tone`。
- 动画时长限制为 1500-15000ms，可设置 `autoplay` 和 `loop`；AI 返回的 `animation`、`animated_visualization`、`visual` 会映射为 `visualization`，其余未知动画结构会被清洗。
- `interactive` 用于自由布局、Canvas、内联 SVG 和自定义 JavaScript 动画，字段为 `html/css/javascript/height`，单字段最多 30000 字符、每页最多 4 个、高度限制为 280-900px。
- `interactive` 在第二层 opaque-origin iframe 中执行，不开放 `allow-same-origin`、表单、弹窗、下载或顶层导航；CSP 禁止网络、外部资源、第三方库、嵌套 iframe 和对象。
- `interactive.javascript` 由平台附加 nonce 后执行；事件必须使用 `addEventListener`，HTML 中的 `onclick` 等内联事件会被 CSP 拒绝。
- 学习网页生成与修改接口接受 `generation_mode`：`auto`、`interactive`、`structured`。`auto` 在要求中识别到动画、交互、模拟、Canvas、SVG 或可视化时使用自由交互模式；`structured` 只使用平台受控区块。
- `interactive` 模式必须返回至少一个同时包含 `html/css/javascript` 的可执行区块。第一次结果不合格时后端自动纠正一次；第二次仍无有效脚本则返回 `400`，不会保存静态伪动画。
- 自定义交互块不能直接提交学习数据；需要采集学生回答时仍必须使用平台 `form` 区块，由固定消息桥写入 API。
- 表单字段白名单为 `single`、`multiple`、`select`、`short_text`、`long_text`、`number`、`scale`。
- 学生只能访问当前课堂、当前已投放环节中实际绑定的学习网页；锁定提交后不能继续提交网页表单。
- `GET` 支持 `presentation=embedded|popout`，学生打开页面会写 `learning_page.opened`；教师预览不生成学生行为。
- `blocks/viewed` 请求体为 `{block_id, block_type, visible_ms, visibility_ratio}`。后端必须校验区块属于当前页面版本；不得上传区块正文、交互代码或表单值。
- iframe 仅在区块至少 50% 可见且单段持续不少于 250ms 后上报；采集请求失败不能阻断页面浏览和表单提交。
- 每次表单提交追加 `LearningWebPageResponse` 和 `learning_page.form_submitted`。新版事件仅保存响应编号、页面/表单版本、字段数量和尝试 UUID，完整答案只在业务响应表中保存。
- 教师统计接口返回表单提交人数、提交次数、选项分布、数值摘要和近期文本回答。
- 传入 `classroom_session` 时只统计该教师、该班级、该课堂场次的回答，并返回班级人数、已完成/进行中/未开始人数、完成率及逐学生进度；网页必须属于该课堂绑定的课程和课时。
## 测试与共享题库 API

### 教师

- `GET /api/v1/teacher/assessment-options/`：本校学科、本人任教班级、本人课程、题型和难度选项。
- `GET|POST /api/v1/teacher/question-bank/`：查询学校共享题库或新增本人题目。查询支持 `scope=shared|mine`、`q`、`subject`、`question_type`、`difficulty`。
- `PATCH|DELETE /api/v1/teacher/question-bank/{id}/`：维护本人题目。删除前必须先设置 `status=disabled`。
- `GET /api/v1/teacher/question-bank/template/`：下载离线 XLSX 导入模板。
- `GET /api/v1/teacher/question-bank/export/`：导出学校共享题库 XLSX。
- `POST /api/v1/teacher/question-bank/import/`：上传 XLSX 批量导入本人题目，单次最多 1000 道。
- `POST /api/v1/teacher/question-bank/ai-generate/`：使用当前教师 DeepSeek 配置生成 1-20 道题目草稿。请求包含 `subject/direction/knowledge_point/question_type/difficulty/count/requirement`，不写数据库。
- `POST /api/v1/teacher/question-bank/ai-confirm/`：提交教师选择并修改后的草稿，整批校验通过后写入学校共享题库。
- `GET|POST /api/v1/teacher/assessments/`：测试列表与创建。
- `GET|PATCH|DELETE /api/v1/teacher/assessments/{id}/`：测试详情与草稿维护。
- `PUT /api/v1/teacher/assessments/{id}/questions/`：保存题目顺序、分值、`randomize_question_order` 和 `randomize_option_order`，同时建立试卷快照。
- `POST /api/v1/teacher/assessments/{id}/publish/`：发布并锁定试卷。
- `POST /api/v1/teacher/assessments/{id}/open/`：开启学生作答。
- `POST /api/v1/teacher/assessments/{id}/close/`：结束测试并自动收交未提交答卷。
- `GET /api/v1/teacher/assessments/{id}/results/`：完成情况、成绩和逐题统计。
- `GET /api/v1/teacher/assessments/{id}/results/export/`：导出测试汇总、学生成绩和逐题统计 XLSX。
- `GET|PATCH /api/v1/teacher/test-attempts/{id}/grade/`：读取完整答卷或保存主观题评分；存在未评分简答题时拒绝结束批阅，整次评分事务回滚。
- `GET|PATCH /api/v1/teacher/test-attempts/{id}/grade/`：查看答卷和保存人工评分。

### 学生

- `GET /api/v1/student/assessments/`：当前班级测试列表。
- `GET /api/v1/student/assessments/{id}/`：测试状态、题目、已存答案和截止时间。
- `POST /api/v1/student/assessments/{id}/start/`：创建或继续唯一答卷；首次开始时按测试设置固化该学生的题目和选项顺序。
- `PATCH /api/v1/student/assessments/{id}/answer/`：逐题暂存答案。
- `POST /api/v1/student/assessments/{id}/submit/`：交卷、自动判分并写入学习事件。

测试详细设计见 `docs/assessment_module_design.md`。

## 课堂实名文字聊天 API

教师端：

```text
GET   /api/v1/teacher/classroom/sessions/{id}/chat/
PATCH /api/v1/teacher/classroom/sessions/{id}/chat/settings/
GET   /api/v1/teacher/classroom/sessions/{id}/chat/messages/?room_type=&target_id=
POST  /api/v1/teacher/classroom/sessions/{id}/chat/messages/
POST  /api/v1/teacher/classroom/sessions/{id}/chat/read/
GET   /api/v1/teacher/classroom/sessions/{id}/chat/moderation/?status=pending|reviewed|all
POST  /api/v1/teacher/classroom/sessions/{id}/chat/messages/{message_id}/moderate/
```

学生端：

```text
GET  /api/v1/student/classroom/{id}/chat/
GET  /api/v1/student/classroom/{id}/chat/messages/?room_type=&target_id=
POST /api/v1/student/classroom/{id}/chat/messages/
POST /api/v1/student/classroom/{id}/chat/read/
POST /api/v1/student/classroom/{id}/chat/moderation-feedback/{message_id}/ack/
```

`room_type` 只允许 `whole_class`、`teacher_private`、`group`。发送体包含 `room_type`、可选 `target_id` 和最多 500 字的 `content`。

教师审核的 `action` 只允许 `allow`、`warn`、`remove`、`deduct`；扣分时另传正数 `points`，系统不自动扣分。

学生消息接口不返回 `removed` 消息，包括该消息的原发送学生。`warn`、`remove`、`deduct` 通过聊天上下文中的 `moderation_feedbacks` 返回一次性反馈；学生确认后调用 `ack` 接口，刷新不再重复提示。

WebSocket 使用 `/ws/classrooms/{session_id}/chat/`。客户端只能发送 `ping`，聊天消息必须走 REST API。服务器推送 `chat.settings.updated`、`chat.message.created`、`chat.moderation.pending` 和 `chat.message.reviewed` 等变化事件，客户端收到后重新读取有权限的数据。

完整规则见 `docs/classroom_chat_design.md`。

## 教学资源中心 API

教师端：

```text
GET    /api/v1/teacher/resources/?scope=mine|school|external|projects&q=&subject=&category=
POST   /api/v1/teacher/resources/
GET    /api/v1/teacher/resources/{id}/
PATCH  /api/v1/teacher/resources/{id}/
DELETE /api/v1/teacher/resources/{id}/
DELETE /api/v1/teacher/resources/{id}/files/{file_id}/
```

新增和编辑使用 `multipart/form-data`。主要字段为 `resource_type`、`category`、`visibility`、`subject`、JSON 数组 `class_ids/tags/project_members`、主文件 `attachment`、封面 `cover` 和多文件 `extra_files`。

学校管理员：

```text
GET   /api/v1/school-admin/resource-reviews/?status=pending|approved|rejected&q=
PATCH /api/v1/school-admin/resource-reviews/{id}/
```

审核体为 `{ "action": "approve|reject", "note": "" }`。退回时 `note` 必填。

学生端：

```text
GET  /api/v1/student/resources/?scope=all|school|external|projects&q=
GET  /api/v1/student/resources/{id}/
POST /api/v1/student/resources/{id}/
```

学生 `POST` 详情接口表示实际打开资源，会增加浏览量并写入 `LearningEvent.resource_view`。权限规则和跨校同步边界见 `docs/resource_center_design.md`。

## 学校数据检查

所有接口只允许学校管理员访问，学校范围必须来自登录用户，不接受客户端学校 ID。

```text
GET  /api/v1/school-admin/analytics/quality/
POST /api/v1/school-admin/analytics/quality/run/
GET  /api/v1/school-admin/analytics/quality/export/
```

查询响应：

```json
{
  "school": { "id": 1, "name": "示例学校", "code": "001" },
  "current": {
    "status": "red",
    "checks_passed": false,
    "check_version": "data-check-v2",
    "source_checksum": "...",
    "window_start": "2026-07-12T00:00:00+08:00",
    "window_end": "2026-07-19T00:00:00+08:00",
    "metrics": [
      {
        "key": "unconverted_old_event_rate",
        "label": "旧事件未转换比例",
        "value": 0.375,
        "level": "red",
        "thresholds": { "amber": 0.05, "red": 0.15, "direction": "high" }
      }
    ],
    "issues": []
  },
  "history": [],
  "runs": []
}
```

手动运行请求体为 `{ "days": 7 }`，允许 1-365 个完整自然日。成功提交返回 202；同校已有 `pending/running` 任务返回 409；Redis/Celery 不可用返回 503 并把检查记录标为失败。

导出返回本校 XLSX，包含“检查报告、检查指标、待处理问题、自动检查记录、执行阶段”五张表。完整口径见 `docs/data_quality_pipeline.md`。

## 教师评价标准管理

所有接口仅允许教师访问，并同时按学校和课程所属教师隔离。客户端不能提交 `school`、`subject`、`scope`、`review_status` 或教师 ID；课程决定学科和学校，新建内容默认处于“课程使用、编辑中”。学校管理员、学生和其他教师不能读取或修改当前教师的评价内容。

```text
GET  /api/v1/teacher/evaluations/options/
GET|POST /api/v1/teacher/evaluations/plans/
GET|PATCH /api/v1/teacher/evaluations/plans/{id}/
POST /api/v1/teacher/evaluations/plans/{id}/publish/
GET|POST /api/v1/teacher/evaluations/standards/
GET|PATCH /api/v1/teacher/evaluations/standards/{id}/
POST /api/v1/teacher/evaluations/standards/{id}/publish/
GET|POST /api/v1/teacher/evaluations/trials/
GET|PATCH|DELETE /api/v1/teacher/evaluations/trials/{id}/
GET /api/v1/teacher/evaluations/trials/export/
GET|PATCH|DELETE /api/v1/teacher/evaluations/lesson-steps/{step_id}/binding/
```

编辑中的内容允许暂时不完整；发布接口检查学习目标、评价依据、学习任务、星级说明和评分示例。发布成功返回详情及最新版本；相同内容重复发布返回现有版本，不新增行。发布失败返回：

```json
{
  "data": null,
  "message": "评价标准发布前检查未通过。",
  "errors": {
    "criteria": ["评价指标 D1 至少需要两个评分示例。"]
  }
}
```

试用记录必须绑定本校已发布的评价标准版本。类型为“内容审核、课堂试用、评分培训、评分一致性检查”，状态为“待进行、进行中、已完成”。已完成记录必须填写参与人数、结果说明和处理结论；评分一致性检查还必须填写 0-100 的一致率。已完成记录不能修改或删除，导出返回本校 XLSX。

发布后的评价方案版本、评价标准版本、评价指标和评分示例不可 PATCH 或 DELETE。完整字段见[教师评价标准管理](evaluation_management.md)。

课时绑定接口只返回当前教师本人课程的已发布标准。`PATCH` 请求体为：

```json
{
  "standard_version": 12,
  "enable_self": true,
  "enable_peer": false,
  "enable_teacher": true
}
```

至少启用一种评价方式。绑定一旦在课堂中使用，修改或删除返回 `409`。课堂开启评价后，正式评价事件的 `object_version` 使用 `standard:{id}:v{version_no}:{hash}`，并与本次课堂冻结快照及学生作答/作品证据保持一致。没有课时绑定的历史课程评价继续使用原课程评价版本，不自动视为正式评价标准证据。
